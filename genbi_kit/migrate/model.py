"""The neutral (tool-independent) model of a BI estate.

Plain dicts so it round-trips as JSON (estate.json in a migration project). Readers fill it; the rules, the decide
step, the converter and the proof read it. Every object keeps the source tool's own words in `type` and `folder`.

estate = {
  "source": {"tool": "cognos", "label": "IBM Cognos Analytics", "version": "11.2.4", "read_from": "exports"},
  "read_at": 1699999999.0, "read_seconds": 12.3,
  "folders":  [{"path": "Team content/Finance", "personal": false, "owner": "Finance", "objects": 702}],
  "datasets": [{"id": "pkg-sales", "name": "Sales", "kind": "package" | "data module", "folder": "...",
                "tables": [{"name": "Sales", "file": "sales.csv", "role": "fact" | "dimension",
                            "columns": [{"name": "Revenue", "type": "decimal", "role": "measure"}, ...]}],
                "relationships": [{"from": "Sales[StoreKey]", "to": "Store[StoreKey]"}], "has_data": true}],
  "reports":  [{"id": "r-0001", "name": "...", "type": "Report", "folder": "...", "owner": "Finance",
                "dataset": "pkg-sales" | null, "missing_dataset": "name" | null, "base": "<report id>" (views),
                "created": "2024-03-01", "modified": "2026-09-30", "shared": true, "personal": false,
                "spec_file": "specs/r-0001.xml",
                "queries":  [{"name": "Query1", "items": [{"name": "Revenue", "expression": "...", "aggregate": "total",
                                                            "kind": "measure" | "attribute" | "calculation"}],
                              "filters": [{"expression": "[Region] = ?pRegion?", "kind": "detail" | "summary"}]}],
                "prompts":  [{"name": "pRegion", "item": "Region", "query": "Query1", "type": "multi" | "value" | "range"}],
                "pages":    [{"name": "Page1", "visuals": [{"id": "List1", "kind": "list", "query": "Query1", "title": "...",
                                                            "category": "Region", "series": null, "measures": ["Revenue"],
                                                            "columns": [...]}]}],
                "features": ["active report", "custom javascript", "map"],
                "usage": {"runs_365": 12, "runs_90": 3, "last_run_days": 14 | null, "failed_days": null, "users": 2},
                "complexity": "simple" | "medium" | "complex" | "very complex", "calculations": 5,
                "dependencies": ["pkg-sales"]}],
  "usage": {"source": "Audit database", "from": "2024-04-01", "to": "2026-09-30", "runs": 81406, "days": 913},
  "problems": ["..."]
}
"""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

COMPLEXITY = ("simple", "medium", "complex", "very complex")
LAST_USED = ("< 30 days", "30–90 days", "90–365 days", "> 1 year", "Never run")
TOOLS = {
    "cognos": {"label": "IBM Cognos Analytics", "versions": ["11.2.x", "12.0.x", "11.1.x"],
               "terms": "Reports, Report views, Dashboards, Stories, Data modules, Packages; usage from the Audit database."},
    "qlik_sense": {"label": "Qlik Sense", "versions": ["Enterprise 2024", "Cloud"],
                   "terms": "Apps, Sheets, Master items, Data connections; usage from the Monitoring apps."},
    "qlikview": {"label": "QlikView", "versions": ["12.x", "11.x"],
                 "terms": "Documents (QVW), load scripts, QVD files, sheets and objects, section access; usage from the QlikView Server logs."},
    "microstrategy": {"label": "MicroStrategy", "versions": ["2021", "ONE"],
                      "terms": "Documents, Dossiers, Reports, Cubes, Attributes, Metrics, Filters; usage from Enterprise Manager."},
    "tableau": {"label": "Tableau", "versions": ["Server 2024.2", "Cloud"],
                "terms": "Workbooks, Views, Data sources, Flows; usage from the Repository."},
    "ssrs": {"label": "SSRS", "versions": ["2022", "2019"],
             "terms": "Reports, Shared datasets, Data sources, Subscriptions; usage from the Execution log."},
    "businessobjects": {"label": "SAP BusinessObjects", "versions": ["BI 4.3"],
                        "terms": "Web Intelligence documents, Universes, Crystal reports; usage from the Audit database."},
}


def new_estate(tool: str, version: str = "", read_from: str = "exports") -> dict:
    return {"source": {"tool": tool, "label": TOOLS.get(tool, {}).get("label", tool), "version": version, "read_from": read_from},
            "read_at": None, "read_seconds": None, "folders": [], "datasets": [], "reports": [],
            "usage": {"source": None, "from": None, "to": None, "runs": 0, "days": 0}, "problems": []}


def column(name: str, type_: str = "string", role: str | None = None) -> dict:
    """A dataset column. role: measure (numbers to add up), attribute (to group by), date, key."""
    if role is None:
        role = "measure" if type_ in ("int", "decimal") else "date" if type_ == "date" else "attribute"
    return {"name": name, "type": type_, "role": role}


def new_table(name: str, columns: list[dict], file: str | None = None, role: str = "dimension", key: str | None = None) -> dict:
    return {"name": name, "file": file, "role": role, "key": key, "columns": columns}


def new_dataset(id_: str, name: str, kind: str, tables: list[dict] | None = None, relationships: list[dict] | None = None,
                folder: str | None = None, has_data: bool = False) -> dict:
    return {"id": id_, "name": name, "kind": kind, "folder": folder, "tables": tables or [], "relationships": relationships or [],
            "has_data": has_data}


def new_report(id_: str, name: str, type_: str, folder: str, owner: str | None, dataset: str | None, **kw) -> dict:
    r = {"id": id_, "name": name, "type": type_, "folder": folder, "owner": owner, "dataset": dataset, "missing_dataset": None,
         "base": None, "created": None, "modified": None, "shared": not folder.startswith("My content"), "personal": folder.startswith("My content"),
         "spec_file": None, "queries": [], "prompts": [], "pages": [], "features": [],
         "usage": {"runs_365": 0, "runs_90": 0, "last_run_days": None, "failed_days": None, "users": 0},
         "complexity": "simple", "calculations": 0, "dependencies": []}
    r.update(kw)
    return r


def item(name: str, expression: str, aggregate: str | None = None, kind: str | None = None) -> dict:
    return {"name": name, "expression": expression, "aggregate": aggregate,
            "kind": kind or ("measure" if aggregate else "attribute" if _plain_ref(expression) else "calculation")}


def visual(id_: str, kind: str, query: str | None, title: str | None = None, **kw) -> dict:
    v = {"id": id_, "kind": kind, "query": query, "title": title, "category": None, "series": None, "measures": [], "columns": []}
    v.update(kw)
    return v


# ------------------------------------------------------------------ derived facts

def calculations(report: dict) -> list[dict]:
    """Every data item that is more than a plain column reference (an aggregate, a formula, a function)."""
    out = []
    for q in report.get("queries") or []:
        for it in q.get("items") or []:
            if it.get("kind") in ("calculation", "measure") or not _plain_ref(it.get("expression") or ""):
                out.append(it)
    return out


_REF = __import__("re").compile(r"^\[[^\]]*\](?:\s*\.\s*\[[^\]]*\])*$")


def _plain_ref(expr: str) -> bool:
    """A bare reference such as [Package].[Query subject].[Item] or [Data item] — a column, not a calculation."""
    return bool(_REF.match(expr.strip()))


def complexity_of(report: dict) -> str:
    """From what the report holds: how many calculations, visuals, pages, prompts and special features."""
    n = len(calculations(report))
    vis = sum(len(p.get("visuals") or []) for p in report.get("pages") or [])
    score = n + vis * 0.6 + len(report.get("pages") or []) * 0.8 + len(report.get("prompts") or []) * 0.5
    if report.get("features"):
        score += 8
    if any(it.get("expression", "").lower().lstrip().startswith(("running-", "moving-", "rank", "percentile", "#")) for it in calculations(report)):
        score += 6
    return "very complex" if score >= 28 else "complex" if score >= 15 else "medium" if score >= 6 else "simple"


def last_used_bucket(report: dict) -> str:
    d = (report.get("usage") or {}).get("last_run_days")
    if d is None:
        return "Never run"
    return "< 30 days" if d < 30 else "30–90 days" if d < 90 else "90–365 days" if d < 365 else "> 1 year"


def finish(estate: dict) -> dict:
    """Fill the derived fields (complexity, calculation counts, folder counts) after a read."""
    folders: dict[str, dict] = {f["path"]: f for f in estate["folders"]}
    for f in folders.values():
        f["objects"] = 0
    for r in estate["reports"]:
        r["calculations"] = len(calculations(r))
        r["complexity"] = r.get("complexity_given") or complexity_of(r)
        r.pop("complexity_given", None)
        f = folders.get(r["folder"])
        if f is None:
            f = folders[r["folder"]] = {"path": r["folder"], "personal": r["folder"].startswith("My content"), "owner": r.get("owner"), "objects": 0}
            estate["folders"].append(f)
        f["objects"] += 1
    estate["read_at"] = estate.get("read_at") or time.time()
    return estate


def counts(estate: dict) -> dict:
    """What we found: every number the Discover step shows, each one derived from the model (never typed in)."""
    rs = estate["reports"]
    by = lambda key: _count(key(r) for r in rs)  # noqa: E731
    used90 = sum(1 for r in rs if (r["usage"].get("last_run_days") is not None and r["usage"]["last_run_days"] <= 90))
    never = sum(1 for r in rs if r["usage"].get("last_run_days") is None)
    ds = estate["datasets"]
    return {"objects": len(rs), "by_type": by(lambda r: r["type"]), "by_folder": by(lambda r: r["folder"]),
            "by_complexity": {c: sum(1 for r in rs if r["complexity"] == c) for c in COMPLEXITY},
            "last_used": {b: sum(1 for r in rs if last_used_bucket(r) == b) for b in LAST_USED},
            "used_90": used90, "never": never, "shared_objects": len(ds),
            "datasets": {"package": sum(1 for d in ds if d["kind"] == "package"), "data module": sum(1 for d in ds if d["kind"] == "data module")},
            "with_data": sum(1 for d in ds if d.get("has_data")),
            "missing_dataset": sum(1 for r in rs if r.get("missing_dataset")),
            "failed_30": sum(1 for r in rs if r["usage"].get("failed_days") is not None and r["usage"]["failed_days"] <= 30),
            "personal": sum(1 for r in rs if r.get("personal")), "runs": estate["usage"].get("runs") or 0,
            "usage_from": estate["usage"].get("from"), "usage_to": estate["usage"].get("to"), "usage_days": estate["usage"].get("days"),
            "calculations": sum(r["calculations"] for r in rs), "folders": len(estate["folders"]), "problems": len(estate.get("problems") or [])}


def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def by_id(estate: dict) -> dict[str, dict]:
    return {r["id"]: r for r in estate["reports"]}


def dataset_of(estate: dict, report: dict) -> dict | None:
    return next((d for d in estate["datasets"] if d["id"] == report.get("dataset")), None)


def validate(estate: dict) -> list[str]:
    """What is wrong with a model a reader produced (shown as 'problems' on the Discover step)."""
    out = []
    ids = set()
    ds = {d["id"] for d in estate.get("datasets") or []}
    for r in estate.get("reports") or []:
        if r["id"] in ids:
            out.append(f"{r['id']}: two objects share this id")
        ids.add(r["id"])
        if r.get("dataset") and r["dataset"] not in ds:
            out.append(f"{r['name']}: points to dataset {r['dataset']}, which was not read")
        for q in r.get("queries") or []:
            names = [it["name"] for it in q.get("items") or []]
            for n in sorted({n for n in names if names.count(n) > 1}):
                out.append(f"{r['name']}: data item '{n}' is defined twice in {q.get('name')}")
    for r in estate.get("reports") or []:
        if r.get("base") and r["base"] not in ids:
            out.append(f"{r['name']}: a report view whose base report {r['base']} is not in the estate")
    return out


# ------------------------------------------------------------------ on disk

def save(path: Path, estate: dict) -> None:
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(estate, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


INVENTORY_COLUMNS = ["id", "name", "type", "folder", "owner", "dataset", "runs_365", "runs_90", "last_run_days", "last_used", "failed_days",
                     "complexity", "calculations", "pages", "visuals", "prompts", "features", "shared", "personal"]


def inventory_rows(estate: dict, predictions: dict | None = None) -> list[dict]:
    """One row per object, in the tool's own terms, for the table and the CSV export."""
    ds = {d["id"]: d["name"] for d in estate["datasets"]}
    out = []
    for r in estate["reports"]:
        u = r["usage"]
        row = {"id": r["id"], "name": r["name"], "type": r["type"], "folder": r["folder"], "owner": r.get("owner") or "",
               "dataset": ds.get(r.get("dataset")) or (f"missing: {r['missing_dataset']}" if r.get("missing_dataset") else ""),
               "runs_365": u.get("runs_365", 0), "runs_90": u.get("runs_90", 0), "last_run_days": u.get("last_run_days"),
               "last_used": last_used_bucket(r), "failed_days": u.get("failed_days"), "complexity": r["complexity"],
               "calculations": r["calculations"], "pages": len(r.get("pages") or []),
               "visuals": sum(len(p.get("visuals") or []) for p in r.get("pages") or []), "prompts": len(r.get("prompts") or []),
               "features": "; ".join(r.get("features") or []), "shared": r.get("shared"), "personal": r.get("personal")}
        if predictions and r["id"] in predictions:
            p = predictions[r["id"]]
            row.update(convert=p["convert"], confidence=p["confidence"], no_rule=p["no_rule"], reason=p["reason"])
        out.append(row)
    return out


def inventory_csv(estate: dict, predictions: dict | None = None) -> str:
    rows = inventory_rows(estate, predictions)
    cols = INVENTORY_COLUMNS + (["convert", "confidence", "no_rule", "reason"] if predictions else [])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return buf.getvalue()
