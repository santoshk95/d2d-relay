"""Test stack only: item 62, a dashboard's semantic model (GET and PUT /api/projects/<id>/semantic, webapp/app/ontology.py).
Before Relay plans, the worker reads the data (worker.read_data): the organisation's ontology goes into the dashboard's
folder (ontology.json, ontology.md), every column is profiled and tagged with its business term, keys of one entity under
different names and the relationships found are listed. Checked on a dashboard seeded into the organisation's folder
(d2d_checks.seed_project: CSVs, project.json waiting at Confirm KPIs, worker.read_data run in the test web container) of
an organisation with the grocery-retail pack, and on one imported from a DAWB hand-off (its data read at the import):
- GET: the tables, columns, types and tags (sls_amt Sales, str_nbr and store_id Store, sls_amt_ly last year's Sales),
  the Store key under two names, the relationship, the counts, the industry, the terms a column can be given, the
  person's rights, how much data was read; ontology.json and ontology.md written, project.json semantic_ready;
- PUT (free, only while the plan waits at Confirm KPIs): the person's own term for a column (how: person), no term, the
  profile made again with them and kept on the next read; unknown columns and terms refused; 409 once the plan is
  confirmed;
- an imported hand-off's plan KPIs matched to the KPI dictionary (plan_dictionary);
- who: another organisation and a colleague without access get 404, no session 401;
- in Chromium: the plan screen's Semantic model card. Screenshot: item62-plan.png.
Its people sign in from 198.18.62.x.
python -I -X utf8 item62_check.py <public> <admin>"""
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

c._ips = (f"198.18.62.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
TYPO = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190))


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


def project_json(pid: str) -> dict:
    return c.last_json(c.in_app(f"""
import json
from app import store
with _db.use({tid!r}):
    print(json.dumps(store.load({pid!r})))
"""))


def col(view: dict, file: str, name: str) -> dict:
    t = next((t for t in (view or {}).get("tables") or [] if t.get("file") == file), {})
    return next((x for x in t.get("columns") or [] if x.get("name") == name), {})


SALES = "txn_dt,str_nbr,sls_amt,sls_amt_ly,units_sold\n" + "".join(
    f"2026-10-{1 + i % 28:02d},{1 + i % 5},{100 + (i * 37) % 400}.{i % 100:02d},{90 + (i * 29) % 380}.50,{1 + i % 9}\n" for i in range(60))
STORES = "store_id,store_name,banner\n1,North Main,Alpha\n2,South Side,Beta\n3,West End,Alpha\n4,East Gate,Beta\n5,Harbour,Alpha\n"

dom = f"shelf{S}.com"
owner, mia = c.Person(f"sol.owner@{dom}"), c.Person(f"mia.member@{dom}")
s, r = owner.sign_in(f"Shelf Co {S}", "Sol Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
s, r = mia.sign_in(person="Mia Member")
other = c.Person(f"ova.owner@elsewhere{S}.com")
s2, r2 = other.sign_in(f"Elsewhere {S}", "Ova Owner")
check("setup: a colleague and another organisation's owner sign in", s == 200 and s2 == 200, (s, s2))
for p in (owner, mia, other):
    p.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
other.post("/api/org/setup")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
s, r = owner.post("/api/ontology/industry", {"pack": "grocery-retail"})
check("setup: the organisation's ontology is the grocery-retail pack", s == 200, (s, detail(r)))

# ---------------------------------------------------------------- the data read before planning
section("the data read before Relay plans")
seed = c.seed_project(tid, owner.email, f"Store sales {S}", {"sales.csv": SALES, "stores.csv": STORES}, announce=True)
pid = seed.get("id")
check("seed: a dashboard waiting at Confirm KPIs, its data read in the test web container (worker.read_data)", bool(pid) and seed.get("tables") == 2, seed)
s, sem = owner.get(f"/api/projects/{pid}/semantic")
sem = sem if isinstance(sem, dict) else {}
view = sem.get("view") or {}
check("GET: the semantic model of both files, with their rows", s == 200 and sorted((t["file"], t["rows"]) for t in view.get("tables") or []) ==
      [("sales.csv", 60), ("stores.csv", 5)], (s, [(t.get("file"), t.get("rows")) for t in view.get("tables") or []]))
tg = lambda f, n: (col(view, f, n).get("tag") or {})                                   # noqa: E731
check("GET: each column with its type (dates, whole numbers, decimals, text)", col(view, "sales.csv", "txn_dt").get("type") == "date"
      and col(view, "sales.csv", "str_nbr").get("type") == "int" and col(view, "sales.csv", "sls_amt").get("type") == "decimal"
      and col(view, "stores.csv", "store_name").get("type") == "string", [(x["name"], x["type"]) for t in view.get("tables") or [] for x in t["columns"]])
check("GET: sls_amt is tagged Sales, a measure in currency, saying why", tg("sales.csv", "sls_amt").get("term") == "Sales"
      and tg("sales.csv", "sls_amt").get("unit") == "currency" and tg("sales.csv", "sls_amt").get("why"), tg("sales.csv", "sls_amt"))
check("GET: sls_amt_ly is last year's Sales", tg("sales.csv", "sls_amt_ly").get("term") == "Sales"
      and tg("sales.csv", "sls_amt_ly").get("variant") == "last year", tg("sales.csv", "sls_amt_ly"))
check("GET: str_nbr and store_id are both the Store key", tg("sales.csv", "str_nbr").get("term") == "Store" and tg("stores.csv", "store_id").get("term") == "Store"
      and tg("stores.csv", "store_id").get("kind") == "key", (tg("sales.csv", "str_nbr"), tg("stores.csv", "store_id")))
semx = view.get("semantic") or {}
check("GET: the Store key under two names in two tables is a likely relationship", any(k.get("entity") == "Store"
      and sorted(k.get("columns") or []) == ["sales.csv[str_nbr]", "stores.csv[store_id]"] for k in semx.get("keys") or []), semx.get("keys"))
check("GET: the relationship found in the values (each str_nbr is a store_id)", any(r_.get("many") == "sales.csv[str_nbr]"
      and r_.get("one") == "stores.csv[store_id]" for r_ in view.get("relationships") or []), view.get("relationships"))
counts = semx.get("counts") or {}
check("GET: how many columns are tagged, of how many", counts.get("columns") == 8 and 5 <= counts.get("tagged", 0) <= 8, counts)
check("GET: the industry, the terms a column can be given, may tag (waiting at Confirm KPIs) and may teach (a BI Dev)",
      view.get("industry") == "Grocery and retail" and any(t.get("name") == "Cases" for t in sem.get("terms") or [])
      and sem.get("may_tag") is True and sem.get("may_teach") is True and sem.get("overrides") == {}, {k: sem.get(k) for k in ("may_tag", "may_teach", "overrides", "industry")})
size = sem.get("data_size") or {}
check("GET: how much data was read (2 files, 65 rows, nothing sampled)", size.get("total_rows") == 65 and size.get("used_rows") == 65
      and size.get("sampled") == {} and len(size.get("files") or []) == 2 and view.get("sample") is None, size)
folder = f"/data/projects/.tenants/{tid}/{pid}"
onto = g.sh(f"cd {folder} && ls ontology.json ontology.md profile.json && grep -c 'Sales' ontology.md && grep -o '\"industry\": \"[^\"]*\"' ontology.json")
check("folder: ontology.json (the organisation's terms and KPIs) and ontology.md (the agent's guide) written beside profile.json",
      "ontology.json" in onto and "ontology.md" in onto and '"industry": "Grocery and retail"' in onto, onto)
pj = project_json(pid)
check("project.json: semantic_ready and data_size set", bool(pj.get("semantic_ready")) and (pj.get("data_size") or {}).get("total_rows") == 65,
      {k: pj.get(k) for k in ("semantic_ready", "data_size")})
act = owner.get(f"/api/projects/{pid}/activity")[1] or []
texts = [e.get("text") or "" for e in act if isinstance(e, dict)]
check("activity: Relay says what it read (tables, columns matched to the ontology, likely relationships)",
      any("read your data: 2 tables" in t.lower() and "matched to your ontology (Grocery and retail)" in t for t in texts), texts[-3:])

# ---------------------------------------------------------------- the person's own terms
section("the person tags columns (PUT, free)")
before = (owner.get("/api/me")[1] or {}).get("org", {}).get("credits")
s, r = owner.put(f"/api/projects/{pid}/semantic", {"overrides": {"sales.csv[units_sold]": "cases", "sales.csv[sls_amt_ly]": ""}})
view2 = (r or {}).get("view") or {} if isinstance(r, dict) else {}
check("PUT: units_sold is Cases as the person says (the term's own spelling kept), chosen by a person",
      s == 200 and (col(view2, "sales.csv", "units_sold").get("tag") or {}).get("term") == "Cases"
      and (col(view2, "sales.csv", "units_sold").get("tag") or {}).get("how") == "person", (s, detail(r), col(view2, "sales.csv", "units_sold")))
check("PUT: sls_amt_ly has no term now (the person said none)", s == 200 and not col(view2, "sales.csv", "sls_amt_ly").get("tag"),
      col(view2, "sales.csv", "sls_amt_ly"))
check("PUT: the answer carries the overrides, and nothing was charged", (r or {}).get("overrides") == {"sales.csv[units_sold]": "Cases", "sales.csv[sls_amt_ly]": ""}
      and (owner.get("/api/me")[1] or {}).get("org", {}).get("credits") == before, ((r or {}).get("overrides"), before))
onto = g.sh(f"cat {folder}/ontology.json")
check("PUT: ontology.json carries the person's tags for the build", '"sales.csv[units_sold]": "Cases"' in onto, onto[-300:])
act = owner.get(f"/api/projects/{pid}/activity")[1] or []
check("PUT: the activity log says what the person tagged", any("Tagged columns: sales.csv[units_sold] = cases" in (e.get("text") or "")
                                                                for e in act if isinstance(e, dict)), [e.get("text") for e in act[-3:] if isinstance(e, dict)])
out = c.read_data(tid, pid)
s, sem3 = owner.get(f"/api/projects/{pid}/semantic")
check("read again: the person's tags stay (the next read uses them)", (col((sem3 or {}).get("view") or {}, "sales.csv", "units_sold").get("tag") or {}).get("how") == "person",
      (out[-200:], col((sem3 or {}).get("view") or {}, "sales.csv", "units_sold")))
for body, why in (({"overrides": {"sales.csv[nope]": "Sales"}}, "a column that is not in the data"),
                  ({"overrides": {"other.csv[sls_amt]": "Sales"}}, "a file that is not the dashboard's"),
                  ({"overrides": {"sales.csv[sls_amt]": "Not A Term"}}, "a term that is not in the ontology")):
    s, r = owner.put(f"/api/projects/{pid}/semantic", body)
    check(f"PUT: refused (400): {why}", s == 400, (s, detail(r)))

# ---------------------------------------------------------------- who
section("who may")
s, r = other.get(f"/api/projects/{pid}/semantic")
s2, r2 = other.put(f"/api/projects/{pid}/semantic", {"overrides": {}})
check("who: another organisation gets 404, reading or tagging", s == 404 and s2 == 404, (s, s2))
s, r = mia.get(f"/api/projects/{pid}/semantic")
check("who: a colleague without access to this private dashboard gets 404", s == 404, (s, detail(r)))
s, r = c.Person("x").get(f"/api/projects/{pid}/semantic")
check("who: nobody without a session (401)", s == 401, (s, r))

# ---------------------------------------------------------------- only while the plan waits
section("only while the plan waits for its KPIs")
c.in_app(f"""
from app import store
with _db.use({tid!r}):
    store.update({pid!r}, status="error", error="item 62 check: as if the build had stopped")
""")
s, r = owner.put(f"/api/projects/{pid}/semantic", {"overrides": {"sales.csv[units_sold]": "Units"}})
check("PUT: refused once the plan is not waiting for its KPIs (409)", s == 409 and "confirm the KPIs" in str(detail(r)), (s, detail(r)))
s, r = owner.get(f"/api/projects/{pid}/semantic")
check("GET: still readable, may_tag false", s == 200 and r.get("may_tag") is False and (r.get("view") or {}).get("tables"), (s, (r or {}).get("may_tag")))

# ---------------------------------------------------------------- a DAWB hand-off: read at the import
section("a dashboard from a DAWB hand-off")
s, r = c.import_handoff(owner, f"Mini {S}")
hid = (r or {}).get("id") if isinstance(r, dict) else None
s2, hs = owner.get(f"/api/projects/{hid}/semantic")
hv = (hs or {}).get("view") or {}
check("import: its data was read at the import (the semantic model is there at once)", s == 200 and s2 == 200
      and sorted(t["file"] for t in hv.get("tables") or []) == ["dim_store.csv", "sales_daily.csv"], (s, s2, detail(r)))
check("import: its plan's KPIs matched to the KPI dictionary (Net sales is the pack's Net Sales)",
      ((hs or {}).get("plan_dictionary") or {}).get("Net sales") == "Net Sales", (hs or {}).get("plan_dictionary"))

PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, pid, typo = sys.argv[1:4]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    for w in (1280, 360):
        ctx = b.new_context(viewport={"width": w, "height": 900})
        ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.goto(f"http://127.0.0.1:8000/#/p/{pid}")
        page.wait_for_selector("#semcard", timeout=30000)
        page.wait_for_function("() => (document.querySelector('#semcard') || {}).innerText && document.querySelector('#semcard').innerText.includes('sales_daily')", timeout=30000)
        page.wait_for_timeout(800)
        text = page.locator("#semcard").inner_text()
        out[str(w)] = {"text": text[:3000], "sideways": page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"),
                       "typo": "".join(ch for ch in text if ch in typo), "errors": errors}
        page.screenshot(path=f"/tmp/item62-plan-{w}.png", full_page=True)
        ctx.close()
    b.close()
print(json.dumps(out))
"""
ui = browser(c.WEB_C, PLAY, c.cookie(owner, "d2d_session"), str(hid), TYPO)
u1, u3 = ui.get("1280") or {}, ui.get("360") or {}
check("screen: the plan screen's Semantic model card: the planned tables, the columns matched to the ontology, its industry, "
      "the KPIs from the dictionary", all(x in str(u1.get("text")) for x in ("Semantic model", "dim_store", "sales_daily", "columns matched",
                                                                               "Grocery and retail", "from your dictionary")), str(u1.get("text"))[:500] or ui)
stray = [w for w in ("null", "undefined", "NaN") if any(f" {w} " in f" {ln} " or ln.strip().startswith(w) for ln in str(u1.get("text")).splitlines())]
check("screen: no stray null, undefined or NaN in the card (an empty part written as text)", u1.get("text") and not stray,
      (stray, [ln for ln in str(u1.get("text")).splitlines() if any(w in ln for w in ("null", "undefined", "NaN"))][:5]))
check("screen: nothing sideways at 1280 or 360 px, plain characters, no script errors",
      u1.get("sideways") is False and u3.get("sideways") is False and u1.get("typo") == "" and u1.get("errors") == [] and u3.get("errors") == [],
      {w: {k: x.get(k) for k in ("sideways", "typo", "errors")} for w, x in (("1280", u1), ("360", u3))} | {"stderr": ui.get("stderr")})
for f in ("item62-plan-1280.png", "item62-plan-360.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
