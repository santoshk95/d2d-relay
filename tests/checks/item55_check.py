"""Test stack only: item 55, Semantic Review (python -I item55_check.py <public> <admin>).

The KPI dictionary (add, edit, one name one KPI, readable DAX, import with a preview, export without spreadsheet
formulas), reviews of every kind of file (model.bim, .pbit with its report, a zipped Power BI project in TMDL, a .pbix
connected live, a broken .pbix, and the real .pbix of TEST_REVIEW_PBIX when it is on this PC), what they find, credits
(charged once, given back when a review does not finish), the meaning check (no Claude on the stack: the review is
complete without it and may retry once at no cost), Review again, starting the dictionary from a review, who may do
what, another organisation's view, "Download my data", the Power BI connection against the stand-in Microsoft APIs
(fake_powerbi.py: getDefinition through its long-running operation, the INFO.VIEW fallback, the values side by side),
and a review cut off by a restart.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402
from review_models import FINANCE, SALES, broken_pbix, live_pbix, pbip, pbit  # noqa: E402,F401

STAMP = str(int(time.time()))[-6:]
PBIX = os.environ.get("TEST_REVIEW_PBIX") or r"C:\Users\santosh.k\PbixBot\Output\Global Ports Executive Summary\Global Ports Executive Summary.pbix"
STANDIN = "http://127.0.0.1:8106"
CLIENT_ID = "33333333-aaaa-4bbb-8ccc-000000000001"
SECRET = "stand-in-client-secret-not-real"
WS_SALES = "11111111-aaaa-4bbb-8ccc-000000000001"
M_SALES, M_FIN = "22222222-aaaa-4bbb-8ccc-000000000001", "22222222-aaaa-4bbb-8ccc-000000000002"


def form(p, path: str, fields: dict, files: list[tuple[str, str, bytes]]):
    """A multipart POST with several files under one name (the review's "files")."""
    boundary = "----sr54" + str(time.time_ns())
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    for field, fn, data in files:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{fn}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(p.base + path, data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
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
    req = urllib.request.Request(p.base + path)
    try:
        with p.http.open(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Disposition") or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), ""


def wait(p, rid: str, seconds: int = 180) -> dict:
    r = {}
    for _ in range(seconds):
        s, r = p.get(f"/api/semreview/runs/{rid}")
        if s == 200 and r.get("status") in ("done", "error"):
            return r
        time.sleep(1)
    return r or {}


def credits(p) -> int:
    return p.get("/api/me")[1]["org"]["credits"]


def rules(run: dict) -> dict:
    out = {}
    for f in (run.get("result") or {}).get("findings") or []:
        out.setdefault(f["rule"], []).append(f)
    return out


# ---------------------------------------------------------------- people

_ips = iter(f"203.0.113.{n}" for n in range(54, 70))      # addresses of their own: a full run's suites share 198.51.100.10 ...


def person(email: str):
    """A Person signing in from an address no other suite uses (sign-in codes are limited per address and hour)."""
    p = c.Person(email)
    p.ip = next(_ips)
    return p


owner = person(f"rita.owner@review{STAMP}.com")
s, r = owner.sign_in("Review Test", "Rita Owner")
c.check("review: PASDACS creates an organisation with 50 credits; its owner signs in", s == 200 and credits(owner) == 50, (s, r))
dev = person(f"dev.bi@review{STAMP}.com")
s, r = dev.sign_in(person="Dev Bi")
c.check("review: a colleague added to it signs in", s == 200 and dev.get("/api/me")[1]["org"]["name"] == "Review Test", (s, r))
other = person(f"olga.owner@elsewhere{STAMP}.com")
s, r = other.sign_in("Elsewhere", "Olga Owner")
c.check("review: another organisation's owner signs in", s == 200, (s, r))
broke = person(f"bo.broke@nocredit{STAMP}.com")
s0, r0 = c.signed_in("info@pasdacs.com", c.ADMIN_BASE).post("/api/admin/orgs", {"name": "No Credit", "email": broke.email, "person": "Bo Broke",
                                                                                 "credits": 0})
s, r = broke.sign_in(provision=False)
c.check("review: an organisation PASDACS created with no credits signs in", s0 == 200 and s == 200 and credits(broke) == 0, (s0, r0, s, r))

anon = c.Person("nobody@example.com")
s, _ = anon.get("/api/semreview")
c.check("review: the API needs a sign-in (401)", s == 401, s)
s, d = owner.get("/api/semreview")
c.check("review: the overview shows the price, no KPIs and no reviews yet", s == 200 and d["cost"] == 10 and d["kpis"] == 0 and d["runs"] == []
        and d["can"] == {"run": True, "edit": True, "connect": True} and d["limits"]["files"] == 5 and d["limits"]["mb"] == 20, d)
s, d = dev.get("/api/semreview")
c.check("review: a BI Dev may run and edit, not connect Power BI", s == 200 and d["can"] == {"run": True, "edit": True, "connect": False}, d)

# ---------------------------------------------------------------- the KPI dictionary
REVENUE = {"name": "Revenue", "synonyms": "Net Sales", "definition": "Sales of completed orders after discounts and returns.",
           "dax": 'CALCULATE ( SUM ( Sales[NetAmount] ), Sales[Status] = "Completed" )', "unit": "currency", "aggregation": "sum",
           "filters": ["Status = Completed"], "time": "fiscal year ending 31 March"}
s, k1 = owner.post("/api/semreview/kpis", REVENUE)
c.check("kpis: a KPI is added, its year end read from the time basis", s == 200 and k1.get("year_end") == "03-31" and k1.get("synonyms") == ["Net Sales"], (s, k1))
s, k2 = owner.post("/api/semreview/kpis", {"name": "Gross Margin %", "dax": "DIVIDE ( [Revenue] - [COGS], [Revenue] )", "unit": "%", "aggregation": "ratio"})
c.check("kpis: units and aggregations are read from plain words (% -> percent)", s == 200 and k2.get("unit") == "percent" and k2.get("aggregation") == "ratio", (s, k2))
s, r = owner.post("/api/semreview/kpis", {"name": "revenue"})
c.check("kpis: one name, one KPI (the same name again is refused)", s == 400 and "already in the dictionary" in r["detail"], (s, r))
s, r = owner.post("/api/semreview/kpis", {"name": "Sales", "synonyms": ["Net Sales"]})
c.check("kpis: another KPI's other name is refused too", s == 400 and "Net Sales" in r["detail"], (s, r))
s, r = owner.post("/api/semreview/kpis", {"name": "Bad", "dax": "SUM ( Sales[Amount]"})
c.check("kpis: DAX that cannot be read is refused", s == 400 and "cannot be read" in r["detail"], (s, r))
s, r = owner.put(f"/api/semreview/kpis/{k2['id']}", {"name": "Gross Margin %", "definition": "Gross profit as a share of revenue.",
                                                        "dax": "DIVIDE ( [Revenue] - [COGS], [Revenue] )", "unit": "percent", "aggregation": "ratio"})
c.check("kpis: a KPI is edited", s == 200 and r["definition"].startswith("Gross profit"), (s, r))
csv_text = ("KPI,Aliases,Description,Calculation,Unit,Aggregation,Owner\n"
            "Active Customers,,Customers with a completed order,Distinct count of customers,count,distinct count,Sales\n"
            "Churn Rate,Attrition,Share of customers lost,Lost / customers at start,percent,ratio,Sales\n"
            "Revenue,Net Sales,Completed sales after returns (finance),,currency,sum,Finance\n")
s, prev = form(owner, "/api/semreview/kpis/import", {"mode": "merge", "apply": "0"}, [("file", "kpis.csv", csv_text.encode())])
c.check("kpis: an import shows what it would do first (2 new, 1 changed)", s == 200 and not prev["applied"] and sorted(prev["added"]) == ["Active Customers", "Churn Rate"]
        and prev["updated"] == ["Revenue"], (s, prev))
c.check("kpis: ... and changes nothing until applied", len(owner.get("/api/semreview/kpis")[1]["kpis"]) == 2)
s, app_ = form(owner, "/api/semreview/kpis/import", {"mode": "merge", "apply": "1"}, [("file", "kpis.csv", csv_text.encode())])
kpis_now = owner.get("/api/semreview/kpis")[1]["kpis"]
c.check("kpis: applied, the dictionary has 4 KPIs", s == 200 and app_["applied"] and len(kpis_now) == 4, (s, app_, len(kpis_now)))
rev = next(k for k in kpis_now if k["name"] == "Revenue")
c.check("kpis: the merge took Revenue's fields from the file and kept the ones it leaves out (the DAX, the year end)",
        rev["definition"].startswith("Completed sales after returns") and rev.get("owner") == "Finance"
        and rev.get("dax", "").startswith("CALCULATE") and rev.get("year_end") == "03-31", rev)
s, rep = form(owner, "/api/semreview/kpis/import", {"mode": "replace", "apply": "0"}, [("file", "two.csv", b"KPI,Definition\nRevenue,Sales\nCOGS,Cost of goods\n")])
c.check("kpis: a replace preview lists what would be removed", s == 200 and sorted(rep["removed"]) == ["Active Customers", "Churn Rate", "Gross Margin %"]
        and rep["added"] == ["COGS"], (s, rep))
s, r = form(owner, "/api/semreview/kpis/import", {"mode": "merge", "apply": "0"}, [("file", "kpis.txt.exe", b"x")])
c.check("kpis: an unknown file kind is refused", s == 400, (s, r))
s, r = form(owner, "/api/semreview/kpis/import", {"mode": "merge", "apply": "0"}, [("file", "k.csv", b"Name of thing,Other\nA,B\n")])
c.check("kpis: a file with no KPI column says what it needs", s == 400 and "KPI" in r["detail"], (s, r))
yaml_doc = b"kpis:\n  - name: Order Count\n    definition: Orders placed\n    aggregation: count\n"
s, r = form(owner, "/api/semreview/kpis/import", {"mode": "merge", "apply": "1"}, [("file", "k.yaml", yaml_doc)])
c.check("kpis: YAML is read too", s == 200 and r["added"] == ["Order Count"], (s, r))
s, evil = owner.post("/api/semreview/kpis", {"name": "=HYPERLINK(\"http://x\")", "definition": "+1"})
s2, text, disp = raw_get(owner, "/api/semreview/kpis/export.csv")
c.check("kpis: the CSV export is a download and starts formula-like cells with a quote", s == 200 and s2 == 200 and "attachment" in disp
        and "'=HYPERLINK" in text and "'+1" in text and text.startswith("KPI,Synonyms,Definition"), (s2, text[:300]))
s, r = owner.delete(f"/api/semreview/kpis/{evil['id']}")
c.check("kpis: a KPI is deleted", s == 200, (s, r))
s2, text, disp = raw_get(owner, "/api/semreview/kpis/export.yaml")
c.check("kpis: the YAML export lists them", s2 == 200 and "name: Revenue" in text and "HYPERLINK" not in text, text[:200])
s2, text, _ = raw_get(owner, "/api/semreview/kpis/template.csv")
c.check("kpis: the template downloads with examples", s2 == 200 and "Gross Margin %" in text, text[:120])
s, r = dev.post("/api/semreview/kpis", {"name": "Dev KPI"})
c.check("kpis: a BI Dev may add KPIs", s == 200, (s, r))
dev.delete(f"/api/semreview/kpis/{r.get('id')}")
s, r = other.get("/api/semreview/kpis")
c.check("kpis: another organisation does not see this dictionary", s == 200 and r["kpis"] == [], (s, r))

# ---------------------------------------------------------------- reviews of files
s, r = form(owner, "/api/semreview/runs", {"name": ""}, [])
c.check("runs: a review needs a model", s == 400, (s, r))
s, r = form(owner, "/api/semreview/runs", {}, [("files", "notes.txt", b"hello")])
c.check("runs: a file the review does not read is refused", s == 400 and "notes.txt" in r["detail"], (s, r))
before = credits(owner)
s, r = form(owner, "/api/semreview/runs", {}, [("files", "huge.pbit", b"x" * (21 * 1024 * 1024))])
c.check("runs: a file over the size limit is refused (413), nothing charged", s == 413 and "20 MB" in r["detail"] and credits(owner) == before, (s, r))
s, r = form(broke, "/api/semreview/runs", {}, [("files", "sales.bim", json.dumps(SALES).encode())])
c.check("runs: no credits, no review (402)", s == 402 and r.get("credits") is True, (s, r))

files = [("files", "Sales model.bim", json.dumps(SALES).encode()), ("files", "Finance.pbit", pbit()), ("files", "Ops project.zip", pbip())]
s, r = form(owner, "/api/semreview/runs", {"name": "Three models"}, files)
c.check("runs: a review of three models starts", s == 200 and str(r.get("id", "")).startswith("sr-"), (s, r))
rid = r.get("id")
run = wait(owner, rid)
res = run.get("result") or {}
c.check("runs: it finishes", run.get("status") == "done", {k: run.get(k) for k in ("status", "step", "error")})
c.check("runs: it used 10 credits", credits(owner) == before - 10, credits(owner))
led = owner.get("/api/org")[1].get("ledger", [])
c.check("runs: the ledger says semantic review, with no refund", any(x["what"] == "review" and x["kind"] == "charge" and x["delta"] == -10 for x in led)
        and not any(x["what"] == "review" and x["kind"] == "refund" for x in led), led[:4])
sm = res.get("summary") or {}
c.check("runs: three models and every measure read", sm.get("models") == 3 and sm.get("measures") == 11 + 3 + 3, sm)
names = {m["name"] for m in res.get("measures") or []}
c.check("runs: the TMDL project's measures were read (multi-line DAX, a quoted name)", {"Revenue LY", "Orders Count"} <= names, sorted(names))
ly = next((m for m in res.get("measures") or [] if m["name"] == "Revenue LY"), {})
c.check("runs: ... with their whole multi-line DAX", "SAMEPERIODLASTYEAR" in (ly.get("dax") or "") and ly.get("format") == "\\$#,0", ly)
fd = rules(run)
want = {"conflict", "differs", "average_of_ratios", "frozen_variable", "iterator_aggregate", "variant_drift", "broken", "implicit_sum",
        "duplicate", "unit", "time_basis", "aggregation", "title", "missing", "bidirectional"}
c.check("runs: every planted problem is found", want <= set(fd), sorted(want - set(fd)))
conf = next((f for f in fd.get("conflict", []) if f["kpi"] == "Revenue"), None)
c.check("runs: Revenue is calculated more than one way across the models", conf is not None and conf["severity"] == "high"
        and "Version" in conf["detail"] and {m["name"] for m in conf["measures"]} >= {"Revenue", "Total Revenue"}, conf)
c.check("runs: the title check names the card that shows the wrong KPI", any("Gross Margin %" in f["title"] for f in fd.get("title", [])), fd.get("title"))
c.check("runs: the frozen variable is high", fd.get("frozen_variable", [{}])[0].get("severity") == "high", fd.get("frozen_variable"))
c.check("runs: the year end is held to the dictionary's (31 March)", any("31 March" in f["detail"] for f in fd.get("time_basis", [])), fd.get("time_basis"))
krows = {k["name"]: k for k in res.get("kpis") or []}
c.check("runs: the KPI table says Revenue has more than one calculation", krows.get("Revenue", {}).get("status") == "conflict"
        and krows["Revenue"]["versions"] >= 2, krows.get("Revenue"))
c.check("runs: Churn Rate is in no model", krows.get("Churn Rate", {}).get("status") == "missing", krows.get("Churn Rate"))
c.check("runs: findings text is plain keyboard characters", not any(ch in json.dumps(res.get("findings"), ensure_ascii=False) for ch in "\u2014\u2013\u2018\u2019\u201c\u201d\u2192\u2022"), "")
ai = run.get("ai") or {}
c.check("runs: no Claude on the test stack: the review is complete without the meaning check, which may run again",
        ai.get("ran") is False and ai.get("can_retry") is True, ai)
tid = g.sql(f"SELECT tenant_id FROM relay.tn_orgs WHERE name = 'Review Test' AND domain = 'review{STAMP}.com'")
schema = "t_" + tid.replace("-", "_")
stored = g.sql(f"SELECT count(*), max(length(body)) FROM {schema}.semreview_models WHERE run_id = '{rid}'")
c.check("runs: the three models are kept (metadata only)", stored.startswith("3|"), stored)
keys = g.sql(f"SELECT DISTINCT jsonb_object_keys(body::jsonb) FROM {schema}.semreview_models WHERE run_id = '{rid}'").split()
c.check("runs: nothing but metadata in what is kept (no rows, no Power Query)", set(keys) <= {"name", "tables", "measures", "relationships", "calc_groups", "usage", "source"}, keys)
c.check("runs: the Power Query of the TMDL project is not kept", "Csv.Document" not in g.sql(f"SELECT body FROM {schema}.semreview_models WHERE run_id = '{rid}'"), "")
left = g.sh(f"ls -A /data/projects/.tenants/{tid}/.semreview 2>/dev/null | wc -l")
c.check("runs: the uploaded files are gone", left.strip() in ("0", ""), left)
s2, text, disp = raw_get(owner, f"/api/semreview/runs/{rid}/findings.csv")
c.check("runs: the findings download as CSV", s2 == 200 and "attachment" in disp and text.startswith("Severity,Check,KPI,Finding")
        and text.count("\n") >= len(res.get("findings") or []), text[:200])
s, lst = owner.get("/api/semreview")
c.check("runs: the overview lists the review with its summary", s == 200 and lst["runs"][0]["id"] == rid and lst["runs"][0]["summary"]["models"] == 3, lst["runs"][:1])
s, r = other.get(f"/api/semreview/runs/{rid}")
c.check("runs: another organisation cannot open it (404)", s == 404, s)
s, r = dev.get(f"/api/semreview/runs/{rid}")
c.check("runs: a colleague can open it", s == 200 and r["status"] == "done" and r["can_delete"] is False, (s, r.get("can_delete") if isinstance(r, dict) else r))

# meaning check again, once, at no cost
cr = credits(owner)
s, r = owner.post(f"/api/semreview/runs/{rid}/meaning")
again = wait(owner, rid)
c.check("meaning: the meaning check runs again at no cost", s == 200 and again.get("status") == "done" and credits(owner) == cr, (s, r, again.get("ai")))
s, r = owner.post(f"/api/semreview/runs/{rid}/meaning")
c.check("meaning: ... only once more", s == 409, (s, r))

# Review again: the same models, today's dictionary, charged again
s, r = owner.post(f"/api/semreview/runs/{rid}/again")
run2 = wait(owner, r.get("id", "")) if s == 200 else {}
c.check("again: Review again reads the kept models (no upload) and charges again", s == 200 and run2.get("status") == "done"
        and run2["result"]["summary"]["models"] == 3 and credits(owner) == cr - 10, (s, r, run2.get("status")))

# the dictionary from a review
ids = [m["id"] for m in res["measures"] if m["name"] in ("Turnover", "Orders Count")]
s, r = owner.post("/api/semreview/kpis/from-run", {"run": rid, "measures": ids})
c.check("from-run: picked measures become KPIs with their DAX", s == 200 and sorted(r["added"]) == ["Orders Count", "Turnover"], (s, r))
s, r = owner.post("/api/semreview/kpis/from-run", {"run": rid, "measures": ids})
c.check("from-run: the same again is left out", s == 200 and r["added"] == [] and len(r["skipped"]) == 2, (s, r))

# who may delete
s, r = dev.delete(f"/api/semreview/runs/{rid}")
c.check("delete: a colleague cannot delete someone else's review", s == 403, (s, r))
s, r = owner.delete(f"/api/semreview/runs/{rid}")
c.check("delete: its owner deletes it, with the models it kept", s == 200 and owner.get(f"/api/semreview/runs/{rid}")[0] == 404
        and g.sql(f"SELECT count(*) FROM {schema}.semreview_models WHERE run_id = '{rid}'") == "0", (s, r))

# files that cannot be reviewed: credits come back
cr = credits(owner)
s, r = form(owner, "/api/semreview/runs", {}, [("files", "Live report.pbix", live_pbix())])
lr = wait(owner, r.get("id", "")) if s == 200 else {}
c.check("pbix: a report connected live says where its model is, and the credits come back", lr.get("status") == "error"
        and "connected to a model" in (lr.get("error") or "") and credits(owner) == cr, (s, lr.get("error"), credits(owner)))
s, r = form(owner, "/api/semreview/runs", {}, [("files", "Broken.pbix", broken_pbix())])
br = wait(owner, r.get("id", "")) if s == 200 else {}
c.check("pbix: a broken .pbix fails with a plain reason and the credits come back", br.get("status") == "error"
        and "could not be read" in (br.get("error") or "") and ".pbit" in (br.get("error") or "") and credits(owner) == cr, (br.get("error"), credits(owner)))
led = owner.get("/api/org")[1].get("ledger", [])
c.check("pbix: the ledger shows the two refunds", sum(1 for x in led if x["what"] == "review" and x["kind"] == "refund") >= 2, led[:5])
if os.path.exists(PBIX) and os.path.getsize(PBIX) < 20 * 1024 * 1024:
    with open(PBIX, "rb") as fh:
        data = fh.read()
    s, r = form(owner, "/api/semreview/runs", {"name": "Real pbix"}, [("files", "Global Ports.pbix", data)])
    pr = wait(owner, r.get("id", ""), 240) if s == 200 else {}
    ms = (pr.get("result") or {}).get("summary", {}).get("measures")
    c.check("pbix: a real .pbix is read in its own process (86 measures, report usage)", pr.get("status") == "done" and ms == 86
            and any(m["shows"] for m in pr["result"]["measures"]), (pr.get("status"), pr.get("error"), ms))
    c.check("pbix: its 9 tables are read, calculated ones included, the engine's own (H$, R$) left out",
            (pr.get("result") or {}).get("models", [{}])[0].get("tables") == 9, (pr.get("result") or {}).get("models"))
    quality = ("broken", "frozen_variable", "iterator_aggregate", "average_of_ratios", "filter_override", "implicit_visual", "variant_drift")
    c.check("pbix: a model D2D Relay built itself has no DAX problem (only differences from this test's dictionary)",
            not [f for f in (pr.get("result") or {}).get("findings", []) if f["rule"] in quality],
            [f["title"] for f in (pr.get("result") or {}).get("findings", []) if f["rule"] in quality][:6])
else:
    print(f"(no .pbix at {PBIX}: the real-file check is skipped)")

# Download my data
s, mine = owner.get("/api/me/data")
c.check("governance: Download my data lists the reviews the person ran", s == 200 and any(x["name"] == "Real pbix" or x["name"].startswith("Three models")
        for x in mine.get("semantic_reviews_you_ran") or []), (s, (mine or {}).get("semantic_reviews_you_ran") if isinstance(mine, dict) else mine))

# ---------------------------------------------------------------- Power BI (the stand-in Microsoft APIs)
urllib.request.urlopen(urllib.request.Request(STANDIN + "/_test/reset", data=b"{}", method="POST"), timeout=10).read()
s, r = owner.put("/api/semreview/pbi", {"tenant": "not a tenant", "client_id": CLIENT_ID, "client_secret": SECRET})
c.check("pbi: a tenant that is not one is refused", s == 400 and "tenant" in r["detail"], (s, r))
s, r = owner.put("/api/semreview/pbi", {"tenant": "contoso.onmicrosoft.com", "client_id": "abc", "client_secret": SECRET})
c.check("pbi: a client id that is not a GUID is refused", s == 400, (s, r))
s, r = dev.put("/api/semreview/pbi", {"tenant": "contoso.onmicrosoft.com", "client_id": CLIENT_ID, "client_secret": SECRET})
c.check("pbi: only an owner connects Power BI", s == 403, (s, r))
s, r = owner.put("/api/semreview/pbi", {"tenant": "contoso.onmicrosoft.com", "client_id": CLIENT_ID, "client_secret": "wrong-secret"})
s2, t = owner.post("/api/semreview/pbi/test")
c.check("pbi: a wrong secret is named as such by the test", s == 200 and s2 == 400 and "secret is wrong" in t["detail"], (s, s2, t))
s, r = owner.put("/api/semreview/pbi", {"tenant": "contoso.onmicrosoft.com", "client_id": CLIENT_ID, "client_secret": SECRET})
c.check("pbi: saved, and the secret is never sent back", s == 200 and r["configured"] and r["has_secret"] and SECRET not in json.dumps(r), r)
s, r = owner.get("/api/semreview/pbi")
c.check("pbi: reading the settings never shows the secret", s == 200 and SECRET not in json.dumps(r) and r["client_id"].endswith("0001"), r)
s, t = dev.post("/api/semreview/pbi/test")
c.check("pbi: the test reaches the workspaces", s == 200 and t["workspaces"] == 2, (s, t))
s, ws = dev.get("/api/semreview/pbi/workspaces")
s2, mods = dev.get(f"/api/semreview/pbi/workspaces/{WS_SALES}/models")
c.check("pbi: workspaces and their models are listed", s == 200 and [w["name"] for w in ws["workspaces"]] == ["Operations", "Sales BI"]
        and s2 == 200 and sorted(m["name"] for m in mods["models"]) == ["Finance model", "Sales model"], (ws, mods))
s, r = dev.get("/api/semreview/pbi/workspaces/not-a-guid/models")
c.check("pbi: an id that is not a GUID never reaches Microsoft", s == 400, (s, r))
cr = credits(owner)
picks = [{"workspace": WS_SALES, "model": M_SALES, "name": "Sales model", "workspace_name": "Sales BI"},
         {"workspace": WS_SALES, "model": M_FIN, "name": "Finance model", "workspace_name": "Sales BI"}]
s, r = form(dev, "/api/semreview/runs", {"azure": json.dumps(picks)}, [])
pr = wait(dev, r.get("id", ""), 120) if s == 200 else {}
pres = pr.get("result") or {}
c.check("pbi: a review of two models in the service finishes", pr.get("status") == "done", (s, r, pr.get("error")))
srcs = [m.get("source") or {} for m in pres.get("models") or []]
c.check("pbi: one read by getDefinition (a long-running operation), one by INFO.VIEW (no write permission for getDefinition)",
        [x.get("via") for x in srcs] == ["definition", "info.view"], srcs)
rv = next((k for k in pres.get("kpis") or [] if k["name"] == "Revenue"), {})
vals = {(i["model_name"], i["measure"]): i.get("value") for i in rv.get("implementations") or []}
c.check("pbi: the disagreeing measures' values are side by side", pres.get("values") is True and vals.get(("Sales model", "Revenue")) == 1234567.5
        and vals.get(("Sales model", "Total Revenue")) == 1300000, vals)
st = json.loads(urllib.request.urlopen(STANDIN + "/_test/state", timeout=10).read())
c.check("pbi: the operation was polled and the result fetched", st.get("operation_poll", 0) >= 2 and st.get("definition_result") == 1 and st.get("get_definition") == 2, st)
c.check("pbi: the review used 10 credits of the organisation", credits(owner) == cr - 10, credits(owner))
s, r = owner.delete("/api/semreview/pbi")
s2, r2 = form(dev, "/api/semreview/runs", {"azure": json.dumps(picks[:1])}, [])
c.check("pbi: removed, and then a Power BI review asks to connect first", s == 200 and not r["configured"] and s2 == 400 and "Connect Power BI" in r2["detail"], (s, r, s2, r2))

# ---------------------------------------------------------------- a review cut off by a restart
out = g.app(f"""
import json, time
from app import db, orgs, semreview
with db.use({tid!r}):
    uid = db.one("SELECT id FROM users WHERE email = ?", ({owner.email!r},))["id"]
    cid = orgs.charge("review", note="restart test")
    db.run("INSERT INTO semreview_runs (id, user_id, name, status, step, created, sources, charge) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
           ("sr-0123456789ab", uid, "restart test", "reading", "Reading", time.time(), "[]", cid))
semreview.recover()
with db.use({tid!r}):
    row = db.one("SELECT status, error FROM semreview_runs WHERE id = 'sr-0123456789ab'")
    print(json.dumps({{"status": row["status"], "error": row["error"], "refunded": orgs.refunded(cid)}}))
""")
try:
    rec = json.loads(out.strip().splitlines()[-1])
except (ValueError, IndexError):
    rec = {}
c.check("restart: a review cut off by a restart ends, its credits given back", rec.get("status") == "error" and rec.get("refunded") is True
        and "restart" in (rec.get("error") or ""), out[-400:])

# ---------------------------------------------------------------- the independent review's cases (2026-11-18), in the other organisation
bomb = "a: &a [x,x,x,x,x,x,x,x,x,x]\n" + "".join(f"{chr(98 + i)}: &{chr(98 + i)} [" + ",".join([f"*{chr(97 + i)}"] * 10) + "]\n"
                                                 for i in range(8)) + "kpis: [{name: *i}]\n"
t0 = time.time()
s, r = form(other, "/api/semreview/kpis/import", {"mode": "merge", "apply": "0"}, [("file", "bomb.yaml", bomb.encode())])
c.check("guard: a YAML file of aliases (a billion values in a few bytes) is refused at once", s == 400 and "aliases" in r["detail"]
        and time.time() - t0 < 10, (s, r, round(time.time() - t0, 1)))
CLEAN = {"name": "Clean model", "model": {"tables": [
    {"name": "Sales", "columns": [{"name": n, "dataType": "decimal", "summarizeBy": "sum"} for n in ("Qty", "Price", "Cost", "Amount")],
     "measures": [{"name": "Revenue", "expression": "SUM ( Sales[Amount] )"},
                  {"name": "Gross Profit", "expression": "[Revenue] - SUM ( Sales[Cost] )"},
                  {"name": "Margin %", "expression": "DIVIDE ( [Gross Profit], [Revenue] )", "formatString": "0.0%"},
                  {"name": "Sales Value", "expression": "SUMX ( Sales, [Qty] * [Price] )"},
                  {"name": "Revenue x2", "expression": "Sales[Revenue] * 2"},
                  {"name": "Revenue 2024", "expression": 'CALCULATE ( [Revenue], DATESBETWEEN ( Sales[Qty], dt"2024-01-01", dt"2024-12-31" ) )'}]
     + [{"name": f"Deep {i}", "expression": f"[Deep {i - 1}] + [Deep {i - 1}]" if i else "SUM ( Sales[Qty] )"} for i in range(31)]}]}}
other.post("/api/semreview/kpis", {"name": "Margin %", "dax": "DIVIDE ( [Gross Profit], [Revenue] )", "unit": "percent", "aggregation": "ratio"})
other.post("/api/semreview/kpis", {"name": "Sales Value", "dax": "SUMX ( Sales, [Qty] * [Price] )"})
t0 = time.time()
s, r = form(other, "/api/semreview/runs", {"name": "Revue des KPI été 第一"}, [("files", "clean.bim", json.dumps(CLEAN).encode())])
cr = wait(other, r.get("id", ""), 120) if s == 200 else {}
cf = rules(cr)
c.check("guard: 31 levels of doubling measure references are reviewed in seconds", cr.get("status") == "done" and time.time() - t0 < 60,
        (cr.get("status"), cr.get("error"), round(time.time() - t0, 1)))
c.check("guard: dictionary DAX that uses the model's own measures and columns matches the same measures (no false differs)",
        "differs" not in cf and all(k["status"] == "consistent" for k in (cr.get("result") or {}).get("kpis", []) if k["name"] in ("Margin %", "Sales Value")),
        [f["title"] for f in cf.get("differs", [])])
c.check("guard: Sales[Revenue] (a measure named with its table) and dt\"2024-01-01\" read fine", "broken" not in cf, [f["title"] for f in cf.get("broken", [])])
s2, text, disp = raw_get(other, f"/api/semreview/runs/{r.get('id')}/findings.csv")
c.check("guard: a review named in other scripts still downloads its findings", s2 == 200 and "attachment" in disp, (s2, disp))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
