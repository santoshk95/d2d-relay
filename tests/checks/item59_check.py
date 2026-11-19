"""Test stack only: item 59 (the user, 2026-11-19: "remove payment all and have only as request credits") as item 85 left
it (the same day: "add back payment as well, let both options be, either they can add credits or request credits as
well, only organisations are allowed to sign in and personal will be blocked"). Buying credits online is back next to
Request credits; payments made before stay, with their invoices (accounting records); personal workspaces are closed
(item 83).
- the selling routes are back: signed in, GET /api/payments answers (200), an order while selling is off is refused
  (403, pointing to Request credits), verifying another organisation's order answers 404, billing details are asked for
  again (a member who may not buy cannot change them, 403); the Razorpay webhook needs no session again (a wrong or
  missing signature: 400, never 401) and the admin portal has none (404); the admin portal's Payments has its settings
  and Check again (the stand-in's live-looking keys, the webhook on the public site's address); /api/me and /api/org
  carry "pay";
- both ways to more credits: while selling is off, "not enough credits" (402) says Request credits only; once PASDACS
  switches selling on, the owner may buy (a member sees it, owners only), Buy credits shows the packs, the 402 offers
  Buy credits and Request credits, and Request credits still works (PASDACS approves 40, the person is told);
- payments seeded into relay.tn_payments as payments.py makes them (d2d_checks.seed_payment) open: a GST invoice (live
  keys, D2D series), a test invoice (TEST series), a receipt from before invoices; never someone else's (unless an
  owner) or another organisation's, none for a checkout never completed (409); /api/org lists the completed ones,
  /api/payments the recent failed checkout too; Download my data lists them;
- the admin portal: every checkout listed (the failed one too, whose Check says it was made with other keys: 409),
  totals of the real ones, the financial years, one payment's invoice, a year's invoices as CSV (test ones only when
  asked); none of it on the public site;
- personal workspaces (item 39) are closed (item 83): a session made before signs nobody in (401), a code asked for
  before is refused (403, the item 83 text), a new one is never made (the answer looks like any address's), and the
  admin portal still lists the workspace;
- in Chromium: the Organisation page of an owner and of a member (Payments with the invoice links, Buy credits and
  Request credits) and the admin portal's Payments page (its settings, the payments with their invoices, Check).
  Screenshots: item59-*.png.
Selling is switched off again at the end, as the other suites expect it. Its people sign in from 198.18.59.x.
python -I -X utf8 item59_check.py <public> <admin>"""
import itertools
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402
import pay_check as pc  # noqa: E402 - selling settings (PASDACS's invoice details, three packs) and a buyer's billing details

c._ips = (f"198.18.59.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190))


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def raw_get(p: c.Person, path: str):
    """(status, text, Content-Disposition, Content-Type) with the person's session."""
    try:
        with p.http.open(urllib.request.Request(p.base + path), timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Disposition") or "", r.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), "", ""


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


def pay_of(p: c.Person) -> dict:
    return (((p.get("/api/me")[1] or {}).get("org") or {}).get("pay")) or {}


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
dom = f"paid{S}.com"
owner, member = c.Person(f"olu.owner@{dom}"), c.Person(f"mo.member@{dom}")
s, r = owner.sign_in(f"Paid Before {S}", "Olu Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
s, r = member.sign_in(person="Mo Member")
check("setup: a member added to it signs in", s == 200, (s, r))
other = c.Person(f"oz.owner@elsewhere{S}.com")
s, r = other.sign_in(f"Elsewhere {S}", "Oz Owner")
check("setup: another organisation's owner signs in", s == 200, (s, r))
for p in (owner, member, other):
    p.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
other.post("/api/org/setup")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
s, a = pc.settings(admin, on=False)                  # as on live until PASDACS switches selling on: the packs set, selling off
check("setup: selling is off (the packs and PASDACS's invoice details set)", s == 200 and ((a or {}).get("settings") or {}).get("on") is False,
      (s, detail(a)))

try:
    # ---------------------------------------------------------------- buying online is back
    section("buying credits online is back, next to Request credits (item 85)")
    s, r = owner.get("/api/payments")
    check("back: GET /api/payments answers the owner (200); while selling is off it offers no packs",
          s == 200 and r.get("on") is False and r.get("packs") == [] and r.get("payments") == [], (s, r))
    s, r = owner.post("/api/payments/order", {"pack": "100-999-1800"})
    check("back: an order while selling is off is refused (403), pointing to Request credits", s == 403 and "Request credits" in str(detail(r)),
          (s, r))
    s, r = owner.post("/api/payments/verify", {"razorpay_order_id": "order_NotThisOrgs12345", "razorpay_payment_id": "pay_ABCDEF123456",
                                               "razorpay_signature": "0" * 64})
    check("back: verifying an order that is not the organisation's answers 404", s == 404, (s, r))
    s, r = owner.put("/api/payments/billing", {})
    check("back: billing details are asked for again (an empty form is refused: 400)", s == 400, (s, r))
    s, r = member.put("/api/payments/billing", pc.BUYER_KA)
    check("back: a member who may not buy cannot change them (403)", s == 403, (s, r))
    for name, hdr in (("a wrong signature", {"X-Razorpay-Signature": "0" * 64}), ("no signature", {})):
        s, r = c.Person("x").call("POST", "/api/payments/webhook", {"event": "payment.captured"}, headers=hdr)
        check(f"back: the Razorpay webhook needs no session again: {name} is refused (400, never 401)", s == 400, (s, r))
    s, r = admin.post("/api/payments/webhook", {})
    check("back: the admin portal has no webhook (404)", s == 404, (s, r))
    s, r = admin.post("/api/admin/payments/pay-0000000000000000/check")
    check("back: the admin portal's Check is there again (an unknown checkout: 404)", s == 404, (s, r))
    s, d = admin.get("/api/admin/payments")
    hook = str((d or {}).get("webhook_url") or "")
    check("back: the admin portal's Payments has its settings again: live-looking keys, both secrets, the webhook on the public site's address",
          s == 200 and d.get("mode") == "live" and d.get("key_secret") is True and d.get("webhook_secret") is True
          and hook.endswith("/api/payments/webhook") and urllib.parse.urlsplit(hook).port == urllib.parse.urlsplit(c.BASE).port
          and "settings" in d and len(d.get("packs") or []) == 6, {k: (d or {}).get(k) for k in ("mode", "key_secret", "webhook_secret", "webhook_url")})
    s, me = owner.get("/api/me")
    mo = (me or {}).get("org") or {}
    check("back: /api/me carries pay again: not open while selling is off", s == 200 and mo.get("id") == tid
          and mo.get("pay") == {"on": False, "can": False}, mo.get("pay"))
    s, o = owner.get("/api/org")
    check("back: /api/org has pay too, and no payments for an organisation that never bought", s == 200 and (o or {}).get("pay") == {"on": False, "can": False}
          and o.get("payments") == [], {k: o.get(k) for k in ("pay", "payments")} if isinstance(o, dict) else o)
    admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": -50, "note": "item 59 check: none left"})
    s, r = c.new_dashboard(owner)
    check("off: no credits: a new dashboard says Request credits only while selling is off (402)", s == 402
          and "Request credits" in str(detail(r)) and "Buy" not in str(detail(r)), (s, r))

    s, a = pc.settings(admin)
    check("on: PASDACS switches selling on (owners buy, 18% GST, three packs)", s == 200 and ((a or {}).get("settings") or {}).get("on") is True,
          (s, detail(a)))
    check("on: the owner may buy", pay_of(owner) == {"on": True, "can": True, "test": False}, pay_of(owner))
    pm = pay_of(member)
    check("on: a member sees it but may not buy (owners only)", pm.get("on") is True and pm.get("can") is False and "owners" in str(pm.get("why")), pm)
    s, r = owner.get("/api/payments", headers={"cf-ipcountry": "IN"})
    check("on: Buy credits shows the packs in rupees (India), the billing details asked for first",
          s == 200 and r.get("on") is True and r.get("currency") == "INR" and [p.get("credits") for p in r.get("packs") or []] == [100, 250, 500]
          and r.get("billing_needed") is True, (s, {k: (r or {}).get(k) for k in ("on", "currency", "packs", "billing_needed")}))
    s, r = c.new_dashboard(owner)
    check("both: no credits: the 402 offers both, Buy credits and Request credits", s == 402 and "Buy credits" in str(detail(r))
          and "Request credits" in str(detail(r)), (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 40, "message": "For item 59's check: asked for next to Buy credits"})
    rid = ((r or {}).get("request") or {}).get("id") if isinstance(r, dict) else None
    check("both: Request credits still works while selling is on (40 asked for)", s == 200 and rid
          and ((r or {}).get("request") or {}).get("credits") == 40, (s, r))
    s, rq = admin.get("/api/admin/requests")
    mine = next((x for x in (rq or {}).get("credits", []) if x.get("id") == rid), {})
    check("both: the request waits on the admin portal", mine.get("status") == "pending" and mine.get("credits") == 40, mine)
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 40, "note": "Approved for item 59's check"})
    po = (owner.get("/api/me")[1] or {}).get("org") or {}
    led = (owner.get("/api/org")[1] or {}).get("ledger") or []
    check("both: PASDACS approves: 40 credits added, the history says so", s == 200 and po.get("credits") == 40
          and any(x.get("kind") == "adjust" and x.get("delta") == 40 for x in led), (s, po.get("credits"), led[:3]))
    s, n = owner.get("/api/notifications")
    check("both: the person is told", "+40 credits" in json.dumps(n), json.dumps(n)[:300])

    # ---------------------------------------------------------------- past payments stay
    section("past payments and their invoices stay")
    s0, before = admin.get("/api/admin/payments")
    inr0 = ((before or {}).get("totals") or {}).get("INR") or {}
    live = c.seed_payment(tid, owner.email, live=True, credits=100)               # a real payment: a tax invoice, D2D series
    test = c.seed_payment(tid, member.email, credits=50, ago=7200)               # test keys: a test invoice, TEST series
    old = c.seed_payment(tid, owner.email, credits=20, invoice=False, ago=86400 * 3)   # paid before invoices: a receipt
    failed = c.seed_payment(tid, owner.email, credits=10, status="failed", ago=600)    # never completed
    theirs = c.seed_payment(((other.get("/api/me")[1] or {}).get("org") or {}).get("id"), other.email, credits=30, invoice=False)
    check("seed: four payments of this organisation and one of another, as payments.py makes them",
          all(x.get("id") for x in (live, test, old, failed, theirs)) and str(live.get("invoice_no", "")).startswith("D2D/")
          and str(test.get("invoice_no", "")).startswith("TEST/") and old.get("invoice_no") is None, (live, test, old, failed, theirs))
    s, o = owner.get("/api/org")
    listed = [x.get("id") for x in (o or {}).get("payments") or []]
    check("list: the owner's Organisation page lists the 3 completed payments, newest first (not the failed one)",
          listed == [live.get("id"), test.get("id"), old.get("id")], listed)
    row = next((x for x in (o or {}).get("payments") or [] if x.get("id") == live.get("id")), {})
    check("list: with its credits, amount, currency, status, method and invoice number", row.get("credits") == 100 and row.get("amount") == 1180000
          and row.get("currency") == "INR" and row.get("status") == "paid" and row.get("method") == "upi" and row.get("invoice_no") == live.get("invoice_no")
          and row.get("live") is True, row)
    s, om = member.get("/api/org")
    check("list: a member sees only their own payment", [x.get("id") for x in (om or {}).get("payments") or []] == [test.get("id")],
          (om or {}).get("payments"))
    s, pl = owner.get("/api/payments")
    got = {x.get("id"): x for x in (pl or {}).get("payments") or []}
    check("list: /api/payments (Buy credits, the Organisation page) lists them too, with the checkout that failed just now",
          s == 200 and {live.get("id"), test.get("id"), old.get("id"), failed.get("id")} <= set(got) and (got.get(failed.get("id")) or {}).get("status") == "failed"
          and theirs.get("id") not in got and (pl or {}).get("all") is True, (s, list(got)))
    s, page = owner.get(f"/api/payments/{live.get('id')}/receipt")
    page = str(page)
    check("invoice: the owner opens the tax invoice: its number, CGST and SGST 9% (Karnataka to Karnataka), the total, no refunds",
          s == 200 and "Tax invoice" in page and str(live.get("invoice_no")) in page and "CGST 9%" in page and "SGST 9%" in page
          and "11,800.00" in page and "not refundable" in page and "Test invoice" not in page, (s, page[:300]))
    s2, text, disp, ctype = raw_get(owner, f"/api/payments/{live.get('id')}/receipt")
    check("invoice: an HTML page of its own, never kept by a cache", s2 == 200 and ctype.startswith("text/html"), (s2, ctype))
    s, page = member.get(f"/api/payments/{test.get('id')}/receipt")
    check("invoice: the member opens their own test invoice (TEST series, says no money moved)", s == 200 and "Test invoice" in str(page)
          and str(test.get("invoice_no")) in str(page) and "no money moved" in str(page), (s, str(page)[:300]))
    s, page = owner.get(f"/api/payments/{test.get('id')}/receipt")
    check("invoice: an owner opens a member's too", s == 200 and str(test.get("invoice_no")) in str(page), (s, str(page)[:200]))
    s, page = owner.get(f"/api/payments/{old.get('id')}/receipt")
    check("receipt: a payment from before invoices opens as a payment receipt (not a tax invoice), a test payment",
          s == 200 and "Payment receipt" in str(page) and "not a tax invoice" in str(page) and "no money moved" in str(page), (s, str(page)[:300]))
    s, r = member.get(f"/api/payments/{live.get('id')}/receipt")
    check("receipt: a member cannot open the owner's (404)", s == 404, (s, str(r)[:150]))
    s, r = other.get(f"/api/payments/{live.get('id')}/receipt")
    check("receipt: another organisation's owner cannot open it (404)", s == 404, (s, str(r)[:150]))
    s, r = owner.get(f"/api/payments/{theirs.get('id')}/receipt")
    check("receipt: nor this owner the other organisation's (404)", s == 404, (s, str(r)[:150]))
    s, r = owner.get(f"/api/payments/{failed.get('id')}/receipt")
    check("receipt: none for a checkout never completed (409)", s == 409, (s, str(r)[:150]))
    s, r = c.Person("x").get(f"/api/payments/{live.get('id')}/receipt")
    check("receipt: nobody without a session (401)", s == 401, (s, str(r)[:150]))
    s, mine = owner.get("/api/me/data")
    check("my data: Download my data lists the owner's own payments with their invoice numbers",
          s == 200 and {x.get("receipt") for x in (mine or {}).get("payments") or []} >= {live.get("id"), old.get("id"), failed.get("id")}
          and any(x.get("invoice_no") == live.get("invoice_no") for x in (mine or {}).get("payments") or []),
          (mine or {}).get("payments") if isinstance(mine, dict) else mine)

    section("the admin portal: every payment")
    s, d = admin.get("/api/admin/payments")
    ids = [x.get("id") for x in (d or {}).get("payments") or []]
    check("admin: every checkout is listed (both organisations'), the failed one too",
          s == 200 and {live.get("id"), test.get("id"), old.get("id"), theirs.get("id"), failed.get("id")} <= set(ids), (s, ids[:8]))
    arow = next((x for x in (d or {}).get("payments") or [] if x.get("id") == live.get("id")), {})
    check("admin: a row says whose it is: organisation, person, address, Razorpay's order", arow.get("org_name") == f"Paid Before {S}"
          and arow.get("email") == owner.email and arow.get("tenant_id") == tid and str(arow.get("order_id", "")).startswith("order_"), arow)
    inr = ((d or {}).get("totals") or {}).get("INR") or {}
    check("admin: the totals count real payments only (the live one: +Rs 11,800, one more)", inr.get("all", 0) - inr0.get("all", 0) == 1180000
          and inr.get("count", 0) - inr0.get("count", 0) == 1, (inr0, inr))
    check("admin: the financial years with invoices are listed", live.get("fy") in ((d or {}).get("years") or []) and (d or {}).get("fy") == live.get("fy"),
          {k: (d or {}).get(k) for k in ("fy", "years")})
    s, r = admin.post(f"/api/admin/payments/{failed.get('id')}/check")
    check("admin: Check on the failed checkout says it was made with other keys (test ones: 409)", s == 409 and "other Razorpay keys" in str(detail(r)),
          (s, r))
    s, page = admin.get(f"/api/admin/payments/{live.get('id')}/invoice")
    check("admin: one payment's invoice opens", s == 200 and str(live.get("invoice_no")) in str(page) and "Tax invoice" in str(page), (s, str(page)[:200]))
    s, r = admin.get(f"/api/admin/payments/{old.get('id')}/invoice")
    check("admin: a payment from before invoices has none (404)", s == 404, (s, r))
    s2, text, disp, ctype = raw_get(admin, f"/api/admin/payments/invoices.csv?fy={live.get('fy')}")
    check("admin: the year's invoices download as CSV for the accountant: the real one, no test invoices",
          s2 == 200 and "attachment" in disp and text.startswith("Invoice no,Invoice date,Test") and str(live.get("invoice_no")) in text
          and str(test.get("invoice_no")) not in text, (s2, disp, text[:300]))
    s2, text, disp, ctype = raw_get(admin, f"/api/admin/payments/invoices.csv?fy={live.get('fy')}&test=1")
    check("admin: with test invoices when asked", s2 == 200 and str(test.get("invoice_no")) in text and str(live.get("invoice_no")) in text
          and "-test.csv" in disp, (s2, disp, text[:300]))
    for path in ("/api/admin/payments", "/api/admin/payments/invoices.csv", f"/api/admin/payments/{live.get('id')}/invoice"):
        s, r = owner.get(path)
        check(f"admin: not on the public site: {path.replace(str(live.get('id')), '<id>')} (404)", s == 404, (s, str(r)[:100]))

    # ---------------------------------------------------------------- personal workspaces are closed (item 83)
    section("personal workspaces are closed (item 83)")
    work = f"pia@piaws{S}.com"
    s, r = admin.post("/api/admin/orgs", {"name": f"Pia {S}", "email": work, "person": "Pia Personal", "credits": 0})
    ptid = (((r or {}).get("created") or {}) if isinstance(r, dict) else {}).get("id")
    pia = c.Person(work)
    s, r = pia.sign_in(provision=False, brand=False)
    s1, pme = pia.get("/api/me")
    check("personal: setup: its person signs in while it is still an organisation", s == 200 and s1 == 200
          and ((pme or {}).get("org") or {}).get("id") == ptid, (s, r, s1))
    c.forget_codes(work)                                 # one code a minute: ask for another now
    later = c.Person(work)
    t0 = time.time()
    s, r = later.post("/auth/otp/start", {"email": work}, headers={"cf-connecting-ip": later.ip})
    held = c.code_from_logs(c.WEB_C, work, t0)
    check("personal: setup: a second code is asked for, and kept unused", s == 200 and bool(held), (s, r))
    g.sql(f"UPDATE relay.tn_orgs SET personal = 1, domain = '{work}' WHERE tenant_id = '{ptid}'")     # one address, as item 39 made them
    s, r = pia.get("/api/me")
    check("personal: a session made before signs nobody in any more (401)", s == 401, (s, r))
    s, r = pia.get("/api/payments")
    check("personal: so Buy credits is closed to it too (401)", s == 401, (s, r))
    s, r = later.post("/auth/otp/verify", {"email": work, "code": held or "000000", "next": "#/d2d"})
    check("personal: the code asked for before is refused (403): D2D Relay is for organisations",
          s == 403 and "personal workspaces are closed" in str(detail(r)), (s, r))
    c.forget_codes(work)
    fresh = c.Person(work)
    t0 = time.time()
    s, r = fresh.post("/auth/otp/start", {"email": work}, headers={"cf-connecting-ip": fresh.ip})
    seen = c.code_now(c.WEB_C, work, t0, wait=3)
    check("personal: asking again answers like for any address (200), and no code is made for it", s == 200 and seen in (None, held), (s, r, seen))
    s, ao = admin.get("/api/admin/orgs")
    prow = next((x for x in (ao or {}).get("orgs", []) if x.get("id") == ptid), {})
    check("personal: its data stays: the admin portal still lists it, as a personal workspace", prow.get("personal") is True, prow)

    # ---------------------------------------------------------------- the screens
    section("the screens")
    PLAY_ORG = r"""
import json, sys
from playwright.sync_api import sync_playwright
typo = sys.argv[3]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for name, cookie in (("owner", sys.argv[1]), ("member", sys.argv[2])):
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, extra_http_headers={"cf-ipcountry": "IN"})
        ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.goto("http://127.0.0.1:8000/#/org")
        page.wait_for_selector("h3:has-text('Credit history')", timeout=30000)
        try:
            page.wait_for_selector("main h3:text-is('Payments')", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        text = page.evaluate("(document.querySelector('main') || document.body).innerText")
        out[name] = {"payments": page.locator("main h3:text-is('Payments')").count(),
                     "request": page.locator("main button:has-text('Request credits')").count(),
                     "buy": page.locator("main button:has-text('Buy credits')").count(),
                     "links": page.locator("main a[href*='/api/payments/']").evaluate_all("xs => xs.map(x => [x.textContent, x.getAttribute('href')])"),
                     "typo": "".join(ch for ch in text if ch in typo), "errors": errors}
        page.screenshot(path=f"/tmp/item59-{name}.png", full_page=True)
        ctx.close()
    b.close()
print(json.dumps(out))
"""
    uo = browser(c.WEB_C, PLAY_ORG, c.cookie(owner, "d2d_session"), c.cookie(member, "d2d_session"), TYPO)
    own_ui, mem_ui = uo.get("owner") or {}, uo.get("member") or {}
    links = own_ui.get("links") or []
    check("screen: the owner's Organisation page lists Payments, each completed one with its invoice or receipt link",
          own_ui.get("payments", 0) >= 1 and len(links) == 3 and any(str(live.get("invoice_no")) in t and str(live.get("id")) in h for t, h in links)
          and any(t.strip() == "Receipt" and str(old.get("id")) in h for t, h in links), uo if not own_ui else links)
    check("screen: both ways to more credits on it: Buy credits and Request credits", own_ui.get("buy", 0) >= 1 and own_ui.get("request", 0) >= 1,
          {k: own_ui.get(k) for k in ("buy", "request")})
    mlinks = mem_ui.get("links") or []
    check("screen: a member's lists only their own payment, and offers Buy credits and Request credits too",
          len(mlinks) == 1 and str(test.get("id")) in mlinks[0][1] and mem_ui.get("buy", 0) >= 1 and mem_ui.get("request", 0) >= 1,
          {k: mem_ui.get(k) for k in ("links", "buy", "request")})
    check("screen: plain characters, no script errors", own_ui.get("typo") == "" and mem_ui.get("typo") == "" and own_ui.get("errors") == []
          and mem_ui.get("errors") == [], uo)

    PLAY_ADMIN = r"""
import json, sys
from playwright.sync_api import sync_playwright
typo = sys.argv[2]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_admin", "value": sys.argv[1], "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/#/payments")
    page.wait_for_selector("h1:text-is('Payments')", timeout=30000)
    page.wait_for_timeout(1000)
    text = page.evaluate("(document.querySelector('main') || document.body).innerText")
    out["text"] = text[:4000]
    out["inputs"] = page.locator("main input, main select, main textarea").count()
    out["invoices"] = page.locator("main a[href*='/api/admin/payments/'][href$='/invoice']").count()
    out["csv"] = page.locator("main a[href*='invoices.csv']").count()
    out["checks"] = page.locator("main button:text-is('Check')").count()
    out["typo"] = "".join(ch for ch in text if ch in typo)
    out["errors"] = errors
    page.screenshot(path="/tmp/item59-admin-payments.png", full_page=True)
    b.close()
print(json.dumps(out))
"""
    ua = browser(c.ADMIN_C, PLAY_ADMIN, c.cookie(admin, "d2d_admin"), TYPO)
    text = str(ua.get("text"))
    check("admin screen: Payments has its settings again (What is on sale, Sell credits online, Tax invoices, the Razorpay keys)",
          "What is on sale" in text and "Sell credits online" in text and "Tax invoices" in text and "Live keys" in text and ua.get("inputs", 0) > 5,
          {k: ua.get(k) for k in ("inputs", "stderr")} | {"text": text[:300]})
    check("admin screen: it lists the payments with their invoices and CSV downloads, and Check for the failed checkout",
          f"Paid Before {S}" in text and ua.get("invoices", 0) >= 2 and ua.get("csv", 0) >= 2 and ua.get("checks", 0) >= 1,
          {k: ua.get(k) for k in ("invoices", "csv", "checks", "stderr")})
    check("admin screen: plain characters, no script errors", ua.get("typo") == "" and ua.get("errors") == [], {k: ua.get(k) for k in ("typo", "errors", "stderr")})
    for f in ("item59-owner.png", "item59-member.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)
    subprocess.run(["docker", "cp", f"{c.ADMIN_C}:/tmp/item59-admin-payments.png", c.out_path("item59-admin-payments.png")], check=False,
                   capture_output=True)
finally:
    s, a = pc.settings(admin, on=False)                 # selling off again, as the other suites expect it
check("end: selling is switched off again", s == 200 and pay_of(owner).get("on") is False, (s, detail(a), pay_of(owner)))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
