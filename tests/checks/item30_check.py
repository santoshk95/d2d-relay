"""Test stack only: item 30 (2026-11-12): the legal pages; the audit's engineering items S4 (the AI engine's API only for
the web app), S6 (the AI engine reaches only Anthropic), S10 (the admin portal only from this PC or through Access),
S11 (FastAPI/Starlette), S15 (RELAY's leftover routes off), S16 (the visual kit's lockfile), S17 (a warehouse sign-in
bound to its browser), P6 (no email in Razorpay's notes: in pay_check.py).
python -I -X utf8 item30_check.py http://127.0.0.1:8103 http://127.0.0.1:8104"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

P, A = c.BASE, c.ADMIN_BASE
check = c.check
ADMIN_HOST = os.environ.get("D2D_TEST_ADMIN_HOST", "d2d-relay-test-admin")
TYPO = "—–…“”‘’·•›‹→←↔"


def raw(method: str, base: str, path: str, headers: dict | None = None, body: bytes | None = None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")


def sh(container: str, user: str, cmd: str, timeout: int = 60) -> str:
    r = subprocess.run(["docker", "exec", "-u", user, container, "sh", "-c", cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout + r.stderr).strip()


def app_py(code: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=code, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- the legal pages
for path, must in (("/terms.html", ["Terms of service", "Bengaluru, Karnataka", "no refunds and no cancellations", "privacy.html",
                                    "laws of India"]),
                   ("/refunds.html", ["no refunds and no cancellations", "Delivery", "Payment errors", "info@pasdacs.com"]),
                   ("/contact.html", ["info@pasdacs.com", "Data Protection Board of India", "Migration D2D"])):
    s, h, t = raw("GET", P, path)
    flat = " ".join(t.split())                                  # the page's words, whatever the line breaks
    check(f"legal: {path} opens without signing in, with what it must say", s == 200 and all(m in flat for m in must),
          (s, [m for m in must if m not in flat]))
    check(f"legal: {path} has the security headers", h.get("x-frame-options") == "SAMEORIGIN"
          and "frame-ancestors 'self'" in h.get("content-security-policy", "") and h.get("x-content-type-options") == "nosniff", h)
    check(f"legal: {path} is in plain characters", not [ch for ch in t if ch in TYPO], "".join(ch for ch in t if ch in TYPO)[:20])
s, h, t = raw("GET", P, "/login.html")
check("legal: the sign-in page says signing in accepts the terms, and links them",       # item 41: "you agree to the Terms"
      'href="terms.html"' in t and ("accept" in t or "agree to the" in t), s)
s, h, t = raw("GET", P, "/privacy.html")
check("legal: the privacy notice links the terms, refunds and contact", all(f'href="{x}.html"' in t for x in ("terms", "refunds", "contact")), s)

# ---------------------------------------------------------------- S15: RELAY's leftover routes are off
p = c.Person(f"sam.sec@sec30{c.STAMP}.com")
s, r = p.sign_in("Sec Thirty", "Sam Sec")
check("setup: an organisation signs up", s == 200, (s, r))
for method, path in (("GET", "/api/me/ai"), ("PUT", "/api/me/ai"), ("GET", "/api/workspace"), ("POST", "/api/workspace/start"),
                     ("GET", "/api/workbench/items"), ("GET", "/api/validate/count"), ("POST", "/api/registry/d2d/interest")):
    s, r = p.call(method, path, {} if method in ("POST", "PUT") else None)
    check(f"S15: {method} {path} is off (404)", s == 404, (s, str(r)[:120]))
s, r = p.get("/api/registry")
check("S15: the module registry the app needs still answers", s == 200 and isinstance(r, dict), s)
for method, path in (("GET", "/gallery"), ("GET", "/auth/github/callback?code=x&state=y"), ("GET", "/auth/microsoft/callback?code=x&state=y"),
                     ("POST", "/auth/observe/hook/x1")):
    s, h, t = raw(method, P, path, {"Content-Type": "application/json"}, b"{}" if method == "POST" else None)
    check(f"S15: {method} {path.split('?')[0]} is off without signing in (404)", s == 404, (s, t[:100]))
    s, r = p.call(method, path, {} if method == "POST" else None)
    check(f"S15: {method} {path.split('?')[0]} is off signed in (404)", s == 404, (s, str(r)[:100]))
s, h, t = raw("GET", P, "/auth/providers")
check("S15: D2D Relay's own sign-in paths still answer", s == 200, (s, t[:100]))

# ---------------------------------------------------------------- S17: a warehouse sign-in finishes only where it started
tid = subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-At", "-h", "/run/postgresql", "-d", "relay", "-c",
                                  f"SELECT tenant_id FROM relay.tn_orgs WHERE domain = 'sec30{c.STAMP}.com'"],
                                 capture_output=True, text=True).stdout.strip()
out = app_py(f"""
import time
from app import db, connectors
db.init()
res = {{}}
with db.use({tid!r}):
    tag = connectors._session_tag("cookie-A")
    for st, sess, me in (("s17-a", "cookie-B", "u-1"), ("s17-b", "cookie-A", "u-2"), ("s17-c", "cookie-A", "u-1"), ("s17-d", None, "u-1")):
        db.run("INSERT INTO auth_flows (state, provider, verifier, nonce, return_to, created) VALUES (?, 'conn:c-none', 'v', 'u-1', ?, ?)",
               (st, tag, time.time()))
        try:
            connectors.oauth_callback(st, "code", "http://127.0.0.1:8103/", sess, me)
            res[st] = "passed"
        except Exception as e:
            res[st] = type(e).__name__ + ": " + str(e)[:90]
print(repr(res))
""")
try:
    res = eval(out.splitlines()[-1])                       # noqa: S307 - our own repr from the container
except Exception:  # noqa: BLE001
    res = {}
where = "browser where you started"
check("S17: another browser session cannot finish someone's warehouse sign-in", where in res.get("s17-a", ""), out[-300:])
check("S17: another person cannot finish it either, even with the same session", where in res.get("s17-b", ""), res.get("s17-b"))
check("S17: the same person in the same session gets past the check (then the test connection is not found)",
      res.get("s17-c") and where not in res["s17-c"], res.get("s17-c"))
check("S17: a callback without the session cookie is refused", where in res.get("s17-d", ""), res.get("s17-d"))

# ---------------------------------------------------------------- S10: the admin portal, only from this PC or through Access
s, h, t = raw("GET", A, "/api/me")
check("S10: from this PC the admin portal still answers (401 before signing in)", s == 401, (s, t[:100]))
code = sh(c.WEB_C, "relay", f"curl -s -o /dev/null -w '%{{http_code}}' http://{ADMIN_HOST}:8000/api/me")
check("S10: a request from another container is refused (403)", code == "403", code)
code = sh(c.WEB_C, "relay", f"curl -s -o /dev/null -w '%{{http_code}}' http://{ADMIN_HOST}:8000/login.html")
check("S10: so is its sign-in page (403)", code == "403", code)
code = sh(c.WEB_C, "relay", f"curl -s -o /dev/null -w '%{{http_code}}' -H 'cf-connecting-ip: 203.0.113.7' http://{ADMIN_HOST}:8000/api/me")
check("S10: with a made-up Cloudflare header too (403: Access is needed)", code == "403", code)
code = sh(c.WEB_C, "relay", f"curl -s -o /dev/null -w '%{{http_code}}' http://{ADMIN_HOST}:8000/healthz")
check("S10: its health check still answers other containers (200)", code == "200", code)
logs = subprocess.run(["docker", "logs", "--since", "10m", c.ADMIN_C], capture_output=True, text=True, encoding="utf-8", errors="replace")
check("S10: the refusals are in the admin portal's log", "[portal] refused a request from" in logs.stdout + logs.stderr, "")

# ---------------------------------------------------------------- S4: the AI engine's API, only for the web app
fg = "curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{\"missing\": false}' http://127.0.0.1:8090/forget"
code = sh(c.WEB_C, "agent", fg)
check("S4: the AI engine's own user cannot call its API (403)", code == "403", code)
code = sh(c.WEB_C, "agent", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health")
check("S4: its health check stays open (200)", code == "200", code)
code = sh(c.WEB_C, "relay", fg)
check("S4: the web app's user still can", code not in ("403", "000"), code)
code = sh(c.WEB_C, "root", fg)
check("S4: root (watchdog, relay-ctl) still can", code not in ("403", "000"), code)

# ---------------------------------------------------------------- S6: the AI engine reaches only Anthropic
logs = subprocess.run(["docker", "logs", c.WEB_C], capture_output=True, text=True, encoding="utf-8", errors="replace")
line = next((ln for ln in (logs.stdout + logs.stderr).splitlines() if "the AI engine's network:" in ln), "")
check("S6: relay-init limited the AI engine's network", "Anthropic only" in line, line)
code = sh(c.WEB_C, "agent", "curl -s -m 10 -o /dev/null -w '%{http_code}' https://example.com; echo \" rc=$?\"")
check("S6: the AI engine's user cannot connect out directly", code.startswith("000") and "rc=0" not in code, code)
code = sh(c.WEB_C, "agent", "getent hosts example.com >/dev/null 2>&1; echo $?")
check("S6: nor look names up (no DNS: nothing leaves in a lookup)", code.strip() != "0", code)
code = sh(c.WEB_C, "agent", "curl -s -m 10 -o /dev/null -w '%{http_connect}' --proxy http://127.0.0.1:3128 https://example.com")
check("S6: the proxy refuses any other host (403)", code.startswith("403"), code)
code = sh(c.WEB_C, "agent", "curl -s -m 20 -o /dev/null -w '%{http_connect} %{http_code}' --proxy http://127.0.0.1:3128 https://api.anthropic.com/", 40)
check("S6: through the proxy it reaches Anthropic's API", code.startswith("200 ") and not code.endswith(" 000"), code)
env = sh(c.WEB_C, "root", "cat /run/relay/env/agent.json")
try:
    aenv = json.loads(env)
except ValueError:
    aenv = {}
check("S6: the AI engine is told to use the proxy", aenv.get("HTTPS_PROXY") == "http://127.0.0.1:3128" and "127.0.0.1" in aenv.get("NO_PROXY", ""),
      {k: aenv.get(k) for k in ("HTTPS_PROXY", "NO_PROXY")})
code = sh(c.WEB_C, "relay", "curl -s -m 15 -o /dev/null -w '%{http_code}' https://example.com")
check("S6: the web app itself still reaches the internet", code == "200", code)
logs = subprocess.run(["docker", "logs", "--since", "10m", c.WEB_C], capture_output=True, text=True, encoding="utf-8", errors="replace")
check("S6: the proxy logs the refused host (and nothing sent)", "[egress] refused example.com:443" in logs.stdout + logs.stderr, "")

# ---------------------------------------------------------------- S11, S16
v = sh(c.WEB_C, "relay", "python3 -c 'import fastapi, starlette; print(fastapi.__version__, starlette.__version__)'")
check("S11: FastAPI 0.120.4 on Starlette 0.49.3", v == "0.120.4 0.49.3", v)
s, h, t = raw("GET", P, "/login.html", {"Range": "bytes=" + ",".join(f"{i}-{i}" for i in range(0, 3000, 2))})
check("S11: a Range of 1,500 parts still gets the whole file (200)", s == 200, s)
code = sh(c.WEB_C, "root", "cd /opt/genbi/vkit && test -f package-lock.json && npm ls --depth=0 >/dev/null 2>&1; echo $?")
check("S16: the visual kit is installed exactly as its lockfile says", code.strip() == "0", code)

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
