"""Test stack only: item 34 (2026-11-12). The user: "default power bi built in visual first and the built in plus custom
if needed and last full custom, and name the AI model as Relay Model powered by Claude"; and, found while moving the
tests into the repo, the job runner's start-up sweep limited to its own stack.
- a new dashboard uses Power BI's built-in visuals unless it asks for mixed or relay (custom); older dashboards stay relay;
- the New dashboard form offers built-in, mixed, custom in that order, built-in chosen, Custom visuals off with it and
  back to its own choice when another is picked; the dashboard page's switch in the same order;
- the model is "Relay Model powered by Claude" in the model list, on a dashboard's Details tab and on Branding;
- the job runner removes only its own stack's job containers when it starts; another stack's are left alone.
Screenshots go to the run's folder (tests/out/<run>): item34-new.png, item34-details.png.
python -I -X utf8 item34_check.py <public> <admin>"""
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
RUNNER = os.environ.get("D2D_TEST_RUNNER", "d2d-relay-test-runner")
NAME = "Relay Model powered by Claude"


def docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def folder(pid: str) -> str:
    return g.sh(f"find /data/projects -maxdepth 3 -type d -name {pid} | head -1", "root")


def request_md(pid: str) -> str:
    return g.sh(f"cat {folder(pid)}/request.md")


def wait_failed(p, pid: str) -> dict:
    """The test stack has no Claude sign-in: the plan run fails at once and gives its credits back."""
    st = {}
    for _ in range(90):
        st = p.get(f"/api/projects/{pid}")[1] or {}
        if st.get("status") == "error":
            break
        time.sleep(2)
    return st


def dashboard(p, **form) -> tuple[str, dict]:
    s, d = p.form("/api/projects", {"prompt": "Sales by region and month", "data_mode": "upload", **form},
                  {"files": ("sales.csv", b"region,month,sales\nNorth,2026-01,10\nSouth,2026-01,12\n")})
    pid = (d or {}).get("id") if isinstance(d, dict) else None
    st = wait_failed(p, pid) if pid else {}
    return pid, st


# ---------------------------------------------------------------- the model's name
p = c.Person(f"vi.visuals@vis{c.STAMP}.com")
s, r = p.sign_in("Visuals Test", "Vi Visuals")
check("setup: an organisation signs up", s == 200, (s, r))
p.post("/api/me/tour", {"step": "done"})                 # the first-time tour and the organisation's setup (its last
p.post("/api/org/setup")                                 # step) stay out of the browser checks below
s, cat = p.get("/api/models")
models = (cat or {}).get("models") or []
check(f"model: the only model offered is called {NAME}", s == 200 and [(m.get("id"), m.get("label")) for m in models] == [("relay", NAME)],
      [(m.get("id"), m.get("label")) for m in models])
check("model: it is the default, and its note says it is powered by Claude", (cat or {}).get("default") == "relay"
      and "powered by Claude" in str((models[0] if models else {}).get("note")), ((cat or {}).get("default"), models[:1]))

# ---------------------------------------------------------------- which visuals a new dashboard uses
pid1, st1 = dashboard(p)
check("visuals: a new dashboard that names none uses Power BI's built-in visuals", st1.get("visuals_mode") == "builtin", st1.get("visuals_mode"))
check("visuals: with built-in only, no new custom visual is built", st1.get("custom_visuals") == "never", st1.get("custom_visuals"))
req = request_md(pid1)
check("visuals: the brief tells Relay so (request.md: Visuals: builtin)", "- Visuals: builtin" in req and "- Custom visuals: never" in req,
      [ln for ln in req.splitlines() if ln.startswith("- ")][-4:])
pid2, st2 = dashboard(p, visuals_mode="mixed")
check("visuals: built-in first with custom where needed is still offered (mixed)", st2.get("visuals_mode") == "mixed"
      and st2.get("custom_visuals") == "ask", (st2.get("visuals_mode"), st2.get("custom_visuals")))
pid3, st3 = dashboard(p, visuals_mode="relay")
check("visuals: Relay custom visuals are still offered (relay)", st3.get("visuals_mode") == "relay" and "- Visuals: relay" in request_md(pid3),
      st3.get("visuals_mode"))
s, r = p.form("/api/projects", {"prompt": "x", "data_mode": "upload", "visuals_mode": "fancy"}, {"files": ("a.csv", b"a,b\n1,2\n")})
check("visuals: anything else is refused (400)", s == 400, (s, r))
s, st = p.post(f"/api/projects/{pid1}/visuals", {"mode": "mixed"})
check("visuals: the dashboard page can switch built-in to mixed for the next versions", s == 200 and (st or {}).get("visuals_mode") == "mixed"
      and "- Visuals: mixed" in request_md(pid1), (s, (st or {}).get("visuals_mode")))
out = g.sh(f"python3 -c \"import json; p='{folder(pid2)}/project.json'; d=json.load(open(p)); d.pop('visuals_mode', None); "
           f"json.dump(d, open(p, 'w')); print('ok')\"")
s, st = p.get(f"/api/projects/{pid2}")
check("visuals: a dashboard from before the choice existed stays on Relay custom visuals", out.endswith("ok") and (st or {}).get("visuals_mode") == "relay",
      (out[-200:], (st or {}).get("visuals_mode")))

# ---------------------------------------------------------------- the screens
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, pid = sys.argv[1], sys.argv[2]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8000/#/new")
    page.wait_for_selector("select[aria-label='Visuals']", timeout=20000)
    page.wait_for_timeout(800)
    vis = page.locator("select[aria-label='Visuals']")
    cv = page.locator("label.f:has-text('Custom visuals') + select")
    out["options"] = vis.evaluate("s => [...s.options].map(o => [o.value, o.textContent])")
    out["chosen"] = vis.input_value()
    out["custom_builtin"] = [cv.input_value(), cv.is_disabled()]
    out["hint_builtin"] = vis.evaluate("s => s.nextElementSibling ? s.nextElementSibling.textContent : ''")
    page.locator(".sect:has(select[aria-label='Visuals'])").screenshot(path="/tmp/item34-new.png")
    vis.select_option("mixed")
    out["custom_mixed"] = [cv.input_value(), cv.is_disabled()]
    cv.select_option("auto")
    vis.select_option("builtin")
    out["custom_back_builtin"] = [cv.input_value(), cv.is_disabled()]
    vis.select_option("relay")
    out["custom_relay"] = [cv.input_value(), cv.is_disabled()]
    page.goto(f"http://127.0.0.1:8000/#/p/{pid}/details")
    page.wait_for_selector("dt:text-is('AI model')", timeout=20000)
    out["model_details"] = page.locator("dt:text-is('AI model') + dd").inner_text()
    sw = page.locator("select[aria-label='Visuals for the next versions']")
    out["switch_options"] = sw.evaluate("s => [...s.options].map(o => o.value)") if sw.count() else []
    page.screenshot(path="/tmp/item34-details.png", full_page=True)
    page.goto("http://127.0.0.1:8000/#/branding")
    page.wait_for_timeout(3000)
    out["branding"] = page.evaluate("document.body.innerText")
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
cookie = next(k.value for k in p.jar if k.name == "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, pid3], input=PLAY, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=240)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("ui: the browser checks ran", bool(o), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
if o:
    check("ui: New dashboard offers built-in, then mixed, then custom", [v for v, _ in o["options"]] == ["builtin", "mixed", "relay"], o["options"])
    check("ui: Power BI's built-in visuals are chosen by default", o["chosen"] == "builtin", o["chosen"])
    check("ui: with built-in, Custom visuals is off (only the available visuals)", o["custom_builtin"] == ["never", True], o["custom_builtin"])
    check("ui: built-in's note says nothing is embedded", "Nothing embedded" in o["hint_builtin"], o["hint_builtin"])
    check("ui: mixed turns Custom visuals back on, at its default (ask me)", o["custom_mixed"] == ["ask", False], o["custom_mixed"])
    check("ui: back to built-in turns it off again; custom remembers the choice made (auto)",
          o["custom_back_builtin"] == ["never", True] and o["custom_relay"] == ["auto", False], (o["custom_back_builtin"], o["custom_relay"]))
    check(f"ui: a dashboard's Details tab names the AI model {NAME}", o["model_details"].strip() == NAME, o["model_details"])
    check("ui: the dashboard page's Visuals switch is in the same order", o["switch_options"] == ["builtin", "mixed", "relay"], o["switch_options"])
    check(f"ui: Branding says {NAME} makes the palettes", f"{NAME} turns them into report palettes" in o["branding"], o["branding"][:300])
    check("ui: no script errors", not o["errors"], o["errors"])
for f in ("item34-new.png", "item34-details.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False)

# ---------------------------------------------------------------- the job runner sweeps only its own stack's jobs
code = docker("exec", RUNNER, "grep", "-c", "d2d-relay.web", "/opt/relay/bin/job-runner").stdout.strip()
fixed = code.isdigit() and int(code) > 0
check("sweep: the runner under test labels its jobs with its web container", fixed, code)
if fixed:                                    # an older runner would remove every job on the PC: never restarted here
    img = docker("inspect", "-f", "{{.Config.Image}}", c.WEB_C).stdout.strip()
    names = {k: f"d2d-relay-test-dummy-{k}-{c.STAMP}" for k in ("own", "legacy-own", "orphan", "other", "legacy-other")}
    gone = f"d2d-relay-test-dummy-gone-{c.STAMP}"

    def job(name: str, *extra: str) -> str:
        r = docker("create", "--name", name, "--label", "d2d-relay.job=1", "--label", "d2d-relay.cwd=/data/projects/dummy-x1",
                   *extra, "--entrypoint", "/bin/true", img)
        return r.stdout.strip() or r.stderr.strip()

    try:
        made = [job(names["own"], "--label", f"d2d-relay.web={c.WEB_C}", "--network", "none"),
                job(names["legacy-own"], "--network", f"container:{c.WEB_C}"),
                docker("create", "--name", gone, "--network", "none", "--entrypoint", "/bin/true", img).stdout.strip(),
                job(names["orphan"], "--network", f"container:{gone}"),
                job(names["other"], "--label", "d2d-relay.web=d2d-relay-other-web", "--network", "none"),
                job(names["legacy-other"], "--network", f"container:{c.ADMIN_C}")]
        docker("rm", gone)
        check("sweep: five stand-in jobs are set up (this stack's, older ones, an orphan, another stack's)",
              all(len(x) == 64 for x in made), [x[:80] for x in made])
        t = time.time()
        docker("restart", RUNNER)
        logs = ""
        for _ in range(60):
            r = docker("logs", "--since", str(int(t) - 2), RUNNER)
            logs = r.stdout + r.stderr
            if "[runner] serving on" in logs:
                break
            time.sleep(1)
        there = {k: bool(docker("ps", "-aq", "--filter", f"name=^/{n}$").stdout.strip()) for k, n in names.items()}
        check("sweep: this stack's job (labelled with its web container) is removed", not there["own"], there)
        check("sweep: an older job in this web container's network is removed", not there["legacy-own"], there)
        check("sweep: an older job whose network container is gone is removed", not there["orphan"], there)
        check("sweep: another stack's job is left alone (a live build is never stopped by a test stack)", there["other"], there)
        check("sweep: an older job in another container's network is left alone", there["legacy-other"], there)
        check("sweep: the runner's log says what it removed and what it left", f"removed a job left from before: {names['own']}" in logs
              and f"left another stack's job alone: {names['other']}" in logs, logs[-800:])
        health = ""
        for _ in range(40):
            health = docker("inspect", "-f", "{{.State.Health.Status}}", RUNNER).stdout.strip()
            if health == "healthy":
                break
            time.sleep(2)
        check("sweep: the runner is healthy again after its restart", health == "healthy", health)
    finally:
        docker("rm", "-f", *names.values(), gone)
check("sweep: no stand-in job is left", not docker("ps", "-aq", "--filter", "name=d2d-relay-test-dummy-").stdout.strip(),
      docker("ps", "-a", "--filter", "name=d2d-relay-test-dummy-", "--format", "{{.Names}}").stdout)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
