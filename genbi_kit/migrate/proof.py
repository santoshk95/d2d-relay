"""Numbers vs source: every visual of the converted report is computed twice — by the source simulator (the source
report's query on the source data, Cognos semantics) and by the converted definition's prototype SQL (the same
numbers Power BI's DAX is then checked against by the values gate) — and compared number by number. "Proven" is the
count of numbers matched, with every difference listed, never a tick.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .. import data as data_mod
from .. import definition
from . import source_sim

MONTHS = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
TOL = 1e-6


def _norm_key(v):
    if v is None:
        return None
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str):
        s = v.strip()
        if s in MONTHS:
            return MONTHS[s]
        try:
            f = float(s)
            return int(f) if f.is_integer() else round(f, 6)
        except ValueError:
            return s
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 6)
    return v


def _same(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, str) or isinstance(b, str):
        return _norm_key(a) == _norm_key(b)
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return abs(a - b) <= TOL * max(1.0, abs(a), abs(b))


def _show(v) -> str:
    if v is None:
        return "blank"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return str(v)


def prove(project_dir: Path, estate: dict, report: dict, plan: dict, source_dir: Path) -> dict:
    """Run the proof for a converted report folder (definition.yaml + data/) against the estate's source data."""
    d = Path(project_dir)
    raw = definition.load(d / "definition.yaml")
    dd = definition.expand(raw)
    con = data_mod.connect(d, dd)
    ds = next((x for x in estate["datasets"] if x["id"] == report.get("dataset")), None)
    queries = {q["name"]: q for q in report.get("queries") or []}
    blank = {m["name"] for m in raw.get("measures") or [] if str(m.get("expression", "")).strip().upper() in ("BLANK ()", "BLANK()")}
    by_id = {v["id"]: v for v in definition.iter_visuals(raw)}
    out: dict = {"visuals": [], "compared": 0, "matched": 0, "differences": 0, "open": sorted(blank), "skipped": 0}
    for pv in plan.get("visuals") or []:
        meta = pv.get("proof")
        if not meta or not pv.get("type"):
            continue
        vis = by_id.get(pv.get("def_id") or pv["id"])
        rec = {"id": pv.get("def_id") or pv["id"], "source_id": pv["id"], "title": pv.get("title") or pv["id"], "kind": pv.get("kind"), "type": pv.get("type"), "compared": 0, "matched": 0,
               "differences": [], "rows_source": 0, "rows_target": 0}
        sql = ((vis or {}).get("prototype") or {}).get("sql")
        q = queries.get(meta.get("query"))
        if not vis or not sql or not q or not ds:
            rec["skipped"] = "no prototype query or source query to compare"
            out["skipped"] += 1; out["visuals"].append(rec); continue
        try:
            target = data_mod.records(con, sql)
        except Exception as e:  # noqa: BLE001 - the gate reports it too
            rec["skipped"] = f"the prototype query failed: {str(e).splitlines()[0][:200]}"
            out["skipped"] += 1; out["visuals"].append(rec); continue
        cats = [c["item"] for c in meta.get("categories") or []]
        meas = [m for m in meta.get("measures") or [] if not m.get("sql_missing")]
        try:
            source = source_sim.evaluate(ds, Path(source_dir) / "data", q, cats, [m["item"] for m in meas], order_by_measure=False, limit=0)
        except source_sim.SimError as e:
            rec["skipped"] = f"the source simulator could not run the query: {e}"
            out["skipped"] += 1; out["visuals"].append(rec); continue
        cat_cols = [c["column"] for c in meta.get("categories") or []]
        src_index = {tuple(_norm_key(r.get(c)) for c in cats): r for r in source}
        rec["rows_source"], rec["rows_target"] = len(source), len(target)
        for tr in target:
            key = tuple(_norm_key(tr.get(c)) for c in cat_cols)
            sr = src_index.get(key)
            if sr is None:
                for m in meas:
                    rec["compared"] += 1
                    rec["differences"].append({"key": " · ".join(_show(tr.get(c)) for c in cat_cols) or "(total)", "measure": m["measure"], "source": "no such row", "target": _show(tr.get(m["measure"]))})
                continue
            for m in meas:
                if m["measure"] in blank:
                    continue                                       # the agent has not written this measure yet: not compared
                rec["compared"] += 1
                a, b = sr.get(m["item"]), tr.get(m["measure"])
                if _same(a, b):
                    rec["matched"] += 1
                else:
                    rec["differences"].append({"key": " · ".join(_show(tr.get(c)) for c in cat_cols) or "(total)", "measure": m["measure"], "source": _show(a), "target": _show(b)})
        if not meas or all(m["measure"] in blank for m in meas):
            rec["skipped"] = "every measure of this visual is still for the agent"
            out["skipped"] += 1
        out["compared"] += rec["compared"]; out["matched"] += rec["matched"]; out["differences"] += len(rec["differences"])
        rec["differences"] = rec["differences"][:20]
        out["visuals"].append(rec)
    out["proven"] = out["compared"] > 0 and out["differences"] == 0 and not blank
    out["when"] = __import__("time").time()
    return out


def evidence(proof: dict, report_name: str) -> dict:
    """The checkpoint's evidence: a table of the first comparisons and every difference, with the counts."""
    rows = []
    for v in proof.get("visuals") or []:
        for dfx in v.get("differences") or []:
            rows.append([v["title"], dfx["key"], dfx["measure"], dfx["source"], dfx["target"], "no"])
        if v.get("compared") and not v.get("differences"):
            rows.append([v["title"], f"{v['rows_target']} rows", "all measures", f"{v['compared']} numbers", "the same", "yes"])
        elif v.get("skipped"):
            rows.append([v["title"], "—", "—", v["skipped"], "", "skipped"])
    items = [f"{proof.get('matched', 0):,} of {proof.get('compared', 0):,} numbers match the source" + (f"; {proof['differences']} differ" if proof.get("differences") else "")]
    if proof.get("open"):
        items.append(f"{len(proof['open'])} measure(s) still for the agent: " + ", ".join(proof["open"][:5]))
    return {"summary": f"{report_name}: numbers against the source", "columns": ["Visual", "Row", "Measure", "Source", "Power BI prototype", "Match"], "rows": rows[:60],
            "items": items, "counts": {"compared": proof.get("compared", 0), "matched": proof.get("matched", 0), "differences": proof.get("differences", 0), "open": len(proof.get("open") or [])},
            "proven": bool(proof.get("proven"))}
