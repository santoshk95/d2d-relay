"""Screenshot selected test cases of a built test page side by side (for a close look at a few tiles).

usage: shoot_cases.py <page name> <out.png> <case index> [<case index> ...]
The page must exist (test/out/<name>.html, written by build_page.py / scripts/test.sh).
"""
import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

here = pathlib.Path(__file__).resolve().parent
name, out, idx = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        page = await b.new_page(viewport={"width": 1220, "height": 900})
        await page.goto((here / "out" / f"{name}.html").as_uri())
        await page.wait_for_timeout(600)
        # hide every case except the chosen ones, then shoot the grid
        await page.evaluate("idx => document.querySelectorAll('.case').forEach((c, k) => { if (!idx.includes(k)) c.style.display = 'none'; })", idx)
        await (await page.query_selector("#cases")).screenshot(path=out)
        await b.close()


asyncio.run(main())
