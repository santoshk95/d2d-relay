"""Test stack only: item 51 (the user, 2026-11-14: "can you give me nice email for otp rather than plain, in D2D
theme"). The sign-in code email in D2D's look (webapp/app/code_email.py). Mail is stubbed inside the test web and admin
containers, so nothing is emailed:
- with mail not set up (the stack's D2D_OTP_DEV_LOG=1) the code is only printed to the log, as before, never sent;
- with mail set up, otp._mail hands the mailer one email to the address: the subject as before, the code once (a
  leading zero kept), the dark band with the D2D lockup and the mint bar, how long it lasts from otp.TTL; the admin
  portal's email says it is for the admin sign-in page;
- plain keyboard characters only; no pictures, web fonts, scripts or links to stylesheets (nothing is fetched when it
  is opened); HTML in a code is escaped;
- in Chromium: nothing sideways at 320, 375 and 1280 px, the mark's three rows, the code centred in its panel, a dark
  card in dark mode.
Screenshots: item51-email-1280.png, item51-email-375-dark.png, item51-email-admin-1280.png in the run's folder.
python -I -X utf8 item51_check.py <public> <admin>"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check
TO = "ivy.item51@example.com"


def section(title: str) -> None:
    print(f"\n== {title}")


def in_app(container: str, script: str) -> dict:
    """Python with the app's context in a test container; its last line of output, as JSON."""
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", container, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = (r.stdout or "").strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (ValueError, IndexError):
        return {"raw": (r.stdout or "")[-300:] + (r.stderr or "")[-600:]}


MAIL = r"""
import contextlib, io, json
from app import code_email, otp, otp_mail, portal
sent = []
otp_mail.send = lambda to, subject, html, reply_to=None: sent.append({"to": to, "subject": subject, "html": html})
out = {"portal": portal.NAME, "ttl": otp.TTL, "set_up": bool(otp_mail.mode())}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    otp._mail("%(to)s", "123450")                      # the stack as it is: mail not set up
out["printed"], out["sent_unset"] = buf.getvalue().strip(), len(sent)
otp_mail.mode = lambda: "delegated"                    # as on live: the mailbox signed in
otp._mail("%(to)s", "035719")
out["sent"] = sent
out["escaped"] = code_email.render("<b>&</b>", 10)[1]
print(json.dumps(out))
""" % {"to": TO}

for container, admin in ((c.WEB_C, False), (c.ADMIN_C, True)):
    where = "admin portal" if admin else "public site"
    section(f"the email, {where}")
    r = in_app(container, MAIL)
    sent = r.get("sent") or []
    h = sent[0]["html"] if len(sent) == 1 else ""
    check(f"{where}: the container is the {where}", r.get("portal") == ("admin" if admin else "public"), {k: v for k, v in r.items() if k != "sent"})
    check(f"{where}: mail not set up (the stack): the code is only printed to the log, nothing is sent",
          r.get("set_up") is False and str(r.get("printed")).startswith(f"[otp] code for {TO}: 123450") and r.get("sent_unset") == 0,
          {k: r.get(k) for k in ("set_up", "printed", "sent_unset", "raw")})
    check(f"{where}: mail set up: one email to the address, the subject as before",
          len(sent) == 1 and sent[0]["to"] == TO and sent[0]["subject"] == "D2D Relay sign-in code: 035719",
          [{k: v for k, v in m.items() if k != "html"} for m in sent] or r)
    check(f"{where}: the code once in the email, its leading zero kept", h.count("035719") == 1 and h.count("35719") == 1, h.count("35719"))
    check(f"{where}: D2D's look: the dark band, the D2D lockup, the mint bar, the code's mint panel",
          'bgcolor="#111111"' in h and "DATA TO DECISION" in h and 'bgcolor="#00C48C"' in h and 'class="d2d-panel"' in h, len(h))
    check(f"{where}: how long it lasts comes from the code's lifetime (otp.TTL)",
          r.get("ttl") == 600 and f"expires in {r.get('ttl', 0) // 60} minutes" in h, r.get("ttl"))
    if admin:
        check("admin portal: the email says it is for the admin sign-in page", "D2D RELAY ADMIN" in h and "on the admin sign-in page" in h)
    else:
        check("public site: the email names D2D Relay and the sign-in page, not the admin portal",
              "D2D RELAY<" in h and "on the sign-in page" in h and "ADMIN" not in h)
    bad = sorted({ch for ch in h if not (32 <= ord(ch) < 127 or ch in "\n\t")})
    check(f"{where}: plain keyboard characters only", h != "" and not bad, bad)
    check(f"{where}: nothing fetched when it is opened (no pictures, web fonts, scripts or stylesheet links)",
          h != "" and not any(x in h.lower() for x in ("<img", "url(", "@import", "@font-face", "<script", "<link")))
    if not admin:
        e = str(r.get("escaped"))
        check("HTML in a code is escaped", "&lt;b&gt;&amp;&lt;/b&gt;" in e and "<b>&</b>" not in e, e[:80])

# ---------------------------------------------------------------- in Chromium
section("the email in Chromium")
PLAY = r"""
import importlib.util, json
from playwright.sync_api import sync_playwright
spec = importlib.util.spec_from_file_location("code_email", "/srv/app/code_email.py")
ce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ce)
for name, admin in (("public", False), ("admin", True)):
    with open(f"/tmp/item51-{name}.html", "w", encoding="utf-8") as f:
        f.write(ce.render("035719", 10, admin=admin)[1])
PROBE = '''() => {
  const doc = document.documentElement, code = document.querySelector('.d2d-code'), panel = document.querySelector('.d2d-panel').getBoundingClientRect();
  const range = document.createRange(); range.selectNodeContents(code);
  const ink = range.getBoundingClientRect(), gap = parseFloat(getComputedStyle(code).letterSpacing) || 0;
  const rows = [...document.querySelectorAll('td[height="6"][bgcolor]')].map(t => { const b = t.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; });
  return {sideways: doc.scrollWidth > doc.clientWidth, code: code.textContent, off: Math.abs(ink.x + (ink.width - gap) / 2 - (panel.x + panel.width / 2)),
          rows, card: getComputedStyle(document.querySelector('.d2d-card')).backgroundColor, ink: getComputedStyle(code).color};
}'''
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    for name, w, scheme, shot in (("public", 1280, "light", "item51-email-1280.png"), ("public", 375, "dark", "item51-email-375-dark.png"),
                                  ("public", 320, "light", ""), ("admin", 1280, "light", "item51-email-admin-1280.png")):
        ctx = b.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme, is_mobile=w < 768, has_touch=w < 768)
        page = ctx.new_page()
        page.goto(f"file:///tmp/item51-{name}.html")
        out[f"{name}-{w}-{scheme}"] = page.evaluate(PROBE)
        if shot:
            page.screenshot(path=f"/tmp/{shot}", full_page=True)
        ctx.close()
    b.close()
print(json.dumps(out))
"""
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-"], input=PLAY, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=300)
try:
    ui = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    ui = {"run": res.returncode, "stderr": (res.stderr or "")[-600:]}
for key in ("public-1280-light", "public-375-dark", "public-320-light", "admin-1280-light"):
    v = ui.get(key) or {}
    check(f"{key}: nothing sideways; the mark's three rows; the code centred in its panel",
          v.get("sideways") is False and v.get("rows") == [[21, 6], [22, 6], [21, 6]] and v.get("code") == "035719" and v.get("off", 99) <= 2,
          v or ui)
check("light: a white card, the code in ink", (ui.get("public-1280-light") or {}).get("card") == "rgb(255, 255, 255)"
      and (ui.get("public-1280-light") or {}).get("ink") == "rgb(17, 17, 17)", ui.get("public-1280-light"))
check("dark mode: a dark card, the code in light ink", (ui.get("public-375-dark") or {}).get("card") == "rgb(22, 22, 22)"
      and (ui.get("public-375-dark") or {}).get("ink") == "rgb(245, 245, 245)", ui.get("public-375-dark"))
for shot in ("item51-email-1280.png", "item51-email-375-dark.png", "item51-email-admin-1280.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{shot}", c.out_path(shot)], check=False, capture_output=True)

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
sys.exit(0 if ok == len(c.RESULTS) else 1)
