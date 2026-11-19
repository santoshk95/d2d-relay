"""Test stack only: upgrading from the image live today to the release candidate, on the same database and folders.
python -I -X utf8 upgrade_check.py <public> <admin> <old image> <new image>
Starts the stack on the old image, makes an organisation with a dashboard and a credit request (the old image's own
sign-up), switches the containers to the new image (volumes kept, as `docker compose up -d` does at a deploy), then
checks the data and the new columns, that a starting-credit request from before the upgrade can still be approved, and
that after it nobody signs up (item 56): an address without an account gets no code, and PASDACS creates organisations.
For a release from item 59 on: a payment made on the old image (seeded as a paid checkout) still opens after the
upgrade (and since item 85 buying online is back, beside Request credits), relay.tn_org_domains exists (item 60) and an older organisation reads an ontology
(item 61)."""
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
       "CODE_APP": "", "CODE_APP_AT": "", "CODE_STATIC": "", "CODE_STATIC_AT": ""}
STAMP = str(int(time.time()))[-6:]
REVIEWED = os.environ.get("OLD_HAS_PURPOSE") == "1"  # the old image reviews new organisations' starting credits (item 27 on)
HAS_PURPOSE = REVIEWED                               # its database has tn_credit_requests.purpose


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


def approve_start(email: str) -> None:
    """The old image: PASDACS approves a new organisation's starting credits the way it did from the command line."""
    rid = psql("SELECT id FROM relay.tn_credit_requests WHERE purpose = 'start' AND status = 'pending' AND email = '"
               + email.replace("'", "''") + "'").split()
    if rid:
        subprocess.run(["docker", "exec", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-m", "app.orgs",
                        "approve", rid[0]], capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")


def org_of(p: c.Person) -> dict:
    return (p.get("/api/me")[1] or {}).get("org") or {}


compose("down", "-v", image=OLD)
compose("up", "-d", image=OLD)
c.check(f"upgrade: the stack starts on the live image ({OLD})", healthy())
owner = c.Person(f"uma@upgrade{STAMP}.com")
s, r = owner.sign_in(f"Upgrade {STAMP}", "Uma Owner", provision=False)   # the old image's own sign-up
SIGNUP = s == 200                                     # an old image from item 56 on has none: PASDACS creates the organisation
if not SIGNUP:
    print("(the old image has no sign-up (item 56 on): PASDACS creates the organisation on its admin portal)", flush=True)
    s, r = owner.sign_in(f"Upgrade {STAMP}", "Uma Owner", again=True)
if REVIEWED and SIGNUP:                               # the live image reviews new organisations: PASDACS approves Uma's first
    approve_start(owner.email)
c.check("old image: a new organisation signs up (or, from item 56 on, PASDACS creates it) and gets its 50 at once",
        s == 200 and org_of(owner).get("credits") == 50, (s, r))
REVIEWED = REVIEWED and SIGNUP                        # an image without sign-up has no starting credits waiting for a review
waiting = c.Person(f"pia@pending{STAMP}.com")
if REVIEWED:                                          # an organisation whose starting credits are still waiting at the upgrade
    s, r = waiting.sign_in(f"Pending {STAMP}", "Pia Pending", provision=False)
    c.check("old image: a second organisation's starting credits wait for PASDACS", s == 200 and org_of(waiting).get("credits") == 0
            and (org_of(waiting).get("pending_request") or {}).get("purpose") == "start", org_of(waiting))
s, p = c.new_dashboard(owner)
pid = (p or {}).get("id")
c.check("old image: a dashboard is made (25 credits)", s == 200 and pid, (s, str(p)[:150]))
s, r = owner.post("/api/org/credit-request", {"credits": 100, "message": "Before the upgrade"})
rid = ((r or {}).get("request") or {}).get("id")
c.check("old image: a credit request waits", s == 200 and rid, (s, r))
cols = psql("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'relay' AND table_name = 'tn_credit_requests' AND column_name = 'purpose'")
if HAS_PURPOSE:                                       # an old image from item 27 on already has it (72b71a1 and later)
    c.check("old image: the database already has the 'purpose' column (item 27 is live)", cols == "1", cols)
else:
    c.check("old image: the database has no 'purpose' column yet", cols == "0", cols)
for _ in range(60):                                   # the test stack has no AI: the run fails and its 25 come back
    if (owner.get(f"/api/projects/{pid}")[1] or {}).get("status") == "error":
        break
    time.sleep(2)
time.sleep(2)
before = org_of(owner).get("credits")
ledger_before = [(x["kind"], x["delta"]) for x in owner.get("/api/org")[1].get("ledger", [])]
c.check("old image: the failed run's credits came back (start 50, charge -25, refund +25)",
        sorted(ledger_before) == sorted([("start", 50), ("charge", -25), ("refund", 25)]), ledger_before)
# item 59 removes buying online: a payment made on the old image (written as its payments.py wrote a paid checkout)
# must still open after the upgrade
me0 = owner.get("/api/me")[1] or {}
PAY = f"pay-upgrade{STAMP}"
now = time.time()
psql("INSERT INTO relay.tn_payments (id, tenant_id, org_name, user_id, user_name, email, credits, price, gst, amount, currency, live, status, "
     f"order_id, payment_id, method, created, paid) VALUES ('{PAY}', '{(me0.get('org') or {}).get('id')}', 'Upgrade {STAMP}', '{me0.get('id')}', "
     f"'Uma Owner', '{owner.email}', 100, 1000000, 180000, 1180000, 'INR', 0, 'paid', 'order_UPG{STAMP}', 'pay_UPG{STAMP}', 'upi', {now - 60}, {now})")
c.check("old image: a paid checkout of the organisation is in relay.tn_payments", psql(f"SELECT status FROM relay.tn_payments WHERE id = '{PAY}'") == "paid")

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
c.check("upgrade (item 56): the sign-up step's table is gone", psql("SELECT count(*) FROM information_schema.tables WHERE table_name = 'otp_signup'") == "0",
        psql("SELECT table_schema FROM information_schema.tables WHERE table_name = 'otp_signup'"))
c.check("upgrade (item 60): the database gained relay.tn_org_domains (an organisation's other email domains)",
        psql("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'relay' AND table_name = 'tn_org_domains'") == "1")
s, page = owner.get(f"/api/payments/{PAY}/receipt")
s2, o = owner.get("/api/org")
c.check("upgrade (item 59): a payment made before still opens as a receipt, and the Organisation page lists it",
        s == 200 and "Payment receipt" in str(page) and [x.get("id") for x in (o or {}).get("payments") or []] == [PAY], (s, str(page)[:150]))
s, r = owner.post("/api/payments/order", {"pack": "p100"})
pay = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("pay")
c.check("upgrade (item 85): buying online is back next to Request credits: /api/me says whether it is on, and an order is "
        "refused while PASDACS does not sell (403) or taken when it does (200)", isinstance(pay, dict) and "on" in pay
        and (s == 403 if not pay.get("on") else s == 200), (s, r, pay))
s, onto = owner.get("/api/ontology")
c.check("upgrade (item 61): an organisation from before has an ontology to read (the general pack's terms until it applies one)",
        s == 200 and onto.get("terms") == [] and onto.get("using_default") is True, (s, str(onto)[:200]))
adm = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s, r = adm.post(f"/api/admin/requests/{rid}/approve", {"credits": 100})
s2, led = owner.get("/api/org")
c.check("upgrade: approving the old request adds 100 as an adjustment", s == 200 and org_of(owner).get("credits") == before + 100
        and any(x["kind"] == "adjust" and x["delta"] == 100 for x in led.get("ledger", [])), (s, str(r)[:150]))
if REVIEWED:
    wid = (org_of(waiting).get("pending_request") or {}).get("id")
    s, r = adm.post(f"/api/admin/requests/{wid}/approve", {"credits": 50})
    s2, led = waiting.get("/api/org")
    c.check("upgrade (item 56): starting credits still waiting from before can be approved, as starting credits",
            s == 200 and org_of(waiting).get("credits") == 50 and any(x["kind"] == "start" and x["delta"] == 50 for x in (led or {}).get("ledger", [])),
            (s, str(r)[:150]))
s, me = owner.get("/api/me")
c.check("upgrade (item 29): the tour is due for someone who started today, and recording it works",
        me.get("tour") is True and owner.post("/api/me/tour", {"step": "done"})[0] == 200 and owner.get("/api/me")[1].get("tour") is False, me.get("tour"))
s, r = owner.post("/api/org/migration-request", {"source": ["qlik"], "target": ["powerbi", "looker"], "dashboards": 8, "message": "after the upgrade"})
c.check("upgrade (item 29): a Migration D2D request works on the upgraded database", s == 200 and "sent" in (r or {}), (s, r))
new = c.Person(f"nia@after{STAMP}.com")
t0 = time.time()
s, r = new.post("/auth/otp/start", {"email": new.email}, headers={"cf-connecting-ip": new.ip})
c.check("upgrade (item 56): after it nobody signs up: an address without an account gets no code", s == 200 and not c.code_now(c.WEB_C, new.email, t0),
        (s, r))
s, r = new.sign_in(f"After {STAMP}", "Nia", again=True)     # PASDACS creates the organisation first (d2d_checks.provision_account)
on = org_of(new)
c.check("upgrade (item 56): PASDACS creates an organisation; its owner signs in with 50 starting credits and nothing waiting",
        s == 200 and on.get("credits") == 50 and not on.get("pending_request"), on)
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
