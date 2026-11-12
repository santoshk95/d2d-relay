"""Test stack only (the web container; nothing is signed in): item 37 (2026-11-12), what item 36's end-to-end run
showed next. The built-in visuals gallery (genbi_kit/examples/stock_gallery.yaml, data samples/*.csv) plus an "Item 37"
page, drawn by the image's `genbi prototype` and looked at in Chromium:
- a Relay Hierarchy sunburst with the thin slices of the AI's sales report (category > channel, name and percent:
  Clothing 4.9%, Accessories 3.7%, their channels 2.5% and less): no label on another, every label inside its own
  slice, and the big slices still labelled;
- the same sunburst in a small tile;
- the image ships Relay Hierarchy 1.0.7.0.
python -I -X utf8 item37_check.py <public> <admin>"""
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
WORK = "/tmp/item37"
ROWS = [("Bikes", "Online", 2430), ("Bikes", "Retail", 2310), ("Components", "Online", 474), ("Components", "Retail", 449),
        ("Clothing", "Online", 156), ("Clothing", "Retail", 150), ("Accessories", "Online", 118), ("Accessories", "Retail", 112)]
SQL = ("SELECT * FROM (VALUES " + ", ".join(f"('{a}', '{b}', {v * 1000}.0)" for a, b, v in ROWS)
       + ") t(\"Category\", \"Channel\", \"Revenue\")")
SUN = lambda vid, span, title: {  # noqa: E731 - a sunburst as the AI lays it out: name and percent on each slice
    "id": vid, "type": "atlasHierarchy", "chart": "sunburst", "span": span, "title": title,
    "subtitle": "Revenue by category (inner ring) and channel (outer ring)",
    "fields": {"levels": ["Sales[Category]", "Sales[Channel]"], "values": "[Revenue]"},
    "format": {"chart": {"content": "namePercent"}}, "prototype": {"sql": SQL}}
PAGE = {"name": "Item 37", "rows": [
    {"height": 312, "visuals": [SUN("sb_wide", 6, "Bikes are 77% of revenue; online sells 52% of it")]},
    {"height": 220, "visuals": [SUN("sb_small", 3, "Revenue mix")]}]}


def docker(*args: str, input_text: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


# ---------------------------------------------------------------- the gallery's prototype, with the Item 37 page
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK)
docker("exec", "-u", "agent", c.WEB_C, "mkdir", "-p", WORK + "/data")
for f in ("sales.csv", "products.csv"):
    docker("cp", os.path.join(REPO, "samples", f), f"{c.WEB_C}:{WORK}/data/{f}")
make = ("import json, yaml\n"
        "d = yaml.safe_load(open('/opt/genbi/genbi_kit/examples/stock_gallery.yaml', encoding='utf-8'))\n"
        f"d['pages'].append(json.loads({json.dumps(json.dumps(PAGE))}))\n"
        f"open('{WORK}/definition.yaml', 'w', encoding='utf-8').write(yaml.safe_dump(d, sort_keys=False, allow_unicode=True))\n"
        f"open('{WORK}/request.md', 'w', encoding='utf-8').write('# request\\nThe check of item 37.\\n')\n"
        "print(len(d['pages']), 'pages')\n")
r = docker("exec", "-i", "-u", "agent", "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-", input_text=make)
check("setup: the gallery definition with the Item 37 page is written", r.stdout.strip().endswith("pages"), (r.stdout + r.stderr)[-400:])
r = docker("exec", "-u", "agent", "-w", WORK, "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "genbi", "prototype", timeout=600)
out = (r.stdout + r.stderr).strip()
problems = [ln.strip() for ln in out.splitlines() if " / " in ln and "(" in ln]
check("prototype: genbi draws the gallery and the Item 37 page, with no problem reported", "wrote prototype/index.html" in out and not problems,
      problems or out[-600:])

# ---------------------------------------------------------------- what the browser shows
PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
SUN = json.loads(sys.stdin.readline())
out = {}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file:///tmp/item37/prototype/index.html")
    page.wait_for_timeout(1500)
    i = page.evaluate("R.pages.findIndex(p => p.name === 'Item 37')")
    page.evaluate(f"current = {i}; draw();")
    page.wait_for_timeout(1500)
    out = page.evaluate("() => { const sun = " + SUN + ";" + '''
      const vs = R.pages[current].visuals, boxes = [...document.querySelectorAll('#page > .v')], o = {};
      boxes.forEach((box, k) => { const v = vs[k]; if (v && v.id.startsWith('sb_')) o[v.id] = sun(box); });
      return o; }''')
    page.screenshot(path="/tmp/item37.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
res = docker("exec", "-i", c.WEB_C, "python3", "-c", PLAY, input_text=json.dumps(c.SUNBURST_JS) + "\n", timeout=300)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("browser: the prototype opens on the Item 37 page with both sunbursts", bool(o.get("sb_wide")) and bool(o.get("sb_small")), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)

if o.get("sb_wide") and o.get("sb_small"):
    print("  sunburst labels:", json.dumps({k: o[k] for k in ("sb_wide", "sb_small")}, ensure_ascii=False), flush=True)
    for vid, what in (("sb_wide", "the report's sunburst"), ("sb_small", "in a small tile")):
        x = o[vid]
        check(f"sunburst ({what}): no label lies on another", x["labels"] and not x["over"], x)
        check(f"sunburst ({what}): every label stays inside its own slice", x["labels"] and not x["outside"], x)
    shown = o["sb_wide"]["labels"]
    check("sunburst: the big slices keep their labels (Bikes and its two channels with their percent, Components)",
          all(any(re.match(p, s) for s in shown) for p in (r"^Bikes \d+%$", r"^Comp\S*( 1\d%)?$"))
          and len([s for s in shown if re.match(r"^(Online|Retail) 3\d%$", s)]) == 2, shown)
    check("ui: no script errors", not o.get("errors"), o.get("errors"))
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item37.png", c.out_path("item37.png")], check=False)

r = docker("exec", "-i", "-u", "agent", "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-", input_text=(
    "from genbi_kit import atlas\nprint(atlas.catalog()['atlasHierarchy'].get('version'))\n"))
check("sunburst: the image ships Relay Hierarchy 1.0.7.0", r.stdout.strip() == "1.0.7.0", (r.stdout + r.stderr)[-200:])
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK, "/tmp/item37.png")

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
