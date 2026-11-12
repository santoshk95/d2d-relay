"""DAX check: Power BI's own engine loads the report's model and evaluates every measure and every visual's query
before the report is shared.

The engine is Analysis Services from Power BI Desktop, so it runs on the Windows PC, not in Docker: the DAX checker
(daxcheck/daxcheck.ps1, started on that PC) watches a queue folder next to the projects. This module builds a check
copy of the model - the same model.bim the PBIP gets, with every CSV table and the date table loaded as a DAX
DATATABLE from the DuckDB views (no Power Query needed) - plus one query per measure and per visual with the
report's default filters, drops them in the queue and reads the engine's answer: object errors (syntax, semantic,
circular dependencies), each query's rows or error, and the measures' values. Then every visual's numbers and title
are compared with what its prototype SQL returned, so Power BI shows what the user approved in the prototype.
"""
import json
import math
import os
import re
import secrets
import time
from pathlib import Path

from . import data as data_mod
from . import report_builder as rb

ROOT = Path(os.environ.get("WORKSPACES", "/data/projects"))
QUEUE = Path(os.environ.get("GENBI_DAXCHECK", ROOT / ".daxcheck"))
DATABASE = "GenBICheck"
MAX_ROWS = 10000                       # rows per table in the check model (a sample beyond, the check is about errors)
DAX_TYPE = {"int": "INTEGER", "decimal": "DOUBLE", "string": "STRING", "date": "DATETIME", "bool": "BOOLEAN"}
COLUMN = re.compile(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$")
MEASURE = re.compile(r"^\[([^\]]+)\]$")


class CheckError(Exception):
    pass


def available() -> dict | None:
    """The checker's heartbeat, if it wrote one in the last 30 seconds."""
    try:
        beat = json.loads((QUEUE / "heartbeat.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return beat if time.time() - float(beat.get("time", 0)) < 30 else None


def _dax_str(s) -> str:
    return '"' + str(s).replace('"', '""') + '"'


def _literal(value, kind: str) -> str:
    if value is None:
        return "BLANK ()"
    if kind == "bool":
        return "TRUE ()" if value else "FALSE ()"
    if kind in ("int", "decimal"):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "BLANK ()"
        return str(int(value)) if kind == "int" else repr(float(value))
    if kind == "date":
        return _dax_str(str(value)[:10])
    return _dax_str(value)


def _datatable(columns: list[dict], rows: list[list]) -> str:
    head = ", ".join(f"{_dax_str(c['name'])}, {DAX_TYPE[c['type']]}" for c in columns)
    rows = rows or [[None] * len(columns)]
    body = ",\n".join("{ " + ", ".join(_literal(v, c["type"]) for v, c in zip(r, columns)) + " }" for r in rows)
    return f"DATATABLE (\n{head},\n{{\n{body}\n}}\n)"


def check_model(dd: dict, project: Path) -> tuple[dict, list[str]]:
    """model.bim for the check (as the PBIP gets it, DAX quoted) with every non-DAX table as a DATATABLE of its data."""
    model = rb.Model(dd)
    model.validate()
    bim = rb._model_bim(dd, model)
    con = data_mod.connect(project, dd)
    sampled = []
    kinds = {t["name"]: {c["name"]: c.get("type", "string") for c in t.get("columns", [])} for t in dd["tables"]}
    for table in bim["model"]["tables"]:
        part = table["partitions"][0]["source"]
        if part.get("type") == "calculated":
            continue
        base = [c for c in table["columns"] if c.get("type") != "calculated"]
        cols = [{"name": c["name"], "type": kinds[table["name"]].get(c["name"], "string")} for c in base]
        q = ", ".join(data_mod._q(c["name"]) for c in cols)
        n = con.execute(f"SELECT COUNT(*) FROM {data_mod._q(table['name'])}").fetchone()[0]
        sample = f" USING SAMPLE {MAX_ROWS} ROWS (reservoir, 42)" if n > MAX_ROWS else ""
        if sample:
            sampled.append(f"{table['name']} ({MAX_ROWS:,} of {n:,} rows)")
        rows = [[data_mod._plain(v) for v in r] for r in con.execute(f"SELECT {q} FROM {data_mod._q(table['name'])}{sample}").fetchall()]
        table["partitions"][0]["source"] = {"type": "calculated", "expression": _datatable(cols, rows)}
        for c in base:
            c.update(type="calculatedTableColumn", isNameInferred=True, isDataTypeInferred=True, sourceColumn=f"[{c['name']}]")
    bim["name"] = DATABASE
    bim["model"].pop("expressions", None)                 # no Power Query in the check copy
    bim["model"]["annotations"] = [a for a in bim["model"].get("annotations", []) if a.get("name") != "PBI_QueryOrder"]
    return bim, sampled


def _filters(dd: dict) -> list[str]:
    """The report-wide slicers' default values, as filter arguments."""
    out = []
    for f in dd.get("filters") or []:
        m = COLUMN.match(str(f.get("field", "")).strip())
        if m and f.get("default") not in (None, ""):
            value = f["default"] if isinstance(f["default"], (int, float)) else _dax_str(f["default"])
            out.append(f"TREATAS ( {{ {value} }}, '{m.group(1)}'[{m.group(2)}] )")
    return out


def _visual_fields(v: dict, catalog: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(role, ref) of the columns a visual groups by - a drill hierarchy at its top level - and of its measures, the
    title measure last (role "title")."""
    entry, groups, measures = catalog.get(v["type"]) or {}, [], []
    drill = set(entry.get("drill") or []) | set(entry.get("first_only") or [])     # the visual opens at the first level
    raw = v.get("fields") or {}
    fields = {"columns": raw} if isinstance(raw, list) else dict(raw)      # a table visual lists its fields
    for role, refs in fields.items():
        refs = refs if isinstance(refs, list) else [refs]
        for i, ref in enumerate(refs):
            ref = str(ref).strip()
            if MEASURE.match(ref):
                measures.append((role, ref))
            elif COLUMN.match(ref) and not (role in drill and i > 0):
                groups.append((role, ref))
    title = str(v.get("title") or "").strip()
    if MEASURE.match(title):
        measures.append(("title", title))
    unique = lambda items: list({ref: (role, ref) for role, ref in reversed(items)}.values())[::-1]
    return unique(groups), unique(measures)


def queries(dd: dict, catalog: dict) -> list[dict]:
    """One query per measure (its value, and its text in the measure's format) and one per visual (the data it asks
    Power BI for), all under the report's default filters."""
    filters = _filters(dd)
    wrap = (lambda body: f"EVALUATE CALCULATETABLE ( {body}, {', '.join(filters)} )") if filters else (lambda body: f"EVALUATE {body}")
    out = []
    for m in dd["measures"]:
        ref = f"[{m['name'].replace(']', ']]')}]"
        fmt = m.get("format")
        shown = f", \"text\", IFERROR ( FORMAT ( {ref}, {_dax_str(fmt)} ), \"\" )" if fmt else ""
        out.append({"key": f"measure:{m['name']}", "dax": wrap(f"ROW ( \"value\", {ref}{shown} )")})
    for page in dd["pages"]:
        for v in page["visuals"]:
            if v["type"] in ("slicer", "textbox", "pageNavigator"):
                continue
            groups, measures = _visual_fields(v, catalog)
            if not groups and not measures:
                continue
            cols = [f"'{COLUMN.match(ref).group(1)}'[{COLUMN.match(ref).group(2)}]" for _, ref in groups]
            args = cols + filters + [f"\"m{i}\", {ref}" for i, (_, ref) in enumerate(measures)]
            out.append({"key": f"visual:{page['name']} / {v['id']}", "dax": f"EVALUATE TOPN ( 50, SUMMARIZECOLUMNS ( {', '.join(args)} ) )"})
    return out


# ---------------------------------------------------------------- does Power BI show what the prototype showed?

NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _key(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    text = str(v).strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else text.lower()


def _numbers(text) -> list[float]:
    return [float(n.replace(",", "")) for n in NUMBER.findall(str(text or "")) if n.replace(",", "").strip("-")]


def _same(a, b) -> bool:
    """Equal as Power BI would show them: numbers within 0.5 %, texts with the same numbers in them (a sentence's
    last digit may round differently in DAX and SQL), blank and 0 alike."""
    blank = lambda x: x is None or x == "" or x == 0
    if blank(a) and blank(b):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(1e-6, 0.005 * max(abs(a), abs(b)))
    na, nb = _numbers(a), _numbers(b)
    return len(na) == len(nb) and all(abs(x - y) <= max(0.1 + 1e-9, 0.005 * max(abs(x), abs(y))) for x, y in zip(na, nb))


def _show(x) -> str:
    if isinstance(x, float):
        return f"{x:,.4f}".rstrip("0").rstrip(".")
    return "(blank)" if x in (None, "") else repr(str(x)) if isinstance(x, str) else str(x)


def _sql_column(row: dict, role: str, ref: str):
    """The prototype SQL column for a field: named after it (Visual Atlas, custom visuals) or after its well (Gen BI)."""
    m, c = MEASURE.match(ref), COLUMN.match(ref)
    names = [m.group(1) if m else c.group(2) if c else ref, role]
    for name in names:
        for col in row:
            if col.lower() == str(name).lower():
                return col
    return None


def differences(dd: dict, con, catalog: dict, report: dict) -> list[str]:
    """Where Power BI's DAX disagrees with the prototype SQL the user reviewed: per visual, the values of matching rows
    (Visual Atlas and custom visuals) and the title and insight sentences (all visuals)."""
    from . import prototype
    got = {q["key"]: q for q in report.get("queries") or [] if q.get("ok")}
    out = []
    for page in dd["pages"]:
        for v in page["visuals"]:
            q, sql = got.get(f"visual:{page['name']} / {v['id']}"), (v.get("prototype") or {}).get("sql")
            if not q or not sql:
                continue
            try:
                rows = prototype.records(con, sql)
            except Exception:  # noqa: BLE001 - the prototype check reports broken SQL
                continue
            groups, measures = _visual_fields(v, catalog)
            atlas = (catalog.get(v["type"]) or {}).get("family") in ("atlas", "powerbi")   # one SQL column per field
            dax = [dict(zip([r for r, _ in groups] + [f"m{i}" for i in range(len(measures))], r)) for r in q.get("rows") or []]
            where, found = f"{page['name']} / {v['id']}", []
            if v["type"] == "narrative" and rows and dax:
                texts = [r.get(_sql_column(r, "item", "item") or "item") for r in rows]
                for i, (_, ref) in enumerate(measures):
                    if i < len(texts) and not _same(texts[i], dax[0].get(f"m{i}")):
                        found.append(f"{ref} - prototype {_show(texts[i])} but Power BI {_show(dax[0].get(f'm{i}'))}")
            for i, (role, ref) in enumerate(measures):
                if role != "title" and not atlas:
                    continue
                col = _sql_column(rows[0], role, ref) if rows else None
                if role == "title":
                    col = col or (_sql_column(rows[0], "title", "title") if rows else None)
                if not col:
                    continue
                if role == "title":      # Power BI evaluates a title for the whole visual, not per category
                    a = next((r[col] for r in rows if r.get(col) not in (None, "")), None)
                    whole = got.get(f"measure:{MEASURE.match(ref).group(1)}")
                    b = whole["rows"][0][0] if whole and whole.get("rows") else None
                    if a is not None and not _same(a, b):
                        found.append(f"title - prototype {_show(a)} but Power BI {_show(b)}")
                    continue
                keys = [(role_g, _sql_column(rows[0], role_g, ref_g)) for role_g, ref_g in groups]
                if any(k is None for _, k in keys):
                    continue
                sql_rows = {tuple(_key(r[k]) for _, k in keys): r[col] for r in rows}
                for d in dax:
                    key = tuple(_key(d.get(role_g)) for role_g, _ in groups)
                    if key in sql_rows and not _same(sql_rows[key], d.get(f"m{i}")):
                        label = f"{ref}" + (f" for {', '.join(str(k) for k in key)}" if key else "")
                        found.append(f"{label} - prototype {_show(sql_rows[key])} but Power BI {_show(d.get(f'm{i}'))}")
            out += [f"{where}: {f}" for f in found[:3]]
    return out


def run(project: Path, dd: dict, catalog: dict, timeout: int = 300) -> dict:
    """Check the model in Power BI's engine. Returns the checker's report plus `problems` (one line each)."""
    if not available():
        raise CheckError("the DAX checker is not running on this PC (start daxcheck\\start-daxcheck.cmd)")
    bim, sampled = check_model(dd, project)
    qs = queries(dd, catalog)
    rid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    req = QUEUE / "requests"
    req.mkdir(parents=True, exist_ok=True)
    (req / f"{rid}.model.json").write_text(json.dumps(bim), encoding="utf-8")
    tmp = req / f"{rid}.json.tmp"
    tmp.write_text(json.dumps({"id": rid, "project": project.name, "queries": qs, "created": time.time()}), encoding="utf-8")
    tmp.rename(req / f"{rid}.json")
    result = QUEUE / "results" / f"{rid}.json"
    deadline = time.time() + timeout
    while not result.exists():
        if time.time() > deadline:
            for f in (req / f"{rid}.json", req / f"{rid}.model.json"):
                f.unlink(missing_ok=True)
            raise CheckError(f"the DAX checker did not answer within {timeout // 60} minutes")
        time.sleep(0.5)
    report = json.loads(result.read_text(encoding="utf-8-sig"))
    result.unlink(missing_ok=True)
    report["sampled"] = sampled
    report["problems"] = problems(report)
    report["differences"] = [] if sampled or report.get("error") else \
        differences(dd, data_mod.connect(project, dd), catalog, report)
    return report


def summary(report: dict) -> dict:
    """What a version or the PBIP keeps: counts, the engine, and every measure's value as Power BI shows it."""
    qs = report.get("queries") or []
    values = [{"name": q["key"][8:], "value": (q["rows"][0][0] if q.get("rows") else None),
               "text": (q["rows"][0][1] if q.get("rows") and len(q["rows"][0]) > 1 else None), "error": q.get("error")}
              for q in qs if q["key"].startswith("measure:")]
    visuals = [{"name": q["key"][7:], "rows": q.get("count"), "error": q.get("error")} for q in qs if q["key"].startswith("visual:")]
    return {"checked": True, "engine": report.get("engine"), "seconds": report.get("seconds"), "when": time.time(),
            "measures": len(values), "visuals": len(visuals), "problems": report.get("problems") or [],
            "differences": report.get("differences") or [], "compared": not report.get("sampled"),
            "sampled": report.get("sampled") or [], "values": values, "visual_rows": visuals}


def text_report(s: dict, name: str) -> str:
    """DAX check.txt for the PBIP: what Power BI's engine computed for every measure and visual."""
    lines = [f"{name} - DAX check in Power BI's engine (Power BI Desktop {s.get('engine')})",
             time.strftime("Checked %Y-%m-%d %H:%M %Z", time.localtime(s.get("when", time.time()))) +
             f" - {s['measures']} measures, {s['visuals']} visuals, {len(s['problems'])} problem(s)", ""]
    if s.get("sampled"):
        lines += ["Large tables were checked on a sample, so these values can differ from the full data: "
                  + "; ".join(s["sampled"]), ""]
    if s["problems"]:
        lines += ["Problems:"] + [f"  - {p}" for p in s["problems"]] + [""]
    if s.get("differences"):
        lines += ["Values that differ from the approved prototype:"] + [f"  - {p}" for p in s["differences"]] + [""]
    elif s.get("compared"):
        lines += ["Every visual's values and titles match the prototype.", ""]
    lines += ["Measures (report's default filters):"]
    width = max([len(v["name"]) for v in s["values"]] + [10])
    for v in s["values"]:
        shown = v["error"] or (v["text"] if v.get("text") not in (None, "") else v["value"])
        lines.append(f"  {v['name'].ljust(width)}  {'' if shown is None else shown}")
    lines += ["", "Visuals (rows returned, up to 50):"]
    lines += [f"  {v['name']}: {v['error'] or v['rows']}" for v in s["visual_rows"]]
    return "\n".join(lines) + "\n"


def problems(report: dict) -> list[str]:
    """What Power BI would show as errors: broken measures, calculated columns or tables, and visual queries that
    fail. A measure that only fails because another one does is reported once, at the root."""
    out = []
    if report.get("error"):
        out.append(f"DAX check: {report['error']}")
    for o in report.get("objects") or []:
        if o.get("error") and o.get("state") != "DependencyError":
            out.append(f"DAX {o['kind']} {o['name']}: {o['error']}")
    broken = {o["name"] for o in report.get("objects") or [] if o.get("error")}
    failing = {q["key"][8:] for q in report.get("queries") or [] if q["key"].startswith("measure:") and q.get("error")}
    for q in report.get("queries") or []:
        if not q.get("error"):
            continue
        if q["key"].startswith("measure:"):
            name = q["key"][8:]
            cause = re.search(r"in measure '[^']*'\[([^\]]+)\]", q["error"])
            if f"[{name}]" in broken or (cause and cause.group(1) != name and cause.group(1) in failing):
                continue                               # reported at the measure that fails first
            out.append(f"DAX measure [{name}]: {q['error']}")
        else:
            out.append(f"DAX visual {q['key'][7:]}: {q['error']}")
    return out
