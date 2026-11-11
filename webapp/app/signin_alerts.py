"""D2D Relay: PASDACS is emailed on every successful sign-in (the user's request of 2026-11-11, to watch for abuse).

One email per sign-in, to D2D_SIGNIN_ALERTS_TO (default: the credits contact, info@pasdacs.com): who signed in, their
organisation (and whether it was created just now, or they joined it just now), the site (public or admin portal),
the network address and country Cloudflare saw, the browser, whether it is the person's first sign-in, the credits
left, and how many sign-in codes that network asked for in the last hour. The email goes out in the background:
a sign-in never waits for it and never fails because of it. Sign-ins need a code, and codes are rate limited per
address and per network (otp.py), so the alerts are rate limited too. D2D_SIGNIN_ALERTS=0 turns them off.
Without mail (a test install) the alert is printed to the log instead ("[signin-alert] ...").
"""
from __future__ import annotations

import html
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import Request

from . import db, orgs, portal

ENABLED = os.environ.get("D2D_SIGNIN_ALERTS", "1").strip() not in ("0", "false", "no", "off")
TO = (os.environ.get("D2D_SIGNIN_ALERTS_TO") or orgs.CONTACT).strip()
IST = timezone(timedelta(hours=5, minutes=30))
KINDS = {"signed_in": "signed in", "joined": "joined the organisation (their first sign-in)",
         "created": "created a new organisation", "admin": "signed in to the admin portal"}


def sign_in(tid: str, uid: str, kind: str, request: Request) -> None:
    """Called once a session exists. Never raises; the email is sent from a background thread."""
    if not ENABLED or not TO:
        return
    try:
        seen = {"ip": (request.headers.get("cf-connecting-ip") or (request.client.host if request.client else ""))[:64],
                "country": (request.headers.get("cf-ipcountry") or "")[:8],
                "agent": (request.headers.get("user-agent") or "")[:240],
                "site": "admin portal" if portal.ADMIN else "public site", "at": time.time()}
        threading.Thread(target=_send, args=(tid, uid, kind, seen), daemon=True, name="signin-alert").start()
    except Exception:  # noqa: BLE001 - an alert never stops a sign-in
        traceback.print_exc()


def _send(tid: str, uid: str, kind: str, seen: dict) -> None:
    try:
        with db.use(tid):
            u = db.one("SELECT id, email, name, org_role FROM users WHERE id = ?", (uid,)) or {}
            sessions = db.one("SELECT count(*) AS n FROM sessions WHERE user_id = ?", (uid,))["n"]
        with db.use(db.PLATFORM):
            o = orgs.row(tid) or {}
            codes = db.one("SELECT count(*) AS n FROM otp_codes WHERE ip = ? AND created > ?",
                           (seen["ip"], seen["at"] - 3600))["n"] if seen["ip"] else 0
        email, org = u.get("email") or "?", o.get("name") or tid
        if kind == "created":
            subject = f"D2D Relay: new organisation {org} ({email})"
        elif kind == "joined":
            subject = f"D2D Relay: {email} joined {org}"
        elif kind == "admin":
            subject = f"D2D Relay admin portal sign-in: {email}"
        else:
            subject = f"D2D Relay sign-in: {email} ({org})"
        when = datetime.fromtimestamp(seen["at"], IST).strftime("%Y-%m-%d %H:%M:%S IST")
        rows = [("Who", f"{u.get('name') or ''} <{email}>"),
                ("Organisation", f"{org} (@{o.get('domain') or '?'})" + (" · the platform's own" if tid == db.PLATFORM else "")),
                ("What", KINDS.get(kind, kind)),
                ("Role", "owner" if u.get("org_role") == "admin" else "member"),
                ("First sign-in", "yes" if sessions <= 1 else f"no ({sessions} sessions on record)"),
                ("When", when), ("Where", seen["site"]),
                ("Network", f"{seen['ip'] or '?'}" + (f" · {seen['country']}" if seen["country"] else "")),
                ("Codes asked from this network in the last hour", str(codes)),
                ("Browser", seen["agent"] or "?"),
                ("Credits left", f"{o.get('credits', '?')}")]
        body = ("<p>Someone signed in to D2D Relay.</p><table cellpadding=\"4\" style=\"border-collapse:collapse\">"
                + "".join(f"<tr><td style=\"color:#666\">{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in rows)
                + "</table><p style=\"color:#777;font-size:12px\">D2D Relay sign-in alerts (D2D_SIGNIN_ALERTS). "
                  "Pause an organisation or switch a person off on the admin portal.</p>")
        from . import otp
        if otp.configured():
            from . import otp_mail
            otp_mail.send(TO, subject, body)
        else:
            print(f"[signin-alert] to {TO}: {subject} | " + " | ".join(f"{k}: {v}" for k, v in rows), flush=True)
        with db.use(db.PLATFORM):
            db.audit("signin.alert", email, {"kind": kind, "tenant": tid, "ip": seen["ip"], "country": seen["country"],
                                             "site": seen["site"], "to": TO}, "system")
    except Exception:  # noqa: BLE001 - the sign-in already happened; the alert is best effort
        traceback.print_exc()
