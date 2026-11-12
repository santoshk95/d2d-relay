"""Test stack only, against Razorpay's real TEST mode (keys in tests/stack/.env.real, git-ignored; test keys move no money).

python -I -X utf8 rzp_real_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
Orders made through D2D Relay and read back from Razorpay; the refusals; Razorpay's own error answers; test keys
letting only PASDACS's own workspace buy. Paying itself is done in the browser (rzp_real_ui.py).
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402
import pay_check as pc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = dict(x.strip().split("=", 1) for x in open(os.path.join(HERE, "..", "stack", ".env.real"))
           if "=" in x and not x.lstrip().startswith("#"))
KEY, SECRET = ENV["TEST_RZP_KEY_ID"], ENV["TEST_RZP_SECRET"]
PACKS = [{"credits": 100, "price": 999, "usd": 100}, {"credits": 250, "price": 2249, "usd": 250}, {"credits": 500, "price": 3999, "usd": 500}]


def razorpay(path: str):
    """Razorpay's API, read directly (to see what D2D Relay made there)."""
    req = urllib.request.Request("https://api.razorpay.com/v1" + path,
                                 headers={"Authorization": "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
    s, a = admin.put("/api/admin/payments/settings", {"on": False, "who": "owners", "gst": 18, "note": "", "packs": PACKS, "invoice": pc.SELLER})
    c.check("setup: packs saved (selling left off: test keys need no switch for PASDACS)", s == 200, (s, c.detail_of(a)))
    s, a = admin.get("/api/admin/payments")
    c.check("admin: the page sees test keys", s == 200 and a["mode"] == "test" and a["key_id"].startswith("rzp_test_"), (s, a.get("mode")))

    other = c.Person(f"ola.other@real{c.STAMP}.com")
    s, r = other.sign_in("Real Other", "Ola Other")
    s, me = other.get("/api/me")
    c.check("test keys: another organisation cannot buy (no free credits)", s == 200 and me["org"]["pay"]["on"] is False, me.get("org", {}).get("pay"))
    s, r = other.get("/api/payments")
    c.check("test keys: ... and gets no packs", s == 200 and r["packs"] == [], (s, r))

    pas = c.signed_in("info@pasdacs.com", c.BASE)
    plain = pas.call                                # rupee flows: Cloudflare's country header for India
    pas.call = lambda method, path, body=None, headers=None: plain(method, path, body, {"cf-ipcountry": "IN", **(headers or {})})
    s, b = pas.put("/api/payments/billing", {**pc.BUYER_KA, "name": "PASDACS"})
    c.check("billing: PASDACS's workspace gives its billing details (Karnataka)", s == 200 and b.get("billing_needed") is False, (s, c.detail_of(b)))
    s, me = pas.get("/api/me")
    c.check("test keys: PASDACS's own workspace can buy, marked as test", me["org"]["pay"] == {"on": True, "can": True, "test": True}, me["org"].get("pay"))
    s, r = pas.get("/api/payments")
    packs = {p["credits"]: p for p in r.get("packs", [])}
    c.check("test keys: PASDACS gets the packs", s == 200 and set(packs) == {100, 250, 500}, (s, r))
    start = r.get("credits")

    s, o = pas.post("/api/payments/order", {"pack": packs[100]["id"]})
    c.check("order: made at Razorpay through D2D Relay", s == 200 and o.get("order_id", "").startswith("order_") and o["key"] == KEY and o["test"] is True, (s, o))
    s2, ro = razorpay(f"/orders/{o.get('order_id')}")
    c.check("order: Razorpay holds it for ₹1,178.82 in INR, with our receipt and notes",
            s2 == 200 and ro["amount"] == 117882 and ro["currency"] == "INR" and ro["receipt"] == o["id"] and ro["status"] == "created"
            and ro["notes"].get("workspace") == "platform" and ro["notes"].get("credits") == "100", (s2, ro))
    s, v = pas.post("/api/payments/verify", {"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_ZZZZZZZZZZZZZZ", "razorpay_signature": "f" * 64})
    c.check("verify: a made-up signature is refused (400)", s == 400, (s, c.detail_of(v)))
    ghost = "pay_" + "Q" * 14
    sig = hmac.new(SECRET.encode(), f"{o['order_id']}|{ghost}".encode(), hashlib.sha256).hexdigest()
    s, v = pas.post("/api/payments/verify", {"razorpay_order_id": o["order_id"], "razorpay_payment_id": ghost, "razorpay_signature": sig})
    c.check("verify: a payment Razorpay does not know is refused (409), with Razorpay's own reason", s == 409 and "could not be used" in c.detail_of(v),
            (s, c.detail_of(v)))
    s, r = pas.get("/api/payments")
    c.check("look-up: an unpaid order is looked up at Razorpay without harm", s == 200 and r["credits"] == start
            and any(p["id"] == o["id"] and p["status"] == "created" for p in r["payments"]), (s, r.get("credits")))
    out = g.app("""
from app import payments
payments.KEY_SECRET = "wrong-secret"
try:
    payments._api("POST", "/orders", {"amount": 10000, "currency": "INR", "receipt": "auth-test"})
    print("no error")
except payments.PayError as e:
    print(f"PayError {e.status}: {e}")
""")
    c.check("keys: wrong keys give Razorpay's own 'Authentication failed' (401)", "PayError 401" in out and "Authentication failed" in out, out[-300:])
    out = g.app("""
from app import payments
try:
    payments._api("POST", "/orders", {"amount": 50, "currency": "INR", "receipt": "min-test"})
    print("no error")
except payments.PayError as e:
    print(f"PayError {e.status}: {e}")
""")
    c.check("keys: Razorpay's refusals come through as text (an order under ₹1)", "PayError 400" in out, out[-300:])
    # US dollars: a buyer billed abroad, anywhere but India (here: Cloudflare cannot say)
    s, b = pas.put("/api/payments/billing", {**pc.BUYER_US, "name": "PASDACS (abroad test)"})
    s, ru = pas.get("/api/payments", headers={"cf-ipcountry": ""})
    usd = {p["credits"]: p for p in ru.get("packs", [])}
    c.check("dollars: outside India the packs are in US dollars", ru.get("currency") == "USD" and set(usd) == {100, 250, 500}, ru.get("currency"))
    s, ou = pas.post("/api/payments/order", {"pack": usd[100]["id"]}, headers={"cf-ipcountry": ""})
    s2, rou = razorpay(f"/orders/{ou.get('order_id')}")
    c.check("dollars: Razorpay takes the order in USD", s == 200 and s2 == 200 and rou["currency"] == "USD" and rou["amount"] == 10000, (s, ou, s2, rou))
    print(json.dumps({"order": o.get("order_id"), "payment_row": o.get("id"), "credits_now": start, "usd_order": ou.get("order_id")}))
    bad = [n for n, ok in c.RESULTS if not ok]
    print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
