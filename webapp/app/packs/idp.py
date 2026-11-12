"""Document processing (registry id `idp`) - invoices and receipts read by the document-AI engine you run (Azure AI
Document Intelligence, AWS Textract, Google Document AI, UiPath Document Understanding, ABBYY Vantage; adapters in idp_engines.py), checked by rules, and every
field Relay is not sure of shown to a person before anything goes on.

Assess   Connect -> Inventory -> Health -> Findings -> Estimate: a labelled sample (the documents and truth.json with what
         each says) read by every connected engine; field-by-field accuracy per engine, how many documents would go to
         a person, the fields an engine gets wrong; the engine that fits and the review effort per month.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: a document type set up - its fields, each one's check (a date,
         an amount, a GSTIN or a UK VAT number, the totals adding up) and the confidence below which a person looks -
         proven on the labelled set (accuracy of what goes straight through, every doubt routed to a person), signed off
         by the named approver; a Run item then reads the documents that arrive.
Run      Watch -> Alert -> Fix -> Approve -> Report: documents uploaded to the item read; the ones with a doubt (a field
         under the confidence line, a check that fails, a field missing) listed with the reason; a person corrects the
         values in place; the approved results written out (CSV and JSON) and handed on.
(Change and Migrate - a field's check changed, UiPath Document Understanding or ABBYY moved to another engine - are a
follow-up.)
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from pathlib import Path

from .. import db, store
from .. import workbench as wb
from . import _w2
from . import idp_engines as ie
from . import idp_sources as src

MODULE = "idp"
THRESHOLD = 0.85
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
UKVAT = re.compile(r"^GB\d{9}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CHECKS = (("", "No check"), ("date", "A date (YYYY-MM-DD)"), ("amount", "An amount"), ("tax_id", "A GSTIN or a UK VAT number"), ("total", "Subtotal + tax = this total"))
DEFAULT_CHECK = {"InvoiceDate": "date", "DueDate": "date", "TransactionDate": "date", "SubTotal": "amount", "TotalTax": "amount", "InvoiceTotal": "total", "Total": "amount", "VendorTaxId": "tax_id"}
REQUIRED = {"invoice": ("VendorName", "InvoiceId", "InvoiceDate", "InvoiceTotal", "CurrencyCode"), "receipt": ("MerchantName", "TransactionDate", "Total")}
MIN_REVIEW = 3            # minutes a person takes to check one document


class EnginePlatform(wb.Platform):
    def __init__(self, label: str, kinds: tuple, simulator: str, reads: str, uploads: tuple = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".json")):
        self.label, self.kinds, self.uploads, self.simulator, self.reads = label, kinds, uploads, simulator, reads


PLATFORMS = {
    "azure_di": EnginePlatform("Azure AI Document Intelligence", ("azure_di",), ie.AzureDocumentIntelligence.simulator, "prebuilt invoice and receipt models (or yours) through a resource key"),
    "textract": EnginePlatform("AWS Textract", ("textract_api",), ie.AwsTextract.simulator, "AnalyzeExpense through an access key"),
    "google": EnginePlatform("Google Document AI", ("google_docai",), ie.GoogleDocumentAI.simulator, "invoice and expense processors through a service account"),
    "uipath_du": EnginePlatform("UiPath Document Understanding", ("uipath_du",), ie.UiPathDocumentUnderstanding.simulator, "digitisation and the predefined (or your) extractors through an external application"),
    "abbyy": EnginePlatform("ABBYY Vantage", ("abbyy_vantage",), ie.AbbyyVantage.simulator, "skills (Invoice, Receipt) through a client; a document in doubt keeps Vantage's review link"),
    "mailbox": EnginePlatform("Outlook mailbox (where documents arrive)", ("m365_mail",), "tests/mocklab/files_sim.py: Graph mail (messages and their attachments)",
                              "the attachments of the messages in a mail folder, read-only - nothing is moved, flagged or deleted", uploads=()),
    "folder": EnginePlatform("SharePoint or OneDrive folder (where documents arrive)", ("sharepoint", "onedrive"), "tests/mocklab/files_sim.py: Graph drives",
                             "the documents in the folder the Run item names, read-only", uploads=()),
}
SOURCE_PLATFORMS = ("mailbox", "folder")


# ================================================================== documents, labels, engines

def _docs(ctx: wb.Ctx) -> list[dict]:
    return [f for f in ctx.files((".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"))]


def _labels(ctx: wb.Ctx) -> dict:
    """truth.json (or labels.json): {file: {field: value}} - keyed by the file's name (a path keeps only its last part)."""
    for f in ctx.files((".json",)):
        if f["name"].lower() in ("truth.json", "labels.json"):
            try:
                d = json.loads((ctx.dir / "data" / f["name"]).read_text(encoding="utf-8"))
            except ValueError as e:
                raise wb.StepFailed(f"{f['name']} is not JSON: {e}") from e
            return {Path(k).name: v for k, v in d.items()}
    return {}


def _kind(name: str, label: dict | None) -> str:
    if label and ("MerchantName" in label or "TransactionDate" in label):
        return "receipt"
    return "receipt" if "receipt" in name.lower() else "invoice"


def _engines(ctx: wb.Ctx) -> list[tuple[dict, ie.Engine]]:
    out = []
    for c in ctx.connections():
        a = _w2.adapter(c)
        if isinstance(a, ie.Engine):
            out.append((c, a))
    return out


def same(field: str, want, got) -> bool:
    if want in (None, "") and got in (None, ""):
        return True
    if field in ie.MONEY:
        a, b = ie._num(want), ie._num(got)
        return a is not None and b is not None and abs(a - b) <= 0.01
    return re.sub(r"\s+", " ", str(want or "")).strip().lower() == re.sub(r"\s+", " ", str(got or "")).strip().lower()


def doubts(res: dict, kind: str, spec: list[dict]) -> list[str]:
    """Why a person must look at this document (nothing: it goes straight through)."""
    f = res.get("fields") or {}
    out = []
    for s in spec:
        name, v = s["field"], (f.get(s["field"]) or {})
        thr = float(s.get("min_confidence") or THRESHOLD)
        if v.get("value") in (None, ""):
            if s.get("required"):
                out.append(f"{name} was not found")
            continue
        if v.get("confidence", 0) < thr:
            out.append(f"{name} read with {v['confidence']:.0%} confidence (below {thr:.0%})")
        chk, val = s.get("check") or "", v["value"]
        if chk == "date" and not ISO.match(str(val)):
            out.append(f"{name} \"{val}\" is not a date")
        elif chk in ("amount", "total") and ie._num(val) is None:
            out.append(f"{name} \"{val}\" is not an amount")
        elif chk == "tax_id" and not (GSTIN.match(str(val)) or UKVAT.match(str(val))):
            out.append(f"{name} \"{val}\" is neither a GSTIN nor a UK VAT number")
        if chk == "total":
            sub, tax, tot = (ie._num((f.get(k) or {}).get("value")) for k in ("SubTotal", "TotalTax", name))
            if None not in (sub, tax, tot) and abs(sub + tax - tot) > 0.01:
                out.append(f"subtotal {sub:.2f} + tax {tax:.2f} is not the total {tot:.2f}")
    return out


def default_spec(kind: str) -> list[dict]:
    return [{"id": k, "field": k, "required": k in REQUIRED.get(kind, ()), "check": DEFAULT_CHECK.get(k, ""), "min_confidence": THRESHOLD} for k in ie.fields_of(kind)]


def _read_all(ctx: wb.Ctx, c: dict, a: ie.Engine, names: list[str], labels: dict) -> dict:
    out = {}
    for n in names:
        try:
            r = a.extract(c, (ctx.dir / "data" / n).read_bytes(), _kind(n, labels.get(n)))
        except Exception as e:  # noqa: BLE001 - one unreadable document is a finding, not a stop
            r = {"fields": {}, "items": [], "error": str(e)[:200]}
        out[n] = r
    return out


# ================================================================== Assess

def a_connect(ctx: wb.Ctx) -> dict:
    eng, docs, labels = _engines(ctx), _docs(ctx), _labels(ctx)
    if not eng:
        raise wb.StepFailed("Pick at least one document-AI connection (Azure AI Document Intelligence, AWS Textract or Google Document AI).")
    if not docs:
        raise wb.StepFailed("Upload a sample of documents (PDF or images) - and truth.json with what each says, to measure accuracy.")
    rows = []
    for c, a in eng:
        try:
            rows.append([c["name"], a.label, "answered", a.sees(c)])
        except Exception as e:  # noqa: BLE001
            rows.append([c["name"], a.label, "refused", str(e)[:200]])
    if not any(r[2] == "answered" for r in rows):
        raise wb.StepFailed("No engine answered: " + "; ".join(f"{r[0]}: {r[3]}" for r in rows))
    lab = sum(1 for d in docs if d["name"] in labels)
    return {"summary": f"{sum(1 for r in rows if r[2] == 'answered')} engine(s) answered; {len(docs)} document(s) uploaded, {lab} with labels.",
            "counts": {"engines": len(rows), "documents": len(docs), "labelled": lab}, "data": _w2.table(["Connection", "Engine", "Status", "What it offers"], rows)}


def a_inventory(ctx: wb.Ctx) -> dict:
    labels = _labels(ctx)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for d in _docs(ctx):
        k = _kind(d["name"], labels.get(d["name"]))
        recs.append({"id": d["name"], "include": (have.get(d["name"]) or {}).get("include", True), "document": d["name"], "kind": (have.get(d["name"]) or {}).get("kind") or k,
                     "labelled": "yes" if d["name"] in labels else "no", "bytes": d["bytes"]})
    return {"summary": f"{len(recs)} document(s): {sum(1 for r in recs if r['kind'] == 'invoice')} invoice(s), {sum(1 for r in recs if r['kind'] == 'receipt')} receipt(s); "
                       f"{sum(1 for r in recs if r['labelled'] == 'yes')} labelled. Untick what is out of scope; correct a type.", "records": recs, "counts": {"documents": len(recs)},
            "data": _w2.table(["Document", "Type", "Labelled", "Bytes"], [[r["document"], r["kind"], r["labelled"], r["bytes"]] for r in recs])}


INV_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("document", "Document", readonly=True), wb.Column("kind", "Type", "select", options=(("invoice", "Invoice"), ("receipt", "Receipt"))),
                            wb.Column("labelled", "Labelled", readonly=True)], add=False, remove=False, label="document")


def a_health(ctx: wb.Ctx) -> dict:
    labels = _labels(ctx)
    docs = [r for r in ctx.records("inventory") if r.get("include")]
    kinds = {r["document"]: r["kind"] for r in docs}
    checks, per = [], {}
    for c, a in _engines(ctx):
        res = _read_all(ctx, c, a, [r["document"] for r in docs], {n: labels.get(n) or ({"MerchantName": 1} if kinds[n] == "receipt" else {}) for n in kinds})
        rows, review = [], 0
        for n, r in res.items():
            lab = labels.get(n) or {}
            for fld in ie.fields_of(kinds[n]):
                if fld in lab:
                    got = (r["fields"].get(fld) or {}).get("value")
                    rows.append({"doc": n, "field": fld, "expected": lab[fld], "got": got, "ok": same(fld, lab[fld], got), "engine": a.label})
            if doubts(r, kinds[n], default_spec(kinds[n])) or r.get("error"):
                review += 1
        g = ctx.proof("accuracy", label=f"{a.label} ({c['name']}): accuracy against the labels", rows=rows, min_pct=95.0) if rows else _w2.gate(f"acc-{c['id']}", f"{a.label}: accuracy", "skip", detail="no labels")
        g["name"] = f"acc-{c['id']}"
        checks.append(g)
        wrong = {}
        for x in rows:
            if not x["ok"]:
                wrong[x["field"]] = wrong.get(x["field"], 0) + 1
        per[c["id"]] = {"engine": a.label, "connection": c["name"], "fields": len(rows), "right": sum(1 for x in rows if x["ok"]), "review": review, "documents": len(res), "wrong": wrong,
                        "errors": sum(1 for r in res.values() if r.get("error"))}
        checks.append(_w2.gate(f"review-{c['id']}", f"{a.label}: documents a person would check", "warn" if review else "pass", f"{review} of {len(res)}", "as few as the documents need",
                               "a field under the 85 % confidence line, a check that fails or a field missing"))
    ctx.put("engines", per)
    eid = ctx.evidence("What each engine read", per, kind="accuracy", ok=True)
    for g in checks:
        g.setdefault("evidence", eid)
    return {"summary": "; ".join(f"{v['engine']}: {round(100 * v['right'] / v['fields'], 1) if v['fields'] else '-'} % right, {v['review']} of {v['documents']} to a person" for v in per.values()) + ".",
            "counts": {"engines": len(per), "documents": len(docs)}, "data": _w2.gates(checks)}


def a_findings(ctx: wb.Ctx) -> dict:
    per = ctx.get("engines") or {}
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    best = max(per.values(), key=lambda v: ((v["right"] / v["fields"]) if v["fields"] else 0, -v["review"]), default=None)
    for cid, v in per.items():
        pct = round(100 * v["right"] / v["fields"], 1) if v["fields"] else None
        recs.append({"id": f"acc-{cid}", "kind": "accuracy", "engine": v["engine"], "severity": "low" if pct and pct >= 95 else "high",
                     "what": f"{v['engine']} reads {pct} % of the labelled fields right" + (" - the best fit here" if v is best else ""), "do": "use it" if v is best else "compare with the best fit"})
        for fld, n in sorted(v["wrong"].items(), key=lambda x: -x[1]):
            recs.append({"id": f"wrong-{cid}-{fld}", "kind": "field", "engine": v["engine"], "severity": "medium", "what": f"{v['engine']} gets {fld} wrong in {n} document(s)",
                         "do": "add a check for it, or keep it under review"})
        if v["review"]:
            recs.append({"id": f"review-{cid}", "kind": "review", "engine": v["engine"], "severity": "medium", "what": f"{v['review']} of {v['documents']} documents need a person with {v['engine']} (a field Relay is not sure of)",
                         "do": "a person checks them in Run before they go on"})
    for r in recs:
        r["decision"] = (have.get(r["id"]) or {}).get("decision") or "keep"
    ctx.put("best", best)
    return {"summary": f"{len(recs)} finding(s)" + (f"; {best['engine']} fits best" if best else "") + ".", "records": recs, "counts": {"findings": len(recs)}, "items": [r["what"] for r in recs[:6]],
            "data": _w2.table(["Engine", "Finding", "Severity", "What to do"], [[r["engine"], r["what"], r["severity"], r["do"]] for r in recs])}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("engine", "Engine", readonly=True),
                             wb.Column("what", "Finding", readonly=True)], add=False, remove=False, label="finding")


def a_estimate(ctx: wb.Ctx) -> dict:
    best = ctx.get("best") or {}
    vol = int(ctx.scope.get("volume") or 0)
    share = (best.get("review") or 0) / (best.get("documents") or 1)
    items = [{"title": "Set it up (Develop)", "detail": "fields, their checks and the confidence line, proven on the labelled set", "effort": "4.0 h"}]
    if vol:
        items.append({"title": "A person's review each month", "detail": f"{vol} documents × {share:.0%} under review × {MIN_REVIEW} min", "effort": f"{vol * share * MIN_REVIEW / 60:.1f} h a month"})
    ctx.output("assessment.md", f"# Assessment: {ctx.title}\n\n" + "".join(f"- {i['title']}: {i['detail']} - {i['effort']}\n" for i in items), label="Assessment (Markdown)")
    return {"summary": f"With {best.get('engine') or 'the best engine'}: {share:.0%} of documents go to a person" + (f", about {vol * share * MIN_REVIEW / 60:.1f} h a month for {vol} documents." if vol else
                                                                                                                  " (give the monthly volume to see the review hours)."),
            "data": {"items": items, "note": f"{MIN_REVIEW} minutes to check one document; no engine price is assumed - your contract's price per page applies."}}


# ================================================================== Develop

def d_describe(ctx: wb.Ctx) -> dict:
    kind = ctx.scope.get("kind") or "invoice"
    labels, docs = _labels(ctx), _docs(ctx)
    if not docs or not labels:
        raise wb.StepFailed("Upload a labelled sample: the documents and truth.json with what each says - the proof is measured on it.")
    ctx.put("kind", kind)
    return {"summary": f"A {kind} type, proven on {sum(1 for d in docs if d['name'] in labels)} labelled document(s)." + (" " + ctx.brief[:200] if ctx.brief else ""), "counts": {"documents": len(docs)},
            "data": {"text": ctx.brief or f"Read {kind}s"}}


def d_shape(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    recs = have or default_spec(ctx.get("kind") or "invoice")
    return {"summary": f"{len(recs)} field(s), {sum(1 for r in recs if r.get('required'))} required: set each one's check and the confidence below which a person looks.", "records": recs,
            "counts": {"fields": len(recs)}, "data": _w2.table(["Field", "Required", "Check", "Confidence line"], [[r["field"], "yes" if r.get("required") else "no", r.get("check") or "-",
                                                                                                                  f"{float(r.get('min_confidence') or THRESHOLD):.0%}"] for r in recs])}


def _validate_shape(recs, ctx):
    out = []
    for r in recs:
        try:
            v = float(r.get("min_confidence") or THRESHOLD)
            if not 0.5 <= v <= 1:
                out.append(f"{r['field']}: the confidence line is between 0.5 and 1")
        except ValueError:
            out.append(f"{r['field']}: the confidence line is a number (e.g. 0.85)")
        if r.get("check") not in {k for k, _ in CHECKS}:
            out.append(f"{r['field']}: unknown check {r.get('check')!r}")
    if not any(r.get("required") for r in recs):
        out.append("mark at least one field required")
    return out


SHAPE_EDIT = wb.Edit(columns=[wb.Column("field", "Field", readonly=True), wb.Column("required", "Required", "bool"), wb.Column("check", "Check", "select", options=CHECKS),
                              wb.Column("min_confidence", "Confidence line", "number", help="below it a person checks the field")], add=False, remove=False, validate=_validate_shape, label="field")


def _engine(ctx) -> tuple[dict, ie.Engine]:
    e = _engines(ctx)
    if len(e) != 1:
        raise wb.StepFailed("Start the work item with exactly one document-AI connection: the engine this document type runs on.")
    return e[0]


def d_build(ctx: wb.Ctx) -> dict:
    c, a = _engine(ctx)
    spec = ctx.records("shape")
    cfg = {"kind": ctx.get("kind"), "engine": a.kind, "connection": c["id"], "fields": [{k: r.get(k) for k in ("field", "required", "check", "min_confidence")} for r in spec]}
    ctx.put("config", cfg)
    ctx.output("document-type.json", json.dumps(cfg, indent=2), label="The document type (fields, checks, confidence lines)")
    return {"summary": f"The {cfg['kind']} type runs on {a.label} ({c['name']}): {len(spec)} field(s) with their checks.", "counts": {"fields": len(spec)},
            "data": _w2.table(["Field", "Required", "Check", "Confidence line"], [[r["field"], "yes" if r.get("required") else "no", r.get("check") or "-", r.get("min_confidence")] for r in spec])}


def d_prove(ctx: wb.Ctx) -> dict:
    c, a = _engine(ctx)
    labels, spec, kind = _labels(ctx), ctx.records("shape") or ctx.records("fix"), ctx.get("kind") or "invoice"
    names = [d["name"] for d in _docs(ctx) if d["name"] in labels and _kind(d["name"], labels[d["name"]]) == kind]
    res = _read_all(ctx, c, a, names, labels)
    straight, auto_rows, all_rows, routed = 0, [], [], []
    for n, r in res.items():
        why = doubts(r, kind, spec)
        for s in spec:
            fld = s["field"]
            if fld in labels[n]:
                row = {"doc": n, "field": fld, "expected": labels[n][fld], "got": (r["fields"].get(fld) or {}).get("value"), "ok": same(fld, labels[n][fld], (r["fields"].get(fld) or {}).get("value"))}
                all_rows.append(row)
                if not why:
                    auto_rows.append(row)
        if why:
            routed.append({"doc": n, "why": "; ".join(why)})
        else:
            straight += 1
    wrong_routed = [x for x in all_rows if not x["ok"] and not any(r["doc"] == x["doc"] for r in routed)]
    rows = [ctx.proof("accuracy", label="What goes straight through is right", rows=auto_rows, min_pct=99.0),
            ctx.proof("accuracy", label="All labelled fields (before a person looks)", rows=all_rows, min_pct=90.0),
            _w2.gate("caught", "Every wrong field is caught for a person", "fail" if wrong_routed else "pass", len(wrong_routed), 0,
                     "; ".join(f"{x['doc']} {x['field']}" for x in wrong_routed[:5]) or "each wrong field is in a document a person checks"),
            _w2.gate("straight", "Documents that go straight through", "pass" if straight else "warn", f"{straight} of {len(res)}", "most of them", "; ".join(f"{r['doc']}: {r['why']}" for r in routed[:4]))]
    rows[0]["name"], rows[1]["name"] = "auto", "all"
    ctx.put("proof", {"straight": straight, "documents": len(res), "routed": routed})
    bad = [g for g in rows if g["status"] == "fail"]
    return {"summary": f"{straight} of {len(res)} labelled document(s) go straight through, all right; {len(routed)} go to a person with the reason." + (" Send it back to Shape: " + bad[0]["label"] if bad else ""),
            "counts": {"documents": len(res), "straight": straight, "fail": len(bad)}, "data": _w2.gates(rows), "ok": not bad}


def d_ship(ctx: wb.Ctx) -> dict:
    p, cfg = ctx.get("proof") or {}, ctx.get("config") or {}
    return {"summary": f"Go live: the {cfg.get('kind')} type on {cfg.get('engine')} - {p.get('straight')} of {p.get('documents')} labelled documents straight through; every doubt goes to a person.",
            "data": {"items": [{"title": "Fields", "detail": ", ".join(f["field"] + (" (required)" if f.get("required") else "") for f in cfg.get("fields") or [])},
                               {"title": "Then", "detail": "A Run item reads the documents that arrive; a person checks the ones in doubt before the results go on."}]}}


def d_run(ctx: wb.Ctx) -> dict:
    cfg = ctx.get("config") or {}
    if not ctx.get("run_item"):
        sources = [c["id"] for c in ctx.connections() if c["kind"] in src.SOURCE_KINDS]
        it = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Read the {cfg.get('kind')}s that arrive, set up by {ctx.id}.", connections=[cfg["connection"]] + sources,
                       scope={"config": cfg, "schedule": {"every": "hour", "tz": "UTC"}, "_source_ok": True, **({"folder": ctx.scope["folder"]} if ctx.scope.get("folder") else {})},
                       approver=ctx.st.get("approver"), parent=ctx.id, start_now=False)
        ctx.put("run_item", it["id"])
    return {"summary": "Live: a Run item reads the documents uploaded to it" + (" and those arriving in the mailbox or folder" if any(c["kind"] in src.SOURCE_KINDS for c in ctx.connections()) else "")
                       + " and routes the ones in doubt to a person.", "counts": {"live": 1},
            "data": {"href": f"#/m/{MODULE}/i/{ctx.get('run_item')}", "label": "Open the Run item", "text": "Upload documents to the Run item; each round reads the new ones."}}


# ================================================================== Change (a live document type, or its engine)

def _live_runs(u: dict) -> list[tuple[str, str]]:
    from . import _w4
    rows = db.q("SELECT id, title FROM wb_items WHERE module = ? AND work = 'run' AND closed IS NULL ORDER BY updated DESC", (MODULE,))
    rows = _w4.visible_items(u, [{**r, "item": r["id"]} for r in rows])
    return [(r["id"], r["title"]) for r in rows]


def _measure(ctx: wb.Ctx, c: dict, a: ie.Engine, spec: list[dict], kind: str, labels: dict) -> dict:
    """A document type on an engine, measured on the labelled sample: what goes straight through, what is right, what
    is caught for a person."""
    names = [d["name"] for d in _docs(ctx) if d["name"] in labels and _kind(d["name"], labels[d["name"]]) == kind]
    res = _read_all(ctx, c, a, names, labels)
    straight, right, fields, routed, wrong_through = 0, 0, 0, [], []
    for n, r in res.items():
        why = doubts(r, kind, spec)
        wrong = [s["field"] for s in spec if s["field"] in labels[n] and not same(s["field"], labels[n][s["field"]], (r["fields"].get(s["field"]) or {}).get("value"))]
        fields += sum(1 for s in spec if s["field"] in labels[n])
        right += sum(1 for s in spec if s["field"] in labels[n]) - len(wrong)
        if why:
            routed.append({"doc": n, "why": "; ".join(why)})
        else:
            straight += 1
            wrong_through += [f"{n} {f}" for f in wrong]
    return {"documents": len(res), "straight": straight, "right_pct": round(100 * right / fields, 1) if fields else 0.0, "routed": routed, "wrong_through": wrong_through}


def _run_item(ctx: wb.Ctx) -> dict:
    rid = ctx.get("run_item") or ctx.scope.get("run_item")
    try:
        return wb._load(rid)
    except Exception as e:  # noqa: BLE001
        raise wb.StepFailed("The Run item this change is for is not there any more.") from e


def _is_engine(ctx: wb.Ctx, cid: str) -> bool:
    try:
        return isinstance(_w2.adapter(ctx.connection(cid)), ie.Engine)
    except wb.StepFailed:
        return False


def _today(ctx: wb.Ctx, run: dict) -> tuple[dict, dict, ie.Engine]:
    """The Run item's document type and the engine it reads with today."""
    cfg = dict((run.get("scope") or {}).get("config") or {})
    kind = cfg.get("kind") or "invoice"
    cfg.setdefault("kind", kind)
    cfg["fields"] = cfg.get("fields") or default_spec(kind)
    cid = cfg.get("connection") or next((x for x in run.get("connections") or [] if _is_engine(ctx, x)), None)
    if not cid:
        raise wb.StepFailed("The Run item has no engine to read with.")
    c = ctx.connection(cid)
    cfg["connection"], cfg["engine"] = c["id"], c["kind"]
    return cfg, c, _w2.adapter(c)


def c_request(ctx: wb.Ctx) -> dict:
    rid = ctx.scope.get("run_item")
    if not rid:
        raise wb.StepFailed("Name the live document type: the Run item it reads with.")
    u = db.user(ctx.owner or "")
    try:
        wb._item(MODULE, rid, u, "edit")
    except Exception as e:  # noqa: BLE001 - HTTPException: not theirs to change
        raise wb.StepFailed("Only the Run item's owner, or a builder it is shared with, can change its document type.") from e
    run = _run_item(ctx)
    if run.get("work") != "run":
        raise wb.StepFailed("That item is not a Run item of document processing.")
    cfg, oc, oa = _today(ctx, run)
    c, a = _engine(ctx)
    labels, docs = _labels(ctx), _docs(ctx)
    if not docs or not labels:
        raise wb.StepFailed("Upload a labelled sample: the documents and truth.json with what each says - the change is proven on it.")
    move = c["id"] != oc["id"]
    ctx.put("run_item", rid)
    ctx.put("kind", cfg["kind"])
    ctx.put("today", cfg)
    ctx.put("move", move)
    return {"summary": f"The {cfg['kind']} type of \"{run['title']}\", on {oa.label} today" + (f", to move to {a.label} ({c['name']})" if move else "")
                       + f"; proven on {sum(1 for d in docs if d['name'] in labels)} labelled document(s).", "counts": {"documents": len(docs), "fields": len(cfg["fields"])},
            "data": _w2.table(["Field", "Required", "Check", "Confidence line"], [[f["field"], "yes" if f.get("required") else "no", f.get("check") or "-", f.get("min_confidence")] for f in cfg["fields"]])}


def c_diagnose(ctx: wb.Ctx) -> dict:
    cfg = ctx.get("today") or {}
    oc = ctx.connection(cfg["connection"])
    oa = _w2.adapter(oc)
    m = _measure(ctx, oc, oa, cfg["fields"], cfg["kind"], _labels(ctx))
    ctx.put("before", m)
    rows = [_w2.gate("today-straight", f"Today, on {oa.label}: documents straight through", "pass", f"{m['straight']} of {m['documents']}", "",
                     "; ".join(f"{r['doc']}: {r['why']}" for r in m["routed"][:4]) or "every document straight through"),
            _w2.gate("today-right", "Today: labelled fields read right (before a person looks)", "pass", f"{m['right_pct']} %", ""),
            _w2.gate("today-through-wrong", "Today: wrong fields that go straight through", "fail" if m["wrong_through"] else "pass", len(m["wrong_through"]), 0,
                     ", ".join(m["wrong_through"][:6]) or "none")]
    return {"summary": f"Today's type on {oa.label}: {m['straight']} of {m['documents']} labelled document(s) straight through, {m['right_pct']} % of fields right"
                       + (f", {len(m['wrong_through'])} wrong field(s) not caught - the change should catch them" if m["wrong_through"] else "") + ".",
            "counts": {"documents": m["documents"], "straight": m["straight"]}, "data": _w2.gates(rows)}


def c_fix(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    cur = (ctx.get("today") or {}).get("fields") or default_spec(ctx.get("kind") or "invoice")
    recs = have or [{"id": f["field"], **{k: f.get(k) for k in ("field", "required", "check", "min_confidence")}} for f in cur]
    was = {f["field"]: f for f in cur}
    diff = [r["field"] for r in recs if any(str(r.get(k)) != str((was.get(r["field"]) or {}).get(k)) for k in ("required", "check", "min_confidence"))]
    return {"summary": f"{len(recs)} field(s) as they are today" + (f"; changed: {', '.join(diff)}" if diff else "") + " - change a check, a required field or a confidence line, then confirm.",
            "records": recs, "counts": {"fields": len(recs), "changed": len(diff)},
            "data": _w2.table(["Field", "Required", "Check", "Confidence line", "Changed"], [[r["field"], "yes" if r.get("required") else "no", r.get("check") or "-", r.get("min_confidence"),
                                                                                         "yes" if r["field"] in diff else ""] for r in recs])}


def c_prove(ctx: wb.Ctx) -> dict:
    out = d_prove(ctx)
    c, a = _engine(ctx)
    after = _measure(ctx, c, a, ctx.records("fix"), ctx.get("kind") or "invoice", _labels(ctx))
    before = ctx.get("before") or {}
    ctx.put("after", after)
    worse = after["straight"] < before.get("straight", 0) or after["right_pct"] < before.get("right_pct", 0)
    g = _w2.gate("against-today", "Against today: straight through and fields right, before and after the change", "warn" if worse else "pass",
                 f"{before.get('straight')} {after['straight']} of {after['documents']} straight; {before.get('right_pct')} % {after['right_pct']} % right",
                 "no worse than today", ("fewer go straight through or fewer fields are right than today: a person decides whether that is the price of catching more" if worse else
                                         "as good as today or better") + (f"; it moves to {a.label}" if ctx.get("move") else ""))
    out["data"]["checks"].append(g)
    out["summary"] += f" Today {before.get('straight')} of {before.get('documents')} went straight through" + (f" on the current engine; on {a.label}, {after['straight']}." if ctx.get("move") else f"; with the change, {after['straight']}.")
    return out


def c_approve(ctx: wb.Ctx) -> dict:
    cur = {f["field"]: f for f in (ctx.get("today") or {}).get("fields") or []}
    diff = [f"{r['field']}: " + ", ".join(f"{k} {(cur.get(r['field']) or {}).get(k)} {r.get(k)}" for k in ("required", "check", "min_confidence")
                                          if str(r.get(k)) != str((cur.get(r['field']) or {}).get(k))) for r in ctx.records("fix")
            if any(str(r.get(k)) != str((cur.get(r["field"]) or {}).get(k)) for k in ("required", "check", "min_confidence"))]
    c, a = _engine(ctx)
    b, af = ctx.get("before") or {}, ctx.get("after") or {}
    return {"summary": f"Change the live {ctx.get('kind')} type: {len(diff)} field(s) changed" + (f", moved to {a.label}" if ctx.get("move") else "")
                       + f"; {b.get('straight')} {af.get('straight')} of {af.get('documents')} labelled documents straight through.",
            "data": {"items": [{"title": "Fields changed", "detail": "; ".join(diff) or "none"}] + ([{"title": "Engine", "detail": f"{(ctx.get('today') or {}).get('engine')} {a.kind} ({c['name']})"}] if ctx.get("move") else [])
                     + [{"title": "Then", "detail": "The Run item reads the next documents with the changed type; the type as it was is kept on the item."}]}}


def c_learn(ctx: wb.Ctx) -> dict:
    c, a = _engine(ctx)
    rid = ctx.get("run_item")
    old = ctx.get("today") or {}
    new = {"kind": ctx.get("kind"), "engine": a.kind, "connection": c["id"], "fields": [{k: r.get(k) for k in ("field", "required", "check", "min_confidence")} for r in ctx.records("fix")]}

    def switch(st):
        sc = st.setdefault("scope", {})
        hist = list(sc.get("config_history") or [])
        hist.append({**old, "until": time.time(), "changed_by": ctx.id})
        sc["config_history"] = hist[-20:]
        sc["config"] = new
        if ctx.get("move"):
            st["connections"] = [x for x in st.get("connections") or [] if x != old.get("connection")] + ([c["id"]] if c["id"] not in (st.get("connections") or []) else [])
    wb._mutate(rid, switch)
    store.note(rid, "Document type changed", f"By {ctx.title} ({ctx.id}): " + (f"moved to {a.label}; " if ctx.get("move") else "") + "the fields, checks and confidence lines as approved.")
    db.audit("idp.type.change", rid, {"from": old.get("engine"), "to": a.kind, "change": ctx.id}, ctx.who or ctx.owner)
    ctx.output("document-type.json", json.dumps(new, indent=2), label="The document type as changed (fields, checks, confidence lines)")
    return {"summary": f"Live: \"{_run_item(ctx)['title']}\" reads with the changed type" + (f" on {a.label}" if ctx.get("move") else "") + "; the type as it was is kept on the Run item.",
            "counts": {"changed": 1}, "data": {"href": f"#/m/{MODULE}/i/{rid}", "label": "Open the Run item", "text": "The next round reads with the changed type."}}


# ================================================================== Run

def _cfg(ctx) -> dict:
    cfg = ctx.scope.get("config") or {}
    kind = cfg.get("kind") or ctx.scope.get("kind") or "invoice"
    return {"kind": kind, "fields": cfg.get("fields") or default_spec(kind)}


def _pull(ctx: wb.Ctx) -> list[dict]:
    """The new documents in the item's mailbox and folder, copied into the item (what was taken is remembered)."""
    seen = set(ctx.get("pulled") or [])
    rows, got = [], []
    for c in ctx.connections():
        if c["kind"] not in src.SOURCE_KINDS:
            continue
        try:
            if c["kind"] == "m365_mail":
                new, n = src.pull_mail(c, seen)
                where = f"{n} message(s) with attachments in {c['config'].get('folder') or 'Inbox'}"
            else:
                path = str(ctx.scope.get("folder") or c["config"].get("folder") or "")
                new, n = src.pull_folder(c, path, seen)
                where = f"{n} document(s) in /{path.strip('/')}"
        except Exception as e:  # noqa: BLE001 - ConnectorError / Reconsent: shown to the person, the round goes on with the rest
            rows.append(_w2.gate(f"source-{_w2.slug(c['name'])}", f"{c['name']}: documents taken", "fail", 0, detail=str(e)[:300]))
            continue
        db.audit("connection.read", c["id"], {"kind": c["kind"], "documents": len(new), "module": MODULE}, ctx.who or ctx.owner)
        if new:
            wb.save_files(ctx.id, [(name, data) for _, name, data in new], ctx.who or ctx.owner)
            got += [k for k, _, _ in new]
        rows.append(_w2.gate(f"source-{_w2.slug(c['name'])}", f"{c['name']}: documents taken", "pass", len(new), detail=f"{len(new)} new of {where}"))
    if got:
        ctx.put("pulled", sorted(seen | set(got)))
        ctx.st = wb._load(ctx.id)
    return rows


def r_watch(ctx: wb.Ctx) -> dict:
    c, a = _engine(ctx)
    cfg = _cfg(ctx)
    pulled = _pull(ctx)
    done = set(ctx.get("done") or [])
    new = [d["name"] for d in _docs(ctx) if d["name"] not in done]
    res = _read_all(ctx, c, a, new, {})
    out = []
    for n, r in res.items():
        why = (["the engine could not read it: " + r["error"]] if r.get("error") else []) + doubts(r, cfg["kind"], cfg["fields"])
        out.append({"doc": n, "fields": {k: (v or {}).get("value") for k, v in r["fields"].items()}, "confidence": {k: (v or {}).get("confidence") for k, v in r["fields"].items()},
                    "items": r.get("items") or [], "why": why})
    ctx.put("batch", out)
    ctx.put("done", sorted(done | set(new)))
    checks = [_w2.gate(f"doc-{_w2.slug(x['doc'])}", x["doc"], "warn" if x["why"] else "pass", "to a person" if x["why"] else "straight through", "straight through", "; ".join(x["why"])[:300] or "every field sure and checked")
              for x in out]
    took = sum(int(g.get("measured") or 0) for g in pulled if g["status"] == "pass")
    return {"summary": f"{len(out)} new document(s) read: {sum(1 for x in out if not x['why'])} straight through, {sum(1 for x in out if x['why'])} to a person."
                       + (f" {took} taken from the mailbox or folder." if pulled else ""),
            "counts": {"documents": len(out), "review": sum(1 for x in out if x["why"])},
            "data": _w2.gates(pulled + (checks or [_w2.gate("none", "New documents", "pass", 0, detail="nothing new")]))}


def r_alert(ctx: wb.Ctx) -> dict:
    b = ctx.get("batch") or []
    review = [x for x in b if x["why"]]
    ctx.put("breaks", review)
    if not b:
        return {"summary": "No new document this round.", "next": "report", "counts": {"review": 0}}
    return {"summary": f"{len(review)} document(s) for a person, each with its reason; {len(b) - len(review)} straight through.", "counts": {"review": len(review)},
            "items": [f"{x['doc']}: {'; '.join(x['why'])}"[:240] for x in review[:6]],
            "data": _w2.table(["Document", "Why a person looks"], [[x["doc"], "; ".join(x["why"])] for x in review])}


def r_fix(ctx: wb.Ctx) -> dict:
    cfg = _cfg(ctx)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for x in ctx.get("batch") or []:
        for s in cfg["fields"]:
            f = s["field"]
            rid = f"{x['doc']}::{f}"
            doubt = [w for w in x["why"] if w.startswith(f + " ") or (f in ("InvoiceTotal", "Total") and "subtotal" in w)]
            recs.append({"id": rid, "doc": x["doc"], "field": f, "value": (have.get(rid) or {}).get("value", x["fields"].get(f)), "read": x["fields"].get(f),
                         "confidence": x["confidence"].get(f), "doubt": "; ".join(doubt), "check": "yes" if doubt else ""})
    n = sum(1 for r in recs if r["check"])
    return {"summary": f"{n} field(s) to check in {len({r['doc'] for r in recs if r['check']})} document(s): correct a value in place, then confirm. The rest are shown as read.",
            "records": recs, "counts": {"to check": n}, "data": _w2.table(["Document", "Field", "Value", "Confidence", "Why"], [[r["doc"], r["field"], r["value"], r["confidence"], r["doubt"]] for r in recs if r["check"]])}


def _validate_review(recs, ctx):
    cfg = _cfg(ctx)
    spec = {s["field"]: s for s in cfg["fields"]}
    out = []
    by: dict = {}
    for r in recs:
        by.setdefault(r["doc"], {})[r["field"]] = r.get("value")
    for doc, f in by.items():
        fake = {"fields": {k: {"value": v, "confidence": 1.0} for k, v in f.items()}}
        for w in doubts(fake, cfg["kind"], list(spec.values())):
            out.append(f"{doc}: {w}")
    return out


REVIEW_EDIT = wb.Edit(columns=[wb.Column("value", "Value"), wb.Column("doc", "Document", readonly=True), wb.Column("field", "Field", readonly=True), wb.Column("doubt", "Why", readonly=True)],
                      add=False, remove=False, validate=_validate_review, label="field")


def r_approve(ctx: wb.Ctx) -> dict:
    cfg = _cfg(ctx)
    by: dict = {}
    for r in ctx.records("fix"):
        by.setdefault(r["doc"], {})[r["field"]] = r.get("value")
    corrected = sum(1 for r in ctx.records("fix") if str(r.get("value")) != str(r.get("read")))
    cols = ["document"] + [s["field"] for s in cfg["fields"]]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for doc, f in by.items():
        w.writerow([doc] + [f.get(k) for k in cols[1:]])
    stamp = ctx.st.get("round") or len(ctx.st.get("rounds") or []) + 1
    ctx.output(f"results-{stamp}.csv", buf.getvalue(), label=f"Results of round {stamp} (CSV)")
    ctx.output(f"results-{stamp}.json", json.dumps(by, indent=1, default=str), label=f"Results of round {stamp} (JSON)")
    h = ctx._handoff({"kind": "results", "label": f"{len(by)} document(s) read and checked", "status": f"written: results-{stamp}.csv ({corrected} value(s) a person corrected)"})
    return {"summary": f"{len(by)} document(s) written out as approved, {corrected} value(s) corrected by a person.", "counts": {"documents": len(by), "corrected": corrected},
            "data": _w2.table(["Document", "Fields"], [[d, len(f)] for d, f in by.items()]), "handoff": h}


def r_report(ctx: wb.Ctx) -> dict:
    w = (ctx.result("watch") or {}).get("counts") or {}
    hist = [[r.get("ended"), (next((s for s in r["steps"] if s["id"] == "watch"), {}).get("counts") or {}).get("documents"),
             (next((s for s in r["steps"] if s["id"] == "watch"), {}).get("counts") or {}).get("review")] for r in (ctx.st.get("rounds") or [])[-11:]]
    hist.append(["this round", w.get("documents"), w.get("review")])
    return {"summary": f"{w.get('documents') or 0} document(s) this round, {w.get('review') or 0} checked by a person.", "counts": {"documents": w.get("documents") or 0},
            "data": _w2.table(["Round", "Documents", "To a person"], hist)}


GUIDE = """# Document processing - the work item

Relay's document processing reads invoices and receipts with the engine you run, checks every field by rules, and
shows a person every field it is not sure of before the results go on. Accuracy is measured on documents a person
labelled - never guessed. Nothing is invented: a value comes from the engine or from the person who corrected it."""

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each document type as a node, the engine it runs on and where its results go",
    schemas={"inventory": ["include", "document", "kind", "labelled"], "finding": ["decision", "engine", "what"]},
    work={
        "assess": wb.Work(title="See which engine reads your documents right, and how many need a person", fields=[wb.Field("volume", "Documents a month", "number", help="to size the review effort")], steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="The engines you connected answer; the sample documents and their labels are uploaded"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Scanner", edit=INV_EDIT, text="Each document, its type and whether it is labelled"),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Checker", text="Every engine reads every document: accuracy against the labels, and how many need a person"),
            "Findings": wb.Step(kind="deterministic", run=a_findings, agent="Checker", edit=FIND_EDIT, text="The engine that fits, the fields each gets wrong, the review share"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="Set-up effort and a person's review hours a month")}),
        "develop": wb.Work(title="Set up a document type - fields, checks, the confidence line - proven on your labelled documents",
                           fields=[wb.Field("kind", "Document type", "select", options=(("invoice", "Supplier invoices"), ("receipt", "Receipts")), default="invoice")], steps={
            "Describe": wb.Step(kind="deterministic", run=d_describe, agent="Reader", text="The document type and the labelled sample it is proven on"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Designer", edit=SHAPE_EDIT, text="The fields, each one's check and the confidence below which a person looks - you set them"),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Builder", text="The document type written for the engine it runs on"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Checker", back_to="shape", text="On the labelled set: what goes straight through is right, and every wrong field is caught for a person"),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver signs off"),
            "Run": wb.Step(kind="platform", run=d_run, view="link", agent="Deployer", text="A Run item reads the documents that arrive")}),
        "change": wb.Work(title="Change a live document type - its fields, checks and confidence lines, or the engine it runs on - proven on your labelled documents first",
                          platforms=tuple(k for k in PLATFORMS if k not in SOURCE_PLATFORMS),
                          fields=[wb.Field("run_item", "The live document type (its Run item)", "select", options=_live_runs, required=True)], steps={
            "Request": wb.Step(kind="platform", run=c_request, agent="Reader", text="The live type, the engine it moves to (or the same one) and the labelled sample it is proven on"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, view="gates", agent="Checker", text="Today's type on today's engine, measured on the sample: straight through, right, caught"),
            "Fix": wb.Step(kind="deterministic", run=c_fix, agent="Designer", edit=SHAPE_EDIT, confirm="the fields, checks and confidence lines as they will be",
                           text="The fields as they are today - you change a check, a required field or a confidence line"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Checker", back_to="fix",
                             text="On the sample, on the engine it will run on: what goes straight through is right, every wrong field is caught, and against today"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver signs the change off"),
            "Learn": wb.Step(kind="platform", run=c_learn, view="link", agent="Deployer", text="The Run item switches to the changed type (and engine); the type as it was is kept on it")}),
        "run": wb.Work(title="Read the documents that arrive; a person checks every doubt before the results go on", needs_source=False, schedule_from="Watch",
                       fields=[wb.Field("schedule", "Read them", "cadence", default={"every": "hour", "tz": "UTC"}),
                               wb.Field("folder", "The SharePoint or OneDrive folder to read (when one is connected)", help="A path in the library, such as Invoices/Incoming.")], steps={
            "Watch": wb.Step(kind="platform", run=r_watch, view="gates", agent="Reader",
                             text="The documents that arrived since the last round - uploaded, in the mailbox or in the folder - read by the engine and checked by rules"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", confirm=False, text="The documents in doubt, each with its reason"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Reviewer", edit=REVIEW_EDIT, confirm="the values, corrected where the engine was not sure",
                           text="A person checks the fields in doubt and corrects them in place"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="The approved results are written out (CSV and JSON)"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm=False, text="Documents read and checked, round by round")}),
    }))
