"""Open a test page in headless Chromium, optionally run a check script, and save a full-page screenshot.

usage: shoot.py <name> <out.png> [js-expression | @file.js]
- <name> is a page built by build_page.py (test/out/<name>.html)
- the optional script runs in the page; if it returns an object with ok == false the run fails
- exits 1 when the page throws, a case fails to render, or a check fails
Set CHROME_PATH to use an installed Chrome instead of Playwright's Chromium.
"""
import asyncio
import json
import os
import pathlib
import sys

from playwright.async_api import async_playwright

here = pathlib.Path(__file__).resolve().parent
name, out = sys.argv[1], sys.argv[2]
extra = sys.argv[3] if len(sys.argv) > 3 else ""
if extra.startswith("@"):
    extra = (here / extra[1:]).read_text(encoding="utf-8")


async def main() -> int:
    async with async_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox"]}
        if os.environ.get("CHROME_PATH"):
            kw["executable_path"] = os.environ["CHROME_PATH"]
        browser = await p.chromium.launch(**kw)
        page = await (await browser.new_context(viewport={"width": 1220, "height": 900})).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await page.goto((here / "out" / f"{name}.html").as_uri())
        await page.wait_for_timeout(800)
        ok = True
        if extra:
            res = await page.evaluate(extra)
            print("CHECKS", json.dumps(res, indent=1)[:6000])
            if isinstance(res, dict) and res.get("ok") is False:
                ok = False
        await page.screenshot(path=out, full_page=True)
        log = await page.evaluate('LOG.filter(x => x[0] !== "rendered")')
        rendered = await page.evaluate('LOG.filter(x => x[0] === "rendered").length')
        print("LOG", json.dumps(log)[:3000])
        print("rendered", rendered, "errors", errors[:5])
        await browser.close()
        if errors or any(x[0] in ("FAILED", "THROW") for x in log):
            ok = False
        print("RESULT", "pass" if ok else "FAIL", name, out)
        return 0 if ok else 1


sys.exit(asyncio.run(main()))
