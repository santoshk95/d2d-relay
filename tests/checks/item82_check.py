"""Item 82 (the user, 2026-11-19, on PASDACS's Notifications page full of other organisations' credit requests and the
job runner's health: "only org or their task or their platform relation notification must be here not all").
Notices about the platform itself are PASDACS's console's: the admin portal shows them and nothing else, the public site
never does; there a person sees their organisation's news, their own work and what PASDACS answered them
(`webapp/app/notify.py`: `PLATFORM`, `_site`). Its people sign in from 198.18.82.x.

python -I -X utf8 item82_check.py <public> <admin>"""
import json
import os
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

check = c.check
STAMP = str(int(time.time()))[-6:]
_ips = iter(f"198.18.82.{n}" for n in range(10, 60))


def person(email: str) -> c.Person:
    p = c.Person(email)
    p.ip = next(_ips)
    return p


def texts(p: c.Person) -> tuple[int, str, int]:
    s, n = p.get("/api/notifications")
    n = n if isinstance(n, dict) else {}
    return s, json.dumps(n.get("items") or []), int(n.get("unread") or 0)


owner = person(f"nora.notes@notes{STAMP}.com")
s, r = owner.sign_in("Notes Org", "Nora Notes")
check("setup: PASDACS creates an organisation; its owner signs in", s == 200, (s, r))
s, r = owner.post("/api/org/credit-request", {"credits": 75, "message": "item 82 check"})
rid = ((r or {}).get("request") or {}).get("id")
check("setup: the owner asks PASDACS for 75 credits", s == 200 and rid, (s, r))
want = f"Notes Org asks for 75 credits"

admin_portal = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s, items, unread = texts(admin_portal)
check("admin portal: PASDACS sees the organisation's request among its notices", s == 200 and want in items, items[:300])
check("admin portal: it shows platform notices only (none of a person's own dashboards or shares)",
      all(x.get("kind") in ("platform", "ops") for x in json.loads(items)), [x.get("kind") for x in json.loads(items)][:10])

public = c.signed_in("info@pasdacs.com", c.BASE)
s, items, unread = texts(public)
check("public site: the same PASDACS person does not see another organisation's request there", s == 200 and want not in items, items[:300])
check("public site: no notice about the platform's health or other organisations (links into the admin portal)",
      not any(str(x.get("link") or "").startswith(("#/requests", "#/orgs", "#/admin/")) or x.get("kind") == "platform" for x in json.loads(items)),
      [(x.get("kind"), x.get("link")) for x in json.loads(items)][:10])
s, before = public.get("/api/notifications")
s2, after = public.post("/api/notifications/read")
s3, items_admin, unread_admin = texts(admin_portal)
check("public site: Mark all read there leaves the admin portal's notices unread", s2 == 200 and unread_admin >= 1, (s2, unread_admin))

s, r = admin_portal.post(f"/api/admin/requests/{rid}/approve", {"credits": 75}) if rid else (0, None)
check("admin portal: PASDACS approves the request", s == 200, (s, r))
s, items, unread = texts(owner)
check("public site: the owner is told about their own request (their relation with PASDACS)", s == 200 and "75 credits" in items, items[:300])
check("public site: the owner sees nothing about the platform", not any(str(x.get("link") or "").startswith(("#/requests", "#/orgs", "#/admin/"))
      or x.get("kind") == "platform" for x in json.loads(items)), items[:300])

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
