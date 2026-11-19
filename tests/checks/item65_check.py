"""Test stack only: item 65 (the user, 2026-11-19: "semantic review should be action as well rather than showing only
finding, it should be able to fix and suggest credits for consumption"). Semantic Review fixes (webapp/app/semreview_fix.py),
on item 55's review of three models (review_models: model.bim, a .pbit and a TMDL project) against a KPI dictionary:
- a finished review says what fixing uses before anything is charged (fix_estimate: fixable findings, those the rules
  already wrote, 1 credit each);
- POST /api/semreview/runs/<id>/fixes {findings}: refused before any charge for a viewer (403), another organisation
  (404), nothing fixable (400), too few credits (402), a review that did not finish (409); else charged 1 credit a fix
  and made in the background;
- the rules' fixes ("ready") need no AI: each kept once it checks out against its own model (a dictionary DAX naming a
  table another model does not have does not, and its credit comes back); the ones Relay would write fail on the test
  stack (no Claude) and their credits come back: the review keeps the credits of the fixes made;
- what comes out, per model: a TMDL script (createOrReplace, each fixed measure in its table, its format), a Tabular
  Editor C# script and a CSV of every fix (spreadsheet formulas off); none for a model with no fix (404); another
  organisation cannot download them.
Its people sign in from 198.18.65.x.
python -I -X utf8 item65_check.py <public> <admin>"""
import csv
import io
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402
from review_models import SALES, live_pbix, pbip, pbit  # noqa: E402

c._ips = (f"198.18.65.{n}" for n in itertools.count(10))     # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def form(p, path: str, fields: dict, files: list[tuple[str, str, bytes]]):
    boundary = "----fix65" + str(time.time_ns())
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    for field, fn, data in files:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{fn}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
    req = urllib.request.Request(p.base + path, data=b"".join(parts) + f"--{boundary}--\r\n".encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with p.http.open(req, timeout=180) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw or b"null")
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def raw_get(p, path: str):
    try:
        with p.http.open(urllib.request.Request(p.base + path), timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Disposition") or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), ""


def wait_run(p, rid: str, seconds: int = 180) -> dict:
    r = {}
    for _ in range(seconds):
        s, r = p.get(f"/api/semreview/runs/{rid}")
        if s == 200 and r.get("status") in ("done", "error"):
            return r
        time.sleep(1)
    return r or {}


def wait_fixes(p, rid: str, seconds: int = 240) -> dict:
    r = {}
    for _ in range(seconds):
        s, r = p.get(f"/api/semreview/runs/{rid}")
        if s == 200 and (r.get("fixes") or {}).get("status") in ("done", "error"):
            return r
        time.sleep(1)
    return r or {}


admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
dom = f"fixit{S}.com"
owner, vic = c.Person(f"fia.owner@{dom}"), c.Person(f"vic.viewer@{dom}")
s, r = owner.sign_in(f"Fix It {S}", "Fia Owner")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
vic.sign_in(person="Vic Viewer")
tid = ((owner.get("/api/me")[1] or {}).get("org") or {}).get("id")
schema = "t_" + str(tid).replace("-", "_")
g.sql(f"UPDATE {schema}.memberships SET role = 'viewer' WHERE user_id = (SELECT id FROM {schema}.users WHERE email = '{vic.email}')")
other = c.Person(f"ono.owner@elsewhere{S}.com")
s, r = other.sign_in(f"Elsewhere {S}", "Ono Owner")
check("setup: a viewer of it and another organisation's owner sign in", s == 200, (s, r))


def balance() -> int:
    return ((owner.get("/api/me")[1] or {}).get("org") or {}).get("credits") or 0


def set_balance(n: int) -> None:
    if n - balance():
        admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": n - balance(), "note": "item 65 check"})


set_balance(100)
check("price: a review finding fixed uses 1 credit (costs.fix)", (((owner.get("/api/me")[1] or {}).get("org") or {}).get("costs") or {}).get("fix") == 1)

# ---------------------------------------------------------------- a finished review and what fixing it uses
section("a finished review and what fixing it uses")
owner.post("/api/semreview/kpis", {"name": "Revenue", "synonyms": "Net Sales", "definition": "Sales of completed orders after discounts and returns.",
                                   "dax": 'CALCULATE ( SUM ( Sales[NetAmount] ), Sales[Status] = "Completed" )', "unit": "currency",
                                   "aggregation": "sum", "filters": ["Status = Completed"], "time": "fiscal year ending 31 March"})
owner.post("/api/semreview/kpis", {"name": "Gross Margin %", "dax": "DIVIDE ( [Revenue] - [COGS], [Revenue] )", "unit": "%", "aggregation": "ratio"})
s, r = form(owner, "/api/semreview/runs", {"name": f"Three models {S}"},
            [("files", "Sales model.bim", json.dumps(SALES).encode()), ("files", "Finance.pbit", pbit()), ("files", "Ops project.zip", pbip())])
rid = (r or {}).get("id") if isinstance(r, dict) else None
run = wait_run(owner, rid) if rid else {}
check("review: a review of three models finishes (10 credits)", run.get("status") == "done" and balance() == 90, (s, run.get("status"), balance()))
est = run.get("fix_estimate") or {}
fd = {f["id"]: f for f in (run.get("result") or {}).get("findings") or []}
ready = [i for i in est.get("ids") or [] if fd.get(i, {}).get("fix_dax")]
relay = [i for i in est.get("ids") or [] if not fd.get(i, {}).get("fix_dax") and fd.get(i, {}).get("rule") in ("average_of_ratios", "iterator_aggregate")]
check("estimate: before anything is charged, the review says what fixing uses: each fixable finding 1 credit, those the rules wrote",
      est.get("each") == 1 and est.get("fixable", 0) >= 10 and est.get("all") == est.get("fixable") and est.get("ready") == len(ready) == 5
      and sum((est.get("by_severity") or {}).values()) == est.get("fixable") and run.get("fixes") is None, est)
check("estimate: the findings about visuals, relationships and descriptions of nothing are not offered",
      not [i for i in est.get("ids") or [] if fd.get(i, {}).get("rule") in ("title", "implicit_visual", "bidirectional")], est.get("ids"))

# ---------------------------------------------------------------- refused before any charge
section("refused before any charge")
s, r = vic.post(f"/api/semreview/runs/{rid}/fixes", {"findings": ready})
check("fix: a viewer cannot (403)", s == 403, (s, detail(r)))
s, r = other.post(f"/api/semreview/runs/{rid}/fixes", {"findings": ready})
check("fix: another organisation cannot (404)", s == 404, (s, detail(r)))
not_fixable = [i for i, f in fd.items() if i not in (est.get("ids") or [])][:2]
for body, why in (({"findings": []}, "nothing picked"), ({"findings": ["f999"]}, "a finding that is not there"),
                  ({"findings": not_fixable}, "only findings that have no measure to fix")):
    s, r = owner.post(f"/api/semreview/runs/{rid}/fixes", body)
    check(f"fix: refused (400): {why}", s == 400 and "Pick findings that can be fixed" in str(detail(r)), (s, detail(r), not_fixable))
set_balance(3)
s, r = owner.post(f"/api/semreview/runs/{rid}/fixes", {"findings": ready})
check("fix: 5 fixes with 3 credits left are refused (402), saying Request credits", s == 402 and "Request credits" in str(detail(r))
      and balance() == 3, (s, detail(r)))
set_balance(90)
s, r = form(owner, "/api/semreview/runs", {}, [("files", "Live report.pbix", live_pbix())])
lr = wait_run(owner, (r or {}).get("id", "")) if s == 200 else {}
s, r = owner.post(f"/api/semreview/runs/{lr.get('id')}/fixes", {"findings": ["f1"]})
check("fix: a review that did not finish cannot be fixed (409)", lr.get("status") == "error" and s == 409, (lr.get("status"), s, detail(r)))
check("fix: nothing was charged by any of these", balance() == 90 and not [x for x in (owner.get("/api/org")[1] or {}).get("ledger", [])
                                                                          if x.get("what") == "fix"], balance())

# ---------------------------------------------------------------- the fixes
section("the fixes: the rules' own, and Relay's (no Claude here)")
picked = ready + relay
s, r = owner.post(f"/api/semreview/runs/{rid}/fixes", {"findings": picked + picked[:1]})
check(f"fix: {len(picked)} fixes start (a finding named twice counts once), {len(picked)} credits charged first",
      s == 200 and r == {"status": "running", "count": len(picked), "credits": len(picked)} and balance() == 90 - len(picked), (s, r, balance()))
run2 = wait_fixes(owner, rid)
fx = run2.get("fixes") or {}
items = {x["finding"]: x for x in fx.get("items") or []}
check("fix: done in the background, every pick accounted for", fx.get("status") == "done" and sorted(items) == sorted(picked)
      and fx.get("charged") == len(picked), {k: fx.get(k) for k in ("status", "charged", "given_back", "error")})
good = [i for i in ready if items.get(i, {}).get("ok")]
gm = items.get(ready[0], {})
check("fix: the rules' fixes need no AI: the dictionary's DAX written for each model (Gross Margin % in both, Total Revenue)",
      all(items.get(i, {}).get("how") == "rules" for i in ready) and len(good) == 3
      and {(items[i]["model_name"], items[i]["measure"]) for i in good} == {("Finance", "Gross Margin %"), ("Sales model", "Gross Margin %"),
                                                                             ("Sales model", "Total Revenue")},
      [(i, items.get(i, {}).get("model_name"), items.get(i, {}).get("measure"), items.get(i, {}).get("ok"), items.get(i, {}).get("why")) for i in ready])
bad_rules = [items[i] for i in ready if not items.get(i, {}).get("ok")]
check("fix: a rules' fix naming a table its model does not have (Sales in the Finance and Ops models) is not kept",
      len(bad_rules) == 2 and all("Sales is not a table of the model" in x.get("why", "") for x in bad_rules), [x.get("why") for x in bad_rules])
check("fix: each keeps the measure's DAX now and its old format", gm.get("old") and gm.get("old_format") is not None and gm.get("table"),
      {k: gm.get(k) for k in ("old", "old_format", "table")})
rel = [items.get(i, {}) for i in relay]
check("fix: the ones Relay writes cannot be made without Claude (not kept)", len(rel) == 2 and all(x.get("how") == "relay" and x.get("ok") is False for x in rel),
      [(x.get("finding"), x.get("ok"), x.get("why")) for x in rel])
check("fix: ... and say Relay could not be reached", all(x.get("why") == "Relay could not be reached." for x in rel), [x.get("why") for x in rel])
failed = [i for i in picked if not items.get(i, {}).get("ok")]
check(f"credits: the {len(failed)} fixes not made gave their credits back; the review keeps the {len(good)} of the fixes made",
      fx.get("given_back") == len(failed) and balance() == 90 - len(good), (fx.get("given_back"), balance(), 90 - len(good)))
led = [(x["kind"], x["delta"]) for x in (owner.get("/api/org")[1] or {}).get("ledger", []) if x.get("what") == "fix"]
check("credits: the history: one charge for the fixes and one give-back for those not made", sorted(led) == sorted([("charge", -len(picked)),
                                                                                                                    ("refund", len(failed))]), led)

# ---------------------------------------------------------------- what comes out
section("what comes out: TMDL, Tabular Editor and CSV")
s2, tm, disp = raw_get(owner, f"/api/semreview/runs/{rid}/fixes.tmdl?model=0")
check("TMDL: the Sales model's script: createOrReplace, its table, each fixed measure with its DAX and format, no comment lines",
      s2 == 200 and "attachment" in disp and "Sales-model.tmdl" in disp and tm.startswith("createOrReplace\n") and "\tref table Sales\n" in tm
      and "\t\tmeasure 'Gross Margin %' = DIVIDE ( [Revenue] - [COGS], [Revenue] )\n" in tm and "measure 'Total Revenue' = CALCULATE" in tm
      and "\t\t\tformatString:" in tm and "///" not in tm, (s2, disp, tm[:500]))
s2, tm1, disp = raw_get(owner, f"/api/semreview/runs/{rid}/fixes.tmdl?model=1")
check("TMDL: the Finance model's: its table's name in quotes ('Fact Sales')", s2 == 200 and "\tref table 'Fact Sales'\n" in tm1
      and "measure 'Gross Margin %'" in tm1 and "Total Revenue" not in tm1, (s2, tm1[:300]))
s2, tm2, disp = raw_get(owner, f"/api/semreview/runs/{rid}/fixes.tmdl?model=2")
check("TMDL: none for the Ops project, whose fix was not kept (404)", s2 == 404, (s2, tm2[:200]))
s2, cs, disp = raw_get(owner, f"/api/semreview/runs/{rid}/fixes.csx?model=0")
check("Tabular Editor: a C# script that adds or replaces each measure, with its expression",
      s2 == 200 and "attachment" in disp and disp.endswith('.csx"') and 'Model.Tables[@"Sales"]' in cs
      and 'm.Expression = @"DIVIDE ( [Revenue] - [COGS], [Revenue] )";' in cs and 't.AddMeasure(@"Total Revenue")' in cs, (s2, cs[:500]))
s2, cv, disp = raw_get(owner, f"/api/semreview/runs/{rid}/fixes.csv")
lines = list(csv.reader(io.StringIO(cv)))
check("CSV: every fix made, one a row, with its old and new DAX and who wrote it", s2 == 200 and "attachment" in disp
      and lines[0] == ["Model", "Table", "Measure", "Finding", "Severity", "DAX now", "Fixed DAX", "Format", "Written by", "Why"]
      and len(lines) == 1 + len(good) and all(row[8] == "the review's rules" for row in lines[1:]), (s2, lines[:4]))
check("CSV: spreadsheet formulas off (no cell starts with =, +, - or @)", all(not cell.startswith(("=", "+", "-", "@"))
                                                                              for row in lines[1:] for cell in row), lines[1:3])
s2, x, _ = raw_get(other, f"/api/semreview/runs/{rid}/fixes.csv")
s3, y, _ = raw_get(other, f"/api/semreview/runs/{rid}/fixes.tmdl?model=0")
check("downloads: another organisation gets none (404)", s2 == 404 and s3 == 404, (s2, s3))
s2, x, _ = raw_get(owner, f"/api/semreview/runs/{lr.get('id')}/fixes.csv")
check("downloads: a review with no fixes has none (404)", s2 == 404, (s2, x[:120]))
s, d = owner.get(f"/api/semreview/runs/{rid}")
check("review: it still says what fixing the rest uses", s == 200 and (d.get("fix_estimate") or {}).get("fixable") == est.get("fixable")
      and (d.get("fixes") or {}).get("status") == "done", (d.get("fix_estimate"), (d.get("fixes") or {}).get("status")))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
