"""Tenants, partners and editions (P17, docs/P17-tenancy.md).

The platform (PASDACS) -> service partners -> their clients, and direct Enterprise clients. Every tenant is a full
workspace with its own schema and folders (db.py, store.py); this module is the control plane around them:

- the platform console: create tenants (with their first admin and a one-time set-up link), the tree, suspend;
- entitlements: an edition per tenant and modules switched on or off (a partner's client never has more than its
  partner); a module that is off answers 403 (denied(), called by auth.middleware);
- access across tenants: time-boxed grants with a reason (1 hour to 30 days), optionally approved by the client
  (checkpoint `tenancy.access`); switching into a granted tenant (relay.tn_acting); revoke; expiry (sweep());
- hand-over: the partner's engagement ends - grants ended, guests' work moved to the client's named owner, partner
  access ended, recorded with its evidence;
- metering: each tenant's costs rolled up per month, per partner, priced by the price book; statements as CSV;
- the deployment pack for a client that runs Relay inside its own network (tenantmove.py).

Everything is audited twice: in the control plane (relay.tn_audit) and in the tenant's own audit log.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import secrets
import time
import traceback

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import auth, checkpoints, db, identity, notify, registry, secrets_store, store

router = APIRouter()

TENANCY = os.environ.get("D2D_TENANCY", "multi")        # single = a dedicated install that serves one tenant
KINDS = {"partner": "Service partner", "client": "Client"}
EDITIONS = {"enterprise": "Enterprise", "partner": "Service partner", "both": "Both editions"}
ROLES = {"admin": "Admin", "dev": "BI Dev / Analyst", "viewer": "Viewer"}
DEPLOYMENTS = {"shared": "Shared (this install)", "dedicated": "Dedicated (inside the client's network)"}
POLICIES = {"open": "Partner admins grant access themselves", "approval": "Our admins approve every request", "ended": "Ended at hand-over"}
DEFAULT_HOURS, MAX_HOURS = 8, 30 * 24
PENDING_DAYS = 7
# always on, whatever is switched off: the platform itself and the dashboard builder at its core
CORE = {"d2d", "bi", "connect", "demodata", "visuals", "gates", "runners", "ops", "govern"}
PRICES = {"currency": "USD", "usd_rate": 1.0, "edition_fee": {"enterprise": 1500.0, "partner": 2500.0, "both": 0.0},
          "module_fee": 150.0, "ai_markup_pct": 20.0}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PACKS = store.state_dir("packs")
_cache: dict[str, tuple[float, object]] = {}


class TenancyError(Exception):
    pass


def _err(e: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status, str(e))


# ------------------------------------------------------------------ the control plane, read

def row(tid: str | None) -> dict | None:
    return db.one("SELECT * FROM relay.tn_tenants WHERE id = ?", (tid,)) if tid else None


def must(tid: str) -> dict:
    t = row(tid)
    if not t or t["status"] == "closed":
        raise HTTPException(404, "No such workspace.")
    return t


def all_rows() -> list[dict]:
    return db.q("SELECT * FROM relay.tn_tenants ORDER BY CASE kind WHEN 'platform' THEN 0 WHEN 'partner' THEN 1 ELSE 2 END, lower(name)")


def children(tid: str) -> list[dict]:
    return db.q("SELECT * FROM relay.tn_tenants WHERE parent_id = ? ORDER BY lower(name)", (tid,))


def partner_of(t: dict) -> dict | None:
    """The partner a client belongs to (None for direct clients, partners and the platform)."""
    if not t or t["kind"] != "client" or not t["parent_id"]:
        return None
    p = row(t["parent_id"])
    return p if p and p["kind"] == "partner" else None


def ctl_audit(action: str, tenant_id: str | None, obj: str | None = None, detail: dict | None = None, who: str | None = None) -> None:
    """One row in the control plane's audit and the same in the tenant's own audit log (its admins see it)."""
    u = auth.current.get()
    who = who or (u or {}).get("id") or "system"
    who_tenant = ((u or {}).get("_tenancy") or {}).get("home")
    detail = {**(detail or {}), "by_name": (u or {}).get("name"), "by_tenant": who_tenant}
    db.run("INSERT INTO relay.tn_audit (ts, who, who_tenant, tenant_id, action, object, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
           (time.time(), who, who_tenant, tenant_id, action, obj, json.dumps(detail, default=str)))
    if tenant_id and row(tenant_id):
        try:
            with db.use(tenant_id):
                db.audit(action, obj, detail, who)
        except Exception:  # noqa: BLE001 - the control-plane row is the record
            traceback.print_exc()


def _invalidate() -> None:
    _cache.clear()


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _cache[key] = (time.time(), v)
    return v


# ------------------------------------------------------------------ who may do what (by the person's HOME tenant)

def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in first.")
    return u


def home(u: dict) -> str:
    return (u.get("_tenancy") or {}).get("home") or db.PLATFORM


def home_admin(u: dict) -> bool:
    return bool((u.get("_tenancy") or {}).get("home_admin"))


def platform_admin(u: dict) -> bool:
    return home(u) == db.PLATFORM and home_admin(u)


def partner_admin_of(u: dict) -> str | None:
    """The partner tenant this person administers (it is their home), else None."""
    t = row(home(u))
    return t["id"] if t and t["kind"] == "partner" and home_admin(u) else None


def manageable(u: dict) -> list[str]:
    """Tenants this person may manage in the console: every one (platform admins) or their partner and its clients."""
    if platform_admin(u):
        return [t["id"] for t in all_rows()]
    p = partner_admin_of(u)
    return [p] + [c["id"] for c in children(p)] if p else []


def may_manage(u: dict, tid: str) -> bool:
    return tid in manageable(u)


def own_admin_here(u: dict) -> bool:
    """An admin of the current tenant who belongs to it (not a guest from another tenant)."""
    return auth.is_admin(u) and not u.get("home_tenant")


def may_enter(u: dict, t: dict) -> str | None:
    """None when this person may be granted access into tenant t; else why not."""
    if TENANCY == "single":
        return "This install serves one workspace."
    if t["id"] == home(u):
        return "This is your own workspace."
    if t["status"] != "active":
        return f"{t['name']} is {t['status']}."
    if platform_admin(u):
        return None
    p = partner_admin_of(u)
    if p and t["kind"] == "client" and t["parent_id"] == p:
        return None if t["partner_access"] != "ended" else f"{t['name']} ended partner access at hand-over; their admin can reopen it."
    return "Only the platform's admins, or the admins of this client's partner, can be given access."


def console(u: dict) -> bool:
    return TENANCY != "single" and (platform_admin(u) or bool(partner_admin_of(u)))


# ------------------------------------------------------------------ entitlements: edition + modules

def _module_ids() -> set[str]:
    return {m["id"] for m in registry.MODULES}


def edition_allows(edition: str) -> set[str]:
    return _module_ids() - set(registry.LOCKED.get(edition, []))


def effective(tid: str) -> set[str]:
    """The modules switched on for a tenant: its edition's, within its partner's, minus what an admin switched off;
    the core is always on."""
    def compute() -> set[str]:
        t = row(tid)
        if not t:
            return set(CORE)
        allowed = edition_allows(t["edition"])
        p = partner_of(t)
        if p:
            allowed &= effective(p["id"])
        off = {r["module_id"] for r in db.q("SELECT module_id FROM relay.tn_modules WHERE tenant_id = ? AND enabled = 0", (tid,))}
        return (allowed - off) | CORE
    return _cached("mods:" + tid, 5, compute)


db._module_check = lambda tid, mid: mid in effective(tid)      # background passes skip switched-off modules


def module_states(tid: str) -> list[dict]:
    t = must(tid)
    allowed = edition_allows(t["edition"])
    p = partner_of(t)
    parent_on = effective(p["id"]) if p else None
    on = effective(tid)
    out = []
    for m in registry.MODULES:
        if m["pl"] in ("hidden", "platform") and m["id"] not in ("migbi", "publish"):
            continue
        why = ("core" if m["id"] in CORE else "edition" if m["id"] not in allowed
               else "partner" if parent_on is not None and m["id"] not in parent_on else None)
        out.append({"id": m["id"], "name": m["name"], "pillar": m["pl"], "status": m["status"], "on": m["id"] in on,
                    "locked": why in ("edition", "partner"), "core": m["id"] in CORE, "why": why})
    return out


def set_modules(u: dict, tid: str, changes: dict[str, bool]) -> list[dict]:
    t = must(tid)
    if not may_manage(u, tid):
        raise HTTPException(403, "You cannot change this workspace's modules.")
    if t["kind"] in ("platform", "partner") and not platform_admin(u):
        raise HTTPException(403, "Only the platform's admins change what a partner has.")
    states = {m["id"]: m for m in module_states(tid)}
    now = time.time()
    for mid, on in changes.items():
        m = states.get(mid)
        if not m:
            raise HTTPException(400, f"Unknown module {mid!r}.")
        if m["core"]:
            raise HTTPException(400, f"{m['name']} is part of the core and is always on.")
        if on and m["locked"]:
            raise HTTPException(400, f"{m['name']} is not part of the {EDITIONS[t['edition']]} edition" if m["why"] == "edition"
                                else f"{m['name']} is not switched on for {partner_of(t)['name']}, so its clients cannot have it.")
        db.run("INSERT OR REPLACE INTO relay.tn_modules (tenant_id, module_id, enabled, updated, updated_by) VALUES (?, ?, ?, ?, ?)",
               (tid, mid, 1 if on else 0, now, u["id"]))
    _invalidate()
    ctl_audit("tenancy.modules", tid, None, {"changes": changes})
    return module_states(tid)


def _owners() -> list[tuple[str, str]]:
    """(api prefix, module id) for every module that names its APIs (registry `api=[...]`), longest prefix first."""
    pairs = [(p, m["id"]) for m in registry.MODULES for p in m.get("api") or []]
    return sorted(pairs, key=lambda x: -len(x[0]))


def module_of(path: str) -> set[str]:
    hits = [(p, mid) for p, mid in _owners() if path == p or path.startswith(p + "/") or path.startswith(p + "-") or path.startswith(p + "?")]
    if not hits:
        return set()
    best = max(len(p) for p, _ in hits)
    return {mid for p, mid in hits if len(p) == best}


def denied(u: dict, method: str, path: str) -> JSONResponse | None:
    """Called by auth.middleware for every /api request: a suspended workspace, or a module that is switched off."""
    if path.startswith(("/api/tenancy", "/api/me", "/api/brand", "/api/registry")):
        return None
    t = row(db.tenant())
    if t and t["status"] == "suspended":
        return JSONResponse({"detail": f"{t['name']} is suspended. Ask the platform's administrators."}, status_code=403)
    owners = module_of(path)
    if not owners or owners & effective(db.tenant()):
        return None
    names = ", ".join(sorted(registry.BY_ID[m]["name"] for m in owners if m in registry.BY_ID))
    return JSONResponse({"detail": f"{names} is not switched on for this workspace. Ask your administrator."}, status_code=403)


# ------------------------------------------------------------------ tenants

def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:24].strip("-") or "workspace"
    if not base[0].isalpha():
        base = "w-" + base
    tid, n = base, 2
    while row(tid) or tid in db.RESERVED_IDS:
        tid, n = f"{base}-{n}", n + 1
    return tid


def public(t: dict, with_counts: bool = False) -> dict:
    out = {k: t[k] for k in ("id", "kind", "parent_id", "name", "edition", "status", "deployment", "host", "partner_access", "region",
                             "notes", "created", "updated")}
    out["kind_label"] = KINDS.get(t["kind"], "Platform")
    out["edition_label"] = EDITIONS.get(t["edition"], t["edition"])
    p = row(t["parent_id"]) if t["parent_id"] else None
    out["parent_name"] = p["name"] if p else None
    if with_counts:
        out["counts"] = counts(t["id"])
    return out


def counts(tid: str) -> dict:
    def compute():
        with db.use(tid):
            people = db.one("SELECT count(*) n FROM users WHERE active = 1 AND home_tenant IS NULL")["n"]
            guests = db.one("SELECT count(*) n FROM users WHERE active = 1 AND home_tenant IS NOT NULL")["n"]
            items = db.one("SELECT count(*) n FROM projects")["n"]
        grants = db.one("SELECT count(*) n FROM relay.tn_access WHERE tenant_id = ? AND status = 'active' AND expires > ?", (tid, time.time()))["n"]
        return {"people": people, "guests": guests, "items": items, "active_grants": grants}
    return _cached("counts:" + tid, 10, compute)


class TenantIn(BaseModel):
    name: str
    kind: str = "client"
    parent_id: str | None = None
    id: str | None = None
    edition: str | None = None
    admin_name: str = ""
    admin_email: str = ""
    modules_off: list[str] = []
    deployment: str = "shared"
    host: str | None = None
    partner_access: str = "open"
    region: str | None = None
    notes: str | None = None


def create(u: dict, body: TenantIn) -> dict:
    if TENANCY == "single":
        raise HTTPException(409, "This is a dedicated install for one workspace; new workspaces are made on the shared platform.")
    name = " ".join((body.name or "").split())[:80]
    if len(name) < 2:
        raise HTTPException(400, "Give the workspace a name.")
    if body.kind not in KINDS:
        raise HTTPException(400, "A workspace is a service partner or a client.")
    p_admin = partner_admin_of(u)
    if platform_admin(u):
        parent = body.parent_id or db.PLATFORM
        pr = row(parent)
        if not pr or pr["status"] == "closed":
            raise HTTPException(400, "Unknown parent workspace.")
        if body.kind == "partner" and parent != db.PLATFORM:
            raise HTTPException(400, "A service partner belongs to the platform.")
        if body.kind == "client" and pr["kind"] not in ("platform", "partner"):
            raise HTTPException(400, "A client belongs to the platform (direct) or to a service partner.")
    elif p_admin:
        if body.kind != "client":
            raise HTTPException(403, "A partner creates clients only.")
        parent = p_admin
        pr = row(parent)
    else:
        raise HTTPException(403, "Only the platform's admins and partner admins create workspaces.")
    edition = body.edition or ("partner" if body.kind == "partner" else (pr["edition"] if pr["kind"] == "partner" else "enterprise"))
    if edition not in EDITIONS or (edition == "both" and not platform_admin(u)):
        raise HTTPException(400, "Edition must be enterprise or partner.")
    if body.deployment not in DEPLOYMENTS:
        raise HTTPException(400, "Deployment must be shared or dedicated.")
    if body.partner_access not in ("open", "approval"):
        raise HTTPException(400, "Partner access must be open or approval.")
    email = (body.admin_email or "").strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter the work email of the workspace's first admin.")
    if db.one("SELECT 1 FROM relay.tn_accounts WHERE email = ?", (email,)):
        raise HTTPException(409, "That email address already belongs to someone on the platform.")
    host = (body.host or "").strip().lower() or None
    if host and (not re.fullmatch(r"[a-z0-9.-]{3,200}", host) or db.one("SELECT 1 FROM relay.tn_tenants WHERE host = ?", (host,))):
        raise HTTPException(400, "The host name is not valid or already used.")
    tid = (body.id or "").strip().lower() or _slug(name)
    if not db.TENANT_ID.match(tid) or tid in db.RESERVED_IDS or row(tid):
        raise HTTPException(400, "The workspace id must be 2-31 lowercase letters, digits or dashes, start with a letter and be new.")
    now, uid = time.time(), "u-" + secrets.token_hex(6)
    db.run("INSERT INTO relay.tn_tenants (id, kind, parent_id, name, edition, status, deployment, host, partner_access, region, notes, "
           "created, created_by, updated, updated_by) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (tid, body.kind, parent, name, edition, body.deployment, host, body.partner_access, (body.region or "")[:40] or None,
            (body.notes or "")[:1000] or None, now, u["id"], now, u["id"]))
    try:
        db.init_tenant(tid)
        with db.use(tid):
            db.run("INSERT INTO users (id, email, name, org_role, created, local_login) VALUES (?, ?, ?, 'admin', ?, 1)",
                   (uid, email, (body.admin_name or email.split("@")[0]).strip()[:120], now))
            db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (uid, db.DEFAULT_TEAM))
            db.run("INSERT INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)", (uid, email, tid, now))
            token = identity.create_setup(uid)
            db.audit("tenant.created", tid, {"name": name, "kind": body.kind, "first_admin": email}, u["id"])
        allowed = edition_allows(edition)
        for mid in body.modules_off:
            if mid in allowed and mid not in CORE:
                db.run("INSERT OR REPLACE INTO relay.tn_modules (tenant_id, module_id, enabled, updated, updated_by) VALUES (?, ?, 0, ?, ?)",
                       (tid, mid, now, u["id"]))
    except Exception:
        db.run("DELETE FROM relay.tn_modules WHERE tenant_id = ?", (tid,))
        db.run("DELETE FROM relay.tn_accounts WHERE home_tenant = ?", (tid,))
        db.run("DELETE FROM relay.tn_setup WHERE tenant_id = ?", (tid,))
        db.run("DELETE FROM relay.tn_tenants WHERE id = ?", (tid,))
        try:
            db.drop_tenant(tid)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        raise
    _invalidate()
    ctl_audit("tenancy.create", tid, tid, {"name": name, "kind": body.kind, "parent": parent, "edition": edition,
                                            "deployment": body.deployment, "first_admin": email})
    return {"tenant": public(row(tid), True), "admin": {"id": uid, "email": email}, "setup_link": setup_link(tid, token)}


def setup_link(tid: str, token: str) -> str:
    return f"/login.html?t={tid}&setup={token}"


class TenantPatch(BaseModel):
    name: str | None = None
    edition: str | None = None
    deployment: str | None = None
    host: str | None = None
    partner_access: str | None = None
    region: str | None = None
    notes: str | None = None
    status: str | None = None


def update(u: dict, tid: str, body: TenantPatch) -> dict:
    t = must(tid)
    here_admin = db.tenant() == tid and own_admin_here(u)
    managed = may_manage(u, tid)
    new = body.model_dump(exclude_none=True)
    if not new:
        return public(t, True)
    if not managed and not (here_admin and set(new) <= {"partner_access"}):
        raise HTTPException(403, "You cannot change this workspace.")
    if t["kind"] == "platform" and ("status" in new or "edition" in new):
        raise HTTPException(400, "The platform's own workspace is always active, with both editions.")
    if "status" in new:
        if new["status"] not in ("active", "suspended"):
            raise HTTPException(400, "Status must be active or suspended.")
        if t["kind"] == "partner" and not platform_admin(u):
            raise HTTPException(403, "Only the platform's admins suspend a partner.")
    if "edition" in new:
        if not platform_admin(u) or new["edition"] not in EDITIONS:
            raise HTTPException(403 if not platform_admin(u) else 400, "Only the platform's admins change an edition (enterprise, partner or both).")
    if "deployment" in new and new["deployment"] not in DEPLOYMENTS:
        raise HTTPException(400, "Deployment must be shared or dedicated.")
    if "partner_access" in new:
        if new["partner_access"] not in ("open", "approval"):
            raise HTTPException(400, "Partner access is open or approval (hand-over ends it).")
        if t["kind"] != "client":
            raise HTTPException(400, "Only a client has a partner-access policy.")
        if t["partner_access"] == "ended" and not (here_admin or platform_admin(u)):
            raise HTTPException(403, "Only the client's own admins reopen partner access after a hand-over.")
    if "host" in new:
        h = new["host"].strip().lower() or None
        if h and (not re.fullmatch(r"[a-z0-9.-]{3,200}", h) or db.one("SELECT 1 FROM relay.tn_tenants WHERE host = ? AND id != ?", (h, tid))):
            raise HTTPException(400, "The host name is not valid or already used.")
        new["host"] = h
    if "name" in new:
        new["name"] = " ".join(new["name"].split())[:80]
        if len(new["name"]) < 2:
            raise HTTPException(400, "Give the workspace a name.")
    sets = ", ".join(f"{k} = ?" for k in new)
    db.run(f"UPDATE relay.tn_tenants SET {sets}, updated = ?, updated_by = ? WHERE id = ?", (*new.values(), time.time(), u["id"], tid))
    if new.get("status") == "suspended":
        db.run("DELETE FROM relay.tn_acting WHERE tenant_id = ?", (tid,))
    _invalidate()
    ctl_audit("tenancy.update", tid, tid, new)
    return public(row(tid), True)


def tree(u: dict) -> list[dict]:
    ids = set(manageable(u))
    rows = [public(t, True) for t in all_rows() if t["id"] in ids]
    mine = {g["tenant_id"]: g for g in my_grants(u)}
    for r in rows:
        g = mine.get(r["id"])
        r["my_access"] = {"id": g["id"], "role": g["role"], "expires": g["expires"]} if g else None
    return rows


def overview(u: dict, tid: str) -> dict:
    t = must(tid)
    if not may_manage(u, tid):
        raise HTTPException(404, "No such workspace.")
    with db.use(tid):
        admins = db.q("SELECT id, name, email, local_login, password_hash IS NOT NULL AS has_password, last_login FROM users "
                      "WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL ORDER BY created")
    month = time.strftime("%Y-%m", time.gmtime())
    return {"tenant": public(t, True), "children": [public(c) for c in children(tid)], "admins": admins,
            "modules": module_states(tid), "grants": grants_for(tid), "handovers": handovers(tid),
            "usage": statement(tid, month), "may": {"modules": t["kind"] == "client" or platform_admin(u),
                                                    "edition": platform_admin(u), "enter": may_enter(u, t) is None,
                                                    "handover": t["kind"] == "client" and t["partner_access"] != "ended" and bool(partner_of(t)),
                                                    "pack": True, "suspend": t["kind"] != "platform" and (t["kind"] == "client" or platform_admin(u))},
            "policies": POLICIES, "roles": ROLES, "editions": EDITIONS, "deployments": DEPLOYMENTS}


def new_setup_link(u: dict, tid: str, uid: str | None = None) -> dict:
    must(tid)
    if not may_manage(u, tid):
        raise HTTPException(403, "You cannot do this for that workspace.")
    with db.use(tid):
        person = db.one("SELECT * FROM users WHERE id = ? AND active = 1 AND home_tenant IS NULL", (uid,)) if uid else \
            db.one("SELECT * FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL ORDER BY created LIMIT 1")
        if not person:
            raise HTTPException(404, "No admin of that workspace to send a link to.")
        db.run("UPDATE relay.tn_setup SET used = ? WHERE tenant_id = ? AND user_id = ? AND used IS NULL", (time.time(), tid, person["id"]))
        token = identity.create_setup(person["id"])
    ctl_audit("tenancy.setup_link", tid, person["id"], {"email": person["email"]})
    return {"setup_link": setup_link(tid, token), "email": person["email"], "hours": identity.SETUP_HOURS}


# ------------------------------------------------------------------ access grants and switching

def _grant_public(g: dict) -> dict:
    out = dict(g)
    now = time.time()
    out["live"] = g["status"] == "active" and (g["expires"] or 0) > now
    out["left_s"] = max(0, round((g["expires"] or 0) - now)) if out["live"] else 0
    out["role_label"] = ROLES.get(g["role"], g["role"])
    t, h = row(g["tenant_id"]), row(g["home_tenant"])
    out["tenant_name"], out["home_name"] = (t or {}).get("name"), (h or {}).get("name")
    with db.use(g["home_tenant"]):
        p = db.one("SELECT name, email FROM users WHERE id = ?", (g["user_id"],))
    out["person"] = {"id": g["user_id"], "name": (p or {}).get("name"), "email": (p or {}).get("email")}
    return out


def grants_for(tid: str, limit: int = 100) -> list[dict]:
    return [_grant_public(g) for g in db.q("SELECT * FROM relay.tn_access WHERE tenant_id = ? ORDER BY created DESC LIMIT ?", (tid, limit))]


def my_grants(u: dict) -> list[dict]:
    """The tenants this person may enter now (their active grants)."""
    rows = db.q("SELECT * FROM relay.tn_access WHERE user_id = ? AND status = 'active' AND expires > ? ORDER BY expires DESC",
                (u["id"], time.time()))
    seen, out = set(), []
    for g in rows:
        if g["tenant_id"] not in seen:
            seen.add(g["tenant_id"])
            out.append(_grant_public(g))
    return out


class GrantIn(BaseModel):
    user_id: str | None = None
    role: str = "admin"
    hours: float = DEFAULT_HOURS
    reason: str = ""


def grant(u: dict, tid: str, body: GrantIn) -> dict:
    t = must(tid)
    why = may_enter(u, t)
    if why:
        raise HTTPException(403, why)
    if body.role not in ROLES:
        raise HTTPException(400, "Role must be admin, dev or viewer.")
    reason = " ".join((body.reason or "").split())[:300]
    if len(reason) < 4:
        raise HTTPException(400, "Say why access is needed (it is shown to the client and kept in the audit).")
    hours = float(body.hours or DEFAULT_HOURS)
    if not 1 <= hours <= MAX_HOURS:
        raise HTTPException(400, "Access lasts from 1 hour to 30 days.")
    grantee = body.user_id or u["id"]
    h = home(u)
    with db.use(h):
        person = db.one("SELECT id, name, email FROM users WHERE id = ? AND active = 1 AND home_tenant IS NULL", (grantee,))
    if not person:
        raise HTTPException(400, "Access can be given to an active person of your own workspace only.")
    with db.use(tid):
        clash = db.one("SELECT id, home_tenant FROM users WHERE lower(email) = ? AND id != ?", ((person["email"] or "").lower(), grantee))
        mine = db.one("SELECT home_tenant FROM users WHERE id = ?", (grantee,))
    if clash or (mine and not mine["home_tenant"]):
        raise HTTPException(409, f"{person['email']} is already a person of {t['name']}; ask its admin to give them a role there instead.")
    now = time.time()
    pending = t["partner_access"] == "approval" and not platform_admin(u)
    gid = "ga-" + secrets.token_hex(6)
    db.run("INSERT INTO relay.tn_access (id, tenant_id, user_id, home_tenant, role, reason, status, hours, requested_by, granted_by, created, "
           "starts, expires) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (gid, tid, grantee, h, body.role, reason, "pending" if pending else "active", hours, u["id"], None if pending else u["id"], now,
            None if pending else now, None if pending else now + hours * 3600))
    g = db.one("SELECT * FROM relay.tn_access WHERE id = ?", (gid,))
    hn = (row(h) or {}).get("name") or h
    if pending:
        with db.use(tid):
            cp = checkpoints.open("tenancy.access", gid, "Partner access", f"{person['name']} ({hn}) asks for {ROLES[body.role]} access",
                                  "text", {"text": f"{person['name']} <{person['email']}> from {hn} asks for {ROLES[body.role]} access to "
                                                   f"{t['name']} for {hours:g} hours.\n\nReason: {reason}",
                                           "person": person, "home": hn, "role": body.role, "hours": hours, "reason": reason},
                                  link="#/admin/partner-access", opened_by=u["id"])
            db.run("UPDATE relay.tn_access SET checkpoint_id = ? WHERE id = ?", (cp["id"], gid))
            _tell_admins(tid, "Partner access needs your approval", f"{person['name']} from {hn}: {reason}", "#/validate")
        ctl_audit("tenancy.access_requested", tid, gid, {"person": person["email"], "role": body.role, "hours": hours, "reason": reason})
    else:
        _activate(g, u["id"])
    return _grant_public(db.one("SELECT * FROM relay.tn_access WHERE id = ?", (gid,)))


def _tell_admins(tid: str, title: str, body: str, link: str) -> None:
    with db.use(tid):
        admins = [r["id"] for r in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL")]
        notify.add_many(admins, "share", title, body, link)


def _tell_person(g: dict, title: str, body: str) -> None:
    with db.use(g["home_tenant"]):
        notify.add(g["user_id"], "share", title, body, "#/")


def _activate(g: dict, who: str) -> None:
    """The grant is live: the person's guest row in the tenant (their name and email, the granted role), notices, audit."""
    now = time.time()
    if g["status"] == "pending":
        db.run("UPDATE relay.tn_access SET status = 'active', granted_by = ?, starts = ?, expires = ? WHERE id = ?",
               (who, now, now + g["hours"] * 3600, g["id"]))
        g = db.one("SELECT * FROM relay.tn_access WHERE id = ?", (g["id"],))
    with db.use(g["home_tenant"]):
        p = db.one("SELECT id, name, email FROM users WHERE id = ?", (g["user_id"],))
    with db.use(g["tenant_id"]):
        have = db.one("SELECT * FROM users WHERE id = ?", (g["user_id"],))
        clash = db.one("SELECT id FROM users WHERE lower(email) = ? AND id != ?", ((p["email"] or "").lower(), g["user_id"]))
        if have and not have.get("home_tenant"):
            raise HTTPException(409, "That person already belongs to this workspace.")
        if clash:
            raise HTTPException(409, f"{p['email']} is already a person of this workspace; ask its admin to give them a role instead.")
        org_role = "admin" if g["role"] == "admin" else "member"
        if have:
            db.run("UPDATE users SET email = ?, name = ?, org_role = ?, active = 1, deactivated = NULL, deactivated_by = NULL, home_tenant = ? "
                   "WHERE id = ?", (p["email"], p["name"], org_role, g["home_tenant"], g["user_id"]))
        else:
            db.run("INSERT INTO users (id, email, name, org_role, active, created, home_tenant) VALUES (?, ?, ?, ?, 1, ?, ?)",
                   (g["user_id"], p["email"], p["name"], org_role, now, g["home_tenant"]))
        db.run("DELETE FROM memberships WHERE user_id = ?", (g["user_id"],))
        db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, ?)",
               (g["user_id"], db.DEFAULT_TEAM, "viewer" if g["role"] == "viewer" else "dev"))
    t, hn = row(g["tenant_id"]), (row(g["home_tenant"]) or {}).get("name")
    until = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(g["expires"]))
    _tell_admins(g["tenant_id"], f"{p['name']} from {hn} can act in {t['name']}",
                 f"{ROLES[g['role']]} until {until}. Reason: {g['reason']}", "#/admin/partner-access")
    _tell_person(g, f"You can enter {t['name']}", f"{ROLES[g['role']]} until {until}. Switch from the workspace menu.")
    _invalidate()
    ctl_audit("tenancy.access_granted", g["tenant_id"], g["id"], {"person": p["email"], "role": g["role"], "hours": g["hours"],
                                                                   "until": g["expires"], "reason": g["reason"]}, who)


def _on_access_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    g = db.one("SELECT * FROM relay.tn_access WHERE id = ?", (c["subject"],))
    if not g or g["status"] != "pending":
        return
    if decision == "accept":
        _activate(g, who)
        return
    db.run("UPDATE relay.tn_access SET status = 'refused', ended = ?, ended_by = ?, end_reason = ? WHERE id = ?",
           (time.time(), who, (comment or "")[:300], g["id"]))
    _tell_person(g, f"Access to {(row(g['tenant_id']) or {}).get('name')} was refused", comment or "")
    ctl_audit("tenancy.access_refused", g["tenant_id"], g["id"], {"comment": comment}, who)


checkpoints.register_kind("tenancy.access", "Partner access", _on_access_decision, own_admins=True)


def _end_guest(tid: str, uid: str, who: str) -> None:
    """When no live grant is left for this person in this tenant, their guest row there is deactivated (their work
    stays where it is) and any switch into it is cleared."""
    left = db.one("SELECT 1 AS x FROM relay.tn_access WHERE tenant_id = ? AND user_id = ? AND status = 'active' AND expires > ?",
                  (tid, uid, time.time()))
    db.run("DELETE FROM relay.tn_acting WHERE user_id = ? AND tenant_id = ?" + ("" if not left else " AND grant_id NOT IN "
           "(SELECT id FROM relay.tn_access WHERE status = 'active')"), (uid, tid))
    if left:
        return
    with db.use(tid):
        db.run("UPDATE users SET active = 0, deactivated = ?, deactivated_by = ? WHERE id = ? AND home_tenant IS NOT NULL",
               (time.time(), who, uid))


def revoke(u: dict, gid: str, reason: str = "") -> dict:
    g = db.one("SELECT * FROM relay.tn_access WHERE id = ?", (gid,))
    if not g:
        raise HTTPException(404, "No such access.")
    allowed = (platform_admin(u) or (home(u) == g["home_tenant"] and home_admin(u)) or g["user_id"] == u["id"]
               or (db.tenant() == g["tenant_id"] and own_admin_here(u)))
    if not allowed:
        raise HTTPException(403, "You cannot end this access.")
    if g["status"] not in ("active", "pending"):
        raise HTTPException(409, f"This access is already {g['status']}.")
    db.run("UPDATE relay.tn_access SET status = 'revoked', ended = ?, ended_by = ?, end_reason = ? WHERE id = ?",
           (time.time(), u["id"], (reason or "")[:300] or None, gid))
    if g["checkpoint_id"]:
        with db.use(g["tenant_id"]):
            checkpoints.withdraw("tenancy.access", gid, who=u["id"])
    _end_guest(g["tenant_id"], g["user_id"], u["id"])
    if g["user_id"] != u["id"]:
        _tell_person(g, f"Your access to {(row(g['tenant_id']) or {}).get('name')} was ended", reason or "")
    _invalidate()
    ctl_audit("tenancy.access_revoked", g["tenant_id"], gid, {"reason": reason, "person": g["user_id"]})
    return _grant_public(db.one("SELECT * FROM relay.tn_access WHERE id = ?", (gid,)))


def session_key(request: Request, u: dict) -> str:
    if auth.MODE == "sso":
        _, sid = identity.split_cookie(request.cookies.get(identity.COOKIE))
        return identity.session_key(sid)
    return "u:" + u["id"]


def switch(u: dict, request: Request, tid: str) -> dict:
    skey = session_key(request, u)
    h = home(u)
    if tid == h:
        db.run("DELETE FROM relay.tn_acting WHERE skey = ?", (skey,))
        ctl_audit("tenancy.return", (u.get("_tenancy") or {}).get("tenant"), None, {"home": h})
        return {"tenant": h}
    t = must(tid)
    if t["status"] != "active":
        raise HTTPException(409, f"{t['name']} is {t['status']}.")
    g = db.one("SELECT * FROM relay.tn_access WHERE user_id = ? AND tenant_id = ? AND status = 'active' AND expires > ? ORDER BY expires DESC LIMIT 1",
               (u["id"], tid, time.time()))
    if not g:
        raise HTTPException(403, f"You have no active access to {t['name']}. Ask for it first.")
    with db.use(tid):
        if not db.user(u["id"]):
            raise HTTPException(403, "Your access to this workspace is not ready; ask for it again.")
    db.run("INSERT OR REPLACE INTO relay.tn_acting (skey, user_id, tenant_id, grant_id, since) VALUES (?, ?, ?, ?, ?)",
           (skey, u["id"], tid, g["id"], time.time()))
    db.run("UPDATE relay.tn_access SET last_used = ? WHERE id = ?", (time.time(), g["id"]))
    ctl_audit("tenancy.switch", tid, g["id"], {"role": g["role"], "until": g["expires"]})
    return {"tenant": tid, "grant": _grant_public(g)}


def sweep() -> dict:
    """Ended by time: live grants past their limit, requests nobody answered within a week; old set-up links and packs."""
    now, out = time.time(), {"expired": 0, "stale": 0}
    for g in db.q("SELECT * FROM relay.tn_access WHERE status = 'active' AND expires <= ?", (now,)):
        db.run("UPDATE relay.tn_access SET status = 'expired', ended = ?, ended_by = 'system', end_reason = 'time limit' WHERE id = ? AND status = 'active'",
               (now, g["id"]))
        _end_guest(g["tenant_id"], g["user_id"], "system")
        _tell_person(g, f"Your access to {(row(g['tenant_id']) or {}).get('name')} has ended", "The time limit was reached.")
        ctl_audit("tenancy.access_expired", g["tenant_id"], g["id"], {"person": g["user_id"]}, "system")
        out["expired"] += 1
    for g in db.q("SELECT * FROM relay.tn_access WHERE status = 'pending' AND created < ?", (now - PENDING_DAYS * 86400,)):
        db.run("UPDATE relay.tn_access SET status = 'expired', ended = ?, ended_by = 'system', end_reason = 'not answered' WHERE id = ?", (now, g["id"]))
        if row(g["tenant_id"]):
            with db.use(g["tenant_id"]):
                checkpoints.withdraw("tenancy.access", g["id"], who="system")
        out["stale"] += 1
    db.run("DELETE FROM relay.tn_setup WHERE expires < ?", (now - 7 * 86400,))
    with db.use(db.PLATFORM):                           # deployment packs are made in the platform's state folder
        try:
            for f in PACKS.glob("*.zip"):
                if f.stat().st_mtime < now - 86400:
                    f.unlink(missing_ok=True)
        except OSError:
            pass
    if out["expired"] or out["stale"]:
        _invalidate()
    return out


async def sweeper() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(sweep)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep sweeping
            traceback.print_exc()


# ------------------------------------------------------------------ hand-over

def transfer_person(uid: str, to: str, who: str) -> dict:
    """Move one person's work in the current tenant to another (dashboards and subjects, library visuals, insight pages,
    schedules) and take away what was theirs alone: shares to them, team roles, stored keys, AI settings."""
    moved = {"items": db.run("UPDATE projects SET owner_id = ? WHERE owner_id = ?", (to, uid)),
             "visuals": db.run("UPDATE library SET owner_id = ? WHERE owner_id = ?", (to, uid)),
             "pages": db.run("UPDATE pages SET owner_id = ? WHERE owner_id = ?", (to, uid)),
             "schedules": db.run("UPDATE schedules SET owner_id = ? WHERE owner_id = ?", (to, uid))}
    db.run("DELETE FROM shares WHERE principal_type = 'user' AND principal_id = ?", (uid,))
    db.run("DELETE FROM page_shares WHERE principal_type = 'user' AND principal_id = ?", (uid,))
    db.run("DELETE FROM memberships WHERE user_id = ?", (uid,))
    db.run("DELETE FROM sessions WHERE user_id = ?", (uid,))
    db.run("DELETE FROM meta WHERE key = ?", (f"ai:{uid}",))
    db.run("UPDATE users SET active = 0, deactivated = ?, deactivated_by = ? WHERE id = ?", (time.time(), who, uid))
    return moved


class HandoverIn(BaseModel):
    owner_id: str
    delivered: str = ""
    evidence: list[str] = []
    move_direct: bool = False


def handover(u: dict, tid: str, body: HandoverIn) -> dict:
    t = must(tid)
    p = partner_of(t)
    if t["kind"] != "client" or not p:
        raise HTTPException(400, "Only a partner's client is handed over.")
    if t["partner_access"] == "ended":
        raise HTTPException(409, "This client was already handed over.")
    if not (platform_admin(u) or partner_admin_of(u) == p["id"] or (db.tenant() == tid and own_admin_here(u))):
        raise HTTPException(403, "The partner's admins, the client's own admins or the platform's admins record a hand-over.")
    delivered = (body.delivered or "").strip()[:4000]
    if len(delivered) < 4:
        raise HTTPException(400, "Say what was delivered (it is kept with the hand-over record).")
    evidence = [str(e).strip()[:300] for e in body.evidence if str(e).strip()][:30]
    now, hid = time.time(), "ho-" + secrets.token_hex(5)
    with db.use(tid):
        owner = db.one("SELECT * FROM users WHERE id = ? AND active = 1 AND home_tenant IS NULL", (body.owner_id,))
        if not owner:
            raise HTTPException(400, "Choose an active person of the client to take over the work.")
        guests = [r["id"] for r in db.q("SELECT id FROM users WHERE home_tenant IS NOT NULL")]
        grants = db.q("SELECT * FROM relay.tn_access WHERE tenant_id = ? AND status IN ('active', 'pending')", (tid,))
        moved, revoked_keys = {}, {}
        with db.transaction():
            for g in grants:
                db.run("UPDATE relay.tn_access SET status = 'ended', ended = ?, ended_by = ?, end_reason = 'hand-over' WHERE id = ?",
                       (now, u["id"], g["id"]))
            db.run("DELETE FROM relay.tn_acting WHERE tenant_id = ?", (tid,))
            for gid in guests:
                moved[gid] = transfer_person(gid, owner["id"], u["id"])
            db.run("UPDATE relay.tn_tenants SET partner_access = 'ended', parent_id = ?, updated = ?, updated_by = ? WHERE id = ?",
                   (db.PLATFORM if body.move_direct else t["parent_id"], now, u["id"], tid))
            summary = {"grants_ended": len(grants), "guests": len(guests), "moved": moved, "owner": owner["email"],
                       "move_direct": body.move_direct, "partner": p["name"]}
            db.run("INSERT INTO relay.tn_handovers (id, tenant_id, partner_id, owner_id, delivered, evidence, summary, move_direct, created, created_by) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (hid, tid, p["id"], owner["id"], delivered, json.dumps(evidence), json.dumps(summary), 1 if body.move_direct else 0, now, u["id"]))
        for g in grants:
            if g["checkpoint_id"]:
                checkpoints.withdraw("tenancy.access", g["id"], who=u["id"])
        for gid in guests:                                  # stored keys are files, outside the transaction
            names = [s["name"] for s in secrets_store.names() if s["scope"] == f"user:{gid}"]
            for n in names:
                secrets_store.delete(f"user:{gid}", n, u["id"])
            revoked_keys[gid] = names
        notify.add(owner["id"], "share", f"{t['name']} was handed over to you", f"From {p['name']}: {delivered[:300]}", "#/admin/partner-access")
    summary["keys_removed"] = revoked_keys
    for g in grants:
        _tell_person(g, f"{t['name']} was handed over", "Your access ended with the hand-over.")
    with db.use(p["id"]):
        admins = [r["id"] for r in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL")]
        notify.add_many(admins, "share", f"Hand-over of {t['name']} recorded", f"{len(grants)} access grant(s) ended; work moved to {owner['email']}.", "#/tenants")
    _invalidate()
    ctl_audit("tenancy.handover", tid, hid, {"partner": p["id"], "owner": owner["email"], "grants_ended": len(grants),
                                              "guests": len(guests), "move_direct": body.move_direct, "evidence": evidence})
    return {"handover": hid, "summary": summary, "tenant": public(row(tid), True)}


def handovers(tid: str) -> list[dict]:
    out = []
    for h in db.q("SELECT * FROM relay.tn_handovers WHERE tenant_id = ? ORDER BY created DESC", (tid,)):
        h = dict(h)
        h["evidence"] = json.loads(h["evidence"] or "[]")
        h["summary"] = json.loads(h["summary"] or "{}")
        out.append(h)
    return out


# ------------------------------------------------------------------ metering, the price book, statements

def prices() -> dict:
    try:
        saved = json.loads(db.ctl_meta("prices") or "{}")
    except ValueError:
        saved = {}
    out = {**PRICES, **{k: v for k, v in saved.items() if k in PRICES}}
    out["edition_fee"] = {**PRICES["edition_fee"], **(saved.get("edition_fee") or {})}
    return out


class PricesIn(BaseModel):
    currency: str | None = None
    usd_rate: float | None = None
    edition_fee: dict[str, float] | None = None
    module_fee: float | None = None
    ai_markup_pct: float | None = None


def set_prices(u: dict, body: PricesIn) -> dict:
    if not platform_admin(u):
        raise HTTPException(403, "Only the platform's admins set the price book.")
    new = body.model_dump(exclude_none=True)
    if "currency" in new and not re.fullmatch(r"[A-Z]{3}", new["currency"]):
        raise HTTPException(400, "Currency is a three-letter code such as USD, INR or EUR.")
    if new.get("usd_rate") is not None and new["usd_rate"] <= 0:
        raise HTTPException(400, "The exchange rate must be above zero.")
    for k in ("module_fee", "ai_markup_pct"):
        if k in new and new[k] < 0:
            raise HTTPException(400, "Prices cannot be negative.")
    if "edition_fee" in new:
        if set(new["edition_fee"]) - set(EDITIONS) or any(v < 0 for v in new["edition_fee"].values()):
            raise HTTPException(400, "Edition fees are per edition (enterprise, partner, both) and not negative.")
    saved = {**prices(), **new}
    db.set_ctl_meta("prices", json.dumps(saved))
    ctl_audit("tenancy.prices", None, None, new)
    return prices()


def month_bounds(month: str | None) -> tuple[str, float, float]:
    from . import usage as costs
    return costs.month_bounds(month)


def _storage(tid: str) -> int:
    def compute():
        total = 0
        base = store.tenant_root(tid)
        for dirpath, dirnames, filenames in os.walk(base):
            if os.path.normpath(dirpath) == os.path.normpath(str(base)):
                dirnames[:] = [d for d in dirnames if d != store.TENANTS_DIR]     # the platform's tree holds the others
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total
    return _cached("storage:" + tid, 600, compute)


def usage_of(tid: str, start: float, end: float) -> dict:
    with db.use(tid):
        kinds = {r["kind"]: {"records": r["n"], "usd": round(r["usd"] or 0, 4)} for r in
                 db.q("SELECT kind, count(*) AS n, sum(cost_usd) AS usd FROM usage WHERE ts >= ? AND ts < ? GROUP BY kind", (start, end))}
        runs = db.one("SELECT count(*) AS n FROM usage WHERE kind = 'llm' AND ts >= ? AND ts < ?", (start, end))["n"]
        people = db.one("SELECT count(*) AS n FROM users WHERE active = 1 AND home_tenant IS NULL")["n"]
        items = db.one("SELECT count(*) AS n FROM projects")["n"]
    return {"cost_usd": round(sum(k["usd"] for k in kinds.values()), 4), "by_kind": kinds, "ai_runs": runs, "people": people,
            "items": items, "storage_bytes": _storage(tid)}


def statement(tid: str, month: str | None = None) -> dict:
    t = must(tid)
    label, start, end = month_bounds(month)
    pb, use = prices(), usage_of(tid, start, end)
    on = [m for m in effective(tid) if m not in CORE and m in registry.BY_ID and registry.BY_ID[m]["pl"] not in ("hidden", "platform")
          and registry.BY_ID[m]["status"] in ("available", "partly")]           # only what can be used today is billed
    rate = pb["usd_rate"]
    lines = [{"item": f"{EDITIONS[t['edition']]} edition, monthly fee", "qty": 1, "unit": pb["edition_fee"].get(t["edition"], 0.0)},
             {"item": "Modules switched on", "qty": len(on), "unit": pb["module_fee"]},
             {"item": f"AI and data usage at cost (USD {use['cost_usd']:.2f}) + {pb['ai_markup_pct']:g} %", "qty": 1,
              "unit": round(use["cost_usd"] * rate * (1 + pb["ai_markup_pct"] / 100), 2)}]
    if t["kind"] == "platform":
        lines = [lines[2]]
    for li in lines:
        li["amount"] = round(li["qty"] * li["unit"], 2)
    return {"tenant": {"id": tid, "name": t["name"], "kind": t["kind"], "parent_id": t["parent_id"]}, "month": label,
            "currency": pb["currency"], "usage": use, "modules": sorted(on), "lines": lines,
            "total": round(sum(li["amount"] for li in lines), 2)}


def rollup(u: dict, month: str | None = None) -> dict:
    ids = manageable(u)
    if not ids:
        raise HTTPException(403, "Only the platform's admins and partner admins see usage across workspaces.")
    rows = [statement(t, month) for t in ids]
    by = {r["tenant"]["id"]: r for r in rows}
    partners = []
    for r in rows:
        if r["tenant"]["kind"] == "partner":
            clients = [x for x in rows if x["tenant"]["parent_id"] == r["tenant"]["id"]]
            partners.append({"partner": r["tenant"], "own": r["total"], "clients": len(clients),
                             "clients_total": round(sum(c["total"] for c in clients), 2),
                             "ai_cost_usd": round(r["usage"]["cost_usd"] + sum(c["usage"]["cost_usd"] for c in clients), 4),
                             "total": round(r["total"] + sum(c["total"] for c in clients), 2)})
    label = rows[0]["month"] if rows else month_bounds(month)[0]
    return {"month": label, "currency": prices()["currency"], "tenants": rows, "partners": partners,
            "total": round(sum(r["total"] for r in rows), 2), "ai_cost_usd": round(sum(r["usage"]["cost_usd"] for r in rows), 4),
            "prices": prices(), "known": [t for t in by]}


def rollup_csv(u: dict, month: str | None = None) -> str:
    r = rollup(u, month)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["month", "workspace", "workspace_id", "kind", "partner", "item", "qty", "unit", "amount", "currency"])
    names = {x["tenant"]["id"]: x["tenant"]["name"] for x in r["tenants"]}
    for s in r["tenants"]:
        for li in s["lines"]:
            w.writerow([s["month"], s["tenant"]["name"], s["tenant"]["id"], s["tenant"]["kind"], names.get(s["tenant"]["parent_id"] or "", ""),
                        li["item"], li["qty"], li["unit"], li["amount"], s["currency"]])
    return out.getvalue()


# ------------------------------------------------------------------ what the shell needs

def me_info(u: dict | None) -> dict:
    if not u:
        return {}
    tz = u.get("_tenancy") or {}
    cur, h = row(tz.get("tenant") or db.PLATFORM), row(tz.get("home") or db.PLATFORM)
    brief = lambda t: {"id": t["id"], "name": t["name"], "kind": t["kind"], "edition": t["edition"]} if t else None  # noqa: E731
    return {**(brief(cur) or {}), "home": brief(h), "acting": bool(tz.get("grant")), "grant": tz.get("grant"),
            "expires": tz.get("expires"), "role": tz.get("role"), "console": console(u), "tenancy": TENANCY,
            "enter": [{"id": g["tenant_id"], "name": g["tenant_name"], "role": g["role"], "expires": g["expires"]} for g in my_grants(u)]}


# ------------------------------------------------------------------ the API

@router.get("/api/tenancy/me")
def api_me():
    return me_info(_u())


@router.post("/api/tenancy/switch")
def api_switch(request: Request, body: dict):
    return switch(_u(), request, str(body.get("tenant") or ""))


@router.post("/api/tenancy/return")
def api_return(request: Request):
    u = _u()
    return switch(u, request, home(u))


@router.get("/api/tenancy/tenants")
def api_tree():
    u = _u()
    if not console(u):
        raise HTTPException(403, "The platform console is for the platform's admins and partner admins.")
    me_row = row(home(u))
    return {"tenants": tree(u), "home": public(me_row) if me_row else None, "platform": platform_admin(u), "kinds": KINDS,
            "editions": EDITIONS, "deployments": DEPLOYMENTS, "policies": POLICIES, "roles": ROLES,
            "partners": [public(t) for t in all_rows() if t["kind"] == "partner" and t["id"] in manageable(u)]}


@router.post("/api/tenancy/tenants")
def api_create(body: TenantIn):
    return create(_u(), body)


@router.get("/api/tenancy/tenants/{tid}")
def api_overview(tid: str):
    return overview(_u(), tid)


@router.patch("/api/tenancy/tenants/{tid}")
def api_update(tid: str, body: TenantPatch):
    return update(_u(), tid, body)


@router.get("/api/tenancy/tenants/{tid}/modules")
def api_modules(tid: str):
    u = _u()
    if not may_manage(u, tid):
        raise HTTPException(404, "No such workspace.")
    return {"modules": module_states(tid)}


@router.put("/api/tenancy/tenants/{tid}/modules")
def api_set_modules(tid: str, body: dict):
    return {"modules": set_modules(_u(), tid, {str(k): bool(v) for k, v in (body.get("modules") or {}).items()})}


@router.get("/api/tenancy/tenants/{tid}/access")
def api_access(tid: str):
    u = _u()
    if not (may_manage(u, tid) or (db.tenant() == tid and own_admin_here(u))):
        raise HTTPException(404, "No such workspace.")
    return {"grants": grants_for(tid)}


@router.post("/api/tenancy/tenants/{tid}/access")
def api_grant(tid: str, body: GrantIn):
    return grant(_u(), tid, body)


@router.post("/api/tenancy/access/{gid}/revoke")
def api_revoke(gid: str, body: dict | None = None):
    return revoke(_u(), gid, str((body or {}).get("reason") or ""))


@router.get("/api/tenancy/people")
def api_people():
    """People of the caller's own workspace (to give them access to a client)."""
    u = _u()
    with db.use(home(u)):
        people = db.q("SELECT id, name, email, org_role FROM users WHERE active = 1 AND home_tenant IS NULL ORDER BY lower(name)")
    return {"people": people}


@router.post("/api/tenancy/tenants/{tid}/handover")
def api_handover(tid: str, body: HandoverIn):
    return handover(_u(), tid, body)


@router.get("/api/tenancy/tenants/{tid}/handover-people")
def api_handover_people(tid: str):
    u = _u()
    t = must(tid)
    p = partner_of(t)
    if not (platform_admin(u) or (p and partner_admin_of(u) == p["id"]) or (db.tenant() == tid and own_admin_here(u))):
        raise HTTPException(404, "No such workspace.")
    with db.use(tid):
        return {"people": db.q("SELECT id, name, email, org_role FROM users WHERE active = 1 AND home_tenant IS NULL ORDER BY lower(name)")}


@router.post("/api/tenancy/tenants/{tid}/setup-link")
def api_setup_link(tid: str, body: dict | None = None):
    return new_setup_link(_u(), tid, (body or {}).get("user_id"))


@router.get("/api/tenancy/usage")
def api_usage(month: str | None = None):
    return rollup(_u(), month)


@router.get("/api/tenancy/usage.csv")
def api_usage_csv(month: str | None = None):
    u = _u()
    text = rollup_csv(u, month)
    label = month_bounds(month)[0]
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="relay-usage-{label}.csv"'})


@router.get("/api/tenancy/prices")
def api_prices():
    u = _u()
    if not console(u):
        raise HTTPException(403, "The price book is for the platform's admins and partner admins.")
    return {"prices": prices(), "editable": platform_admin(u)}


@router.put("/api/tenancy/prices")
def api_set_prices(body: PricesIn):
    return {"prices": set_prices(_u(), body), "editable": True}


@router.get("/api/tenancy/audit")
def api_audit(tenant: str | None = None, limit: int = 200):
    u = _u()
    ids = set(manageable(u))
    if not ids:
        raise HTTPException(403, "The platform audit is for the platform's admins and partner admins.")
    if tenant and tenant not in ids:
        raise HTTPException(404, "No such workspace.")
    rows = db.q("SELECT * FROM relay.tn_audit " + ("WHERE tenant_id = ? " if tenant else "") + "ORDER BY id DESC LIMIT ?",
                ((tenant, min(limit, 500)) if tenant else (min(limit, 2000),)))
    out = []
    for r in rows:
        if r["tenant_id"] and r["tenant_id"] not in ids and not platform_admin(u):
            continue
        r = dict(r)
        r["detail"] = json.loads(r["detail"]) if r["detail"] else None
        out.append(r)
    return {"items": out[:limit]}


@router.post("/api/tenancy/tenants/{tid}/pack")
def api_pack(tid: str):
    from . import tenantmove
    u = _u()
    t = must(tid)
    if not may_manage(u, tid):
        raise HTTPException(404, "No such workspace.")
    if t["kind"] == "platform":
        raise HTTPException(400, "The platform's own workspace is this install.")
    info = tenantmove.pack(tid)
    ctl_audit("tenancy.pack", tid, info["name"], {"files": info["files"], "bytes": info["bytes"]})
    return info


@router.get("/api/tenancy/packs/{name}")
def api_pack_download(name: str):
    u = _u()
    m = re.fullmatch(r"relay-pack-([a-z][a-z0-9-]{1,30})-\d{8}-\d{6}\.zip", name)
    if not m or not may_manage(u, m.group(1)):
        raise HTTPException(404, "No such pack.")
    with db.use(db.PLATFORM):
        f = PACKS / name
        if not f.exists():
            raise HTTPException(404, "This pack has expired; make a new one.")
        path = str(f)
    return FileResponse(path, media_type="application/zip", filename=name)


@router.get("/api/admin/partner-access")
def api_partner_access():
    """Admin > Partner access (the current workspace's own admins): who from outside can act here, the policy."""
    u = _u()
    t = must(db.tenant())
    p = partner_of(t)
    return {"tenant": public(t), "partner": public(p) if p else None, "grants": grants_for(t["id"]), "handovers": handovers(t["id"]),
            "policy": t["partner_access"], "policies": POLICIES, "editable": own_admin_here(u) and t["kind"] == "client",
            "guests": _guests()}


def _guests() -> list[dict]:
    rows = db.q("SELECT id, name, email, org_role, home_tenant, active FROM users WHERE home_tenant IS NOT NULL ORDER BY active DESC, lower(name)")
    for r in rows:
        r["home_name"] = (row(r["home_tenant"]) or {}).get("name")
    return rows


@router.put("/api/admin/partner-access")
def api_set_partner_access(body: dict):
    u = _u()
    if not own_admin_here(u):
        raise HTTPException(403, "Only this workspace's own admins set the partner-access policy.")
    update(u, db.tenant(), TenantPatch(partner_access=str(body.get("policy") or "")))
    return api_partner_access()
