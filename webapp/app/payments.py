"""D2D Relay: buying credits online with Razorpay (item 23).

An organisation buys a pack of credits on its Organisation page (Buy credits). The server makes a Razorpay order for
the pack's price (the amount is always the server's, never the browser's); Razorpay's own checkout window takes the
payment (card, UPI, netbanking, wallet: card and bank details never reach D2D Relay); the credits are added once
Razorpay has captured the payment. Three ways lead there, and all three are safe to repeat: a payment adds its credits
once, in the database transaction that marks it paid (_fulfil):
  1. the checkout's answer (POST /api/payments/verify): Razorpay's signature over "order_id|payment_id" is checked with
     the key secret, then the payment is fetched from Razorpay (its order, amount and currency must match) and captured
     when it was only authorised;
  2. Razorpay's webhook (POST /api/payments/webhook, no sign-in: the body is signed with the webhook secret):
     payment.captured, order.paid, payment.failed, refund.processed. It covers a tab closed before the answer came;
  3. a look at Razorpay when the Organisation page opens, or when a platform admin presses Check on the admin portal:
     checkouts of the last two days that are still waiting.

Keys (.env only, never in commits): RELAY_RAZORPAY_KEY_ID, RELAY_RAZORPAY_KEY_SECRET, RELAY_RAZORPAY_WEBHOOK_SECRET.
Test keys (rzp_test_...) move no money, so with them only PASDACS's own workspace may buy (anyone else would get
credits for nothing); D2D_PAYMENTS_TEST_FOR=all opens test payments to every organisation, on a test install only.
With live keys (rzp_live_...) organisations buy once a platform admin switches selling on. The admin portal's Payments
page sets the packs and their prices, GST, a note under the prices and who may buy (relay.tn_meta 'd2d_payments').

Records: relay.tn_payments, one row per checkout (created, then paid or failed; refunded once Razorpay refunded all of
it). Paid rows are accounting records and stay (tax law asks for eight years); checkouts never paid are deleted after
the log period (governance.sweep). Refunds are made on the Razorpay Dashboard: the webhook records them and tells
PASDACS, who takes the credits back by hand when that is the rule (Organisations, Credits).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import db, notify, orgs, portal

router = APIRouter()

KEY_ID = (os.environ.get("D2D_RAZORPAY_KEY_ID") or "").strip()
KEY_SECRET = (os.environ.get("D2D_RAZORPAY_KEY_SECRET") or "").strip()
WEBHOOK_SECRET = (os.environ.get("D2D_RAZORPAY_WEBHOOK_SECRET") or "").strip()
API = (os.environ.get("D2D_RAZORPAY_API") or "https://api.razorpay.com/v1").rstrip("/")   # a stand-in on the test stack
TEST_FOR = (os.environ.get("D2D_PAYMENTS_TEST_FOR") or "platform").strip().lower()      # test keys: "platform" or "all"
WEBHOOK_PATH = "/api/payments/webhook"
EVENTS = ("payment.captured", "order.paid", "payment.failed", "refund.processed")      # what the webhook listens to
SETTINGS_KEY = "d2d_payments"
DEFAULTS = {"on": False, "who": "owners", "gst": 0, "note": "", "packs": []}
MAX_PACKS = 6
ORDERS_PER_HOUR = 10            # checkouts one person may open in an hour
CHECK_DAYS = 2                  # how far back a checkout still waiting is looked up at Razorpay
PAY_ID = re.compile(r"^pay_[A-Za-z0-9]{6,40}$")
ORDER_ID = re.compile(r"^order_[A-Za-z0-9]{6,40}$")
METHODS = {"card": "Card", "upi": "UPI", "netbanking": "Netbanking", "wallet": "Wallet", "emi": "EMI", "paylater": "Pay later",
           "bank_transfer": "Bank transfer"}
IST = timezone(timedelta(hours=5, minutes=30))
_checking = threading.Lock()    # one look at Razorpay for waiting checkouts at a time (in this process)


class PayError(Exception):
    """Razorpay refused, could not be reached, or answered something that cannot be used. The text is shown."""

    def __init__(self, text: str, status: int = 0):
        super().__init__(text)
        self.status = status


# ---------------------------------------------------------------- settings and what is on sale

def mode() -> str:
    """'live', 'test' (rzp_test_ keys: no money moves) or 'off' (no keys on this install)."""
    if not (KEY_ID and KEY_SECRET):
        return "off"
    return "test" if KEY_ID.startswith("rzp_test_") else "live"


def settings() -> dict:
    """What a platform admin set on the admin portal (Payments)."""
    try:
        s = json.loads(db.ctl_meta(SETTINGS_KEY) or "{}")
    except ValueError:
        s = {}
    s = s if isinstance(s, dict) else {}
    return {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS or k in ("updated", "updated_by")}}


def packs(s: dict | None = None) -> list[dict]:
    """The packs on sale, fewest credits first: price before GST, the GST added and the amount charged (all in paise).
    A pack's id changes with its price or the GST, so a dialog left open with old prices cannot buy at them."""
    s = s or settings()
    bp = int(round(float(s.get("gst") or 0) * 100))                 # basis points: 18% = 1800
    out = []
    for p in s.get("packs") or []:
        try:
            credits, rupees = int(p["credits"]), int(p["price"])
        except (KeyError, TypeError, ValueError):
            continue
        base = rupees * 100
        tax = (base * bp + 5000) // 10000                           # rounded half up, to the paisa
        out.append({"id": f"{credits}-{rupees}-{bp}", "credits": credits, "price": base, "gst": tax, "amount": base + tax})
    return sorted(out, key=lambda x: x["credits"])


def offer(u: dict | None, o: dict | None) -> dict:
    """Whether buying online is open to this organisation (on) and to this person (can, else why)."""
    m, s = mode(), settings()
    shut = {"on": False, "can": False}
    if not o or m == "off" or not s["packs"]:
        return shut
    if m == "test" and o["tenant_id"] != db.PLATFORM and TEST_FOR != "all":
        return shut                         # test payments move no money: anyone else would get credits for nothing
    if m == "live" and not s["on"]:
        return shut
    out = {"on": True, "can": True, "test": m == "test"}
    if u and u.get("home_tenant"):
        return {**out, "can": False, "why": "Guests cannot buy credits for this organisation."}
    if s["who"] != "everyone" and not orgs.is_owner(u):
        return {**out, "can": False, "why": "Only your organisation's owners can buy credits. Ask one of them, or ask PASDACS (Request credits)."}
    return out


def inr(paise: int | None, decimals: bool = False) -> str:
    """₹1,17,882.50 (Indian grouping); whole rupees without decimals unless asked."""
    rupees, p = divmod(int(paise or 0), 100)
    s = str(rupees)
    if len(s) > 3:
        head, groups = s[:-3], [s[-3:]]
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups)
    return f"₹{s}" + (f".{p:02d}" if p or decimals else "")


def _ist(ts: float | None) -> str:
    return datetime.fromtimestamp(ts or time.time(), IST).strftime("%d %b %Y, %H:%M IST")


# ---------------------------------------------------------------- Razorpay

def _api(method: str, path: str, body: dict | None = None, timeout: float = 20) -> dict:
    try:
        r = httpx.request(method, API + path, json=body, auth=(KEY_ID, KEY_SECRET), timeout=timeout)
    except httpx.HTTPError as e:
        raise PayError(f"Razorpay could not be reached ({type(e).__name__}).") from None
    try:
        j = r.json()
    except ValueError:
        j = None
    if r.status_code >= 400 or not isinstance(j, dict):
        err = j.get("error") if isinstance(j, dict) and isinstance(j.get("error"), dict) else {}
        raise PayError((err.get("description") or f"Razorpay answered HTTP {r.status_code}.").strip(), r.status_code)
    return j


def _signed(message: bytes | str, signature: str, secret: str) -> bool:
    """Razorpay's HMAC-SHA256 signature, compared in constant time."""
    if not secret or not signature:
        return False
    if isinstance(message, str):
        message = message.encode()
    want = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, signature.strip())


def _mismatch(r: dict, pay: dict) -> str:
    """Why a Razorpay payment cannot pay for this checkout ('' when it can)."""
    if pay.get("order_id") != r["order_id"]:
        return f"payment {pay.get('id')} belongs to order {pay.get('order_id')}, not {r['order_id']}"
    if int(pay.get("amount") or 0) != int(r["amount"]) or (pay.get("currency") or "") != r["currency"]:
        return f"payment {pay.get('id')} is for {pay.get('currency')} {pay.get('amount')}, not {r['currency']} {r['amount']}"
    return ""


def _captured(r: dict, pay: dict) -> dict:
    """The payment, captured: it must belong to this checkout and be for its amount; one only authorised is captured
    here (when the Razorpay account does not capture on its own). PayError when it cannot be used."""
    bad = _mismatch(r, pay)
    if bad:
        raise PayError(bad, 422)
    if pay.get("status") == "authorized" and PAY_ID.match(pay.get("id") or ""):
        try:
            pay = _api("POST", f"/payments/{pay['id']}/capture", {"amount": int(r["amount"]), "currency": r["currency"]})
        except PayError:
            pay = _api("GET", f"/payments/{pay['id']}")             # captured meanwhile, by the account's own setting
        bad = _mismatch(r, pay)
        if bad:
            raise PayError(bad, 422)
    return pay


# ---------------------------------------------------------------- paid, failed, refunded

def _fulfil(r: dict, pay: dict, via: str) -> bool:
    """Mark the checkout paid and add its credits: once, in one transaction. False: it was paid before."""
    now = time.time()
    note = f"{inr(r['amount'], True)} paid online, Razorpay {pay['id']}" + ("" if r["live"] else " (a test payment: no money moved)")
    e = None
    with orgs._lock, db.transaction():                                  # noqa: SLF001 - the credits' own lock
        if not db.run("UPDATE relay.tn_payments SET status = 'paid', payment_id = ?, method = ?, paid = ?, updated = ?, error = NULL "
                      "WHERE id = ? AND status IN ('created', 'failed')",
                      (pay["id"], (pay.get("method") or "")[:30] or None, now, now, r["id"])):
            return False
        e = orgs._entry(r["tenant_id"], "adjust", int(r["credits"]), what="purchase", note=note, ref=r["id"],   # noqa: SLF001
                        who={"id": r.get("user_id"), "name": r.get("user_name")})
        if e:
            db.run("UPDATE relay.tn_payments SET credit_id = ? WHERE id = ?", (e["id"], r["id"]))
    _paid_news({**r, "status": "paid", "payment_id": pay["id"], "method": pay.get("method"), "paid": now}, via, bool(e))
    return True


def _failed(r: dict, pay: dict) -> None:
    """Razorpay says the payment failed. The customer may still retry on the same order, which then pays it."""
    why = (pay.get("error_description") or pay.get("error_reason") or "declined")[:300]
    db.run("UPDATE relay.tn_payments SET status = 'failed', payment_id = ?, method = ?, error = ?, updated = ? WHERE id = ? AND status = 'created'",
           (pay.get("id"), (pay.get("method") or "")[:30] or None, why, time.time(), r["id"]))


def _refunded(r: dict, ref: dict) -> bool:
    """Razorpay refunded (part of) a payment: recorded once per refund; PASDACS and the owners are told. The credits
    are not taken back here: PASDACS does that by hand when that is the rule."""
    rid = str(ref.get("id") or "")
    with db.transaction():
        cur = db.one("SELECT refunds, refunded, amount, status FROM relay.tn_payments WHERE id = ?", (r["id"],))
        done = json.loads(cur["refunds"] or "[]")
        if not rid or rid in done:
            return False
        total = int(cur["refunded"] or 0) + int(ref.get("amount") or 0)
        db.run("UPDATE relay.tn_payments SET refunds = ?, refunded = ?, status = ?, updated = ? WHERE id = ?",
               (json.dumps(done + [rid]), total, "refunded" if total >= int(cur["amount"]) else cur["status"], time.time(), r["id"]))
    from . import tenancy
    amount = inr(ref.get("amount"), True)
    tenancy.ctl_audit("d2d.payment_refunded", r["tenant_id"], r["id"], {"refund": rid, "amount": ref.get("amount"), "total": total},
                      who="system")
    try:
        with db.use(r["tenant_id"]):
            for uid in {r.get("user_id"), *orgs.owner_ids()} - {None}:
                notify.add(uid, "ops", f"{amount} refunded to {r['org_name']}",
                           f"PASDACS refunded {amount} of the payment for {r['credits']:,} credits ({_ist(r.get('paid'))}).", "#/org")
    except Exception:  # noqa: BLE001 - the organisation may be gone; PASDACS is told below
        traceback.print_exc()
    orgs._tell_platform(f"Refund for {r['org_name']}: {amount}", f"Razorpay refunded {amount} of {r['payment_id']} ({r['credits']:,} credits). "  # noqa: SLF001
                        "The credits were not taken back; do it on Organisations if that is the rule.", "#/payments")
    _mail(orgs.CONTACT, f"D2D Relay: {amount} refunded to {r['org_name']}", "Razorpay refunded a D2D Relay payment.",
          _rows(r) + [("Refunded now", amount), ("Refunded in all", inr(total, True)), ("Razorpay refund", rid)],
          "The organisation keeps the credits it bought until you take them back by hand (admin portal, Organisations, Credits).")
    return True


def _alert(r: dict | None, text: str, pay: dict | None = None) -> None:
    """Something only a person can sort out (a payment that does not match, or a second one for one order)."""
    from . import tenancy
    tenancy.ctl_audit("d2d.payment_alert", (r or {}).get("tenant_id"), (r or {}).get("id"), {"text": text, "payment": (pay or {}).get("id")},
                      who="system")
    orgs._tell_platform("A payment needs a look", text, "#/payments")                            # noqa: SLF001
    _mail(orgs.CONTACT, "D2D Relay: a payment needs a look", text, _rows(r) if r else [("Razorpay payment", (pay or {}).get("id") or "")])


def _paid_news(r: dict, via: str, added: bool) -> None:
    """Everyone who should know: the buyer and the owners (in the app), the buyer (a receipt by email), PASDACS."""
    from . import tenancy
    test = "" if r["live"] else " (test)"
    try:
        tenancy.ctl_audit("d2d.payment", r["tenant_id"], r["id"], {"credits": r["credits"], "amount": r["amount"], "payment": r["payment_id"],
                          "method": r.get("method"), "via": via, "live": bool(r["live"]), "added": added}, who=r.get("user_id") or "system")
        if added:
            with db.use(r["tenant_id"]):
                for uid in {r.get("user_id"), *orgs.owner_ids()} - {None}:
                    notify.add(uid, "ops", f"+{r['credits']:,} credits for {r['org_name']}",
                               f"{r.get('user_name') or 'Someone'} paid {inr(r['amount'])} online{test}. The credits are in.", "#/org")
        orgs._tell_platform(f"{r['org_name']} bought {r['credits']:,} credits{test}",                  # noqa: SLF001
                            f"{r.get('user_name') or ''} ({r.get('email') or ''}) paid {inr(r['amount'], True)}, Razorpay {r['payment_id']}."
                            + ("" if added else " The organisation is gone, so no credits were added: refund it on the Razorpay Dashboard."),
                            "#/payments")
    except Exception:  # noqa: BLE001 - the payment is recorded; the news is best effort
        traceback.print_exc()
    rows = _rows(r)
    if added and r.get("email"):
        _mail(r["email"], f"D2D Relay: payment received, {r['credits']:,} credits added to {r['org_name']}{test}",
              f"Thank you. We received your payment and added {r['credits']:,} credits to {r['org_name']}.", rows,
              "This is a payment receipt, not a tax invoice. Questions about it? Reply to this email.", reply_to=orgs.CONTACT)
    _mail(orgs.CONTACT, f"D2D Relay: {r['org_name']} bought {r['credits']:,} credits for {inr(r['amount'])}{test}",
          "A D2D Relay organisation bought credits online." if added else
          "A payment came in for an organisation that no longer exists, so no credits were added. Refund it on the Razorpay Dashboard.",
          rows, reply_to=r.get("email") or None)


def _rows(r: dict) -> list[tuple[str, str]]:
    out = [("Receipt", r["id"]), ("Date", _ist(r.get("paid") or r.get("created"))), ("Organisation", r.get("org_name") or ""),
           ("Paid by", f"{r.get('user_name') or ''} <{r.get('email') or ''}>"), ("Credits", f"{int(r['credits']):,}")]
    if r.get("gst"):
        rate = round(int(r["gst"]) * 100 / max(int(r["price"]), 1), 2)
        out += [("Price", inr(r["price"], True)), (f"GST ({rate:g}%)", inr(r["gst"], True))]
    out += [("Total paid", inr(r["amount"], True)), ("Paid with", METHODS.get(r.get("method") or "", r.get("method") or "Razorpay")),
            ("Razorpay payment", r.get("payment_id") or "")]
    if not r.get("live"):
        out.append(("Test payment", "made with Razorpay test keys: no money moved"))
    return out


def _mail(to: str, subject: str, intro: str, rows: list[tuple[str, str]], outro: str = "", reply_to: str | None = None) -> None:
    """An email from a background thread (a payment never waits for it); without mail set up, a line in the log."""
    def send() -> None:
        try:
            from . import otp
            e = html.escape
            body = (f"<p>{e(intro)}</p><table cellpadding=\"4\" style=\"border-collapse:collapse\">"
                    + "".join(f"<tr><td style=\"color:#666\">{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows) + "</table>"
                    + (f"<p>{e(outro)}</p>" if outro else "")
                    + f"<p style=\"color:#777;font-size:12px\">D2D Relay · a Relay Platform product by PASDACS · {e(orgs.CONTACT)}</p>")
            if otp.configured():
                from . import otp_mail
                otp_mail.send(to, subject, body, reply_to=reply_to)
            else:
                print(f"[payments] mail to {to}: {subject} | " + " | ".join(f"{k}: {v}" for k, v in rows), flush=True)
        except Exception:  # noqa: BLE001 - the payment is recorded and shown in the app either way
            traceback.print_exc()
    if to:
        threading.Thread(target=send, daemon=True, name="payment-mail").start()


# ---------------------------------------------------------------- checkouts still waiting

def check_waiting(tid: str | None = None, pid: str | None = None, force: bool = False, limit: int = 5, budget: float = 8) -> int:
    """Ask Razorpay about checkouts still waiting (a tab closed before the answer, a webhook not set up yet): one that
    was paid gets its credits. Each is looked up at most once a minute, for CHECK_DAYS days (force: now, whatever its
    age), and the look stops after `budget` seconds (a page waits for it). Returns how many were completed."""
    m = mode()
    if m == "off" or not _checking.acquire(blocking=False):
        return 0
    try:
        now = time.time()
        sql, args = "SELECT * FROM relay.tn_payments WHERE status IN ('created', 'failed') AND live = ?", [1 if m == "live" else 0]
        if not force:
            sql += " AND created > ? AND (checked IS NULL OR checked < ?)"
            args += [now - CHECK_DAYS * 86400, now - 60]
        if tid:
            sql, args = sql + " AND tenant_id = ?", args + [tid]
        if pid:
            sql, args = sql + " AND id = ?", args + [pid]
        done = 0
        for r in db.q(sql + " ORDER BY created DESC LIMIT ?", (*args, limit)):
            left = budget - (time.time() - now)
            if left < 1:
                break
            db.run("UPDATE relay.tn_payments SET checked = ? WHERE id = ?", (now, r["id"]))
            if not ORDER_ID.match(r["order_id"] or ""):
                continue
            try:
                items = _api("GET", f"/orders/{r['order_id']}/payments", timeout=min(left, 8)).get("items") or []
                good = [p for p in items if p.get("status") in ("captured", "authorized") and not _mismatch(r, p)]
                good.sort(key=lambda p: p.get("status") != "captured")          # captured first
                if good:
                    pay = _captured(r, good[0])
                    if pay.get("status") == "captured" and _fulfil(r, pay, "check"):
                        done += 1
                elif items and r["status"] == "created" and all(p.get("status") == "failed" for p in items):
                    _failed(r, items[0])
            except PayError:
                continue
        return done
    finally:
        _checking.release()


# ---------------------------------------------------------------- the organisation's side

def _public(r: dict) -> dict:
    return {"id": r["id"], "created": r["created"], "paid": r.get("paid"), "status": r["status"], "credits": r["credits"],
            "price": r["price"], "gst": r["gst"], "amount": r["amount"], "currency": r["currency"], "method": r.get("method"),
            "payment_id": r.get("payment_id"), "refunded": r.get("refunded") or 0, "user_name": r.get("user_name"),
            "live": bool(r.get("live")), "error": r.get("error")}


@router.get("/api/payments")
def overview():
    """Buy credits and the Organisation page: whether this person can buy here, the packs and their prices, and the
    organisation's payments (owners see all of them, others their own). Checkouts still waiting are looked up first."""
    u, o = orgs._must()                                                      # noqa: SLF001
    tid = o["tenant_id"]
    if mode() != "off":
        check_waiting(tid)
    o = orgs.row(tid) or o                                                   # its credits, after a payment just found
    off, s = offer(u, o), settings()
    everyone = orgs.is_owner(u)
    recent = time.time() - CHECK_DAYS * 86400
    sql = "SELECT * FROM relay.tn_payments WHERE tenant_id = ? AND (status IN ('paid', 'refunded') OR created > ?)"
    rows = db.q(sql + (" ORDER BY created DESC LIMIT 50" if everyone else " AND user_id = ? ORDER BY created DESC LIMIT 50"),
                (tid, recent) if everyone else (tid, recent, u["id"]))
    return {**off, "packs": packs(s) if off["on"] else [], "gst": s["gst"] if off["on"] else 0, "note": s["note"] if off["on"] else "",
            "credits": o["credits"], "org": o["name"], "contact": orgs.CONTACT, "payments": [_public(r) for r in rows], "all": everyone}


class Buy(BaseModel):
    pack: str


@router.post("/api/payments/order")
def start(body: Buy):
    """Open a checkout: a Razorpay order for the pack's price, and what Razorpay's checkout window needs."""
    u, o = orgs._must()                                                      # noqa: SLF001
    off = offer(u, o)
    if not off["on"]:
        raise HTTPException(403, f"Buying credits online is not open for {o['name']}. Use Request credits, or write to {orgs.CONTACT}.")
    if not off["can"]:
        raise HTTPException(403, off["why"])
    pack = next((p for p in packs() if p["id"] == body.pack), None)
    if not pack:
        raise HTTPException(409, "The prices have just changed. Close this window and open Buy credits again.")
    started = db.one("SELECT count(*) AS n FROM relay.tn_payments WHERE user_id = ? AND created > ?", (u["id"], time.time() - 3600))["n"]
    if started >= ORDERS_PER_HOUR:
        raise HTTPException(429, f"You started several payments this hour. Try again later, or write to {orgs.CONTACT}.")
    pid = "pay-" + secrets.token_hex(8)                                      # also the Razorpay receipt (40 characters at most)
    notes = {"d2d_payment": pid, "organisation": o["name"][:250], "workspace": o["tenant_id"], "credits": str(pack["credits"]),
             "email": (u.get("email") or "")[:250]}
    try:
        r = _api("POST", "/orders", {"amount": pack["amount"], "currency": "INR", "receipt": pid, "notes": notes})
    except PayError as e:
        raise HTTPException(502, f"Razorpay could not start the payment: {e} Nothing was charged. Try again in a minute, "
                                 "or use Request credits.") from None
    if not ORDER_ID.match(str(r.get("id") or "")) or r.get("amount") != pack["amount"] or r.get("currency") != "INR":
        raise HTTPException(502, "Razorpay's answer did not match the price, so the payment was not started. Nothing was charged.")
    now, live = time.time(), mode() == "live"
    db.run("INSERT INTO relay.tn_payments (id, tenant_id, org_name, user_id, user_name, email, credits, price, gst, amount, currency, live, "
           "status, order_id, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INR', ?, 'created', ?, ?, ?)",
           (pid, o["tenant_id"], o["name"], u["id"], u.get("name"), u.get("email"), pack["credits"], pack["price"], pack["gst"],
            pack["amount"], 1 if live else 0, r["id"], now, now))
    db.audit("payment.started", pid, {"credits": pack["credits"], "amount": pack["amount"], "order": r["id"], "live": live}, u["id"])
    return {"id": pid, "key": KEY_ID, "order_id": r["id"], "amount": pack["amount"], "currency": "INR", "name": "D2D Relay",
            "description": f"{pack['credits']:,} credits for {o['name']}"[:250], "test": not live,
            "prefill": {"name": u.get("name") or "", "email": u.get("email") or ""}}


class Answer(BaseModel):
    razorpay_order_id: str = ""
    razorpay_payment_id: str = ""
    razorpay_signature: str = ""


def _done(r: dict) -> dict:
    o = orgs.row(r["tenant_id"]) or {}
    return {"ok": True, "payment": _public(r), "added": r["credits"], "credits": o.get("credits"), "org": o.get("name") or r.get("org_name")}


@router.post("/api/payments/verify")
def verify(body: Answer):
    """Razorpay's checkout says it was paid: check its signature, then Razorpay itself, then add the credits (once)."""
    u, o = orgs._must()                                                      # noqa: SLF001
    r = db.one("SELECT * FROM relay.tn_payments WHERE order_id = ? AND tenant_id = ?", (body.razorpay_order_id, o["tenant_id"]))
    if not r:
        raise HTTPException(404, "There is no such payment in your organisation.")
    if r["status"] in ("paid", "refunded"):
        return _done(r)
    if not PAY_ID.match(body.razorpay_payment_id) or not _signed(f"{r['order_id']}|{body.razorpay_payment_id}", body.razorpay_signature, KEY_SECRET):
        db.audit("payment.bad_signature", r["id"], {"payment": body.razorpay_payment_id[:60]}, u["id"])
        raise HTTPException(400, "This payment could not be confirmed: Razorpay's signature does not match, so no credits were added. "
                                 f"If money left your account, write to {orgs.CONTACT} with the payment's details.")
    try:
        pay = _captured(r, _api("GET", f"/payments/{body.razorpay_payment_id}"))
    except PayError as e:
        if e.status in (0, 429) or e.status >= 500:
            raise HTTPException(503, "Razorpay has not confirmed the payment yet. The credits appear on their own as soon as it does: "
                                     "nothing more to do here.") from None
        _alert(r, f"A checkout's payment could not be used: {e}")
        raise HTTPException(409, f"This payment could not be used: {e} PASDACS has been told and will sort it out.") from None
    if pay.get("status") == "captured":
        _fulfil(r, pay, "checkout")
        return _done(db.one("SELECT * FROM relay.tn_payments WHERE id = ?", (r["id"],)))
    if pay.get("status") == "failed":
        _failed(r, pay)
        raise HTTPException(400, f"The payment failed: {pay.get('error_description') or 'it was declined'}. Nothing was charged; you can try again.")
    raise HTTPException(503, "Razorpay has not finished the payment yet. The credits appear on their own as soon as it does: nothing more to do here.")


@router.post(WEBHOOK_PATH)
async def webhook(request: Request):
    """Razorpay tells D2D Relay what happened to a payment. No sign-in: the body is signed with the webhook secret.
    Answers within Razorpay's 5 seconds (emails go out in the background); a refusal makes Razorpay retry for a day."""
    if portal.ADMIN:
        return JSONResponse({"detail": "Not on the admin portal."}, status_code=404)
    raw = await request.body()
    if not WEBHOOK_SECRET:
        return JSONResponse({"detail": "The payments webhook is not set up on this site."}, status_code=503)
    if len(raw) > 1_000_000 or not _signed(raw, request.headers.get("x-razorpay-signature") or "", WEBHOOK_SECRET):
        return JSONResponse({"detail": "The signature does not match."}, status_code=400)
    try:
        ev = json.loads(raw)
    except ValueError:
        return JSONResponse({"detail": "Not JSON."}, status_code=400)
    if not isinstance(ev, dict):
        return JSONResponse({"detail": "Not an event."}, status_code=400)
    return {"ok": True, **await asyncio.to_thread(_event, ev)}


def _event(ev: dict) -> dict:
    kind = str(ev.get("event") or "")
    pl = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
    ent = lambda k: (pl.get(k) or {}).get("entity") if isinstance(pl.get(k), dict) else None   # noqa: E731
    pay, order = ent("payment") or {}, ent("order") or {}
    if kind in ("payment.captured", "order.paid", "payment.failed"):
        oid = pay.get("order_id") or order.get("id")
        r = db.one("SELECT * FROM relay.tn_payments WHERE order_id = ?", (oid,)) if oid else None
        if not r:
            return {"ignored": "not a D2D Relay order"}                # another use of the same Razorpay account
        if kind == "payment.failed":
            if r["status"] == "created":
                _failed(r, pay)
                return {"failed": r["id"]}
            return {"ignored": f"already {r['status']}"}
        if pay.get("status") != "captured":
            return {"ignored": f"payment {pay.get('status')}"}
        if not PAY_ID.match(pay.get("id") or ""):
            return {"ignored": "no payment id"}
        bad = _mismatch(r, pay)
        if bad:
            _alert(r, f"Razorpay reported a captured payment that does not match its checkout: {bad}. No credits were added.", pay)
            return {"ignored": "does not match"}
        if r["status"] in ("paid", "refunded") and r.get("payment_id") and r["payment_id"] != pay["id"]:
            _alert(r, f"A second payment ({pay['id']}) was captured for an order already paid by {r['payment_id']}. "
                      "No credits were added for it: refund it on the Razorpay Dashboard.", pay)
            return {"ignored": "second payment"}
        return {"credited": _fulfil(r, pay, "webhook"), "payment": r["id"]}
    if kind == "refund.processed":
        ref = ent("refund") or {}
        r = db.one("SELECT * FROM relay.tn_payments WHERE payment_id = ?", (ref.get("payment_id"),)) if ref.get("payment_id") else None
        if not r:
            return {"ignored": "not a D2D Relay payment"}
        return {"refund": _refunded(r, ref), "payment": r["id"]}
    return {"ignored": kind or "no event"}


@router.get("/api/payments/{pid}/receipt")
def receipt(pid: str):
    """A paid checkout's receipt, to print or keep: for the person who paid and the organisation's owners."""
    u, o = orgs._must()                                                      # noqa: SLF001
    r = db.one("SELECT * FROM relay.tn_payments WHERE id = ? AND tenant_id = ?", (pid, o["tenant_id"]))
    if not r or (r["user_id"] != u["id"] and not orgs.is_owner(u)):
        raise HTTPException(404, "There is no such receipt.")
    if r["status"] not in ("paid", "refunded"):
        raise HTTPException(409, "This payment was not completed, so there is no receipt.")
    e = html.escape
    rows = _rows(r) + ([("Refunded", inr(r["refunded"], True))] if r.get("refunded") else [])
    page = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Receipt {e(r['id'])} · D2D Relay</title><style>"
            "body{font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;color:#1d1d1f;background:#fff;margin:0;padding:32px 16px}"
            "main{max-width:620px;margin:0 auto}h1{font-size:22px;margin:0 0 2px}.muted{color:#6b6b70}"
            "table{border-collapse:collapse;width:100%;margin:20px 0}td{padding:8px 0;border-bottom:1px solid #e6e6ea;vertical-align:top}"
            "td:first-child{color:#6b6b70;width:42%;padding-right:12px}tr.total td{font-weight:700;color:#1d1d1f}"
            ".test{background:#fff4e5;color:#8a4b00;padding:8px 12px;border-radius:6px;margin:16px 0}"
            "@media (prefers-color-scheme:dark){body{background:#151517;color:#ececf0}td{border-color:#2c2c31}tr.total td{color:#ececf0}"
            ".test{background:#3a2a12;color:#ffcf8a}}@media print{body{padding:0}}</style>"
            "<main><h1>Payment receipt</h1><div class=\"muted\">D2D Relay · a Relay Platform product by PASDACS</div>"
            + ("" if r["live"] else "<div class=\"test\">A test payment, made with Razorpay test keys: no money moved.</div>")
            + "<table>" + "".join(f"<tr{' class=total' if k == 'Total paid' else ''}><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows)
            + "</table><p class=\"muted\">Paid online through Razorpay. This is a payment receipt, not a tax invoice. "
            f"Questions: {e(orgs.CONTACT)}. Print it or save it as a PDF from your browser.</p></main></html>")
    return HTMLResponse(page, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                       "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


# ---------------------------------------------------------------- platform admins (the admin portal's Payments page)

def _admin_row(r: dict) -> dict:
    return {**_public(r), "org_name": r.get("org_name"), "tenant_id": r["tenant_id"], "email": r.get("email"),
            "order_id": r.get("order_id"), "checked": r.get("checked")}


def _site() -> str:
    """The public site's address (the webhook URL to give Razorpay); the admin portal's own address is not it."""
    from . import identity
    return (os.environ.get("D2D_PAYMENTS_SITE") or ("" if portal.ADMIN else identity.PUBLIC_URL) or "https://d2d-relay.pasdacs.com").rstrip("/")


@router.get("/api/admin/payments")
def admin_view():
    orgs._admin()                                                            # noqa: SLF001
    s = settings()
    rows = db.q("SELECT * FROM relay.tn_payments ORDER BY created DESC LIMIT 200")
    month = datetime.now(IST).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    paid = db.q("SELECT amount, refunded, paid FROM relay.tn_payments WHERE live = 1 AND status IN ('paid', 'refunded')")
    net = lambda p: int(p["amount"]) - int(p["refunded"] or 0)            # noqa: E731
    return {"mode": mode(), "key_id": (KEY_ID[:13] + "…" + KEY_ID[-4:]) if len(KEY_ID) > 20 else KEY_ID, "key_secret": bool(KEY_SECRET),
            "webhook_secret": bool(WEBHOOK_SECRET), "webhook_url": _site() + WEBHOOK_PATH, "events": list(EVENTS), "test_for": TEST_FOR,
            "settings": s, "packs": packs(s), "payments": [_admin_row(r) for r in rows], "contact": orgs.CONTACT,
            "totals": {"month": sum(net(p) for p in paid if (p["paid"] or 0) >= month), "all": sum(net(p) for p in paid), "count": len(paid)}}


class PackIn(BaseModel):
    credits: int
    price: int                  # whole rupees, before any GST added


class SettingsIn(BaseModel):
    on: bool = False
    who: str = "owners"
    gst: float = 0
    note: str = ""
    packs: list[PackIn] = []


@router.put("/api/admin/payments/settings")
def admin_save(body: SettingsIn):
    """Selling on or off, who may buy, the GST added on top (0: prices as they are), the note under the prices, the packs."""
    from . import tenancy
    u = orgs._admin()                                                        # noqa: SLF001
    if body.who not in ("owners", "everyone"):
        raise HTTPException(400, "Who may buy: owners or everyone.")
    gst = round(float(body.gst or 0), 2)
    if not 0 <= gst <= 28:
        raise HTTPException(400, "GST is a percentage from 0 to 28 (0: none added; the prices are what people pay).")
    if len(body.packs) > MAX_PACKS:
        raise HTTPException(400, f"Up to {MAX_PACKS} packs.")
    seen, out = set(), []
    for p in body.packs:
        if not 1 <= p.credits <= 100_000:
            raise HTTPException(400, "A pack has 1 to 1,00,000 credits.")
        if not 1 <= p.price <= 1_000_000:
            raise HTTPException(400, "A pack costs ₹1 to ₹10,00,000.")
        if p.credits in seen:
            raise HTTPException(400, f"Two packs have {p.credits:,} credits.")
        seen.add(p.credits)
        out.append({"credits": p.credits, "price": p.price})
    if body.on and not out:
        raise HTTPException(400, "Add at least one pack before switching selling on.")
    new = {"on": bool(body.on), "who": body.who, "gst": gst, "note": " ".join((body.note or "").split())[:200],
           "packs": sorted(out, key=lambda x: x["credits"]), "updated": time.time(), "updated_by": u.get("name") or u.get("email")}
    db.set_ctl_meta(SETTINGS_KEY, json.dumps(new))
    tenancy.ctl_audit("d2d.payment_settings", None, SETTINGS_KEY, {k: new[k] for k in DEFAULTS})
    return admin_view()


@router.post("/api/admin/payments/{pid}/check")
def admin_check(pid: str):
    """Ask Razorpay now about one checkout still waiting (whatever its age)."""
    orgs._admin()                                                            # noqa: SLF001
    r = db.one("SELECT * FROM relay.tn_payments WHERE id = ?", (pid,))
    if not r:
        raise HTTPException(404, "No such payment.")
    if r["status"] in ("created", "failed"):
        if mode() == "off" or bool(r["live"]) != (mode() == "live"):
            raise HTTPException(409, "This checkout was made with other Razorpay keys than this site has now; look it up on the Razorpay Dashboard.")
        check_waiting(pid=pid, force=True)
    return admin_view()
