"""D2D Relay: organisations and credits.

An organisation is a P17 tenant of its own (a client under the platform, docs/P17-tenancy.md): its own database schema
and folders, so its dashboards, connections, branding, Ask Relay conversations and notifications are never seen by
another organisation. People are matched to it by their email domain (otp.py): the first person from a business domain
creates it and is its owner (the tenant's admin); everyone after them from that domain joins it as a BI Dev. Public and
disposable mail domains (public_domains.py) cannot sign in at all. The platform's own workspace (PASDACS, where the
platform admin works) is an organisation too, for the platform admin's domain.

Credits are pooled per organisation (relay.tn_orgs.credits); every change is a row in relay.tn_credits:
  start   the starting credits (D2D_CREDITS_START, 100)
  charge  a new dashboard (D2D_CREDITS_DASHBOARD, 30) or a change (D2D_CREDITS_CHANGE, 15): asking Relay to revise the
          plan, a change request on a prototype, building a custom visual Relay suggested, an Ask Relay answer sent to
          a dashboard
  refund  the run a charge paid for failed or was stopped before it delivered, so the credits come back (Retry charges
          again). A new dashboard is delivered with its first prototype (planning and building are both part of it);
          a change with its new plan or version.
  adjust  a platform admin added (or took back) credits, e.g. after a payment
Free: confirming the plan, asking Relay to fix failed review gates, approving and publishing, Ask Relay questions and
brand palettes. A run carries the id of the charge it delivers (job args `charge`); worker.py gives it back when the
run fails, is stopped, or is cut off by a restart.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import threading
import time
import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, notify, public_domains

router = APIRouter()

START = int(os.environ.get("D2D_CREDITS_START") or 100)
COST = {"dashboard": int(os.environ.get("D2D_CREDITS_DASHBOARD") or 30), "change": int(os.environ.get("D2D_CREDITS_CHANGE") or 15)}
WHAT = {"dashboard": "New dashboard", "change": "Change"}
CONTACT = (os.environ.get("D2D_CREDITS_CONTACT") or "info@pasdacs.com").strip()
PLATFORM_EMAIL = (os.environ.get("D2D_OTP_EMAIL") or os.environ.get("D2D_ADMIN_EMAIL") or "").strip().lower()
REQUESTS_PER_HOUR = 5
_lock = threading.RLock()                 # credits: one change at a time (the app is one process)
_create_lock = threading.Lock()           # two people of a new domain signing up at once make one organisation


class NoCredits(Exception):
    """Not enough credits for what the person asked (HTTP 402, main.py)."""


class OrgError(Exception):
    """Shown to the person as it is."""


# ---------------------------------------------------------------- domains and names

def domain_of(email: str) -> str:
    return (email or "").strip().lower().rsplit("@", 1)[-1]


def public(email_or_domain: str) -> bool:
    """A free or disposable mail address/domain (never the platform admin's own address)."""
    v = (email_or_domain or "").strip().lower()
    if "@" in v and v == PLATFORM_EMAIL:
        return False
    return public_domains.is_public(domain_of(v))


def suggested_name(domain: str) -> str:
    """acme-foods.co.uk -> Acme Foods (a starting point; the person names their organisation)."""
    labels = [x for x in (domain or "").lower().split(".") if x]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc", "gen", "biz"}:
        base = labels[-3]
    else:
        base = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", base) if w)[:80] or domain


def name_from(email: str) -> str:
    """jane.doe@acme.com -> Jane Doe (until the person says otherwise)."""
    local = (email or "").split("@", 1)[0]
    words = [w for w in re.split(r"[._+-]+", local) if w and not w.isdigit()]
    return (" ".join(w.capitalize() for w in words) or local or "New member")[:120]


# ---------------------------------------------------------------- organisations

def row(tid: str | None) -> dict | None:
    return db.one("SELECT * FROM relay.tn_orgs WHERE tenant_id = ?", (tid,)) if tid else None


def by_domain(domain: str) -> dict | None:
    return db.one("SELECT * FROM relay.tn_orgs WHERE domain = ?", ((domain or "").lower(),))


def platform_admin(u: dict | None) -> bool:
    """An admin of the platform's own workspace, working there (info@pasdacs.com): sees every organisation."""
    t = (u or {}).get("_tenancy") or {}
    return bool(u) and t.get("home") == db.PLATFORM and t.get("tenant") == db.PLATFORM and bool(t.get("home_admin")) \
        and not u.get("home_tenant")


def init() -> None:
    """At start: the platform's own workspace is an organisation too (the platform admin's domain), with its starting
    credits the first time. Idempotent."""
    with db.use(db.PLATFORM):
        if row(db.PLATFORM):
            return
        admin = db.one("SELECT email FROM users WHERE id = ?", (db.ADMIN_ID,)) or {}
        email = PLATFORM_EMAIL or (admin.get("email") or "").lower()
        domain = domain_of(email) if "@" in email else ""
        if not domain or by_domain(domain):
            print(f"[orgs] the platform workspace has no organisation (admin address {email!r})", flush=True)
            return
        t = db.one("SELECT name FROM relay.tn_tenants WHERE id = ?", (db.PLATFORM,)) or {}
        db.run("INSERT OR IGNORE INTO relay.tn_orgs (tenant_id, name, domain, owner_id, credits, setup_done, created, created_by) "
               "VALUES (?, ?, ?, ?, 0, 1, ?, 'system')", (db.PLATFORM, t.get("name") or db.PLATFORM_NAME, domain, db.ADMIN_ID, time.time()))
        _entry(db.PLATFORM, "start", START, note="Starting credits", who={})


def create(name: str, email: str, person: str) -> tuple[str, str]:
    """A new organisation for a new business domain: its tenant (schema, folders), its owner (the tenant's admin and a
    BI Dev in its Default team) and its starting credits. Returns (tenant id, owner's user id). OrgError('exists') when
    another person of the domain made it first."""
    from . import tenancy
    email = (email or "").strip().lower()
    domain = domain_of(email)
    name = " ".join((name or "").split())[:80]
    person = " ".join((person or "").split())[:120] or name_from(email)
    if len(name) < 2:
        raise OrgError("Give your organisation a name.")
    if public(email):
        raise OrgError("Use your work email address.")
    with _create_lock:
        with db.use(db.PLATFORM):
            if by_domain(domain):
                raise OrgError("exists")
            if db.one("SELECT 1 AS x FROM relay.tn_accounts WHERE email = ?", (email,)):
                raise OrgError("This email address already has an account. Sign in again.")
            tid = tenancy._slug(name)                                   # noqa: SLF001 - the console's own id rule
            now, uid = time.time(), "u-" + secrets.token_hex(6)
            db.run("INSERT INTO relay.tn_tenants (id, kind, parent_id, name, edition, status, deployment, host, partner_access, region, "
                   "notes, created, created_by, updated, updated_by) VALUES (?, 'client', ?, ?, 'enterprise', 'active', 'shared', NULL, "
                   "'open', NULL, ?, ?, 'signup', ?, 'signup')", (tid, db.PLATFORM, name, f"D2D Relay organisation ({domain})", now, now))
        try:
            db.init_tenant(tid)
            with db.use(tid):
                db.run("INSERT INTO users (id, email, name, org_role, created, local_login) VALUES (?, ?, ?, 'admin', ?, 0)",
                       (uid, email, person, now))
                db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (uid, db.DEFAULT_TEAM))
                db.run("INSERT INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)", (uid, email, tid, now))
                db.run("INSERT INTO relay.tn_orgs (tenant_id, name, domain, owner_id, credits, setup_done, created, created_by) "
                       "VALUES (?, ?, ?, ?, 0, 0, ?, ?)", (tid, name, domain, uid, now, uid))
                _entry(tid, "start", START, note="Starting credits", who={"id": uid, "name": person})
        except Exception:
            with db.use(db.PLATFORM):
                for sql in ("DELETE FROM relay.tn_credits WHERE tenant_id = ?", "DELETE FROM relay.tn_orgs WHERE tenant_id = ?",
                            "DELETE FROM relay.tn_accounts WHERE home_tenant = ?", "DELETE FROM relay.tn_tenants WHERE id = ?"):
                    db.run(sql, (tid,))
            try:
                db.drop_tenant(tid)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            raise
    tenancy._invalidate()                                               # noqa: SLF001
    tenancy.ctl_audit("d2d.org_created", tid, tid, {"name": name, "domain": domain, "owner": email}, who=uid)
    return tid, uid


def join(tid: str, email: str) -> str:
    """A new person from an organisation's domain: a BI Dev in its Default team; the owner is told. Returns their id."""
    email = (email or "").strip().lower()
    o = row(tid)
    with db.use(tid):
        old = db.one("SELECT id FROM users WHERE lower(email) = ? AND home_tenant IS NULL", (email,))
        if old:
            db.run("INSERT OR IGNORE INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)",
                   (old["id"], email, tid, time.time()))
            return old["id"]
        now, uid, name = time.time(), "u-" + secrets.token_hex(6), name_from(email)
        db.run("INSERT INTO users (id, email, name, org_role, created) VALUES (?, ?, ?, 'member', ?)", (uid, email, name, now))
        db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (uid, db.DEFAULT_TEAM))
        db.run("INSERT INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)", (uid, email, tid, now))
        db.audit("org.joined", uid, {"email": email}, uid)
        if o:
            notify.add(o["owner_id"], "share", f"{name} joined {o['name']}",
                       f"{email} signed in for the first time and joined your organisation. Credits are shared.", "#/org")
    return uid


# ---------------------------------------------------------------- credits

def _entry(tid: str, kind: str, delta: int, *, what: str | None = None, pid: str | None = None, pname: str | None = None,
           note: str | None = None, ref: str | None = None, who: dict | None = None, guard: bool = False) -> dict | None:
    """Change an organisation's credits by delta and write its ledger row, in one transaction. guard: refuse (None)
    when the balance would go below zero. who: the person (default: the one asking; {} = Relay itself)."""
    u = auth.current.get() if who is None else who
    with _lock, db.transaction():
        n = db.run("UPDATE relay.tn_orgs SET credits = credits + ? WHERE tenant_id = ?" + (" AND credits + ? >= 0" if guard else ""),
                   (delta, tid, delta) if guard else (delta, tid))
        if not n:
            return None
        bal = db.one("SELECT credits FROM relay.tn_orgs WHERE tenant_id = ?", (tid,))["credits"]
        e = {"id": "cr-" + secrets.token_hex(6), "tenant_id": tid, "ts": time.time(), "kind": kind, "delta": int(delta),
             "balance": int(bal), "what": what, "user_id": (u or {}).get("id"), "user_name": (u or {}).get("name"),
             "project_id": pid, "project_name": (pname or "")[:120] or None, "note": (note or "")[:300] or None, "ref": ref}
        db.run("INSERT INTO relay.tn_credits (id, tenant_id, ts, kind, delta, balance, what, user_id, user_name, project_id, "
               "project_name, note, ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(e.values()))
    return e


def _short(o: dict, what: str) -> str:
    noun = "A new dashboard" if what == "dashboard" else "A change"
    return f"Not enough credits. {noun} uses {COST[what]} credits and {o['name']} has {o['credits']} left. Add credits to continue."


def require(what: str) -> None:
    """Before any work starts: refuse (NoCredits) when this organisation cannot pay for `what`."""
    o = row(db.tenant())
    if o and o["credits"] < COST[what]:
        raise NoCredits(_short(o, what))


def charge(what: str, pid: str | None = None, name: str | None = None, note: str | None = None) -> str | None:
    """Take the credits for `what` from the current organisation; returns the charge id (None: no organisation here,
    nothing to pay). NoCredits when the balance is too low."""
    tid = db.tenant()
    if not row(tid):
        return None
    e = _entry(tid, "charge", -COST[what], what=what, pid=pid, pname=name, note=note, guard=True)
    if e is None:
        raise NoCredits(_short(row(tid), what))
    return e["id"]


def paid(what: str, pid: str, name: str | None, start, note: str | None = None):
    """Charge for `what`, then start the work: start(charge id or None) queues the run that delivers it. If starting
    fails, the credits are given back and the error goes on."""
    cid = charge(what, pid, name, note)
    try:
        return start(cid)
    except BaseException:
        refund(cid, "The run could not be started.")
        raise


def job_args(cid: str | None) -> dict:
    """What a charged run carries in its job args."""
    return {"charge": cid} if cid else {}


def charge_row(cid: str | None) -> dict | None:
    return db.one("SELECT * FROM relay.tn_credits WHERE id = ? AND kind = 'charge' AND tenant_id = ?", (cid, db.tenant())) if cid else None


def refunded(cid: str | None) -> bool:
    return bool(cid) and bool(db.one("SELECT 1 AS x FROM relay.tn_credits WHERE kind = 'refund' AND ref = ? AND tenant_id = ?",
                                     (cid, db.tenant())))


def refund(cid: str | None, note: str = "") -> int:
    """Give a charge back, once (the current tenant's own charges only). Returns the credits given back."""
    if not cid:
        return 0
    with _lock:
        c = charge_row(cid)
        if not c or refunded(cid):
            return 0
        e = _entry(c["tenant_id"], "refund", -c["delta"], what=c["what"], pid=c["project_id"], pname=c["project_name"],
                   note=note, ref=cid, who={})
    return -c["delta"] if e else 0


def refund_text(n: int, what: str | None) -> str:
    return (f"The {n} credits for this {'dashboard' if what == 'dashboard' else 'change'} were given back because the run "
            f"did not finish. Retry uses {n} credits again.")


def project_credits(pid: str) -> dict:
    """What a dashboard has used: its charges and refunds (newest first) and the net total."""
    rows = db.q("SELECT id, ts, kind, delta, what, user_name, note, ref FROM relay.tn_credits WHERE tenant_id = ? AND project_id = ? "
                "ORDER BY ts DESC", (db.tenant(), pid))
    return {"used": -sum(r["delta"] for r in rows), "items": rows[:50]}


def retry_cost(st: dict) -> int:
    """What pressing Retry costs: the charge of the failed run when it was given back, else nothing."""
    job = st.get("job") or {}
    c = charge_row(job.get("charge"))
    return -c["delta"] if c and st.get("status") == "error" and refunded(c["id"]) else 0


def ledger(tid: str, limit: int = 100) -> list[dict]:
    return db.q("SELECT id, ts, kind, delta, balance, what, user_name, project_id, project_name, note FROM relay.tn_credits "
                "WHERE tenant_id = ? ORDER BY ts DESC LIMIT ?", (tid, limit))


# ---------------------------------------------------------------- what the screens need

def _owner(o: dict) -> dict | None:
    with db.use(o["tenant_id"]):
        return db.one("SELECT id, name, email FROM users WHERE id = ?", (o["owner_id"],))


def me_info(u: dict | None) -> dict:
    """For /api/me: the person's organisation, its owner and credits, and whether its first-time setup is open."""
    if not u:
        return {}
    o = row(auth.tenant_of(u))
    out = {"platform_admin": platform_admin(u), "costs": COST, "contact": CONTACT}
    if not o:
        return out
    owner = u["id"] == o["owner_id"]
    return {**out, "id": o["tenant_id"], "name": o["name"], "domain": o["domain"], "credits": o["credits"], "owner": _owner(o),
            "is_owner": owner, "setup_needed": owner and not o["setup_done"]}     # only the owner sets the organisation up


def _must() -> tuple[dict, dict]:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in first.")
    o = row(db.tenant())
    if not o:
        raise HTTPException(404, "This workspace is not an organisation.")
    return u, o


def _may_manage(u: dict, o: dict) -> bool:
    return u["id"] == o["owner_id"] or platform_admin(u)


@router.get("/api/org")
def get_org():
    """The person's organisation: owner, people, credits and their history."""
    u, o = _must()
    people = db.q("SELECT id, name, email, org_role, last_login, created FROM users WHERE active = 1 AND home_tenant IS NULL "
                  "ORDER BY created")
    for p in people:
        p["owner"] = p["id"] == o["owner_id"]
    dashboards = db.one("SELECT count(*) AS n FROM projects")["n"]
    rows = ledger(o["tenant_id"])
    can_open = auth.access_map(u, list({r["project_id"] for r in rows if r["project_id"]}))   # a private dashboard is named, not linked
    for r in rows:
        r["project_open"] = bool(r["project_id"]) and r["project_id"] in can_open
    return {**me_info(u), "created": o["created"], "people": people, "dashboards": dashboards, "ledger": rows,
            "may_manage": _may_manage(u, o)}


class OrgPatch(BaseModel):
    name: str | None = None


@router.patch("/api/org")
def rename_org(body: OrgPatch):
    u, o = _must()
    if not _may_manage(u, o):
        raise HTTPException(403, "Only the organisation's owner can rename it.")
    name = " ".join((body.name or "").split())[:80]
    if len(name) < 2:
        raise HTTPException(400, "Give your organisation a name.")
    db.run("UPDATE relay.tn_orgs SET name = ? WHERE tenant_id = ?", (name, o["tenant_id"]))
    db.run("UPDATE relay.tn_tenants SET name = ?, updated = ?, updated_by = ? WHERE id = ?", (name, time.time(), u["id"], o["tenant_id"]))
    from . import tenancy
    tenancy._invalidate()                                               # noqa: SLF001
    db.audit("org.renamed", o["tenant_id"], {"from": o["name"], "to": name}, u["id"])
    return get_org()


@router.post("/api/org/setup")
def setup_done():
    """The owner finished (or skipped) the first-time setup."""
    u, o = _must()
    if u["id"] != o["owner_id"]:
        raise HTTPException(403, "Only the organisation's owner sets it up.")
    db.run("UPDATE relay.tn_orgs SET setup_done = 1 WHERE tenant_id = ?", (o["tenant_id"],))
    return me_info(u)


class CreditRequest(BaseModel):
    credits: int = 100
    message: str = ""


@router.post("/api/org/credit-request")
def credit_request(body: CreditRequest):
    """Add credits: until online payment exists, the request goes to PASDACS by email (and to the platform admins in the
    app); a platform admin adds the credits on Organisations."""
    from . import otp_mail, tenancy
    u, o = _must()
    n = int(body.credits or 0)
    if not 1 <= n <= 100000:
        raise HTTPException(400, "Ask for 1 to 100,000 credits.")
    msg = (body.message or "").strip()[:1500]
    recent = db.one("SELECT count(*) AS n FROM relay.tn_audit WHERE action = 'd2d.credit_request' AND who = ? AND ts > ?",
                    (u["id"], time.time() - 3600))["n"]
    if recent >= REQUESTS_PER_HOUR:
        raise HTTPException(429, f"You sent several requests this hour. We will answer them; for anything urgent write to {CONTACT}.")
    e = html.escape
    rows = [("Organisation", o["name"]), ("Email domain", o["domain"]), ("Workspace id", o["tenant_id"]),
            ("Requested by", f"{u.get('name') or ''} <{u.get('email') or ''}>"), ("Credits requested", f"{n:,}"),
            ("Credits now", f"{o['credits']:,}"), ("Message", msg or "(none)")]
    body_html = ("<p>A D2D Relay organisation asks for more credits.</p><table cellpadding=\"4\" style=\"border-collapse:collapse\">"
                 + "".join(f"<tr><td><b>{e(k)}</b></td><td>{e(str(v)).replace(chr(10), '<br>')}</td></tr>" for k, v in rows)
                 + "</table><p>Add them in D2D Relay under Organisations once the payment is agreed.</p>")
    sent = False
    try:
        otp_mail.send(CONTACT, f"D2D Relay: {o['name']} asks for {n:,} credits", body_html, reply_to=u.get("email"))
        sent = True
    except Exception:  # noqa: BLE001 - the request is still recorded and shown to the platform admins in the app
        traceback.print_exc()
    tenancy.ctl_audit("d2d.credit_request", o["tenant_id"], u["id"], {"credits": n, "message": msg[:500], "email": u.get("email"),
                                                                       "name": u.get("name"), "sent": sent})
    with db.use(db.PLATFORM):
        for a in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL"):
            notify.add(a["id"], "ops", f"{o['name']} asks for {n:,} credits", f"{u.get('name')} ({u.get('email')}): {msg[:300] or 'no message'}",
                       "#/orgs")
    return {"sent": sent, "contact": CONTACT}


# ---------------------------------------------------------------- platform admins: every organisation

def _admin() -> dict:
    u = auth.current.get()
    if not platform_admin(u):
        raise HTTPException(403, "Only the platform's admins see every organisation.")
    return u


@router.get("/api/admin/orgs")
def all_orgs():
    _admin()
    out = []
    for o in db.q("SELECT * FROM relay.tn_orgs ORDER BY created DESC"):
        t = db.one("SELECT status FROM relay.tn_tenants WHERE id = ?", (o["tenant_id"],)) or {}
        try:
            with db.use(o["tenant_id"]):
                people = db.one("SELECT count(*) AS n FROM users WHERE active = 1 AND home_tenant IS NULL")["n"]
                dashboards = db.one("SELECT count(*) AS n FROM projects")["n"]
                owner = db.one("SELECT name, email FROM users WHERE id = ?", (o["owner_id"],))
                last = db.one("SELECT max(last_login) AS t FROM users")["t"]
        except db.UnknownTenant:
            continue
        spent = -(db.one("SELECT coalesce(sum(delta), 0) AS s FROM relay.tn_credits WHERE tenant_id = ? AND kind IN ('charge', 'refund')",
                         (o["tenant_id"],))["s"] or 0)
        out.append({"id": o["tenant_id"], "name": o["name"], "domain": o["domain"], "credits": o["credits"], "spent": spent,
                    "owner": owner, "people": people, "dashboards": dashboards, "created": o["created"], "last_login": last,
                    "status": t.get("status"), "platform": o["tenant_id"] == db.PLATFORM})
    reqs = db.q("SELECT ts, tenant_id, detail FROM relay.tn_audit WHERE action = 'd2d.credit_request' ORDER BY id DESC LIMIT 30")
    names = {o["id"]: o["name"] for o in out}
    requests = [{"ts": r["ts"], "org": r["tenant_id"], "org_name": names.get(r["tenant_id"], r["tenant_id"]), **json.loads(r["detail"] or "{}")}
                for r in reqs]
    return {"orgs": out, "requests": requests, "costs": COST, "start": START}


class Adjust(BaseModel):
    credits: int
    note: str = ""


@router.post("/api/admin/orgs/{tid}/credits")
def adjust(tid: str, body: Adjust):
    """A platform admin adds credits to an organisation (a payment, a goodwill refund) or takes some back."""
    u = _admin()
    o = row(tid)
    if not o:
        raise HTTPException(404, "No such organisation.")
    n, note = int(body.credits or 0), " ".join((body.note or "").split())[:300]
    if not n or abs(n) > 1_000_000:
        raise HTTPException(400, "Add or remove between 1 and 1,000,000 credits.")
    if not note:
        raise HTTPException(400, "Say why (for example the payment or invoice), so the organisation's history explains it.")
    if _entry(tid, "adjust", n, note=note, guard=True) is None:
        raise HTTPException(400, f"{o['name']} has {o['credits']} credits; you cannot take away more than that.")
    from . import tenancy
    tenancy.ctl_audit("d2d.credits", tid, tid, {"credits": n, "note": note})
    with db.use(tid):
        notify.add(o["owner_id"], "ops", f"{n:+,} credits for {o['name']}", note, "#/org")
    return all_orgs()
