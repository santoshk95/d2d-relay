"""Test stack only: Ask Relay's credits (python -I ask_credits_check.py <public> <admin>).

The test stack has no AI sign-in, so every question fails: that proves the credits of an unanswered question come back.
Conversations with 1, 5 and 6 answered questions are seeded in the test database to check when a question is charged.
"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402

stamp = str(int(time.time()))[-6:]
owner = c.Person(f"asha.owner@ask{stamp}.com")
s, r = owner.sign_in("Ask Test", "Asha Owner")
c.check("ask: a new organisation signs up with 50 credits", s == 200 and (owner.get("/api/me")[1].get("org") or {}).get("credits") == 50, (s, r))
org = owner.get("/api/me")[1]["org"]


def ledger():
    return owner.get("/api/org")[1].get("ledger", [])


def balance():
    return owner.get("/api/me")[1]["org"]["credits"]


# 1. a new conversation's first question is charged, and given back when it gets no answer
before = len(ledger())
s, r = owner.post("/api/askd/ask", {"question": "What were total sales last month?", "scope": {"kind": "team"}})
led = ledger()
new = led[:len(led) - before]
c.check("ask: the question fails on the test stack (no AI there), not with 402", s in (400, 503), (s, r))
c.check("ask: its 10 credits were charged and given back", any(x["kind"] == "charge" and x["what"] == "ask" and x["delta"] == -10 for x in new)
        and any(x["kind"] == "refund" and x["what"] == "ask" and x["delta"] == 10 for x in new) and balance() == 50, (new, balance()))

# 2. seeded conversations: when the next question is charged, and what the page is told
uid = owner.get("/api/me")[1]["id"]
seed = f"""
import json, secrets, time
from app import db
db.init_tenant({org['id']!r})              # a script's own process: open the tenant the way the app does at first use
with db.use({org['id']!r}):
    for n in (1, 5, 6):
        tid = 't-seed{stamp}-' + str(n)
        db.run('INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES (?, ?, ?, ?, ?, ?)',
               (tid, {uid!r}, json.dumps({{'kind': 'team'}}), 'seeded', time.time(), time.time()))
        for i in range(n):
            for role in ('user', 'assistant'):
                db.run('INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, ?, ?, ?)',
                       (role[0] + '-' + secrets.token_hex(6), tid, role, json.dumps({{'text': 'q', 'summary': 'a'}}), time.time()))
print('seeded')
"""
out = subprocess.run(["docker", "exec", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-c", seed],
                     capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
c.check("ask: three conversations seeded (1, 5 and 6 answers)", "seeded" in out.stdout, (out.stdout[-300:], out.stderr[-500:]))
for n, used, left in ((1, 10, 4), (5, 10, 0), (6, 20, 4)):
    s, k = owner.get(f"/api/askd/costs?thread=t-seed{stamp}-{n}")
    c.check(f"ask: after {n} answers the page is told {used} credits used, {left} questions left",
            s == 200 and k.get("used") == used and k.get("left") == left and k.get("per") == 10 and k.get("questions") == 5, (s, k))
before = len(ledger())
s, r = owner.post("/api/askd/ask", {"question": "And the month before?", "scope": {"kind": "team"}, "thread_id": f"t-seed{stamp}-1"})
c.check("ask: the 2nd question of a conversation is not charged", len(ledger()) == before and balance() == 50, (s, r, ledger()[:2]))
before = len(ledger())
s, r = owner.post("/api/askd/ask", {"question": "And by region?", "scope": {"kind": "team"}, "thread_id": f"t-seed{stamp}-5"})
new = ledger()[:len(ledger()) - before]
c.check("ask: the 6th question is charged (and given back here: no answer)",
        [x["kind"] for x in new] == ["refund", "charge"] and all(x["what"] == "ask" for x in new) and balance() == 50, (s, new))

# 3. not enough credits
admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s, r = admin.post(f"/api/admin/orgs/{org['id']}/credits", {"credits": -45, "note": "Test: 5 left"})
c.check("ask: PASDACS leaves the organisation 5 credits", s == 200 and balance() == 5, (s, r))
s, r = owner.post("/api/askd/ask", {"question": "Top products?", "scope": {"kind": "team"}})
c.check("ask: with 5 credits a new conversation is refused (402), saying why", s == 402 and "Ask Relay uses 10 credits for up to 5 questions" in str(c.detail_of(r)), (s, r))
s, r = owner.post("/api/askd/ask", {"question": "And by store?", "scope": {"kind": "team"}, "thread_id": f"t-seed{stamp}-1"})
c.check("ask: ... but a conversation with questions left goes on (not 402)", s != 402, (s, r))
s, a = admin.get("/api/admin/orgs")
c.check("ask: the admin portal shows the new start and prices", s == 200 and a.get("start") == 50 and (a.get("costs") or {}).get("ask") == 10, (s, a.get("start"), a.get("costs")))
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed")
sys.exit(len(bad))
