"""Who is asking, and may they? Every request passes `middleware` (platform plan, phases 0-1).

Modes (D2D_AUTH):
  single  (default) one local user: every request is the bootstrap admin - the app works as before sign-in existed
  sso     sign-in required: SSO (OpenID Connect) for everyone, a local password for the bootstrap admin only
  header  tests only: the X-D2D-User header names the user
  otp     D2D Relay: a code by email for business addresses, each person in their organisation's workspace (otp.py)

Roles: Admin (organisation-wide); per team membership 'dev' (BI Dev / Analyst) or 'viewer'.
Projects are private to their owner by default; the owner (or an Admin) shares them with people, teams or the whole
organisation, to view or edit, optionally until a date. Editing (change requests, KPIs, approving, publishing)
also needs the BI Dev / Analyst role: a Viewer never changes or publishes a dashboard, whatever it is shared as.

P17 (tenants): every request runs inside one tenant. A person belongs to a home tenant (header mode: X-D2D-Tenant or
the directory; SSO: the session cookie's prefix; single mode: the platform). With an active access grant they may act
in another tenant (relay.tn_acting, re-checked on every request): the request then runs in that tenant as their guest
row there. A module that is switched off for the tenant answers 403 (entitlements, tenancy.py).
"""
import asyncio
import contextvars
import html
import os
import re
import time
from urllib.parse import quote, urlparse

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import db, edition, identity, instances, portal, store

MODE = os.environ.get("D2D_AUTH", "single")
current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("d2d_user", default=None)
TENANT_HEADER = "x-d2d-tenant"

PROJECT = re.compile(r"^/api/projects/([a-z0-9][a-z0-9-]{2,63})(/.*)?$")
LIBRARY = re.compile(r"^/api/library/([^/]+)$")
PUBLISH = {"/approve", "/pbix"}             # D2D Relay: making the Power BI file is publishing
SHARE = {"/shares"}
OPEN_PATHS = ("/login.html", "/privacy.html", "/terms.html", "/refunds.html", "/contact.html", "/auth/", "/css/login.css", "/css/fonts.css", "/fonts/", "/relay-mark.svg", "/d2d-mark.svg", "/favicon.ico", "/powered-by.svg", "/icons/", "/manifest.webmanifest",
              "/favicon", "/metrics", "/healthz", "/portal.js")   # reachable without signing in (/metrics checks its own token)
ADMIN_AUTH = ("/auth/otp/", "/auth/providers", "/auth/logout", "/auth/brand")   # D2D Relay: the admin portal's sign-in paths
SAFE = {"GET", "HEAD", "OPTIONS"}


def tenant_row(t: str | None) -> dict | None:
    """The control-plane row of a tenant this install serves (not closed), or None."""
    if not t:
        return None
    row = db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (t,))
    return row if row and row["status"] != "closed" else None


def _directory_home(uid: str) -> str | None:
    row = db.one("SELECT home_tenant FROM relay.tn_accounts WHERE user_id = ?", (uid,)) if uid else None
    return row["home_tenant"] if row else None


def home_of(request: Request) -> tuple[str, dict | None, str]:
    """(home tenant, the person as their home tenant knows them, the key their acting tenant is kept under)."""
    if MODE == "header":
        uid = request.headers.get("x-d2d-user", "")
        t = request.headers.get(TENANT_HEADER) or _directory_home(uid) or db.PLATFORM
        if not tenant_row(t):
            return db.PLATFORM, None, ""
        with db.use(t):
            u = db.user(uid)
        if u and u.get("home_tenant"):                  # a guest row is never anyone's home
            u = None
        return t, u, ("u:" + uid) if u else ""
    if MODE in ("sso", "otp"):                          # D2D Relay: otp = one email, one-time code (otp.py)
        t, sid = identity.split_cookie(request.cookies.get(identity.COOKIE))
        if not tenant_row(t):
            return db.PLATFORM, None, ""
        with db.use(t):
            u = identity.session_user(sid)
        return t, u, identity.session_key(sid) if u else ""
    with db.use(db.PLATFORM):
        u = db.user(db.ADMIN_ID)
    return db.PLATFORM, u, ("u:" + db.ADMIN_ID) if u else ""


def acting(skey: str, uid: str) -> dict | None:
    """The grant this person is acting under (with its tenant row), or None. An ended grant clears the switch."""
    if not skey:
        return None
    row = db.one("SELECT a.tenant_id, a.grant_id, a.since, g.status, g.expires, g.role, g.user_id AS grant_user, g.home_tenant "
                 "FROM relay.tn_acting a JOIN relay.tn_access g ON g.id = a.grant_id WHERE a.skey = ? AND a.user_id = ?", (skey, uid))
    if not row:
        return None
    t = tenant_row(row["tenant_id"])
    if row["status"] != "active" or (row["expires"] or 0) <= time.time() or row["grant_user"] != uid or not t or t["status"] != "active":
        db.run("DELETE FROM relay.tn_acting WHERE skey = ?", (skey,))
        return None
    return {**row, "tenant": t}


def _anon_tenant(request: Request) -> str:
    """The tenant of a request nobody is signed in to (the sign-in page, its brand and flows): ?t=, the OIDC state,
    the host name, an old session cookie, else the platform."""
    qp = request.query_params
    for t in (qp.get("t"), (qp.get("state") or "").split(identity.SEP, 1)[0] if identity.SEP in (qp.get("state") or "") else None):
        if t and tenant_row(t):
            return t
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host:
        row = db.one("SELECT id FROM relay.tn_tenants WHERE host = ? AND status != 'closed'", (host,))
        if row:
            return row["id"]
    t, _ = identity.split_cookie(request.cookies.get(identity.COOKIE))
    return t if tenant_row(t) else db.PLATFORM


def resolve(request: Request) -> dict | None:
    """The person making this request, in the tenant it runs in (their guest row while acting elsewhere)."""
    home, hu, skey = home_of(request)
    if hu is None:
        return None
    g = acting(skey, hu["id"])
    if g:
        with db.use(g["tenant_id"]):
            guest = db.user(hu["id"])
        if guest:
            guest["_tenancy"] = {"home": home, "tenant": g["tenant_id"], "grant": g["grant_id"], "expires": g["expires"],
                                 "role": g["role"], "home_admin": is_admin(hu), "home_name": hu.get("name")}
            return guest
        db.run("DELETE FROM relay.tn_acting WHERE skey = ?", (skey,))
    hu["_tenancy"] = {"home": home, "tenant": home, "grant": None, "expires": None, "role": None, "home_admin": is_admin(hu),
                      "home_name": hu.get("name")}
    return hu


def tenant_of(u: dict | None) -> str:
    return ((u or {}).get("_tenancy") or {}).get("tenant") or db.PLATFORM


def who() -> str | None:
    u = current.get()
    return u["id"] if u else None


def is_admin(u: dict) -> bool:
    return u.get("org_role") == "admin"


def is_dev(u: dict, team_id: str | None = None) -> bool:
    return is_admin(u) or any(t["role"] == "dev" and (team_id is None or t["id"] == team_id) for t in u.get("teams", []))


def _shares(pid: str) -> list[dict]:
    return db.q("SELECT * FROM shares WHERE project_id = ? AND (expires IS NULL OR expires > ?)", (pid, time.time()))


def access(u: dict, p: dict | None, shares: list[dict] | None = None) -> tuple[str | None, str]:
    """The strongest access this person has to a project: ('owner' | 'edit' | 'view' | None, how).
    A folder with no index row (made outside the app) is only visible to Admins."""
    if p is None:
        return ("owner", "admin") if is_admin(u) else (None, "")
    if p["owner_id"] == u["id"]:
        return "owner", "owner"
    if is_admin(u):
        return "owner", "admin"
    member = {t["id"]: t["role"] for t in u.get("teams", [])}
    best, how = None, ""
    grants = list(shares if shares is not None else _shares(p["id"]))
    if p["visibility"] == "org":
        grants.append({"principal_type": "org", "principal_id": "*", "permission": "view"})
    if p["visibility"] == "team" and p["team_id"]:     # shared with its team: the team's BI Devs may edit
        grants.append({"principal_type": "team", "principal_id": p["team_id"], "permission": "edit"})
    for g in grants:
        applies = (g["principal_type"] == "org" or (g["principal_type"] == "user" and g["principal_id"] == u["id"])
                   or (g["principal_type"] == "team" and g["principal_id"] in member))
        if not applies:
            continue
        level = "edit" if g["permission"] == "edit" and is_dev(u) else "view"   # Viewers never edit
        if best != "edit":
            best, how = level, g["principal_type"]
    return best, how


def can_project(u: dict, action: str, p: dict | None) -> bool:
    level, _ = access(u, p)
    if action == "view":
        return level is not None
    if action == "share":
        return level == "owner"
    return level in ("owner", "edit") and (action != "publish" or is_dev(u))


def visible_to(p: dict | None) -> set[str]:
    """People given this dashboard directly or through a team (not Admins, not an organisation-wide share): the ones
    told when it is shared with them."""
    if p is None:
        return set()
    shares = _shares(p["id"])
    out = set()
    for r in db.q("SELECT id FROM users WHERE active = 1"):
        u = db.user(r["id"])
        level, how = access(u, p, shares) if u else (None, "")
        if level and how in ("user", "team", "owner"):
            out.add(r["id"])
    return out


def visible(u: dict, project_ids: list[str]) -> set[str]:
    return set(access_map(u, project_ids))


def access_map(u: dict, project_ids: list[str]) -> dict[str, dict]:
    """project id -> {access, via, owner_id, visibility} for every project this person can see."""
    rows = {r["id"]: r for r in db.q("SELECT * FROM projects")}
    shares: dict[str, list] = {}
    for s in db.q("SELECT * FROM shares WHERE expires IS NULL OR expires > ?", (time.time(),)):
        shares.setdefault(s["project_id"], []).append(s)
    out = {}
    for pid in project_ids:
        p = rows.get(pid)
        level, how = access(u, p, shares.get(pid, []))
        if level:
            out[pid] = {"access": level, "via": how, "owner_id": p["owner_id"] if p else None,
                        "visibility": p["visibility"] if p else "private", "team_id": p["team_id"] if p else None}
    return out


def _deny(status: int, text: str) -> JSONResponse:
    return JSONResponse({"detail": text}, status_code=status)


def check(u: dict | None, method: str, path: str) -> JSONResponse | None:
    """The rule for one request; None means allowed."""
    if not path.startswith("/api/"):
        return None                                    # the app shell and static files (sign-in handled in middleware)
    if edition.blocked(path):
        return _deny(404, "That is not part of D2D Relay.")
    if portal.ADMIN:
        # D2D Relay's admin portal (portal.py): its own few APIs, for PASDACS people only
        if not portal.api_allowed(path):
            return _deny(404, "That is not part of the D2D Relay admin portal.")
        if u is None:
            return _deny(401, "Sign in to the D2D Relay admin portal.")
        return None if portal.is_admin(u) else _deny(403, "The admin portal is for PASDACS people only.")
    if u is None:
        if path == "/api/payments/webhook" and method == "POST":     # Razorpay: no sign-in, its body is signed (payments.py)
            return None
        return _deny(401, "Sign in to D2D Relay.")
    if path.startswith("/api/admin"):
        # D2D Relay: no platform powers on the public site. Every organisation, credits and connectors are on the
        # admin portal (admin-d2d.pasdacs.com, its own container); an organisation's owner manages their own
        # workspace through /api/org.
        return _deny(404, "Administration is on the D2D Relay admin portal.")
    if path == "/api/projects" and method == "POST":
        return None if is_dev(u) else _deny(403, "Your account cannot create dashboards in this organisation.")
    m = PROJECT.match(path)
    if m:
        if db.project(m.group(1)) is None and not (store.ROOT / m.group(1) / "project.json").exists():
            return _deny(404, "Project not found")          # no such dashboard in this workspace (Admins included)
        rest = m.group(2) or ""
        action = ("view" if method in SAFE else "share" if rest in SHARE
                  else "publish" if rest in PUBLISH else "edit")
        if not can_project(u, action, db.project(m.group(1))):
            if not can_project(u, "view", db.project(m.group(1))):
                return _deny(404, "Project not found")
            return _deny(403, "Only the owner or an admin can change who this is shared with." if action == "share"
                         else "You can view this dashboard but not change it.")
        return None
    m = LIBRARY.match(path)
    if m and method == "DELETE":
        item = db.library_item(m.group(1))
        if not (is_admin(u) or (item and item["owner_id"] == u["id"])):
            return _deny(403, "Only the visual's owner or an admin can remove it.")
    return None


def _same_origin(request: Request) -> bool:
    """Browsers send Origin on cross-site POSTs; refuse them (SameSite=Lax cookies are the first line)."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    return urlparse(origin).netloc == host or (identity.PUBLIC_URL and origin == identity.PUBLIC_URL)


def _refused_page(text: str) -> HTMLResponse:
    return HTMLResponse("<!doctype html><meta charset=utf-8><title>D2D Relay admin</title><body style=\"font:15px system-ui;"
                        f"max-width:560px;margin:15vh auto;padding:0 16px\"><h2>D2D Relay admin</h2><p>{html.escape(text)}</p>",
                        status_code=403)


async def middleware(request: Request, call_next):
    path = request.url.path
    if edition.page_off(path):                          # security audit S15: RELAY's pages and callbacks
        return _deny(404, "That is not part of D2D Relay.")
    if portal.ADMIN and path not in ("/healthz",):
        # D2D Relay's admin portal: through Cloudflare, only with a valid Cloudflare Access token (portal.py)
        why = await asyncio.to_thread(portal.access_refusal, request.headers, request.cookies) \
            if request.headers.get("cf-connecting-ip") else portal.local_refusal(request.client.host if request.client else None)
        if why:
            return _deny(403, why) if path.startswith("/api/") else _refused_page(why)
        if path.startswith("/auth/") and not path.startswith(ADMIN_AUTH):
            return _deny(404, "That is not part of the D2D Relay admin portal.")
    if MODE in ("sso", "otp") and request.method not in SAFE and not _same_origin(request):
        return _deny(403, "Cross-site request refused.")
    u = resolve(request)
    request.state.uid = u["id"] if u else None          # for the request log (monitor.py)
    if MODE in ("sso", "otp") and u is None and not path.startswith("/api/") and not path.startswith(OPEN_PATHS):
        return RedirectResponse("/login.html" + (f"?next={quote(request.url.fragment)}" if request.url.fragment else ""), 303)
    # the tenant this request runs in: sign-in routes stay in the person's home tenant (their session lives there)
    tid = (u["_tenancy"]["home"] if path.startswith("/auth/") else u["_tenancy"]["tenant"]) if u else _anon_tenant(request)
    ttoken = db.TENANT.set(tid)
    try:
        denied = check(u, request.method, path)
        if denied is None and u is not None and path.startswith("/api/"):
            from . import tenancy                       # late import: tenancy -> registry -> auth
            denied = tenancy.denied(u, request.method, path)
        if denied is not None:
            return denied
        if u is not None and path.startswith("/api/"):
            instances.touch(u["id"])
        token = current.set(u)
        try:
            response = await call_next(request)
        finally:
            current.reset(token)
    finally:
        db.TENANT.reset(ttoken)
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"      # revalidate (ETag), so a redeploy never leaves old UI code
    return response
