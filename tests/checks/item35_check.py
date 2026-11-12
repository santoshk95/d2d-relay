"""Test stack only (the web container; nothing is signed in): item 35 (2026-11-12), the labels the end-to-end run of
item 34 showed wrong. The app's own prototype of the Power BI built-in visuals gallery (genbi_kit/examples/
stock_gallery.yaml, data samples/*.csv) plus a "Labels" page with the three cases, drawn by the image's `genbi
prototype` and looked at in Chromium:
- Power BI's own visuals (the prototype's stand-in renderer): no text runs past its visual's edge on any page; the
  longest bar's label goes inside the bar's end when the plot has no room after it (Power BI's Auto position);
- Relay Compare's dumbbell of two percentages labels the change in points, not a relative %;
- Relay Finance's waterfall with labels fixed to millions shows its small steps in their own unit, never $0M;
- the image ships the rebuilt Atlas visuals.
python -I -X utf8 item35_check.py <public> <admin>"""
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
WORK = "/tmp/item35"
LABELS_PAGE = {"name": "Labels", "rows": [
    {"height": 300, "visuals": [
        {"id": "lb_bars", "type": "pbi.clusteredBarChart", "span": 6, "title": "Revenue by category",
         "fields": {"axis": "Sales[Category]", "values": "[Revenue]"}, "format": {"labels": {"show": True}},
         "prototype": {"sql": "SELECT * FROM (VALUES ('Bikes', 4778000.0), ('Components', 926000.0), ('Clothing', 305000.0), "
                              "('Accessories', 75000.0)) t(\"Category\", \"Revenue\")"}},
        {"id": "lb_dumbbell", "type": "atlasCompare", "chart": "dumbbell", "span": 6, "title": "Margin vs target margin",
         "fields": {"category": "Sales[Category]", "values": ["[Margin %]", "[Target Margin %]"]}, "format": {"labels": {"show": True}},
         "prototype": {"sql": "SELECT * FROM (VALUES ('Accessories', 0.256, -0.096), ('Components', 0.231, -0.089), "
                              "('Clothing', 0.27, -0.103), ('Bikes', 0.249, -0.111)) t(\"Category\", \"Margin %\", \"Target Margin %\")"}}]},
    {"height": 300, "visuals": [
        {"id": "lb_waterfall", "type": "atlasFinance", "chart": "waterfall", "span": 12, "title": "Revenue bridge, labels fixed to millions",
         "fields": {"category": "Sales[Category]", "values": "[Revenue Change]"},
         "format": {"labels": {"show": True, "displayUnits": 1000000, "decimals": 0}, "waterfall": {"startTotal": True, "endLabel": "This year"}},
         "prototype": {"sql": "SELECT * FROM (VALUES ('Last year', 5910000.0), ('Bikes', 240000.0), ('Components', -59000.0), "
                              "('Clothing', 15000.0), ('Accessories', 33000.0), ('Other', -4000.0)) t(\"Category\", \"Revenue Change\")"}}]}]}


def docker(*args: str, input_text: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input_text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


# ---------------------------------------------------------------- the gallery's prototype, with the Labels page
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK)
docker("exec", "-u", "agent", c.WEB_C, "mkdir", "-p", WORK + "/data")
for f in ("sales.csv", "products.csv"):
    docker("cp", os.path.join(REPO, "samples", f), f"{c.WEB_C}:{WORK}/data/{f}")
make = ("import json, yaml\n"
        "d = yaml.safe_load(open('/opt/genbi/genbi_kit/examples/stock_gallery.yaml', encoding='utf-8'))\n"
        f"d['pages'].append(json.loads({json.dumps(json.dumps(LABELS_PAGE))}))\n"
        f"open('{WORK}/definition.yaml', 'w', encoding='utf-8').write(yaml.safe_dump(d, sort_keys=False, allow_unicode=True))\n"
        f"open('{WORK}/request.md', 'w', encoding='utf-8').write('# request\\nThe labels check of item 35.\\n')\n"
        "print(len(d['pages']), 'pages')\n")
r = docker("exec", "-i", "-u", "agent", "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-", input_text=make)
check("setup: the gallery definition with the Labels page is written", r.stdout.strip().endswith("pages"), (r.stdout + r.stderr)[-400:])
r = docker("exec", "-u", "agent", "-w", WORK, "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "genbi", "prototype", timeout=600)
out = (r.stdout + r.stderr).strip()
check("prototype: genbi draws every visual of the gallery and the Labels page from the data", r.returncode == 0 and "wrote prototype/index.html" in out
      and "need attention" not in out, out[-800:])

# ---------------------------------------------------------------- what the browser shows
PLAY = r"""
import json
from playwright.sync_api import sync_playwright
out = {"pages": [], "overflow": [], "labels": {}}
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file:///tmp/item35/prototype/index.html")
    page.wait_for_timeout(1500)
    n = page.evaluate("R.pages.length")
    for i in range(n):
        page.evaluate(f"current = {i}; draw();")
        page.wait_for_timeout(700)
        name = page.evaluate("R.pages[current].name")
        out["pages"].append(name)
        out["overflow"] += page.evaluate('''(name) => {
          const vs = R.pages[current].visuals, boxes = [...document.querySelectorAll('#page > .v')], bad = [];
          boxes.forEach((box, k) => {
            const v = vs[k]; if (!v || !v.stock) return;
            const r = box.getBoundingClientRect();
            box.querySelectorAll('svg text').forEach(t => { const q = t.getBoundingClientRect(); if (!q.width) return;
              const over = Math.max(q.right - r.right, r.left - q.left, q.bottom - r.bottom, r.top - q.top);
              if (over > 1) bad.push([name, v.id, t.textContent, Math.round(over)]); });
          });
          return bad; }''', name)
        if name == "Labels":
            out["labels"] = page.evaluate('''() => {
              const vs = R.pages[current].visuals, boxes = [...document.querySelectorAll('#page > .v')], o = {};
              boxes.forEach((box, k) => { const v = vs[k]; if (!v) return;
                o[v.id] = [...box.querySelectorAll('svg text')].map(t => { const q = t.getBoundingClientRect(), r = box.getBoundingClientRect();
                  return {text: t.textContent, x: Math.round(q.left - r.left), right: Math.round(r.right - q.right), fill: t.getAttribute('fill') || ''}; });
                if (v.id === 'lb_bars') o.bars_rects = [...box.querySelectorAll('svg rect')].map(e => { const q = e.getBoundingClientRect(), r = box.getBoundingClientRect();
                  return [Math.round(q.left - r.left), Math.round(q.right - r.left), Math.round(q.width), Math.round(q.height)]; })
                  .filter(x => x[2] > 0 && x[3] > 0 && x[3] < 80);          // the bars (not a background)
              });
              return o; }''')
            page.screenshot(path="/tmp/item35-labels.png", full_page=True)
    out["errors"] = errors
    b.close()
print(json.dumps(out))
"""
res = docker("exec", "-i", c.WEB_C, "python3", "-", input_text=PLAY, timeout=300)
try:
    o = json.loads(res.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    o = {}
if not check("browser: the prototype opens and every page is drawn", bool(o) and "Labels" in o.get("pages", []), res.stderr[-600:]):
    print(res.stderr[-3000:], flush=True)
if o:
    check(f"stock labels: no text of Power BI's own visuals runs past its visual's edge ({len(o['pages'])} pages)", not o["overflow"], o["overflow"][:8])
    lab = o["labels"]
    bars = [t for t in lab.get("lb_bars", []) if "4" in t["text"] and ("M" in t["text"] or "K" in t["text"]) and "7" in t["text"]]
    widest = max((r for r in lab.get("bars_rects", [])), key=lambda r: r[2], default=None)
    check("stock labels: the longest bar's label sits inside the end of its bar (no room after it)",
          bool(bars) and widest is not None and widest[0] <= bars[0]["x"] and bars[0]["x"] + 5 < widest[1], (bars, widest))
    dumb = [t["text"] for t in lab.get("lb_dumbbell", []) if t["text"].endswith("pts")]
    check("atlas: the dumbbell of two percentages labels each change in points (-35 pts, not -140%)",
          sorted(dumb) == sorted(["-35 pts", "-32 pts", "-37 pts", "-36 pts"]) and not any(re.match(r"^[+-]\d{3,}%$", t["text"]) for t in lab.get("lb_dumbbell", [])),
          [t["text"] for t in lab.get("lb_dumbbell", [])])
    wf = [t["text"] for t in lab.get("lb_waterfall", [])]
    check("atlas: the waterfall fixed to millions shows small steps in their own unit (+$240K, -$4K), never $0M",
          all(s in wf for s in ("+$240K", "-$59K", "+$15K", "+$33K", "-$4K")) and not any(s.endswith("$0M") for s in wf), wf)
    check("ui: no script errors", not o.get("errors"), o.get("errors"))
subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/item35-labels.png", c.out_path("item35-labels.png")], check=False)

# ---------------------------------------------------------------- the rebuilt visuals are the ones shipped
r = docker("exec", "-i", "-u", "agent", "-e", "PYTHONPATH=/opt/genbi", c.WEB_C, "/usr/local/bin/python3", "-P", "-", input_text=(
    "import json\nfrom genbi_kit import atlas\n"
    "print(json.dumps({k: v.get('version') for k, v in atlas.catalog().items() if k in ('atlasCompare', 'atlasFinance', 'atlasColumns')}))\n"))
try:
    vers = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    vers = {"error": (r.stdout + r.stderr)[-300:]}
check("atlas: the image ships the rebuilt visuals (Compare 1.0.7.0, Finance 1.0.7.0, Columns 1.0.9.0)",
      vers == {"atlasCompare": "1.0.7.0", "atlasFinance": "1.0.7.0", "atlasColumns": "1.0.9.0"}, vers)
docker("exec", "-u", "root", c.WEB_C, "rm", "-rf", WORK, "/tmp/item35-labels.png")

bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
