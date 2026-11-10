"""D2D Relay sign-in: a one-time code by email, for ONE address only (D2D_AUTH=otp).

  D2D_OTP_EMAIL              the only address that may sign in (it becomes the bootstrap admin's address)
  D2D_OTP_FROM               the mailbox the code is sent from (default: D2D_OTP_EMAIL)
  D2D_OTP_MS_TENANT          Microsoft Entra tenant id or domain of that mailbox
  D2D_OTP_MS_CLIENT_ID       an Entra app with the Microsoft Graph *application* permission Mail.Send (admin consent);
  D2D_OTP_MS_CLIENT_SECRET   limit it to the D2D_OTP_FROM mailbox with an Exchange application access policy

The code: 6 digits, valid 10 minutes, 5 tries, then it dies. One code a minute and 6 an hour per address. Only a salted
hash is stored. Every answer to "send me a code" is the same, whether or not the address may sign in, so the page
never tells a stranger which address works.
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

from . import db, identity

router = APIRouter()

EMAIL = (os.environ.get("D2D_OTP_EMAIL") or "").strip().lower()
SENDER = (os.environ.get("D2D_OTP_FROM") or EMAIL).strip()
MS_TENANT = (os.environ.get("D2D_OTP_MS_TENANT") or "").strip()
MS_CLIENT_ID = (os.environ.get("D2D_OTP_MS_CLIENT_ID") or "").strip()
MS_SECRET = (os.environ.get("D2D_OTP_MS_CLIENT_SECRET") or "").strip()
MS_LOGIN = os.environ.get("D2D_MS_LOGIN", "https://login.microsoftonline.com")
MS_GRAPH = os.environ.get("D2D_MS_GRAPH", "https://graph.microsoft.com/v1.0")
# Testing only: with no Microsoft app set, print the code in the log instead of sending it. Ignored once mail is set up.
DEV_LOG = os.environ.get("D2D_OTP_DEV_LOG") == "1"

TTL = 600
TRIES = 5
GAP = 60
PER_HOUR = 6
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SENT_TEXT = "If that address may sign in, a 6-digit code is on its way. It works for 10 minutes."
_lock = threading.Lock()

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
CREATE INDEX IF NOT EXISTS otp_codes_email ON otp_codes (email, created);""")


def configured() -> bool:
    return bool(MS_TENANT and MS_CLIENT_ID and MS_SECRET and SENDER)


def sync_admin() -> None:
    """The one allowed address is the bootstrap admin's address (called at start)."""
    if EMAIL:
        db.run("UPDATE users SET email = ?, active = 1 WHERE id = ?", (EMAIL, db.ADMIN_ID))
        db.run("UPDATE relay.tn_accounts SET email = ? WHERE user_id = ?", (EMAIL, db.ADMIN_ID))


def _hash(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _ip(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip") or (request.client.host if request.client else ""))[:64]


def _mail(to: str, code: str) -> None:
    if not configured():
        if DEV_LOG:
            print(f"[otp] code for {to}: {code} (mail is not set up; D2D_OTP_DEV_LOG=1)", flush=True)
            return
        raise RuntimeError("Email sending is not set up (D2D_OTP_MS_TENANT / CLIENT_ID / CLIENT_SECRET).")
    tok = httpx.post(f"{MS_LOGIN}/{MS_TENANT}/oauth2/v2.0/token", timeout=20,
                     data={"client_id": MS_CLIENT_ID, "client_secret": MS_SECRET, "grant_type": "client_credentials",
                           "scope": "https://graph.microsoft.com/.default"})
    if tok.status_code != 200:
        raise RuntimeError(f"Microsoft sign-in for mail failed ({tok.status_code}): {tok.text[:300]}")
    html = (f"<p>Your D2D Relay sign-in code is</p><p style=\"font-size:28px;font-weight:700;letter-spacing:6px\">{code}</p>"
            "<p>It works once, for 10 minutes. If you did not ask for it, you can ignore this email.</p>")
    r = httpx.post(f"{MS_GRAPH}/users/{SENDER}/sendMail", timeout=30, headers={"Authorization": "Bearer " + tok.json()["access_token"]},
                   json={"message": {"subject": f"D2D Relay sign-in code: {code}", "body": {"contentType": "HTML", "content": html},
                                     "toRecipients": [{"emailAddress": {"address": to}}]}, "saveToSentItems": False})
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Microsoft Graph refused the email ({r.status_code}): {r.text[:300]}")


class StartBody(BaseModel):
    email: str = ""


class VerifyBody(BaseModel):
    email: str = ""
    code: str = ""
    next: str = ""


@router.post("/auth/otp/start")
def start(body: StartBody, request: Request):
    email = (body.email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return JSONResponse({"detail": "Type your email address."}, status_code=400)
    if not EMAIL or not hmac.compare_digest(email, EMAIL):
        db.audit("auth.otp_refused", None, {"ip": _ip(request)}, "system")
        return {"ok": True, "message": SENT_TEXT}
    now = time.time()
    with _lock:
        recent = db.q("SELECT created FROM otp_codes WHERE email = ? AND created > ? ORDER BY created DESC", (email, now - 3600))
        if recent and now - recent[0]["created"] < GAP:
            return JSONResponse({"detail": f"A code was sent less than a minute ago. Wait {int(GAP - (now - recent[0]['created'])) + 1} seconds."}, status_code=429)
        if len(recent) >= PER_HOUR:
            return JSONResponse({"detail": "Too many codes this hour. Try again later."}, status_code=429)
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(8)
        db.run("UPDATE otp_codes SET used = ? WHERE email = ? AND used IS NULL", (now, email))      # one live code at a time
        db.run("INSERT INTO otp_codes (id, email, code_hash, salt, created, expires, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (secrets.token_hex(8), email, _hash(code, salt), salt, now, now + TTL, _ip(request)))
    try:
        _mail(email, code)
    except Exception:  # noqa: BLE001 - the person is told the code could not be sent; the reason goes to the log
        traceback.print_exc()
        db.run("UPDATE otp_codes SET used = ? WHERE email = ? AND used IS NULL", (time.time(), email))
        return JSONResponse({"detail": "The code could not be sent. Try again in a minute; if it keeps failing, write to info@pasdacs.com."}, status_code=502)
    db.audit("auth.otp_sent", db.ADMIN_ID, {"ip": _ip(request)}, "system")
    return {"ok": True, "message": SENT_TEXT}


@router.post("/auth/otp/verify")
def verify(body: VerifyBody, request: Request):
    email = (body.email or "").strip().lower()
    code = re.sub(r"\D", "", body.code or "")
    wrong = JSONResponse({"detail": "That code is wrong or has expired. Ask for a new one."}, status_code=400)
    if len(code) != 6 or not EMAIL or not hmac.compare_digest(email, EMAIL):
        return wrong
    now = time.time()
    with _lock:
        row = db.one("SELECT * FROM otp_codes WHERE email = ? AND used IS NULL AND expires > ? ORDER BY created DESC LIMIT 1", (email, now))
        if not row or row["tries"] >= TRIES:
            return wrong
        if not hmac.compare_digest(_hash(code, row["salt"]), row["code_hash"]):
            db.run("UPDATE otp_codes SET tries = tries + 1 WHERE id = ?", (row["id"],))
            db.audit("auth.otp_wrong", db.ADMIN_ID, {"ip": _ip(request)}, "system")
            return wrong
        db.run("UPDATE otp_codes SET used = ? WHERE id = ?", (now, row["id"]))
    sid = identity.create_session(db.ADMIN_ID, "otp", _ip(request), request.headers.get("user-agent", ""))
    r = JSONResponse({"ok": True, "next": "/" + (body.next if (body.next or "").startswith("#/") else "")})
    r.set_cookie(identity.COOKIE, identity.cookie_value(sid), max_age=int(identity.SESSION_HOURS * 3600), httponly=True,
                 samesite="lax", secure=identity.SECURE_COOKIE, path="/")
    return r
