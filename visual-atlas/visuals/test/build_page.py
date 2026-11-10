"""Wrap a packaged visual's bundle and a set of test cases into one HTML page.

usage: build_page.py <name> <bundle.js> <bundle.css> <cases.js>   ->  test/out/<name>.html
The page loads host.js (the mock Power BI host), the visual bundle, data.json and the cases.
"""
import pathlib
import sys

here = pathlib.Path(__file__).resolve().parent
name, js, css, cases = sys.argv[1:5]
read = lambda p: pathlib.Path(p).read_text(encoding="utf-8")
html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{name}</title>
<style>body{{margin:0;padding:16px;background:#f3f2f1;font:12px 'Segoe UI',Arial,sans-serif}}#cases{{display:grid;grid-template-columns:repeat(2,max-content);gap:14px}}
.case{{background:#fff;border:1px solid #e1dfdd;border-radius:6px;padding:8px}}.case .cap{{font-weight:600;margin-bottom:6px;color:#252423}}.vbox{{position:relative;background:#fff}}.vbox.dark{{background:#1f1f1f}}
{read(css)}</style></head><body><div id="cases"></div>
<script>{read(here / 'host.js')}</script><script>{read(js)}</script>
<script>window.DATA={read(here / 'data.json')};</script><script>{read(cases)}</script></body></html>"""
out = here / "out"
out.mkdir(exist_ok=True)
(out / f"{name}.html").write_text(html, encoding="utf-8")
print("wrote", out / f"{name}.html", len(html))
