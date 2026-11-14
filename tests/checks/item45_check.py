"""Test stack only: item 45 (2026-11-14). The user, on a dashboard that said "1 job(s) ahead of this one": "Why to
public it shows other job details?". The shared agent serves every organisation one job at a time; what it does for
one organisation is not shown to another.
- a project's queue position counts only its own organisation's jobs (another one's running or waiting jobs never);
- /api/health: the queue is the organisation's own; the agent is "busy" for it only while its own job runs;
- a queued dashboard says "In the queue" and that it starts shortly, with no count of the jobs ahead;
- no Stop: the user, of the Stop button, "hide it everywhere, so customers can't stop a waiting or running build"
  (no button, and the API refuses with 403).
Screenshot: item45-queued.png in the run's folder.
python -I -X utf8 item45_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

check = c.check
a = c.Person(f"ana.queue@qa{c.STAMP}.com")
s1, _ = a.sign_in("Queue A", "Ana Queue")
b = c.Person(f"ben.queue@qb{c.STAMP}.com")
s2, _ = b.sign_in("Queue B", "Ben Queue")
ta = (a.get("/api/me")[1].get("org") or {}).get("id")
tb = (b.get("/api/me")[1].get("org") or {}).get("id")
check("setup: two organisations sign up", s1 == 200 and s2 == 200 and ta and tb and ta != tb, (s1, s2, ta, tb))

# ---------------------------------------------------------------- the queue as each organisation sees it
out = g.app(f"""
import asyncio, json
import httpx
from app import worker, main


class _Busy:                                   # the AI engine as it answers while it runs a job
    def json(self):
        return {{"ok": True, "busy": True}}


async def _busy_get(self, url, *args, **kwargs):
    return _Busy()


httpx.AsyncClient.get = _busy_get
A, B = {ta!r}, {tb!r}
rows = [{{"pid": "b-1", "tenant": B, "created": 1, "id": "j1"}}, {{"pid": "a-1", "tenant": A, "created": 2, "id": "j2"}},
        {{"pid": "b-2", "tenant": B, "created": 3, "id": "j3"}}, {{"pid": "a-2", "tenant": A, "created": 4, "id": "j4"}}]
worker._waiting_rows = lambda: rows            # B has a job running and two waiting; A has two waiting
dict.update(worker.current, pid="b-run", tenant=B, model="relay", owner="u-b", kind="build", job="j0")
res = {{}}
with _db.use(A):
    res["a"] = [worker.position("a-1"), worker.position("a-2"), worker.waiting_here()]
    h = asyncio.run(main.health())
    res["health_a"] = [h["agent"].get("busy"), h["queue"], h["running"]]
with _db.use(B):
    res["b"] = [worker.position("b-2"), worker.waiting_here()]
    h = asyncio.run(main.health())
    res["health_b"] = [h["agent"].get("busy"), h["queue"], h["running"]]
res["all"] = worker.waiting()
print(json.dumps(res))
""")
try:
    r = json.loads(out.strip().splitlines()[-1])
except (ValueError, IndexError):
    r = {}
check("queue: the stand-in queue was read (B running, B and A waiting)", bool(r) and r.get("all") == 4, out[-600:])
check("queue: A's first job has none of its own ahead (B's running and waiting jobs are not counted)", r.get("a", [None])[0] == 0, r.get("a"))
check("queue: A's second job has one ahead: A's first", r.get("a", [None, None])[1] == 1, r.get("a"))
check("queue: A counts its own two waiting jobs only", r.get("a", [None] * 3)[2] == 2, r.get("a"))
check("queue: B's second job has two of B's own ahead (its running job and its first)", r.get("b", [None])[0] == 2, r.get("b"))
check("health: while the agent runs B's job, A sees it not busy, its own queue of 2 and no running job named",
      r.get("health_a") == [False, 2, None], r.get("health_a"))
check("health: B sees the agent busy with its own job and its own queue of 2", r.get("health_b") == [True, 2, "b-run"], r.get("health_b"))

# ---------------------------------------------------------------- a queued dashboard's page
s, d = a.form("/api/projects", {"prompt": "Sales by region", "data_mode": "upload"}, {"files": ("sales.csv", b"region,sales\nNorth,10\n")})
pid = d.get("id") if isinstance(d, dict) and s == 200 else None
check("setup: A makes a dashboard", bool(pid), (s, d))
for _ in range(90):                            # its first run fails at once here and gives its credits back
    st = (a.get(f"/api/projects/{pid}")[1] or {}) if pid else {}
    if not pid or (st.get("status") == "error" and not (st.get("credits") or {}).get("used")):
        break
    time.sleep(2)
s, r = a.post(f"/api/projects/{pid}/stop") if pid else (0, None)
check("stop: a customer cannot stop a build (403), and is told it finishes on its own", s == 403
      and "finishes on its own" in str(c.detail_of(r)), (s, r))
PLAY = r"""
import json, sys, time
from playwright.sync_api import sync_playwright
cookie, pid, folder = sys.argv[1], sys.argv[2], sys.argv[3]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1300, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # stand in for a dashboard waiting its turn: queued, with a job the worker does not have (it stays queued)
    p = folder + "/project.json"
    d = json.load(open(p))
    d.update(status="queued", error=None, job={"kind": "plan", "id": "j-item45-standin"})
    json.dump(d, open(p, "w"))
    page.goto(f"http://127.0.0.1:8000/#/p/{pid}")
    page.wait_for_selector(".banner.run, .box.run, #btext", timeout=20000)
    page.wait_for_timeout(1500)
    out["text"] = page.evaluate("document.body.innerText")
    out["stop_buttons"] = page.locator("button:text-is('Stop')").count()
    page.screenshot(path="/tmp/item45-queued.png", full_page=False)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
folder = g.sh(f"find /data/projects -maxdepth 3 -type d -name {pid} | head -1", "root") if pid else ""
cookie = next(k.value for k in a.jar if k.name == "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, pid or "", folder], input=PLAY, capture_output=True,
                     text=True, encoding="utf-8", errors="replace", timeout=240)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("ui: the browser check ran", bool(o), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
if o:
    t = o["text"]
    check("ui: a queued dashboard says In the queue and that it starts shortly", "In the queue" in t
          and "It starts shortly. You can leave this page; it keeps its place." in t, t[:600])
    check("ui: ... with no count of the jobs ahead and no 'waiting for the agent'", "ahead of this one" not in t and "Waiting for the agent" not in t, t[:600])
    check("ui: ... and no Stop button", o.get("stop_buttons") == 0, o.get("stop_buttons"))
    check("ui: no script errors", not o["errors"], o["errors"])
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item45-queued.png", c.out_path("item45-queued.png")], check=False)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
