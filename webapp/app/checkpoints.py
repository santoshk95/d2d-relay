"""The checkpoint service (build-plan v2, P10): any agent run can pause at a named checkpoint with an evidence
payload and a view type; the Validation queue lists them; a person accepts, sends back with a comment or
reassigns; every decision is signed, audited, measured (time to validate, right first time) and handed back to the
phase module that opened the checkpoint (register_kind). The queue also shows the human steps that existed before
P10 — a dashboard waiting for its KPIs or its review, a publishing review — as derived items that open the page
where the decision is made.
"""
from __future__ import annotations

import json
import secrets
import statistics
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, notify, store

router = APIRouter()

db.register_schema("""
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, module TEXT NOT NULL, name TEXT NOT NULL,
  view TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '{}', link TEXT, agent TEXT, run_id TEXT,
  status TEXT NOT NULL CHECK (status IN ('open', 'accepted', 'sent_back', 'withdrawn')),
  assignee_id TEXT, team_id TEXT, opened_by TEXT, created REAL NOT NULL, decided REAL, decided_by TEXT, comment TEXT, seconds REAL);
CREATE INDEX IF NOT EXISTS checkpoints_open ON checkpoints (status, created);
CREATE INDEX IF NOT EXISTS checkpoints_subject ON checkpoints (kind, subject);
""")

VIEWS = ("process", "fields", "plan", "kpis", "prototype", "gates", "mapping", "table", "text", "link")
KINDS: dict[str, dict] = {}            # kind -> {label, on_decision}
DERIVED = {"awaiting_kpis": ("dashboard.kpis", "Confirm the KPIs and their formulas", "kpis"),
           "awaiting_review": ("dashboard.review", "Review the prototype", "prototype")}


def register_kind(kind: str, label: str, on_decision=None, own_admins: bool = False) -> None:
    """A phase module names its checkpoint kinds; on_decision(checkpoint, decision, comment, who) runs after a
    decision is stored, so the module can continue (re-read with the correction, start the next step, write back).
    own_admins (P17): only the tenant's own admins see and decide it — never a guest from another tenant."""
    KINDS[kind] = {"label": label, "on_decision": on_decision, "own_admins": own_admins}


def _public(r: dict) -> dict:
    out = dict(r)
    try:
        out["evidence"] = json.loads(r.get("evidence") or "{}")
    except ValueError:
        out["evidence"] = {}
    out["label"] = (KINDS.get(r["kind"]) or {}).get("label") or r["kind"]
    out["derived"] = False
    return out


def get(cid: str) -> dict | None:
    r = db.one("SELECT * FROM checkpoints WHERE id = ?", (cid,))
    return _public(r) if r else None


def open(kind: str, subject: str, module: str, name: str, view: str = "text", evidence: dict | None = None, *,  # noqa: A001
         link: str | None = None, assignee: str | None = None, team: str | None = None, agent: str | None = None,
         run_id: str | None = None, opened_by: str | None = None) -> dict:
    """Open a checkpoint (or return the one already open for the same kind + subject + name)."""
    if view not in VIEWS:
        raise ValueError(f"Unknown view type {view!r}; one of {', '.join(VIEWS)}")
    have = db.one("SELECT * FROM checkpoints WHERE kind = ? AND subject = ? AND name = ? AND status = 'open'", (kind, subject, name))
    if have:
        return _public(have)
    cid = "cp-" + secrets.token_hex(5)
    db.run("INSERT INTO checkpoints (id, kind, subject, module, name, view, evidence, link, agent, run_id, status, assignee_id, team_id, opened_by, created) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)",
           (cid, kind, subject, module, name[:200], view, json.dumps(evidence or {}), link, agent, run_id, assignee, team, opened_by or "agent", time.time()))
    db.audit("checkpoint.open", cid, {"kind": kind, "subject": subject, "name": name, "assignee": assignee}, opened_by or "system")
    if assignee:
        notify.add(assignee, "review", f"Your check: {name}", f"{module} · {(KINDS.get(kind) or {}).get('label') or kind}", link or "#/validate")
    elif team:
        notify.add_many(notify.team_members(team), "review", f"A check is waiting: {name}", module, link or "#/validate")
    return get(cid)


def withdraw(kind: str, subject: str, name: str | None = None, who: str | None = None) -> int:
    """The subject moved on (a new version, a cancelled start): close what is still open without a decision."""
    rows = db.q("SELECT id FROM checkpoints WHERE kind = ? AND subject = ? AND status = 'open'" + (" AND name = ?" if name else ""),
                (kind, subject, name) if name else (kind, subject))
    for r in rows:
        db.run("UPDATE checkpoints SET status = 'withdrawn', decided = ?, decided_by = ? WHERE id = ?", (time.time(), who or "system", r["id"]))
    return len(rows)


def decide(cid: str, decision: str, who: str, comment: str | None = None) -> dict:
    """accept or send_back; the decision is signed, timed and handed to the kind's on_decision."""
    if decision not in ("accept", "send_back"):
        raise HTTPException(400, "Decision must be accept or send_back.")
    c = get(cid)
    if not c:
        raise HTTPException(404, "No such checkpoint.")
    if c["status"] != "open":
        raise HTTPException(409, f"This checkpoint was already {c['status'].replace('_', ' ')}.")
    if decision == "send_back" and not (comment or "").strip():
        raise HTTPException(400, "Say what to change when you send it back.")
    now = time.time()
    status = "accepted" if decision == "accept" else "sent_back"
    db.run("UPDATE checkpoints SET status = ?, decided = ?, decided_by = ?, comment = ?, seconds = ? WHERE id = ?",
           (status, now, who, (comment or "").strip()[:2000] or None, round(now - c["created"], 1), cid))
    db.audit("checkpoint." + status, cid, {"kind": c["kind"], "subject": c["subject"], "name": c["name"], "comment": (comment or "")[:300]}, who)
    c = get(cid)
    hook = (KINDS.get(c["kind"]) or {}).get("on_decision")
    if hook:
        hook(c, decision, comment, who)
    return c


def reassign(cid: str, to: str, who: str) -> dict:
    c = get(cid)
    if not c:
        raise HTTPException(404, "No such checkpoint.")
    if c["status"] != "open":
        raise HTTPException(409, "Only an open checkpoint can be reassigned.")
    if not db.user(to):
        raise HTTPException(400, "No such person.")
    db.run("UPDATE checkpoints SET assignee_id = ? WHERE id = ?", (to, cid))
    db.audit("checkpoint.reassign", cid, {"to": to, "name": c["name"]}, who)
    notify.add(to, "review", f"Reassigned to you: {c['name']}", c["module"], c.get("link") or "#/validate")
    return get(cid)


def _teams(u: dict) -> set[str]:
    return {t["id"] for t in (u.get("teams") or [])}


# P17 entitlements (consolidation): the queue does not list a checkpoint of a module switched off for the workspace
# (its API answers 403 there and nothing of it runs); it comes back when the module is on again. A decision already
# under way is not refused: the module holds the work until it is on (the workbench's rule).
KIND_API = {"itsm": "/api/servicedesk", "intan": "/api/intan", "observe": "/api/observe", "migbi": "/api/migrate-bi", "heal": "/api/heal",
            "sdlc": "/api/sdlc", "studio": "/api/studio", "rfp": "/api/rfp", "lineage": "/api/lineage", "semantic": "/api/semantic", "schedule": "/api/schedules"}


def modules_of(c: dict) -> set[str]:
    """The catalogue modules a checkpoint belongs to: wb.<module> for the workbench; else the module whose API its
    kind is named after (itsm.write -> the Service desk); else the module whose screen it links to (a connection
    write a studio filing asked for). A module sharing its API with others (the studio's) counts as any of them.
    Empty: the core (dashboards, connections, tenancy), always on."""
    from . import registry
    kind = str(c.get("kind") or "")
    if kind.startswith("wb."):
        return {kind[3:]}
    api = KIND_API.get(kind.split(".", 1)[0])
    if not api:
        link = str(c.get("link") or "").split("?", 1)[0].rstrip("/")
        owner = next((m for m in registry.MODULES if m.get("api") and m.get("route") and (link == m["route"] or link.startswith(m["route"] + "/"))), None)
        api = (owner.get("api") or [None])[0] if owner else None
    if not api:
        return set()
    from .tenancy import CORE                  # the core is always on: it owns no checkpoint
    return {m["id"] for m in registry.MODULES if api in (m.get("api") or []) and m["id"] not in CORE}


def module_on(c: dict) -> bool:
    owners = modules_of(c)
    if not owners or db._module_check is None:
        return True
    return any(db._module_check(db.tenant(), m) for m in owners)


def visible(u: dict, c: dict) -> bool:
    if (KINDS.get(c.get("kind")) or {}).get("own_admins"):
        return auth.is_admin(u) and not u.get("home_tenant")
    if auth.is_admin(u):
        return True
    if c.get("assignee_id"):
        return c["assignee_id"] == u["id"]
    if c.get("team_id"):
        return c["team_id"] in _teams(u)
    return c.get("opened_by") == u["id"] or auth.is_dev(u)


def derived(u: dict) -> list[dict]:
    """The human steps that existed before P10, shown in the same queue; they open the page where the decision lives."""
    out = []
    for p in store.all_projects():
        kind = DERIVED.get(p["status"])
        row = db.project(p["id"])
        if not kind or not auth.can_project(u, "edit", row):
            continue
        st = store.load(p["id"])
        out.append({"id": f"d-{kind[0]}-{p['id']}", "kind": kind[0], "subject": p["id"], "module": "D2D", "name": f"{kind[1]}: {p['name']}", "view": kind[2],
                    "evidence": {"summary": (st.get("prompt") or "")[:160], "versions": len(st.get("versions") or [])}, "link": f"#/p/{p['id']}",
                    "agent": "Relay", "status": "open", "assignee_id": None, "team_id": row.get("team_id") if row else None, "created": st.get("updated") or st.get("created") or 0,
                    "label": "Dashboard", "derived": True})
    try:
        from . import publishing
        for r in publishing.my_reviews(u["id"]):
            out.append({"id": f"d-publish.review-{r['project']}-{r.get('v')}", "kind": "publish.review", "subject": r["project"], "module": "D2D",
                        "name": f"Review v{r.get('v')} for publishing: {r['name']}", "view": "gates", "evidence": {"summary": r.get("note") or ""},
                        "link": f"#/p/{r['project']}/versions", "agent": r.get("requester") or "", "status": "open", "assignee_id": u["id"], "team_id": None,
                        "created": r.get("requested") or 0, "label": "Publishing review", "derived": True})
    except Exception:  # noqa: BLE001 - reviews are optional
        pass
    return out


def queue(u: dict) -> list[dict]:
    rows = [_public(r) for r in db.q("SELECT * FROM checkpoints WHERE status = 'open' ORDER BY created")]
    items = [c for c in rows if module_on(c) and visible(u, c)] + derived(u)      # a switched-off module's checkpoints wait out of sight
    return sorted(items, key=lambda c: c["created"] or 0)


def metrics(since: float, u: dict | None = None) -> dict:
    """Decisions in a period: how many, how fast, how often accepted unchanged (right first time)."""
    rows = db.q("SELECT * FROM checkpoints WHERE decided >= ? AND status IN ('accepted', 'sent_back')", (since,))
    if u is not None and not auth.is_admin(u):
        rows = [r for r in rows if r.get("decided_by") == u["id"] or r.get("team_id") in _teams(u)]
    secs = [r["seconds"] for r in rows if r.get("seconds") is not None]
    acc = sum(1 for r in rows if r["status"] == "accepted")
    by_who: dict[str, dict] = {}
    for r in rows:
        w = by_who.setdefault(r["decided_by"], {"decided": 0, "accepted": 0, "seconds": []})
        w["decided"] += 1; w["accepted"] += r["status"] == "accepted"
        if r.get("seconds") is not None:
            w["seconds"].append(r["seconds"])
    names = {x["id"]: x["name"] for x in db.q("SELECT id, name FROM users")}
    people = [{"id": k, "name": names.get(k, k), "decided": v["decided"], "accepted": v["accepted"],
               "median_seconds": round(statistics.median(v["seconds"]), 1) if v["seconds"] else None} for k, v in by_who.items()]
    return {"decided": len(rows), "accepted": acc, "sent_back": len(rows) - acc,
            "rft": round(100 * acc / len(rows), 1) if rows else None,
            "median_seconds": round(statistics.median(secs), 1) if secs else None,
            "open": db.one("SELECT COUNT(*) AS n FROM checkpoints WHERE status = 'open'")["n"], "people": sorted(people, key=lambda p: -p["decided"])}


# ------------------------------------------------------------------ API

class Decision(BaseModel):
    comment: str | None = None


class Reassign(BaseModel):
    to: str


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    return u


@router.get("/api/validate")
def api_queue(period: str = "30d"):
    u = _u()
    since = time.time() - {"7d": 7, "30d": 30, "6m": 183}.get(period, 30) * 86400
    items = queue(u)
    return {"items": items, "count": len(items), "mine": sum(1 for c in items if c.get("assignee_id") == u["id"] or c.get("derived")),
            "metrics": metrics(since, u), "kinds": {k: v["label"] for k, v in KINDS.items()}}


@router.get("/api/validate/count")
def api_count():
    u = _u()
    return {"count": len(queue(u))}


def _may_decide(cid: str) -> dict:
    """Only someone the checkpoint is for may decide it: the same rule as the queue (admin, the assignee, the team,
    or — when it is for nobody in particular — a builder or the person who opened it)."""
    u = _u()
    c = get(cid)
    if not c:
        raise HTTPException(404, "No such checkpoint.")
    if not visible(u, c):
        raise HTTPException(403, "This check is for someone else; ask them or an admin to reassign it.")
    return u


@router.post("/api/validate/{cid}/accept")
def api_accept(cid: str, body: Decision | None = None):
    return decide(cid, "accept", _may_decide(cid)["id"], body.comment if body else None)


@router.post("/api/validate/{cid}/send-back")
def api_send_back(cid: str, body: Decision):
    return decide(cid, "send_back", _may_decide(cid)["id"], body.comment)


@router.post("/api/validate/{cid}/reassign")
def api_reassign(cid: str, body: Reassign):
    u = _u()
    c = get(cid)
    if not c:
        raise HTTPException(404, "No such checkpoint.")
    if not (auth.is_admin(u) or c.get("assignee_id") == u["id"] or (c.get("team_id") and c["team_id"] in _teams(u))):
        raise HTTPException(403, "Only the assignee, the team or an admin can reassign it.")
    return reassign(cid, body.to, u["id"])


@router.get("/api/validate/history")
def api_history(limit: int = 50):
    u = _u()
    rows = [_public(r) for r in db.q("SELECT * FROM checkpoints WHERE status != 'open' ORDER BY decided DESC LIMIT ?", (min(limit, 200),))]
    return {"items": [c for c in rows if visible(u, c) or c.get("decided_by") == u["id"]]}
