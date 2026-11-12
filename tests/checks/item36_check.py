"""Test stack only (the web container; nothing is signed in): item 36 (2026-11-12), what item 35's end-to-end run showed
next. The built-in visuals gallery (genbi_kit/examples/stock_gallery.yaml, data samples/*.csv) plus an "Item 36" page,
drawn by the image's `genbi prototype` and looked at in Chromium:
- Relay Gauges KPI tiles under a title and subtitle (low tiles, as in the AI's reports): the name never runs into the
  value ("Revenue Growth %+11.3%"); a medium name stays whole with the value beside it, a long one is shortened, and
  the value keeps a readable size;
- a visual whose title is a measure: with a "title" column in its prototype SQL the prototype shows that sentence;
  without one `genbi prototype` reports it and the prototype shows a readable stand-in ("Revenue Trend", not the
  measure's name "Title Revenue Trend");
- the image ships Relay Gauges 1.0.7.0.
python -I -X utf8 item36_check.py <public> <admin>"""
import json
import os
import subprocess
import sys

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d2d_checks as c  # noqa: E402

check = c.check
REPO = os.path.dirname(os.path.dirname(HERE))
WORK = "/tmp/item36"
SENTENCE = "Revenue is up 5.6% on last year"
MEASURES = [
    {"name": "Average selling price per order", "format": "\\$#,0.00", "folder": "Item 36", "expression": "DIVIDE ( [Revenue], [Units] )"},
    {"name": "Revenue Growth %", "format": "+0.0%;-0.0%;0.0%", "folder": "Item 36", "expression": "[Revenue vs LY %]"},
    {"name": "Title Revenue Trend", "folder": "Item 36", "expression": f"\"{SENTENCE}\""},
]
MONTHS = ("SELECT CAST(DATE '2026-01-01' + INTERVAL (i) MONTH AS DATE) AS \"Order Date\", {value} AS \"{field}\", {target} AS \"{tfield}\" "
          "FROM range(10) t(i) ORDER BY 1")
KPI = lambda vid, title, value, target, sql_value, sql_target: {  # noqa: E731 - one KPI tile under a title and subtitle, as the AI lays them out
    "id": vid, "type": "atlasGauges", "chart": "kpi", "span": 3, "title": title, "subtitle": "Latest month vs same month last year",
    "fields": {"trend": "Sales[Order Date]", "values": f"[{value}]", "target": f"[{target}]"},
    "prototype": {"sql": MONTHS.format(value=sql_value, field=value, target=sql_target, tfield=target)}}
PAGE = {"name": "Item 36", "rows": [
    {"height": 150, "visuals": [                             # four tiles a row, about 280 px each, as in the AI's reports
        KPI("kp_long", "Selling price", "Average selling price per order", "Avg Order Value", "290 + i * 2.5", "290.0"),
        KPI("kp_med", "Revenue growth", "Revenue Growth %", "Target Margin %", "0.08 + i * 0.0035", "0.1"),
        KPI("kp_med2", "Average price", "Avg Order Value", "Average selling price per order", "300 + i * 1.2", "296.12"),
        KPI("kp_short", "Units", "Units", "Orders", "1800 + i * 18", "1850")]},
    {"height": 260, "visuals": [
        {"id": "tt_none", "type": "pbi.lineChart", "span": 6, "title": "[Title Revenue Trend]", "subtitle": "Revenue by month",
         "fields": {"axis": "Sales[Order Date]", "values": "[Revenue]"},
         "prototype": {"sql": "SELECT CAST(DATE '2026-01-01' + INTERVAL (i) MONTH AS DATE) AS \"Order Date\", 500000 + i * 9000 AS \"Revenue\" FROM range(10) t(i) ORDER BY 1"}},
        {"id": "tt_ok", "type": "pbi.clusteredColumnChart", "span": 6, "title": "[Title Revenue Trend]", "subtitle": "Revenue by region",
         "fields": {"axis": "Sales[Region]", "values": "[Revenue]"},
         "prototype": {"sql": f"SELECT * FROM (VALUES ('North', 1660000.0, '{SENTENCE}'), ('South', 1300000.0, '{SENTENCE}')) t(\"Region\", \"Revenue\", \"title\")"}}]}]}


def docker(*args: str, input_text: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


# ---------------------------------------------------------------- the gallery's prototype, with the Item 36 page
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK)
docker("exec", "-u", "agent", c.WEB_C, "mkdir", "-p", WORK + "/data")
for f in ("sales.csv", "products.csv"):
    docker("cp", os.path.join(REPO, "samples", f), f"{c.WEB_C}:{WORK}/data/{f}")
make = ("import json, yaml\n"
        "d = yaml.safe_load(open('/opt/genbi/genbi_kit/examples/stock_gallery.yaml', encoding='utf-8'))\n"
        f"d['measures'] += json.loads({json.dumps(json.dumps(MEASURES))})\n"
        f"d['pages'].append(json.loads({json.dumps(json.dumps(PAGE))}))\n"
        f"open('{WORK}/definition.yaml', 'w', encoding='utf-8').write(yaml.safe_dump(d, sort_keys=False, allow_unicode=True))\n"
        f"open('{WORK}/request.md', 'w', encoding='utf-8').write('# request\\nThe check of item 36.\\n')\n"
        "print(len(d['pages']), 'pages')\n")
r = docker("exec", "-i", "-u", "agent", "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-", input_text=make)
check("setup: the gallery definition with the Item 36 page is written", r.stdout.strip().endswith("pages"), (r.stdout + r.stderr)[-400:])
r = docker("exec", "-u", "agent", "-w", WORK, "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "genbi", "prototype", timeout=600)
out = (r.stdout + r.stderr).strip()
problems = [ln.strip() for ln in out.splitlines() if " / " in ln and "(" in ln]
check("prototype: genbi draws the gallery and the Item 36 page", "wrote prototype/index.html" in out, out[-600:])
check("titles: a measure title without a \"title\" column in the prototype SQL is reported to the agent (and only that)",
      len(problems) == 1 and "tt_none" in problems[0] and "[Title Revenue Trend]" in problems[0] and "\"title\" column" in problems[0], problems or out[-500:])

# ---------------------------------------------------------------- what the browser shows
PLAY = r"""
import json
from playwright.sync_api import sync_playwright
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file:///tmp/item36/prototype/index.html")
    page.wait_for_timeout(1500)
    i = page.evaluate("R.pages.findIndex(p => p.name === 'Item 36')")
    page.evaluate(f"current = {i}; draw();")
    page.wait_for_timeout(1500)
    out = page.evaluate('''() => {
      const vs = R.pages[current].visuals, boxes = [...document.querySelectorAll('#page > .v')], o = {titles: {}, kpi: {}};
      boxes.forEach((box, k) => { const v = vs[k]; if (!v) return;
        o.titles[v.id] = v.header ? v.header.title : null;
        if (v.id.startsWith('kp_')) o.kpi[v.id] = [...box.querySelectorAll('text.ttl')].map(t => { const r = t.getBoundingClientRect();
          return {s: t.textContent, fs: +t.getAttribute('font-size'), l: r.left, r: r.right, t: r.top, b: r.bottom}; });
      });
      return o; }''')
    page.screenshot(path="/tmp/item36.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
res = docker("exec", "-i", c.WEB_C, "python3", "-", input_text=PLAY, timeout=300)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("browser: the prototype opens on the Item 36 page", bool(o.get("titles")), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)


def kpi(vid: str, name_start: str) -> dict:
    t = (o.get("kpi") or {}).get(vid) or []
    n = next((x for x in t if x["s"].startswith(name_start)), None)
    v = next((x for x in t if x is not n and x["s"][:1] in "$+-0123456789"), None)
    if not (n and v):
        return {"missing": t}
    apart = n["r"] <= v["l"] + 1 or v["r"] <= n["l"] + 1 or n["b"] <= v["t"] + 1 or v["b"] <= n["t"] + 1
    return {"name": n["s"], "value": v["s"], "valueSize": v["fs"], "apart": apart}


if o:
    tiles = {vid: kpi(vid, start) for vid, start in (("kp_long", "Average"), ("kp_med", "Revenue Growth"), ("kp_med2", "Avg Order"), ("kp_short", "Units"))}
    print("  kpi tiles:", json.dumps(tiles), flush=True)
    check("kpi: in all four low tiles the name stays clear of the value, which keeps 14px or more",
          all(t.get("apart") is True and t.get("valueSize", 0) >= 14 for t in tiles.values()), tiles)
    check("kpi: medium names stay whole (Revenue Growth %, Avg Order Value), their values at 18px or more",
          all(tiles[k].get("name") == n and tiles[k].get("valueSize", 0) >= 18 for k, n in (("kp_med", "Revenue Growth %"), ("kp_med2", "Avg Order Value"))), tiles)
    check("titles: with a \"title\" column the prototype shows the sentence", o["titles"].get("tt_ok") == SENTENCE, o["titles"])
    check("titles: without one it shows a readable stand-in (\"Revenue Trend\", not \"Title Revenue Trend\")", o["titles"].get("tt_none") == "Revenue Trend", o["titles"])
    check("ui: no script errors", not o.get("errors"), o.get("errors"))
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item36.png", c.out_path("item36.png")], check=False)

r = docker("exec", "-i", "-u", "agent", "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-", input_text=(
    "from genbi_kit import atlas\nprint(atlas.catalog()['atlasGauges'].get('version'))\n"))
check("kpi: the image ships Relay Gauges 1.0.7.0", r.stdout.strip() == "1.0.7.0", (r.stdout + r.stderr)[-200:])
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK, "/tmp/item36.png")

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
