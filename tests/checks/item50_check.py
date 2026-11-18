
"""Test stack only: item 50 (2026-11-14). The user: "can you put a small dashboard in the admin like live users and who
are have signed up". The admin portal opens on an Overview: who is online now (a public-site session seen in the last
five minutes), everyone with an account (newest first; since item 56 people are added, not signed up) and the totals.
- an owner and the colleague PASDACS added to their organisation both show, with their organisation and kind, and online;
- someone not seen for an hour is still listed but no longer online;
- PASDACS's own people are not listed, and a PASDACS person on the admin portal only is not online;
- the public site has no such API; the admin portal's first page is the Overview, with its tiles and tables.
Screenshot: item50-overview.png in the run's folder.
python -I -X utf8 item50_check.py <public> <admin>"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

check = c.check
biz = c.Person(f"bea.biz@ovbiz{c.STAMP}.com")
s1, _ = biz.sign_in("Overview Biz", "Bea Biz")
mate = c.Person(f"max.mate@ovbiz{c.STAMP}.com")
s2, _ = mate.sign_in()
old = c.Person(f"oli.old@ovold{c.STAMP}.com")
s3, _ = old.sign_in("Overview Old", "Oli Old")
check("setup: two organisations' owners and a colleague, all added by PASDACS, sign in", s1 == 200 and s2 == 200 and s3 == 200, (s1, s2, s3))
old_tid = (old.get("/api/me")[1].get("org") or {}).get("id")
out = g.app(f"""
with _db.use({old_tid!r}):
    print(_db.run("UPDATE sessions SET last_seen = last_seen - 3600"))
""")
check("setup: the third was last seen an hour ago", out.strip().splitlines()[-1:] != ["0"], out[-200:])

staff = c.signed_in(f"ops{c.STAMP}@pasdacs.com", c.ADMIN_BASE)       # a PASDACS person on the admin portal only
s, d = staff.get("/api/admin/overview")
check("api: the admin portal answers its overview", s == 200 and isinstance(d, dict) and {"totals", "online", "people"} <= set(d or {}), (s, str(d)[:200]))
d = d if isinstance(d, dict) else {}
by = {r["email"]: r for r in d.get("people") or []}
on = {r["email"] for r in d.get("online") or []}
check("people: the owner, with their organisation, its kind and when they were added", biz.email in by and by[biz.email]["org"] == "Overview Biz"
      and by[biz.email]["personal"] is False and by[biz.email].get("owner") is True and by[biz.email].get("added"), by.get(biz.email))
check("people: the colleague, in the same organisation, not its owner", mate.email in by and by[mate.email]["org"] == "Overview Biz"
      and by[mate.email].get("owner") is False, by.get(mate.email))
check("people: newest first", [r["email"] for r in d.get("people") or []].index(old.email) < [r["email"] for r in d.get("people") or []].index(biz.email)
      if old.email in by and biz.email in by else False, [r["email"] for r in (d.get("people") or [])[:5]])
check("online: both people seen just now are online", {biz.email, mate.email} <= on, sorted(on))
check("online: the one last seen an hour ago is not, but is still listed with a last-seen time", old.email not in on and old.email in by
      and by[old.email].get("last_seen"), by.get(old.email))
check("pasdacs: its people are not listed", not [r for r in d.get("people") or [] if r.get("platform") or r["email"].endswith("@pasdacs.com")],
      [r["email"] for r in d.get("people") or [] if r["email"].endswith("@pasdacs.com")])
check("pasdacs: a PASDACS person on the admin portal only is not online", f"ops{c.STAMP}@pasdacs.com" not in on, sorted(on))
t = d.get("totals") or {}
check("totals: people, today, workspaces by kind and online agree with the lists", t.get("people") == len(d.get("people") or [])
      and t.get("today", 0) >= 3 and t.get("business", 0) >= 2 and t.get("workspaces") == t.get("business", 0) + t.get("personal", 0)
      and t.get("online") == len([r for r in d.get("online") or [] if not r.get("platform")]), t)
s, r = biz.get("/api/admin/overview")
check("public site: no such API for a customer (404)", s == 404, (s, r))

# ---------------------------------------------------------------- the admin portal's first page
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie = sys.argv[1]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_admin", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8000/")
    page.wait_for_selector("h1:text-is('Overview')", timeout=20000)
    page.wait_for_timeout(800)
    out["hash"] = page.evaluate("location.hash")
    out["text"] = page.evaluate("document.body.innerText")
    out["nav"] = page.evaluate("[...document.querySelectorAll('#nav a')].map(a => a.textContent.trim()).filter(Boolean)")
    page.screenshot(path="/tmp/item50-overview.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
cookie = next((k.value for k in staff.jar if k.name == "d2d_admin"), "")
res = subprocess.run(["docker", "exec", "-i", c.ADMIN_C, "python3", "-", cookie], input=PLAY, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=240)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("ui: the browser check ran", bool(o), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
if o:
    txt = o["text"]
    check("ui: the admin portal opens on its Overview", o["hash"] == "#/overview", o["hash"])
    check("ui: its tiles: online now, people, workspaces, dashboards", all(x in txt for x in ("Online now", "People", "Workspaces", "Dashboards"))
          and "signed up" not in txt.lower(), txt[:400])
    check("ui: the people table names the owner and the colleague, with their kind and when they were added",
          biz.email in txt and mate.email in txt and "Business" in txt and "ADDED" in txt.upper(),      # headers show in capitals
          [ln for ln in txt.splitlines() if biz.email in ln or mate.email in ln or "ADDED" in ln.upper()][:6])
    check("ui: Overview comes first in the menu, then Organisations", [n for n in o["nav"] if n in ("Overview", "Organisations")][:2] == ["Overview", "Organisations"],
          o["nav"])
    check("ui: no script errors", not o["errors"], o["errors"])
subprocess.run(["docker", "cp", f"{c.ADMIN_C}:/tmp/item50-overview.png", c.out_path("item50-overview.png")], check=False)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
