"""Test stack only: item 61 (the user, 2026-11-19: "ontology layer as well where we bring default ontology and kpi as per
industry and user can also configure and change"). Each organisation's business vocabulary (webapp/app/ontology.py,
genbi_kit/ontology.py and its industry packs in genbi_kit/ontology_packs/):
- a new organisation reads with the general pack until it has terms of its own; the packs are listed in their order and
  open in full (an unknown one, or a path, is 404);
- applying the grocery-retail pack adds its business terms and its KPIs to the KPI dictionary; again it keeps what is
  there, with replace it takes the pack's versions; an unknown pack is 404; it is audited;
- matching column names: sls_amt is Sales, str_nbr is Store, sls_amt_ly is last year's Sales, gm_pct Gross Margin %;
  a column it does not know is left untagged;
- business terms: add, edit, remove, with their rules (one name, no name two terms of a kind share, kinds and units);
- teaching a column name to a term (zorbl_amt means Sales), once; then the column is tagged;
- export as YAML and import into another organisation (merge, replace; files that are not terms refused);
- who: BI Devs and owners change it, a viewer only reads (403), another organisation never sees it, no session 401;
- PASDACS creating an organisation with an industry starts its ontology with that pack (an unknown one: none);
- in Chromium: the Ontology page (Industry, Business terms) at 1280 and 360 px. Screenshots: item61-*.png.
Its people sign in from 198.18.61.x.
python -I -X utf8 item61_check.py <public> <admin>"""
import itertools
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

c._ips = (f"198.18.61.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190))


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def raw_get(p: c.Person, path: str):
    try:
        with p.http.open(urllib.request.Request(p.base + path), timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Disposition") or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), ""


def upload(p: c.Person, path: str, fields: dict, name: str, data: bytes):
    """A multipart POST with one file under "file"."""
    boundary = "----onto61" + str(time.time_ns())
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                 + data + b"\r\n")
    req = urllib.request.Request(p.base + path, data=b"".join(parts) + f"--{boundary}--\r\n".encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with p.http.open(req, timeout=120) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


def tags(p: c.Person, cols: list[tuple[str, str]]) -> dict:
    s, r = p.post("/api/ontology/match", {"columns": [{"name": n, "type": t} for n, t in cols]})
    return {x["name"]: x.get("tag") for x in (r or {}).get("columns", [])} if s == 200 and isinstance(r, dict) else {"status": s, "answer": r}


def make_viewer(tid: str, email: str) -> None:
    """Test database only: a person of the organisation becomes a viewer of its Default team (not a BI Dev)."""
    schema = "t_" + tid.replace("-", "_")
    g.sql(f"UPDATE {schema}.memberships SET role = 'viewer' WHERE user_id = (SELECT id FROM {schema}.users WHERE email = '{email}')")


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
dom = f"freshco{S}.com"
owner, vic = c.Person(f"fay.owner@{dom}"), c.Person(f"vic.viewer@{dom}")
s, r = owner.sign_in(f"FreshCo {S}", "Fay Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
s, r = vic.sign_in(person="Vic Viewer")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
make_viewer(tid, vic.email)
check("setup: a colleague signs in, a viewer (not a BI Dev)", s == 200 and (vic.get("/api/me")[1] or {}).get("teams", [{}])[0].get("role") == "viewer",
      (s, (vic.get("/api/me")[1] or {}).get("teams")))
other = c.Person(f"ott.owner@otherco{S}.com")
s, r = other.sign_in(f"OtherCo {S}", "Ott Owner")
check("setup: another organisation's owner signs in", s == 200, (s, r))
for p in (owner, vic, other):
    p.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
other.post("/api/org/setup")

# ---------------------------------------------------------------- a new organisation, the packs
section("a new organisation and the industry packs")
s, o = owner.get("/api/ontology")
packs = (o or {}).get("packs") or []
check("new: no terms of its own yet, so the general pack's terms tag its columns", s == 200 and o.get("terms") == [] and o.get("using_default") is True
      and o.get("default_terms", 0) > 20 and o.get("kpis") == 0 and o.get("industry") == {}, {k: (o or {}).get(k) for k in ("terms", "using_default", "default_terms", "kpis", "industry")})
check("new: the 13 industry packs in their order (grocery and retail first, general business last), with their sizes",
      len(packs) == 13 and packs[0].get("id") == "grocery-retail" and packs[-1].get("id") == "general"
      and all(x.get("terms", 0) > 0 and x.get("kpis", 0) > 0 and x.get("name") for x in packs), [(x.get("id"), x.get("terms"), x.get("kpis")) for x in packs])
check("new: the owner may change it; kinds, units and aggregations are offered; the general pack's example questions",
      o.get("may_edit") is True and o.get("kinds") == ["measure", "key", "date", "attribute"] and "currency" in (o.get("units") or [])
      and "distinct_count" in (o.get("aggregations") or []) and len(o.get("questions") or []) >= 3, {k: o.get(k) for k in ("may_edit", "kinds", "units", "questions")})
s, v = vic.get("/api/ontology")
check("new: a viewer reads it and may not change it", s == 200 and v.get("may_edit") is False, (s, (v or {}).get("may_edit")))
s, pk = owner.get("/api/ontology/packs/grocery-retail")
pk = pk if isinstance(pk, dict) else {}
n_terms, n_kpis = len(pk.get("terms") or []), len(pk.get("kpis") or [])
grocery = next((x for x in packs if x.get("id") == "grocery-retail"), {})
check("pack: grocery-retail opens in full: its terms, KPIs and example questions", s == 200 and pk.get("name") == "Grocery and retail"
      and n_terms == grocery.get("terms") and n_kpis == grocery.get("kpis") and len(pk.get("questions") or []) >= 3
      and any(t["name"] == "Store" and t["kind"] == "key" for t in pk.get("terms") or []), (s, pk.get("name"), n_terms, n_kpis))
for bad in ("no-such-pack", "..%2F..%2Fetc%2Fpasswd", "GROCERY-RETAIL"):
    s, r = owner.get(f"/api/ontology/packs/{bad}")
    check(f"pack: {bad} is not a pack (404)", s == 404, (s, r))
s, r = c.Person("x").get("/api/ontology")
check("pack: nobody without a session (401)", s == 401, (s, r))

# ---------------------------------------------------------------- applying the grocery pack
section("applying the grocery-retail pack")
s, r = vic.post("/api/ontology/industry", {"pack": "grocery-retail"})
check("apply: a viewer cannot (403)", s == 403, (s, detail(r)))
s, r = owner.post("/api/ontology/industry", {"pack": "no-such-pack"})
check("apply: an unknown pack (404)", s == 404, (s, detail(r)))
s, r = owner.post("/api/ontology/industry", {"pack": "grocery-retail"})
ap = (r or {}).get("applied") or {} if isinstance(r, dict) else {}
at, ak = ap.get("terms") or {}, ap.get("kpis") or {}
check("apply: the pack's terms are added (none skipped) and its KPIs go into the KPI dictionary",
      s == 200 and ap.get("pack") == "Grocery and retail" and at.get("added") == n_terms and at.get("skipped") == 0
      and ak.get("added", 0) + ak.get("skipped", 0) == n_kpis and ak.get("added", 0) > 0, (s, ap))
s, o = owner.get("/api/ontology")
check("apply: the ontology is the organisation's own now, its industry named, by whom",
      len(o.get("terms") or []) == n_terms and o.get("using_default") is False and (o.get("industry") or {}).get("packs") == ["grocery-retail"]
      and (o.get("industry") or {}).get("name") == "Grocery and retail" and (o.get("industry") or {}).get("by") == "Fay Owner"
      and o.get("kpis") == ak.get("added") and o.get("conflicts") == [], {k: o.get(k) for k in ("industry", "kpis", "conflicts", "using_default")})
check("apply: the example questions are the grocery pack's", o.get("questions") == (pk.get("questions") or [])[:12], o.get("questions"))
s, kd = owner.get("/api/semreview/kpis")
names = {k["name"] for k in (kd or {}).get("kpis") or []}
check("apply: the KPI dictionary (Semantic Review's) has the pack's KPIs, with their DAX where the pack gives it",
      len(names) == ak.get("added") and {"Net Sales", "Sales Growth %"} <= names
      and any(k["name"] == "Sales Growth %" and "DIVIDE" in (k.get("dax") or "") for k in kd.get("kpis") or []), sorted(names)[:8])
s, r = owner.post("/api/ontology/industry", {"pack": "grocery-retail"})
again = ((r or {}).get("applied") or {}) if isinstance(r, dict) else {}
check("apply again: everything it has is kept (nothing added or replaced)", s == 200 and (again.get("terms") or {}).get("kept") == n_terms
      and (again.get("terms") or {}).get("added") == 0 and (again.get("kpis") or {}).get("added") == 0, again)
s, r = owner.post("/api/ontology/industry", {"pack": "grocery-retail", "replace": True})
rep = ((r or {}).get("applied") or {}) if isinstance(r, dict) else {}
check("apply with replace: the pack's versions are taken (all its terms replaced)", s == 200 and (rep.get("terms") or {}).get("replaced") == n_terms,
      rep)
aud = c.in_app(f"""
import json
with _db.use({tid!r}):
    print(json.dumps([r["detail"] for r in _db.audit_log(action="ontology.pack")]))
""")
check("apply: each is audited (ontology.pack, with what it did)", aud.count("replace") >= 3 and '"added": ' + str(n_terms) in aud, aud[-300:])

# ---------------------------------------------------------------- matching column names
section("matching column names")
t = tags(owner, [("sls_amt", "decimal"), ("str_nbr", "int"), ("sls_amt_ly", "decimal"), ("gm_pct", "decimal"), ("zorbl_amt", "decimal"),
                 ("NetSlsAmt", "decimal")])
check("match: sls_amt is Sales (a measure in currency that adds up)", (t.get("sls_amt") or {}).get("term") == "Sales"
      and (t.get("sls_amt") or {}).get("kind") == "measure" and (t.get("sls_amt") or {}).get("unit") == "currency", t.get("sls_amt") or t)
check("match: str_nbr is Store (its key)", (t.get("str_nbr") or {}).get("term") == "Store" and (t.get("str_nbr") or {}).get("kind") == "key",
      t.get("str_nbr") or t)
check("match: sls_amt_ly is Sales, last year's", (t.get("sls_amt_ly") or {}).get("term") == "Sales"
      and (t.get("sls_amt_ly") or {}).get("variant") == "last year", t.get("sls_amt_ly"))
check("match: gm_pct is Gross Margin % (not Gross Margin)", (t.get("gm_pct") or {}).get("term") == "Gross Margin %", t.get("gm_pct"))
check("match: NetSlsAmt (camelCase) is Net Sales", (t.get("NetSlsAmt") or {}).get("term") == "Net Sales", t.get("NetSlsAmt"))
check("match: a column name it does not know is left untagged", "zorbl_amt" in t and t.get("zorbl_amt") is None, t.get("zorbl_amt"))
check("match: each tag says why", "another name for Sales" in str((t.get("str_nbr") or {}).get("why", "")) or "Store" in str((t.get("str_nbr") or {}).get("why", "")),
      t.get("str_nbr"))
t2 = tags(other, [("sls_amt", "decimal")])
check("match: another organisation (no terms of its own) is matched with the general pack", isinstance(t2, dict) and "sls_amt" in t2, t2)

# ---------------------------------------------------------------- business terms
section("business terms")
LOYAL = {"name": "Loyalty Points", "kind": "measure", "unit": "count", "aggregation": "sum", "synonyms": ["pts earned", "loyalty pts"],
         "description": "Points members earn"}
s, lt = owner.post("/api/ontology/terms", LOYAL)
lid = (lt or {}).get("id") if isinstance(lt, dict) else None
check("terms: a term is added (its id, its other names)", s == 200 and str(lid).startswith("t-") and lt.get("synonyms") == ["pts earned", "loyalty pts"], (s, lt))
for body, why in (({**LOYAL, "synonyms": []}, "the same name again"),
                  ({"name": "Points Earned", "kind": "measure", "synonyms": ["loyalty pts"]}, "another measure's other name"),
                  ({"name": "Thing", "kind": "widget"}, "an unknown kind"),
                  ({"name": "Thing", "kind": "measure", "unit": "parsecs"}, "an unknown unit"),
                  ({"name": "  ", "kind": "measure"}, "no name")):
    s, r = owner.post("/api/ontology/terms", body)
    check(f"terms: refused (400): {why}", s == 400, (s, detail(r)))
s, r = owner.post("/api/ontology/terms", {"name": "Loyalty Member", "kind": "key", "entity": "Customer", "synonyms": ["loyalty pts"]})
check("terms: a term of another kind may share a name (the column's type tells them apart)", s == 200, (s, detail(r)))
s, r = owner.put(f"/api/ontology/terms/{lid}", {**LOYAL, "description": "Points members earn on purchases"})
check("terms: edited", s == 200 and r.get("description") == "Points members earn on purchases" and r.get("id") == lid, (s, r))
s, r = owner.put("/api/ontology/terms/t-0000000000", LOYAL)
check("terms: editing one that is not there (404)", s == 404, (s, detail(r)))
s, r = vic.post("/api/ontology/terms", {"name": "Viewer Term", "kind": "attribute"})
check("terms: a viewer cannot add (403)", s == 403, (s, detail(r)))
s, r = vic.delete(f"/api/ontology/terms/{lid}")
check("terms: ... nor remove (403)", s == 403, (s, detail(r)))
t = tags(owner, [("loyalty_pts", "decimal")])
t2 = tags(owner, [("loyalty_pts", "string")])
check("terms: the new terms tag columns at once, the column's type telling the two kinds apart (numbers: the measure, text: the key)",
      (t.get("loyalty_pts") or {}).get("term") == "Loyalty Points" and (t2.get("loyalty_pts") or {}).get("term") == "Loyalty Member", (t, t2))
s, r = owner.delete(f"/api/ontology/terms/{lid}")
s2, r2 = owner.delete(f"/api/ontology/terms/{lid}")
check("terms: removed, and once only (then 404)", s == 200 and s2 == 404, (s, s2))
s, o = owner.get("/api/ontology")
check("terms: the ontology has the pack's terms and the one added", len(o.get("terms") or []) == n_terms + 1, len(o.get("terms") or []))

# ---------------------------------------------------------------- teaching a column name
section("teaching a column name")
s, r = owner.post("/api/ontology/teach", {"term": "Sales", "synonym": "zorbl_amt"})
check("teach: zorbl_amt means Sales", s == 200 and r.get("taught") is True and "zorbl_amt" in (r.get("term") or {}).get("synonyms", []), (s, r))
t = tags(owner, [("zorbl_amt", "decimal")])
check("teach: now the column is tagged Sales on its own (exact, saying so)", (t.get("zorbl_amt") or {}).get("term") == "Sales"
      and (t.get("zorbl_amt") or {}).get("how") == "exact", t)
s, r = owner.post("/api/ontology/teach", {"term": "Sales", "synonym": "ZorblAmt"})
check("teach: the same name again (camelCase reads alike) changes nothing", s == 200 and r.get("taught") is False, (s, r))
s, r = owner.post("/api/ontology/teach", {"term": "No Such Term", "synonym": "abc_col"})
check("teach: a term that is not in the ontology (404)", s == 404, (s, detail(r)))
s, r = owner.post("/api/ontology/teach", {"term": "Sales", "synonym": " _ "})
check("teach: no column name (400)", s == 400, (s, detail(r)))
s, r = vic.post("/api/ontology/teach", {"term": "Sales", "synonym": "viewer_col"})
check("teach: a viewer cannot (403)", s == 403, (s, detail(r)))
s, r = other.post("/api/ontology/teach", {"term": "Sales", "synonym": "qwx_amt"})
s2, o2 = other.get("/api/ontology")
check("teach: an organisation without terms of its own gets its own copy of the general pack's term",
      s == 200 and r.get("taught") is True and [x["name"] for x in o2.get("terms") or []] == ["Sales"] and o2.get("using_default") is False,
      (s, detail(r), [x["name"] for x in (o2 or {}).get("terms") or []]))

# ---------------------------------------------------------------- export and import
section("export and import")
s2, text, disp = raw_get(owner, "/api/ontology/export.yaml")
check("export: a YAML download with the industry, every term (zorbl_amt taught) and the KPIs",
      s2 == 200 and "attachment" in disp and text.startswith("industry: Grocery and retail") and "\nterms:\n" in text
      and "- name: Store\n" in text and "zorbl_amt" in text and "\nkpis:\n" in text and "Sales Growth %" in text, (s2, disp, text[:300]))
yours = c.Person(f"yan.owner@yourco{S}.com")
s, r = yours.sign_in(f"YourCo {S}", "Yan Owner")
s, r = upload(yours, "/api/ontology/import", {"replace": "0"}, "ontology.yaml", text.encode())
imp = ((r or {}).get("imported") or {}) if isinstance(r, dict) else {}
check("import: another organisation imports the export: every business term (the KPIs go through the KPI dictionary's own import)",
      s == 200 and imp.get("added") == n_terms + 1 and len(r.get("terms") or []) == n_terms + 1 and r.get("kpis") == 0, (s, imp, detail(r)))
t = tags(yours, [("zorbl_amt", "decimal")])
check("import: the taught column name came along", (t.get("zorbl_amt") or {}).get("term") == "Sales", t)
s, r = upload(yours, "/api/ontology/import", {"replace": "0"}, "ontology.yaml", text.encode())
check("import again: kept as they are (merge)", s == 200 and ((r or {}).get("imported") or {}).get("kept") == n_terms + 1, (s, (r or {}).get("imported")))
s, r = upload(yours, "/api/ontology/import", {"replace": "1"}, "terms.json",
              json.dumps([{"name": "Sales", "kind": "measure", "unit": "currency", "aggregation": "sum", "synonyms": ["till takings"]}]).encode())
check("import with replace, from a JSON list: the file's version wins", s == 200 and ((r or {}).get("imported") or {}).get("replaced") == 1
      and any(x["name"] == "Sales" and x.get("synonyms") == ["till takings"] for x in (r or {}).get("terms") or []), (s, (r or {}).get("imported")))
for name, data, want, why in (("bad.yaml", b"terms: [unclosed", 400, "YAML that cannot be read"),
                              ("empty.yaml", b"kpis:\n  - name: X\n", 400, "no business terms in it"),
                              ("wrong.yaml", b"terms:\n  - name: X\n    kind: gadget\n", 400, "a term that is not one"),
                              ("big.yaml", b"terms: []\n" + b"#" * (2 * 1024 * 1024 + 10), 413, "over 2 MB")):
    s, r = upload(yours, "/api/ontology/import", {}, name, data)
    check(f"import: refused ({want}): {why}", s == want, (s, detail(r)))
s, r = upload(vic, "/api/ontology/import", {}, "ontology.yaml", text.encode())
check("import: a viewer cannot (403)", s == 403, (s, detail(r)))
s, o = other.get("/api/ontology")
check("separate: another organisation never sees this one's terms", [x["name"] for x in o.get("terms") or []] == ["Sales"], [x["name"] for x in o.get("terms") or []])

# ---------------------------------------------------------------- an organisation made with an industry
section("PASDACS creates an organisation with an industry")
s, r = admin.post("/api/admin/orgs", {"name": f"Hotel Co {S}", "email": f"hal@hotelco{S}.com", "person": "Hal", "industry": "hospitality"})
hid = (((r or {}).get("created") or {}) if isinstance(r, dict) else {}).get("id")
hal = c.Person(f"hal@hotelco{S}.com")
hal.sign_in(provision=False)
s2, ho = hal.get("/api/ontology")
s3, hp = hal.get("/api/ontology/packs/hospitality")
check("industry: its ontology starts with the hospitality pack, applied by PASDACS", s == 200 and hid
      and (ho.get("industry") or {}).get("packs") == ["hospitality"] and (ho.get("industry") or {}).get("by") == "PASDACS"
      and len(ho.get("terms") or []) == len((hp or {}).get("terms") or []) and ho.get("kpis", 0) > 0, (s, detail(r), (ho or {}).get("industry")))
s, r = admin.post("/api/admin/orgs", {"name": f"Odd Co {S}", "email": f"ody@oddco{S}.com", "industry": "no-such-pack"})
ody = c.Person(f"ody@oddco{S}.com")
ody.sign_in(provision=False)
s2, oo = ody.get("/api/ontology")
check("industry: an unknown industry still makes the organisation, with no ontology of its own", s == 200 and s2 == 200
      and oo.get("terms") == [] and oo.get("using_default") is True, (s, detail(r), (oo or {}).get("terms")))

# ---------------------------------------------------------------- the screens
section("the screens")
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, typo = sys.argv[1:3]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for w in (1280, 360):
        ctx = b.new_context(viewport={"width": w, "height": 900})
        ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        res = {}
        for name, hash_ in (("home", "#/ontology"), ("terms", "#/ontology/terms")):
            page.goto("http://127.0.0.1:8000/" + hash_)
            page.wait_for_selector("h1:text-is('Ontology')", timeout=30000)
            page.wait_for_timeout(1500)
            text = page.evaluate("(document.querySelector('main') || document.body).innerText")
            res[name] = text[:4000]
            res[name + "_sideways"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            page.screenshot(path=f"/tmp/item61-{name}-{w}.png", full_page=True)
        res["typo"] = "".join(ch for ch in res["home"] + res["terms"] if ch in typo)
        res["errors"] = errors
        out[str(w)] = res
        ctx.close()
    b.close()
print(json.dumps(out))
"""
ui = browser(c.WEB_C, PLAY, c.cookie(owner, "d2d_session"), TYPO)
w1, w3 = ui.get("1280") or {}, ui.get("360") or {}
check("screen: Ontology, Industry: the grocery pack applied and the other packs to choose from",
      "Grocery and retail" in str(w1.get("home")) and "Healthcare" in str(w1.get("home")),
      str(w1.get("home"))[:600] or ui)
check("screen: Ontology, Business terms: the organisation's terms (Store, Sales)", "Store" in str(w1.get("terms")) and "Sales" in str(w1.get("terms")),
      str(w1.get("terms"))[:600])
check("screen: nothing sideways at 1280 or 360 px", all(x.get(k) is False for x in (w1, w3) for k in ("home_sideways", "terms_sideways")),
      {w: {k: x.get(k) for k in ("home_sideways", "terms_sideways")} for w, x in (("1280", w1), ("360", w3))})
check("screen: plain characters, no script errors", w1.get("typo") == "" and w3.get("typo") == "" and w1.get("errors") == [] and w3.get("errors") == [],
      {w: {k: x.get(k) for k in ("typo", "errors")} for w, x in (("1280", w1), ("360", w3))} | {"stderr": ui.get("stderr")})
for f in ("item61-home-1280.png", "item61-terms-1280.png", "item61-home-360.png", "item61-terms-360.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
