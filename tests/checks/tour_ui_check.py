"""Test stack only: the tour in a real browser (headless Chromium inside the test web container). Since 2026-11-19 the tour
is a guided walk over the app: the screen dims, one part is lit, a callout says what it is, with Next, Back and Skip; it
opens with six guides (build a dashboard, KPIs, Ask Relay, Semantic Review, Ontology, Relay Visual) that open the pages
and light each part. Checked: a new owner gets it on the front page (the organisation setup offered first, and the end
of the walk leads to it), the walk through everything (lit parts, light, dark and the device's look), two guides, Back,
the setup finished, the tour not shown again and opened again from Take the tour, a member skipping it, a deep link left
alone, a phone; Migration D2D (one contact, the dialog), DAWB (coming soon, one contact), and single sign-on shown on the
sign-in code step. Screenshots go to the run's folder (tests/out/<run>): tour-*.png, mig-*.png, dawb-*.png, login-*.png.

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
def settle(page):
    page.wait_for_function("() => { const t = document.querySelector('#coach .coach-tip'); return t && !t.classList.contains('wait'); }", timeout=15000)
    page.wait_for_timeout(450)
def state(page, sel=None):
    return page.evaluate('''(sel) => { const t = document.querySelector('#coach .coach-tip'), hole = document.querySelector('.coach-hole');
      if (!t) return null; const r = t.getBoundingClientRect(), W = document.documentElement.clientWidth, H = innerHeight;
      let on = null; if (sel) { const e = document.querySelector(sel); if (e && !hole.classList.contains('none')) { const a = e.getBoundingClientRect(), b = hole.getBoundingClientRect();
        on = b.left <= a.left + 1 && b.top <= a.top + 1 && b.right >= a.right - 1 && b.bottom >= a.bottom - 1; } else on = false; }
      return {title: (document.querySelector('#coach-title') || {}).textContent || '', hash: location.hash, lit: !hole.classList.contains('none'), on,
        inview: r.left >= 0 && r.top >= 0 && r.right <= W + 1 && r.bottom <= H + 1, go: (t.querySelector('.coach-go') || {}).textContent || '',
        covered: document.elementFromPoint(5, H - 5) === document.querySelector('#coach'),
        sample: ((document.querySelector('#main .tsample') || {}).dataset || {}).sample || '', text: (document.querySelector('#coach-text') || {}).textContent || '', box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height), W, H]}; }''', sel)
def nxt(page):
    page.click("#coach .coach-foot button:text-is('Next')"); settle(page)
def walk(page):
    seen = [state(page)]
    while page.locator("#coach .coach-foot button:text-is('Next')").count():
        nxt(page); seen.append(state(page))
        if len(seen) > 30: break
    return seen
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": owner, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_selector("#coach #coach-title", timeout=20000); settle(page)
    out["owner"] = state(page)
    out["guides"] = page.locator("#coach .coach-act b").all_inner_texts()
    out["first"] = page.locator("#coach .coach-first").inner_text() if page.locator("#coach .coach-first").count() else ""
    out["org_line"] = page.locator("#coach .coach-org").inner_text() if page.locator("#coach .coach-org").count() else ""
    out["typo_welcome"] = typo(page)
    page.screenshot(path="/tmp/tour-1-welcome.png")
    # the walk through everything: each part lit in turn
    page.click("#coach button:has-text('Show me around')"); settle(page)
    out["all_home"] = state(page, ".side .nav a[href='#/']")
    page.screenshot(path="/tmp/tour-2-home.png")
    seen = [out["all_home"]]
    while page.locator("#coach .coach-foot button:text-is('Next')").count() and len(seen) < 30:
        nxt(page); s = state(page); seen.append(s)
        if s["title"] == "Ask Relay":
            out["all_ask"] = state(page, ".side .nav a[href='#/askd']"); page.screenshot(path="/tmp/tour-3-ask.png")
        if s["title"] == "Light or dark":
            page.click("#coach .coach-looks button:has-text('Dark')")
            out["dark_theme"] = page.evaluate("document.documentElement.dataset.theme || ''")
            out["dark_saved"] = page.evaluate("localStorage.getItem('d2d.theme')")
            page.screenshot(path="/tmp/tour-4-dark.png")
            page.click("#coach .coach-looks button:has-text('Match my device')")
            out["system_theme"] = page.evaluate("document.documentElement.dataset.theme || ''")
            out["system_saved"] = page.evaluate("localStorage.getItem('d2d.theme')")
            page.emulate_media(color_scheme="dark"); page.wait_for_timeout(300)
            out["system_follows_dark"] = page.evaluate("document.documentElement.dataset.theme || ''")
            page.emulate_media(color_scheme="light"); page.wait_for_timeout(300)
            page.click("#coach .coach-looks button:has-text('Light')")
            out["light_theme"] = page.evaluate("document.documentElement.dataset.theme || ''")
    out["all"] = [[s["title"], s["lit"], s["inview"], s["box"]] for s in seen]
    out["typo_all"] = typo(page)
    page.click("#coach .coach-foot button:text-is('Back')"); settle(page)
    out["back"] = state(page)["title"]
    nxt(page)
    out["last_buttons"] = page.locator("#coach .coach-foot button").all_inner_texts()
    page.screenshot(path="/tmp/tour-5-last.png")
    # the Ask Relay guide opens Ask Relay and lights its parts
    page.click("#coach button:has-text('All guides')"); settle(page)
    page.click("#coach .coach-act:has-text('Ask Relay')"); settle(page)
    ask = walk(page)
    out["ask"] = [[s["title"], s["sample"], s["lit"]] for s in ask] + [ask[-1]["go"]]
    out["ask_banner"] = page.locator("#main .tsample .ts-banner").inner_text() if page.locator("#main .tsample .ts-banner").count() else ""
    page.screenshot(path="/tmp/tour-6-ask-guide.png")
    page.click("#coach .coach-foot .coach-go"); page.wait_for_timeout(2500)        # Ask a question: the real Ask Relay
    out["ask_end"] = [page.evaluate("location.hash"), page.locator("#coach").count(), page.locator("#main .tsample").count()]
    page.click("#tourlink"); page.wait_for_selector("#coach #coach-title", timeout=10000); settle(page)
    # the Build a dashboard guide (from the welcome, opened again): New dashboard lit, then a sample filled in; with the
    # setup open it ends at the setup
    page.click("#coach .coach-act:has-text('Build a dashboard')"); settle(page)
    out["build_1"] = state(page, "#newbtn")
    nxt(page)
    out["build_2"] = state(page, "#main .tsample .ts-name")
    build = [out["build_2"]]
    while page.locator("#coach .coach-foot button:text-is('Next')").count() and len(build) < 30:
        nxt(page); st = state(page); build.append(st)
        if st["title"] == "Credits are taken here":
            out["build_credits"] = dict(st, on=state(page, "#main .tsample .ts-next")["on"], page=page.locator("#main .tsample").inner_text()[:900])
            page.screenshot(path="/tmp/tour-7-build-guide.png")
    out["build"] = [[x["title"], x["sample"], x["lit"]] for x in build]
    out["build_go"] = build[-1]["go"]
    out["typo_guides"] = typo(page)
    page.click("#coach .coach-foot .coach-go"); page.wait_for_timeout(2000)
    out["after_build"] = [page.evaluate("location.hash"), page.locator("#coach").count()]
    # finish the setup as d2d_checks.ensure_setup does (no AI): the standard proposal, nothing extra kept, a standard palette
    out["setup_done"] = page.evaluate('''async () => {
      const call = (method, path, body) => fetch(path, {method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined})
        .then(r => r.json().then(j => [r.status, j]));
      await call('PUT', '/api/org/profile/context', {industry: 'general', about: 'A small test business that sells products to its customers.'});
      const [, std] = await call('POST', '/api/org/profile/standard');
      await call('PUT', '/api/org/profile/understanding', (std.proposal || {}).understanding || {summary: 'A small test business.'});
      await call('POST', '/api/org/profile/kpis', {accept: []});
      await call('POST', '/api/org/profile/terms', {accept: []});
      await call('POST', '/api/branding/choose', {index: 0, standard: true});
      const [st, done] = await call('POST', '/api/org/profile/done');
      return st === 200 && done.status === 'done'; }''')
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_timeout(3000)
    out["reload"] = [page.evaluate("location.hash"), page.locator("#coach").count()]
    # Take the tour, above the foot of the menu, opens the guides again; Escape closes them
    page.click("#tourlink"); page.wait_for_selector("#coach #coach-title", timeout=10000); settle(page)
    out["again"] = [state(page)["title"], page.locator("#coach .coach-first").count()]
    page.keyboard.press("Escape"); page.wait_for_timeout(1200)
    out["after_escape"] = [page.evaluate("location.hash"), page.locator("#coach").count()]
    # the organisation menu, the menu
    page.click("#orgchip .orgbtn"); page.wait_for_timeout(400)
    out["menu"] = page.locator(".pmitem").all_inner_texts()
    page.keyboard.press("Escape")
    out["nav"] = page.locator(".side .nav a").all_inner_texts()
    # Migration D2D: one contact, then the dialog
    page.evaluate("location.hash = '#/migration'")
    page.wait_for_selector("h1:has-text('Migrate any dashboard')", timeout=10000)
    out["typo_migration"] = typo(page)
    out["mig_tools"] = page.locator(".migrmap .card").first.inner_text()
    out["mig_contacts"] = page.locator("#main :text-is('Contact PASDACS')").count()
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
    page.wait_for_timeout(600)
    # DAWB: coming soon, what it is, one contact
    page.evaluate("location.hash = '#/dawb'")
    page.wait_for_selector("#main h3:has-text('Interested in DAWB?')", timeout=10000)
    page.wait_for_timeout(800)
    out["dawb"] = {"text": page.locator("#main").inner_text()[:2500], "contacts": page.locator("#main :text-is('Contact PASDACS')").count(),
                   "href": page.locator("#main a:has-text('Contact PASDACS')").get_attribute("href") or ""}
    out["typo_dawb"] = typo(page)
    page.screenshot(path="/tmp/dawb-1-page.png", full_page=True)
    ctx.close()
    # a phone, in dark mode: nothing reaches past the right edge; the tour's callout fits and the menu opens as a drawer
    ph = b.new_context(viewport={"width": 375, "height": 812}, color_scheme="dark")
    ph.add_cookies([{"name": "d2d_session", "value": owner, "url": "http://127.0.0.1:8000"}])
    pp = ph.new_page()
    WIDE = '''() => { const W = document.documentElement.clientWidth; const r = [];
      for (const e of document.querySelectorAll("#main *")) { const x = e.getBoundingClientRect();
        if (x.right > W + 1 && x.width > 0) r.push(e.tagName.toLowerCase() + ': ' + (e.innerText || "").slice(0, 30)); }
      return {scroll: document.documentElement.scrollWidth - W, wide: r.slice(0, 6), dark: document.documentElement.dataset.theme || ""}; }'''
    for route, name in (("#/migration", "mig-4-phone-dark.png"), ("#/dawb", "dawb-2-phone-dark.png")):
        pp.goto("http://127.0.0.1:8000/" + route)
        pp.wait_for_timeout(2500)
        out["phone_" + route[2:]] = pp.evaluate(WIDE)
        pp.screenshot(path="/tmp/" + name, full_page=True)
    pp.goto("http://127.0.0.1:8000/#/welcome"); pp.wait_for_selector("#coach #coach-title", timeout=20000); settle(pp)
    out["phone_welcome"] = state(pp)
    pp.screenshot(path="/tmp/tour-8-phone-dark.png")
    pp.click("#coach button:has-text('Show me around')"); settle(pp); pp.wait_for_timeout(500)
    out["phone_home"] = dict(state(pp, ".side .nav a[href='#/']"), drawer=pp.evaluate("document.querySelector('.app').classList.contains('drawer')"))
    pp.screenshot(path="/tmp/tour-9-phone-menu.png")
    pp.keyboard.press("Escape"); pp.wait_for_timeout(1200)
    out["phone_after"] = [pp.locator("#coach").count(), pp.evaluate("document.querySelector('.app').classList.contains('drawer')")]
    ph.close()
    # a member: a deep link is left alone; the front page opens the tour; Skip the tour
    m = b.new_context(viewport={"width": 1200, "height": 900})
    m.add_cookies([{"name": "d2d_session", "value": member, "url": "http://127.0.0.1:8000"}])
    mp = m.new_page()
    mp.on("pageerror", lambda e: errors.append(str(e)))
    mp.goto("http://127.0.0.1:8000/#/org")
    mp.wait_for_timeout(3000)
    out["member_deeplink"] = [mp.evaluate("location.hash"), mp.locator("#coach").count()]
    mp.goto("http://127.0.0.1:8000/#/d2d")
    mp.reload()
    mp.wait_for_selector("#coach #coach-title", timeout=20000); settle(mp)
    out["member"] = [mp.evaluate("location.hash"), mp.locator("#coach .coach-act").count(), mp.locator("#coach .coach-first").count()]
    mp.screenshot(path="/tmp/tour-10-member.png")
    mp.click("#coach button:has-text('Skip the tour')")
    mp.wait_for_timeout(1500)
    out["member_after_skip"] = [mp.evaluate("location.hash"), mp.locator("#coach").count()]
    out["member_toast"] = mp.locator("#toasts").inner_text()
    m.close()
    # sign-in: the code step offers single sign-on with Google and Microsoft, switched on by PASDACS (a bot check on this
    # stack stops a real code here, so the code step is shown as the page shows it after Continue)
    lg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    lg.on("pageerror", lambda e: errors.append(str(e)))
    lg.goto("http://127.0.0.1:8000/login.html"); lg.wait_for_timeout(800)
    out["sso_before"] = lg.locator("#ssobox").is_visible()
    lg.fill("#email", "ana@contoso-retail.com")
    lg.evaluate("() => { document.getElementById('askform').hidden = true; document.getElementById('codeform').hidden = false; ssoLinks(); }")
    lg.wait_for_timeout(300)
    out["sso"] = {"shown": lg.locator("#ssobox").is_visible(), "text": lg.inner_text("#ssobox"),
                  "google": lg.get_attribute("#sso-google", "href"), "microsoft": lg.get_attribute("#sso-microsoft", "href")}
    out["typo_login"] = typo(lg)
    lg.screenshot(path="/tmp/login-1-sso.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""

owner, member = c.Person(f"una.tour@tui{c.STAMP}.com"), c.Person(f"max.tour@tui{c.STAMP}.com")
s, r = owner.sign_in("Tour UI", "Una Tour", brand=False)        # no setup yet: the tour offers it first (item 81)
c.check("ui: an organisation is set up", s == 200, (s, r))
s, r = member.sign_in()
c.check("ui: a colleague joins it", s == 200, (s, r))
ck = lambda p: next(k.value for k in p.jar if k.name == "d2d_session")      # noqa: E731
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", ck(owner), ck(member)], input=PLAY, capture_output=True,
                     text=True, encoding="utf-8", timeout=600)
if res.returncode:
    c.check("ui: headless Chromium ran", False, res.stderr[-2000:])
else:
    o = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps(o, indent=1, ensure_ascii=False))
    w = o["owner"]
    c.check("tour: a new owner opening the front page gets the tour, the screen dimmed", w["hash"] == "#/welcome" and w["covered"] and w["inview"], w)
    c.check("tour: it opens with what they want to do: six guides", o["guides"] == ["Build a dashboard", "Set up your KPIs", "Ask Relay",
            "Semantic Review", "Ontology", "Relay Visual"], o["guides"])
    c.check("tour: an owner is offered the organisation setup first (item 81)", "First, set up Tour UI" in o["first"] and "Set up now" in o["first"], o["first"])
    c.check("tour: it says who is in the organisation: the people the owner adds", "the people you add" in o["org_line"], o["org_line"])
    h1 = o["all_home"]
    c.check("tour: Show me around lights Home in the menu first", h1["title"] == "Home" and h1["lit"] and h1["on"] and h1["inview"], h1)
    titles = [x[0] for x in o["all"]]
    for want in ("Set up Tour UI first", "New dashboard", "Dashboards", "Ask Relay", "Semantic Review", "Ontology", "Relay Visual",
                 "Migration D2D", "DAWB, coming soon", "Organisation", "Branding", "Connections", "Notifications", "Light or dark", "Come back any time"):
        c.check(f"tour: the walk shows {want}", want in titles, titles)
    c.check("tour: every part of the walk is lit, its callout on the screen", all(x[1] and x[2] for x in o["all"]),
            [x for x in o["all"] if not (x[1] and x[2])])
    c.check("tour: Ask Relay is lit where it is in the menu", (o.get("all_ask") or {}).get("on") is True, o.get("all_ask"))
    c.check("tour: Dark switches the app to dark and remembers it", o.get("dark_theme") == "dark" and o.get("dark_saved") == '"dark"', o)
    c.check("tour: Match my device follows the device (light now, dark when the device turns dark)",
            o.get("system_theme") == "" and o.get("system_saved") == '"system"' and o.get("system_follows_dark") == "dark", o)
    c.check("tour: Light switches back", o.get("light_theme") == "", o.get("light_theme"))
    c.check("tour: Back goes one step back", o["back"] == titles[-2], (o["back"], titles[-2:]))
    c.check("tour: the walk ends at the setup while it is open (Set up Tour UI), with All guides beside it",
            "Set up Tour UI" in o["last_buttons"] and "All guides" in o["last_buttons"], o["last_buttons"])
    ask = o["ask"]
    c.check("guide: Ask Relay lights Ask Relay in the menu, then a sample conversation, each part lit",
            ask[0][1] == "" and all(x[1] == "ask" for x in ask[1:-1]) and all(x[2] for x in ask[:-1])
            and [x[0] for x in ask[:-1]] == ["Ask Relay", "Ask in your own words", "The answer", "Ask the next question"], ask)
    c.check("guide: the sample says it is a sample, nothing saved or charged", "Sample." in o["ask_banner"] and "nothing here is saved or charged" in o["ask_banner"], o["ask_banner"])
    c.check("guide: Ask Relay ends with Ask a question, which opens the real Ask Relay", ask[-1] == "Ask a question" and o["ask_end"] == ["#/askd", 0, 0],
            (ask[-1], o["ask_end"]))
    c.check("guide: Build a dashboard starts at New dashboard, lit", o["build_1"]["on"] is True and o["build_1"]["title"] == "Start with New dashboard", o["build_1"])
    c.check("guide: then a sample New dashboard, filled in (the name lit)",
            o["build_2"]["title"] == "1. Name" and o["build_2"]["sample"] == "nd-0" and o["build_2"]["on"] is True and o["build_2"]["hash"] == "#/welcome", o["build_2"])
    bt = [x[0] for x in o["build"]]
    c.check("guide: the sample goes through all six steps, Confirm KPIs, the prototype and the Power BI file",
            all(t in bt for t in ("2. Your data", "3. What to build", "4. Theme", "5. Visuals", "6. Check and start", "Confirm KPIs",
                                  "The prototype", "Your Power BI file")) and all(x[2] for x in o["build"]), o["build"])
    bc = o.get("build_credits") or {}
    c.check("guide: it shows where the credits are taken: Next on Your data, 25 credits, not refunded; custom visuals 25 more",
            bc.get("on") is True and "25 credits" in bc.get("text", "") and "not refunded" in bc.get("text", "")
            and "Going on takes 25 credits" in bc.get("page", "") and "take 25 more" in bc.get("page", ""), bc)
    c.check("guide: with the setup open it ends at the setup (Set up Tour UI first)", o["build_go"] == "Set up Tour UI first", o["build_go"])
    c.check("guide: which opens the setup and closes the tour", o["after_build"][0].startswith("#/setup") and o["after_build"][1] == 0, o["after_build"])
    c.check("tour: the setup is finished (with a standard palette)", o.get("setup_done") is True, o.get("setup_done"))
    c.check("tour: opening the app again does not show it again", o["reload"][0] in ("", "#/", "#/d2d") and o["reload"][1] == 0, o["reload"])
    c.check("tour: Take the tour opens the guides again, no setup offered once it is done",
            o["again"][0].startswith("Welcome to D2D Relay") and o["again"][1] == 0, o["again"])
    c.check("tour: Escape closes it", o["after_escape"][1] == 0, o["after_escape"])
    c.check("tour: the organisation menu has Migration D2D and Take the tour",
            any("Migration D2D" in x for x in o["menu"]) and any("Take the tour" in x for x in o["menu"]), o["menu"])
    c.check("migration: the sidebar has Migration D2D", any("Migration D2D" in x for x in o["nav"]), o["nav"])
    c.check("dawb: the sidebar has DAWB, marked Soon", any(x.split("\n")[0] == "DAWB" and "Soon" in x for x in o["nav"]), o["nav"])
    c.check("migration: the page lists Cognos, Qlik, Looker, Power BI", all(t in o["mig_tools"] for t in ("Cognos", "Qlik", "Looker", "Power BI")), o["mig_tools"])
    c.check("migration: one contact on the page, not two", o["mig_contacts"] == 1, o["mig_contacts"])
    c.check("migration: Send with nothing chosen asks for the tools", "Choose where your dashboards are now" in o["mig_empty"], o["mig_empty"])
    c.check("migration: Send tells the person it went to PASDACS (or what to do if the email failed)",
            "Sent to info@pasdacs.com" in o["mig_sent"] or "recorded" in o["mig_sent"], o["mig_sent"])
    d = o["dawb"]
    c.check("dawb: coming soon, and what it is", "Coming soon" in d["text"] and "AI agents do the data-engineering work" in d["text"]
            and "How it works" in d["text"] and "What it covers" in d["text"], d["text"])
    c.check("dawb: one contact, an email to PASDACS", d["contacts"] == 1 and d["href"].startswith("mailto:info@pasdacs.com?subject="), d)
    for k in ("phone_migration", "phone_dawb"):
        v = o[k]
        c.check(f"{k[6:]}: on a phone in dark mode nothing reaches past the screen", v["scroll"] <= 0 and not v["wide"] and v["dark"] == "dark", v)
    c.check("tour: on a phone the welcome fits the screen", o["phone_welcome"]["inview"] and o["phone_welcome"]["covered"], o["phone_welcome"])
    c.check("tour: on a phone the menu opens as a drawer and Home is lit in it",
            o["phone_home"]["drawer"] is True and o["phone_home"]["on"] is True and o["phone_home"]["inview"], o["phone_home"])
    c.check("tour: closing it on a phone closes the drawer too", o["phone_after"] == [0, False], o["phone_after"])
    c.check("tour: a deep link (#/org) is opened as asked, not replaced by the tour", o["member_deeplink"] == ["#/org", 0], o["member_deeplink"])
    c.check("tour: a member gets the six guides, no setup to do", o["member"] == ["#/welcome", 6, 0], o["member"])
    c.check("tour: Skip the tour goes Home and says where to find it again",
            o["member_after_skip"] == ["#/", 0] and "Take the tour" in o["member_toast"], (o["member_after_skip"], o["member_toast"]))
    sso = o["sso"]
    c.check("sign-in: single sign-on is not shown before the code step", o["sso_before"] is False, o["sso_before"])
    c.check("sign-in: the code step offers Google and Microsoft single sign-on, contact to enable",
            sso["shown"] and "Sign in with Google" in sso["text"] and "Sign in with Microsoft" in sso["text"] and sso["text"].count("Contact to enable") == 2, sso)
    c.check("sign-in: each writes to PASDACS for the address's domain",
            all((sso[k] or "").startswith("mailto:info@pasdacs.com?subject=") and "contoso-retail.com" in sso[k] for k in ("google", "microsoft")), sso)
    for k in ("typo_welcome", "typo_all", "typo_guides", "typo_migration", "typo_dawb", "typo_login"):
        c.check(f"plain: no long dashes, curly quotes or arrows on {k[5:]}", not o[k], o[k])
    c.check("ui: no script errors", not o["errors"], o["errors"])
    for f in ("tour-1-welcome.png", "tour-2-home.png", "tour-3-ask.png", "tour-4-dark.png", "tour-5-last.png", "tour-6-ask-guide.png",
              "tour-7-build-guide.png", "tour-8-phone-dark.png", "tour-9-phone-menu.png", "tour-10-member.png", "mig-1-page.png",
              "mig-2-dialog.png", "mig-3-sent.png", "mig-4-phone-dark.png", "dawb-1-page.png", "dawb-2-phone-dark.png", "login-1-sso.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False)
s, me = owner.get("/api/me")
c.check("tour: finished, the server says it is not due, and the organisation is set up",
        me.get("tour") is False and not (me.get("org") or {}).get("setup_needed"), (me.get("tour"), (me.get("org") or {}).get("setup_needed")))
s, br = owner.get("/api/branding")
c.check("tour: the organisation's brand is the standard palette picked in the setup (ready for dashboards)",
        s == 200 and br.get("ready") is True and (br.get("style") or {}).get("name"), (s, {k: (br or {}).get(k) for k in ("ready", "style")}))
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
