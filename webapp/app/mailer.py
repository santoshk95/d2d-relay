"""Email sending accounts (phase 7): each person's own Gmail (app password, SMTP) or Microsoft work account (OAuth,
Microsoft Graph sendMail). The person picks which account each schedule sends from.

Secrets (the app password, the Microsoft refresh token) are encrypted in the secrets store under the person's scope.
An account whose password or token stops working is marked 'expired'; schedules that use it pause and the person is
told (see schedules.py) instead of failing silently."""
import base64
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import auth, db, identity, secrets_store

router = APIRouter()

SMTP_HOST = os.environ.get("D2D_GMAIL_SMTP", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("D2D_GMAIL_SMTP_PORT", "465"))
MS_LOGIN = os.environ.get("D2D_MS_LOGIN", "https://login.microsoftonline.com")
MS_GRAPH = os.environ.get("D2D_MS_GRAPH", "https://graph.microsoft.com/v1.0")
MS_SCOPE = "offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ATTACH = 20 * 1024 * 1024


class EmailError(Exception):
    pass


class EmailExpired(EmailError):
    """The account's password or token no longer works: the person must reconnect it."""


def _scope(uid: str) -> str:
    return f"user:{uid}"


def accounts(uid: str) -> list[dict]:
    return db.q("SELECT id, kind, address, status, error, created, last_used FROM email_accounts WHERE owner_id = ? ORDER BY created", (uid,))


def account(aid: str, uid: str) -> dict:
    a = db.one("SELECT * FROM email_accounts WHERE id = ? AND owner_id = ?", (aid, uid))
    if not a:
        raise EmailError("Unknown email account.")
    return a


def _set(aid: str, status: str, error: str | None = None) -> None:
    db.run("UPDATE email_accounts SET status = ?, error = ? WHERE id = ?", (status, error, aid))


def remove(aid: str, uid: str) -> None:
    account(aid, uid)
    secrets_store.delete(_scope(uid), f"email:{aid}", uid)
    db.run("DELETE FROM email_accounts WHERE id = ?", (aid,))
    db.run("UPDATE schedules SET status = 'paused', paused_reason = 'Its email account was removed.' WHERE email_account_id = ?", (aid,))
    db.audit("email.remove", aid, None, uid)


# ---------------------------------------------------------------- Gmail (app password over SMTP)

def _smtp():
    return smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30)


def add_gmail(uid: str, address: str, app_password: str) -> dict:
    address, pw = address.strip(), re.sub(r"\s+", "", app_password or "")
    if not EMAIL_RE.match(address):
        raise EmailError("Enter the Gmail address.")
    if len(pw) < 12:
        raise EmailError("Paste the 16-letter app password from your Google account (Security > App passwords).")
    try:
        with _smtp() as s:
            s.login(address, pw)
    except smtplib.SMTPAuthenticationError as e:
        raise EmailError("Gmail did not accept the address and app password.") from e
    except (OSError, smtplib.SMTPException) as e:
        raise EmailError(f"Could not reach Gmail: {str(e)[:200]}") from e
    aid = "em-" + secrets.token_hex(5)
    db.run("INSERT INTO email_accounts (id, owner_id, kind, address, status, created) VALUES (?, ?, 'gmail', ?, 'connected', ?)",
           (aid, uid, address, time.time()))
    secrets_store.put(_scope(uid), f"email:{aid}", pw, uid)
    db.audit("email.connect", aid, {"kind": "gmail", "address": address}, uid)
    return account(aid, uid)


def _send_gmail(a: dict, to: list[str], subject: str, html: str, attachments: list[tuple[str, str, bytes]]) -> None:
    pw = secrets_store.get(_scope(a["owner_id"]), f"email:{a['id']}")
    if not pw:
        raise EmailExpired("The Gmail app password is missing; connect the account again.")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = a["address"], ", ".join(to), subject
    msg.set_content(re.sub(r"<[^>]+>", "", html))
    msg.add_alternative(html, subtype="html")
    for name, mime, data in attachments:
        main, _, sub = mime.partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=name)
    try:
        with _smtp() as s:
            s.login(a["address"], pw)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise EmailExpired("Gmail no longer accepts the app password (it was revoked or the Google password changed).") from e
    except (OSError, smtplib.SMTPException) as e:
        raise EmailError(f"Gmail did not send the email: {str(e)[:200]}") from e


# ---------------------------------------------------------------- Microsoft work account (OAuth + Graph)

def ms_app() -> dict:
    return json.loads(db.meta("microsoft_mail_app") or "{}")


def save_ms_app(client_id: str, tenant: str, secret: str | None, who: str | None) -> dict:
    tenant = (tenant or "organizations").strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,80}", tenant):
        raise EmailError("Tenant must be a tenant id, a domain, or 'organizations'.")
    db.set_meta("microsoft_mail_app", json.dumps({"client_id": client_id.strip(), "tenant": tenant}))
    if secret:
        secrets_store.put("org", "microsoft_mail:client_secret", secret, who)
    db.audit("email.microsoft_app", None, {"client_id": client_id.strip(), "tenant": tenant}, who)
    return ms_app_public()


def ms_app_public() -> dict:
    return {**ms_app(), "has_secret": secrets_store.get("org", "microsoft_mail:client_secret") is not None}


def _redirect(base_url: str) -> str:
    return f"{identity.PUBLIC_URL or base_url.rstrip('/')}/auth/microsoft/callback"


def ms_start(uid: str, base_url: str) -> str:
    app = ms_app()
    if not app.get("client_id"):
        raise EmailError("Your administrator has not set up Microsoft email yet (Admin > Scheduling).")
    state = secrets.token_urlsafe(24)
    db.run("INSERT INTO auth_flows (state, provider, verifier, nonce, return_to, created) VALUES (?, 'msmail', '', ?, '#/settings', ?)",
           (state, uid, time.time()))
    return f"{MS_LOGIN}/{app['tenant']}/oauth2/v2.0/authorize?" + urlencode(
        {"client_id": app["client_id"], "response_type": "code", "redirect_uri": _redirect(base_url), "response_mode": "query",
         "scope": MS_SCOPE, "state": state, "prompt": "select_account"})


def _token(data: dict) -> dict:
    app = ms_app()
    r = httpx.post(f"{MS_LOGIN}/{app.get('tenant', 'organizations')}/oauth2/v2.0/token", timeout=20,
                   data={"client_id": app.get("client_id", ""), "client_secret": secrets_store.get("org", "microsoft_mail:client_secret") or "",
                         "scope": MS_SCOPE, **data})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "access_token" not in body:
        err = body.get("error") or str(r.status_code)
        if err in ("invalid_grant", "interaction_required", "invalid_client", "unauthorized_client"):
            raise EmailExpired(f"Microsoft no longer accepts the sign-in ({err}); connect the account again.")
        raise EmailError(f"Microsoft sign-in failed: {body.get('error_description', err)[:200]}")
    return body


def ms_callback(state: str, code: str, base_url: str) -> str:
    flow = db.one("SELECT * FROM auth_flows WHERE state = ? AND provider = 'msmail'", (state,))
    db.run("DELETE FROM auth_flows WHERE state = ?", (state,))
    if not flow or time.time() - flow["created"] > 900:
        raise EmailError("The Microsoft sign-in took too long or was already used.")
    uid = flow["nonce"]
    tok = _token({"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect(base_url)})
    me = httpx.get(f"{MS_GRAPH}/me", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=20).json()
    address = me.get("mail") or me.get("userPrincipalName")
    if not address:
        raise EmailError("Microsoft did not return an email address for this account.")
    old = db.one("SELECT id FROM email_accounts WHERE owner_id = ? AND kind = 'microsoft' AND lower(address) = lower(?)", (uid, address))
    aid = old["id"] if old else "em-" + secrets.token_hex(5)
    if not old:
        db.run("INSERT INTO email_accounts (id, owner_id, kind, address, status, created) VALUES (?, ?, 'microsoft', ?, 'connected', ?)",
               (aid, uid, address, time.time()))
    _set(aid, "connected")
    secrets_store.put(_scope(uid), f"email:{aid}", tok.get("refresh_token", ""), uid)
    db.run("UPDATE schedules SET status = 'active', paused_reason = NULL WHERE email_account_id = ? AND paused_reason LIKE 'Email:%'", (aid,))
    db.audit("email.connect", aid, {"kind": "microsoft", "address": address}, uid)
    return uid


def _send_ms(a: dict, to: list[str], subject: str, html: str, attachments: list[tuple[str, str, bytes]]) -> None:
    refresh = secrets_store.get(_scope(a["owner_id"]), f"email:{a['id']}")
    if not refresh:
        raise EmailExpired("The Microsoft sign-in is missing; connect the account again.")
    tok = _token({"grant_type": "refresh_token", "refresh_token": refresh})
    if tok.get("refresh_token") and tok["refresh_token"] != refresh:
        secrets_store.put(_scope(a["owner_id"]), f"email:{a['id']}", tok["refresh_token"], a["owner_id"])
    msg = {"subject": subject, "body": {"contentType": "HTML", "content": html},
           "toRecipients": [{"emailAddress": {"address": t}} for t in to],
           "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": n, "contentType": m,
                            "contentBytes": base64.b64encode(d).decode()} for n, m, d in attachments]}
    r = httpx.post(f"{MS_GRAPH}/me/sendMail", headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=60,
                   json={"message": msg, "saveToSentItems": True})
    if r.status_code in (401, 403):
        raise EmailExpired(f"Microsoft refused to send from {a['address']} ({r.status_code}); connect the account again.")
    if r.status_code >= 300:
        raise EmailError(f"Microsoft did not send the email ({r.status_code}): {r.text[:200]}")


# ---------------------------------------------------------------- sending

def send(aid: str, uid: str, to: list[str], subject: str, html: str, attachments: list[tuple[str, str, bytes]] | None = None) -> None:
    a = account(aid, uid)
    attachments = attachments or []
    if sum(len(d) for _, _, d in attachments) > MAX_ATTACH:
        raise EmailError("The attachment is over 20 MB.")
    try:
        (_send_gmail if a["kind"] == "gmail" else _send_ms)(a, to, subject, html, attachments)
    except EmailExpired as e:
        _set(aid, "expired", str(e))
        raise
    db.run("UPDATE email_accounts SET last_used = ?, status = 'connected', error = NULL WHERE id = ?", (time.time(), aid))
    db.audit("email.send", aid, {"to": to, "subject": subject[:200], "attachments": [n for n, _, _ in attachments]}, uid)


# ---------------------------------------------------------------- endpoints (each person's own accounts)

def _u() -> dict:
    return auth.current.get()


class GmailBody(BaseModel):
    address: str
    app_password: str


@router.get("/api/email/accounts")
def my_accounts():
    return {"accounts": accounts(_u()["id"]), "microsoft_ready": bool(ms_app().get("client_id"))}


@router.post("/api/email/gmail")
def connect_gmail(body: GmailBody):
    try:
        add_gmail(_u()["id"], body.address, body.app_password)
    except EmailError as e:
        raise HTTPException(400, str(e))
    return my_accounts()


@router.post("/api/email/microsoft/start")
def connect_microsoft(request: Request):
    try:
        return {"url": ms_start(_u()["id"], str(request.base_url))}
    except EmailError as e:
        raise HTTPException(400, str(e))


@router.get("/auth/microsoft/callback")
def microsoft_done(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error or not code:
        return RedirectResponse("/#/settings?" + urlencode({"email_error": (error_description or error or "cancelled")[:200]}), 303)
    try:
        ms_callback(state, code, str(request.base_url))
    except EmailError as e:
        return RedirectResponse("/#/settings?" + urlencode({"email_error": str(e)[:200]}), 303)
    return RedirectResponse("/#/settings", 303)


class TestBody(BaseModel):
    to: str | None = None


@router.post("/api/email/accounts/{aid}/test")
def test_account(aid: str, body: TestBody):
    u = _u()
    try:
        send(aid, u["id"], [u["email"]], "Relay test email", "<p>Your Relay email account works: scheduled reports and alerts "
             "can be sent from it.</p>")
    except EmailError as e:
        raise HTTPException(400, str(e))
    return my_accounts()


@router.delete("/api/email/accounts/{aid}")
def remove_account(aid: str):
    try:
        remove(aid, _u()["id"])
    except EmailError as e:
        raise HTTPException(404, str(e))
    return my_accounts()


class MsApp(BaseModel):
    client_id: str
    tenant: str = "organizations"
    client_secret: str | None = None


@router.get("/api/admin/email")
def admin_email(request: Request):
    return {**ms_app_public(), "redirect_uri": _redirect(str(request.base_url))}


@router.put("/api/admin/email")
def admin_set_email(body: MsApp, request: Request):
    try:
        save_ms_app(body.client_id, body.tenant, body.client_secret, auth.who())
    except EmailError as e:
        raise HTTPException(400, str(e))
    return admin_email(request)
