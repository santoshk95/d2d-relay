"""Item 90 (2026-11-19): a new dashboard's credits are taken in its steps. Going on from Your data takes the built-in
visuals' price; going on from Visuals with custom visuals takes the difference; once each per draft (back and forth, or
the page opened again, takes nothing more); neither comes back. Starting the dashboard uses the draft (nothing more to
pay) and moves its charges onto the dashboard; its first run keeps them when it fails, and Retry is free. A dashboard
started without the steps (the API alone) still pays at the start, as before. Needs a stack without Claude: the plan
run must fail.

python -I -X utf8 item90_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
"""
import os
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

o = c.Person(f"nia.owner@steps{c.STAMP}.com")
s, r = o.sign_in("Steps Credits", "Nia Owner")
c.check("item 90: an organisation with its 50 starting credits", s == 200, (s, r))


def credits():
    return (o.get("/api/me")[1].get("org") or {}).get("credits")


s, d = o.get("/api/new-dashboard/credits")
c.check("item 90: no draft yet, nothing paid", s == 200 and d.get("base") is False and d.get("custom") is False, (s, d))
s, r = o.post("/api/new-dashboard/credits", {"stage": "data", "name": "Steps test"})
c.check("item 90: going on from Your data takes 25 credits", s == 200 and r.get("charged") == 25 and r.get("credits") == 25 and r.get("base") is True, (s, r))
s, r = o.post("/api/new-dashboard/credits", {"stage": "data", "name": "Steps test"})
c.check("item 90: ... once: going on again takes nothing", s == 200 and r.get("charged") == 0 and credits() == 25, (s, r))
s, r = o.post("/api/new-dashboard/credits", {"stage": "visuals", "visuals_mode": "builtin"})
c.check("item 90: built-in visuals take nothing more", s == 200 and r.get("charged") == 0 and r.get("custom") is False, (s, r))
s, r = o.post("/api/new-dashboard/credits", {"stage": "visuals", "visuals_mode": "mixed"})
c.check("item 90: custom visuals take the difference, 25 more", s == 200 and r.get("charged") == 25 and r.get("custom") is True and credits() == 0, (s, r))
s, r = o.post("/api/new-dashboard/credits", {"stage": "visuals", "visuals_mode": "relay"})
c.check("item 90: ... once", s == 200 and r.get("charged") == 0, (s, r))
s, r = o.post("/api/new-dashboard/credits", {"stage": "build"})
c.check("item 90: an unknown step is refused (400)", s == 400, (s, r))
s, d = o.get("/api/new-dashboard/credits")
c.check("item 90: the draft says what it paid", d.get("base") is True and d.get("custom") is True, d)

s, r = o.form("/api/projects", {"prompt": "Sales by region and month", "data_mode": "upload", "name": "Steps test", "visuals_mode": "mixed"},
              {"files": ("sales.csv", c.CSV)})
pid = (r or {}).get("id")
c.check("item 90: starting uses the draft: nothing more to pay (the organisation has no credits left)", s == 200 and bool(pid) and credits() == 0, (s, r))
s, d = o.get("/api/new-dashboard/credits")
c.check("item 90: the draft is used up", d.get("base") is False, d)
s, p = o.get(f"/api/projects/{pid}")
cr = p.get("credits") or {}
c.check("item 90: the dashboard carries both charges (50) and has custom visuals paid",
        cr.get("used") == 50 and len(cr.get("items") or []) == 2 and p.get("custom_paid") is True and cr.get("custom_extra") == 0, cr)
end = time.time() + 120
while time.time() < end and p.get("status") not in ("error", "awaiting_kpis", "ready"):
    time.sleep(3)
    p = o.get(f"/api/projects/{pid}")[1]
c.check("item 90: the plan run ends (it fails on a stack without Claude)", p.get("status") == "error", p.get("status"))
c.check("item 90: a failed first run keeps the credits (not refunded)", credits() == 0 and (p.get("credits") or {}).get("used") == 50, p.get("credits"))
c.check("item 90: ... and Retry is free", (p.get("credits") or {}).get("retry") == 0, p.get("credits"))
s, r = o.post(f"/api/projects/{pid}/retry")
c.check("item 90: Retry runs with no credits left", s == 200 and credits() == 0, (s, r))

s, r = o.post("/api/new-dashboard/credits", {"stage": "data", "name": "Second"})
c.check("item 90: a new draft with no credits is refused (402)", s == 402, (s, r))
s, r = c.new_dashboard(o)
c.check("item 90: a dashboard started without the steps pays at the start, as before (402 with no credits)", s == 402, (s, r))

# ---------------------------------------------------------------- the steps in a real browser (a second organisation)
import json  # noqa: E402
import subprocess  # noqa: E402

PLAY = c.ND_FLOW + r"""
import json, sys
from playwright.sync_api import sync_playwright
open("/tmp/steps.csv", "w").write("month,region,sales\n2026-01,North,120\n2026-02,North,135\n2026-01,South,98\n2026-02,South,101\n")
out = {}
NAV = "form.formcard.nd .nd-nav button[type=submit]"
credits = lambda page: page.evaluate("fetch('/api/me').then(r => r.json()).then(j => j.org.credits)")
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1366, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": sys.argv[1], "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page(); errs = []
    page.on("pageerror", lambda e: errs.append(str(e)[:200]))
    nd_open(page)
    page.fill("#nd-name", "Steps UI")
    nd_next(page, 1)
    nd_upload(page, ".csv", "/tmp/steps.csv", "steps.csv")
    page.wait_for_timeout(600)
    out["data_cost"] = page.inner_text(ND_SHOWN + " .nd-cost")
    out["data_next"] = page.inner_text(NAV)
    out["before"] = credits(page)
    nd_next(page, 2)
    page.wait_for_timeout(800)
    out["after_data"] = credits(page)
    page.click("form.formcard.nd .nd-nav button:has-text('Back')"); nd_step(page, 1); page.wait_for_timeout(600)
    out["data_cost_paid"] = page.inner_text(ND_SHOWN + " .nd-cost")
    out["data_next_paid"] = page.inner_text(NAV)
    nd_next(page, 2)
    page.wait_for_timeout(800)
    if not page.input_value("#nd-prompt"):
        page.fill("#nd-prompt", "Sales by region and month")
    nd_next(page, 3)
    page.wait_for_selector(ND_SHOWN + " .nd-theme", timeout=30000)
    nd_next(page, 4)
    page.wait_for_timeout(500)
    out["vis_cards"] = page.locator(ND_SHOWN + " .nd-card .cr").all_inner_texts()
    page.click(ND_SHOWN + " label.nd-card:has(input[value='mixed'])")
    page.wait_for_timeout(300)
    out["vis_next"] = page.inner_text(NAV)
    out["vis_text"] = page.inner_text(ND_SHOWN)
    nd_next(page, 5)
    page.wait_for_timeout(800)
    out["after_vis"] = credits(page)
    out["check"] = page.inner_text(ND_SHOWN + " dl.nd-sum")
    page.reload()
    page.wait_for_selector("form.formcard.nd", timeout=30000)
    page.wait_for_timeout(2500)
    out["after_reload"] = credits(page)
    out["reload_check"] = page.inner_text(ND_SHOWN) if page.locator(ND_SHOWN + " dl.nd-sum").count() else page.inner_text(ND_SHOWN)[:300]
    out["errors"] = errs
    page.screenshot(path="/tmp/item90-check.png", full_page=True)
    print(json.dumps(out))
"""
u = c.Person(f"ola.owner@stepsui{c.STAMP}.com")
s, r = u.sign_in("Steps UI", "Ola Owner")
c.check("item 90 ui: a second organisation with 50 credits", s == 200, (s, r))
u.post("/api/me/tour", {"step": "done"})        # the first-time tour would open on #/new otherwise (38-tour.js TOUR_LANDING)
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", c.cookie(u, "d2d_session")], input=PLAY, capture_output=True,
                     text=True, encoding="utf-8", timeout=400)
if res.returncode:
    c.check("item 90 ui: headless Chromium ran", False, res.stderr[-2000:])
else:
    w = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps(w, indent=1, ensure_ascii=False))
    c.check("item 90 ui: Your data says what going on takes, and that it is not refunded",
            "Going on takes 25 credits" in w["data_cost"] and "not refunded" in w["data_cost"] and "take 25 more" in w["data_cost"], w["data_cost"])
    c.check("item 90 ui: ... and so does its Next", "25 credits" in w["data_next"] and w["before"] == 50, (w["data_next"], w["before"]))
    c.check("item 90 ui: Next on Your data takes 25", w["after_data"] == 25, w["after_data"])
    c.check("item 90 ui: back on Your data it says they are taken, and Next takes nothing more",
            "are taken" in w["data_cost_paid"] and "credits" not in w["data_next_paid"], (w["data_cost_paid"], w["data_next_paid"]))
    c.check("item 90 ui: Visuals: built-in included, custom visuals 25 more", w["vis_cards"][:1] == ["Included"] and all(x == "+25 credits" for x in w["vis_cards"][1:]),
            w["vis_cards"])
    c.check("item 90 ui: choosing custom visuals: Next says 25 credits, and that they are not refunded",
            "25 credits" in w["vis_next"] and "Custom visuals take 25 more credits when you go on" in w["vis_text"] and "not refunded" in w["vis_text"],
            (w["vis_next"], w["vis_text"][-400:]))
    c.check("item 90 ui: Next on Visuals takes 25 more", w["after_vis"] == 0, w["after_vis"])
    c.check("item 90 ui: Check and start says it is all taken: starting uses no more", "taken in the steps: starting uses no more" in w["check"], w["check"])
    c.check("item 90 ui: the page opened again takes nothing more", w["after_reload"] == 0, w["after_reload"])
    c.check("item 90 ui: no script errors", not w["errors"], w["errors"])
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item90-check.png", c.out_path("item90-check.png")], check=False)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
