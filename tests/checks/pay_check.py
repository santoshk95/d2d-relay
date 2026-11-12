"""Test stack only: buying credits online (item 23) against the stand-in Razorpay (fake_razorpay.py in the web container).

python -I pay_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
The stack runs keys that look live (rzp_live_...), so selling needs a platform admin to switch it on, as on live.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = dict(x.strip().split("=", 1) for x in open(os.path.join(HERE, "..", "stack", ".env"))   # written by stack.sh
           if "=" in x and not x.lstrip().startswith("#"))
KEY, SECRET, WH = "rzp_live_D2DTESTSTACK01", ENV["TEST_RZP_SECRET"], ENV["TEST_RZP_WEBHOOK"]
FAKE = "http://127.0.0.1:8105"
STAMP = c.STAMP


def fake(path: str, body=None, auth: bool = False):
    hdr = {"Content-Type": "application/json"}
    if auth:
        hdr["Authorization"] = "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    req = urllib.request.Request(FAKE + path, data=json.dumps(body).encode() if body is not None else None, headers=hdr,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def pay(order_id: str, **kw) -> dict:
    """The customer pays the order at the stand-in Razorpay."""
    return fake("/_test/pay", {"order_id": order_id, **kw})


def answer(pr: dict) -> dict:
    return {k: pr[k] for k in ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")}


def webhook(event: str, payload: dict, secret: str = WH, sig: str | None = None, origin: str | None = None, base: str | None = None):
    raw = json.dumps({"entity": "event", "account_id": "acc_test", "event": event, "contains": list(payload), "payload": payload,
                      "created_at": int(time.time())}).encode()
    s = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest() if sig is None else sig
    hdr = {"Content-Type": "application/json", "X-Razorpay-Signature": s, "x-razorpay-event-id": "evt_" + os.urandom(6).hex()}
    if origin:
        hdr["Origin"] = origin
    req = urllib.request.Request((base or c.BASE) + "/api/payments/webhook", data=raw, headers=hdr, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def credits_of(p) -> int | None:
    s, r = p.get("/api/org")
    return r.get("credits") if s == 200 else None


def row(pid: str) -> dict:
    cols = ["status", "credits", "amount", "gst", "live", "method", "credit_id", "refunded", "user_id", "email", "org_name", "error", "payment_id"]
    out = g.sql("SELECT status, credits, amount, gst, live, coalesce(method, ''), coalesce(credit_id, ''), refunded, coalesce(user_id, ''), "
                f"coalesce(email, ''), coalesce(org_name, ''), coalesce(error, ''), coalesce(payment_id, '') FROM relay.tn_payments WHERE id = '{pid}'")
    return dict(zip(cols, out.split("|"))) if out else {}


def audits(action: str) -> int:
    return int(g.sql(f"SELECT count(*) FROM relay.tn_audit WHERE action = '{action}'") or 0)


def order(p, pack_id: str, headers: dict | None = None):
    return p.post("/api/payments/order", {"pack": pack_id}, headers=headers)


ABROAD = {"cf-ipcountry": "US"}                 # what Cloudflare adds for a buyer in the United States


def in_india(p):
    """Every call from this person carries Cloudflare's country header for India, unless a call says otherwise."""
    plain = p.call
    p.call = lambda method, path, body=None, headers=None: plain(method, path, body, {"cf-ipcountry": "IN", **(headers or {})})
    return p


_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin(first14: str) -> str:
    """A GSTIN with its check character (mod 36), for the tests."""
    total = 0
    for i, ch in enumerate(first14):
        v = _B36.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return first14 + _B36[(36 - total % 36) % 36]


SELLER = {"name": "PASDACS Test Pvt Ltd", "address": "1 Test Street\nBengaluru", "state": "29", "pin": "560001",
          "gstin": gstin("29ABCDE1234F1Z"), "sac": "998314", "prefix": "D2D", "lut": "AD2911260000001", "description": "D2D Relay credits"}
BUYER_KA = {"name": "Pay Test Pvt Ltd", "address": "2 MG Road\nBengaluru", "country": "India", "state": "29", "pin": "560002", "gstin": ""}
BUYER_MH = {"name": "Pay Test Pvt Ltd", "address": "3 Marine Drive\nMumbai", "country": "India", "state": "", "pin": "400001",
            "gstin": gstin("27AAACP1234Q1Z")}
BUYER_US = {"name": "Abroad Inc", "address": "1 Main Street, Austin, TX", "country": "United States", "state": "", "pin": "73301", "gstin": ""}


def invoice(pid: str) -> dict:
    out = g.sql(f"SELECT coalesce(invoice, '') FROM relay.tn_payments WHERE id = '{pid}'")
    return json.loads(out) if out.startswith("{") else {}


def seq(no: str) -> int:
    return int(no.rsplit("/", 1)[-1]) if no else -1


def settings(admin, **kw):
    body = {"on": True, "who": "owners", "gst": 18, "gst_included": False, "note": "Prices exclude GST.", "invoice": SELLER,
            "packs": [{"credits": 100, "price": 999, "usd": 100}, {"credits": 250, "price": 2249, "usd": 250}, {"credits": 500, "price": 3999, "usd": 500}]}
    body.update(kw)
    return admin.put("/api/admin/payments/settings", body)


def main():
    admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
    base = (admin.get("/api/admin/payments")[1] or {}).get("totals") or {}       # earlier runs on this stack, if any
    b_inr, b_usd = base.get("INR", {"all": 0, "count": 0}), base.get("USD", {"all": 0, "count": 0})
    dom = f"pay{STAMP}.com"
    owner, member = c.Person(f"olive.owner@{dom}"), c.Person(f"max.member@{dom}")
    s, r = owner.sign_in("Pay Test", "Olive Owner")
    c.check("setup: an organisation signs up", s == 200, (s, r))
    s, r = member.sign_in()
    c.check("setup: a colleague joins it", s == 200, (s, r))
    in_india(owner), in_india(member)                  # rupee flows below; dollar ones say ABROAD
    tid = g.sql(f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = '{dom}'")
    c.check("setup: it starts with 50 credits", credits_of(owner) == 50, credits_of(owner))

    # ---------------------------------------------------------------- selling is off until a platform admin opens it
    s, me = owner.get("/api/me")
    c.check("off: /api/me says buying is not open", s == 200 and me["org"]["pay"] == {"on": False, "can": False}, me.get("org", {}).get("pay"))
    s, r = owner.get("/api/payments")
    c.check("off: no packs on sale", s == 200 and r["on"] is False and r["packs"] == [], (s, r))
    s, r = order(owner, "100-999-1800")
    c.check("off: an order is refused (403)", s == 403, (s, r))
    s, a = admin.get("/api/admin/payments")
    c.check("admin: the Payments page sees live keys, both secrets and the webhook URL",
            s == 200 and a["mode"] == "live" and a["key_secret"] and a["webhook_secret"] and a["webhook_url"].endswith("/api/payments/webhook")
            and a["events"] == ["payment.captured", "order.paid", "payment.failed", "refund.processed"], (s, a if s != 200 else {k: a[k] for k in ("mode", "webhook_url")}))
    c.check("admin: the key id is shown shortened", s == 200 and a["key_id"].startswith("rzp_live_D2D") and "..." in a["key_id"], a.get("key_id"))
    s, r = owner.get("/api/admin/payments")
    c.check("admin: not on the public site (404)", s == 404, (s, r))

    # ---------------------------------------------------------------- settings: what is refused
    for name, kw in [("selling on with no packs", {"packs": []}), ("GST over 28%", {"gst": 30}),
                     ("two packs of the same size", {"packs": [{"credits": 100, "price": 999}, {"credits": 100, "price": 899}]}),
                     ("seven packs", {"packs": [{"credits": n, "price": n * 10} for n in range(1, 8)]}),
                     ("who = someone", {"who": "someone"}), ("a pack at ₹0", {"packs": [{"credits": 100, "price": 0}]}),
                     ("a dollar price below zero", {"packs": [{"credits": 100, "price": 999, "usd": -5}]}),
                     ("selling for real money without invoice details", {"invoice": {"prefix": "D2D"}}),
                     ("PASDACS's GSTIN with a wrong check character", {"invoice": {**SELLER, "gstin": SELLER["gstin"][:14] + ("A" if SELLER["gstin"][14] != "A" else "B")}}),
                     ("an invoice prefix of TEST", {"invoice": {**SELLER, "prefix": "TEST"}})]:
        s, r = settings(admin, **kw)
        c.check(f"settings: refused: {name} (400)", s == 400, (s, c.detail_of(r)))
    s, a = settings(admin)
    amounts = [(p["currency"], p["amount"], p["gst"]) for p in a.get("packs", [])] if s == 200 else []
    c.check("settings: saved; GST of 18% added to rupee prices, rounded to the paisa; dollar prices without GST",
            s == 200 and amounts == [("INR", 117882, 17982), ("INR", 265382, 40482), ("INR", 471882, 71982),
                                     ("USD", 10000, 0), ("USD", 25000, 0), ("USD", 50000, 0)], (s, amounts))
    c.check("settings: the change is audited", audits("d2d.payment_settings") >= 1)
    c.check("invoices: PASDACS's details are complete (nothing missing)", a.get("missing") == [] and a["seller"]["gstin"] == SELLER["gstin"], a.get("missing"))
    s, a2 = settings(admin, gst_included=True)
    inc = [(p["currency"], p["amount"], p["gst"]) for p in a2.get("packs", [])][:1] if s == 200 else []
    c.check("settings: rupee prices may include GST: ₹999 charged, ₹152.39 of it GST", s == 200 and inc == [("INR", 99900, 15239)], (s, inc))
    s, a = settings(admin)

    # ---------------------------------------------------------------- who may buy
    s, me = owner.get("/api/me")
    c.check("open: the owner may buy", me["org"]["pay"] == {"on": True, "can": True, "test": False}, me["org"].get("pay"))
    s, me = member.get("/api/me")
    pm = me["org"]["pay"]
    c.check("open: a member sees it but may not buy (owners only)", pm["on"] and not pm["can"] and "owners" in pm.get("why", ""), pm)
    s, r = owner.get("/api/payments")
    packs = {p["credits"]: p for p in r.get("packs", [])}
    c.check("open: the owner gets the packs and the GST", s == 200 and set(packs) == {100, 250, 500} and r["gst"] == 18 and r["note"] == "Prices exclude GST.", (s, r))
    c.check("location: in India, rupees only", r["currency"] == "INR" and {p["currency"] for p in r["packs"]} == {"INR"}, r.get("currency"))
    c.check("billing: asked for before the first purchase; the owner may give them", r["billing_needed"] is True and r["may_edit_billing"] is True
            and r["no_refunds"] == "Credits are not refundable, and a purchase cannot be cancelled once paid.", {k: r.get(k) for k in ("billing_needed", "may_edit_billing", "no_refunds")})
    s, x = order(owner, packs[100]["id"])
    c.check("billing: no order without them (409)", s == 409 and "billing" in c.detail_of(x), (s, c.detail_of(x)))
    for name, b in [("a wrong GSTIN", {**BUYER_KA, "gstin": "29AAAAA0000A1Z0"}), ("India without a PIN", {**BUYER_KA, "pin": ""}),
                    ("India without a state or GSTIN", {**BUYER_KA, "state": ""}), ("a GSTIN outside India", {**BUYER_US, "gstin": BUYER_MH["gstin"]}),
                    ("no legal name", {**BUYER_KA, "name": ""}), ("no address", {**BUYER_KA, "address": ""})]:
        s, x = owner.put("/api/payments/billing", b)
        c.check(f"billing: refused: {name} (400)", s == 400, (s, c.detail_of(x)))
    s, x = member.put("/api/payments/billing", BUYER_KA)
    c.check("billing: a member who may not buy cannot change them (403)", s == 403, (s, c.detail_of(x)))
    s, r = owner.put("/api/payments/billing", BUYER_KA)
    c.check("billing: saved (Karnataka, PASDACS's own state)", s == 200 and r["billing_needed"] is False and r["billing"]["state"] == "29", (s, r.get("billing")))
    s, ru = owner.get("/api/payments", headers=ABROAD)
    s, rn = owner.get("/api/payments", headers={"cf-ipcountry": ""})
    c.check("location: an organisation billed in India pays rupees even from abroad", ru["currency"] == "INR" and rn["currency"] == "INR",
            (ru.get("currency"), rn.get("currency")))
    # a foreign organisation (billed in the United States): dollars outside India, rupees from India
    abroad = c.Person(f"ana.abroad@abroad{STAMP}.com")
    s, x = abroad.sign_in("Abroad Inc", "Ana Abroad")
    c.check("setup: a foreign organisation signs up", s == 200, (s, x))
    s, x = abroad.put("/api/payments/billing", BUYER_US, headers=ABROAD)
    c.check("billing: a foreign organisation gives its country", s == 200 and x["billing"]["country"] == "United States", (s, c.detail_of(x)))
    s, ru = abroad.get("/api/payments", headers=ABROAD)
    usd = {p["credits"]: p for p in ru.get("packs", [])}
    c.check("location: outside India, US dollars only, $1 a credit, no GST", ru["currency"] == "USD" and ru["gst"] == 0
            and {p["currency"] for p in ru["packs"]} == {"USD"} and [p["amount"] for p in ru["packs"]] == [10000, 25000, 50000], ru.get("packs"))
    s, rn = abroad.get("/api/payments", headers={"cf-ipcountry": ""})
    s, rx = abroad.get("/api/payments", headers={"cf-ipcountry": "XX"})
    s, ri = abroad.get("/api/payments", headers={"cf-ipcountry": "IN"})
    c.check("location: unknown is US dollars (the fallback); from India, rupees", rn["currency"] == "USD" and rx["currency"] == "USD"
            and ri["currency"] == "INR", (rn.get("currency"), rx.get("currency"), ri.get("currency")))
    s, x = order(owner, usd[100]["id"])
    c.check("location: a dollar pack cannot be bought by an organisation billed in India (409)", s == 409, (s, c.detail_of(x)))
    s, x = order(abroad, packs[100]["id"], headers=ABROAD)
    c.check("location: a rupee pack cannot be bought from abroad (409)", s == 409, (s, c.detail_of(x)))
    s, r = order(member, packs[100]["id"])
    c.check("open: a member's order is refused (403)", s == 403, (s, c.detail_of(r)))
    s, r = order(owner, "100-899-1800")
    c.check("open: an order at an old price is refused (409)", s == 409, (s, c.detail_of(r)))
    out = g.app(f"""
from app import db, orgs
with db.use({tid!r}):
    print(orgs._short(orgs.row({tid!r}), "dashboard"))
""")
    c.check("open: 'not enough credits' now says Buy credits", "Buy credits" in out, out[-300:])

    # ---------------------------------------------------------------- checkout 1: paid through the checkout's answer
    s, o1 = order(owner, packs[100]["id"])
    c.check("checkout: an order is made for the server's price", s == 200 and o1["order_id"].startswith("order_") and o1["amount"] == 117882
            and o1["key"] == KEY and o1["prefill"]["email"] == owner.email and o1["test"] is False and o1["currency"] == "INR", (s, o1))
    od = fake(f"/v1/orders/{o1['order_id']}", auth=True)
    c.check("checkout (audit P6): the order's notes carry no email address", isinstance(od.get("notes"), dict)
            and "email" not in od["notes"] and "@" not in json.dumps(od["notes"]), od.get("notes"))
    ro = fake(f"/v1/orders/{o1['order_id']}", auth=True)
    c.check("checkout: Razorpay's order carries our receipt and notes", ro["receipt"] == o1["id"] and ro["notes"]["workspace"] == tid
            and ro["notes"]["credits"] == "100", ro)
    c.check("checkout: recorded as created, live, with its GST", row(o1["id"]) | {} and row(o1["id"])["status"] == "created"
            and row(o1["id"])["live"] == "1" and row(o1["id"])["gst"] == "17982", row(o1["id"]))
    s, r = owner.post("/api/payments/verify", {"razorpay_order_id": o1["order_id"], "razorpay_payment_id": "pay_Fake1234567890",
                                               "razorpay_signature": "0" * 64})
    c.check("verify: a wrong signature is refused (400), nothing added", s == 400 and credits_of(owner) == 50, (s, c.detail_of(r)))
    ghost = "pay_" + os.urandom(7).hex()[:14]
    sig = hmac.new(SECRET.encode(), f"{o1['order_id']}|{ghost}".encode(), hashlib.sha256).hexdigest()
    before = audits("d2d.payment_alert")
    s, r = owner.post("/api/payments/verify", {"razorpay_order_id": o1["order_id"], "razorpay_payment_id": ghost, "razorpay_signature": sig})
    c.check("verify: a payment Razorpay does not know is refused (409) and PASDACS is alerted",
            s == 409 and credits_of(owner) == 50 and audits("d2d.payment_alert") == before + 1, (s, c.detail_of(r)))
    pr1 = pay(o1["order_id"])
    s, v = owner.post("/api/payments/verify", answer(pr1))
    c.check("verify: paid; 100 credits added (50 -> 150)", s == 200 and v["added"] == 100 and v["credits"] == 150, (s, v))
    rr = row(o1["id"])
    c.check("verify: the checkout is paid, by UPI, with its credit row", rr["status"] == "paid" and rr["method"] == "upi" and rr["credit_id"].startswith("cr-"), rr)
    s, org = owner.get("/api/org")
    top = org["ledger"][0] if s == 200 and org["ledger"] else {}
    c.check("history: 'Bought online' with the amount and Razorpay's id", top.get("kind") == "adjust" and top.get("what") == "purchase"
            and top.get("delta") == 100 and "₹1,178.82 paid online" in (top.get("note") or "") and pr1["razorpay_payment_id"] in (top.get("note") or ""), top)
    s, v = owner.post("/api/payments/verify", answer(pr1))
    c.check("verify: again, nothing more is added (150)", s == 200 and credits_of(owner) == 150, (s, v))
    i1 = invoice(o1["id"])
    import re as _re
    c.check("invoice: issued with the payment, numbered D2D/yy-yy/00000", bool(_re.fullmatch(r"D2D/\d\d-\d\d/\d{5}", i1.get("no", ""))) and not i1["test"], i1.get("no"))
    c.check("invoice: same state as PASDACS: CGST 9% + SGST 9% on ₹999", i1.get("cgst") == 8991 and i1.get("sgst") == 8991 and i1.get("igst") == 0
            and i1.get("taxable") == 99900 and i1.get("total") == 117882 and i1.get("place") == "Karnataka (29)", {k: i1.get(k) for k in ("cgst", "sgst", "igst", "taxable", "total", "place")})
    c.check("invoice: PASDACS's and the buyer's details, SAC, no refunds", i1["seller"]["gstin"] == SELLER["gstin"] and i1["buyer"]["name"] == "Pay Test Pvt Ltd"
            and i1["sac"] == "998314" and "not refundable" in " ".join(i1["notes"]), {k: i1.get(k) for k in ("seller", "buyer", "sac", "notes")})
    s, w = webhook("payment.captured", {"payment": {"entity": pr1["payment"] | {"status": "captured"}}})
    c.check("webhook: the same payment again adds nothing", s == 200 and w.get("credited") is False and credits_of(owner) == 150, (s, w))

    # ---------------------------------------------------------------- the webhook's own checks
    s, w = webhook("payment.captured", {"payment": {"entity": pr1["payment"]}}, secret="not-the-secret")
    c.check("webhook: a wrong signature is refused (400)", s == 400, (s, w))
    s, w = webhook("payment.captured", {"payment": {"entity": pr1["payment"]}}, sig="")
    c.check("webhook: no signature is refused (400)", s == 400, (s, w))
    s, w = webhook("payment.captured", {"payment": {"entity": {**pr1["payment"], "order_id": "order_NotOurs12345678"}}})
    c.check("webhook: another integration's order is ignored", s == 200 and "not a D2D Relay order" in str(w.get("ignored")), (s, w))
    s, w = webhook("payment.captured", {"payment": {"entity": pr1["payment"]}}, origin="https://evil.example")
    c.check("webhook: a cross-site browser post is refused (403)", s == 403, (s, w))
    s, w = webhook("payment.captured", {"payment": {"entity": pr1["payment"]}}, base=c.ADMIN_BASE)
    c.check("webhook: not on the admin portal (404)", s == 404, (s, w))

    # ---------------------------------------------------------------- checkout 2: authorised only, captured by D2D Relay
    s, o2 = order(owner, packs[250]["id"])
    caps = fake("/_test/state")["captures"]
    pr2 = pay(o2["order_id"], status="authorized", method="card")
    s, v = owner.post("/api/payments/verify", answer(pr2))
    c.check("authorised: D2D Relay captures it and adds 250 (150 -> 400)", s == 200 and v["credits"] == 400
            and fake("/_test/state")["captures"] == caps + 1 and row(o2["id"])["method"] == "card", (s, v))
    i2 = invoice(o2["id"])
    c.check("invoice: the next payment gets the next number", seq(i2.get("no")) == seq(i1.get("no")) + 1, (i1.get("no"), i2.get("no")))
    s, r = owner.put("/api/payments/billing", BUYER_MH)
    c.check("billing: changed to a Maharashtra GSTIN (the state comes from it)", s == 200 and r["billing"]["state"] == "27", (s, r.get("billing")))

    # ---------------------------------------------------------------- checkout 3: the tab closed; the webhook pays it
    s, o3 = order(owner, packs[500]["id"])
    pr3 = pay(o3["order_id"])
    order_entity = fake(f"/v1/orders/{o3['order_id']}", auth=True)
    s, w = webhook("order.paid", {"payment": {"entity": pr3["payment"]}, "order": {"entity": order_entity}})
    c.check("webhook: order.paid adds 500 (400 -> 900)", s == 200 and w.get("credited") is True and credits_of(owner) == 900, (s, w))
    i3 = invoice(o3["id"])
    c.check("invoice: another state: IGST 18%, with the buyer's GSTIN", i3.get("igst") == 71982 and i3.get("cgst") == 0
            and i3["buyer"]["gstin"] == BUYER_MH["gstin"] and i3.get("place") == "Maharashtra (27)" and seq(i3["no"]) == seq(i2["no"]) + 1,
            {k: i3.get(k) for k in ("igst", "cgst", "place", "no")})
    s, r = owner.put("/api/payments/billing", BUYER_KA)
    s, w = webhook("order.paid", {"payment": {"entity": pr3["payment"]}, "order": {"entity": order_entity}})
    c.check("webhook: the same event again adds nothing", s == 200 and w.get("credited") is False and credits_of(owner) == 900, (s, w))

    # ---------------------------------------------------------------- checkout 4: no answer, no webhook: found on the next look
    s, o4 = order(owner, packs[100]["id"])
    pay(o4["order_id"])
    s, r = owner.get("/api/payments")
    c.check("look-up: opening the Organisation page finds the payment (900 -> 1000)", s == 200 and r["credits"] == 1000
            and row(o4["id"])["status"] == "paid", (s, r.get("credits"), row(o4["id"])))

    # ---------------------------------------------------------------- checkout 5: failed, then paid on a retry
    s, o5 = order(owner, packs[100]["id"])
    pf = pay(o5["order_id"], status="failed")
    s, w = webhook("payment.failed", {"payment": {"entity": pf["payment"]}})
    c.check("failed: recorded with Razorpay's reason", s == 200 and row(o5["id"])["status"] == "failed" and "failed" in row(o5["id"])["error"].lower(), (s, w, row(o5["id"])))
    pr5 = pay(o5["order_id"])
    s, w = webhook("payment.captured", {"payment": {"entity": pr5["payment"]}})
    c.check("failed: a retry that succeeds pays it (1000 -> 1100)", s == 200 and w.get("credited") is True and credits_of(owner) == 1100
            and row(o5["id"])["status"] == "paid", (s, w))

    # ---------------------------------------------------------------- what must never add credits
    s, o6 = order(owner, packs[100]["id"])
    before = audits("d2d.payment_alert")
    pm6 = pay(o6["order_id"], amount=100)
    s, v = owner.post("/api/payments/verify", answer(pm6))
    c.check("mismatch: a payment for another amount adds nothing (409) and PASDACS is alerted",
            s == 409 and credits_of(owner) == 1100 and audits("d2d.payment_alert") == before + 1, (s, c.detail_of(v)))
    before = audits("d2d.payment_alert")
    second = pay(o1["order_id"])
    s, w = webhook("payment.captured", {"payment": {"entity": second["payment"]}})
    c.check("second payment: one order paid twice adds nothing more; PASDACS is told to refund it",
            s == 200 and w.get("ignored") == "second payment" and credits_of(owner) == 1100 and audits("d2d.payment_alert") == before + 1, (s, w))

    # ---------------------------------------------------------------- refunds (made on the Razorpay Dashboard)
    refund = {"id": "rfnd_" + os.urandom(7).hex()[:14], "entity": "refund", "amount": 117882, "currency": "INR",
              "payment_id": pr1["razorpay_payment_id"], "status": "processed"}
    s, w = webhook("refund.processed", {"refund": {"entity": refund}, "payment": {"entity": pr1["payment"]}})
    rr = row(o1["id"])
    c.check("refund: recorded; the checkout shows refunded; credits are left for PASDACS to take back",
            s == 200 and w.get("refund") is True and rr["status"] == "refunded" and rr["refunded"] == "117882" and credits_of(owner) == 1100, (s, w, rr))
    s, w = webhook("refund.processed", {"refund": {"entity": refund}})
    c.check("refund: the same refund again changes nothing", s == 200 and w.get("refund") is False and row(o1["id"])["refunded"] == "117882", (s, w))
    part = {**refund, "id": "rfnd_" + os.urandom(7).hex()[:14], "amount": 1000, "payment_id": pr2["razorpay_payment_id"]}
    s, w = webhook("refund.processed", {"refund": {"entity": part}})
    c.check("refund: a part refund keeps it paid, with the amount refunded", s == 200 and row(o2["id"])["status"] == "paid"
            and row(o2["id"])["refunded"] == "1000", (s, w, row(o2["id"])))

    # ---------------------------------------------------------------- receipts, lists, news
    req = urllib.request.Request(c.BASE + f"/api/payments/{o2['id']}/receipt")
    with owner.http.open(req, timeout=30) as resp:
        page, csp = resp.read().decode(), resp.headers.get("Content-Security-Policy") or ""
    c.check("invoice page: the owner's opens: tax invoice, number, both GSTINs, CGST and SGST, the total, a strict CSP",
            "Tax invoice" in page and i2["no"] in page and SELLER["gstin"] in page and "CGST 9%" in page and "SGST 9%" in page and "₹202.41" in page
            and "₹2,653.82" in page and "998314" in page and "Place of supply" in page and "not refundable" in page and "default-src 'none'" in csp, page[:300])
    s, r = member.get(f"/api/payments/{o1['id']}/receipt")
    c.check("receipt: a member cannot open the owner's (404)", s == 404, (s, r))
    s, r = owner.get(f"/api/payments/{o6['id']}/receipt")
    c.check("receipt: none for a payment never made (409)", s == 409, (s, r))
    s, r = member.get("/api/payments")
    c.check("list: a member sees only their own payments", s == 200 and r["payments"] == [] and r["all"] is False, (s, r.get("payments")))
    s, r = owner.get("/api/payments")
    mine = {p["id"]: p for p in r.get("payments", [])}
    c.check("list: the owner sees the organisation's payments", s == 200 and r["all"] is True and {o1["id"], o2["id"], o3["id"], o4["id"], o5["id"], o6["id"]} <= set(mine)
            and mine[o1["id"]]["status"] == "refunded", (s, list(mine)))
    s, n = owner.get("/api/notifications")
    texts = json.dumps(n)
    c.check("news: the owner is told in the app", "+100 credits for Pay Test" in texts and "refunded to Pay Test" in texts, texts[:300])
    logs = __import__("subprocess").run(["docker", "logs", c.WEB_C], capture_output=True, text=True, encoding="utf-8", errors="replace")
    lg = logs.stdout + logs.stderr
    c.check("news: the invoice to the buyer and a note to PASDACS (printed: no mail on the test stack)",
            f"[payments] mail to {owner.email}: D2D Relay: tax invoice {i1['no']}, 100 credits for Pay Test" in lg
            and "[payments] mail to info@pasdacs.com: D2D Relay: Pay Test bought 100 credits" in lg, lg[-600:])
    s, a = admin.get("/api/admin/payments")
    t = (a.get("totals") or {}).get("INR", {})
    c.check("admin: every payment listed; totals are live payments less refunds",
            s == 200 and {o1["id"], o6["id"]} <= {p["id"] for p in a["payments"]} and t.get("all") - b_inr["all"] == 265382 - 1000 + 471882 + 117882 + 117882
            and t.get("count") - b_inr["count"] == 5 and a["totals"]["USD"]["count"] == b_usd["count"], (s, a.get("totals"), base))

    # ---------------------------------------------------------------- the admin's Check, an outage, the hourly limit
    s, o7 = order(owner, packs[100]["id"])
    pay(o7["order_id"])
    s, a = admin.post(f"/api/admin/payments/{o7['id']}/check")
    c.check("admin: Check finds a payment (1100 -> 1200)", s == 200 and row(o7["id"])["status"] == "paid" and credits_of(owner) == 1200, (s, row(o7["id"])))
    s, o9 = order(owner, packs[100]["id"])
    pr9 = pay(o9["order_id"])
    fake("/_test/down", {"seconds": 60})
    s, v = owner.post("/api/payments/verify", answer(pr9))
    c.check("outage: Razorpay down: 'not confirmed yet' (503), nothing added", s == 503 and credits_of(owner) == 1200, (s, c.detail_of(v)))
    fake("/_test/down", {"seconds": 0})
    s, r = owner.get("/api/payments")
    c.check("outage: once Razorpay is back, the next look adds it (1200 -> 1300)", s == 200 and r["credits"] == 1300, (s, r.get("credits")))
    uid = owner.get("/api/me")[1]["id"]
    already = int(g.sql(f"SELECT count(*) FROM relay.tn_payments WHERE user_id = '{uid}' AND created > extract(epoch from now()) - 3600"))
    made, last = 0, 200
    for _ in range(12):
        last, _r = order(owner, packs[100]["id"])
        if last != 200:
            break
        made += 1
    c.check("limit: at most 10 checkouts an hour per person (429)", last == 429 and made == 10 - already, (made, already, last))

    # ---------------------------------------------------------------- everyone may buy; selling off
    s, a = settings(admin, who="everyone")
    s, me = member.get("/api/me")
    c.check("everyone: a member may buy once the admin allows it", me["org"]["pay"]["can"] is True, me["org"]["pay"])
    s, o8 = order(member, packs[250]["id"])
    c.check("everyone: the member's order is made", s == 200 and o8.get("prefill", {}).get("email") == member.email, (s, o8))

    # ---------------------------------------------------------------- US dollars, from abroad (item 24)
    before = credits_of(abroad)
    s, u1 = order(abroad, usd[100]["id"], headers=ABROAD)
    c.check("dollars: from abroad the order is made in US dollars for $100", s == 200 and u1["currency"] == "USD" and u1["amount"] == 10000, (s, u1))
    rz = fake(f"/v1/orders/{u1['order_id']}", auth=True)
    c.check("dollars: Razorpay's order is in USD, without GST", rz["currency"] == "USD" and rz["amount"] == 10000, rz)
    pu = pay(u1["order_id"], method="card")
    s, v = abroad.post("/api/payments/verify", answer(pu))
    c.check("dollars: paid; 100 credits added", s == 200 and v["added"] == 100 and credits_of(abroad) == before + 100, (s, v))
    iu = invoice(u1["id"])
    c.check("invoice: an export under the LUT: no IGST, the declaration, the rupee value at Razorpay's rate",
            iu.get("igst") == 0 and iu.get("taxable") == 10000 and "UNDER LETTER OF UNDERTAKING" in (iu.get("export") or {}).get("declaration", "")
            and SELLER["lut"] in iu["export"]["declaration"] and (iu.get("inr") or {}).get("total") == 935000 and iu.get("place") == "Outside India (96)",
            {k: iu.get(k) for k in ("igst", "taxable", "export", "inr", "place")})
    s, org = abroad.get("/api/org")
    top = org["ledger"][0] if s == 200 and org["ledger"] else {}
    c.check("dollars: the history says $100.00 paid online", "$100.00 paid online" in (top.get("note") or ""), top.get("note"))
    req = urllib.request.Request(c.BASE + f"/api/payments/{u1['id']}/receipt")
    with abroad.http.open(req, timeout=30) as resp:
        page = resp.read().decode()
    c.check("dollars: the invoice is in dollars, zero-rated, with the rupee value", "$100.00" in page and "IGST 0%" in page and "₹9,350.00" in page
            and "LETTER OF UNDERTAKING" in page and "United States" in page, page[:300])
    s, u2 = order(abroad, usd[250]["id"], headers=ABROAD)
    wrong = pay(u2["order_id"], currency="INR")
    s, v = abroad.post("/api/payments/verify", answer(wrong))
    c.check("dollars: a payment in another currency adds nothing (409)", s == 409 and credits_of(abroad) == before + 100, (s, c.detail_of(v)))
    s, a = settings(admin, invoice={**SELLER, "lut": ""})
    s, u3 = order(abroad, usd[100]["id"], headers=ABROAD)
    abroad.post("/api/payments/verify", answer(pay(u3["order_id"], method="card")))
    i4 = invoice(u3["id"])
    c.check("invoice: an export without an LUT: IGST 18% included in the dollar price", i4.get("taxable") == 8475 and i4.get("igst") == 1525
            and i4.get("total") == 10000 and "ON PAYMENT OF INTEGRATED TAX" in (i4.get("export") or {}).get("declaration", ""),
            {k: i4.get(k) for k in ("taxable", "igst", "total", "export")})
    s, a = settings(admin)
    s, a = admin.get("/api/admin/payments")
    tu = (a.get("totals") or {}).get("USD", {})
    c.check("dollars: the admin's totals keep dollars apart", s == 200 and tu.get("all") - b_usd["all"] == 20000 and tu.get("count") - b_usd["count"] == 2,
            (s, a.get("totals"), base))
    s, pl = abroad.get("/api/payments", headers=ABROAD)
    mine = {p["id"]: p for p in pl.get("payments", [])}
    c.check("dollars: the buyer's list shows the payment in dollars, with its invoice", mine.get(u1["id"], {}).get("currency") == "USD"
            and mine[u1["id"]].get("invoice_no") == iu.get("no"), list(mine.values())[:2])
    s, csv_text = admin.get(f"/api/admin/payments/invoices.csv?fy={i1['fy']}")
    c.check("CSV: the year's invoices for GST returns, rupee and dollar ones", s == 200 and isinstance(csv_text, str) and csv_text.startswith("Invoice no,")
            and i1["no"] in csv_text and i3["no"] in csv_text and iu["no"] in csv_text and BUYER_MH["gstin"] in csv_text, str(csv_text)[:300])
    s, x = owner.get(f"/api/admin/payments/invoices.csv?fy={i1['fy']}")
    c.check("CSV: not on the public site", s in (401, 404), s)
    s, a = settings(admin, on=False)
    s, me = owner.get("/api/me")
    c.check("off again: buying closes at once", me["org"]["pay"]["on"] is False and order(owner, packs[100]["id"])[0] == 403, me["org"]["pay"])

    # ---------------------------------------------------------------- test keys: only PASDACS's own workspace can buy
    out = g.app(f"""
import json
from app import db, orgs, payments
payments.KEY_ID = "rzp_test_ABCDEFGH123456"
with db.use(db.PLATFORM):
    plat, client = orgs.row(db.PLATFORM), orgs.row({tid!r})
    a = [payments.mode(), payments.offer(None, client)["on"], payments.offer(None, plat)["on"]]
    payments.TEST_FOR = "all"
    a.append(payments.offer(None, client)["on"])
    from app import invoices
    inv = invoices.issue({{"live": 0, "currency": "INR", "amount": 117882, "price": 99900, "gst": 17982, "credits": 100, "billing": {BUYER_KA!r}}},
                         payments.settings(), __import__("time").time(), {{"id": "pay_TestSeries001"}})
    a.append(inv["no"].startswith("TEST/") and inv["test"])
print(json.dumps(a))
""")
    c.check("test keys: other organisations cannot buy; PASDACS can (selling switch aside); 'all' opens it; test payments get TEST/ invoices",
            out.strip().endswith('["test", false, true, true, true]'), out[-300:])

    # ---------------------------------------------------------------- data governance
    s, d = owner.get("/api/me/data")
    c.check("my data: the owner's payments are in the download", s == 200 and len(d.get("payments") or []) >= 7
            and all("amount" in p and p.get("currency") == "INR" for p in d["payments"]) and any(p.get("invoice_no") == i1["no"] for p in d["payments"]),
            (s, len((d or {}).get("payments") or [])))
    out = g.app(f"""
from app import governance
print(governance.erase_org({tid!r}, "pay-check"))
""")
    c.check("erase: the organisation is erased", "'erased'" in out, out[-300:])
    rr = row(o2["id"])
    c.check("erase: its payments stay for the accounts, without the people", rr["user_id"] == "" and rr["email"] == "" and rr["org_name"] == "Pay Test"
            and rr["amount"] == "265382" and rr["status"] == "paid", rr)
    c.check("erase: its GST invoices stay (accounts are kept eight years)", invoice(o2["id"]).get("no") == i2["no"], invoice(o2["id"]).get("no"))
    g.sql(f"UPDATE relay.tn_payments SET created = created - 400 * 86400 WHERE id = '{o6['id']}'")
    out = g.app("""
from app import governance
print(governance.sweep()["unpaid_checkouts"])
""")
    c.check("sweep: a checkout never paid goes after the log period; paid ones stay", out.strip().splitlines()[-1] == "1" and row(o6["id"]) == {}
            and row(o2["id"]).get("status") == "paid", out[-200:])

    bad = [n for n, ok in c.RESULTS if not ok]
    print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
