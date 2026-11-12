"""Document & knowledge assistants (registry id `assist`) - answers from the tenant's own documents, each citing the
passage and page it came from; when the documents do not answer, the assistant says so. Nothing is invented.

Index    assist_index: documents (PDF, Word, PowerPoint, text, Markdown) read into passages with their page or section,
         searched with full-text search (SQLite FTS5 / PostgreSQL text search) - no vector database. A corpus belongs
         to one team of one tenant: only its people (and admins) may ask it.
Answers  extractive by rules: the sentences of the passages found that cover the question, each with its citation;
         Relay (the agent, in the sequential lane) may draft the wording at Prove - every sentence must cite one of the
         passages it was given and carry no number those passages do not hold, or the draft is refused.
Proof    golden questions: what a person expects the assistant to answer, from which document, with which words - and
         questions it must refuse. Scored at Prove and on every scheduled run, kept as scores over time.
Assess   Connect -> Inventory -> Health -> Findings -> Estimate: what the documents hold and where they are weak.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: the documents read, the golden questions agreed, the index
         built, the score proven, a named approval, then the assistant live for its team and evaluated on a schedule.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: documents added or removed, golden questions edited,
         re-proven against today's score before release.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: a FAQ or another assistant's question-and-answer export
         turned into golden questions over the documents, old and new answers side by side.
Run      Watch -> Alert -> Fix -> Approve -> Report: the golden set re-scored; a drop waits for a person."""
from __future__ import annotations

import csv
import io
import json
import secrets as _secrets
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import auth, db, registry
from .. import workbench as wb
from . import assist_index as ai

MODULE = "assist"
PASS_SCORE = 80.0
MINUTES = {"read and tidy a document": 6, "write a golden question": 4, "review the answers": 15}

db.register_schema("""
CREATE TABLE IF NOT EXISTS assist_corpora (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, item TEXT, team_id TEXT, version INTEGER NOT NULL DEFAULT 1, docs TEXT NOT NULL DEFAULT '[]', golden TEXT NOT NULL DEFAULT '[]',
  scores TEXT NOT NULL DEFAULT '[]', run_item TEXT, owner_id TEXT, published_by TEXT, published REAL, status TEXT NOT NULL DEFAULT 'live', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assist_questions (
  id TEXT PRIMARY KEY, corpus TEXT NOT NULL, asked_by TEXT, question TEXT NOT NULL, answered INTEGER NOT NULL DEFAULT 0, answer TEXT, citations TEXT, created REAL NOT NULL);
""")


class DocsPlatform(wb.Platform):
    id, label = "docs", "Documents you upload"
    uploads = ai.DOC_EXT
    simulator = "documents the tests write (PDF with a text layer, Word, PowerPoint, Markdown)"
    reads = "the documents you upload - a copy in this work item's folder, read page by page into passages"


DOCS = DocsPlatform()
FILES = wb.FilesPlatform()
FILES.reads = "a question-and-answer export (CSV or Excel: question, answer, source) to migrate from"
PLATFORMS = {"docs": DOCS, "files": FILES}


# ------------------------------------------------------------------ corpora

def corpus(cid: str, u: dict | None = None) -> dict | None:
    r = db.one("SELECT * FROM assist_corpora WHERE id = ?", (cid,))
    if not r or (u is not None and not may_ask(u, r)):
        return None
    return {**r, **{k: json.loads(r[k] or "[]") for k in ("docs", "golden", "scores")}}


def may_ask(u: dict, r: dict) -> bool:
    """A corpus is its team's: its people (and admins) ask it; the owner of its work item and anyone it is shared with too."""
    if auth.is_admin(u) or any(t["id"] == r.get("team_id") for t in u.get("teams") or []):
        return True
    return bool(r.get("item") and auth.can_project(u, "view", db.project(r["item"])))


def corpora(u: dict) -> list[dict]:
    return [c for c in (corpus(r["id"], u) for r in db.q("SELECT id FROM assist_corpora WHERE status = 'live' ORDER BY updated DESC")) if c]


def corpus_options(u: dict) -> list[tuple[str, str]]:
    return [(c["id"], f"{c['name']} - version {c['version']} - {len(c['docs'])} documents") for c in corpora(u)]


def publish(ctx: wb.Ctx, docs: list[dict], golden: list[dict], score: float | None, cid: str | None = None, note: str = "") -> dict:
    now, who = time.time(), ctx.who or ctx.owner
    team = (db.project(ctx.id) or {}).get("team_id")
    meta = [{k: d.get(k) for k in ("name", "title", "fingerprint")} | {"passages": len(d["passages"])} for d in docs]
    if cid and db.one("SELECT 1 FROM assist_corpora WHERE id = ?", (cid,)):
        old = corpus(cid)
        scores = (old["scores"] + [{"when": now, "score": score, "version": old["version"] + 1, "item": ctx.id}])[-60:]
        db.run("UPDATE assist_corpora SET version = version + 1, docs = ?, golden = ?, scores = ?, published_by = ?, published = ?, updated = ? WHERE id = ?",
               (json.dumps(meta), json.dumps(golden), json.dumps(scores), who, now, now, cid))
    else:
        cid = "asc-" + _secrets.token_hex(4)
        db.run("INSERT INTO assist_corpora (id, name, item, team_id, version, docs, golden, scores, owner_id, published_by, published, status, created, updated) "
               "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'live', ?, ?)", (cid, ctx.title[:160], ctx.id, team, json.dumps(meta), json.dumps(golden),
                                                                       json.dumps([{"when": now, "score": score, "version": 1, "item": ctx.id}]), ctx.owner, who, now, now, now))
    n = ai.index(cid, docs)
    db.audit("assist.corpus.publish", cid, {"documents": len(docs), "passages": n, "score": score, "item": ctx.id, "note": note[:200]}, who)
    return corpus(cid)


# ------------------------------------------------------------------ documents and golden questions

def read_docs(ctx: wb.Ctx, names: set[str] | None = None) -> tuple[list[dict], list[list]]:
    """Every uploaded document read into passages ({"name", "title", "passages", "fingerprint"}); the rows of what was
    read, unreadable ones with the reason."""
    docs, rows = [], []
    for f in ctx.files(ai.DOC_EXT):
        if names is not None and f["name"] not in names:
            continue
        try:
            title, ps = ai.read(ctx.dir / "data" / f["name"])
        except Exception as e:  # noqa: BLE001 - shown as the reason, the other documents go on
            rows.append([f["name"], "-", 0, 0, f"could not be read: {str(e)[:160]}"])
            continue
        d = {"name": f["name"], "title": title, "passages": ps, "fingerprint": ai.fingerprint(ps)}
        docs.append(d)
        rows.append([f["name"], title, len({p.get("page") or p.get("section") for p in ps}), len(ps), "read"])
    return docs, rows


def save_docs(ctx: wb.Ctx, docs: list[dict]) -> None:
    (ctx.dir / "passages.json").write_text(ai.to_json(docs), encoding="utf-8")


def load_docs(ctx: wb.Ctx) -> list[dict]:
    p = ctx.dir / "passages.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def suggest_golden(docs: list[dict]) -> list[dict]:
    """Golden questions suggested from the documents' own headings (a person corrects them): what the section says,
    from that document, with two of its words; and one question every assistant must refuse."""
    out = []
    for d in docs:
        secs = []
        for p in d["passages"]:
            if p.get("section") and p["section"] not in [s["section"] for s in secs]:
                secs.append(p)
        for p in secs[:2]:
            words = [w for w in ai.terms(p["text"]) if w not in ai.terms(p["section"])][:2]
            out.append({"id": f"g-{len(out) + 1}", "include": True, "question": f"What does {d['title']} say about {p['section'].lower()}?", "expect_doc": d["name"],
                        "expect": ", ".join(words), "origin": "suggested"})
    out.append({"id": f"g-{len(out) + 1}", "include": True, "question": "What will the weather be in Paris tomorrow?", "expect_doc": "none", "expect": "", "origin": "refusal"})
    return out


def _doc_options(ctx: wb.Ctx):
    names = [d["name"] for d in load_docs(ctx)] or [f["name"] for f in ctx.files(ai.DOC_EXT)]
    for k in ("current_docs",):
        names += [d["name"] for d in ctx.get(k) or [] if d["name"] not in names]
    return [("none", "None - it must refuse")] + [(n, n) for n in names]


def _validate_golden(recs: list[dict], ctx: wb.Ctx) -> list[str]:
    probs = [f"Row {i}: write the question" for i, r in enumerate(recs, 1) if r.get("include") and len(str(r.get("question") or "").strip()) < 8]
    if not any(r.get("include") for r in recs):
        probs.append("Keep at least one golden question.")
    return probs


GOLDEN_COLUMNS = [wb.Column("include", "Use", "bool"), wb.Column("question", "Golden question", "longtext"),
                  wb.Column("expect_doc", "Answered by", "select", options=_doc_options), wb.Column("expect", "Words the answer must hold", help="Comma separated; blank: any answer from that document")]
GOLDEN_EDIT = wb.Edit(columns=GOLDEN_COLUMNS, validate=_validate_golden, label="golden question")


def evaluate(ctx: wb.Ctx, cid: str, golden: list[dict], tag: str) -> tuple[list[dict], float | None]:
    """Every golden question asked of the corpus: did the right document come back, does the answer hold the words,
    and is a question the documents cannot answer refused? (gate rows, score in per cent)"""
    checks, ok_n, n = [], 0, 0
    for g in [x for x in golden if x.get("include")]:
        res = ai.answer(cid, g["question"])
        want = [w.strip().lower() for w in str(g.get("expect") or "").split(",") if w.strip()]
        if g.get("expect_doc") == "none":
            good = not res["answered"]
            detail = "refused, as it should" if good else f"answered when it should refuse: {res['answer'][:200]}"
        else:
            docs = [c["doc"] for c in res["citations"]]
            hit = g.get("expect_doc") in docs
            words = all(w in res["answer"].lower() for w in want)
            good = res["answered"] and hit and words
            detail = (res["answer"][:300] + " - " + "; ".join(c["cite"] for c in res["citations"])) if res["answered"] else "not answered: no passage covers the question"
            if res["answered"] and not hit:
                detail += f" (expected a citation of {g.get('expect_doc')})"
            elif res["answered"] and not words:
                detail += f" (missing: {', '.join(w for w in want if w not in res['answer'].lower())})"
        ev = ctx.evidence(f"{tag}: {g['question'][:80]}", {"question": g["question"], "expected": {"document": g.get("expect_doc"), "words": want}, **res,
                                                          "rows": [{"cite": ai.cite(p), "passage": p["id"], "text": p["text"][:400]} for p in res["passages"]]}, kind="answer", ok=good)
        n += 1
        ok_n += 1 if good else 0
        checks.append({"name": g["id"], "label": g["question"][:160], "status": "pass" if good else "fail", "measured": "refused" if not res["answered"] else f"{len(res['citations'])} citation(s)",
                       "expected": "refused" if g.get("expect_doc") == "none" else f"cites {g.get('expect_doc')}", "detail": detail, "evidence": ev})
    score = round(100.0 * ok_n / n, 1) if n else None
    checks.insert(0, {"name": "score", "label": "Golden questions answered as expected", "status": "pass" if score is not None and score >= PASS_SCORE else "fail" if score is not None else "skip",
                      "measured": f"{score:g} %" if score is not None else "-", "expected": f"at least {PASS_SCORE:g} %", "detail": f"{ok_n} of {n} golden question(s)"})
    return checks, score


# ------------------------------------------------------------------ the agent helper: answers worded from the passages, every claim cited

DRAFT = """Read WORK.md, then questions.json in this folder: golden questions, each with the passages Relay found for it
(id, cite, text). Write answers.yaml:

answers:
  g-1:
    answer: "One or two sentences that answer the question, in British English."
    citations: [ch-abc123]

Use only what the passages say: every answer cites at least one of the passage ids given for that question, and
holds no number, name or fact that is not in the passages it cites. When the passages do not answer the question,
write answer: "The documents do not answer this." with citations: []."""


def _draft_prompt(ctx: wb.Ctx) -> str:
    qs = []
    for g in [x for x in ctx.get("golden") or [] if x.get("include")]:
        found = ai.search(ctx.get("draft") or "", g["question"])
        qs.append({"id": g["id"], "question": g["question"], "passages": [{"id": p["id"], "cite": ai.cite(p), "text": p["text"]} for p in found]})
    (ctx.dir / "questions.json").write_text(ai.to_json(qs), encoding="utf-8")
    ctx.put("asked", qs)
    return DRAFT


def _draft_check(ctx: wb.Ctx) -> list[str]:
    import yaml
    p = ctx.dir / "answers.yaml"
    if not p.exists():
        return ["answers.yaml was not written"]
    try:
        y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return [f"answers.yaml does not parse: {str(e).splitlines()[0]}"]
    ans = y.get("answers") if isinstance(y, dict) else None
    if not isinstance(ans, dict):
        return ["answers.yaml needs a mapping `answers:` from question id to {answer, citations}"]
    asked = {q["id"]: q for q in ctx.get("asked") or []}
    out = [f"unknown question id {k}" for k in ans if k not in asked]
    for qid, a in ans.items():
        if qid not in asked or not isinstance(a, dict):
            continue
        given = {x["id"]: x for x in asked[qid]["passages"]}
        cites = [str(c) for c in (a.get("citations") or [])]
        bad = [c for c in cites if c not in given]
        if bad:
            out.append(f"{qid}: cites passages it was not given ({', '.join(bad[:3])})")
        refusal = "do not answer" in str(a.get("answer") or "").lower()
        if not cites and not refusal:
            out.append(f"{qid}: an answer must cite at least one passage")
        out += [f"{qid}: {x}" for x in ai.grounded(str(a.get("answer") or ""), [given[c] for c in cites if c in given])]
    return out


def _draft_after(ctx: wb.Ctx, res: dict) -> dict:
    import yaml
    ans = (yaml.safe_load((ctx.dir / "answers.yaml").read_text(encoding="utf-8")) or {}).get("answers") or {}
    st = ctx.result(ctx.step_id) or {}
    checks = list(((st.get("data") or {}).get("checks")) or [])
    for c in checks:
        a = ans.get(c["name"])
        if isinstance(a, dict):
            c["detail"] = f"Relay's wording (check it): {str(a.get('answer') or '')[:300]} - cites {', '.join(a.get('citations') or []) or 'nothing'}"
    ctx.evidence("Answers worded by Relay", {"answers": ans, "summary": res.get("text") or ""}, kind="agent", ok=True)
    return {"summary": f"Relay worded {len(ans)} answer(s), each citing the passages it was given and holding no number they do not - check them; the scores did not change.",
            "data": {"checks": checks}}


# ------------------------------------------------------------------ Develop

def d_describe(ctx: wb.Ctx) -> dict:
    docs, rows = read_docs(ctx)
    if not docs:
        raise wb.StepFailed("Upload the documents the assistant answers from (PDF with a text layer, Word, PowerPoint, text or Markdown).")
    save_docs(ctx, docs)
    ctx.put("doc_names", [d["name"] for d in docs])
    return {"summary": f"{len(docs)} document(s) read into {sum(len(d['passages']) for d in docs)} passage(s), each with its page or section." + (f" {len(rows) - len(docs)} could not be read." if len(rows) > len(docs) else ""),
            "counts": {"documents": len(docs), "passages": sum(len(d["passages"]) for d in docs)},
            "data": {"columns": ["Document", "Title", "Pages or sections", "Passages", "Status"], "rows": rows}}


def d_shape(ctx: wb.Ctx) -> dict:
    have = ctx.records(ctx.step_id)
    recs = have or suggest_golden(load_docs(ctx))
    return {"summary": f"{len(recs)} golden question(s): what the assistant must answer, from which document, with which words - and one it must refuse. "
                       "Suggested from the documents' headings: correct them, add your own, then confirm the design.",
            "counts": {"golden questions": len(recs)}, "records": recs,
            "data": {"columns": ["Use", "Golden question", "Answered by", "Words"], "rows": [["yes" if r.get("include") else "no", r["question"], r.get("expect_doc"), r.get("expect")] for r in recs]}}


def d_build(ctx: wb.Ctx) -> dict:
    docs = load_docs(ctx)
    draft = f"draft-{ctx.id}"
    n = ai.index(draft, docs)
    ctx.put("draft", draft)
    ctx.put("golden", ctx.records("shape"))
    ctx.output("corpus.json", ai.to_json([{k: d[k] for k in ("name", "title", "fingerprint")} | {"passages": len(d["passages"])} for d in docs]), label="The corpus (documents and passages)")
    return {"summary": f"{n} passage(s) of {len(docs)} document(s) indexed for full-text search - a draft only this work item uses until it is approved.",
            "counts": {"passages": n, "documents": len(docs)}, "data": {"columns": ["Document", "Passages"], "rows": [[d["name"], len(d["passages"])] for d in docs]}}


def d_prove(ctx: wb.Ctx) -> dict:
    checks, score = evaluate(ctx, ctx.get("draft") or "", ctx.get("golden") or [], "Golden question")
    ctx.put("score", score)
    return {"summary": f"{checks[0]['detail']} as expected ({score:g} %). Each answer is made of sentences from the documents, with its citation; open a row's evidence for the passages found."
            if score is not None else "No golden question to ask.", "counts": {"score %": score or 0}, "data": {"checks": checks},
            "items": [f"{c['label']}: {c['status']}" for c in checks[1:7]]}


def d_ship(ctx: wb.Ctx) -> dict:
    docs = load_docs(ctx)
    team = (db.one("SELECT name FROM teams WHERE id = ?", ((db.project(ctx.id) or {}).get("team_id"),)) or {}).get("name") or "the item's team"
    approver = db.user(ctx.st.get("approver") or "") or {}
    return {"summary": f"Go live: an assistant over {len(docs)} document(s) for {team}, scoring {ctx.get('score')} % on its golden questions.",
            "data": {"items": [{"title": "Documents", "detail": ", ".join(d["title"] for d in docs)[:600]},
                               {"title": "Who may ask", "detail": f"the people of {team} (and admins); nobody else, and never another workspace"},
                               {"title": "Then", "detail": "a Run item re-scores the golden questions on a schedule; a drop waits for a person"},
                               {"title": "Named approval", "detail": approver.get("name") or "the owner of this work item"}]}}


def _run_item(ctx: wb.Ctx, c: dict, cad: dict) -> str:
    rid = c.get("run_item")
    if rid and db.one("SELECT 1 FROM wb_items WHERE id = ? AND closed IS NULL", (rid,)):
        return rid
    p = db.project(ctx.id) or {}
    item = wb.create(MODULE, "run", f"Run: {ctx.title}"[:160], who=ctx.owner, brief=f"Scheduled evaluation of the assistant \"{c['name']}\", published from {ctx.id}.",
                     scope={"corpus": c["id"], "schedule": cad}, approver=ctx.st.get("approver"), visibility=p.get("visibility") or "private", team_id=p.get("team_id"), parent=ctx.id)
    db.run("UPDATE assist_corpora SET run_item = ? WHERE id = ?", (item["id"], c["id"]))
    return item["id"]


def d_run(ctx: wb.Ctx) -> dict:
    c = publish(ctx, load_docs(ctx), ctx.get("golden") or [], ctx.get("score"), ctx.get("corpus"), "go-live from Develop")
    ai.drop(ctx.get("draft") or "")
    ctx.put("corpus", c["id"])
    job = ctx.lineage_node("job", "Relay assistants", f"Assistant: {c['name']}", properties={"corpus": c["id"], "version": c["version"]})
    for d in c["docs"]:
        ctx.lineage_edge(ctx.lineage_node("table", ctx.id, d["name"], label=f"{d['name']} (document)", own=False), job, "reads", {"passages": d["passages"]})
    cad = wb.check_schedule(ctx.scope.get("cadence") or {"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})
    rid = _run_item(ctx, c, cad)
    return {"summary": f"The assistant \"{c['name']}\" (version {c['version']}) is live for its team; the Run item re-scores it {wb.schedule_text(cad).lower()}.",
            "counts": {"version": c["version"], "documents": len(c["docs"])},
            "data": {"href": f"#/m/{MODULE}/i/{rid}", "label": "Open the Run item", "text": f"{len(c['docs'])} document(s) - {ctx.get('score')} % on {len([g for g in c['golden'] if g.get('include')])} golden question(s)"}}


# ------------------------------------------------------------------ Assess

def a_connect(ctx: wb.Ctx) -> dict:
    rows = DOCS.test(ctx)
    if not rows:
        raise wb.StepFailed("Upload the documents to assess (PDF, Word, PowerPoint, text or Markdown).")
    return {"summary": f"{len(rows)} document(s) uploaded - read-only copies.", "counts": {"documents": len(rows)},
            "data": {"columns": ["Document", "Kind", "Status", "What Relay sees", "Access"], "rows": [[r["source"], r["kind"], "answered", r["sees"], r["scope"]] for r in rows]}}


def a_inventory(ctx: wb.Ctx) -> dict:
    docs, rows = read_docs(ctx)
    save_docs(ctx, docs)
    recs = [{"id": f"d-{i}", "include": True, "name": r[0], "title": r[1], "passages": r[3], "status": r[4]} for i, r in enumerate(rows, 1)]
    return {"summary": f"{len(rows)} document(s): {len(docs)} read into passages. Untick what the assistant should not answer from.", "counts": {"documents": len(rows), "read": len(docs)},
            "records": recs, "data": {"columns": ["Document", "Title", "Passages", "Status"], "rows": [[r["name"], r["title"], r["passages"], r["status"]] for r in recs]}}


def a_health(ctx: wb.Ctx) -> dict:
    keep = {r["name"] for r in ctx.records("inventory") if r.get("include")}
    docs = [d for d in load_docs(ctx) if d["name"] in keep]
    seen, checks, findings = {}, [], []
    for d in docs:
        words = sum(len(p["text"].split()) for p in d["passages"])
        dup = seen.get(d["fingerprint"])
        seen.setdefault(d["fingerprint"], d["name"])
        issues = ([("the same text as " + dup, "high")] if dup else []) + ([(f"only {words} words: too thin to answer much", "medium")] if words < 120 else []) \
            + ([("no headings or pages to cite: answers cannot say where in the document", "low")] if not any(p.get("page") or p.get("section") for p in d["passages"]) else [])
        for i, (txt, sev) in enumerate(issues):
            findings.append({"id": f"{d['name']}-{i}", "document": d["name"], "issue": txt, "severity": sev, "decision": "keep"})
        checks.append({"name": d["name"], "label": f"{d['title']} ({d['name']})", "status": "fail" if dup else "warn" if issues else "pass", "measured": f"{len(d['passages'])} passages - {words} words",
                       "expected": "", "detail": "; ".join(t for t, _ in issues) or "readable, citable, not a duplicate"})
    for r in ctx.records("inventory"):
        if r.get("include") and r["status"] != "read":
            findings.append({"id": f"{r['name']}-unread", "document": r["name"], "issue": r["status"], "severity": "high", "decision": "keep"})
            checks.append({"name": r["name"], "label": r["name"], "status": "error", "measured": "", "expected": "", "detail": r["status"]})
    ctx.put("findings", findings)
    ctx.put("docs_n", len(docs))
    return {"summary": f"{len(docs)} document(s) checked: {len(findings)} issue(s).", "counts": {"documents": len(docs), "issues": len(findings)}, "data": {"checks": checks}}


FIND_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep"), ("ignore", "Ignore"))), wb.Column("document", "Document", readonly=True),
                             wb.Column("issue", "Issue", readonly=True), wb.Column("severity", "Severity", readonly=True)], add=False, remove=False, label="finding")


def a_findings(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**f, "decision": (have.get(f["id"]) or {}).get("decision") or "keep"} for f in ctx.get("findings") or []]
    return {"summary": f"{len(recs)} finding(s): keep what matters, ignore what does not." if recs else "No issue: the documents are readable, citable and not duplicated.",
            "counts": {"findings": len(recs)}, "records": recs, "data": {"columns": ["Document", "Issue", "Severity"], "rows": [[r["document"], r["issue"], r["severity"]] for r in recs]}}


def a_estimate(ctx: wb.Ctx) -> dict:
    n = ctx.get("docs_n") or 0
    kept = [f for f in ctx.records("findings") if f.get("decision") != "ignore"]
    b = registry.brand()
    rate, cur = float(b.get("hourly_rate") or 0), b.get("currency") or ""
    h = (n * MINUTES["read and tidy a document"] * (1 if kept else 0.5) + max(5, 2 * n) * MINUTES["write a golden question"] + MINUTES["review the answers"]) / 60
    note = "Assumptions: " + "; ".join(f"{v} min to {k}" for k, v in MINUTES.items()) + "; two golden questions per document, at least five." + ("" if rate else " Set an hourly rate under Admin > Branding to see the cost.")
    items = [{"title": "Wave 1 - the assistant", "detail": f"{n} document(s), {len(kept)} issue(s) to fix first, {max(5, 2 * n)} golden question(s) to write", "effort": f"{h:.1f} h" + (f" - {cur}{rate * h:,.0f}" if rate else "")}]
    ctx.output("assessment.md", f"# Assistant assessment: {ctx.title}\n\n{items[0]['detail']}\n\nEffort: {items[0]['effort']}\n\n{note}\n", label="Assessment (Markdown)")
    return {"summary": f"About {h:.1f} h of a person's time to put this assistant live.", "counts": {"hours": round(h, 1)}, "data": {"items": items, "total": f"{h:.1f} h", "note": note}}


# ------------------------------------------------------------------ Change

def _corpus_or_fail(ctx: wb.Ctx) -> dict:
    c = corpus(ctx.scope.get("corpus") or "", db.user(ctx.owner or "") or {})
    if not c:
        raise wb.StepFailed("The assistant this work item changes is not one its owner may use any more.")
    return c


def c_request(ctx: wb.Ctx) -> dict:
    c = _corpus_or_fail(ctx)
    ctx.put("corpus", c["id"])
    ctx.put("version", c["version"])
    ctx.put("golden_now", c["golden"])
    item = c["item"]
    st = wb._load(item) if item else None
    cur = json.loads((wb.folder(item) / "passages.json").read_text(encoding="utf-8")) if item and (wb.folder(item) / "passages.json").exists() else []
    ctx.put("current_docs", [{**d, "from": item} for d in cur if d["name"] in {x["name"] for x in c["docs"]}])
    new, _ = read_docs(ctx)
    ctx.put("new_docs", new)
    return {"summary": f"Change to \"{c['name']}\" (version {c['version']}, {len(c['docs'])} documents)" + (f"; {len(new)} new document(s) uploaded with the request." if new else "."),
            "counts": {"documents": len(c["docs"]), "new": len(new)}, "data": {"text": ctx.brief or "(no request text)"}} if st is not None or not item else {"summary": "", "data": {"text": ""}}


def c_diagnose(ctx: wb.Ctx) -> dict:
    checks, score = evaluate(ctx, ctx.get("corpus") or "", ctx.get("golden_now") or [], "Today")
    ctx.put("before", score)
    return {"summary": f"Today: {checks[0]['detail']} as expected ({score:g} %)." if score is not None else "No golden question yet.", "counts": {"score %": score or 0}, "data": {"checks": checks}}


def c_fix(ctx: wb.Ctx) -> dict:
    recs = ctx.records(ctx.step_id) or [dict(g) for g in ctx.get("golden_now") or []]
    docs = [d["name"] for d in ctx.get("current_docs") or []] + [d["name"] for d in ctx.get("new_docs") or []]
    return {"summary": f"Edit the golden questions (add questions the new documents answer). The assistant will hold {len(docs)} document(s): " + ", ".join(docs)[:400] + ".",
            "records": recs, "data": {"columns": ["Use", "Golden question", "Answered by"], "rows": [["yes" if r.get("include") else "no", r["question"], r.get("expect_doc")] for r in recs]}}


def c_prove(ctx: wb.Ctx) -> dict:
    docs = (ctx.get("current_docs") or []) + (ctx.get("new_docs") or [])
    draft = f"draft-{ctx.id}"
    ai.index(draft, docs)
    ctx.put("draft", draft)
    golden = ctx.records("fix")
    checks, score = evaluate(ctx, draft, golden, "Changed")
    before = ctx.get("before")
    checks.insert(1, {"name": "vs", "label": "Against today's assistant", "status": "warn" if before is not None and score is not None and score < before else "pass",
                      "measured": f"{score:g} %" if score is not None else "-", "expected": f"today {before:g} %" if before is not None else "", "detail": "lower than today" if before is not None and score is not None and score < before else "as good or better"})
    ctx.put("score", score)
    ctx.put("golden", golden)
    save_docs(ctx, docs)
    return {"summary": f"The changed assistant: {score:g} % on its golden questions (today {before:g} %)." if score is not None and before is not None else "Proven.", "counts": {"score %": score or 0},
            "data": {"checks": checks}}


def c_approve(ctx: wb.Ctx) -> dict:
    return {"summary": f"Release version {(ctx.get('version') or 0) + 1}: {len(load_docs(ctx))} document(s), {ctx.get('score')} % on the golden questions.",
            "data": {"items": [{"title": d["title"], "detail": d["name"]} for d in load_docs(ctx)]}}


def c_learn(ctx: wb.Ctx) -> dict:
    c = publish(ctx, load_docs(ctx), ctx.get("golden") or [], ctx.get("score"), ctx.get("corpus"), (ctx.brief or "")[:200])
    ai.drop(ctx.get("draft") or "")
    return {"summary": f"Version {c['version']} of \"{c['name']}\" is live; the Run item re-scores it from its next round.", "counts": {"version": c["version"]},
            "data": {"href": f"#/m/{MODULE}/i/{c['run_item']}" if c.get("run_item") else f"#/m/{MODULE}/run", "label": "Open the Run item" if c.get("run_item") else "Run & support",
                     "text": f"{len(c['docs'])} document(s)"}}


# ------------------------------------------------------------------ Migrate (a FAQ / another assistant's Q&A export)

def m_discover(ctx: wb.Ctx) -> dict:
    qa = []
    for f in ctx.files((".csv", ".xlsx")):
        path = ctx.dir / "data" / (f.get("table") or f["name"])
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8", errors="replace"))))
        for i, r in enumerate(rows, 1):
            low = {k.lower().strip(): v for k, v in r.items() if k}
            if low.get("question") and low.get("answer"):
                qa.append({"id": f"qa-{len(qa) + 1}", "question": low["question"].strip(), "answer": low["answer"].strip(), "source": (low.get("source") or "").strip()})
    docs, rows = read_docs(ctx)
    if not qa:
        raise wb.StepFailed("Upload the question-and-answer export (CSV with question and answer columns) next to the documents.")
    if not docs:
        raise wb.StepFailed("Upload the documents the answers come from.")
    save_docs(ctx, docs)
    ctx.put("qa", qa)
    return {"summary": f"{len(qa)} question(s) and answer(s) in the export; {len(docs)} document(s) read.", "counts": {"questions": len(qa), "documents": len(docs)},
            "data": {"columns": ["Question", "Old answer", "Source"], "rows": [[q["question"], q["answer"][:160], q["source"]] for q in qa]}}


def m_decide(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    names = {d["name"].lower(): d["name"] for d in load_docs(ctx)}
    recs = [{**q, "decision": (have.get(q["id"]) or {}).get("decision") or "keep", "expect_doc": names.get(q["source"].lower(), next(iter(names.values()), "none"))} for q in ctx.get("qa") or []]
    return {"summary": f"{len(recs)} question(s): keep each as a golden question (its old answer is compared with Relay's), or retire it.", "records": recs,
            "data": {"columns": ["Question", "Old answer", "Decision"], "rows": [[r["question"], r["answer"][:160], r["decision"]] for r in recs]}}


DECIDE_EDIT = wb.Edit(columns=[wb.Column("decision", "Decision", "select", options=(("keep", "Keep as a golden question"), ("retire", "Retire"))),
                               wb.Column("question", "Question", readonly=True), wb.Column("answer", "Old answer", readonly=True)], add=False, remove=False, label="question")


def m_convert(ctx: wb.Ctx) -> dict:
    docs = load_docs(ctx)
    draft = f"draft-{ctx.id}"
    n = ai.index(draft, docs)
    ctx.put("draft", draft)
    golden = [{"id": r["id"], "include": True, "question": r["question"], "expect_doc": r["expect_doc"], "expect": ", ".join(ai.terms(r["answer"])[:2]), "old": r["answer"], "origin": "migrated"}
              for r in ctx.records("decide") if r.get("decision") == "keep"]
    ctx.put("golden", golden)
    return {"summary": f"{n} passage(s) indexed; {len(golden)} question(s) kept as golden questions, each expecting two words of its old answer.", "counts": {"passages": n, "golden": len(golden)},
            "data": {"columns": ["Golden question", "Answered by", "Words"], "rows": [[g["question"], g["expect_doc"], g["expect"]] for g in golden]}}


def m_prove(ctx: wb.Ctx) -> dict:
    checks, score = evaluate(ctx, ctx.get("draft") or "", ctx.get("golden") or [], "Side by side")
    olds = {g["id"]: g.get("old") for g in ctx.get("golden") or []}
    for c in checks[1:]:
        if olds.get(c["name"]):
            c["detail"] = f"Old: {olds[c['name']][:160]} - Relay: {c['detail']}"
    ctx.put("score", score)
    return {"summary": f"Old answers and Relay's cited answers side by side: {score:g} % as expected." if score is not None else "Nothing to compare.", "counts": {"score %": score or 0},
            "data": {"checks": checks}}


def m_handover(ctx: wb.Ctx) -> dict:
    return {"summary": f"Sign off the move: {len(load_docs(ctx))} document(s), {len(ctx.get('golden') or [])} golden question(s), {ctx.get('score')} % as expected.",
            "data": {"items": [{"title": g["question"][:120], "detail": f"answered by {g['expect_doc']}"} for g in ctx.get("golden") or []]}}


# ------------------------------------------------------------------ Run & support

def r_watch(ctx: wb.Ctx) -> dict:
    c = _corpus_or_fail(ctx)
    ctx.put("corpus", c["id"])
    checks, score = evaluate(ctx, c["id"], c["golden"], f"Run {len(ctx.st.get('rounds') or []) + 1}")
    last = next((s["score"] for s in reversed(c["scores"]) if s.get("score") is not None), None)
    scores = (c["scores"] + [{"when": time.time(), "score": score, "version": c["version"], "item": ctx.id, "run": True}])[-60:]
    db.run("UPDATE assist_corpora SET scores = ?, updated = ? WHERE id = ?", (json.dumps(scores), time.time(), c["id"]))
    issues = [{"id": x["name"], "question": x["label"], "detail": x["detail"], "action": "keep", "note": ""} for x in checks[1:] if x["status"] == "fail"]
    ctx.put("issues", issues if (score is not None and (score < PASS_SCORE or (last is not None and score < last - 5))) else [])
    ctx.put("score", score)
    ctx.put("last", last)
    return {"summary": f"Version {c['version']}: {score:g} % of its golden questions as expected (last time {last:g} %)." if score is not None and last is not None else f"{score} %",
            "counts": {"score %": score or 0, "failing": len(issues)}, "data": {"checks": checks}}


def r_alert(ctx: wb.Ctx) -> dict:
    iss = ctx.get("issues") or []
    if not iss:
        return {"summary": "The assistant answers its golden questions as before: nothing to alert.", "next": "report", "counts": {"issues": 0}}
    return {"summary": f"The score fell to {ctx.get('score')} % (last time {ctx.get('last')} %): {len(iss)} golden question(s) no longer answered as expected.",
            "counts": {"issues": len(iss)}, "items": [i["question"] for i in iss[:6]], "data": {"columns": ["Golden question", "What happened"], "rows": [[i["question"], i["detail"]] for i in iss]}}


def r_fix(ctx: wb.Ctx) -> dict:
    have = {r["id"]: r for r in ctx.records(ctx.step_id)}
    recs = [{**i, **({k: have[i["id"]][k] for k in ("action", "note") if k in have[i["id"]]} if i["id"] in have else {})} for i in ctx.get("issues") or []]
    return {"summary": f"{len(recs)} golden question(s) to look at: keep watching, or raise a ticket for the document's owner. Nothing goes out until you confirm.", "records": recs,
            "data": {"columns": ["Golden question", "What happened", "Action"], "rows": [[r["question"], r["detail"], r["action"]] for r in recs]}}


FIX_EDIT = wb.Edit(columns=[wb.Column("action", "Action", "select", options=(("keep", "Keep watching"), ("ticket", "Raise a ticket"))), wb.Column("note", "Note", "longtext"),
                            wb.Column("question", "Golden question", readonly=True), wb.Column("detail", "What happened", readonly=True)], add=False, remove=False, label="question")


def r_approve(ctx: wb.Ctx) -> dict:
    from . import anomaly
    rows = []
    for r in ctx.records("fix"):
        if r["action"] == "ticket":
            h = anomaly.service_desk_ticket(ctx, f"Assistant no longer answers: {r['question'][:120]}", f"{r['detail']}\n\n{r.get('note') or ''}\nWork item: {wb.route_of(ctx.st)}", "P3",
                                            about=r["question"], origin=f"assist:{ctx.id}:{r['id']}")
            rows.append([r["question"], "Ticket", h.get("status")])
        else:
            rows.append([r["question"], "Keep watching", "recorded"])
    return {"summary": f"{sum(1 for r in rows if r[1] == 'Ticket')} ticket(s), {sum(1 for r in rows if r[1] != 'Ticket')} kept - as you approved.", "data": {"columns": ["Golden question", "Decision", "Status"], "rows": rows}}


def r_report(ctx: wb.Ctx) -> dict:
    c = corpus(ctx.get("corpus") or "") or {"scores": []}
    rows = [[time.strftime("%d %b %Y %H:%M", time.gmtime(s["when"])), s.get("version"), s.get("score")] for s in c["scores"][-12:]]
    ctx.output(f"report-{time.strftime('%Y%m%d-%H%M', time.gmtime())}.md", "# Assistant scores over time\n\n" + "".join(f"- {r[0]}: version {r[1]}, {r[2]} %\n" for r in rows), label="Scores over time (Markdown)")
    return {"summary": f"{ctx.get('score')} % this run; {len(rows)} score(s) over time.", "counts": {"score %": ctx.get("score") or 0}, "data": {"columns": ["When", "Version", "Score %"], "rows": rows}}


# ------------------------------------------------------------------ the module page and the ask API

def _cards(u: dict) -> list[dict]:
    rows = []
    for c in corpora(u):
        team = (db.one("SELECT name FROM teams WHERE id = ?", (c.get("team_id"),)) or {}).get("name") or "-"
        last = next((s["score"] for s in reversed(c["scores"]) if s.get("score") is not None), None)
        asked = (db.one("SELECT COUNT(*) AS n FROM assist_questions WHERE corpus = ?", (c["id"],)) or {}).get("n") or 0
        rows.append([c["name"], f"v{c['version']}", team, len(c["docs"]), f"{last:g} %" if last is not None else "-", asked, f"#/m/{MODULE}/i/{c['run_item']}" if c.get("run_item") else ""])
    return [{"title": "Live assistants", "columns": ["Assistant", "Version", "Team", "Documents", "Golden score", "Questions asked", "Run item"], "rows": rows,
             "empty": "No assistant is live yet: a Develop item's Run step publishes one after its named approval."}]


class Ask(BaseModel):
    question: str


router = APIRouter()


@router.get("/api/m/assist/corpora")
def api_corpora():
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    return {"corpora": [{k: c[k] for k in ("id", "name", "version", "team_id")} | {"documents": len(c["docs"])} for c in corpora(u)]}


@router.post("/api/m/assist/corpora/{cid}/ask")
def api_ask(cid: str, body: Ask):
    """Ask an assistant: an answer made of the documents' own sentences, each cited - or a plain refusal."""
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    c = corpus(cid, u)
    if not c:
        raise HTTPException(404, "No such assistant.")
    q = (body.question or "").strip()[:1000]
    if len(q) < 3:
        raise HTTPException(400, "Ask a question.")
    res = ai.answer(cid, q)
    db.run("INSERT INTO assist_questions (id, corpus, asked_by, question, answered, answer, citations, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           ("aq-" + _secrets.token_hex(5), cid, u["id"], q, 1 if res["answered"] else 0, res["answer"][:4000], ai.to_json(res["citations"]), time.time()))
    db.audit("assist.ask", cid, {"answered": res["answered"], "citations": len(res["citations"])}, u["id"])
    return {"answered": res["answered"], "answer": res["answer"], "citations": res["citations"]}


GUIDE = """# Document & knowledge assistants - the work item

This folder is one work item of Relay's knowledge assistants. Answers come from the documents in data/, read into
passages (passages.json) with their page or section. When you are asked to word answers, questions.json holds each
golden question with the passages found for it: use only what those passages say, cite the passage ids, and never
write a number, a name or a fact that is not in a passage you cite. If the passages do not answer, say so."""

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, lineage="each document an assistant answers from, and the assistant as a job (system \"Relay assistants\")",
    platforms=PLATFORMS, schemas={"golden": GOLDEN_COLUMNS}, cards=_cards, router=router,
    work={
        "assess": wb.Work(title="See what your documents hold and where an assistant would be weak", platforms=("docs",), steps={
            "Connect": wb.Step(kind="platform", run=a_connect, agent="Reader", text="The documents you upload are opened - read-only copies in this work item"),
            "Inventory": wb.Step(kind="platform", run=a_inventory, agent="Reader", text="Every document read into passages with its pages or sections - you untick what is out of scope",
                                 edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("name", "Document", readonly=True), wb.Column("title", "Title", readonly=True),
                                                       wb.Column("status", "Status", readonly=True)], add=False, remove=False, label="document")),
            "Health": wb.Step(kind="proof", run=a_health, view="gates", agent="Checker", text="Unreadable, thin, duplicated or uncitable documents found - measured, not guessed"),
            "Findings": wb.Step(kind="person", run=a_findings, edit=FIND_EDIT, text="You keep or ignore each finding"),
            "Estimate": wb.Step(kind="deterministic", run=a_estimate, view="plan", agent="Estimator", text="The time a person needs to put the assistant live")}),
        "develop": wb.Work(title="An assistant over your documents that cites every answer", platforms=("docs",), steps={
            "Describe": wb.Step(kind="platform", run=d_describe, agent="Reader", text="The documents read into passages, each with its page or section"),
            "Shape": wb.Step(kind="deterministic", run=d_shape, agent="Librarian", edit=GOLDEN_EDIT, confirm="the golden questions - what it must answer, from which document, and what it must refuse",
                             text="Golden questions suggested from the documents' headings - you correct them, add your own and one it must refuse"),
            "Build": wb.Step(kind="deterministic", run=d_build, agent="Indexer", text="The passages indexed for full-text search, as a draft only this work item uses"),
            "Prove": wb.Step(kind="proof", run=d_prove, view="gates", agent="Evaluator", back_to="shape", text="Every golden question asked: the right document cited, the right words, a refusal where the documents are silent",
                             actions={"wording": wb.Action(label="Ask Relay to word the answers", kind="agent", prompt=_draft_prompt, check=_draft_check, after=_draft_after, agent="Answer writer",
                                                           help="The agent words each answer from the passages found; every sentence must cite them, and the scores do not change.")}),
            "Ship": wb.Step(kind="person", run=d_ship, view="plan", approver=True, text="The named approver confirms the assistant goes live for its team"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The assistant goes live for its team; a Run item re-scores it on a schedule")},
            fields=[wb.Field("cadence", "Once live, re-score it", "cadence", default={"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})]),
        "change": wb.Work(title="Add or change documents, re-proven before release", needs_source=False, platforms=("docs",), steps={
            "Request": wb.Step(kind="deterministic", run=c_request, view="text", agent="Librarian", text="The change in plain words, the live assistant, and any new documents uploaded with it"),
            "Diagnose": wb.Step(kind="proof", run=c_diagnose, view="gates", agent="Evaluator", text="Today's golden questions asked of today's assistant"),
            "Fix": wb.Step(kind="person", run=c_fix, edit=GOLDEN_EDIT, confirm="the golden questions for the changed assistant", text="You edit the golden questions; the new documents join the assistant"),
            "Prove": wb.Step(kind="proof", run=c_prove, view="gates", agent="Evaluator", back_to="fix", text="The changed assistant indexed as a draft and scored against today's"),
            "Approve": wb.Step(kind="person", run=c_approve, view="plan", approver=True, text="The named approver releases the new version"),
            "Learn": wb.Step(kind="deterministic", run=c_learn, view="link", agent="Publisher", text="The new version is published; its score is kept with the others")},
            fields=[wb.Field("corpus", "Assistant to change", "select", options=corpus_options, required=True)]),
        "migrate": wb.Work(title="Move a FAQ or another assistant to Relay, answers side by side", platforms=("docs", "files"), steps={
            "Discover": wb.Step(kind="platform", run=m_discover, agent="Reader", text="The question-and-answer export and the documents behind it"),
            "Decide": wb.Step(kind="deterministic", run=m_decide, agent="Librarian", edit=DECIDE_EDIT, text="Keep each question as a golden question, or retire it"),
            "Convert": wb.Step(kind="deterministic", run=m_convert, agent="Indexer", text="The documents indexed; the kept questions become golden questions"),
            "Prove": wb.Step(kind="proof", run=m_prove, view="gates", agent="Evaluator", text="Old answers and Relay's cited answers side by side"),
            "Hand over": wb.Step(kind="person", run=m_handover, view="plan", approver=True, text="The named approver signs off the move"),
            "Run": wb.Step(kind="deterministic", run=d_run, view="link", agent="Publisher", text="The assistant goes live with a Run item")},
            fields=[wb.Field("cadence", "Once live, re-score it", "cadence", default={"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})]),
        "run": wb.Work(title="Re-score a live assistant on a schedule; a drop waits for a person", needs_source=False, sources=False, platforms=("docs",), steps={
            "Watch": wb.Step(kind="proof", run=r_watch, view="gates", agent="Evaluator", text="The golden questions asked again; the score kept with the ones before it"),
            "Alert": wb.Step(kind="deterministic", run=r_alert, agent="Triage", text="A drop in the score, with the questions it no longer answers as expected"),
            "Fix": wb.Step(kind="deterministic", run=r_fix, agent="Triage", edit=FIX_EDIT, text="Relay proposes what happens to each - you confirm"),
            "Approve": wb.Step(kind="platform", run=r_approve, agent="Dispatcher", text="What you approved goes out: a ticket through the service desk's own approval"),
            "Report": wb.Step(kind="deterministic", run=r_report, agent="Reporter", confirm_if=lambda ctx, out: bool(ctx.get("issues")), text="Scores over time; you confirm it when the score fell")},
            fields=[wb.Field("corpus", "Assistant to watch", "select", options=corpus_options, required=True), wb.Field("schedule", "Re-score it", "cadence", default={"every": "week", "at": "06:00", "weekday": 0, "tz": "UTC"})]),
    }))
