# Testing

There are two layers: a **mock Power BI host** that runs the packaged visuals in headless Chromium (automated, runs in Docker), and **real Power BI** (manual, done by the user).

## Docker

```bash
docker build -t visual-atlas -f docker/Dockerfile .
docker run --rm -v "$PWD":/work -w /work visual-atlas make all
```

- Windows PowerShell: `docker run --rm -v "${PWD}:/work" -w /work visual-atlas make all`.
- The image has Node 22, `powerbi-visuals-tools@7.2.1`, `make`, and a Python venv with `playwright==1.63.0` (with Chromium and its system libraries) and `jsonschema==4.26.0`.
- `node_modules` folders are created inside your project folder by the container (Linux builds). Delete them before installing natively on Windows or macOS.
- The hand-off session couldn't build the image (no Docker daemon or registry there), but every step inside it was run natively and passed. If a pinned version is unavailable, bump it in `docker/Dockerfile`.

## What `make all` does

1. `scripts/build.sh`
   - `visuals/sync.sh` copies `common/` into each visual.
   - For each folder with a `pbiviz.json`: `npm ci` (if `node_modules` is missing), then `pbiviz package`.
   - Copies to `release/<DisplayName>.<version>.pbiviz`.
2. `scripts/themes.sh`: regenerates `visuals/themes/*.json` from the gallery brand engine and validates them against the schema (fails on any error).
3. `scripts/test.sh`
   - `tools/extract_bundle.py` pulls the compiled JS and CSS out of each `.pbiviz` (exactly what Power BI would load).
   - `visuals/test/build_page.py` wraps the bundle, the mock host (`host.js`), the sample data (`data.json`) and the test cases into `visuals/test/out/<name>.html`.
   - `visuals/test/shoot.py` opens each page in headless Chromium, runs the optional check script, saves a full-page screenshot, and fails on page errors, `renderingFailed`, thrown cases or failed checks.

Outputs: `visuals/test/out/flow_test.png` and `cols_test.png` (every case), `cols_checks.png`, and `cols_format.png`.

**Always open the screenshots** (in Claude Code: Read the PNG). The checks catch crashes and broken interactions, not layout problems such as overlapping labels, clipped text or odd colors.

## The mock host (`visuals/test/host.js`)

- `makeHost(opts)` returns an `IVisualHost` stand-in:
  - Color palette: the classic Power BI theme colors, with options for dark, high contrast or a custom theme.
  - Selection ids are readable strings such as `Year=2023&m=m.Sales` or `series=Retail`.
  - The selection manager, tooltip service, context menu, `drill`, `displayWarningIcon` and rendering events push entries into `window.LOG`.
  - `allowInteractions` (option), localization (returns the key, so fallbacks are used), `locale = en-US`.
- `renderCase(guid, title, dataView, {w, h, dark, hc, allowInteractions})` creates a 560×340 box (by default), constructs the visual and calls `update()`.
- Data views are built by helpers in the case files: `flowDV()` in `flow_cases.js` and `colDV()` in `cols_cases.js` (levels, measures or series groups, highlights, tooltips, `drillableRoles`, category objects, Format pane objects).

`data.json` is generated from the gallery's sample data by `node visuals/test/dump.js`, so the tests use the same numbers as the gallery.

## Test cases

Atlas Flow (`flow_cases.js`, 10):

1. Sankey · soft · report theme
2. Sankey · 3D · gradient links
3. Sankey · income statement · flat · brand color
4. Chord · soft · custom colors
5. Chord · 3D · trade
6. Network · soft · communities
7. Network · 3D · size by connections · dark theme
8. Sankey · highlighted from another visual
9. No fields yet (landing page)
10. Sankey · high contrast

Atlas Columns (`cols_cases.js`, 17):

1. Clustered column · soft · report theme
2. Stacked column · flat · total labels
3. 100% stacked bar · 3D · brand color · percent labels
4. Clustered bar · lollipop · brand palette
5. Expanded hierarchy · Year › Quarter · drill buttons
6. Drilled into 2024 · stacked by channel
7. Cross-highlighted · stacked column
8. Variance · negatives · average line · pill
9. Scrolls when crowded · 120 categories
10. Dark theme · stacked bar · soft · legend right
11. Color each category · custom list · square
12. Concatenated labels · 3D clustered column
13. High contrast · clustered column
14. No fields yet (landing page)
15. Clustered bar · Category › Subcategory tiers
16. Stacked column · gains and losses
17. Conditional colors (fx rule results)

`cols_checks.js` (the order of the cases matters) checks:

- the tooltip text
- click select, Ctrl multi-select, the context menu with the point's identity
- the legend selecting a series
- the three drill buttons calling `host.drill` with 1, 3 and 2
- the Enter key selecting
- a background click clearing the selection
- horizontal scrolling with 120 categories
- the tooltip of a highlighted point

`format_checks.js` checks the Format pane model:

- fx on "Default color" with one series and on each category color
- the reference line card in the Analytics pane
- total labels only for stacked charts
- shadow strength hidden for the flat look

Add a case for every new option and every bug you fix.

Atlas Distribution (`dist_cases.js`, 22; checks in `dist_checks.js`):

1. Histogram · soft · auto bins · labels
2. Histogram · two groups overlapping · flat
3. Histogram · 3D · mean, median, normal curve
4. Histogram · stacked · $50 bins · percent · brand
5. Box · delivery days by carrier · soft
6. Box · every point jittered · mean · flat
7. Box · horizontal · sorted by median · 3D · labels
8. Box · points beside · min-max whiskers · custom palette
9. Violin · session length by device · soft
10. Violin · box inside · horizontal · 3D
11. Raincloud · half violin, box, points · brand
12. Violin · quartiles · barcode · dark
13. Parallel coordinates · by category · soft
14. Parallel · cross-highlighted · smooth · all ticks
15. Box · high contrast
16. Histogram · dark · cross-highlighted
17. Box · no group, two measures · by measure
18. Landing page (no fields)
19. Parallel with one measure · hint
20. Violin · small tile
21. Histogram · every value the same
22. Box · blanks and a one-value group · tooltips

The checks cover:

- bin, group, point, line and legend selection; multi-select, the context menu, keyboard and background clear
- highlights and tooltips, including tooltip measures
- no NaN in any attribute
- which Format pane cards show for each chart type

## Not covered by the mock host (check in real Power BI)

- Drill mode (click a bar to drill), the header drill icons, context-menu drill entries; expand all sending several category columns; `drillableRoles` values at each level; "Allow drilling" (`setCanDrill`).
- Evaluated fx rules arriving in `categories[k].objects` (Columns); per-item color overrides persisting.
- The Format pane UI itself: card order, toggles, hidden slices, the Analytics pane card.
- Report page tooltips, the Sort axis menu, bookmarks restoring selection (`registerOnSelectCallback`), cross-filtering of other visuals, cross-highlight coming from other visuals.
- Theme `visualStyles` for the custom visuals (GUID keys), and the container drop shadow and border on built-in visuals.
- Fonts (Segoe UI in Power BI; the tests fall back to the container's sans-serif), export to PDF, the mobile layout, performance with thousands of points.

## Every family

`scripts/test.sh` runs every family in its `FAMILIES` list: cases in `visuals/test/<prefix>_cases.js`, checks in `<prefix>_checks.js`, screenshot in `visuals/test/out/<prefix>_test.png`. `ONLY=<prefix>` runs one. `visuals/test/shoot_cases.py <page> <out.png> <case numbers>` screenshots a few tiles for a close look.

| Prefix | Visual | Cases | What the checks cover beyond select, multi-select, context menu, keyboard, highlights, no NaN and Format cards |
|---|---|---|---|
| flow, cols, dist | Flow, Columns, Distribution | 10, 17, 22 | see above |
| compare | Compare | 19 | legend series, hints for missing series |
| hierarchy | Hierarchy | 16 | zoom in and out, open an org card, select mode |
| proportion | Proportion | 19 | waffle %, "7 in 10", Venn set selection and hint |
| time | Time | 17 | timeline filter JSON, shift-click range, clear, saved filter, scrolling |
| finance | Finance | 16 | subtotals, breakdown, conversion rate, candle scrolling |
| gauges | Gauges | 19 | card target and delta, KPI goal, liquid %, ticker animation |
| text | Text | 11 | no overlapping words, stop words, extra stop words |
| lines | Lines | 21 | hover bands, drill buttons, zoom by keyboard, forecast, anomalies |
| parts | Parts | 17 | no overlapping outside labels, drill, progress ring, Other |
| scatter | Scatter | 17 | drag zoom, play frame, Gantt header, milestones |

## Ready-made test report

`make report` writes `release/report/Visual Atlas Test.pbip` and `release/VisualAtlasTest.zip`. It has three pages with every Atlas visual already bound to embedded sample data, plus the built-in clustered column for comparison. Open the `.pbip` in Power BI Desktop, select **Refresh**, and use **File › Save as** for a `.pbix`. If Desktop offers to upgrade the model to TMDL, either choice works. `python3 tools/validate_report.py "release/report/Visual Atlas Test.Report"` checks the report JSON against Microsoft's schemas (the schemas are cached in `tools/schema/pbir/`).

## Testing in real Power BI

1. `make build`, then import `release/AtlasColumns.1.0.0.0.pbiviz` , `release/AtlasFlow.1.0.0.0.pbiviz` and `release/AtlasDistribution.1.0.0.0.pbiviz`. In Power BI Desktop, first enable **File › Options and settings › Options › Current file › Report settings › Develop a visual**, then in the Visualizations pane select **…** › **Import a visual from a file**.
2. Live development: run `pbiviz start` in the visual folder **natively** (not in Docker; it serves https://localhost:8080 and needs the pbiviz developer certificate trusted by your browser). Then add the Developer visual to a report in the Power BI service with developer mode on. Follow Microsoft's [environment setup](https://learn.microsoft.com/en-us/power-bi/developer/visuals/environment-setup) guide for the certificate and the service settings.
3. Sample data for a quick report: the CSV files in `visuals/test/sample-data/` (made by `python3 tools/export_csv.py` from `data.json`):
   - `flow_*.csv`: Source, Target and value columns for Atlas Flow
   - `dist_*.csv`: one row per observation (group, ID, value) for Atlas Distribution. Put the ID in Sample by and the value in Values.
   - `sales_by_date.csv`: Year, Quarter, Month, MonthNo, Sales, Profit
   - `sales_by_product.csv`: Category, Subcategory, Product, Sales, Profit
   - `revenue_by_channel.csv`: Month, MonthNo, Channel, Revenue

   Set Month to sort by MonthNo, and make a Year › Quarter › Month hierarchy to try drill-down.
