"""Test stack only (the web container; the AI is not called): item 52 (2026-11-15), the three display bugs a real build
showed (docs/LOG.md). The built-in visuals gallery (genbi_kit/examples/stock_gallery.yaml, data samples/*.csv) plus an
"Item 52" page, drawn by the image's `genbi prototype` and looked at in Chromium; the numbers it should show are
worked out here from samples/sales.csv:
- the matrix never adds up a ratio: Power BI computes every measure once per row header. A stepped matrix opens at its
  first Rows level, one row per Region from SQL at that level, the Total line from its ROLLUP row (ratios too); SQL at
  a finer grain is reported to the agent and shows the sums of measures that add up, other cells blank; with
  rowHeaders.autoExpand every level opens: bold groups with their own values above indented children, sorted by the
  visual's sort, or a Total row after them (Bottom); a missing group row is reported; the DAX check asks Power BI for
  the level the matrix opens at and compares two Rows levels by position;
- a card's text: Power BI's multi-row card cuts a sentence with "..." inside its own place (no value runs into the
  next) and the Display check fails it; the new card with value.textWrap shows the sentences whole;
- Ask Relay: a percentage held as a fraction reads 84.5% (chips, axis, labels, table, "See the numbers", the snapshot),
  the count reads "8 cities", and the prompt asks for fractions in pct-named columns.
python -I -X utf8 item52_check.py <public> <admin>"""
import csv
import json
import os
import re
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check
REPO = os.path.dirname(os.path.dirname(HERE))
WORK = "/tmp/item52"
S = ["Revenue grew 3.5% to $1,241,172 and profit grew 4.1% to $408,605. North grew fastest (+23.2%), South lagged (-11.8%).",
     "Margin is 32.9%, 2.3 pts above target, but 4 of 8 products miss their target margin; Headphones has the largest gap.",
     "Retail is the most profitable channel ($145,369, 34.1% margin) and Laptop the top product, earning 44% of all profit."]
MEASURES = [{"name": f"Insight {n}", "folder": "Item 52", "expression": f"\"{s}\""} for n, s in zip(("One", "Two", "Three"), S)]
Y25 = 'FROM "Sales" s JOIN "Date" d ON d."Date" = s."Order Date" WHERE d."Year" = 2025'
RM = 'SUM(s."Revenue Amount") AS "Revenue", SUM(s."Profit Amount") / SUM(s."Revenue Amount") AS "Margin %"'
AOV = 'SUM(s."Revenue Amount") / COUNT(DISTINCT s."Order ID") AS "Avg Order Value"'
M = lambda vid, rows, values, sql, fmt=None, span=6: {"id": vid, "type": "pbi.pivotTable", "span": span, "title": vid,  # noqa: E731
                                                      "fields": {"rows": rows, "values": values}, "sort": ["[Revenue]", "desc"],
                                                      **({"format": fmt} if fmt else {}), "prototype": {"sql": sql}}
EXP = {"rowHeaders": {"autoExpand": True}}
PAGE = {"name": "Item 52", "rows": [
    {"height": 260, "visuals": [
        M("m_collapsed", ["Sales[Region]", "Sales[City]"], ["[Revenue]", "[Margin %]", "[Avg Order Value]"],
          f'SELECT s."Region" AS "Region", {RM}, {AOV} {Y25} GROUP BY ROLLUP (s."Region") ORDER BY 2 DESC'),
        M("m_leaf", ["Sales[Region]", "Sales[City]"], ["[Revenue]", "[Margin %]", "[Avg Order Value]"],
          f'SELECT s."Region" AS "Region", s."City" AS "City", {RM}, {AOV} {Y25} GROUP BY 1, 2 ORDER BY 1, 2')]},
    {"height": 380, "visuals": [
        M("m_expanded", ["Sales[Category]", "Sales[Product]"], ["[Revenue]", "[Margin %]"],
          f'SELECT s."Category" AS "Category", s."Product" AS "Product", {RM} {Y25} GROUP BY ROLLUP (s."Category", s."Product") '
          f'ORDER BY s."Category" NULLS LAST, s."Product" NULLS FIRST', EXP),
        M("m_nogroups", ["Sales[Category]", "Sales[Product]"], ["[Revenue]", "[Margin %]"],
          f'SELECT s."Category" AS "Category", s."Product" AS "Product", {RM} {Y25} GROUP BY 1, 2 ORDER BY 1, 2', EXP)]},
    {"height": 380, "visuals": [
        M("m_bottom", ["Sales[Region]", "Sales[City]"], ["[Revenue]"],
          f'SELECT s."Region" AS "Region", s."City" AS "City", SUM(s."Revenue Amount") AS "Revenue" {Y25} GROUP BY ROLLUP (s."Region", s."City")',
          {"rowHeaders": {"autoExpand": True}, "subTotals": {"rowSubtotalsPosition": "Bottom"}})]},
    {"height": 170, "visuals": [
        {"id": "mr_sentences", "type": "pbi.multiRowCard", "span": 12, "title": "Key insights (multi-row card)",
         "fields": {"values": ["[Insight One]", "[Insight Two]", "[Insight Three]"]},
         "prototype": {"sql": "SELECT " + ", ".join(f"'{s}' AS \"Insight {n}\"" for n, s in zip(("One", "Two", "Three"), S))}}]},
    {"height": 170, "visuals": [
        {"id": "cv_wrap", "type": "pbi.cardVisual", "span": 12, "title": "Key insights (new card, text wrap)",
         "fields": {"Data": ["[Insight One]", "[Insight Two]", "[Insight Three]"]},
         "format": {"value": {"textWrap": True, "fontSize": 11, "bold": False}, "label": {"show": False}},
         "prototype": {"sql": "SELECT " + ", ".join(f"'{s}' AS \"Insight {n}\"" for n, s in zip(("One", "Two", "Three"), S))}}]}]}


def docker(*args: str, input_text: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def kit(code: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return docker("exec", "-i", "-u", "agent", "-w", WORK, "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-",
                  input_text=code, timeout=timeout)


# ---------------------------------------------------------------- what the numbers are (samples/sales.csv, 2025)
agg: dict = {}
with open(os.path.join(REPO, "samples", "sales.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if not r["Order Date"].startswith("2025"):
            continue
        for k in (("region", r["Region"]), ("city", r["Region"], r["City"]), ("cat", r["Category"]), ("prod", r["Category"], r["Product"]), ("all",)):
            a = agg.setdefault(k, {"rev": 0.0, "prof": 0.0, "orders": set()})
            a["rev"] += float(r["Revenue"])
            a["prof"] += float(r["Profit"])
            a["orders"].add(r["Order ID"])
want = lambda *k: (agg[k]["rev"], agg[k]["prof"] / agg[k]["rev"], agg[k]["rev"] / len(agg[k]["orders"]))  # noqa: E731
regions = sorted({k[1] for k in agg if k[0] == "region"}, key=lambda x: -agg[("region", x)]["rev"])
cats = sorted({k[1] for k in agg if k[0] == "cat"}, key=lambda x: -agg[("cat", x)]["rev"])


def number(s: str) -> float | None:
    s = str(s or "").strip()
    if not s:
        return None
    neg = s.startswith("-") or s.startswith("(")
    x = float(re.sub(r"[^0-9.]", "", s) or "nan")
    return -x if neg else x


near = lambda shown, value, pct=False: shown is not None and abs(shown - (value * 100 if pct else value)) <= (0.051 if pct else 0.51 + abs(value) * 1e-9)  # noqa: E731

# ---------------------------------------------------------------- the gallery's prototype, with the Item 52 page
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK)
docker("exec", "-u", "agent", c.WEB_C, "mkdir", "-p", WORK + "/data")
for f in ("sales.csv", "products.csv"):
    docker("cp", os.path.join(REPO, "samples", f), f"{c.WEB_C}:{WORK}/data/{f}")
docker("exec", "-u", "root", c.WEB_C, "chown", "-R", "agent", WORK)
make = ("import json, yaml\n"
        "d = yaml.safe_load(open('/opt/genbi/genbi_kit/examples/stock_gallery.yaml', encoding='utf-8'))\n"
        f"d['measures'] += json.loads({json.dumps(json.dumps(MEASURES))})\n"
        f"d['pages'].append(json.loads({json.dumps(json.dumps(PAGE))}))\n"
        f"open('{WORK}/definition.yaml', 'w', encoding='utf-8').write(yaml.safe_dump(d, sort_keys=False, allow_unicode=True))\n"
        f"open('{WORK}/request.md', 'w', encoding='utf-8').write('# request\\nThe check of item 52.\\n')\n"
        "print(len(d['pages']), 'pages')\n")
r = kit(make)
check("setup: the gallery definition with the Item 52 page is written", r.stdout.strip().endswith("pages"), (r.stdout + r.stderr)[-400:])
r = docker("exec", "-u", "agent", "-w", WORK, "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "genbi", "prototype", timeout=600)
out = (r.stdout + r.stderr).strip()
problems = [ln.strip() for ln in out.splitlines() if " / " in ln and "(" in ln]
check("prototype: genbi draws the gallery and the Item 52 page", "wrote prototype/index.html" in out, out[-600:])
check("matrix: SQL with several rows for one row header is reported to the agent, and only it and a missing group row",
      len(problems) == 2 and "m_leaf" in problems[0] and "rows for Region = " in problems[0] and "autoExpand" in problems[0]
      and "GROUP BY ROLLUP" in problems[0], problems or out[-500:])
check("matrix: with Auto expand, a group without its own row is reported (a ratio cannot be added up)",
      len(problems) == 2 and "m_nogroups" in problems[1] and "with Product empty" in problems[1] and "[Margin %]" in problems[1], problems)

# ---------------------------------------------------------------- what the browser shows
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1500, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file:///tmp/item52/prototype/index.html")
    page.wait_for_timeout(1500)
    i = page.evaluate("R.pages.findIndex(p => p.name === 'Item 52')")
    page.evaluate(f"current = {i}; draw();")
    page.wait_for_timeout(1500)
    out = page.evaluate('''() => {
      const vs = R.pages[current].visuals, boxes = [...document.querySelectorAll('#page > .v')], o = {};
      boxes.forEach((box, k) => { const v = vs[k]; if (!v) return;
        const bb = box.getBoundingClientRect();
        o[v.id] = {rows: [...box.querySelectorAll('tr')].map(tr => [...tr.children].map(td => ({t: td.textContent,
                     b: +getComputedStyle(td).fontWeight >= 600, pl: parseFloat(getComputedStyle(td).paddingLeft), bg: td.style.background || ''}))),
                   texts: [...box.querySelectorAll('svg text')].map(t => { const r = t.getBoundingClientRect();
                     return {s: t.textContent, cut: t.getAttribute('data-cut'), l: r.left, r: r.right, t: r.top, b: r.bottom}; }),
                   box: {l: bb.left, r: bb.right, t: bb.top, b: bb.bottom}, error: (box.querySelector('.err') || {}).textContent || null};
      });
      return o; }''')
    page.screenshot(path="/tmp/item52.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
res = docker("exec", "-i", c.WEB_C, "python3", "-", input_text=PLAY, timeout=300)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("browser: the prototype opens on the Item 52 page", "m_collapsed" in o, res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item52.png", c.out_path("item52-prototype.png")], check=False)


def table(vid: str) -> list[list[dict]]:
    return (o.get(vid) or {}).get("rows") or []


if o:
    t = table("m_collapsed")
    body, total = t[1:-1], t[-1] if t else []
    got = [(row[0]["t"], number(row[1]["t"]), number(row[2]["t"]), number(row[3]["t"])) for row in body]
    print("  m_collapsed:", got, [x["t"] for x in total], flush=True)
    check("matrix: a stepped matrix opens at its first Rows level - one row per Region, biggest first (the visual's sort)",
          [g[0] for g in got] == regions, (got, regions))
    check("matrix: each Region's margin and average order value are its own (never a sum of its cities)",
          all(near(g[1], want("region", g[0])[0]) and near(g[2], want("region", g[0])[1], True) and near(g[3], want("region", g[0])[2]) for g in got), got)
    check("matrix: the Total line takes its values from the SQL's ROLLUP row, the ratios too",
          len(total) == 4 and total[0]["t"] == "Total" and near(number(total[1]["t"]), want("all")[0]) and near(number(total[2]["t"]), want("all")[1], True)
          and near(number(total[3]["t"]), want("all")[2]), [x["t"] for x in total])
    t = table("m_leaf")
    got = [(row[0]["t"], number(row[1]["t"]), row[2]["t"], row[3]["t"]) for row in t[1:-1]]
    print("  m_leaf:", got, [x["t"] for x in t[-1]] if t else None, flush=True)
    check("matrix: SQL at the City grain still shows one row per Region, whose revenue adds up its cities",
          [g[0] for g in got] == regions and all(near(g[1], want("region", g[0])[0]) for g in got), got)
    check("matrix: ... and leaves its margin and average order value blank rather than add them up (Total too)",
          all(g[2] == "" and g[3] == "" for g in got) and t and [x["t"] for x in t[-1]][2:] == ["", ""], (got, t[-1] if t else None))
    t = table("m_expanded")
    lines = [(row[0]["t"], row[0]["b"], row[0]["pl"], number(row[1]["t"]), number(row[2]["t"]), row[2]["b"]) for row in t[1:-1]]
    print("  m_expanded:", lines, flush=True)
    groups = [x for x in lines if x[1]]
    check("matrix: with Auto expand every Category opens, bold, in the visual's order (Revenue, biggest first)", [x[0] for x in groups] == cats, lines)
    check("matrix: each Category's row carries its own revenue and margin (its ROLLUP row), in bold",
          all(near(x[3], want("cat", x[0])[0]) and near(x[4], want("cat", x[0])[1], True) and x[5] for x in groups), groups)
    kids_ok, idx = True, 0
    for g in cats:
        idx = next(i for i, x in enumerate(lines) if x[0] == g and x[1])
        prods = sorted({k[2] for k in agg if k[0] == "prod" and k[1] == g}, key=lambda p: -agg[("prod", g, p)]["rev"])
        kids = lines[idx + 1: idx + 1 + len(prods)]
        kids_ok &= [k[0] for k in kids] == prods and all(not k[1] and k[2] > lines[idx][2] + 4 and near(k[3], want("prod", g, k[0])[0])
                                                         and near(k[4], want("prod", g, k[0])[1], True) for k in kids)
    check("matrix: ... with its products indented beneath, each with its own numbers, biggest first", kids_ok, lines)
    tot = t[-1] if t else []
    check("matrix: the expanded matrix's Total line is the SQL's grand total (its margin too)",
          len(tot) == 3 and near(number(tot[1]["t"]), want("all")[0]) and near(number(tot[2]["t"]), want("all")[1], True), [x["t"] for x in tot])
    t = table("m_nogroups")
    groups = [(row[0]["t"], number(row[1]["t"]), row[2]["t"]) for row in t[1:-1] if row[0]["b"]]
    check("matrix: without group rows a Category shows its products' revenue added up and no margin (not a sum of margins)",
          [x[0] for x in groups] == cats and all(near(x[1], want("cat", x[0])[0]) and x[2] == "" for x in groups), groups)
    t = table("m_bottom")
    lines = [(row[0]["t"], row[0]["b"], number(row[1]["t"])) for row in t[1:-1]]
    ok = True
    for g in sorted(regions):
        i = next((k for k, x in enumerate(lines) if x[0] == g), None)
        n = len({k[2] for k in agg if k[0] == "city" and k[1] == g})
        ok &= i is not None and lines[i][1] and lines[i][2] is None and lines[i + n + 1][0] == "Total" and near(lines[i + n + 1][2], want("region", g)[0])
    check("matrix: Row subtotal position Bottom - a Region's row has no values and a Total row follows its cities", ok, lines)
    mr = (o.get("mr_sentences") or {}).get("texts") or []
    vals = [x for x in mr if x["s"].startswith(("Revenue", "Margin", "Retail"))]
    print("  multi-row card:", [(x["s"], round(x["l"]), round(x["r"])) for x in vals], flush=True)
    apart = all(a["r"] <= b["l"] or b["r"] <= a["l"] or a["b"] <= b["t"] or b["b"] <= a["t"] for k, a in enumerate(vals) for b in vals[k + 1:])
    check("card: the multi-row card cuts each sentence with \"...\" inside its own place - no value runs into the next",
          len(vals) == 3 and apart and all(x["s"].endswith("...") and x["r"] <= o["mr_sentences"]["box"]["r"] for x in vals), vals)
    check("card: ... and marks each cut sentence for the Display check", [x["cut"] for x in vals] == S, [x["cut"] for x in vals])
    cv = o.get("cv_wrap") or {}
    lines = [x for x in cv.get("texts") or [] if x["s"]]
    inside = all(cv["box"]["l"] <= x["l"] and x["r"] <= cv["box"]["r"] + 1 and x["b"] <= cv["box"]["b"] + 1 for x in lines) if lines else False
    cols: dict = {}
    for x in sorted(lines, key=lambda x: (round(x["l"] / 50), x["t"])):
        cols.setdefault(round(x["l"] / 50), []).append(x["s"])
    check("card: the new card with value.textWrap shows the three sentences whole, over several lines, inside the visual",
          sorted(" ".join(v) for v in cols.values()) == sorted(S) and not any(x["cut"] for x in lines) and inside and len(lines) > 3,
          (cols, inside))
    check("ui: no script errors on the page", not o.get("errors") and not any((o.get(v) or {}).get("error") for v in o if v != "errors"), o.get("errors"))

# ---------------------------------------------------------------- the Display check and the DAX check (no Power BI engine here)
r = kit("""
import json
from pathlib import Path
from genbi_kit import catalog, daxcheck, definition, display, prototype, stock
from genbi_kit.data import connect
W = Path('__WORK__')                   # absolute: the kit's DuckDB reads its cache by absolute path only
g = display.check(W / 'prototype' / 'index.html')
dd = definition.expand(definition.load(W / 'definition.yaml'))
qs = {q['key'].split(' / ')[-1]: q['dax'] for q in daxcheck.queries(dd, catalog())}
con, cat = connect(W, dd), catalog()
v = next(v for p in dd['pages'] for v in p['visuals'] if v['id'] == 'm_expanded')
rows = [r for r in prototype.records(con, v['prototype']['sql']) if r['Category'] is not None and r['Product'] is not None]
same = [[r['Category'], r['Product'], r['Revenue'], r['Margin %']] for r in rows]
changed = [list(x) for x in same]
changed[0][3] += 0.2
diff = lambda dax: daxcheck.differences(dd, con, cat, {'queries': [{'key': 'visual:Item 52 / m_expanded', 'ok': True, 'rows': dax}]})
add = stock.additive_measures(dd['measures'])
print(json.dumps({'status': g['status'], 'items': [i['level'] + ' ' + i['text'] for i in g['items']],
                  'q': {k: qs[k] for k in ('m_collapsed', 'm_expanded')}, 'same': diff(same), 'changed': diff(changed),
                  'additive': sorted(k for k, x in add.items() if x and not k.startswith(('Insight', 'Margin Color')))}))
""".replace("__WORK__", WORK))
try:
    k = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    k = {}
if not check("gates: the Display and DAX checks ran on the Item 52 prototype", bool(k), (r.stdout + r.stderr)[-800:]):
    print((r.stdout + r.stderr)[-3000:], flush=True)
if k:
    cut = [i for i in k["items"] if "cut with" in i]
    check("display: the Display check fails the cut multi-row card - one item, saying what to do - and no other visual",
          len(cut) == 1 and cut[0].startswith("fail Item 52: Key insights (multi-row card) (mr_sentences): 3 text values cut")
          and "textWrap: true" in cut[0], k["items"])
    check("dax: Power BI is asked for the level a matrix opens at - Region alone, Category and Product with Auto expand",
          "SUMMARIZECOLUMNS ( 'Sales'[Region], TREATAS" in k["q"]["m_collapsed"] and "'Sales'[City]" not in k["q"]["m_collapsed"]
          and "SUMMARIZECOLUMNS ( 'Sales'[Category], 'Sales'[Product], TREATAS" in k["q"]["m_expanded"], k["q"])
    check("dax: two Rows levels are compared by position: the same numbers pass, a changed margin is reported for its product",
          k["same"] == [] and len(k["changed"]) == 1 and "[Margin %] for " in k["changed"][0], (k["same"], k["changed"]))
    check("dax: measures that add up are told from those that do not (distinct counts, ratios, averages)",
          k["additive"] == ["Cost", "Profit", "Revenue", "Revenue Change", "Revenue LY", "Revenue Target", "Units"], k["additive"])
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK, "/tmp/item52.png")

# ---------------------------------------------------------------- Ask Relay: a seeded answer with a growth rate by city
owner = c.Person(f"ana.ask@ask52{c.STAMP}.com")
s, r = owner.sign_in("Ask 52 Test", "Ana Ask")
check("ask: an organisation is set up", s == 200, (s, r))
owner.post("/api/me/tour", {"step": "done"})
owner.post("/api/org/setup")
me = owner.get("/api/me")[1]
CITIES = [("Bergen", 0.845, 194917.4), ("Warsaw", 0.497, 152170.2), ("Porto", 0.172, 162149.0), ("Madrid", -0.024, 176603.1),
          ("Oslo", -0.15, 144258.3), ("Lisbon", -0.166, 130307.7), ("Krakow", -0.163, 149054.0), ("Seville", -0.219, 131715.5)]
BODY = {"result": {"type": "chart", "headline": "Bergen grew fastest, up 84.5% on last year",
                   "chart": {"kind": "bar", "x": "city", "y": ["growth_pct"]}},
        "data": {"columns": ["city", "growth_pct", "revenue"], "row_count": 8, "limited": False,   # a stored answer keeps a decimal as text
                 "rows": [{"city": n, "growth_pct": str(g) if i % 2 else g, "revenue": v} for i, (n, g, v) in enumerate(CITIES)]},
        "summary": "Bergen and Warsaw grew fastest; Seville fell most.", "actions": [], "next_questions": [],
        "validation": {"queries": []}, "usage": {}}
seed = f"""
import json, time
from app import db
db.init_tenant({me['org']['id']!r})
with db.use({me['org']['id']!r}):
    db.run('INSERT INTO askd_threads (id, user_id, scope, title, created, updated) VALUES (?, ?, ?, ?, ?, ?)',
           ('t-item52{c.STAMP}', {me['id']!r}, json.dumps({{'kind': 'team'}}), 'Growth by city', time.time(), time.time()))
    db.run('INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, ?, ?, ?)',
           ('u-item52{c.STAMP}', 't-item52{c.STAMP}', 'user', json.dumps({{'text': 'Which cities grew fastest?'}}), time.time() - 1))
    db.run('INSERT INTO askd_messages (id, thread_id, role, body, created) VALUES (?, ?, ?, ?, ?)',
           ('a-item52{c.STAMP}', 't-item52{c.STAMP}', 'assistant', {json.dumps(json.dumps(BODY))}, time.time()))
from app import askd
html = askd.snapshot_html(json.loads({json.dumps(json.dumps(BODY))}), 'Which cities grew fastest?')
print(json.dumps({{'seeded': True, 'snapshot': html, 'prompt': 'return a percentage as a fraction' in askd.SYSTEM}}))
"""
r = subprocess.run(["docker", "exec", "-i", "-u", "relay", "-w", "/srv", c.WEB_C, "/opt/relay/bin/launch", "web", "python", "-"], input=seed,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "MSYS_NO_PATHCONV": "1"})
try:
    a = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    a = {}
check("ask: an answer with a growth rate by city is seeded", a.get("seeded") is True, (r.stdout[-300:], r.stderr[-600:]))
snap = a.get("snapshot") or ""
check("ask: the snapshot image labels the bars and the table in percent (84.5%, -21.9%), never 0.845",
      "84.5%" in snap and "-21.9%" in snap and ">0.845<" not in snap and "0.845" not in re.sub(r"<[^>]+>", " ", snap.split("<table")[-1]), snap[-1500:])
check("ask: the snapshot's revenue reads with separators (194,917.4), not as a raw float", "194,917.4" in snap, snap[-800:])
check("ask: the prompt asks for a percentage as a fraction in a pct-named column", a.get("prompt") is True, a)
UI = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie, tid = sys.argv[1], sys.argv[2]
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:8000/#/askd/{tid}")
    page.wait_for_selector(".achart svg", timeout=20000)
    page.wait_for_timeout(800)
    out["chips"] = page.locator(".akpi").all_inner_texts()
    out["foot"] = page.locator(".awfoot").first.inner_text()
    out["svg"] = page.locator(".achart svg text").all_text_contents()
    page.locator(".achart").first.screenshot(path="/tmp/item52-ask.png")
    page.click(".atools button:text-is('Table')")
    page.wait_for_timeout(500)
    out["table"] = page.locator(".achart .utable td.n").all_text_contents()
    page.click("summary:has-text('See the numbers')")
    page.wait_for_timeout(300)
    out["numbers"] = page.locator("details.more .dprev table tr").nth(1).locator("td").all_text_contents()
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
cookie = next(x.value for x in owner.jar if x.name == "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie, f"t-item52{c.STAMP}"], input=UI, capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=240)
try:
    u = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    u = {}
if not check("ask: the conversation opens with its chart", bool(u), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item52-ask.png", c.out_path("item52-ask.png")], check=False)
if u:
    print("  ask:", json.dumps({k: u[k] for k in ("chips", "foot", "table", "numbers")}), flush=True)
    avg = f"{sum(g for _, g, _ in CITIES) / len(CITIES) * 100:.1f}%"
    check(f"ask: the growth chip reads as a percentage average (Growth Pct avg {avg}), not a plain decimal",
          len(u["chips"]) == 1 and re.sub(r"\s+", " ", u["chips"][0]).strip() == f"Growth Pct avg {avg}", (u["chips"], avg))
    check("ask: the count says \"8 cities\", not \"8 citys\"", u["foot"].startswith("8 cities - 8 of 8 rows"), u["foot"])
    ticks = [x for x in u["svg"] if re.fullmatch(r"-?[\d.,]+%", x)]
    check("ask: the axis and the bars' labels are percentages (84.5% on Bergen's bar, ticks like 50%)",
          "84.5%" in u["svg"] and "-21.9%" in u["svg"] and len(ticks) >= 12 and "0.845" not in u["svg"], u["svg"])
    check("ask: the Table view shows 84.5% (two decimals at most), the stored text values too",
          u["table"][:2] == ["84.5%", "49.7%"] and "-21.9%" in u["table"], u["table"])
    check("ask: \"See the numbers\" shows the rate in percent as well", u["numbers"][:2] == ["Bergen", "84.5%"], u["numbers"])
    check("ask: no script errors", not u.get("errors"), u.get("errors"))

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
