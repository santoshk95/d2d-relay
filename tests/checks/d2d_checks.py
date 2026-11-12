"""End-to-end API checks for D2D Relay against an isolated test container (never the live one).

python -I d2d_checks.py <public site> <admin portal> <group> [<group> ...]
    e.g. http://127.0.0.1:8103 http://127.0.0.1:8104 connectors portal

Signs people in the real way: it asks for a code and reads it from the test container's log (the test stack has no
mail, so RELAY_OTP_DEV_LOG=1 prints it there). Nothing is emailed. The code limits are real too: on the public site
each person comes from an address of their own (cf-connecting-ip, as Cloudflare would send it), and forget_codes()
clears a person's earlier codes in the test database before they sign in again within the minute.
Each group prints one line per check and a summary; the exit code is the number of failures.
"""
import http.cookiejar
import itertools
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")
ADMIN_BASE = sys.argv[2].rstrip("/")
GROUPS = sys.argv[3:]
RESULTS = []
STAMP = str(int(time.time()))[-6:]
WEB_C = os.environ.get("D2D_TEST_WEB", "d2d-relay-test-web")
ADMIN_C = os.environ.get("D2D_TEST_ADMIN", "d2d-relay-test-admin")
DB_C = os.environ.get("D2D_TEST_DB", "d2d-relay-test-db")
TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the repository's tests/ folder
OUT = os.environ.get("D2D_TEST_OUT") or os.path.join(TESTS, "out")      # this run's logs and screenshots (git-ignored)
_ips = (f"198.51.100.{n}" for n in itertools.count(10))


def out_path(name: str) -> str:
    """Where a screenshot goes: the run's folder (D2D_TEST_OUT, set by run_all.sh), else tests/out."""
    os.makedirs(OUT, exist_ok=True)
    return os.path.join(OUT, name)


# A JavaScript function for Chromium (item 37): given a visual's box on a prototype page, its sunburst labels (the
# rotated lines that share one transform) that lie on another label or leave their own slice. Each label's corners come
# from its lines' boxes in their own coordinates, taken to the page by the text's screen matrix; two labels overlap
# unless an axis separates them (1 px allowed); a label is inside when every corner, 1 px in, is in the fill of the
# slice its centre is in. Returns {labels, over, outside}.
SUNBURST_JS = r"""(box) => {
  const by = {};
  box.querySelectorAll('svg text[transform^="rotate"]').forEach(t => { const k = t.getAttribute('transform'); (by[k] = by[k] || []).push(t); });
  const labels = Object.values(by).map(ts => {
    const bs = ts.map(t => t.getBBox()), x0 = Math.min(...bs.map(b => b.x)), y0 = Math.min(...bs.map(b => b.y));
    const x1 = Math.max(...bs.map(b => b.x + b.width)), y1 = Math.max(...bs.map(b => b.y + b.height)), m = ts[0].getScreenCTM();
    return {s: ts.map(t => t.textContent).join(' '), c: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(([x, y]) => new DOMPoint(x, y).matrixTransform(m))};
  });
  const apart = (A, B) => [A, B].some(P => P.some((a, i) => {
    const b = P[(i + 1) % 4], nx = b.y - a.y, ny = a.x - b.x, len = Math.hypot(nx, ny) || 1, pr = Q => Q.map(p => (p.x * nx + p.y * ny) / len);
    const pa = pr(A), pb = pr(B);
    return Math.max(...pa) <= Math.min(...pb) + 1 || Math.max(...pb) <= Math.min(...pa) + 1;
  }));
  const centre = c => ({x: (c[0].x + c[2].x) / 2, y: (c[0].y + c[2].y) / 2});
  const inFill = (p, path) => path.isPointInFill(new DOMPoint(p.x, p.y).matrixTransform(path.getScreenCTM().inverse()));
  const shrink = c => { const m = centre(c); return c.map(p => { const dx = p.x - m.x, dy = p.y - m.y, d = Math.hypot(dx, dy) || 1; return {x: p.x - dx / d, y: p.y - dy / d}; }); };
  const slices = [...box.querySelectorAll('.grp > path:not([transform])')], over = [], outside = [];
  labels.forEach((a, i) => labels.slice(i + 1).forEach(b => { if (!apart(a.c, b.c)) over.push(a.s + ' | ' + b.s); }));
  labels.forEach(l => { const home = slices.find(p => inFill(centre(l.c), p)); if (!home || !shrink(l.c).every(p => inFill(p, home))) outside.push(l.s); });
  return {labels: labels.map(l => l.s), over, outside};
}"""


def code_from_logs(container: str, email: str, since: float) -> str | None:
    """The sign-in code the app printed for this address (RELAY_OTP_DEV_LOG=1), the newest since `since`."""
    for _ in range(20):
        out = subprocess.run(["docker", "logs", "--since", str(int(since) - 2), container], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        found = re.findall(r"\[otp\] code for " + re.escape(email) + r": (\d{6})", out.stdout + out.stderr)
        if found:
            return found[-1]
        time.sleep(0.5)
    return None


def approve_start(email: str) -> None:
    """Item 27, review on (D2D_TEST_APPROVE_START=1): PASDACS approves a new organisation's starting credits the way
    it does from the command line (python -m app.orgs approve), so the suites' "starts with 50" still holds."""
    rid = subprocess.run(["docker", "exec", "-u", "postgres", DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c",
                          "SELECT id FROM relay.tn_credit_requests WHERE purpose = 'start' AND status = 'pending' AND email = '"
                          + email.replace("'", "''") + "'"], capture_output=True, text=True, check=True).stdout.split()
    if rid:
        subprocess.run(["docker", "exec", "-u", "relay", "-w", "/srv", os.environ.get("D2D_TEST_WEB", "d2d-relay-test-web"),
                        "/opt/relay/bin/launch", "web", "python", "-m", "app.orgs", "approve", rid[0]],
                       capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")


def forget_codes(email: str) -> None:
    """Test database only: forget this address's earlier codes, so it may ask again within the minute."""
    subprocess.run(["docker", "exec", "-u", "postgres", DB_C, "psql", "-q", "-h", "/run/postgresql", "-d", "relay", "-c",
                    "DELETE FROM otp_codes WHERE email = '" + email.replace("'", "''") + "'"], capture_output=True, check=True)


class Person:
    def __init__(self, email: str, base: str = BASE):
        self.email, self.base = email, base
        self.container = ADMIN_C if base == ADMIN_BASE else WEB_C
        self.ip = None if base == ADMIN_BASE else next(_ips)      # the admin portal refuses Cloudflare's header without Access
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={**({"Content-Type": "application/json"} if data else {}), **(headers or {})})
        try:
            with self.http.open(req, timeout=60) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            out = json.loads(raw or b"null")
        except ValueError:
            out = raw.decode("utf-8", "replace")
        return status, out

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)

    def put(self, path, body=None, **kw):
        return self.call("PUT", path, body if body is not None else {}, **kw)

    def patch(self, path, body=None, **kw):
        return self.call("PATCH", path, body if body is not None else {}, **kw)

    def delete(self, path, **kw):
        return self.call("DELETE", path, **kw)

    def form(self, path: str, fields: dict, files: dict | None = None):
        """A multipart POST (fields, and files as name -> (filename, bytes))."""
        boundary = "----d2dcheck" + str(time.time_ns())
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for k, (fn, data) in (files or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: text/csv\r\n\r\n'.encode()
                         + data + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with self.http.open(req, timeout=120) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, raw.decode("utf-8", "replace")

    def sign_in(self, org_name: str | None = None, person: str | None = None, again: bool = False):
        """Ask for a code, read it from the container's log, sign in (and name a new organisation)."""
        if again:
            forget_codes(self.email)
        hdr = {"cf-connecting-ip": self.ip} if self.ip else {}
        t0 = time.time()
        s, r = self.post("/auth/otp/start", {"email": self.email}, headers=hdr)
        if s != 200:
            return s, r
        code = code_from_logs(self.container, self.email, t0)
        if not code:
            return 0, "no code in the container log"
        s, r = self.post("/auth/otp/verify", {"email": self.email, "code": code, "next": "#/d2d"})
        if s == 200 and isinstance(r, dict) and r.get("organisation"):
            s, r = self.post("/auth/otp/organisation", {"name": org_name or r["organisation"]["suggested"], "person": person or ""})
            if s == 200 and os.environ.get("D2D_TEST_APPROVE_START") == "1":
                approve_start(self.email)
        return s, r


_signed: dict[tuple[str, str], "Person"] = {}


def signed_in(email: str, base: str) -> "Person":
    """One signed-in session per address and site for the whole run (an address may ask for one code a minute)."""
    key = (base, email)
    if key not in _signed:
        p = Person(email, base)
        s, r = p.sign_in(again=True)          # the same address may have asked for a code on the other site just now
        check(f"sign-in: {email} on {'the admin portal' if base == ADMIN_BASE else 'the public site'}", s == 200, (s, r))
        _signed[key] = p
    return _signed[key]


def check(name: str, ok: bool, detail=None) -> bool:
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or detail is None else f"   -> {str(detail)[:400]}"), flush=True)
    return bool(ok)


def detail_of(r):
    return r.get("detail") if isinstance(r, dict) else r


# ---------------------------------------------------------------------------------------------------- connectors

def connectors():
    stamp = str(int(time.time()))[-6:]
    owner = Person(f"olive.owner@acme{stamp}.com")
    s, r = owner.sign_in("Acme Test", "Olive Owner")
    check("connectors: a new organisation's owner signs in", s == 200, (s, r))
    s, me = owner.get("/api/me")
    org = (me or {}).get("org") or {}
    check("connectors: a new organisation has none switched on (CSV only)", s == 200 and org.get("connectors") == [], (s, org))
    s, cat = owner.get("/api/org/connectors")
    kinds = [c["kind"] for c in (cat or {}).get("connectors", [])]
    check("connectors: every connector is listed, all on request", s == 200 and len(kinds) == 6 and not any(c["on"] for c in cat["connectors"]), (s, cat))
    check("connectors: the list says what each one reads", all(c.get("note") and c.get("label") for c in cat.get("connectors", [])), cat)
    s, r = owner.get("/api/connectors")
    check("connectors: the wizard offers no connector", s == 200 and r.get("kinds") == {}, (s, r))
    s, r = owner.post("/api/connections", {"kind": "bigquery", "name": "BQ", "auth_mode": "service_account",
                                           "config": {"project": "p"}, "secrets": {"service_account_json": "{}"}})
    check("connectors: adding a BigQuery connection is refused (403)", s == 403 and "PASDACS" in str(detail_of(r)), (s, r))
    s, r = owner.post("/api/org/connector-request", {"kinds": ["bigquery", "snowflake"], "message": "Sales tables, 2M rows"})
    check("connectors: asking PASDACS is recorded (not emailed here: no mail set up)", s == 200 and r.get("sent") is False, (s, r))
    s, r = owner.post("/api/org/connector-request", {"kinds": ["nope"]})
    check("connectors: an unknown connector cannot be asked for (400)", s == 400, (s, r))
    s, r = owner.post("/api/org/connector-request", {"kinds": []})
    check("connectors: a request names at least one connector (400)", s == 400, (s, r))
    s, r = owner.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": ["bigquery"]})
    check("connectors: an owner cannot switch connectors on (no admin API on the public site)", s in (403, 404), (s, r))

    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/orgs")
    mine = next((o for o in (d or {}).get("orgs", []) if o["id"] == org.get("id")), {})
    plat = next((o for o in (d or {}).get("orgs", []) if o.get("platform")), {})
    check("connectors: Organisations shows the new organisation as CSV only", s == 200 and mine.get("connectors") == [], (s, mine))
    check("connectors: PASDACS's own workspace has every connector", len(plat.get("connectors") or []) == 6, plat)
    s, rq = admin.get("/api/admin/requests")
    req = next((x for x in (rq or {}).get("connectors", []) if x.get("org") == org.get("id")), {})
    check("connectors: the request is listed for the platform admin (Requests)", req.get("kinds") == ["bigquery", "snowflake"] and req.get("message"), rq)
    s, r = admin.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": ["bigquery", "warp-drive"]})
    check("connectors: an unknown connector cannot be switched on (400)", s == 400, (s, r))
    s, r = admin.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": ["bigquery"]})
    mine = next((o for o in (r or {}).get("orgs", []) if o["id"] == org.get("id")), {})
    check("connectors: the platform admin switches BigQuery on", s == 200 and mine.get("connectors") == ["bigquery"], (s, mine))

    s, me = owner.get("/api/me")
    check("connectors: the owner's organisation now has BigQuery", (me.get("org") or {}).get("connectors") == ["bigquery"], me.get("org"))
    s, r = owner.get("/api/connectors")
    check("connectors: the wizard offers BigQuery only", s == 200 and list(r.get("kinds", {})) == ["bigquery"], (s, list((r or {}).get("kinds", {}))))
    s, r = owner.post("/api/connections", {"kind": "snowflake", "name": "SF", "auth_mode": "password",
                                           "config": {"account": "a", "warehouse": "w", "database": "d", "user": "u"}, "secrets": {"password": "x"}})
    check("connectors: Snowflake is still refused (403)", s == 403, (s, r))
    s, c = owner.post("/api/connections", {"kind": "bigquery", "name": "BQ test", "auth_mode": "service_account",
                                           "config": {"project": "demo-project"}, "secrets": {"service_account_json": '{"type": "service_account"}'}})
    check("connectors: a BigQuery connection can be added now", s == 200 and (c or {}).get("id"), (s, c))
    cid = (c or {}).get("id")
    s, n = owner.get("/api/notifications") if cid else (0, None)
    texts = json.dumps(n)
    check("connectors: the owner was told BigQuery is switched on", "Connectors for Acme Test" in texts, texts[:300])

    s, r = admin.put(f"/api/admin/orgs/{org.get('id')}/connectors", {"kinds": []})
    check("connectors: the platform admin switches it off again", s == 200, (s, r))
    s, r = owner.get("/api/connections")
    conn = next((x for x in (r or {}).get("connections", []) if x["id"] == cid), {})
    check("connectors: the connection stays, marked switched off", conn.get("allowed") is False, conn)
    s, r = owner.post(f"/api/connections/{cid}/test")
    check("connectors: a switched-off connection cannot be tested (403)", s == 403, (s, r))
    s, r = owner.get(f"/api/connections/{cid}/browse?q=")
    check("connectors: ... nor browsed (403)", s == 403, (s, r))
    s, r = owner.post(f"/api/connections/{cid}/query", {"sql": "SELECT 1"})
    check("connectors: ... nor queried (403)", s == 403, (s, r))
    s, r = owner.put(f"/api/connections/{cid}/tables", {"objects": ["a.b"]})
    check("connectors: ... nor given tables (403)", s == 403, (s, r))
    s, r = owner.delete(f"/api/connections/{cid}")
    check("connectors: but it can be removed", s == 200 and not any(x["id"] == cid for x in r.get("connections", [])), (s, r))


# ---------------------------------------------------------------------------------------------------- the admin portal

def cookie(p: Person, name: str):
    return next((c.value for c in p.jar if c.name == name), None)


def admin_portal():
    s, js = Person("x", BASE).get("/portal.js")
    check("portal: the public site says it is public", s == 200 and '"portal": "public"' in str(js), js)
    s, js = Person("x", ADMIN_BASE).get("/portal.js")
    check("portal: the admin portal says it is the admin portal", s == 200 and '"portal": "admin"' in str(js), js)
    s, h = Person("x", ADMIN_BASE).get("/healthz")
    check("portal: the admin portal is up on the shared database", s == 200 and h.get("portal") == "admin" and h.get("database") == "postgres", h)

    outsider = Person(f"pat@acme{STAMP}.com", ADMIN_BASE)
    s, r = outsider.post("/auth/otp/start", {"email": outsider.email})
    check("portal: a non-PASDACS address cannot ask for a code (403)", s == 403 and "PASDACS" in str(detail_of(r)), (s, r))
    s, r = outsider.post("/auth/otp/verify", {"email": outsider.email, "code": "123456"})
    check("portal: ... nor sign in with any code", s in (400, 403), (s, r))

    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    check("portal: info@pasdacs.com signs in to the admin portal with its own cookie", cookie(admin, "d2d_admin") and not cookie(admin, "d2d_session"),
          [c.name for c in admin.jar])
    s, me = admin.get("/api/me")
    check("portal: ... as a platform admin on the admin portal", s == 200 and me.get("portal") == "admin" and (me.get("org") or {}).get("platform_admin") is True, me)
    staff = Person(f"ops{STAMP}@pasdacs.com", ADMIN_BASE)
    s, r = staff.sign_in()
    s2, me2 = staff.get("/api/me")
    check("portal: any new @pasdacs.com address signs in and is an admin", s == 200 and (me2.get("org") or {}).get("platform_admin") is True, (s, r, me2))
    for path, want in (("/api/admin/orgs", 200), ("/api/admin/requests", 200), ("/api/notifications", 200), ("/api/projects", 404),
                       ("/api/connections", 404), ("/api/admin/audit", 404), ("/api/admin/backups", 404), ("/api/health", 404),
                       ("/api/org", 404), ("/api/askd/threads", 404)):
        s, r = admin.get(path)
        check(f"portal: admin portal GET {path} -> {want}", s == want, (s, detail_of(r)))
    s, r = admin.post("/auth/otp/organisation", {"name": "X", "person": "Y"})
    check("portal: no organisation can be created on the admin portal", s == 404, (s, r))

    owner = Person(f"olga.owner@bravo{STAMP}.com")
    s, r = owner.sign_in("Bravo Test", "Olga Owner")
    check("portal: an organisation still signs up on the public site", s == 200 and cookie(owner, "d2d_session"), (s, r))
    s, r = owner.get("/api/admin/orgs")
    check("portal: the public site has no admin APIs (404)", s == 404, (s, r))
    pub_admin = signed_in("info@pasdacs.com", BASE)
    s, r = pub_admin.get("/api/admin/orgs")
    check("portal: ... not even for info@pasdacs.com there (404)", s == 404, (s, r))
    s, me = pub_admin.get("/api/me")
    check("portal: on the public site info@pasdacs.com is no platform admin", s == 200 and (me.get("org") or {}).get("platform_admin") is False, me.get("org"))

    swap = Person("x", ADMIN_BASE)       # a public session's cookie, offered to the admin portal under its cookie name
    swap.jar.set_cookie(http.cookiejar.Cookie(0, "d2d_admin", cookie(owner, "d2d_session"), None, False, "127.0.0.1", False, False, "/", True,
                                              False, None, False, None, None, {}))
    s, r = swap.get("/api/me")
    check("portal: a public-site session is refused by the admin portal (401)", s == 401, (s, r))
    swap2 = Person("x", BASE)
    swap2.jar.set_cookie(http.cookiejar.Cookie(0, "d2d_session", cookie(admin, "d2d_admin"), None, False, "127.0.0.1", False, False, "/", True,
                                               False, None, False, None, None, {}))
    s, r = swap2.get("/api/me")
    check("portal: an admin-portal session is refused by the public site (401)", s == 401, (s, r))

    cf = {"cf-connecting-ip": "203.0.113.7"}
    s, r = admin.get("/api/me", headers=cf)
    check("portal: through Cloudflare without Access set up, the admin portal refuses (403)", s == 403 and "Cloudflare Access" in str(detail_of(r)), (s, r))
    s, r = Person("x", ADMIN_BASE).get("/login.html", headers=cf)
    check("portal: ... its pages too", s == 403 and "Cloudflare Access" in str(r), (s, str(r)[:200]))
    s, r = owner.get("/api/me", headers=cf)
    check("portal: the public site is not affected by that", s == 200, (s, r))


# ---------------------------------------------------------------------------------------------------- credits by approval

CSV = b"month,region,sales\n2026-01,North,120\n2026-02,North,135\n2026-01,South,98\n2026-02,South,101\n"


def new_dashboard(p: Person):
    return p.form("/api/projects", {"prompt": "Sales by region and month", "data_mode": "upload", "name": "Credit check"},
                  {"files": ("sales.csv", CSV)})


def credits_by_approval():
    dom = f"credit{STAMP}.com"
    owner, colleague = Person(f"cara.owner@{dom}"), Person(f"colin.colleague@{dom}")
    s, r = owner.sign_in("Credit Test", "Cara Owner")
    check("credits: a new organisation signs up", s == 200, (s, r))
    s, me = owner.get("/api/me")
    org = me.get("org") or {}
    check("credits: it starts with 50 credits", org.get("credits") == 50 and org.get("pending_request") is None, org)
    s, o = owner.get("/api/org")
    check("credits: ... with a 'starting credits' line of 50 in its history",
          s == 200 and any(x["kind"] == "start" and x["delta"] == 50 for x in o.get("ledger", [])), o.get("ledger"))
    check("credits: the prices: 25 a dashboard, 10 a change, 10 for up to 5 Ask Relay questions",
          (org.get("costs") or {}) == {"dashboard": 25, "change": 10, "ask": 10, "ask_questions": 5}, org.get("costs"))
    admin0 = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, r = admin0.post(f"/api/admin/orgs/{org.get('id')}/credits", {"credits": -50, "note": "Test: back to none"})
    check("credits: PASDACS takes the 50 back (to test running out)", s == 200, (s, r))
    s, r = new_dashboard(owner)
    check("credits: a new dashboard is refused without credits (402)", s == 402 and "PASDACS" in str(detail_of(r)), (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 100, "message": "First pilot"})
    check("credits: the owner asks PASDACS for 100 credits", s == 200 and (r.get("request") or {}).get("credits") == 100, (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 50})
    check("credits: a second request while one is waiting is refused (409)", s == 409, (s, r))
    s, r = colleague.sign_in()
    s, me2 = colleague.get("/api/me")
    pend = (me2.get("org") or {}).get("pending_request") or {}
    check("credits: a colleague sees the waiting request", pend.get("credits") == 100, me2.get("org"))
    s, r = colleague.post(f"/api/org/credit-request/{pend.get('id')}/withdraw")
    check("credits: ... but cannot withdraw someone else's (403)", s == 403, (s, r))
    s, r = owner.post(f"/api/org/credit-request/{pend.get('id')}/withdraw")
    check("credits: the owner withdraws it", s == 200 and r.get("pending_request") is None, (s, r))
    s, r = owner.post("/api/org/credit-request", {"credits": 150, "message": "Pilot, 5 dashboards"})
    rid = (r.get("request") or {}).get("id")
    check("credits: ... and asks for 150 instead", s == 200 and rid, (s, r))
    s, r = owner.post(f"/api/admin/requests/{rid}/approve", {"credits": 150})
    check("credits: nobody approves on the public site (404)", s == 404, (s, r))

    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/requests")
    mine = next((x for x in d.get("credits", []) if x["id"] == rid), {})
    check("credits: the admin portal lists it as waiting", mine.get("status") == "pending" and mine.get("org_name") == "Credit Test" and d.get("pending", 0) >= 1, mine)
    s, d2 = admin.get("/api/admin/orgs")
    org_row = next((x for x in d2.get("orgs", []) if x["id"] == org.get("id")), {})
    check("credits: Organisations shows what it asks for", (org_row.get("pending") or {}).get("credits") == 150, org_row)
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 0})
    check("credits: approving 0 credits is refused (400)", s == 400, (s, r))
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 120, "note": "Pilot agreed"})
    check("credits: the admin approves 120 (another amount than asked)", s == 200, (s, r))
    s, r = admin.post(f"/api/admin/requests/{rid}/approve", {"credits": 120})
    check("credits: ... once only (409)", s == 409, (s, r))
    s, me = owner.get("/api/me")
    check("credits: the organisation has the 120 credits at once", (me.get("org") or {}).get("credits") == 120 and not (me.get("org") or {}).get("pending_request"), me.get("org"))
    s, o = owner.get("/api/org")
    led = next((x for x in o.get("ledger", []) if x["kind"] == "adjust"), {})
    req = next((x for x in o.get("requests", []) if x["id"] == rid), {})
    check("credits: its history says PASDACS added them for the approved request", led.get("delta") == 120 and "Request approved" in (led.get("note") or ""), led)
    check("credits: its requests say approved, +120", req.get("status") == "approved" and req.get("granted") == 120, req)
    s, n = owner.get("/api/notifications")
    check("credits: the owner was told", "+120 credits for Credit Test" in json.dumps(n), json.dumps(n)[:300])

    s, r = owner.post("/api/org/credit-request", {"credits": 5000, "message": "Big project"})
    rid2 = (r.get("request") or {}).get("id")
    s, r = admin.post(f"/api/admin/requests/{rid2}/decline", {"note": ""})
    check("credits: declining needs a reason (400)", s == 400, (s, r))
    s, r = admin.post(f"/api/admin/requests/{rid2}/decline", {"note": "Please talk to us about a plan first"})
    check("credits: the admin declines with a reason", s == 200, (s, r))
    s, o = owner.get("/api/org")
    req2 = next((x for x in o.get("requests", []) if x["id"] == rid2), {})
    check("credits: the organisation sees it declined, with the reason, and no credits added",
          req2.get("status") == "declined" and "plan first" in (req2.get("note") or "") and o.get("credits") == 120, (req2, o.get("credits")))
    s, r = admin.post(f"/api/admin/requests/{rid2}/approve", {"credits": 10})
    check("credits: a declined request cannot be approved later (409)", s == 409, (s, r))
    s, r = new_dashboard(owner)
    check("credits: with credits, a new dashboard starts", s == 200 and (r or {}).get("id"), (s, str(r)[:200]))
    s, o = owner.get("/api/org")
    check("credits: ... and its 25 credits are charged", any(x["kind"] == "charge" and x["delta"] == -25 for x in o.get("ledger", [])), o.get("ledger"))


# ---------------------------------------------------------------------------------------------------- people management

def person(o: dict, email: str) -> dict:
    return next((p for p in o.get("people", []) if p["email"] == email), {})


def people_management():
    dom = f"people{STAMP}.com"
    olivia, mark, nina = Person(f"olivia@{dom}"), Person(f"mark@{dom}"), Person(f"nina@{dom}")
    s, r = olivia.sign_in("People Test", "Olivia Owner")
    check("people: an organisation signs up; Olivia is its main owner", s == 200, (s, r))
    s, me = olivia.get("/api/me")
    check("people: ... an owner, and the main one", (me.get("org") or {}).get("is_owner") and (me.get("org") or {}).get("is_primary"), me.get("org"))
    s, r = olivia.post("/api/org/people", {"email": f"mark@{dom}", "role": "member"})
    check("people: an owner adds Mark as a member (not emailed here: no mail set up)", s == 200 and (r.get("added") or {}).get("invited") is False
          and person(r, f"mark@{dom}").get("owner") is False, (s, r.get("added") if isinstance(r, dict) else r))
    s, r = olivia.post("/api/org/people", {"email": "someone@other-company.com"})
    check("people: only the organisation's own domain can be added (400)", s == 400 and dom in str(detail_of(r)), (s, r))
    s, r = olivia.post("/api/org/people", {"email": f"mark@{dom}"})
    check("people: adding someone twice is refused (409)", s == 409, (s, r))
    s, r = olivia.post("/api/org/people", {"email": "info@pasdacs.com"})
    check("people: an address of another organisation cannot be added (400/409)", s in (400, 409), (s, r))
    s, r = mark.sign_in()
    s, me = mark.get("/api/me")
    check("people: Mark signs in to People Test (added before he ever signed in)", (me.get("org") or {}).get("name") == "People Test"
          and (me.get("org") or {}).get("is_owner") is False, me.get("org"))
    s, r = mark.post("/api/org/people", {"email": f"nina@{dom}"})
    check("people: a member cannot add people (403)", s == 403, (s, r))
    s, o = mark.get("/api/org")
    olivia_id = person(o, f"olivia@{dom}").get("id")
    s, r = mark.patch(f"/api/org/people/{olivia_id}", {"role": "member"})
    check("people: a member cannot change roles (403)", s == 403, (s, r))
    mark_id = person(o, f"mark@{dom}").get("id")
    s, r = olivia.patch(f"/api/org/people/{mark_id}", {"role": "owner"})
    check("people: Olivia makes Mark an owner (several owners)", s == 200 and person(r, f"mark@{dom}").get("owner") is True, (s, r))
    s, me = mark.get("/api/me")
    check("people: Mark is now an owner", (me.get("org") or {}).get("is_owner") is True and (me.get("org") or {}).get("is_primary") is False, me.get("org"))
    s, r = mark.patch(f"/api/org/people/{olivia_id}", {"role": "member"})
    check("people: the main owner cannot be made a member (409)", s == 409, (s, r))
    s, r = mark.delete(f"/api/org/people/{olivia_id}")
    check("people: ... nor removed (409)", s == 409, (s, r))
    s, r = mark.post("/api/org/transfer", {"uid": mark_id})
    check("people: only the main owner hands over the main ownership (403)", s == 403, (s, r))
    s, r = mark.post("/api/org/people", {"email": f"nina@{dom}", "role": "member"})
    check("people: an owner other than the main one adds Nina", s == 200, (s, r))
    s, r = nina.sign_in()
    s, o = olivia.get("/api/org")
    nina_id = person(o, f"nina@{dom}").get("id")
    s, r = olivia.delete(f"/api/org/people/{nina_id}")
    # item 31 (the user, 2026-11-12): removing someone deletes their account at once; the address can come back as a new person
    check("people: Olivia removes Nina: her account is deleted at once, not kept as removed", s == 200 and not person(r, f"nina@{dom}")
          and not any(p.get("email") == f"nina@{dom}" for p in r.get("removed", [])), (s, r))
    s, r = nina.get("/api/me")
    check("people: Nina's session ends at once (401)", s == 401, (s, r))
    s, r = olivia.post("/api/org/people", {"email": f"nina@{dom}", "role": "member"})
    check("people: an owner can add her address back, as a new person", s == 200 and person(r, f"nina@{dom}")
          and person(r, f"nina@{dom}").get("id") != nina_id, (s, r))
    s, r = nina.sign_in(again=True)
    check("people: and she signs in again", s == 200, (s, r))
    s, o = olivia.get("/api/org")
    nina_id = person(o, f"nina@{dom}").get("id")              # her new account
    s, r = olivia.post("/api/org/transfer", {"uid": olivia_id})
    check("people: the main owner cannot hand it to herself (400)", s == 400, (s, r))
    s, r = olivia.post("/api/org/transfer", {"uid": nina_id, "stay_owner": False})
    check("people: Olivia hands the main ownership to Nina and becomes a member", s == 200, (s, r))
    s, me = nina.get("/api/me")
    check("people: Nina is the main owner now", (me.get("org") or {}).get("is_primary") is True and (me.get("org") or {}).get("is_owner") is True, me.get("org"))
    s, me = olivia.get("/api/me")
    check("people: Olivia is a member", (me.get("org") or {}).get("is_owner") is False and (me.get("org") or {}).get("is_primary") is False, me.get("org"))
    s, n = nina.get("/api/notifications")
    check("people: Nina was told", "main owner of People Test" in json.dumps(n), json.dumps(n)[:300])
    s, r = mark.delete(f"/api/org/people/{mark_id}")
    check("people: an owner can leave (signed out)", s == 200 and r.get("signed_out") is True, (s, r))
    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/orgs")
    po = next((x for x in d.get("orgs", []) if x["name"] == "People Test"), {})
    check("people: the admin portal shows the new main owner and 2 people", (po.get("owner") or {}).get("email") == f"nina@{dom}" and po.get("people") == 2, po)


# ---------------------------------------------------------------------------------------------------- production clean-up

def production():
    for base, where in ((BASE, "public site"), (ADMIN_BASE, "admin portal")):
        s, r = Person("x", base).get("/auth/otp/test-login")
        check(f"production: the temporary test login is gone ({where}: 404)", s == 404, (s, str(r)[:120]))
        s, page = Person("x", base).get("/login.html")
        check(f"production: the sign-in page has no testing mode ({where})", s == 200 and "testbanner" not in str(page) and "test_code" not in str(page),
              str(page)[:120])
    p = Person(f"limit.one@limits{STAMP}.com")
    s, r = p.post("/auth/otp/start", {"email": p.email}, headers={"cf-connecting-ip": p.ip})
    s2, r2 = p.post("/auth/otp/start", {"email": p.email}, headers={"cf-connecting-ip": p.ip})
    check("production: one code a minute per address (429)", s == 200 and s2 == 429, (s, s2, r2))
    s, r = p.post("/auth/otp/verify", {"email": p.email, "code": "000000"})
    tries = [p.post("/auth/otp/verify", {"email": p.email, "code": "000000"})[0] for _ in range(5)]
    code = code_from_logs(WEB_C, p.email, time.time() - 120)
    s, r = p.post("/auth/otp/verify", {"email": p.email, "code": code or "", "next": ""})
    check("production: after 5 wrong tries even the right code is refused", s == 400 and all(t == 400 for t in tries), (s, tries))
    ip = f"203.0.113.{int(STAMP) % 200 + 20}"      # a network of its own each run
    codes = [Person(f"net{i}.{STAMP}@limits{STAMP}.com").post("/auth/otp/start", {"email": f"net{i}.{STAMP}@limits{STAMP}.com"},
                                                               headers={"cf-connecting-ip": ip})[0] for i in range(21)]
    check("production: 20 codes an hour per network, then 429", codes[:20] == [200] * 20 and codes[20] == 429, codes)
    s, r = Person("x").post("/auth/otp/start", {"email": "someone@gmail.com"})
    check("production: free mail addresses are refused", s == 400, (s, r))


def rehearsal():
    """After loading a copy of the live database into the test stack: the live data is there and works."""
    admin = signed_in("info@pasdacs.com", ADMIN_BASE)
    s, d = admin.get("/api/admin/orgs")
    plat = next((o for o in (d or {}).get("orgs", []) if o.get("platform")), {})
    check("rehearsal: the PASDACS organisation came across with its 70 credits and 4 dashboards",
          plat.get("domain") == "pasdacs.com" and plat.get("credits") == 70 and plat.get("dashboards") == 4, plat)
    check("rehearsal: ... and every connector switched on for it", len(plat.get("connectors") or []) == 6, plat)
    pub = signed_in("info@pasdacs.com", BASE)
    s, me = pub.get("/api/me")
    org = me.get("org") or {}
    check("rehearsal: info@pasdacs.com is its main owner on the public site", org.get("is_owner") and org.get("is_primary") and org.get("credits") == 70, org)


GROUP_FUNCS = {"connectors": connectors, "portal": admin_portal, "credits": credits_by_approval, "people": people_management,
               "production": production, "rehearsal": rehearsal}

if __name__ == "__main__":
    for g in GROUPS:
        print(f"--- {g}", flush=True)
        try:
            GROUP_FUNCS[g]()
        except Exception as e:  # noqa: BLE001
            check(f"{g}: ran to the end", False, repr(e))
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
    sys.exit(len(bad))
