"""Test stack only: item 29 (2026-11-12): the first-time tour, Migration D2D requests, plain characters in what the app
shows. python -I -X utf8 item29_check.py http://127.0.0.1:8103 http://127.0.0.1:8104"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

P, A = c.BASE, c.ADMIN_BASE
STAMP = str(int(time.time()))[-6:]
check, detail = c.check, c.detail_of


def sql(q: str) -> str:
    r = subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-At", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def in_web(code: str) -> str:
    r = subprocess.run(["docker", "exec", "-u", "relay", "-w", "/srv", c.WEB_C, "/usr/local/bin/python", "-P", "-X", "utf8", "-c", code],
                       capture_output=True, text=True, encoding="utf-8")
    return (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- the first-time tour
dom = f"tour{STAMP}.com"
owner, member = c.Person(f"tia.owner@{dom}"), c.Person(f"mo.member@{dom}")
s, r = owner.sign_in("Tour Test", "Tia Owner")
check("setup: an organisation signs up", s == 200, (s, r))
s, r = member.sign_in()
check("setup: a colleague joins it", s == 200, (s, r))
s, me = owner.get("/api/me")
check("tour: a new owner is due the tour", s == 200 and me.get("tour") is True, (s, me.get("tour") if isinstance(me, dict) else me))
s, mm = member.get("/api/me")
check("tour: a new member is due it too", s == 200 and mm.get("tour") is True, (s, mm.get("tour") if isinstance(mm, dict) else mm))
s, r = member.post("/api/me/tour", {"step": "look"})
check("tour: skipping it is recorded", s == 200 and r.get("ok"), (s, r))
check("tour: then it is not due for that person", member.get("/api/me")[1].get("tour") is False)
check("tour: and still due for the owner (one flag per person)", owner.get("/api/me")[1].get("tour") is True)
s, r = owner.post("/api/me/tour", {"step": "<script>alert(1)</script>" * 5})
tid = sql(f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = '{dom}'")
schema = "t_" + tid.replace("-", "_")
oid = sql(f"SELECT id FROM \"{schema}\".users WHERE email = 'tia.owner@{dom}'")
kept = sql(f"SELECT value FROM \"{schema}\".meta WHERE key = 'tour:{oid}'")
check("tour: a finished tour keeps only letters of the step it names", s == 200 and kept and json.loads(kept)["step"].isalpha()
      and len(json.loads(kept)["step"]) <= 20, kept)
check("tour: finished, it is not due", owner.get("/api/me")[1].get("tour") is False)
old = c.Person(f"ola.old@{dom}")
s, r = old.sign_in()
sql(f"UPDATE \"{schema}\".users SET created = 1790000000 WHERE email = 'ola.old@{dom}'")
check("tour: someone who started before 12 November 2026 is not shown it", old.get("/api/me")[1].get("tour") is False)
s, r = c.Person(f"x@{dom}").post("/api/me/tour", {"step": "done"})
check("tour: signed out, recording it is refused (401)", s == 401, (s, r))
admin = c.signed_in("info@pasdacs.com", A)
check("tour: never on the admin portal", admin.get("/api/me")[1].get("tour") is False)

# ---------------------------------------------------------------- Migration D2D requests
good = {"source": ["cognos", "qlik"], "target": ["powerbi"], "dashboards": 40, "message": "40 Cognos reports on Oracle — by March"}
s, r = member.post("/api/org/migration-request", good)
check("migration: a member asks PASDACS (200)", s == 200 and "sent" in r and r.get("contact"), (s, r))
s, d = admin.get("/api/admin/requests")
got = next((x for x in d.get("migrations") or [] if x.get("org") == tid), None) if s == 200 else None
check("migration: the admin portal's Requests lists it with the organisation, tools and count",
      got and got.get("org_name") == "Tour Test" and got.get("source") == ["cognos", "qlik"] and got.get("target") == ["powerbi"]
      and got.get("dashboards") == 40 and got.get("email") == f"mo.member@{dom}", got)
check("migration: the tool names come with it", (d.get("bi_tools") or {}).get("powerbi") == "Power BI", d.get("bi_tools"))
for name, body in (("no source", {**good, "source": []}), ("no target", {**good, "target": []}),
                   ("an unknown tool", {**good, "source": ["cognos", "excelsheet"]}), ("a tool that is not a string", {**good, "target": [7]})):
    s, r = member.post("/api/org/migration-request", body)
    check(f"migration: {name} is refused (400/422)", s in (400, 422), (s, r))
s, r = member.post("/api/org/migration-request", {**good, "dashboards": -5, "message": "x" * 5000})
row = sql(f"SELECT detail FROM relay.tn_audit WHERE action = 'd2d.migration_request' AND tenant_id = '{tid}' ORDER BY id DESC LIMIT 1")
det = json.loads(row) if row.startswith("{") else {}
check("migration: a bad count is dropped and a long message cut (500 kept in the log)", s == 200 and det.get("dashboards") is None
      and len(det.get("message") or "") == 500, (s, r, {k: det.get(k) for k in ("dashboards",)}, len(det.get("message") or "")))
codes = [member.post("/api/org/migration-request", good)[0] for _ in range(5)]
check("migration: at most 5 an hour per person (429 after)", 429 in codes, codes)
s, r = c.Person(f"y@{dom}").post("/api/org/migration-request", good)
check("migration: signed out, refused (401)", s == 401, (s, r))
s, r = admin.post("/api/org/migration-request", good)
check("migration: not an API of the admin portal (404)", s == 404, (s, r))
notes = sql(f"SELECT count(*) FROM public.notifications WHERE title LIKE 'Tour Test asks about Migration D2D%'")
check("migration: the platform admins are notified", notes.isdigit() and int(notes) >= 1, notes)

# ---------------------------------------------------------------- what the app shows: plain characters
out = in_web("""
import json, sys, tempfile, pathlib
sys.path[:0] = ["/srv", "/opt/genbi"]
from app import store
store.ROOT = pathlib.Path(tempfile.mkdtemp())
(store.ROOT / 'plain-test').mkdir()
(store.ROOT / 'plain-test' / 'project.json').write_text('{}')
store.log('plain-test', {'kind': 'say', 'text': 'Built the plan \\u2014 3 pages \\u2192 next: \\u201cSales\\u201d\\u2026', 'items': ['a \\u00b7 b']})
store.log('plain-test', {'kind': 'user', 'text': 'Named v1 \\u201cBoard \\u2014 final\\u201d'})
print(json.dumps([{k: e.get(k) for k in ('kind', 'text', 'items')} for e in store.activity('plain-test')]))
""")
try:
    ev = json.loads(out.splitlines()[-1])
except (ValueError, IndexError):
    ev = []
check("plain: the agent's words are shown with keyboard characters", ev and ev[0]["text"] == 'Built the plan - 3 pages -> next: "Sales"...'
      and ev[0]["items"] == ["a - b"], out[-300:])
check("plain: what a person typed is shown as they typed it", len(ev) > 1 and ev[1]["text"] == "Named v1 “Board — final”", out[-300:])
for path in ("/", "/js/38-tour.js", "/js/39-migration.js", "/js/36-org.js", "/js/02-shell.js", "/privacy.html", "/login.html"):
    s, t = member.call("GET", path)
    text = t if isinstance(t, str) else json.dumps(t)
    left = [ch for ch in text if ch in "—–…“”‘’·•›‹→←↔"]
    check(f"plain: {path} has no long dashes, curly quotes, arrows or bullets", s == 200 and not left, (s, "".join(left[:10])))

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
