"""Process mining & discovery (registry id `mining`) — event logs from ERP and ticketing turned into the real process:
variants, delays, rework and what to automate first; an event log built from SAP or Oracle extracts and proven; KPIs
watched on a schedule. Celonis and SAP Signavio Process Intelligence are read through their APIs (mining_sources);
UiPath Process Mining, Power Automate Process Mining and SAP / Oracle extracts come in as CSV, Excel or XES.

Assess   Connect → Inventory → Health → Findings → Estimate: every log read (the columns found by name, a person
         corrects them; rules first — a column that is not in the file is refused), then mined: variants, throughput
         time, waits between activities (bottlenecks), rework, ping-pong, cancellations, and the fit with a published
         process; findings kept or ignored; what to automate first, ranked by the hours a month it takes people, with
         the minutes per event as an assumption a person sets.
Develop  Describe → Shape → Build → Prove → Ship → Run: an event log designed from ERP tables (SAP EBAN / EKKO / EKBE /
         RBKP / BSAK, Oracle PO / AP tables: known date columns become activities by rule), built with DuckDB, proven
         (every event reconciles with the dates in the tables, every case key has its purchase order), approved by a
         named person, loaded into Celonis after its own approval, and watched by a scheduled Run item.
Run      Watch → Alert → Fix → Approve → Report: the KPIs (throughput time, the slowest wait, rework, variants) against
         the baseline; a drift grouped with its likely cause; a person decides the hand-off before it goes out.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import statistics
import time
from pathlib import Path

from .. import connectors, db
from .. import workbench as wb
from . import _w4
from . import mining_sources as ms

MODULE = "mining"
UPLOADS = (".csv", ".tsv", ".xlsx", ".xes", ".log")
SYSTEM_USERS = re.compile(r"^(system|sap_?wf|rfc|job|bot|relay)|batch", re.I)       # SYSTEM, SAP_BATCH, WF-BATCH: not a person's work
SAP_ACTIVITIES = {("eban", "badat"): "Create purchase requisition", ("ekko", "aedat"): "Create purchase order", ("cdhdr", "udate"): "Approve purchase order",
                  ("ekbe", "budat"): "Record goods receipt", ("rbkp", "cpudt"): "Enter invoice", ("rbkp", "budat"): "Post invoice", ("bsak", "augdt"): "Clear invoice",
                  ("po_headers_all", "creation_date"): "Create purchase order", ("po_headers_all", "approved_date"): "Approve purchase order",
                  ("rcv_transactions", "transaction_date"): "Record goods receipt", ("ap_invoices_all", "creation_date"): "Enter invoice",
                  ("ap_invoice_payments_all", "creation_date"): "Pay invoice"}
SAP_FILTERS = {("ekbe", "budat"): "BEWTP = 'E'", ("cdhdr", "udate"): "TCODE = 'ME29N'", ("rcv_transactions", "transaction_date"): "TRANSACTION_TYPE = 'RECEIVE'"}
CASE_KEYS = ("ebeln", "objectid", "po_header_id", "po_number", "case_id")   # CDHDR.OBJECTID is the order number for OBJECTCLAS EINKBELEG
HEADER_TABLES = ("EKKO", "PO_HEADERS_ALL")                                    # where every purchase order is: the proof's reference
DOC_DATES = {("rbkp", "bldat"): "the invoice's own date (when the supplier wrote it), not something done in the process"}
MINUTES = 5                                     # the default minutes a person spends on one event (an assumption the person changes)

FILES = wb.FilesPlatform()
FILES.label = "Event logs and ERP extracts"
FILES.uploads = UPLOADS
FILES.reads = ("event logs (CSV, Excel, XES — UiPath Process Mining and Power Automate Process Mining exports included) and SAP or Oracle table extracts — "
               "a copy in this work item's folder, read with DuckDB")
FILES.simulator = "synthetic fixtures in tests/mocklab/fixtures/mining/ (a purchase-to-pay log, its slower November, SAP extracts)"


class MiningPlatform(wb.Platform):
    id = "mining"
    label = "Celonis or SAP Signavio Process Intelligence"
    kinds = ms.SOURCES
    simulator = "tests/mocklab/sims/process.py: celonis (Intelligence API, Data Push API), signavio-pi"
    reads = "the event records of a knowledge model or a process, read-only; Celonis loads an event log only after you approve it"


MINING = MiningPlatform()


# ------------------------------------------------------------------ the logs an item reads, and what mining finds in them

def _header(f: Path) -> list[str] | None:
    """The first row of an uploaded log (CSV, TSV or the first sheet of a workbook); None for what has no header (XES)."""
    import csv
    if not f.is_file():
        return None
    if f.suffix.lower() == ".xlsx":
        import openpyxl
        book = openpyxl.load_workbook(str(f), read_only=True, data_only=True)
        try:
            return [str(v or "").strip() for v in next(book.worksheets[0].iter_rows(values_only=True), ())]
        finally:
            book.close()
    if f.suffix.lower() not in (".csv", ".tsv", ".log"):
        return None
    with f.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        delim = "\t" if f.suffix.lower() == ".tsv" or sample.count("\t") > sample.count(",") else ";" if sample.count(";") > sample.count(",") else ","
        return [h.strip() for h in next(csv.reader(fh, delimiter=delim), [])]


def _rows_in(p: Path) -> int | None:
    """The data rows of an upload (blank lines aside), to reconcile with the events read."""
    ext = p.suffix.lower()
    if ext in (".csv", ".tsv", ".log"):
        with p.open(encoding="utf-8-sig", errors="replace") as fh:
            return max(0, sum(1 for line in fh if line.strip()) - 1)
    if ext == ".xlsx":
        import openpyxl
        book = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        try:
            return max(0, sum(1 for r in book.worksheets[0].iter_rows(values_only=True) if r and any(str(v or "").strip() for v in r)) - 1)
        finally:
            book.close()
    return None


def _sources(ctx: wb.Ctx) -> list[dict]:
    """What the item can mine: every upload (an XES log, or a table whose columns a person may name) and the event
    records of each Celonis / Signavio PI connection (read once, kept in sources/ for the steps that follow)."""
    out = []
    for f in ctx.files(UPLOADS):
        p = ctx.dir / "data" / f["name"]
        out.append({"source": f["name"], "kind": "xes" if p.suffix.lower() == ".xes" else "upload", "header": _header(p), "rows": _rows_in(p)})
    for c in ctx.connections():
        if c["kind"] not in ms.SOURCES:
            continue
        try:
            objs = connectors.browse(c)
            obj = c["config"].get("record") or c["config"].get("process") or (objs[0]["object"] if objs else None)
            cols, rows = connectors.sdk.get(c["kind"]).events(c, obj)
        except Exception as e:  # noqa: BLE001 - ConnectorError / Reconsent / ScopeError: shown to the person
            raise wb.StepFailed(f"{c['name']} could not be read: {e}") from e
        db.audit("connection.read", c["id"], {"kind": c["kind"], "object": obj, "rows": len(rows), "module": MODULE}, ctx.who or ctx.owner)
        name = f"{c['name']} · {next((o.get('type') for o in objs if o['object'] == obj), None) or obj}"
        key = _w4.slug(name, 40)
        (ctx.dir / "sources").mkdir(exist_ok=True)
        (ctx.dir / "sources" / f"raw-{key}.json").write_text(json.dumps({"columns": cols, "rows": rows}, default=str), encoding="utf-8")
        out.append({"source": name, "kind": "connection", "key": key, "header": cols, "rows": len(rows)})
    return out


def _mapping(rec: dict) -> dict | None:
    m = {k: (rec.get(k) or "").strip() for k in ("case", "activity", "time", "resource")}
    if not all(m[k] for k in ("case", "activity", "time")):
        return None
    m["resource"] = m["resource"] or None
    return m


def _read(ctx: wb.Ctx, rec: dict) -> dict | None:
    """One inventory record's event log, read with the columns the record names (the person's correction included)."""
    if rec.get("kind") == "connection":
        try:
            raw = json.loads((ctx.dir / "sources" / f"raw-{rec['key']}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            return None
        m = _mapping(rec)
        return _w4.eventlog_from_rows(rec["source"], raw["columns"], raw["rows"], m) if m and all(m[k] in raw["columns"] for k in ("case", "activity", "time")) else None
    p = ctx.dir / "data" / rec["source"]
    try:
        return _w4.read_eventlog(p) if rec.get("kind") == "xes" else (_w4.read_eventlog(p, _mapping(rec)) if _mapping(rec) else None)
    except Exception:  # noqa: BLE001 - not a log after all
        return None


def _median(xs):
    return statistics.median(xs) if xs else 0.0


def _p90(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.9 * len(xs)))] if xs else 0.0


def analyse(lg: dict) -> dict:
    """Rules, no AI: variants, throughput, waits, rework, ping-pong, endings and the people's share of the work."""
    cases = {k: v for k, v in lg["cases"].items() if v}
    n = len(cases) or 1
    vs = _w4.variants(cases)
    thr = [evs[-1][0] - evs[0][0] for evs in cases.values() if len(evs) > 1]
    waits: dict = {}
    for evs in cases.values():
        for a, b in zip(evs, evs[1:]):
            waits.setdefault((a[1], b[1]), []).append(b[0] - a[0])
    pairs = sorted(({"from": a, "to": b, "cases": len(v), "median_h": round(_median(v) / 3600, 1), "total_h": round(sum(v) / 3600, 1)} for (a, b), v in waits.items()),
                   key=lambda p: (-p["total_h"], p["from"], p["to"]))
    rework = collections.Counter()
    pingpong = 0
    for evs in cases.values():
        acts = [e[1] for e in evs]
        for a, k in collections.Counter(acts).items():
            if k > 1:
                rework[a] += 1
        if any(acts[i] == acts[i + 2] and acts[i] != acts[i + 1] for i in range(len(acts) - 2)):
            pingpong += 1
    times = [e[0] for v in cases.values() for e in v]
    span = max(1.0, (max(times) - min(times)) / 86400) if times else 1.0
    acts = collections.Counter(e[1] for v in cases.values() for e in v)
    people = collections.Counter(e[1] for v in cases.values() for e in v if e[2] and not SYSTEM_USERS.match(e[2]))
    last = collections.Counter(v[-1][1] for v in cases.values())
    first = collections.Counter(v[0][1] for v in cases.values())
    return {"cases": len(cases), "events": sum(acts.values()), "activities": dict(acts), "variants": len(vs),
            "top": [{"path": v["path"], "cases": v["cases"], "share": round(v["cases"] / n, 3), "median_h": round(_median(v["durations"]) / 3600, 1)} for v in vs[:8]],
            "throughput_h": round(_median(thr) / 3600, 1), "throughput_p90_h": round(_p90(thr) / 3600, 1), "waits": pairs[:12],
            "pairs": {f"{a} → {b}": round(_median(v) / 3600, 1) for (a, b), v in waits.items()},
            "rework": dict(rework), "rework_rate": round(sum(1 for evs in cases.values() if len({e[1] for e in evs}) < len(evs)) / n, 3), "pingpong": pingpong,
            "span_days": round(span, 1), "per_month": {a: round(k * 30 / span, 1) for a, k in acts.items()}, "people": dict(people),
            "first": list(first.most_common(1)[0]) if first else None, "last": dict(last)}


# ------------------------------------------------------------------ Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = []
    for c in ctx.connections():
        if c["kind"] not in ms.SOURCES:
            continue
        try:
            t = connectors.test({**c, "_who": ctx.who or ctx.owner})
            rows.append([c["name"], connectors.KINDS[c["kind"]]["label"], "answered", t.get("sees")])
        except Exception as e:  # noqa: BLE001 - ConnectorError / Reconsent: shown to the person
            rows.append([c["name"], connectors.KINDS[c["kind"]]["label"], "refused", str(e)[:200]])
    for f in ctx.files(UPLOADS):
        rows.append([f["name"], "Upload", "a read-only copy", f"{f['bytes']:,} bytes"])
    if not rows:
        raise wb.StepFailed("Connect Celonis or Signavio Process Intelligence, or upload an event log (CSV, Excel or XES) or an ERP extract.")
    if all(r[2] == "refused" for r in rows):
        raise wb.StepFailed("None of the sources answered: " + "; ".join(f"{r[0]}: {r[3]}" for r in rows)[:500])
    return {"summary": f"{sum(1 for r in rows if r[2] != 'refused')} of {len(rows)} source(s) answered — read-only.", "data": {"columns": ["Source", "Kind", "Status", "What Relay sees"], "rows": rows}}


def _describe(rec: dict, lg: dict | None, rows: int | None) -> dict:
    """The counts an inventory record shows for the log its columns read."""
    if not (lg and lg["events"]):
        return {"cases": 0, "events": 0, "activities": 0, "from": "", "to": "", "skipped": (lg or {}).get("skipped", 0), "rows": rows}
    times = [e[0] for v in lg["cases"].values() for e in v]
    return {"cases": len(lg["cases"]), "events": lg["events"], "activities": len({e[1] for v in lg["cases"].values() for e in v}), "skipped": lg["skipped"], "rows": rows,
            "from": time.strftime("%Y-%m-%d", time.gmtime(min(times))), "to": time.strftime("%Y-%m-%d", time.gmtime(max(times)))}


def a_inventory(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for s in _sources(ctx):
        prev = have.get(s["source"]) or {}
        guess = (_w4.eventlog_columns(s["header"]) if s["header"] else None) or {}
        rec = {"id": s["source"], "source": s["source"], "kind": s["kind"], "key": s.get("key") or _w4.slug(s["source"], 40)}
        for k in ("case", "activity", "time", "resource"):
            rec[k] = prev[k] if k in prev else (guess.get(k) or "")
        lg = _read(ctx, rec)
        if s["kind"] == "xes" and lg:
            rec.update({k: lg["columns"][k] for k in ("case", "activity", "time", "resource")})
        rec.update(_describe(rec, lg, s["rows"]))
        ok = bool(lg and lg["events"])
        rec["include"] = bool(prev.get("include", True)) and ok
        rec["why"] = ("" if ok else "not an event log: no header row" if not s["header"] and s["kind"] != "xes"
                      else "Relay could not tell which columns are the case, the activity and the time — name them, then tick Include")
        recs.append(rec)
    if not recs:
        raise wb.StepFailed("Nothing to mine: upload an event log (CSV, Excel or XES) or connect Celonis or Signavio Process Intelligence.")
    on = [r for r in recs if r["include"]]
    odd = [r for r in recs if r["why"]]
    return {"summary": f"{len(recs)} source(s): {len(on)} event log(s) with {sum(r['cases'] for r in on):,} cases and {sum(r['events'] for r in on):,} events"
            + (f"; {len(odd)} whose columns Relay could not tell — name them" if odd else "") + ". Check the columns Relay found, untick what is out of scope, then confirm.",
            "records": recs, "counts": {"logs": len(on), "cases": sum(r["cases"] for r in on)},
            "items": [f"{r['source']}: {r['why']}" for r in odd][:6],
            "data": {"columns": ["Include", "Log", "Cases", "Events", "Activities", "From", "To", "Case · activity · time"],
                     "rows": [["yes" if r["include"] else "no", r["source"], r["cases"], r["events"], r["activities"], r["from"], r["to"], f"{r['case']} · {r['activity']} · {r['time']}"] for r in recs]}}


def _validate_inventory(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """Rules first: an included log names columns that are in it and reads as events; the counts follow the columns."""
    out = []
    for r in recs:
        if r.get("kind") == "xes":
            if r.get("include") and not r.get("events"):
                out.append(f"{r['source']}: this XES file has no event Relay can read")
            continue
        if not r.get("include"):
            continue
        if r.get("kind") == "connection":
            try:
                head = json.loads((ctx.dir / "sources" / f"raw-{r['key']}.json").read_text(encoding="utf-8"))["columns"]
            except (OSError, ValueError, KeyError):
                head = []
        else:
            head = _header(ctx.dir / "data" / r["source"]) or []
        bad = [k for k in ("case", "activity", "time") if (r.get(k) or "").strip() not in head]
        for k in bad:
            out.append(f"{r['source']}: there is no column {r.get(k)!r} for the {k} (the log has {', '.join(head[:8])})")
        if (r.get("resource") or "").strip() and r["resource"].strip() not in head:
            out.append(f"{r['source']}: there is no column {r['resource']!r} for who did it — leave it empty if the log does not say")
            bad.append("resource")
        if bad:
            continue
        lg = _read(ctx, r)
        if not (lg and lg["events"]):
            out.append(f"{r['source']}: no row has a time Relay can read in {r['time']!r} — is it the right column?")
            continue
        r.update(_describe(r, lg, r.get("rows")))
        r["why"] = ""
    return out


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("source", "Log", readonly=True), wb.Column("case", "Case column"), wb.Column("activity", "Activity column"),
                            wb.Column("time", "Time column"), wb.Column("resource", "Who column"), wb.Column("events", "Events", "number", readonly=True),
                            wb.Column("why", "Note", readonly=True)],
                   add=False, remove=False, validate=_validate_inventory, label="log")


def a_health(ctx: wb.Ctx) -> dict:
    inc = [r for r in ctx.records("inventory") if r.get("include")]
    if not inc:
        raise wb.StepFailed("No log is included: tick at least one in the inventory.")
    checks, results = [], {}
    pid = ctx.scope.get("process") or ""
    proc = None
    if pid:
        from . import processdocs
        u = db.user(ctx.owner or "")
        proc = processdocs.process(pid, u) if u else None
        if not proc:
            checks.append({"name": "process", "label": "The published process to compare with", "status": "warn", "detail": "it is not there any more, or its owner cannot see it"})
    for r in inc:
        lg = _read(ctx, r)
        if not (lg and lg["events"]):
            checks.append({"name": f"read-{r['key']}", "label": f"{r['source']}: read as an event log", "status": "fail", "detail": "the columns named in the inventory no longer read as events"})
            continue
        an = analyse(lg)
        results[r["key"]] = an
        eid = ctx.evidence(f"Mined: {r['source']}", {"rows": [{"variant": " → ".join(v["path"]), "cases": v["cases"], "share": v["share"], "median hours": v["median_h"]} for v in an["top"]],
                                               "waits": an["waits"], "rework": an["rework"], "pingpong": an["pingpong"], "throughput_h": an["throughput_h"], "columns": lg["columns"]}, kind="mining", ok=True)
        if r.get("rows") is not None:
            ok_ = lg["events"] + lg["skipped"] == r["rows"]
            checks.append({"name": f"rows-{r['key']}", "label": f"{r['source']}: every row is an event, or is set aside with its reason", "status": "pass" if ok_ else "fail",
                           "measured": f"{lg['events']} events + {lg['skipped']} set aside (no time or no activity)", "expected": f"{r['rows']} rows",
                           "detail": "the counts reconcile" if ok_ else "rows went missing in reading"})
        fa, fk = an["first"] or ("", 0)
        share = fk / max(1, an["cases"])
        checks.append({"name": f"start-{r['key']}", "label": f"{r['source']}: the cases start the same way", "status": "pass" if share >= 0.9 else "warn",
                       "measured": f"{share:.0%} start with {fa}", "expected": "90 % or more", "detail": "complete cases" if share >= 0.9 else "a log cut off at the start shows cases already under way"})
        checks.append({"name": f"variants-{r['key']}", "label": f"{r['source']}: {an['variants']} variant(s), throughput {an['throughput_h']} h median (p90 {an['throughput_p90_h']} h)", "status": "pass",
                       "measured": f"the top variant is {an['top'][0]['share']:.0%} of the cases" if an["top"] else "—", "detail": " → ".join(an["top"][0]["path"]) if an["top"] else "", "evidence": eid})
        if proc:
            from .. import lineage

            from . import processdocs
            conf = _w4.conformance(proc["map"], lg)
            orig = {_w4.name_key(e[1]): e[1] for v in lg["cases"].values() for e in v}
            ln = ctx.lineage_node("table", "Event log", r["source"], label=f"Event log: {r['source']}", properties={"cases": an["cases"], "events": an["events"]})
            pn = lineage.node_id("process", processdocs.SYSTEM, proc["id"])
            if db.one("SELECT 1 FROM lineage_nodes WHERE id = ?", (pn,)):
                ctx.lineage_edge(ln, pn, "relates", {"fitness": conf["fitness"], "what": "the log against the published map"})
            checks.append({"name": f"fit-{r['key']}", "label": f"{r['source']} against the published “{proc['name']}” (version {proc['version']})",
                           "status": "pass" if conf["fitness"] >= 0.9 else "warn" if conf["fitness"] >= 0.7 else "fail",
                           "measured": f"{conf['fitness']:.0%} of the moves", "expected": "90 % or more",
                           "detail": ("not on the map: " + ", ".join(sorted(orig.get(x, x) for x in conf["missing"])[:5])) if conf["missing"] else "every activity is on the map",
                           "evidence": ctx.evidence(f"Conformance of {r['source']}", conf, kind="proof", ok=conf["fitness"] >= 0.7)})
    for cn in ctx.connections():                       # the platform's own health: a failed load means a log missing its newest events
        if cn["kind"] != "celonis":
            continue
        try:
            loads = connectors.sdk.get("celonis").loads(cn, 5)
        except Exception as e:  # noqa: BLE001 - shown as the check's detail
            loads, err = [], str(e)[:200]
        else:
            err = ""
        last = loads[0] if loads else {}
        good = last.get("loadStatus") == "SUCCESS"
        checks.append({"name": f"loads-{_w4.slug(cn['name'], 24)}", "label": f"{cn['name']}: the data model's last load", "status": "pass" if good else "warn",
                       "measured": f"{last.get('loadStatus') or 'unknown'} · {last.get('endDate') or last.get('startDate') or ''}".strip(" ·"),
                       "detail": "loaded" if good else ((last.get("message") or err or "no load history") + " — the event log may miss its newest events")[:400]})
    ctx.put("analysis", results)
    return {"summary": f"{len(results)} log(s) mined: " + "; ".join(f"{a['cases']} cases, {a['variants']} variants, {a['throughput_h']} h median" for a in results.values()) + ".",
            "counts": {"logs": len(results), "variants": sum(a["variants"] for a in results.values())}, "data": {"checks": checks},
            "ok": not any(x["status"] == "fail" and x["name"].startswith(("rows-", "read-")) for x in checks)}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    out = []
    for key, an in (ctx.get("analysis") or {}).items():
        for w in an["waits"][:3]:
            out.append({"id": f"wait-{key}-{_w4.slug(w['from'] + w['to'], 30)}", "kind": "delay", "what": f"{w['from']} → {w['to']}: {w['median_h']} h median wait over {w['cases']} case(s) ({w['total_h']} h in all)",
                        "severity": "high" if w is an["waits"][0] else "medium", "decision": "keep"})
        for a, k in sorted(an["rework"].items(), key=lambda kv: -kv[1]):
            out.append({"id": f"rework-{key}-{_w4.slug(a, 30)}", "kind": "rework", "what": f"{a} is done more than once in {k} case(s) ({k / max(1, an['cases']):.0%})", "severity": "medium", "decision": "keep"})
        if an["pingpong"]:
            out.append({"id": f"pingpong-{key}", "kind": "ping-pong", "what": f"{an['pingpong']} case(s) go back and forth (an activity, another, the first again)", "severity": "medium", "decision": "keep"})
        usual = max(an["last"], key=an["last"].get) if an["last"] else None
        ends = {a: k for a, k in an["last"].items() if a != usual}
        for a, k in ends.items():
            out.append({"id": f"end-{key}-{_w4.slug(a, 30)}", "kind": "exit", "what": f"{k} case(s) end with {a} instead of the usual end", "severity": "low", "decision": "keep"})
    recs = [{**f, **({"decision": have[f["id"]]["decision"]} if f["id"] in have else {})} for f in out]
    return {"summary": f"{len(recs)} finding(s): delays, rework, ping-pong and other endings — keep what matters.", "records": recs, "counts": {"findings": len(recs)},
            "items": [f["what"][:200] for f in recs[:6]], "data": {"columns": ["Kind", "What", "Severity"], "rows": [[f["kind"], f["what"], f["severity"]] for f in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("kind", "Kind", readonly=True),
                             wb.Column("what", "What", readonly=True), wb.Column("severity", "Severity", readonly=True)], add=False, remove=False, label="finding")
ROUTES = (("rpa", "RPA (a bot)"), ("n8n", "Workflows (n8n)"), ("sdlc", "AI SDLC (change the system)"), ("none", "Not now"))


def a_estimate(ctx: wb.Ctx) -> dict:
    from .. import registry
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for key, an in (ctx.get("analysis") or {}).items():
        for a, k in sorted(an["people"].items(), key=lambda kv: -an["per_month"].get(kv[0], 0)):
            pm = an["per_month"].get(a, 0) * (k / max(1, an["activities"].get(a, 1)))
            rec = {"id": f"{key}-{_w4.slug(a, 30)}", "log": key, "activity": a, "per_month": round(pm, 1), "minutes": MINUTES, "route": "rpa" if a in an["rework"] else "n8n",
                   "share": 100, "wait_cut": 50, "stop_rework": a in an["rework"],
                   "why": f"done by people {k} time(s) in the log" + ("; also re-done" if a in an["rework"] else "")}
            rec = {**rec, **({k_: have[rec["id"]][k_] for k_ in WHATIF_KEEP if k_ in have[rec["id"]]} if rec["id"] in have else {})}
            rec["hours"] = round(float(rec["minutes"] or 0) * rec["per_month"] / 60, 1)
            recs.append(rec)
    recs.sort(key=lambda r: -r["hours"])
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    total = sum(r["hours"] for r in recs if r["route"] != "none")
    ctx.output("automate-first.md", "# What to automate first\n\n" + "\n".join(f"{i}. {r['activity']}: {r['per_month']} a month × {r['minutes']} min = {r['hours']} h a month → {dict(ROUTES)[r['route']]}"
                                                                         for i, r in enumerate(recs, 1)) + f"\n\nAssumption: the minutes a person spends on one event (default {MINUTES}).\n", label="What to automate first (Markdown)")
    return {"summary": f"What to automate first: {len(recs)} activit{'y' if len(recs) == 1 else 'ies'} people do, ranked by the hours a month they take — {total:.1f} h in all"
            + (f" ({cur}{rate * total:,.0f} a month)" if rate else "") + ". The minutes per event are an assumption: set them, then confirm.",
            "records": recs, "counts": {"candidates": len(recs), "hours a month": round(total, 1)},
            "data": {"items": [{"title": r["activity"], "detail": f"{r['per_month']} a month × {r['minutes']} min → {dict(ROUTES).get(r['route'], r['route'])} ({r['why']})", "effort": f"{r['hours']} h a month"} for r in recs],
                     "total": f"{total:.1f} h a month", "note": f"Assumption: {MINUTES} minutes per event unless you set it per activity." + ("" if rate else " Set an hourly rate under Admin › Branding to see the cost.")}}


def _validate_estimate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for r in recs:
        for k_, label in (("share", "the share a bot takes"), ("wait_cut", "the cut in the wait before it")):
            try:
                v = float(r.get(k_) if r.get(k_) not in (None, "") else (100 if k_ == "share" else 0))
                if not 0 <= v <= 100:
                    raise ValueError
                r[k_] = v
            except (TypeError, ValueError):
                out.append(f"{r.get('activity')}: {label} is a percentage from 0 to 100")
        try:
            m = float(r.get("minutes"))
            if not 0 < m <= 480:
                raise ValueError
            r["hours"] = round(m * float(r.get("per_month") or 0) / 60, 1)
        except (TypeError, ValueError):
            out.append(f"{r.get('activity')}: the minutes per event are between 1 and 480")
    return out


EST_EDIT = wb.Edit(columns=[wb.Column("activity", "Activity", readonly=True), wb.Column("per_month", "A month", "number", readonly=True), wb.Column("minutes", "Minutes each", "number"),
                            wb.Column("route", "Automate with", "select", options=ROUTES), wb.Column("hours", "Hours a month", "number", readonly=True),
                            wb.Column("share", "What-if: a bot takes %", "number"), wb.Column("wait_cut", "What-if: wait before it cut %", "number"),
                            wb.Column("stop_rework", "What-if: no re-work", "bool")],
                   add=False, remove=False, validate=_validate_estimate, label="activity")


# ------------------------------------------------------------------ What-if (the log replayed with the changes)

def replay(lg: dict, changes: dict) -> dict:
    """The log's cases replayed with each change, by rules: a re-done activity dropped (with the wait into it), and the
    wait into an activity a bot takes cut by its share × cut. Same cases, same order; only the gaps change."""
    cases = {k: v for k, v in lg["cases"].items() if v}
    thr, rework, events = [], 0, 0
    for evs in cases.values():
        seen, kept, gaps = set(), [evs[0]], []
        seen.add(evs[0][1])
        for prev, e in zip(evs, evs[1:]):
            gap = e[0] - prev[0]
            ch = changes.get(e[1]) or {}
            if e[1] in seen and ch.get("stop_rework"):
                continue
            seen.add(e[1])
            if ch:
                gap *= 1 - (ch.get("share", 0) / 100) * (ch.get("wait_cut", 0) / 100)
            kept.append(e)
            gaps.append(gap)
        events += len(kept)
        thr.append(sum(gaps)) if len(kept) > 1 else None
        rework += len({e[1] for e in kept}) < len(kept)
    n = len(cases) or 1
    return {"cases": len(cases), "events": events, "throughput_h": round(_median(thr) / 3600, 1), "throughput_p90_h": round(_p90(thr) / 3600, 1), "rework_rate": round(rework / n, 3)}


def a_whatif(ctx: wb.Ctx) -> dict:
    from .. import registry
    recs = ctx.records("estimate")
    if not recs:
        raise wb.StepFailed("Nothing to change yet: the Estimate has no activity people do.")
    logs = {r["key"]: r for r in ctx.records("inventory") if r.get("include")}
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    rows, results, lines = [], {}, []
    for key, inv in logs.items():
        mine = [r for r in recs if r.get("log") == key or str(r["id"]).startswith(key + "-")]
        if not mine:
            continue
        lg = _read(ctx, inv)
        if not (lg and lg["events"]):
            raise wb.StepFailed(f"{inv['source']} no longer reads as an event log — check the inventory.")
        changes = {r["activity"]: {"share": float(r.get("share") or 0) if r.get("route") != "none" else 0.0, "wait_cut": float(r.get("wait_cut") or 0), "stop_rework": bool(r.get("stop_rework"))}
                   for r in mine}
        before = replay(lg, {})
        after = replay(lg, changes)
        h0 = sum(float(r.get("hours") or 0) for r in mine)
        saved = sum(float(r.get("hours") or 0) * changes[r["activity"]]["share"] / 100 for r in mine)
        results[key] = {"source": inv["source"], "before": before, "after": after, "people_hours": round(h0, 1), "hours_saved": round(saved, 1),
                        "changes": {a: c for a, c in changes.items() if c["share"] or c["stop_rework"]}}
        name = inv["source"]
        rows += [[name, "Median throughput (h)", before["throughput_h"], after["throughput_h"]], [name, "p90 throughput (h)", before["throughput_p90_h"], after["throughput_p90_h"]],
                 [name, "Cases with re-work", f"{before['rework_rate']:.0%}", f"{after['rework_rate']:.0%}"], [name, "Events", before["events"], after["events"]],
                 [name, "People's hours a month", round(h0, 1), round(h0 - saved, 1)]]
        lines.append(f"## {name}\n\n| Measure | Today | What-if |\n|---|---|---|\n" + "\n".join(f"| {r[1]} | {r[2]} | {r[3]} |" for r in rows if r[0] == name)
                     + "\n\nChanges: " + "; ".join(f"{a}: a bot takes {c['share']:.0f} %, the wait before it cut {c['wait_cut']:.0f} %" + (", no re-work" if c["stop_rework"] else "")
                                                  for a, c in results[key]["changes"].items()) + "\n")
    if not results:
        raise wb.StepFailed("No log in the inventory matches the Estimate's activities.")
    ctx.put("whatif", results)
    saved = sum(r["hours_saved"] for r in results.values())
    eid = ctx.evidence("What-if: the log replayed with the changes", results, kind="mining", ok=True)
    ctx.output("what-if.md", "# What-if\n\nThe event log replayed by rules with the changes set in the Estimate step: same cases, only the waits and the re-done "
                             "activities change. A what-if is an estimate, not a forecast.\n\n" + "\n".join(lines), label="What-if (Markdown)")
    first = next(iter(results.values()))
    cur_data = next((s.get("data") for s in (ctx.st or {}).get("steps", []) if s["id"] == ctx.step_id), None) or {}
    return {"summary": f"What-if: median throughput {first['before']['throughput_h']} h → {first['after']['throughput_h']} h, {saved:.1f} h a month of people's work saved"
            + (f" ({cur}{rate * saved:,.0f} a month)" if rate else "") + " — the log replayed with your changes.",
            "data": {**cur_data, "compare": {"title": "What-if — the log replayed with your changes", "columns": ["Log", "Measure", "Today", "What-if"], "rows": rows, "evidence": eid}}}


WHATIF_KEEP = ("minutes", "route", "share", "wait_cut", "stop_rework")


# ------------------------------------------------------------------ Develop (an event log from ERP extracts)

KNOWN_TABLES = sorted({t for t, _ in SAP_ACTIVITIES} | {t for t, _ in DOC_DATES}, key=len, reverse=True)


def _table_name(file: str) -> str:
    """The ERP table an extract holds, from its file name: "sap-ekko-2026.csv" and "EKKO.csv" are both EKKO."""
    stem = re.sub(r"\W+", "_", Path(file).stem).strip("_").lower()
    for t in KNOWN_TABLES:
        if re.search(rf"(^|_){re.escape(t)}(_|$)", stem):
            return t.upper()
    return stem.upper() or "TABLE"


def _tables(ctx: wb.Ctx) -> dict:
    from genbi_kit import data as data_mod
    out = {}
    for f in ctx.files((".csv", ".parquet", ".xlsx")):
        if not f.get("table"):
            continue
        r = None
        name = _table_name(f["name"])
        try:
            r = ctx.reader({"source": "file", "file": f["table"]})
            cols = r.columns()
            out[name] = {"file": f["table"], "view": data_mod.raw_name(Path(f["table"])), "columns": [c["name"] for c in cols], "rows": r.count(), "kinds": {c["name"]: c["kind"] for c in cols}}
        except Exception as e:  # noqa: BLE001 - an unreadable extract is shown, not fatal
            out[name] = {"file": f["table"], "view": "", "columns": [], "rows": 0, "kinds": {}, "error": str(e)[:200]}
        finally:
            wb._close(r)
    return out


def d_describe(ctx: wb.Ctx) -> dict:
    t = _tables(ctx)
    if not t:
        raise wb.StepFailed("Upload the ERP extracts the event log comes from (CSV or Excel: e.g. SAP EKKO, EKBE, RBKP, BSAK, or Oracle PO / AP tables).")
    ctx.put("tables", t)
    bad = [k for k, v in t.items() if v.get("error")]
    return {"summary": f"{len(t)} table(s) read: " + ", ".join(f"{k} ({v['rows']:,} rows)" for k, v in t.items() if not v.get("error")) + "." + (f" Not readable: {', '.join(bad)}." if bad else ""),
            "counts": {"tables": len(t)}, "ok": len(bad) < len(t),
            "data": {"columns": ["Table", "File", "Rows", "Columns"], "rows": [[k, v["file"], v["rows"], v.get("error") or ", ".join(v["columns"][:12])] for k, v in t.items()]}}


def d_shape(ctx: wb.Ctx) -> dict:
    t = ctx.get("tables") or {}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for name, info in t.items():
        cols = {c.lower(): c for c in info["columns"]}
        key = next((cols[k] for k in CASE_KEYS if k in cols), "")
        for c in info["columns"]:
            kind = info["kinds"].get(c)
            known = SAP_ACTIVITIES.get((name.lower(), c.lower()))
            if not (known or kind == "date" or re.search(r"(dat|dt|date|time|_at)$", c.lower())):
                continue
            rid = f"{name}.{c}"
            doc = DOC_DATES.get((name.lower(), c.lower()))
            why = (f"{name}.{c} is “{known}” in the ERP's own data model" if known else f"left out: {doc}" if doc else "a date column with no known meaning — name it or leave it out") \
                + ("" if key else f"; {name} has no case key ({', '.join(CASE_KEYS)})")
            rec = {"id": rid, "include": bool(known) and bool(key), "table": name, "column": c, "activity": known or f"{name}: {c}", "case_key": key,
                   "filter": SAP_FILTERS.get((name.lower(), c.lower()), ""), "why": why}
            if rid in have:
                rec.update({k: have[rid][k] for k in ("include", "activity", "case_key", "filter") if k in have[rid]})
            recs.append(rec)
    on = [r for r in recs if r["include"]]
    return {"summary": f"{len(on)} activit{'y' if len(on) == 1 else 'ies'} from {len({r['table'] for r in on})} table(s), by the ERP's own column meanings (rules first); "
            f"{len(recs) - len(on)} other date column(s) left out. Change the names, add a filter or include a column, then confirm the design.",
            "records": recs, "counts": {"activities": len(on), "left out": len(recs) - len(on)},
            "data": {"columns": ["Include", "Table", "Column", "Activity", "Case key", "Filter", "Why"], "rows": [["yes" if r["include"] else "no", r["table"], r["column"], r["activity"], r["case_key"], r["filter"], r["why"]] for r in recs]}}


FILTER_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*(=|<>|!=)\s*'([^']*)'\s*$")


def _validate_design(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """Rules first: an included activity names a table and column that exist, a case key that table has, and a filter
    of the form COLUMN = 'value' on one of its columns."""
    t = ctx.get("tables") or {}
    on = [r for r in recs if r.get("include")]
    out = [] if len(on) >= 2 else ["include at least two activities: a log needs a start and what follows"]
    names = [str(r.get("activity") or "").strip().lower() for r in on]
    for r in on:
        info = t.get(r.get("table") or "")
        where = f"{r.get('table')}.{r.get('column')}"
        if not info or not info.get("columns"):
            out.append(f"{where}: no readable table {r.get('table')!r}")
            continue
        cols = {c.lower(): c for c in info["columns"]}
        if (r.get("column") or "").lower() not in cols:
            out.append(f"{where}: no column {r.get('column')!r} in {r['table']}")
        if (r.get("case_key") or "").strip().lower() not in cols:
            out.append(f"{where}: {r['table']} has no case key column {r.get('case_key')!r}")
        if not str(r.get("activity") or "").strip():
            out.append(f"{where}: name the activity")
        elif names.count(str(r["activity"]).strip().lower()) > 1:
            out.append(f"{where}: two columns are both “{r['activity']}” — name them apart")
        if (r.get("filter") or "").strip():
            m = FILTER_RE.match(r["filter"])
            if not m or m.group(1).lower() not in cols:
                out.append(f"{where}: the filter must look like COLUMN = 'value' on a column of {r['table']}")
    return out


DESIGN_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("table", "Table", readonly=True), wb.Column("column", "Date column", readonly=True),
                               wb.Column("activity", "Activity"), wb.Column("case_key", "Case key"), wb.Column("filter", "Filter", help="e.g. BEWTP = 'E' (goods receipts only)"),
                               wb.Column("why", "Why", readonly=True)], add=False, remove=False, validate=_validate_design, label="activity")


def _qi(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _ql(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _col(info: dict, name: str) -> str:
    """The column as the table spells it (a person may type ebeln for EBELN)."""
    return {c.lower(): c for c in info["columns"]}.get(str(name).strip().lower(), str(name).strip())


def _ts(info: dict, col: str) -> str:
    """A date column as a timestamp, whatever the extract wrote: a DATE / TIMESTAMP, SAP's 20261006 or 06.10.2026."""
    q = _qi(col)
    kind = info["kinds"].get(col)
    if kind == "date":
        return f"CAST({q} AS TIMESTAMP)"
    if kind in ("number", "integer", "int"):
        return f"strptime(CAST({q} AS VARCHAR), '%Y%m%d')"
    return f"COALESCE(TRY_CAST({q} AS TIMESTAMP), try_strptime(CAST({q} AS VARCHAR), '%Y%m%d'), try_strptime(CAST({q} AS VARCHAR), '%d.%m.%Y'))"


def _cond(info: dict, r: dict, keyed: bool = True) -> str:
    """The rows of a table that are this activity: its date is there, the person's filter (checked above) holds and —
    unless `keyed` is False — the row has a case key."""
    out = f"{_ts(info, _col(info, r['column']))} IS NOT NULL"
    m = FILTER_RE.match(r.get("filter") or "")
    if m:
        out += f" AND CAST({_qi(_col(info, m.group(1)))} AS VARCHAR) {'<>' if m.group(2) != '=' else '='} {_ql(m.group(3))}"
    if keyed:
        out += f" AND NULLIF(TRIM(CAST({_qi(_col(info, r['case_key']))} AS VARCHAR)), '') IS NOT NULL"
    return out


def _sql(ctx: wb.Ctx, rows: list[dict]) -> str:
    t = ctx.get("tables") or {}
    parts = []
    for i, r in enumerate(rows, 1):
        info = t[r["table"]]
        parts.append(f"SELECT CAST({_qi(_col(info, r['case_key']))} AS VARCHAR) AS case_id, {_ql(r['activity'].strip())} AS activity, "
                     f"{_ts(info, _col(info, r['column']))} AS timestamp, {_ql(r['table'])} AS source_table, {i} AS step_order FROM {_qi(info['view'])} WHERE {_cond(info, r)}")
    return "\nUNION ALL\n".join(parts) + "\nORDER BY case_id, timestamp, step_order"


def _duck(ctx: wb.Ctx):
    from genbi_kit import data as data_mod
    return data_mod.connect(ctx.dir)


def d_build(ctx: wb.Ctx) -> dict:
    rows = [r for r in ctx.records("shape") if r.get("include")]
    probs = _validate_design(rows, ctx)
    if probs:
        raise wb.StepFailed("The design has problems: " + "; ".join(probs[:4]))
    sql = _sql(ctx, rows)
    con = _duck(ctx)
    try:
        res = con.execute(sql).fetchall()
    except Exception as e:  # noqa: BLE001 - a date the extract writes some other way: shown, with Shape to fix it
        raise wb.StepFailed(f"The event log could not be built: {str(e).splitlines()[0][:300]}") from e
    finally:
        con.close()
    text = _w4.csv_text(["case_id", "activity", "timestamp", "source_table"], [[a, b, c.isoformat() if hasattr(c, "isoformat") else c, d] for a, b, c, d, _ in res])
    ctx.output("eventlog.csv", text, label="The event log (CSV)")
    ctx.output("eventlog.sql", sql + "\n", label="The event log's SQL (DuckDB; the same shape runs on the warehouse)")
    import yaml
    ctx.output("kpis.yaml", yaml.safe_dump({"kpis": [{"name": "Throughput time", "formula": "median of (last event − first event) per case", "unit": "hours"},
                                                     {"name": "Rework rate", "formula": "share of cases with an activity done more than once"},
                                                     {"name": "Slowest wait", "formula": "the directly-follows pair with the largest total waiting time"}],
                                            "activities": [{"activity": r["activity"], "from": f"{r['table']}.{r['column']}", "case_key": r["case_key"], "filter": r.get("filter") or None} for r in rows]},
                                           sort_keys=False, allow_unicode=True), label="The KPIs and the activities (YAML)")
    ctx.put("built", {"events": len(res), "cases": len({x[0] for x in res}), "sha256": hashlib.sha256(text.encode()).hexdigest()})
    job = ctx.lineage_node("job", "Relay event log", ctx.id, label=f"Event log: {ctx.title}", properties={"events": len(res)})
    for tname in sorted({r["table"] for r in rows}):
        src = ctx.lineage_node("table", "ERP extract", tname, label=tname, own=False)
        ctx.lineage_edge(src, job, "reads", {"columns": [r["column"] for r in rows if r["table"] == tname]})
    return {"summary": f"The event log is built: {len(res):,} events in {len({x[0] for x in res}):,} cases from {len(rows)} activit{'y' if len(rows) == 1 else 'ies'} (DuckDB), with its SQL and the KPI definitions.",
            "counts": {"events": len(res), "activities": len(rows)},
            "data": {"columns": ["Activity", "Table", "Column", "Filter"], "rows": [[r["activity"], r["table"], r["column"], r.get("filter") or ""] for r in rows]}}


def d_prove(ctx: wb.Ctx) -> dict:
    rows = [r for r in ctx.records("shape") if r.get("include")]
    t = ctx.get("tables") or {}
    checks = []
    con = _duck(ctx)
    try:
        expected, unkeyed, per = 0, 0, []
        for r in rows:
            info = t[r["table"]]
            n = con.execute(f"SELECT COUNT(*) FROM {_qi(info['view'])} WHERE {_cond(info, r)}").fetchone()[0]
            k = con.execute(f"SELECT COUNT(*) FROM {_qi(info['view'])} WHERE {_cond(info, r, keyed=False)}").fetchone()[0] - n
            expected += n
            unkeyed += k
            per.append({"activity": r["activity"], "from": f"{r['table']}.{r['column']}", "filter": r.get("filter") or "", "events": n, "no case key": k})
        built = (ctx.get("built") or {}).get("events")
        checks.append({"name": "row_count", "label": "Every event reconciles with a date in the tables", "status": "pass" if built == expected else "fail", "measured": built, "expected": expected,
                       "detail": f"{built} events built, {expected} dated rows with a case key in the tables" + (f"; {unkeyed} dated row(s) with no case key set aside (e.g. a requisition not yet ordered)" if unkeyed else ""),
                       "evidence": ctx.evidence("Events per activity", {"rows": per}, kind="proof", ok=built == expected)})
        head = next((r for r in rows if r["table"] in HEADER_TABLES), rows[0])
        hi = t[head["table"]]
        keys = [str(x[0]).strip() for x in con.execute(f"SELECT DISTINCT CAST({_qi(_col(hi, head['case_key']))} AS VARCHAR) FROM {_qi(hi['view'])}").fetchall() if x[0] is not None]
        refs = []
        for r in rows:
            if r is head:
                continue
            info = t[r["table"]]
            refs += [str(x[0]).strip() for x in con.execute(f"SELECT DISTINCT CAST({_qi(_col(info, r['case_key']))} AS VARCHAR) FROM {_qi(info['view'])} WHERE {_cond(info, r)}").fetchall()]
        span = con.execute("SELECT MIN(timestamp), MAX(timestamp) FROM read_csv_auto(?, header = true)", [str(ctx.dir / "outputs" / "eventlog.csv")]).fetchone()
    finally:
        con.close()
    checks.append(ctx.proof("references_real", label=f"Every case is an order in {head['table']} (its “{head['activity'].lower()}”)", refs=sorted(set(refs)), known=keys))
    lo, hi_ = span
    plausible = bool(lo and hi_) and str(lo)[:4] >= "1990" and str(hi_)[:10] <= time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400))
    checks.append({"name": "dates", "label": "The dates are plausible: none in the future, none before 1990", "status": "pass" if plausible else "fail", "measured": f"{str(lo)[:10]} to {str(hi_)[:10]}",
                   "detail": "every event between the two" if plausible else "a date column read the wrong way — check its format in Shape"})
    lg = _w4.read_eventlog(ctx.dir / "outputs" / "eventlog.csv")
    an = analyse(lg) if lg and lg["events"] else None
    if an:
        ctx.put("kpis", _kpis(an))
        checks.append({"name": "kpis", "label": f"KPIs: throughput {an['throughput_h']} h median, rework {an['rework_rate']:.0%}, {an['variants']} variant(s)", "status": "pass",
                       "detail": f"slowest wait: {an['waits'][0]['from']} → {an['waits'][0]['to']} ({an['waits'][0]['median_h']} h median)" if an["waits"] else "",
                       "evidence": ctx.evidence("The KPIs on the built log", {k: an[k] for k in ("cases", "events", "variants", "throughput_h", "throughput_p90_h", "rework_rate", "waits", "top")}, kind="proof", ok=True)})
    bad = [c for c in checks if c["status"] == "fail"]
    return {"summary": f"{len(checks)} proof(s): " + ("every event reconciles, every case is an order and the dates are plausible" if not bad
                                                      else f"{len(bad)} fail ({bad[0]['detail'][:120]}) — send it back to Shape, or confirm with the reason") + ".",
            "data": {"checks": checks}, "counts": {"failing": len(bad)}}


def _kpis(an: dict) -> dict:
    """What a Run item compares each round with: the KPIs and every wait between two activities (its median)."""
    return {"throughput_h": an["throughput_h"], "rework_rate": an["rework_rate"], "variants": an["variants"], "slowest": an["waits"][0] if an["waits"] else None, "pairs": an["pairs"]}


def d_ship(ctx: wb.Ctx) -> dict:
    k = ctx.get("kpis") or {}
    cel = _w4.tracker_connection(ctx, ("celonis",))
    return {"summary": f"Go live: the event log ({(ctx.get('built') or {}).get('events')} events) and its KPIs" + (f", loaded into {cel['name']} after its own approval" if cel else "") + ", watched on a schedule.",
            "data": {"items": [{"title": "The event log", "detail": f"{(ctx.get('built') or {}).get('events')} events — eventlog.csv and its SQL"},
                               {"title": "The KPIs today", "detail": f"throughput {k.get('throughput_h')} h, rework {k.get('rework_rate', 0):.0%}, {k.get('variants')} variant(s)"},
                               {"title": "Then", "detail": "a Run item compares them with today's on its schedule; a drift waits for a person before anything goes out"}]}}


def d_run(ctx: wb.Ctx) -> dict:
    """Go live: the event log loaded into Celonis after its own approval (asked again only when the last load failed),
    and a Run item that watches the KPIs on the cadence chosen in the wizard."""
    cel = _w4.tracker_connection(ctx, ("celonis",))
    built = ctx.get("built") or {}
    last = _w4.push_of(ctx.id, "run")
    if cel and (not last or last["status"] == "failed"):
        if not connectors.may_write(cel):
            raise wb.StepFailed(f"{cel['name']} is read-only: change its scope to “Read & write — with approval” to load the event log, or remove it.")
        _w4.request_push(ctx, cel["id"], "eventlog", {"file": "eventlog.csv", "sha256": built.get("sha256"), "table": "RELAY_P2P_EVENT_LOG"},
                         f"Load the event log ({built.get('events')} events) into {cel['name']}", step="run",
                         items=[f"Events: {built.get('events')} in {built.get('cases')} cases", "Into: the data pool's table RELAY_P2P_EVENT_LOG (replaced)", f"File: eventlog.csv (sha256 {str(built.get('sha256'))[:12]}…)"])
    run_id = ctx.get("run_item")
    if not run_id or not db.one("SELECT 1 FROM wb_items WHERE id = ? AND closed IS NULL", (run_id,)):
        cad = ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}
        p = db.project(ctx.id) or {}
        it = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Scheduled KPI checks of the event log built in {ctx.id}.",
                       scope={"from_item": ctx.id, "baseline": ctx.get("kpis") or {}, "schedule": cad, "_source_ok": True},
                       approver=ctx.st.get("approver"), visibility=p.get("visibility") or "private", team_id=p.get("team_id"), parent=ctx.id)
        run_id = it["id"]
        ctx.put("run_item", run_id)
    return d_run_state(ctx)


def d_run_state(ctx: wb.Ctx) -> dict:
    """What the Run step says now (also redrawn when the load is approved, written or fails)."""
    p = _w4.push_of(ctx.id, "run")
    run_id = ctx.get("run_item")
    load = ""
    if p:
        res = p["result"] or {}
        load = {"awaiting": "; loading the event log into Celonis is waiting for its own approval", "written": f"; the event log is written to Celonis ({res.get('rows')} rows, push job {((res.get('created') or [{}])[0]).get('key')})",
                "failed": f"; loading into Celonis failed ({str(res.get('error') or '')[:160]}) — run the step again to ask for a new approval"}.get(p["status"], "")
    return {"summary": "Live: a Run item watches the KPIs on its schedule" + load + ".", "ok": not (p and p["status"] == "failed"),
            "data": {"href": f"#/m/{MODULE}/i/{run_id}", "label": "Open the Run item", "text": f"The KPIs today: throughput {(ctx.get('kpis') or {}).get('throughput_h')} h median, rework {(ctx.get('kpis') or {}).get('rework_rate', 0):.0%}."}}


_w4.REFRESH["mining.run"] = d_run_state


# ------------------------------------------------------------------ Run & support

def _run_log(ctx: wb.Ctx) -> dict | None:
    """This round's log: the newest upload that reads as events, else the connection's records, else the event log the
    Develop item built (its outputs)."""
    srcs = _sources(ctx)
    when = {f["name"]: f.get("when") or 0 for f in ctx.files(UPLOADS)}
    for s in sorted(srcs, key=lambda s: -when.get(s["source"], 0)):
        rec = {"source": s["source"], "kind": s["kind"], "key": s.get("key") or _w4.slug(s["source"], 40), **((_w4.eventlog_columns(s["header"]) if s["header"] else None) or {})}
        lg = _read(ctx, rec)
        if lg and lg["events"]:
            return {**lg, "source": s["source"]}
    src = ctx.scope.get("from_item")
    if src:
        p = wb.folder(src) / "outputs" / "eventlog.csv"
        if p.exists():
            lg = _w4.read_eventlog(p)
            if lg:
                return {**lg, "source": f"the event log built in {src}"}
    return None


def r_watch(ctx: wb.Ctx) -> dict:
    lg = _run_log(ctx)
    if not lg:
        raise wb.StepFailed("There is no event log to watch: the Develop item's log is gone and nothing is uploaded or connected here.")
    an = analyse(lg)
    base = ctx.scope.get("baseline") or ctx.get("baseline") or {}
    first = not base
    if first:
        base = _kpis(an)
        ctx.put("baseline", base)
    rows = []

    def gate(name, label, now, then, limit, unit):
        if not then:
            rows.append({"name": name, "label": label, "status": "pass", "measured": f"{now}{unit}", "detail": "the first baseline" if first else "no baseline for it"})
            return
        ch = (now - then) / then
        rows.append({"name": name, "label": label, "status": "fail" if ch > limit else "pass", "measured": f"{now}{unit}", "expected": f"within {limit:.0%} of {then}{unit}",
                     "detail": f"{then}{unit} at the baseline, {now}{unit} now ({ch:+.0%})"})
    gate("throughput", "Throughput time (median)", an["throughput_h"], base.get("throughput_h"), 0.2, " h")
    gate("rework", "Rework rate", round(an["rework_rate"] * 100, 1), round((base.get("rework_rate") or 0) * 100, 1), 0.3, " %")
    grew = sorted(((p, now, base["pairs"][p]) for p, now in an["pairs"].items() if (base.get("pairs") or {}).get(p) is not None), key=lambda x: -(x[1] - x[2]))
    if grew and grew[0][1] - grew[0][2] > 0:
        p, now, then = grew[0]
        ch = (now - then) / then if then else 1.0
        rows.append({"name": "wait", "label": f"The wait that grew most: {p}", "status": "fail" if (now - then) >= 24 and ch > 0.5 else "pass", "measured": f"{now} h median",
                     "expected": f"within 50 % (or a day) of {then} h", "detail": f"{then} h at the baseline, {now} h now"})
    ctx.put("analysis", {k: an[k] for k in ("cases", "events", "variants", "throughput_h", "throughput_p90_h", "rework_rate", "waits", "pairs")})
    ctx.put("grew", [{"pair": p, "now": n_, "then": t_} for p, n_, t_ in grew[:3]])
    ctx.put("results", rows)
    ctx.evidence(f"Mined: {lg['source']}", {"rows": [{"variant": " → ".join(v["path"]), "cases": v["cases"]} for v in an["top"]], "waits": an["waits"], "baseline": base}, kind="mining", ok=True)
    bad = sum(1 for r in rows if r["status"] == "fail")
    return {"summary": f"{lg['source']}: {an['cases']} cases, throughput {an['throughput_h']} h median — " + (f"{bad} KPI(s) drifted from the baseline." if bad else "every KPI within its limit."),
            "data": {"checks": rows}, "counts": {"cases": an["cases"], "drifted": bad}}


def r_alert(ctx: wb.Ctx) -> dict:
    bad = [r for r in ctx.get("results") or [] if r["status"] == "fail"]
    if not bad:
        ctx.put("breaks", [])
        return {"summary": "Every KPI is within its limit: nothing to alert.", "next": "report", "counts": {"breaks": 0}}
    g = (ctx.get("grew") or [None])[0]
    cause = f"the wait {g['pair']} grew from {g['then']} h to {g['now']} h (median)" if g else "no single wait explains it — look at the variants"
    brks = [{"id": f"b-{r['name']}", "kpi": r["label"], "what": r["detail"], "cause": cause if r["name"] in ("throughput", "wait") else "more cases are done twice: look at the rework in the variants",
             "route": "ticket", "note": ""} for r in bad]
    ctx.put("breaks", brks)
    return {"summary": f"{len(brks)} KPI(s) drifted, grouped with their likely cause: {cause}.", "counts": {"breaks": len(brks)}, "items": [f"{b['kpi']}: {b['what']}" for b in brks],
            "data": {"columns": ["KPI", "What", "Likely cause"], "rows": [[b["kpi"], b["what"], b["cause"]] for b in brks]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **({k: have[b["id"]][k] for k in ("route", "note") if k in have[b["id"]]} if b["id"] in have else {})} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} drift(s): choose who looks at each — a ticket for the process owner, or expected. Nothing goes out until you confirm.", "records": recs,
            "data": {"columns": ["KPI", "Route", "Likely cause"], "rows": [[r["kpi"], r["route"], r["cause"]] for r in recs]}}


FIX_EDIT = wb.Edit(columns=[wb.Column("route", "Route", "select", options=(("ticket", "Raise a ticket"), ("expected", "Expected — no action"))), wb.Column("note", "Note", "longtext"),
                            wb.Column("kpi", "KPI", readonly=True), wb.Column("cause", "Likely cause", readonly=True)], add=False, remove=False, label="drift")


def r_approve(ctx: wb.Ctx) -> dict:
    rows = []
    for b in ctx.records("fix"):
        if b["route"] == "ticket":
            h = ctx.ticket(f"Process KPI drift: {b['kpi']}", f"{b['what']}\n\nLikely cause: {b['cause']}\n\n{b.get('note') or ''}\nWork item: {wb.route_of(ctx.st)}", priority="P3", about=b["kpi"])
        else:
            h = {"kind": "expected", "status": "expected — recorded"}
        rows.append([b["kpi"], b["route"], h.get("status"), h.get("output") or h.get("checkpoint") or ""])
    return {"summary": f"{sum(1 for r in rows if r[1] == 'ticket')} ticket(s), {sum(1 for r in rows if r[1] != 'ticket')} expected — as you approved.", "data": {"columns": ["KPI", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    an = ctx.get("analysis") or {}
    rows = [[r["label"], r["status"], r["detail"]] for r in ctx.get("results") or []]
    text = f"# Process report: {ctx.title}\n\n{time.strftime('%d %B %Y', time.gmtime())}\n\n- Cases: {an.get('cases')}\n- Throughput (median): {an.get('throughput_h')} h\n- Rework rate: {an.get('rework_rate', 0):.0%}\n- Variants: {an.get('variants')}\n\n" + "".join(f"- {r[0]}: {r[1]} — {r[2]}\n" for r in rows)
    ctx.output(f"process-report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", text, label="Process report (Markdown)")
    return {"summary": f"The process this round: {an.get('cases')} cases, throughput {an.get('throughput_h')} h, rework {an.get('rework_rate', 0):.0%}.", "data": {"columns": ["KPI", "Status", "Detail"], "rows": rows}}


# ------------------------------------------------------------------ the module page

def _on_done(ctx: wb.Ctx) -> None:
    """An assessment ends with the ranking as the person confirmed it (their minutes per event, their routes)."""
    if ctx.work != "assess":
        return
    recs = sorted(ctx.records("estimate"), key=lambda r: -float(r.get("hours") or 0))
    if not recs:
        return
    ctx.output("automate-first.md", "# What to automate first\n\n" + "\n".join(
        f"{i}. {r['activity']}: {r['per_month']} a month × {r['minutes']} min = {r['hours']} h a month → {dict(ROUTES).get(r['route'], r['route'])}" for i, r in enumerate(recs, 1))
        + "\n\nThe minutes per event are the assumptions confirmed in the Estimate step.\n"
        + "".join(f"\nWhat-if on {w['source']}: median throughput {w['before']['throughput_h']} h → {w['after']['throughput_h']} h, {w['hours_saved']} h a month of people's work saved.\n"
                  for w in (ctx.get("whatif") or {}).values()), label="What to automate first (Markdown)")
    wb._mutate(ctx.id, lambda s: wb._save_ctx(ctx, s))


def _cards(u: dict) -> list[dict]:
    rows = db.q("SELECT id, title, status, next_run FROM wb_items WHERE module = ? AND work = 'run' AND closed IS NULL ORDER BY updated DESC", (MODULE,))
    rows = _w4.visible_items(u, [{**r, "item": r["id"]} for r in rows])
    return [{"title": "Watched processes", "columns": ["Run item", "Status", "Next check", "Open"], "rows": [[r["title"], r["status"], _w4.when(r.get("next_run")), f"#/m/{MODULE}/i/{r['id']}"] for r in rows],
             "empty": "Nothing is watched yet: a Develop item's Run step starts a Run item."}]


def _process_options(u: dict) -> list[tuple[str, str]]:
    try:
        from . import processdocs
        return [("", "No — just mine the logs")] + processdocs.process_options(u)
    except Exception:  # noqa: BLE001
        return [("", "No — just mine the logs")]


wb.register(wb.Pack(
    module=MODULE,
    guide="# Process mining & discovery — the work item\n\nEvent logs are mined by rules here; nothing is drafted by an agent. Every figure comes from the log.",
    lineage="the event log built from ERP tables as a job that reads them",
    platforms={"files": FILES, "mining": MINING},
    schemas={"log": INV_EDIT.columns, "activity": DESIGN_EDIT.columns},
    cards=_cards,
    on_done=_on_done,
    work={
        "assess": wb.Work(title="See how the work really runs — variants, delays, rework — and what to automate first", platforms=("files", "mining"), steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Connector", text="Celonis or Signavio PI tested with your key, uploads opened — read-only"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Log reader", edit=INV_EDIT, text="Every event log with its cases, events and period, and the columns Relay found — you correct them"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Miner", text="Mined by rules: variants, throughput, waits, rework, ping-pong; the rows reconcile; the fit with a published process"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="Delays, rework, ping-pong and other endings — keep or ignore each"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", edit=EST_EDIT, confirm="what to automate first, with the minutes per event you set",
                                text="What to automate first: the activities people do, ranked by the hours a month they take — and a what-if on the real log",
                                actions={"whatif": wb.Action(label="Run the what-if", kind="platform", run=a_whatif, agent="Simulator",
                                                             help="Replays the event log with the share a bot takes, the cut in each wait and the re-work stopped, as set per activity.")})},
            fields=[wb.Field("process", "Compare with a published process", "select", options=_process_options, help="Its BPMN map is checked against the log (conformance).")]),
        "develop": wb.Work(title="Build an event log from SAP or Oracle extracts, prove it, load it and watch it", platforms=("files", "mining"), steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Connector", text="The ERP extracts are read: tables, rows and columns"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Log designer", edit=DESIGN_EDIT, text="Activities from the ERP's own date columns (rules first), with the case key and filters — you confirm the design"),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Log builder", text="The event log built with DuckDB, with its SQL and the KPI definitions"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="Every event reconciles with a date in the tables; every case has its key; the KPIs on the built log"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver takes it live"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="Loaded into Celonis after its own approval; a Run item watches the KPIs")},
            fields=[wb.Field("cadence", "Once live, check the KPIs", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
        "run": wb.Work(title="Watch the process's KPIs on a schedule; a drift goes to a person first", needs_source=False, platforms=("files", "mining"), steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Watcher", text="The log read again and its KPIs compared with the baseline"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="A drift with its likely cause"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=FIX_EDIT, text="Relay proposes who looks at each drift; you confirm"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="The process report; you confirm it when something drifted")},
            fields=[wb.Field("schedule", "Check it", "cadence", default={"every": "day", "at": "06:00", "tz": "UTC"})]),
    }))
