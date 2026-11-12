"""IBM Cognos Analytics readers.

CognosExports reads what a Cognos administrator can hand over without a server connection: a deployment archive
(.zip) or an export folder holding

    manifest.json        product, version, namespace, when it was exported (optional)
    content.csv          the content store listing: id, path, name, type, owner, created, modified, base, dataset, shared
    specs/<id>.xml       report specifications (reports; a report view points to its base report in content.csv)
    specs/<id>.json      dashboard and story specifications
    datasets/<id>.json   packages and data modules: query subjects and items, relationships, the files behind them
    audit.csv            the Audit database export (COGIPF_RUNREPORT): timestamp, report path, user, status, run time
    data/*.csv           optional: the tables behind the packages (the sample estate ships them; a client extracts them)

Report specifications are read with the namespaces Cognos has used over the years (report/8.x ... 16.x); the reader
looks at local names, so an archive mixing versions is fine. Objects are read page by page with a progress callback
and a pause hook, and a cursor lets a scan resume from the same page after a restart.

CognosRest is the thin client for a live server (Cognos Analytics 11.1+ REST API): it signs in, lists the content
store, downloads specifications and the audit rows into the same export layout, then CognosExports reads them - one
code path for both. It backs off on HTTP 429 (Retry-After) and reports every wait plainly.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .. import expr, model

READS = ["Reports", "Report views", "Dashboards", "Stories", "Data modules", "Packages", "usage from the Audit database"]
TYPES = {"report": "Report", "reportview": "Report view", "report view": "Report view", "dashboard": "Dashboard", "story": "Story",
         "package": "Package", "module": "Data module", "data module": "Data module", "datamodule": "Data module", "folder": "Folder"}
CHART_KINDS = {"v2_combinationchart": "column", "combinationchart": "column", "v2_linechart": "line", "v2_piechart": "pie", "piechart": "pie",
               "v2_gaugechart": "gauge", "gaugechart": "gauge", "v2_mapchart": "map", "mapchart": "map", "v2_scatterchart": "scatter",
               "v2_bubblechart": "scatter", "v2_bulletchart": "gauge", "v2_areachart": "line", "v2_barchart": "bar",
               "v2_progressivechart": "column", "v2_paretochart": "column", "v2_treemap": "treemap", "v2_heatmap": "heatmap"}
WIDGET_KINDS = {"column": "column", "bar": "bar", "line": "line", "pie": "pie", "donut": "pie", "kpi": "kpi", "summary": "kpi", "list": "list",
                "table": "list", "crosstab": "crosstab", "map": "map", "text": "text", "gauge": "gauge", "area": "line", "scatter": "scatter"}


class ReadError(Exception):
    pass


class Stopped(Exception):
    """The person stopped the scan; what was read so far is kept (in the estate passed in) and `cursor` says where."""

    def __init__(self, text: str, cursor: dict | None = None):
        super().__init__(text)
        self.cursor = cursor


class SignInAgain(ReadError):
    pass


def _local(el) -> str:
    return el.tag.split("}")[-1].lower() if isinstance(el.tag, str) else ""


def _find(el, name: str):
    name = name.lower()
    for x in el.iter():
        if _local(x) == name:
            return x
    return None


def _findall(el, name: str) -> list:
    name = name.lower()
    return [x for x in el.iter() if _local(x) == name]


def _children(el, name: str) -> list:
    return [x for x in el if _local(x) == name.lower()]


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _days(ts: str | None, as_of: dt.date) -> int | None:
    if not ts:
        return None
    try:
        d = dt.date.fromisoformat(str(ts)[:10])
    except ValueError:
        return None
    return (as_of - d).days


# ------------------------------------------------------------------ specifications

def parse_report_spec(xml_text: str) -> dict:
    """A Cognos report specification (XML) -> queries, prompts, pages / visuals, features, model path."""
    try:
        root = ET.fromstring(xml_text.lstrip("﻿"))
    except ET.ParseError as e:
        raise ReadError(f"the report specification is not well-formed XML ({e})")
    out: dict = {"model_path": _text(_find(root, "modelPath")), "name": _text(_find(root, "reportName")), "queries": [], "prompts": [],
                 "pages": [], "features": []}
    if _local(root) == "activereport" or _find(root, "activeReport") is not None or root.get("activeReport") == "true":
        out["features"].append("active report")
    m = re.search(r"(?:package|module)\[@name='([^']+)'\]", out["model_path"])
    out["dataset_name"] = m.group(1) if m else None
    out["dataset_kind"] = "data module" if "module[" in out["model_path"] else "package"
    for q in _findall(root, "query"):
        items, filters = [], []
        for di in _findall(q, "dataItem"):
            name = di.get("name") or ""
            ex = _text(_find(di, "expression"))
            agg = (di.get("aggregate") or "").lower() or None
            if agg in ("none", "automatic", ""):
                agg = None
            kind = "attribute"
            if agg or re.search(r"\b(total|sum|average|count|minimum|maximum|percentage|running-|moving-|rank|percentile)\s*\(", ex, re.I):
                kind = "measure"
            elif not model._plain_ref(ex):
                kind = "calculation"
            items.append({"name": name, "expression": ex, "aggregate": agg, "kind": kind})
        for f in _findall(q, "detailFilter"):
            filters.append({"expression": _text(_find(f, "filterExpression")), "kind": "detail"})
        for f in _findall(q, "summaryFilter"):
            filters.append({"expression": _text(_find(f, "filterExpression")), "kind": "summary"})
        out["queries"].append({"name": q.get("name") or f"Query{len(out['queries']) + 1}", "items": items, "filters": filters})
    item_kind = {it["name"]: it["kind"] for q in out["queries"] for it in q["items"]}
    pages_root = _find(root, "reportPages")
    for page in (_children(pages_root, "page") if pages_root is not None else []):
        visuals = []
        for el in page.iter():
            tag = _local(el)
            v = None
            if tag == "list":
                cols = [x.get("refDataItem") for x in _findall(el, "dataItemValue") if x.get("refDataItem")]
                v = model.visual(el.get("name") or f"List{len(visuals) + 1}", "list", el.get("refQuery"), el.get("name"),
                                 columns=list(dict.fromkeys(cols)), measures=[c for c in dict.fromkeys(cols) if item_kind.get(c) == "measure"])
            elif tag == "crosstab":
                rows = [x.get("refDataItem") for x in _findall(_find(el, "crosstabRows") or el, "crosstabNodeMember") if x.get("refDataItem")]
                cols = [x.get("refDataItem") for x in _findall(_find(el, "crosstabColumns") or ET.Element("x"), "crosstabNodeMember") if x.get("refDataItem")]
                measures = [x.get("refDataItem") for x in _findall(el, "defaultMeasure")] + [c for c in rows + cols if item_kind.get(c) == "measure"]
                rows = [r for r in rows if item_kind.get(r) != "measure"]
                cols = [c for c in cols if item_kind.get(c) != "measure"]
                v = model.visual(el.get("name") or f"Crosstab{len(visuals) + 1}", "crosstab", el.get("refQuery"), el.get("name"),
                                 category=rows[0] if rows else None, series=cols[0] if cols else None, rows=rows, columns=cols,
                                 measures=list(dict.fromkeys(m for m in measures if m)))
            elif tag in CHART_KINDS:
                kind = CHART_KINDS[tag]
                if tag in ("v2_combinationchart", "combinationchart"):
                    has_bar = bool(_findall(el, "v2_combinationTypeBar") or _findall(el, "combinationTypeBar"))
                    has_line = bool(_findall(el, "v2_combinationTypeLine") or _findall(el, "combinationTypeLine"))
                    if has_line and not has_bar:
                        kind = "line"
                    elif (el.get("orientation") or "").lower() == "horizontal":
                        kind = "bar"
                measures = [x.get("refDataItem") for x in el.iter() if _local(x).endswith("typemeasure") and x.get("refDataItem")]
                cats = [x.get("refDataItem") for x in el.iter() if _local(x) in ("v2_categorynodemember", "v2_pienodemember", "v2_gaugenodemember",
                                                                                    "categorynodemember", "v2_mapnodemember") and x.get("refDataItem")]
                series = [x.get("refDataItem") for x in el.iter() if _local(x) in ("v2_seriesnodemember", "seriesnodemember") and x.get("refDataItem")]
                v = model.visual(el.get("name") or f"Chart{len(visuals) + 1}", kind, el.get("refQuery"), el.get("name"),
                                 category=cats[0] if cats else None, series=series[0] if series else None, measures=list(dict.fromkeys(measures)))
            elif tag == "singleton":
                vals = [x.get("refDataItem") for x in _findall(el, "dataItemValue") if x.get("refDataItem")]
                v = model.visual(el.get("name") or f"Singleton{len(visuals) + 1}", "kpi", el.get("refQuery"), el.get("name"), measures=list(dict.fromkeys(vals)))
            elif tag == "htmlitem":
                v = model.visual(el.get("name") or f"HTML{len(visuals) + 1}", "html", None, "HTML item")
                out["features"].append("custom javascript" if "<script" in _text(el).lower() else "HTML item")
            elif tag == "repeatertable":
                v = model.visual(el.get("name") or f"Repeater{len(visuals) + 1}", "repeater", el.get("refQuery"), el.get("name"))
            if v is not None:
                visuals.append(v)
        out["pages"].append({"name": page.get("name") or f"Page{len(out['pages']) + 1}", "visuals": visuals})
    prompt_pages = _find(root, "promptPages")
    for el in (prompt_pages.iter() if prompt_pages is not None else []):
        tag = _local(el)
        if tag in ("valueprompt", "textbox", "datetimeprompt", "dateprompt", "selectvalueprompt", "intervalprompt"):
            use = _find(el, "useItem")
            ptype = "range" if (el.get("range") or "").lower() == "true" or tag in ("datetimeprompt", "dateprompt", "intervalprompt") else \
                "multi" if (el.get("multiSelect") or "").lower() == "true" else "value"
            out["prompts"].append({"name": el.get("parameter") or el.get("name") or f"p{len(out['prompts']) + 1}", "item": use.get("refDataItem") if use is not None else None,
                                   "query": el.get("refQuery"), "type": ptype})
    known = {p["name"] for p in out["prompts"]}
    for q in out["queries"]:
        for f in q["filters"]:
            for name in re.findall(r"\?([A-Za-z_][\w ]*)\?", f["expression"]):
                if name not in known:
                    known.add(name)
                    out["prompts"].append({"name": name, "item": None, "query": q["name"], "type": "value"})
    out["features"] = list(dict.fromkeys(out["features"]))
    return out


def parse_dashboard_spec(text: str) -> dict:
    """A dashboard or story specification (JSON) -> the same shape as a report: one page per tab / scene, one visual per
    widget, one query per data source with the items the widgets use."""
    try:
        spec = json.loads(text.lstrip("﻿"))
    except ValueError as e:
        raise ReadError(f"the dashboard specification is not valid JSON ({e})")
    sources = {s.get("id"): s for s in spec.get("dataSources") or []}
    first = next(iter(sources.values()), {})
    out: dict = {"model_path": "", "name": spec.get("name") or "", "queries": [], "prompts": [], "pages": [], "features": [],
                 "dataset_name": first.get("name"), "dataset_kind": "data module" if (first.get("type") or "module") == "module" else "package"}
    queries: dict[str, dict] = {}
    for tab in spec.get("tabs") or spec.get("scenes") or []:
        visuals = []
        for w in tab.get("widgets") or []:
            ds = sources.get(w.get("dataSource")) or first
            qname = f"Q {ds.get('name') or 'data'}"
            q = queries.setdefault(qname, {"name": qname, "items": [], "filters": []})
            have = {it["name"] for it in q["items"]}
            cats = []
            for cname in w.get("categories") or []:
                ref = (w.get("itemPaths") or {}).get(cname) or cname
                if cname not in have:
                    kind = "attribute" if model._plain_ref(ref) else "calculation"
                    q["items"].append({"name": cname, "expression": ref if (ref.startswith("[") or kind == "calculation") else f"[{cname}]", "aggregate": None, "kind": kind}); have.add(cname)
                cats.append(cname)
            measures = []
            for val in w.get("values") or []:
                label = val.get("label") or val.get("item")
                if val.get("expression"):                       # a calculation written in the widget
                    if label not in have:
                        q["items"].append({"name": label, "expression": val["expression"], "aggregate": None, "kind": "measure"}); have.add(label)
                    measures.append(label)
                    continue
                ref = val.get("path") or f"[{val.get('item')}]"
                agg = {"sum": "total", "avg": "average", "average": "average", "count": "count", "min": "minimum", "max": "maximum", "countDistinct": "count distinct"}.get(val.get("aggregate") or "sum", "total")
                if label not in have:
                    q["items"].append({"name": label, "expression": f"{agg}({ref})", "aggregate": agg.split()[0], "kind": "measure"}); have.add(label)
                measures.append(label)
            for f in w.get("filters") or []:
                q["filters"].append({"expression": f, "kind": "detail"})
            kind = WIDGET_KINDS.get((w.get("type") or "").lower(), "custom")
            series = (w.get("series") or [None])[0] if isinstance(w.get("series"), list) else w.get("series")
            if series and series not in have:
                q["items"].append({"name": series, "expression": f"[{series}]", "aggregate": None, "kind": "attribute"}); have.add(series)
            visuals.append(model.visual(w.get("id") or f"w{len(visuals) + 1}", kind, qname, w.get("title"), category=cats[0] if cats else None,
                                        series=series, measures=measures, columns=cats + measures))
            if kind == "custom":
                out["features"].append(f"widget {w.get('type')}")
        out["pages"].append({"name": tab.get("title") or f"Tab {len(out['pages']) + 1}", "visuals": visuals})
    out["queries"] = list(queries.values())
    out["features"] = list(dict.fromkeys(out["features"]))
    return out


def parse_dataset_spec(text: str) -> dict:
    """A package or data module listing (JSON): query subjects with their items, relationships and data files."""
    try:
        spec = json.loads(text.lstrip("﻿"))
    except ValueError as e:
        raise ReadError(f"the package / module specification is not valid JSON ({e})")
    tables = []
    for qs in spec.get("tables") or spec.get("querySubject") or []:
        cols = []
        for c in qs.get("columns") or qs.get("queryItem") or []:
            t = (c.get("type") or c.get("datatype") or "string").lower()
            t = {"integer": "int", "int64": "int", "float": "decimal", "double": "decimal", "number": "decimal", "decimal": "decimal", "date": "date",
                 "datetime": "date", "boolean": "bool", "text": "string", "string": "string", "varchar": "string", "int": "int"}.get(t, "string")
            role = c.get("role") or ("measure" if (c.get("usage") or "").lower() == "fact" else "attribute" if c.get("usage") else None)
            cols.append(model.column(c.get("name") or c.get("label"), t, role))
        tables.append(model.new_table(qs.get("name") or qs.get("label"), cols, qs.get("file"), qs.get("role") or "dimension", qs.get("key")))
    rels = [{"from": r["from"], "to": r["to"]} if isinstance(r, dict) and "from" in r else
            {"from": f"{r['left']}[{r['leftKey']}]", "to": f"{r['right']}[{r['rightKey']}]"} for r in spec.get("relationships") or spec.get("relationship") or []]
    kind = (spec.get("kind") or spec.get("type") or "package").lower()
    return {"id": spec.get("id"), "name": spec.get("name") or spec.get("label"), "kind": "data module" if "module" in kind else "package",
            "folder": spec.get("folder"), "tables": tables, "relationships": rels}


# ------------------------------------------------------------------ the export reader

class CognosExports:
    PHASES = ["packages", "data modules", "dashboards", "reports", "report views", "stories", "usage", "dependencies"]

    def __init__(self, root: str | Path, page_size: int = 100, version: str = ""):
        root = Path(root)
        self.tmp = None
        if root.is_file() and root.suffix.lower() == ".zip":
            self.tmp = Path(tempfile.mkdtemp(prefix="cognos-export-"))
            with zipfile.ZipFile(root) as z:
                for info in z.infolist():                # never outside the folder
                    name = info.filename.replace("\\", "/")
                    if name.startswith("/") or ".." in name.split("/"):
                        continue
                    z.extract(info, self.tmp)
            root = self.tmp
            inner = [p for p in root.iterdir() if p.is_dir()]
            if not (root / "content.csv").exists() and len(inner) == 1 and (inner[0] / "content.csv").exists():
                root = inner[0]
        if not root.is_dir():
            raise ReadError(f"{root} is not an export folder or a deployment archive")
        self.root = root
        self.page_size = max(1, page_size)
        self.version = version
        self.manifest = {}
        if (root / "manifest.json").exists():
            try:
                self.manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
            except ValueError:
                self.manifest = {}

    def close(self) -> None:
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- the listing
    def listing(self) -> list[dict]:
        path = self.root / "content.csv"
        if not path.exists():
            # no listing: every specification file is an object
            rows = []
            for f in sorted((self.root / "specs").glob("*")) if (self.root / "specs").is_dir() else []:
                rows.append({"id": f.stem, "path": f"Team content/{f.stem}", "name": f.stem, "type": "Dashboard" if f.suffix == ".json" else "Report",
                             "owner": "", "created": "", "modified": "", "base": "", "dataset": "", "shared": "true"})
            return rows
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = [dict(r) for r in csv.DictReader(fh)]
        for r in rows:
            r["type"] = TYPES.get((r.get("type") or "").strip().lower(), (r.get("type") or "Report").strip() or "Report")
            r["path"] = (r.get("path") or "").strip() or f"Team content/{r.get('name')}"
            r["name"] = (r.get("name") or "").strip() or r["path"].rsplit("/", 1)[-1]
        return rows

    def test(self) -> dict:
        rows = self.listing()
        folders = {r["path"].rsplit("/", 1)[0] for r in rows if r["type"] != "Folder"} | {r["path"] for r in rows if r["type"] == "Folder"}
        audit = self.root / "audit.csv"
        days = None
        if audit.exists():
            with open(audit, encoding="utf-8-sig", newline="") as fh:
                stamps = [row.get("COGIPF_LOCALTIMESTAMP") or row.get("timestamp") or "" for row in csv.DictReader(fh)]
            stamps = sorted(s[:10] for s in stamps if s)
            if stamps:
                days = (dt.date.fromisoformat(stamps[-1]) - dt.date.fromisoformat(stamps[0])).days + 1
        return {"ok": True, "product": self.manifest.get("product", "IBM Cognos Analytics"), "version": self.manifest.get("version") or self.version or "unknown",
                "namespace": self.manifest.get("namespace"), "team_folders": sum(1 for f in folders if not f.startswith("My content")),
                "personal_folders": sum(1 for f in folders if f.startswith("My content")), "users": self.manifest.get("users"),
                "objects": sum(1 for r in rows if r["type"] != "Folder"), "usage_source": "Audit database export" if audit.exists() else None,
                "usage_days": days, "permissions": "Read content, read audit - no write access (an export cannot write)",
                "data_files": len(list((self.root / "data").glob("*.csv"))) if (self.root / "data").is_dir() else 0,
                "estimate_seconds": max(2, round(len(rows) / 60))}

    # ---- reading
    def read(self, progress=None, pause=None, cursor: dict | None = None, estate: dict | None = None) -> dict:
        """progress(event) is called after every page; pause() may block and returns False to stop; cursor
        {phase, page} and the partial estate let a scan resume where it stopped."""
        t0 = time.time()
        progress = progress or (lambda e: None)
        pause = pause or (lambda: True)
        rows = self.listing()
        est = estate or model.new_estate("cognos", self.manifest.get("version") or self.version, "exports")
        est.setdefault("problems", [])
        est["source"]["version"] = self.manifest.get("version") or self.version or est["source"].get("version")
        done_phase = {c["phase"]: c["page"] for c in [cursor]} if cursor else {}
        start_phase = self.PHASES.index(cursor["phase"]) if cursor and cursor.get("phase") in self.PHASES else 0
        by_type = lambda t: [r for r in rows if r["type"] == t]  # noqa: E731
        groups = {"packages": by_type("Package"), "data modules": by_type("Data module"), "dashboards": by_type("Dashboard"),
                  "reports": by_type("Report"), "report views": by_type("Report view"), "stories": by_type("Story")}
        have_ds = {d["id"] for d in est["datasets"]}
        have_r = {r["id"] for r in est["reports"]}
        names_ds: dict[str, dict] = {}

        def step(phase, items, fn):
            pages = max(1, -(-len(items) // self.page_size))
            first = done_phase.get(phase, 0) if self.PHASES.index(phase) == start_phase else 0
            for p in range(first, pages):
                chunk = items[p * self.page_size:(p + 1) * self.page_size]
                for row in chunk:
                    try:
                        fn(row)
                    except ReadError as e:
                        est["problems"].append(f"{row.get('name') or row.get('id')}: {e}")
                found = self._found(est)
                progress({"phase": phase, "page": p + 1, "pages": pages, "found": found, "cursor": {"phase": phase, "page": p + 1},
                          "text": f"reading {phase} - page {p + 1} of {pages}" if pages > 1 else f"reading {phase} - 1 page",
                          "pct": self._pct(phase, p + 1, pages, groups)})
                if not pause():
                    raise Stopped(f"stopped while reading {phase}, page {p + 1} of {pages}", {"phase": phase, "page": p + 1})

        def add_dataset(row):
            if row["id"] in have_ds:
                return
            spec_path = self.root / "datasets" / f"{row['id']}.json"
            if spec_path.exists():
                spec = parse_dataset_spec(spec_path.read_text(encoding="utf-8"))
            else:
                spec = {"name": row["name"], "kind": row["type"].lower(), "tables": [], "relationships": [], "folder": None}
            d = model.new_dataset(row["id"], spec.get("name") or row["name"], "data module" if row["type"] == "Data module" else "package",
                                  spec["tables"], spec["relationships"], spec.get("folder") or row["path"].rsplit("/", 1)[0])
            files = [t.get("file") for t in d["tables"] if t.get("file")]
            d["has_data"] = bool(files) and all((self.root / "data" / f).is_file() for f in files)
            d["owner"] = row.get("owner") or None
            est["datasets"].append(d)
            have_ds.add(d["id"])

        def add_report(row, kind: str):
            if row["id"] in have_r:
                return
            folder = row["path"].rsplit("/", 1)[0]
            r = model.new_report(row["id"], row["name"], row["type"], folder, row.get("owner") or None, None, created=row.get("created") or None,
                                 modified=row.get("modified") or None, shared=(row.get("shared") or "").lower() not in ("false", "0", "no"))
            r["personal"] = folder.startswith("My content")
            if kind == "view":
                r["base"] = (row.get("base") or "").strip() or None
                r["spec_file"] = None
            else:
                ext = "json" if kind in ("dashboard", "story") else "xml"
                f = self.root / "specs" / f"{row['id']}.{ext}"
                if not f.exists():
                    f = next(iter((self.root / "specs").glob(f"{row['id']}.*")), f) if (self.root / "specs").is_dir() else f
                if f.exists():
                    r["spec_file"] = f"specs/{f.name}"
                    try:
                        spec = parse_dashboard_spec(f.read_text(encoding="utf-8")) if f.suffix.lower() == ".json" else parse_report_spec(f.read_text(encoding="utf-8"))
                    except ReadError as e:            # the object stays in the inventory, without its content
                        est["problems"].append(f"{row['name']}: {e}")
                        r["features"].append("specification could not be read")
                        spec = {"queries": [], "prompts": [], "pages": [], "features": r["features"], "dataset_name": row.get("dataset") or None}
                    r.update(queries=spec["queries"], prompts=spec["prompts"], pages=spec["pages"], features=spec["features"])
                    if spec.get("name"):
                        r["name"] = r["name"] or spec["name"]
                    r["_dataset_name"] = spec.get("dataset_name") or (row.get("dataset") or None)
                else:
                    est["problems"].append(f"{row['name']}: no specification file for {row['id']}")
                    r["_dataset_name"] = row.get("dataset") or None
            est["reports"].append(r)
            have_r.add(r["id"])

        for phase in self.PHASES[start_phase:]:
            if phase in ("packages", "data modules"):
                step(phase, groups[phase], add_dataset)
                names_ds = {d["name"].lower(): d for d in est["datasets"]}
            elif phase in ("dashboards", "reports", "stories"):
                step(phase, groups[phase], lambda row, k=phase[:-1]: add_report(row, k))
            elif phase == "report views":
                step(phase, groups[phase], lambda row: add_report(row, "view"))
            elif phase == "usage":
                self._usage(est, progress)
                if not pause():
                    raise Stopped("stopped after reading the usage")
            elif phase == "dependencies":
                names_ds = {d["name"].lower(): d for d in est["datasets"]}        # also after a resume that skipped the dataset phases
                self._dependencies(est, names_ds, progress)
        est["read_seconds"] = round((est.get("read_seconds") or 0) + time.time() - t0, 1)
        est["read_at"] = time.time()
        model.finish(est)
        est["problems"] = list(dict.fromkeys(est["problems"] + model.validate(est)))
        progress({"phase": "done", "page": 1, "pages": 1, "found": self._found(est), "cursor": None, "pct": 100,
                  "text": f"scan complete - {len(est['reports']):,} objects in {est['read_seconds']} s"})
        return est

    def _found(self, est: dict) -> dict:
        out: dict = {}
        for r in est["reports"]:
            key = r["type"][:-1] + "ies" if r["type"].endswith("y") else r["type"] + "s"
            out[key] = out.get(key, 0) + 1
        out["Data modules"] = sum(1 for d in est["datasets"] if d["kind"] == "data module")
        out["Packages"] = sum(1 for d in est["datasets"] if d["kind"] == "package")
        return out

    def _pct(self, phase: str, page: int, pages: int, groups: dict) -> int:
        weights = {"packages": 4, "data modules": 4, "dashboards": 6, "reports": 50, "report views": 6, "stories": 2, "usage": 18, "dependencies": 10}
        done = sum(weights[p] for p in self.PHASES[:self.PHASES.index(phase)])
        return min(99, round(done + weights[phase] * page / max(1, pages)))

    def _usage(self, est: dict, progress) -> None:
        audit = self.root / "audit.csv"
        est["usage"] = {"source": "Audit database export" if audit.exists() else None, "from": None, "to": None, "runs": 0, "days": 0}
        if not audit.exists():
            progress({"phase": "usage", "page": 1, "pages": 1, "text": "no Audit database export in the archive - usage unknown", "level": "warn", "pct": 80})
            return
        by_path: dict[str, dict] = {}
        n, lo, hi = 0, None, None
        with open(audit, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                ts = (row.get("COGIPF_LOCALTIMESTAMP") or row.get("timestamp") or "")[:10]
                path = (row.get("COGIPF_REPORTPATH") or row.get("path") or "").strip()
                if not ts or not path:
                    continue
                n += 1
                lo = ts if lo is None or ts < lo else lo
                hi = ts if hi is None or ts > hi else hi
                u = by_path.setdefault(path, {"runs": [], "users": set(), "failed": []})
                u["runs"].append(ts)
                if row.get("COGIPF_USERNAME") or row.get("user"):
                    u["users"].add(row.get("COGIPF_USERNAME") or row.get("user"))
                st = (row.get("COGIPF_STATUS") or row.get("status") or "").lower()
                if st and st not in ("success", "succeeded", "ok", "0"):
                    u["failed"].append(ts)
        as_of = dt.date.fromisoformat(self.manifest.get("as_of", hi)[:10]) if (self.manifest.get("as_of") or hi) else dt.date.today()
        est["usage"].update({"from": lo, "to": hi, "runs": n, "days": ((dt.date.fromisoformat(hi) - dt.date.fromisoformat(lo)).days + 1) if lo and hi else 0,
                             "as_of": as_of.isoformat()})
        paths = {r["folder"] + "/" + r["name"]: r for r in est["reports"]}
        ids = {r["id"]: r for r in est["reports"]}
        for path, u in by_path.items():
            r = paths.get(path) or ids.get(path)
            if not r:
                continue
            days = sorted(_days(t, as_of) for t in u["runs"])
            days = [d for d in days if d is not None]
            r["usage"] = {"runs_365": sum(1 for d in days if d <= 365), "runs_90": sum(1 for d in days if d <= 90),
                          "last_run_days": days[0] if days else None, "users": len(u["users"]),
                          "failed_days": min((d for d in (_days(t, as_of) for t in u["failed"]) if d is not None), default=None)}
        progress({"phase": "usage", "page": 1, "pages": 1, "pct": 86, "found": self._found(est),
                  "text": f"{est['usage']['days']} days of the Audit database read - {n:,} runs; "
                          f"{sum(1 for r in est['reports'] if r['usage']['last_run_days'] is not None and r['usage']['last_run_days'] <= 90):,} objects used in 90 days, "
                          f"{sum(1 for r in est['reports'] if r['usage']['last_run_days'] is None):,} never run"})

    def _dependencies(self, est: dict, names_ds: dict, progress) -> None:
        ids = {r["id"]: r for r in est["reports"]}
        missing = 0
        for r in est["reports"]:
            name = r.pop("_dataset_name", None)
            if r.get("base"):
                base = ids.get(r["base"])
                if base:
                    r.update(queries=base["queries"], prompts=base["prompts"], pages=base["pages"], features=list(base["features"]),
                             dataset=base.get("dataset"), missing_dataset=base.get("missing_dataset"))
                    r["dependencies"] = [base["id"]] + ([base["dataset"]] if base.get("dataset") else [])
                else:
                    r["missing_dataset"] = None
                    r["dependencies"] = []
                continue
            d = names_ds.get((name or "").lower()) if name else None
            if d:
                r["dataset"] = d["id"]
                r["dependencies"] = [d["id"]]
            elif name:
                r["missing_dataset"] = name
                missing += 1
        shared = {d["id"] for r in est["reports"] for d in est["datasets"] if d["id"] == r.get("dataset")}
        progress({"phase": "dependencies", "page": 1, "pages": 1, "pct": 96, "found": self._found(est),
                  "text": f"linking {len(est['reports']):,} objects to {sum(1 for d in est['datasets'] if d['kind'] == 'package')} packages and "
                          f"{sum(1 for d in est['datasets'] if d['kind'] == 'data module')} data modules - {len(shared)} shared objects in use"
                          + (f"; {missing} reports point to missing packages" if missing else "")})


# ------------------------------------------------------------------ the live server (thin client)

class CognosRest:
    """Signs in, lists the content store, downloads specifications and audit rows into an export folder, then
    CognosExports reads that folder. Every wait (HTTP 429, Retry-After) is reported through `progress` in plain words."""

    def __init__(self, base_url: str, user: str = "", secret: str = "", namespace: str = "", page_size: int = 100, max_rps: float = 4,
                 sleep=time.sleep, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.user, self.secret, self.namespace = user, secret, namespace
        self.page_size, self.min_gap, self.sleep, self.timeout = max(1, page_size), 1.0 / max(0.1, max_rps), sleep, timeout
        self.token = None
        self.calls = self.retries = 0
        self.waits: list[float] = []
        self.problems: list[str] = []
        self._last = 0.0
        self.progress = lambda e: None

    def _req(self, method: str, path: str, body: dict | None = None, raw: bool = False, attempts: int = 6):
        gap = self.min_gap - (time.monotonic() - self._last)
        if gap > 0:
            self.sleep(gap)
        self._last = time.monotonic()
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "application/json, application/xml, text/xml"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["IBM-BA-Authorization"] = self.token
        for attempt in range(attempts):
            self.calls += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=self.timeout) as r:
                    payload = r.read()
                    return payload if raw else (json.loads(payload) if payload.strip() else {})
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise SignInAgain("The server did not accept the sign-in (HTTP 401): check the user, password or API key, then sign in again.")
                if e.code == 403:
                    raise ReadError(f"No permission for {path} (HTTP 403): the service account needs read access to the content store.")
                if e.code == 404:
                    raise ReadError(f"{path} is not there (HTTP 404)")
                if e.code == 429 or 500 <= e.code < 600:
                    wait = float(e.headers.get("Retry-After") or (2 * (attempt + 1)))
                    wait = min(wait, 60)
                    self.retries += 1
                    self.waits.append(wait)
                    self.progress({"phase": "wait", "level": "warn", "text": (f"server asked to slow down (HTTP 429) - waiting {wait:g} s, then continuing"
                                                                              if e.code == 429 else f"server error (HTTP {e.code}) - trying again in {wait:g} s")})
                    self.sleep(wait)
                    continue
                raise ReadError(f"HTTP {e.code} from {path}")
            except urllib.error.URLError as e:
                raise ReadError(f"Cannot reach {self.base}: {e.reason}")
        raise ReadError(f"{path}: the server kept refusing after {attempts} attempts")

    def sign_in(self) -> dict:
        params = [{"name": "CAMNamespace", "value": self.namespace}, {"name": "CAMUsername", "value": self.user}, {"name": "CAMPassword", "value": self.secret}]
        if not self.user:
            params = [{"name": "CAMAPILoginKey", "value": self.secret}]
        out = self._req("PUT", "/api/v1/session", {"parameters": params})
        self.token = out.get("session_key") or out.get("sessionKey") or "Bearer " + (out.get("token") or "")
        return out

    def test(self) -> dict:
        info = self.sign_in()
        session = self._req("GET", "/api/v1/session")
        folders = self._req("GET", "/api/v1/content/team_folders/items?limit=1")
        audit = self._req("GET", "/api/v1/audit/summary")
        return {"ok": True, "product": session.get("product") or "IBM Cognos Analytics", "version": session.get("version") or info.get("version") or "unknown",
                "namespace": self.namespace or session.get("namespace"), "team_folders": folders.get("total_folders") or folders.get("folders"),
                "personal_folders": folders.get("personal_folders"), "users": session.get("users"), "objects": folders.get("total_objects") or folders.get("objects"),
                "usage_source": f"Audit database - {audit.get('days')} days available" if audit.get("days") else None, "usage_days": audit.get("days"),
                "permissions": session.get("permissions") or "Read content, read audit", "estimate_seconds": max(5, round((folders.get("total_objects") or 100) / 6))}

    def download(self, dest: Path, progress=None, pause=None, scope: dict | None = None) -> Path:
        """Everything the export reader needs, written as files under `dest` - so the same reader runs on it."""
        self.progress = progress or (lambda e: None)
        pause = pause or (lambda: True)
        scope = scope or {}
        dest = Path(dest)
        for sub in ("specs", "datasets"):
            (dest / sub).mkdir(parents=True, exist_ok=True)
        if not self.token:
            self.sign_in()
        session = self._req("GET", "/api/v1/session")
        objects: list[dict] = []
        roots = ["team_folders"] + (["my_folders"] if scope.get("personal", True) else [])
        for root in roots:
            offset, page = 0, 0
            while True:
                page += 1
                out = self._req("GET", f"/api/v1/content/{root}/items?limit={self.page_size}&offset={offset}&recursive=true")
                items = out.get("items") or []
                objects += items
                total = out.get("total") or len(objects)
                self.progress({"phase": "listing", "page": page, "pages": max(1, -(-total // self.page_size)), "pct": min(10, page),
                               "text": f"listing the content store ({root.replace('_', ' ')}) - page {page} of {max(1, -(-total // self.page_size))}"})
                if not pause():
                    raise Stopped("stopped while listing the content store")
                if len(items) < self.page_size:
                    break
                offset += self.page_size
        with open(dest / "content.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["id", "path", "name", "type", "owner", "created", "modified", "base", "dataset", "shared"], lineterminator="\n")
            w.writeheader()
            for o in objects:
                w.writerow({"id": o.get("id"), "path": o.get("path") or f"Team content/{o.get('defaultName')}", "name": o.get("defaultName") or o.get("name"),
                            "type": o.get("type"), "owner": o.get("owner"), "created": o.get("creationTime"), "modified": o.get("modificationTime"),
                            "base": o.get("base") or "", "dataset": o.get("dataset") or "", "shared": "false" if (o.get("path") or "").startswith("My content") and not o.get("shared") else "true"})
        kinds = {"report": ("reports", "xml"), "dashboard": ("dashboards", "json"), "story": ("stories", "json"), "module": ("modules", "json"), "package": ("packages", "json")}
        by_kind: dict[str, list] = {}
        for o in objects:
            t = (o.get("type") or "").lower()
            if t in kinds and (scope.get("types") is None or t in scope["types"]):
                by_kind.setdefault(t, []).append(o)
        for t, (api, ext) in kinds.items():
            items = by_kind.get(t) or []
            pages = max(1, -(-len(items) // self.page_size))
            for p in range(pages):
                for o in items[p * self.page_size:(p + 1) * self.page_size]:
                    sub = "datasets" if t in ("module", "package") else "specs"
                    try:
                        payload = self._req("GET", f"/api/v1/{api}/{o['id']}/specification", raw=True)
                    except ReadError as e:               # one object without a specification never stops the scan
                        self.problems.append(f"{o.get('defaultName') or o['id']}: {e}")
                        continue
                    (dest / sub / f"{o['id']}.{ext}").write_bytes(payload)
                self.progress({"phase": api if api != "modules" else "data modules", "page": p + 1, "pages": pages, "pct": 10 + round(60 * (list(kinds).index(t) + (p + 1) / pages) / len(kinds)),
                               "text": f"reading {api.replace('modules', 'data modules')} - page {p + 1} of {pages}", "found": {TYPES.get(t, t) + 's': min(len(items), (p + 1) * self.page_size)}})
                if not pause():
                    raise Stopped(f"stopped while reading {api}")
        if scope.get("usage", True):
            offset, page, rows = 0, 0, []
            while True:
                page += 1
                out = self._req("GET", f"/api/v1/audit/runs?limit=5000&offset={offset}")
                items = out.get("items") or []
                rows += items
                self.progress({"phase": "usage", "page": page, "pages": max(1, -(-(out.get('total') or len(rows)) // 5000)), "pct": 72 + min(20, page * 2),
                               "text": f"reading the Audit database - {len(rows):,} runs so far"})
                if not pause():
                    raise Stopped("stopped while reading the audit")
                if len(items) < 5000:
                    break
                offset += 5000
            with open(dest / "audit.csv", "w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["COGIPF_LOCALTIMESTAMP", "COGIPF_REPORTPATH", "COGIPF_USERNAME", "COGIPF_STATUS", "COGIPF_RUNTIME"], lineterminator="\n")
                w.writeheader()
                for r in rows:
                    w.writerow({"COGIPF_LOCALTIMESTAMP": r.get("timestamp"), "COGIPF_REPORTPATH": r.get("path"), "COGIPF_USERNAME": r.get("user"),
                                "COGIPF_STATUS": r.get("status"), "COGIPF_RUNTIME": r.get("runtime")})
        (dest / "manifest.json").write_text(json.dumps({"product": session.get("product") or "IBM Cognos Analytics", "version": session.get("version"),
                                                        "namespace": self.namespace, "users": session.get("users"), "exported": dt.datetime.now().isoformat(timespec="seconds"),
                                                        "as_of": session.get("as_of"), "source": self.base}), encoding="utf-8")
        return dest
