"""Test stack only: the review of commit 4c595c9 (Ask D is Ask Relay everywhere), as its note in docs/LOG.md asks: the
Ask Relay page, and a dashboard's change request from a question. python -I -X utf8 rename_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check


def app_py(code: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=code, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return (r.stdout + r.stderr).strip()


p = c.Person(f"rae.rename@ren{c.STAMP}.com")
s, r = p.sign_in("Rename Review", "Rae Rename")
check("setup: an organisation signs up", s == 200, (s, r))
s, reg = p.get("/api/registry")
text = json.dumps(reg)
check("rename: the module catalogue never says Ask D (D2D Relay reaches Ask Relay from its sidebar, not the catalogue)",
      s == 200 and "Ask D " not in text and "Ask D-" not in text and '"Ask D"' not in text, [m.get("id") for m in (reg or {}).get("modules", [])])

# the Ask Relay page in a browser
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1300, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": sys.argv[1], "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.goto("http://127.0.0.1:8000/#/askd")
    page.wait_for_timeout(4000)
    body = page.evaluate("document.body.innerText")
    page.screenshot(path="/tmp/askrelay-page.png")
    print(json.dumps({"hash": page.evaluate("location.hash"), "ask_relay": "Ask Relay" in body, "ask_d": "Ask D " in body or "Ask D\n" in body,
                      "title": page.title()}))
    b.close()
"""
cookie = next(k.value for k in p.jar if k.name == "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie], input=PLAY, capture_output=True, text=True,
                     encoding="utf-8", timeout=180)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
check("rename: the Ask Relay page says Ask Relay, never Ask D", o.get("hash") == "#/askd" and o.get("ask_relay") and not o.get("ask_d"),
      (o, res.stderr[-400:]))
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/askrelay-page.png", c.out_path("askrelay-page.png")], check=False)

# a dashboard's change request from a question: a dashboard with a version (planted: the test stack has no AI) and an answer
s, d = c.new_dashboard(p)
pid = (d or {}).get("id")
check("setup: a dashboard is made", s == 200 and pid, (s, str(d)[:150]))
for _ in range(90):
    if (p.get(f"/api/projects/{pid}")[1] or {}).get("status") == "error":
        break
    time.sleep(2)
tid = subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-At", "-h", "/run/postgresql", "-d", "relay", "-c",
                      f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = 'ren{c.STAMP}.com'"], capture_output=True, text=True).stdout.strip()
out = app_py(f"""
import json, time
from app import db, store
db.init()
with db.use({tid!r}):
    st = store.load({pid!r})
    st["status"] = "awaiting_review"
    st["versions"] = [{{"v": 1, "when": time.time(), "summary": "first version"}}]
    store.save(st)
    uid = db.one("SELECT id FROM users WHERE email = ?", ({p.email!r},))["id"]
    now = time.time()
    db.run("INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES ('t-ren1', ?, ?, 'Sales by region?', ?, ?)",
           (uid, json.dumps({{"kind": "project", "id": {pid!r}}}), now, now))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES ('q-ren1', 't-ren1', 'user', ?, ?)",
           (json.dumps({{"text": "Sales by region?"}}), now))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES ('a-ren1', 't-ren1', 'assistant', ?, ?)",
           (json.dumps({{"summary": "North sold the most.", "result": {{"type": "table", "headline": "North leads"}},
                         "validation": {{"queries": [], "main_query": None}}}}), now + 1))
print("planted")
""")
check("setup: a version and an answer are planted", out.endswith("planted"), out[-300:])
s, r = p.post("/api/askd/messages/a-ren1/to-dashboard", {"project": pid})
check("rename: the answer goes to the dashboard as a change request", s == 200 and r.get("ok"), (s, r))
s, req = p.get(f"/api/projects/{pid}/files/request.md")
req = req if isinstance(req, str) else json.dumps(req)
check("rename: the dashboard's request says Change request (from Ask Relay) and what Ask Relay found",
      "## Change request (from Ask Relay)" in req and "Ask Relay found: North sold the most." in req and "Ask D" not in req, req[-400:])
s, acts = p.get(f"/api/projects/{pid}/activity")
acts = acts if isinstance(acts, list) else (acts or {}).get("events", acts)
texts = [e.get("text", "") for e in acts] if isinstance(acts, list) else []
check("rename: its activity says From Ask Relay: <the question>", any(t == "From Ask Relay: Sales by region?" for t in texts), texts[-5:])

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
