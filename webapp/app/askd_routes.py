"""Ask D endpoints (platform plan, phase 5). Conversations are personal; the dashboard scope needs view access to
that dashboard (checked in askd.scope_sources); sending an answer to a dashboard needs edit access to it."""
import base64

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from . import askd, auth, connectors, db, instances, orgs, store

router = APIRouter()


def _u() -> dict:
    return auth.current.get()


class Ask(BaseModel):
    question: str
    scope: dict = {"kind": "team"}
    thread_id: str | None = None
    model: str | None = None              # a model id from the person's catalog; empty = Ask D's default


def _no_cost(body: dict) -> dict:
    """D2D Relay: an answer without its AI cost and tokens (the conversation's total is all a person sees)."""
    return {k: v for k, v in body.items() if k != "usage"} if isinstance(body, dict) else body


def _answered(tid: str | None, uid: str) -> int:
    """How many of this person's questions in the conversation have an answer (0 for a new conversation)."""
    if not tid:
        return 0
    return db.one("SELECT count(*) AS n FROM askd_messages m JOIN askd_threads t ON t.id = m.thread_id "
                  "WHERE t.id = ? AND t.user_id = ? AND m.role = 'assistant'", (tid, uid))["n"]


def _credits(tid: str | None, uid: str) -> dict:
    """D2D Relay: a conversation's credits: what it used, and the questions left before the next charge."""
    n, per, block = _answered(tid, uid), orgs.COST["ask"], orgs.ASK_QUESTIONS
    return {"answered": n, "used": -(-n // block) * per, "left": (-n) % block, "per": per, "questions": block}


@router.post("/api/askd/ask")
async def ask(body: Ask):
    if body.scope.get("kind") not in ("dashboard", "team", "org"):
        raise HTTPException(400, "Scope must be dashboard, team or org.")
    if not body.question.strip():
        raise HTTPException(400, "Ask a question.")
    u = _u()
    cid = None
    # D2D Relay: Ask Relay's credits pay for up to ASK_QUESTIONS answers in one conversation: its 1st, 6th, 11th ...
    # question is charged (NoCredits -> 402), and given back when that question gets no answer
    if _answered(body.thread_id, u["id"]) % orgs.ASK_QUESTIONS == 0:
        cid = orgs.charge("ask", note='"' + body.question.strip()[:60] + '"')
    try:
        r = _no_cost(await askd.ask(u, body.question, body.scope, body.thread_id, body.model))
    except (askd.AskError, connectors.ConnectorError, instances.InstanceError) as e:
        orgs.refund(cid, "The question was not answered.")
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        orgs.refund(cid, "The question was not answered.")
        raise HTTPException(503, f"Could not reach the AI service ({e.__class__.__name__}).")
    except BaseException:
        orgs.refund(cid, "The question was not answered.")
        raise
    return {**r, "credits": _credits(r.get("thread_id"), u["id"])}


@router.get("/api/askd/models")
def ask_models():
    m = askd.models_for(_u()["id"])
    return {"default": m["default"], "models": m["models"]}


@router.get("/api/askd/threads")
def my_threads():
    return {"threads": askd.threads(_u()["id"])}


@router.get("/api/askd/threads/{tid}")
def one_thread(tid: str):
    try:
        t = askd.thread(tid, _u()["id"])
    except askd.AskError:
        raise HTTPException(404, "Unknown conversation")
    t["messages"] = [{**m, "body": _no_cost(m.get("body"))} for m in t["messages"]]
    return t


@router.get("/api/askd/options")
def scope_options():
    """What the person can ask about: dashboards they can open, their connections with configured tables."""
    u = _u()
    ps = store.dashboards()
    access = auth.access_map(u, [p["id"] for p in ps])
    return {"dashboards": [{"id": p["id"], "name": p["name"]} for p in ps if p["id"] in access],
            "connections": [{"id": c["id"], "name": c["name"], "kind": c["kind"], "tables": len(c["tables"])} for c in connectors.mine(u["id"])],
            "teams": u.get("teams", []), "viewer": not auth.is_dev(u),
            "suggestions": _suggestions([p for p in ps if p["id"] in access]), "brand_colors": _brand_colors()}


def _kpi_names(pid: str) -> list[str]:
    import yaml
    try:
        plan = yaml.safe_load((store.project_dir(pid) / "plan.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return []
    return [str(k.get("label") or k.get("name")) for k in (plan.get("kpis") or []) if isinstance(k, dict) and (k.get("label") or k.get("name"))]


def _suggestions(ps: list[dict]) -> list[str]:
    """D2D Relay: starter questions built from the person's own dashboards' KPIs (most recent dashboards first)."""
    names: list[str] = []
    for p in sorted(ps, key=lambda x: x.get("created") or 0, reverse=True)[:3]:
        for n in _kpi_names(p["id"]):
            if n not in names:
                names.append(n)
    if not names:
        return ["What are the main numbers in my data?", "How did things change month by month?", "What stands out as unusual?"]
    import re
    base = [n for n in names if not re.search(r"last year|vs|prior|previous|target|goal|ly|change|growth|%|·", n, re.I)] or names
    k = base + base[:1] * 4
    return [f"How has {k[0]} changed month by month?", f"What is driving {k[1]} up or down?",
            f"Where is {k[2]} weakest, and why?", f"How does {k[0]} compare with last year?"]


def _brand_colors() -> list[str]:
    from . import branding
    s = branding.chosen_style()
    return (s or {}).get("colors") or []


@router.get("/api/askd/costs")
def ai_costs(thread: str = ""):
    """D2D Relay: the credits one conversation used and the questions left in them (its AI cost stays in the usage
    table on the server; people pay in credits)."""
    return _credits(thread or None, _u()["id"])


@router.get("/api/projects/{pid}/askd-context")
def dashboard_context(pid: str):
    """Pages and report filters (with their values) for the dashboard panel."""
    defn = askd._project_defn(pid)                     # noqa: SLF001
    filters = []
    try:
        con, tables = askd._extract_engine([pid], False)   # noqa: SLF001
        for f in defn.get("filters") or []:
            field = str(f.get("field", ""))
            if "[" not in field:
                continue
            t, c = field.split("[", 1)
            t, c = t.strip().strip("'"), c.rstrip("]")
            try:
                vals = [r[0] for r in con.execute(f'SELECT DISTINCT "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL ORDER BY 1 LIMIT 60').fetchall()]
            except Exception:  # noqa: BLE001
                vals = []
            filters.append({"field": field, "label": f.get("label") or c, "values": [str(v) for v in vals]})
    except Exception:  # noqa: BLE001 - no data yet
        pass
    return {"pages": [p.get("name") for p in defn.get("pages") or []], "filters": filters,
            "measures": [m["name"] for m in defn.get("measures") or []]}


class Feedback(BaseModel):
    rating: int
    corrected_sql: str | None = None
    comment: str | None = None


@router.post("/api/askd/messages/{mid}/feedback")
def give_feedback(mid: str, body: Feedback):
    try:
        askd.feedback(mid, _u(), body.rating, body.corrected_sql, body.comment)
    except askd.AskError:
        raise HTTPException(404, "Unknown answer")
    return {"ok": True}


@router.post("/api/askd/messages/{mid}/snapshot")
async def snapshot(mid: str):
    """A PNG of the answer, drawn in the agent's headless browser."""
    try:
        body, meta = askd.message(mid, _u()["id"])
    except askd.AskError:
        raise HTTPException(404, "Unknown answer")
    url = await instances.agent_url(_u()["id"]) if instances.ENABLED else instances.SHARED_AGENT
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{url}/snapshot", json={"html": askd.snapshot_html(body, meta["question"]), "width": 760})
    if r.status_code != 200:
        raise HTTPException(502, "The snapshot could not be drawn.")
    db.audit("askd.snapshot", mid, None, _u()["id"])
    return Response(base64.b64decode(r.json()["png"]), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="ask-d-{mid}.png"'})


class ToDashboard(BaseModel):
    project: str
    note: str = ""


@router.post("/api/askd/messages/{mid}/to-dashboard")
def to_dashboard(mid: str, body: ToDashboard):
    """Follow-through: the answer becomes a change request on a dashboard (a page or visual answering the question)."""
    from . import worker
    try:
        ans, meta = askd.message(mid, _u()["id"])
    except askd.AskError:
        raise HTTPException(404, "Unknown answer")
    if not auth.can_project(_u(), "edit", db.project(body.project)):
        raise HTTPException(403, "You cannot change that dashboard.")
    st = store.load(body.project)
    if st["status"] not in ("awaiting_review", "done", "error") or not st.get("versions"):
        raise HTTPException(409, f"Not now (status: {st['status']}).")
    orgs.require("change")                       # D2D Relay: a change request costs credits
    v = ans.get("validation") or {}
    main = next((q for q in v.get("queries") or [] if q.get("id") == v.get("main_query")), None)
    request = (f"Add to the dashboard what answers this Ask D question: \"{meta['question']}\".\n"
               f"Ask D found: {ans.get('summary', '')}\n"
               + (f"The query Ask D used ({main['where']}; adapt it to the model views for the prototype):\n{main['sql']}\n" if main else "")
               + (f"Note: {body.note}\n" if body.note else "")
               + "Put it where it fits best (a new visual on an existing page, or a new page if it is a new topic).")
    store.note(body.project, "Change request (from Ask D)", request)
    store.log(body.project, {"kind": "user", "stage": "revise", "text": f"From Ask D: {meta['question'][:160]}"})
    orgs.paid("change", body.project, st.get("name"), lambda cid: worker.enqueue(body.project, "revise", feedback=request, attachments=[],
                                                                                 **orgs.job_args(cid)), note="From Ask Relay")
    db.audit("askd.to_dashboard", mid, {"project": body.project}, _u()["id"])
    return {"ok": True}
