"""Test stack only: item 57 (the user, 2026-11-18, for demos on the live install once its tunnel was removed: "add a option
to show the otp in the screen itself as all is local not in public"). With RELAY_OTP_ON_SCREEN=1 (the test stack sets it
for the admin portal only) an account's sign-in code is shown on the sign-in page instead of emailed, and no bot check is
asked, for a request made on this PC only:
- the admin portal (on): its sign-in options say so; an account's code comes back in the answer and signs in, once; the
  limits still count; an address without an account still gets the usual answer and no code; a request that came
  through a proxy (X-Forwarded-For) gets the emailed path; PASDACS can see a code was shown (auth.otp_shown);
- the public site (off): its options and the emailed path as before, even for a request from this PC;
- who counts as this PC (in the app): loopback and the Docker host, never another address, never with a Cloudflare or
  proxy header, never with the setting off;
- in Chromium, the admin sign-in page shows the code, fills it in and signs in with one click.
Screenshot: item57-admin-signin.png in the run's folder.
python -I -X utf8 item57_check.py <public> <admin>"""
import itertools
import json
import os
import re
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

c._ips = (f"198.18.0.{n}" for n in itertools.count(10))  # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
ADMIN_EMAIL = "info@pasdacs.com"


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def sql(q: str) -> str:
    return subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                          capture_output=True, text=True).stdout.strip()


def in_app(container: str, script: str) -> dict:
    """Python with the app's context in a test container; its last line of output, as JSON."""
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", container, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = (r.stdout or "").strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (ValueError, IndexError):
        return {"raw": (r.stdout or "")[-300:] + (r.stderr or "")[-600:]}


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


# ---------------------------------------------------------------- the admin portal: on
section("the admin portal: the code on the screen")
s, cfg = c.Person("x", c.ADMIN_BASE).get("/auth/providers")
check("admin portal: its sign-in options say the code is shown on this PC, with no bot check",
      s == 200 and isinstance(cfg, dict) and cfg.get("on_screen") is True and not cfg.get("turnstile"), cfg)
c.forget_codes(ADMIN_EMAIL)
a = c.Person(ADMIN_EMAIL, c.ADMIN_BASE)
s, r = a.post("/auth/otp/start", {"email": ADMIN_EMAIL})
code = str(r.get("code") or "") if isinstance(r, dict) else ""
check("admin portal: an account's code comes back in the answer, with the on-screen note",
      s == 200 and bool(re.fullmatch(r"\d{6}", code)) and "shown below" in str(r.get("message")), (s, r))
s, r = a.post("/auth/otp/verify", {"email": ADMIN_EMAIL, "code": code, "next": ""})
check("admin portal: the code from the screen signs in", s == 200 and bool(c.cookie(a, "d2d_admin")), (s, r))
s, me = a.get("/api/me")
check("admin portal: ... as a platform admin", s == 200 and (me.get("org") or {}).get("platform_admin") is True, me)
s, r = a.post("/auth/otp/verify", {"email": ADMIN_EMAIL, "code": code})
check("admin portal: the code works once (400)", s == 400, (s, r))
s, r = a.post("/auth/otp/start", {"email": ADMIN_EMAIL})
check("admin portal: the one-code-a-minute limit still counts (429)", s == 429, (s, r))
c.forget_codes(ADMIN_EMAIL)
s, r = a.post("/auth/otp/start", {"email": ADMIN_EMAIL}, headers={"X-Forwarded-For": "203.0.113.77"})
check("admin portal: through a proxy (X-Forwarded-For) no code comes back: the emailed path",
      s == 200 and isinstance(r, dict) and "code" not in r and "we sent it a sign-in code" in str(r.get("message")), (s, r))
c.forget_codes(ADMIN_EMAIL)
nobody = f"nobody.{S}@pasdacs.com"
t0 = time.time()
s, r = c.Person(nobody, c.ADMIN_BASE).post("/auth/otp/start", {"email": nobody})
check("admin portal: an address without an account gets the usual answer and no code",
      s == 200 and isinstance(r, dict) and "code" not in r and str(r.get("message", "")).startswith(f"If {nobody} has a D2D Relay account")
      and not c.code_now(c.ADMIN_C, nobody, t0, wait=1), (s, r))
c.forget_codes(nobody)
check("admin portal: PASDACS can see a code was shown (auth.otp_shown, the domain only)",
      sql("SELECT count(*) FROM public.audit WHERE action = 'auth.otp_shown' AND detail LIKE '%pasdacs.com%' AND detail NOT LIKE '%info@%'")
      not in ("", "0"), sql("SELECT detail FROM public.audit WHERE action = 'auth.otp_shown' ORDER BY ts DESC LIMIT 1"))

# ---------------------------------------------------------------- the public site: off
section("the public site: the emailed code, as before")
s, cfg = c.Person("x").get("/auth/providers")
check("public site: its sign-in options show no code on screen, and the bot check as before",
      s == 200 and isinstance(cfg, dict) and cfg.get("on_screen") is False and bool(cfg.get("turnstile")), cfg)
pub = c.Person(f"pia@local{S}.com")
c.provision_account(pub.email, f"Local {S}")
t0 = time.time()
s, r = pub.post("/auth/otp/start", {"email": pub.email})       # from this PC with no proxy header, but the setting is off here
check("public site: with the setting off, no code comes back even from this PC (it goes the usual way)",
      s == 200 and isinstance(r, dict) and "code" not in r and bool(c.code_from_logs(c.WEB_C, pub.email, t0)), (s, r))
c.forget_codes(pub.email)

# ---------------------------------------------------------------- who counts as this PC
section("who counts as this PC")
UNIT = r"""
import json
from starlette.requests import Request
from app import otp, portal
def req(host, headers=()):
    return Request({"type": "http", "method": "POST", "path": "/auth/otp/start", "query_string": b"", "client": (host, 50000),
                    "headers": [(k.encode(), v.encode()) for k, v in headers]})
host = sorted(h for h in portal.LOCAL if h not in ("127.0.0.1", "::1"))
otp.ON_SCREEN = True
out = {"loopback": otp.on_screen(req("127.0.0.1")), "ipv6": otp.on_screen(req("::1")),
       "docker_host": bool(host) and otp.on_screen(req(host[0])), "other": otp.on_screen(req("10.1.2.3"))}
for h in otp.PROXY_HEADERS:
    out[h] = otp.on_screen(req("127.0.0.1", [(h, "203.0.113.5")]))
otp.ON_SCREEN = False
out["off"] = otp.on_screen(req("127.0.0.1"))
print(json.dumps(out))
"""
u = in_app(c.WEB_C, UNIT)
check("this PC: loopback and the Docker host count", u.get("loopback") is True and u.get("ipv6") is True and u.get("docker_host") is True, u)
check("this PC: another address never does", u.get("other") is False, u)
check("this PC: never with a Cloudflare or proxy header",
      all(u.get(h) is False for h in ("cf-connecting-ip", "x-forwarded-for", "forwarded", "x-real-ip")), u)
check("this PC: never with the setting off", u.get("off") is False, u)

# ---------------------------------------------------------------- the admin sign-in page in Chromium
section("the admin sign-in page in Chromium")
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
email = sys.argv[1]
typo = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190, 0x2194))
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/login.html")
    page.wait_for_selector("#askform", timeout=20000)
    page.wait_for_timeout(800)
    out["lead"] = page.locator("#lead").inner_text()
    page.fill("#email", email)
    page.click("#askbtn")
    page.wait_for_selector("#shown:not([hidden])", timeout=20000)
    out["shown"] = page.locator("#shown").inner_text().strip()
    out["filled"] = page.input_value("#code")
    out["note"] = page.locator("#note").inner_text()
    page.screenshot(path="/tmp/item57-admin-signin.png", full_page=True)
    page.click("#codebtn")
    page.wait_for_selector("#nav a", timeout=20000)
    out["signed_in"] = True
    out["typo"] = "".join(ch for ch in out["lead"] + out["note"] if ch in typo)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
c.forget_codes(ADMIN_EMAIL)
ui = browser(c.ADMIN_C, PLAY, ADMIN_EMAIL)
check("admin sign-in page: says the code is shown here", "shown here" in str(ui.get("lead")), ui)
check("admin sign-in page: shows the 6-digit code and fills it in",
      bool(re.fullmatch(r"\d{6}", str(ui.get("shown")))) and ui.get("filled") == ui.get("shown"), ui)
check("admin sign-in page: one click on Sign in, and the admin portal opens", ui.get("signed_in") is True, ui)
check("admin sign-in page: plain characters, no script errors", ui.get("typo") == "" and ui.get("errors") == [], ui)
subprocess.run(["docker", "cp", f"{c.ADMIN_C}:/tmp/item57-admin-signin.png", c.out_path("item57-admin-signin.png")], check=False,
               capture_output=True)
c.forget_codes(ADMIN_EMAIL)

# ---------------------------------------------------------------- the start page lists the dashboards (found preparing the demo)
section("the start page after signing in")
s, r = pub.sign_in(again=True, provision=False)
check("public site: Pia signs in (the emailed path)", s == 200, (s, r))
home_name = f"Start page check {S}"
s, d = pub.form("/api/projects", {"name": home_name, "prompt": "Sales by month", "data_mode": "upload"},
                {"files": ("sales.csv", b"month,sales\n2026-01,10\n2026-02,12\n")})
check("public site: she makes a dashboard", s == 200 and isinstance(d, dict) and bool(d.get("id")), (s, str(d)[:200]))
pub.post("/api/me/tour", {"step": "done"})          # a new organisation's owner starts on the first-time tour (#/welcome)
pub.post("/api/org/setup")                          # until both are done
PLAY_HOME = r"""
import json, sys, time
from playwright.sync_api import sync_playwright
cookie, name = sys.argv[1], sys.argv[2]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.route("**/api/projects", lambda route: (time.sleep(1.5), route.continue_()))   # the list arrives late, as after a sign-in
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_timeout(5000)
    out["hash"] = page.evaluate("location.hash")
    out["empty"] = page.locator("main h3:has-text('No dashboards yet')").count()
    out["listed"] = page.locator("main .dcard", has_text=name).count()
    b.close()
print(json.dumps(out))
"""
uh = browser(c.WEB_C, PLAY_HOME, c.cookie(pub, "d2d_session"), home_name)
check("start page: \"/\" lists her dashboard once the list arrives, not \"No dashboards yet\"",
      uh.get("listed") == 1 and uh.get("empty") == 0, uh)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
