"""Test stack only: data governance (item 22): erasure, "Download my data", the privacy notice, blocked egress routes,
the nightly retention sweep, organisation erasure and the AI engine's forget step.

python -I gov_check.py http://127.0.0.1:8103 http://127.0.0.1:8104
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

WEB, DB = c.WEB_C, c.DB_C
STAMP = c.STAMP
UUID1, UUID2, UUID3 = "11111111-2222-3333-4444-555555555555", "66666666-7777-8888-9999-000000000000", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def sh(cmd: str, user: str = "relay") -> str:
    r = subprocess.run(["docker", "exec", "-u", user, WEB, "sh", "-c", cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip()


def app(code: str) -> str:
    """Python inside the test web container, with the app's settings (database and folders)."""
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", WEB, "/opt/relay/bin/launch", "web", "python", "-"],
                       input="from app import db as _db\n_db.init()\n" + code, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip()


def sql(q: str) -> str:
    r = subprocess.run(["docker", "exec", "-u", "postgres", DB, "psql", "-At", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def slug(path: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def plant_transcript(folder: str, sid: str, days_old: float = 0) -> str:
    d = f"/home/agent/.claude/projects/{slug(folder)}"
    touch = f"touch -d '@{int(time.time() - days_old * 86400)}' {d}/{sid}.jsonl" if days_old else "true"
    return sh(f"mkdir -p {d}/{sid}/tool-results /home/agent/.claude/tasks/{sid} && echo '{{\"secret\": \"rows\"}}' > {d}/{sid}.jsonl "
              f"&& echo data > {d}/{sid}/tool-results/out.txt && echo '{{}}' > /home/agent/.claude/tasks/{sid}/1.json && {touch} && echo planted", "agent")


def exists(path: str) -> bool:
    return sh(f"test -e '{path}' && echo yes || echo no", "root").endswith("yes")


def wait_idle(p, pid: str) -> str:
    for _ in range(90):
        s, r = p.get(f"/api/projects/{pid}")
        if s == 200 and r.get("status") not in ("queued", "extracting", "generating_data", "planning", "building", "revising", "building_pbi"):
            return r.get("status")
        if s == 200 and _ == 20:
            p.post(f"/api/projects/{pid}/stop")
        time.sleep(2)
    return "still running"


def tenant_of(pid: str) -> str:
    out = sh(f"ls -d /data/projects/.tenants/*/{pid} 2>/dev/null")
    return out.split("/")[4] if out.startswith("/data/projects/.tenants/") else ""


# ---------------------------------------------------------------------------------------------------- privacy notice
def privacy():
    req = urllib.request.Request(c.BASE + "/privacy.html")
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
        c.check("privacy: the notice opens without signing in", r.status == 200 and "Privacy notice" in body and "Data Protection Board" in body, r.status)
    with urllib.request.urlopen(c.BASE + "/login.html", timeout=30) as r:
        c.check("privacy: the sign-in page links to it", 'href="privacy.html"' in r.read().decode())


def main():
    privacy()
    dom = f"gov{STAMP}.com"
    owner, member = c.Person(f"gina.owner@{dom}"), c.Person(f"mo.member@{dom}")
    s, r = owner.sign_in("Gov Test", "Gina Owner")
    c.check("setup: an organisation signs up", s == 200, (s, r))
    s, r = member.sign_in()
    c.check("setup: a colleague joins it", s == 200, (s, r))

    # ---------------------------------------------------------------- deleting a dashboard
    s, d1 = c.new_dashboard(owner)
    c.check("dashboard: the owner makes one", s == 200 and isinstance(d1, dict) and d1.get("id"), (s, d1))
    pid = d1["id"]
    st = wait_idle(owner, pid)
    c.check("dashboard: its first run ends (no AI login on the test stack)", st != "still running", st)
    tid = tenant_of(pid)
    c.check("dashboard: it lives in its organisation's folder", bool(tid), tid)
    folder = f"/data/projects/.tenants/{tid}/{pid}"
    c.check("dashboard: an AI transcript of it is planted", plant_transcript(folder, UUID1).endswith("planted"))
    out = app(f"""
import json, time
from app import db
with db.use({tid!r}):
    uid = db.one("SELECT id FROM users WHERE email = ?", ({owner.email!r},))["id"]
    db.run("INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES ('t-gov1', ?, ?, 'About it', ?, ?)",
           (uid, json.dumps({{"kind": "dashboard", "project": {pid!r}}}), time.time(), time.time()))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES ('q-gov1', 't-gov1', 'user', ?, ?)", (json.dumps({{"text": "how much?"}}), time.time()))
    db.run("INSERT INTO askd_cache (key, body, created) VALUES ('k-gov1', ?, ?)", (json.dumps({{"sources": [{pid!r}]}}), time.time()))
print("ok")
""")
    c.check("dashboard: a conversation about it and a cached answer are planted", out.endswith("ok"), out[-300:])

    s, r = member.delete(f"/api/projects/{pid}")
    c.check("dashboard: a colleague it is not shared with cannot delete it (404)", s == 404, (s, r))
    s, r = owner.get("/api/org")
    mid = next((p["id"] for p in r.get("people", []) if p["email"] == member.email), None) if s == 200 else None
    s, r = owner.put(f"/api/projects/{pid}/shares", {"visibility": "private", "shares": [{"principal_type": "user", "principal_id": mid, "permission": "edit"}]})
    c.check("dashboard: the owner shares it with the colleague to edit", s == 200, (s, r))
    s, r = member.get(f"/api/projects/{pid}")
    c.check("dashboard: the colleague sees no Delete (can_delete false)", s == 200 and r["access"]["can_delete"] is False, (s, r.get("access") if isinstance(r, dict) else r))
    s, r = member.delete(f"/api/projects/{pid}")
    c.check("dashboard: an editor cannot delete it (403)", s == 403, (s, r))
    s, r = owner.get(f"/api/projects/{pid}")
    c.check("dashboard: the owner sees Delete (can_delete true)", s == 200 and r["access"]["can_delete"] is True, (s, r.get("access") if isinstance(r, dict) else r))
    s, r = owner.delete(f"/api/projects/{pid}")
    c.check("dashboard: the owner deletes it", s == 200 and r.get("deleted") == pid and r.get("conversations") == 1, (s, r))
    s, r = owner.get(f"/api/projects/{pid}")
    c.check("dashboard: it is gone (404)", s == 404, (s, r))
    s, r = owner.get("/api/projects")
    ids = [p["id"] for p in (r if isinstance(r, list) else r.get("projects", []))] if s == 200 else None
    c.check("dashboard: it has left the list", s == 200 and pid not in ids, (s, ids))
    c.check("dashboard: its folder is gone", not exists(folder) and sh(f"ls -a /data/projects/.tenants/{tid}").find(pid) < 0,
            sh(f"ls -a /data/projects/.tenants/{tid}"))
    c.check("dashboard: the AI engine's transcript of it is gone", not exists(f"/home/agent/.claude/projects/{slug(folder)}"))
    c.check("dashboard: its task list in the AI engine is gone", not exists(f"/home/agent/.claude/tasks/{UUID1}"))
    out = app(f"""
from app import db
with db.use({tid!r}):
    print(len(db.q("SELECT 1 AS x FROM askd_threads WHERE id = 't-gov1'")), len(db.q("SELECT 1 AS x FROM askd_messages WHERE thread_id = 't-gov1'")),
          len(db.q("SELECT 1 AS x FROM askd_cache WHERE key = 'k-gov1'")), len(db.q("SELECT 1 AS x FROM projects WHERE id = ?", ({pid!r},))),
          len(db.q("SELECT 1 AS x FROM shares WHERE project_id = ?", ({pid!r},))), len(db.q("SELECT 1 AS x FROM audit WHERE action = 'project.deleted' AND object = ?", ({pid!r},))))
""")
    c.check("dashboard: its conversation, cached answer, index row and shares are gone; the deletion is audited", out.endswith("0 0 0 0 0 1"), out[-300:])
    s, r = owner.get("/api/org")
    led = [x for x in r.get("ledger", []) if x.get("project_id") == pid] if s == 200 else []
    c.check("dashboard: its credit history stays (credits are money)", len(led) >= 1, led)

    # ---------------------------------------------------------------- deleting one Ask Relay conversation
    out = app(f"""
import json, time
from app import db
with db.use({tid!r}):
    uid = db.one("SELECT id FROM users WHERE email = ?", ({owner.email!r},))["id"]
    db.run("INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES ('t-gov2', ?, ?, 'All my data', ?, ?)",
           (uid, json.dumps({{"kind": "team"}}), time.time(), time.time()))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES ('q-gov2', 't-gov2', 'user', ?, ?)", (json.dumps({{"text": "top 5?"}}), time.time()))
    db.run("INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES ('a-gov2', 't-gov2', 'assistant', ?, ?)", (json.dumps({{"summary": "North leads", "cache_key": "k-gov2"}}), time.time()))
    db.run("INSERT INTO askd_feedback (message_id, user_id, rating, created) VALUES ('a-gov2', ?, 1, ?)", (uid, time.time()))
    db.run("INSERT INTO askd_cache (key, body, created) VALUES ('k-gov2', '{{}}', ?)", (time.time(),))
print("ok")
""")
    c.check("conversation: one is planted with an answer, feedback and a cached answer", out.endswith("ok"), out[-300:])
    s, r = member.delete("/api/askd/threads/t-gov2")
    c.check("conversation: someone else cannot delete it (404)", s == 404, (s, r))
    s, r = owner.delete("/api/askd/threads/t-gov2")
    c.check("conversation: its owner deletes it", s == 200 and r.get("deleted") == "t-gov2", (s, r))
    s, r = owner.get("/api/askd/threads/t-gov2")
    c.check("conversation: it is gone (404)", s == 404, (s, r))
    out = app(f"""
from app import db
with db.use({tid!r}):
    print(len(db.q("SELECT 1 AS x FROM askd_messages WHERE thread_id = 't-gov2'")), len(db.q("SELECT 1 AS x FROM askd_feedback WHERE message_id = 'a-gov2'")),
          len(db.q("SELECT 1 AS x FROM askd_cache WHERE key = 'k-gov2'")))
""")
    c.check("conversation: its messages, feedback and cached answer are gone", out.endswith("0 0 0"), out[-300:])

    # ---------------------------------------------------------------- download my data
    req = urllib.request.Request(c.BASE + "/api/me/data")
    with owner.http.open(req, timeout=60) as resp:
        disp, data = resp.headers.get("Content-Disposition", ""), json.loads(resp.read())
    c.check("my data: it downloads as a file", "attachment" in disp and "d2d-relay-my-data.json" in disp, disp)
    c.check("my data: it is the person's own", data["you"]["email"] == owner.email and data["organisation"]["name"] == "Gov Test", data.get("you"))
    acts = data.get("activity_last_365_days") or []
    c.check("my data: it lists their sign-ins and what they did", any(a["action"] == "auth.login" for a in acts) and any(a["action"] == "project.deleted" for a in acts),
            [a["action"] for a in acts][:12])
    c.check("my data: it holds no one else's data", member.email not in json.dumps(data), "member's address found")
    s, r = member.get("/api/me/data")
    c.check("my data: each person gets their own", s == 200 and r["you"]["email"] == member.email, (s, r.get("you") if isinstance(r, dict) else r))

    # ---------------------------------------------------------------- routes that would send data out
    s, r = owner.post("/api/projects/anything-0000/github", {"repo": "x/y"})
    c.check("egress: pushing a dashboard to GitHub is not part of D2D Relay (404)", s == 404, (s, r))
    s, r = owner.post("/api/connections/c-1/write", {"object": "t", "payload": {}})
    c.check("egress: writing back into a warehouse is not part of D2D Relay (404)", s == 404, (s, r))

    # ---------------------------------------------------------------- the AI engine refuses paths outside the projects
    out = sh("""python3 - <<'EOF'
import json, urllib.request
def post(body):
    req = urllib.request.Request("http://127.0.0.1:8090/forget", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
print(post({"workdir": "../../etc"}), post({"workdir": "/etc"}), post({"workdir": "x", "sessions": ["../../y"]}), post({"workdir": "x", "sessions": ["*"]}))
EOF""")
    c.check("forget: the AI engine refuses folders and sessions outside its own", out.endswith("400 400 400 400"), out[-200:])

    # ---------------------------------------------------------------- retention sweep
    old = time.time() - 400 * 86400
    out = app(f"""
import time
from app import db
with db.use({tid!r}):
    db.run("INSERT INTO audit (ts, who, instance, action, object, detail) VALUES (?, 'x', 'web', 'gov.old', 'o', NULL)", ({old},))
    db.run("INSERT INTO audit (ts, who, instance, action, object, detail) VALUES (?, 'x', 'web', 'gov.new', 'o', NULL)", (time.time(),))
    db.run("INSERT INTO askd_cache (key, body, created) VALUES ('k-old', '{{}}', ?)", (time.time() - 30 * 86400,))
    db.run("INSERT INTO askd_cache (key, body, created) VALUES ('k-new', '{{}}', ?)", (time.time(),))
with db.use(db.PLATFORM):
    db.run("INSERT INTO otp_codes (id, email, code_hash, salt, created, expires, ip) VALUES ('gov-old', 'old@x.com', 'h', 's', ?, ?, '1.2.3.4')", ({old}, {old} + 600))
    db.run("INSERT INTO relay.tn_audit (ts, who, tenant_id, action) VALUES (?, 'x', 'p', 'gov.old')", ({old},))
print("ok")
""")
    c.check("sweep: old and new records are planted", out.endswith("ok"), out[-300:])
    sh("mkdir -p /data/backups && touch -d '@%d' /data/backups/relay-db-20200101-000000.dump /data/backups/relay-export-20200101.tar.gz "
       "&& touch /data/backups/relay-db-29990101-000000.dump && echo ok" % (time.time() - 60 * 86400), "relay")
    live_folder = f"/data/projects/.tenants/{tid}"
    sh(f"mkdir -p {live_folder}/askd-ukeep && chown relay {live_folder}/askd-ukeep", "root")
    c.check("sweep: a transcript of a folder that is gone is planted", plant_transcript("/data/projects/gone-dashboard-0000", UUID2).endswith("planted"))
    c.check("sweep: a 10-day-old transcript of a live folder is planted", plant_transcript(f"{live_folder}/askd-ukeep", UUID3, days_old=10).endswith("planted"))
    plant_transcript(f"{live_folder}/askd-ukeep", "bbbbbbbb-0000-0000-0000-000000000000")       # a fresh one stays
    out = app("""
import json
from app import governance
print(json.dumps(governance.sweep()))
""")
    try:
        res = json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        res = {}
    c.check("sweep: it runs", bool(res), out[-400:])
    after = app(f"""
from app import db
with db.use({tid!r}):
    a = [r["action"] for r in db.q("SELECT action FROM audit WHERE action LIKE 'gov.%'")]
    k = [r["key"] for r in db.q("SELECT key FROM askd_cache WHERE key IN ('k-old', 'k-new')")]
with db.use(db.PLATFORM):
    o = len(db.q("SELECT 1 AS x FROM otp_codes WHERE id = 'gov-old'"))
    t = len(db.q("SELECT 1 AS x FROM relay.tn_audit WHERE action = 'gov.old'"))
print(sorted(a), sorted(k), o, t)
""")
    c.check("sweep: logs older than a year go, newer ones stay", "['gov.new']" in after, after[-300:])
    c.check("sweep: cached answers older than 7 days go", "['k-new']" in after, after[-300:])
    c.check("sweep: year-old sign-in codes and control-plane logs go", after.endswith("0 0"), after[-300:])
    c.check("sweep: dumps made by hand over 30 days ago go; recent ones stay",
            not exists("/data/backups/relay-db-20200101-000000.dump") and not exists("/data/backups/relay-export-20200101.tar.gz")
            and exists("/data/backups/relay-db-29990101-000000.dump"))
    c.check("sweep: the transcript of a folder that is gone goes", not exists(f"/home/agent/.claude/projects/{slug('/data/projects/gone-dashboard-0000')}"))
    k = f"/home/agent/.claude/projects/{slug(live_folder + '/askd-ukeep')}"
    c.check("sweep: a live folder's 10-day-old transcript goes, today's stays",
            not exists(f"{k}/{UUID3}.jsonl") and not exists(f"/home/agent/.claude/tasks/{UUID3}") and exists(f"{k}/bbbbbbbb-0000-0000-0000-000000000000.jsonl"))
    sh("rm -f /data/backups/relay-db-29990101-000000.dump", "relay")

    # ---------------------------------------------------------------- erasing an organisation
    dom2 = f"erase{STAMP}.com"
    boss = c.Person(f"ed.boss@{dom2}")
    s, r = boss.sign_in("Erase Me", "Ed Boss")
    c.check("erase: a second organisation signs up", s == 200, (s, r))
    s, d2 = c.new_dashboard(boss)
    c.check("erase: it makes a dashboard", s == 200 and isinstance(d2, dict) and d2.get("id"), (s, d2))
    wait_idle(boss, d2["id"])
    tid2 = tenant_of(d2["id"])
    plant_transcript(f"/data/projects/.tenants/{tid2}/{d2['id']}", "cccccccc-0000-0000-0000-000000000000")
    run = lambda *a: subprocess.run(["docker", "exec", "-u", "relay", "-w", "/srv", WEB, "/opt/relay/bin/launch", "web", "python", "-m", "app.governance", *a],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
    r1 = run("erase-org", tid2, "Wrong Name")
    c.check("erase: a wrong name is refused", r1.returncode == 1 and "does not match" in r1.stdout, (r1.returncode, r1.stdout[-300:], r1.stderr[-300:]))
    r2 = run("erase-org", tid2, "Erase Me")
    c.check("erase: PASDACS erases it with its exact name", r2.returncode == 0 and '"erased"' in r2.stdout, (r2.returncode, r2.stdout[-400:], r2.stderr[-600:]))
    c.check("erase: its database schema is gone", sql(f"SELECT count(*) FROM pg_namespace WHERE nspname = 't_{tid2.replace('-', '_')}'") == "0")
    c.check("erase: its folders are gone", not exists(f"/data/projects/.tenants/{tid2}") and not exists(f"/data/state/tenants/{tid2}"))
    c.check("erase: the AI engine's transcripts of it are gone", not exists(f"/home/agent/.claude/projects/{slug(f'/data/projects/.tenants/{tid2}/' + d2['id'])}"))
    c.check("erase: its people's accounts and the organisation row are gone",
            sql(f"SELECT (SELECT count(*) FROM relay.tn_accounts WHERE home_tenant = '{tid2}') + (SELECT count(*) FROM relay.tn_orgs WHERE tenant_id = '{tid2}')") == "0")
    c.check("erase: the workspace is closed", sql(f"SELECT status FROM relay.tn_tenants WHERE id = '{tid2}'") == "closed")
    c.check("erase: its credit history stays, without names",
            sql(f"SELECT count(*) || '/' || count(user_name) || '/' || count(project_name) FROM relay.tn_credits WHERE tenant_id = '{tid2}'").endswith("/0/0")
            and not sql(f"SELECT count(*) FROM relay.tn_credits WHERE tenant_id = '{tid2}'").startswith("0"))
    c.check("erase: it is audited", sql(f"SELECT count(*) FROM relay.tn_audit WHERE action = 'd2d.org_erased' AND tenant_id = '{tid2}'") == "1")
    s, r = boss.get("/api/me")
    c.check("erase: its people are signed out", s == 401, (s, r))
    s, r = owner.get("/api/projects")
    c.check("erase: the other organisation is untouched", s == 200, (s, r))
    r3 = run("erase-org", "platform", "PASDACS")
    c.check("erase: the platform's own workspace cannot be erased", r3.returncode != 0, (r3.returncode, r3.stdout[-200:]))

    # ---------------------------------------------------------------- the AI engine's settings
    ms = json.loads(sh("cat /etc/claude-code/managed-settings.json"))
    c.check("settings: transcripts kept 7 days at most, no auto-memory", ms.get("cleanupPeriodDays") == 7 and ms.get("autoMemoryEnabled") is False, ms)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        c.check("governance: ran to the end", False, repr(e))
    bad = [n for n, ok in c.RESULTS if not ok]
    print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    sys.exit(len(bad))
