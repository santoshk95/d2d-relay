"""How D2D Relay emails sign-in codes: as info@pasdacs.com, through Microsoft Graph, with a DELEGATED sign-in.

No client secret is needed: the Entra app is a public client (Authentication → "Allow public client flows" = Yes) with
the delegated Graph permissions Mail.Send and offline_access. The mailbox signs in once with a device code:

    docker exec -it -u relay -w /srv d2d-relay /opt/relay/bin/launch web python -m app.otp_mail login

Delegated means the app can only ever send as the account that signed in — so it is limited to info@pasdacs.com
without any Exchange policy. The refresh token is kept encrypted in the secrets store; every use returns a new one,
and main.py refreshes it once a day so it never lapses (Microsoft ends one after 90 days unused).

    ... python -m app.otp_mail status     who is signed in, and whether a token can be fetched
    ... python -m app.otp_mail test       email a test message to D2D_OTP_EMAIL
    ... python -m app.otp_mail logout     forget the sign-in
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import httpx

from . import db, secrets_store

TENANT = (os.environ.get("D2D_OTP_MS_TENANT") or "").strip()
CLIENT_ID = (os.environ.get("D2D_OTP_MS_CLIENT_ID") or "").strip()
SECRET = (os.environ.get("D2D_OTP_MS_CLIENT_SECRET") or "").strip()     # optional: app-only sending, if a tenant allows secrets
SENDER = (os.environ.get("D2D_OTP_FROM") or os.environ.get("D2D_OTP_EMAIL") or "").strip()
MS_LOGIN = os.environ.get("D2D_MS_LOGIN", "https://login.microsoftonline.com")
MS_GRAPH = os.environ.get("D2D_MS_GRAPH", "https://graph.microsoft.com/v1.0")
SCOPE = "offline_access https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read"
TOKEN_NAME = "otp_mail:refresh_token"
_lock = threading.Lock()


class MailError(Exception):
    pass


def _token_url() -> str:
    return f"{MS_LOGIN}/{TENANT}/oauth2/v2.0/token"


def mode() -> str:
    """'app' (client secret), 'delegated' (signed in), or '' (not set up)."""
    if TENANT and CLIENT_ID and SECRET:
        return "app"
    if TENANT and CLIENT_ID and secrets_store.get("org", TOKEN_NAME):
        return "delegated"
    return ""


def _delegated_token() -> str:
    with _lock:
        rt = secrets_store.get("org", TOKEN_NAME)
        if not rt:
            raise MailError("The sending mailbox has not signed in yet (python -m app.otp_mail login).")
        r = httpx.post(_token_url(), timeout=20, data={"client_id": CLIENT_ID, "grant_type": "refresh_token",
                                                       "refresh_token": rt, "scope": SCOPE})
        if r.status_code != 200:
            raise MailError(f"Microsoft refused the saved sign-in ({r.status_code}): {r.text[:300]}. Sign in again.")
        j = r.json()
        if j.get("refresh_token"):
            secrets_store.put("org", TOKEN_NAME, j["refresh_token"], "otp_mail")
        db.set_meta("otp_mail_refreshed", str(time.time()))
        return j["access_token"]


def _app_token() -> str:
    r = httpx.post(_token_url(), timeout=20, data={"client_id": CLIENT_ID, "client_secret": SECRET, "grant_type": "client_credentials",
                                                   "scope": "https://graph.microsoft.com/.default"})
    if r.status_code != 200:
        raise MailError(f"Microsoft sign-in for mail failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


def send(to: str, subject: str, html: str, reply_to: str | None = None) -> None:
    m = mode()
    if not m:
        raise MailError("Email sending is not set up.")
    token = _app_token() if m == "app" else _delegated_token()
    url = f"{MS_GRAPH}/users/{SENDER}/sendMail" if m == "app" else f"{MS_GRAPH}/me/sendMail"
    message = {"subject": subject, "body": {"contentType": "HTML", "content": html},
               "toRecipients": [{"emailAddress": {"address": to}}]}
    if reply_to:                        # a credit request: answering it writes to the person who asked
        message["replyTo"] = [{"emailAddress": {"address": reply_to}}]
    r = httpx.post(url, timeout=30, headers={"Authorization": "Bearer " + token},
                   json={"message": message, "saveToSentItems": False})
    if r.status_code not in (200, 202):
        raise MailError(f"Microsoft Graph refused the email ({r.status_code}): {r.text[:300]}")


def keep_alive() -> None:
    """Called once a day: use the refresh token so it never lapses."""
    if mode() == "delegated":
        _delegated_token()


# ---------------------------------------------------------------- command line (run inside the container as the web part)

def _login() -> None:
    if not (TENANT and CLIENT_ID):
        sys.exit("Set RELAY_OTP_MS_TENANT and RELAY_OTP_MS_CLIENT_ID in .env and restart the container first.")
    r = httpx.post(f"{MS_LOGIN}/{TENANT}/oauth2/v2.0/devicecode", timeout=20, data={"client_id": CLIENT_ID, "scope": SCOPE})
    if r.status_code != 200:
        sys.exit(f"Microsoft refused to start the sign-in ({r.status_code}): {r.text[:400]}\n"
                 "Check the app: Authentication → Allow public client flows = Yes.")
    dc = r.json()
    print("\n" + dc["message"] + f"\n\nSign in as {SENDER}. Waiting…", flush=True)
    end, wait = time.time() + int(dc.get("expires_in", 900)), int(dc.get("interval", 5))
    while time.time() < end:
        time.sleep(wait)
        t = httpx.post(_token_url(), timeout=20, data={"client_id": CLIENT_ID, "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                                       "device_code": dc["device_code"]})
        j = t.json()
        if t.status_code == 200:
            me = httpx.get(f"{MS_GRAPH}/me", timeout=20, headers={"Authorization": "Bearer " + j["access_token"]}).json()
            who = {(me.get("mail") or "").lower(), (me.get("userPrincipalName") or "").lower()}
            if SENDER.lower() not in who:
                sys.exit(f"That was {me.get('userPrincipalName')}, not {SENDER}. Nothing saved; run login again and sign in as {SENDER}.")
            secrets_store.put("org", TOKEN_NAME, j["refresh_token"], "otp_mail")
            db.set_meta("otp_mail_account", json.dumps({"address": SENDER, "since": time.time()}))
            print(f"Signed in as {SENDER}. D2D Relay will email sign-in codes from this mailbox.")
            return
        err = j.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            wait += 5
            continue
        sys.exit(f"Sign-in did not finish: {j.get('error_description') or err}")
    sys.exit("The code expired before the sign-in finished. Run login again.")


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "login":
        _login()
    elif cmd == "status":
        m = mode()
        print(f"sending as: {SENDER or '(not set)'} · mode: {m or 'not set up'}")
        if m:
            (_app_token if m == "app" else _delegated_token)()
            print("Microsoft gave a token: sending works.")
    elif cmd == "test":
        to = (os.environ.get("D2D_OTP_EMAIL") or SENDER).strip()
        send(to, "D2D Relay: test email", "<p>D2D Relay can send sign-in codes from this mailbox.</p>")
        print(f"Sent a test email to {to}.")
    elif cmd == "logout":
        secrets_store.delete("org", TOKEN_NAME, "otp_mail")
        print("Forgot the sign-in. Codes cannot be sent until someone signs in again.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except MailError as e:
        sys.exit(str(e))
