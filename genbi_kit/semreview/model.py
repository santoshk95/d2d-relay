"""The review's model readers: one neutral model, metadata only, whatever the source.

    {"name", "source": {"kind": pbix | pbit | bim | pbip | powerbi, "file"},
     "tables": [{"name", "hidden", "description", "expression" (a calculated table's DAX),
                 "columns": [{"name", "type", "summarize", "format", "hidden", "expression", "category", "description"}]}],
     "measures": [{"table", "name", "expression", "format", "description", "folder", "hidden"}],
     "relationships": [{"from": [table, column], "to": [table, column], "active", "cross": single | both, "card"}],
     "calc_groups": [{"table", "items": [{"name", "expression"}]}],
     "usage": {"measures": {name: [{"page", "visual", "title"}]}, "columns": {"Table[Column]": [{..., "agg"}]},
               "pages": n, "visuals": n}   (when the file has a report)}

Never read: the data, Power Query (it can name servers and paths), roles and their members.

Readers take the file's bytes from disk with fixed limits (zip members, sizes), so a hostile file costs bounded
memory and time. A .pbix's model is compressed with XPress9 and read by pbix_read.py in a separate process
(pbix_command); read_pbix_parts() reads the rest of a .pbix (its report) here.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

from . import tmdl

MAX_MEMBER = 64 * 1024 * 1024          # one zip member read into memory at most
MAX_TOTAL = 160 * 1024 * 1024          # all the members one file has read at most
MAX_MEMBERS = 50000
MAX_MEASURES = 20000
EXTENSIONS = (".pbix", ".pbit", ".bim", ".json", ".zip")


class ModelError(Exception):
    """Shown to the person as it is."""


# ---------------------------------------------------------------- TMSL (model.bim, a .pbit's DataModelSchema, Fabric)

def _text(v) -> str | None:
    """TMSL keeps long text as a list of lines."""
    if v is None:
        return None
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return str(v)


def from_tmsl(doc: dict, name: str = "") -> dict:
    """The neutral model from a TMSL database object ({"name", "compatibilityLevel", "model": {...}}) or a bare
    model object ({"tables": ...})."""
    if not isinstance(doc, dict):
        raise ModelError("This file does not hold a Power BI model.")
    m = doc.get("model") if isinstance(doc.get("model"), dict) else doc
    if not isinstance(m.get("tables"), list):
        raise ModelError("This file does not hold a Power BI model (no tables in it).")
    tables, measures, groups = [], [], []
    for t in m["tables"]:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        tname = str(t["name"])
        calc_expr = None
        for p in t.get("partitions") or []:
            src = (p or {}).get("source") or {}
            if src.get("type") == "calculated":
                calc_expr = _text(src.get("expression"))
        cols = []
        for c in t.get("columns") or []:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            cols.append({"name": str(c["name"]), "type": c.get("dataType"), "summarize": c.get("summarizeBy"),
                         "format": c.get("formatString"), "hidden": bool(c.get("isHidden")),
                         "expression": _text(c.get("expression")) if c.get("type") == "calculated" or c.get("expression") else None,
                         "category": c.get("dataCategory"), "description": _text(c.get("description"))})
        tables.append({"name": tname, "hidden": bool(t.get("isHidden")), "description": _text(t.get("description")),
                       "columns": cols, "expression": calc_expr})
        for ms in t.get("measures") or []:
            if not isinstance(ms, dict) or not ms.get("name"):
                continue
            measures.append({"table": tname, "name": str(ms["name"]), "expression": _text(ms.get("expression")) or "",
                             "format": ms.get("formatString"), "description": _text(ms.get("description")),
                             "folder": ms.get("displayFolder"), "hidden": bool(ms.get("isHidden"))})
        cg = t.get("calculationGroup")
        if isinstance(cg, dict):
            groups.append({"table": tname, "items": [{"name": str(i.get("name")), "expression": _text(i.get("expression")) or ""}
                                                     for i in cg.get("calculationItems") or [] if isinstance(i, dict)]})
    rels = []
    for r in m.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        rels.append({"from": [r.get("fromTable"), r.get("fromColumn")], "to": [r.get("toTable"), r.get("toColumn")],
                     "active": r.get("isActive", True) is not False,
                     "cross": "both" if r.get("crossFilteringBehavior") == "bothDirections" else "single",
                     "card": f"{'1' if r.get('fromCardinality') == 'one' else 'M'}:{'M' if r.get('toCardinality') == 'many' else '1'}"})
    return {"name": name or str(doc.get("name") or ""), "tables": tables, "measures": measures, "relationships": rels,
            "calc_groups": groups}


def _json_bytes(data: bytes) -> dict:
    """JSON in UTF-8, UTF-8 with a BOM or UTF-16 (a .pbit's DataModelSchema is UTF-16 LE)."""
    encs = ("utf-16-le", "utf-8-sig", "utf-16") if data[1:2] == b"\x00" and data[:2] not in (b"\xff\xfe", b"\xfe\xff") \
        else ("utf-8-sig", "utf-16", "utf-16-le")
    for enc in encs:
        try:
            text = data.decode(enc)
            return json.loads(text)
        except (UnicodeDecodeError, ValueError):
            continue
    raise ModelError("The model inside this file could not be read (it is not JSON).")


# ---------------------------------------------------------------- zip files, read with limits

class _Zip:
    def __init__(self, path: Path):
        try:
            self.z = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as e:
            raise ModelError("This file is not a Power BI file (it is not a zip package).") from e
        infos = self.z.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ModelError("This file holds too many parts to be a Power BI file.")
        self.names = {i.filename: i for i in infos if not i.is_dir()}
        self.read_total = 0

    def read(self, name: str, limit: int = MAX_MEMBER) -> bytes:
        info = self.names[name]
        if info.file_size > limit or self.read_total + info.file_size > MAX_TOTAL:
            raise ModelError(f"A part of this file is too big to read ({info.file_size // 1048576} MB).")
        with self.z.open(info) as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            raise ModelError("A part of this file is bigger than it says.")
        self.read_total += len(data)
        return data

    def close(self):
        self.z.close()


# ---------------------------------------------------------------- report usage (which visuals show which fields)

AGG_FN = {0: "Sum", 1: "Average", 2: "Count", 3: "Min", 4: "Max", 5: "Count (not blank)", 6: "Median",
          7: "Standard deviation", 8: "Variance"}


def _literal(v) -> str | None:
    if isinstance(v, str):
        return v[1:-1].replace("''", "'") if len(v) >= 2 and v[0] == "'" and v[-1] == "'" else v
    return None


def _fields(obj, out: list, depth: int = 0):
    """Every field a visual's query or projections name: ("measure", table, name), ("column", table, name, agg)."""
    if depth > 40:
        return
    if isinstance(obj, dict):
        if "Measure" in obj and isinstance(obj["Measure"], dict):
            m = obj["Measure"]
            ent = ((m.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
            if m.get("Property"):
                out.append(("measure", ent, m["Property"], None))
                return
        if "Aggregation" in obj and isinstance(obj["Aggregation"], dict):
            a = obj["Aggregation"]
            col = (a.get("Expression") or {}).get("Column") or {}
            ent = ((col.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
            if col.get("Property"):
                out.append(("column", ent, col["Property"], AGG_FN.get(a.get("Function"), "Aggregate")))
                return
        for v in obj.values():
            _fields(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _fields(v, out, depth + 1)


def _title(objects) -> str | None:
    try:
        props = objects["title"][0]["properties"]
        return _literal(props["text"]["expr"]["Literal"]["Value"])
    except (KeyError, IndexError, TypeError):
        return None


def _usage_add(use: dict, page: str, vtype: str, title: str | None, fields: list) -> None:
    n = len({name for kind, _, name, _ in fields if kind == "measure"})          # how many measures the visual shows
    for kind, ent, name, agg in fields:
        where = {"page": page, "visual": vtype, "title": title, "measures": n}
        if kind == "measure":
            use["measures"].setdefault(name, []).append(where)
        else:
            use["columns"].setdefault(f"{ent}[{name}]", []).append({**where, "agg": agg})


def report_usage(z: _Zip, prefix: str = "") -> dict | None:
    """Which measures and columns the report's visuals show (PBIR folders or the older Report/Layout)."""
    use = {"measures": {}, "columns": {}, "pages": 0, "visuals": 0}
    names = [n for n in z.names if n.startswith(prefix)]
    layout = next((n for n in names if n[len(prefix):] in ("Report/Layout", "report.json", "Report/report.json")), None)
    pbir = sorted(n for n in names if re.search(r"(^|/)definition/pages/[^/]+/visuals/[^/]+/visual\.json$", n[len(prefix):]))
    if pbir:
        pages = {}
        for n in names:
            m = re.search(r"(^|/)definition/pages/([^/]+)/page\.json$", n[len(prefix):])
            if m:
                try:
                    pages[m.group(2)] = _json_bytes(z.read(n, 4 * 1024 * 1024)).get("displayName") or m.group(2)
                except ModelError:
                    pages[m.group(2)] = m.group(2)
        use["pages"] = len(pages)
        for n in pbir[:5000]:
            try:
                v = _json_bytes(z.read(n, 4 * 1024 * 1024))
            except ModelError:
                continue
            page = pages.get(re.search(r"pages/([^/]+)/visuals", n).group(1), "")
            vis = v.get("visual") or {}
            fields: list = []
            _fields(vis.get("query") or {}, fields)
            if not fields:
                continue
            use["visuals"] += 1
            _usage_add(use, page, str(vis.get("visualType") or ""), _title(vis.get("visualContainerObjects") or {}), fields)
        return use
    if layout:
        try:
            doc = _json_bytes(z.read(layout, 32 * 1024 * 1024))
        except ModelError:
            return None
        sections = doc.get("sections") or []
        use["pages"] = len(sections)
        for s in sections[:500]:
            page = s.get("displayName") or s.get("name") or ""
            for vc in (s.get("visualContainers") or [])[:2000]:
                try:
                    cfg = json.loads(vc.get("config") or "{}")
                except ValueError:
                    continue
                sv = cfg.get("singleVisual") or {}
                fields = []
                _fields(sv.get("prototypeQuery") or {}, fields)
                if not fields:
                    continue
                use["visuals"] += 1
                _usage_add(use, page, str(sv.get("visualType") or ""), _title(sv.get("vcObjects") or {}), fields)
        return use
    return None


# ---------------------------------------------------------------- the readers

def read_bim(path: Path, name: str = "") -> dict:
    data = Path(path).read_bytes()
    if len(data) > MAX_MEMBER:
        raise ModelError("This model file is too big to read.")
    m = from_tmsl(_json_bytes(data), name)
    m["source"] = {"kind": "bim"}
    return m


def read_pbit(path: Path, name: str = "") -> dict:
    z = _Zip(Path(path))
    try:
        if "DataModelSchema" not in z.names:
            raise ModelError("This template has no model in it.")
        m = from_tmsl(_json_bytes(z.read("DataModelSchema")), name)
        m["usage"] = report_usage(z)
    finally:
        z.close()
    m["source"] = {"kind": "pbit"}
    return m


def read_pbip_zip(path: Path, name: str = "") -> dict:
    """A zipped Power BI project folder: <name>.SemanticModel (or .Dataset) with model.bim or definition/*.tmdl, and
    its .Report folder when it is there."""
    z = _Zip(Path(path))
    try:
        names = list(z.names)
        bim = next((n for n in names if re.search(r"(^|/)[^/]*\.(SemanticModel|Dataset)/model\.bim$", n)), None) \
            or next((n for n in names if n.endswith("model.bim")), None)
        tmdl_files = [n for n in names if n.lower().endswith(".tmdl") and "/definition/" in "/" + n]
        if bim:
            m = from_tmsl(_json_bytes(z.read(bim)), name)
            root = bim.rsplit("/", 2)[0] if "/" in bim else ""
        elif tmdl_files:
            files = {}
            for n in tmdl_files[:3000]:
                files[n] = z.read(n, 8 * 1024 * 1024).decode("utf-8-sig", errors="replace")
            m = tmdl.model(files, name)
            root = ""
        elif any(n.lower().endswith(".pbix") for n in names):
            raise ModelError("This zip holds a .pbix file: upload the .pbix itself.")
        else:
            raise ModelError("This zip is not a Power BI project: no model.bim or TMDL files (definition/*.tmdl) in it.")
        rep = next((n.split("definition/")[0] for n in names if re.search(r"\.Report/definition/", n)), None) \
            or next((n.rsplit("report.json", 1)[0] for n in names if re.search(r"\.Report/report\.json$", n)), None)
        m["usage"] = report_usage(z, rep) if rep is not None else None
        del root
    finally:
        z.close()
    m["source"] = {"kind": "pbip"}
    return m


def tmdl_parts(parts: dict[str, bytes], name: str = "") -> dict:
    """The neutral model from a Fabric definition's parts (path -> bytes): model.bim (TMSL) or definition/*.tmdl."""
    if "model.bim" in parts:
        return from_tmsl(_json_bytes(parts["model.bim"]), name)
    files = {p: b.decode("utf-8-sig", errors="replace") for p, b in parts.items() if p.lower().endswith(".tmdl")}
    if not files:
        raise ModelError("The Power BI service sent no model definition.")
    return tmdl.model(files, name)


def read_pbix_parts(path: Path) -> dict:
    """What a .pbix holds besides its compressed model: whether there is a model at all (a report connected live to
    a model in the Power BI service has none) and the report's usage."""
    z = _Zip(Path(path))
    try:
        has_model = "DataModel" in z.names
        live = "Connections" in z.names and not has_model
        usage = report_usage(z)
    finally:
        z.close()
    return {"has_model": has_model, "live": live, "usage": usage}


def pbix_command(src: Path, out: Path) -> list[str]:
    """The command that reads a .pbix's model into out (JSON): this interpreter, isolated (-I: no PYTHONPATH, no
    current folder on the path; pbix_read.py imports only the standard library and PBIXRay), run by its path."""
    return [sys.executable, "-I", str(Path(__file__).with_name("pbix_read.py")), str(src), str(out)]


def kind_of(filename: str) -> str | None:
    ext = Path(filename or "").suffix.lower()
    return {".pbix": "pbix", ".pbit": "pbit", ".bim": "bim", ".json": "bim", ".zip": "pbip"}.get(ext)


def read(path: Path, filename: str, name: str = "") -> dict:
    """Every kind but .pbix (which needs its own process: pbix_command)."""
    kind = kind_of(filename)
    if kind == "pbit":
        return read_pbit(path, name)
    if kind == "bim":
        return read_bim(path, name)
    if kind == "pbip":
        return read_pbip_zip(path, name)
    raise ModelError(f'"{filename}" is not a file the review reads: upload a .pbix, .pbit, model.bim or a zipped Power BI project.')


def tidy(m: dict) -> dict:
    """Limits and clean-up shared by every reader: the automatic date tables Power BI adds (LocalDateTable_...,
    DateTableTemplate_...) are left out, names are text, and a model over MAX_MEASURES measures is refused."""
    # also the engine's own hierarchy tables (H$..., R$..., U$...) a .pbix's metadata lists
    auto = re.compile(r"^((LocalDateTable|DateTableTemplate)_[0-9a-f-]+|[HRU]\$.*)$", re.I)
    m["tables"] = [t for t in m.get("tables") or [] if not auto.match(str(t.get("name") or ""))]
    m["measures"] = [x for x in m.get("measures") or [] if str(x.get("name") or "").strip()]
    m["relationships"] = [r for r in m.get("relationships") or []
                          if not (auto.match(str((r.get("to") or [""])[0] or "")) or auto.match(str((r.get("from") or [""])[0] or "")))]
    if len(m["measures"]) > MAX_MEASURES:
        raise ModelError(f"This model has {len(m['measures']):,} measures; the review reads up to {MAX_MEASURES:,}.")
    m.setdefault("calc_groups", [])
    m.setdefault("usage", None)
    return m
