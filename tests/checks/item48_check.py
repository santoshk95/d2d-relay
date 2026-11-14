"""Test stack only: item 48 (2026-11-14), the user's rule for a prototype build that does not finish (kept off every
screen at the user's request).
- a prototype build or change that had started keeps its credits when it stops, and Retry starts it again at no cost;
- a run before building (planning) still gives its credits back, as before;
- no screen, message or the terms say that credits come back.
The test stack has no Claude sign-in, so every AI run fails at once.
python -I -X utf8 item48_check.py <public> <admin>"""
import json
import os
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

check = c.check
p = c.Person(f"kai.keep@keep{c.STAMP}.com")
s, r = p.sign_in("Keep Test", "Kai Keep")
check("setup: an organisation signs up", s == 200, (s, r))
p.post("/api/me/tour", {"step": "done"})
p.post("/api/org/setup")
org = p.get("/api/me")[1].get("org") or {}
admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)


def balance() -> int:
    return (p.get("/api/me")[1].get("org") or {}).get("credits") or 0


def ledger(pid: str) -> list[dict]:
    return [x for x in p.get("/api/org")[1].get("ledger", []) if x.get("project_id") == pid]


def settled(pid: str, runs: int = 1) -> dict:
    st = {}
    for _ in range(90):
        st = p.get(f"/api/projects/{pid}")[1] or {}
        if st.get("status") == "error":
            break
        time.sleep(2)
    time.sleep(3)                                  # the job's end (and any refund) a moment after the status
    return p.get(f"/api/projects/{pid}")[1] or {}


s, _ = admin.post(f"/api/admin/orgs/{org.get('id')}/credits", {"credits": 100 - balance(), "note": "item 48 check"})
check("setup: the organisation has 100 credits", s == 200 and balance() == 100, balance())

# ---------------------------------------------------------------- planning still gives its credits back
s, d = p.form("/api/projects", {"prompt": "Sales by region", "data_mode": "upload"}, {"files": ("sales.csv", b"region,sales\nNorth,10\nSouth,12\n")})
pid = d.get("id") if isinstance(d, dict) and s == 200 else None
settled(pid) if pid else None
kinds = sorted((x["kind"], x["delta"]) for x in ledger(pid)) if pid else []
check("plan: a planning run that fails still gives its 25 back (charge, refund)", pid and kinds == [("charge", -25), ("refund", 25)]
      and balance() == 100, (kinds, balance()))

# ---------------------------------------------------------------- a change that had started keeps its credits
tid = org.get("id")
out = g.app(f"""
from app import orgs, worker
with _db.use({tid!r}):
    cid = orgs.charge("change", {pid!r}, "Keep test", "item 48 check")
    worker.enqueue({pid!r}, "revise", feedback="Make the bars blue", attachments=[], charge=cid)
    print(cid)
""")
cid = out.strip().splitlines()[-1] if out.strip() else ""
check("setup: a change is charged (10) and its build queued", cid.startswith("cr-") and balance() == 90, (out[-300:], balance()))
st = settled(pid)
led = ledger(pid)
check("keep: the change's build failed, and its 10 credits were not given back", st.get("status") == "error"
      and not [x for x in led if x["kind"] == "refund" and x.get("delta") == 10] and balance() == 90, (st.get("status"), led[:4], balance()))
check("keep: Retry is free for it (the page is told 0)", (st.get("credits") or {}).get("retry") == 0, st.get("credits"))
s, r = p.post(f"/api/projects/{pid}/retry", {})
st = settled(pid)
led = ledger(pid)
check("keep: Retry ran it again with no new charge (still one 10-credit change)", s == 200
      and len([x for x in led if x["kind"] == "charge" and x["delta"] == -10]) == 1 and balance() == 90, (s, led[:4], balance()))
act = json.dumps(p.get(f"/api/projects/{pid}/activity")[1])
check("keep: the activity log says nothing about the change's credits coming back", "credits for this change were given back" not in act
      and len(act) > 10, act[-300:])

# ---------------------------------------------------------------- nothing says credits come back
import urllib.request  # noqa: E402
terms = urllib.request.urlopen(c.BASE + "/terms.html", timeout=20).read().decode("utf-8", "replace")
check("terms: they no longer say that credits come back", "come back" not in terms and "Terms of service" in terms, "come back" in terms)
js = g.sh("cat /srv/static/js/36-org.js /srv/static/js/07-tabs.js /srv/static/js/06-project.js", "root")
check("screens: the Organisation page, a dashboard's Credits card and Retry say nothing of it",
      "credits come back" not in js and "Retry costs no credits" not in js and len(js) > 1000, len(js))
s, r = p.post(f"/api/projects/{pid}/stop")
check("stop: the refusal says only that a build finishes on its own", s == 403 and "come back" not in str(c.detail_of(r)), (s, r))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
