"""Test stack only: the data-governance screens in a real browser (headless Chromium inside the test web container).

python -I gov_ui_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
Delete on a dashboard page (confirm dialog, then gone), Delete conversation in Ask Relay, the "Your data" card with
Download my data on the organisation page, the privacy notice linked from the sign-in page. Screenshots go to the
run's folder (tests/out/<run>): gov-yourdata.png, gov-delete-dialog.png, gov-privacy.png.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, pid, thread, name = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_timeout(2500)
    # the organisation page: Your data
    page.evaluate("location.hash = '#/org'")
    page.wait_for_selector("text=Your data", timeout=20000)
    card = page.locator(".card", has=page.locator("h3", has_text="Your data"))
    out["yourdata_link"] = card.locator("a.btn").get_attribute("href")
    out["yourdata_text"] = card.inner_text()[:400]
    card.screenshot(path="/tmp/gov-yourdata.png")
    with page.expect_download() as dl:
        card.locator("a.btn").click()
    d = dl.value
    path = d.path()
    out["download_name"] = d.suggested_filename
    out["download_email_ok"] = json.loads(open(path, encoding="utf-8").read())["you"]["email"]
    # Ask Relay: delete the conversation
    page.evaluate(f"location.hash = '#/askd/{thread}'")
    page.wait_for_selector("text=Delete conversation", timeout=20000)
    page.click("text=Delete conversation")
    page.wait_for_selector(".modal.confirm", timeout=5000)
    page.click(".modal.confirm button.danger")
    page.wait_for_timeout(2500)
    out["askd_hash_after"] = page.evaluate("location.hash")
    out["askd_list_after"] = page.locator(".vlist").inner_text()[:300]
    # the dashboard: Delete, the confirm dialog, then gone
    page.evaluate(f"location.hash = '#/p/{pid}'")
    page.wait_for_selector(".phead button:has-text('Delete')", timeout=20000)
    page.click(".phead button:has-text('Delete')")
    page.wait_for_selector(".modal.confirm", timeout=5000)
    out["dialog_text"] = page.locator(".modal.confirm").inner_text()[:500]
    page.locator(".modal.confirm").screenshot(path="/tmp/gov-delete-dialog.png")
    page.click(".modal.confirm button.danger")
    page.wait_for_timeout(3000)
    out["dash_hash_after"] = page.evaluate("location.hash")
    out["dash_list_has_it"] = name in page.locator("#main").inner_text()
    # signed out: the sign-in page links the notice, which opens
    anon = b.new_context(viewport={"width": 1200, "height": 900})
    lp = anon.new_page()
    lp.goto("http://127.0.0.1:8000/login.html")
    out["login_privacy_link"] = lp.locator("#privacy a[href='privacy.html']").get_attribute("href")
    lp.click("#privacy a[href='privacy.html']")
    lp.wait_for_load_state("load")
    out["privacy_url"] = lp.url
    out["privacy_h1"] = lp.locator("h1").inner_text()
    lp.screenshot(path="/tmp/gov-privacy.png", full_page=False)
    b.close()
print(json.dumps(out))
"""

p = c.Person(f"una.ui@ui{c.STAMP}.com")
s, r = p.sign_in("UI Gov", "Una Ui")
c.check("ui: an organisation signs up", s == 200, (s, r))
s, d = c.new_dashboard(p)
c.check("ui: it makes a dashboard", s == 200 and isinstance(d, dict) and d.get("id"), (s, d))
pid, name = d["id"], d["name"]
g.wait_idle(p, pid)
tid = g.tenant_of(pid)
out = g.app(f"""
import json, time
from app import db
with db.use({tid!r}):
    uid = db.one("SELECT id FROM users WHERE email = ?", ({p.email!r},))["id"]
    db.run("INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES ('t-ui1', ?, ?, 'Sales by month?', ?, ?)",
           (uid, json.dumps({{"kind": "team"}}), time.time(), time.time()))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES ('q-ui1', 't-ui1', 'user', ?, ?)", (json.dumps({{"text": "Sales by month?"}}), time.time()))
print("ok")
""")
c.check("ui: a conversation is planted", out.endswith("ok"), out[-300:])
cookie = next(ck.value for ck in p.jar if ck.name == "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, pid, "t-ui1", name], input=PLAY, capture_output=True, text=True, timeout=240)
if res.returncode:
    c.check("ui: headless Chromium ran", False, res.stderr[-1500:])
else:
    o = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps(o, indent=1))
    c.check("ui: the organisation page has Your data with Download my data", o["yourdata_link"] == "/api/me/data" and "privacy notice" in o["yourdata_text"], o["yourdata_text"])
    c.check("ui: Download my data saves the person's own file", o["download_name"] == "d2d-relay-my-data.json" and o["download_email_ok"] == p.email, o)
    c.check("ui: Delete conversation asks, deletes, returns to Ask Relay", o["askd_hash_after"] == "#/askd" and "Sales by month?" not in o["askd_list_after"], o)
    c.check("ui: Delete on the dashboard asks first, saying what goes", "cannot be undone" in o["dialog_text"] and "14 days" in o["dialog_text"], o["dialog_text"])
    c.check("ui: after Delete the dashboards list opens without it", o["dash_hash_after"] == "#/d2d" and not o["dash_list_has_it"], o)
    c.check("ui: the sign-in page links the privacy notice, which opens", o["login_privacy_link"] == "privacy.html" and o["privacy_h1"] == "Privacy notice", o)
    for f in ("gov-yourdata.png", "gov-delete-dialog.png", "gov-privacy.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False)
s, r = p.get(f"/api/projects/{pid}")
c.check("ui: the dashboard is really gone (404)", s == 404, (s, r))
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
