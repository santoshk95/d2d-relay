# Project history

Everything the user asked for, in order, what was built in response, and the decisions and corrections along the way. The user's messages are quoted exactly (typos included). Work happened in one claude.ai session, 2–3 Nov 2026 (user's time zone: Asia/Calcutta).

## 1. The gallery page

> "create a power bi visual html page with all power bi visual avilable in standard, all should look very attractive and modern html, and create all possible combination of uses of each visual and ways to represent it"

Built **Power BI Visual Atlas**, one self-contained HTML page (now `gallery/`). For every built-in visual it shows a catalog card with what it's for, the best use, which field wells to fill, when to avoid it, and a set of variants (different encodings, layouts and formatting). Sample data is invented but deterministic (`gallery/src/data.js`: sales by month this year and last year, products, regions, channels, and three drillable hierarchies).

## 2. Drill-down and zoom

> "with drill down options as well and click and zoom as well like drill"

Added Power BI style interaction to the gallery:

- Drill up, drill mode (click a data point), go to the next level, expand all down one level, with breadcrumbs, for date (Year › Quarter › Month) and product (Category › Subcategory › Product) hierarchies, maps and matrices
- Zoom sliders, brush, pan, play axis, focus mode and tooltips

## 3. Looks and brand colors

> "Can you make it more interesting and clean and looks very good and 3d or shades or shadaows etc to make it look more appealing than the standard and color agonistic so it can adapt to any brand color palette and looks very nice"

- Three looks: **Flat**, **Soft** (gradients, soft shadows, glossy dots, glow) and **3D** (extruded bars, tilted pies, raised maps). The gradients read CSS variables, so a brand change recolors every chart without re-rendering (`gallery/src/look.js`).
- A color engine (`gallery/src/brand.js`):
  - Palettes are generated in OKLCH from one brand color, as Spectrum, Analogous or Mono, or taken from a pasted list (hex codes or a whole Power BI theme JSON).
  - Colors are kept inside validated lightness bands: light background L 0.43–0.77, dark background L 0.48–0.67, chroma at least 0.10.
  - Neighbouring colors are checked for separation under normal vision and protan/deutan color-blindness simulation (Machado 2009, OKLab ΔE × 100).
  - It also derives sequential, diverging and status colors, and light and dark surface tokens.
- A **theme studio** on the page sets the brand color, palette mode and look. **Copy theme JSON** exports a Power BI report theme.

## 4. Non-standard visuals

> "And also add all other visuals as well which is not part of standard and so this is a complhrensivs visuals and all combinations"

Added AppSource and build-your-own visuals in seven extra categories:

- Flow, network & hierarchy
- Distributions & targets
- Comparison & ranking
- Proportion, overlap & text
- Calendars, time & finance
- Gauges & live KPIs
- Build your own (Deneb, SVG measures, HTML content)

The page now has 84 visuals in 19 categories. It was published as a claude.ai artifact (private to the user): https://claude.ai/artifact/KJMpGZiS7QoPx6XoGGtQjK, version 2.

## 5. Real custom visuals

> "Now is it possible to create all these as custom visual and color palette and all 100%configirabke sonit can be used dynamically?"

Asked three scoping questions. The user's answers:

| Question | Answer |
|---|---|
| Packaging | **One per family (Recommended)**: one `.pbiviz` per family, with a chart-type switch in the Format pane |
| Scope | **Pilot first (Recommended)**: the Flow family (Sankey, chord, network) first, the rest after testing |
| Built-in visuals | **"Both so i can compare, why it cant have drill down ?"** Deliver a theme for the built-in visuals AND rebuilt built-ins as custom visuals |

**Correction.** Before this, the answer had said rebuilt visuals would lose drill-down. That was wrong. Custom visuals support drill-down through the `drilldown` capability (any API version), and since API 4.7 the visual can also trigger drills itself with the Drilldown API. Atlas Columns was built with drill-down to prove it.

What was built (all in `visuals/`):

- **Atlas Flow**: Sankey, chord and network in one visual.
  - Source, Target and Weight fields, plus Tooltips.
  - Flat, Soft and 3D looks; palette from the report theme, a brand color or a custom list.
  - A color per node; Sankey alignment, node width, spacing and corners.
  - Link coloring (source, target, gradient, neutral) and opacity.
  - Chord gap, arc width and ribbon opacity; network size by value or by connections, and community coloring (label propagation).
  - Labels with display units. Highlights, selection, tooltips, keyboard, high contrast, landing page.
  - A warning icon when Sankey loops are skipped.
- **Atlas Columns**: the six built-in column and bar charts rebuilt (clustered, stacked, 100% stacked × column, bar).
  - Drill-down three ways: the header icons, the context menu or drill mode, and on-visual buttons that use the Drilldown API.
  - Hierarchy tier labels, or concatenated labels.
  - Bar shapes: rounded, square, pill or lollipop. Looks: Flat, Soft or 3D prisms.
  - Palette from the theme, a brand color or a custom list, with per-series or per-category colors and **fx conditional formatting** when there's one series.
  - Data labels (5 positions; value, percent or both) and total labels.
  - Axis options (title, display units, decimals, start and end), gridline styles, and 5 legend positions.
  - A reference line in the **Analytics pane** (average, median, min, max or constant).
  - Sort axis, cross-highlighting, multi-select, keyboard, high contrast, and scrolling when crowded.
  - A warning when 5,000 categories are exceeded.
- **Themes**: Flat, Soft, 3D and Soft Dark, generated from the gallery brand engine.
  - They hold palette, structural colors, text sizes, the page background, and visual container styles (corner radius, border, drop shadow, padding, title).
  - They also set the default look of the two Atlas visuals (`visualStyles` keyed by GUID).
  - All four pass Microsoft's theme schema 2.159.
- The gallery's **Copy theme JSON** now includes the look, the shadow and border settings, and the Atlas visual defaults. Republished as artifact version 3.

Problems found and fixed during testing (in the mock host, `visuals/test/`):

- Sankey on large values (an income statement in dollars): the vertical scale was clamped to a minimum of 0.0001 px per unit, so nodes overflowed. The clamp was made tiny (1e-12).
- Label halos were white on dark backgrounds. They now use the surface color through the CSS variable `--atl-halo`.
- Gradient and filter ids clashed when several visuals were on one page; the first visual's gradients were used everywhere. Ids now include an instance counter.
- Label widths were guessed (0.56 × font size per character), so labels were clipped. `textW()` now measures on a canvas.
- Rotated category labels were cut at the left edge and too dense. They now skip based on the rotated spacing, and the label layer extends under the value axis.
- Data labels showed noisy decimals ("$209.12K"). `labelFormatter` now gives about 3 significant digits ($209K, $4.77M), and `axisFormatter` uses one unit per axis.
- Outside labels on single-series columns can now use the whole category width.

Delivered: both `.pbiviz` files, the four theme JSON files, a source zip with a README, and test screenshots.

## 6. Hand-off to Claude Code

> "give me one zip file with all details and memory, i will shift to claude code in my system where it has docker as well so i can generate a pbib and test it same"

Created this package:

- `CLAUDE.md` and `docs/` as project memory
- a Docker image definition and a Makefile with scripts (`make all` = build both `.pbiviz` files, regenerate and validate themes, run every mock-host test)
- portable test scripts with pass/fail checks
- the gallery source with a path-independent build
- the last built artifacts in `release/`

The whole pipeline was run from a clean copy (npm ci → pbiviz package → themes → tests) and everything passed. The Docker image itself couldn't be built in the hand-off session, because that workspace had no Docker daemon or registry access. If `docker build` fails on a version pin, adjust it in `docker/Dockerfile`.

## 7. Remaining families, one at a time (Claude Code, 3 Nov 2026)

> "can you start one by one and no multiple agents and all sequence only"

The user asked to start the remaining families now (before real Power BI feedback on the pilot), strictly one after another, with no parallel agents or sessions. Order: `docs/ROADMAP.md`.

**Family 1: Atlas Distribution** (`visuals/atlasDistribution`, GUID `atlasDistribution1C4252B29C654CC1BF16155962622408`):

- Chart types: histogram, box and whisker, violin (full or half/raincloud), parallel coordinates.
- Roles: Group (optional), Sample by (one row per observation), Values (one or more measures), Tooltips. Top 30,000 rows, with a warning icon beyond that.
- Without a Group but with several measures, box, violin and histogram show one group per measure.
- Every gallery variant is a setting: bins (auto, count, width), overlapping or stacked groups, count or percent, normal curve, mean/median lines (Analytics pane), whiskers (1.5 IQR, min-max, 5th-95th), outliers, mean marker, points (jittered or beside), orientation, sort by median, violin side, inner box or quartiles, jitter or barcode points, smoothing, trim.
- Jitter is a hash of the row index (no `Math.random`). Selection works on observations: a bin, a group (box, violin, legend), a point or a line. Highlights from other visuals ghost the bars and dim boxes, points and lines.
- Tests: `visuals/test/dist_cases.js` (22 cases) and `dist_checks.js` (interaction, highlight, no-NaN and Format pane checks). Sample CSVs: `dist_orders.csv`, `dist_shipments.csv`, `dist_sessions.csv`.

## 8. A ready-made test report (3 Nov 2026)

> "give me a pbib file with report built"

A finished `.pbix` is a binary that only Power BI Desktop writes, so the report is generated as a **Power BI project** instead: `release/report/Visual Atlas Test.pbip` (zipped as `release/VisualAtlasTest.zip`). Desktop opens it like a `.pbix`, and **File › Save as** turns it into one.

- `tools/mk_report.py` writes it (`make report`, also part of `make all`).
- The data is embedded in each Power Query as base64 JSON, so Refresh needs no files: 10 tables from `visuals/test/sample-data/`, each with explicit measures.
- The three `.pbiviz` files are unpacked into `CustomVisuals/<GUID>/` and registered as `CustomVisual` resource packages in `report.json`, following Microsoft's `skills-for-fabric` custom-visuals reference. The Atlas Soft theme is the report theme.
- Pages:
  - Atlas Distribution: Carrier slicer, box, raincloud, histogram, parallel coordinates
  - Atlas Columns: drill hierarchy next to the built-in clustered column, stacked by channel, bar
  - Atlas Flow: Sankey, chord, network
- `tools/validate_report.py` checks every report file against Microsoft's published PBIR schemas (all valid). `visualContainer` 2.14.0 doesn't exist publicly; the report uses 2.13.0.
- Not opened in Power BI Desktop by Claude (computer use was off in the session); the user tests it.
- First open in Desktop failed: "The 'Delivery Days' measure cannot be created because a column with the same name already exists". Power BI compares names without case, so the measure `Delivery Days` clashed with the column `Delivery days`, and `Order Value` with `Order value`. The measures were renamed `Days to Deliver` and `Order Amount`. `mk_report.py` now stops on any case-insensitive measure/column clash, and on any visual field that doesn't exist in the model.

## 9. First look in real Power BI (3 Nov 2026)

The user opened the test report: all four Atlas Distribution visuals render in Power BI Desktop (theme colors, legends, mean markers, median line, normal curves, raincloud). Fixes from the screenshot:

- Axis ticks at zero showed the display unit ("0K", "$0K"). `axisFormatter` in `common/util.ts` now prints zero without unit or decimals ("$0"); there's a `zeroWithoutUnit` check in `dist_checks.js`. This affects every visual.
- The Carrier slicer showed its name twice; the report turns off the slicer's container title.
- All three visuals are now 1.0.1.0. `mk_report.py` picks the newest `.pbiviz` per visual in `release/`.

The Atlas Columns and Atlas Flow pages haven't been reported on yet.

> "i think relation is not established in the model"

Correct. Each visual read its own unrelated sample table, so the Carrier slicer only filtered the box plot. The report model is now a star schema generated in `mk_report.py` from a seeded generator:
- **Orders** fact table: 2,400 orders in 2024–2025, with order value, quantity, delivery days and minutes on site (online orders only).
- **Dimensions**: Date (every day), Carrier, Channel, Device, Product (the 48 sample products, with list price and margin rate).
- **Relationships**: many-to-one, single direction.
- **Measures** on Orders: Sales, Profit, Margin %, Order Count, Units, Avg Order Value, Days to Deliver, Avg Delivery Days, Session Minutes.

All visuals except chord and network read Orders through the dimensions, so slicers (Carrier, Channel, Year) and clicks filter every visual on the page. The Columns drill uses the Date dimension, and the Sankey shows Device to Category. The generator checks that relationship keys exist and are unique, and that every fact value has a dimension row.

## 10. All families, fully configurable, one customization layer (3 Nov 2026)

> "ok now can you generate all viusla custom and completely configurable design and color so i can be used across all and prepare a md file as well on how to customise it and change it"

Plan: build every remaining family one at a time (roadmap order), and make design and color configurable the same way across all of them. `CUSTOMIZING.md` explains how.

Shared groundwork (in `visuals/common/`, used by every new family):
- `cards.ts`: the shared Format pane cards: **Style** (font, text color; new, also added to Columns, Flow and Distribution), Palette, Colors, Data labels, Category axis, Value axis, Gridlines, Legend.
- `family.ts`: `FamilyVisual` base class (host wiring, look, Style, palette, per-item colors, selection sync, highlights, landing page, rendering events, row-limit warning). A family implements `read()`, `draw()` and `tidy()`.
- `interact.ts`: `Interact` (bind targets: tooltips, select, multi-select, context menu, keyboard; `active` = selection, else highlights).
- `chart.ts`: `nice`, `domain`, `valueAxis` (the last tick right-aligns at the edge), `legend`.
- `data.ts`: role columns, `fillOf`, `tipsAt`.
- `look.ts`: `setFont()`, so text measuring follows the Style font.
- `tools/mk_caps.js`: writes a family's `capabilities.json` from its `caps.js` plus the shared objects; `visuals/sync.sh` runs it.
- `tools/scaffold.py`: new family project (GUID, icon, package files).
- `scripts/test.sh`: data-driven `FAMILIES` list; `ONLY=<prefix>` runs one family.
- `visuals/test/shoot_cases.py`: screenshot chosen tiles.
- `tools/mk_themes.js`: `visualStyles` for **every** GUID found in `visuals/*/pbiviz.json` (look, shadow, palette source; optional `ATLAS_FONT`, `ATLAS_SHADOW`).

**Family 2: Atlas Compare** (`visuals/atlasCompare`, GUID `atlasCompare1934AF42622F4D63BF12168C02806AC8`):
- Chart types: lollipop, dot plot, dumbbell (two series, or a range with 3+), slope, bump (ranks), tornado (mirror or around a base value), radar (polygon or circle grid, fill, one radar per series).
- One category × series matrix (series from the Legend or from the measures).
- Settings: sort (value, change, name), focus on one item (others gray), marker shape and size, stem and line width, color by series, category or sign, connector up/down colors, tornado layout and base, radar grid, levels, max and small multiples.
- Tests: `compare_cases.js` (19 cases), `compare_checks.js`.

**Family 3: Atlas Hierarchy** (`visuals/atlasHierarchy`, GUID `atlasHierarchy21AE4CB2A0F74216862D09F0C9A3BF2E`, uses `d3-hierarchy` 3.1.2):
- Chart types: treemap (squarified, balanced or slice-and-dice tiling, group headers), sunburst (hole, gap, labels along rings, center shows the total and zooms out), circle packing, org chart / tree (top down or left to right, curved, elbow or straight links, team-size badges, value bars, open and close branches).
- Data: Levels (Category › Subcategory › Product) or ID + Parent ID + Label for org charts (cycles and missing parents become top nodes).
- Click a group to zoom in (or select, by setting); a breadcrumb zooms out. Color by top-level branch (lighter per level), by level, or by a Color value measure on a low/high gradient.
- `FamilyVisual` gained `grow()`: a drawing larger than the tile scrolls (the tree never shrinks below 60%).
- Tests: `hierarchy_cases.js` (16 cases), `hierarchy_checks.js` (zoom in and out, expand a card, select mode, legend, keyboard, highlights).

**Family 4: Atlas Proportion** (`visuals/atlasProportion`, GUID `atlasProportion74F95B1AE3CB4D9195CC248A3EC140A4`):
- Chart types: Mekko (column width = total, segments = shares, totals), waffle (one share, category shares, or one per category from part and total; square, rounded or circle cells; big number), pictogram (built-in SVG icons: person, circle, square, star, heart, drop; "7 in 10" ratio, or rows with units per icon and partial icons), aster plot (score length, weight width, outline at the maximum, weighted score in the center), rose / polar area (area follows the value, stacked by legend, shade by value), Venn (2 or 3 sets from "A & B" categories, areas and overlaps solved numerically, labels at the deepest point of each region).
- The category × series reader moved to `common/matrix.ts` (Compare re-exports it). `measuresAreParts` keeps the colors on categories when a second measure is a total or weight.
- Tests: `proportion_cases.js` (19 cases), `proportion_checks.js`.

**Family 5: Atlas Time** (`visuals/atlasTime`, GUID `atlasTime657C41A78B0A405A998ADA36387448E9`, uses `powerbi-models` 1.15.2; 1.15.3 was published without its `dist/` files):
- Calendar heatmap (a year of weeks, or month pages with day numbers and values; week starts Monday or Sunday).
- Heat grid and punch card (Rows × Time).
- Stream graph: wiggle (Byron & Wattenberg), silhouette, stacked or 100%, with labels at the thickest point.
- Timeline slicer: day, week, month, quarter or year; click, shift-click to extend, ✕ to clear. It writes an `AdvancedFilter` on the Time column with `applyJsonFilter` and reads it back from `options.jsonFilters`. A date hierarchy level can't be filtered, so the visual shows a warning.
- Color scale card: by value or by rank (quantiles), low, high and no-data colors, steps, gap, radius.
- `FamilyVisual` keeps the last update `options` (for `jsonFilters`). The mock host logs `applyJsonFilter` and passes `jsonFilters`.
- Tests: `time_cases.js` (17 cases), `time_checks.js` (filter JSON, range extend, clear, saved filter, scrolling).

**Family 6: Atlas Finance** (`visuals/atlasFinance`, GUID `atlasFinance8C601CA9CAF44ADCB6574FA21FDDE583`):
- Candlestick: Open, High, Low, Close and Volume roles; candles, OHLC bars or a close line; volume panel; moving average; scrolls when crowded.
- Waterfall: first bar as a total, total at the end with a custom label, named subtotals (P&L walks), increase, decrease and total colors, connectors. With a Legend it draws a breakdown from the first to the last category.
- Ribbon: ranked columns joined by ribbons, with opacity and column width.
- Funnel: bars or tapered; value, % of first, % of previous; conversion rate; one color, a color per stage, or darker by stage.
- Category labels wrap to two lines when names are long.
- Tests: `finance_cases.js` (16 cases), `finance_checks.js`.

**Family 7: Atlas Gauges, with the Cards family merged in** (`visuals/atlasGauges`, GUID `atlasGauges797C4E4189814B78AD7FCCDFF53CBC47`). The roadmap suggested merging Cards into Gauges; Power BI's Goals scorecard is a service feature, so KPIs with targets plus multi-row cards cover it.
- Chart types: card (one or many; accent bar; target and delta), multi-row card, KPI (status arrow and colors, goal, trend as area, line or columns), gauge, dial (bands from data or %, needle, target), radial bars (progress to target), liquid fill (circle or rounded square), bullet (bands, horizontal or vertical), ticker (CSS animation, paused on hover and for reduced motion).
- Roles: Category, Trend axis, Value (several measures make one card each), Target, Minimum, Maximum, Band 1, Band 2.
- Status: higher or lower is better, an amber tolerance, good, close and off colors, color the value by status.
- Tests: `gauges_cases.js` (19 cases), `gauges_checks.js`.

**Family 8: Atlas Text** (`visuals/atlasText`, GUID `atlasTextC961F02E238E426A825D8355E3503AA9`):
- Word cloud and ranked words.
- Text can be phrases or free text, split into words (auto, keep phrases or split), with a built-in English stop list plus "Also remove", a minimum length, a maximum word count and lowercase.
- Words are weighted by a measure, or counted.
- Colors: a color per word, one color, by topic (legend), or by a Color value on a gradient (sentiment).
- Placement: a deterministic Archimedean spiral with box collision checks, shrinking until the words fit. Rotation none, some vertical or mixed (set from a hash of the word). Size scale square root, linear or log.
- Tests: `text_cases.js` (11 cases), `text_checks.js` (no overlaps, stop words).

Shared change: report-theme colors are now adapted for dark backgrounds too (`colorer` in `common/util.ts`), as brand and custom palettes already were.

**Family 9: Atlas Lines** (`visuals/atlasLines`, GUID `atlasLines36E69B273DB443A5AF8E62CB16DB4547`):
- Chart types: line, area, stacked area, 100% stacked area, line and stacked column, line and clustered column (lines on a secondary axis by setting).
- Drill-down as in Atlas Columns (buttons, `setCanDrill`); an expanded hierarchy shows as concatenated labels.
- Line shape: straight, smooth or stepped. Markers (none, all, last), dashed series by name, area opacity, series names at the line ends, focus on one series.
- Error band from Lower/Upper bound measures. Hover bands per category: the tooltip lists every series, and a click selects the category.
- Zoom slider: overview with draggable handles and window; arrow keys on the handles.
- Analytics pane: trend line, min/max, average, target zone, forecast (from the last value along the least-squares slope, 95% band widening with √k), anomalies (median of the neighbors, MAD spread, more than 3 spreads away).
- Shared fix: the axis formatter counts decimals after the ×100 of percent formats ("22%", not "22.00%").
- Not done: small multiples.
- Tests: `lines_cases.js` (21 cases), `lines_checks.js`.

**Family 10: Atlas Parts** (`visuals/atlasParts`, GUID `atlasPartsA0676FD0579D44EFB545170E4799ADC9`):
- Pie and donut. Full or half, start angle, inner radius, gap.
- Order: largest first or data order; top N plus "Other".
- Labels: outside with non-overlapping leader lines, inside, or inside when they fit. Content: percent, category and percent, category and value, all, value.
- Center total with caption; last slice as a track (progress ring); Details field draws an outer ring in shades of each slice.
- Drill-down (`common/drill.ts` now holds the shared drill buttons; Atlas Lines uses it too).
- `common/matrix.ts` now reads every level of an expanded hierarchy and carries `drill`, `drillDisabled` and `levelNames`.
- Tests: `parts_cases.js` (17 cases), `parts_checks.js` (no label overlaps, drill, progress).

**Family 11: Atlas Scatter** (`visuals/atlasScatter`, GUID `atlasScatter0B23674C661C4797A349BBC2B0AD313A`):
- Scatter and bubble: Legend colors, one color, or automatic clusters (k-means with deterministic starts on standardized x and y).
- Guides in the Analytics pane: quadrants (averages or typed splits), trend line, ratio line, symmetry shading (Y = X), logarithmic X and Y (each tick with its own display unit), drag to zoom (rubber band, double-click or ⟲ to reset).
- Play axis: play/pause, speed, loop, frame dots; the timer stops on new data and in `destroy()`.
- Dot plot on a categorical X-axis (deterministic jitter).
- Gantt: Task, Start, End (blank = milestone), Phase (Legend), Owner, % complete; progress as fill or overlay; today line; weekends shaded at day scale; day, week or month header; scrolls when there are many tasks.
- Tests: `scatter_cases.js` (17 cases), `scatter_checks.js` (zoom drag, play frame, Gantt).

**Wrap-up of the family build:**
- **Test report:** `tools/mk_report.py` has 12 pages, one per family (Text and Parts share a page): 50 visuals on one model.
  - Orders star schema, plus small tables for the org chart (Employees), candlestick (Prices), funnel (Pipeline), word cloud (Reviews) and Gantt (Tasks).
  - New measures: Sales 2024, Sales 2025, Sales Target, Margin Score.
- **Versions:** Columns, Flow and Distribution are 1.0.2.0 (Style card and shared fixes); the new visuals are 1.0.0.0.
- **Gallery:** "Copy theme JSON" now covers every Atlas GUID too (`gallery/src/brand.js`).
- **Docs:** README, `visuals/README.md`, `CUSTOMIZING.md` (cards and GUIDs for all 13), ROADMAP (status per visual and known gaps), ARCHITECTURE (family layer), TESTING (per-family table).

## 11. Drill-down feedback from the 12-page test report (3 Nov 2026)

> "no reset or clear after drill and multipe drill legends not clear" (with a PDF export of the report)

- `common/drill.ts`: the drill bar adds **Back to the top level** (drills up one level now, then once per update while Up is still available, at most 8 levels; `afterUpdate()` is called from `read()`) and **Clear selection** (shown only while something is selected). Atlas Columns now uses the shared drill bar too. Columns, Lines and Parts have the new strings.
- **Atlas Lines never drew its legend** (`lg.draw` was missing), which is why the stacked area and combo had no legend in the PDF. Fixed, with a `legendDrawn` check.
- Expanded hierarchy levels read "2023 › Qtr 1" and "Bikes › Road" (Lines labels, `common/matrix.ts` names, so the Parts legend too).
- Anomalies use the standard modified z-score cutoff, 3.5 (Iglewicz and Hoaglin), not 3; the daily-orders page flagged too many points.
- Versions: Columns 1.0.3.0; Lines, Parts, Compare, Proportion and Finance 1.0.1.0 (they use the changed shared code).

## 12. Zoom, legend and label feedback (3 Nov 2026)

> "unable to zoom out after this, and legends not clear, funnel sales font not clear, click and zoom not working in, check all from the pdf as well" (screenshots of circle packing and sunburst zoomed in, the funnel, the stacked area and the daily-orders area)

- **Hierarchy zoom-out:** the "All › Bikes › Mountain" breadcrumb was drawn in the same place as the legend, so the way back was hidden. It now sits under the legend, with a **‹ Back** button (zooms out one level; keyboard too). Sunburst outer-ring labels are left out rather than cut to "Ro…". Checks: `crumbBelowLegend`, `backButton`.
- **Funnel labels:** inside labels had the light halo every label gets, which blurred white text on blue. Labels on a colored mark use class `lbl in` (no halo), in Finance (funnel) and Time (heat grid).
- **"0.09K", "0.03K":** `labelFormatter` with Auto units now gives a value smaller than the visual's unit its own unit, so it shows "90" (funnel, aster and every other data label).
- **Lines click and zoom:**
  - The filled area was on top of the per-category hover bands, so a click selected the whole series ("Series: Order Count"). The bands now sit above lines and areas, under the markers.
  - Dragging the slider lost the pointer after the first redraw (the handle is redrawn). The `<svg>` now captures the pointer for the drag.
  - New: mouse wheel over the plot zooms around the pointer; double-click on the plot or slider shows everything again; a click on the slider track moves the window there; a "Double-click to show all" hint shows while zoomed.
  - The anomaly band is lighter. Checks: `wheelZoom`, `dblclickResets`, `areaClickHitsCategory`.
- **From the PDF:** bubbles were cut at the plot edge (Scatter pads the domain by the largest bubble). The candlestick showed two scrollbars and cut dates: `ctx.grow()` now shrinks the other side by the scrollbar (`SCROLLBAR` in `common/family.ts`), and Finance and Time lay out for it.
- Versions: every visual +0.0.1 (shared label code changed).

## 13. Selection marker and a clearer Reset zoom (3 Nov 2026)

> "all wrking, while a visual is selected/filteres can we put a small colored * next to it so we know its selected/filtered"
> "move the reset button and make it clear" (screenshot: the Scatter's ⟲ icon on top of the "Margin % above" label)

- `common/corner.ts`: one flex row in the top-right corner of every visual holds **Reset zoom**, the drill bar and the **selection marker**, so they never overlap. `DrillBar` now lives in that row.
- **Marker:** a small colored * (Style card: *Selection marker*, *Marker color* (default #e8590c), *Also when another visual highlights it*, off by default). It shows while something is selected in the visual (all 13), or while the visual filters the report (`isFiltering()`: jsonFilters, or Atlas Time's own range). Its tooltip says which; clicking it clears the selection (`io.clearSelection()`) or the filter (`clearFilter()`). The visual title is drawn by Power BI, so the marker sits inside the visual's corner. A visual can't tell when a slicer filters it, only when another visual's selection highlights it.
- **Reset zoom:** a labelled pill button ("↺ Reset zoom") in the corner (`ctx.resetZoom()`), in Scatter (replaces the ⟲ icon that covered the quadrant label) and Lines (replaces the "Double-click to show all" hint). The plot moves down while zoomed so the button never covers it.
- Checks: `selectionMarker` (Columns, Lines), `filterMarker` (Time), `resetButton` (Scatter).
- Versions: every visual +0.0.1 again (Style card changed).

## 14. Cross-filtering, legends, month and drag selection (3 Nov 2026)

> "this look plain, sunburst dosne show the selected legends same with others as well, why month is not seletable, this gauges page not changing when selecting visuals same with these 2 visuals, atlas lines done have seelct from click and drag seelct" (screenshots: built-in clustered column, zoomed sunburst, rose, the Gauges page, donut and pie, the Lines page)

- **Visuals didn't change when another visual was selected.** Atlas visuals support highlights, so Power BI sends highlight values instead of filtering them. They only dimmed items whose highlight was zero. A partly matched item (Online sales of Bikes) looked the same, so cards, KPI, gauges and the donut never changed. New rule (`hlModeOf()`, `hlValue()` in `common/data.ts`):
  - **Selection on another field** (some value partly highlighted, mode "filter"): the visual draws the highlighted parts, as a filter would. Cards, gauges and KPI show the selected numbers; donut, rose, treemap, waterfall, word cloud, calendar and Sankey are redrawn from them. Used by the shared matrix reader (Compare, Finance, Parts, Proportion) and by Gauges, Hierarchy, Time, Text and Flow.
  - **Selection of whole items** (every highlight is all or nothing, mode "keep"): values are kept and the rest is dimmed, like Power BI's own pie.
  - Lines and Scatter always "keep": a point moves to its highlighted value, and points with nothing selected stay (dimmed). Tooltips show "Before the selection".
- **Legends while zoomed** (Hierarchy): only the branch on screen stays bright.
- **Month names in the rose (and aster) are selectable**: clicking one selects the whole month.
- **Lines: click and drag** across the plot selects every category in between; Ctrl adds (`Interact.selectMany()`).
- **Built-in column looks plain:** a theme can't add gradients or rounded bars (no such property in the 2.159 theme schema). The Atlas themes now give built-in column and bar charts no axis titles, softer gridlines, bold data labels and a tighter series gap. The full look needs Atlas Columns.
- Checks: `partialHighlight` (Parts, Gauges), `zoomLegend` (Hierarchy), `monthLabelSelects` (Proportion), `dragSelect` (Lines). The existing whole-item `highlights` checks still pass.
- Versions: every visual +0.0.1.

## 15. Zoom to the selection, clickable axis labels, honest cursors (3 Nov 2026)

> "selection is working, but when selected it should zoom as well" (stacked area by month above the daily-orders area)
> "also ensure all x y legends are selectable as well and can the cursor change only when there is selected in visual ? rather than the entire card showing seletable ?"

- **Lines zooms to the selection** (Chart card: *Zoom to the selection*, on by default, shown with the zoom slider). It zooms to a range dragged in the chart, or to the categories another visual's selection highlights; a single click inside the chart doesn't zoom. The window has at least 7 categories, and the earlier window comes back when the selection clears (`zoomToSelection()` in `atlasLines/src/render.ts`; `View.key`, `View.saved`).
- **The selected stretch of a line stands out:** the rest of the line and area fades to 28%, and the selected run is drawn on top (`.sel-run`). Before this, a highlight in "keep" mode only dimmed markers, so a line chart looked unchanged.
- **Axis and category labels select what they name** (`Interact.bindLabel()`, `catTarget()` in `common/matrix.ts`; Columns has its own `bindCat()`):
  - Columns and Lines: x-axis labels (y-axis on bar charts).
  - Compare: lollipop, dumbbell and slope labels.
  - Finance: waterfall steps, ribbon months, candlestick dates and funnel stages.
  - Proportion: Mekko columns, pictogram rows, rose and aster months.
  - Time: heat-grid rows and columns.
  - Gauges: names on gauges, cards, bullets and bars.
  - Scatter: dot-plot categories and Gantt tasks.
  - Legends already selected.
- **Cursor:** the hand shows only where a click selects data. `Interact.bind()` sets it per mark: a measure-only mark (four separate measure cards) can't filter anything, so it keeps the arrow. Full-plot hover strips (`Target.wide`, Lines bands, candlestick hit areas) keep the arrow too, and the Scatter's whole-plot crosshair is gone. The blanket `cursor: pointer` on `.grp`, `.mk`, `.pt` and `.pl` was removed. Zoomable hierarchy shapes and org-chart cards with children keep the hand.
- The mock host's selection ids now return a metadata-only selector for measure-only ids, as Power BI does.
- Checks: `zoomToSelection`, `axisLabelSelects`, `bandArrow` (Lines), `categoryLabelSelects` (Columns), `cursorOnlyWhenSelectable` (Gauges).
- Versions: every visual +0.0.1.

## 16. Selections in several visuals at once (3 Nov 2026)

> "working but currently only 1 visual can be seelcted/filtered, i need multiple"

- Power BI's default: `select(ids, false)` (a plain click) replaces the selection, including other visuals' selections; only Ctrl+click adds.
- New Style card option **Keep other visuals' selections**, on by default. A plain click replaces only this visual's selection, by toggling its old ids off and the new ones on in one `select(ids, true)` call (`replaceSelection()` and `choose()` in `common/interact.ts`). Deselecting by clicking again, and the * or Clear selection buttons, also toggle this visual's ids off rather than calling `clear()`. A click on empty space still calls `clear()`.
- Used everywhere: `Interact` (the 10 family visuals) and the click code in Columns, Flow and Distribution.
- The mock selection manager now keeps its ids like Power BI's (`multiSelect` toggles, otherwise replaces) and returns them from `getSelectionIds()`.
- Check: `keepOtherVisuals` (Parts). Not testable in the mock: how several visuals' selections combine in real Power BI.
- Versions: every visual +0.0.1.

> "all ok", the user's confirmation after testing in Power BI.

## 17. Packaged for another project (3 Nov 2026)

> "zip all as i will be use in another project and content and how to customise all and docs"

- `CONTENTS.md` (new, start here): what's in the package, the 13 visuals with GUIDs and versions, and three paths: use, restyle (the four levels of `CUSTOMIZING.md`), develop.
- `visuals/README.md` gained an *Interactions* section: click, axis labels, several visuals, cross-filtering, the * marker, drill, zoom, cursor.
- `release/screenshots/` now holds the latest test screenshot of every visual.
- `VisualAtlas-project.zip` at the project root holds the whole project under `visual-atlas/`, without `node_modules/`, build output, `visuals/test/out/` or the duplicate report copies. Unpacked into an empty folder, `make build test` rebuilds everything.

## Decisions to keep

- One `.pbiviz` per family, with a chart-type switch.
- Pilot first; build the next families only after the user tests in real Power BI. (Changed on 3 Nov 2026: the user asked to build the remaining families now, one at a time, with no parallel agents.)
- Built-in visuals get a theme (container look only); the full look (gradients, 3D, rounded bars) needs the custom visuals.
- Visuals stay certification-friendly: no innerHTML, no network, no randomness, `privileges: []`.
- Every option the gallery shows as a variant becomes a Format pane setting.
