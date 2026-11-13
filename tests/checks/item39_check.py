"""Test stack only: item 39 (the user, 2026-11-13: "allow gmail and all emails but no credits and request credit options,
they can only buy online so i get larger base"; then: organisations keep Request credits, a personal workspace is just
its person, throw-away inboxes stay refused, PASDACS hears of personal sign-ups as of organisations').
- a free mail address (Gmail, Outlook, Yahoo ...) signs in to a personal workspace of its own: nobody else joins it, no
  starting credits, no Request credits, no Add people; it buys online; PASDACS can still add credits by hand;
- throw-away inboxes are still refused; a business domain still makes its organisation, with its starting credits;
- PASDACS is told of each new personal account (the sign-in alert) and sees it on the admin portal;
- the screens: the sign-in page and terms, the Organisation page without Request credits or people, plain characters.
python -I -X utf8 item39_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import pay_check as pc  # noqa: E402

check, S = c.check, c.STAMP
IN = {"cf-ipcountry": "IN"}
PACKS = [{"credits": 25, "price": 2500, "usd": 25}, {"credits": 100, "price": 10000, "usd": 100}]


def section(title: str) -> None:
    print(f"\n== {title}")


def signup(email: str, name: str | None = None, person: str | None = None, create: bool = True):
    """A code from the container's log, the code, and (create) naming the new organisation or workspace.
    Returns (the person, the verify answer, the create answer or None)."""
    p = c.Person(email)
    t0 = time.time()
    s, r = p.post("/auth/otp/start", {"email": email}, headers={"cf-connecting-ip": p.ip})
    if s != 200:
        return p, (s, r), None
    code = c.code_from_logs(c.WEB_C, email, t0)
    v = p.post("/auth/otp/verify", {"email": email, "code": code or "", "next": "#/d2d"})
    made = None
    if create and v[0] == 200 and isinstance(v[1], dict) and v[1].get("organisation"):
        made = p.post("/auth/otp/organisation", {"name": name or v[1]["organisation"]["suggested"], "person": person or ""})
    return p, v, made


def org_of(p) -> dict:
    s, me = p.get("/api/me")
    return ((me or {}).get("org") or {}) if isinstance(me, dict) else {}


def in_app(script: str) -> str:
    """Python with the app's context in the test web container; its last line of output."""
    r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"],
                       input=script, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    lines = (r.stdout or "").strip().splitlines()
    return lines[-1] if lines else (r.stderr or "")[-400:]


# ---------------------------------------------------------------- who may sign in
section("who may sign in")
for addr in (f"temp.{S}@mailinator.com", f"temp.{S}@yopmail.com"):
    s, r = c.Person(addr).post("/auth/otp/start", {"email": addr})
    check(f"throw-away: @{addr.split('@')[1]} is still refused (400)", s == 400 and "throw-away" in str(c.detail_of(r)), (s, r))

g1, g2 = f"gita.{S}@gmail.com", f"hari.{S}@gmail.com"
p1, v1, m1 = signup(g1, f"Gita {S}", "Gita Test")
o1 = v1[1].get("organisation") if isinstance(v1[1], dict) else None
check("gmail: the code works and the next step names a personal workspace", v1[0] == 200 and (o1 or {}).get("personal") is True, v1)
check("gmail: no starting credits and nothing for PASDACS to review", (o1 or {}).get("credits") == 0 and (o1 or {}).get("credits_review") == 0, o1)
check("gmail: the workspace is made and its owner goes on to set it up",
      bool(m1) and m1[0] == 200 and "#/setup" in str((m1[1] or {}).get("next")), m1)
org1 = org_of(p1)
check("gmail: /api/me says personal, keyed by the full address, its owner, no credits and no request",
      org1.get("personal") is True and org1.get("domain") == g1 and org1.get("is_owner") is True and org1.get("credits") == 0
      and not org1.get("pending_request"), org1)

p2, v2, m2 = signup(g2, f"Hari {S}", "Hari Test")
org2 = org_of(p2)
check("gmail: a second address gets a workspace of its own, not the first one's",
      bool(m2) and m2[0] == 200 and org2.get("personal") is True and org2.get("id") and org2.get("id") != org1.get("id"),
      (org1.get("id"), org2.get("id"), m2))
s, d1 = p1.get("/api/org")
check("gmail: each personal workspace holds its one person",
      s == 200 and [x.get("email") for x in d1.get("people", [])] == [g1], d1.get("people") if isinstance(d1, dict) else d1)
c.forget_codes(g1)                             # one code a minute per address: the first one was just now
p1b, v1b, _ = signup(g1, create=False)
check("gmail: signing in again goes straight to the same workspace (no naming step)",
      v1b[0] == 200 and isinstance(v1b[1], dict) and not v1b[1].get("organisation") and org_of(p1b).get("id") == org1.get("id"), v1b)

for addr in (f"yamini.{S}@yahoo.co.in", f"omar.{S}@outlook.com"):
    _, vy, _ = signup(addr, create=False)
    oy = vy[1].get("organisation") if isinstance(vy[1], dict) else None
    check(f"free mail: @{addr.split('@')[1]} is a personal workspace too", vy[0] == 200 and (oy or {}).get("personal") is True, vy)

admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
s, d = admin.get("/api/admin/orgs")
start = d.get("start") if isinstance(d, dict) else None
biz = f"bina@biz{S}.com"
pb = c.Person(biz)
s, r = pb.sign_in(f"Biz {S}")
ob = org_of(pb)
check("business domain: still an organisation by domain, not personal, with its starting credits",
      s == 200 and ob.get("personal") is False and ob.get("domain") == f"biz{S}.com" and ob.get("credits") == start, (ob, start))
s, r = pb.post("/api/org/people", {"email": f"gita.two.{S}@gmail.com", "role": "member"})
check("business domain: a Gmail address cannot be added to the organisation (400)", s == 400, (s, r))

# ---------------------------------------------------------------- a personal workspace buys; it does not ask
section("a personal workspace buys; it does not ask")
s, r = p1.post("/api/org/credit-request", {"credits": 100, "message": "please"})
check("personal: Request credits is refused (403) and names Buy credits", s == 403 and "Buy credits" in str(c.detail_of(r)), (s, r))
s, r = p1.post("/api/org/people", {"email": f"friend.{S}@gmail.com", "role": "member"})
check("personal: Add people is refused (403): just you", s == 403 and "just you" in str(c.detail_of(r)), (s, r))
s, r = p1.post("/api/org/people", {"email": f"x.{S}@biz{S}.com", "role": "member"})
check("personal: ... whatever the address (403)", s == 403, (s, r))
s, d1 = p1.get("/api/org")
check("personal: no credit request on record", s == 200 and d1.get("requests") == [], d1.get("requests") if isinstance(d1, dict) else d1)
msg = in_app(f"from app import db, orgs\nwith db.use(db.PLATFORM):\n    o = orgs.row({org1.get('id')!r})\nprint(orgs._short(o, 'dashboard'))\n")
check("personal: out of credits, it is told to buy, never to request", "your workspace has 0 left" in msg and "Request credits" not in msg, msg)

# ---------------------------------------------------------------- the admin portal
section("the admin portal")
s, d = admin.get("/api/admin/orgs")
mine = next((x for x in (d or {}).get("orgs", []) if x.get("id") == org1.get("id")), {})
check("admin: Organisations lists the workspace as personal, with its address and nothing pending",
      mine.get("personal") is True and mine.get("domain") == g1 and not mine.get("pending"), mine)
s, rq = admin.get("/api/admin/requests")
check("admin: no starting-credit request for a personal workspace", s == 200 and g1 not in json.dumps(rq), (s, str(rq)[:300]))
s, r = admin.post(f"/api/admin/orgs/{org1.get('id')}/credits", {"credits": 30, "note": "item 39 check"})
check("admin: PASDACS can still add credits to a personal workspace by hand", s == 200 and org_of(p1).get("credits") == 30, (s, c.detail_of(r)))

# ---------------------------------------------------------------- buying online
section("buying online")
s, a = admin.put("/api/admin/payments/settings", {"on": True, "who": "owners", "gst": 18, "note": "", "packs": PACKS, "invoice": pc.SELLER})
check("setup: selling switched on (the stand-in Razorpay, keys that look live)", s == 200, (s, c.detail_of(a)))
check("personal: its owner is offered Buy credits, for real money", org_of(p1).get("pay") == {"on": True, "can": True, "test": False},
      org_of(p1).get("pay"))
s, b = p1.call("PUT", "/api/payments/billing", {"name": "Gita Test", "address": "4 Lake Road\nBengaluru", "country": "India",
                                                 "state": "29", "pin": "560003", "gstin": ""}, IN)
check("personal: billing details as a person (no GSTIN)", s == 200 and isinstance(b, dict) and b.get("billing_needed") is False, (s, c.detail_of(b)))
s, r = p1.call("GET", "/api/payments", None, IN)
pk = next((x for x in (r or {}).get("packs", []) if x.get("credits") == 25), None) if isinstance(r, dict) else None
check("personal: the rupee packs, GST added (25 credits: Rs 2,950)", s == 200 and pk and pk["amount"] == 295000 and pk["currency"] == "INR",
      (s, (r or {}).get("packs") if isinstance(r, dict) else r))
s, o = p1.call("POST", "/api/payments/order", {"pack": (pk or {}).get("id", "")}, IN)
check("personal: a checkout opens at (the stand-in) Razorpay", s == 200 and str((o or {}).get("order_id", "")).startswith("order_"), (s, o))

# ---------------------------------------------------------------- PASDACS hears of it
section("PASDACS hears of it")
time.sleep(2)
logs = subprocess.run(["docker", "logs", "--since", "20m", c.WEB_C], capture_output=True, text=True, encoding="utf-8", errors="replace")
text = (logs.stdout or "") + (logs.stderr or "")
check("alert: PASDACS is told of each new personal account (sign-in alert)", f"new personal account {g1}" in text and f"new personal account {g2}" in text,
      [ln[:200] for ln in text.splitlines() if "personal account" in ln][-3:])
check("alert: and gets no starting-credit review mail for it", not any("[org-review]" in ln and g1 in ln for ln in text.splitlines()),
      [ln[:200] for ln in text.splitlines() if "[org-review]" in ln and g1 in ln][:2])

# ---------------------------------------------------------------- the screens
section("the screens")
s, page = c.Person("x").get("/login.html")
check("sign-in page: any email; no 'Use your work email' any more",
      s == 200 and "Enter your email" in str(page) and "Use your work email" not in str(page) and "Create your workspace" in str(page), s)
s, t = c.Person("x").get("/terms.html")
check("terms: personal workspaces described (no free credits, they buy online)", s == 200 and "personal workspace" in str(t) and "buys them online" in str(t), s)
p1.post("/api/me/tour", {"step": "done"})
p1.post("/api/org/setup")
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie = sys.argv[1]
TYPO = "—–…“”‘’·•›‹→←↔"
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/#/org")
    page.wait_for_selector("h3:has-text('Credit history')", timeout=20000)
    page.wait_for_timeout(1500)
    text = page.evaluate("(document.querySelector('main') || document.body).innerText")
    out["eyebrow"] = "Personal workspace" in text
    out["just_you"] = "personal workspace is just you" in text
    out["request_btn"] = page.locator("main button:has-text('Request credits')").count()
    out["add_people"] = page.locator("main :text('Add people')").count()
    out["requests_card"] = page.locator("h3:has-text('Credit requests')").count()
    out["buy_btn"] = page.locator("main button:has-text('Buy credits')").count()
    out["typo"] = "".join(ch for ch in text if ch in TYPO)
    out["stray"] = [ln for ln in text.splitlines() if ln.strip() in ("null", "undefined", "NaN")]
    page.screenshot(path="/tmp/item39-org.png", full_page=True)
    page.click("#orgchip button")
    page.wait_for_timeout(700)
    out["menu_personal"] = page.locator("text=Your personal workspace").count() > 0
    out["menu_request"] = page.locator(".pmitem:has-text('Request credits')").count()
    out["menu_buy"] = page.locator(".pmitem:has-text('Buy credits')").count()
    page.screenshot(path="/tmp/item39-menu.png")
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", c.cookie(p1, "d2d_session")], input=PLAY, capture_output=True,
                     text=True, encoding="utf-8", errors="replace", timeout=300)
try:
    ui = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    ui = {"run": res.returncode, "stderr": (res.stderr or "")[-600:]}
check("screen: the Organisation page says Personal workspace, just you", ui.get("eyebrow") is True and ui.get("just_you") is True, ui)
check("screen: no Request credits, no Add people, no Credit requests card",
      ui.get("request_btn") == 0 and ui.get("add_people") == 0 and ui.get("requests_card") == 0, ui)
check("screen: Buy credits is offered", (ui.get("buy_btn") or 0) >= 1, ui)
check("screen: the top bar menu says Your personal workspace and has Buy credits, not Request credits",
      ui.get("menu_personal") is True and ui.get("menu_request") == 0 and (ui.get("menu_buy") or 0) >= 1, ui)
check("screen: plain characters, no script errors", ui.get("typo") == "" and ui.get("errors") == [], ui)
check("screen: no stray null, undefined or NaN where a card is left out", ui.get("stray") == [], ui.get("stray"))
for f in ("item39-org.png", "item39-menu.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)

ok = sum(1 for _, x in c.RESULTS if x)
print(f"{ok}/{len(c.RESULTS)} checks passed")
sys.exit(0 if ok == len(c.RESULTS) else 1)
