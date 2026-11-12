"""Test stack only: Buy credits and the admin portal's Payments page in a real browser (headless Chromium inside the
test containers), with rzp_stub.js standing in for Razorpay's checkout window and fake_razorpay.py for its API.

python -I -X utf8 pay_ui_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
Screenshots go to the run's folder (tests/out/<run>): pay-buy-dialog.png, pay-done.png, pay-org-payments.png,
pay-receipt.png, pay-mobile.png, pay-member.png, pay-admin.png.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402
import pay_check as pc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
owner_cookie, member_cookie, foreign_cookie = sys.argv[1], sys.argv[2], sys.argv[3]
STUB = open("/tmp/rzp_stub.js", encoding="utf-8").read()
URL = "http://127.0.0.1:8000"
out, errors = {}, []
card = lambda page, title: page.locator(".card", has=page.locator("h3", has_text=title))
def signed(b, cookie, country="IN", **kw):
    ctx = b.new_context(extra_http_headers={"cf-ipcountry": country}, **kw)     # Cloudflare's country header
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": URL}])
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx, page = signed(b, owner_cookie, viewport={"width": 1300, "height": 950})
    page.route("https://checkout.razorpay.com/**", lambda r: r.abort())          # first: Razorpay's script is blocked
    page.goto(URL + "/")
    page.wait_for_timeout(2500)
    page.evaluate("location.hash = '#/org'")
    page.wait_for_selector(".card h3:has-text('Credits')", timeout=20000)
    out["credits_buttons"] = card(page, "Credits").locator("button").all_inner_texts()
    page.wait_for_selector(".card h3:has-text('Payments')", timeout=15000)
    out["payments_empty"] = card(page, "Payments").inner_text()
    page.click("#orgchip button")
    page.wait_for_timeout(400)
    out["chip_menu"] = page.locator(".pmitem").all_inner_texts()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    card(page, "Credits").locator("button:has-text('Buy credits')").click()
    page.wait_for_selector(".modal .billform", timeout=15000)
    bf = page.locator(".modal .billform")
    out["billing_intro"] = page.locator(".modal .mbody p").first.inner_text()
    out["billing_name"] = bf.locator("input").first.input_value()
    bf.locator("textarea").fill("1 Test Road\nBengaluru")
    bf.locator("select").select_option("29")
    bf.locator("input[placeholder='6 digits']").fill("560001")
    page.locator(".modal [role=dialog]").screenshot(path="/tmp/pay-billing.png")
    bf.locator("button:has-text('Save billing details')").click()
    page.wait_for_selector(".modal .pack", timeout=15000)
    m = page.locator(".modal")
    out["invoices_to"] = m.locator(".mbody div.small.muted").first.inner_text()
    out["no_refunds"] = m.locator(".mbody").inner_text()
    out["packs"] = m.locator(".pack").all_inner_texts()
    out["selected"] = m.locator(".pack.on .pcred").inner_text()
    out["pay_label"] = m.locator(".mbody button.btn.primary").inner_text()
    out["hint"] = m.locator(".hint").inner_text()
    m.locator("[role=dialog]").screenshot(path="/tmp/pay-buy-dialog.png")
    m.locator(".pack").nth(0).click()
    out["pay_label_100"] = m.locator(".mbody button.btn.primary").inner_text()
    m.locator(".mbody button.btn.primary").click()
    page.wait_for_selector(".modal .note.err", timeout=30000)
    out["blocked_msg"] = m.locator(".note.err").inner_text()
    # the stand-in window instead of Razorpay's: closed, failed, then paid
    page.unroute("https://checkout.razorpay.com/**")
    page.route("https://checkout.razorpay.com/**", lambda r: r.fulfill(status=200, content_type="application/javascript", body=STUB))
    page.evaluate("window.__rzpMode = 'dismiss'")
    m.locator(".mbody button.btn.primary").click()
    page.wait_for_selector(".modal .note.warn:has-text('closed')", timeout=20000)
    out["dismiss_msg"] = m.locator(".note.warn").inner_text()
    page.evaluate("window.__rzpMode = 'fail'")
    m.locator(".mbody button.btn.primary").click()
    page.wait_for_selector(".modal .note.err:has-text('You can try again')", timeout=20000)
    out["fail_msg"] = m.locator(".note.err").inner_text()
    out["enabled_after_fail"] = m.locator(".mbody button.btn.primary").is_enabled()
    page.evaluate("window.__rzpMode = 'pay'")
    m.locator(".mbody button.btn.primary").click()
    page.wait_for_selector(".modal .note.ok", timeout=40000)
    out["ok_msg"] = m.locator(".note.ok").inner_text()
    out["opened"] = page.evaluate("window.__rzp.opened")
    m.locator("[role=dialog]").screenshot(path="/tmp/pay-done.png")
    out["chip"] = page.locator("#orgchip").inner_text()
    out["balance_line"] = m.locator(".mbody > p").first.inner_text()
    m.locator("button:has-text('Done')").click()
    page.wait_for_function("() => [...document.querySelectorAll('.card')].some(c => (c.querySelector('h3') || {}).textContent === 'Payments' && c.textContent.includes('Invoice '))", timeout=20000)
    pc_ = card(page, "Payments")
    out["payments_row"] = pc_.locator("tbody tr").first.inner_text()
    # the same person abroad (Cloudflare's country header): US dollars only (item 24)
    uctx, up = signed(b, foreign_cookie, country="US", viewport={"width": 1300, "height": 950})
    up.route("https://checkout.razorpay.com/**", lambda r: r.fulfill(status=200, content_type="application/javascript", body=STUB))
    up.goto(URL + "/")
    up.wait_for_timeout(2500)
    up.evaluate("location.hash = '#/org'")
    up.wait_for_selector(".card h3:has-text('Credits')", timeout=20000)
    card(up, "Credits").locator("button:has-text('Buy credits')").click()
    up.wait_for_selector(".modal .pack", timeout=15000)
    um = up.locator(".modal")
    out["usd_toggles"] = um.locator(".segbtn").count()
    out["usd_packs"] = um.locator(".pack").all_inner_texts()
    out["usd_pay_label"] = um.locator(".mbody button.btn.primary").inner_text()
    out["usd_hints"] = um.locator(".hint").all_inner_texts()
    um.locator("[role=dialog]").screenshot(path="/tmp/pay-usd-dialog.png")
    um.locator(".pack").nth(0).click()
    um.locator(".mbody button.btn.primary").click()
    up.wait_for_selector(".modal .note.ok", timeout=40000)
    out["usd_ok"] = um.locator(".note.ok").inner_text()
    out["usd_opened"] = up.evaluate("window.__rzp.opened[window.__rzp.opened.length - 1]")
    um.locator("button:has-text('Done')").click()
    up.wait_for_function("() => [...document.querySelectorAll('.card')].some(c => (c.querySelector('h3') || {}).textContent === 'Payments' && c.textContent.includes('$100.00'))", timeout=20000)
    out["usd_row"] = card(up, "Payments").locator("tbody tr").first.inner_text()
    uctx.close()
    out["history_top"] = card(page, "Credit history").locator("tbody tr").first.inner_text()
    pc_.screenshot(path="/tmp/pay-org-payments.png")
    href = pc_.locator("a:has-text('Invoice')").first.get_attribute("href")
    r = ctx.new_page()
    r.goto(URL + href)
    out["receipt"] = r.locator("main").inner_text()
    r.screenshot(path="/tmp/pay-receipt.png", full_page=True)
    # a phone: the dialog fits
    mctx, mp = signed(b, owner_cookie, viewport={"width": 390, "height": 844})
    mp.route("https://checkout.razorpay.com/**", lambda r: r.fulfill(status=200, content_type="application/javascript", body=STUB))
    mp.goto(URL + "/")
    mp.wait_for_timeout(2500)
    mp.evaluate("location.hash = '#/org'")
    mp.wait_for_selector(".card h3:has-text('Credits')", timeout=20000)
    card(mp, "Credits").locator("button:has-text('Buy credits')").click()
    mp.wait_for_selector(".modal .pack", timeout=10000)
    out["mobile_overflow"] = mp.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    out["mobile_dialog_right"] = mp.evaluate("Math.round(document.querySelector('.modal [role=dialog]').getBoundingClientRect().right)")
    mp.screenshot(path="/tmp/pay-mobile.png")
    # a member (owners only buy): sees the prices, not a Pay button
    _, mem = signed(b, member_cookie, viewport={"width": 1300, "height": 950})
    mem.goto(URL + "/")
    mem.wait_for_timeout(2500)
    mem.evaluate("location.hash = '#/org'")
    mem.wait_for_selector(".card h3:has-text('Credits')", timeout=20000)
    card(mem, "Credits").locator("button:has-text('Buy credits')").click()
    mem.wait_for_selector(".modal .pack", timeout=10000)
    out["member_note"] = mem.locator(".modal .note").first.inner_text()
    out["member_pay_buttons"] = mem.locator(".modal button:has-text('Pay ')").count()
    mem.locator(".modal [role=dialog]").screenshot(path="/tmp/pay-member.png")
    b.close()
out["errors"] = errors
print(json.dumps(out))
"""

ADMIN_PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie = sys.argv[1]
URL = "http://127.0.0.1:8000"
out, errors = {}, []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_admin", "value": cookie, "url": URL}])
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL + "/#/payments")
    page.wait_for_selector("text=What is on sale", timeout=30000)
    page.wait_for_timeout(500)
    out["nav_has_payments"] = page.locator("a[href='#/payments']").count()
    card = lambda title: page.locator(".card", has=page.locator("h3", has_text=title))
    out["keys"] = card("Razorpay").inner_text()
    out["rows"] = page.locator(".packrow").count()
    out["usd_values"] = [page.locator(".packrow").nth(i).locator("input").nth(2).input_value() for i in range(page.locator(".packrow").count())]
    out["invoices_card"] = card("Tax invoices").inner_text()
    out["csv_links"] = card("Tax invoices").locator("a[href*='invoices.csv']").count()
    out["list"] = card("Payments").inner_text()[:800]
    page.screenshot(path="/tmp/pay-admin.png", full_page=True)
    page.locator(".packrow").first.locator("input").nth(1).fill("1099")
    page.click("button:has-text('Save')")
    page.wait_for_timeout(2500)
    out["price_after_save"] = page.locator(".packrow").first.locator("input").nth(1).input_value()
    b.close()
out["errors"] = errors
print(json.dumps(out))
"""


def run(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=400)
    if res.returncode:
        print(res.stderr[-3500:], flush=True)
        c.check(f"ui: headless Chromium ran in {container}", False, res.stderr[-300:])
        return {}
    return json.loads(res.stdout.strip().splitlines()[-1])


def main():
    admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
    s, a = pc.settings(admin)
    c.check("setup: selling is on (owners, 18% GST, three packs)", s == 200, (s, c.detail_of(a)))
    dom = f"payui{c.STAMP}.com"
    owner, member = c.Person(f"uma.owner@{dom}"), c.Person(f"mo.member@{dom}")
    s, r = owner.sign_in("Pay UI", "Uma Owner")
    c.check("setup: an organisation signs up", s == 200, (s, r))
    s, r = member.sign_in()
    c.check("setup: a colleague joins it", s == 200, (s, r))
    foreign = c.Person(f"fay.foreign@foreign{c.STAMP}.com")
    s, r = foreign.sign_in("Foreign UI", "Fay Foreign")
    c.check("setup: a foreign organisation signs up", s == 200, (s, r))
    s, r = foreign.put("/api/payments/billing", pc.BUYER_US, headers={"cf-ipcountry": "US"})
    c.check("setup: it is billed in the United States", s == 200, (s, c.detail_of(r)))
    subprocess.run(["docker", "cp", os.path.join(HERE, "rzp_stub.js"), f"{c.WEB_C}:/tmp/rzp_stub.js"], check=True)
    o = run(c.WEB_C, PLAY, c.cookie(owner, "d2d_session"), c.cookie(member, "d2d_session"), c.cookie(foreign, "d2d_session"))
    if o:
        print(json.dumps({k: v for k, v in o.items() if k != "receipt"}, indent=1, ensure_ascii=False))
        c.check("ui: the Credits card offers Buy credits first, then Request credits", o["credits_buttons"][:2] == ["Buy credits", "Request credits"], o["credits_buttons"])
        c.check("ui: the menu under the organisation chip has Buy credits", "Buy credits" in o["chip_menu"] and "Request credits" in o["chip_menu"], o["chip_menu"])
        c.check("ui: an empty Payments card says how to pay", "None yet" in o["payments_empty"], o["payments_empty"])
        c.check("ui: three packs with GST, the middle one chosen", len(o["packs"]) == 3 and o["selected"] == "250" and "+ ₹404.82 GST" in o["packs"][1], o["packs"])
        c.check("ui: Pay shows the amount with GST, and follows the pack", o["pay_label"] == "Pay ₹2,653.82" and o["pay_label_100"] == "Pay ₹1,178.82",
                (o["pay_label"], o["pay_label_100"]))
        c.check("ui: the GST and the note are said under the packs", "GST of 18% is added" in o["hint"] and "Prices exclude GST." in o["hint"], o["hint"])
        c.check("ui: Buy credits asks for the billing details first, for the GST invoice", "billing details" in o["billing_intro"]
                and "GST invoices" in o["billing_intro"] and o["billing_name"] == "Pay UI", (o["billing_intro"], o["billing_name"]))
        c.check("ui: then shows who the invoices go to, and that credits are not refundable", "Pay UI, Karnataka" in o["invoices_to"]
                and "Credits are not refundable, and a purchase cannot be cancelled once paid." in o["no_refunds"] and "Refund and cancellation policy" in o["no_refunds"], (o["invoices_to"], o["no_refunds"][-200:]))
        c.check("ui: a blocked Razorpay script is explained", "could not load" in o["blocked_msg"], o["blocked_msg"])
        c.check("ui: closing Razorpay's window says nothing was charged", "Nothing was charged" in o["dismiss_msg"], o["dismiss_msg"])
        c.check("ui: a failed payment keeps its reason and Pay works again", "Card declined (test)" in o["fail_msg"] and o["enabled_after_fail"], o["fail_msg"])
        last = (o.get("opened") or [{}])[-1]
        c.check("ui: Razorpay gets the server's order, amount, key and the person's email", last.get("amount") == 117882 and last.get("currency") == "INR"
                and str(last.get("order_id", "")).startswith("order_") and last.get("key") == pc.KEY and last.get("prefill", {}).get("email") == owner.email
                and last.get("theme", {}).get("color", "").startswith("#"), last)
        c.check("ui: paid: 100 credits added, with the invoice", "100 credits added" in o["ok_msg"] and "150 credits" in o["ok_msg"] and "Open the invoice" in o["ok_msg"], o["ok_msg"])
        c.check("ui: the chip and the dialog show the new balance at once", "150 credits" in o["chip"] and "has 150 credits" in o["balance_line"],
                (o["chip"], o["balance_line"]))
        c.check("ui: the Payments card lists it as paid by card, with its invoice", "Paid" in o["payments_row"] and "₹1,178.82" in o["payments_row"]
                and "Card" in o["payments_row"] and "Invoice D2D/" in o["payments_row"], o["payments_row"])
        c.check("ui: the credit history says Bought online", "Bought online" in o["history_top"] and "+100" in o["history_top"], o["history_top"])
        c.check("ui: abroad, US dollars with no currency switch, $1 a credit, no GST", o["usd_toggles"] == 0 and len(o["usd_packs"]) == 3
                and "$100" in o["usd_packs"][0] and "$1.00 a credit" in o["usd_packs"][0] and "GST" not in " ".join(o["usd_packs"])
                and not any("GST of" in x for x in o["usd_hints"])
                and o["usd_pay_label"] == "Pay $250", (o["usd_packs"], o["usd_pay_label"], o["usd_hints"]))
        uo = o.get("usd_opened") or {}
        c.check("ui: abroad, Razorpay gets a dollar order", uo.get("currency") == "USD" and uo.get("amount") == 10000, uo)
        c.check("ui: paid in dollars: 100 credits, listed as $100.00 with its invoice", "100 credits added" in o["usd_ok"] and "150 credits" in o["usd_ok"]
                and "$100.00" in o["usd_row"] and "Invoice D2D/" in o["usd_row"], (o["usd_ok"], o["usd_row"]))
        c.check("ui: the GST invoice opens: CGST and SGST, the total, the buyer", "Tax invoice" in o["receipt"] and "₹1,178.82" in o["receipt"]
                and "CGST 9%" in o["receipt"] and "SGST 9%" in o["receipt"] and "Pay UI" in o["receipt"], o["receipt"][:400])
        c.check("ui: on a phone the dialog fits (no sideways scroll)", o["mobile_overflow"] <= 0 and o["mobile_dialog_right"] <= 390,
                (o["mobile_overflow"], o["mobile_dialog_right"]))
        c.check("ui: a member sees the prices and who can buy, but no Pay", "owners can buy" in o["member_note"] and o["member_pay_buttons"] == 0, o["member_note"])
        c.check("ui: no script errors", not o["errors"], o["errors"])
    a_out = run(c.ADMIN_C, ADMIN_PLAY, c.cookie(admin, "d2d_admin"))
    if a_out:
        print(json.dumps(a_out, indent=1, ensure_ascii=False)[:1500])
        c.check("admin ui: Payments is in the menu and opens", a_out["nav_has_payments"] >= 1, a_out)
        c.check("admin ui: the keys card says live keys and gives the webhook URL", "Live keys" in a_out["keys"] and "/api/payments/webhook" in a_out["keys"], a_out["keys"])
        c.check("admin ui: the three packs are there to edit, with their dollar prices", a_out["rows"] == 3 and a_out["usd_values"] == ["100", "250", "500"],
                (a_out["rows"], a_out.get("usd_values")))
        c.check("admin ui: the payment made in the browser is listed", "Pay UI" in a_out["list"] and "₹1,178.82" in a_out["list"], a_out["list"])
        c.check("admin ui: a price change is saved", a_out["price_after_save"] == "1099", a_out["price_after_save"])
        c.check("admin ui: Tax invoices shows PASDACS's details, ready, with CSV downloads", "Ready" in a_out["invoices_card"]
                and a_out["csv_links"] >= 2, (a_out["invoices_card"][:300], a_out["csv_links"]))
        c.check("admin ui: no script errors", not a_out["errors"], a_out["errors"])
        s, r = owner.get("/api/payments", headers={"cf-ipcountry": "IN"})
        c.check("admin ui: the new rupee price is what the organisation sees in India", s == 200 and [p["price"] for p in r["packs"]][0] == 109900, (s, r.get("packs")))
    for f in ("pay-buy-dialog.png", "pay-done.png", "pay-org-payments.png", "pay-receipt.png", "pay-mobile.png", "pay-member.png", "pay-usd-dialog.png",
              "pay-billing.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False)
    subprocess.run(["docker", "cp", f"{c.ADMIN_C}:/tmp/pay-admin.png", c.out_path("pay-admin.png")], check=False)
    pc.settings(admin, on=False)                        # the prices back as they were, selling off for the other suites
    bad = [n for n, ok in c.RESULTS if not ok]
    print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
