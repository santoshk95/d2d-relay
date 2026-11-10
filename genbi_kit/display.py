"""Display check: draw every page of a prototype in headless Chromium and read back what each visual shows.

Fails on script errors, visuals that could not draw, and labels no business user should see — NaN, undefined,
∞, [object …], doubled display units ($2.95BM). Warns on unformatted numbers, values cut off by their card and
visuals that draw nothing. Runs where Playwright is installed (the agent image): `genbi gates` and the agent
service's POST /display-check, which the app calls for every version and before publishing.
"""
import re
from pathlib import Path

from .gates import fail, gate, warn

BROKEN = [(re.compile(r"\bNaN\b"), "shows NaN"), (re.compile(r"\bundefined\b"), 'shows "undefined"'),
          (re.compile(r"\bInfinity\b|∞"), "shows ∞ (a division by zero?)"), (re.compile(r"\[object \w+\]"), "shows [object …]"),
          (re.compile(r"\d(?:[KMB]|bn)\s?[KMB]\b"), "shows doubled display units")]
RAW = re.compile(r"(?<![\w.,])-?\d+\.\d{5,}(?![\d])")

READ = r"""async () => {
  if (typeof R === 'undefined' || typeof draw !== 'function') return {error: 'this file is not a Gen BI prototype'};
  const out = [];
  for (let i = 0; i < R.pages.length; i++) {
    let err = null;
    try { current = i; draw(); } catch (e) { err = String((e && e.message) || e); }
    await new Promise(r => setTimeout(r, 150));
    const boxes = [...document.querySelectorAll('#page > .v')];
    out.push({page: R.pages[i].name, error: err, visuals: R.pages[i].visuals.map((v, k) => {
      const b = boxes[k];
      const name = (v.header && v.header.title) || (v.model && (v.model.label || v.model.heading)) || v.label || v.id;
      if (!b) return {id: v.id, name, type: v.type, missing: true};
      const svgText = [...b.querySelectorAll('svg text')].map(t => t.textContent).join(' ');
      return {id: v.id, name, type: v.type, text: ((b.innerText || '') + ' ' + svgText).slice(0, 6000),
              marks: b.querySelectorAll('svg path, svg rect, svg circle, svg line, svg polygon, svg polyline, canvas, img, td').length,
              clipped: [...b.querySelectorAll('.gb-kpi-value')].some(e => e.scrollWidth > e.clientWidth + 1),
              overflow: b.scrollWidth > b.clientWidth + 6 || b.scrollHeight > b.clientHeight + 6,
              failed: !!b.querySelector('.aerr'), queryFailed: !!b.querySelector('.err'),
              data: !!(v.model || v.atlas)};
    })});
  }
  return {pages: out};
}"""

SKIP = {"pageNavigator", "slicer", "textbox"}


def check(html: Path, timeout_s: int = 120) -> dict:
    """The display gate for one prototype HTML file."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return gate("display", skip="no headless browser here (Playwright is in the agent image)")
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1320, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(Path(html).resolve().as_uri(), wait_until="load", timeout=timeout_s * 1000)
            res = page.evaluate(READ)
        finally:
            browser.close()
    if res.get("error"):
        return gate("display", skip=res["error"])
    items, n_vis = [], 0
    for e in dict.fromkeys(errors):
        items.append(fail(f"script error while drawing: {e[:300]}"))
    for pg in res["pages"]:
        if pg["error"]:
            items.append(fail(f"{pg['page']}: drawing the page stopped — {pg['error'][:300]}"))
        for v in pg["visuals"]:
            if v["type"] in SKIP:
                continue
            n_vis += 1
            where = f"{pg['page']}: {v['name']} ({v['id']})"
            if v.get("missing"):
                items.append(fail(f"{where} was not drawn"))
                continue
            if v["failed"]:
                items.append(fail(f"{where} could not draw: {v['text'].strip()[:200]}"))
                continue
            if v["queryFailed"]:
                continue                                    # the prototype gate reports failed queries
            for rx, what in BROKEN:
                m = rx.search(v["text"])
                if m:
                    ctx = v["text"][max(0, m.start() - 30):m.end() + 30].replace("\n", " ").strip()
                    items.append(fail(f"{where} {what}: \"…{ctx}…\""))
            raw = RAW.search(v["text"])
            if raw:
                items.append(warn(f"{where} shows an unformatted number ({raw.group(0)}) — give the measure a format string"))
            if v["clipped"]:
                items.append(warn(f"{where}: the value is cut off — the card is too narrow for it"))
            elif v["overflow"] and v["type"] != "table":
                items.append(warn(f"{where}: its content spills out of its box"))
            if v["data"] and not v["marks"] and not v["text"].strip():
                items.append(warn(f"{where} draws nothing"))
    return gate("display", items, ok=f"{len(res['pages'])} pages and {n_vis} visuals drawn — no broken labels")
