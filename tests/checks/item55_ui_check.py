"""Test stack only: item 55's screens in a real browser (headless Chromium inside the test web container).

python -I item55_ui_check.py <public> <admin>
Semantic Review in the menu; a new review from two files chosen with the file picker; the report (findings with the
KPI that is calculated two ways, the KPI table, the measures, the models); the KPI dictionary and its Add dialog; a
phone-width page without sideways scrolling; dark mode; no script errors. Screenshots go to the run's folder:
sr-home.png, sr-report.png, sr-kpis-tab.png, sr-dictionary.png, sr-add-kpi.png, sr-phone.png, sr-dark.png.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import d2d_checks as c  # noqa: E402
import review_models as t54  # noqa: E402

PLAY = r"""
import json, sys
from playwright.sync_api import sync_playwright
cookie = sys.argv[1]
out = {"errors": []}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    page = ctx.new_page()
    page.on("pageerror", lambda e: out["errors"].append(str(e)[:300]))
    # failed requests, except the shell's /api/workspace (switched off in D2D Relay on every page, edition.py)
    page.on("response", lambda r: out["errors"].append(f"{r.status} {r.url}") if r.status >= 400 and "/api/workspace" not in r.url else None)
    page.goto("http://127.0.0.1:8000/#/d2d")
    page.wait_for_timeout(2500)
    out["menu"] = page.locator("#nav a[href='#/review']").inner_text()
    page.click("#nav a[href='#/review']")
    page.wait_for_selector("text=One KPI, one meaning, one value", timeout=20000)
    out["home_text"] = page.locator("#main").inner_text()[:1500]
    page.screenshot(path="/tmp/sr-home.png", full_page=True)
    page.set_input_files(".drop input[type=file]", ["/tmp/sr54/Sales model.bim", "/tmp/sr54/Finance.pbit"])
    out["picked"] = page.locator(".flist.attached").inner_text()
    page.fill("input[placeholder^='For example: Sales and Finance']", "Browser review")
    page.click("button:has-text('Start review')")
    page.wait_for_function("location.hash.startsWith('#/review/sr-')", timeout=30000)
    page.wait_for_selector("text=Findings (", timeout=90000)
    page.wait_for_timeout(500)
    out["report_text"] = page.locator("#main").inner_text()[:4000]
    page.screenshot(path="/tmp/sr-report.png", full_page=True)
    page.click("button.chip:has-text('High')")
    out["high_cards"] = page.locator(".srfind").count()
    out["high_all_high"] = page.locator(".srfind:not(.sev-high)").count() == 0
    first = page.locator(".srfind").first
    if first.locator("button:has-text('Show the DAX')").count():
        first.locator("button:has-text('Show the DAX')").click()
        out["dax_shown"] = first.locator("pre.srdax").first.is_visible()
    page.click(".tabs a:has-text('KPIs')")
    page.wait_for_selector(".srtable", timeout=10000)
    out["kpi_tab"] = page.locator("#main .srtable").inner_text()[:1500]
    page.screenshot(path="/tmp/sr-kpis-tab.png", full_page=True)
    page.click(".tabs a:has-text('Measures')")
    out["measure_rows"] = page.locator("#main .srtable tbody tr").count()
    page.click(".tabs a:has-text('Models')")
    out["models_text"] = page.locator(".srmodels").inner_text()[:600]
    page.evaluate("location.hash = '#/review/kpis'")
    page.wait_for_selector("h1:has-text('KPI dictionary')", timeout=15000)
    out["dict_rows"] = page.locator("#main .srtable tbody tr").count()
    page.screenshot(path="/tmp/sr-dictionary.png", full_page=True)
    page.click("button:has-text('Add a KPI')")
    page.wait_for_selector(".modal [role=dialog]", timeout=5000)
    out["add_dialog"] = page.locator(".modal [role=dialog]").inner_text()[:800]
    page.locator(".modal [role=dialog]").screenshot(path="/tmp/sr-add-kpi.png")
    page.keyboard.press("Escape")
    phone = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
    phone.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    pp = phone.new_page()
    pp.goto("http://127.0.0.1:8000/#/review")
    pp.wait_for_selector("text=One KPI, one meaning, one value", timeout=20000)
    pp.wait_for_timeout(800)
    out["phone_overflow"] = pp.evaluate("document.scrollingElement.scrollWidth - window.innerWidth")
    pp.screenshot(path="/tmp/sr-phone.png", full_page=True)
    dark = b.new_context(viewport={"width": 1400, "height": 1000}, color_scheme="dark")
    dark.add_cookies([{"name": "d2d_session", "value": cookie, "url": "http://127.0.0.1:8000"}])
    dp = dark.new_page()
    dp.goto("http://127.0.0.1:8000/#/review")
    dp.wait_for_selector("text=One KPI, one meaning, one value", timeout=20000)
    dp.click("table.srtable tbody tr.srrow")
    dp.wait_for_selector("text=Findings (", timeout=20000)
    dp.wait_for_timeout(500)
    out["dark"] = dp.evaluate("document.documentElement.dataset.theme || ''")
    dp.screenshot(path="/tmp/sr-dark.png", full_page=False)
    b.close()
print(json.dumps(out))
"""

p = c.Person(f"una.review@srui{c.STAMP}.com")
p.ip = "203.0.113.70"                         # an address of its own: a full run's suites share 198.51.100.10 ...
s, r = p.sign_in("Review UI", "Una Review")
c.check("ui: an organisation signs up", s == 200, (s, r))
p.post("/api/org/setup")                        # the first-time tour is done (the owner is not sent to #/welcome)
p.post("/api/me/tour", {"step": "done"})
s1, _ = p.post("/api/semreview/kpis", {"name": "Revenue", "synonyms": ["Net Sales"], "unit": "currency", "aggregation": "sum",
                                        "dax": 'CALCULATE ( SUM ( Sales[NetAmount] ), Sales[Status] = "Completed" )',
                                        "definition": "Sales of completed orders"})
s2, _ = p.post("/api/semreview/kpis", {"name": "Gross Margin %", "unit": "percent", "aggregation": "ratio", "dax": "DIVIDE ( [Revenue] - [COGS], [Revenue] )"})
c.check("ui: two KPIs in the dictionary", s1 == 200 and s2 == 200, (s1, s2))
tmp = tempfile.mkdtemp(prefix="sr54-")
with open(os.path.join(tmp, "Sales model.bim"), "w", encoding="utf-8") as fh:
    json.dump(t54.SALES, fh)
with open(os.path.join(tmp, "Finance.pbit"), "wb") as fh:
    fh.write(t54.pbit())
subprocess.run(["docker", "exec", "-u", "root", c.WEB_C, "sh", "-c", "rm -rf /tmp/sr54 && mkdir -p /tmp/sr54"], check=True, capture_output=True)
for f in ("Sales model.bim", "Finance.pbit"):
    subprocess.run(["docker", "cp", os.path.join(tmp, f), f"{c.WEB_C}:/tmp/sr54/{f}"], check=True, capture_output=True,
                   env={**os.environ, "MSYS_NO_PATHCONV": "1"})
cookie = c.cookie(p, "d2d_session")
res = subprocess.run(["docker", "exec", "-i", c.WEB_C, "python3", "-", cookie], input=PLAY, capture_output=True, text=True, timeout=400)
if res.returncode:
    c.check("ui: headless Chromium ran", False, res.stderr[-2000:])
else:
    o = json.loads(res.stdout.strip().splitlines()[-1])
    print(json.dumps({k: (v[:300] if isinstance(v, str) else v) for k, v in o.items()}, indent=1))
    c.check("ui: Semantic Review is in the menu", o["menu"].strip() == "Semantic Review", o["menu"])
    c.check("ui: the page says what it does, with the price and the dictionary", "Start review" in o["home_text"] and "10 credits" in o["home_text"]
            and "KPI dictionary" in o["home_text"] and "2\nKPIs defined" in o["home_text"], o["home_text"][:600])
    c.check("ui: the file picker lists both files", "Sales model.bim" in o["picked"] and "Finance.pbit" in o["picked"], o["picked"])
    c.check("ui: the review opens its report when done", "Revenue is calculated 2 different ways" in o["report_text"]
            and "KPIs with one meaning" in o["report_text"], o["report_text"][:800])
    c.check("ui: the meaning check's absence is said, with a retry", "Check meaning again" in o["report_text"], "")
    c.check("ui: the High filter shows only high findings", o["high_cards"] > 0 and o["high_all_high"], o["high_cards"])
    c.check("ui: a finding shows its DAX on request", o.get("dax_shown") is True, o.get("dax_shown"))
    c.check("ui: the KPI table says Revenue is calculated more than one way", "Calculated more than one way" in o["kpi_tab"] and "v2" in o["kpi_tab"], o["kpi_tab"][:500])
    c.check("ui: the measures tab lists every measure", o["measure_rows"] == 14, o["measure_rows"])
    c.check("ui: the models tab names both models and their kinds", "Sales model" in o["models_text"] and "Power BI template (.pbit)" in o["models_text"], o["models_text"])
    c.check("ui: the dictionary lists the two KPIs", o["dict_rows"] == 2, o["dict_rows"])
    c.check("ui: the Add a KPI dialog has the fields", all(x in o["add_dialog"] for x in ("Other names", "Reference DAX", "Aggregation", "Time basis")), o["add_dialog"][:300])
    c.check("ui: no sideways scrolling at phone width", o["phone_overflow"] <= 1, o["phone_overflow"])
    c.check("ui: dark mode follows the system", o["dark"] == "dark", o["dark"])
    c.check("ui: no script errors and no failed requests", not o["errors"], o["errors"][:5])
    c.check("ui: a fix is advice in words, with its DAX apart to copy", "What to do" in o["report_text"], "")
    for f in ("sr-home.png", "sr-report.png", "sr-kpis-tab.png", "sr-dictionary.png", "sr-add-kpi.png", "sr-phone.png", "sr-dark.png"):
        subprocess.run(["docker", "cp", f"{c.WEB_C}:/tmp/{f}", c.out_path(f)], check=False, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
bad = [n for n, ok in c.RESULTS if not ok]
print(f"\n{len(c.RESULTS) - len(bad)} of {len(c.RESULTS)} checks passed" + (f"; failed: {bad}" if bad else ""))
sys.exit(len(bad))
