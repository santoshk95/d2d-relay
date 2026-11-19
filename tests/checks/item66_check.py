"""Test stack only: item 66, Ask Relay (webapp/app/askd_routes.py):
- PATCH /api/askd/threads/<id> {title}: the person names their own conversation (spaces collapsed, 120 characters at
  most); an empty name is refused; another person's conversation, or one that is not there, is not found;
- GET /api/askd/options: besides the dashboards (now with their status and when they were made) and connections, the
  organisation's KPIs for the side panel (its KPI dictionary: name, unit, a short definition; then its dashboards'
  KPIs) and its industry's example questions (the general pack's until it applies one).
Conversations are seeded in the test web container (as item52_check.py does): the test stack has no Claude to answer.
Its people sign in from 198.18.66.x.
python -I -X utf8 item66_check.py <public> <admin>"""
import itertools
import json
import os
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

c._ips = (f"198.18.66.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def seed_thread(tid: str, uid: str, tag: str, title: str) -> str:
    """A conversation of `uid` with one question and its answer, as askd keeps them; returns its id."""
    th = f"t-item66{tag}{S}"
    body = {"result": {"type": "text", "headline": "North sold most"}, "summary": "North sold most.", "data": {"columns": [], "rows": []},
            "actions": [], "next_questions": [], "validation": {"queries": []}, "usage": {}}
    out = c.in_app(f"""
import json, time
with _db.use({tid!r}):
    _db.run('INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES (?, ?, ?, ?, ?, ?)',
            ({th!r}, {uid!r}, json.dumps({{'kind': 'team'}}), {title!r}, time.time(), time.time()))
    _db.run('INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, ?, ?, ?)',
            ('q-' + {th!r}, {th!r}, 'user', json.dumps({{'text': 'Which region sold most?'}}), time.time() - 1))
    _db.run('INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, ?, ?, ?)',
            ('a-' + {th!r}, {th!r}, 'assistant', {json.dumps(json.dumps(body))}, time.time()))
print(json.dumps({{"seeded": {th!r}}}))
""")
    return c.last_json(out).get("seeded") or ""


dom = f"askco{S}.com"
owner, ned = c.Person(f"ada.owner@{dom}"), c.Person(f"ned.member@{dom}")
s, r = owner.sign_in(f"Ask Co {S}", "Ada Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
s, r = ned.sign_in(person="Ned Member")
other = c.Person(f"ora.owner@elsewhere{S}.com")
s2, r2 = other.sign_in(f"Elsewhere {S}", "Ora Owner")
check("setup: a colleague and another organisation's owner sign in", s == 200 and s2 == 200, (s, s2))
for p in (owner, ned, other):
    p.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
other.post("/api/org/setup")
me = owner.get("/api/me")[1] or {}
tid, uid = (me.get("org") or {}).get("id"), me.get("id")
nid = (ned.get("/api/me")[1] or {}).get("id")

# ---------------------------------------------------------------- renaming a conversation
section("renaming a conversation")
th = seed_thread(tid, uid, "a", "Which region sold most?")
th_ned = seed_thread(tid, nid, "b", "Ned's question")
check("setup: two conversations, the owner's and a colleague's", bool(th) and bool(th_ned), (th, th_ned))
s, r = owner.patch(f"/api/askd/threads/{th}", {"title": "   Regional   sales,\n Q3  "})
check("rename: the owner names their conversation (spaces collapsed)", s == 200 and r == {"id": th, "title": "Regional sales, Q3"}, (s, r))
s, lst = owner.get("/api/askd/threads")
s2, one = owner.get(f"/api/askd/threads/{th}")
check("rename: the list and the conversation carry the new name; its messages are as they were",
      any(t.get("id") == th and t.get("title") == "Regional sales, Q3" for t in (lst or {}).get("threads") or [])
      and one.get("title") == "Regional sales, Q3" and len(one.get("messages") or []) == 2, (s, s2, one.get("title")))
s, r = owner.patch(f"/api/askd/threads/{th}", {"title": "x" * 300})
check("rename: a long name is cut at 120 characters", s == 200 and r.get("title") == "x" * 120, (s, len(str((r or {}).get("title")))))
for body, why in (({"title": "   "}, "only spaces"), ({"title": ""}, "empty")):
    s, r = owner.patch(f"/api/askd/threads/{th}", body)
    check(f"rename: refused (400): {why}", s == 400, (s, detail(r)))
s, r = owner.patch(f"/api/askd/threads/{th}", {})
check("rename: no title at all (422)", s == 422, (s, detail(r)))
s, r = owner.patch(f"/api/askd/threads/{th_ned}", {"title": "Mine now"})
check("rename: not a colleague's conversation (404: conversations are personal)", s == 404, (s, detail(r)))
s, one = ned.get(f"/api/askd/threads/{th_ned}")
check("rename: ... which keeps its name", one.get("title") == "Ned's question", one.get("title"))
s, r = other.patch(f"/api/askd/threads/{th}", {"title": "Theirs"})
check("rename: not another organisation's (404)", s == 404, (s, detail(r)))
s, r = owner.patch("/api/askd/threads/t-nothere000", {"title": "Nothing"})
check("rename: not one that is not there (404)", s == 404, (s, detail(r)))
s, r = c.Person("x").patch(f"/api/askd/threads/{th}", {"title": "Anon"})
check("rename: nobody without a session (401)", s == 401, (s, r))

# ---------------------------------------------------------------- what Ask Relay offers
section("what Ask Relay offers (options)")
s, gen = owner.get("/api/ontology/packs/general")
s, o = owner.get("/api/askd/options")
check("options: no industry yet: the general pack's example questions, no KPIs", s == 200 and o.get("industry") == ""
      and o.get("questions") == (gen.get("questions") or [])[:12] and len(o.get("questions") or []) > 0 and o.get("kpis") == [],
      {k: o.get(k) for k in ("industry", "questions", "kpis")})
owner.post("/api/ontology/industry", {"pack": "grocery-retail"})
s, r = owner.post("/api/semreview/kpis", {"name": "Shelf Gap Index", "unit": "count", "aggregation": "average",
                                          "definition": "Shelf facings left empty at the morning count, " + "store by store and aisle by aisle, " * 8})
check("setup: the organisation's ontology is the grocery pack, and a KPI of its own is in its dictionary", s == 200, (s, detail(r)))
s, imp = c.import_handoff(owner, f"Ask Mini {S}")
s, o = owner.get("/api/askd/options")
s2, pk = owner.get("/api/ontology/packs/grocery-retail")
k = {x["name"]: x for x in o.get("kpis") or []}
check("options: the industry's example questions and name (grocery and retail)", o.get("industry") == "Grocery and retail"
      and o.get("questions") == (pk.get("questions") or [])[:12], {k_: o.get(k_) for k_ in ("industry", "questions")})
check("options: the KPI dictionary's KPIs, each with its unit and a short definition (200 characters at most)",
      k.get("Net Sales", {}).get("from") == "dictionary" and k.get("Net Sales", {}).get("unit") == "currency"
      and k.get("Shelf Gap Index", {}).get("unit") == "count" and 0 < len(k.get("Shelf Gap Index", {}).get("definition") or "") <= 200,
      {n: k.get(n) for n in ("Net Sales", "Shelf Gap Index")})
check("options: then the KPIs of the person's dashboards that the dictionary does not have, named by their dashboard",
      k.get("Order count", {}).get("from") == f"Ask Mini {S}" and k.get("Net sales") is None, {n: k.get(n) for n in ("Order count", "Average order", "Net sales")})
dash = next((d for d in o.get("dashboards") or [] if d.get("id") == (imp or {}).get("id")), {})
check("options: the dashboards come with their status and when they were made", dash.get("status") == "awaiting_kpis" and dash.get("created"), dash)
s, on = ned.get("/api/askd/options")
check("options: a colleague sees the organisation's KPIs and questions, not the owner's private dashboard",
      s == 200 and on.get("industry") == "Grocery and retail" and any(x["name"] == "Net Sales" for x in on.get("kpis") or [])
      and not any(d.get("id") == (imp or {}).get("id") for d in on.get("dashboards") or []) and "Order count" not in {x["name"] for x in on.get("kpis") or []},
      {k_: on.get(k_) for k_ in ("industry", "dashboards")})
s, oo = other.get("/api/askd/options")
check("options: another organisation sees none of it", s == 200 and not any(x["name"] == "Shelf Gap Index" for x in oo.get("kpis") or [])
      and oo.get("industry") == "", {k_: oo.get(k_) for k_ in ("industry", "kpis")})

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
