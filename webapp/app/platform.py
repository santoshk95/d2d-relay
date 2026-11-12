"""Sign-in, sharing and administration endpoints (platform plan, phase 1). Permission checks happen in
auth.middleware before any of these run (admin paths: Admins only; /shares changes: owner or Admin)."""
import json
import re
import secrets
import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from genbi_kit import daxcheck

from . import auth, db, identity, instances, providers, secrets_store, store, worker

router = APIRouter()
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _user_out(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "email", "name", "org_role", "active", "created", "last_login", "auth_provider",
                                  "deactivated", "home_tenant")} | {"teams": u.get("teams") or []}


def _guest(u: dict) -> None:
    """A guest from another tenant (P17) is managed through their access grant, not as a person of this workspace."""
    if u.get("home_tenant"):
        raise HTTPException(409, "This person is a guest from another workspace; change or end their access under Admin > Partner access.")


def _all_users() -> list[dict]:
    users = db.q("SELECT * FROM users ORDER BY active DESC, lower(name)")
    teams = db.q("SELECT m.user_id, t.id, t.name, m.role FROM memberships m JOIN teams t ON t.id = m.team_id ORDER BY t.name")
    owned = {r["owner_id"]: r["n"] for r in db.q("SELECT owner_id, count(*) n FROM projects GROUP BY owner_id")}
    for u in users:
        u["teams"] = [{"id": t["id"], "name": t["name"], "role": t["role"]} for t in teams if t["user_id"] == u["id"]]
        u["projects"] = owned.get(u["id"], 0)
    return [_user_out(u) | {"projects": u["projects"], "local": bool(u.get("password_hash"))} for u in users]


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _signed_in(uid: str, provider: str, request: Request, return_to: str = "") -> RedirectResponse:
    sid = identity.create_session(uid, provider, _ip(request), request.headers.get("user-agent", ""))
    r = RedirectResponse("/" + (return_to if return_to.startswith("#/") else ""), 303)
    r.set_cookie(identity.COOKIE, identity.cookie_value(sid), max_age=int(identity.SESSION_HOURS * 3600), httponly=True,
                 samesite="lax", secure=identity.SECURE_COOKIE, path="/")     # P17: the cookie names the home tenant
    return r


def _to_login(message: str) -> RedirectResponse:
    t = db.tenant()
    return RedirectResponse("/login.html?" + (f"t={quote(t)}&" if t != db.PLATFORM else "") + "error=" + quote(message), 303)


# ---------------------------------------------------------------- sign-in

@router.get("/auth/providers")
def sign_in_options():
    out = {"mode": auth.MODE, "providers": identity.providers(public=True), "local": identity.local_enabled()}
    t = auth.tenant_row(db.tenant())
    if t and t["kind"] != "platform":                  # P17: the workspace this sign-in page is for
        out["tenant"] = {"id": t["id"], "name": t["name"], "kind": t["kind"]}
    return out


@router.post("/auth/setup")
def setup_password(request: Request, token: str = Form(...), password: str = Form(...)):
    """A new workspace's first admin sets their local password with the one-time link (P17)."""
    if auth.MODE == "otp":
        return _to_login("Sign in with a code sent to your email.")          # D2D Relay: email codes only
    t = identity.setup_tenant(token)
    if not t:
        return _to_login("This set-up link has expired or was already used. Ask for a new one.")
    with db.use(t):
        try:
            u = identity.use_setup(token, password)
        except identity.SignInError as e:
            return RedirectResponse(f"/login.html?t={quote(t)}&setup={quote(token)}&error=" + quote(str(e)), 303)
        if auth.MODE != "sso":
            return RedirectResponse(f"/login.html?t={quote(t)}&done=1", 303)
        return _signed_in(u["id"], "local", request)


@router.get("/auth/oidc/{pid}/start")
def oidc_start(pid: str, request: Request, next: str = ""):
    if auth.MODE == "otp":
        return _to_login("Sign in with a code sent to your email.")          # D2D Relay: email codes only
    try:
        return RedirectResponse(identity.start(pid, str(request.base_url), next), 303)
    except identity.SignInError as e:
        return _to_login(str(e))
    except httpx.HTTPError:
        return _to_login("Could not reach the identity provider. Try again in a moment.")


@router.get("/auth/oidc/{pid}/callback")
def oidc_callback(pid: str, request: Request, code: str = "", state: str = "", error: str = "",
                  error_description: str = ""):
    if error:
        return _to_login(error_description or "Sign-in was cancelled.")
    try:
        u, return_to = identity.callback(pid, code, state, str(request.base_url))
    except identity.SignInError as e:
        return _to_login(str(e))
    except httpx.HTTPError:
        return _to_login("Could not reach the identity provider. Try again in a moment.")
    return _signed_in(u["id"], pid, request, return_to)


@router.post("/auth/local")
def local_sign_in(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("")):
    if auth.MODE == "otp":
        return _to_login("Sign in with a code sent to your email.")          # D2D Relay: email codes only
    try:
        u = identity.local_sign_in(email, password, _ip(request))
    except identity.SignInError as e:
        return _to_login(str(e))
    return _signed_in(u["id"], "local", request, next)


@router.post("/auth/logout")
def sign_out(request: Request):
    _, sid = identity.split_cookie(request.cookies.get(identity.COOKIE))
    u = identity.session_user(sid)
    identity.end_session(sid)
    if u:
        db.audit("auth.logout", u["id"], None, u["id"])
    r = JSONResponse({"ok": True})
    r.delete_cookie(identity.COOKIE, path="/")
    return r


# ---------------------------------------------------------------- people and teams anyone may look up (to share with)

@router.get("/api/directory")
def directory(q: str = ""):
    q = f"%{q.strip().lower()}%"
    users = db.q("SELECT id, name, email FROM users WHERE active = 1 AND (lower(name) LIKE ? OR lower(email) LIKE ?) "
                 "ORDER BY lower(name) LIMIT 20", (q, q))
    teams = db.q("SELECT t.id, t.name, (SELECT count(*) FROM memberships m WHERE m.team_id = t.id) members FROM teams t "
                 "WHERE lower(t.name) LIKE ? ORDER BY lower(t.name) LIMIT 20", (q,))
    return {"users": users, "teams": teams}


# ---------------------------------------------------------------- sharing

class Grant(BaseModel):
    principal_type: str
    principal_id: str = "*"
    permission: str = "view"
    expires: float | None = None


class Sharing(BaseModel):
    visibility: str | None = None
    team_id: str | None = None
    shares: list[Grant] = []


def _sharing(pid: str) -> dict:
    p = db.project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    owner = db.one("SELECT id, name, email FROM users WHERE id = ?", (p["owner_id"],))
    team = db.one("SELECT id, name FROM teams WHERE id = ?", (p["team_id"],)) if p["team_id"] else None
    shares = db.q("SELECT * FROM shares WHERE project_id = ? ORDER BY principal_type DESC, created", (pid,))
    names = {r["id"]: r for r in db.q("SELECT id, name, email FROM users")} | {r["id"]: r for r in db.q("SELECT id, name FROM teams")}
    for s in shares:
        n = names.get(s["principal_id"]) or {}
        s["name"] = "Everyone in the organisation" if s["principal_type"] == "org" else n.get("name", s["principal_id"])
        s["email"] = n.get("email")
        s["expired"] = bool(s["expires"] and s["expires"] < time.time())
    u = auth.current.get()
    level, _ = auth.access(u, p)
    return {"owner": owner, "visibility": p["visibility"], "team": team, "shares": shares, "can_share": level == "owner",
            "teams": db.q("SELECT id, name FROM teams ORDER BY name")}


@router.get("/api/projects/{pid}/shares")
def get_shares(pid: str):
    return _sharing(pid)


@router.put("/api/projects/{pid}/shares")
def set_shares(pid: str, body: Sharing):
    p = db.project(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    vis = body.visibility or p["visibility"]
    if vis not in ("private", "team", "org"):
        raise HTTPException(400, "Visibility must be private, team or org.")
    team = body.team_id if body.team_id is not None else p["team_id"]
    if vis == "team" and not (team and db.one("SELECT 1 FROM teams WHERE id = ?", (team,))):
        raise HTTPException(400, "Pick the team to share with.")
    rows = []
    for g in body.shares:
        if g.principal_type not in ("user", "team", "org") or g.permission not in ("view", "edit"):
            raise HTTPException(400, "Each share needs a person, team or the organisation, and view or edit.")
        if g.principal_type == "user" and not db.one("SELECT 1 FROM users WHERE id = ? AND active = 1", (g.principal_id,)):
            raise HTTPException(400, "Unknown person.")
        if g.principal_type == "team" and not db.one("SELECT 1 FROM teams WHERE id = ?", (g.principal_id,)):
            raise HTTPException(400, "Unknown team.")
        if g.principal_type == "user" and g.principal_id == p["owner_id"]:
            continue
        rows.append((pid, g.principal_type, "*" if g.principal_type == "org" else g.principal_id, g.permission,
                     g.expires, time.time(), auth.who()))
    before = auth.visible_to(db.project(pid))
    with db.transaction():                     # one transaction for the whole change
        db.run("UPDATE projects SET visibility = ?, team_id = ? WHERE id = ?", (vis, team, pid))
        db.run("DELETE FROM shares WHERE project_id = ?", (pid,))
        for r in rows:
            db.run("INSERT OR REPLACE INTO shares (project_id, principal_type, principal_id, permission, expires, "
                   "created, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)", r)
    db.audit("project.share", pid, {"visibility": vis, "team": team,
                                    "shares": [{"to": f"{r[1]}:{r[2]}", "permission": r[3], "expires": r[4]} for r in rows]},
             auth.who())
    from . import notify
    me = db.user(auth.who() or "") or {}
    notify.add_many(sorted(auth.visible_to(db.project(pid)) - before), "share", f"{me.get('name', 'Someone')} shared a dashboard with you",
                    store.load(pid).get("name") or pid, f"#/p/{pid}", skip=auth.who())
    store.log(pid, {"kind": "user", "text": f"Sharing: {vis}" + (f" + {len(rows)} share{'s' if len(rows) != 1 else ''}" if rows else "")})
    return _sharing(pid)


# ---------------------------------------------------------------- administration: people and teams

class Membership(BaseModel):
    team_id: str
    role: str


class Person(BaseModel):
    email: str | None = None
    name: str | None = None
    org_role: str | None = None
    teams: list[Membership] | None = None


def _set_teams(uid: str, teams: list[Membership]) -> None:
    for m in teams:
        if m.role not in ("dev", "viewer") or not db.one("SELECT 1 FROM teams WHERE id = ?", (m.team_id,)):
            raise HTTPException(400, "Each membership needs a known team and the role dev or viewer.")
    with db.transaction():
        db.run("DELETE FROM memberships WHERE user_id = ?", (uid,))
        for m in teams:
            db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, ?)", (uid, m.team_id, m.role))


def _admins() -> int:
    """The workspace's own admins (a guest admin from a partner does not count)."""
    return db.one("SELECT count(*) n FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL")["n"]


@router.get("/api/admin/users")
def admin_users():
    return {"users": _all_users(), "teams": admin_teams()["teams"]}


@router.post("/api/admin/users")
def admin_add_user(body: Person):
    email = (body.email or "").strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter the person's work email address.")
    if db.one("SELECT 1 FROM users WHERE lower(email) = ?", (email,)):
        raise HTTPException(409, "That person is already in D2D.")
    other = db.one("SELECT home_tenant FROM relay.tn_accounts WHERE email = ?", (email,))
    if other and other["home_tenant"] != db.tenant():
        raise HTTPException(409, "That email address belongs to someone in another workspace; give them access from there instead.")
    uid = "u-" + secrets.token_hex(6)
    db.run("INSERT INTO users (id, email, name, org_role, created) VALUES (?, ?, ?, ?, ?)",
           (uid, email, (body.name or email.split("@")[0]).strip()[:120], "admin" if body.org_role == "admin" else "member",
            time.time()))
    db.run("INSERT OR IGNORE INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)",
           (uid, email, db.tenant(), time.time()))
    _set_teams(uid, body.teams or [])
    from . import orgs                                  # late import (orgs -> platform)
    orgs.unblock(email)                                 # item 32: adding someone lifts a block on their address
    db.audit("user.add", uid, {"email": email, "org_role": body.org_role or "member",
                               "teams": [m.model_dump() for m in body.teams or []]}, auth.who())
    return admin_users()


@router.patch("/api/admin/users/{uid}")
def admin_change_user(uid: str, body: Person):
    u = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    if not u:
        raise HTTPException(404, "Unknown person")
    _guest(u)
    if body.org_role is not None:
        if body.org_role not in ("admin", "member"):
            raise HTTPException(400, "Organisation role must be admin or member.")
        if u["org_role"] == "admin" and body.org_role != "admin" and _admins() <= 1:
            raise HTTPException(409, "Keep at least one admin.")
        db.run("UPDATE users SET org_role = ? WHERE id = ?", (body.org_role, uid))
    if body.name:
        db.run("UPDATE users SET name = ? WHERE id = ?", (body.name.strip()[:120], uid))
    if body.teams is not None:
        _set_teams(uid, body.teams)
    db.audit("user.change", uid, body.model_dump(exclude_none=True), auth.who())
    return admin_users()


class Offboard(BaseModel):
    transfer_to: str


@router.post("/api/admin/users/{uid}/deactivate")
async def admin_deactivate(uid: str, body: Offboard):
    """Offboarding: the person loses access at once; their dashboards and library visuals go to someone else;
    their sessions, stored keys and tokens are revoked. (Phase 2 also destroys their workspace instance.)"""
    u = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    if not u or not u["active"]:
        raise HTTPException(404, "Unknown or already deactivated person")
    _guest(u)
    if uid == auth.who():
        raise HTTPException(409, "You cannot deactivate yourself.")
    if u["org_role"] == "admin" and _admins() <= 1:
        raise HTTPException(409, "Keep at least one admin.")
    to = db.one("SELECT * FROM users WHERE id = ? AND active = 1", (body.transfer_to,))
    if not to or to["id"] == uid:
        raise HTTPException(400, "Choose an active person to take over the work.")
    moved = db.run("UPDATE projects SET owner_id = ? WHERE owner_id = ?", (to["id"], uid))
    visuals = db.run("UPDATE library SET owner_id = ? WHERE owner_id = ?", (to["id"], uid))
    db.run("DELETE FROM shares WHERE principal_type = 'user' AND principal_id = ?", (uid,))
    db.run("DELETE FROM memberships WHERE user_id = ?", (uid,))
    sessions = identity.end_user_sessions(uid)
    revoked = [s["name"] for s in secrets_store.names() if s["scope"] == f"user:{uid}"]
    for name in revoked:
        secrets_store.delete(f"user:{uid}", name, auth.who())
    db.run("UPDATE users SET active = 0, deactivated = ?, deactivated_by = ? WHERE id = ?", (time.time(), auth.who(), uid))
    db.run("DELETE FROM meta WHERE key = ?", (f"ai:{uid}",))
    try:
        instance = (await instances.destroy(uid, auth.who())).get("state")
    except (instances.InstanceError, httpx.HTTPError) as e:
        instance = f"not removed: {e}"
    summary = {"dashboards_transferred": moved, "visuals_transferred": visuals, "sessions_ended": sessions,
               "secrets_revoked": revoked, "transfer_to": to["id"],
               "instance": "removed" if instance == "absent" else "shared agent (no personal instance)" if instance == "shared" else instance}
    db.audit("user.deactivate", uid, summary, auth.who())
    return {"summary": summary, **admin_users()}


@router.post("/api/admin/users/{uid}/reactivate")
def admin_reactivate(uid: str):
    if not db.run("UPDATE users SET active = 1, deactivated = NULL, deactivated_by = NULL WHERE id = ? AND active = 0 "
                  "AND home_tenant IS NULL", (uid,)):                # a guest comes back through a new access grant
        raise HTTPException(404, "Unknown or active person")
    db.audit("user.reactivate", uid, None, auth.who())
    return admin_users()


class Team(BaseModel):
    name: str


@router.get("/api/admin/teams")
def admin_teams():
    teams = db.q("SELECT t.id, t.name, t.created, (SELECT count(*) FROM memberships m WHERE m.team_id = t.id) members, "
                 "(SELECT count(*) FROM projects p WHERE p.team_id = t.id) projects FROM teams t ORDER BY lower(t.name)")
    return {"teams": teams}


@router.post("/api/admin/teams")
def admin_add_team(body: Team):
    name = body.name.strip()[:80]
    if not name:
        raise HTTPException(400, "Name the team.")
    if db.one("SELECT 1 FROM teams WHERE lower(name) = ?", (name.lower(),)):
        raise HTTPException(409, "A team with that name exists.")
    tid = "t-" + secrets.token_hex(5)
    db.run("INSERT INTO teams (id, name, created) VALUES (?, ?, ?)", (tid, name, time.time()))
    db.audit("team.add", tid, {"name": name}, auth.who())
    return admin_teams()


@router.patch("/api/admin/teams/{tid}")
def admin_rename_team(tid: str, body: Team):
    name = body.name.strip()[:80]
    if not name or not db.run("UPDATE teams SET name = ? WHERE id = ?", (name, tid)):
        raise HTTPException(404, "Unknown team")
    db.audit("team.rename", tid, {"name": name}, auth.who())
    return admin_teams()


@router.delete("/api/admin/teams/{tid}")
def admin_remove_team(tid: str):
    t = db.one("SELECT * FROM teams WHERE id = ?", (tid,))
    if not t:
        raise HTTPException(404, "Unknown team")
    if tid == db.DEFAULT_TEAM:
        raise HTTPException(409, "The default team stays.")
    if db.one("SELECT 1 FROM projects WHERE team_id = ?", (tid,)):
        raise HTTPException(409, "Move this team's dashboards to another team first.")
    db.run("DELETE FROM shares WHERE principal_type = 'team' AND principal_id = ?", (tid,))
    db.run("DELETE FROM memberships WHERE team_id = ?", (tid,))
    db.run("DELETE FROM teams WHERE id = ?", (tid,))
    db.audit("team.remove", tid, {"name": t["name"]}, auth.who())
    return admin_teams()


# ---------------------------------------------------------------- administration: sign-in, AI policy, instances

class Providers(BaseModel):
    providers: list[dict]
    secrets: dict[str, str] = {}


@router.get("/api/admin/sso")
def admin_sso(request: Request):
    return {"mode": auth.MODE, "providers": identity.providers(), "local": identity.local_enabled(),
            "redirect_uri": identity.redirect_uri("<id>", str(request.base_url)), "session_hours": identity.SESSION_HOURS}


@router.put("/api/admin/sso")
def admin_set_sso(body: Providers, request: Request):
    try:
        identity.save_providers(body.providers, body.secrets, auth.who())
    except identity.SignInError as e:
        raise HTTPException(400, str(e))
    return admin_sso(request)


AI_PROVIDERS = {"claude_account": "Claude Docker: Claude account (per person, today's setup)",
                "anthropic_api": "Anthropic API key",
                "bedrock": "Amazon Bedrock (via LiteLLM)", "azure_foundry": "Azure AI Foundry (via LiteLLM)",
                "vertex": "Google Vertex AI (via LiteLLM)", "enterprise": "Enterprise endpoint (Anthropic API)",
                "docker": "Self-hosted model (Docker)", "codex": "OpenAI Codex CLI (own agent image)",
                "gemini": "Gemini CLI (own agent image)", "antigravity": "Antigravity CLI (own agent image; Google login or Gemini key)"}
RESIDENCY = {"any": "Any region", "eu": "EU only", "us": "US only", "eu_us": "EU and US"}
DEFAULT_POLICY = {"allowed": ["claude_account", "anthropic_api", "bedrock", "vertex"], "residency": "any",
                  "default": "claude_account", "backup": None}


class AIPolicy(BaseModel):
    allowed: list[str]
    residency: str = "any"
    default: str = "claude_account"
    backup: str | None = None


def ai_policy() -> dict:
    return json.loads(db.meta("ai_policy") or "null") or DEFAULT_POLICY


@router.get("/api/admin/ai-policy")
def admin_ai_policy():
    return {"policy": ai_policy(), "providers": AI_PROVIDERS, "residency": RESIDENCY}


@router.put("/api/admin/ai-policy")
def admin_set_ai_policy(body: AIPolicy):
    if not body.allowed or any(a not in AI_PROVIDERS for a in body.allowed):
        raise HTTPException(400, "Allow at least one known provider.")
    if body.residency not in RESIDENCY or body.default not in body.allowed or (body.backup and body.backup not in body.allowed):
        raise HTTPException(400, "The default and backup must be allowed providers, and the region a known one.")
    db.set_meta("ai_policy", json.dumps(body.model_dump()))
    db.audit("ai.policy", None, body.model_dump(), auth.who())
    return admin_ai_policy()


@router.get("/api/admin/instances")
async def admin_instances():
    """Phase 1 view of the running services; per-person instances arrive in phase 2."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            agent = (await client.get(f"{worker.AGENT_URL}/health")).json()
    except Exception as e:  # noqa: BLE001
        agent = {"ok": False, "error": e.__class__.__name__}
    counts = {r["state"]: r["n"] for r in db.q("SELECT state, count(*) n FROM jobs GROUP BY state")}
    sessions = db.one("SELECT count(*) n, count(DISTINCT user_id) people FROM sessions WHERE expires > ?", (time.time(),))
    return {"instance": db.INSTANCE, "agent": agent, "jobs": counts, "waiting": worker.waiting(),
            "running": {k: v for k, v in worker.current.items() if k != "task"}, "daxcheck": daxcheck.available(),
            "sessions": sessions, "auth": auth.MODE, "last_backup": json.loads(db.meta("last_backup") or "null")}


# ---------------------------------------------------------------- my AI provider and workspace (phase 2)

class MyAI(BaseModel):
    kind: str
    route: str | None = None
    base_url: str | None = None
    backup: str | None = None
    claude_oauth_token: str | None = None
    anthropic_api_key: str | None = None
    enterprise_token: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    cli_model: str | None = None
    clear_claude_oauth_token: bool = False
    clear_anthropic_api_key: bool = False
    clear_enterprise_token: bool = False
    clear_openai_api_key: bool = False
    clear_gemini_api_key: bool = False


def _my_ai(uid: str) -> dict:
    pol = ai_policy()
    kinds = {k: v for k, v in providers.KINDS.items() if k != "litellm" and k in pol["allowed"]}
    mine = providers.routes_for(uid)
    if mine:
        kinds["litellm"] = providers.KINDS["litellm"]
    return {"settings": providers.settings(uid), "kinds": kinds, "instances": instances.ENABLED,
            "routes": [{"alias": r["alias"], "label": r["label"], "provider": providers.ROUTE_PROVIDERS[r["provider"]]} for r in mine],
            "policy_backup": pol.get("backup"), "policy_default": pol.get("default")}


class Pins(BaseModel):
    pins: list[str]


@router.get("/api/me/pins")
def my_pins():
    """Dashboards the person pinned to the sidebar (only ones they can still open)."""
    u = auth.current.get()
    pins = json.loads(db.meta(f"pins:{u['id']}") or "[]")
    visible = auth.visible(u, pins)
    return {"pins": [p for p in pins if p in visible]}


@router.put("/api/me/pins")
def set_my_pins(body: Pins):
    u = auth.current.get()
    pins = list(dict.fromkeys(p for p in body.pins if isinstance(p, str) and re.fullmatch(r"[\w-]{1,80}", p)))[:20]
    db.set_meta(f"pins:{u['id']}", json.dumps(pins))
    return my_pins()


# D2D Relay (2026-11-12): the first-time tour (brand, light or dark, the basics). Shown once to people who start using
# D2D Relay from this day on, finished or skipped; "Take the tour" in the profile menu opens it again.
TOUR_SINCE = 1794441600                     # 2026-11-12 00:00 UTC: people who signed in before it know the app already


class Tour(BaseModel):
    step: str = ""                          # "done", or the step it was skipped at


def tour_due(u: dict) -> bool:
    """Whether the person has yet to see the first-time tour."""
    if db.meta(f"tour:{u['id']}"):
        return False
    row = db.one("SELECT created FROM users WHERE id = ?", (u["id"],))
    return bool(row) and (row["created"] or 0) >= TOUR_SINCE


@router.post("/api/me/tour")
def tour_seen(body: Tour):
    """The person finished or skipped the first-time tour: it is not shown on its own again."""
    u = auth.current.get()
    db.set_meta(f"tour:{u['id']}", json.dumps({"when": time.time(), "step": re.sub(r"[^a-z]", "", body.step.lower())[:20]}))
    return {"ok": True}


@router.get("/api/me/ai")
def my_ai():
    return _my_ai(auth.who())


@router.put("/api/me/ai")
def set_my_ai(body: MyAI):
    try:
        providers.save(auth.who(), body.model_dump(), auth.who())
    except providers.ProviderError as e:
        raise HTTPException(400, str(e))
    return _my_ai(auth.who())


@router.get("/api/workspace")
async def my_workspace():
    try:
        return {"enabled": instances.ENABLED, **(await instances.status(auth.who()))}
    except (instances.InstanceError, httpx.HTTPError) as e:
        return {"enabled": instances.ENABLED, "state": "error", "error": str(e)}


@router.post("/api/workspace/start")
async def start_my_workspace():
    """Called on sign-in: creates the person's instance the first time, starts it when it was stopped."""
    try:
        return {"enabled": instances.ENABLED, **(await instances.start(auth.who()))}
    except (instances.InstanceError, httpx.HTTPError) as e:
        raise HTTPException(503, str(e))


# ---------------------------------------------------------------- administration: gateway routes and instances

class Routes(BaseModel):
    routes: list[dict]
    credentials: dict[str, dict[str, str]] = {}


@router.get("/api/admin/llm-routes")
def admin_llm_routes():
    return {"routes": providers.routes_admin(), "providers": providers.ROUTE_PROVIDERS, "secrets": providers.ROUTE_SECRETS,
            "gateway": providers.GATEWAY_URL, "teams": db.q("SELECT id, name FROM teams ORDER BY name")}


@router.put("/api/admin/llm-routes")
async def admin_set_llm_routes(body: Routes):
    try:
        providers.save_routes(body.routes, body.credentials, auth.who())
    except providers.ProviderError as e:
        raise HTTPException(400, str(e))
    await instances.restart_gateway()
    return admin_llm_routes()


@router.get("/api/admin/workspaces")
async def admin_workspaces():
    try:
        data = await instances.listing()
    except (instances.InstanceError, httpx.HTTPError) as e:
        return {"enabled": instances.ENABLED, "instances": [], "error": str(e)}
    names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
    for i in data.get("instances", []):
        i["name_of_user"] = names.get(i.get("user"), i.get("user"))
    return data


@router.post("/api/admin/workspaces/{uid}/{action}")
async def admin_workspace_action(uid: str, action: str):
    if action not in ("start", "stop"):
        raise HTTPException(400, "start or stop")
    if action == "stop" and worker.current.get("owner") == uid:
        raise HTTPException(409, "This person's job is running; stop it from the dashboard first.")
    try:
        return await (instances.start(uid) if action == "start" else instances.stop(uid, "stopped by an admin", auth.who()))
    except (instances.InstanceError, httpx.HTTPError) as e:
        raise HTTPException(503, str(e))
