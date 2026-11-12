"""Controls & compliance (registry id `controls`) - internal controls mapped to processes, systems and owners; their
evidence collected by rules from the data the process leaves behind; tested on a schedule; changed with a named
approval. SOX / ICFR risk & control matrices come in as an Excel tracker or an AuditBoard / SAP GRC export; statutory
evidence (GSTR-1 against the sales register, Form 26AS from TRACES against the TDS books, MCA filings) as files.

Assess   Connect -> Inventory -> Health -> Findings -> Estimate: the matrix read in its own terms; gaps by rules (a key
         control with no owner, not tested within its frequency, failed last time, duplicates, a process nobody
         published); findings kept or ignored; the testing effort a year, and what Relay's evidence rules save.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: each control's evidence rule proposed by rules (a tie-out of
         two files by period, segregation of duties, a threshold, a document that must exist, or manual) - a person
         corrects it in place (what cannot run is refused); the evidence collected (DuckDB, the engine's totals proof
         for tie-outs); every control's result proven with its evidence; the named approver takes it live; the
         library published and a scheduled Run item.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: one control changed in place, re-run on its data, approved,
         kept as a new version.
Run      Watch -> Alert -> Fix -> Approve -> Report: the live controls run on the newest data each period; exceptions per
         control with their owner; a person routes each (a ticket, or accepted with the reason); the period's report.
"""
from __future__ import annotations

import fnmatch
import json
import re
import time
from pathlib import Path

from .. import db
from .. import workbench as wb
from . import _w4

MODULE = "controls"
UPLOADS = (".xlsx", ".csv", ".pdf", ".docx", ".png", ".jpg", ".json")
KINDS = (("tieout", "Tie-out of two files"), ("sod", "Segregation of duties"), ("threshold", "Threshold"), ("evidence", "A document must exist"), ("manual", "Manual (the owner attaches evidence)"))
FREQ = {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "half-yearly": 183, "annual": 366, "yearly": 366}
PER_YEAR = {"daily": 250, "weekly": 52, "monthly": 12, "quarterly": 4, "half-yearly": 2, "annual": 1, "yearly": 1}
COLS = {"id": ("control id", "control_id", "control ref", "ref", "id", "control number"), "name": ("control", "control description", "description", "name", "title"),
        "process": ("process", "business process", "cycle"), "risk": ("risk", "risk description"), "owner": ("owner", "control owner"), "frequency": ("frequency",),
        "key": ("key", "key control"), "type": ("type", "nature", "automated/manual"), "evidence": ("evidence", "evidence required"),
        "last_tested": ("last tested", "last test date", "tested on"), "result": ("result", "last result", "test result", "conclusion")}
MEASURES = ("taxable_value", "igst", "cgst", "sgst", "cess", "tds_amount", "amount", "value", "total")
BY = ("period", "month", "quarter", "tax_period", "return_period")
USER_PAIRS = (("requested_by", "approved_by"), ("created_by", "approved_by"), ("maker", "checker"), ("prepared_by", "reviewed_by"), ("raised_by", "released_by"))
EXPR = re.compile(r"^\s*([A-Za-z_]\w*)\s*(=|<>|!=|<=|>=|<|>)\s*(-?\d+(?:\.\d+)?|'[^']*')\s*$")
MINUTES = {"manual": 45, "automated": 10}

db.register_schema("""
CREATE TABLE IF NOT EXISTS controls_library (
  id TEXT PRIMARY KEY, item TEXT, name TEXT NOT NULL, process TEXT, process_id TEXT, owner TEXT, frequency TEXT, key_control INTEGER NOT NULL DEFAULT 0,
  rule TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'live', last_result TEXT, last_run REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS controls_versions (
  control TEXT NOT NULL, version INTEGER NOT NULL, item TEXT, record TEXT NOT NULL, by_id TEXT, at REAL NOT NULL, note TEXT, PRIMARY KEY (control, version));
""")

FILES = wb.FilesPlatform()
FILES.label = "Control matrices, trackers and evidence"
FILES.uploads = UPLOADS
FILES.reads = ("a risk & control matrix (an Excel tracker, an AuditBoard or SAP GRC export) and the data and documents the evidence comes from - "
               "GSTR-1 and the sales register, Form 26AS (TRACES) and the TDS books, approvals and payments extracts, signed reconciliations")
FILES.simulator = "synthetic fixtures in tests/mocklab/fixtures/controls/ (a 2026 matrix, approvals, payments, GSTR-1, 26AS, a signed bank reconciliation)"


# ------------------------------------------------------------------ reading what was uploaded

def _rows(p: Path) -> tuple[list[str], list[dict]]:
    import csv
    if p.suffix.lower() == ".xlsx":
        import openpyxl
        book = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        try:
            vals = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
        finally:
            book.close()
    elif p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="", errors="replace") as fh:
            vals = list(csv.reader(fh))
    else:
        return [], []
    vals = [r for r in vals if r and any(str(v or "").strip() for v in r)]
    if not vals:
        return [], []
    head = [str(h or "").strip() for h in vals[0]]
    return head, [{h: ("" if v is None else str(v).strip()) for h, v in zip(head, r)} for r in vals[1:]]


def _pick(head: list[str], names: tuple) -> str | None:
    low = {h.lower(): h for h in head}
    return next((low[n] for n in names if n in low), None)


def _matrix(ctx: wb.Ctx) -> tuple[str | None, list[dict]]:
    """The first upload that reads as a control matrix (it has a control id and a control column), as records."""
    for f in ctx.files((".xlsx", ".csv")):
        head, rows = _rows(ctx.dir / "data" / f["name"])
        m = {k: _pick(head, v) for k, v in COLS.items()}
        if not (m["id"] and m["name"]):
            continue
        out = []
        for r in rows:
            rec = {k: (r.get(col) or "") if col else "" for k, col in m.items()}
            if rec["id"]:
                rec["key"] = "yes" if rec["key"].lower() in ("yes", "y", "true", "key", "1") else "no"
                rec["type"] = "automated" if "auto" in rec["type"].lower() else "manual"
                rec["frequency"] = rec["frequency"].lower()
                out.append(rec)
        return f["name"], out
    return None, []


def _data(ctx: wb.Ctx, item: str | None = None) -> dict:
    """The data files an item holds (not the matrix): name -> {"table", "columns", "when"}."""
    st = wb._load(item) if item and item != ctx.id else ctx.st
    mat = (ctx.get("matrix") or "") if not item or item == ctx.id else ""
    out = {}
    for f in st.get("files") or []:
        if f.get("table") and f["name"] != mat:
            head, _ = _rows(wb.folder(st["id"]) / "data" / f["table"]) if f["table"].endswith(".csv") else ([], [])
            if not head and f["name"].endswith(".xlsx"):
                head, _ = _rows(wb.folder(st["id"]) / "data" / f["name"])
            out[f["name"]] = {"table": f["table"], "columns": head, "when": f.get("when") or 0, "item": st["id"]}
    return out


def _docs(ctx: wb.Ctx, item: str | None = None) -> list[str]:
    st = wb._load(item) if item and item != ctx.id else ctx.st
    return [f["name"] for f in st.get("files") or []]


def _people() -> dict:
    return {(u.get("email") or "").lower(): u for u in db.q("SELECT id, name, email FROM users")}


def _stem(s: str) -> set:
    return {w[:5] for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in ("than", "with", "from", "that", "have", "each", "someone", "other")}


# ------------------------------------------------------------------ Assess

def a_connect(ctx: wb.Ctx) -> dict:
    fs = ctx.files(UPLOADS)
    if not fs:
        raise wb.StepFailed("Upload the control matrix (an Excel tracker, or an AuditBoard / SAP GRC export) and any evidence files.")
    return {"summary": f"{len(fs)} upload(s), read-only copies in this work item.", "data": {"columns": ["File", "Size"], "rows": [[f["name"], f"{f['bytes']:,} bytes"] for f in fs]}}


def a_inventory(ctx: wb.Ctx) -> dict:
    name, recs = _matrix(ctx)
    if not recs:
        raise wb.StepFailed("No control matrix found: a matrix has a Control ID and a Control column (Excel or CSV).")
    ctx.put("matrix", name)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**r, **{k: have[r["id"]][k] for k in ("owner", "frequency", "key") if r["id"] in have}} for r in recs]
    return {"summary": f"{len(recs)} control(s) in {name}, in the matrix's own terms - {sum(1 for r in recs if r['key'] == 'yes')} key, "
            f"{sum(1 for r in recs if r['type'] == 'automated')} automated. Correct what is wrong, then confirm.", "records": recs,
            "counts": {"controls": len(recs), "key": sum(1 for r in recs if r["key"] == "yes")},
            "data": {"columns": ["Control", "Name", "Process", "Owner", "Frequency", "Key", "Last tested", "Result"],
                     "rows": [[r["id"], r["name"], r["process"], r["owner"] or "-", r["frequency"], r["key"], r["last_tested"], r["result"]] for r in recs]}}


def _validate_inventory(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out, seen = [], set()
    for r in recs:
        if r["id"] in seen:
            out.append(f"{r['id']} is listed twice")
        seen.add(r["id"])
        if (r.get("frequency") or "").lower() not in FREQ:
            out.append(f"{r['id']}: the frequency is one of {', '.join(FREQ)}")
        r["frequency"] = (r.get("frequency") or "").lower()
        r["key"] = "yes" if str(r.get("key")).lower() in ("yes", "y", "true", "1") else "no"
    return out


INV_EDIT = wb.Edit(columns=[wb.Column("id", "Control", readonly=True), wb.Column("name", "Name", readonly=True), wb.Column("owner", "Owner (e-mail)"),
                            wb.Column("frequency", "Frequency"), wb.Column("key", "Key", "select", options=(("yes", "Key"), ("no", "Not key"))),
                            wb.Column("last_tested", "Last tested", readonly=True), wb.Column("result", "Last result", readonly=True)], add=False, remove=False, validate=_validate_inventory, label="control")


def _gaps(recs: list[dict], ctx: wb.Ctx) -> list[dict]:
    """Rules, no AI: what an auditor would ask about first."""
    from . import processdocs
    u = db.user(ctx.owner or "") or {}
    published = {p["name"].lower() for p in processdocs.processes(u)} if u else set()
    people = _people()
    now = time.time()
    out = []
    for r in recs:
        if not r.get("owner"):
            out.append({"id": f"owner-{r['id']}", "control": r["id"], "kind": "no owner", "status": "fail" if r["key"] == "yes" else "warn", "what": f"{r['id']} ({r['name']}) has no owner"})
        elif r["owner"].lower() not in people:
            out.append({"id": f"who-{r['id']}", "control": r["id"], "kind": "owner unknown", "status": "warn", "what": f"{r['id']}: its owner {r['owner']} is not a person in this workspace"})
        t = _w4.parse_time(r.get("last_tested"))
        days = FREQ.get(r.get("frequency"), 366)
        if not t:
            out.append({"id": f"never-{r['id']}", "control": r["id"], "kind": "never tested", "status": "fail" if r["key"] == "yes" else "warn", "what": f"{r['id']} has no test date"})
        elif now - t > max(days * 1.5, 45) * 86400 and now - t > 365 * 86400:
            out.append({"id": f"stale-{r['id']}", "control": r["id"], "kind": "not tested", "status": "fail" if r["key"] == "yes" else "warn",
                        "what": f"{r['id']} ({r['frequency']}) was last tested on {r['last_tested']} - more than a year ago"})
        if (r.get("result") or "").lower().startswith(("not", "ineffective", "fail", "deficien")):
            out.append({"id": f"failed-{r['id']}", "control": r["id"], "kind": "failed last test", "status": "warn", "what": f"{r['id']} failed its last test ({r['result']}): is it remediated?"})
        if published and (r.get("process") or "").lower() not in published:
            out.append({"id": f"proc-{r['id']}", "control": r["id"], "kind": "process not documented", "status": "warn", "what": f"{r['id']}: no published process document for \"{r['process']}\""})
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            sa, sb = _stem(a["name"]), _stem(b["name"])
            if sa and sb and len(sa & sb) >= 2 and len(sa & sb) / min(len(sa), len(sb)) >= 0.6:
                out.append({"id": f"dup-{a['id']}-{b['id']}", "control": f"{a['id']} / {b['id']}", "kind": "duplicate", "status": "warn",
                            "what": f"{a['id']} and {b['id']} test the same thing: \"{a['name']}\" / \"{b['name']}\""})
    return out


def a_health(ctx: wb.Ctx) -> dict:
    recs = ctx.records("inventory")
    gaps = _gaps(recs, ctx)
    ctx.put("gaps", gaps)
    by = {}
    for g in gaps:
        by.setdefault(g["kind"], []).append(g)
    checks = [{"name": k.replace(" ", "_"), "label": k[0].upper() + k[1:], "status": "fail" if any(x["status"] == "fail" for x in v) else "warn", "measured": f"{len(v)} control(s)",
               "detail": "; ".join(x["what"] for x in v)[:600]} for k, v in by.items()]
    checks.insert(0, {"name": "matrix", "label": "The matrix read in full", "status": "pass", "measured": f"{len(recs)} controls", "detail": ctx.get("matrix") or ""})
    ctx.evidence("Control gaps", {"rows": gaps}, kind="proof", ok=not any(g["status"] == "fail" for g in gaps))
    return {"summary": f"{len(gaps)} gap(s) in {len(recs)} controls: " + (", ".join(f"{len(v)} {k}" for k, v in by.items()) or "none") + ".", "data": {"checks": checks},
            "counts": {"gaps": len(gaps)}}


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**g, "decision": (have.get(g["id"]) or {}).get("decision", "keep")} for g in ctx.get("gaps") or []]
    return {"summary": f"{len(recs)} finding(s) - keep what goes in the report, ignore what is already handled.", "records": recs, "items": [g["what"] for g in recs][:6],
            "data": {"columns": ["Control", "Kind", "What"], "rows": [[g["control"], g["kind"], g["what"]] for g in recs]}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("control", "Control", readonly=True),
                             wb.Column("kind", "Kind", readonly=True), wb.Column("what", "What", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    data = _data(ctx)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for r in ctx.records("inventory"):
        rule = _propose(r, data, _docs(ctx))
        auto = rule["kind"] != "manual"
        rec = {"id": r["id"], "name": r["name"], "tests": PER_YEAR.get(r["frequency"], 1), "minutes": MINUTES[r["type"]], "relay": "yes" if auto else "no",
               "why": dict(KINDS)[rule["kind"]] + (f" ({rule.get('files') or rule.get('pattern') or ''})" if auto else "")}
        if r["id"] in have:
            rec["minutes"] = have[r["id"]].get("minutes", rec["minutes"])
        rec["hours"] = round(float(rec["minutes"] or 0) * rec["tests"] / 60, 1)
        recs.append(rec)
    recs.sort(key=lambda x: -x["hours"])
    total = sum(x["hours"] for x in recs)
    saved = sum(x["hours"] for x in recs if x["relay"] == "yes")
    return {"summary": f"Testing these controls takes about {total:.0f} hours a year; Relay's evidence rules can collect {saved:.0f} of them. The minutes per test are an assumption: set them, then confirm.",
            "records": recs, "counts": {"hours a year": round(total), "automatable": round(saved)},
            "data": {"items": [{"title": f"{x['id']} {x['name']}", "detail": f"{x['tests']} test(s) a year × {x['minutes']} min - " + ("Relay collects it: " + x["why"] if x["relay"] == "yes" else "manual"),
                                "effort": f"{x['hours']} h a year"} for x in recs], "total": f"{total:.0f} h a year", "note": f"Assumptions: {MINUTES['manual']} min per manual test, {MINUTES['automated']} per automated one, unless you set them."}}


def _validate_estimate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for r in recs:
        try:
            m = float(r.get("minutes"))
            assert 0 < m <= 960
            r["hours"] = round(m * float(r.get("tests") or 1) / 60, 1)
        except (TypeError, ValueError, AssertionError):
            out.append(f"{r['id']}: the minutes per test are between 1 and 960")
    return out


EST_EDIT = wb.Edit(columns=[wb.Column("id", "Control", readonly=True), wb.Column("tests", "Tests a year", "number", readonly=True), wb.Column("minutes", "Minutes each", "number"),
                            wb.Column("relay", "Relay collects it", readonly=True), wb.Column("hours", "Hours a year", "number", readonly=True)], add=False, remove=False, validate=_validate_estimate, label="control")


# ------------------------------------------------------------------ evidence rules (rules first)

def _propose(r: dict, data: dict, docs: list[str]) -> dict:
    """An evidence rule for a control from its own words and the files it names - never guessed beyond them."""
    ev = r.get("evidence") or ""
    named = [n for n in data if n.lower() in ev.lower()]
    name = (r.get("name") or "").lower()
    if len(named) >= 2:
        a, b = data[named[0]]["columns"], data[named[1]]["columns"]
        by = next((x for x in BY if x in a and x in b), "")
        ms = [x for x in MEASURES if x in a and x in b]
        return {"kind": "tieout", "files": f"{named[0]}; {named[1]}", "by": by, "measures": ", ".join(ms)}
    if named:
        cols = data[named[0]]["columns"]
        pair = next(((x, y) for x, y in USER_PAIRS if x in cols and y in cols), None)
        m = re.search(r"(?:over|above|more than)\s*₹?\s*([\d,]+)", name)
        if pair and re.search(r"differ|other than|segregat|not the same", name):
            return {"kind": "sod", "files": named[0], "a": pair[0], "b": pair[1]}
        if m and "approval" in name and "amount" in cols and "approvals" in cols:
            n = 2 if re.search(r"\btwo\b|\b2\b|second|dual", name) else 1
            return {"kind": "threshold", "files": named[0], "where": f"amount > {int(m.group(1).replace(',', ''))}", "check": f"approvals >= {n}"}
    if "*" in ev:
        return {"kind": "evidence", "pattern": ev.strip()}
    return {"kind": "manual"}


def _check_rule(r: dict, data: dict) -> list[str]:
    """Rules first: refuse an evidence rule that cannot run."""
    k, out, where = r.get("kind"), [], r["id"]
    files = [x.strip() for x in (r.get("files") or "").split(";") if x.strip()]
    if k not in dict(KINDS):
        return [f"{where}: the rule is one of {', '.join(dict(KINDS))}"]
    if k in ("tieout", "sod", "threshold"):
        need = 2 if k == "tieout" else 1
        if len(files) != need:
            return [f"{where}: a {dict(KINDS)[k].lower()} names {need} file(s) (separate them with ;)"]
        for f in files:
            if f not in data:
                out.append(f"{where}: no data file {f!r} in this work item")
        if out:
            return out
    cols = lambda f: data[f]["columns"]  # noqa: E731
    if k == "tieout":
        if not r.get("by") or any(r["by"] not in cols(f) for f in files):
            out.append(f"{where}: the tie-out needs a period column both files have (e.g. {', '.join(BY[:3])})")
        ms = [m.strip() for m in (r.get("measures") or "").split(",") if m.strip()]
        if not ms or any(m not in cols(f) for m in ms for f in files):
            out.append(f"{where}: the amounts to tie must be columns of both files")
    if k == "sod":
        for c in ("a", "b"):
            if (r.get(c) or "") not in cols(files[0]):
                out.append(f"{where}: no column {r.get(c)!r} in {files[0]}")
    if k == "threshold":
        for c in ("where", "check"):
            m = EXPR.match(r.get(c) or "")
            if not m or m.group(1) not in cols(files[0]):
                out.append(f"{where}: {c} must look like column > 100000 on a column of {files[0]}")
    if k == "evidence" and not (r.get("pattern") or "").strip():
        out.append(f"{where}: name the document pattern (e.g. bank-rec-*.pdf)")
    return out


def _sql_expr(e: str) -> str:
    m = EXPR.match(e)
    return f'"{m.group(1)}" {"<>" if m.group(2) == "!=" else m.group(2)} {m.group(3)}'


def collect(ctx: wb.Ctx, r: dict, data: dict, docs: list[str], label: str = "") -> dict:
    """Run one control's evidence rule: a gate row (status, measured, detail, evidence) and its exceptions."""
    from genbi_kit import data as data_mod
    k = r.get("kind")
    files = [x.strip() for x in (r.get("files") or "").split(";") if x.strip()]
    title = label or f"{r['id']}: {r['name']}"
    if k == "tieout":
        a, b = data[files[0]], data[files[1]]
        g = ctx.proof("totals", label=title, source={"source": "file", "item": a["item"], "file": a["table"]}, target={"source": "file", "item": b["item"], "file": b["table"]},
                      measures=[m.strip() for m in r["measures"].split(",")], by=r["by"], tolerance_pct=0.0)
        try:
            ev = json.loads((ctx.dir / "evidence" / (ctx.step_id or "item") / f"{g['evidence']}.json").read_text(encoding="utf-8"))["payload"]["rows"]
        except (OSError, ValueError, KeyError):
            ev = []
        diffs = [x for x in ev if not x.get("same")]
        if diffs:
            g["detail"] += ": " + "; ".join(f"{x['group']} {x['measure']} differs by {x['difference']:,.0f}" if x.get("difference") is not None else f"{x['group']} {x['measure']} is in one file only"
                                            for x in diffs[:4])
        return {**g, "name": r["id"], "control": r["id"], "exceptions": [{"period": x["group"], "amount": x["measure"], files[0]: x["source"], files[1]: x["target"], "difference": x["difference"]} for x in diffs]}
    if k in ("sod", "threshold"):
        f = data[files[0]]
        con = data_mod.connect(wb.folder(f["item"]))
        try:
            view = '"' + data_mod.raw_name(Path(f["table"])) + '"'
            cond = f'lower(trim(CAST("{r["a"]}" AS VARCHAR))) = lower(trim(CAST("{r["b"]}" AS VARCHAR)))' if k == "sod" else f"({_sql_expr(r['where'])}) AND NOT ({_sql_expr(r['check'])})"
            cur = con.execute(f"SELECT * FROM {view} WHERE {cond}")
            names = [d[0] for d in cur.description]
            exc = [dict(zip(names, [str(v) for v in row])) for row in cur.fetchall()]
            n = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        finally:
            con.close()
        what = (f"{r['a']} is also {r['b']}" if k == "sod" else f"{r['where']} without {r['check']}")
        eid = ctx.evidence(f"{r['id']}: exceptions ({what})", {"rows": exc, "population": n, "rule": {x: r.get(x) for x in ("kind", "files", "a", "b", "where", "check")}}, kind="proof", ok=not exc)
        return {"name": r["id"], "control": r["id"], "label": title, "status": "pass" if not exc else "fail", "measured": f"{len(exc)} exception(s) in {n} rows",
                "expected": "none", "detail": ("every row passes" if not exc else f"{len(exc)} where {what}: " + ", ".join(next(iter(x.values())) for x in exc[:5])), "evidence": eid, "exceptions": exc}
    if k == "evidence":
        hit = [d for d in docs if fnmatch.fnmatch(d.lower(), r["pattern"].strip().lower())]
        eid = ctx.evidence(f"{r['id']}: documents matching {r['pattern']}", {"rows": [{"document": d} for d in hit]}, kind="proof", ok=bool(hit))
        return {"name": r["id"], "control": r["id"], "label": title, "status": "pass" if hit else "fail", "measured": f"{len(hit)} document(s)", "expected": r["pattern"],
                "detail": ", ".join(hit) if hit else f"no document matches {r['pattern']} - upload it", "evidence": eid, "exceptions": [] if hit else [{"missing": r["pattern"]}]}
    return {"name": r["id"], "control": r["id"], "label": title, "status": "warn", "measured": "manual", "detail": f"the owner ({r.get('owner') or 'nobody yet'}) attaches the evidence", "exceptions": []}


# ------------------------------------------------------------------ Develop

def d_describe(ctx: wb.Ctx) -> dict:
    name, recs = _matrix(ctx)
    if not recs:
        raise wb.StepFailed("No control matrix found: upload an Excel tracker or an AuditBoard / SAP GRC export with a Control ID and a Control column.")
    ctx.put("matrix", name)
    ctx.put("controls", recs)
    data = _data(ctx)
    return {"summary": f"{len(recs)} control(s) in {name}; {len(data)} data file(s) and {len(_docs(ctx)) - len(data) - 1} document(s) for the evidence.",
            "counts": {"controls": len(recs), "data files": len(data)},
            "data": {"columns": ["File", "Columns"], "rows": [[k, ", ".join(v["columns"][:10])] for k, v in data.items()]}}


def d_shape(ctx: wb.Ctx) -> dict:
    from . import processdocs, raci
    data, docs = _data(ctx), _docs(ctx)
    u = db.user(ctx.owner or "") or {}
    procs = {p["name"].lower(): p for p in processdocs.processes(u)} if u else {}
    people = _people()
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for c in ctx.get("controls") or []:
        p = procs.get((c.get("process") or "").lower())
        owner = c.get("owner") or ""
        if not owner and p:                                  # nobody named: the process's Accountable owner (RACI)
            acc = raci.accountable(p["id"])
            owner = next(((db.user(x) or {}).get("email") or "" for x in acc), "") if acc else ""
        rec = {"id": c["id"], "name": c["name"], "key": c["key"], "frequency": c["frequency"], "process": c.get("process") or "", "process_id": p["id"] if p else "",
               "owner": owner, "owner_name": (people.get(owner.lower()) or {}).get("name") or "", **{k: "" for k in ("files", "by", "measures", "a", "b", "where", "check", "pattern")},
               **_propose(c, data, docs)}
        if c["id"] in have:
            rec.update({k: v for k, v in have[c["id"]].items() if k in ("kind", "files", "by", "measures", "a", "b", "where", "check", "pattern", "owner")})
        recs.append(rec)
    auto = [r for r in recs if r["kind"] != "manual"]
    return {"summary": f"{len(recs)} control(s): {len(auto)} with an evidence rule Relay can run (from their own words and the files they name), {len(recs) - len(auto)} manual. "
            "Correct the rules and owners in place, then confirm the design.", "records": recs, "counts": {"rules": len(auto), "manual": len(recs) - len(auto)},
            "data": {"columns": ["Control", "Rule", "Files", "Owner"], "rows": [[r["id"], dict(KINDS)[r["kind"]], r["files"] or r["pattern"] or "-", r["owner"] or "-"] for r in recs]}}


def _validate_design(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    data, people, out = _data(ctx), _people(), []
    for r in recs:
        out += _check_rule(r, data)
        if r.get("key") == "yes" and not (r.get("owner") or "").strip():
            out.append(f"{r['id']}: a key control needs an owner")
        elif (r.get("owner") or "").strip() and r["owner"].strip().lower() not in people:
            out.append(f"{r['id']}: {r['owner']} is not a person in this workspace")
        r["owner_name"] = (people.get((r.get("owner") or "").strip().lower()) or {}).get("name") or ""
    return out


DESIGN_EDIT = wb.Edit(columns=[wb.Column("id", "Control", readonly=True), wb.Column("name", "Name", readonly=True), wb.Column("kind", "Rule", "select", options=KINDS),
                               wb.Column("files", "Files", help="one file, or two for a tie-out, separated by ;"), wb.Column("by", "Period column"), wb.Column("measures", "Amounts to tie"),
                               wb.Column("a", "Raised by column"), wb.Column("b", "Approved by column"), wb.Column("where", "Where", help="e.g. amount > 1000000"),
                               wb.Column("check", "Must hold", help="e.g. approvals >= 2"), wb.Column("pattern", "Document", help="e.g. bank-rec-*.pdf"),
                               wb.Column("owner", "Owner (e-mail)")], add=False, remove=False, validate=_validate_design, label="control")


def d_build(ctx: wb.Ctx) -> dict:
    recs = ctx.records("shape")
    probs = _validate_design([dict(r) for r in recs], ctx)
    if probs:
        raise wb.StepFailed("The design has problems: " + "; ".join(probs[:4]))
    data, docs = _data(ctx), _docs(ctx)
    res = [collect(ctx, r, data, docs) for r in recs]
    ctx.put("results", [{k: v for k, v in g.items() if k != "exceptions"} for g in res])
    for g in res:
        if g["exceptions"]:
            ctx.output(f"exceptions-{g['control']}.csv", _w4.csv_text(list(g["exceptions"][0]), [list(x.values()) for x in g["exceptions"]]), label=f"Exceptions: {g['control']}")
    _tracker(ctx, recs, res)
    for r in recs:
        cn = ctx.lineage_node("control", "Relay controls", r["id"], label=f"Control {r['id']}: {r['name']}", properties={"kind": r["kind"], "owner": r.get("owner")})
        if r.get("process_id"):
            from .. import lineage
            pn = lineage.node_id("process", "Relay process documents", r["process_id"])
            if db.one("SELECT 1 FROM lineage_nodes WHERE id = ?", (pn,)):
                ctx.lineage_edge(cn, pn, "relates", {"what": "the control covers this process"})
        for f in [x.strip() for x in (r.get("files") or "").split(";") if x.strip()]:
            ctx.lineage_edge(ctx.lineage_node("table", "Control evidence", f, label=f, own=False), cn, "feeds", {"rule": r["kind"]})
    bad = [g for g in res if g["status"] == "fail"]
    return {"summary": f"Evidence collected for {len(res)} control(s): {sum(1 for g in res if g['status'] == 'pass')} clean, {len(bad)} with exceptions, "
            f"{sum(1 for g in res if g['status'] == 'warn')} manual - the tracker is in the outputs.", "counts": {"clean": sum(1 for g in res if g["status"] == "pass"), "exceptions": len(bad)},
            "data": {"columns": ["Control", "Result", "Detail"], "rows": [[g["control"], g["status"], g["detail"][:200]] for g in res]}}


def _tracker(ctx: wb.Ctx, recs: list[dict], res: list[dict]) -> None:
    import io

    import openpyxl
    from openpyxl.styles import Font, PatternFill
    by = {g["control"]: g for g in res}
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Controls"
    head = ["Control", "Name", "Process", "Owner", "Frequency", "Key", "Evidence rule", "Result", "Measured", "Detail", "Evidence id"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    fill = {"pass": "D9EAD3", "fail": "F4CCCC", "warn": "FFF2CC"}
    for r in recs:
        g = by.get(r["id"]) or {}
        ws.append([r["id"], r["name"], r.get("process"), r.get("owner"), r.get("frequency"), r.get("key"), dict(KINDS).get(r.get("kind"), r.get("kind")),
                   {"pass": "effective", "fail": "exceptions", "warn": "manual"}.get(g.get("status"), g.get("status")), str(g.get("measured") or ""), g.get("detail"), g.get("evidence") or ""])
        ws.cell(ws.max_row, 8).fill = PatternFill("solid", fgColor=fill.get(g.get("status"), "FFFFFF"))
    buf = io.BytesIO()
    book.save(buf)
    ctx.output("controls-tracker.xlsx", buf.getvalue(), label="Controls tracker (Excel)")


def d_prove(ctx: wb.Ctx) -> dict:
    res = ctx.get("results") or []
    bad = [g for g in res if g["status"] == "fail"]
    return {"summary": f"{len(res)} control(s) proven with their evidence: " + (f"{len(bad)} with exceptions ({', '.join(g['control'] for g in bad)}) - confirm with the reason, or send the design back"
                                                                                if bad else "every automated control is clean") + ".",
            "data": {"checks": [{k: g.get(k) for k in ("name", "label", "status", "measured", "expected", "detail", "evidence")} for g in res]}, "counts": {"exceptions": len(bad)}}


def d_ship(ctx: wb.Ctx) -> dict:
    recs = ctx.records("shape")
    return {"summary": f"Go live: {len(recs)} controls into the library, their evidence collected {ctx.scope.get('cadence', {}).get('every', 'month')}ly by a Run item.",
            "data": {"items": [{"title": f"{r['id']} {r['name']}", "detail": f"{dict(KINDS)[r['kind']]} - owner {r.get('owner_name') or r.get('owner') or '-'}"} for r in recs]}}


def publish(ctx: wb.Ctx, recs: list[dict], note: str = "") -> int:
    now, n = time.time(), 0
    rule_keys = ("kind", "files", "by", "measures", "a", "b", "where", "check", "pattern")
    for r in recs:
        rule = {k: r.get(k) or "" for k in rule_keys}
        have = db.one("SELECT version, rule, owner FROM controls_library WHERE id = ?", (r["id"],))
        if have and _w4.j(have["rule"], {}) == rule and have["owner"] == r.get("owner"):
            continue
        v = (have["version"] + 1) if have else 1
        if have:
            db.run("UPDATE controls_library SET item = ?, name = ?, process = ?, process_id = ?, owner = ?, frequency = ?, key_control = ?, rule = ?, version = ?, status = 'live', updated = ? WHERE id = ?",
                   (ctx.id, r["name"], r.get("process"), r.get("process_id"), r.get("owner"), r.get("frequency"), 1 if r.get("key") == "yes" else 0, json.dumps(rule), v, now, r["id"]))
        else:
            db.run("INSERT INTO controls_library (id, item, name, process, process_id, owner, frequency, key_control, rule, version, status, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'live', ?, ?)",
                   (r["id"], ctx.id, r["name"], r.get("process"), r.get("process_id"), r.get("owner"), r.get("frequency"), 1 if r.get("key") == "yes" else 0, json.dumps(rule), now, now))
        db.run("INSERT INTO controls_versions (control, version, item, record, by_id, at, note) VALUES (?, ?, ?, ?, ?, ?, ?)", (r["id"], v, ctx.id, json.dumps(r, default=str), ctx.who or ctx.owner, now, note or None))
        n += 1
    return n


def library(ids: list[str] | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM controls_library WHERE status = 'live' ORDER BY id")
    return [{**r, **_w4.j(r["rule"], {}), "key": "yes" if r["key_control"] else "no"} for r in rows if not ids or r["id"] in ids]


def d_run(ctx: wb.Ctx) -> dict:
    recs = ctx.records("shape")
    n = publish(ctx, recs, "went live")
    run_id = ctx.get("run_item")
    if not run_id or not db.one("SELECT 1 FROM wb_items WHERE id = ? AND closed IS NULL", (run_id,)):
        p = db.project(ctx.id) or {}
        it = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"The controls of {ctx.id}, their evidence collected each period.",
                       scope={"from_item": ctx.id, "controls": [r["id"] for r in recs], "schedule": ctx.scope.get("cadence") or {"every": "day", "at": "06:00", "tz": "UTC"}, "_source_ok": True},
                       approver=ctx.st.get("approver"), visibility=p.get("visibility") or "private", team_id=p.get("team_id"), parent=ctx.id)
        run_id = it["id"]
        ctx.put("run_item", run_id)
    return {"summary": f"Live: {n} control(s) published to the library; a Run item collects their evidence on its schedule.",
            "data": {"href": f"#/m/{MODULE}/i/{run_id}", "label": "Open the Run item", "text": f"{len(recs)} controls, owners named, evidence rules proven."}}


# ------------------------------------------------------------------ Change

def c_request(ctx: wb.Ctx) -> dict:
    cid = ctx.scope.get("control") or ""
    lib = library([cid])
    if not lib:
        raise wb.StepFailed("Pick a live control to change (the library is filled by a Develop item going live).")
    c = lib[0]
    ctx.put("control", c)
    return {"summary": f"{c['id']} ({c['name']}), version {c['version']}: {ctx.brief or 'the change in the brief'}.", "data": {"columns": ["Field", "Now"], "rows": [[k, c.get(k)] for k in ("name", "kind", "files", "where", "check", "by", "measures", "owner", "frequency")]}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    c = ctx.get("control") or {}
    files = [x.strip() for x in (c.get("files") or "").split(";") if x.strip()]
    others = [x["id"] for x in library() if x["id"] != c["id"] and set(files) & {y.strip() for y in (x.get("files") or "").split(";") if y.strip()}]
    checks = [{"name": "rule", "label": f"Its rule: {dict(KINDS).get(c.get('kind'))}", "status": "pass", "detail": ", ".join(f"{k} {c[k]}" for k in ("files", "where", "check", "by", "measures", "pattern") if c.get(k))},
              {"name": "shared", "label": "Other controls reading the same data", "status": "warn" if others else "pass", "detail": ", ".join(others) or "none"},
              {"name": "last", "label": "Its last result", "status": "pass", "detail": c.get("last_result") or "not run yet"}]
    return {"summary": f"{c.get('id')}: what the change touches - " + (f"{len(others)} other control(s) read the same data" if others else "nothing else reads its data") + ".", "data": {"checks": checks}}


def c_fix(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    c = ctx.get("control") or {}
    rec = have[0] if have else {k: c.get(k) or "" for k in ("id", "name", "key", "frequency", "process", "process_id", "kind", "files", "by", "measures", "a", "b", "where", "check", "pattern", "owner")}
    return {"summary": f"Change {c.get('id')} in place; the rule is checked as you save, then re-run on its data.", "records": [rec]}


def _data_of(ctx: wb.Ctx, item: str | None) -> tuple[dict, list[str]]:
    if item and db.one("SELECT 1 FROM wb_items WHERE id = ?", (item,)):
        return _data(ctx, item), _docs(ctx, item)
    return _data(ctx), _docs(ctx)


def _validate_fix(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    data, _ = _data_of(ctx, (ctx.get("control") or {}).get("item"))
    return [p for r in recs for p in _check_rule(r, data)]


FIX_EDIT = wb.Edit(columns=DESIGN_EDIT.columns, add=False, remove=False, validate=_validate_fix, label="control")


def c_prove(ctx: wb.Ctx) -> dict:
    rec = (ctx.records("fix") or [None])[0]
    if not rec:
        raise wb.StepFailed("Nothing changed: correct the control in Fix first.")
    c = ctx.get("control") or {}
    data, docs = _data_of(ctx, c.get("item"))
    g = collect(ctx, rec, data, docs, label=f"{rec['id']} as changed")
    before = next((x for x in (wb._load(c["item"]).get("data") or {}).get("results") or [] if x.get("control") == rec["id"]), None) if c.get("item") and db.one("SELECT 1 FROM wb_items WHERE id = ?", (c["item"],)) else None
    rows = [{k: g.get(k) for k in ("name", "label", "status", "measured", "expected", "detail", "evidence")}]
    if before:
        rows.append({"name": "before", "label": f"{rec['id']} before the change", "status": before.get("status"), "measured": before.get("measured"), "detail": before.get("detail")})
    return {"summary": f"{rec['id']} re-run on its data: {g['measured']}" + (f" (before: {before.get('measured')})" if before else "") + ".", "data": {"checks": rows}}


def c_approve(ctx: wb.Ctx) -> dict:
    rec = (ctx.records("fix") or [{}])[0]
    c = ctx.get("control") or {}
    ch = [k for k in ("kind", "files", "by", "measures", "a", "b", "where", "check", "pattern", "owner") if (rec.get(k) or "") != (c.get(k) or "")]
    return {"summary": f"Approve {rec.get('id')} version {int(c.get('version') or 1) + 1}: " + (", ".join(f"{k} {c.get(k) or '-'} {rec.get(k) or '-'}" for k in ch) or "no change"),
            "data": {"items": [{"title": k, "detail": f"{c.get(k) or '-'} {rec.get(k) or '-'}"} for k in ch]}}


def c_learn(ctx: wb.Ctx) -> dict:
    rec = dict((ctx.records("fix") or [{}])[0])
    c = ctx.get("control") or {}
    rec.update({k: c.get(k) for k in ("name", "process", "process_id", "frequency") if not rec.get(k)})
    rec["key"] = rec.get("key") or c.get("key")
    n = publish(ctx, [rec], ctx.brief[:300] or "changed")
    v = db.one("SELECT version FROM controls_library WHERE id = ?", (rec["id"],))["version"]
    return {"summary": f"{rec['id']} is version {v} in the library" + ("" if n else " (no change)") + "; the Run items use it from their next round.", "counts": {"version": v}}


# ------------------------------------------------------------------ Run

def r_watch(ctx: wb.Ctx) -> dict:
    src = ctx.scope.get("from_item")
    lib = library(ctx.scope.get("controls"))
    if not lib:
        raise wb.StepFailed("No live control to run: the Develop item's controls are not in the library.")
    base, docs = _data_of(ctx, src)
    mine, my_docs = _data(ctx), _docs(ctx)
    data = dict(base)
    for k in list(base):                              # this period's file: the newest upload whose name starts with the file's own name
        stem = Path(k).stem.lower()
        new = sorted([x for x in mine if Path(x).stem.lower().startswith(stem)], key=lambda x: -mine[x]["when"])
        if new:
            data[k] = mine[new[0]]
    res = [collect(ctx, r, data, docs + my_docs) for r in lib]
    now = time.time()
    for g in res:
        db.run("UPDATE controls_library SET last_result = ?, last_run = ? WHERE id = ?", (f"{g['status']}: {g['measured']}", now, g["control"]))
    ctx.put("results", [{k: v for k, v in g.items() if k != "exceptions"} | {"exceptions": g["exceptions"][:50], "owner": next(x.get("owner") for x in lib if x["id"] == g["control"])} for g in res])
    bad = [g for g in res if g["status"] == "fail"]
    used = {k: v["table"] for k, v in data.items() if v["item"] == ctx.id}
    return {"summary": f"{len(res)} control(s) run" + (f" on this period's {', '.join(used.values())}" if used else "") + f": {len(bad)} with exceptions.",
            "data": {"checks": [{k: g.get(k) for k in ("name", "label", "status", "measured", "expected", "detail", "evidence")} for g in res]}, "counts": {"exceptions": len(bad)}}


def r_alert(ctx: wb.Ctx) -> dict:
    bad = [g for g in ctx.get("results") or [] if g["status"] == "fail"]
    if not bad:
        ctx.put("breaks", [])
        return {"summary": "Every control is clean this period: nothing to alert.", "next": "report", "counts": {"breaks": 0}}
    brks = [{"id": f"b-{g['control']}", "control": g["control"], "what": g["detail"][:300], "owner": g.get("owner") or "", "route": "ticket", "note": ""} for g in bad]
    ctx.put("breaks", brks)
    return {"summary": f"{len(brks)} control(s) with exceptions, each for its owner.", "counts": {"breaks": len(brks)}, "items": [f"{b['control']}: {b['what']}" for b in brks],
            "data": {"columns": ["Control", "Exceptions", "Owner"], "rows": [[b["control"], b["what"], b["owner"] or "-"] for b in brks]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**b, **{k: have[b["id"]][k] for k in ("route", "note") if b["id"] in have}} for b in ctx.get("breaks") or []]
    return {"summary": f"{len(recs)} control(s) with exceptions: a ticket for the owner, or accepted with the reason. Nothing goes out until you confirm.", "records": recs}


def _validate_routes(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return [f"{r['control']}: say why the exceptions are accepted" for r in recs if r.get("route") == "accepted" and not (r.get("note") or "").strip()]


ROUTE_EDIT = wb.Edit(columns=[wb.Column("control", "Control", readonly=True), wb.Column("what", "Exceptions", readonly=True), wb.Column("route", "Route", "select", options=(("ticket", "A ticket for the owner"), ("accepted", "Accepted - with the reason"))),
                              wb.Column("note", "Reason / note", "longtext"), wb.Column("owner", "Owner", readonly=True)], add=False, remove=False, validate=_validate_routes, label="control")


def r_approve(ctx: wb.Ctx) -> dict:
    rows = []
    for b in ctx.records("fix"):
        if b["route"] == "ticket":
            h = ctx.ticket(f"Control exceptions: {b['control']}", f"{b['what']}\n\nOwner: {b['owner'] or '-'}\n{b.get('note') or ''}\nWork item: {wb.route_of(ctx.st)}", priority="P2", about=b["control"])
        else:
            h = {"status": f"accepted - {b['note']}"}
        rows.append([b["control"], b["route"], h.get("status"), h.get("output") or h.get("checkpoint") or ""])
    return {"summary": f"{sum(1 for r in rows if r[1] == 'ticket')} ticket(s), {sum(1 for r in rows if r[1] == 'accepted')} accepted - as you decided.", "data": {"columns": ["Control", "Route", "Status", "Reference"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    res = ctx.get("results") or []
    period = time.strftime("%B %Y", time.gmtime())
    text = f"# Controls report - {period}\n\n{ctx.title}\n\n| Control | Result | Detail |\n|---|---|---|\n" + "".join(f"| {g['control']} | {g['status']} | {str(g['detail'])[:160].replace('|', '/')} |\n" for g in res)
    ctx.output(f"controls-report-{time.strftime('%Y%m', time.gmtime())}.md", text, label="Controls report (Markdown)")
    lib = {c["id"]: c for c in library(ctx.scope.get("controls"))}
    _tracker(ctx, [lib[g["control"]] for g in res if g["control"] in lib], res)
    return {"summary": f"{period}: {sum(1 for g in res if g['status'] == 'pass')} clean, {sum(1 for g in res if g['status'] == 'fail')} with exceptions, {sum(1 for g in res if g['status'] == 'warn')} manual.",
            "data": {"columns": ["Control", "Result", "Detail"], "rows": [[g["control"], g["status"], g["detail"][:200]] for g in res]}}


# ------------------------------------------------------------------ the module page

def _cards(u: dict) -> list[dict]:
    rows = _w4.visible_items(u, [{**r, "item": r["item"]} for r in db.q("SELECT * FROM controls_library ORDER BY id")])
    return [{"title": "Live controls", "columns": ["Control", "Name", "Owner", "Version", "Last result", "Open"],
             "rows": [[r["id"], r["name"], r["owner"] or "-", r["version"], r["last_result"] or "not run yet", f"#/m/{MODULE}/i/{r['item']}" if r["item"] else ""] for r in rows],
             "empty": "No live control yet: a Develop item's Run step publishes them."}]


def _control_options(u: dict) -> list[tuple[str, str]]:
    rows = _w4.visible_items(u, [{**r, "item": r["item"]} for r in db.q("SELECT id, name, version, item FROM controls_library WHERE status = 'live' ORDER BY id")])
    return [(r["id"], f"{r['id']} {r['name']} - version {r['version']}") for r in rows]


wb.register(wb.Pack(
    module=MODULE,
    guide="# Controls & compliance - the work item\n\nEvidence is collected by rules from the files in data/; nothing is drafted by an agent. Every result names its evidence.",
    lineage="each control as a node that covers its process and is fed by the data its evidence comes from",
    platforms={"files": FILES},
    schemas={"control": DESIGN_EDIT.columns},
    cards=_cards,
    work={
        "assess": wb.Work(title="Read a control matrix and find the gaps an auditor would ask about", steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="The matrix and the evidence files, read-only copies"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Matrix reader", edit=INV_EDIT, text="Every control in the matrix's own terms - you correct owners and frequencies"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Gap finder", text="By rules: no owner, not tested in time, failed last time, duplicates, undocumented processes"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="Keep or ignore each gap"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", edit=EST_EDIT, text="The testing effort a year, and what Relay's evidence rules collect")}),
        "develop": wb.Work(title="Map each control to its process, owner and evidence rule; collect the evidence; go live", steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Reader", text="The matrix and the data files the evidence comes from"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Control mapper", edit=DESIGN_EDIT, text="Each control's evidence rule from its own words and files, its process and owner - you correct them"),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Evidence collector", text="The evidence collected by rules (DuckDB; tie-outs with the engine's totals proof), the tracker and the exceptions"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Prover", back_to="shape", text="Every control's result with its evidence"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver takes the controls live"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The library published; a Run item collects the evidence each period")},
            fields=[wb.Field("cadence", "Once live, collect the evidence", "cadence", default={"every": "week", "at": "06:00", "tz": "Asia/Kolkata", "weekday": 0})]),
        "change": wb.Work(title="Change a live control - what it touches, changed in place, re-run, approved", needs_source=False, steps={
            "Request": wb.Step(kind="deterministic", run=c_request, agent="Intake", text="The control and the change asked for"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Impact checker", text="Its rule, the controls that read the same data, its last result"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=FIX_EDIT, text="The control changed in place; the rule checked as you save"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Prover", back_to="fix", text="Re-run on its data, before and after"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, agent="Librarian", text="A new version in the library; Run items use it next round")},
            fields=[wb.Field("control", "Control", "select", options=_control_options, required=True)]),
        "run": wb.Work(title="Collect the evidence each period; exceptions go to their owner after a person decides", needs_source=False, steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Evidence collector", text="The live controls run on this period's data"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="Exceptions per control, with its owner"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=ROUTE_EDIT, text="A ticket for the owner, or accepted with the reason - you confirm"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved hand-offs go out"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("breaks")), text="The period's controls report and tracker")},
            fields=[wb.Field("schedule", "Collect it", "cadence", default={"every": "week", "at": "06:00", "tz": "Asia/Kolkata", "weekday": 0})]),
    }))
