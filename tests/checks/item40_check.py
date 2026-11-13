"""Test stack only: item 40 (the user, 2026-11-13: "bot check add back"): Cloudflare Turnstile before a sign-in code is
emailed, now that anyone can sign up (item 39). The stack runs with Cloudflare's published test keys, which pass any
token; every other suite sends one (d2d_checks.Person). Here:
- the public sign-in page gets the site key and shows the widget; the admin portal neither shows nor asks for it;
- no token: 403, no code, and the address's one-code-a-minute limit is not used up; a token: the code goes out;
- Cloudflare saying no (its always-fail test key), Cloudflare out of reach, a token made for another action: no code;
- in Chromium the widget appears under the form, a code is asked for and sent, nothing sideways at 320 and 1280 px.
python -I -X utf8 item40_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check, S = c.check, c.STAMP
TEST_SITE_KEY = "1x00000000000000000000AA"


def section(title: str) -> None:
    print(f"\n== {title}")


def in_app(script: str) -> str:
    """Python with the app's context in the test web container; its last line of output."""
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = (r.stdout or "").strip().splitlines()
    return lines[-1] if lines else (r.stderr or "")[-400:]


# ---------------------------------------------------------------- the settings reach the right pages
section("the site key")
s, cfg = c.Person("x").get("/auth/providers")
check("public site: /auth/providers gives the sign-in page Turnstile's site key", s == 200 and cfg.get("turnstile") == TEST_SITE_KEY, cfg)
s, cfg = c.Person("x", c.ADMIN_BASE).get("/auth/providers")
check("admin portal: no site key (it never asks)", s == 200 and not cfg.get("turnstile"), cfg)
s, page = c.Person("x").get("/login.html")
check("sign-in page: the widget's place and Turnstile's loader are in it",
      s == 200 and 'id="botcheck"' in str(page) and "challenges.cloudflare.com/turnstile/v0/api.js" in str(page), s)

# ---------------------------------------------------------------- no token, no code
section("no token, no code")
p = c.Person(f"nora.{S}@bots{S}.com")
hdr = {"cf-connecting-ip": p.ip}
t0 = time.time()
s, r = p.post("/auth/otp/start", {"email": p.email, "turnstile": ""}, headers=hdr)
check("no token: refused (403) with a plain reason", s == 403 and "security check" in str(c.detail_of(r)), (s, r))
time.sleep(2)
check("no token: no code was made or sent", c.code_from_logs(c.WEB_C, p.email, t0) is None, "a code is in the log")
t1 = time.time()
s, r = p.post("/auth/otp/start", {"email": p.email}, headers=hdr)
code = c.code_from_logs(c.WEB_C, p.email, t1)
check("with a token, at once: the code goes out (the refusal used none of the one-a-minute limit)", s == 200 and code, (s, r))
s, r = p.post("/auth/otp/verify", {"email": p.email, "code": code or "", "next": ""})
check("... and the code signs in as before", s == 200 and isinstance(r, dict) and (r.get("organisation") or r.get("ok")), (s, r))
s, r = c.Person(f"olaf.{S}@bots{S}.com").post("/auth/otp/start", {"email": f"olaf.{S}@bots{S}.com", "turnstile": "x" * 3000})
check("a token longer than any real one: refused (403)", s == 403, (s, r))

section("the admin portal never asks")
c.forget_codes("info@pasdacs.com")
t2 = time.time()
s, r = c.Person("info@pasdacs.com", c.ADMIN_BASE).post("/auth/otp/start", {"email": "info@pasdacs.com", "turnstile": ""})
check("admin portal: a PASDACS address gets its code without a token", s == 200 and c.code_from_logs(c.ADMIN_C, "info@pasdacs.com", t2), (s, r))

# ---------------------------------------------------------------- Cloudflare's answers, inside the app
section("Cloudflare's answers")
out = in_app("from app import otp\notp.TURNSTILE_SECRET = '2x0000000000000000000000000000000AA'\n"
             "print(otp._human('XXXX.DUMMY.TOKEN.XXXX', ''))\n")
check("Cloudflare says no (its always-fail test key): not a person", out == "False", out)
out = in_app("from app import otp\nprint(otp._human('XXXX.DUMMY.TOKEN.XXXX', '203.0.113.9'))\n")
check("Cloudflare says yes (the stack's always-pass key)", out == "True", out)
out = in_app("from app import otp\notp.TURNSTILE_VERIFY = 'http://127.0.0.1:9/'\nprint(otp._human('XXXX.DUMMY.TOKEN.XXXX', ''))\n")
check("Cloudflare out of reach: no answer, so no code (None)", out == "None", out)
out = in_app("from app import otp\n"
             "class R:\n    def __init__(self, a): self.a = a\n    def json(self): return {'success': True, 'action': self.a}\n"
             "otp.httpx.post = lambda *a, **k: R('login')\nx = otp._human('t', '')\n"
             "otp.httpx.post = lambda *a, **k: R('otp-start')\nprint(x, otp._human('t', ''))\n")
check("a token made for another action is refused; one for otp-start passes", out == "False True", out)
out = in_app("from app import otp\nprint(otp.turnstile_on(), bool(otp.TURNSTILE_SITE_KEY), bool(otp.TURNSTILE_SECRET))\n")
check("the web app has the check on (both keys)", out == "True True True", out)

# ---------------------------------------------------------------- in Chromium
section("the sign-in page in Chromium")
email = f"pia.{S}@bots{S}.com"
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
email = sys.argv[1]
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    for w in (320, 1280):
        ctx = b.new_context(viewport={"width": w, "height": 900}, is_mobile=w < 768, has_touch=w < 768)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.goto("http://127.0.0.1:8000/login.html")
        try:
            page.wait_for_function("() => typeof BOT !== 'undefined' && !!BOT.token", timeout=30000)
            out[f"token_{w}"] = page.evaluate("BOT.token")
        except Exception as e:
            out[f"token_{w}"] = "none: " + str(e)[:120]
        out[f"widget_{w}"] = page.evaluate("document.querySelector('#botcheck').getBoundingClientRect().height") > 40
        out[f"sideways_{w}"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        page.screenshot(path=f"/tmp/item40-signin-{w}.png", full_page=True)
        if w == 1280:
            page.fill("#email", email)
            page.click("#askbtn")
            page.wait_for_selector("#codeform:not([hidden])", timeout=20000)
            out["note"] = page.locator("#note").inner_text()
            out["error"] = page.locator("#error").inner_text() if page.locator("#error").is_visible() else ""
            out["token_after"] = page.evaluate("BOT.token")
            page.click("#again")
            page.wait_for_timeout(500)
            out["resend_back"] = page.evaluate("!document.querySelector('#askform').hidden && document.querySelector('#codeform').hidden")
        out[f"errors_{w}"] = errors
        ctx.close()
    b.close()
print(json.dumps(out))
"""
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", email], input=PLAY, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=300)
try:
    ui = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    ui = {"run": res.returncode, "stderr": (res.stderr or "")[-600:]}
for w in (320, 1280):
    check(f"{w} px: the widget renders and gives its token", ui.get(f"widget_{w}") is True and ui.get(f"token_{w}") == "XXXX.DUMMY.TOKEN.XXXX", ui)
    check(f"{w} px: nothing sideways, no script errors", ui.get(f"sideways_{w}") is False and ui.get(f"errors_{w}") == [], ui)
check("1280 px: Continue sends the code (the token went with it)", "We sent a sign-in code" in str(ui.get("note")) and not ui.get("error"), ui)
check("1280 px: the widget is reset for the next ask (a token works once)", ui.get("token_after") in ("", "XXXX.DUMMY.TOKEN.XXXX"), ui)
check("1280 px: Resend code goes back to the email step for a fresh check", ui.get("resend_back") is True, ui)
for w in (320, 1280):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item40-signin-{w}.png", c.out_path(f"item40-signin-{w}.png")], check=False, capture_output=True)

s, t = c.Person("x").get("/privacy.html")
check("privacy notice: names Cloudflare's Turnstile check on the sign-in page", s == 200 and "Turnstile" in str(t), s)

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
sys.exit(0 if ok == len(c.RESULTS) else 1)
