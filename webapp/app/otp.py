"""D2D Relay sign-in: a one-time code by email, for people with a business email address (D2D_AUTH=otp).

Who may sign in (orgs.py):
  - anyone with an address at a business domain. The first person from a domain names and creates their
    organisation on the sign-in page and becomes its owner; everyone after them from that domain joins it;
  - never an address at a free or disposable mail domain (Gmail, Outlook, Yahoo …: public_domains.py);
  - D2D_OTP_EMAIL is the platform admin (the bootstrap admin of the platform's own workspace).

  D2D_OTP_FROM               the mailbox the code is sent from (default: D2D_OTP_EMAIL)
  D2D_OTP_MS_TENANT          Microsoft Entra tenant of that mailbox, and
  D2D_OTP_MS_CLIENT_ID       a public-client Entra app with delegated Mail.Send; the mailbox signs in once
                             (otp_mail.py says how). A client secret (D2D_OTP_MS_CLIENT_SECRET) also works, app-only.

The code: 6 digits, valid 10 minutes, 5 tries, then it dies. One code a minute and 6 an hour per address, 20 an hour
per network. Only a salted hash is stored (in the platform's schema, whatever workspace the person belongs to). A
session is made in the person's own workspace (their organisation's tenant), so the cookie carries it.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import traceback

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import auth, db, identity, orgs, otp_mail

router = APIRouter()

EMAIL = (os.environ.get("D2D_OTP_EMAIL") or "").strip().lower()
SENDER = (os.environ.get("D2D_OTP_FROM") or EMAIL).strip()
# Testing only: with no Microsoft app set, print the code in the log instead of sending it. Ignored once mail is set up.
DEV_LOG = os.environ.get("D2D_OTP_DEV_LOG") == "1"

TTL = 600
TRIES = 5
GAP = 60
PER_HOUR = 6
PER_IP_HOUR = 20
SIGNUP_TTL = 1800                       # after the code: time to name the new organisation
SIGNUP_COOKIE = "d2d_signup"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PUBLIC_TEXT = ("Use your work email address. Personal and free email addresses (Gmail, Outlook, Yahoo and the like) "
               "cannot be used for D2D Relay.")
_lock = threading.Lock()

db.register_schema("""-- D2D Relay: one-time sign-in codes (hash only) and the step after them for a new organisation
CREATE TABLE IF NOT EXISTS otp_codes (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  created REAL NOT NULL,
  expires REAL NOT NULL,
  tries INTEGER NOT NULL DEFAULT 0,
  used REAL,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS otp_codes_email ON otp_codes (email, created);
CREATE TABLE IF NOT EXISTS otp_signup (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  created REAL NOT NULL,
  expires REAL NOT NULL,
  used REAL
);""")


def configured() -> bool:
    return bool(otp_mail.mode())


def sync_admin() -> None:
    """D2D_OTP_EMAIL is the platform admin's address (the bootstrap admin; called at start)."""
    if EMAIL:
        db.run("UPDATE users SET email = ?, active = 1 WHERE id = ?", (EMAIL, db.ADMIN_ID))
        db.run("UPDATE relay.tn_accounts SET email = ? WHERE user_id = ?", (EMAIL, db.ADMIN_ID))


def _hash(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip") or (request.client.host if request.client else ""))[:64]


def _err(text: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"detail": text}, status_code=status)


def _mail(to: str, code: str) -> None:
    if not configured():
        if DEV_LOG:
            print(f"[otp] code for {to}: {code} (mail is not set up; D2D_OTP_DEV_LOG=1)", flush=True)
            return
        raise RuntimeError("Email sending is not set up: set D2D_OTP_MS_TENANT / CLIENT_ID and sign the mailbox in (otp_mail.py).")
    html = (f"<p>Your D2D Relay sign-in code is</p><p style=\"font-size:28px;font-weight:700;letter-spacing:6px\">{code}</p>"
            "<p>It works once, for 10 minutes. If you did not ask for it, you can ignore this email.</p>")
    otp_mail.send(to, f"D2D Relay sign-in code: {code}", html)


class StartBody(BaseModel):
    email: str = ""


class VerifyBody(BaseModel):
    email: str = ""
    code: str = ""
    next: str = ""


class OrgBody(BaseModel):
    name: str = ""
    person: str = ""


@router.post("/auth/otp/start")
def start(body: StartBody, request: Request):
    email = (body.email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return _err("Type your email address.")
    if orgs.public(email):
        with db.use(db.PLATFORM):
            db.audit("auth.otp_refused", None, {"ip": _ip(request), "reason": "public domain"}, "system")
        return _err(PUBLIC_TEXT)
    now, ip = time.time(), _ip(request)
    with _lock, db.use(db.PLATFORM):
        recent = db.q("SELECT created FROM otp_codes WHERE email = ? AND created > ? ORDER BY created DESC", (email, now - 3600))
        if recent and now - recent[0]["created"] < GAP:
            return _err(f"A code was sent less than a minute ago. Wait {int(GAP - (now - recent[0]['created'])) + 1} seconds.", 429)
        if len(recent) >= PER_HOUR:
            return _err("Too many codes this hour. Try again later.", 429)
        if ip and db.one("SELECT count(*) AS n FROM otp_codes WHERE ip = ? AND created > ?", (ip, now - 3600))["n"] >= PER_IP_HOUR:
            return _err("Too many codes were asked for from this network this hour. Try again later.", 429)
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(8)
        db.run("UPDATE otp_codes SET used = ? WHERE email = ? AND used IS NULL", (now, email))      # one live code at a time
        db.run("INSERT INTO otp_codes (id, email, code_hash, salt, created, expires, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (secrets.token_hex(8), email, _hash(code, salt), salt, now, now + TTL, ip))
    try:
        _mail(email, code)
    except Exception:  # noqa: BLE001 - the person is told the code could not be sent; the reason goes to the log
        traceback.print_exc()
        with db.use(db.PLATFORM):
            db.run("UPDATE otp_codes SET used = ? WHERE email = ? AND used IS NULL", (time.time(), email))
        return _err("The code could not be sent. Try again in a minute; if it keeps failing, write to info@pasdacs.com.", 502)
    with db.use(db.PLATFORM):
        db.audit("auth.otp_sent", None, {"ip": ip, "domain": orgs.domain_of(email)}, "system")
    return {"ok": True, "message": f"A 6-digit code is on its way to {email}. It works for 10 minutes."}


def _check_code(email: str, code: str, request: Request) -> bool:
    now = time.time()
    with _lock, db.use(db.PLATFORM):
        row = db.one("SELECT * FROM otp_codes WHERE email = ? AND used IS NULL AND expires > ? ORDER BY created DESC LIMIT 1", (email, now))
        if not row or row["tries"] >= TRIES:
            return False
        if not hmac.compare_digest(_hash(code, row["salt"]), row["code_hash"]):
            db.run("UPDATE otp_codes SET tries = tries + 1 WHERE id = ?", (row["id"],))
            db.audit("auth.otp_wrong", None, {"ip": _ip(request), "domain": orgs.domain_of(email)}, "system")
            return False
        db.run("UPDATE otp_codes SET used = ? WHERE id = ?", (now, row["id"]))
    return True


def _signed_in(tid: str, uid: str, request: Request, next_hash: str) -> JSONResponse:
    """A session in the person's own workspace; the cookie carries that workspace (identity.cookie_value)."""
    with db.use(tid):
        sid = identity.create_session(uid, "otp", _ip(request), request.headers.get("user-agent", ""))
        value = identity.cookie_value(sid)
    r = JSONResponse({"ok": True, "next": "/" + (next_hash if (next_hash or "").startswith("#/") else "")})
    r.set_cookie(identity.COOKIE, value, max_age=int(identity.SESSION_HOURS * 3600), httponly=True,
                 samesite="lax", secure=identity.SECURE_COOKIE, path="/")
    r.delete_cookie(SIGNUP_COOKIE, path="/auth/otp/")
    return r


def _account(email: str) -> tuple[str, dict] | JSONResponse | None:
    """(tenant, person) of an existing account, a refusal, or None when the address has no account yet."""
    with db.use(db.PLATFORM):
        acct = db.one("SELECT user_id, home_tenant FROM relay.tn_accounts WHERE email = ?", (email,))
        if not acct and EMAIL and email == EMAIL:
            acct = {"user_id": db.ADMIN_ID, "home_tenant": db.PLATFORM}
    if not acct:
        return None
    tid = acct["home_tenant"]
    t = auth.tenant_row(tid)
    if not t:
        return _err("Your organisation's account has been closed. Write to info@pasdacs.com.", 403)
    if t["status"] == "suspended":
        return _err(f"{t['name']} is paused on D2D Relay. Write to info@pasdacs.com.", 403)
    with db.use(tid):
        u = db.one("SELECT * FROM users WHERE id = ?", (acct["user_id"],))
    if not u or not u["active"]:
        return _err("Your D2D Relay account is switched off. Ask your organisation's owner, or write to info@pasdacs.com.", 403)
    return tid, u


@router.post("/auth/otp/verify")
def verify(body: VerifyBody, request: Request):
    email = (body.email or "").strip().lower()
    code = re.sub(r"\D", "", body.code or "")
    if len(code) != 6 or not EMAIL_RE.match(email) or orgs.public(email) or not _check_code(email, code, request):
        return _err("That code is wrong or has expired. Ask for a new one.")
    found = _account(email)
    if isinstance(found, JSONResponse):
        return found
    if found:
        tid, u = found
        return _signed_in(tid, u["id"], request, body.next)
    with db.use(db.PLATFORM):
        o = orgs.by_domain(orgs.domain_of(email))
    if o:                                            # a colleague created the organisation: join it
        if not auth.tenant_row(o["tenant_id"]):
            return _err("Your organisation's account has been closed. Write to info@pasdacs.com.", 403)
        uid = orgs.join(o["tenant_id"], email)
        return _signed_in(o["tenant_id"], uid, request, body.next or "#/d2d")
    # the first person from this domain: they name the organisation next (POST /auth/otp/organisation)
    token, now = secrets.token_urlsafe(32), time.time()
    with db.use(db.PLATFORM):
        db.run("INSERT INTO otp_signup (token_hash, email, created, expires) VALUES (?, ?, ?, ?)",
               (hashlib.sha256(token.encode()).hexdigest(), email, now, now + SIGNUP_TTL))
    domain = orgs.domain_of(email)
    r = JSONResponse({"ok": True, "organisation": {"email": email, "domain": domain, "suggested": orgs.suggested_name(domain),
                                                   "person": orgs.name_from(email), "credits": orgs.START}})
    r.set_cookie(SIGNUP_COOKIE, token, max_age=SIGNUP_TTL, httponly=True, samesite="lax", secure=identity.SECURE_COOKIE,
                 path="/auth/otp/")
    return r


def _signup(request: Request) -> dict | None:
    token = request.cookies.get(SIGNUP_COOKIE) or ""
    if not token:
        return None
    with db.use(db.PLATFORM):
        return db.one("SELECT * FROM otp_signup WHERE token_hash = ? AND used IS NULL AND expires > ?",
                      (hashlib.sha256(token.encode()).hexdigest(), time.time()))


@router.get("/auth/otp/organisation")
def signup_pending(request: Request):
    """The sign-in page after a reload: is a new organisation waiting for its name?"""
    s = _signup(request)
    if not s:
        return {}                                    # nothing waiting (the usual case)
    domain = orgs.domain_of(s["email"])
    return {"email": s["email"], "domain": domain, "suggested": orgs.suggested_name(domain), "person": orgs.name_from(s["email"]),
            "credits": orgs.START}


@router.post("/auth/otp/organisation")
def create_organisation(body: OrgBody, request: Request):
    """The first person from a business domain names their organisation: it is created, they own it, and they go on to
    the first-time setup (#/setup: the brand)."""
    s = _signup(request)
    if not s:
        return _err("This step has expired. Sign in again to get a new code.", 401)
    try:
        tid, uid = orgs.create(body.name, s["email"], body.person)
    except orgs.OrgError as e:
        if str(e) != "exists":
            return _err(str(e))
        with db.use(db.PLATFORM):                    # a colleague was a moment quicker: join their organisation
            o = orgs.by_domain(orgs.domain_of(s["email"]))
        if not o:
            return _err("Your organisation could not be created. Try again in a minute.", 409)
        tid, uid = o["tenant_id"], orgs.join(o["tenant_id"], s["email"])
    with db.use(db.PLATFORM):
        db.run("UPDATE otp_signup SET used = ? WHERE token_hash = ?", (time.time(), s["token_hash"]))
    return _signed_in(tid, uid, request, "#/setup")
