"""Tool & vendor selection (registry id `selection`) - choosing a platform with the reasons written down: the RFP & bid
response engine (P11) the other way round, as a consulting engagement.

Engagement  Requirements -> Long list -> Issue -> Score -> PoC -> Recommend.
Requirements  read from an uploaded requirements sheet (CSV / Excel: id, requirement, category, weight, mandatory) -
            rules first - or, from Word / PDF documents, by the agent ("Ask Relay to read the requirements"), every
            requirement with the file and page it came from; a person corrects them; the weights add up to 100.
Long list   the candidates Relay's own catalogue lists for the kind of tool (the module's platforms, e.g. BI &
            dashboards: Power BI, Tableau, Looker ...) plus any a person adds with the reason; a person picks the short
            list the RFP goes to (two at least).
Issue       the RFP pack to issue: the RFP document (Word, through the P11 docs engine: scope, requirements with their
            weights, how to answer, how answers are scored) and one response workbook per vendor (Excel: every
            requirement with Comply / Partial / Not / Alternative - RFP & bid response's own statuses - the answer
            and its evidence). A person sends it; Relay sends nothing.
Score       the vendors' completed workbooks are uploaded and read ("Read the responses"): points per requirement
            (Comply 1, Partial and Alternative ½, Not 0 - the method the RFP stated) × its weight; a mandatory
            requirement answered Not excludes the vendor; every score carries the vendor's own answer and evidence.
            A person may change a status, with the reason.
PoC         the proof of concept for the leading vendors: each success criterion (the mandatory requirements) with its
            result and where the evidence is.
Recommend   the recommendation: the best weighted score among the vendors that met every mandatory requirement and
            passed the proof of concept, with the decision memo (Word) and the decision deck (PowerPoint) through the
            docs engine, every figure sourced - a person confirms the decision.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time

from .. import registry
from .. import workbench as wb
from . import _consult as cx
from . import _narrative as nv

MODULE = "selection"
STATUSES = ("Comply", "Partial", "Not", "Alternative")     # RFP & bid response's own (rfp.STATUSES)
POINTS = {"Comply": 1.0, "Partial": 0.5, "Alternative": 0.5, "Not": 0.0}
RESULTS = (("planned", "Planned"), ("passed", "Passed"), ("failed", "Failed"))


class RequirementsPlatform(wb.Platform):
    label = "Requirements and vendors' responses"
    uploads = (".csv", ".xlsx", ".docx", ".pdf", ".txt", ".md")
    reads = ("your requirements (a sheet, or Word / PDF documents the agent reads with page references) and the response workbooks the vendors "
             "send back - copies in this work item's folder; nothing is sent from here")
    simulator = "requirements sheets, documents and completed response workbooks the tests write"


DOCS = RequirementsPlatform()


def _categories(u=None) -> list[tuple[str, str]]:
    return [(m["id"], f"{m['name']} - {', '.join(m['platforms'][:4])}") for m in registry.MODULES if m["pl"] not in ("hidden", "platform") and len(m["platforms"]) >= 2]


# ------------------------------------------------------------------ Requirements

def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("yes", "y", "true", "1", "mandatory", "must", "x")


def _sheet_rows(ctx: wb.Ctx) -> tuple[list[dict], list[str]]:
    out, notes = [], []
    for f in ctx.files((".csv", ".xlsx")):
        p = ctx.dir / "data" / (f.get("table") or f["name"])
        try:
            rows = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8-sig"))))
        except (OSError, UnicodeDecodeError):
            continue
        if not rows:
            continue
        h = {c.strip().lower(): i for i, c in enumerate(rows[0])}
        col = lambda *ns: next((h[n] for n in ns if n in h), None)  # noqa: E731
        if f["name"].lower().startswith("rfp-") or "status" in h:
            continue                                       # a vendor's response workbook: read at Score
        ti = col("requirement", "text", "description")
        if ti is None:
            notes.append(f"{f['name']}: no requirement column")
            continue
        ii, ci, wi, mi, ei = col("id", "ref", "#"), col("category", "area"), col("weight", "weighting"), col("mandatory", "must"), col("evidence", "how to evidence")
        for n, r in enumerate(rows[1:], 1):
            if len(r) <= ti or not r[ti].strip():
                continue
            g = lambda i: r[i].strip() if i is not None and i < len(r) else ""  # noqa: E731
            try:
                w = float(g(wi)) if g(wi) else None
            except ValueError:
                w = None
            ref = _ref(g(ii) or f"R{n}")
            out.append({"id": ref, "ref": ref, "text": r[ti].strip(), "category": g(ci) or "General", "weight": w, "mandatory": _truthy(g(mi)),
                        "evidence": g(ei), "source": f"{f['name']} row {n + 1}", "origin": "sheet"})
    return out, notes


def _ref(s) -> str:
    return re.sub(r"[^A-Za-z0-9.\-]+", "", str(s or "")).upper()[:20]


def requirements(ctx: wb.Ctx) -> dict:
    fresh, notes = _sheet_rows(ctx)
    have = ctx.records(ctx.step_id)
    ids = {r.get("ref") for r in have}
    recs = have + [r for r in fresh if r["ref"] not in ids]
    docs = ctx.files((".docx", ".pdf", ".txt", ".md"))
    tot = sum(float(r.get("weight") or 0) for r in recs)
    return {"summary": f"{len(recs)} requirement(s)" + (f" read from the sheet" if fresh else "") + (f"; {len(docs)} document(s) Relay can read for more" if docs else "")
                       + (f"; {'; '.join(notes)}" if notes else "") + f". The weights add up to {cx.num(tot)} - they must add up to 100.",
            "counts": {"requirements": len(recs), "mandatory": sum(1 for r in recs if r.get("mandatory")), "documents": len(docs)}, "records": recs,
            "data": {"columns": ["Id", "Requirement", "Category", "Weight", "Mandatory", "From"], "rows": [[r.get("ref"), r["text"], r.get("category"), r.get("weight"), "yes" if r.get("mandatory") else "no", r.get("source")] for r in recs]}}


def _req_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if recs else ["Add the requirements (upload a sheet, ask Relay to read the documents, or type them in)."]
    seen, tot = set(), 0.0
    for r in recs:
        r["ref"] = _ref(r.get("ref"))
        if not r["ref"]:
            probs.append(f"{str(r.get('text') or 'A requirement')[:40]}: give it an id.")
        if not str(r.get("text") or "").strip():
            probs.append(f"{r.get('ref')}: the requirement is empty.")
        if r["ref"] and r["ref"] in seen:
            probs.append(f"{r.get('ref')}: two requirements share this id.")
        seen.add(r["ref"])
        try:
            w = float(r.get("weight"))
        except (TypeError, ValueError):
            w = None
        if w is None or w < 0:
            probs.append(f"{r.get('ref')}: the weight is a number (zero or more).")
        else:
            tot += w
    if recs and abs(tot - 100) > 0.01:
        probs.append(f"The weights add up to {cx.num(tot)}: they must add up to 100, so the scores compare.")
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("text", "category", "evidence"))


REQ_EDIT = wb.Edit(columns=[wb.Column("ref", "Id"), wb.Column("text", "Requirement", "longtext", required=True), wb.Column("category", "Category"),
                            wb.Column("weight", "Weight", "number"), wb.Column("mandatory", "Mandatory", "bool"), wb.Column("evidence", "How to evidence it"),
                            wb.Column("source", "From", readonly=True)], validate=_req_validate, label="requirement")

READ_REQS = """FILE requirements.yaml - read WORK.md, then every document in data/ with `genbi read data/<file>` (Word, PDF,
text). List each requirement the documents state:

requirements:
  - {id: R1, text: "<the requirement in one sentence>", category: "<area>", mandatory: true|false, source: "<file name>", page: <page or section>}

Only requirements the documents state, with the file and page they came from; no weights (a person sets them); no
requirement that is not in the documents."""


def _read_prompt(ctx: wb.Ctx) -> str:
    if not ctx.files((".docx", ".pdf", ".txt", ".md")):
        raise wb.StepFailed("Upload the requirement documents (Word, PDF or text) first.")
    return READ_REQS


def _read_check(ctx: wb.Ctx) -> list[str]:
    import yaml
    p = ctx.dir / "requirements.yaml"
    if not p.exists():
        return ["requirements.yaml was not written"]
    try:
        y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return [f"requirements.yaml does not parse: {str(e).splitlines()[0][:200]}"]
    reqs = y.get("requirements") if isinstance(y, dict) else None
    if not isinstance(reqs, list) or not reqs:
        return ["requirements.yaml needs `requirements:` - a list"]
    files = {f["name"] for f in ctx.files()}
    probs, seen = [], set()
    for i, r in enumerate(reqs, 1):
        if not isinstance(r, dict) or not str(r.get("text") or "").strip():
            probs.append(f"requirement {i}: text is empty")
            continue
        if str(r.get("source") or "") not in files:
            probs.append(f"requirement {r.get('id') or i}: source {r.get('source')!r} is not one of the uploaded files ({', '.join(sorted(files))})")
        if r.get("page") in (None, ""):
            probs.append(f"requirement {r.get('id') or i}: say the page or section it came from")
        if r.get("id") in seen:
            probs.append(f"requirement {r.get('id')}: two share this id")
        seen.add(r.get("id"))
        if r.get("weight") is not None:
            probs.append(f"requirement {r.get('id') or i}: leave the weight out - a person sets it")
    return probs


def _read_after(ctx: wb.Ctx, res: dict) -> dict:
    import yaml
    y = yaml.safe_load((ctx.dir / "requirements.yaml").read_text(encoding="utf-8")) or {}
    recs = ctx.records(ctx.step_id)
    refs = {r.get("ref") for r in recs}
    n = 0
    for r in y.get("requirements") or []:
        ref = _ref(r.get("id") or f"D{n + 1}") or f"D{n + 1}"
        while ref in refs:
            ref += "X"
        refs.add(ref)
        recs.append({"id": f"doc-{ref}", "ref": ref, "text": str(r["text"]).strip(), "category": str(r.get("category") or "General"), "weight": None, "mandatory": bool(r.get("mandatory")),
                     "evidence": "", "source": f"{r['source']} p. {r['page']}", "origin": "agent"})
        n += 1
    ctx.evidence("Requirements Relay read from the documents", {"requirements": y.get("requirements"), "note": res.get("text") or ""}, kind="agent", ok=True)
    tot = sum(float(r.get("weight") or 0) for r in recs)
    return {"summary": f"Relay read {n} requirement(s) from the documents, each with its file and page - set their weights (the total is {cx.num(tot)}; it must be 100).",
            "records": recs, "data": {"columns": ["Id", "Requirement", "Category", "Weight", "Mandatory", "From"],
                                      "rows": [[r.get("ref"), r["text"], r.get("category"), r.get("weight"), "yes" if r.get("mandatory") else "no", r.get("source")] for r in recs]}}


# ------------------------------------------------------------------ Long list

def long_list(ctx: wb.Ctx) -> dict:
    cat = registry.BY_ID.get(ctx.scope.get("category") or "") or {}
    fresh = [{"id": cx.slug(p, 40), "vendor": p, "why": f"Listed by Relay's catalogue for {cat['name']}", "source": f"module:{cat['id']}", "shortlist": i < 3, "origin": "catalogue"}
             for i, p in enumerate(cat.get("platforms") or [])]
    recs = cx.keep_edits(ctx, fresh, ("shortlist", "why"))
    short = [r for r in recs if r.get("shortlist")]
    return {"summary": f"{len(recs)} candidate(s) on the long list from Relay's catalogue for {cat.get('name', 'this kind of tool')} - add any other with the reason, "
                       f"and tick the short list the RFP goes to ({len(short)} now).",
            "counts": {"long list": len(recs), "short list": len(short)}, "records": recs,
            "data": {"columns": ["Short list", "Vendor or tool", "Why it is on the list"], "rows": [["yes" if r.get("shortlist") else "no", r["vendor"], r["why"]] for r in recs]}}


def _long_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if sum(1 for r in recs if r.get("shortlist")) >= 2 else ["Put at least two on the short list: a selection needs an alternative."]
    probs += [f"{r.get('vendor') or 'A row'}: why is it on the list?" for r in recs if not str(r.get("why") or "").strip()]
    probs += [f"Row {i}: name the vendor or tool." for i, r in enumerate(recs, 1) if not str(r.get("vendor") or "").strip()]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("vendor", "why"))


LONG_EDIT = wb.Edit(columns=[wb.Column("shortlist", "Short list", "bool"), wb.Column("vendor", "Vendor or tool", required=True), wb.Column("why", "Why it is on the list")],
                    validate=_long_validate, label="candidate")


# ------------------------------------------------------------------ Issue: the RFP pack, the other way round

def _reqs(ctx: wb.Ctx) -> list[dict]:
    return [{**{k: r.get(k) for k in ("text", "category", "weight", "mandatory", "evidence", "source")}, "id": r.get("ref")} for r in ctx.records("requirements")]


def _short(ctx: wb.Ctx) -> list[dict]:
    return [r for r in ctx.records("long-list") if r.get("shortlist")]


def _workbook(ctx: wb.Ctx, vendor: str, reqs: list[dict]) -> bytes:
    import openpyxl
    from openpyxl.worksheet.datavalidation import DataValidation
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Response"
    ws.append(["Id", "Requirement", "Category", "Weight", "Mandatory", "Status", "Response", "Evidence"])
    for r in reqs:
        ws.append([r["id"], r["text"], r["category"], r["weight"], "yes" if r["mandatory"] else "no", "", "", ""])
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"F2:F{len(reqs) + 1}")
    v = book.create_sheet("Vendor")
    for k, val in (("Vendor", vendor), ("Selection", ctx.title), ("Responses due", ctx.scope.get("due") or ""), ("Item", ctx.id)):
        v.append([k, val])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def issue(ctx: wb.Ctx) -> dict:
    reqs, short = _reqs(ctx), _short(ctx)
    rec = {"requirements": len(reqs), "mandatory": sum(1 for r in reqs if r["mandatory"]), "short_list": len(short), "long_list": len(ctx.records("long-list")),
           "due": ctx.scope.get("due") or "", "points": POINTS, "vendors": [r["vendor"] for r in short],
           "rows": [[r["id"], r["text"], r["category"], cx.num(r["weight"]), "yes" if r["mandatory"] else "no"] for r in reqs],
           "vendor_rows": [[r["vendor"], r["why"]] for r in short]}
    cx.put(ctx, "rfp", rec)
    files = []
    for r in short:
        files.append(ctx.output(f"rfp-{cx.slug(r['vendor'])}.xlsx", _workbook(ctx, r["vendor"], reqs), label=f"Response workbook for {r['vendor']} (Excel)"))
    R = "record:rfp"
    p1, f1 = cx.say("We invite you to answer {n} requirements, {m} of them mandatory.", n=(rec["requirements"], f"{R}#requirements"), m=(rec["mandatory"], f"{R}#mandatory"))
    sections = [{"title": "What we are choosing", "blocks": [{"kind": "paragraph", "text": (ctx.brief or f"We are choosing {registry.BY_ID.get(ctx.scope.get('category') or '', {}).get('name', 'a tool')}.").strip()[:1500]},
                                                             {"kind": "paragraph", "text": p1, "figures": f1},
                                                             {"kind": "paragraph", "text": f"Responses are due on {rec['due']}." if rec["due"] else "The response date is in the covering letter."}]},
                {"title": "Requirements", "blocks": [{"kind": "table", "table": cx.table(["Id", "Requirement", "Category", "Weight", "Mandatory"], ch, f"{R}#rows",
                                                                                       "Every requirement with its weight; the weights add up to 100")} for ch in cx.chunks(rec["rows"])]},
                {"title": "How to answer", "blocks": [{"kind": "bullets", "bullets": ["Answer in the response workbook sent with this document, one row per requirement.",
                                                                                     "Status: Comply, Partial, Not or Alternative - with your answer and the evidence (a document, a reference, a demonstration).",
                                                                                     "Leave no requirement unanswered: an empty status scores nothing."]}]},
                {"title": "How answers are scored", "blocks": [{"kind": "bullets", "bullets": ["Comply scores the full weight, Partial and Alternative half of it, Not nothing.",
                                                                                              "A mandatory requirement answered Not ends the response's evaluation.",
                                                                                              "The leading responses are invited to a proof of concept on the mandatory requirements."]}]}]
    doc = {"kind": "doc", "title": f"Request for proposal: {ctx.title}"[:70], "subtitle": f"Issued {cx.iso_day(time.time())}", "audience": "the invited vendors", "date": cx.iso_day(time.time()), "sections": sections}
    a = cx.deliver(ctx, "rfp-pack", doc, "RFP document")
    gates = [a["gate"], ctx.proof("references_real", label="Every vendor on the short list has its response workbook", refs=[f"rfp-{cx.slug(r['vendor'])}.xlsx" for r in short], known=files)]
    return {"summary": (f"The RFP pack: the document and {len(files)} response workbook(s) for {', '.join(r['vendor'] for r in short)} - check them, then send them yourself; Relay sends nothing."
                        if a["ok"] else "The RFP document did not pass its checks: " + "; ".join(a["problems"][:3])),
            "ok": a["ok"], "counts": {"vendors": len(files), "requirements": len(reqs)}, "data": {"checks": gates}}


# ------------------------------------------------------------------ Score: the vendors' answers × the weights

def _vendor_of(ctx: wb.Ctx, f: dict, book) -> str | None:
    names = {cx.slug(r["vendor"]): r["vendor"] for r in _short(ctx)}
    if "Vendor" in book.sheetnames:
        for row in book["Vendor"].iter_rows(values_only=True):
            if row and str(row[0] or "").strip().lower() == "vendor" and row[1]:
                v = str(row[1]).strip()
                if cx.slug(v) in names:
                    return names[cx.slug(v)]
    m = re.match(r"rfp-(.+?)(?:-\d+)?\.xlsx$", f["name"])
    return names.get(m.group(1)) if m else None


def _responses(ctx: wb.Ctx) -> tuple[dict, list[str]]:
    import openpyxl
    out, notes = {}, []
    for f in ctx.files((".xlsx",)):
        try:
            book = openpyxl.load_workbook(ctx.dir / "data" / f["name"], read_only=True, data_only=True)
        except Exception as e:  # noqa: BLE001 - not a workbook a vendor returned
            notes.append(f"{f['name']}: could not be opened ({str(e)[:80]})")
            continue
        if "Response" not in book.sheetnames:
            book.close()
            continue
        v = _vendor_of(ctx, f, book)
        if not v:
            notes.append(f"{f['name']}: no vendor of the short list named in it")
            book.close()
            continue
        rows = {}
        for row in list(book["Response"].iter_rows(values_only=True))[1:]:
            if row and row[0]:
                st = str(row[5] or "").strip().title()
                rows[str(row[0]).strip().upper()] = {"status": st if st in STATUSES else "", "response": str(row[6] or "").strip(), "evidence": str(row[7] or "").strip()}
        book.close()
        out[v] = {"file": f["name"], "rows": rows}
    return out, notes


def score(ctx: wb.Ctx) -> dict:
    reqs = {r["id"]: r for r in _reqs(ctx)}
    resp, notes = _responses(ctx)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = []
    for v, got in resp.items():
        for rid, r in reqs.items():
            a = got["rows"].get(rid) or {"status": "", "response": "", "evidence": ""}
            key = f"{cx.slug(v)}|{rid}"
            old = have.get(key) or {}
            recs.append({"id": key, "vendor": v, "req": rid, "requirement": r["text"][:200], "weight": r["weight"], "mandatory": r["mandatory"],
                         "stated": a["status"] or "(no answer)", "status": old.get("status") or a["status"] or "", "note": old.get("note") or "",
                         "answer": a["response"], "evidence": (a["evidence"] + f" ({got['file']})").strip()})
    _points(recs)
    waiting = [r["vendor"] for r in _short(ctx) if r["vendor"] not in resp]
    tot = _totals(recs, list(resp))
    return {"summary": (f"{len(resp)} response(s) read" + (f"; waiting for {', '.join(waiting)}" if waiting else "") + (f"; {'; '.join(notes)}" if notes else "")
                        + (". " + "; ".join(f"{t['vendor']}: {cx.num(t['score'])} of 100" + (" (excluded: a mandatory requirement answered Not)" if t["excluded"] else "") for t in tot) if tot else
                           ". Upload each vendor's completed workbook, then press Read the responses.")),
            "counts": {"responses": len(resp), "waiting": len(waiting)}, "records": recs,
            "items": [f"{t['vendor']}: {cx.num(t['score'])} of 100" for t in tot],
            "data": {"columns": ["Vendor", "Score (of 100)", "Mandatory met", "Excluded"], "rows": [[t["vendor"], cx.num(t["score"]), f"{t['mandatory_met']} of {t['mandatory']}", "yes" if t["excluded"] else "no"] for t in tot]}}


def _points(recs: list[dict]) -> None:
    for r in recs:
        st = r.get("status") if r.get("status") in STATUSES else ""
        r["points"] = round(POINTS.get(st, 0.0) * float(r.get("weight") or 0), 2)


def _totals(recs: list[dict], vendors: list[str]) -> list[dict]:
    out = []
    for v in vendors:
        rs = [r for r in recs if r["vendor"] == v]
        mand = [r for r in rs if r["mandatory"]]
        out.append({"vendor": v, "score": round(sum(r["points"] for r in rs), 2), "mandatory": len(mand), "mandatory_met": sum(1 for r in mand if r.get("status") in ("Comply", "Partial", "Alternative")),
                    "excluded": any(r.get("status") == "Not" for r in mand), "answered": sum(1 for r in rs if r.get("status") in STATUSES), "requirements": len(rs)})
    return sorted(out, key=lambda t: (t["excluded"], -t["score"], t["vendor"]))


def _score_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [] if recs else ["No response has been read yet: upload the vendors' workbooks and press Read the responses."]
    for r in recs:
        if r.get("status") not in STATUSES:
            probs.append(f"{r['vendor']} - {r['req']}: the status is Comply, Partial, Not or Alternative (the vendor gave none).")
        elif r.get("status") != r.get("stated") and not str(r.get("note") or "").strip():
            probs.append(f"{r['vendor']} - {r['req']}: you changed the vendor's answer ({r.get('stated')} {r['status']}) - say why.")
    _points(recs)
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("note",))


SCORE_EDIT = wb.Edit(columns=[wb.Column("vendor", "Vendor", readonly=True), wb.Column("req", "Id", readonly=True), wb.Column("requirement", "Requirement", readonly=True),
                              wb.Column("stated", "Vendor's answer", readonly=True), wb.Column("status", "Status", "select", options=tuple((s, s) for s in STATUSES)),
                              wb.Column("points", "Points", "number", readonly=True), wb.Column("evidence", "Their evidence", readonly=True),
                              wb.Column("note", "Why you changed it", "longtext")], add=False, remove=False, validate=_score_validate, label="answer")


def _put_scores(ctx: wb.Ctx) -> dict:
    recs = ctx.records("score")
    _points(recs)
    vendors = list(dict.fromkeys(r["vendor"] for r in recs))
    tot = _totals(recs, vendors)
    rec = {"vendors": tot, "by_vendor": {t["vendor"]: t for t in tot}, "points": POINTS, "count": len(tot),
           "rows": [[t["vendor"], cx.num(t["score"]), f"{t['mandatory_met']} of {t['mandatory']}", "yes" if t["excluded"] else "no"] for t in tot],
           "answers": [[r["vendor"], r["req"], r["stated"], r["status"], cx.num(r["points"]), (r.get("note") or r.get("evidence") or "-")[:160]] for r in recs]}
    cx.put(ctx, "scores", rec)
    return rec


# ------------------------------------------------------------------ PoC

def poc(ctx: wb.Ctx) -> dict:
    sc = _put_scores(ctx)
    n = int(float(ctx.scope.get("poc_count") or 2))
    lead = [t for t in sc["vendors"] if not t["excluded"]][:max(1, n)]
    crit = [r for r in _reqs(ctx) if r["mandatory"]] or sorted(_reqs(ctx), key=lambda r: -float(r["weight"] or 0))[:3]
    fresh = [{"id": f"{cx.slug(t['vendor'])}|{c['id']}", "vendor": t["vendor"], "criterion": f"{c['id']}: {c['text'][:140]}", "result": "planned", "evidence": "", "when": ""}
             for t in lead for c in crit]
    recs = cx.keep_edits(ctx, fresh, ("result", "evidence", "when"))
    return {"summary": f"A proof of concept for {', '.join(t['vendor'] for t in lead)} on {len(crit)} criterion(s) - record each result and where its evidence is.",
            "counts": {"vendors": len(lead), "criteria": len(crit)}, "records": recs,
            "data": {"columns": ["Vendor", "Criterion", "Result", "Evidence"], "rows": [[r["vendor"], r["criterion"], r["result"], r.get("evidence")] for r in recs]}}


def _poc_validate(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [f"{r['vendor']} - {r['criterion'][:40]}: record the result." for r in recs if r.get("result") == "planned"]
    probs += [f"{r['vendor']} - {r['criterion'][:40]}: where is the evidence?" for r in recs if r.get("result") in ("passed", "failed") and not str(r.get("evidence") or "").strip()]
    from .delivery import _text_problems
    return probs + _text_problems(recs, ("evidence",))


POC_EDIT = wb.Edit(columns=[wb.Column("vendor", "Vendor", readonly=True), wb.Column("criterion", "Criterion", readonly=True), wb.Column("result", "Result", "select", options=RESULTS),
                            wb.Column("evidence", "Where the evidence is"), wb.Column("when", "When")], add=False, remove=False, validate=_poc_validate, label="result")


# ------------------------------------------------------------------ Recommend

def recommend(ctx: wb.Ctx) -> dict:
    sc = _put_scores(ctx)
    pocs = ctx.records("poc")
    ran = {r["vendor"] for r in pocs}
    failed = {r["vendor"] for r in pocs if r.get("result") == "failed"}
    ranked = []
    for t in sc["vendors"]:
        why = "excluded: a mandatory requirement answered Not" if t["excluded"] else "failed the proof of concept" if t["vendor"] in failed else \
              "passed the proof of concept" if t["vendor"] in ran else "not in the proof of concept"
        ranked.append({**t, "poc": "failed" if t["vendor"] in failed else "passed" if t["vendor"] in ran else "not run", "why": why})
    pick = next((t for t in ranked if not t["excluded"] and t["poc"] == "passed"), None)
    rec = {"recommended": pick["vendor"] if pick else None, "score": pick["score"] if pick else 0, "ranked": ranked, "count": len(ranked),
           "rows": [[t["vendor"], cx.num(t["score"]), f"{t['mandatory_met']} of {t['mandatory']}", t["poc"], t["why"]] for t in ranked],
           "poc_rows": [[r["vendor"], r["criterion"], r["result"], r.get("evidence") or "-"] for r in pocs], "rfp": cx.read(ctx, "rfp") or {}}
    cx.put(ctx, "decision", rec)
    D = "record:decision"
    if pick:
        s1, f1 = cx.say("We recommend " + pick["vendor"] + ": the best weighted score among the vendors that met every mandatory requirement and passed the proof of concept, {s} of 100.",
                        s=(pick["score"], f"{D}#score"))
    else:
        s1, f1 = "No vendor met every mandatory requirement and passed the proof of concept: there is no recommendation yet.", []
    s2, f2 = cx.say("{r} requirements were scored for {v} vendors on the short list.", r=((rec["rfp"] or {}).get("requirements", 0), "record:rfp#requirements"),
                    v=((rec["rfp"] or {}).get("short_list", 0), "record:rfp#short_list"))
    blocks = [{"kind": "paragraph", "text": s1, "figures": f1}, {"kind": "paragraph", "text": s2, "figures": f2}] + nv.blocks(ctx, "In short")
    day = cx.iso_day(time.time())
    doc = {"kind": "doc", "title": f"Decision: {ctx.title}"[:70], "subtitle": f"Tool & vendor selection - {day}", "audience": "the decision makers", "date": day,
           "sections": [{"title": "Recommendation", "blocks": blocks},
                        {"title": "How the vendors compare", "blocks": [{"kind": "table", "table": cx.table(["Vendor", "Score (of 100)", "Mandatory met", "Proof of concept", "Why"], rec["rows"], f"{D}#rows",
                                                                                                         "Weighted scores from each vendor's own answers and evidence")}]},
                        {"title": "Proof of concept", "blocks": [{"kind": "table", "table": cx.table(["Vendor", "Criterion", "Result", "Evidence"], ch, f"{D}#poc_rows", "Each criterion with where its evidence is")}
                                                                 for ch in cx.chunks(rec["poc_rows"])] if rec["poc_rows"] else [{"kind": "paragraph", "text": "No proof of concept was run."}]},
                        {"title": "Every answer", "blocks": [{"kind": "table", "table": cx.table(["Vendor", "Id", "Their answer", "Status", "Points", "Evidence or reason"], ch, "record:scores#answers",
                                                                                              "The vendors' answers, and the reason wherever a person changed one")} for ch in cx.chunks((cx.read(ctx, "scores") or {}).get("answers") or [])]},
                        {"title": "Method", "blocks": [{"kind": "bullets", "bullets": ["Comply scores the full weight of a requirement, Partial and Alternative half, Not nothing; the weights add up to 100.",
                                                                                      "A mandatory requirement answered Not ends a vendor's evaluation.",
                                                                                      "The recommendation is the best score among the vendors that passed the proof of concept."]}]}]}
    slides = [{"layout": "title", "title": ctx.title[:70], "subtitle": f"Decision - {day}"},
              {"layout": "bullets", "title": "Our recommendation", "bullets": [s1, s2], "figures": f1 + f2},
              {"layout": "chart", "title": "Weighted scores", "chart": {"type": "bar", "categories": [t["vendor"] for t in ranked], "series": [{"name": "Score (of 100)", "values": [float(t["score"]) for t in ranked]}],
                                                                       "unit": "points", "source": f"{D}#ranked", "alt": "Each vendor's weighted score out of 100"}},
              {"layout": "table", "title": "How the vendors compare", "table": cx.table(["Vendor", "Score (of 100)", "Mandatory met", "Proof of concept", "Why"], rec["rows"][:14], f"{D}#rows", "Weighted scores and the proof of concept")}]
    if rec["poc_rows"]:
        slides.append({"layout": "table", "title": "Proof of concept", "table": cx.table(["Vendor", "Criterion", "Result", "Evidence"], rec["poc_rows"][:14], f"{D}#poc_rows", "Each criterion with its evidence")})
    slides.append({"layout": "closing", "title": "Thank you", "bullets": [cx.brand_line()]})
    deck = {"kind": "deck", "title": f"Decision: {ctx.title}"[:70], "subtitle": f"Tool & vendor selection - {day}", "audience": "the decision makers", "date": day, "sections": [{"title": "Decision", "slides": slides}]}
    a = cx.deliver(ctx, "decision-memo", doc, "Decision memo")
    b = cx.deliver(ctx, "decision-deck", deck, "Decision deck")
    gates = [a["gate"], b["gate"], ctx.proof("sourced", label="Every figure of the memo and the deck resolves to its record",
                                             figures=[{"label": f["text"], "value": f["value"], "source": f["source"]} for f in f1 + f2])]
    ok = a["ok"] and b["ok"] and gates[-1]["status"] in ("pass", "skip")
    ctx.put("summary", {"recommended": rec["recommended"], "score": rec["score"], "vendors": len(ranked), "when": time.time()})
    return {"summary": ((f"Recommended: {rec['recommended']} ({cx.num(rec['score'])} of 100)." if pick else "No vendor qualifies for a recommendation yet.")
                        + (" The decision memo and the deck pass every check - confirm the decision." if ok else " The memo did not pass its checks: " + "; ".join((a["problems"] + b["problems"])[:3]))),
            "ok": ok, "counts": {"vendors": len(ranked)}, "data": {"checks": gates}, "items": [f"{t['vendor']}: {cx.num(t['score'])} - {t['why']}" for t in ranked]}


def _page_cards(u: dict) -> list[dict]:
    from .. import auth, db
    rows = db.q("SELECT id, title, status FROM wb_items WHERE module = ? ORDER BY updated DESC LIMIT 30", (MODULE,))
    vis = auth.access_map(u, [r["id"] for r in rows]) if u else {}
    out = []
    for r in rows:
        if r["id"] in vis:
            s = (wb._load(r["id"]).get("data") or {}).get("summary") or {}
            out.append([r["title"], wb.STATUS_LABEL.get(r["status"], r["status"]), s.get("recommended") or "-", cx.num(s["score"]) if s.get("score") else "-", f"#/m/{MODULE}/i/{r['id']}"])
    return [{"title": "Selections", "columns": ["Selection", "Status", "Recommended", "Score", "Open"], "rows": out, "empty": "No selection yet."}]


GUIDE = """# Tool & vendor selection - the work item

This folder is one selection of Relay's Tool & vendor selection module.

- `data/`: the requirement documents and sheets, and the response workbooks the vendors sent back (`rfp-<vendor>.xlsx`).
- `requirements.yaml`: what you write when asked to read the requirements - each with the file and page it came
  from, no weights (a person sets them).
- `sources/rfp.json`, `scores.json`, `decision.json`: the RFP that was issued, the weighted scores, the decision.
- `narrative.yaml`: what you write when asked - a few paragraphs, every number declared with its `record:` source.

Never invent a requirement, a vendor's answer or a score."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, cards=_page_cards,
    lineage="none: a selection reads documents and vendors' answers; it writes nothing to a live system",
    platforms={"documents": DOCS},
    schemas={"requirement": REQ_EDIT.columns, "candidate": LONG_EDIT.columns, "answer": SCORE_EDIT.columns, "result": POC_EDIT.columns},
    work={"engage": wb.Work(
        title="Choose a tool or vendor: requirements, a long and short list, an RFP issued, weighted scores with evidence, a proof of concept, the decision",
        needs_source=False, journey=["Requirements", "Long list", "Issue", "Score", "PoC", "Recommend"],
        steps={
            "Requirements": wb.Step(kind="deterministic", run=requirements, agent="Requirements reader", edit=REQ_EDIT, confirm="the requirements, their weights and what is mandatory",
                                    actions={"read": wb.Action(label="Ask Relay to read the requirements", kind="agent", prompt=_read_prompt, check=_read_check, after=_read_after,
                                                               agent="Requirements reader", help="The agent reads the Word, PDF or text documents and lists each requirement with its file and page; you set the weights.")},
                                    text="Read from your requirements sheet (rules first) or from your documents by the agent, each with where it came from; you set the weights, which add up to 100"),
            "Long list": wb.Step(kind="deterministic", run=long_list, agent="Market reader", edit=LONG_EDIT, confirm="who is on the long list and why, and the short list the RFP goes to",
                                 text="The candidates Relay's catalogue lists for this kind of tool, and any you add with the reason; you pick the short list"),
            "Issue": wb.Step(kind="deterministic", run=issue, view="gates", agent="RFP writer", confirm="the RFP pack and who receives it - you send it, Relay sends nothing",
                             confirm_if=lambda ctx, out: out["ok"], text="The RFP document through the docs engine and a response workbook for each vendor on the short list"),
            "Score": wb.Step(kind="platform", run=score, agent="Evaluator", edit=SCORE_EDIT, confirm="the weighted scores, each with the vendor's own answer and evidence",
                             actions={"responses": wb.Action(label="Read the responses", kind="platform", run=score, agent="Evaluator",
                                                             help="Read the vendors' completed workbooks you uploaded (Files > Upload on this item).")},
                             text="The vendors' workbooks read and scored: each answer × its weight, a mandatory Not excludes; you may change a status, with the reason"),
            "PoC": wb.Step(kind="deterministic", run=poc, agent="Evaluator", edit=POC_EDIT, confirm="the proof-of-concept results with where their evidence is",
                           text="The leading vendors tried on the mandatory requirements; you record each result and its evidence"),
            "Recommend": wb.Step(kind="deterministic", run=recommend, view="gates", agent="Decision writer", back_to="poc", confirm="the recommendation, before the decision is taken",
                                 confirm_if=lambda ctx, out: out["ok"],
                                 actions={"wording": nv.action(("decision", "scores", "rfp"), "Explain the recommendation for the decision makers: how the vendors compare, the proof of concept, the reasons.",
                                                               agent="Decision writer", rebuild=lambda ctx: recommend(ctx))},
                                 text="The best weighted score among the vendors that met every mandatory requirement and passed the proof of concept, with the decision memo and deck through the docs engine")},
        fields=[wb.Field("category", "What kind of tool", "select", options=_categories, required=True, help="Its platforms in Relay's catalogue start the long list."),
                wb.Field("due", "Responses due (YYYY-MM-DD)", "text", required=True),
                wb.Field("poc_count", "Vendors in the proof of concept", "number", default=2),
                wb.Field("template", "Template", "select", options=cx.template_options, default="relay")])}))
