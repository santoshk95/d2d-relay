"""A .pbix's model, read in a process of its own: python -I <this file> <file.pbix> <out.json> (model.pbix_command)

A .pbix keeps its model (the DataModel part) as an Analysis Services backup compressed with XPress9; PBIXRay
(MIT, pinned in the image) decompresses it with Microsoft's own XPress9 code and reads the model's metadata
database. That is native code reading a file someone uploaded, so it runs here, apart from the web app: limited
memory, processor time and file size, its spill file in the folder it was given, an empty environment, and only
metadata written out (names, DAX, formats; never the data, Power Query or roles).

Exit codes: 0 read (out.json written), 2 no model in the file (a report connected live to a model elsewhere),
3 not readable (the reason on stderr, one line).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LIMIT_MEMORY = int(os.environ.get("D2D_PBIX_READ_MEMORY_MB") or 3072) * 1024 * 1024
LIMIT_CPU_S = int(os.environ.get("D2D_PBIX_READ_CPU_S") or 240)
LIMIT_FILE = int(os.environ.get("D2D_PBIX_READ_SPILL_MB") or 6144) * 1024 * 1024

DATA_TYPE = {1: "automatic", 2: "string", 6: "int64", 8: "double", 9: "dateTime", 10: "decimal", 11: "boolean",
             17: "binary", 19: "unknown", 20: "variant"}
SUMMARIZE = {1: "default", 2: "none", 3: "sum", 4: "min", 5: "max", 6: "count", 7: "average", 8: "distinctCount"}


def _limits() -> None:
    try:
        import resource
    except ImportError:                       # not on Linux (a developer's PC): no limits to set
        return
    for what, n in ((resource.RLIMIT_AS, LIMIT_MEMORY), (resource.RLIMIT_CPU, LIMIT_CPU_S), (resource.RLIMIT_FSIZE, LIMIT_FILE)):
        try:
            resource.setrlimit(what, (n, n))
        except (ValueError, OSError):
            pass
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def _s(v):
    if v is None:
        return None
    try:
        if v != v:                            # NaN from pandas
            return None
    except TypeError:
        pass
    return str(v)


def _b(v) -> bool:
    try:
        return bool(int(v))
    except (TypeError, ValueError):
        return str(v).strip().lower() == "true"


def _rows(df) -> list[dict]:
    try:
        return df.to_dict("records")
    except Exception:  # noqa: BLE001 - an empty or odd frame reads as nothing
        return []


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _tables(m) -> dict[str, dict]:
    """Tables and columns from the metadata database itself: PBIXRay's own lists keep only SystemFlags = 0 and so
    leave out calculated tables (DATATABLE, CALENDAR ...), which measures use. Left out here: the engine's own tables
    (SystemFlags bit 1: H$, R$, U$) and each table's row-number column (Type 3)."""
    db = m._metadata.source._db                                 # noqa: SLF001
    tables: dict[str, dict] = {}
    try:
        for r in _rows(db.query("SELECT t.Name AS Name, t.Description AS Description, t.IsHidden AS IsHidden FROM [Table] t "
                                "WHERE (t.SystemFlags & 1) = 0")):
            name = _s(r.get("Name"))
            if name:
                tables[name] = {"name": name, "hidden": _b(r.get("IsHidden")), "description": _s(r.get("Description")),
                                "columns": [], "expression": None}
        cols = _rows(db.query("SELECT t.Name AS TableName, COALESCE(c.ExplicitName, c.InferredName) AS Name, c.Type AS Type, "
                              "c.ExplicitDataType AS ExplicitDataType, c.InferredDataType AS InferredDataType, c.SummarizeBy AS SummarizeBy, "
                              "c.FormatString AS FormatString, c.IsHidden AS IsHidden, c.Expression AS Expression, c.DataCategory AS DataCategory, "
                              "c.Description AS Description FROM [Column] c JOIN [Table] t ON t.ID = c.TableID "
                              "WHERE (t.SystemFlags & 1) = 0 AND c.Type <> 3"))
        calc = _rows(db.query("SELECT t.Name AS TableName, p.QueryDefinition AS Expression FROM Partition p "
                              "JOIN [Table] t ON t.ID = p.TableID WHERE p.Type = 2"))
    except Exception:  # noqa: BLE001 - an older metadata layout: PBIXRay's own lists (without calculated tables)
        tables, calc = {}, []
        for r in _rows(m.tmschema_tables):
            name = _s(r.get("Name"))
            if name:
                tables[name] = {"name": name, "hidden": _b(r.get("IsHidden")), "description": _s(r.get("Description")), "columns": [], "expression": None}
        cols = [{**r, "ExplicitDataType": r.get("DataType")} for r in _rows(m.tmschema_columns) if str(r.get("Type")) != "3"]
    for r in cols:
        t, name = _s(r.get("TableName")), _s(r.get("Name"))
        if not t or not name or t not in tables:
            continue
        explicit, inferred = _int(r.get("ExplicitDataType")), _int(r.get("InferredDataType"))
        dt = DATA_TYPE.get(explicit if explicit not in (None, 1) else inferred)
        tables[t]["columns"].append({"name": name, "type": dt, "summarize": SUMMARIZE.get(_int(r.get("SummarizeBy"))),
                                     "format": _s(r.get("FormatString")), "hidden": _b(r.get("IsHidden")),
                                     "expression": _s(r.get("Expression")) if str(r.get("Type")) == "2" else None,
                                     "category": _s(r.get("DataCategory")), "description": _s(r.get("Description"))})
    for r in calc:
        t = _s(r.get("TableName"))
        if t in tables:
            tables[t]["expression"] = _s(r.get("Expression"))
    return tables


def read(src: str, spill: str) -> dict:
    from pbixray import PBIXRay
    try:
        from pbixray.exceptions import LiveConnectionError, NoEmbeddedModelError
    except ImportError:                       # older PBIXRay: no such classes
        LiveConnectionError = NoEmbeddedModelError = type("Never", (Exception,), {})
    try:
        m = PBIXRay(src, on_disk=True, temp_dir=spill)
    except (LiveConnectionError, NoEmbeddedModelError):
        raise SystemExit(2)
    try:
        measures = []
        raw = None
        try:
            raw = m._metadata.source._db.query(              # noqa: SLF001 - the formats and hidden flags dax_measures leaves out
                "SELECT t.Name AS TableName, m.Name AS Name, m.Expression AS Expression, m.FormatString AS FormatString, "
                "m.Description AS Description, m.DisplayFolder AS DisplayFolder, m.IsHidden AS IsHidden "
                "FROM Measure m JOIN [Table] t ON m.TableID = t.ID")
        except Exception:  # noqa: BLE001 - an older model: the plain list below
            raw = None
        for r in _rows(raw if raw is not None else m.dax_measures):
            measures.append({"table": _s(r.get("TableName")), "name": _s(r.get("Name")), "expression": _s(r.get("Expression")) or "",
                             "format": _s(r.get("FormatString")), "description": _s(r.get("Description")),
                             "folder": _s(r.get("DisplayFolder")), "hidden": _b(r.get("IsHidden"))})
        tables = _tables(m)
        rels = []
        for r in _rows(m.relationships):
            rels.append({"from": [_s(r.get("FromTableName")), _s(r.get("FromColumnName"))],
                         "to": [_s(r.get("ToTableName")), _s(r.get("ToColumnName"))], "active": _b(r.get("IsActive")),
                         "cross": "both" if str(r.get("CrossFilteringBehavior")) in ("Both", "2") else "single",
                         "card": _s(r.get("Cardinality")) or "M:1"})
        groups = []
        try:
            items = _rows(m.tmschema_calculation_items)
            cgs = {str(g.get("ID")): g for g in _rows(m.tmschema_calculation_groups)}
            tid = {str(t.get("ID")): _s(t.get("Name")) for t in _rows(m._metadata.source._db.query("SELECT ID, Name FROM [Table]"))}   # noqa: SLF001
            by_group: dict[str, list] = {}
            for i in items:
                by_group.setdefault(str(i.get("CalculationGroupID")), []).append({"name": _s(i.get("Name")), "expression": _s(i.get("Expression")) or ""})
            for gid, its in by_group.items():
                g = cgs.get(gid) or {}
                groups.append({"table": tid.get(str(g.get("TableID"))) or "", "items": its})
        except Exception:  # noqa: BLE001 - no calculation groups (most models)
            groups = []
    finally:
        try:
            m.close()
        except Exception:  # noqa: BLE001
            pass
    return {"tables": list(tables.values()), "measures": measures, "relationships": rels, "calc_groups": groups}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: pbix_read <file.pbix> <out.json>", file=sys.stderr)
        return 3
    src, out = argv[1], Path(argv[2])
    _limits()
    try:
        model = read(src, str(out.parent))
    except SystemExit as e:
        return int(e.code or 0)
    except MemoryError:
        print("The model is too big to read here.", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001 - one line for the person; never the traceback with paths
        print(f"The model could not be read ({e.__class__.__name__}).", file=sys.stderr)
        return 3
    out.write_text(json.dumps(model), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
