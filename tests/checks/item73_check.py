"""Test stack only: item 73 (the user, 2026-11-19: "data needs to be reviewed and let them know if any gaps or assumptions
made ... any deviation or assumption or calculation needs to be approved"). Every gap, assumption and difference from the
KPI dictionary is approved before the build (ontology.approval_items, main.review_kpis):
- the plan's own gaps and assumptions (plan.yaml) and the analyst review's (item 68: gaps, assumptions, KPIs that
  deviate from the dictionary) come as approval_items with GET /api/projects/<id> while the plan waits at Confirm KPIs,
  each with a stable id (its kind and text: the same text twice is one item), its kind and where it came from;
- Confirm KPIs is refused while any is not approved (400, saying how many are left and which), accepted once all are
  (extra ids are ignored); what was approved is kept (project.json approvals: the items, who, when) and noted in
  request.md for the build; a plan without any confirms as before.
The test stack has no Claude, so the analyst review never runs: its findings are seeded into project.json (plan_review)
of a dashboard imported from a DAWB hand-off (waiting at Confirm KPIs), as worker._plan writes them. In Chromium: the
plan screen's Review and approve, Confirm off until every item is ticked. Screenshot: item73-approve.png.
Its people sign in from 198.18.73.x.
python -I -X utf8 item73_check.py <public> <admin>"""
import itertools
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

c._ips = (f"198.18.73.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190))
REVIEW = {"ran": True, "parsed": True, "verdict": "approve", "role": "analyst", "label": "Analyst review",
          "summary": "The plan can be built from the data, with the points below.", "checked": ["Every KPI against the data"], "issues": [],
          "plan_gaps": ["There is no returns data, so Net sales cannot exclude returns.", "Stores have no opening dates."],
          "gaps": ["There is no returns data, so Net sales cannot exclude returns.", "Prices are not in the data, only sales values."],
          "plan_assumptions": ["Online orders are counted on the day they were placed."],
          "assumptions": ["Sales are in US dollars."],
          "deviations": [{"kpi": "Net sales", "dictionary": "Net Sales", "difference": "It does not take off coupons, which your dictionary's Net Sales does."}]}


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


def seed_review(pid: str, review: dict) -> str:
    """project.json plan_review, as worker._plan writes it after the analyst review (approvals cleared)."""
    return c.in_app(f"""
import json, time
from app import store
with _db.use({tid!r}):
    store.update({pid!r}, plan_review={{"when": time.time(), **json.loads({json.dumps(json.dumps(review))})}}, approvals=None)
print(json.dumps({{"seeded": True}}))
""")


def confirm(p: c.Person, pid: str, approved: list[str] | None):
    st = p.get(f"/api/projects/{pid}")[1] or {}
    body = {"action": "confirm", "kpis": (st.get("plan") or {}).get("kpis") or [], "feedback": "", "visuals": {}}
    if approved is not None:
        body["approved"] = approved
    return p.form(f"/api/projects/{pid}/kpis", {"payload": json.dumps(body)})


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
owner = c.Person(f"ama.owner@approve{S}.com")
s, r = owner.sign_in(f"Approve Co {S}", "Ama Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
owner.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": 100, "note": "item 73 check"})

# ---------------------------------------------------------------- what is to be approved
section("what is to be approved")
s, r = c.import_handoff(owner, f"Approve Mini {S}")
pid = (r or {}).get("id") if isinstance(r, dict) else None
st = owner.get(f"/api/projects/{pid}")[1] or {}
check("plain: a plan with no gaps, assumptions or deviations has nothing to approve", s == 200 and st.get("status") == "awaiting_kpis"
      and st.get("approval_items") == [], (s, st.get("approval_items")))
out = seed_review(pid, REVIEW)
st = owner.get(f"/api/projects/{pid}")[1] or {}
items = st.get("approval_items") or []
kinds = [(i.get("kind"), i.get("source")) for i in items]
check("items: the analyst review's findings seeded (plan_review), as the worker writes them", '"seeded": true' in out, out[-300:])
check("items: every gap, assumption and deviation, the plan's first, the same text twice only once (6 items)",
      kinds == [("gap", "plan"), ("gap", "plan"), ("gap", "review"), ("assumption", "plan"), ("assumption", "review"), ("deviation", "review")], kinds)
dev = next((i for i in items if i.get("kind") == "deviation"), {})
check("items: a deviation names the KPI, the difference and the dictionary's KPI", dev.get("text") ==
      "Net sales: It does not take off coupons, which your dictionary's Net Sales does. (your KPI dictionary's Net Sales)", dev.get("text"))
check("items: each has a stable id of its kind (gap-, ass-, dev- and a hash of its text)", all(str(i.get("id", "")).startswith(i["kind"][:3] + "-")
                                                                                             and len(i["id"]) == 14 for i in items), [i.get("id") for i in items])
st2 = owner.get(f"/api/projects/{pid}")[1] or {}
check("items: the ids stay the same each time they are asked for", [i.get("id") for i in st2.get("approval_items") or []] == [i["id"] for i in items],
      [i.get("id") for i in st2.get("approval_items") or []])

# ---------------------------------------------------------------- confirming
section("confirming the plan")
b0 = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("credits")
s, r = confirm(owner, pid, None)
check("confirm: refused while nothing is approved (400, 6 left, naming them)", s == 400 and "(6 left)" in str(detail(r))
      and "There is no returns data" in str(detail(r)), (s, detail(r)))
s, r = confirm(owner, pid, [i["id"] for i in items[:4]])
check("confirm: refused while some are not approved (400, 2 left)", s == 400 and "(2 left)" in str(detail(r)) and "Sales are in US dollars" in str(detail(r)),
      (s, detail(r)))
s, r = confirm(owner, pid, ["gap-0000000000"] + [i["id"] for i in items[1:]])
check("confirm: a made-up id does not count for a real one (400, 1 left)", s == 400 and "(1 left)" in str(detail(r)), (s, detail(r)))
st = owner.get(f"/api/projects/{pid}")[1] or {}
check("confirm: nothing changed while refused (still waiting at Confirm KPIs, no new charge, no approvals kept)",
      st.get("status") == "awaiting_kpis" and not st.get("approvals")
      and ((owner.get("/api/me")[1] or {}).get("org") or {}).get("credits") == b0, (st.get("status"), st.get("approvals")))
s, r = confirm(owner, pid, [i["id"] for i in items] + ["ass-ffffffffff"])
check("confirm: accepted once every item is approved (an extra id is ignored); the build is queued", s == 200
      and ((r or {}).get("job") or {}).get("kind") == "build", (s, detail(r)))
pj = c.last_json(c.in_app(f"""
import json
from app import store
with _db.use({tid!r}):
    print(json.dumps(store.load({pid!r}).get("approvals")))
"""))
check("approvals: kept in project.json: the 6 items, who approved them and when", isinstance(pj, dict) and [i.get("id") for i in pj.get("items") or []]
      == [i["id"] for i in items] and pj.get("by") == "Ama Owner" and pj.get("when"), pj)
s, req = owner.get(f"/api/projects/{pid}/files/request.md")
check("approvals: noted in request.md for the build, each with its kind", "The person approved these before the build" in str(req)
      and "- deviation: Net sales: It does not take off coupons" in str(req) and "- gap: Stores have no opening dates." in str(req), str(req)[-800:])

# ---------------------------------------------------------------- the screen
section("the screen")
s, r = c.import_handoff(owner, f"Approve Screen {S}")
pid2 = (r or {}).get("id") if isinstance(r, dict) else None
seed_review(pid2, REVIEW)
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, pid, typo = sys.argv[1:4]
out = {}
CONFIRM = "button:has-text('Confirm & build prototype')"
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto(f"http://127.0.0.1:8000/#/p/{pid}")
    page.wait_for_selector("text=Review and approve", timeout=30000)
    page.wait_for_timeout(1000)
    boxes = page.locator(".apcard input[type=checkbox]")
    out["boxes"] = boxes.count()
    out["confirm_off"] = page.locator(CONFIRM).first.is_disabled()
    out["badge"] = page.locator("text=Differs from your KPI dictionary").count()
    out["card"] = page.locator(".apcard").first.inner_text() if page.locator(".apcard").count() else page.evaluate("document.body.innerText")[:3000]
    approve_all = page.locator(".apcard button:has-text('Approve all')")
    if approve_all.count():
        approve_all.first.click()
    else:
        for k in range(boxes.count()):
            boxes.nth(k).check()
    page.wait_for_timeout(500)
    out["confirm_on"] = not page.locator(CONFIRM).first.is_disabled()
    page.screenshot(path="/tmp/item73-approve.png", full_page=True)
    text = page.evaluate("document.body.innerText")
    out["typo"] = "".join(ch for ch in text if ch in typo)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
ui = browser(c.WEB_C, PLAY, c.cookie(owner, "d2d_session"), str(pid2), TYPO)
check("screen: Review and approve lists the 6 items, Confirm stays off until they are approved",
      ui.get("boxes") == 6 and ui.get("confirm_off") is True, {k: ui.get(k) for k in ("boxes", "confirm_off", "card", "stderr")})
check("screen: Approve all turns Confirm on", ui.get("confirm_on") is True, ui.get("confirm_on"))
check("screen: the KPI the analyst found different says it differs from the KPI dictionary", ui.get("badge", 0) >= 1, ui.get("badge"))
check("screen: plain characters, no script errors", ui.get("typo") == "" and ui.get("errors") == [], {k: ui.get(k) for k in ("typo", "errors")})
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item73-approve.png", c.out_path("item73-approve.png")], check=False, capture_output=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
