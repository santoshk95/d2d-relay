"""Test stack only, end to end with real Claude: one dashboard in each Visuals mode, in the order the New dashboard form
offers them (item 34): Power BI's built-in visuals, built-in first with custom where needed, Relay custom visuals.
Each is planned and built by real Claude in job containers, approved, published through Power BI's own engine (the DAX
check) and made into a .pbix by this PC's Power BI file maker; then what each report is made of is checked, in its
definition and inside the .pbix.

Needs (tests/README.md, "End to end with real Claude"):
  - the stack started with live's Claude sign-in: TEST_CLAUDE_VOLUME=claude-api-auth TEST_CLAUDE_EXTERNAL=true;
  - the test stack's own DAX checker and file maker: tests/stack/helpers.ps1 start (never live's).
python -I -X utf8 visuals_e2e_check.py <public> <admin> [builtin,mixed,relay]
Afterwards delete the test runs' transcripts from the sign-in volume (the command is printed at the end)."""
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

MODES = (sys.argv[3] if len(sys.argv) > 3 else "builtin,mixed,relay").split(",")
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

check = c.check
NATIVE = {"slicer", "textbox", "pageNavigator", "table"}          # what the builder writes as Power BI's own visuals
LABEL = {"builtin": "Power BI's built-in visuals", "mixed": "Built-in first, custom where needed", "relay": "Relay custom visuals"}
PROMPT = ("Sales performance for the leadership team: revenue, gross margin and units by month, region, product category "
          "and channel; show where we grow, where we fall behind plan, and which products drive the margin.")


def sales_csv() -> bytes:
    """704 rows of made-up sales (22 months x 4 regions x 4 categories x 2 channels), the same every run."""
    rows = ["month,region,category,channel,units,revenue,cost"]
    regions = {"North": 1.15, "South": 0.9, "East": 1.0, "West": 1.25}
    cats = {"Bikes": (950.0, 0.62), "Accessories": (45.0, 0.38), "Clothing": (60.0, 0.45), "Components": (180.0, 0.55)}
    for m in range(22):
        y, mo = 2025 + (m // 12), m % 12 + 1
        season = 1 + 0.25 * [0, 0.1, 0.3, 0.6, 0.9, 1, 0.8, 0.6, 0.3, 0.1, 0.4, 0.9][mo - 1]
        for r, rf in regions.items():
            for cat, (price, cost_share) in cats.items():
                for ch, cf in (("Online", 0.8 + 0.02 * m), ("Retail", 1.2 - 0.01 * m)):
                    units = int(40 * rf * cf * season * (1 + ((m * 7 + len(r) * 3 + len(cat)) % 11) / 20))
                    revenue = round(units * price * (0.97 if ch == "Online" else 1.0), 2)
                    rows.append(f"{y}-{mo:02d},{r},{cat},{ch},{units},{revenue},{round(revenue * cost_share, 2)}")
    return ("\n".join(rows) + "\n").encode()


def in_web(cmd: str, user: str = "root") -> str:
    return g.sh(cmd, user)


def visual_types(pid: str, v: int) -> list[str]:
    folder = in_web(f"find /data/projects -maxdepth 3 -type d -name {pid} | head -1")
    code = ("import json, sys\nsys.path[:0] = ['/srv', '/opt/genbi']\nfrom genbi_kit import definition\n"
            f"raw = definition.load('{folder}/versions/v{v}/definition.yaml')\ntypes = []\n"
            "for pg in raw.get('pages') or []:\n"
            "    types += [x.get('type') for row in pg.get('rows') or [] for x in row.get('visuals') or []]\n"
            "    types += [x.get('type') for x in pg.get('visuals') or []]\n"
            "print(json.dumps(types))\n")
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", c.WEB_C, "/usr/local/bin/python3", "-P", "-"], input=code,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return ["<unreadable: " + (r.stderr or r.stdout)[-200:] + ">"]


def builtin_type(t: str) -> bool:
    return str(t).startswith("pbi.") or t in NATIVE


LABELS = r"""
import json, re, sys
from playwright.sync_api import sync_playwright
cookie, pid = sys.argv[1], sys.argv[2]
out = {"pages": 0, "overflow": [], "zeros": []}
ZERO = re.compile(r"^[+-]?[^0-9\s]{0,3}0*(\.0+)?\s?(K|M|bn|B|T)$")          # "$0M", "+$M": a value shown as nothing
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.goto(f"http://127.0.0.1:8000/api/projects/{pid}/prototype/live")
    page.wait_for_timeout(3000)
    n = page.evaluate("R.pages.length")
    for i in range(n):
        page.evaluate(f"current = {i}; draw();")
        page.wait_for_timeout(1500)
        found = page.evaluate('''() => {
          const vs = R.pages[current].visuals, boxes = [...document.querySelectorAll('#page > .v')], over = [], zeros = [];
          boxes.forEach((box, k) => { const v = vs[k]; if (!v || !(v.stock || v.atlas)) return;
            const r = box.getBoundingClientRect();
            box.querySelectorAll('svg text').forEach(t => { const q = t.getBoundingClientRect(); if (!q.width) return;
              const o = Math.max(q.right - r.right, r.left - q.left, q.bottom - r.bottom, r.top - q.top);
              if (o > 1) over.push([R.pages[current].name, v.id, t.textContent, Math.round(o)]); });
            if (v.atlas) box.querySelectorAll('text.lbl').forEach(t => zeros.push([R.pages[current].name, v.id, t.textContent])); });
          return {over, zeros}; }''')
        out["overflow"] += found["over"]
        out["zeros"] += [z for z in found["zeros"] if ZERO.match(z[2].strip())]
        out["pages"] += 1
    b.close()
print(json.dumps(out))
"""


def labels_of(p, pid: str) -> dict:
    """Every page of the dashboard's prototype in Chromium: labels past their visual's edge, Atlas labels shown as nothing."""
    cookie = next(k.value for k in p.jar if k.name == "d2d_session")
    r = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, pid], input=LABELS, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (r.stderr or r.stdout)[-400:]}


def download(p, pid: str) -> bytes:
    req = urllib.request.Request(p.base + f"/api/projects/{pid}/download")
    with p.http.open(req, timeout=300) as r:
        return r.read()


# ---------------------------------------------------------------- what the run needs
def beat(queue: str) -> str:
    return in_web(f"cat /data/projects/{queue}/heartbeat.json 2>/dev/null").lstrip("﻿").strip()


def fresh(queue: str) -> bool:
    """A helper on this PC is alive when its heartbeat (written every few seconds) is under a minute old."""
    try:
        return time.time() - float(json.loads(beat(queue)).get("time", 0)) < 60
    except (ValueError, AttributeError):
        return False


check("needs: the test stack's DAX checker is running (tests/stack/helpers.ps1 start)", fresh(".daxcheck"), beat(".daxcheck")[:200])
check("needs: the test stack's Power BI file maker is running (tests/stack/helpers.ps1 start)", fresh(".pbix"), beat(".pbix")[:200])
signin = in_web("test -s /home/agent/.claude/.credentials.json && echo yes || echo no")
check("needs: the stack has a Claude sign-in (TEST_CLAUDE_VOLUME=claude-api-auth, TEST_CLAUDE_EXTERNAL=true)", signin == "yes", signin)
if not all(ok for _, ok in c.RESULTS):
    print("\nnot started: see above")
    sys.exit(1)
review = in_web("printenv RELAY_CREDITS_START_REVIEW")
os.environ.setdefault("D2D_TEST_APPROVE_START", "1" if review != "0" else "0")

# ---------------------------------------------------------------- an organisation with credits for three dashboards
p = c.Person(f"eve.e2e@e2e{c.STAMP}.com")
s, r = p.sign_in("End To End", "Eve E2E")
check("setup: an organisation signs up", s == 200, (s, r))
p.post("/api/me/tour", {"step": "done"})
p.post("/api/org/setup")
s, r = p.post("/api/org/credit-request", {"credits": 100, "message": "end-to-end test"})
rid = ((r or {}).get("request") or {}).get("id")
adm = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s2, r2 = adm.post(f"/api/admin/requests/{rid}/approve", {"credits": 100}) if rid else (0, r)
credits = (p.get("/api/me")[1].get("org") or {}).get("credits")
check("setup: PASDACS approves 100 more credits (three dashboards use 75)", s2 == 200 and (credits or 0) >= 25 * len(MODES), (s, r, s2, credits))
tid = g.sql(f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = 'e2e{c.STAMP}.com'")

data = sales_csv()
runs = {}
for mode in MODES:
    s, d = p.form("/api/projects", {"name": f"{LABEL[mode]} {c.STAMP}", "prompt": PROMPT, "data_mode": "upload", "visuals_mode": mode},
                  {"files": ("sales.csv", data)})
    pid = (d or {}).get("id") if isinstance(d, dict) else None
    check(f"{mode}: the dashboard is made with Visuals {mode}; Relay starts planning", s == 200 and pid and d.get("visuals_mode") == mode,
          (s, str(d)[:200]))
    runs[mode] = {"pid": pid, "t0": time.time(), "steps": {}, "status": "", "error": ""}

# ---------------------------------------------------------------- plan -> KPIs -> build -> approve -> publish -> .pbix
end = time.time() + 120 * 60
while time.time() < end:
    busy = False
    for mode, run in runs.items():
        if not run["pid"] or run["status"] in ("done", "error"):
            continue
        busy = True
        st = p.get(f"/api/projects/{run['pid']}")[1] or {}
        status = st.get("status") or ""
        if status == "awaiting_kpis" and "plan" not in run["steps"]:
            run["steps"]["plan"] = round((time.time() - run["t0"]) / 60, 1)
            kpis = (st.get("plan") or {}).get("kpis") or []
            run["kpis"] = len(kpis)
            s, r = p.form(f"/api/projects/{run['pid']}/kpis", {"payload": json.dumps({"action": "confirm", "kpis": kpis, "feedback": ""})})
            run["confirmed"] = s == 200
            print(f"  {mode}: planned in {run['steps']['plan']} min, {len(kpis)} KPIs confirmed ({s})", flush=True)
        elif status == "awaiting_review" and "build" not in run["steps"]:
            run["steps"]["build"] = round((time.time() - run["t0"]) / 60, 1)
            v = (st.get("versions") or [{}])[-1]
            run["v"], run["gates"] = v.get("v"), {x.get("id"): x.get("status") for x in v.get("gates") or []}
            s, r = p.post(f"/api/projects/{run['pid']}/approve", {"version": run["v"]})
            run["approved"] = s == 200
            run["approve_answer"] = "" if s == 200 else str(r)[:300]
            print(f"  {mode}: built v{run['v']} at {run['steps']['build']} min; gates {run['gates']}; approved ({s})", flush=True)
            if s != 200:
                run["status"], run["error"] = "error", f"approve refused: {str(r)[:300]}"
        elif status == "done" and run.get("approved"):
            run["steps"]["published"] = round((time.time() - run["t0"]) / 60, 1)
            run["status"], run["output"] = "done", st.get("output") or {}
            print(f"  {mode}: published with its .pbix at {run['steps']['published']} min", flush=True)
        elif status == "error":
            run["status"], run["error"] = "error", (st.get("error") or "")[:500]
            print(f"  {mode}: stopped: {run['error'][:300]}", flush=True)
    if not busy:
        break
    time.sleep(10)

# ---------------------------------------------------------------- what each report is made of
summary = []
for mode, run in runs.items():
    pid = run["pid"]
    check(f"{mode}: Real Claude planned it and the KPIs were confirmed", run.get("confirmed") is True and run.get("kpis", 0) > 0,
          (run["steps"], run.get("kpis"), run["error"][:200]))
    check(f"{mode}: Real Claude built it; no review gate failed", "build" in run["steps"] and "fail" not in run.get("gates", {}).values(),
          (run.get("gates"), run["error"][:200]))
    check(f"{mode}: approved, published through Power BI's engine and made into a .pbix", run["status"] == "done",
          (run["status"], run["error"][:400]))
    types = visual_types(pid, run["v"]) if run.get("v") else []
    builtin = [t for t in types if builtin_type(t)]
    custom = [t for t in types if not builtin_type(t)]
    run["types"] = types
    if mode == "builtin":
        check("builtin: every visual is one of Power BI's own", types and not custom, types)
    elif mode == "mixed":
        check("mixed: Power BI's own visuals come first (most of the report), custom only where needed",
              types and len(builtin) >= len(custom), {"builtin": len(builtin), "custom": sorted(set(custom))})
    else:
        check("relay: the report uses Relay custom visuals", bool(custom), types)
    out = run.get("output") or {}
    dax = out.get("dax") or {}
    check(f"{mode}: Power BI's engine checked its DAX (measures and visual queries) before it was published",
          dax.get("checked") is True and (dax.get("measures") or 0) > 0, dax)
    embedded = None
    if run["status"] == "done":
        try:
            z = zipfile.ZipFile(io.BytesIO(download(p, pid)))
            pbix_name = next(n for n in z.namelist() if n.endswith(".pbix"))
            inner = zipfile.ZipFile(io.BytesIO(z.read(pbix_name)))
            embedded = sorted({n.split("/")[2] for n in inner.namelist() if n.startswith("Report/CustomVisuals/") and n.count("/") >= 3})
            check(f"{mode}: the download holds the .pbix ({pbix_name}, {round(z.getinfo(pbix_name).file_size / 1048576, 1)} MB)", True)
        except Exception as e:  # noqa: BLE001 - reported as a failure
            check(f"{mode}: the download holds the .pbix", False, repr(e))
    if embedded is not None:
        if mode == "builtin":
            check("builtin: the .pbix embeds no custom visual", not embedded, embedded)
        elif mode == "relay":
            check("relay: the .pbix embeds the Relay custom visuals it uses", bool(embedded), embedded)
        else:
            print(f"  mixed: custom visuals embedded in the .pbix: {embedded or 'none'}", flush=True)
    summary.append((mode, run["steps"], len(types), len(builtin), sorted(set(custom)), embedded))
    if run["status"] == "done":
        lab = labels_of(p, pid)
        check(f"{mode}: no label in the report runs past its visual's edge ({lab.get('pages', 0)} pages)",
              bool(lab.get("pages")) and not lab.get("overflow"), lab.get("overflow", lab)[:8] if isinstance(lab.get("overflow", lab), list) else lab)
        check(f"{mode}: no data label of a Relay visual reads $0M or a unit without a number",
              bool(lab.get("pages")) and not lab.get("zeros"), lab.get("zeros"))

print("\nmode     minutes (plan/build/published)  visuals  built-in  custom types  embedded in the .pbix")
for mode, steps, n, nb, cu, emb in summary:
    print(f"{mode:8} {str(steps.get('plan'))}/{str(steps.get('build'))}/{str(steps.get('published')):26} {n:7}  {nb:8}  {cu}  {emb}")
print(f"\nTranscripts to delete afterwards (organisation {tid}):\n  MSYS_NO_PATHCONV=1 docker run --rm -v claude-api-auth:/c "
      f"--entrypoint /bin/sh <image> -c 'cd /c/projects && rm -rf -- ./-data-projects--tenants-{tid}-*'")
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
