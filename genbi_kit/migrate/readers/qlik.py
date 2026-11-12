"""Qlik readers: inventory and the neutral model from app exports.

Qlik Sense: an app exported with `qlik app unbuild` (or a folder holding several of them), i.e.
    app-properties.json        qTitle, qLastReloadTime, owner ...
    script.qvs                 the load script
    sheets/<id>.json           qInfo, qMetaDef.title, cells[] naming the objects on the sheet
    objects/<id>.json          qInfo.qType (barchart, linechart, piechart, kpi, table, pivot-table, combochart, gauge, map ...),
                               title, qHyperCubeDef with qDimensions / qMeasures (inline qDef or qLibraryId)
    measures/<id>.json         master measures (qMeasure.qDef, qLabel);  dimensions/<id>.json  master dimensions
    variables/<id>.json        variables
    usage.csv (optional)       Monitoring apps export: app, user, timestamp, status

QlikView: a document's project folder (`-prj`): DocProperties.xml (Title), LoadScript.txt, SH*.xml sheets
(SheetProperties/Title, ChildObjects), CH*.xml charts (ChartProperties: Title, ChartType, Dimensions/FieldDef,
Expressions/Definition + Label). Section Access in the script is flagged as a feature.

Qlik expressions (Sum(Sales), Count(distinct Customer), set analysis {$<Year={2024}>}) are kept as written: there are no
conversion rules for them in P15, so every calculation counts as "no rule yet" and the converter asks the agent.
The load script gives the datasets: LOAD ... FROM [lib://.../file.qvd] and SQL SELECT ... FROM table statements.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from .. import model

READS_SENSE = ["Apps", "Sheets", "Charts and tables", "Master measures and dimensions", "Variables", "Load scripts and data connections",
               "usage from the Monitoring apps"]
READS_VIEW = ["Documents (QVW)", "Load scripts", "QVD files", "Sheets and objects", "Section access", "usage from the QlikView Server logs"]
OBJECT_KINDS = {"barchart": "column", "linechart": "line", "piechart": "pie", "kpi": "kpi", "table": "list", "pivot-table": "crosstab", "combochart": "column",
                "gauge": "gauge", "map": "map", "scatterplot": "scatter", "treemap": "treemap", "text-image": "text", "filterpane": "filter",
                "listbox": "filter", "boxplot": "custom", "distributionplot": "custom", "histogram": "column", "waterfallchart": "column", "mekkochart": "custom"}
QV_KINDS = {"BAR": "column", "LINE": "line", "PIE": "pie", "TABLE": "list", "STRAIGHT_TABLE": "list", "PIVOT": "crosstab", "PIVOT_TABLE": "crosstab",
            "GAUGE": "gauge", "TEXT": "text", "LISTBOX": "filter", "SCATTER": "scatter", "COMBO": "column", "GRID": "crosstab", "RADAR": "custom",
            "MEKKO": "custom", "FUNNEL": "custom", "BLOCK": "treemap"}


class ReadError(Exception):
    pass


def parse_load_script(text: str) -> dict:
    """Tables, fields and sources from a load script: LOAD a, b, c FROM [lib://x/y.qvd] (qvd); SQL SELECT ... FROM t;"""
    tables, connections, features = [], [], []
    cleaned = re.sub(r"(?<![:\w])//[^\n]*", "", text)      # comments, but not the // in lib://
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.S)
    if re.search(r"^\s*Section\s+Access\s*;", cleaned, re.I | re.M):
        features.append("section access")
    for m in re.finditer(r"LIB\s+CONNECT\s+TO\s+'([^']+)'|CONNECT\s+TO\s+'([^']+)'|ODBC\s+CONNECT\s+TO\s+([\w\-.]+)", cleaned, re.I):
        connections.append(next(g for g in m.groups() if g))
    def columns(fields: str) -> list[dict]:
        cols = []
        for f in re.split(r",(?![^(]*\))", fields):
            f = f.strip()
            if not f or f == "*":
                continue
            alias = re.search(r"\bas\s+(\[[^\]]+\]|\"[^\"]+\"|[\w.]+)\s*$", f, re.I)
            name = (alias.group(1) if alias else f).strip("[]\"")
            if name and name.lower() not in ("distinct",):
                cols.append(model.column(name.split("(")[-1].strip(") ") if not alias and "(" in name else name, "string", "attribute"))
        return cols

    label_re = r"(?:^|\n)[ \t]*(?:\[?([\w ]+?)\]?[ \t]*:[ \t]*\n?)?"
    stmts = []
    for m in re.finditer(label_re + r"(?:(?:NoConcatenate|Concatenate\s*\([^)]*\))\s+)?LOAD\b(.*?)(?:\bFROM\b\s*(\[[^\]]+\]|'[^']+'|\S+)\s*(?:\(([^)]*)\))?|\bRESIDENT\b\s+(\[[^\]]+\]|\w+)|\bINLINE\b|\bAUTOGENERATE\b)[^;]*;",
                         cleaned, re.I | re.S):
        label, fields, src, fmt, resident = m.groups()
        if src:
            source = src.strip("[]'\"")
            kind = (fmt or "").split(",")[0].strip().lower() or Path(source).suffix.lstrip(".").lower() or "file"
        elif resident:
            source, kind = resident.strip("[]"), "resident"
        else:
            source, kind = None, "inline"
        stmts.append((m.start(), label, fields, source, kind))
    for m in re.finditer(label_re + r"SQL\s+SELECT\b(.*?)\bFROM\s+([\w.\[\]\"]+)[^;]*;", cleaned, re.I | re.S):
        label, fields, table = m.groups()
        stmts.append((m.start(), label, fields, table.strip("[]\""), "sql"))
    access = [(m.start(), m.end()) for m in re.finditer(r"Section\s+Access\s*;.*?(?:Section\s+Application\s*;|$)", cleaned, re.I | re.S)]
    for start, label, fields, source, kind in sorted(stmts, key=lambda s: s[0]):
        if any(a <= start < b for a, b in access):
            continue                                   # the section access tables are not data
        leaf = Path(source.replace("\\", "/")) if source else None          # Windows paths in scripts read on Linux too
        name = (label or (leaf.stem if leaf else f"Table{len(tables) + 1}")).strip()
        tables.append({"name": name, "columns": columns(fields), "source": source, "source_kind": kind,
                       "file": leaf.name if leaf is not None and kind in ("qvd", "csv", "txt", "xlsx", "file") else None})
    return {"tables": tables, "connections": list(dict.fromkeys(connections)), "features": features}


def _usage_rows(path: Path) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("app") or row.get("document") or row.get("App") or "").strip()
            ts = (row.get("timestamp") or row.get("Timestamp") or "")[:10]
            if not key or not ts:
                continue
            u = out.setdefault(key, {"runs": [], "users": set(), "failed": []})
            u["runs"].append(ts)
            if row.get("user") or row.get("User"):
                u["users"].add(row.get("user") or row.get("User"))
            if (row.get("status") or "").lower() not in ("", "ok", "success"):
                u["failed"].append(ts)
    return out


def _apply_usage(r: dict, u: dict | None, as_of: dt.date) -> None:
    if not u:
        return
    days = sorted(d for d in ((as_of - dt.date.fromisoformat(t)).days for t in u["runs"]) if d is not None)
    r["usage"] = {"runs_365": sum(1 for d in days if d <= 365), "runs_90": sum(1 for d in days if d <= 90), "last_run_days": days[0] if days else None,
                  "users": len(u["users"]), "failed_days": min(((as_of - dt.date.fromisoformat(t)).days for t in u["failed"]), default=None)}


class QlikSenseUnbuild:
    """One unbuilt app (a folder with app-properties.json) or a folder of them."""

    def __init__(self, root: str | Path, page_size: int = 100, version: str = ""):
        self.root = Path(root)
        if not self.root.is_dir():
            raise ReadError(f"{root} is not a folder")
        self.page_size, self.version = page_size, version

    def apps(self) -> list[Path]:
        if (self.root / "app-properties.json").exists():
            return [self.root]
        return sorted(p.parent for p in self.root.glob("*/app-properties.json"))

    def test(self) -> dict:
        apps = self.apps()
        return {"ok": True, "product": "Qlik Sense", "version": self.version or "unbuild export", "objects": len(apps), "team_folders": 1, "personal_folders": 0,
                "usage_source": "Monitoring apps export" if (self.root / "usage.csv").exists() else None, "permissions": "Read (exported files)",
                "estimate_seconds": max(1, len(apps) // 20), "users": None, "usage_days": None, "data_files": 0}

    def read(self, progress=None, pause=None, cursor=None, estate=None) -> dict:
        progress = progress or (lambda e: None)
        pause = pause or (lambda: True)
        t0 = time.time()
        est = estate or model.new_estate("qlik_sense", self.version, "exports")
        usage = _usage_rows(self.root / "usage.csv")
        as_of = dt.date.today()
        apps = self.apps()
        pages = max(1, -(-len(apps) // self.page_size))
        for p in range(pages):
            for app in apps[p * self.page_size:(p + 1) * self.page_size]:
                try:
                    self._app(app, est, usage, as_of)
                except (ReadError, OSError, ValueError) as e:
                    est["problems"].append(f"{app.name}: {e}")
            progress({"phase": "apps", "page": p + 1, "pages": pages, "pct": round(90 * (p + 1) / pages), "text": f"reading apps - page {p + 1} of {pages}",
                      "found": {"Apps": len(est["reports"]), "Data connections": len(est["datasets"])}})
            if not pause():
                from .cognos import Stopped
                raise Stopped("stopped while reading apps")
        est["usage"] = {"source": "Monitoring apps export" if usage else None, "from": None, "to": None, "runs": sum(len(u["runs"]) for u in usage.values()), "days": None}
        est["read_seconds"] = round(time.time() - t0, 1)
        model.finish(est)
        est["problems"] = list(dict.fromkeys(est["problems"] + model.validate(est)))
        progress({"phase": "done", "page": 1, "pages": 1, "pct": 100, "text": f"scan complete - {len(est['reports'])} apps in {est['read_seconds']} s"})
        return est

    def _app(self, app: Path, est: dict, usage: dict, as_of: dt.date) -> None:
        props = json.loads((app / "app-properties.json").read_text(encoding="utf-8-sig"))
        title = props.get("qTitle") or props.get("title") or app.name
        aid = "app-" + re.sub(r"[^a-z0-9]+", "-", (props.get("qId") or app.name).lower()).strip("-")[:40]
        script = (app / "script.qvs").read_text(encoding="utf-8-sig") if (app / "script.qvs").exists() else ""
        loaded = parse_load_script(script)
        did = "ds-" + aid
        ds = model.new_dataset(did, f"{title} (data model)", "data module", [model.new_table(t["name"], t["columns"], t.get("file"), "fact" if i == 0 else "dimension")
                                                                           for i, t in enumerate(loaded["tables"])], [], "Apps")
        ds["connections"] = loaded["connections"]
        est["datasets"].append(ds)
        masters: dict[str, dict] = {}
        for f in sorted((app / "measures").glob("*.json")) if (app / "measures").is_dir() else []:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
            masters[m.get("qInfo", {}).get("qId") or f.stem] = {"name": (m.get("qMeasure") or {}).get("qLabel") or f.stem, "expression": (m.get("qMeasure") or {}).get("qDef") or "", "kind": "measure"}
        for f in sorted((app / "dimensions").glob("*.json")) if (app / "dimensions").is_dir() else []:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            defs = (d.get("qDim") or {}).get("qFieldDefs") or []
            masters[d.get("qInfo", {}).get("qId") or f.stem] = {"name": (d.get("qDim") or {}).get("qLabel") or (defs[0] if defs else f.stem), "expression": defs[0] if defs else "", "kind": "attribute"}
        objects: dict[str, dict] = {}
        for f in sorted((app / "objects").glob("*.json")) if (app / "objects").is_dir() else []:
            o = json.loads(f.read_text(encoding="utf-8-sig"))
            objects[o.get("qInfo", {}).get("qId") or f.stem] = o
        items: list[dict] = []
        have: set[str] = set()

        def add_item(name, expression, kind):
            if name not in have:
                have.add(name)
                items.append({"name": name, "expression": expression, "aggregate": "sum" if kind == "measure" and re.match(r"\s*sum\s*\(", expression, re.I) else None, "kind": kind})
            return name

        pages, features = [], list(loaded["features"])
        sheets = sorted((app / "sheets").glob("*.json")) if (app / "sheets").is_dir() else []
        for f in sheets:
            s = json.loads(f.read_text(encoding="utf-8-sig"))
            visuals = []
            for cell in s.get("cells") or []:
                o = objects.get(cell.get("name"))
                if not o:
                    continue
                qtype = (o.get("qInfo") or {}).get("qType") or ""
                kind = OBJECT_KINDS.get(qtype, "custom")
                hc = o.get("qHyperCubeDef") or {}
                cats, measures = [], []
                for d in hc.get("qDimensions") or []:
                    if d.get("qLibraryId") and d["qLibraryId"] in masters:
                        mm = masters[d["qLibraryId"]]
                        cats.append(add_item(mm["name"], mm["expression"], "attribute"))
                    else:
                        defs = (d.get("qDef") or {}).get("qFieldDefs") or []
                        if defs:
                            cats.append(add_item((d.get("qDef") or {}).get("qFieldLabels", [None])[0] or defs[0].strip("[]"), defs[0], "calculation" if defs[0].startswith("=") else "attribute"))
                for m in hc.get("qMeasures") or []:
                    if m.get("qLibraryId") and m["qLibraryId"] in masters:
                        mm = masters[m["qLibraryId"]]
                        measures.append(add_item(mm["name"], mm["expression"], "measure"))
                    else:
                        qd = m.get("qDef") or {}
                        if qd.get("qDef"):
                            measures.append(add_item(qd.get("qLabel") or qd["qDef"], qd["qDef"], "measure"))
                if kind == "custom":
                    features.append(f"{qtype} object")
                otitle = o.get("title") if isinstance(o.get("title"), str) else (o.get("title") or {}).get("qStringExpression", {}).get("qExpr") if isinstance(o.get("title"), dict) else None
                visuals.append(model.visual(cell.get("name"), kind, "Q1", otitle or qtype, category=cats[0] if cats else None, series=cats[1] if len(cats) > 1 else None,
                                            measures=measures, columns=cats + measures))
            pages.append({"name": (s.get("qMetaDef") or {}).get("title") or f.stem, "visuals": visuals})
        r = model.new_report(aid, title, "App", "Apps/" + (props.get("stream") or props.get("qStream") or "Everyone"), props.get("owner") or None, did,
                             created=(props.get("createdDate") or "")[:10] or None, modified=(props.get("qLastReloadTime") or props.get("modifiedDate") or "")[:10] or None,
                             spec_file=f"{app.name}/app-properties.json", queries=[{"name": "Q1", "items": items, "filters": []}],
                             prompts=[], pages=pages, features=list(dict.fromkeys(features)), dependencies=[did])
        _apply_usage(r, usage.get(title) or usage.get(aid), as_of)
        est["reports"].append(r)


class QlikViewProject:
    """One -prj folder (DocProperties.xml + LoadScript.txt) or a folder of them."""

    def __init__(self, root: str | Path, page_size: int = 100, version: str = ""):
        self.root = Path(root)
        if not self.root.is_dir():
            raise ReadError(f"{root} is not a folder")
        self.page_size, self.version = page_size, version

    def docs(self) -> list[Path]:
        if (self.root / "DocProperties.xml").exists():
            return [self.root]
        return sorted(p.parent for p in self.root.glob("*/DocProperties.xml"))

    def test(self) -> dict:
        docs = self.docs()
        return {"ok": True, "product": "QlikView", "version": self.version or "project folder", "objects": len(docs), "team_folders": 1, "personal_folders": 0,
                "usage_source": "QlikView Server log export" if (self.root / "usage.csv").exists() else None, "permissions": "Read (exported files)",
                "estimate_seconds": max(1, len(docs) // 20), "users": None, "usage_days": None, "data_files": 0}

    def read(self, progress=None, pause=None, cursor=None, estate=None) -> dict:
        progress = progress or (lambda e: None)
        pause = pause or (lambda: True)
        t0 = time.time()
        est = estate or model.new_estate("qlikview", self.version, "exports")
        usage = _usage_rows(self.root / "usage.csv")
        as_of = dt.date.today()
        docs = self.docs()
        pages = max(1, -(-len(docs) // self.page_size))
        for p in range(pages):
            for doc in docs[p * self.page_size:(p + 1) * self.page_size]:
                try:
                    self._doc(doc, est, usage, as_of)
                except (ReadError, OSError, ValueError, ET.ParseError) as e:
                    est["problems"].append(f"{doc.name}: {e}")
            progress({"phase": "documents", "page": p + 1, "pages": pages, "pct": round(90 * (p + 1) / pages), "text": f"reading documents - page {p + 1} of {pages}",
                      "found": {"Documents": len(est["reports"]), "QVD files": sum(len(d['tables']) for d in est['datasets'])}})
            if not pause():
                from .cognos import Stopped
                raise Stopped("stopped while reading documents")
        est["usage"] = {"source": "QlikView Server log export" if usage else None, "from": None, "to": None, "runs": sum(len(u["runs"]) for u in usage.values()), "days": None}
        est["read_seconds"] = round(time.time() - t0, 1)
        model.finish(est)
        est["problems"] = list(dict.fromkeys(est["problems"] + model.validate(est)))
        progress({"phase": "done", "page": 1, "pages": 1, "pct": 100, "text": f"scan complete - {len(est['reports'])} documents in {est['read_seconds']} s"})
        return est

    def _doc(self, doc: Path, est: dict, usage: dict, as_of: dt.date) -> None:
        props = ET.parse(doc / "DocProperties.xml").getroot()
        title = (props.findtext(".//Title") or doc.name.replace("-prj", "")).strip()
        did_base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
        aid, did = f"qvw-{did_base}", f"ds-qvw-{did_base}"
        script = (doc / "LoadScript.txt").read_text(encoding="utf-8-sig", errors="replace") if (doc / "LoadScript.txt").exists() else ""
        loaded = parse_load_script(script)
        ds = model.new_dataset(did, f"{title} (data model)", "data module", [model.new_table(t["name"], t["columns"], t.get("file"), "fact" if i == 0 else "dimension")
                                                                           for i, t in enumerate(loaded["tables"])], [], "Documents")
        ds["connections"] = loaded["connections"]
        est["datasets"].append(ds)
        items, have, pages, features = [], set(), [], list(loaded["features"])

        def add_item(name, expression, kind):
            if name not in have:
                have.add(name)
                items.append({"name": name, "expression": expression, "aggregate": "sum" if kind == "measure" and re.match(r"\s*sum\s*\(", expression, re.I) else None, "kind": kind})
            return name

        charts: dict[str, dict] = {}
        for f in sorted(doc.glob("CH*.xml")):
            ch = ET.parse(f).getroot()
            ctype = (ch.findtext(".//ChartType") or ch.findtext(".//Type") or "TABLE").strip().upper()
            dims = [(d.findtext("FieldDef") or d.findtext("Field") or "").strip() for d in ch.findall(".//Dimension")]
            exprs = [((e.findtext("Label") or e.findtext("Definition") or "").strip(), (e.findtext("Definition") or "").strip()) for e in ch.findall(".//Expression")]
            charts[f.stem] = {"kind": QV_KINDS.get(ctype, "custom"), "title": (ch.findtext(".//Title/v") or ch.findtext(".//Title") or f.stem).strip(), "dims": dims, "exprs": exprs, "type": ctype}
        for f in sorted(doc.glob("SH*.xml")):
            sh = ET.parse(f).getroot()
            visuals = []
            for obj in [o.text.strip() for o in sh.findall(".//ChildObjects/Object") if o.text] or [c for c in charts if c.startswith("CH")]:
                c = charts.get(obj)
                if not c:
                    continue
                cats = [add_item(d, f"[{d}]", "attribute") for d in c["dims"] if d]
                measures = [add_item(label, defn, "measure") for label, defn in c["exprs"] if defn]
                if c["kind"] == "custom":
                    features.append(f"{c['type'].lower()} object")
                visuals.append(model.visual(obj, c["kind"], "Q1", c["title"], category=cats[0] if cats else None, series=cats[1] if len(cats) > 1 else None,
                                            measures=measures, columns=cats + measures))
            pages.append({"name": (sh.findtext(".//Title") or sh.findtext(".//Name") or f.stem).strip(), "visuals": visuals})
        r = model.new_report(aid, title, "Document", "Documents", (props.findtext(".//Author") or "").strip() or None, did, spec_file=f"{doc.name}/DocProperties.xml",
                             queries=[{"name": "Q1", "items": items, "filters": []}], prompts=[], pages=pages, features=list(dict.fromkeys(features)), dependencies=[did])
        _apply_usage(r, usage.get(title) or usage.get(doc.name), as_of)
        est["reports"].append(r)
