"""Test stack only: upgrading from the image live today to the release candidate, on the same database and folders.
python -I -X utf8 upgrade_check.py <public> <admin> <old image> <new image>
Starts the stack on the old image, makes an organisation with a dashboard and a credit request, switches the
containers to the new image (volumes kept, as `docker compose up -d` does at a deploy), then checks the data and the
new columns, and that a new sign-up gets the starting-credit review."""
import json
import os
import subprocess
import sys
import time

OLD, NEW = sys.argv[3], sys.argv[4]
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

STACK = os.path.join(HERE, "..", "stack")           # tests/stack: its compose file and the .env stack.sh wrote
ENV = {**os.environ, **dict(x.strip().split("=", 1) for x in open(os.path.join(STACK, ".env"))
                            if "=" in x and not x.lstrip().startswith("#")),
       "CODE_APP": "", "CODE_APP_AT": "", "CODE_STATIC": "", "CODE_STATIC_AT": "", "TEST_START_REVIEW": "1"}
STAMP = str(int(time.time()))[-6:]


def compose(*args, image: str):
    return subprocess.run(["docker", "compose", "-p", "d2d-relay-test", *args], cwd=STACK, env={**ENV, "TEST_IMAGE": image},
                          capture_output=True, text=True)


def healthy() -> bool:
    for _ in range(90):
        st = [subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", n], capture_output=True, text=True).stdout.strip()
              for n in ("d2d-relay-test-web", "d2d-relay-test-admin")]
        if st == ["healthy", "healthy"]:
            return True
        time.sleep(5)
    return False


def psql(q: str) -> str:
    return subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                          capture_output=True, text=True).stdout.strip()


compose("down", "-v", image=OLD)
compose("up", "-d", image=OLD)
c.check(f"upgrade: the stack starts on the live image ({OLD})", healthy())
owner = c.Person(f"uma@upgrade{STAMP}.com")
s, r = owner.sign_in(f"Upgrade {STAMP}", "Uma Owner")
if os.environ.get("OLD_HAS_PURPOSE") == "1":         # the live image reviews new organisations: PASDACS approves Uma's first
    c.approve_start(owner.email)
c.check("old image: a new organisation signs up and gets its 50 at once", s == 200 and (owner.get("/api/me")[1].get("org") or {}).get("credits") == 50, (s, r))
s, p = c.new_dashboard(owner)
pid = (p or {}).get("id")
c.check("old image: a dashboard is made (25 credits)", s == 200 and pid, (s, str(p)[:150]))
s, r = owner.post("/api/org/credit-request", {"credits": 100, "message": "Before the upgrade"})
rid = ((r or {}).get("request") or {}).get("id")
c.check("old image: a credit request waits", s == 200 and rid, (s, r))
cols = psql("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'relay' AND table_name = 'tn_credit_requests' AND column_name = 'purpose'")
if os.environ.get("OLD_HAS_PURPOSE") == "1":         # an old image from item 27 on already has it (72b71a1 and later)
    c.check("old image: the database already has the 'purpose' column (item 27 is live)", cols == "1", cols)
else:
    c.check("old image: the database has no 'purpose' column yet", cols == "0", cols)
for _ in range(60):                                   # the test stack has no AI: the run fails and its 25 come back
    if (owner.get(f"/api/projects/{pid}")[1] or {}).get("status") == "error":
        break
    time.sleep(2)
time.sleep(2)
before = (owner.get("/api/me")[1].get("org") or {}).get("credits")
ledger_before = [(x["kind"], x["delta"]) for x in owner.get("/api/org")[1].get("ledger", [])]
c.check("old image: the failed run's credits came back (start 50, charge -25, refund +25)",
        sorted(ledger_before) == sorted([("start", 50), ("charge", -25), ("refund", 25)]), ledger_before)

compose("up", "-d", image=NEW)
c.check(f"upgrade: web and admin restart on the release candidate ({NEW}), same volumes", healthy())
img = subprocess.run(["docker", "inspect", "-f", "{{.Config.Image}}", "d2d-relay-test-web"], capture_output=True, text=True).stdout.strip()
c.check("upgrade: the web container runs the new image", img == NEW, img)
s, me = owner.get("/api/me")
o = (me or {}).get("org") or {}
c.check("upgrade: Uma's session survives the restart", s == 200, (s, me))
c.check("upgrade: her credits and their history are as before", o.get("credits") == before and sorted(
    (x["kind"], x["delta"]) for x in owner.get("/api/org")[1].get("ledger", [])) == sorted(ledger_before), (o.get("credits"), before))
pend = o.get("pending_request") or {}
c.check("upgrade: her waiting request is kept, as a request for more (not starting credits)", pend.get("id") == rid and pend.get("purpose") == "more", pend)
s, d = owner.get(f"/api/projects/{pid}")
c.check("upgrade: her dashboard opens", s == 200 and d.get("id") == pid, (s, str(d)[:120]))
for table, col in (("tn_credit_requests", "purpose"), ("tn_payments", "billing"), ("tn_payments", "invoice_no"), ("tn_payments", "invoice"),
                   ("tn_payments", "base_amount"), ("tn_orgs", "billing")):
    n = psql(f"SELECT count(*) FROM information_schema.columns WHERE table_schema = 'relay' AND table_name = '{table}' AND column_name = '{col}'")
    c.check(f"upgrade: the database gained {table}.{col}", n == "1", n)
adm = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s, r = adm.post(f"/api/admin/requests/{rid}/approve", {"credits": 100})
s2, led = owner.get("/api/org")
c.check("upgrade: approving the old request adds 100 as an adjustment", s == 200 and (owner.get("/api/me")[1].get("org") or {}).get("credits") == before + 100
        and any(x["kind"] == "adjust" and x["delta"] == 100 for x in led.get("ledger", [])), (s, str(r)[:150]))
s, me = owner.get("/api/me")
c.check("upgrade (item 29): the tour is due for someone who started today, and recording it works",
        me.get("tour") is True and owner.post("/api/me/tour", {"step": "done"})[0] == 200 and owner.get("/api/me")[1].get("tour") is False, me.get("tour"))
s, r = owner.post("/api/org/migration-request", {"source": ["qlik"], "target": ["powerbi", "looker"], "dashboards": 8, "message": "after the upgrade"})
c.check("upgrade (item 29): a Migration D2D request works on the upgraded database", s == 200 and "sent" in (r or {}), (s, r))
new = c.Person(f"nia@after{STAMP}.com")
s, r = new.sign_in(f"After {STAMP}", "Nia")
on = (new.get("/api/me")[1].get("org") or {})
c.check("upgrade: a sign-up after the upgrade waits for PASDACS (0 credits, starting credits pending)",
        s == 200 and on.get("credits") == 0 and (on.get("pending_request") or {}).get("purpose") == "start", on)
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
