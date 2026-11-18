"""Test stack only: item 56 (the user, 2026-11-18: "Remove signup and bring login directly as internal team management";
D2D is licensed to client organisations, not offered to the public). Nobody signs up:
- an address without an account gets the answer an account gets and no code; any code for it is wrong; the code limits
  count it the same way; PASDACS can see it was asked (auth.otp_no_account); the old sign-up step is gone;
- PASDACS creates an organisation on the admin portal (its name, main owner and starting credits), with its rules; the
  owner signs in with a code, as its main owner, with those credits and the first-time setup due;
- the owners add their people, who then get codes; a removed person gets none; PASDACS can add someone to an
  organisation (a new owner, say), and the owners are told; the public site has none of PASDACS's routes;
- the admin portal: PASDACS addresses with an account in PASDACS's own workspace, added by a PASDACS owner;
- in Chromium: the sign-in page (no organisation step, who sets accounts up), the admin portal's New organisation and
  Person dialogs, the Overview's words, the Organisation page and the tour for an owner; plain characters throughout.
Screenshots: item56-*.png in the run's folder.
python -I -X utf8 item56_check.py <public> <admin>"""
import json
import os
import subprocess
import sys
import time

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

c._ips = iter(f"192.0.2.{n}" for n in range(10, 250))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def org_of(p: c.Person) -> dict:
    s, me = p.get("/api/me")
    return ((me or {}).get("org") or {}) if isinstance(me, dict) else {}


def sql(q: str) -> str:
    return subprocess.run(["docker", "exec", "-u", "postgres", c.DB_C, "psql", "-qtA", "-h", "/run/postgresql", "-d", "relay", "-c", q],
                          capture_output=True, text=True).stdout.strip()


def logs_since(container: str, since: float) -> str:
    out = subprocess.run(["docker", "logs", "--since", str(int(since) - 2), container], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout + out.stderr


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
T0 = time.time()

# ---------------------------------------------------------------- nobody signs up
section("nobody signs up")
dom = f"lic{S}.com"
ana = c.Person(f"ana@{dom}")                    # the main owner-to-be: no account yet
t0 = time.time()
s, r = ana.post("/auth/otp/start", {"email": ana.email}, headers={"cf-connecting-ip": ana.ip})
check("no account: the usual answer", s == 200 and isinstance(r, dict)
      and str(r.get("message", "")).startswith(f"If {ana.email} has a D2D Relay account, we sent it a sign-in code"), (s, r))
check("no account: no code is sent", not c.code_now(c.WEB_C, ana.email, t0), "a code is in the log")
check("no account: PASDACS can see it was asked (auth.otp_no_account, no address kept)",
      sql(f"SELECT count(*) FROM public.audit WHERE action = 'auth.otp_no_account' AND detail LIKE '%{dom}%' AND detail NOT LIKE '%ana@%'")
      not in ("", "0"), sql("SELECT detail FROM public.audit WHERE action = 'auth.otp_no_account' ORDER BY ts DESC LIMIT 1"))
s, r = ana.post("/auth/otp/verify", {"email": ana.email, "code": "123456"})
check("no account: any code is wrong (400)", s == 400 and "wrong" in str(detail(r)), (s, r))
s, r = ana.post("/auth/otp/start", {"email": ana.email}, headers={"cf-connecting-ip": ana.ip})
check("no account: the one-code-a-minute limit counts it like any address (429)", s == 429, (s, r))
for method in ("GET", "POST"):
    s, r = ana.call(method, "/auth/otp/organisation", {"name": "Mine", "person": "Ana"} if method == "POST" else None)
    check(f"the sign-up step is gone ({method} /auth/otp/organisation: 404 or 405, no such route)", s in (404, 405), (s, r))
for addr in (f"gita.{S}@gmail.com", f"temp.{S}@mailinator.com"):
    t1 = time.time()
    s, r = c.Person(addr).post("/auth/otp/start", {"email": addr})
    check(f"no account at @{addr.split('@')[1]}: the usual answer and no code", s == 200 and not c.code_now(c.WEB_C, addr, t1, wait=1), (s, r))

# ---------------------------------------------------------------- PASDACS creates an organisation
section("PASDACS creates an organisation")
s, d = admin.get("/api/admin/orgs")
check("admin: Organisations says what a new organisation starts with, and has no review any more",
      s == 200 and isinstance(d, dict) and d.get("start") == 50 and "review" not in d, {k: d.get(k) for k in ("start", "review")} if isinstance(d, dict) else d)
for body, want, why in (({"name": "", "email": f"x@{dom}"}, 400, "no name"),
                        ({"name": "Lic", "email": "not-an-address"}, 400, "not an address"),
                        ({"name": "Lic", "email": f"gita.{S}@gmail.com"}, 400, "a free mail owner"),
                        ({"name": "Lic", "email": f"temp.{S}@mailinator.com"}, 400, "a throw-away owner"),
                        ({"name": "Lic", "email": ana.email, "credits": -1}, 400, "negative credits"),
                        ({"name": "Second PASDACS", "email": f"someone.{S}@pasdacs.com"}, 409, "a domain that is already an organisation")):
    s, r = admin.post("/api/admin/orgs", body)
    check(f"admin: refused ({want}): {why}", s == want, (s, detail(r)))
s, r = admin.post("/api/admin/orgs", {"name": f"Licensed {S}", "email": ana.email, "person": "Ana Owner", "credits": 40})
made = (r or {}).get("created") or {} if isinstance(r, dict) else {}
check("admin: PASDACS creates the organisation, Ana its main owner, 40 starting credits",
      s == 200 and made.get("id") and (made.get("owner") or {}).get("email") == ana.email, (s, detail(r)))
check("admin: the answer says the owner was not emailed (the test stack has no mail)", made.get("invited") is False, made)
row = next((o for o in (r or {}).get("orgs", []) if o.get("id") == made.get("id")), {}) if isinstance(r, dict) else {}
check("admin: Organisations lists it: its domain, its owner, one person, 40 credits",
      row.get("domain") == dom and (row.get("owner") or {}).get("name") == "Ana Owner" and row.get("people") == 1 and row.get("credits") == 40, row)
s, r = admin.post("/api/admin/orgs", {"name": "Again", "email": f"zoe@{dom}"})
check("admin: a second organisation for the same domain is refused (409)", s == 409 and "already" in str(detail(r)), (s, r))
s, r = ana.sign_in(again=True, provision=False)
o = org_of(ana)
check("owner: Ana gets a code and signs in: the main owner, 40 credits, first-time setup due",
      s == 200 and o.get("id") == made.get("id") and o.get("is_primary") is True and o.get("credits") == 40 and o.get("setup_needed") is True, (s, o))
s, led = ana.get("/api/org")
check("owner: the credit history shows 40 starting credits", any(x["kind"] == "start" and x["delta"] == 40 for x in (led or {}).get("ledger", [])),
      (led or {}).get("ledger"))
s, r = ana.post("/api/admin/orgs", {"name": "Mine", "email": f"x@other{S}.com"})
check("public site: an owner cannot create organisations (404)", s == 404, (s, r))
s, r = ana.post(f"/api/admin/orgs/{made.get('id')}/people", {"email": f"x@{dom}"})
check("public site: ... nor use PASDACS's way of adding people (404)", s == 404, (s, r))

# ---------------------------------------------------------------- the owners add their people
section("the owners add their people")
ben = c.Person(f"ben@{dom}")
t0 = time.time()
s, r = ben.post("/auth/otp/start", {"email": ben.email}, headers={"cf-connecting-ip": ben.ip})
check("people: a colleague at the domain whom nobody added gets no code", s == 200 and not c.code_now(c.WEB_C, ben.email, t0), (s, r))
s, r = ana.post("/api/org/people", {"email": ben.email, "role": "member"})
check("people: Ana adds Ben", s == 200 and (r.get("added") or {}).get("email") == ben.email, (s, detail(r)))
s, r = ben.sign_in(again=True, provision=False)
ob = org_of(ben)
check("people: added, Ben gets a code and signs in as a member", s == 200 and ob.get("id") == made.get("id") and ob.get("is_owner") is False, (s, ob))
s, r = ana.post("/api/org/people", {"email": f"x@other{S}.com"})
check("people: only the organisation's own domain can be added (400)", s == 400 and dom in str(detail(r)), (s, r))
s, o = ana.get("/api/org")
check("people: there is no blocked list any more", s == 200 and "blocked" not in o, sorted(o) if isinstance(o, dict) else o)
ben_id = next((x["id"] for x in (o or {}).get("people", []) if x["email"] == ben.email), None)
s, r = ana.delete(f"/api/org/people/{ben_id}")
check("people: Ana removes Ben", s == 200 and not any(x["email"] == ben.email for x in (r or {}).get("people", [])), (s, detail(r)))
time.sleep(4)                                   # the log is read from 2 s back: past the code he just signed in with
s, r = ben.sign_in(again=True, provision=False)
check("people: removed, Ben gets no code any more", s == 0 and "no code" in str(r), (s, r))
s, r = ana.post("/api/org/unblock", {"email": ben.email})
check("people: the old Unblock is gone (404 or 405: no such route)", s in (404, 405), (s, r))

# ---------------------------------------------------------------- PASDACS adds someone
section("PASDACS adds someone")
cara = c.Person(f"cara@{dom}")
s, r = admin.post(f"/api/admin/orgs/{made.get('id')}/people", {"email": cara.email, "role": "owner"})
check("admin: PASDACS adds Cara as an owner", s == 200 and (r.get("added") or {}).get("email") == cara.email, (s, detail(r)))
s, n = ana.get("/api/notifications")
check("admin: the owners are told", "PASDACS added" in json.dumps(n) and cara.email in json.dumps(n), json.dumps(n)[:300])
s, r = cara.sign_in(again=True, provision=False)
oc = org_of(cara)
check("admin: Cara signs in as an owner, not the main one", s == 200 and oc.get("is_owner") is True and oc.get("is_primary") is False, (s, oc))
for body, tid, want, why in (({"email": f"x@other{S}.com"}, made.get("id"), 400, "an address at another domain"),
                             ({"email": cara.email}, made.get("id"), 409, "someone already in it"),
                             ({"email": f"x@{dom}", "role": "boss"}, made.get("id"), 400, "an unknown role"),
                             ({"email": f"x@{dom}"}, "no-such-org", 404, "an organisation that does not exist")):
    s, r = admin.post(f"/api/admin/orgs/{tid}/people", body)
    check(f"admin: adding is refused ({want}): {why}", s == want, (s, detail(r)))

# ---------------------------------------------------------------- the admin portal: PASDACS's own people
section("the admin portal")
staff = c.Person(f"ops.{S}@pasdacs.com", c.ADMIN_BASE)
t0 = time.time()
s, r = staff.post("/auth/otp/start", {"email": staff.email})
check("admin portal: a @pasdacs.com address without an account gets no code", s == 200 and not c.code_now(c.ADMIN_C, staff.email, t0), (s, r))
pub = c.signed_in("info@pasdacs.com", c.BASE)
s, r = pub.post("/api/org/people", {"email": staff.email, "role": "member"})
check("admin portal: PASDACS's main owner adds a colleague on the public site", s == 200, (s, detail(r)))
s, r = staff.sign_in(again=True, provision=False)
s2, me = staff.get("/api/me")
check("admin portal: the colleague now signs in there, as a platform admin", s == 200 and (me.get("org") or {}).get("platform_admin") is True, (s, r, me))
s, r = c.Person(ana.email, c.ADMIN_BASE).post("/auth/otp/start", {"email": ana.email})
check("admin portal: a client's address is refused there (403)", s == 403, (s, r))
log = logs_since(c.WEB_C, T0)
alert = [ln for ln in log.splitlines() if "[signin-alert]" in ln and ana.email in ln]
check("alert: PASDACS hears of Ana's sign-in as a sign-in (nothing about creating or joining)",
      bool(alert) and "signed in" in alert[-1] and "new organisation" not in alert[-1] and "joined" not in alert[-1], alert[-1:] or log[-300:])

# ---------------------------------------------------------------- the screens
section("the screens")
PLAY_LOGIN = r"""
import json, sys
from playwright.sync_api import sync_playwright
email = sys.argv[1]
typo = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190, 0x2194))
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for w in (360, 1280):
        ctx = b.new_context(viewport={"width": w, "height": 900})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.goto("http://127.0.0.1:8000/login.html")
        page.wait_for_selector("#askform", timeout=20000)
        page.wait_for_timeout(500)
        text = page.evaluate("document.body.innerText")
        out[f"orgform_{w}"] = page.locator("#orgform").count()
        out[f"who_{w}"] = page.locator("#who").inner_text()
        out[f"sideways_{w}"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        out[f"typo_{w}"] = "".join(ch for ch in text if ch in typo)
        if w == 1280:
            try:
                page.wait_for_function("() => typeof BOT === 'undefined' || !BOT.key || !!BOT.token", timeout=30000)
            except Exception:
                pass
            page.fill("#email", email)
            page.click("#askbtn")
            page.wait_for_selector("#codeform:not([hidden])", timeout=20000)
            out["note"] = page.locator("#note").inner_text()
        page.screenshot(path=f"/tmp/item56-signin-{w}.png", full_page=True)
        out[f"errors_{w}"] = errors
        ctx.close()
    b.close()
print(json.dumps(out))
"""
ui = browser(c.WEB_C, PLAY_LOGIN, f"nobody.ui.{S}@unknown{S}.com")
for w in (360, 1280):
    check(f"sign-in page {w} px: no organisation step, and who sets accounts up", ui.get(f"orgform_{w}") == 0
          and "set up by your organisation" in str(ui.get(f"who_{w}")), ui)
    check(f"sign-in page {w} px: plain characters, nothing sideways, no script errors",
          ui.get(f"typo_{w}") == "" and ui.get(f"sideways_{w}") is False and ui.get(f"errors_{w}") == [], ui)
check("sign-in page: an address without an account sees the usual note", "has a D2D Relay account, we sent it a sign-in code" in str(ui.get("note")), ui)

ui_org, ui_owner, ui_person = f"UI Org {S}", f"uma@uiorg{S}.com", f"ivo@uiorg{S}.com"
PLAY_ADMIN = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, name, owner, person = sys.argv[1:5]
typo = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190, 0x2194))
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_admin", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/#/orgs")
    page.wait_for_selector("h1:text-is('Organisations')", timeout=20000)
    page.wait_for_timeout(600)
    out["meta"] = page.locator(".phead .meta").first.inner_text()
    page.click("button:has-text('New organisation')")
    page.wait_for_selector(".modal input[placeholder='name@company.com']", timeout=10000)
    out["dialog"] = page.locator(".modal").last.inner_text()
    page.fill(".modal input[placeholder='For example: Acme Foods']", name)
    page.fill(".modal input[placeholder='name@company.com']", owner)
    page.fill(".modal input[type=number]", "30")
    page.screenshot(path="/tmp/item56-new-org.png")
    page.click(".modal button:has-text('Create')")
    page.wait_for_selector(f"td:has-text('{name}')", timeout=20000)
    page.wait_for_timeout(500)
    out["modal_after_create"] = page.locator(".modal").count()
    page.locator("tr", has_text=name).first.locator("button[aria-label^='Add someone']").click()
    page.wait_for_selector(".modal input[type=email]", timeout=10000)
    out["person_dialog"] = page.locator(".modal").last.inner_text()
    page.fill(".modal input[type=email]", person)
    page.screenshot(path="/tmp/item56-add-person.png")
    page.click(".modal button:has-text('Add')")
    page.wait_for_timeout(2000)
    out["modal_after_add"] = page.locator(".modal").count()
    page.screenshot(path="/tmp/item56-orgs.png", full_page=True)
    page.goto("http://127.0.0.1:8000/#/overview")
    page.wait_for_selector("h1:text-is('Overview')", timeout=20000)
    page.wait_for_timeout(800)
    out["overview"] = page.evaluate("document.body.innerText")
    text = out["meta"] + out["dialog"] + out["person_dialog"] + out["overview"]
    out["typo"] = "".join(ch for ch in text if ch in typo)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
ua = browser(c.ADMIN_C, PLAY_ADMIN, c.cookie(admin, "d2d_admin"), ui_org, ui_owner, ui_person)
check("admin screen: Organisations says nobody signs up and PASDACS creates each organisation", "Nobody signs up" in str(ua.get("meta")), ua.get("meta") or ua)
check("admin screen: New organisation asks for the name, the main owner's email and name, and the starting credits",
      all(x in str(ua.get("dialog")) for x in ("Organisation name", "Main owner's email", "Main owner's name", "Starting credits")), ua.get("dialog") or ua)
check("admin screen: Create closes the dialog and lists the new organisation", ua.get("modal_after_create") == 0, ua)
check("admin screen: Add someone (the person button) adds someone at the organisation's domain",
      "@uiorg" in str(ua.get("person_dialog")) and ua.get("modal_after_add") == 0, ua)
s, d = admin.get("/api/admin/orgs")
mine = next((o for o in (d or {}).get("orgs", []) if o.get("name") == ui_org), {}) if isinstance(d, dict) else {}
check("admin screen: ... the organisation exists with 30 credits, its owner and the person added: 2 people",
      mine.get("credits") == 30 and (mine.get("owner") or {}).get("email") == ui_owner and mine.get("people") == 2, mine)
ov = str(ua.get("overview"))
check("admin screen: the Overview speaks of people added, not sign-ups (headers are shown in capitals)",
      "People" in ov and "ADDED" in ov.upper() and "signed up" not in ov.lower(), ov[:400])
check("admin screen: plain characters, no script errors", ua.get("typo") == "" and ua.get("errors") == [], ua)

ana.post("/api/me/tour", {"step": "done"})
ana.post("/api/org/setup")
PLAY_ORG = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie = sys.argv[1]
typo = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190, 0x2194))
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/#/welcome")
    try:
        page.wait_for_selector("dt:has-text('Who is in it')", timeout=15000)
        out["tour"] = page.evaluate("(() => { const dt = [...document.querySelectorAll('dt')].find(x => x.textContent.trim() === 'Who is in it'); "
                                    "return dt && dt.nextElementSibling ? dt.nextElementSibling.textContent : ''; })()")
    except Exception as e:
        out["tour"] = "none: " + str(e)[:120]
    page.goto("http://127.0.0.1:8000/#/org")
    page.wait_for_selector("h3:has-text('Credit history')", timeout=20000)
    page.wait_for_timeout(1000)
    text = page.evaluate("(document.querySelector('main') || document.body).innerText")
    out["only_added"] = "Only the people its owners add" in text
    out["blocked"] = ("Blocked" in text) or ("Unblock" in text)
    page.click("main button:has-text('Add people')")
    page.wait_for_selector(".modal textarea", timeout=10000)
    out["add_dialog"] = page.locator(".modal").last.inner_text()
    page.screenshot(path="/tmp/item56-org.png", full_page=True)
    out["typo"] = "".join(ch for ch in text + out["add_dialog"] + out["tour"] if ch in typo)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
uo = browser(c.WEB_C, PLAY_ORG, c.cookie(ana, "d2d_session"))
check("owner screen: the tour says who is in the organisation: the people the owner adds", "the people you add" in str(uo.get("tour")), uo.get("tour") or uo)
check("owner screen: the Organisation page says only the people its owners add can sign in, and has no blocked list",
      uo.get("only_added") is True and uo.get("blocked") is False, uo)
check("owner screen: Add people says only the people added there can sign in", "Only the people added here can sign in" in str(uo.get("add_dialog")),
      uo.get("add_dialog") or uo)
check("owner screen: plain characters, no script errors", uo.get("typo") == "" and uo.get("errors") == [], uo)
for f in ("item56-signin-360.png", "item56-signin-1280.png", "item56-org.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)
for f in ("item56-new-org.png", "item56-add-person.png", "item56-orgs.png"):
    subprocess.run(["docker", "cp", f"{c.ADMIN_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
