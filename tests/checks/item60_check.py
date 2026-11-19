"""Test stack only: item 60 (the user, 2026-11-19): one organisation for a company that uses several email domains
(relay.tn_org_domains).
- PASDACS creates an organisation with other domains besides its main owner's (POST /api/admin/orgs "domains"); the
  Organisations rows and /api/me list them, the main one first; free mail, throw-away and malformed domains are refused,
  as is a domain another organisation has (one organisation a domain), also when it is someone else's other domain;
- PASDACS adds a domain (POST /api/admin/orgs/{tid}/domains) and takes one away (DELETE .../domains/{domain}), never the
  main one; the owners are told; both are audited;
- the owners add people at any of the organisation's domains (and PASDACS too), who get codes and sign in; an address at
  another domain is refused with the domains it may have; after a domain is taken away its people keep their accounts
  and nobody new can be added with it;
- in Chromium: the admin portal's New organisation (Other email domains) and the Email domains dialog. Screenshots:
  item60-*.png. Its people sign in from 198.18.60.x.
python -I -X utf8 item60_check.py <public> <admin>"""
import itertools
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

c._ips = (f"198.18.60.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190))


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def org_row(tid: str | None = None, name: str | None = None) -> dict:
    s, d = admin.get("/api/admin/orgs")
    return next((o for o in (d or {}).get("orgs", []) if (tid and o.get("id") == tid) or (name and o.get("name") == name)), {}) \
        if isinstance(d, dict) else {}


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
main, second, third = f"grocer{S}.com", f"grocer-stores{S}.com", f"grocer-pharmacy{S}.com"

# ---------------------------------------------------------------- an organisation with several domains
section("PASDACS creates an organisation with several email domains")
for body, want, why in (({"domains": [f"gita.{S}@gmail.com".split("@")[1]]}, 400, "a free mail service's domain (gmail.com)"),
                        ({"domains": ["mailinator.com"]}, 400, "a throw-away inbox service's domain"),
                        ({"domains": ["not a domain"]}, 400, "something that is not a domain"),
                        ({"domains": ["pasdacs.com"]}, 409, "a domain another organisation has (PASDACS's)")):
    s, r = admin.post("/api/admin/orgs", {"name": f"Grocer {S}", "email": f"gail@{main}", "person": "Gail Grocer", **body})
    check(f"create: refused ({want}) with {why}, and nothing made", s == want and not org_row(name=f"Grocer {S}")
          and not c.has_account(f"gail@{main}"), (s, detail(r)))
s, r = admin.post("/api/admin/orgs", {"name": f"Grocer {S}", "email": f"gail@{main}", "person": "Gail Grocer",
                                      "domains": [f"@{second.upper()}", second, f"{main}"]})
made = ((r or {}).get("created") or {}) if isinstance(r, dict) else {}
tid = made.get("id")
row = org_row(tid)
check("create: the organisation is made with its main domain first and the other one once ('@' and capitals read as one)",
      s == 200 and row.get("domain") == main and row.get("domains") == [main, second], (s, detail(r), row.get("domains")))
aud = g.sql(f"SELECT detail FROM relay.tn_audit WHERE action = 'd2d.org_created' AND tenant_id = '{tid}'")
check("create: the audit names its other domains", second in aud, aud)
s, r = admin.post("/api/admin/orgs", {"name": f"Copycat {S}", "email": f"cole@{second}", "person": "Cole"})
check("one organisation a domain: an owner at its other domain cannot start another (409)", s == 409 and "already" in str(detail(r)), (s, detail(r)))
s, r = admin.post("/api/admin/orgs", {"name": f"Copycat {S}", "email": f"cole@copycat{S}.com", "domains": [second]})
check("one organisation a domain: nor can a new one take it as an other domain (409)", s == 409 and second in str(detail(r)), (s, detail(r)))

gail = c.Person(f"gail@{main}")
s, r = gail.sign_in(provision=False)
mo = (gail.get("/api/me")[1] or {}).get("org") or {}
check("owner: the main owner signs in; /api/me lists the organisation's domains, the main one first",
      s == 200 and mo.get("id") == tid and mo.get("domains") == [main, second] and mo.get("domain") == main, (s, mo.get("domains")))
gail.post("/api/me/tour", {"step": "done"})
gail.post("/api/org/setup")

# ---------------------------------------------------------------- people at any of its domains
section("people at any of its domains")
sam = c.Person(f"sam@{second}")
s, r = gail.post("/api/org/people", {"email": sam.email, "role": "member"})
check("people: the owner adds someone at the other domain", s == 200 and ((r or {}).get("added") or {}).get("email") == sam.email, (s, detail(r)))
s, r = sam.sign_in(provision=False)
so = (sam.get("/api/me")[1] or {}).get("org") or {}
check("people: they get a code and sign in to the organisation", s == 200 and so.get("id") == tid and so.get("is_owner") is False, (s, so))
s, r = gail.post("/api/org/people", {"email": f"x@{third}"})
check("people: an address at a domain the organisation does not have is refused, naming the ones it has (400)",
      s == 400 and f"@{main}" in str(detail(r)) and f"@{second}" in str(detail(r)), (s, detail(r)))
s, r = admin.post(f"/api/admin/orgs/{tid}/people", {"email": f"ola@{second}", "role": "owner"})
check("people: PASDACS can add someone at the other domain too", s == 200, (s, detail(r)))
s, r = admin.post(f"/api/admin/orgs/{tid}/people", {"email": f"x@{third}"})
check("people: ... not at a domain the organisation does not have (400)", s == 400, (s, detail(r)))
helper = c.Person(f"hal@{second}")
c.provision_account(helper.email)                    # the suites' own helper adds a person at an organisation's other domain
check("people: an address at the other domain is added to this organisation (not a new one)",
      g.sql(f"SELECT home_tenant FROM relay.tn_accounts WHERE email = '{helper.email}'") == tid,
      g.sql(f"SELECT home_tenant FROM relay.tn_accounts WHERE email = '{helper.email}'"))

# ---------------------------------------------------------------- PASDACS adds and takes away domains
section("PASDACS adds a domain and takes one away")
for dom, want, why in (("gmail.com", 400, "a free mail service's"), ("yopmail.com", 400, "a throw-away service's"),
                       ("x", 400, "not a domain"), (main, 409, "its main one, already its"), (second, 409, "already one of its"),
                       ("pasdacs.com", 409, "another organisation's")):
    s, r = admin.post(f"/api/admin/orgs/{tid}/domains", {"domain": dom})
    check(f"add: refused ({want}): {why}", s == want, (s, detail(r)))
s, r = admin.post(f"/api/admin/orgs/no-such-org-{S}/domains", {"domain": f"nowhere{S}.com"})
check("add: an organisation that does not exist (404)", s == 404, (s, detail(r)))
s, r = admin.post(f"/api/admin/orgs/{tid}/domains", {"domain": f" {third.upper()} "})
row = next((o for o in (r or {}).get("orgs", []) if o.get("id") == tid), {}) if isinstance(r, dict) else {}
check("add: PASDACS adds a third domain (spaces and capitals cleaned), listed last", s == 200 and row.get("domains") == [main, second, third],
      (s, detail(r), row.get("domains")))
s, n = gail.get("/api/notifications")
check("add: the owners are told the new domain's addresses can join", f"@{third} addresses can join" in json.dumps(n), json.dumps(n)[:300])
s, r = gail.post("/api/org/people", {"email": f"pat@{third}", "role": "member"})
check("add: the owner can now add people at it", s == 200, (s, detail(r)))
s, r = gail.post("/api/admin/orgs/" + str(tid) + "/domains", {"domain": f"mine{S}.com"})
check("add: the owner cannot add domains (admin portal only: 404)", s == 404, (s, detail(r)))
s, r = admin.delete(f"/api/admin/orgs/{tid}/domains/{main}")
check("remove: the main domain stays (400)", s == 400 and "main domain" in str(detail(r)), (s, detail(r)))
s, r = admin.delete(f"/api/admin/orgs/{tid}/domains/nothere{S}.com")
check("remove: a domain that is not its own (404)", s == 404, (s, detail(r)))
s, r = admin.delete(f"/api/admin/orgs/{tid}/domains/{second}")
row = next((o for o in (r or {}).get("orgs", []) if o.get("id") == tid), {}) if isinstance(r, dict) else {}
check("remove: PASDACS takes the second domain away", s == 200 and row.get("domains") == [main, third], (s, detail(r), row.get("domains")))
aud = g.sql(f"SELECT action || ' ' || detail FROM relay.tn_audit WHERE action IN ('d2d.org_domain_added', 'd2d.org_domain_removed') "
            f"AND tenant_id = '{tid}' ORDER BY id")
check("remove: adding and taking away are audited", third in aud and second in aud and "removed" in aud, aud)
s, me = sam.get("/api/me")
check("remove: the people at it keep their accounts and sessions", s == 200 and ((me or {}).get("org") or {}).get("id") == tid, (s, me))
s, r = sam.sign_in(again=True, provision=False)
check("remove: ... and still sign in with a code", s == 200, (s, r))
s, r = gail.post("/api/org/people", {"email": f"new@{second}"})
check("remove: nobody new can be added with it, by the owners (400)", s == 400 and f"@{second}" not in str(detail(r)), (s, detail(r)))
s, r = admin.post(f"/api/admin/orgs/{tid}/people", {"email": f"newer@{second}"})
check("remove: ... or by PASDACS (400)", s == 400, (s, detail(r)))

# a personal workspace has no domains to add (item 39)
gm = f"pat.{S}@gmail.com"
s, r = admin.post("/api/admin/orgs", {"name": f"Pat {S}", "email": f"pat@patws{S}.com", "credits": 0})
ptid = (((r or {}).get("created") or {}) if isinstance(r, dict) else {}).get("id")
g.sql(f"UPDATE relay.tn_orgs SET personal = 1, domain = '{gm}' WHERE tenant_id = '{ptid}'")
s, r = admin.post(f"/api/admin/orgs/{ptid}/domains", {"domain": f"patcorp{S}.com"})
check("personal: a personal workspace (one address) cannot be given domains (400)", s == 400 and "personal" in str(detail(r)), (s, detail(r)))
check("personal: and its row lists just its address", org_row(ptid).get("domains") == [gm], org_row(ptid).get("domains"))

# ---------------------------------------------------------------- the screens
section("the screens")
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, name, dom, typo = sys.argv[1:5]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_admin", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/#/orgs")
    page.wait_for_selector("h1:text-is('Organisations')", timeout=30000)
    page.wait_for_timeout(800)
    page.click("button:has-text('New organisation')")
    page.wait_for_selector(".modal input[placeholder='name@company.com']", timeout=10000)
    page.wait_for_function("() => (document.querySelector('.modal input[type=number]') || {}).value", timeout=10000)
    page.evaluate("() => new Promise(done => setTimeout(done, 100))")
    out["new_dialog"] = page.locator(".modal").last.inner_text()
    out["industries"] = page.locator(".modal select option").count()
    page.screenshot(path="/tmp/item60-new-org.png")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    if page.locator(".modal").count():
        page.locator(".modal header button:has-text('Close')").first.click(timeout=3000)
    page.locator("tr", has_text=name).first.locator(f"button[aria-label='Email domains of {name}']").click()
    # the dialog titled for the organisation; its one text field adds a domain (found by its place, not its example text)
    dlg = page.locator(".modal [role=dialog]", has=page.locator(f"header b:text-is('Email domains of {name}')"))
    dlg.locator("input[type=text]").wait_for(timeout=10000)
    page.evaluate("() => new Promise(done => setTimeout(done, 100))")
    out["before"] = dlg.inner_text()
    dlg.locator("input[type=text]").fill(dom)
    dlg.locator("button:has-text('Add')").click()
    page.wait_for_function(f"() => [...document.querySelectorAll('.modal span')].some(x => x.textContent.startsWith('@{dom}'))", timeout=10000)
    out["after"] = page.locator(".modal").last.inner_text()
    page.screenshot(path="/tmp/item60-domains.png")
    page.click(".modal button:has-text('Done')")
    page.wait_for_timeout(1000)
    text = out["new_dialog"] + out["before"] + out["after"]
    out["typo"] = "".join(ch for ch in text if ch in typo)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
fourth = f"grocer-fuel{S}.com"
ui = browser(c.ADMIN_C, PLAY, c.cookie(admin, "d2d_admin"), f"Grocer {S}", fourth, TYPO)
check("screen: New organisation asks for other email domains and an industry to start from",
      "Other email domains" in str(ui.get("new_dialog")) and "Industry" in str(ui.get("new_dialog")) and ui.get("industries", 0) >= 10,
      {k: ui.get(k) for k in ("new_dialog", "industries", "stderr")})
check("screen: Email domains lists the main one (Main) and the others", "@" + main in str(ui.get("before")) and "Main" in str(ui.get("before"))
      and "@" + third in str(ui.get("before")), ui.get("before") or ui)
check("screen: a domain added there is listed and saved", "@" + fourth in str(ui.get("after")) and org_row(tid).get("domains") == [main, third, fourth],
      (ui.get("after"), org_row(tid).get("domains")))
check("screen: plain characters, no script errors", ui.get("typo") == "" and ui.get("errors") == [], {k: ui.get(k) for k in ("typo", "errors", "stderr")})
for f in ("item60-new-org.png", "item60-domains.png"):
    subprocess.run(["docker", "cp", f"{c.ADMIN_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
