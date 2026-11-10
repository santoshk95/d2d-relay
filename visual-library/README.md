# Visual library

Custom Power BI visuals that the Relay agent built for earlier reports. Every new report can use them
(`genbi catalog` lists them for Claude), and the web app shows them on the **Visual library** page.

One folder per visual:

- `<name>.pbiviz` — the packaged visual (import it into any Power BI report)
- `source/` — its TypeScript source on the Visual Atlas framework (`caps.js`, `src/`, `style/`, `pbiviz.json`)
- `preview.png` — the browser test screenshot
- `visual.json` — name, title, field wells, version and the report it was made for

The web app adds a visual here after a run that built it, used it in the report and passed `genbi visual test`;
a later change to the same visual (`genbi visual edit <name>` in another project) updates it here. Removing a
visual from the library does not affect reports that already embed it. This is an ordinary folder, so you can
keep it in git.
