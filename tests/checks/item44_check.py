"""Test stack only: item 44 (2026-11-14). The user: "25 credits in dashboard is for default visual and 50 credits for
custom visuals (fully custom / default plus custom)".
- the prices: 25 for a new dashboard of Power BI's built-in visuals only, 50 with custom visuals (mixed or relay);
- not enough credits for custom visuals: refused (402) before anything is saved, while built-in still fits;
- a built-in dashboard moved to custom visuals pays the difference (25) once; moving back and forth again is free; a
  custom one moved to built-in and back pays nothing; too few credits for the difference: refused, nothing changes;
- dashboards from before item 44 keep what they had (custom ones count as paid, built-in ones pay the difference);
- Retry after a failed run charges what the failed run's charge was (50 for custom visuals);
- the screens: the New dashboard form's choices carry their credits and its "Uses" line follows the choice, the
  Organisation page and a dashboard's Credits card give both prices, the Visuals switch says what custom visuals add.
The test stack has no Claude sign-in, so every first run fails at once and gives its credits back.
Screenshots go to the run's folder (tests/out/<run>): item44-new.png, item44-details.png.
python -I -X utf8 item44_check.py <public> <admin>"""
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
p = c.Person(f"pia.prices@price{c.STAMP}.com")
s, r = p.sign_in("Prices Test", "Pia Prices")
check("setup: an organisation signs up", s == 200, (s, r))
p.post("/api/me/tour", {"step": "done"})
p.post("/api/org/setup")
org = p.get("/api/me")[1].get("org") or {}
admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)


def balance() -> int:
    return (p.get("/api/me")[1].get("org") or {}).get("credits") or 0


def set_balance(n: int) -> bool:
    s, _ = admin.post(f"/api/admin/orgs/{org.get('id')}/credits", {"credits": n - balance(), "note": f"item 44 check: {n}"})
    return s == 200 and balance() == n


def ledger() -> list[dict]:
    return p.get("/api/org")[1].get("ledger", [])


def charges(pid: str, what: str | None = None) -> list[dict]:
    return [x for x in ledger() if x.get("project_id") == pid and x["kind"] == "charge" and (what is None or x["what"] == what)]


def folder(pid: str) -> str:
    return g.sh(f"find /data/projects -maxdepth 3 -type d -name {pid} | head -1", "root")


def settled(pid: str) -> dict:
    """The first run fails at once here and gives its credits back; the status turns to error a moment before the
    refund, so wait for both."""
    st = {}
    for _ in range(90):
        st = p.get(f"/api/projects/{pid}")[1] or {}
        if st.get("status") == "error" and not (st.get("credits") or {}).get("used"):
            break
        time.sleep(2)
    return st


def dashboard(**form) -> tuple[int, dict, str | None]:
    s, d = p.form("/api/projects", {"prompt": "Sales by region and month", "data_mode": "upload", **form},
                  {"files": ("sales.csv", b"region,month,sales\nNorth,2026-01,10\nSouth,2026-01,12\n")})
    pid = d.get("id") if isinstance(d, dict) and s == 200 else None
    if pid:
        settled(pid)
    return s, d, pid


def switch(pid: str, mode: str) -> tuple[int, dict]:
    return p.post(f"/api/projects/{pid}/visuals", {"mode": mode})


def legacy(pid: str, mode: str) -> str:
    """Make a dashboard look like one from before item 44: no custom_paid, the visuals given."""
    return g.sh(f"python3 -c \"import json; p='{folder(pid)}/project.json'; d=json.load(open(p)); d.pop('custom_paid', None); "
                f"d['visuals_mode']='{mode}'; json.dump(d, open(p, 'w')); print('ok')\"")


# ---------------------------------------------------------------- the prices
costs = org.get("costs") or {}
check("prices: 25 for a dashboard of built-in visuals, 50 with custom visuals", costs.get("dashboard") == 25 and costs.get("dashboard_custom") == 50, costs)
check("setup: PASDACS gives the organisation 200 credits", set_balance(200), balance())

s, d, pb = dashboard()
check("built-in: a dashboard that names no visuals is built-in and charged 25", s == 200 and pb and (d or {}).get("visuals_mode") == "builtin"
      and [x["delta"] for x in charges(pb, "dashboard")] == [-25], (s, charges(pb) if pb else d))
st = p.get(f"/api/projects/{pb}")[1] if pb else {}
check("built-in: it has not paid for custom visuals; moving to them would use 25 more", st.get("custom_paid") is False
      and (st.get("credits") or {}).get("custom_extra") == 25, (st.get("custom_paid"), (st.get("credits") or {}).get("custom_extra")))
s, d, pm = dashboard(visuals_mode="mixed")
mc = charges(pm, "dashboard") if pm else []
check("custom: built-in first with custom where needed (mixed) is charged 50, noted as custom visuals",
      s == 200 and pm and [x["delta"] for x in mc] == [-50] and mc[0].get("note") == "custom visuals", (s, mc or d))
s, d, pr = dashboard(visuals_mode="relay")
check("custom: Relay custom visuals (relay) are charged 50", s == 200 and pr and [x["delta"] for x in charges(pr, "dashboard")] == [-50],
      (s, charges(pr) if pr else d))
st = p.get(f"/api/projects/{pr}")[1] if pr else {}
check("custom: a custom dashboard has paid; nothing more to move", st.get("custom_paid") is True and (st.get("credits") or {}).get("custom_extra") == 0,
      (st.get("custom_paid"), (st.get("credits") or {}).get("custom_extra")))
check("refunds: every failed first run gave its credits back (balance 200 again)", balance() == 200, balance())

# ---------------------------------------------------------------- not enough credits
n_before = len(p.get("/api/projects")[1] or [])
check("setup: the organisation is left 30 credits", set_balance(30), balance())
s, r = p.form("/api/projects", {"prompt": "Sales by region", "data_mode": "upload", "visuals_mode": "relay"},
              {"files": ("sales.csv", b"region,sales\nNorth,10\n")})
check("short: with 30 credits custom visuals are refused (402), saying they use 50", s == 402
      and "A new dashboard with custom visuals uses 50 credits" in str(c.detail_of(r)), (s, r))
check("short: ... and nothing is saved", len(p.get("/api/projects")[1] or []) == n_before, n_before)
s, d, pb2 = dashboard()
check("short: ... while a built-in dashboard still fits (25 of the 30)", s == 200 and pb2 and [x["delta"] for x in charges(pb2, "dashboard")] == [-25],
      (s, d))

# ---------------------------------------------------------------- moving between built-in and custom visuals
check("setup: back to 200 credits", set_balance(200), balance())
s, st = switch(pb, "mixed")
vc = charges(pb, "visuals") if pb else []
check("switch: built-in to mixed pays the difference, 25, once", s == 200 and (st or {}).get("visuals_mode") == "mixed"
      and [x["delta"] for x in vc] == [-25] and "switched to" in str(vc[0].get("note")) and balance() == 175, (s, vc, balance()))
check("switch: ... and the dashboard has now paid for custom visuals", (st or {}).get("custom_paid") is True
      and ((st or {}).get("credits") or {}).get("custom_extra") == 0, ((st or {}).get("custom_paid"), (st or {}).get("credits")))
s1, st1 = switch(pb, "builtin")
s2, st2 = switch(pb, "relay")
check("switch: back to built-in and on to relay costs nothing more", s1 == 200 and s2 == 200 and (st2 or {}).get("visuals_mode") == "relay"
      and len(charges(pb, "visuals")) == 1 and balance() == 175, (s1, s2, charges(pb, "visuals"), balance()))
s1, _ = switch(pm, "builtin")
s2, st2 = switch(pm, "relay")
check("switch: a custom dashboard moved to built-in and back pays nothing", s1 == 200 and s2 == 200 and (st2 or {}).get("visuals_mode") == "relay"
      and not charges(pm, "visuals") and balance() == 175, (s1, s2, charges(pm, "visuals"), balance()))
check("setup: the organisation is left 10 credits", set_balance(10), balance())
s, r = switch(pb2, "relay")
st = p.get(f"/api/projects/{pb2}")[1] if pb2 else {}
check("switch: with 10 credits moving to custom visuals is refused (402), saying it uses 25 more", s == 402
      and "Custom visuals on this dashboard use 25 more credits" in str(c.detail_of(r)), (s, r))
check("switch: ... and nothing changes: still built-in, nothing charged", st.get("visuals_mode") == "builtin" and not charges(pb2, "visuals")
      and balance() == 10, (st.get("visuals_mode"), charges(pb2, "visuals"), balance()))

# ---------------------------------------------------------------- dashboards from before item 44
check("setup: back to 200 credits for the older dashboards", set_balance(200), balance())
out = legacy(pr, "relay")
st = p.get(f"/api/projects/{pr}")[1] if pr else {}
check("older: one on custom visuals counts as paid", out.endswith("ok") and st.get("custom_paid") is True
      and (st.get("credits") or {}).get("custom_extra") == 0, (out[-200:], st.get("custom_paid")))
s1, _ = switch(pr, "builtin")
s2, _ = switch(pr, "mixed")
check("older: ... and moves to built-in and back for nothing", s1 == 200 and s2 == 200 and not charges(pr, "visuals") and balance() == 200,
      (s1, s2, charges(pr, "visuals"), balance()))
out = legacy(pm, "builtin")
st = p.get(f"/api/projects/{pm}")[1] if pm else {}
check("older: one on built-in visuals would pay the difference", out.endswith("ok") and st.get("custom_paid") is False
      and (st.get("credits") or {}).get("custom_extra") == 25, (out[-200:], st.get("custom_paid")))
s, _ = switch(pm, "relay")
check("older: ... and pays 25 when it moves to custom visuals", s == 200 and [x["delta"] for x in charges(pm, "visuals")] == [-25]
      and balance() == 175, (s, charges(pm, "visuals"), balance()))

# ---------------------------------------------------------------- Retry charges what the failed run's charge was
s, d, pc = dashboard(visuals_mode="relay")
st = p.get(f"/api/projects/{pc}")[1] if pc else {}
check("retry: a failed custom dashboard says Retry uses 50", pc and (st.get("credits") or {}).get("retry") == 50, (st.get("status"), st.get("credits")))
s, r = p.post(f"/api/projects/{pc}/retry", {}) if pc else (0, None)
settled(pc) if pc else None
check("retry: ... and Retry charges 50 again (then gives them back here)", s == 200 and [x["delta"] for x in charges(pc, "dashboard")] == [-50, -50]
      and balance() == 175, (s, charges(pc), balance()))
s, d, pd = dashboard()
s, r = p.post(f"/api/projects/{pd}/retry", {}) if pd else (0, None)
settled(pd) if pd else None
check("retry: a built-in one's Retry charges 25", s == 200 and [x["delta"] for x in charges(pd, "dashboard")] == [-25, -25], (s, charges(pd) if pd else d))

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
    out["options"] = vis.evaluate("s => [...s.options].map(o => [o.value, o.textContent])")
    out["use_builtin"] = page.locator("b.useline").inner_text()
    vis.select_option("mixed")
    out["use_mixed"] = page.locator("b.useline").inner_text()
    page.locator(".sect:has(select[aria-label='Visuals'])").screenshot(path="/tmp/item44-new.png")
    page.goto("http://127.0.0.1:8000/#/org")
    page.wait_for_selector("dt:text-is('New dashboard')", timeout=20000)
    out["org_new"] = page.locator("dt:text-is('New dashboard') + dd").inner_text()
    page.goto(f"http://127.0.0.1:8000/#/p/{pid}/details")
    page.wait_for_selector("select[aria-label='Visuals for the next versions']", timeout=20000)
    page.wait_for_timeout(500)
    sw = page.locator("select[aria-label='Visuals for the next versions']")
    out["switch"] = sw.evaluate("s => [...s.options].map(o => [o.value, o.textContent])")
    out["switch_hint"] = sw.evaluate("s => s.nextElementSibling ? s.nextElementSibling.textContent : ''")
    out["credits_card"] = page.locator(".card:has(h3:text-is('Credits'))").first.inner_text()
    page.screenshot(path="/tmp/item44-details.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
cookie = next(k.value for k in p.jar if k.name == "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, pb2 or ""], input=PLAY, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=240)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("ui: the browser checks ran", bool(o), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
if o:
    check("ui: New dashboard's choices carry their credits", o["options"] == [["builtin", "Power BI's built-in visuals only (25 credits)"],
          ["mixed", "Built-in first, custom where needed (50 credits)"], ["relay", "Relay custom visuals (50 credits)"]], o["options"])
    check("ui: its Uses line says 25 for built-in and 50 once mixed is picked", o["use_builtin"].startswith("Uses 25 credits")
          and o["use_mixed"].startswith("Uses 50 credits"), (o["use_builtin"], o["use_mixed"]))
    check("ui: the Organisation page gives both prices", "25 credits with Power BI's built-in visuals" in o["org_new"]
          and "50 credits with custom visuals" in o["org_new"], o["org_new"])
    check("ui: a built-in dashboard's Visuals switch says custom visuals use 25 more credits",
          [t for v, t in o["switch"] if v != "builtin" and "(25 more credits)" in t] and all("more credits" not in t for v, t in o["switch"] if v == "builtin")
          and "Custom visuals use 25 more credits on this dashboard, once." in o["switch_hint"], (o["switch"], o["switch_hint"]))
    check("ui: its Credits card gives both prices", "A new dashboard uses 25 with Power BI's built-in visuals or 50 with custom visuals" in o["credits_card"],
          o["credits_card"][:300])
    check("ui: no script errors", not o["errors"], o["errors"])
for f in ("item44-new.png", "item44-details.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
