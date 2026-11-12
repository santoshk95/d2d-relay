"""Test stack only: item 29 in a real browser (headless Chromium inside the test web container): the first-time tour
(an owner through every step, a member skipping it, a deep link left alone), light, dark and the device's look, and
Migration D2D (page, dialog, request). Screenshots go to the run's folder (tests/out/<run>): tour-*.png, mig-*.png.

python -I -X utf8 tour_ui_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
owner, member = sys.argv[1], sys.argv[2]
out = {}
TYPO = "—–…“”‘’·•›‹→←↔"
def typo(page):
    return "".join(ch for ch in page.evaluate("document.body.innerText") if ch in TYPO)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": owner, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_selector("h1:has-text('A quick tour')", timeout=20000)
    out["owner_hash"] = page.evaluate("location.hash")
    out["owner_steps"] = page.locator(".steps .step").all_inner_texts()
    out["typo_welcome"] = typo(page)
    page.screenshot(path="/tmp/tour-1-welcome.png")
    page.click("button:has-text('Next')")
    page.wait_for_selector("h1:has-text('Your brand')", timeout=10000)
    page.wait_for_timeout(1500)
    out["brand_has_logo_box"] = page.locator("text=Add your logo").count() > 0
    out["typo_brand"] = typo(page)
    page.screenshot(path="/tmp/tour-2-brand.png")
    page.click("button:has-text('Next: light or dark')")
    page.wait_for_selector("h1:has-text('Light or dark')", timeout=10000)
    page.click(".look:has(b:text-is('Dark'))")
    out["dark_theme"] = page.evaluate("document.documentElement.dataset.theme || ''")
    out["dark_saved"] = page.evaluate("localStorage.getItem('d2d.theme')")
    out["typo_look"] = typo(page)
    page.screenshot(path="/tmp/tour-3-dark.png")
    page.click(".look:has(b:text-is('Match my device'))")
    out["system_theme"] = page.evaluate("document.documentElement.dataset.theme || ''")
    out["system_saved"] = page.evaluate("localStorage.getItem('d2d.theme')")
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(300)
    out["system_follows_dark"] = page.evaluate("document.documentElement.dataset.theme || ''")
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(300)
    page.click(".look:has(b:text-is('Light'))")
    out["light_theme"] = page.evaluate("document.documentElement.dataset.theme || ''")
    page.click("button:has-text('Next')")
    page.wait_for_selector("h1:has-text('The basics')", timeout=10000)
    out["typo_basics"] = typo(page)
    out["basics_text"] = page.locator(".tourbody").inner_text()[:600]
    page.screenshot(path="/tmp/tour-4-basics.png", full_page=True)
    page.click("button:has-text('Go to Dashboards')")
    page.wait_for_timeout(1500)
    out["after_done_hash"] = page.evaluate("location.hash")
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_timeout(3000)
    out["reload_hash"] = page.evaluate("location.hash")
    # the organisation menu: Migration D2D and Take the tour
    page.click("#orgchip .orgbtn")
    page.wait_for_timeout(400)
    out["menu"] = page.locator(".pmitem").all_inner_texts()
    page.keyboard.press("Escape")
    out["nav"] = page.locator(".side .nav a").all_inner_texts()
    # Migration D2D
    page.evaluate("location.hash = '#/migration'")
    page.wait_for_selector("h1:has-text('Migrate any dashboard')", timeout=10000)
    out["typo_migration"] = typo(page)
    out["mig_tools"] = page.locator(".migrmap .card").first.inner_text()
    page.screenshot(path="/tmp/mig-1-page.png", full_page=True)
    page.locator("button:has-text('Contact PASDACS')").first.click()
    page.wait_for_selector(".modal", timeout=5000)
    page.click(".modal button:has-text('Send to PASDACS')")
    out["mig_empty"] = page.locator(".modal [role=status]").inner_text()
    page.locator(".modal .toolpick").nth(0).locator("label:has-text('IBM Cognos Analytics') input").check()
    page.locator(".modal .toolpick").nth(1).locator("label:has-text('Power BI') input").check()
    page.fill(".modal input.num", "12")
    page.fill(".modal textarea", "Our finance pack")
    page.screenshot(path="/tmp/mig-2-dialog.png")
    page.click(".modal button:has-text('Send to PASDACS')")
    page.wait_for_function("!document.querySelector('.modal [role=status]').innerText.includes('Choose where')", timeout=15000)
    out["mig_sent"] = page.locator(".modal [role=status]").inner_text()
    page.screenshot(path="/tmp/mig-3-sent.png")
    page.keyboard.press("Escape")
    ctx.close()
    # a phone, in dark mode: nothing reaches past the right edge (the tour and Migration D2D)
    ph = b.new_context(viewport={"width": 375, "height": 812}, color_scheme="dark")
    ph.add_cookies([{"name": "d2d_session", "value": owner, "url": "http://127.0.0.1:8000"}])
    pp = ph.new_page()
    WIDE = '''() => { const W = document.documentElement.clientWidth; const r = [];
      for (const e of document.querySelectorAll("#main *")) { const x = e.getBoundingClientRect();
        if (x.right > W + 1 && x.width > 0) r.push(e.tagName.toLowerCase() + ': ' + (e.innerText || "").slice(0, 30)); }
      return {scroll: document.documentElement.scrollWidth - W, wide: r.slice(0, 6), dark: document.documentElement.dataset.theme || ""}; }'''
    for route, name in (("#/migration", "mig-4-phone-dark.png"), ("#/welcome", "tour-6-phone-dark.png")):
        pp.goto("http://127.0.0.1:8000/" + route)
        pp.wait_for_timeout(2500)
        out["phone_" + route[2:]] = pp.evaluate(WIDE)
        pp.screenshot(path="/tmp/" + name, full_page=True)
    ph.close()
    # a member: a deep link is left alone; the front page opens the tour without the brand step; Skip
    m = b.new_context(viewport={"width": 1200, "height": 900})
    m.add_cookies([{"name": "d2d_session", "value": member, "url": "http://127.0.0.1:8000"}])
    mp = m.new_page()
    mp.on("pageerror", lambda e: errors.append(str(e)))
    mp.goto("http://127.0.0.1:8000/#/org")
    mp.wait_for_timeout(3000)
    out["member_deeplink_hash"] = mp.evaluate("location.hash")
    mp.goto("http://127.0.0.1:8000/#/d2d")
    mp.reload()
    mp.wait_for_selector("h1:has-text('A quick tour')", timeout=20000)
    out["member_steps"] = mp.locator(".steps .step").all_inner_texts()
    mp.screenshot(path="/tmp/tour-5-member.png")
    mp.click("button:has-text('Skip the tour')")
    mp.wait_for_timeout(1500)
    out["member_after_skip"] = mp.evaluate("location.hash")
    out["member_toast"] = mp.locator("#toasts").inner_text()
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""

owner, member = c.Person(f"una.tour@tui{c.STAMP}.com"), c.Person(f"max.tour@tui{c.STAMP}.com")
s, r = owner.sign_in("Tour UI", "Una Tour")
c.check("ui: an organisation signs up", s == 200, (s, r))
s, r = member.sign_in()
c.check("ui: a colleague joins it", s == 200, (s, r))
ck = lambda p: next(k.value for k in p.jar if k.name == "d2d_session")      # noqa: E731
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", ck(owner), ck(member)], input=PLAY, capture_output=True,
                     text=True, encoding="utf-8", timeout=300)
if res.returncode:
    c.check("ui: headless Chromium ran", False, res.stderr[-2000:])
else:
    o = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps(o, indent=1, ensure_ascii=False))
    c.check("tour: a new owner opening the front page gets the tour", o["owner_hash"] == "#/welcome", o["owner_hash"])
    c.check("tour: an owner's tour has four steps, the brand among them", [x.split("\n")[-1] for x in o["owner_steps"]]
            == ["Welcome", "Your brand", "Light or dark", "The basics"], o["owner_steps"])
    c.check("tour: the brand step shows Branding (logo and words)", o["brand_has_logo_box"])
    c.check("tour: Dark switches the app to dark and remembers it", o["dark_theme"] == "dark" and o["dark_saved"] == '"dark"', o)
    c.check("tour: Match my device follows the device (light now, dark when the device turns dark)",
            o["system_theme"] == "" and o["system_saved"] == '"system"' and o["system_follows_dark"] == "dark", o)
    c.check("tour: Light switches back", o["light_theme"] == "", o["light_theme"])
    c.check("tour: the basics say how a dashboard is made, credits and Migration D2D",
            "How a dashboard is made" in o["basics_text"] and "Credits" in o["basics_text"] and "Migration D2D" in o["basics_text"], o["basics_text"])
    c.check("tour: Go to Dashboards ends it", o["after_done_hash"] == "#/d2d", o["after_done_hash"])
    c.check("tour: opening the app again does not show it again", o["reload_hash"] in ("", "#/", "#/d2d"), o["reload_hash"])
    c.check("tour: the organisation menu has Migration D2D and Take the tour",
            any("Migration D2D" in x for x in o["menu"]) and any("Take the tour" in x for x in o["menu"]), o["menu"])
    c.check("migration: the sidebar has Migration D2D", any("Migration D2D" in x for x in o["nav"]), o["nav"])
    c.check("migration: the page lists Cognos, Qlik, Looker, Power BI", all(t in o["mig_tools"] for t in ("Cognos", "Qlik", "Looker", "Power BI")), o["mig_tools"])
    c.check("migration: Send with nothing chosen asks for the tools", "Choose where your dashboards are now" in o["mig_empty"], o["mig_empty"])
    c.check("migration: Send tells the person it went to PASDACS (or what to do if the email failed)",
            "Sent to info@pasdacs.com" in o["mig_sent"] or "recorded" in o["mig_sent"], o["mig_sent"])
    for k in ("phone_migration", "phone_welcome"):
        v = o[k]
        c.check(f"{k[6:]}: on a phone in dark mode nothing reaches past the screen", v["scroll"] <= 0 and not v["wide"] and v["dark"] == "dark", v)
    c.check("tour: a deep link (#/org) is opened as asked, not replaced by the tour", o["member_deeplink_hash"] == "#/org", o["member_deeplink_hash"])
    c.check("tour: a member's tour has no brand step", [x.split("\n")[-1] for x in o["member_steps"]] == ["Welcome", "Light or dark", "The basics"], o["member_steps"])
    c.check("tour: Skip the tour goes to Dashboards and says where to find it again",
            o["member_after_skip"] == "#/d2d" and "Take the tour" in o["member_toast"], (o["member_after_skip"], o["member_toast"]))
    for k in ("typo_welcome", "typo_brand", "typo_look", "typo_basics", "typo_migration"):
        c.check(f"plain: no long dashes, curly quotes or arrows on {k[5:]}", not o[k], o[k])
    c.check("ui: no script errors", not o["errors"], o["errors"])
    for f in ("tour-1-welcome.png", "tour-2-brand.png", "tour-3-dark.png", "tour-4-basics.png", "tour-5-member.png",
              "mig-1-page.png", "mig-2-dialog.png", "mig-3-sent.png", "mig-4-phone-dark.png", "tour-6-phone-dark.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False)
s, me = owner.get("/api/me")
c.check("tour: finished, the server says it is not due, and the organisation is set up",
        me.get("tour") is False and not (me.get("org") or {}).get("setup_needed"), (me.get("tour"), (me.get("org") or {}).get("setup_needed")))
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
