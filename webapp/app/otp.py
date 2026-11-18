"""D2D Relay sign-in: a one-time code by email (D2D_AUTH=otp).

Who may sign in: only people with an account (item 56, the user 2026-11-18: "Remove signup and bring login directly as
internal team management"; D2D is licensed to client organisations, not offered to the public). Nobody makes an
account on the sign-in page:
  - PASDACS creates each organisation with its main owner on the admin portal (Organisations, New organisation:
    orgs.create), and can add people to it;
  - an organisation's owners add their own people (Organisation, People, Add people: orgs.add_person);
  - D2D_OTP_EMAIL is the platform admin (the bootstrap admin of the platform's own workspace).
An address without an account gets the same answer as one with an account, but no code: nobody can find out from the
sign-in page which addresses have accounts. Its answer comes after about as long as sending a code takes, and the limits
below count it like any other.

  D2D_OTP_FROM               the mailbox the code is sent from (default: D2D_OTP_EMAIL)
  D2D_OTP_MS_TENANT          Microsoft Entra tenant of that mailbox, and
  D2D_OTP_MS_CLIENT_ID       a public-client Entra app with delegated Mail.Send; the mailbox signs in once
                             (otp_mail.py says how). A client secret (D2D_OTP_MS_CLIENT_SECRET) also works, app-only.

The code: 6 digits, valid 10 minutes, 5 tries, then it dies. One code a minute, 6 an hour and 20 a day per address, 20
an hour per network. Only a salted hash is stored (in the platform's schema, whatever workspace the person belongs to). A
session is made in the person's own workspace (their organisation's tenant), so the cookie carries it.

A bot check before any code is sent (item 40, the user 2026-11-13: "bot check add back"; security audit S7, S13): with
both Cloudflare Turnstile keys set (RELAY_TURNSTILE_SITE_KEY, RELAY_TURNSTILE_SECRET) the public site's sign-in page
shows Turnstile's widget, and /auth/otp/start needs its token, checked with Cloudflare (siteverify) before a code is
made or sent; a token works once. Without the keys nothing changes. If Cloudflare cannot be asked, no code is sent.

The admin portal (portal.py, D2D_PORTAL=admin) uses the same codes, without the bot check, for addresses at the admin
domains (pasdacs.com) with an account in the platform's own workspace (PASDACS): a PASDACS owner adds colleagues on the
public site's Organisation page, like any organisation's owner. Its sessions are of their own kind (portal.SESSION_KIND)
and cookie (d2d_admin).

The code on the screen (item 57, the user 2026-11-18, for demos on the live install once its tunnel was removed: "add a
option to show the otp in the screen itself as all is local not in public"): with D2D_OTP_ON_SCREEN=1 the sign-in page
shows an account's code itself instead of emailing it, and asks for no bot check, but only for a request made on this
PC: from its own addresses (portal.LOCAL: loopback, the Docker host) with no Cloudflare or proxy header. Anything else
gets the emailed code as always. Off by default; only for an install nobody reaches from outside this PC.
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

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import auth, code_email, db, identity, orgs, otp_mail, portal, signin_alerts

router = APIRouter()
ADMIN_ONLY_TEXT = "Only PASDACS addresses can sign in to the D2D Relay admin portal."
SENT_TEXT = "If {email} has a D2D Relay account, we sent it a sign-in code. It expires in 10 minutes."
SHOWN_TEXT = "Your sign-in code is shown below (this D2D Relay is used on this computer only). It expires in 10 minutes."
WRONG_TEXT = "That code is wrong or has expired. Ask for a new one."
# item 57: the code on the sign-in page itself, for requests made on this PC only (on_screen)
ON_SCREEN = (os.environ.get("D2D_OTP_ON_SCREEN") or "").strip().lower() in ("1", "true", "yes", "on")
PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "forwarded", "x-real-ip")

EMAIL = (os.environ.get("D2D_OTP_EMAIL") or "").strip().lower()
SENDER = (os.environ.get("D2D_OTP_FROM") or EMAIL).strip()
# Testing only: with no Microsoft app set, print the code in the log instead of sending it. Ignored once mail is set up.
DEV_LOG = os.environ.get("D2D_OTP_DEV_LOG") == "1"

TTL = 600
TRIES = 5
GAP = 60
PER_HOUR = 6
PER_DAY = 20                            # security audit (S13): at most 100 guesses a day at one address's codes
PER_IP_HOUR = 20
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_lock = threading.Lock()
_SENDING = {"s": 0.0}                   # how long sending a code took lately (seconds, a moving average)
# Item 40: Cloudflare Turnstile on "Email me a code" (both keys, or off)
TURNSTILE_SITE_KEY = (os.environ.get("D2D_TURNSTILE_SITE_KEY") or "").strip()
TURNSTILE_SECRET = (os.environ.get("D2D_TURNSTILE_SECRET") or "").strip()
TURNSTILE_VERIFY = (os.environ.get("D2D_TURNSTILE_VERIFY") or "https://challenges.cloudflare.com/turnstile/v0/siteverify").strip()
TURNSTILE_ACTION = "otp-start"                      # the widget's action; a token made for another action is refused
BOT_TEXT = "Please complete the security check, then try again."
BOT_DOWN_TEXT = "The security check could not be confirmed. Please try again in a minute."


def turnstile_on() -> bool:
    """The public site asks for Turnstile's token when both keys are set; the admin portal never does."""
    return bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET) and not portal.ADMIN


def on_screen(request: Request) -> bool:
    """Item 57: whether this request gets its sign-in code on the screen (D2D_OTP_ON_SCREEN=1): only one made on this
    PC, from its own addresses (portal.LOCAL), with none of the headers a tunnel or proxy adds."""
    if not ON_SCREEN or any(request.headers.get(h) for h in PROXY_HEADERS):
        return False
    return (request.client.host if request.client else "") in portal.LOCAL


def _human(token: str, ip: str) -> bool | None:
    """Cloudflare's answer for the widget's token: True (a person), False (refused), None (Cloudflare could not be
    asked: no code is sent then either)."""
    token = (token or "").strip()
    if not token or len(token) > 2048:
        return False
    try:
        r = httpx.post(TURNSTILE_VERIFY, data={"secret": TURNSTILE_SECRET, "response": token, **({"remoteip": ip} if ip else {})},
                       timeout=10)
        j = r.json()
    except Exception:  # noqa: BLE001 - the reason goes to the log; the person is asked to try again
        traceback.print_exc()
        return None
    if not isinstance(j, dict):
        return None
    if not j.get("success"):
        return False
    return not (j.get("action") and j["action"] != TURNSTILE_ACTION)

db.register_schema("""-- D2D Relay: one-time sign-in codes (hash only)
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
-- item 56: the step after the code that named a new organisation is gone with the sign-up, and its table with it
DROP TABLE IF EXISTS otp_signup;""")


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
    subject, html = code_email.render(code, TTL // 60, admin=portal.ADMIN)      # item 51: in D2D's look
    otp_mail.send(to, subject, html)


def _known(email: str) -> bool:
    """Whether a code goes to this address: it has an account (on the admin portal, one in PASDACS's own workspace), or
    it is the platform admin's own address."""
    if EMAIL and email == EMAIL:
        return True
    with db.use(db.PLATFORM):
        acct = db.one("SELECT home_tenant FROM relay.tn_accounts WHERE email = ?", (email,))
    return bool(acct) and (acct["home_tenant"] == db.PLATFORM or not portal.ADMIN)


def _like_sending() -> None:
    """For an address without an account: wait about as long as sending a code takes lately, so the answer's timing
    does not tell the two apart (nothing to wait for when codes are only printed to the log)."""
    s = _SENDING["s"] or (0.8 if configured() else 0.0)
    if s > 0.01:
        time.sleep(min(5.0, s * (0.85 + secrets.randbelow(300) / 1000)))


class StartBody(BaseModel):
    email: str = ""
    turnstile: str = ""                     # item 40: the Turnstile widget's token, when the bot check is on


class VerifyBody(BaseModel):
    email: str = ""
    code: str = ""
    next: str = ""


@router.post("/auth/otp/start")
def start(body: StartBody, request: Request):
    email = (body.email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return _err("Type your email address.")
    if portal.ADMIN and not portal.admin_email(email):
        with db.use(db.PLATFORM):
            db.audit("auth.otp_refused", None, {"ip": _ip(request), "reason": "admin portal", "domain": orgs.domain_of(email)}, "system")
        return _err(ADMIN_ONLY_TEXT, 403)
    shown = on_screen(request)                       # item 57: on this PC, the code on the screen and no bot check
    if turnstile_on() and not shown:                 # item 40: a person, not a bot, before any code is made or sent
        human = _human(body.turnstile, _ip(request))
        if not human:
            with db.use(db.PLATFORM):
                db.audit("auth.otp_refused", None, {"ip": _ip(request), "reason": "bot check" if human is False else "bot check unreachable"},
                         "system")
            return _err(BOT_TEXT if human is False else BOT_DOWN_TEXT, 403 if human is False else 503)
    now, ip = time.time(), _ip(request)
    known = _known(email)
    with _lock, db.use(db.PLATFORM):
        recent = db.q("SELECT created FROM otp_codes WHERE email = ? AND created > ? ORDER BY created DESC", (email, now - 3600))
        if recent and now - recent[0]["created"] < GAP:
            return _err(f"A code was sent less than a minute ago. Wait {int(GAP - (now - recent[0]['created'])) + 1} seconds.", 429)
        if len(recent) >= PER_HOUR:
            return _err("Too many codes this hour. Try again later.", 429)
        if db.one("SELECT count(*) AS n FROM otp_codes WHERE email = ? AND created > ?", (email, now - 86400))["n"] >= PER_DAY:
            return _err("Too many codes today for this address. Try again tomorrow, or write to info@pasdacs.com.", 429)
        if ip and db.one("SELECT count(*) AS n FROM otp_codes WHERE ip = ? AND created > ?", (ip, now - 3600))["n"] >= PER_IP_HOUR:
            return _err("Too many codes were asked for from this network this hour. Try again later.", 429)
        # an address without an account gets a row too (its code is never sent), so the limits treat both alike
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(8)
        db.run("UPDATE otp_codes SET used = ? WHERE email = ? AND used IS NULL", (now, email))      # one live code at a time
        db.run("INSERT INTO otp_codes (id, email, code_hash, salt, created, expires, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (secrets.token_hex(8), email, _hash(code, salt), salt, now, now + TTL, ip))
    if not known:
        _like_sending()
        with db.use(db.PLATFORM):
            db.audit("auth.otp_no_account", None, {"ip": ip, "domain": orgs.domain_of(email)}, "system")
        return {"ok": True, "message": SENT_TEXT.format(email=email)}
    if shown:                                        # item 57: shown on this PC's screen, not emailed
        if DEV_LOG:
            print(f"[otp] code for {email}: {code} (shown on screen, D2D_OTP_ON_SCREEN=1)", flush=True)
        with db.use(db.PLATFORM):
            db.audit("auth.otp_shown", None, {"ip": ip, "domain": orgs.domain_of(email)}, "system")
        return {"ok": True, "message": SHOWN_TEXT, "code": code}
    t0 = time.monotonic()
    try:
        _mail(email, code)
    except Exception:  # noqa: BLE001 - the person is told the code could not be sent; the reason goes to the log
        traceback.print_exc()
        with db.use(db.PLATFORM):
            db.run("UPDATE otp_codes SET used = ? WHERE email = ? AND used IS NULL", (time.time(), email))
        return _err("The code could not be sent. Try again in a minute; if it keeps failing, write to info@pasdacs.com.", 502)
    took = time.monotonic() - t0
    _SENDING["s"] = took if not _SENDING["s"] else 0.8 * _SENDING["s"] + 0.2 * took
    with db.use(db.PLATFORM):
        db.audit("auth.otp_sent", None, {"ip": ip, "domain": orgs.domain_of(email)}, "system")
    return {"ok": True, "message": SENT_TEXT.format(email=email)}


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
    """A session in the person's own workspace; the cookie carries that workspace (identity.cookie_value). PASDACS is
    emailed about it (signin_alerts: in the background, never in the way of the sign-in)."""
    with db.use(tid):
        sid = identity.create_session(uid, portal.SESSION_KIND if portal.ADMIN else "otp", _ip(request), request.headers.get("user-agent", ""))
        value = identity.cookie_value(sid)
    signin_alerts.sign_in(tid, uid, "admin" if portal.ADMIN else "signed_in", request)
    r = JSONResponse({"ok": True, "next": "/" + (next_hash if (next_hash or "").startswith("#/") else "")})
    r.set_cookie(identity.COOKIE, value, max_age=int(identity.SESSION_HOURS * 3600), httponly=True,
                 samesite="lax", secure=identity.SECURE_COOKIE, path="/")
    return r


def _account(email: str) -> tuple[str, dict] | JSONResponse | None:
    """(tenant, person) of an existing account, a refusal, or None when the address has no account."""
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
    if len(code) != 6 or not EMAIL_RE.match(email) or not _check_code(email, code, request):
        return _err(WRONG_TEXT)
    found = _account(email)
    if isinstance(found, JSONResponse):
        return found
    if not found:                       # no account: no code was ever sent, so only a lucky guess gets here
        return _err(WRONG_TEXT)
    tid, u = found
    if portal.ADMIN:                    # the admin portal: PASDACS's own people only, whatever the code
        if not portal.admin_email(email):
            return _err(ADMIN_ONLY_TEXT, 403)
        if tid != db.PLATFORM:
            return _err("This address belongs to another organisation's workspace, not PASDACS's.", 403)
        return _signed_in(tid, u["id"], request, body.next or "#/orgs")
    return _signed_in(tid, u["id"], request, body.next)
