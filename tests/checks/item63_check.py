"""Test stack only: item 63 (the user, 2026-11-19: "each kpi can be fixed or change by natural language as well each 1
credit"). A KPI changed in plain words (webapp/app/kpi_words.py), in two places:
- a dashboard's plan while it waits at Confirm KPIs (POST /api/projects/<id>/kpis/change {index, instruction, current});
- the organisation's KPI dictionary (POST /api/semreview/kpis/<id>/change {instruction}).
Each uses COST["kpi"] (1 credit), charged before Relay is asked and given back when no change comes of it. The test stack
has no Claude login, so Relay cannot be reached: each answers 503 and the credit comes back; the plan and the
dictionary stay as they were. Before any charge: a too short instruction (400), a KPI that is not there (404), a plan
not waiting for its KPIs (409), no credits (402, Request credits), someone who may not change it (403), another
organisation (404). In Chromium: the plan screen's "Change it in words" under each KPI, with its price and whether it
is a dictionary KPI. Screenshot: item63-plan.png. Its people sign in from 198.18.63.x.
python -I -X utf8 item63_check.py <public> <admin>"""
import itertools
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

c._ips = (f"198.18.63.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190))


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
dom = f"wordy{S}.com"
owner, vic = c.Person(f"wil.owner@{dom}"), c.Person(f"vic.viewer@{dom}")
s, r = owner.sign_in(f"Wordy Co {S}", "Wil Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
vic.sign_in(person="Vic Viewer")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
schema = "t_" + str(tid).replace("-", "_")
g.sql(f"UPDATE {schema}.memberships SET role = 'viewer' WHERE user_id = (SELECT id FROM {schema}.users WHERE email = '{vic.email}')")
other = c.Person(f"oli.owner@elsewhere{S}.com")
s, r = other.sign_in(f"Elsewhere {S}", "Oli Owner")
check("setup: a viewer of it and another organisation's owner sign in", s == 200, (s, r))
for p in (owner, vic, other):
    p.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
other.post("/api/org/setup")


def balance() -> int:
    return ((owner.get("/api/me")[1] or {}).get("org") or {}).get("credits") or 0


def set_balance(n: int) -> None:
    if n - balance():
        admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": n - balance(), "note": "item 63 check"})


def kpi_rows() -> list[tuple]:
    return [(x["kind"], x["delta"]) for x in (owner.get("/api/org")[1] or {}).get("ledger", []) if x.get("what") == "kpi"]


costs = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("costs") or {}
check("price: a KPI changed in words uses 1 credit (costs.kpi)", costs.get("kpi") == 1, costs)
s, r = owner.post("/api/ontology/industry", {"pack": "grocery-retail"})
s, r = c.import_handoff(owner, f"Words {S}")
pid = (r or {}).get("id") if isinstance(r, dict) else None
plan0 = ((owner.get(f"/api/projects/{pid}")[1] or {}).get("plan") or {}).get("kpis") or []
check("setup: a dashboard waits at Confirm KPIs with its plan's 3 KPIs (a DAWB hand-off)", s == 200 and len(plan0) == 3, (s, detail(r)))
set_balance(10)

# ---------------------------------------------------------------- a plan's KPI
section("a plan's KPI, changed in words")
s, r = owner.post(f"/api/projects/{pid}/kpis/change", {"index": 0, "instruction": "x"})
check("plan: an instruction of a letter is refused before any charge (400)", s == 400 and balance() == 10 and kpi_rows() == [], (s, detail(r), kpi_rows()))
s, r = owner.post(f"/api/projects/{pid}/kpis/change", {"index": 9, "instruction": "exclude the online channel"})
check("plan: a KPI that is not in the plan (404), nothing charged", s == 404 and balance() == 10 and kpi_rows() == [], (s, detail(r)))
s, r = vic.post(f"/api/projects/{pid}/kpis/change", {"index": 0, "instruction": "exclude the online channel"})
check("plan: a viewer cannot (403 or 404)", s in (403, 404) and balance() == 10, (s, detail(r)))
s, r = other.post(f"/api/projects/{pid}/kpis/change", {"index": 0, "instruction": "exclude the online channel"})
check("plan: another organisation cannot (404)", s == 404 and balance() == 10, (s, detail(r)))
s, r = owner.post(f"/api/projects/{pid}/kpis/change", {"index": 0, "instruction": "exclude the online channel",
                                                       "current": {"name": "Net sales", "dax": "SUM(sales_daily[net_sales])"}})
check("plan: no Claude on the stack: Relay could not be reached (503), saying the credit was given back",
      s == 503 and "given back" in str(detail(r)), (s, detail(r)))
check("plan: the credit came back (charged 1, refunded 1), the balance unchanged", balance() == 10 and kpi_rows() == [("refund", 1), ("charge", -1)],
      (balance(), kpi_rows()))
led = [x for x in (owner.get("/api/org")[1] or {}).get("ledger", []) if x.get("what") == "kpi"]
check("plan: the charge names the dashboard and the KPI", any(x.get("project_id") == pid and "Net sales" in str(x.get("note")) for x in led), led[:2])
plan1 = ((owner.get(f"/api/projects/{pid}")[1] or {}).get("plan") or {}).get("kpis") or []
check("plan: the plan's KPIs are as they were", plan1 == plan0, plan1)
set_balance(0)
s, r = owner.post(f"/api/projects/{pid}/kpis/change", {"index": 0, "instruction": "exclude the online channel"})
check("plan: without credits, 402 saying Request credits", s == 402 and "Request credits" in str(detail(r)) and (r or {}).get("credits") is True, (s, r))
set_balance(10)

# ---------------------------------------------------------------- a dictionary KPI
section("a KPI dictionary entry, changed in words")
s, kd = owner.get("/api/semreview/kpis")
entry = next((k for k in (kd or {}).get("kpis") or [] if k.get("name") == "Net Sales"), {})
kid = entry.get("id")
check("setup: the dictionary has the grocery pack's Net Sales", bool(kid), [k.get("name") for k in (kd or {}).get("kpis") or []][:6])
n0 = len(kpi_rows())
s, r = owner.post(f"/api/semreview/kpis/{kid}/change", {"instruction": " "})
check("dictionary: no instruction is refused before any charge (400)", s == 400 and len(kpi_rows()) == n0, (s, detail(r)))
s, r = owner.post("/api/semreview/kpis/k-0000000000/change", {"instruction": "make it weekly"})
check("dictionary: a KPI that is not in it (404), nothing charged", s == 404 and len(kpi_rows()) == n0 and balance() == 10, (s, detail(r)))
s, r = vic.post(f"/api/semreview/kpis/{kid}/change", {"instruction": "make it weekly"})
check("dictionary: a viewer cannot (403)", s == 403 and balance() == 10, (s, detail(r)))
s, r = other.post(f"/api/semreview/kpis/{kid}/change", {"instruction": "make it weekly"})
check("dictionary: another organisation's entry is not found (404)", s == 404, (s, detail(r)))
s, r = owner.post(f"/api/semreview/kpis/{kid}/change", {"instruction": "exclude fuel sales from it"})
check("dictionary: no Claude on the stack: Relay could not be reached (503), saying the credit was given back",
      s == 503 and "given back" in str(detail(r)), (s, detail(r)))
check("dictionary: the credit came back, the balance unchanged", balance() == 10 and kpi_rows()[:2] == [("refund", 1), ("charge", -1)]
      and len(kpi_rows()) == n0 + 2, (balance(), kpi_rows()))
s, kd2 = owner.get("/api/semreview/kpis")
after = next((k for k in (kd2 or {}).get("kpis") or [] if k.get("id") == kid), {})
check("dictionary: the entry is as it was", {k: v for k, v in after.items() if k != "updated"} == {k: v for k, v in entry.items() if k != "updated"},
      (entry, after))
set_balance(0)
s, r = owner.post(f"/api/semreview/kpis/{kid}/change", {"instruction": "make it weekly"})
check("dictionary: without credits, 402", s == 402, (s, detail(r)))
set_balance(10)

# ---------------------------------------------------------------- after the plan is confirmed
section("once the plan is confirmed")
st = owner.get(f"/api/projects/{pid}")[1] or {}
s, r = owner.form(f"/api/projects/{pid}/kpis", {"payload": json.dumps({"action": "confirm", "kpis": plan0, "feedback": "", "visuals": {},
                                                                     "approved": [i["id"] for i in st.get("approval_items") or []]})})
check("confirm: the plan is confirmed (the build starts)", s == 200, (s, detail(r)))
s, r = owner.post(f"/api/projects/{pid}/kpis/change", {"index": 0, "instruction": "exclude the online channel"})
check("confirmed: a plan KPI cannot be changed in words any more (409), nothing charged", s == 409 and balance() == 10, (s, detail(r)))
check("in all: the organisation's credits are what they were", balance() == 10, balance())

# ---------------------------------------------------------------- the screens
section("the screens")
set_balance(35)
s, r = c.import_handoff(owner, f"Words Screen {S}")             # 25 credits: 10 left
pid2 = (r or {}).get("id") if isinstance(r, dict) else None
check("screen: another dashboard waits at Confirm KPIs", s == 200 and pid2 and balance() == 10, (s, detail(r), balance()))
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, pid, typo = sys.argv[1:4]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto(f"http://127.0.0.1:8000/#/p/{pid}")
    page.wait_for_selector("input[aria-label='Change this KPI in words']", timeout=30000)
    page.wait_for_timeout(1000)
    out["inputs"] = page.locator("input[aria-label='Change this KPI in words']").count()
    out["buttons"] = page.locator(".kw button:has-text('Change')").evaluate_all("xs => xs.map(x => x.textContent)")
    out["badges"] = page.locator(".kw .kpidict").evaluate_all("xs => xs.map(x => x.textContent)")
    page.locator("input[aria-label='Change this KPI in words']").first.fill("exclude the online channel")
    page.locator(".kw button:has-text('Change')").first.click()
    page.wait_for_timeout(4000)
    out["after"] = page.evaluate("document.body.innerText")[:6000]
    text = page.evaluate("document.body.innerText")
    out["typo"] = "".join(ch for ch in text if ch in typo)
    out["errors"] = errors
    page.screenshot(path="/tmp/item63-plan.png", full_page=True)
    b.close()
print(json.dumps(out))
"""
b0 = balance()
ui = browser(c.WEB_C, PLAY, c.cookie(owner, "d2d_session"), str(pid2), TYPO)
check("screen: each of the plan's 3 KPIs can be changed in words, its price shown (1 credit)", ui.get("inputs") == 3
      and len(ui.get("buttons") or []) == 3 and all("1 credit" in x for x in ui.get("buttons") or []), {k: ui.get(k) for k in ("inputs", "buttons", "stderr")})
check("screen: a KPI of the organisation's dictionary says so (Net sales: From your KPI dictionary: Net Sales)",
      any("From your KPI dictionary: Net Sales" in x for x in ui.get("badges") or []) and any("New KPI" in x for x in ui.get("badges") or []), ui.get("badges"))
check("screen: Change with no Relay to reach leaves the credits as they were; plain characters, no script errors",
      balance() == b0 and ui.get("typo") == "" and ui.get("errors") == [], (balance(), b0, ui.get("typo"), ui.get("errors")))
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item63-plan.png", c.out_path("item63-plan.png")], check=False, capture_output=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
