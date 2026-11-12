"""Test stack only: security across sites, roles and organisations (the security audit of 2026-11-11).
python -I -X utf8 sec_check.py http://127.0.0.1:8103 http://127.0.0.1:8104

Anonymous access to every route; sign-in hardening; CSRF; session cookies tampered with across organisations and
sites; owner / member / removed person; one organisation against another's dashboards, files, people, requests and
payments; uploads and paths; security headers and the Range guard; the platform console off the public site; the
starting-credit review (when the stack runs it). Never the live site.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

P, A = c.BASE, c.ADMIN_BASE
STAMP = str(int(time.time()))[-6:]
BLOCKED = "That is not part of D2D Relay."
ROUTES = os.path.join(HERE, "..", "audit", "routes-public.txt")     # tests/audit: regenerate with routes.py after adding routes
RZP = "http://127.0.0.1:8105"
check, detail = c.check, c.detail_of


def raw(method: str, base: str, path: str, headers: dict | None = None, body: bytes | None = None):
    """A request with no session: (status, headers, text). Redirects are not followed."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")


def with_cookie(base: str, path: str, name: str, value: str, method: str = "GET", headers: dict | None = None):
    s, h, t = raw(method, base, path, {"Cookie": f"{name}={value}", **(headers or {})})
    try:
        return s, json.loads(t)
    except ValueError:
        return s, t


def jar_value(p: c.Person, name: str) -> str | None:
    return next((k.value for k in p.jar if k.name == name), None)


def section(name: str) -> None:
    print(f"--- {name}", flush=True)


def logs(container: str, since: float) -> str:
    out = subprocess.run(["docker", "logs", "--since", str(int(since) - 2), container], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout + out.stderr


def sql(q: str) -> str:
    return subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                          capture_output=True, text=True, check=True).stdout.strip()


def sign_up(email: str, org: str, person: str, approve: bool = True) -> c.Person:
    """A new person (and a new organisation for a new domain); review on: approve its starting credits unless asked not to."""
    p = c.Person(email)
    keep = os.environ.get("D2D_TEST_APPROVE_START")
    os.environ["D2D_TEST_APPROVE_START"] = "1" if approve else "0"
    try:
        s, r = p.sign_in(org, person)
    finally:
        os.environ["D2D_TEST_APPROVE_START"] = keep or "0"
    check(f"setup: {email} signs in", s == 200, (s, r))
    return p


def org_of(p: c.Person) -> dict:
    return (p.get("/api/me")[1] or {}).get("org") or {}


def people_ids(p: c.Person) -> dict:
    s, o = p.get("/api/org")
    return {x["email"]: x["id"] for x in (o or {}).get("people", [])}


def new_dashboard(p: c.Person, name: str, files=None):
    s, r = p.form("/api/projects", {"prompt": "Sales by region and month", "data_mode": "upload", "name": name},
                  files or {"files": ("sales.csv", b"region,month,sales\nNorth,2026-01,10\nSouth,2026-01,12\n")})
    return s, r


# ---------------------------------------------------------------------------------------------------- anonymous
section("anonymous: every route of the public site, the admin portal")
routes = []
for line in open(ROUTES, encoding="utf-8"):
    f = line.rstrip("\n").split("\t")
    if len(f) >= 3 and f[0] == "OPEN" and f[2].startswith("/api/"):
        routes.append((f[1], re.sub(r"\{[^}]+\}", "x-audit-1", f[2])))
bad = []
for method, path in routes:
    s, h, t = raw(method, P, path, {"Content-Type": "application/json"}, b"{}" if method != "GET" else None)
    want = (400,) if path == "/api/payments/webhook" else (401, 404)
    if s not in want:
        bad.append((method, path, s, t[:80]))
check(f"anonymous: none of the {len(routes)} reachable API routes answers without a session (401/404; the webhook 400)",
      not bad and len(routes) > 100, bad[:8])
for path in ("/api/me", "/api/admin/orgs", "/api/admin/requests", "/api/admin/payments"):
    s, h, t = raw("GET", A, path)
    check(f"anonymous: admin portal {path} needs its sign-in (401)", s == 401, (s, t[:100]))
s, h, t = raw("GET", A, "/api/projects")
check("anonymous: the admin portal answers none of the public site's APIs (404)", s == 404, (s, t[:100]))
s, h, t = raw("GET", A, "/api/me", {"cf-connecting-ip": "203.0.113.9"})
check("admin portal: a request through Cloudflare without an Access token is refused (403)", s == 403, (s, t[:120]))
s, h, t = raw("GET", P, "/metrics")
check("anonymous: /metrics is off without its token (404)", s == 404, s)
s, h, t = raw("GET", P, "/healthz")
check("anonymous: /healthz answers and says nothing private", s == 200 and set(json.loads(t)) <= {"ok", "database", "instance", "portal"}, t)
for base, path in ((P, "/login.html"), (P, "/privacy.html"), (P, "/api/me"), (P, "/healthz"), (A, "/login.html"), (P, "/js/36-org.js")):
    s, h, t = raw("GET", base, path)
    ok = (h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "SAMEORIGIN"
          and "frame-ancestors 'self'" in h.get("content-security-policy", "") and h.get("referrer-policy"))
    check(f"headers: {'admin' if base == A else 'public'} {path} has the security headers", ok, {k: h.get(k) for k in (
        "x-content-type-options", "x-frame-options", "content-security-policy", "referrer-policy")})
s, h, t = raw("GET", P, "/login.html", {"Range": "bytes=" + ",".join(f"{i}-{i}" for i in range(0, 3000, 2))})
check("headers: a Range of 1,500 parts gets the whole file (200)", s == 200, s)
s, h, t = raw("GET", P, "/login.html", {"Range": "bytes=0-9"})
check("headers: one range still works (206)", s == 206 and len(t) == 10, (s, len(t)))

# ---------------------------------------------------------------------------------------------------- sign-in
section("sign-in hardening")
for addr in ("someone@gmail.com", "someone@outlook.com", "someone@yahoo.co.in", "someone@mailinator.com", "a@b"):
    s, r = c.Person(addr).post("/auth/otp/start", {"email": addr})
    check(f"sign-in: {addr} is refused", s == 400, (s, r))
s, r = c.Person(f"x@acme{STAMP}.com", A).post("/auth/otp/start", {"email": f"x@acme{STAMP}.com"})
check("sign-in: the admin portal refuses an address outside PASDACS (403)", s == 403, (s, r))
v = c.Person(f"vera@guess{STAMP}.com")
hdr = {"cf-connecting-ip": v.ip}
t0 = time.time()
s, r = v.post("/auth/otp/start", {"email": v.email}, headers=hdr)
code = c.code_from_logs(c.WEB_C, v.email, t0)
check("sign-in: a code is sent", s == 200 and code, (s, r))
s, r = v.post("/auth/otp/start", {"email": v.email}, headers=hdr)
check("sign-in: a second code within the minute is refused (429)", s == 429, (s, r))
wrong = f"{(int(code) + 1) % 1000000:06d}"
for i in range(5):
    v.post("/auth/otp/verify", {"email": v.email, "code": wrong})
s, r = v.post("/auth/otp/verify", {"email": v.email, "code": code})
check("sign-in: after 5 wrong tries the right code no longer works", s == 400, (s, r))
s, r = v.post("/auth/otp/organisation", {"name": "No Cookie", "person": "x"})
check("sign-in: naming an organisation without the sign-up step is refused (401)", s == 401, (s, r))
c.forget_codes(v.email)
t0 = time.time()
v.post("/auth/otp/start", {"email": v.email}, headers=hdr)
code = c.code_from_logs(c.WEB_C, v.email, t0)
req = urllib.request.Request(P + "/auth/otp/verify", data=json.dumps({"email": v.email, "code": code}).encode(), method="POST",
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=60) as resp:
    setcookie = resp.headers.get_all("Set-Cookie") or []
check("sign-in: the sign-up step's cookie is HttpOnly, SameSite=Lax and limited to /auth/otp/",
      any("d2d_signup=" in x and "HttpOnly" in x and "samesite=lax" in x.lower() and "Path=/auth/otp/" in x for x in setcookie), setcookie)
s, r = v.post("/auth/otp/verify", {"email": v.email, "code": code})
check("sign-in: a code works once", s == 400, (s, r))
for i in range(20):
    sql(f"INSERT INTO otp_codes (id, email, code_hash, salt, created, expires, used, ip) VALUES ('t{STAMP}{i}', 'dana@cap{STAMP}.com', 'x', 'x', "
        f"{time.time() - 7200 - i}, {time.time() - 7000}, {time.time() - 7000}, '192.0.2.1')")
d = c.Person(f"dana@cap{STAMP}.com")
s, r = d.post("/auth/otp/start", {"email": d.email}, headers={"cf-connecting-ip": d.ip})
check("sign-in: at most 20 codes a day per address (S13)", s == 429 and "today" in str(detail(r)), (s, r))

# ---------------------------------------------------------------------------------------------------- people and organisations
section("organisations and roles")
dom_a, dom_b = f"alpha{STAMP}.com", f"beta{STAMP}.com"
a1 = sign_up(f"ann@{dom_a}", f"Alpha {STAMP}", "Ann Owner")
a2 = sign_up(f"bob@{dom_a}", None, None)
b1 = sign_up(f"cat@{dom_b}", f"Beta {STAMP}", "Cat Owner")
oa, ob = org_of(a1), org_of(b1)
check("setup: Ann owns Alpha, Bob joined it as a member", oa.get("is_owner") and org_of(a2).get("id") == oa.get("id")
      and not org_of(a2).get("is_owner"), (oa, org_of(a2)))
check("setup: Alpha and Beta are different workspaces", oa.get("id") and ob.get("id") and oa["id"] != ob["id"])
if (oa.get("credits") or 0) < 50:
    c.approve_start(a1.email)
if (ob.get("credits") or 0) < 25:
    c.approve_start(b1.email)
s, pa1 = new_dashboard(a1, "Ann's private dashboard")
s2, pa2 = new_dashboard(a2, "Bob's private dashboard")
s3, pb1 = new_dashboard(b1, "Cat's dashboard")
check("setup: each makes a dashboard", s == 200 and s2 == 200 and s3 == 200, (s, s2, s3, str(pa1)[:120]))
A1, A2, B1 = pa1.get("id"), pa2.get("id"), pb1.get("id")
time.sleep(2)
s, r = a2.get(f"/api/projects/{A1}")
check("member: Bob cannot open Ann's private dashboard (404)", s == 404, (s, r))
s, r = a1.get(f"/api/projects/{A2}")
check("owner: Ann can open Bob's dashboard (owners see every dashboard; the notice says so)", s == 200, (s, detail(r)))
for method, path in (("DELETE", f"/api/projects/{A1}"), ("POST", f"/api/projects/{A1}/feedback")):
    s, r = a2.call(method, path, {} if method == "POST" else None)
    check(f"member: Bob cannot {method} {path.split('/')[-1]} on Ann's dashboard (404)", s == 404, (s, r))
ids = people_ids(a1)
for name, (method, path, body) in {"rename the organisation": ("PATCH", "/api/org", {"name": "Hijacked"}),
                                   "add people": ("POST", "/api/org/people", {"email": f"eve@{dom_a}", "role": "owner"}),
                                   "make himself an owner": ("PATCH", f"/api/org/people/{ids.get(a2.email)}", {"role": "owner"}),
                                   "remove the owner": ("DELETE", f"/api/org/people/{ids.get(a1.email)}", None),
                                   "take the main ownership": ("POST", "/api/org/transfer", {"uid": ids.get(a2.email)})}.items():
    s, r = a2.call(method, path, body)
    check(f"member: Bob cannot {name} (403)", s == 403, (s, r))

section("one organisation against another")
for method, path, body in (("GET", f"/api/projects/{A1}", None), ("GET", f"/api/projects/{A1}/activity", None),
                           ("GET", f"/api/projects/{A1}/activity/export", None), ("GET", f"/api/projects/{A1}/data/sales.csv", None),
                           ("GET", f"/api/projects/{A1}/files/request.md", None), ("GET", f"/api/projects/{A1}/prototype/live", None),
                           ("GET", f"/api/projects/{A1}/shares", None), ("GET", f"/api/projects/{A1}/download", None),
                           ("POST", f"/api/projects/{A1}/feedback", {}), ("POST", f"/api/projects/{A1}/retry", {}),
                           ("POST", f"/api/projects/{A1}/stop", {}), ("PUT", f"/api/projects/{A1}/shares", {"grants": []}),
                           ("DELETE", f"/api/projects/{A1}", None), ("POST", f"/api/export/project/{A1}?fmt=pdf", {}),
                           ("POST", f"/api/reviews/{A1}/r-1", {"decision": "approve", "comment": ""})):
    s, r = b1.call(method, path, body)
    check(f"cross-organisation: Cat {method} {path.replace(A1, '<Alpha dashboard>')} -> 404", s == 404, (s, r))
s, lst = b1.get("/api/projects")
check("cross-organisation: Cat's dashboard list has none of Alpha's", s == 200 and not {A1, A2} & {x.get("id") for x in lst}, [x.get("id") for x in lst or []])
for method, path, body in (("PATCH", f"/api/org/people/{ids.get(a2.email)}", {"role": "owner"}),
                           ("DELETE", f"/api/org/people/{ids.get(a2.email)}", None),
                           ("POST", "/api/org/transfer", {"uid": ids.get(a1.email)})):
    s, r = b1.call(method, path, body)
    check(f"cross-organisation: Cat {method} {path.split('/api/')[1].split('/')[0:3]} on Alpha's people -> 404", s == 404, (s, r))
s, o = b1.get("/api/org")
check("cross-organisation: Cat's organisation lists only Beta's people", s == 200 and all(x["email"].endswith(dom_b) for x in o["people"]), o.get("people"))

section("session cookies tampered with")
va = jar_value(a1, "d2d_session")
tid_a, sid = va.split("~", 1)
tid_b = ob["id"]
for label, value in ((f"another organisation's workspace ({tid_b}~...)", f"{tid_b}~{sid}"), ("no workspace", sid),
                     ("a workspace that does not exist", f"nosuch~{sid}"), ("a guessed session", f"{tid_a}~{'A' * 43}")):
    s, r = with_cookie(P, "/api/me", "d2d_session", value)
    check(f"cookie: {label} signs nobody in (401)", s == 401, (s, r))
s, r = with_cookie(P, "/api/me", "d2d_session", va, headers={"X-D2D-Tenant": tid_b})
check("cookie: a tenant header cannot move Ann into Beta", s == 200 and (r.get("org") or {}).get("id") == tid_a, (s, (r or {}).get("org")))
s, r = with_cookie(P, f"/api/me?t={tid_b}", "d2d_session", va)
check("cookie: ?t= cannot move Ann into Beta", s == 200 and (r.get("org") or {}).get("id") == tid_a, (s, (r or {}).get("org")))
s, r = with_cookie(A, "/api/me", "d2d_admin", va)
check("cookie: a public site session is not accepted by the admin portal (401)", s == 401, (s, r))
s, r = with_cookie(P, "/api/org/credit-request", "d2d_session", va, method="POST",
                   headers={"Origin": "https://evil.example", "Content-Type": "application/json"})
check("csrf: a cross-site POST with Ann's cookie is refused (403)", s == 403 and "Cross-site" in str(detail(r)), (s, r))

section("removed person")
s, r = a1.post("/api/org/people", {"email": f"dan@{dom_a}", "role": "member"})
check("owner: Ann adds Dan", s == 200, (s, r))
dan = c.Person(f"dan@{dom_a}")
s, r = dan.sign_in()
check("removed: Dan signs in", s == 200, (s, r))
dan_old = people_ids(a1).get(dan.email)
s, r = a1.delete(f"/api/org/people/{dan_old}")
check("owner: Ann removes Dan", s == 200, (s, r))
s, r = dan.get("/api/me")
check("removed: Dan's open session ends at once (401)", s == 401, (s, r))
# items 31-32 (the user, 2026-11-12): removing deletes the account at once, and the address is blocked from joining again
s, r = dan.sign_in(again=True)
check("removed: Dan cannot sign in again: his address is blocked (403)", s == 403 and "removed this address" in str(detail(r)), (s, r))

section("platform powers")
for path in ("/api/admin/orgs", "/api/admin/requests", "/api/admin/payments", "/api/admin/audit", "/api/admin/secrets", "/api/admin/jobs"):
    s, r = a1.get(path)
    check(f"public: an owner gets no {path} (404)", s == 404, (s, r))
s, r = a1.post("/api/admin/orgs/x/credits", {"credits": 1000, "note": "free"})
check("public: an owner cannot add credits (404)", s == 404, (s, r))
pub = c.signed_in("info@pasdacs.com", P)
for path in ("/api/admin/orgs", "/api/tenancy/audit", "/api/tenancy/usage", "/api/tenancy/prices", "/api/tenancy/people"):
    s, r = pub.get(path)
    check(f"public: PASDACS's own owner gets no {path} there (404, S9)", s == 404, (s, r))
s, r = pub.get("/api/tenancy/me")
check("public: /api/tenancy/me still answers", s == 200, (s, r))
adm = c.signed_in("info@pasdacs.com", A)
s, r = adm.get("/api/admin/orgs")
check("admin portal: a PASDACS admin sees every organisation", s == 200 and any(o["id"] == tid_a for o in r.get("orgs", [])), (s, str(r)[:200]))
s, r = with_cookie(P, "/api/me", "d2d_session", jar_value(adm, "d2d_admin"))
check("cookie: an admin portal session is not accepted by the public site (401)", s == 401, (s, r))
s, h = a1.get("/api/health")
check("health: the AI engine's details stay private (only ok and busy, S14)", s == 200 and set((h.get("agent") or {})) <= {"ok", "busy"}, h.get("agent"))

section("uploads and paths")
s, r = new_dashboard(a1, "Upload names", {"files": ("../../../evil.csv", b"a,b\n1,2\n")})
check("upload: a file name with ../ is saved inside data/ under its own name", s == 200 and [f["name"] for f in r.get("files", [])] == ["evil.csv"],
      (s, r.get("files") if isinstance(r, dict) else r))
s, r = new_dashboard(a1, "Upload html", {"files": ("page.html", b"<script>alert(1)</script>")})
check("upload: anything but a .csv is refused (400)", s == 400, (s, r))
for path in (f"/api/projects/{A1}/data/..%2Fproject.json", f"/api/projects/{A1}/data/..%2F..%2F{A2}%2Fdata%2Fsales.csv",
             f"/api/projects/{A1}/files/project.json", f"/api/projects/{A1}/files/CLAUDE.md", f"/api/projects/{A1}/files/..%2F{A2}%2Frequest.md",
             f"/api/projects/{A1}/images/..%2Fproject.json", f"/api/projects/{A1}/prototype/..%2F..%2F..%2Fetc", f"/api/projects/..%2F{A2}",
             f"/api/projects/{A1}/visuals/..%2F..%2Fx/preview", "/api/library/..%2F..%2Fetc/download"):
    s, r = a1.get(path)
    check(f"paths: {urllib.parse.unquote(path).replace(A1, '<dash>').replace(A2, '<other>')} -> refused", s in (400, 404, 405), (s, str(r)[:100]))

section("payments across organisations")
s, r = b1.post("/api/payments/verify", {"razorpay_order_id": "order_ABCDEF123456", "razorpay_payment_id": "pay_ABCDEF123456",
                                        "razorpay_signature": "0" * 64})
check("payments: verifying an order that is not the organisation's answers 404", s == 404, (s, r))
s, h, t = raw("POST", P, "/api/payments/webhook", {"x-razorpay-signature": "0" * 64, "Content-Type": "application/json"}, b'{"event":"payment.captured"}')
check("payments: a webhook with a wrong signature is refused (400)", s == 400, (s, t[:100]))
s, h, t = raw("POST", A, "/api/payments/webhook", {"Content-Type": "application/json"}, b"{}")
check("payments: the admin portal has no webhook (404)", s == 404, (s, t[:100]))
paid = sql(f"SELECT id FROM relay.tn_payments WHERE status = 'paid' AND tenant_id != '{tid_b}' ORDER BY created DESC LIMIT 1")
if paid:
    s, r = b1.get(f"/api/payments/{paid}/receipt")
    check("payments: another organisation's receipt answers 404", s == 404, (s, str(r)[:100]))
s, r = a2.put("/api/payments/billing", {"name": "X", "address": "Y", "country": "India", "state": "29", "pin": "560001"})
check("payments: a member cannot change the billing details (403)", s == 403, (s, r))

# ---------------------------------------------------------------------------------------------------- starting credits
section("starting credits (item 27)")
t0 = time.time()
dom_c = f"review{STAMP}.com"
c1 = sign_up(f"cleo@{dom_c}", f"Review {STAMP}", "Cleo Owner", approve=False)
oc = org_of(c1)
REVIEW = (oc.get("pending_request") or {}).get("purpose") == "start"
print(f"(this stack reviews starting credits: {REVIEW})")
if not REVIEW:
    check("review off: a new organisation starts with 50, nothing waits", oc.get("credits") == 50 and not oc.get("pending_request"), oc)
else:
    check("review: a new organisation starts with none; its 50 wait for PASDACS", oc.get("credits") == 0 and oc["pending_request"]["credits"] == 50, oc)
    c2 = sign_up(f"cody@{dom_c}", None, None, approve=False)
    check("review: a colleague who joins sees the same review", (org_of(c2).get("pending_request") or {}).get("purpose") == "start", org_of(c2))
    s, r = new_dashboard(c1, "Too early")
    check("review: a dashboard before the answer is refused, saying why (402)", s == 402 and "PASDACS is reviewing" in str(detail(r)), (s, r))
    s, r = c1.post("/api/org/credit-request", {"credits": 100})
    check("review: asking for more meanwhile says PASDACS is reviewing (409)", s == 409 and "reviewing" in str(detail(r)), (s, r))
    rid = oc["pending_request"]["id"]
    s, r = a1.post(f"/api/admin/requests/{rid}/approve", {"credits": 50})
    check("review: an owner on the public site cannot approve it (404)", s == 404, (s, r))
    s, r = adm.get("/api/admin/requests")
    row = next((x for x in r.get("credits", []) if x["id"] == rid), {})
    check("review: the admin portal lists it as a new organisation's starting credits", row.get("purpose") == "start" and row.get("status") == "pending", row)
    s, r = adm.post(f"/api/admin/requests/{rid}/decline", {"note": ""})
    check("review: declining needs a reason (400)", s == 400, (s, r))
    s, r = adm.post(f"/api/admin/requests/{rid}/approve", {"credits": 40, "note": "Pilot"})
    check("review: PASDACS approves 40 instead of 50", s == 200, (s, str(r)[:150]))
    s, r = adm.post(f"/api/admin/requests/{rid}/approve", {"credits": 40})
    check("review: approving twice is refused (409)", s == 409, (s, r))
    o = org_of(c1)
    s, led = c1.get("/api/org")
    check("review: the owner has 40, as starting credits in the history", o.get("credits") == 40 and any(
        x["kind"] == "start" and x["delta"] == 40 for x in led.get("ledger", [])), (o.get("credits"), led.get("ledger")))
    s, n = c1.get("/api/notifications")
    check("review: the owner is told in the app", "is approved" in json.dumps(n), str(n)[:200])
    d1 = sign_up(f"dora@x1.{dom_c}", f"Sub {STAMP}", "Dora", approve=False)
    log = logs(c.WEB_C, t0)
    sub = [ln for ln in log.splitlines() if "[org-review]" in ln and f"x1.{dom_c}" in ln]
    check("review: the review for a subdomain names the organisation on its parent domain",
          bool(sub) and f"Review {STAMP} (@{dom_c})" in sub[-1].split(f"Other organisations on {dom_c}")[-1], sub[-1][:300] if sub else log[-300:])
    check("review: no separate sign-in alert for a new organisation under review",
          not [ln for ln in log.splitlines() if "[signin-alert]" in ln and "new organisation" in ln and dom_c in ln])
    rid2 = org_of(d1)["pending_request"]["id"]
    s, r = adm.post(f"/api/admin/requests/{rid2}/decline", {"note": "Please write to us first"})
    check("review: PASDACS declines another, with a reason", s == 200, (s, str(r)[:150]))
    s, n = d1.get("/api/notifications")
    check("review: that owner is told why", "Please write to us first" in json.dumps(n), str(n)[:200])
    s, r = d1.post("/api/org/credit-request", {"credits": 100, "message": "We wrote"})
    check("review: after a decline the organisation can still ask for credits", s == 200, (s, r))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
