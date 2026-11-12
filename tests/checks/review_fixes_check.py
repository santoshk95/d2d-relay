"""Checks for the review's fixes, on the test stack only (python -I review_fixes_check.py <public> <admin>)."""
import os
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))    # python -I leaves the script's folder out
import d2d_checks as c  # noqa: E402

BLOCKED = "That is not part of D2D Relay."
stamp = str(int(time.time()))[-6:]
owner = c.Person(f"olive.owner@review{stamp}.com")
s, r = owner.sign_in("Review Test", "Olive Owner")
c.check("a new organisation signs up", s == 200, (s, r))
s, r = owner.post("/api/reviews/no-such-dashboard/r-1234", {"decision": "approve", "comment": ""})
c.check("a reviewer's answer reaches the app (not blocked)", s == 404 and c.detail_of(r) != BLOCKED, (s, r))
s, r = owner.get("/api/reviews")
c.check("the list of everyone's reviews stays off", s == 404 and c.detail_of(r) == BLOCKED, (s, r))
for path in ("/api/me/channels", "/api/me/github", "/api/me/github/repos"):
    s, r = owner.get(path)
    c.check(f"{path} is off", s == 404 and c.detail_of(r) == BLOCKED, (s, r))
s, r = owner.post("/api/share/channel", {"channel": "x", "kind": "project", "id": "x", "text": ""})
c.check("/api/share/channel is off", s == 404 and c.detail_of(r) == BLOCKED, (s, r))
for path in ("/api/schedules-measures/no-such-dashboard", "/api/schedules-draft"):
    s, r = owner.get(path)
    c.check(f"{path} is off", s == 404 and c.detail_of(r) == BLOCKED, (s, r))
s, r = owner.post("/api/schedules-preview", {"target": {}})
c.check("/api/schedules-preview is off", s == 404 and c.detail_of(r) == BLOCKED, (s, r))
s, r = owner.post("/api/export/project/no-such-dashboard?fmt=pdf")
c.check("exporting an unknown dashboard answers 404, not 500", s == 404 and c.detail_of(r) == "Unknown dashboard", (s, r))
s, lib = owner.get("/api/library")
items = (lib or {}).get("visuals") or (lib or {}).get("items") or [] if isinstance(lib, dict) else []
c.check("the visual library answers", s == 200, (s, str(lib)[:200]))
if items:
    name = items[0].get("name")
    req = c.urllib.request.Request(owner.base + f"/api/library/{name}/preview")
    try:
        with owner.http.open(req, timeout=60) as resp:
            st = resp.status
    except c.urllib.error.HTTPError as e:
        st = e.code
    c.check(f"a library visual's preview opens ({name})", st == 200, st)
s, me = owner.get("/api/me")
c.check("the owner is the organisation's owner", (me.get("org") or {}).get("is_owner") is True, me.get("org"))
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed")
sys.exit(len(bad))
