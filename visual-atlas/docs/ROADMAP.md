# Roadmap

## Where things stand

All families are built (3 Nov 2026). Each is one `.pbiviz` with a chart-type switch, tested in the mock host; Columns, Flow and Distribution have also been opened in real Power BI.

| Package | Chart types | Status |
|---|---|---|
| **Atlas Columns** | Clustered, stacked, 100% × column, bar | Real Power BI: renders (first report) |
| **Atlas Flow** | Sankey, chord, network | Mock host; on the test report |
| **Atlas Distribution** | Histogram, box, violin/raincloud, parallel coordinates | Real Power BI: renders, slicers filter it |
| **Atlas Compare** | Lollipop, dot plot, dumbbell, slope, bump, tornado, radar | Mock host |
| **Atlas Hierarchy** | Treemap, sunburst, circle packing, org chart / tree | Mock host |
| **Atlas Proportion** | Mekko, waffle, pictogram, aster, rose, Venn | Mock host |
| **Atlas Time** | Calendar heatmap, heat grid / punch card, stream, timeline slicer | Mock host (filter JSON checked) |
| **Atlas Finance** | Candlestick, waterfall, ribbon, funnel | Mock host |
| **Atlas Gauges** (Cards merged in) | Card, multi-row card, KPI, gauge, dial, radial bars, liquid fill, bullet, ticker | Mock host |
| **Atlas Text** | Word cloud, ranked words | Mock host |
| **Atlas Lines** | Line, area, stacked/100% area, line + column combos | Mock host |
| **Atlas Parts** | Pie, donut | Mock host |
| **Atlas Scatter** | Scatter/bubble (play axis), dot plot, Gantt | Mock host |
| Themes (4) | Built-in visuals (container look) + every Atlas visual (look, palette, optional font) | Schema-valid |
| Test report | All 13 visuals on 12 pages, one related model | Schema-valid; open in Power BI to check |

## Next

1. Open the test report (`make report`) in Power BI and check each page; fix what real Power BI shows differently (see `docs/TESTING.md`, "Not covered by the mock host").
2. Known gaps: small multiples (Lines, Columns), Venn with 4+ sets, sunburst corner radius, drill-down in Hierarchy uses in-visual zoom rather than `host.drill`.
3. More locales in `stringResources/`, on-object formatting, certification preparation.

## Families as planned (all built)

The gallery has 84 visuals in 19 categories (`gallery/src/catalog.js`; the number in brackets is how many variants the gallery shows). Each family below is one `.pbiviz` with a chart-type switch, sharing `visuals/common/`.

### Custom (AppSource-style) visuals

1. ~~**Atlas Distribution**~~ (built 3 Nov 2026, see `docs/ARCHITECTURE.md`): Histogram (4), Box and whisker (4), Violin and raincloud (3), Parallel coordinates (2).
   - Roles: a category (optional), a value measure, and a detail field to get one row per observation.
   - Settings for bin count or width, whiskers (1.5 IQR or min/max), outliers, jitter, kernel bandwidth.
   - Reduce to about 30k rows and show a warning.
2. **Atlas Compare**: Lollipop and dot plot (3), Dumbbell (3), Slope (2), Bump (2), Tornado (2), Radar (3).
   - Roles: category, two or more measures (or a legend), period for slope and bump.
3. **Atlas Hierarchy**: Org chart and hierarchy tree (3), Sunburst (3), Circle packing (2), and a Treemap rebuild (built-in: 5).
   - Roles: hierarchy levels (Grouping, drillable), or parent and child IDs for the org chart; size measure.
   - Drill-down and zoom into a node.
4. **Atlas Proportion**: Mekko (2), Waffle (3), Pictogram (2), Aster plot (2), Rose / polar area (2), Venn (2).
   - Pictogram icons must be built-in SVG paths (no network).
5. **Atlas Calendar & Time**: Calendar heatmap (2), Heat grid and punch card (2), Stream graph (2), Timeline slicer (2).
   - The timeline slicer must filter the report: use the `applyJsonFilter` API with a `general.filter` object and the slicer's data roles.
6. **Atlas Finance**: Candlestick (2, roles open/high/low/close/date), plus rebuilt Waterfall (6), Ribbon (4) and Funnel (6) from the built-in "Rank, flow & change".
7. **Atlas Gauges**: Liquid fill (2), Radial bar (2), Tachometer / dial (2), Ticker and scroller (2), Bullet chart (3), plus rebuilt Gauge (6) and KPI (6).
   - Roles: value, target, minimum, maximum, bands.
8. **Atlas Text**: Word cloud (2) (tokenize text, stop words, rotation options, deterministic layout).

### Rebuilt built-in visuals (for comparison, with drill-down)

9. **Atlas Lines**: Line (17), Area (6), Stacked area (5), 100% stacked area (4), Line and stacked column (6), Line and clustered column (6).
   - Date hierarchy drill-down, markers, forecast and error bands, zoom slider.
   - Follow the built-in behavior for the combo charts' second axis.
10. **Atlas Parts**: Pie (7), Donut (7) (the treemap goes in Hierarchy).
11. **Atlas Scatter**: Scatter, bubble and dot plot (13), with a play axis, and Gantt (8).
12. **Atlas Cards**: Card (8), Multi-row card (4), Goals (4) (consider merging with Gauges).

### Probably not as custom visuals

- Maps: Azure Maps, Bing, ArcGIS, filled map and shape map. Tiles need network access (not certifiable, `privileges` needed). A shape map with embedded TopoJSON is possible later.
- Tables and matrices, slicers, AI visuals, Power Apps, Power Automate, R and Python, paginated reports, and report elements. These are host features or are better served by the built-ins.
- Build your own (Deneb, SVG measures, HTML content): these are techniques, not visuals.

## Improvements to the pilot (after feedback)

Atlas Columns:

- Small multiples
- A line overlay (or leave that to Atlas Lines)
- A zoom slider on the category axis
- Selecting a category by clicking its axis label
- `fetchMoreData` beyond 5,000 categories
- Label collision handling for clustered outside labels
- Legend paging instead of "+N"
- Error bars
- Sub-selection (on-object formatting) support

Atlas Flow:

- More than two path columns (multi-stage Sankey from a Path role)
- Node ordering options (by value or alphabetical)
- Link labels
- Draggable nodes (persist with `persistProperties`)
- Better label placement in a dense chord
- A performance cap for large networks

Both:

- More locales in `stringResources/`
- On-object formatting
- Certification preparation (public repository, README, privacy statement, AppSource listing assets) if the user wants PowerPoint export and email subscriptions

## How to add a family (checklist)

1. `cd visuals && pbiviz new AtlasXyz && cd atlasXyz && npm i powerbi-visuals-utils-formattingutils@6.1.2` (add `powerbi-visuals-utils-dataviewutils@6.1.0` for fx).
2. Fill `pbiviz.json` (displayName "Atlas Xyz", description, author "Visual Atlas" / atlas@example.com, supportUrl), add `assets/icon.png` (20×20) and `stringResources/en-US/resources.resjson`.
3. Write `capabilities.json`, `src/settings.ts` (with `tidy()`), `src/model.ts`, `src/render.ts`, `src/visual.ts`. Start from Atlas Columns' visual.ts for the host wiring.
4. Add `visuals/test/xyz_cases.js` (cover every chart type × look, dark, high contrast, highlights, landing page, edge cases) and a step in `scripts/test.sh`.
5. `make build test`, then look at the screenshots and fix what you see.
6. Update `docs/HISTORY.md`, `docs/ARCHITECTURE.md` and the README tables.
