"""Test stack only, Razorpay's real TEST mode in headless Chromium (inside the test web container): Buy credits as
PASDACS, Razorpay's own checkout window, its test UPI ID (success@razorpay pays, failure@razorpay fails; no money
moves with test keys).

python -I -X utf8 rzp_real_ui.py http://127.0.0.1:8103 http://127.0.0.1:8104 explore|pay|pay-usd|fail|closed-tab
Screenshots: rzp-*.png in tests/out (or D2D_TEST_OUT).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
MODE = sys.argv[3] if len(sys.argv) > 3 else "explore"
sys.argv = sys.argv[:3]
import d2d_checks as c  # noqa: E402


PLAY = r"""
import json, sys, time
from playwright.sync_api import sync_playwright
cookie, mode = sys.argv[1], sys.argv[2]
URL = "http://127.0.0.1:8000"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
out, steps, n = {"mode": mode}, [], [0]
def shot(page, name):
    n[0] += 1
    path = f"/tmp/rzp-{n[0]:02d}-{name}.png"
    page.screenshot(path=path)
    steps.append(path)
def frame_of(page):
    for f in page.frames:
        if "api.razorpay.com" in (f.url or "") or "checkout" in (f.url or "") and f != page.main_frame:
            return f
    return None
def describe(f):
    return f.evaluate('''() => ({
      text: document.body ? document.body.innerText.slice(0, 1500) : '',
      inputs: [...document.querySelectorAll('input')].filter(e => e.offsetParent).map(e => ({name: e.name, id: e.id, type: e.type, ph: e.placeholder, al: e.getAttribute('aria-label')})).slice(0, 20),
      buttons: [...document.querySelectorAll('button, [role=button]')].filter(e => e.offsetParent).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 60)).filter(Boolean).slice(0, 30)})''')
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    abroad = "usd" in mode                          # Cloudflare's country: the United States (dollars) or India (rupees)
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, user_agent=UA, extra_http_headers={"cf-ipcountry": "US" if abroad else "IN"})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": URL}])
    page = ctx.new_page()
    errors, fails = [], []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.on("requestfailed", lambda r: fails.append((r.url[:120], r.failure)))
    if mode == "closed-tab":                        # the answer never reaches D2D Relay (as if the tab closed)
        page.route("**/api/payments/verify", lambda r: r.abort())
    page.goto(URL + "/")
    page.wait_for_timeout(2500)
    page.evaluate("location.hash = '#/org'")
    page.wait_for_selector(".card h3:has-text('Credits')", timeout=20000)
    out["credits_before"] = page.locator(".credbig").first.inner_text()
    page.locator(".card", has=page.locator("h3", has_text="Credits")).locator("button:has-text('Buy credits')").click()
    page.wait_for_selector(".modal .pack", timeout=15000)
    out["test_note"] = page.locator(".modal .note.warn").first.inner_text() if page.locator(".modal .note.warn").count() else ""
    page.locator(".modal .pack").nth(0).click()
    page.locator(".modal .mbody button.btn.primary").click()
    page.wait_for_selector("iframe.razorpay-checkout-frame", timeout=30000)
    page.wait_for_timeout(6000)
    shot(page, "opened")
    f = frame_of(page)
    out["frames"] = [fr.url[:100] for fr in page.frames]
    out["frame"] = describe(f) if f else None
    if mode != "explore" and f:
        try:
            # the contact step (Razorpay asks for a mobile number when none is given): a test number
            mob = f.get_by_placeholder("Mobile number")
            mob.click()
            mob.press_sequentially("9123456780", delay=90)
            page.wait_for_timeout(800)
            shot(page, "contact")
            f.locator("button:visible:has-text('Continue')").last.click()
            page.wait_for_timeout(3000)
            out["contact_dialog_left"] = f.get_by_placeholder("Mobile number").is_visible() if f.get_by_placeholder("Mobile number").count() else False
            shot(page, "after-contact")
            out["after_contact"] = describe(f)
            # Razorpay's published test card (from the user, for this test transaction)
            if f.get_by_text("Cards", exact=True).count():
                f.get_by_text("Cards", exact=True).first.click()
                page.wait_for_timeout(1500)
            # Razorpay's published test cards: domestic Visa for rupees, international Visa for dollars
            f.get_by_placeholder("Card Number").press_sequentially("4012888888881881" if mode == "pay-usd" else "4100280000001007", delay=60)
            f.get_by_placeholder("MM / YY").press_sequentially("1226", delay=80)
            f.get_by_placeholder("CVV").press_sequentially("123", delay=80)
            page.wait_for_timeout(1000)
            shot(page, "card")
            out["card_form"] = describe(f)
            pages_before = len(ctx.pages)
            f.locator("button:visible:has-text('Pay'), button:visible:has-text('Continue')").last.click()
            page.wait_for_timeout(6000)
            shot(page, "after-card")
            out["after_card"] = describe(f) if not f.is_detached() else "checkout closed"
            out["pages"] = [pg.url[:120] for pg in ctx.pages]
            bank = ctx.pages[-1] if len(ctx.pages) > pages_before else None
            if bank:
                bank.wait_for_load_state("load")
                bank.wait_for_timeout(2000)
                bank.screenshot(path="/tmp/rzp-bank.png")
                steps.append("/tmp/rzp-bank.png")
                out["bank_page"] = bank.evaluate("document.body.innerText.slice(0, 800)")
                out["bank_buttons"] = bank.evaluate("[...document.querySelectorAll('button, input[type=submit], a')].map(e => (e.innerText || e.value || '').trim()).filter(Boolean).slice(0, 20)")
                pick = "Failure" if mode.startswith("fail") else "Success"
                bank.locator(f"button:has-text('{pick}'), input[value='{pick}'], a:has-text('{pick}')").first.click()
                page.wait_for_timeout(6000)
                shot(page, "after-bank")
            else:
                # the test bank's page may open inside the checkout window instead
                out["inline_bank"] = describe(f) if not f.is_detached() else "checkout closed"
                pick = "Failure" if mode.startswith("fail") else "Success"
                cand = f.locator(f"button:visible:has-text('{pick}')")
                if cand.count():
                    cand.first.click()
                    page.wait_for_timeout(6000)
                    shot(page, "after-bank")
            out["after_bank"] = describe(f) if not f.is_detached() else "checkout closed"
        except Exception as e:  # noqa: BLE001 - exploring
            out["step_error"] = str(e)[:600]
            shot(page, "error")
            try:
                out["at_error"] = describe(f)
            except Exception:  # noqa: BLE001
                pass
        # what D2D Relay shows afterwards
        try:
            page.wait_for_selector(".modal .note.ok, .modal .note.err, .modal .note.warn:has-text('confirmed')", timeout=60000)
        except Exception as e:  # noqa: BLE001
            out["wait_error"] = str(e)[:200]
        shot(page, "result")
        notes = page.locator(".modal .note")
        out["notes"] = [notes.nth(i).inner_text() for i in range(notes.count())]
        out["chip"] = page.locator("#orgchip").inner_text()
    out["errors"], out["failed_requests"], out["shots"] = errors, fails[:10], steps
    b.close()
print(json.dumps(out))
"""


def main():
    pas = c.signed_in("info@pasdacs.com", c.BASE)
    res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", c.cookie(pas, "d2d_session"), MODE], input=PLAY,
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=400)
    if res.returncode:
        print(res.stderr[-3000:])
        return 1
    o = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps(o, indent=1, ensure_ascii=False)[:9000])
    for path in o.get("shots", []):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:{path}", c.out_path(os.path.basename(path))], check=False)
    s, r = pas.get("/api/payments")
    print(json.dumps({"credits": r.get("credits"), "payments": [{k: p[k] for k in ("id", "status", "credits", "amount", "method", "payment_id", "live")}
                                                                for p in r.get("payments", [])[:4]]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
