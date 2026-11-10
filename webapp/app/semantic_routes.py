"""Semantic layer endpoints (platform plan, phase 4). Everyone signed in reads; who may change what is checked in
semantic.py (team BI Devs / Analysts, a different reviewer, Admins for organisation defaults)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, semantic, store

router = APIRouter()


def _u() -> dict:
    return auth.current.get()


def _err(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


def _my_projects() -> list[str]:
    return sorted(auth.visible(_u(), [p["id"] for p in store.dashboards()]))


@router.get("/api/semantic/metrics")
def list_metrics(team: str | None = None):
    teams = db.q("SELECT id, name FROM teams ORDER BY name")
    mine = [t["id"] for t in _u().get("teams", [])]
    return {"metrics": semantic.metrics([team] if team else None), "teams": teams, "my_teams": mine,
            "dialects": semantic.WAREHOUSE_DIALECTS}


class Draft(BaseModel):
    team_id: str
    name: str
    body: dict


@router.post("/api/semantic/metrics")
def draft_metric(d: Draft):
    try:
        return semantic.save_draft(d.team_id, d.name, d.body, _u())
    except semantic.SemanticError as e:
        raise _err(e)


@router.get("/api/semantic/metrics/{mid}")
def get_metric(mid: str):
    try:
        return semantic.metric(mid)
    except semantic.SemanticError:
        raise HTTPException(404, "Unknown metric")


class Decision(BaseModel):
    version: int
    approve: bool | None = None
    note: str = ""


@router.post("/api/semantic/metrics/{mid}/submit")
def submit_metric(mid: str, d: Decision):
    try:
        return semantic.submit(mid, d.version, _u())
    except semantic.SemanticError as e:
        raise _err(e)


@router.post("/api/semantic/metrics/{mid}/decide")
def decide_metric(mid: str, d: Decision):
    try:
        return semantic.decide(mid, d.version, _u(), bool(d.approve), d.note)
    except semantic.SemanticError as e:
        raise _err(e)


@router.get("/api/semantic/reviews")
def reviews():
    """Versions waiting for review in my teams (an Admin sees all)."""
    teams = None if auth.is_admin(_u()) else [t["id"] for t in _u().get("teams", []) if t["role"] == "dev"]
    out = []
    for m in semantic.metrics(teams):
        if m["open_status"] == "review":
            full = semantic.metric(m["id"])
            out.append({**full, "can_decide": full["open"]["author_id"] != _u()["id"] or auth.is_admin(_u())})
    return {"reviews": out}


@router.get("/api/semantic/terms")
def list_terms():
    return {"terms": semantic.terms(None), "teams": db.q("SELECT id, name FROM teams ORDER BY name")}


@router.post("/api/semantic/terms")
def add_term(body: dict):
    try:
        return semantic.save_term(body, _u())
    except semantic.SemanticError as e:
        raise _err(e)


@router.put("/api/semantic/terms/{tid}")
def change_term(tid: str, body: dict):
    try:
        return semantic.save_term(body, _u(), tid)
    except semantic.SemanticError as e:
        raise _err(e)


@router.delete("/api/semantic/terms/{tid}")
def delete_term(tid: str):
    try:
        semantic.remove_term(tid, _u())
    except semantic.SemanticError as e:
        raise _err(e)
    return list_terms()


@router.get("/api/semantic/context")
def get_context():
    return {"tables": semantic.context(_my_projects())}


class Note(BaseModel):
    source: str
    tbl: str
    col: str
    description: str = ""
    sensitive: bool = False


@router.put("/api/semantic/context/note")
def set_note(n: Note):
    try:
        semantic.save_note(n.source, n.tbl, n.col, n.description, n.sensitive, _u())
    except semantic.SemanticError as e:
        raise _err(e)
    return {"ok": True}


@router.get("/api/semantic/ontology")
def get_ontology():
    return {**semantic.ontology(), "teams": db.q("SELECT id, name FROM teams ORDER BY name")}


@router.post("/api/semantic/ontology/scan")
def scan_ontology():
    """Look for keys that match across sources (by their values) and metric names that conflict across teams."""
    if not auth.is_dev(_u()):
        raise HTTPException(403, "Only BI Devs / Analysts run the scan.")
    n = semantic.find_key_matches(_my_projects())
    semantic._same_word_suggestions()                     # noqa: SLF001
    return {"found": n, **get_ontology()}


@router.post("/api/semantic/entities")
def add_entity(body: dict):
    try:
        return semantic.save_entity(body, _u())
    except semantic.SemanticError as e:
        raise _err(e)


@router.put("/api/semantic/entities/{eid}")
def change_entity(eid: str, body: dict):
    try:
        return semantic.save_entity(body, _u(), eid)
    except semantic.SemanticError as e:
        raise _err(e)


@router.delete("/api/semantic/entities/{eid}")
def delete_entity(eid: str):
    try:
        semantic.remove_entity(eid, _u())
    except semantic.SemanticError as e:
        raise _err(e)
    return get_ontology()


class Relation(BaseModel):
    from_id: str
    verb: str
    to_id: str
    remove: bool = False


@router.post("/api/semantic/relations")
def relation(r: Relation):
    try:
        semantic.relate(r.from_id, r.verb, r.to_id, _u(), r.remove)
    except semantic.SemanticError as e:
        raise _err(e)
    return get_ontology()


class SuggestionDecision(BaseModel):
    accept: bool
    choice: str | None = None


@router.post("/api/semantic/suggestions/{sid}")
def decide_suggestion(sid: str, d: SuggestionDecision):
    try:
        return {**semantic.decide_suggestion(sid, d.accept, _u(), d.choice), "teams": db.q("SELECT id, name FROM teams ORDER BY name")}
    except semantic.SemanticError as e:
        raise _err(e)


@router.get("/api/semantic/match-groups")
def match_groups():
    return {"groups": semantic.match_groups(_my_projects()), "can_decide": auth.is_dev(_u())}


class GroupDecision(BaseModel):
    ids: list[str]
    accept: bool
    name: str | None = None


@router.post("/api/semantic/match-groups/decide")
def decide_group(d: GroupDecision):
    try:
        n = semantic.decide_group(d.ids, d.accept, _u(), d.name)
    except semantic.SemanticError as e:
        raise _err(e)
    return {"decided": n, "groups": semantic.match_groups(_my_projects()), **get_ontology()}


# ---------------------------------------------------------------- a dashboard and the team's metrics

class Promote(BaseModel):
    names: list[str]


@router.post("/api/projects/{pid}/promote")
def promote(pid: str, body: Promote):
    try:
        done = semantic.promote(pid, body.names, _u())
    except semantic.SemanticError as e:
        raise _err(e)
    store.log(pid, {"kind": "user", "text": f"Sent {len(done)} KPI(s) for review as team metrics: " + ", ".join(m["name"] for m in done)})
    return {"metrics": [{"id": m["id"], "name": m["name"], "version": m["open"]["version"]} for m in done]}


class Certify(BaseModel):
    measure: str


@router.post("/api/projects/{pid}/certify")
def update_to_certified(pid: str, body: Certify):
    """A measure that differs from (or predates) the team's published metric: ask Claude to use the certified DAX."""
    from . import worker
    cert = semantic.certification(pid).get(body.measure)
    if not cert or cert["status"] == "certified":
        raise HTTPException(409, "That measure already matches the certified definition.")
    st = store.load(pid)
    if st["status"] not in ("awaiting_review", "done", "error") or not st.get("versions"):
        raise HTTPException(409, f"Not now (status: {st['status']}).")
    request = (f"Use the certified team metric for [{body.measure}] (v{cert['version']}): set its DAX to exactly\n"
               f"{cert['dax']}\nKeep everything else as it is.")
    store.note(pid, "Change request", request)
    store.log(pid, {"kind": "user", "stage": "revise", "text": f"Update [{body.measure}] to the certified definition v{cert['version']}"})
    worker.enqueue(pid, "revise", feedback=request, attachments=[])
    return {"ok": True}


# ---------------------------------------------------------------- descriptions: AI drafts, review, entity details

class DraftTable(BaseModel):
    source: str
    redo: bool = False                    # also redraft descriptions that exist (people's own are never replaced)


@router.post("/api/semantic/context/draft")
async def draft_table_descriptions(body: DraftTable):
    from . import askd, describe, usage
    try:
        return await describe.draft_table(_u(), body.source, _my_projects(), body.redo)
    except (describe.DescribeError, askd.AskError, usage.QuotaError) as e:
        raise HTTPException(429 if isinstance(e, usage.QuotaError) else 400, str(e))


class Accept(BaseModel):
    source: str
    tbl: str
    cols: list[str]


@router.post("/api/semantic/context/accept")
def accept_descriptions(body: Accept):
    from . import describe
    try:
        n = describe.accept(body.source, body.tbl, body.cols, _u())
    except describe.DescribeError as e:
        raise HTTPException(403, str(e))
    return {"accepted": n}


@router.get("/api/semantic/entities/{eid}/details")
def entity_details(eid: str):
    from . import describe
    try:
        return describe.details(eid, _u(), _my_projects())
    except describe.DescribeError as e:
        raise HTTPException(404, str(e))


@router.post("/api/semantic/entities/{eid}/draft")
async def draft_entity(eid: str):
    from . import askd, describe, usage
    try:
        return await describe.draft_entity(_u(), eid, _my_projects())
    except usage.QuotaError as e:
        raise HTTPException(429, str(e))
    except (describe.DescribeError, askd.AskError) as e:
        raise HTTPException(400, str(e))
