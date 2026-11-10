"""BRD & requirements (registry id `brd`) — workshop notes, call recordings, e-mails and whiteboards in; a BRD in the
tenant's template, user stories with acceptance criteria, a sign-off by each business owner, a backlog pushed to Jira or
Azure Boards after its own approval, and every requirement traced from its source to the build, the tests and the
sign-off.

Develop  Gather → Draft → Review → Approve → Backlog → Trace. Gather reads every upload into passages with ids (Word,
         PDF, slides, sheets, e-mail, call transcripts, page exports; recordings and whiteboard photos are looked at by
         the agent); Draft is the agent's: brd.yaml with scope, stakeholders, current and future process, requirements,
         rules, data, risks and open questions — each citing the passage it rests on, word for word, checked strictly
         (an unknown passage, a quote that is not in it or a figure no cited passage holds is refused); the BRD is built
         in the tenant's Word template by the P11 docs engine. Review records the business owners' comments and the
         answers to the open questions (listed, never guessed). Approve builds the version for approval and asks each
         business owner to sign it (a checkpoint each), then the named approver. Backlog turns the approved requirements
         into user stories with Given / When / Then acceptance criteria. Trace asks for the write to Jira or Azure
         Boards (its own approval), reads the keys back and shows the traceability matrix.
Change   Request → Diagnose → Fix → Prove → Approve → Learn: an approved BRD changed with review — what the change
         touches (requirements, stories, keys, tests), the agent's drafted change (sourced), proof, release, a new version
         and the tracker updated after its approval.
Migrate  Collect → Read → Standardise → Gaps → Approve → Backlog → Trace: old specs (Word, PDF, Confluence or SharePoint
         exports) read and mapped to the BRD template by the agent; duplicates and contradictions listed with where they
         came from; gaps against how the system really behaves (the knowledge map); owners approve the standard version.
Approved BRDs are kept in `brd_documents` / `brd_versions` (every version); Test plans & UAT reads them.
"""
from __future__ import annotations

import json
import re
import secrets as _secrets
import time

from .. import auth, connectors, db
from .. import workbench as wb
from . import _w4, brd_trackers as trk

MODULE = "brd"
SYSTEM = "Relay BRD"
TYPES = (("functional", "Functional"), ("non-functional", "Non-functional"), ("rule", "Business rule"), ("data", "Data"), ("report", "Report"))
PRIORITIES = (("must", "Must"), ("should", "Should"), ("could", "Could"), ("wont", "Won't (this time)"))
STORY_TYPES = {"functional", "report", "data", "rule"}
UPLOADS = (".docx", ".pdf", ".pptx", ".txt", ".md", ".eml", ".vtt", ".srt", ".html", ".htm", ".xlsx", ".csv", ".mp3", ".wav", ".m4a", ".mp4", ".webm", ".mov",
           ".png", ".jpg", ".jpeg", ".webp")

db.register_schema("""
CREATE TABLE IF NOT EXISTS brd_documents (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, item TEXT, version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'approved', requirements TEXT NOT NULL DEFAULT '[]',
  stories TEXT NOT NULL DEFAULT '[]', owner_id TEXT, approved_by TEXT, approved REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS brd_versions (
  doc_id TEXT NOT NULL, version INTEGER NOT NULL, item TEXT, status TEXT NOT NULL, requirements TEXT NOT NULL, file TEXT, signed TEXT NOT NULL DEFAULT '[]',
  by_id TEXT, created REAL NOT NULL, note TEXT, PRIMARY KEY (doc_id, version));
""")

FILES = wb.FilesPlatform()
FILES.label = "Workshop notes, recordings, e-mails and whiteboards"
FILES.uploads = UPLOADS
FILES.reads = ("the files you upload — Word, PDF, slides, sheets, e-mails (.eml), call transcripts (.vtt / .srt), Confluence or SharePoint page exports; "
               "recordings and whiteboard photos are looked at by the agent — a copy in this work item's folder")
FILES.simulator = "synthetic fixtures in tests/mocklab/fixtures/brd/ (notes, transcript, e-mail, whiteboard, recording, old specs)"


class TrackerPlatform(wb.Platform):
    id = "tracker"
    label = "Azure Boards (where the backlog goes) — or Jira through a Service desk source"
    kinds = trk.TRACKERS
    simulator = "tests/mocklab/sims/process.py: azure-boards (Azure DevOps REST 7.1); Jira: jira-software (Jira Cloud REST v3) behind a Service desk source"
    reads = "the project and its work item types; Jira through the Service desk's source. Stories are written only after you approve each write"


TRACKER = TrackerPlatform()
DESK_PRIORITY = {"must": "P2", "should": "P3", "could": "P4", "wont": "P4"}


def _target(ctx: wb.Ctx) -> dict:
    """Where the backlog goes: a Service desk source for Jira (field `jira`), else an Azure Boards connection, else CSV."""
    sid = ctx.scope.get("jira") or ""
    if sid:
        row = db.one("SELECT * FROM itsm_sources WHERE id = ?", (sid,)) if "itsm_sources" in db.tables() else None
        s = next((x for x in _w4.desk_sources() if x["id"] == sid), None)
        o = _w4.j((row or {}).get("options"), {})
        project = o.get("project") or (_w4.j((row or {}).get("projects"), []) or [""])[0]
        return {"kind": "jira", "id": sid, "name": (row or {}).get("name") or "the Service desk source", "system": f"Jira {project}".strip(), "gone": s is None}
    c = _w4.tracker_connection(ctx, trk.TRACKERS)
    if c:
        return {"kind": "boards", "id": c["id"], "name": c["name"], "conn": c, "system": f"Azure Boards {c['config'].get('project') or ''}".strip()}
    return {"kind": "csv", "name": "CSV files to import", "system": "Relay backlog"}

STOP = set("a an the and or of to in on for with by is are be shall must should will can may it this that as at from each every all any we our they their "
           "has have when then given which who what into than more less within over under per".split())
NEG = re.compile(r"\b(not|never|no|without|cannot|can't|won't|mustn't)\b")


# ------------------------------------------------------------------ the approved BRDs (versions kept)

def document(did: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM brd_documents WHERE id = ?", (did,))
    if not r:
        return None
    if u is not None and r.get("item") and not auth.can_project(u, "view", db.project(r["item"])):
        return None
    return {**r, "requirements": _w4.j(r["requirements"], []), "stories": _w4.j(r["stories"], [])}


def documents(u: dict) -> list[dict]:
    rows = [{**r, "requirements": _w4.j(r["requirements"], []), "stories": _w4.j(r["stories"], [])} for r in db.q("SELECT * FROM brd_documents ORDER BY updated DESC")]
    return _w4.visible_items(u, rows)


def document_options(u: dict) -> list[tuple[str, str]]:
    return [(d["id"], f"{d['title']} · version {d['version']} · {len(d['requirements'])} requirements") for d in documents(u)]


def publish(ctx: wb.Ctx, reqs: list[dict], stories: list[dict], did: str | None, signed: list[dict], file: str, note: str = "") -> dict:
    now = time.time()
    who = ctx.who or ctx.owner
    if did and db.one("SELECT 1 FROM brd_documents WHERE id = ?", (did,)):
        v = db.one("SELECT version FROM brd_documents WHERE id = ?", (did,))["version"] + 1
        db.run("UPDATE brd_documents SET version = ?, requirements = ?, stories = ?, approved_by = ?, approved = ?, updated = ?, status = 'approved' WHERE id = ?",
               (v, json.dumps(reqs), json.dumps(stories), who, now, now, did))
    else:
        did, v = "brd-" + _secrets.token_hex(4), 1
        db.run("INSERT INTO brd_documents (id, title, item, version, status, requirements, stories, owner_id, approved_by, approved, created, updated) VALUES (?, ?, ?, 1, 'approved', ?, ?, ?, ?, ?, ?, ?)",
               (did, ctx.title[:160], ctx.id, json.dumps(reqs), json.dumps(stories), ctx.owner, who, now, now, now))
    db.run("INSERT OR REPLACE INTO brd_versions (doc_id, version, item, status, requirements, file, signed, by_id, created, note) VALUES (?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?)",
           (did, v, ctx.id, json.dumps(reqs), file, json.dumps(signed), who, now, note[:500] or None))
    db.audit("brd.publish", did, {"version": v, "requirements": len(reqs), "item": ctx.id}, who)
    return document(did)


def set_stories(did: str, stories: list[dict]) -> None:
    db.run("UPDATE brd_documents SET stories = ?, updated = ? WHERE id = ?", (json.dumps(stories), time.time(), did))


# ------------------------------------------------------------------ brd.yaml: the agent's draft, checked strictly

def _list(v) -> list:
    return v if isinstance(v, list) else [] if v is None else [v]


def _given(lines: list[str]) -> list[str]:
    return [f"“{l[:60]}” is not Given / When / Then" for l in lines if not (re.search(r"\bgiven\b", l, re.I) and re.search(r"\bwhen\b", l, re.I) and re.search(r"\bthen\b", l, re.I))]


def check_brd(y: dict, segs: dict) -> list[str]:
    out = []
    if not str(y.get("title") or "").strip():
        out.append("title is missing")
    if not str(y.get("scope") or "").strip():
        out.append("scope is missing (one paragraph, from the sources)")
    reqs = _list(y.get("requirements"))
    if not reqs:
        out.append("requirements is empty")
    seen = set()
    for i, r in enumerate(reqs, 1):
        if not isinstance(r, dict):
            out.append(f"requirement {i} must be a mapping")
            continue
        rid = str(r.get("id") or "")
        where = rid or f"requirement {i}"
        if not re.fullmatch(r"BR-\d{3}", rid):
            out.append(f"{where}: the id must look like BR-001")
        elif rid in seen:
            out.append(f"{where}: the id is used twice")
        seen.add(rid)
        if not str(r.get("statement") or "").strip():
            out.append(f"{where}: the statement is empty")
        if r.get("type") not in dict(TYPES):
            out.append(f"{where}: type must be one of {', '.join(dict(TYPES))}")
        if r.get("priority") not in dict(PRIORITIES):
            out.append(f"{where}: priority must be one of {', '.join(dict(PRIORITIES))}")
        out += _w4.check_sources(where, _w4.parse_refs(r.get("sources")), segs, statement=f"{r.get('statement') or ''} {' '.join(map(str, _list(r.get('acceptance'))))}")
        acc = [str(a) for a in _list(r.get("acceptance")) if str(a).strip()]
        if r.get("type") in STORY_TYPES:
            if not acc:
                out.append(f"{where}: give at least one acceptance criterion (Given … when … then …)")
            out += [f"{where}: {p}" for p in _given(acc)]
            st = r.get("story") if isinstance(r.get("story"), dict) else {}
            if not all(str(st.get(k) or "").strip() for k in ("as_a", "i_want", "so_that")):
                out.append(f"{where}: story needs as_a, i_want and so_that")
    for key, label in (("stakeholders", "stakeholder"), ("rules", "rule"), ("risks", "risk"), ("current_process", "current step"), ("future_process", "future step")):
        for i, x in enumerate(_list(y.get(key)), 1):
            if isinstance(x, dict):
                out += _w4.check_sources(f"{label} {i}", _w4.parse_refs(x.get("sources")), segs, need_quote=False)
    for i, q in enumerate(_list(y.get("open_questions")), 1):
        if not isinstance(q, dict) or not str(q.get("question") or "").strip().endswith("?"):
            out.append(f"open question {i}: write it as a question (ending with ?) — what the sources do not settle")
        elif q.get("sources"):
            out += _w4.check_sources(f"open question {i}", _w4.parse_refs(q.get("sources")), segs, need_quote=False)
    return out


def _req_record(r: dict, segs: dict, origin: str = "agent") -> dict:
    refs = _w4.parse_refs(r.get("sources"))
    st = r.get("story") if isinstance(r.get("story"), dict) else {}
    return {"id": r["id"], "req": r["id"], "keep": True, "title": str(r.get("title") or "")[:200], "statement": str(r.get("statement") or ""), "type": r.get("type"),
            "priority": r.get("priority"), "owner": str(r.get("owner") or ""), "source": ", ".join(x["ref"] for x in refs), "sources": refs,
            "where": _w4.where_text(refs, segs), "acceptance": "\n".join(str(a) for a in _list(r.get("acceptance"))),
            "as_a": str(st.get("as_a") or ""), "i_want": str(st.get("i_want") or ""), "so_that": str(st.get("so_that") or ""), "origin": origin}


def _reqs_table(recs: list[dict]) -> dict:
    return {"columns": ["Keep", "Requirement", "Statement", "Type", "Priority", "From"],
            "rows": [["yes" if r.get("keep", True) else "no", f"{r['req']}: {r.get('title') or ''}", r.get("statement"), dict(TYPES).get(r.get("type"), r.get("type")),
                      dict(PRIORITIES).get(r.get("priority"), r.get("priority")), r.get("where") or r.get("source")] for r in recs]}


def _validate_reqs(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    """Rules first: a requirement keeps a source (a passage id, or 'stated by <name>' for what a person adds), its
    figures are in what it cites, and its acceptance criteria are Given / When / Then."""
    segs = _w4.segments(ctx)
    used = {r.get("req") for r in recs if r.get("req")}
    n = max([int(x[3:]) for x in used if re.fullmatch(r"BR-\d{3}", str(x or ""))] + [0])
    out = []
    for r in recs:
        if not r.get("req") or not re.fullmatch(r"BR-\d{3}", str(r["req"])) or (r.get("origin") == "person" and sum(1 for x in recs if x.get("req") == r["req"]) > 1):
            n += 1
            r["req"] = f"BR-{n:03d}"
        if not r.get("keep", True):
            continue
        where = r["req"]
        if not str(r.get("statement") or "").strip():
            out.append(f"{where}: the statement is empty")
        if r.get("type") not in dict(TYPES):
            out.append(f"{where}: pick a type")
        if r.get("priority") not in dict(PRIORITIES):
            out.append(f"{where}: pick a priority")
        who = _w4.person_source(r.get("source"))
        if who:
            r["sources"], r["where"] = [], f"stated by {who}"
        else:
            refs = _w4.parse_refs(r.get("source"))
            have = {x["ref"]: x for x in r.get("sources") or []}
            refs = [have.get(x["ref"], x) for x in refs]
            out += _w4.check_sources(where, refs, segs, need_quote=False, statement=f"{r.get('statement') or ''} {r.get('acceptance') or ''}")
            r["sources"], r["where"] = refs, _w4.where_text(refs, segs)
        acc = [a for a in str(r.get("acceptance") or "").splitlines() if a.strip()]
        if r.get("type") in STORY_TYPES:
            if not acc:
                out.append(f"{where}: give at least one acceptance criterion (Given … when … then …), one per line")
            out += [f"{where}: {p}" for p in _given(acc)]
    return out


REQ_COLUMNS = [wb.Column("keep", "Keep", "bool"), wb.Column("req", "Id", readonly=True), wb.Column("title", "Title"), wb.Column("statement", "Requirement", "longtext"),
               wb.Column("type", "Type", "select", options=TYPES), wb.Column("priority", "Priority", "select", options=PRIORITIES),
               wb.Column("source", "Source", help="the passage ids it rests on (from the evidence, e.g. workshop-notes.docx#p4), comma-separated — or “stated by <your name>”"),
               wb.Column("acceptance", "Acceptance criteria", "longtext", help="one per line: Given … when … then …")]
REQ_EDIT = wb.Edit(columns=REQ_COLUMNS, validate=_validate_reqs, label="requirement")


# ------------------------------------------------------------------ the BRD document (P11 docs engine, the tenant's template)

def _brd_doc(ctx: wb.Ctx, name: str, version: int, status: str, reqs: list[dict], y: dict, decisions: list[dict] | None = None, signed: list[dict] | None = None) -> dict:
    segs = _w4.segments(ctx)

    def src(x):
        return _w4.where_text(_w4.parse_refs(x.get("sources")), segs) if isinstance(x, dict) else ""
    rec = {"scope": str(y.get("scope") or ""), "requirements": reqs, "stakeholders": _list(y.get("stakeholders")), "rules": _list(y.get("rules")), "risks": _list(y.get("risks")),
           "open_questions": _list(y.get("open_questions")), "decisions": decisions or [], "signed": signed or []}
    rec["scope"] = rec["scope"] or "The scope is set out by the requirements below."
    secs = [{"title": "Scope", "blocks": [_w4.para(rec["scope"], f"record:{name}#scope")]},
            {"title": "Stakeholders", "blocks": [_w4.table(["Who", "Role", "Interest", "From"], [[s.get("name"), s.get("role"), s.get("interest"), src(s)] for s in rec["stakeholders"] if isinstance(s, dict)],
                                                           f"record:{name}#stakeholders", "Stakeholders and what they need")]},
            {"title": "Current and future process", "blocks": [
                _w4.table(["Today", "From"], [[x.get("step") if isinstance(x, dict) else x, src(x)] for x in _list(y.get("current_process"))], f"record:{name}#scope", "How the work is done today"),
                _w4.table(["In future", "From"], [[x.get("step") if isinstance(x, dict) else x, src(x)] for x in _list(y.get("future_process"))], f"record:{name}#scope", "How it will be done")]},
            {"title": "Requirements", "blocks": [_w4.table(["Id", "Requirement", "Type", "Priority", "From"], [[r["req"], r["statement"], dict(TYPES).get(r.get("type"), r.get("type")),
                                                                                                                dict(PRIORITIES).get(r.get("priority"), r.get("priority")), r.get("where") or ""] for r in reqs],
                                                           f"record:{name}#requirements", "Every requirement with the passage it comes from")]},
            {"title": "Acceptance criteria", "blocks": [_w4.table(["Id", "Criterion"], [[r["req"], a] for r in reqs for a in str(r.get("acceptance") or "").splitlines() if a.strip()],
                                                                  f"record:{name}#requirements", "Given / When / Then, per requirement")]},
            {"title": "Business rules, data and risks", "blocks": [
                _w4.table(["Rule", "From"], [[x.get("text"), src(x)] for x in rec["rules"] if isinstance(x, dict)], f"record:{name}#rules", "Business rules"),
                _w4.table(["Risk", "Mitigation", "From"], [[x.get("risk"), x.get("mitigation"), src(x)] for x in rec["risks"] if isinstance(x, dict)], f"record:{name}#risks", "Risks")]},
            {"title": "Open questions and decisions", "blocks": [
                _w4.table(["Question", "Why it is open"], [[q.get("question"), q.get("why")] for q in rec["open_questions"] if isinstance(q, dict) and not any(d["q"] == q.get("id") for d in rec["decisions"])],
                          f"record:{name}#open_questions", "Listed, not guessed"),
                _w4.table(["Question", "Answer", "Answered by"], [[d["question"], d["answer"], d["by"]] for d in rec["decisions"]], f"record:{name}#decisions", "Answered in review")]},
            {"title": "Sign-off", "blocks": [_w4.table(["Business owner", "Decision", "When"], [[s["person"], s["decision"], s["when"]] for s in rec["signed"]] or [["—", status, ""]],
                                                       f"record:{name}#signed", "Approval with names and dates")]}]
    return _w4.build_doc(ctx, name, f"Business requirements: {ctx.title}", f"Version {version} · {status}", secs, {name: rec}, label=f"BRD version {version} ({status})",
                         audience="the business owners and the delivery team")


# ------------------------------------------------------------------ Develop

def d_gather(ctx: wb.Ctx) -> dict:
    read = _w4.read_uploads(ctx, UPLOADS)
    if not read["files"]:
        raise wb.StepFailed("Upload what the requirements come from: workshop notes, call transcripts or recordings, e-mails, whiteboard photos (Word, PDF, .eml, .vtt, images).")
    texts = sum(f["passages"] for f in read["files"])
    if not texts:
        raise wb.StepFailed("None of the uploads has text Relay can cite (a recording needs its transcript next to it, .vtt or .srt).")
    rows = _w4.files_table(read)
    tracker = []
    for c in ctx.connections():
        try:
            t = connectors.sdk.get(c["kind"]).test(c)
            tracker.append(f"{c['name']}: {t.get('sees')}")
        except (connectors.ConnectorError, connectors.sdk.ScopeError) as e:
            tracker.append(f"{c['name']}: could not be read — {e}")
    tg = _target(ctx)
    if tg["kind"] == "jira":
        try:
            from .. import itsm
            t = itsm.adapter_for(itsm._src(tg["id"])).test()
            tracker.append(f"{tg['name']} (Service desk): {tg['system']} as {t.get('account')}" + ("" if not tg["gone"] else " — it may not raise tickets yet (Service desk › Sources › May do)"))
        except Exception as e:  # noqa: BLE001 - shown, not fatal: the backlog can still be exported
            tracker.append(f"{tg['name']}: could not be read — {str(e)[:160]}")
    ctx.put("tracker_seen", tracker)
    return {"summary": f"{len(read['files'])} file(s) read into {texts} passage(s) Relay can cite" + (f"; {', '.join(tracker)}" if tracker else "; no tracker connected — the backlog will be exported as CSV") + ".",
            "counts": {"files": len(read["files"]), "passages": texts, "media": sum(1 for f in read["files"] if f["passages"] == 0)}, "data": rows,
            "items": [f"{f['name']}: {f['kind']}, {f['what']}" for f in read["files"][:8]]}


DRAFT = """Read WORK.md, then sources/segments.json: every passage of the uploads with its id (file#where) — workshop
notes, e-mails, call transcripts, page exports. Look at the images and recordings in data/ yourself (`genbi read
data/<file>` gives a video's key frames; Read an image to see a whiteboard).

FILE brd.yaml — the business requirements document, in this shape:

title: <what the work is>
scope: <one paragraph: what is in and out, from the sources>
stakeholders:   [{name, role, interest, sources: [{ref: <passage id>, quote: <its words>}]}]
current_process: [{step, sources}]
future_process:  [{step, sources}]
requirements:
  - id: BR-001
    title: <short>
    statement: <one sentence a business owner can sign>
    type: functional | non-functional | rule | data | report
    priority: must | should | could | wont
    owner: <role, from the sources>
    sources: [{ref: workshop-notes.docx#p4, quote: "the exact words it rests on"}]
    acceptance: ["Given …, when …, then …"]          # functional, rule, data and report requirements
    story: {as_a: <role>, i_want: <capability>, so_that: <benefit>}
rules: [{id: RULE-01, text, sources}]
risks: [{risk, mitigation, sources}]
open_questions: [{id: Q-01, question: <ends with ?>, why: <what the sources leave open>}]

Every requirement cites at least one passage id from sources/segments.json with the words it rests on, copied word
for word. A figure (an amount, a number of days, a percentage) must be in a passage it cites. Where the sources do not
settle something, write an open question — never guess. British English."""


def _draft_prompt(ctx: wb.Ctx) -> str:
    return DRAFT


def _draft_check(ctx: wb.Ctx) -> list[str]:
    y, probs = _w4.load_yaml(ctx.dir / "brd.yaml")
    return probs if probs else check_brd(y, _w4.segments(ctx))


def _draft_after(ctx: wb.Ctx, res: dict) -> dict:
    y, _ = _w4.load_yaml(ctx.dir / "brd.yaml")
    segs = _w4.segments(ctx)
    recs = [_req_record(r, segs) for r in _list(y.get("requirements")) if isinstance(r, dict)]
    have = {r["req"]: r for r in ctx.records(ctx.step_id) if r.get("origin") == "person"}
    recs += [r for k, r in have.items() if k not in {x["req"] for x in recs}]
    ctx.put("brd", y)
    ctx.put("version", 1)
    info = _brd_doc(ctx, "brd-v1", 1, "draft", recs, y)
    probs = _w4.doc_problems(info)
    ctx.evidence("The agent's draft (brd.yaml)", {"brd": y, "summary": res.get("text") or ""}, kind="agent", ok=True)
    qs = _list(y.get("open_questions"))
    media = sum(1 for r in recs if r["sources"] and all((segs.get(x["ref"]) or {}).get("kind") == "media" for x in r["sources"]))
    return {"summary": f"{len(recs)} requirement(s) drafted from {len({x['ref'].split('#')[0] for r in recs for x in r['sources']})} source file(s), each citing its passage; "
            f"{len(qs)} open question(s) listed, not guessed" + (f"; {media} rest on a recording alone — check them against it" if media else "")
            + (f". The document check found {len(probs)} problem(s): {probs[0]}" if probs else ". The BRD is in your template (Word and an HTML preview).") + " Correct the rows, then confirm.",
            "counts": {"requirements": len(recs), "open questions": len(qs), "must": sum(1 for r in recs if r["priority"] == "must")},
            "records": recs, "data": _reqs_table(recs), "items": [f"{r['req']}: {r['statement'][:140]}" for r in recs[:6]]}


def d_review(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    y = ctx.get("brd") or {}
    reqs = [r for r in ctx.records("draft") if r.get("keep", True)]
    recs = []
    for r in reqs:
        rec = {"id": r["req"], "kind": "requirement", "ref": r["req"], "text": r["statement"], "decision": "keep", "comment": ""}
        recs.append({**rec, **{k: have[rec["id"]][k] for k in ("text", "decision", "comment") if rec["id"] in have}})
    for q in _list(y.get("open_questions")):
        if isinstance(q, dict):
            rec = {"id": str(q.get("id") or f"Q-{len(recs)}"), "kind": "open question", "ref": str(q.get("id") or ""), "text": q.get("question"), "decision": "still open", "comment": ""}
            recs.append({**rec, **{k: have[rec["id"]][k] for k in ("decision", "comment") if rec["id"] in have}})
    nq = sum(1 for r in recs if r["kind"] == "open question")
    return {"summary": f"{len(reqs)} requirement(s) for the business owners to comment on in place, {nq} open question(s) to answer — what nobody can answer yet stays open, never guessed.",
            "records": recs, "counts": {"requirements": len(reqs), "open questions": nq},
            "data": {"columns": ["Kind", "Ref", "Text", "Decision", "Comment or answer"], "rows": [[r["kind"], r["ref"], r["text"], r["decision"], r["comment"]] for r in recs]}}


def _validate_review(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for r in recs:
        if r.get("kind") == "open question":
            if r.get("decision") not in ("answered", "still open"):
                out.append(f"{r['ref']}: an open question is answered or still open")
            elif r["decision"] == "answered" and not str(r.get("comment") or "").strip():
                out.append(f"{r['ref']}: write the answer (and who gave it) in the comment")
        else:
            if r.get("decision") not in ("keep", "drop"):
                out.append(f"{r['ref']}: a requirement is kept or dropped")
            elif r["decision"] == "drop" and not str(r.get("comment") or "").strip():
                out.append(f"{r['ref']}: say why it is dropped")
            if not str(r.get("text") or "").strip():
                out.append(f"{r['ref']}: the requirement text is empty")
    return out


REVIEW_EDIT = wb.Edit(columns=[wb.Column("kind", "Kind", readonly=True), wb.Column("ref", "Ref", readonly=True), wb.Column("text", "Requirement or question", "longtext"),
                               wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("drop", "Drop"), ("answered", "Answered"), ("still open", "Still open"))),
                               wb.Column("comment", "Comment or answer", "longtext", help="the business owner's comment, or the answer and who gave it")],
                      add=False, remove=False, validate=_validate_review, label="comment")


def _final_reqs(ctx: wb.Ctx) -> tuple[list[dict], list[dict]]:
    review = {r["ref"]: r for r in ctx.records("review")}
    base = ctx.records("draft") or ctx.records("read")
    reqs = []
    for r in base:
        if not r.get("keep", True):
            continue
        rv = review.get(r["req"])
        if rv and rv.get("decision") == "drop":
            continue
        if ctx.records("standardise"):
            if any(x.get("decision") == "keep A" and x.get("b") == r["req"] or x.get("decision") == "keep B" and x.get("a") == r["req"] or x.get("decision") == "merge" and x.get("b") == r["req"] for x in ctx.records("standardise")):
                continue
        reqs.append({**r, "statement": (rv or {}).get("text") or r["statement"], "review": (rv or {}).get("comment") or ""})
    n = max([int(r["req"][3:]) for r in reqs if re.fullmatch(r"BR-\d{3}", str(r.get("req") or ""))] + [0])
    for g in ctx.records("gaps"):
        if g.get("decision") == "add as requirement" and isinstance(g.get("requirement"), dict):
            n += 1
            reqs.append({**g["requirement"], "req": f"BR-{n:03d}", "review": g.get("note") or ""})
    who = _w4.user_name(ctx.who or ctx.owner)
    decisions = [{"q": r["ref"], "question": r["text"], "answer": r["comment"], "by": f"recorded by {who}"} for r in review.values() if r.get("kind") == "open question" and r.get("decision") == "answered"]
    return reqs, decisions


def d_approve(ctx: wb.Ctx) -> dict:
    reqs, decisions = _final_reqs(ctx)
    if not reqs:
        raise wb.StepFailed("No requirement is left to approve.")
    v = int(ctx.get("version") or 1) + 1
    round_ = f"v{v}"
    ctx.put("version", v)
    ctx.put("round", round_)
    ctx.put("final", reqs)
    ctx.put("decisions", decisions)
    owners, probs = _w4.people(ctx.scope.get("owners") or "")
    if probs:
        raise wb.StepFailed("; ".join(probs) + " — correct the business owners (one e-mail or name per line).")
    info = _brd_doc(ctx, f"brd-v{v}", v, "for approval", reqs, ctx.get("brd") or {}, decisions)
    _w4.ask_signoff(ctx, owners, round_=round_, what=f"BRD version {v} for approval: {len(reqs)} requirement(s). Open the work item to read it (Word and an HTML preview).",
                    items=[f"{r['req']}: {r['statement'][:160]}" for r in reqs[:10]], role="business owner")
    out = _approve_view(ctx)
    probs = _w4.doc_problems(info)
    if probs:
        out["summary"] += f" The document check found {len(probs)} problem(s): {probs[0]}"
    return out


def _approve_view(ctx: wb.Ctx) -> dict:
    round_ = ctx.get("round") or "v2"
    recs = _w4.signoff_records(ctx.id, "approve", round_)
    if not recs:
        recs = [{"id": "approver", "person": _w4.user_name(ctx.st.get("approver") or ctx.owner), "role": "named approver", "decision": "signs alone (no business owners named)", "when": "", "comment": ""}]
    done = sum(1 for r in recs if r["decision"] == "signed off")
    waiting = [r["person"] for r in recs if r["decision"] == "waiting"]
    return {"summary": f"Version {str(round_)[1:]} for approval: {done} of {len(recs)} business owner(s) signed off" + (f"; waiting for {', '.join(waiting)}" if waiting else "")
            + ". The named approver confirms once everyone has signed.", "records": recs, "counts": {"owners": len(recs), "signed": done},
            "data": {"columns": ["Business owner", "Role", "Decision", "When", "Comment"], "rows": [[r["person"], r["role"], r["decision"], r["when"], r["comment"]] for r in recs]}}


def _validate_signed(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    return _w4.signoff_problems(ctx.id, "approve", ctx.get("round") or "v2")


SIGN_EDIT = wb.Edit(columns=[wb.Column("person", "Business owner", readonly=True), wb.Column("role", "Role", readonly=True), wb.Column("decision", "Decision", readonly=True),
                             wb.Column("when", "When", readonly=True), wb.Column("comment", "Comment", readonly=True)], add=False, remove=False, validate=_validate_signed, label="sign-off")
_w4.REFRESH["brd.approve"] = _approve_view


def _story_of(r: dict, n: int) -> dict:
    who = r.get("as_a") or "user"
    want = r.get("i_want") or (r.get("title") or r["statement"])[:1].lower() + (r.get("title") or r["statement"])[1:]
    summ = f"As {'an' if who[:1].lower() in 'aeio' else 'a'} {who}, I want {want}, so that {r.get('so_that') or 'the requirement is met'}"
    return {"id": f"US-{n:03d}", "story": f"US-{n:03d}", "req": r["req"], "include": True, "summary": summ[:255], "acceptance": r.get("acceptance") or "", "priority": r.get("priority") or "should"}


def d_backlog(ctx: wb.Ctx) -> dict:
    reqs = ctx.get("final") or []
    signed = _w4.signoff_records(ctx.id, "approve", ctx.get("round") or "v2")
    if not ctx.get("doc"):                              # the approval is recorded once: a new version of the approved BRD
        info = _brd_doc(ctx, f"brd-v{ctx.get('version')}-approved", ctx.get("version"), "approved", reqs, ctx.get("brd") or {}, ctx.get("decisions") or [], signed)
        doc = publish(ctx, reqs, [], ctx.scope.get("brd") or None, signed, f"brd-v{ctx.get('version')}-approved.docx", note=f"approved in {ctx.id}")
        ctx.put("doc", doc["id"])
        ctx.put("doc_version", doc["version"])
        _w4.doc_problems(info)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    stories = []
    for r in reqs:
        if r.get("type") not in STORY_TYPES:
            continue
        s = _story_of(r, len(stories) + 1)
        stories.append({**s, **{k: have[s["id"]][k] for k in ("include", "summary", "acceptance", "priority") if s["id"] in have}})
    tg = _target(ctx)
    where = {"jira": f"{tg['system']} through {tg['name']} (one approval per story)", "boards": f"{tg['name']} (Azure Boards)"}.get(tg["kind"], "CSV files to import (no tracker connected)")
    return {"summary": f"BRD version {ctx.get('doc_version')} is approved and kept. {len(stories)} user stor{'y' if len(stories) == 1 else 'ies'} from it, each with its acceptance criteria — "
            f"they go to {where} once you confirm and approve the write.", "records": stories, "counts": {"stories": len(stories), "requirements": len(reqs)},
            "data": {"columns": ["Story", "Requirement", "Summary", "Priority", "Acceptance criteria"], "rows": [[s["story"], s["req"], s["summary"], s["priority"], s["acceptance"]] for s in stories]},
            "items": [f"{s['story']} ({s['req']}): {s['summary'][:120]}" for s in stories[:6]]}


def _validate_stories(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    reqs = {r["req"] for r in ctx.get("final") or []}
    out = []
    for s in recs:
        if not s.get("include"):
            continue
        if not re.match(r"^\s*As an? .+,? I want .+", str(s.get("summary") or ""), re.I):
            out.append(f"{s.get('story')}: write it as “As a …, I want …, so that …”")
        acc = [a for a in str(s.get("acceptance") or "").splitlines() if a.strip()]
        if not acc:
            out.append(f"{s.get('story')}: give at least one acceptance criterion")
        out += [f"{s.get('story')}: {p}" for p in _given(acc)]
        if s.get("req") not in reqs:
            out.append(f"{s.get('story')}: it must trace to an approved requirement")
    return out


STORY_EDIT = wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("story", "Story", readonly=True), wb.Column("req", "Requirement", readonly=True),
                              wb.Column("summary", "User story", "longtext"), wb.Column("priority", "Priority", "select", options=PRIORITIES),
                              wb.Column("acceptance", "Acceptance criteria", "longtext", help="one per line: Given … when … then …")], add=False, remove=False, validate=_validate_stories, label="story")


def _story_payload(ctx: wb.Ctx, s: dict, reqs: dict) -> dict:
    r = reqs.get(s["req"]) or {}
    return {"ref": s["story"], "summary": s["summary"], "priority": s.get("priority"), "acceptance": [a for a in str(s.get("acceptance") or "").splitlines() if a.strip()],
            "description": f"{r.get('statement') or ''} — from BRD “{ctx.title}” version {ctx.get('doc_version')}, {s['req']}; source: {r.get('where') or ''}",
            "labels": ["brd", ctx.get("doc") or "", s["req"]]}


def _keys(ctx: wb.Ctx) -> dict:
    out = {}
    for p in _w4.pushes(ctx.id):
        for c in (p["result"] or {}).get("created") or []:
            out[c["ref"]] = c
    return out


def _desk_story(ctx: wb.Ctx, s: dict, reqs: dict) -> dict:
    pl = _story_payload(ctx, s, reqs)
    return {"title": s["summary"], "description": pl["description"] + "\n\nAcceptance criteria:\n" + "\n".join(f"- {a}" for a in pl["acceptance"]),
            "priority": DESK_PRIORITY.get(s.get("priority") or "", "P3"), "labels": ["brd", s["req"]]}


def d_trace(ctx: wb.Ctx) -> dict:
    stories = [s for s in ctx.records("backlog") if s.get("include")]
    reqs = {r["req"]: r for r in ctx.get("final") or []}
    tg = _target(ctx)
    keys = _keys(ctx)
    todo = [s for s in stories if s["story"] not in keys]
    ctx.output("backlog-jira.csv", _w4.csv_text(["Summary", "Issue Type", "Priority", "Description", "Labels"],
                                                 [[s["summary"], "Story", trk.PRIORITY_JIRA.get(s.get("priority") or "", "Medium"), _story_payload(ctx, s, reqs)["description"] + "\n\nAcceptance criteria:\n" + s["acceptance"],
                                                   " ".join(["relay", s["req"]])] for s in stories]), label="Backlog for Jira's CSV import")
    ctx.output("backlog-azure-boards.csv", _w4.csv_text(["Work Item Type", "Title", "Description", "Acceptance Criteria", "Priority", "Tags"],
                                                         [["User Story", s["summary"], _story_payload(ctx, s, reqs)["description"], s["acceptance"], trk.PRIORITY_ADO.get(s.get("priority") or "", 2), f"relay; {s['req']}"] for s in stories]),
               label="Backlog for Azure Boards' CSV import")
    if tg["kind"] == "jira" and todo:
        if tg["gone"]:
            raise wb.StepFailed(f"{tg['name']} may not raise tickets: an admin allows it under Service desk › Sources › May do (Read & write), or pick no Jira project to use the CSV files.")
        waiting = {p["result"].get("ref") for p in _w4.latest_pushes(ctx.id, "trace") if p["status"] == "awaiting"}
        for s in todo:
            if s["story"] not in waiting:
                _w4.desk_write(ctx, tg["id"], "create", _desk_story(ctx, s, reqs), step="trace", ref=s["story"], name=f"Story {s['story']} to {tg['system']}: {s['summary'][:110]}")
    elif tg["kind"] == "boards" and todo:
        if not connectors.may_write(tg["conn"]):
            raise wb.StepFailed(f"{tg['name']} is read-only: change its scope to “Read & write — with approval” to push the backlog, or remove it from the work item to use the CSV files.")
        _w4.request_push(ctx, tg["id"], "stories", {"stories": [_story_payload(ctx, s, reqs) for s in todo]},
                         f"Push {len(todo)} user stor{'y' if len(todo) == 1 else 'ies'} to {tg['name']} (BRD {ctx.title}, version {ctx.get('doc_version')})", step="trace",
                         items=[f"{s['story']} ({s['req']}): {s['summary'][:150]}" for s in todo[:8]])
    _lineage(ctx, stories, reqs)
    return _trace_view(ctx)


def _story_state(s: dict, keys: dict, latest: list[dict], tg: dict) -> str:
    if (keys.get(s["story"]) or {}).get("key"):
        return keys[s["story"]]["key"]
    p = next((p for p in latest if p["target"] == "jira" and p["result"].get("ref") == s["story"]), None) or next((p for p in latest if p["target"] != "jira"), None)
    if not p:
        return "CSV export" if tg["kind"] == "csv" else "not asked yet"
    return {"awaiting": "awaiting its write approval", "failed": "not written — run Trace again"}.get(p["status"], "not written")


def _tests_of(nid: str) -> list[str]:
    rows = db.q("SELECT n.label, n.name FROM lineage_edges e JOIN lineage_nodes n ON n.id = e.to_id WHERE e.from_id = ? AND n.kind = 'test'", (nid,))
    return [r["label"] or r["name"] for r in rows]


def _trace_view(ctx: wb.Ctx) -> dict:
    stories = [s for s in ctx.records("backlog") if s.get("include")]
    reqs = ctx.get("final") or []
    keys = _keys(ctx)
    signed = ", ".join(f"{r['person']} ({r['when']})" for r in _w4.signoff_records(ctx.id, "approve", ctx.get("round") or "v2") if r["decision"] == "signed off") or _w4.user_name(ctx.st.get("approver") or ctx.owner)
    tg = _target(ctx)
    latest = _w4.latest_pushes(ctx.id, "trace")
    from .. import lineage
    rows = []
    for r in reqs:
        ss = [s for s in stories if s["req"] == r["req"]]
        nid = lineage.node_id("requirement", f"{SYSTEM} {ctx.get('doc')}", r["req"])
        tests = _tests_of(nid)
        rows.append({"id": r["req"], "requirement": f"{r['req']}: {r.get('title') or r['statement'][:60]}", "source": r.get("where") or "", "version": f"v{ctx.get('doc_version')}",
                     "signed": signed, "story": ", ".join(s["story"] for s in ss) or "—", "tracker": ", ".join(_story_state(s, keys, latest, tg) for s in ss) or "—",
                     "tests": ", ".join(tests) or "none yet"})
    pushed = sum(1 for s in stories if (keys.get(s["story"]) or {}).get("key"))
    waiting = sum(1 for p in latest if p["status"] == "awaiting")
    errs = [e for p in latest for e in (p["result"].get("errors") or [])]
    state = (f"in {tg['system']}: " + ", ".join(keys[s["story"]]["key"] for s in stories if (keys.get(s["story"]) or {}).get("key")) if pushed and pushed == len(stories)
             else f"waiting for {waiting} write approval(s) in the Validation queue ({pushed} of {len(stories)} written)" if waiting
             else f"partly written ({pushed} of {len(stories)}): run Trace again for the rest" if pushed or latest else "exported as CSV for a person to import")
    return {"summary": f"{len(reqs)} requirement(s) traced to their passage, version {ctx.get('doc_version')}, the sign-off and {len(stories)} stor{'y' if len(stories) == 1 else 'ies'}; "
            f"the backlog is {state}" + (f"; {len(errs)} refused: {errs[0].get('error')}" if errs else "") + ".",
            "counts": {"requirements": len(reqs), "stories": len(stories), "in the tracker": pushed}, "records": rows,
            "data": {"columns": ["Requirement", "Source", "Version", "Signed off by", "Story", "Tracker", "Tests"],
                     "rows": [[x["requirement"], x["source"], x["version"], x["signed"], x["story"], x["tracker"], x["tests"]] for x in rows]}}


def _lineage(ctx: wb.Ctx, stories: list[dict], reqs: dict) -> None:
    did = ctx.get("doc")
    keys = _keys(ctx)
    doc = ctx.lineage_node("document", SYSTEM, did, label=f"BRD: {ctx.title} (v{ctx.get('doc_version')})", properties={"version": ctx.get("doc_version"), "requirements": len(reqs)})
    for f in {x["ref"].split("#")[0] for r in reqs.values() for x in r.get("sources") or []}:
        src = ctx.lineage_node("document", "upload", f"{ctx.id}/{f}", label=f"{f} (upload)")
        ctx.lineage_edge(src, doc, "feeds")
    tsys = _target(ctx)["system"]
    for rid, r in reqs.items():
        rn = ctx.lineage_node("requirement", f"{SYSTEM} {did}", rid, label=f"{rid}: {(r.get('title') or r['statement'])[:80]}", properties={"priority": r.get("priority"), "type": r.get("type")})
        ctx.lineage_edge(doc, rn, "contains")
        for s in [s for s in stories if s["req"] == rid]:
            k = keys.get(s["story"]) or {}
            sn = ctx.lineage_node("story", tsys, f"{did}/{s['story']}", label=f"{k.get('key') or s['story']}: {s['summary'][:70]}", properties={"story": s["story"], "key": k.get("key"), "url": k.get("url")})
            ctx.lineage_edge(rn, sn, "relates", {"story": s["story"], "key": k.get("key")})


def _trace_refresh(ctx: wb.Ctx) -> dict:
    stories = [s for s in ctx.records("backlog") if s.get("include")]
    reqs = {r["req"]: r for r in ctx.get("final") or []}
    _lineage(ctx, stories, reqs)
    keys = _keys(ctx)
    if ctx.get("doc"):
        set_stories(ctx.get("doc"), [{**s, "key": (keys.get(s["story"]) or {}).get("key"), "url": (keys.get(s["story"]) or {}).get("url")} for s in stories])
    return _trace_view(ctx)


_w4.REFRESH["brd.trace"] = _trace_refresh


def _validate_trace(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = _w4.push_problems(ctx.id, "trace")
    errs = [e for p in _w4.latest_pushes(ctx.id, "trace") if p["status"] == "written" for e in (p["result"].get("errors") or [])]
    if errs:
        out.append(f"{len(errs)} stor{'y was' if len(errs) == 1 else 'ies were'} refused by the tracker ({errs[0].get('error')}): run Trace again to send them")
    return out


TRACE_EDIT = wb.Edit(columns=[wb.Column("requirement", "Requirement", readonly=True), wb.Column("source", "Source", readonly=True), wb.Column("version", "Version", readonly=True),
                              wb.Column("signed", "Signed off by", readonly=True), wb.Column("story", "Story", readonly=True), wb.Column("tracker", "Tracker", readonly=True),
                              wb.Column("tests", "Tests", readonly=True)], add=False, remove=False, validate=_validate_trace, label="trace row")


# ------------------------------------------------------------------ Change

def _doc_or_fail(ctx: wb.Ctx) -> dict:
    d = document(ctx.scope.get("brd") or "", db.user(ctx.owner or "") or {})
    if not d:
        raise wb.StepFailed("The BRD this work item changes is not one its owner can see any more.")
    return d


def carried(ctx: wb.Ctx, d: dict) -> list[dict]:
    """The passages an approved BRD's requirements cite, carried over from the items that drafted and changed it (only
    those its owner may still see), so a change can cite them by the same ids."""
    want = {x["ref"] for r in d["requirements"] for x in r.get("sources") or []}
    items = [d.get("item")] + [v["item"] for v in db.q("SELECT item FROM brd_versions WHERE doc_id = ? ORDER BY version", (d["id"],))]
    u = db.user(ctx.owner or "") or {}
    have: dict = {}
    for it in dict.fromkeys(i for i in items if i and i != ctx.id):
        p = db.project(it)
        if not (p and auth.can_project(u, "view", p)):
            continue
        try:
            for s in json.loads((wb.folder(it) / "sources" / "segments.json").read_text(encoding="utf-8")).get("segments") or []:
                if s["id"] in want:
                    have[s["id"]] = {**s, "carried_from": it}
        except (OSError, ValueError):
            continue
    return list(have.values())


def c_request(ctx: wb.Ctx) -> dict:
    d = _doc_or_fail(ctx)
    read = _w4.read_uploads(ctx, UPLOADS, extra=_w4.request_segment(ctx) + carried(ctx, d))
    ctx.put("current", d["requirements"])
    ctx.put("stories_now", d["stories"])
    ctx.put("doc", d["id"])
    ctx.put("doc_version", d["version"])
    return {"summary": f"Change to “{d['title']}” (version {d['version']}, {len(d['requirements'])} requirement(s), {len(d['stories'])} stor{'y' if len(d['stories']) == 1 else 'ies'})"
            + (f"; {len(read['files'])} new file(s) read" if read["files"] else "") + ".", "counts": {"requirements": len(d["requirements"]), "version": d["version"]},
            "data": {"text": ctx.brief or "(no request text)"}}


def _stem(w: str) -> str:
    return w[:-3] + "y" if w.endswith("ies") and len(w) > 4 else w[:-1] if w.endswith("s") and not w.endswith("ss") and len(w) > 3 else w


def _toks(s: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", _w4.norm(s)) if w not in STOP and len(w) > 2}


def c_diagnose(ctx: wb.Ctx) -> dict:
    from .. import lineage
    reqs = ctx.get("current") or []
    words = _toks(ctx.brief)
    named = set(re.findall(r"BR-\d{3}", ctx.brief))
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    stories = ctx.get("stories_now") or []
    recs = []
    for r in reqs:
        hit = r["req"] in named or len(words & _toks(f"{r.get('title')} {r['statement']}")) >= 2
        nid = lineage.node_id("requirement", f"{SYSTEM} {ctx.get('doc')}", r["req"])
        ss = [s for s in stories if s.get("req") == r["req"]]
        rec = {"id": r["req"], "req": r["req"], "touched": hit, "statement": r["statement"], "stories": ", ".join(s.get("key") or s["story"] for s in ss) or "—", "tests": ", ".join(_tests_of(nid)) or "—"}
        recs.append({**rec, **({"touched": have[r["req"]]["touched"]} if r["req"] in have else {})})
    t = [r for r in recs if r["touched"]]
    return {"summary": f"The request touches {len(t)} of {len(recs)} requirement(s)" + (f", with {sum(1 for r in t if r['stories'] != '—')} stor{'y' if len(t) == 1 else 'ies'} in the tracker and their tests" if t else "")
            + ". Tick what the change is about before anything is drafted.", "records": recs, "counts": {"touched": len(t), "requirements": len(recs)},
            "data": {"columns": ["Touched", "Requirement", "Statement", "Stories", "Tests"], "rows": [["yes" if r["touched"] else "no", r["req"], r["statement"], r["stories"], r["tests"]] for r in recs]},
            "items": [f"{r['req']}: {r['statement'][:140]}" for r in t[:6]]}


DIAG_EDIT = wb.Edit(columns=[wb.Column("touched", "Touched", "bool"), wb.Column("req", "Requirement", readonly=True), wb.Column("statement", "Statement", readonly=True),
                             wb.Column("stories", "Stories", readonly=True), wb.Column("tests", "Tests", readonly=True)], add=False, remove=False, label="requirement")

CHANGE = """Read WORK.md, request.md (the change request), sources/segments.json (the passages you may cite: the request
itself as request#p1…, and any new upload) and current.json (the approved requirements this change starts from; the
ones the person ticked are marked touched: true).

FILE brd_change.yaml:

changes:
  - op: change | add | remove
    id: BR-003                    # an existing id for change / remove; the next free BR-0xx for add
    title: …
    statement: …                  # change / add
    type: functional | non-functional | rule | data | report
    priority: must | should | could | wont
    sources: [{ref: request#p1, quote: "the words the change rests on"}]
    acceptance: ["Given …, when …, then …"]
    story: {as_a, i_want, so_that}
    why: <one line>

Only what the request asks for; cite the passage for every change, word for word; a figure must be in what you cite."""


def _change_prompt(ctx: wb.Ctx) -> str:
    touched = {r["req"] for r in ctx.records("diagnose") if r.get("touched")}
    (ctx.dir / "current.json").write_text(json.dumps([{**{k: r.get(k) for k in ("req", "title", "statement", "type", "priority", "acceptance")}, "touched": r["req"] in touched} for r in ctx.get("current") or []], indent=1),
                                          encoding="utf-8")
    return CHANGE


def _change_check(ctx: wb.Ctx) -> list[str]:
    y, probs = _w4.load_yaml(ctx.dir / "brd_change.yaml")
    if probs:
        return probs
    segs = _w4.segments(ctx)
    cur = {r["req"] for r in ctx.get("current") or []}
    out = []
    ch = _list(y.get("changes"))
    if not ch:
        out.append("changes is empty")
    for i, c in enumerate(ch, 1):
        if not isinstance(c, dict):
            out.append(f"change {i} must be a mapping")
            continue
        where = f"{c.get('op')} {c.get('id')}"
        if c.get("op") not in ("change", "add", "remove"):
            out.append(f"change {i}: op is change, add or remove")
        if c.get("op") in ("change", "remove") and c.get("id") not in cur:
            out.append(f"{where}: no approved requirement has that id")
        if c.get("op") == "add" and (c.get("id") in cur or not re.fullmatch(r"BR-\d{3}", str(c.get("id") or ""))):
            out.append(f"{where}: an added requirement takes the next free BR-0xx id")
        if c.get("op") in ("change", "add"):
            if not str(c.get("statement") or "").strip():
                out.append(f"{where}: the statement is empty")
            if c.get("type") not in dict(TYPES) or c.get("priority") not in dict(PRIORITIES):
                out.append(f"{where}: type and priority are needed")
            acc = [str(a) for a in _list(c.get("acceptance")) if str(a).strip()]
            if c.get("type") in STORY_TYPES:
                out += [f"{where}: {p}" for p in _given(acc)] + ([f"{where}: give an acceptance criterion"] if not acc else [])
        out += _w4.check_sources(where, _w4.parse_refs(c.get("sources")), segs, statement=f"{c.get('statement') or ''} {' '.join(map(str, _list(c.get('acceptance'))))}")
    return out


def _change_after(ctx: wb.Ctx, res: dict) -> dict:
    y, _ = _w4.load_yaml(ctx.dir / "brd_change.yaml")
    segs = _w4.segments(ctx)
    cur = {r["req"]: r for r in ctx.get("current") or []}
    recs = []
    for c in _list(y.get("changes")):
        base = cur.get(c.get("id")) or {}
        rec = _req_record({**base, **{k: v for k, v in c.items() if k != "op"}, "id": c["id"], "sources": c.get("sources"), "type": c.get("type") or base.get("type"),
                           "priority": c.get("priority") or base.get("priority"), "statement": c.get("statement") or base.get("statement") or ""}, segs)
        recs.append({**rec, "op": c["op"], "why": str(c.get("why") or "")})
    ctx.evidence("The agent's change (brd_change.yaml)", {"change": y, "summary": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"{sum(1 for r in recs if r['op'] == 'change')} changed, {sum(1 for r in recs if r['op'] == 'add')} added, {sum(1 for r in recs if r['op'] == 'remove')} removed — each citing what it rests on. "
            "Correct the rows, then confirm.", "records": recs, "data": {"columns": ["Change", "Requirement", "Statement", "From", "Why"],
                                                                         "rows": [[r["op"], r["req"], r["statement"], r["where"], r["why"]] for r in recs]}, "counts": {"changes": len(recs)}}


CHANGE_EDIT = wb.Edit(columns=[wb.Column("op", "Change", "select", options=(("change", "Change"), ("add", "Add"), ("remove", "Remove")))] + REQ_COLUMNS[1:], validate=_validate_reqs, label="change")


def _apply_change(ctx: wb.Ctx) -> list[dict]:
    cur = {r["req"]: dict(r) for r in ctx.get("current") or []}
    for c in ctx.records("fix"):
        if not c.get("keep", True):
            continue
        if c["op"] == "remove":
            cur.pop(c["req"], None)
        else:
            cur[c["req"]] = {k: v for k, v in c.items() if k not in ("op", "why")}
    return sorted(cur.values(), key=lambda r: r["req"])


def c_prove(ctx: wb.Ctx) -> dict:
    after = _apply_change(ctx)
    segs = _w4.segments(ctx)
    changed = [c for c in ctx.records("fix") if c.get("keep", True)]
    refs = [x["ref"] for c in changed for x in c.get("sources") or []]
    rows = [ctx.proof("references_real", label="Every change cites a passage that exists", refs=refs or ["(none)"], known=list(segs))]
    unsourced = []
    for c in changed:
        if c["op"] != "remove" and not _w4.person_source(c.get("source")):
            miss = _w4.numbers_unsourced(c["statement"], [segs[x["ref"]]["text"] for x in c.get("sources") or [] if x["ref"] in segs])
            if miss:
                unsourced.append(f"{c['req']}: {', '.join(miss)}")
    rows.append({"name": "figures", "label": "Every figure is in what it cites", "status": "fail" if unsourced else "pass", "measured": len(changed) - len(unsourced), "expected": len(changed),
                 "detail": "; ".join(unsourced) or "no figure without a source", "evidence": ctx.evidence("Figures in the changed requirements", {"rows": [{"unsourced": u} for u in unsourced]}, kind="proof", ok=not unsourced)})
    ids = [r["req"] for r in after]
    rows.append({"name": "ids", "label": "Requirement ids stay unique", "status": "pass" if len(ids) == len(set(ids)) else "fail", "measured": len(set(ids)), "expected": len(ids), "detail": f"{len(ids)} requirement(s) in the new version"})
    gone = [s for s in ctx.get("stories_now") or [] if s.get("req") not in set(ids)]
    rows.append({"name": "stories", "label": "Every story of a removed requirement is accounted for", "status": "warn" if gone else "pass", "measured": len(gone), "expected": 0,
                 "detail": (f"{len(gone)} stor{'y' if len(gone) == 1 else 'ies'} ({', '.join(s.get('key') or s['story'] for s in gone)}) will get a comment that the requirement was removed" if gone else "no story is left without a requirement")})
    v = int(ctx.get("doc_version") or 1) + 1
    info = _brd_doc(ctx, f"brd-v{v}-proposed", v, "proposed change", after, {"scope": f"Version {v} of an approved BRD, changed as requested."})
    dp = _w4.doc_problems(info)
    rows.append({"name": "document", "label": "The new version builds and passes the document checks", "status": "fail" if dp else "pass", "detail": "; ".join(dp[:3]) or "Word and the HTML preview built in your template"})
    ctx.put("after", after)
    ctx.put("next_version", v)
    bad = sum(1 for r in rows if r["status"] == "fail")
    return {"summary": f"{len(changed)} change(s) proven" + (f": {bad} check(s) fail" if bad else ": every check passes") + f"; version {v} is ready for release.", "data": {"checks": rows},
            "counts": {"changes": len(changed), "failing": bad}, "ok": True}


def c_approve(ctx: wb.Ctx) -> dict:
    ch = [c for c in ctx.records("fix") if c.get("keep", True)]
    return {"summary": f"Release version {ctx.get('next_version')}: " + ", ".join(f"{sum(1 for c in ch if c['op'] == k)} {k}d" if k != "add" else f"{sum(1 for c in ch if c['op'] == k)} added" for k in ("change", "add", "remove")) + ".",
            "data": {"items": [{"title": f"{c['op'].title()} {c['req']}", "detail": c.get("statement") if c["op"] != "remove" else "removed"} for c in ch]}}


def c_learn(ctx: wb.Ctx) -> dict:
    after = ctx.get("after") or _apply_change(ctx)
    v = ctx.get("next_version")
    _brd_doc(ctx, f"brd-v{v}-approved", v, "approved", after, {"scope": f"Version {v} of an approved BRD, changed as requested."})
    stories = list(ctx.get("stories_now") or [])
    changed = {c["req"]: c for c in ctx.records("fix") if c.get("keep", True)}
    updates, new = [], []
    for s in stories:
        c = changed.get(s.get("req"))
        if c and s.get("key"):
            updates.append({"ref": s["story"], "key": s["key"], "comment": (f"Requirement {c['req']} was removed in BRD version {v}." if c["op"] == "remove" else
                                                                           f"Requirement {c['req']} changed in BRD version {v}: {c['statement']}"),
                            **({"summary": _story_of(c, 0)["summary"]} if c["op"] == "change" and c.get("as_a") else {})})
    n = len(stories)
    for c in changed.values():
        if c["op"] == "add" and c.get("type") in STORY_TYPES:
            n += 1
            st = _story_of(c, n)
            stories.append(st)
            new.append({"ref": st["story"], "summary": st["summary"], "priority": st["priority"], "acceptance": [a for a in st["acceptance"].splitlines() if a.strip()],
                        "description": f"{c['statement']} — from BRD “{ctx.title}” version {v}, {c['req']}", "labels": ["brd", ctx.get("doc"), c["req"]]})
    d = publish(ctx, after, stories, ctx.get("doc"), [], f"brd-v{v}-approved.docx", note=(ctx.brief or "")[:300])
    tg = _target(ctx)
    if tg["kind"] == "jira" and not tg["gone"]:
        for u in updates:
            _w4.desk_write(ctx, tg["id"], "comment", {"key": u["key"], "text": u["comment"]}, step="learn", ref=u["ref"], name=f"Comment on {u['key']}: BRD version {v}")
        for s in new:
            _w4.desk_write(ctx, tg["id"], "create", {"title": s["summary"], "description": s["description"] + "\n\nAcceptance criteria:\n" + "\n".join(f"- {a}" for a in s["acceptance"]),
                                                    "priority": DESK_PRIORITY.get(s.get("priority") or "", "P3"), "labels": [x for x in s["labels"] if x]}, step="learn", ref=s["ref"],
                           name=f"Story {s['ref']} to {tg['system']}: {s['summary'][:110]}")
    elif tg["kind"] == "boards" and (updates or new) and connectors.may_write(tg["conn"]):
        _w4.request_push(ctx, tg["id"], "updates", {"updates": updates, "stories": new}, f"Update {len(updates)} and add {len(new)} stor{'y' if len(updates) + len(new) == 1 else 'ies'} in {tg['name']} (BRD version {v})",
                         step="learn", items=[f"{u['key']}: {u['comment'][:160]}" for u in updates[:6]] + [f"new {s['ref']}: {s['summary'][:120]}" for s in new[:4]])
    return _learn_view(ctx, d)


def _learn_view(ctx: wb.Ctx, d: dict | None = None) -> dict:
    d = d or document(ctx.get("doc") or "") or {}
    ps = _w4.latest_pushes(ctx.id, "learn")
    state = ("nothing to update" if not ps else "done" if all(p["status"] == "written" for p in ps) else
             f"{sum(1 for p in ps if p['status'] == 'awaiting')} waiting for their own approval in the Validation queue" if any(p["status"] == "awaiting" for p in ps) else "failed — see the activity")
    return {"summary": f"Version {d.get('version')} of “{d.get('title')}” is approved and kept; tracker updates: {state}.", "counts": {"version": d.get("version") or 0},
            "data": {"href": f"#/m/{MODULE}/i/{ctx.id}", "label": "This work item", "text": f"Version {d.get('version')} · {len(d.get('requirements') or [])} requirement(s)"}}


_w4.REFRESH["brd.learn"] = lambda ctx: _learn_view(ctx)


# ------------------------------------------------------------------ Migrate (old specs to the standard BRD)

def m_collect(ctx: wb.Ctx) -> dict:
    out = d_gather(ctx)
    out["summary"] = out["summary"].replace("file(s) read", "old spec(s) read")
    return out


def m_standardise(ctx: wb.Ctx) -> dict:
    reqs = [r for r in ctx.records("read") if r.get("keep", True)]
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    issues = []
    for i, a in enumerate(reqs):
        for b in reqs[i + 1:]:
            ta, tb = _toks(a["statement"]), _toks(b["statement"])
            jac = len(ta & tb) / len(ta | tb) if ta | tb else 0
            na, nb = _w4.numbers(a["statement"]), _w4.numbers(b["statement"])
            neg = bool(NEG.search(_w4.norm(a["statement"]))) != bool(NEG.search(_w4.norm(b["statement"])))
            kind = None
            if jac >= 0.6 and na == nb and not neg:
                kind = "duplicate"
            elif jac >= 0.3 and ((na and nb and na != nb) or neg):
                kind = "contradiction"
            if kind:
                iid = f"{kind[:3]}-{a['req']}-{b['req']}"
                rec = {"id": iid, "kind": kind, "a": a["req"], "b": b["req"], "a_text": a["statement"], "b_text": b["statement"], "where": f"{a.get('where')} | {b.get('where')}",
                       "decision": "merge" if kind == "duplicate" else "", "note": ""}
                issues.append({**rec, **{k: have[iid][k] for k in ("decision", "note") if iid in have}})
    return {"summary": f"{len(reqs)} requirement(s) mapped to the BRD template; {sum(1 for x in issues if x['kind'] == 'duplicate')} duplicate(s) and "
            f"{sum(1 for x in issues if x['kind'] == 'contradiction')} contradiction(s), each with where it came from — decide each one.",
            "records": issues, "counts": {"requirements": len(reqs), "duplicates": sum(1 for x in issues if x["kind"] == "duplicate"), "contradictions": sum(1 for x in issues if x["kind"] == "contradiction")},
            "data": {"columns": ["Kind", "A", "B", "A says", "B says", "Where"], "rows": [[x["kind"], x["a"], x["b"], x["a_text"], x["b_text"], x["where"]] for x in issues]},
            "items": [f"{x['kind']}: {x['a']} / {x['b']}" for x in issues[:6]]}


def _validate_issues(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for x in recs:
        if x.get("decision") not in ("merge", "keep A", "keep B", "keep both"):
            out.append(f"{x['a']} / {x['b']}: decide — merge, keep A, keep B or keep both")
        elif x["kind"] == "contradiction" and x["decision"] in ("keep both", "merge"):
            out.append(f"{x['a']} / {x['b']}: a contradiction cannot stand — keep A or keep B")
    return out


ISSUE_EDIT = wb.Edit(columns=[wb.Column("kind", "Kind", readonly=True), wb.Column("a", "A", readonly=True), wb.Column("b", "B", readonly=True), wb.Column("where", "Where", readonly=True),
                              wb.Column("decision", "Decision", "select", options=(("merge", "Merge (keep A)"), ("keep A", "Keep A"), ("keep B", "Keep B"), ("keep both", "Keep both"))),
                              wb.Column("note", "Note", "longtext")], add=False, remove=False, validate=_validate_issues, label="issue")

GAP_KINDS = ("report", "flow", "job", "bot", "api", "table", "page")


def m_gaps(ctx: wb.Ctx) -> dict:
    reqs = [r for r in ctx.records("read") if r.get("keep", True)]
    nodes = db.q(f"SELECT kind, system, name, label FROM lineage_nodes WHERE kind IN ({','.join('?' * len(GAP_KINDS))})", GAP_KINDS)
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    gaps = []
    for r in reqs:
        named = set(re.findall(r"“([^”]{3,80})”|\"([^\"]{3,80})\"", r["statement"]))
        names = {a or b for a, b in named} | {m.strip() for m in re.findall(r"((?:[A-Z][\w&-]*\s){1,5}(?:report|dashboard|flow|job|bot|API|table|extract))", r["statement"])}
        for nm in names:
            hit = [n for n in nodes if _w4.norm(nm) in _w4.norm(n["label"] or n["name"]) or _w4.norm(n["label"] or n["name"]) in _w4.norm(nm)]
            if not hit:
                gid = f"gap-{r['req']}-{_w4.slug(nm, 24)}"
                rec = {"id": gid, "kind": "not on the knowledge map", "req": r["req"], "what": f"{r['req']} names “{nm}”, which the knowledge map does not have — the system may not do this today",
                       "decision": "", "note": ""}
                gaps.append({**rec, **{k: have[gid][k] for k in ("decision", "note") if gid in have}})
    text = _w4.norm(" ".join(r["statement"] for r in reqs))
    spec_words = _toks(text)
    def near_spec(n):                                   # the map's items in the spec's own terms: two words in common, half of the item's name
        t = _toks(n["label"] or n["name"])
        return len(t & spec_words) >= 2 and len(t & spec_words) * 2 >= len(t)
    near = [n for n in nodes if n["kind"] in ("report", "flow", "bot") and _w4.norm(n["label"] or n["name"]) not in text and near_spec(n)]
    for n in near[:25]:
        gid = f"gap-map-{_w4.slug(n['name'], 30)}"
        rec = {"id": gid, "kind": "no requirement", "req": "—", "what": f"the knowledge map has {n['kind']} “{n['label'] or n['name']}” ({n['system']}); no requirement says what it should do",
               "decision": "", "note": "", "requirement": {"id": f"gap-{_w4.slug(n['name'], 20)}", "req": "", "keep": True, "title": n["label"] or n["name"],
                                                           "statement": f"The {n['kind']} “{n['label'] or n['name']}” keeps working as it does today.", "type": "report" if n["kind"] == "report" else "functional",
                                                           "priority": "should", "source": "", "sources": [], "where": f"the knowledge map: {n['kind']} {n['label'] or n['name']}",
                                                           "acceptance": f"Given the {n['kind']} runs today, when the change goes live, then it gives the same results", "origin": "knowledge map",
                                                           "as_a": "business user", "i_want": f"the {n['kind']} {n['label'] or n['name']} to keep working", "so_that": "nothing that works today is lost"}}
        gaps.append({**rec, **{k: have[gid][k] for k in ("decision", "note") if gid in have}})
    return {"summary": f"{len(nodes)} item(s) on the knowledge map compared with {len(reqs)} requirement(s): {sum(1 for g in gaps if g['kind'] == 'not on the knowledge map')} requirement(s) name something "
            f"the map does not have, {sum(1 for g in gaps if g['kind'] == 'no requirement')} thing(s) the system does that no requirement covers.",
            "records": gaps, "counts": {"gaps": len(gaps), "on the map": len(nodes)},
            "data": {"columns": ["Gap", "Requirement", "What"], "rows": [[g["kind"], g["req"], g["what"]] for g in gaps]}, "items": [g["what"][:200] for g in gaps[:6]]}


def _validate_gaps(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    out = []
    for g in recs:
        ok = ("accept the gap", "ignore") + (("add as requirement",) if g.get("kind") == "no requirement" else ())
        if g.get("decision") not in ok:
            out.append(f"{g.get('req')}: decide — {', '.join(ok)}")
    return out


GAP_EDIT = wb.Edit(columns=[wb.Column("kind", "Gap", readonly=True), wb.Column("req", "Requirement", readonly=True), wb.Column("what", "What", readonly=True),
                            wb.Column("decision", "Decision", "select", options=(("accept the gap", "Accept the gap (the system will be changed)"), ("add as requirement", "Add a requirement for it"), ("ignore", "Ignore"))),
                            wb.Column("note", "Note", "longtext")], add=False, remove=False, validate=_validate_gaps, label="gap")


# ------------------------------------------------------------------ the module page

def _cards(u: dict) -> list[dict]:
    rows = [[d["title"], f"v{d['version']}", len(d["requirements"]), len(d["stories"]), sum(1 for s in d["stories"] if s.get("key")), _w4.user_name(d.get("approved_by")),
             time.strftime("%d %b %Y", time.gmtime(d["approved"])) if d.get("approved") else "—", f"#/m/{MODULE}/i/{d['item']}" if d.get("item") else ""] for d in documents(u)]
    return [{"title": "Approved BRDs", "columns": ["BRD", "Version", "Requirements", "Stories", "In the tracker", "Approved by", "When", "Work item"], "rows": rows,
             "empty": "No BRD is approved yet: a Develop item's Approve step records one."}]


GUIDE = """# BRD & requirements — the work item

This folder is one work item of Relay's BRD & requirements module. The agent drafts; people review, sign off and
approve; nothing reaches Jira or Azure Boards without its own approval.

- `data/`: the uploads — workshop notes, e-mails (.eml), call transcripts (.vtt / .srt), recordings, whiteboard photos,
  old specs. `genbi read data/<file>` reads any of them (a video's key frames, a PDF's pages).
- `sources/segments.json`: every passage the app read, with its id (`<file>#<where>`) — the only things a requirement
  may cite. A recording or an image has one passage `<file>#media` with no text: look at it yourself, but a figure
  needs a passage that says it.
- `brd.yaml` (Draft / Read): the BRD — scope, stakeholders, current and future process, requirements (BR-001…, each
  with sources [{ref, quote}], acceptance criteria Given / When / Then and a user story), rules, risks, open questions.
- `brd_change.yaml` (Change): what changes in an approved BRD; `current.json` is where it starts from.

Never invent a requirement, a figure or a quote: cite the passage, word for word; what the sources do not settle is
an open question."""


wb.register(wb.Pack(
    module=MODULE, guide=GUIDE,
    lineage="the BRD as a document fed by its uploads, each requirement it contains, and each requirement's user stories (with their Jira or Azure Boards keys); Test plans links its tests to the requirements",
    platforms={"files": FILES, "tracker": TRACKER},
    schemas={"requirement": REQ_COLUMNS, "story": STORY_EDIT.columns, "trace": TRACE_EDIT.columns},
    cards=_cards,
    work={
        "develop": wb.Work(title="From workshop notes, recordings and e-mails to an approved BRD and a backlog in Jira or Azure Boards", platforms=("files", "tracker"), steps={
            "Gather": wb.Step(kind="platform", run=d_gather, agent="Reader", text="Every upload is read into passages with ids — notes, e-mails, transcripts, page exports; recordings and whiteboard photos are looked at by the agent"),
            "Draft": wb.Step(kind="agent", prompt=_draft_prompt, check=_draft_check, after=_draft_after, agent="BRD writer", edit=REQ_EDIT, turns=60,
                             text="The agent drafts the BRD in your template: scope, stakeholders, current vs future process, requirements, rules, data, risks — each requirement citing the passage it rests on"),
            "Review": wb.Step(kind="person", run=d_review, edit=REVIEW_EDIT, confirm="the business owners' comments in place, and the answers to the open questions",
                              text="Business owners comment in place; open questions are answered or stay open — never guessed"),
            "Approve": wb.Step(kind="deterministic", run=d_approve, agent="Sign-off clerk", approver=True, edit=SIGN_EDIT, back_to="review",
                               confirm="sign-off by each business owner, then the named approver", text="The version for approval goes to each business owner to sign (names and dates); every version is kept"),
            "Backlog": wb.Step(kind="deterministic", run=d_backlog, agent="Story writer", edit=STORY_EDIT, text="User stories and acceptance criteria from the approved requirements — you confirm them before they go anywhere"),
            "Trace": wb.Step(kind="platform", run=d_trace, agent="Tracer", edit=TRACE_EDIT, confirm="the trace — every requirement to its source, the sign-off, its stories and their keys",
                             text="The stories go to Jira or Azure Boards after their own approval (or as CSV files); each requirement is traced to its source, the build, the tests and the sign-off")},
            fields=[wb.Field("owners", "Business owners who sign off", "longtext", help="One per line: the e-mail or name of each business owner. Blank: the named approver signs alone."), wb.Field("jira", "Jira project for the stories", "select", options=_w4.desk_options, help="A Service desk source that may raise tickets (Service desk › Sources › May do: Read & write, with the project and the issue type Story). Each story is written after its own approval. Or connect Azure Boards above, or neither: the backlog is exported as CSV files.")]),
        "change": wb.Work(title="Change an approved BRD — what it touches, a sourced change, proof, release and the tracker updated", needs_source=False, platforms=("files", "tracker"), steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Reader", text="The change in plain words, the approved BRD it changes, and any new notes"),
            "Diagnose": wb.Step(kind="deterministic", run=c_diagnose, agent="Impact reader", edit=DIAG_EDIT, confirm="what the change touches — requirements, stories and tests",
                                text="Which requirements the request touches, with their stories in the tracker and their tests"),
            "Fix": wb.Step(kind="agent", prompt=_change_prompt, check=_change_check, after=_change_after, agent="BRD writer", edit=CHANGE_EDIT, text="The agent drafts the change — changed, added and removed requirements, each citing what it rests on"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Checker", back_to="fix", text="Every change cites a real passage, figures are sourced, ids stay unique, stories are accounted for and the new version builds"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the new version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The new version is kept; the tracker's stories are updated after their own approval")},
            fields=[wb.Field("brd", "BRD to change", "select", options=document_options, required=True), wb.Field("jira", "Jira project its stories are in", "select", options=_w4.desk_options, help="A Service desk source that may raise tickets (Service desk › Sources › May do: Read & write, with the project and the issue type Story). Each story is written after its own approval. Or connect Azure Boards above, or neither: the backlog is exported as CSV files.")]),
        "migrate": wb.Work(title="Old specs in Word, PDF, Confluence or SharePoint to the standard BRD — duplicates, contradictions and gaps found", platforms=("files", "tracker"),
                           journey=["Collect", "Read", "Standardise", "Gaps", "Approve", "Backlog", "Trace"], steps={
            "Collect": wb.Step(kind="platform", run=m_collect, agent="Reader", text="Bring old specs in Word, PDF, Confluence or SharePoint exports — every passage read with its id"),
            "Read": wb.Step(kind="agent", prompt=_draft_prompt, check=_draft_check, after=_draft_after, agent="BRD writer", edit=REQ_EDIT, turns=60, confirm="every old requirement mapped to your BRD template",
                            text="The agent reads them and maps every requirement to your BRD template, each with the passage it came from"),
            "Standardise": wb.Step(kind="deterministic", run=m_standardise, agent="Standardiser", edit=ISSUE_EDIT, confirm="the duplicates and contradictions, each decided",
                                   text="Duplicates and contradictions listed with where they came from — rules first"),
            "Gaps": wb.Step(kind="deterministic", run=m_gaps, agent="Gap finder", edit=GAP_EDIT, confirm="the gaps against how the system really behaves",
                            text="Gaps against how the system really behaves (from the knowledge map) flagged"),
            "Approve": wb.Step(kind="deterministic", run=d_approve, agent="Sign-off clerk", approver=True, edit=SIGN_EDIT, back_to="standardise",
                               confirm="sign-off by each owner of the standard version, then the named approver", text="Owners approve the standard version"),
            "Backlog": wb.Step(kind="deterministic", run=d_backlog, agent="Story writer", edit=STORY_EDIT, confirm="the user stories before they go to the tracker",
                               text="User stories and acceptance criteria from the standard BRD"),
            "Trace": wb.Step(kind="platform", run=d_trace, agent="Tracer", edit=TRACE_EDIT, confirm="the trace — every requirement to its source, the sign-off, its stories and their keys",
                             text="The backlog goes to Jira or Azure Boards after its own approval; every requirement traced")},
            fields=[wb.Field("owners", "Owners who approve the standard version", "longtext", help="One per line: the e-mail or name of each owner. Blank: the named approver signs alone."), wb.Field("jira", "Jira project for the stories", "select", options=_w4.desk_options, help="A Service desk source that may raise tickets (Service desk › Sources › May do: Read & write, with the project and the issue type Story). Each story is written after its own approval. Or connect Azure Boards above, or neither: the backlog is exported as CSV files.")]),
    }))
