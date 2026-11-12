"""Test stack only: item 31's accounts (the user, 2026-11-12): owners see every dashboard with who made it; Remove
deletes a person at once (their work stays, held by the main owner, marked as made by a former member); Delete my
account; the main owner deletes the whole organisation after typing its name.
python -I -X utf8 accounts_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check


def sql(q: str) -> str:
    r = subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-At", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def wait_idle(p, pid):
    for _ in range(90):
        if (p.get(f"/api/projects/{pid}")[1] or {}).get("status") in ("error", "awaiting_kpis", "awaiting_review", "done"):
            return
        time.sleep(2)


dom = f"acct{c.STAMP}.com"
owner, mia, max_ = c.Person(f"ola.owner@{dom}"), c.Person(f"mia.member@{dom}"), c.Person(f"max.member@{dom}")
s, r = owner.sign_in("Accounts Test", "Ola Owner")
check("setup: an organisation signs up", s == 200, (s, r))
mia.sign_in(person="Mia Member")
max_.sign_in(person="Max Member")
tid = sql(f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = '{dom}'")
schema = "t_" + tid.replace("-", "_")
mia_id = sql(f"SELECT id FROM \"{schema}\".users WHERE email = 'mia.member@{dom}'")
s, d = c.new_dashboard(mia)
mpid = (d or {}).get("id")
check("setup: Mia makes a dashboard", s == 200 and mpid, (s, str(d)[:120]))
wait_idle(mia, mpid)
now = time.time()
sql(f"INSERT INTO \"{schema}\".askd_threads (id, user_id, scope, title, created, updated) VALUES ('t-mia1', '{mia_id}', '{{\"kind\": \"team\"}}', 'Mia asks', {now}, {now})")
sql(f"INSERT INTO \"{schema}\".askd_messages (id, thread_id, role, body, created) VALUES ('q-mia1', 't-mia1', 'user', '{{\"text\": \"Sales?\"}}', {now})")

# ---------------------------------------------------------------- owners see every dashboard, with its maker
s, lst = owner.get("/api/projects")
mine = next((x for x in lst if x.get("id") == mpid), None) if isinstance(lst, list) else None
check("makers: the owner sees Mia's dashboard, with Mia as its maker", mine and mine.get("owner") == "Mia Member", mine and {k: mine.get(k) for k in ("owner", "via")})
s, st = owner.get(f"/api/projects/{mpid}")
check("makers: the dashboard itself says who made it", s == 200 and st.get("maker") == "Mia Member", (s, st.get("maker")))
s, st = mia.get(f"/api/projects/{mpid}")
check("makers: to its maker it says you", s == 200 and st.get("maker") == "you", (s, st.get("maker")))

# ---------------------------------------------------------------- Remove deletes at once; the work stays
s, r = owner.delete(f"/api/org/people/{mia_id}")
check("remove: the owner removes Mia (200)", s == 200, (s, str(r)[:150]))
row = sql(f"SELECT name || '|' || email || '|' || active FROM \"{schema}\".users WHERE id = '{mia_id}'")
check("remove: her name and address are gone at once (Former member, no address, switched off)",
      row.startswith("Former member|deleted-") and row.endswith("|0") and "mia.member" not in row, row)
s, r = mia.get("/api/me")
check("remove: her session ended at once (401)", s == 401, s)
check("remove: her Ask Relay conversation is deleted", sql(f"SELECT count(*) FROM \"{schema}\".askd_threads WHERE user_id = '{mia_id}'") == "0")
check("remove: her sign-in codes are deleted (the platform's table)", sql(f"SELECT count(*) FROM public.otp_codes WHERE lower(email) = 'mia.member@{dom}'") == "0")
check("remove: her address is free (no account maps to it)", sql(f"SELECT count(*) FROM relay.tn_accounts WHERE lower(email) = 'mia.member@{dom}'") == "0")
owner_of = sql(f"SELECT o.owner_id = p.owner_id FROM relay.tn_orgs o, \"{schema}\".projects p WHERE o.tenant_id = '{tid}' AND p.id = '{mpid}'")
check("remove: her dashboard stays, held by the main owner", owner_of == "t", owner_of)
s, lst = owner.get("/api/projects")
mine = next((x for x in lst if x.get("id") == mpid), None) if isinstance(lst, list) else None
check("remove: the list marks it as made by a former member", mine and mine.get("made_by") == "former member", mine and mine.get("made_by"))
s, st = owner.get(f"/api/projects/{mpid}")
check("remove: the dashboard says made by a former member", st.get("maker") == "Former member", st.get("maker"))
s, o = owner.get("/api/org")
check("remove: she is not listed under Removed (nothing to add back)", not any("Former" in (x.get("name") or "") for x in o.get("removed", [])),
      o.get("removed"))
check("remove: the logs keep no address of hers", sql(f"SELECT count(*) FROM \"{schema}\".audit WHERE detail LIKE '%mia.member@{dom}%'") == "0")
again = c.Person(f"mia.member@{dom}")
s, r = again.sign_in()
check("block: her address cannot join again: the owner removed it (403, saying so)", s == 403 and "removed this address" in str(c.detail_of(r)), (s, r))
s, o = owner.get("/api/org")
check("block: the owner sees it under Blocked", any(b.get("email") == f"mia.member@{dom}" for b in o.get("blocked", [])), o.get("blocked"))
s, r = mia.get("/api/org")
s, r = c.Person(f"zed.member@{dom}").sign_in()
check("block: nobody else at the domain is affected", s == 200, (s, r))
s, r = again.post("/api/org/unblock", {"email": f"mia.member@{dom}"})
check("block: someone not signed in cannot unblock (401)", s == 401, (s, r))
s, r = owner.post("/api/org/unblock", {"email": f"mia.member@{dom}"})
check("block: the owner unblocks her", s == 200 and not any(b.get("email") == f"mia.member@{dom}" for b in r.get("blocked", [])), (s, r))
s, r = owner.post("/api/org/unblock", {"email": f"mia.member@{dom}"})
check("block: unblocking twice says it is not blocked (404)", s == 404, (s, r))
s, r = again.sign_in(again=True)
s2, me = again.get("/api/me")
check("block: unblocked, her address joins again as a new person", s == 200 and me.get("id") and me.get("id") != mia_id, (s, me.get("id")))

ann = c.Person(f"ann.again@{dom}")
ann.sign_in()
ann_id = sql(f"SELECT id FROM \"{schema}\".users WHERE email = 'ann.again@{dom}'")
s, r = owner.delete(f"/api/org/people/{ann_id}")
check("remove: the owner removes Ann", s == 200, (s, str(r)[:120]))
s, r = owner.post("/api/org/people", {"email": f"ann.again@{dom}", "role": "member"})
check("remove: an owner can add a removed person's address back, as a new person (no clash), which lifts the block", s == 200
      and not any(b.get("email") == f"ann.again@{dom}" for b in r.get("blocked", [])), (s, str(r)[:200]))
new_ann = sql(f"SELECT id FROM \"{schema}\".users WHERE email = 'ann.again@{dom}'")
check("remove: the address added back is a new account", new_ann and new_ann != ann_id, (ann_id, new_ann))

# ---------------------------------------------------------------- Delete my account
s, r = max_.post("/api/me/delete", {"confirm": "delete me"})
check("self: a wrong confirmation is refused (400)", s == 400, (s, r))
s, r = owner.post("/api/me/delete", {"confirm": "DELETE"})
check("self: the main owner is told to hand over or delete the organisation (409)", s == 409, (s, r))
s, r = max_.post("/api/me/delete", {"confirm": "DELETE"})
check("self: Max deletes his own account (signed out)", s == 200 and r.get("signed_out"), (s, r))
check("self: his session ended", max_.get("/api/me")[0] == 401)
check("self: the owners are told", sql(f"SELECT count(*) FROM \"{schema}\".notifications WHERE title = 'Someone deleted their account'") != "0")
s, r = max_.sign_in(again=True)
check("self: deleting your own account blocks nothing: Max can join again as a new person", s == 200, (s, r))

# ---------------------------------------------------------------- the main owner deletes the organisation
s, r = again.post("/api/org/delete", {"confirm": "Accounts Test"})
check("org: someone who is not the main owner cannot delete it (403)", s == 403, (s, r))
s, r = owner.post("/api/org/delete", {"confirm": "Accounts"})
check("org: the wrong name is refused (400)", s == 400, (s, r))
s, r = owner.post("/api/org/delete", {"confirm": " accounts  TEST "})
check("org: the main owner deletes it, typing its name (any case and spacing)", s == 200 and r.get("erased"), (s, r))
check("org: it is gone from the platform", sql(f"SELECT count(*) FROM relay.tn_orgs WHERE tenant_id = '{tid}'") == "0")
check("org: its workspace is gone", sql(f"SELECT count(*) FROM information_schema.schemata WHERE schema_name = '{schema}'") == "0")
check("org: the owner's session is gone", owner.get("/api/me")[0] in (401, 403))
check("org: PASDACS is told", sql("SELECT count(*) FROM public.notifications WHERE title = 'Accounts Test deleted itself'") != "0")
s, r = c.Person(f"new.owner@{dom}").sign_in("Accounts Again", "New Owner")
check("org: the domain can sign up again as a new organisation", s == 200, (s, r))

# ---------------------------------------------------------------- item 32's follow-up: PASDACS's own people and the admin portal
pasdacs = c.signed_in("info@pasdacs.com", c.BASE)
pat = c.Person(f"pat.test{c.STAMP}@pasdacs.com")
s, r = pat.sign_in()
check("pasdacs: a PASDACS address joins PASDACS on the public site", s == 200, (s, r))
s, o = pasdacs.get("/api/org")
pat_id = next((x["id"] for x in o.get("people", []) if x.get("email") == pat.email), None)
s, r = pasdacs.delete(f"/api/org/people/{pat_id}")
check("pasdacs: its main owner removes them (blocked)", s == 200 and any(b.get("email") == pat.email for b in r.get("blocked", [])),
      (s, str(r)[:200]))
s, r = c.Person(pat.email, c.ADMIN_BASE).sign_in()
check("pasdacs: the removed address cannot sign in to the admin portal either (403)", s == 403 and "removed this address" in str(c.detail_of(r)),
      (s, r))
s, r = pasdacs.post("/api/org/unblock", {"email": pat.email})
check("pasdacs: unblocked again (tidy)", s == 200, (s, str(r)[:120]))
ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
