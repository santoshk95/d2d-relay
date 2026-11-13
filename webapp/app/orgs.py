"""D2D Relay: organisations and credits.

An organisation is a P17 tenant of its own (a client under the platform, docs/P17-tenancy.md): its own database schema
and folders, so its dashboards, connections, branding, Ask Relay conversations and notifications are never seen by
another organisation. People are matched to it by their email domain (otp.py): the first person from a business domain
creates it and is its owner (the tenant's admin); everyone after them from that domain joins it as a BI Dev. The
platform's own workspace (PASDACS, where the platform admin works) is an organisation too, for the platform admin's domain.

Personal workspaces (item 39, the user 2026-11-13: "allow gmail and all emails but no credits and request credit
options, they can only buy online"): an address at a free mail domain (Gmail, Outlook, Yahoo ...: public_domains.is_free)
gets an organisation of its own, personal = 1, whose `domain` is the full address (so nobody else ever matches it). It
holds that one person only (no Add people), starts with no credits (no starting-credit request) and cannot use Request
credits: it buys online (payments.py). A platform admin can still add credits by hand. Disposable mail cannot sign in.

Credits are pooled per organisation (relay.tn_orgs.credits); every change is a row in relay.tn_credits:
  start   the starting credits (D2D_CREDITS_START, 50)
  charge  a new dashboard (D2D_CREDITS_DASHBOARD, 25); a change (D2D_CREDITS_CHANGE, 10): asking Relay to revise the
          plan, a change request on a prototype, building a custom visual Relay suggested, an Ask Relay answer sent to
          a dashboard; Ask Relay (D2D_CREDITS_ASK, 10) for up to D2D_CREDITS_ASK_QUESTIONS (5) answered questions in
          one conversation: charged at its 1st, 6th, 11th ... question (askd_routes.py)
  refund  the run a charge paid for failed or was stopped before it delivered, so the credits come back (Retry charges
          again). A new dashboard is delivered with its first prototype (planning and building are both part of it);
          a change with its new plan or version; Ask Relay's credits with the answer.
  adjust  a platform admin added (or took back) credits: approving a request, or by hand (e.g. after a payment);
          and credits bought online with Razorpay (what = 'purchase', ref = the payment: payments.py, item 23)
Free: confirming the plan, asking Relay to fix failed review gates, approving and publishing, and brand palettes. A run
carries the id of the charge it delivers (job args `charge`); worker.py gives it back when the run fails, is stopped,
or is cut off by a restart.

Starting credits are reviewed (the user's decision, 2026-11-11: no free credits at sign-up): a new organisation starts
with none, and its "starting credits" request (purpose 'start', for START credits) waits for PASDACS, who is emailed
about every new organisation with what helps to judge it (the owner, the network and country, other organisations
from that network or on the same parent domain). Approving it (admin portal, Requests, or `python -m app.orgs approve`)
adds the credits as starting credits; declining tells the owner why. D2D_CREDITS_START_REVIEW=0 adds them at once,
as before.

More credits come from PASDACS (against abuse: anyone with a business mailbox can sign up) or are bought online once
PASDACS opens selling (payments.py). An organisation asks for them (Request credits: relay.tn_credit_requests, one
pending request at a time, also emailed to PASDACS) or writes to PASDACS; a platform admin approves the request on the
admin portal (the amount may differ) or declines it with a reason, and the organisation is told either way. A platform
admin can also add or take back credits by hand.
The public site charges and refunds, the admin portal adds: every change is one database transaction (_entry).

Connectors (relay.tn_orgs.connectors, a JSON list of connector kinds): the public side takes CSV files only. Every
connector in edition.CONNECTORS is listed for everyone, and PASDACS switches it on for one organisation at a time, on
request (Connections -> Ask PASDACS sends the request by email; a platform admin switches it on). An organisation can
add, test, query and pull from a connector only while it is on (require_connector, data_routes.py and main.py).
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
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, db, edition, notify, portal, public_domains

router = APIRouter()
db.register_control_columns("tn_orgs", {"connectors": "TEXT NOT NULL DEFAULT '[]'"})   # the connectors switched on
db.register_control_columns("tn_orgs", {"personal": "INTEGER NOT NULL DEFAULT 0"})       # item 39: one free-mail address
# what a credit request is for: 'start' (a new organisation's starting credits, made at sign-up) or 'more' (asked for)
db.register_control_columns("tn_credit_requests", {"purpose": "TEXT NOT NULL DEFAULT 'more'"})

START = int(os.environ.get("D2D_CREDITS_START") or 50)    # a new organisation's starting credits; more come on request
# 1 (default): a new organisation's starting credits wait for PASDACS's review; 0: they are added at sign-up
START_REVIEW = (os.environ.get("D2D_CREDITS_START_REVIEW") or "1").strip().lower() not in ("0", "false", "no", "off")
IST = timezone(timedelta(hours=5, minutes=30))
SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc", "gen", "biz"}


def reviews_new() -> bool:
    """Whether a new organisation's starting credits wait for PASDACS (else they are added at sign-up)."""
    return bool(START) and START_REVIEW
COST = {"dashboard": int(os.environ.get("D2D_CREDITS_DASHBOARD") or 25), "change": int(os.environ.get("D2D_CREDITS_CHANGE") or 10),
        "ask": int(os.environ.get("D2D_CREDITS_ASK") or 10)}
ASK_QUESTIONS = int(os.environ.get("D2D_CREDITS_ASK_QUESTIONS") or 5)   # the Ask Relay questions COST["ask"] pays for


def costs() -> dict:
    """What the screens show: each kind of work's credits, and how many Ask Relay questions COST["ask"] covers."""
    return {**COST, "ask_questions": ASK_QUESTIONS}
WHAT = {"dashboard": "New dashboard", "change": "Change"}
CONTACT = (os.environ.get("D2D_CREDITS_CONTACT") or "info@pasdacs.com").strip()
PLATFORM_EMAIL = (os.environ.get("D2D_OTP_EMAIL") or os.environ.get("D2D_ADMIN_EMAIL") or "").strip().lower()
REQUESTS_PER_HOUR = 5
_lock = threading.RLock()                 # credits: one change at a time in this process (and each one transaction)
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


REFUSED_TEXT = ("Use an email address you keep: throw-away inboxes (Mailinator, temp mail and the like) cannot be used "
                "for D2D Relay.")
PERSONAL_PEOPLE_TEXT = ("A personal workspace is just you. To work with colleagues, sign in with your work email: your "
                        "company gets an organisation of its own.")
PERSONAL_REQUEST_TEXT = "Personal workspaces buy credits online: use Buy credits."


def refused(email: str) -> bool:
    """A disposable (throw-away) mail address: it cannot sign in at all (never the platform admin's own address)."""
    v = (email or "").strip().lower()
    if "@" in v and v == PLATFORM_EMAIL:
        return False
    return public_domains.is_disposable(domain_of(v))


def personal_address(email: str) -> bool:
    """A free mail address (Gmail, Outlook, Yahoo ...): a personal workspace of its own, never an organisation by
    domain (item 39). Never the platform admin's own address."""
    v = (email or "").strip().lower()
    if "@" in v and v == PLATFORM_EMAIL:
        return False
    return public_domains.is_free(domain_of(v))


def is_personal(o: dict | None) -> bool:
    return bool(o) and bool(o.get("personal"))


def where(o: dict | None) -> str:
    """How an organisation is shown next to its name: @its domain, or the address of a personal workspace."""
    if not o:
        return "?"
    return f"personal, {o['domain']}" if is_personal(o) else f"@{o['domain']}"


def suggested_name(domain: str) -> str:
    """acme-foods.co.uk -> Acme Foods (a starting point; the person names their organisation)."""
    labels = [x for x in (domain or "").lower().split(".") if x]
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL:
        base = labels[-3]
    else:
        base = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", base) if w)[:80] or domain


def parent_domain(domain: str) -> str:
    """sales.acme.co.uk -> acme.co.uk, x1.example.com -> example.com: the domain a company registered (a near guess)."""
    labels = [x for x in (domain or "").lower().split(".") if x]
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


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
    """A PASDACS person on the admin portal (admin-d2d.pasdacs.com, portal.py): sees every organisation. On the public
    site nobody is, the PASDACS workspace's own owner included."""
    return portal.ADMIN and portal.is_admin(u)


def init() -> None:
    """At start: the platform's own workspace is an organisation too (the platform admin's domain), with its starting
    credits the first time, and every connector switched on (once). Idempotent."""
    with db.use(db.PLATFORM):
        if not row(db.PLATFORM):
            admin = db.one("SELECT email FROM users WHERE id = ?", (db.ADMIN_ID,)) or {}
            email = PLATFORM_EMAIL or (admin.get("email") or "").lower()
            domain = domain_of(email) if "@" in email else ""
            if not domain or by_domain(domain):
                print(f"[orgs] the platform workspace has no organisation (admin address {email!r})", flush=True)
                return
            t = db.one("SELECT name FROM relay.tn_tenants WHERE id = ?", (db.PLATFORM,)) or {}
            db.run("INSERT OR IGNORE INTO relay.tn_orgs (tenant_id, name, domain, owner_id, credits, setup_done, created, created_by) "
                   "VALUES (?, ?, ?, ?, 0, 1, ?, 'system')", (db.PLATFORM, t.get("name") or db.PLATFORM_NAME, domain, db.ADMIN_ID, time.time()))
            if START:
                _entry(db.PLATFORM, "start", START, note="Starting credits", who={})
        if not db.one("SELECT 1 AS x FROM relay.tn_meta WHERE key = 'd2d_platform_connectors'"):
            # PASDACS's own workspace may use every connector it offers (once: a platform admin may change it later)
            db.run("UPDATE relay.tn_orgs SET connectors = ? WHERE tenant_id = ? AND connectors = '[]'",
                   (json.dumps(list(edition.CONNECTORS)), db.PLATFORM))
            db.run("INSERT OR REPLACE INTO relay.tn_meta (key, value) VALUES ('d2d_platform_connectors', ?)", (str(time.time()),))


def create(name: str, email: str, person: str, seen: dict | None = None) -> tuple[str, str]:
    """A new organisation for a new business domain: its tenant (schema, folders), its owner (the tenant's admin and a
    BI Dev in its Default team) and its starting credits, or (reviews_new) its request for them, which PASDACS is
    emailed to review. A free mail address gets a personal workspace instead (item 39): keyed by the full address, no
    starting credits and no request; PASDACS hears of it through the sign-in alert. seen: where the sign-up came from
    (signin_alerts.seen). Returns (tenant id, owner's user id). OrgError('exists') when another person of the domain
    made it first (or, for a personal address, its workspace is already there)."""
    from . import tenancy
    email = (email or "").strip().lower()
    domain = domain_of(email)
    personal = personal_address(email)
    key = email if personal else domain                                 # tn_orgs.domain: unique; a personal one is the address
    name = " ".join((name or "").split())[:80]
    person = " ".join((person or "").split())[:120] or name_from(email)
    if len(name) < 2:
        raise OrgError("Give your workspace a name." if personal else "Give your organisation a name.")
    if refused(email):
        raise OrgError(REFUSED_TEXT)
    with _create_lock:
        with db.use(db.PLATFORM):
            if by_domain(key):
                raise OrgError("exists")
            if db.one("SELECT 1 AS x FROM relay.tn_accounts WHERE email = ?", (email,)):
                raise OrgError("This email address already has an account. Sign in again.")
            tid = tenancy._slug(name)                                   # noqa: SLF001 - the console's own id rule
            now, uid = time.time(), "u-" + secrets.token_hex(6)
            notes = f"D2D Relay personal workspace ({email})" if personal else f"D2D Relay organisation ({domain})"
            db.run("INSERT INTO relay.tn_tenants (id, kind, parent_id, name, edition, status, deployment, host, partner_access, region, "
                   "notes, created, created_by, updated, updated_by) VALUES (?, 'client', ?, ?, 'enterprise', 'active', 'shared', NULL, "
                   "'open', NULL, ?, ?, 'signup', ?, 'signup')", (tid, db.PLATFORM, name, notes, now, now))
        try:
            db.init_tenant(tid)
            with db.use(tid):
                db.run("INSERT INTO users (id, email, name, org_role, created, local_login) VALUES (?, ?, ?, 'admin', ?, 0)",
                       (uid, email, person, now))
                db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (uid, db.DEFAULT_TEAM))
                db.run("INSERT INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)", (uid, email, tid, now))
                db.run("INSERT INTO relay.tn_orgs (tenant_id, name, domain, owner_id, credits, setup_done, created, created_by, personal) "
                       "VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?)", (tid, name, key, uid, now, uid, 1 if personal else 0))
                if START and not START_REVIEW and not personal:
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
    seen = seen or {}
    tenancy.ctl_audit("d2d.org_created", tid, tid, {"name": name, "domain": key, "personal": personal, "owner": email,
                                                    "ip": seen.get("ip"), "country": seen.get("country")}, who=uid)
    if reviews_new() and not personal:
        try:
            _start_request(tid, uid, name, domain, person, email, seen)
        except Exception:  # noqa: BLE001 - the organisation exists; PASDACS can still add credits by hand
            traceback.print_exc()
    return tid, uid


# ---------------------------------------------------------------- a new organisation's starting credits, reviewed

def _start_request(tid: str, uid: str, name: str, domain: str, person: str, email: str, seen: dict) -> str:
    """The new organisation's starting credits wait for PASDACS: a pending request for START credits (purpose 'start'),
    the platform admins told in the app, and PASDACS emailed (in the background: a sign-up never waits for mail)."""
    from . import tenancy
    rid = "crq-" + secrets.token_hex(6)
    with db.use(db.PLATFORM):
        db.run("INSERT INTO relay.tn_credit_requests (id, tenant_id, user_id, user_name, email, credits, message, status, created, purpose) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'start')",
               (rid, tid, uid, person, email, START, "Starting credits for a new organisation", time.time()))
    tenancy.ctl_audit("d2d.credit_request", tid, rid, {"credits": START, "purpose": "start", "email": email, "name": person},
                      who=uid)
    _tell_platform(f"New organisation: {name}", f"{person} ({email}) signed up @{domain}. Review its {START:,} starting credits.",
                   "#/requests")
    threading.Thread(target=_review_mail, args=(rid, tid, name, domain, person, email, seen), daemon=True,
                     name="org-review-mail").start()
    return rid


def _review_signals(tid: str, domain: str, ip: str) -> list[tuple[str, str]]:
    """What helps PASDACS judge a new organisation: sign-in codes and organisations from the same network, and other
    organisations on the same parent domain (one company, or someone collecting starting credits with subdomains)."""
    now, out = time.time(), []
    with db.use(db.PLATFORM):
        if ip:
            codes = db.one("SELECT count(*) AS n FROM otp_codes WHERE ip = ? AND created > ?", (ip, now - 3600))["n"]
            out.append(("Sign-in codes from this network, last hour", str(codes)))
            same = []
            for r in db.q("SELECT tenant_id, detail FROM relay.tn_audit WHERE action = 'd2d.org_created' AND ts > ? AND tenant_id != ?",
                          (now - 30 * 86400, tid)):
                try:
                    d = json.loads(r["detail"] or "{}")
                except ValueError:
                    continue
                if d.get("ip") == ip:
                    at = f"personal, {d.get('domain')}" if d.get("personal") else f"@{d.get('domain') or '?'}"
                    same.append(f"{d.get('name') or r['tenant_id']} ({at})")
            out.append(("Organisations from this network, last 30 days", ", ".join(same[:10]) or "none"))
        base = parent_domain(domain)
        near = [f"{o['name']} (@{o['domain']})" for o in db.q("SELECT name, domain, personal FROM relay.tn_orgs WHERE tenant_id != ?", (tid,))
                if not o["personal"] and (o["domain"] == base or o["domain"].endswith("." + base))]
        out.append((f"Other organisations on {base}", ", ".join(near[:10]) or "none"))
    return out


def _review_mail(rid: str, tid: str, name: str, domain: str, person: str, email: str, seen: dict) -> None:
    from . import otp
    try:
        rows = [("Organisation", name), ("Email domain", f"@{domain}"), ("Workspace id", tid), ("Owner", f"{person} <{email}>"),
                ("Starting credits to approve", f"{START:,}"),
                ("Signed up", datetime.fromtimestamp(seen.get("at") or time.time(), IST).strftime("%Y-%m-%d %H:%M IST")),
                ("Network", (seen.get("ip") or "?") + (f" - {seen['country']}" if seen.get("country") else ""))]
        rows += _review_signals(tid, domain, seen.get("ip") or "")
        rows.append(("Browser", seen.get("agent") or "?"))
        subject = f"D2D Relay: new organisation {name} (@{domain}), review its starting credits"
        intro = (f"{name} signed up for D2D Relay. It has no credits until you approve its {START:,} starting credits; "
                 "nothing is added before that.")
        outro = ("Approve it (the credits are added at once and the owner is emailed) or decline it with the reason they are "
                 "told, on the D2D Relay admin portal under Requests.")
        if otp.configured():
            sent = _to_pasdacs(subject, intro, rows, email, outro)
        else:                                               # a test install: the log instead
            print(f"[org-review] to {CONTACT}: {subject} | " + " | ".join(f"{k}: {v}" for k, v in rows), flush=True)
            sent = False
        with db.use(db.PLATFORM):
            db.run("UPDATE relay.tn_credit_requests SET emailed = ? WHERE id = ?", (1 if sent else 0, rid))
    except Exception:  # noqa: BLE001 - the request is on the admin portal either way
        traceback.print_exc()


# Item 32 (the user, 2026-11-12): everyone at an organisation's domain joins it, so an address an owner removed is kept
# on the organisation's blocked list (its meta table: blocked:<address>) until an owner unblocks it or adds it back.
# Deleting your own account does not block you.
def is_blocked(tid: str, email: str) -> bool:
    with db.use(tid):
        return db.meta(f"blocked:{(email or '').strip().lower()}") is not None


def block(email: str, by: str) -> None:
    """In the organisation's own workspace (the request's)."""
    db.set_meta(f"blocked:{(email or '').strip().lower()}", json.dumps({"when": time.time(), "by": by}))


def unblock(email: str) -> bool:
    return bool(db.run("DELETE FROM meta WHERE key = ?", (f"blocked:{(email or '').strip().lower()}",)))


def blocked_list() -> list[dict]:
    out = []
    for r in db.q("SELECT key, value FROM meta WHERE key LIKE 'blocked:%' ORDER BY key"):
        try:
            v = json.loads(r["value"] or "{}")
        except ValueError:
            v = {}
        out.append({"email": r["key"][len("blocked:"):], "when": v.get("when")})
    return out


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
            for oid in owner_ids():
                notify.add(oid, "share", f"{name} joined {o['name']}",
                           f"{email} signed in for the first time and joined your organisation. Credits are shared.", "#/org")
    return uid


def owner_ids() -> list[str]:
    """The current workspace's owners (people management: an organisation can have several; its admins)."""
    return [r["id"] for r in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1 AND home_tenant IS NULL")]


# ---------------------------------------------------------------- connectors (switched on per organisation by PASDACS)

def connectors_of(tid: str | None) -> list[str]:
    """The connectors switched on for an organisation, in the order they are listed (none: CSV files only)."""
    o = row(tid)
    try:
        on = set(json.loads((o or {}).get("connectors") or "[]"))
    except (TypeError, ValueError):
        on = set()
    return [k for k in edition.CONNECTORS if k in on]


def connector_on(kind: str | None, tid: str | None = None) -> bool:
    return bool(kind) and kind in connectors_of(tid or db.tenant())


def connector_label(kind: str | None) -> str:
    from . import connectors
    return (connectors.KINDS.get(kind or "") or {}).get("label") or kind or "This connector"


def require_connector(kind: str | None) -> None:
    """Before a connection is added, tested, queried or pulled from: refused (403) unless PASDACS switched its
    connector on for this organisation."""
    if not connector_on(kind):
        o = row(db.tenant()) or {}
        raise HTTPException(403, f"{connector_label(kind)} is not switched on for {o.get('name') or 'your organisation'}. "
                                 f"Your own warehouse or database comes as a turnkey deployment by PASDACS: ask on the Connections page, "
                                 f"or write to {CONTACT}.")


def _to_pasdacs(subject: str, intro: str, rows: list[tuple[str, str]], reply_to: str | None, outro: str = "") -> bool:
    """A request to PASDACS by email (CONTACT, through the sign-in mailbox), Reply-To the person. False: not sent."""
    from . import otp_mail
    e = html.escape
    body = (f"<p>{e(intro)}</p><table cellpadding=\"4\" style=\"border-collapse:collapse\">"
            + "".join(f"<tr><td><b>{e(k)}</b></td><td>{e(str(v)).replace(chr(10), '<br>')}</td></tr>" for k, v in rows)
            + "</table>" + (f"<p>{e(outro)}</p>" if outro else ""))
    try:
        otp_mail.send(CONTACT, subject, body, reply_to=reply_to)
        return True
    except Exception:  # noqa: BLE001 - the request is still recorded and shown to the platform admins in the app
        traceback.print_exc()
        return False


def _tell_platform(title: str, text: str, link: str) -> None:
    """A notification for every PASDACS person (the admin portal's people: portal.ADMIN_DOMAINS)."""
    with db.use(db.PLATFORM):
        for a in db.q("SELECT id, email FROM users WHERE active = 1 AND home_tenant IS NULL"):
            if portal.admin_email(a["email"]):
                notify.add(a["id"], "ops", title, text, link)


def _tell_owners(tid: str, title: str, text: str, link: str) -> None:
    """A notification for every owner of the organisation."""
    if not row(tid):
        return
    with db.use(tid):
        for oid in owner_ids():
            notify.add(oid, "ops", title, text, link)


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
    uses = (f"Ask Relay uses {COST['ask']} credits for up to {ASK_QUESTIONS} questions" if what == "ask" else
            f"{'A new dashboard' if what == 'dashboard' else 'A change'} uses {COST[what]} credits")
    p = _pending(o["tenant_id"])
    if p and p.get("purpose") == "start":
        return (f"Not enough credits. {uses}, and {o['name']} has none yet: PASDACS is reviewing your new organisation and adds "
                f"its {int(p['credits']):,} starting credits when it approves. You will get an email.")
    from . import payments
    if is_personal(o):                                  # item 39: personal workspaces only buy
        more = ("Buy credits to continue." if payments.offer(None, o)["on"]
                else f"Buying credits online is not open right now; write to {CONTACT}.")
        return f"Not enough credits. {uses} and your workspace has {o['credits']} left. {more}"
    more = ("Buy credits, or ask PASDACS for some (Request credits), to continue." if payments.offer(None, o)["on"]
            else "Ask PASDACS for credits (Request credits) to continue.")
    return f"Not enough credits. {uses} and {o['name']} has {o['credits']} left. {more}"


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
    out = {"platform_admin": platform_admin(u), "portal": portal.NAME, "costs": costs(), "contact": CONTACT}
    if not o:
        return out
    primary = u["id"] == o["owner_id"]
    return {**out, "id": o["tenant_id"], "name": o["name"], "domain": o["domain"], "credits": o["credits"], "owner": _owner(o),
            "personal": is_personal(o),                                           # item 39: one free-mail address, buys only
            "is_owner": is_owner(u), "is_primary": primary,                       # people management: several owners, one main
            "setup_needed": primary and not o["setup_done"],                      # only the main owner sets the organisation up
            "connectors": connectors_of(o["tenant_id"]),                          # none: CSV files only
            "pending_request": _pending(o["tenant_id"]),                          # credits asked for, not answered yet
            "pay": _pay_offer(u, o)}                                              # buying credits online (payments.py)


def _pay_offer(u: dict, o: dict) -> dict:
    from . import payments
    try:
        return payments.offer(u, o)
    except Exception:  # noqa: BLE001 - /api/me must answer even if the payment settings cannot be read
        traceback.print_exc()
        return {"on": False, "can": False}


def _pending(tid: str) -> dict | None:
    """The organisation's credit request that PASDACS has not answered yet (there is at most one)."""
    return db.one("SELECT id, credits, created, user_name, purpose FROM relay.tn_credit_requests WHERE tenant_id = ? "
                  "AND status = 'pending' ORDER BY created DESC LIMIT 1", (tid,))


def _requests_of(tid: str, limit: int = 20) -> list[dict]:
    return db.q("SELECT id, credits, message, status, created, user_id, user_name, decided, decided_name, granted, note, purpose "
                "FROM relay.tn_credit_requests WHERE tenant_id = ? ORDER BY created DESC LIMIT ?", (tid, limit))


def _must() -> tuple[dict, dict]:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in first.")
    o = row(db.tenant())
    if not o:
        raise HTTPException(404, "This workspace is not an organisation.")
    return u, o


def is_owner(u: dict | None) -> bool:
    """One of the organisation's owners: its admins, in their own workspace (never a guest row)."""
    return bool(u) and u.get("org_role") == "admin" and not u.get("home_tenant") and bool(u.get("active", 1))


def _may_manage(u: dict, o: dict) -> bool:
    return is_owner(u) or platform_admin(u)


@router.get("/api/org")
def get_org():
    """The person's organisation: its owners and people, credits and their history, credit requests. Owners also get
    the people they removed (to add them back)."""
    u, o = _must()
    everyone = db.q("SELECT id, name, email, org_role, active, last_login, created, deactivated FROM users WHERE home_tenant IS NULL "
                    "ORDER BY created")
    for p in everyone:
        p["owner"], p["primary"] = p["org_role"] == "admin", p["id"] == o["owner_id"]
    people = [p for p in everyone if p["active"]]
    removed = [p for p in everyone if not p["active"] and not str(p["email"]).endswith("@deleted.invalid")] if _may_manage(u, o) else []
    blocked = blocked_list() if _may_manage(u, o) else []
    dashboards = db.one("SELECT count(*) AS n FROM projects")["n"]
    rows = ledger(o["tenant_id"])
    can_open = auth.access_map(u, list({r["project_id"] for r in rows if r["project_id"]}))   # a private dashboard is named, not linked
    for r in rows:
        r["project_open"] = bool(r["project_id"]) and r["project_id"] in can_open
    return {**me_info(u), "created": o["created"], "people": people, "removed": removed, "blocked": blocked, "dashboards": dashboards, "ledger": rows,
            "may_manage": _may_manage(u, o), "requests": _requests_of(o["tenant_id"])}


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


# ---------------------------------------------------------------- people (the organisation's owners manage them)

PEOPLE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PEOPLE_PER_HOUR = 30                    # people one owner may add in an hour (each one is emailed an invitation)


def _must_owner() -> tuple[dict, dict]:
    u, o = _must()
    if not is_owner(u):
        raise HTTPException(403, "Only the organisation's owners manage its people.")
    return u, o


def _person(uid: str) -> dict:
    p = db.one("SELECT * FROM users WHERE id = ? AND home_tenant IS NULL AND active = 1", (uid,))
    if not p:
        raise HTTPException(404, "There is no such person in this organisation.")
    return p


def _invite_mail(email: str, name: str, by: dict, o: dict, role: str) -> bool:
    """Tell a person they were added (best effort: they can sign in anyway, with their email address)."""
    from . import identity, otp_mail
    url = identity.PUBLIC_URL or "D2D Relay"
    lines = [f"Hello {name},", f"{by.get('name') or 'A colleague'} added you to {o['name']} on D2D Relay"
             + (", as one of its owners." if role == "admin" else "."),
             "D2D Relay (D2D: Data to Decision, a Relay Platform product) turns your CSV files into checked Power BI dashboards.",
             f"Sign in at {url} with {email}: we email you a 6-digit code, no password needed.",
             f"D2D Relay - a Relay Platform product by PASDACS - {CONTACT}"]
    try:
        otp_mail.send(email, f"You were added to {o['name']} on D2D Relay", "".join(f"<p>{html.escape(x)}</p>" for x in lines),
                      reply_to=by.get("email"))
        return True
    except Exception:  # noqa: BLE001 - they can still sign in; the owner is told it was not emailed
        traceback.print_exc()
        return False


class PersonAdd(BaseModel):
    email: str = ""
    role: str = "member"                # member | owner


@router.post("/api/org/people")
def add_person(body: PersonAdd):
    """An owner adds someone from the organisation's own email domain (or adds back someone they removed), as a member
    or an owner. They are emailed an invitation; they sign in with a code like everyone else."""
    u, o = _must_owner()
    if is_personal(o):                                          # item 39: a personal workspace is its one person
        raise HTTPException(403, PERSONAL_PEOPLE_TEXT)
    email = (body.email or "").strip().lower()
    role = {"owner": "admin", "member": "member"}.get((body.role or "member").strip().lower())
    if not role:
        raise HTTPException(400, "The role is owner or member.")
    if not PEOPLE_EMAIL.match(email):
        raise HTTPException(400, "Type their email address.")
    if domain_of(email) != o["domain"]:
        raise HTTPException(400, f"Only @{o['domain']} addresses can join {o['name']}.")
    if db.one("SELECT count(*) AS n FROM audit WHERE action = 'org.person_added' AND who = ? AND ts > ?",
              (u["id"], time.time() - 3600))["n"] >= PEOPLE_PER_HOUR:
        raise HTTPException(429, f"You added {PEOPLE_PER_HOUR} people this hour. Add the others a little later.")
    acct = db.one("SELECT home_tenant FROM relay.tn_accounts WHERE email = ?", (email,))
    if acct and acct["home_tenant"] != o["tenant_id"]:
        raise HTTPException(409, "This address already belongs to another organisation on D2D Relay.")
    old = db.one("SELECT * FROM users WHERE lower(email) = ? AND home_tenant IS NULL", (email,))
    if old and old["active"]:
        raise HTTPException(409, f"{old['name']} is already in {o['name']}.")
    if unblock(email):                                          # item 32: an owner adding them back lifts the block
        db.audit("org.person_unblocked", None, {"by_adding": True}, u["id"])
    now = time.time()
    if old:                                                     # someone an owner removed earlier: back in
        uid, name = old["id"], old["name"]
        db.run("UPDATE users SET active = 1, deactivated = NULL, deactivated_by = NULL, org_role = ? WHERE id = ?", (role, uid))
        db.run("INSERT OR IGNORE INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (uid, db.DEFAULT_TEAM))
        db.run("INSERT OR IGNORE INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)", (uid, email, o["tenant_id"], now))
    else:
        uid, name = "u-" + secrets.token_hex(6), name_from(email)
        db.run("INSERT INTO users (id, email, name, org_role, created) VALUES (?, ?, ?, ?, ?)", (uid, email, name, role, now))
        db.run("INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (uid, db.DEFAULT_TEAM))
        db.run("INSERT INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)", (uid, email, o["tenant_id"], now))
    db.audit("org.person_added", uid, {"email": email, "role": role, "back": bool(old)}, u["id"])
    invited = _invite_mail(email, name, u, o, role)
    return {**get_org(), "added": {"id": uid, "name": name, "email": email, "back": bool(old), "invited": invited}}


class PersonPatch(BaseModel):
    role: str = ""


@router.patch("/api/org/people/{uid}")
def change_role(uid: str, body: PersonPatch):
    """An owner makes someone an owner, or an owner a member again (never the main owner: hand that over first)."""
    u, o = _must_owner()
    p = _person(uid)
    role = {"owner": "admin", "member": "member"}.get((body.role or "").strip().lower())
    if not role:
        raise HTTPException(400, "The role is owner or member.")
    if role == p["org_role"]:
        return get_org()
    if role == "member" and p["id"] == o["owner_id"]:
        raise HTTPException(409, f"{p['name']} is the main owner. Hand the main ownership to someone else first (Transfer ownership).")
    db.run("UPDATE users SET org_role = ? WHERE id = ?", (role, uid))
    db.audit("org.role", uid, {"email": p["email"], "role": role}, u["id"])
    if uid != u["id"]:
        notify.add(uid, "share", f"You are {'an owner' if role == 'admin' else 'a member'} of {o['name']}",
                   f"{u.get('name')} changed your role." + (" Owners manage the people, the organisation and its credit requests."
                                                             if role == "admin" else ""), "#/org")
    return get_org()


@router.delete("/api/org/people/{uid}")
def remove_person(uid: str):
    """An owner removes someone (or leaves): the account is deleted at once (the user's decision, 2026-11-12;
    governance.delete_person). Their dashboards stay with the organisation, held by the main owner and marked as made
    by a former member. The main owner hands the main ownership over first."""
    from . import governance
    u, o = _must_owner()
    p = _person(uid)
    if p["id"] == o["owner_id"]:
        raise HTTPException(409, f"{p['name']} is the main owner and cannot be removed. Hand the main ownership to someone else first.")
    governance.delete_person(uid, u["id"])
    if uid == u["id"]:                                          # leaving: no block
        return {"signed_out": True}
    block(p["email"], u["id"])                                  # item 32: they cannot rejoin until an owner unblocks them
    db.audit("org.person_blocked", None, {}, u["id"])
    return get_org()


class Unblock(BaseModel):
    email: str = ""


@router.post("/api/org/unblock")
def unblock_address(body: Unblock):
    """An owner lifts the block on an address (item 32): it can join the organisation again, as a new person."""
    u, o = _must_owner()
    if not unblock(body.email):
        raise HTTPException(404, "That address is not blocked.")
    db.audit("org.person_unblocked", None, {}, u["id"])
    return get_org()


class Confirm(BaseModel):
    confirm: str = ""


@router.post("/api/me/delete")
def delete_my_account(body: Confirm):
    """Delete my account: at once, after typing DELETE (the user's decision, 2026-11-12). The main owner hands the main
    ownership over first, or deletes the whole organisation."""
    from . import governance
    u, o = _must()
    if u.get("home_tenant"):
        raise HTTPException(400, "This is a guest visit; your account is in your own organisation.")
    if (body.confirm or "").strip().upper() != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm.")
    if u["id"] == o["owner_id"]:
        raise HTTPException(409, "You are the main owner: hand the main ownership to someone else first (Transfer ownership), "
                                 "or delete the whole organisation.")
    governance.delete_person(u["id"], u["id"])
    _tell_owners(o["tenant_id"], "Someone deleted their account", "A person in your organisation deleted their account. Their "
                 "dashboards stay, held by the main owner and marked as made by a former member.", "#/org")
    return {"signed_out": True}


@router.post("/api/org/delete")
def delete_organisation(body: Confirm):
    """The main owner deletes the whole organisation at once, after typing its name (the user's decision, 2026-11-12;
    governance.erase_org: payments and their invoices stay without names, as the law requires)."""
    from . import governance
    u, o = _must()
    if u["id"] != o["owner_id"] or u.get("home_tenant"):
        raise HTTPException(403, "Only the main owner can delete the organisation.")
    if " ".join((body.confirm or "").split()).lower() != " ".join(o["name"].split()).lower():
        raise HTTPException(400, f"Type the organisation's name, {o['name']}, to confirm.")
    out = governance.erase_org(o["tenant_id"], u["id"])
    _tell_platform(f"{o['name']} deleted itself", f"The main owner deleted {o['name']} ({where(o)}): {out['people']} people, "
                   f"{out['dashboards']} dashboards. Its payments and invoices stay, without names.", "#/orgs")
    return {"erased": True, "signed_out": True}


class Transfer(BaseModel):
    uid: str
    stay_owner: bool = True


@router.post("/api/org/transfer")
def transfer_ownership(body: Transfer):
    """The main owner hands the main ownership to someone else in the organisation, who becomes an owner too; the
    previous main owner stays an owner unless they say otherwise."""
    from . import tenancy
    u, o = _must()
    if u["id"] != o["owner_id"]:
        raise HTTPException(403, "Only the main owner can hand over the main ownership.")
    p = _person(body.uid)
    if p["id"] == u["id"]:
        raise HTTPException(400, "Choose someone else.")
    with db.transaction():
        db.run("UPDATE users SET org_role = 'admin' WHERE id = ?", (p["id"],))
        db.run("UPDATE relay.tn_orgs SET owner_id = ? WHERE tenant_id = ?", (p["id"], o["tenant_id"]))
        if not body.stay_owner:
            db.run("UPDATE users SET org_role = 'member' WHERE id = ?", (u["id"],))
    tenancy.ctl_audit("d2d.owner_transferred", o["tenant_id"], p["id"], {"from": u["id"], "to": p["id"], "stay_owner": body.stay_owner})
    notify.add(p["id"], "share", f"You are now the main owner of {o['name']}",
               f"{u.get('name')} handed the main ownership of {o['name']} to you.", "#/org")
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
    """Request credits: PASDACS approves every one (the admin portal's Requests). One pending request per organisation;
    it also goes to PASDACS by email, Reply-To the person, and to the platform admins' notifications."""
    from . import tenancy
    u, o = _must()
    if is_personal(o):                                          # item 39: personal workspaces only buy
        raise HTTPException(403, PERSONAL_REQUEST_TEXT)
    n = int(body.credits or 0)
    if not 1 <= n <= 100000:
        raise HTTPException(400, "Ask for 1 to 100,000 credits.")
    msg = (body.message or "").strip()[:1500]
    waiting = _pending(o["tenant_id"])
    if waiting and waiting.get("purpose") == "start":
        raise HTTPException(409, f"PASDACS is reviewing {o['name']} and adds its {waiting['credits']:,} starting credits when it "
                                 f"approves; you will get an email. For anything urgent, write to {CONTACT}.")
    if waiting:
        raise HTTPException(409, f"{waiting['user_name'] or 'Someone'} already asked PASDACS for {waiting['credits']:,} credits for "
                                 f"{o['name']}, and the answer is on its way. Withdraw that request first to ask for a different amount.")
    _not_too_many(u, "d2d.credit_request")
    rid = "crq-" + secrets.token_hex(6)
    db.run("INSERT INTO relay.tn_credit_requests (id, tenant_id, user_id, user_name, email, credits, message, status, created) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)", (rid, o["tenant_id"], u["id"], u.get("name"), u.get("email"), n, msg or None, time.time()))
    rows = [("Organisation", o["name"]), ("Email domain", o["domain"]), ("Workspace id", o["tenant_id"]),
            ("Requested by", f"{u.get('name') or ''} <{u.get('email') or ''}>"), ("Credits requested", f"{n:,}"),
            ("Credits now", f"{o['credits']:,}"), ("Message", msg or "(none)")]
    sent = _to_pasdacs(f"D2D Relay: {o['name']} asks for {n:,} credits", "A D2D Relay organisation asks for credits.", rows,
                       u.get("email"), "Approve or decline it on the D2D Relay admin portal, under Requests.")
    db.run("UPDATE relay.tn_credit_requests SET emailed = ? WHERE id = ?", (1 if sent else 0, rid))
    tenancy.ctl_audit("d2d.credit_request", o["tenant_id"], rid, {"credits": n, "message": msg[:500], "email": u.get("email"),
                                                                  "name": u.get("name"), "sent": sent})
    _tell_platform(f"{o['name']} asks for {n:,} credits", f"{u.get('name')} ({u.get('email')}): {msg[:300] or 'no message'}", "#/requests")
    return {"sent": sent, "contact": CONTACT, "request": _pending(o["tenant_id"])}


@router.post("/api/org/credit-request/{rid}/withdraw")
def withdraw_request(rid: str):
    """The person who asked, or the owner, takes back a request PASDACS has not answered yet."""
    from . import tenancy
    u, o = _must()
    r = db.one("SELECT * FROM relay.tn_credit_requests WHERE id = ? AND tenant_id = ?", (rid, o["tenant_id"]))
    if not r:
        raise HTTPException(404, "No such request.")
    if r["user_id"] != u["id"] and not _may_manage(u, o):
        raise HTTPException(403, "Only the person who asked, or the owner, can withdraw it.")
    if not db.run("UPDATE relay.tn_credit_requests SET status = 'withdrawn', decided = ?, decided_by = ?, decided_name = ? "
                  "WHERE id = ? AND status = 'pending'", (time.time(), u["id"], u.get("name"), rid)):
        raise HTTPException(409, "PASDACS has already answered this request.")
    tenancy.ctl_audit("d2d.credit_withdrawn", o["tenant_id"], rid, {"credits": r["credits"]})
    return {"requests": _requests_of(o["tenant_id"]), "pending_request": None}


def _not_too_many(u: dict, action: str) -> None:
    """At most REQUESTS_PER_HOUR requests of one kind an hour per person."""
    recent = db.one("SELECT count(*) AS n FROM relay.tn_audit WHERE action = ? AND who = ? AND ts > ?",
                    (action, u["id"], time.time() - 3600))["n"]
    if recent >= REQUESTS_PER_HOUR:
        raise HTTPException(429, f"You sent several requests this hour. We will answer them; for anything urgent write to {CONTACT}.")


@router.get("/api/org/connectors")
def org_connectors():
    """Every connector D2D Relay offers, and which ones PASDACS has switched on for this organisation."""
    u, o = _must()
    on = set(connectors_of(o["tenant_id"]))
    return {"connectors": [{"kind": k, "label": connector_label(k), "note": note, "on": k in on} for k, note in edition.CONNECTORS.items()],
            "contact": CONTACT, "org": o["name"]}


class ConnectorRequest(BaseModel):
    kinds: list[str] = []
    message: str = ""


@router.post("/api/org/connector-request")
def connector_request(body: ConnectorRequest):
    """Ask PASDACS to connect a warehouse or database for this organisation: by email, and in the platform admins'
    notifications; a platform admin switches the connector on (Organisations)."""
    from . import tenancy
    u, o = _must()
    kinds = [k for k in edition.CONNECTORS if k in set(body.kinds or [])]
    if not kinds or len(kinds) != len(set(body.kinds or [])):
        raise HTTPException(400, "Choose the connectors you need from the list.")
    msg = (body.message or "").strip()[:1500]
    _not_too_many(u, "d2d.connector_request")
    names = ", ".join(connector_label(k) for k in kinds)
    on = connectors_of(o["tenant_id"])
    rows = [("Organisation", o["name"]), ("Personal address" if is_personal(o) else "Email domain", o["domain"]), ("Workspace id", o["tenant_id"]),
            ("Requested by", f"{u.get('name') or ''} <{u.get('email') or ''}>"), ("Connectors requested", names),
            ("Switched on now", ", ".join(connector_label(k) for k in on) or "none (CSV files only)"), ("Message", msg or "(none)")]
    sent = _to_pasdacs(f"D2D Relay: {o['name']} asks to connect {names}", "A D2D Relay organisation asks PASDACS to connect its own "
                       "warehouse or database: a turnkey deployment.", rows, u.get("email"),
                       "Agree the turnkey deployment with them; on the shared site, a connector can still be switched on for the organisation on the D2D Relay admin portal (Organisations, Connectors).")
    tenancy.ctl_audit("d2d.connector_request", o["tenant_id"], u["id"], {"kinds": kinds, "message": msg[:500], "email": u.get("email"),
                                                                          "name": u.get("name"), "sent": sent})
    _tell_platform(f"{o['name']} asks to connect {names}", f"{u.get('name')} ({u.get('email')}): {msg[:300] or 'no message'}", "#/requests")
    return {"sent": sent, "contact": CONTACT}


# D2D Relay (2026-11-12): Migration D2D, "Migrate any Dashboard to Dashboard". Not self-service yet: an organisation tells
# PASDACS which BI tools its dashboards are in and where they should go, and PASDACS switches it on with them. The same
# ids are listed on the page (39-migration.js).
BI_TOOLS = {"cognos": "IBM Cognos Analytics", "qlik": "Qlik Sense or QlikView", "looker": "Looker", "powerbi": "Power BI",
            "tableau": "Tableau", "microstrategy": "MicroStrategy", "businessobjects": "SAP BusinessObjects",
            "ssrs": "SQL Server Reporting Services", "other": "Another tool"}


class MigrationRequest(BaseModel):
    source: list[str] = []          # BI_TOOLS ids: where the dashboards are now
    target: list[str] = []          # and where they should go
    dashboards: int | None = None   # roughly how many
    message: str = ""


@router.post("/api/org/migration-request")
def migration_request(body: MigrationRequest):
    """Ask PASDACS about Migration D2D: by email (Reply-To the person), in the platform admins' notifications and on
    the admin portal's Requests page."""
    from . import tenancy
    u, o = _must()
    pick = lambda ids: [k for k in BI_TOOLS if k in set(ids or [])]          # noqa: E731
    src, dst = pick(body.source), pick(body.target)
    if not src or not dst or len(src) != len(set(body.source)) or len(dst) != len(set(body.target)):
        raise HTTPException(400, "Choose the tools your dashboards are in now and the ones they should move to.")
    n = body.dashboards if isinstance(body.dashboards, int) and 0 < body.dashboards <= 100000 else None
    msg = (body.message or "").strip()[:1500]
    _not_too_many(u, "d2d.migration_request")
    names = lambda ids: ", ".join(BI_TOOLS[k] for k in ids)                 # noqa: E731
    rows = [("Organisation", o["name"]), ("Personal address" if is_personal(o) else "Email domain", o["domain"]), ("Workspace id", o["tenant_id"]),
            ("Requested by", f"{u.get('name') or ''} <{u.get('email') or ''}>"), ("Moving from", names(src)),
            ("Moving to", names(dst)), ("Dashboards, roughly", f"{n:,}" if n else "not given"), ("Message", msg or "(none)")]
    sent = _to_pasdacs(f"D2D Relay: {o['name']} asks about Migration D2D ({names(src)} to {names(dst)})",
                       "A D2D Relay organisation would like to move its dashboards from one BI tool to another with Migration D2D.",
                       rows, u.get("email"), "Reply to them to agree what moves and when; PASDACS switches Migration D2D on with them.")
    tenancy.ctl_audit("d2d.migration_request", o["tenant_id"], u["id"], {"source": src, "target": dst, "dashboards": n,
                                                                          "message": msg[:500], "email": u.get("email"),
                                                                          "name": u.get("name"), "sent": sent})
    _tell_platform(f"{o['name']} asks about Migration D2D",
                   f"{u.get('name')} ({u.get('email')}): {names(src)} to {names(dst)}. {msg[:200]}".strip(), "#/requests")
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
        out.append({"id": o["tenant_id"], "name": o["name"], "domain": o["domain"], "personal": is_personal(o), "credits": o["credits"], "spent": spent,
                    "owner": owner, "people": people, "dashboards": dashboards, "created": o["created"], "last_login": last,
                    "status": t.get("status"), "platform": o["tenant_id"] == db.PLATFORM, "connectors": connectors_of(o["tenant_id"]),
                    "pending": _pending(o["tenant_id"])})
    return {"orgs": out, "catalogue": [{"kind": k, "label": connector_label(k)} for k in edition.CONNECTORS], "costs": costs(), "start": START,
            "review": reviews_new()}


def _asked(action: str) -> list[dict]:
    """The latest requests of one kind (audited when they were sent), newest first, with the organisation's name."""
    names = {o["tenant_id"]: o["name"] for o in db.q("SELECT tenant_id, name FROM relay.tn_orgs")}
    rows = db.q("SELECT ts, tenant_id, detail FROM relay.tn_audit WHERE action = ? ORDER BY id DESC LIMIT 50", (action,))
    return [{"ts": r["ts"], "org": r["tenant_id"], "org_name": names.get(r["tenant_id"], r["tenant_id"]), **json.loads(r["detail"] or "{}")}
            for r in rows]


@router.get("/api/admin/requests")
def all_requests():
    """Credit requests (pending first, then the latest answers) and connector requests from every organisation (the
    admin portal's Requests page)."""
    _admin()
    names = {o["tenant_id"]: (o["name"], o["credits"]) for o in db.q("SELECT tenant_id, name, credits FROM relay.tn_orgs")}
    rows = db.q("SELECT * FROM relay.tn_credit_requests ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, created DESC LIMIT 100")
    credits = [{**r, "org_name": names.get(r["tenant_id"], (r["tenant_id"], 0))[0], "org_credits": names.get(r["tenant_id"], ("", 0))[1]}
               for r in rows]
    return {"credits": credits, "pending": sum(r["status"] == "pending" for r in rows), "connectors": _asked("d2d.connector_request"),
            "migrations": _asked("d2d.migration_request"), "bi_tools": BI_TOOLS,
            "catalogue": [{"kind": k, "label": connector_label(k)} for k in edition.CONNECTORS], "costs": costs()}


def _answer_mail(r: dict, o: dict, subject: str, lines: list[str]) -> bool:
    """Tell the person who asked, by email (best effort; they are also told in the app)."""
    if not r.get("email"):
        return False
    from . import otp_mail
    body = "".join(f"<p>{html.escape(x)}</p>" for x in [f"Hello {r.get('user_name') or ''},".replace(" ,", ","), *lines,
                                                          f"D2D Relay - a Relay Platform product by PASDACS - {CONTACT}"])
    try:
        otp_mail.send(r["email"], subject, body, reply_to=CONTACT)
        return True
    except Exception:  # noqa: BLE001 - the in-app notification still tells them
        traceback.print_exc()
        return False


def _tell_asker(r: dict, o: dict, title: str, text: str) -> None:
    """The person who asked and the organisation's owners, in the app."""
    with db.use(r["tenant_id"]):
        for uid in {r.get("user_id"), *owner_ids()} - {None}:
            notify.add(uid, "ops", title, text, "#/org")


class Answer(BaseModel):
    credits: int | None = None          # approve: the credits to add (default: what was asked)
    note: str = ""                      # approve: shown in the credit history (optional); decline: the reason (required)


def approve(rid: str, credits: int | None, note: str, u: dict) -> dict:
    """Approve a credit request: the credits (what was asked, or another amount) are added to the organisation in the
    same transaction that marks the request approved, so a request is never approved twice. A new organisation's
    request (purpose 'start') adds them as its starting credits. u: the PASDACS person deciding."""
    from . import tenancy
    r = db.one("SELECT * FROM relay.tn_credit_requests WHERE id = ?", (rid,))
    if not r:
        raise HTTPException(404, "No such request.")
    o = row(r["tenant_id"])
    if not o:
        raise HTTPException(404, "That organisation is gone.")
    n = int(credits if credits is not None else r["credits"])
    if not 1 <= n <= 1_000_000:
        raise HTTPException(400, "Add between 1 and 1,000,000 credits.")
    note = " ".join((note or "").split())[:300]
    start = r.get("purpose") == "start"
    with _lock, db.transaction():
        if not db.run("UPDATE relay.tn_credit_requests SET status = 'approved', decided = ?, decided_by = ?, decided_name = ?, granted = ?, "
                      "note = ? WHERE id = ? AND status = 'pending'", (time.time(), u["id"], u.get("name"), n, note or None, rid)):
            raise HTTPException(409, "This request was already answered or withdrawn.")
        _entry(r["tenant_id"], "start" if start else "adjust", n,
               note=("Starting credits, approved by PASDACS" if start else "Request approved") + (f": {note}" if note else ""),
               ref=rid, who=u)
    tenancy.ctl_audit("d2d.credit_approved", r["tenant_id"], rid, {"asked": r["credits"], "granted": n, "note": note,
                                                                   "purpose": r.get("purpose")}, who=u["id"])
    left = (row(r["tenant_id"]) or {}).get("credits", 0)
    if start:
        from .payments import _site
        text = f"PASDACS approved {o['name']} on D2D Relay and added {n:,} starting credits" + (f". {note}" if note else ".")
        _tell_asker(r, o, f"{o['name']} is approved: {n:,} starting credits", text)
        _answer_mail(r, o, f"D2D Relay: {o['name']} is approved, {n:,} starting credits added",
                     [text, f"Sign in at {_site()} to build your first dashboard (a new dashboard uses {COST['dashboard']} credits)."])
    else:
        text = f"PASDACS approved {n:,} credits for {o['name']}" + (f" (you asked for {r['credits']:,})" if n != r["credits"] else "") + \
            (f". {note}" if note else ".")
        _tell_asker(r, o, f"{n:+,} credits for {o['name']}", text)
        _answer_mail(r, o, f"D2D Relay: {n:,} credits added to {o['name']}", [text, f"{o['name']} now has {left:,} credits."])
    return {**r, "status": "approved", "granted": n, "org": o["name"], "credits_now": left}


def decline(rid: str, note: str, u: dict) -> dict:
    """Decline a credit request, with the reason the organisation is told (a new organisation's starting credits too:
    it keeps working with none, and can still ask for credits or buy them)."""
    from . import tenancy
    r = db.one("SELECT * FROM relay.tn_credit_requests WHERE id = ?", (rid,))
    if not r:
        raise HTTPException(404, "No such request.")
    o = row(r["tenant_id"]) or {"name": r["tenant_id"], "owner_id": None}
    note = " ".join((note or "").split())[:300]
    if not note:
        raise HTTPException(400, "Say why, so the organisation knows what to do next.")
    if not db.run("UPDATE relay.tn_credit_requests SET status = 'declined', decided = ?, decided_by = ?, decided_name = ?, note = ? "
                  "WHERE id = ? AND status = 'pending'", (time.time(), u["id"], u.get("name"), note, rid)):
        raise HTTPException(409, "This request was already answered or withdrawn.")
    tenancy.ctl_audit("d2d.credit_declined", r["tenant_id"], rid, {"asked": r["credits"], "note": note, "purpose": r.get("purpose")},
                      who=u["id"])
    if r.get("purpose") == "start":
        text = f"PASDACS did not add starting credits to {o['name']}: {note}"
        _tell_asker(r, o, f"No starting credits for {o['name']}", text)
        _answer_mail(r, o, f"D2D Relay: about {o['name']}'s starting credits", [text, f"Questions? Reply to this email or write to {CONTACT}."])
    else:
        text = f"PASDACS declined the request for {r['credits']:,} credits: {note}"
        _tell_asker(r, o, f"Credit request for {o['name']} declined", text)
        _answer_mail(r, o, f"D2D Relay: your request for {r['credits']:,} credits", [text, f"Questions? Reply to this email or write to {CONTACT}."])
    return {**r, "status": "declined", "note": note, "org": o["name"]}


@router.post("/api/admin/requests/{rid}/approve")
def approve_request(rid: str, body: Answer):
    approve(rid, body.credits, body.note, _admin())
    return all_requests()


@router.post("/api/admin/requests/{rid}/decline")
def decline_request(rid: str, body: Answer):
    decline(rid, body.note, _admin())
    return all_requests()


class Connectors(BaseModel):
    kinds: list[str] = []


@router.put("/api/admin/orgs/{tid}/connectors")
def set_connectors(tid: str, body: Connectors):
    """A platform admin switches connectors on (or off) for an organisation; its owner is told. A connector switched
    off stops working at once for that organisation: its connections stay, but cannot be tested, queried or pulled."""
    from . import tenancy
    _admin()
    o = row(tid)
    if not o:
        raise HTTPException(404, "No such organisation.")
    wanted = set(body.kinds or [])
    if wanted - set(edition.CONNECTORS):
        raise HTTPException(400, "Unknown connector: " + ", ".join(sorted(wanted - set(edition.CONNECTORS))))
    kinds, before = [k for k in edition.CONNECTORS if k in wanted], connectors_of(tid)
    db.run("UPDATE relay.tn_orgs SET connectors = ? WHERE tenant_id = ?", (json.dumps(kinds), tid))
    tenancy.ctl_audit("d2d.connectors", tid, tid, {"from": before, "to": kinds})
    added, removed = [k for k in kinds if k not in before], [k for k in before if k not in kinds]
    if added or removed:
        text = " ".join(filter(None, [
            f"Switched on: {', '.join(connector_label(k) for k in added)}. Add a connection under Connections." if added else "",
            f"Switched off: {', '.join(connector_label(k) for k in removed)}." if removed else ""]))
        _tell_owners(tid, f"Connectors for {o['name']}", text, "#/connections")
    return all_orgs()


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
    _tell_owners(tid, f"{n:+,} credits for {o['name']}", note, "#/org")
    return all_orgs()


# ---------------------------------------------------------------- the same answers from the command line (PASDACS)

def _cli(argv: list[str]) -> int:
    """python -m app.orgs requests                                 the credit requests waiting for PASDACS
    python -m app.orgs approve <request id> [credits] ["note"]      add them (what was asked, or this many)
    python -m app.orgs decline <request id> "<reason>"              the organisation is told the reason
    Run it in the web container, which sends the emails:
      docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.orgs requests"""
    db.init()
    pasdacs = {"id": "pasdacs-cli", "name": "PASDACS"}
    try:
        if argv[:1] == ["requests"] and len(argv) == 1:
            names = {o["tenant_id"]: (o["name"], o["domain"], o["credits"]) for o in db.q("SELECT tenant_id, name, domain, credits FROM relay.tn_orgs")}
            rows = db.q("SELECT * FROM relay.tn_credit_requests WHERE status = 'pending' ORDER BY created")
            for r in rows:
                name, domain, left = names.get(r["tenant_id"], (r["tenant_id"], "?", 0))
                when = datetime.fromtimestamp(r["created"], IST).strftime("%Y-%m-%d %H:%M IST")
                what = "starting credits" if r.get("purpose") == "start" else "more credits"
                print(f"{r['id']}  {when}  {name} (@{domain}, {left} left)  {what}: {r['credits']}  {r.get('user_name') or ''} "
                      f"<{r.get('email') or ''}>" + (f"  \"{r['message']}\"" if r.get("message") and r.get("purpose") != "start" else ""))
            print(f"{len(rows)} waiting" if rows else "Nothing waiting.")
            return 0
        if argv[:1] == ["approve"] and 2 <= len(argv) <= 4:
            n = int(argv[2]) if len(argv) >= 3 and argv[2].strip() else None
            print(json.dumps(approve(argv[1], n, argv[3] if len(argv) == 4 else "", pasdacs), indent=1, default=str))
            return 0
        if argv[:1] == ["decline"] and len(argv) == 3:
            print(json.dumps(decline(argv[1], argv[2], pasdacs), indent=1, default=str))
            return 0
    except HTTPException as e:
        print(e.detail)
        return 1
    except ValueError:
        print("credits: a whole number")
        return 2
    print(_cli.__doc__)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
