"""Test stack only: item 58 (the user, 2026-11-18): a new dashboard from a DAWB hand-off, with DAWB's plan as given.
- New dashboard takes the hand-off folder as one .zip (POST /api/projects/import). Before anything is saved or
  charged D2D checks it against its manifest (sha256, rows, columns), reads each CSV, profiles the data, checks the
  relationships' keys and filter paths and the plan; a hand-off with a problem is refused with what is wrong, takes no
  credits and leaves nothing behind;
- a good one becomes a dashboard waiting at Confirm KPIs with DAWB's KPIs (currency \\$#,0, percent 0.0%, whole number
  #,0, a format_string as given; a KPI named like a column renamed, its label and the KPIs that use it following,
  strings and comments untouched), pages, tables, relationships and descriptions; profile.md / profile.json as Relay's
  planning writes them; request.md for the build (the hand-off's visuals and queries as guidance); the price of a new
  dashboard (25 built-in, 50 custom); Confirm KPIs starts the build with that charge;
- the real hand-off DAWB writes on this PC, when it is there (TEST_HANDOFF_DIR, by default
  Downloads\\DAWB\\handoff\\d2d\\pinecrest in the home folder): imported whole, its KPIs and pages as project.json says;
- in Chromium: New dashboard's "From a DAWB hand-off", an import from the form, the plan at Confirm KPIs (1280 and
  360 px, plain characters, nothing sideways, no script errors). Screenshots: item58-*.png in the run's folder.
python -I -X utf8 item58_check.py <public> <admin>"""
import hashlib
import io
import itertools
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402
import gov_check as g  # noqa: E402

c._ips = (f"198.18.58.{n}" for n in itertools.count(10))  # addresses of their own: a full run's suites share 198.51.100.x
check, detail, S = c.check, c.detail_of, c.STAMP
REAL = Path(os.environ.get("TEST_HANDOFF_DIR") or Path.home() / "Downloads" / "DAWB" / "handoff" / "d2d" / "pinecrest")
FORMATS = {"currency": "\\$#,0", "percent": "0.0%", "whole number": "#,0", "decimal": "#,0.00"}


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def browser(container: str, script: str, *args: str) -> dict:
    res = subprocess.run(["docker", "exec", "-i", container, "python3", "-", *args], input=script, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=420)
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"run": res.returncode, "stderr": (res.stderr or "")[-800:]}


# ---------------------------------------------------------------- a small hand-off in DAWB's format 1

DIM_STORE = "store_id,store_name,banner_name,region_name\n1,North Main,Alpha,East\n2,South Side,Beta,East\n3,West End,Alpha,West\n"
DIM_DATE = "date,year,month_name\n2026-11-01,2026,November\n2026-11-02,2026,November\n2026-11-03,2026,November\n"
SALES = ("sale_date,store_id,channel,orders,net_sales\n2026-11-01,1,store,10,100.50\n2026-11-01,2,online,4,80.00\n"
         "2026-11-02,1,store,12,130.25\n2026-11-02,3,store,7,70.00\n2026-11-03,2,online,5,95.75\n2026-11-03,3,store,9,88.10\n")
COLS = {"dim_store": [("store_id", "whole number", "Store number"), ("store_name", "text", "Store name"),
                      ("banner_name", "text", "Trade name the store operates under"), ("region_name", "text", "Region")],
        "dim_date": [("date", "date", "The day"), ("year", "whole number", "Calendar year"), ("month_name", "text", "Name of the month")],
        "sales_daily": [("sale_date", "date", "Trading day; joins to dim_date"), ("store_id", "whole number", "Store; joins to dim_store"),
                        ("channel", "text", "store or online"), ("orders", "whole number", "Orders placed"),
                        ("net_sales", "decimal", "Sales after discounts, USD")]}
DESCR = {"dim_store": "One row per store, with its banner and region.", "dim_date": "One row per day.",
         "sales_daily": "Daily sales per store and channel."}
KPIS = [{"name": "Net sales", "dax": "SUM(sales_daily[net_sales])", "description": "Sales after discounts, USD", "format": "currency"},
        {"name": "Orders", "dax": "SUM(sales_daily[orders])", "description": "Orders placed", "format": "whole number"},
        {"name": "Average order", "dax": "DIVIDE([Net sales], [Orders])", "description": "Net sales per order, USD",
         "format": "currency", "format_string": "$#,0.00"},
        {"name": "Online share %", "dax": 'DIVIDE(CALCULATE([Net sales], sales_daily[channel] = "online"), [Net sales])',
         "description": "Share of net sales from online orders", "format": "percent"},
        {"name": "Store orders", "dax": 'CALCULATE([Orders], sales_daily[channel] = "store") // [Orders] at the till',
         "description": "Orders at the till", "format": "whole number"}]
EXPECT = [("Net sales", "Net sales", "\\$#,0", "SUM(sales_daily[net_sales])"),
          ("Total orders", "Orders", "#,0", "SUM(sales_daily[orders])"),
          ("Average order", "Average order", "$#,0.00", "DIVIDE([Net sales], [Total orders])"),
          ("Online share %", "Online share %", "0.0%", 'DIVIDE(CALCULATE([Net sales], sales_daily[channel] = "online"), [Net sales])'),
          ("Store orders", "Store orders", "#,0", 'CALCULATE([Total orders], sales_daily[channel] = "store") // [Orders] at the till')]
PAGES = [{"name": "Overview", "purpose": "How the stores sell", "visuals": [
             {"title": "Net sales", "visual": "card", "query": "SELECT SUM(net_sales) AS net_sales FROM gold.sales_daily",
              "x": 0, "y": 0, "w": 6, "h": 4},
             {"title": "Net sales by banner", "visual": "clustered bar chart",
              "query": "SELECT s.banner_name, SUM(f.net_sales) AS net_sales FROM gold.sales_daily f JOIN gold.dim_store s USING (store_id) GROUP BY 1",
              "x": 6, "y": 0, "w": 18, "h": 7}]},
         {"name": "Channels", "purpose": "Store and online orders", "visuals": [
             {"title": "Orders by channel", "visual": "donut chart",
              "query": "SELECT channel, SUM(orders) AS orders FROM gold.sales_daily GROUP BY channel", "x": 0, "y": 0, "w": 12, "h": 7}]}]
RELS = ["sales_daily[store_id] -> dim_store[store_id]", "sales_daily[sale_date] -> dim_date[date]"]


def rows_of(text: str) -> int:
    return len([ln for ln in text.splitlines()[1:] if ln.strip()])


def handoff(mutate=None, after=None, name: str | None = None) -> dict[str, bytes]:
    """A small hand-off as {path: bytes}. mutate(project, data) edits it before the manifest is written (the manifest
    then matches the files, as DAWB would write it); after(files) edits the files once it is written (it no longer
    matches)."""
    data = {"dim_store": DIM_STORE, "dim_date": DIM_DATE, "sales_daily": SALES}
    project = {"kind": "d2d-project", "format": 1, "name": name or f"Mini Grocer {S}",
               "made_by": {"product": "DAWB", "release": "T-1", "at": "2026-11-18 06:00 UTC"},
               "steps": [{"step": "Describe the dashboard and upload the data", "status": "done"},
                         {"step": "Profile the data and propose the plan", "status": "done"},
                         {"step": "Confirm or edit the plan", "status": "start here"}],
               "description": "Show the store leaders how sales and orders move by banner and channel.",
               "audience": "Store leaders",
               "inputs": [{"file": f"data/{t}.csv", "table": t, "description": DESCR[t], "rows": rows_of(data[t]),
                           "columns": [{"name": n, "type": ty, "description": d} for n, ty, d in COLS[t]]} for t in data],
               "plan": {"model": {"tables": [{"name": "dim_date", "role": "date table", "grain": "one row per day"},
                                             {"name": "dim_store", "role": "dimension", "grain": "one row per store"},
                                             {"name": "sales_daily", "role": "fact", "grain": "one row per day, store and channel"}],
                                  "relationships": list(RELS), "note": "A small star: sales join the dates and the stores."},
                        "kpis": json.loads(json.dumps(KPIS)), "pages": json.loads(json.dumps(PAGES)), "grid": {"columns": 24}},
               "refresh": "after every lakehouse build", "privacy": "No personal data.", "quality": "3 automated checks",
               "lineage": [{"system": "Store tills", "kind": "s3", "lands": ["pos_tlog"]}], "profiled_at": "2026-11-18T060000Z"}
    if mutate:
        mutate(project, data)
    files = {f"data/{t}.csv": text.encode() for t, text in data.items()}
    files["README.md"] = b"# Mini Grocer\n\nA test hand-off.\n"
    files["project.json"] = json.dumps(project, indent=2).encode()
    inputs = {i.get("table"): i for i in project.get("inputs") or [] if isinstance(i, dict)}
    listed = {}
    for path, b in files.items():
        t = path[5:-4] if path.startswith("data/") else None
        listed[path] = ({"rows": inputs[t]["rows"], "sha256": sha(b),
                         "columns": {cc["name"]: cc["type"] for cc in inputs[t]["columns"]}} if t in inputs else {"sha256": sha(b)})
    files["manifest.json"] = json.dumps({"run": f"2026-11-18T06{S}Z", "release": "T-1", "files": listed,
                                         "rows": sum(i["rows"] for i in inputs.values())}, indent=2).encode()
    if after:
        after(files)
    return files


def zipped(files: dict[str, bytes], folder: str | None = "mini", backslash: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, b in files.items():
            name = f"{folder}/{path}" if folder else path
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 18, 6, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            if backslash:                       # as Windows PowerShell 5.1's Compress-Archive writes them
                info.filename = name.replace("/", "\\")
            z.writestr(info, b)
    return buf.getvalue()


def imp(p: c.Person, data: bytes, filename: str = "mini.zip", **fields):
    return p.form("/api/projects/import", {"visuals_mode": "builtin", **fields}, {"handoff": (filename, data)})


owner = c.Person(f"hana.handoff@handoff{S}.com")
s, r = owner.sign_in(f"Handoff Test {S}", "Hana Handoff")
check("setup: PASDACS's new organisation's owner signs in", s == 200, (s, r))
owner.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
admin = c.signed_in("info@pasdacs.com", c.ADMIN_BASE)
org = (owner.get("/api/me")[1] or {}).get("org") or {}
tid = org.get("id")


def balance() -> int:
    return ((owner.get("/api/me")[1] or {}).get("org") or {}).get("credits") or 0


def set_balance(n: int) -> None:
    delta = n - balance()
    if delta:
        admin.post(f"/api/admin/orgs/{tid}/credits", {"credits": delta, "note": "item 58 check"})


def dashboards() -> list[dict]:
    s, d = owner.get("/api/projects")
    return d if isinstance(d, list) else []


def leftovers() -> str:
    return g.sh(f"ls -A /data/projects/.tenants/{tid} 2>/dev/null | grep '^[.]import-' || true")


def ledger(pid: str) -> list[dict]:
    return [x for x in (owner.get("/api/org")[1] or {}).get("ledger", []) if x.get("project_id") == pid]


set_balance(400)
check("setup: the organisation has 400 credits", balance() == 400, balance())

# ---------------------------------------------------------------- refused before anything is saved or charged
section("refused: what is wrong is said, nothing is saved, no credits are used")


def refused(label: str, data: bytes, phrase: str, filename: str = "mini.zip") -> None:
    s, r = imp(owner, data, filename)
    check(f"refused: {label} (400, says so)", s == 400 and phrase.lower() in str(detail(r)).lower(), (s, detail(r)))


def drop_project(files):
    files.pop("project.json")


def two_handoffs():
    one, two = handoff(), handoff()
    return zipped({**{f"a/{k}": v for k, v in one.items()}, **{f"b/{k}": v for k, v in two.items()}}, folder=None)


def escape():
    files = handoff()
    buf = io.BytesIO(zipped(files))
    with zipfile.ZipFile(buf, "a") as z:
        z.writestr("../evil.csv", b"a,b\n1,2\n")
    return buf.getvalue()


def change_csv(files):
    files["data/sales_daily.csv"] = files["data/sales_daily.csv"].replace(b"100.50", b"999.50")


def lose_readme(files):
    files.pop("README.md")


def header(project, data):
    data["sales_daily"] = data["sales_daily"].replace("net_sales\n", "net_amount\n", 1)


def extra_row(project, data):
    project["inputs"][2]["rows"] = rows_of(data["sales_daily"])
    data["sales_daily"] += "2026-11-03,1,store,3,30.00\n"


def unknown_column(project, data):
    project["plan"]["model"]["relationships"][0] = "sales_daily[shop_id] -> dim_store[store_id]"


def duplicate_keys(project, data):
    data["dim_store"] += "3,West End Two,Alpha,West\n"
    project["inputs"][0]["rows"] = rows_of(data["dim_store"])


def two_paths(project, data):
    project["inputs"].append({"file": "data/dim_region.csv", "table": "dim_region", "description": "Regions", "rows": 2,
                              "columns": [{"name": "region_name", "type": "text", "description": "Region"}]})
    data["dim_region"] = "region_name\nEast\nWest\n"
    project["inputs"][2]["columns"].append({"name": "region_name", "type": "text", "description": "Region"})
    data["sales_daily"] = "\n".join(ln + (",region_name" if i == 0 else ",East") for i, ln in enumerate(data["sales_daily"].splitlines())) + "\n"
    project["plan"]["model"]["relationships"] += ["dim_store[region_name] -> dim_region[region_name]",
                                                  "sales_daily[region_name] -> dim_region[region_name]"]


def bad_dax(project, data):
    project["plan"]["kpis"][0]["dax"] = 'CALCULATE(SUM(sales_daily[net_sales]), sales_daily[channel] = "store)'


def bad_format(project, data):
    project["plan"]["kpis"][1]["format"] = "money"


def type_mismatch(project, data):
    project["plan"]["model"]["relationships"][0] = "sales_daily[channel] -> dim_store[store_id]"


def many_files():
    buf = io.BytesIO(zipped(handoff()))
    with zipfile.ZipFile(buf, "a") as z:
        for n in range(2001):
            z.writestr(f"mini/notes/n{n}.txt", b"x")
    return buf.getvalue()


before, n_before = balance(), len(dashboards())
refused("a CSV instead of the .zip", SALES.encode(), "one .zip", "sales_daily.csv")
refused("a file that is not a zip", b"PK\x03\x04 this is not a zip at all", "not a .zip")
refused("no project.json", zipped(handoff(after=drop_project)), "no project.json")
refused("two hand-offs in one zip", two_handoffs(), "more than one hand-off")
refused("a file outside the folder (../evil.csv)", escape(), "outside its folder")
refused("another format (2)", zipped(handoff(mutate=lambda p, d: p.update(format=2))), "format 1")
refused("not a D2D project (kind)", zipped(handoff(mutate=lambda p, d: p.update(kind="lakehouse"))), "not a D2D project hand-off")
refused("no manifest.json", zipped({k: v for k, v in handoff().items() if k != "manifest.json"}), "no manifest.json")
refused("a CSV changed after the manifest (names the file)", zipped(handoff(after=change_csv)),
        "data/sales_daily.csv does not match the manifest (sha256)")
refused("a file the manifest lists is not in the zip", zipped(handoff(after=lose_readme)), "README.md is in the manifest but not in the zip")
refused("a CSV's columns differ from project.json's", zipped(handoff(mutate=header)), "its columns are")
refused("a CSV holds more rows than project.json says", zipped(handoff(mutate=extra_row)), "holds 7 rows, but project.json says 6")
refused("a relationship names a column that is not there", zipped(handoff(mutate=unknown_column)), "sales_daily[shop_id]")
refused("a relationship's one side repeats a key", zipped(handoff(mutate=duplicate_keys)), "dim_store[store_id] repeats values")
refused("two filter paths between tables", zipped(handoff(mutate=two_paths)), "filter paths to sales_daily")
refused("a relationship joins two types", zipped(handoff(mutate=type_mismatch)), "same type")
refused("a KPI's DAX has an unterminated string (D2D's plan check)", zipped(handoff(mutate=bad_dax)), "plan check")
refused("a KPI's format is not one of DAWB's", zipped(handoff(mutate=bad_format)), "money")
refused("more files than a hand-off has", many_files(), "more than a hand-off has")
check("refused: no credits were used", balance() == before, (before, balance()))
check("refused: no dashboard was made", len(dashboards()) == n_before, [d.get("name") for d in dashboards()])
check("refused: nothing is left behind in the organisation's folder", leftovers() == "", leftovers())

set_balance(10)
s, r = imp(owner, zipped(handoff()))
check("not enough credits: 402 before anything is saved", s == 402 and "credits" in str(detail(r)).lower(), (s, detail(r)))
check("not enough credits: no dashboard, nothing left behind", len(dashboards()) == n_before and leftovers() == "", leftovers())
set_balance(400)

# ---------------------------------------------------------------- a good hand-off
section("a good hand-off: a dashboard at Confirm KPIs with DAWB's plan")
files = handoff()
upload = zipped(files)
s, r = imp(owner, upload, f"mini-{S}.zip")
pid = r.get("id") if s == 200 and isinstance(r, dict) else None
check("import: 200, a new dashboard", bool(pid), (s, detail(r)))
st = owner.get(f"/api/projects/{pid}")[1] if pid else {}
st = st if isinstance(st, dict) else {}
plan = st.get("plan") or {}
check("import: it waits at Confirm KPIs (awaiting_kpis), the plan made once, no job", st.get("status") == "awaiting_kpis"
      and st.get("plan_rounds") == 1 and not st.get("job"), {k: st.get(k) for k in ("status", "plan_rounds", "job", "plan_error")})
check("import: named after the hand-off", st.get("name") == f"Mini Grocer {S}", st.get("name"))
check("import: the price of a new dashboard with Power BI's built-in visuals (25)", balance() == 375
      and [(x["kind"], x["delta"]) for x in ledger(pid)] == [("charge", -25)], (balance(), ledger(pid)))
check("import: the charge says it came from a hand-off, and rides with the first build",
      "hand-off" in str((ledger(pid) or [{}])[0].get("note")) and bool(st.get("credit_charge")), (ledger(pid), st.get("credit_charge")))
ho = st.get("handoff") or {}
check("import: where it came from (DAWB, release, run, 3 tables, 12 rows, 2 relationships, 1 KPI renamed)",
      ho.get("from") == "DAWB" and ho.get("release") == "T-1" and ho.get("run") == f"2026-11-18T06{S}Z" and ho.get("tables") == 3
      and ho.get("rows") == 12 and ho.get("relationships") == 2 and ho.get("renamed") == [["Orders", "Total orders"]], ho)
got = [(k.get("name"), k.get("label"), k.get("format"), k.get("dax")) for k in plan.get("kpis") or []]
check("plan: DAWB's 5 KPIs in order, labels its names, formats mapped (currency, whole number, percent, its format_string)",
      [x[:3] for x in got] == [x[:3] for x in EXPECT], got)
check("plan: the KPI named like a column is now Total orders, and the KPIs using it follow (not strings or comments)",
      [x[3] for x in got] == [x[3] for x in EXPECT], [x[3] for x in got])
check("plan: the KPIs' descriptions are DAWB's", [k.get("description") for k in plan.get("kpis") or []] == [k["description"] for k in KPIS],
      [k.get("description") for k in plan.get("kpis") or []])
check("plan: DAWB's pages with their purpose and visuals", plan.get("pages") == [
    {"name": "Overview", "purpose": "How the stores sell", "visuals": ["Net sales (card)", "Net sales by banner (clustered bar chart)"]},
    {"name": "Channels", "purpose": "Store and online orders", "visuals": ["Orders by channel (donut chart)"]}], plan.get("pages"))
model = plan.get("model") or {}
check("plan: the model's tables (CSV, role, grain, description), relationships and note",
      [(t.get("name"), t.get("csv"), t.get("role"), t.get("grain"), t.get("description")) for t in model.get("tables") or []] == [
          ("dim_date", "dim_date.csv", "date table", "one row per day", DESCR["dim_date"]),
          ("dim_store", "dim_store.csv", "dimension", "one row per store", DESCR["dim_store"]),
          ("sales_daily", "sales_daily.csv", "fact", "one row per day, store and channel", DESCR["sales_daily"])]
      and model.get("relationships") == RELS and model.get("note") == "A small star: sales join the dates and the stores.", model)
check("plan: its summary is the hand-off's description and audience", plan.get("summary") ==
      "Show the store leaders how sales and orders move by banner and channel. For: Store leaders.", plan.get("summary"))
note = str(st.get("plan_summary"))
check("plan notes: from DAWB's hand-off, KPIs and pages counted, the manifest matched, the rename explained",
      "DAWB's plan from its hand-off (release T-1" in note and "5 KPIs on 2 pages" in note and "matches the hand-off's manifest" in note
      and "Orders is now Total orders" in note and "2 relationships join the tables" in note, note)
check("files: the 3 CSVs as uploaded (names and sizes)", sorted((f["name"], f["bytes"]) for f in st.get("files") or []) ==
      sorted((p[5:], len(b)) for p, b in files.items() if p.startswith("data/")), st.get("files"))
s, prev = owner.get(f"/api/projects/{pid}/data/sales_daily.csv?limit=5")
check("files: the data reads back (6 rows of sales)", s == 200 and isinstance(prev, dict) and prev.get("total") == 6, (s, prev))
check("files: profile.md is there to read, as Relay's planning makes it", "profile.md" in (st.get("files_available") or []), st.get("files_available"))
s, prof = owner.get(f"/api/projects/{pid}/files/profile.md")
check("files: ... with every table profiled", s == 200 and all(f"{t}.csv" in str(prof) for t in COLS), str(prof)[:300])
s, req = owner.get(f"/api/projects/{pid}/files/request.md")
req = str(req)
check("request.md: from a DAWB hand-off, how to use its plan (keep the names the KPIs use, visuals as guidance)",
      "## From a DAWB hand-off" in req and "keep each KPI's DAX logic and the table and column names it uses" in req
      and "not as a fixed layout" in req, req[:600])
check("request.md: the data with DAWB's table and column descriptions and types", "- sales_daily.csv (" in req
      and "  - net_sales (decimal -> decimal): Sales after discounts, USD" in req and "Daily sales per store and channel." in req, req[:1500])
check("request.md: the relationships, the model note, the renamed KPI", "- sales_daily[store_id] -> dim_store[store_id]" in req
      and "A small star" in req and "- Orders -> Total orders" in req, req[-1500:])
check("request.md: the planned visuals with their place on the grid and their query", "- Net sales (card); x 0, y 0, w 6, h 4: "
      "`SELECT SUM(net_sales) AS net_sales FROM gold.sales_daily`" in req, req[-900:])
check("request.md: the visuals section as any new dashboard's (built-in visuals only)", "## Visuals" in req and "Visuals: builtin" in req, req[-400:])
s, py = owner.get(f"/api/projects/{pid}/files/plan.yaml")
check("plan.yaml: written, with the renamed KPI", s == 200 and "Total orders" in str(py) and "label: Orders" in str(py), str(py)[:400])
act = owner.get(f"/api/projects/{pid}/activity")[1] or []
texts = [e.get("text") or "" for e in act if isinstance(e, dict)]
check("activity: the import and the plan are logged", any(t.startswith("Imported DAWB's hand-off (release T-1") and "3 files with 12 rows" in t for t in texts)
      and any(t.startswith("Plan from DAWB: 5 KPIs on 2 pages") for t in texts), texts[-4:])
mine = next((d for d in dashboards() if d.get("id") == pid), {})
check("dashboards list: it is there, waiting for its KPIs", mine.get("status") == "awaiting_kpis", mine)
folder = f"/data/projects/.tenants/{tid}/{pid}"
kept = g.sh(f"cd {folder} && sha256sum handoff/project.json handoff/manifest.json && ls -A && ls -A .genbi/cache | wc -l")
check("folder: DAWB's project.json and manifest.json kept as written", sha(files["project.json"]) in kept and sha(files["manifest.json"]) in kept, kept)
check("folder: data, plan.yaml, request.md, profile.json, CLAUDE.md, the profile's cache; nothing left beside it",
      all(x in kept.split() for x in ("data", "plan.yaml", "request.md", "profile.json", "profile.md", "CLAUDE.md", ".genbi"))
      and leftovers() == "", (kept, leftovers()))
aud = g.app(f"""
import json
with _db.use({tid!r}):
    rows = _db.audit_log(action="project.import")
    print(json.dumps([(r["object"], r["detail"]) for r in rows]))
""")
check("audit: project.import with where it came from", pid in aud and '"from": "DAWB"' in aud and '"run": "2026-11-18T06' in aud, aud[-400:])

# ---------------------------------------------------------------- the other shapes and prices
section("the zip as people make it, custom visuals, no relationships")
s, r = imp(owner, zipped(handoff(name=f"Mini Root {S}"), folder=None, backslash=True), "root.zip")
st2 = owner.get(f"/api/projects/{r.get('id')}")[1] if s == 200 and isinstance(r, dict) else {}
check("zip: files at its top with Windows backslashes in their names import too", s == 200 and (st2 or {}).get("status") == "awaiting_kpis"
      and len((st2 or {}).get("files") or []) == 3, (s, detail(r)))
b0 = balance()
s, r = imp(owner, zipped(handoff(name=f"Mini Custom {S}")), "custom.zip", visuals_mode="mixed")
st3 = owner.get(f"/api/projects/{r.get('id')}")[1] if s == 200 and isinstance(r, dict) else {}
check("price: built-in first with custom visuals uses 50, as a new dashboard does", s == 200 and b0 - balance() == 50
      and (st3 or {}).get("visuals_mode") == "mixed", (s, b0, balance()))


def no_rels(project, data):
    project["plan"]["model"].pop("relationships")
    project["plan"]["model"]["tables"] = ["sales_daily", "dim_store", "dim_date"]


s, r = imp(owner, zipped(handoff(mutate=no_rels, name=f"Mini Plain {S}")), "plain.zip")
st4 = owner.get(f"/api/projects/{r.get('id')}")[1] if s == 200 and isinstance(r, dict) else {}
p4 = (st4 or {}).get("plan") or {}
check("no relationships: the tables as they are (names only: every table a fact), and the notes say so", s == 200
      and [t.get("role") for t in (p4.get("model") or {}).get("tables") or []] == ["fact"] * 3
      and (p4.get("model") or {}).get("relationships") == [] and "no relationships" in str((st4 or {}).get("plan_summary")), (s, detail(r), p4.get("model")))

# ---------------------------------------------------------------- the build, and the toolkit's parts
section("Confirm KPIs, the build's instructions, column descriptions in the model")
s, after = owner.form(f"/api/projects/{pid}/kpis", {"payload": json.dumps({"action": "confirm", "kpis": plan.get("kpis") or [],
                                                                          "feedback": "", "visuals": {}})})
after = after if isinstance(after, dict) else {}
check("confirm: the build is queued with the import's charge (no new charge)", s == 200 and (after.get("job") or {}).get("kind") == "build"
      and (after.get("job") or {}).get("charge") == st.get("credit_charge") and len(ledger(pid)) == 1, (s, after.get("job"), ledger(pid)))
s, req2 = owner.get(f"/api/projects/{pid}/files/request.md")
check("confirm: request.md records the KPIs as confirmed", "## KPIs confirmed by the user" in str(req2) and "**Total orders** (Orders)" in str(req2), str(req2)[-500:])
for _ in range(90):                             # the test stack has no Claude: the build stops at once
    st5 = owner.get(f"/api/projects/{pid}")[1] or {}
    if st5.get("status") == "error":
        break
    time.sleep(2)
time.sleep(3)
st5 = owner.get(f"/api/projects/{pid}")[1] or {}
check("confirm: a build that had started keeps the import's credits and Retry is free (item 48, as any dashboard)",
      st5.get("status") == "error" and [x["kind"] for x in ledger(pid)] == ["charge"] and (st5.get("credits") or {}).get("retry") == 0,
      (st5.get("status"), ledger(pid), st5.get("credits")))
out = g.app("""
from app import prompts
print(prompts.HANDOFF.strip() in prompts.build([], "builtin", handoff=True), prompts.HANDOFF.strip() in prompts.build([], "builtin"))
""")
check("build: an imported dashboard's build is told how to use the hand-off's plan (others are not)", out.strip().endswith("True False"), out[-300:])
out = g.app("""
import yaml
from genbi_kit import definition, report_builder as rb
raw = yaml.safe_load(open("/opt/genbi/genbi_kit/examples/atlas_retail.yaml", encoding="utf-8"))
t = next(t for t in raw["tables"] if t.get("csv") and t.get("columns"))
t["columns"][0]["description"] = "Sales after discounts \\u2014 USD"
dd = definition.expand(raw)
bim = rb._model_bim(dd, rb.Model(dd))
col = next(cc for tt in bim["model"]["tables"] if tt["name"] == t["name"] for cc in tt["columns"] if cc["name"] == t["columns"][0]["name"])
print("DESC", col.get("description"))
""")
check("model: a column's description reaches Power BI's model, in plain characters", "DESC Sales after discounts - USD" in out, out[-300:])

# ---------------------------------------------------------------- the real hand-off DAWB writes on this PC
section("the real hand-off on this PC")


def real_files() -> dict[str, bytes] | None:
    """The hand-off folder's files once they match its manifest (DAWB may be writing it: try for a minute)."""
    for _ in range(12):
        try:
            files = {f.relative_to(REAL).as_posix(): f.read_bytes() for f in sorted(REAL.rglob("*")) if f.is_file()}
            m = json.loads(files["manifest.json"])
            if all(sha(files[p]) == i["sha256"] for p, i in m["files"].items()):
                return files
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(5)
    return None


if not (REAL / "project.json").is_file():
    print(f"(no hand-off at {REAL}: set TEST_HANDOFF_DIR to check one; skipped)", flush=True)
else:
    real = real_files()
    check("real: the hand-off folder matches its manifest", real is not None, str(REAL))
    if real:
        rp, rm = json.loads(real["project.json"]), json.loads(real["manifest.json"])
        s, r = imp(owner, zipped(real, folder=REAL.name), f"{REAL.name}.zip")
        rid = r.get("id") if s == 200 and isinstance(r, dict) else None
        rs = owner.get(f"/api/projects/{rid}")[1] if rid else {}
        rs = rs if isinstance(rs, dict) else {}
        rplan, kp, pg = rs.get("plan") or {}, rp["plan"]["kpis"], rp["plan"]["pages"]
        renamed = {a: b for a, b in (rs.get("handoff") or {}).get("renamed") or []}
        check(f"real: {rp['name']} ({rm.get('release')}, run {rm.get('run')}) waits at Confirm KPIs with {len(kp)} KPIs and "
              f"{len(pg)} pages", rs.get("status") == "awaiting_kpis" and len(rplan.get("kpis") or []) == len(kp)
              and len(rplan.get("pages") or []) == len(pg), (s, detail(r), rs.get("status")))
        check(f"real: its {len(rp['inputs'])} tables with {sum(i['rows'] for i in rp['inputs']):,} rows",
              sorted(f["name"] for f in rs.get("files") or []) == sorted(f"{i['table']}.csv" for i in rp["inputs"])
              and (rs.get("handoff") or {}).get("rows") == sum(i["rows"] for i in rp["inputs"]), rs.get("handoff"))

        def follow(dax: str) -> str:
            for a, b in renamed.items():
                dax = re.sub(r"(?<![\w'])\[" + re.escape(a) + r"\]", "[" + b + "]", dax, flags=re.I)
            return dax.strip()
        got = rplan.get("kpis") or []
        check("real: each KPI as DAWB wrote it (its DAX, label and format), renamed only where it had a column's name",
              len(got) == len(kp) and all(g_["dax"] == follow(k["dax"]) and g_["label"] == k["name"]
                                          and g_["name"] == renamed.get(k["name"], k["name"])
                                          and g_["format"] == (k.get("format_string") or FORMATS[k["format"]]) for g_, k in zip(got, kp)),
              [(g_.get("name"), g_.get("format")) for g_ in got])
        columns = {cc["name"].lower() for i in rp["inputs"] for cc in i["columns"]}
        check("real: no KPI keeps a column's name", not [k["name"] for k in got if k["name"].lower() in columns], [k["name"] for k in got])
        check("real: its pages and relationships as DAWB wrote them", [p_["name"] for p_ in rplan.get("pages") or []] == [p_["name"] for p_ in pg]
              and (rplan.get("model") or {}).get("relationships") == [re.sub(r"\s*->\s*", " -> ", x.strip())
                                                                      for x in rp["plan"]["model"].get("relationships") or []], rplan.get("model"))

# ---------------------------------------------------------------- the screens
section("the screens")
local = Path(c.out_path(f"item58-mini-{S}.zip"))
local.write_bytes(zipped(handoff(name=f"Mini Screens {S}")))
cp = subprocess.run(["docker", "cp", str(local), f"{c.WEB_C}:/tmp/item58-mini.zip"], capture_output=True, text=True)
g.sh("chmod a+r /tmp/item58-mini.zip", "root")
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, name = sys.argv[1], sys.argv[2]
typo = "".join(chr(x) for x in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019, 0xB7, 0x2022, 0x203A, 0x2039, 0x2192, 0x2190, 0x2194))
out, errors = {}, []
H3 = "() => [...document.querySelectorAll('h3')].some(x => x.textContent.trim() === \"DAWB's plan\")"
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    # New dashboard, the guided way (2026-11-19): Name, then Your data's "From a DAWB hand-off", then the steps to Start
    nd_open(page)
    page.fill("#nd-name", name)
    nd_next(page, 1)
    page.click(".dmode button:has-text('From a DAWB hand-off')")
    page.wait_for_timeout(300)
    out["zip_shown"] = page.locator(f"{ND_SHOWN} input[type=file][accept^='.zip']").evaluate("e => !e.closest('[hidden]')")
    out["csv_hidden"] = page.locator(f"{ND_SHOWN} input[type=file][accept^='.csv']").evaluate("e => !!e.closest('[hidden]')")
    data_text = page.locator(ND_SHOWN).inner_text()
    page.screenshot(path="/tmp/item58-new-1280.png", full_page=True)
    nd_upload(page, ".zip", "/tmp/item58-mini.zip", "item58-mini.zip")
    nd_next(page, 2)
    out["label"] = page.locator(f"{ND_SHOWN} label[for=nd-added]").inner_text()
    out["prompt_hidden"] = page.locator("#nd-prompt").evaluate("e => !!e.closest('[hidden]')")
    build_text = page.locator(ND_SHOWN).inner_text()
    nd_next(page, 3)
    page.wait_for_selector(f"{ND_SHOWN} .nd-theme", timeout=30000)
    nd_next(page, 4)
    nd_next(page, 5)
    out["button"] = page.locator("form.formcard.nd .nd-nav button[type=submit]").inner_text()
    out["form_text"] = data_text + "\n" + build_text + "\n" + page.locator(ND_SHOWN).inner_text()
    nd_next(page)
    page.wait_for_function("() => location.hash.startsWith('#/p/')", timeout=60000)
    page.wait_for_function(H3, timeout=30000)
    page.wait_for_timeout(800)
    out["hash"] = page.evaluate("location.hash")
    out["kpis"] = page.locator(".kpi").count()
    out["names"] = page.locator(".kpi .k-name").evaluate_all("xs => xs.map(x => x.value)")
    out["labels"] = page.locator(".kpi .k-label").evaluate_all("xs => xs.map(x => x.value)")
    out["text"] = page.evaluate("document.querySelector('#main').innerText")
    out["full"] = page.evaluate("document.querySelector('#main').textContent")
    out["sideways_1280"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    page.screenshot(path="/tmp/item58-plan-1280.png", full_page=True)
    ctx.close()
    # a phone opens it at its own width (a fresh browser, as the other suites do: the app keeps a wide window's sidebar
    # state, d2d.rail, which a desktop window shrunk to 360 px would carry)
    ctx = b.new_context(viewport={"width": 360, "height": 800})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)[:300]))
    page.goto("http://127.0.0.1:8000/" + out["hash"])
    page.wait_for_function(H3, timeout=30000)
    page.wait_for_timeout(800)
    out["sideways_360"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    page.screenshot(path="/tmp/item58-plan-360.png", full_page=True)
    nd_open(page)                                   # the guided New dashboard at phone width: Your data, a hand-off
    page.fill("#nd-name", "Phone check")
    nd_next(page, 1)
    page.click(".dmode button:has-text('From a DAWB hand-off')")
    page.wait_for_timeout(300)
    out["new_sideways_360"] = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    page.screenshot(path="/tmp/item58-new-360.png", full_page=True)
    out["typo"] = "".join(ch for ch in out["form_text"] + out["text"] if ch in typo)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
n0, b0 = len(dashboards()), balance()
ui = browser(c.WEB_C, c.ND_FLOW + PLAY, c.cookie(owner, "d2d_session"), f"Mini Screens {S}")
check("New dashboard: 'From a DAWB hand-off' shows the .zip picker and hides the CSV one", ui.get("zip_shown") is True
      and ui.get("csv_hidden") is True, ui if "zip_shown" not in ui else {k: ui.get(k) for k in ("zip_shown", "csv_hidden")})
check("New dashboard: for a hand-off, What to build asks only for anything to add; the last step's button says what comes next",
      "Anything to add" in str(ui.get("label")) and ui.get("prompt_hidden") is True and "Import - confirm DAWB's plan next" in str(ui.get("button")),
      (ui.get("label"), ui.get("prompt_hidden"), ui.get("button")))
check("New dashboard: it says D2D checks the manifest and shows DAWB's plan", "checks every file against the hand-off's manifest" in str(ui.get("form_text"))
      and "shows DAWB's plan for you to confirm" in str(ui.get("form_text")), str(ui.get("form_text"))[-600:])
check("import from the form: it opens the new dashboard at Confirm KPIs", str(ui.get("hash", "")).startswith("#/p/mini-screens")
      and len(dashboards()) == n0 + 1 and b0 - balance() == 25, (ui.get("hash"), len(dashboards()) - n0, b0 - balance()))
check("plan screen: DAWB's plan, from a DAWB hand-off, with its 5 KPIs (Total orders labelled Orders)",
      "DAWB's plan" in str(ui.get("text")) and "From a DAWB hand-off" in str(ui.get("text")) and ui.get("kpis") == 5
      and ui.get("names") == [x[0] for x in EXPECT] and ui.get("labels") == [x[1] for x in EXPECT], {k: ui.get(k) for k in ("kpis", "names", "labels")})
# since items 61/62 the plan screen shows the semantic model (its diagram: a relationship is its line's title) in place
# of the Data model card, once the data was read (at the import)
check("plan screen: the rename in the notes' first paragraph (shown), the pages, the relationships (in the semantic model's diagram)",
      "Orders is now Total orders" in str(ui.get("text")) and "Orders by channel (donut chart)" in str(ui.get("text"))
      and "sales_daily[store_id] -> dim_store[store_id]" in str(ui.get("full")) and "2 relationships join the tables" in str(ui.get("full")),
      str(ui.get("text"))[:900])
check("plan screen: the hand-off's note on its model (DAWB's own words) is shown", "A small star" in str(ui.get("text")),
      [ln for ln in str(ui.get("text")).splitlines() if "model" in ln.lower()][:6])
check("screens: nothing sideways at 1280 and 360 px (plan and New dashboard), plain characters, no script errors",
      ui.get("sideways_1280") is False and ui.get("sideways_360") is False and ui.get("new_sideways_360") is False
      and ui.get("typo") == "" and ui.get("errors") == [], {k: ui.get(k) for k in ("sideways_1280", "sideways_360", "new_sideways_360", "typo", "errors", "stderr")})
for f in ("item58-new-1280.png", "item58-plan-1280.png", "item58-plan-360.png", "item58-new-360.png"):
    subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, capture_output=True)
local.unlink(missing_ok=True)

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
