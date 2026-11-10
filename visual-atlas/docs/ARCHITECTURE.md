# Architecture

## Custom visuals (`visuals/`)

Each visual is a standard pbiviz project (created with `pbiviz new`, API 5.11.1). The shared code sits in `visuals/common/`, and `sync.sh` copies it into each project, because pbiviz/webpack only bundles files inside the project folder.

### Shared code: `visuals/common/`

| File | What it does |
|---|---|
| `color.ts` | Color engine. `hex2rgb`, `lch` (OKLCH), `hexOf` (gamut-clipped), `mix`, `luminance`, `contrast`, `inkOn` (white or near-black text on a fill), `separation` (normal and color-blind ΔE), `adapt(hex, dark)` (pulls a color into the readable lightness band for light or dark backgrounds), `generate(brand, mode, count)` (Spectrum / Analogous / Mono palettes, greedy pick for separation, cached), `parseColors(text)` (hex list or a pasted theme JSON's `dataColors`), `check(pal)` |
| `look.ts` | `el(tag, attrs, parent, text)` builds SVG with createElementNS/textContent; `clear`, `r1` (round to 0.1); `textW(text, size)` measures with a canvas in `FONT_STACK` at weight 600 (cached); `trunc` (binary-search ellipsis). `class Look`: `reset(name, shadowColor, strength)` recreates `<defs>`: filters `sh` (soft shadow), `sh3` (3D shadow), `glow`. `fill(color, "v"/"h"/"r")` returns a cached gradient url in Soft/3D or the plain color in Flat; `linkGradient(a, b, x0, x1)`; `side(c)` / `top(c)` for 3D faces; `shadow()`, `glow()`. Ids use the prefix given by the visual (`atlc<n>-`, `atlf<n>-`) with a per-instance counter |
| `util.ts` | `colorer(palette options, host, dark)` returns `(key, index) => color`: high contrast uses the foreground; brand/custom use generated or pasted colors (adapted for dark); theme uses `host.colorPalette.getColor(key)`. `isDark(host)`. `formatter(format, units, decimals, sample, culture)` wraps `valueFormatter`. `autoUnit`. `labelFormatter` gives about 3 significant digits with no trailing zeros. `axisFormatter` uses one unit per axis and only the decimals the step needs. `nameFormatter` formats category and series values (dates, numbers, `(Blank)`). `landing(root, title, lines)` |
| `atlas.less` | Shared styles: `.atl`, `.atl-svg`, label halo `.lbl` (stroke `var(--atl-halo)` = surface color), `.dim` (opacity .22), hover and focus, `.atl-landing` |

### Atlas Flow (`visuals/atlasFlow`)

- **capabilities.json**
  - Roles: `source`, `target` (Grouping), `weight` (Measure), `tooltips` (Measure).
  - Categorical mapping: categories select source and target (top 30,000 rows), values select weight and tooltips. Conditions: max 1 each.
  - Objects: `chart` (chartType sankey/chord/network, look, shadow), `palette` (source, brand, mode, custom), `nodeColors` (fill, per node), `nodes` (width, padding, radius, align, sizeBy, maxSize), `links` (colorBy, opacity), `labels` (show, fontSize, color, showValues, displayUnits, decimals), `chord` (padAngle, arcWidth, ribbonOpacity), `network` (colorBy, labelCount, spacing).
  - Supports highlight, landing page, empty data view, keyboard focus and multi-visual selection; `privileges: []`.
- **src/model.ts**: `FNode` (key, name, in/out value, degree, color, selection id, layout fields), `FLink` (source and target index, value, highlight, row, selection id, tooltip items), and `Ctx`, the context shared by the renderers.
- **src/visual.ts**: `read()` builds nodes and links from the data view:
  - A node's selection id comes from its first row's category. Its color override comes from `col.objects[row].nodeColors.fill`.
  - A link's selection id combines both categories at that row.
  - Highlights come from `weight.highlights`.
  - The Format pane gets one color picker per node (first 60).
  - `draw()` dispatches to `drawSankey`, `drawChord` or `drawNetwork`. `bind()` wires tooltips, select, multi-select, context menu and keyboard.
- **src/sankey.ts**:
  - Columns come from a Kahn longest-path pass; back links are flagged and skipped. "Justify" pushes sinks to the last column.
  - Room is reserved for last-column labels. `ky` is the minimum over columns, and node spacing shrinks when there are too many nodes.
  - `stack()` resolves collisions; six barycenter relaxation passes follow. Then link slots, link paths, and nodes as rects or 3D prisms with labels.
- **src/chord.ts**: directed chord. Each node's arc holds its outgoing then incoming slots, so a ribbon keeps the same width at both ends.
- **src/network.ts**: d3-force (300 ticks, deterministic), label-propagation communities, fit to the viewport, top-N labels with collision checks, and neighbour highlighting on selection.
- **src/settings.ts**: formatting-model cards. `tidy()` hides settings for the other chart types and palette sources.

### Atlas Columns (`visuals/atlasColumns`)

- **capabilities.json**
  - Roles: `category` (Grouping, drillable), `series` (Grouping, the legend), `values` (Measure, several allowed), `tooltips` (Measure).
  - `"drilldown": {"roles": ["category"], "canDisableDrill": {"disabledByDefault": false}}` and `"sorting": {"default": {}}`.
  - Mapping: categorical; categories `for in category` (top 5,000); values `group by series` with `select [for in values, for in tooltips]` (top 60 series).
  - Conditions: `{category max 1, series max 0}` (any number of measures), or `{category max 1, series max 1, values max 1}`.
  - Objects: `chart`, `palette`, `dataColors`, `labels`, `totals`, `categoryAxis`, `valueAxis`, `gridlines`, `legend`, `refLine` (`objectCategory: 2`, the Analytics pane), `drill`.
- **src/model.ts**: `readModel(dataView, host)`
  - `Cat`: one per row. Its path holds one value per category column (an expanded hierarchy sends several columns). Selection id = `withCategory` for every category column. `override` = a color from objects, including evaluated fx rules.
  - `Ser`: legend groups (`withSeries(values, group)`, color from `group.objects`) or measures (`withMeasure(queryName)`, selector `{metadata: queryName}`, color from `column.source.objects`).
  - `Pt`: one per category and series with a value. Selection id = categories + series or measure. Holds highlight and tooltip items.
  - `drill` = `metadata.dataRoles.drillableRoles.category`.
- **src/layout.ts**: `stackUp(model, mode)` gives each point its value-space start and end (`a`, `b`). Positive and negative values stack separately; 100% divides by the category's absolute total. It also sets `share`, `base` and `outer` flags (for rounding the outer ends) and category totals. `nice()` makes 1-2-5 ticks. `refValue()` handles average, median, min, max and constant. `parseNum()` reads the axis start and end text.
- **src/render.ts**: `render(env)` draws one frame onto four layers:
  - `back` SVG (gridlines, value axis, titles; holds `<defs>`)
  - `scroller` div with the `front` SVG (bars, labels, category axis). It scrolls when categories don't fit, at a minimum step of font size + 3 px for columns or 1.25 × font size for bars.
  - `over` SVG (legend and reference line, `pointer-events: none` except the legend's hit rects)
  - an HTML drill bar
  - What gets laid out and drawn:
    - Legend: top, top center, bottom, bottom center or right; wraps up to 3 rows, then "+N".
    - Value domain and ticks; the plot rectangle; category label mode (flat, two-line wrap, or rotated −45° with skipping); hierarchy tiers, with separators.
    - Bars: `rpath()` gives rounded data ends. Pill and lollipop shapes. In 3D, the side and top faces are sorted and drawn before the fronts.
    - Highlights draw a ghost bar plus the highlighted part. Stacked segments get a 2 px gap.
    - Data labels in 5 positions; inside labels use `inkOn`. Totals; reference line.
- **src/visual.ts**:
  - Builds the layers. Wheel over a wide chart scrolls sideways. Calls `setCanDrill` for "Allow drilling".
  - `colorize()` sets palette colors and the dataColors slices: per category with fx, a single "Default color" with fx, or per series.
  - Selection keys: `p<c>|<s>` for points, `s<i>` for series. `syncSelection(ids)` (bookmarks, other visuals) maps ids back to keys with `equals`.
  - `drawDrill()` creates the buttons, each calling `host.drill`. `tooltip()` lists category levels, series, value, share, highlighted value and tooltip measures.
  - Shows a warning icon at 5,000 categories.
- **src/settings.ts**: cards Chart, Palette, Colors (dynamic), Data labels, Total labels, Category axis, Value axis, Gridlines, Legend, Reference line (analytics pane), Drill-down. `tidy({series, levels, drillable})` hides settings that don't apply: shadow when flat, radius unless rounded, totals unless stacked, legend for one series, start and end for 100%, outside-end label position for stacked.

### Atlas Distribution (`visuals/atlasDistribution`)

- **capabilities.json**
  - Roles: `category` (Group, Grouping, optional), `detail` (Sample by, Grouping), `values` (Measure, several), `tooltips` (Measure).
  - Categorical mapping: categories select Group and Sample by (top 30,000 rows); values select values and tooltips. Conditions: category max 1, detail max 1.
  - Objects: `chart` (chartType histogram/box/violin/parallel, look, shadow, orientation, sort), `palette`, `dataColors` (per group), `histogram`, `box`, `violin`, `points`, `parallel`, `labels`, `categoryAxis` (the group axis), `valueAxis`, `gridlines`, `legend`, `stats` (mean and median lines, `objectCategory: 2`).
- **src/model.ts**: `readModel(dv, host, chartType)` returns:
  - `Obs`, one per row: values per measure, label, selection id from every category column, tooltip items, highlight flag.
  - `Group`: one per Group value (`withCategory` id), or one per measure (`withMeasure`) when there is no Group and several measures, or a single group.
  - Statistics: `stats()` (type-7 quantiles, whiskers by rule, outliers), `kde()` (Gaussian, Silverman bandwidth × smoothing, a 4h window found by binary search), `binning()` (auto 1-2-5 width, count or width), `jitter(i)` (an integer hash).
- **src/render.ts**: `render(env)` draws into one SVG: the legend (histogram and parallel), then one of:
  - `histogram()`: counts per group and bin, overlapping (with opacity) or stacked, count or percent; a ghost bar plus a solid part for highlights and selection; normal curves, total labels, mean and median lines.
  - `boxOrViolin()`: works in (group offset, value) space through `P(u, v)`, so vertical and horizontal share one code path. Boxes (3D faces, whiskers, outliers, mean diamond, jittered or beside points) or violins (full or half, inner box or quartiles, jitter or barcode points).
  - `parallel()`: one axis per measure (own or shared scale), straight or smooth lines, dimmed lines drawn first. Events are bound only up to 3,000 lines and 4,000 points.
  - Every interactive mark goes through `env.bind(el, Target)`. A `Target` holds its key, observation indexes, selection ids and a tooltip builder.
- **src/visual.ts**: host wiring as in Columns. Selection is a map from picked targets to observations. `active` (the selection, else the highlighted observations) drives dimming. `syncSelection` maps ids back through groups and observations.
- **src/settings.ts**: `tidy({groups, measures})` hides what doesn't apply:
  - only the current chart type's card shows
  - bin count or bin width, by bins mode
  - overlap opacity, only with several groups
  - the legend, for histogram and parallel with groups
  - the points card, only when points are drawn

### Family visuals (Compare, Hierarchy, Proportion, Time, Finance, Gauges, Text, Lines, Parts, Scatter)

The newer visuals share one layer in `visuals/common/` and differ only in their own `caps.js`, `src/settings.ts`, `src/model.ts` (when the shared matrix isn't enough), `src/render.ts` and a short `src/visual.ts`:

- `caps.js` → `tools/mk_caps.js` → `capabilities.json`: roles, data mapping and chart objects; the shared objects (style, palette, dataColors, labels, categoryAxis, valueAxis, gridlines, legend) are added the same way everywhere. `visuals/sync.sh` runs it.
- `common/family.ts` `FamilyVisual<S, M>`: update flow, landing page, rendering events, row-limit warning, palette and the Colors card (`model.colored`), selection sync (`model.ids`, `model.hl`), Style card (font, text color, `setFont`), look, `grow()` for scrolling. A family implements `newSettings`, `read`, `draw`, `tidy`, and optionally `describe` and `destroy`.
- `common/interact.ts` `Interact`: `bind(element, Target)` gives tooltips, select, Ctrl multi-select, context menu and Enter/Space; `active` is the selection, else the highlights; `on(i)`, `anyOn(items)` drive dimming.
- `common/cards.ts`: shared Format pane cards. `common/chart.ts`: `nice`, `domain`, `valueAxis`, `legend`. `common/matrix.ts`: category × series reader (multi-level categories, drill info). `common/drill.ts`: drill buttons and `setCanDrill`. `common/data.ts`: role columns, colors from objects, tooltip items.

| Visual | Model | Notes |
|---|---|---|
| Compare | `common/matrix` | Lollipop/dot/dumbbell share a band layout `P(u, v)`; slope and bump labels are spread so they don't overlap |
| Hierarchy | own tree (levels or ID/parent) | d3-hierarchy layouts; `View` keeps the zoom path and open branches |
| Proportion | `common/matrix` (`measuresAreParts`) | Venn layout solves circle overlaps numerically; labels at the deepest point of each region |
| Time | own (time × rows × series) | Timeline writes an `AdvancedFilter` (powerbi-models 1.15.2) with `applyJsonFilter`, reads `options.jsonFilters` |
| Finance | `common/matrix` + candles | Waterfall breakdown mode with a Legend |
| Gauges | own item list | One tile per item; ticker is a CSS animation |
| Text | own word list | Spiral placement with box collisions, shrinking to fit |
| Lines | own (multi-level, series by role) | Hover bands per category; forecast and anomaly math in `render.ts` |
| Parts | `common/matrix` | Outside labels in two columns with leader lines |
| Scatter | own (points or tasks) | k-means clusters, drag zoom, play timer (stopped in `destroy`) |

### Styling per visual

`style/visual.less` imports `atlas.less` and adds the visual's own rules (Columns: layers, scroller, legend hit area, ghost, label weights, drill buttons).

### Adding a family visual (pattern)

1. `cd visuals && pbiviz new AtlasXyz`, then `npm i powerbi-visuals-utils-formattingutils@6.1.2` (and dataviewutils if you need fx).
2. In `pbiviz.json`, set displayName, description, author (`Visual Atlas`, `atlas@example.com`) and supportUrl. Keep the generated GUID forever.
3. `capabilities.json`: roles, mapping, objects (one object per Format card), tooltips, the `supports*` flags, `privileges: []`, and drilldown where a category role exists.
4. `src/settings.ts`: cards, with a `tidy()`. `src/model.ts`: read the data view into plain arrays with selection ids. `src/render.ts`: pure drawing. `src/visual.ts`: host wiring, copied from Atlas Columns (bind, selection sync, tooltips, landing, rendering events, warnings).
5. `stringResources/en-US/resources.resjson` and `assets/icon.png` (20×20).
6. Test cases in `visuals/test/<name>_cases.js` and a step in `scripts/test.sh`.

## Gallery (`gallery/`)

One HTML page built by concatenating the scripts in `gallery/src` and inlining them into `shell.html` (`gallery/scripts/build.mjs`). Load order: geo, data, layouts, engine, engine-maps, engine-html, engine-x1, engine-x2, glyphs, catalog, catalog-x, brand, look, app.

| File | Role |
|---|---|
| `data.js` | Deterministic sample data (seeded RNG): months, this year and last year, products, regions, channels, and the HD (date), HP (product) and geo hierarchies |
| `geo.js`, `layouts.js` | Precomputed map geometry and circle-packing/force layouts (generated by `scripts/gen-geo.mjs` and `scripts/gen-layouts.mjs` from the npm packages listed in `gallery/geo/package.json`; run `npm install` in `gallery/geo` first) |
| `engine.js` | SVG chart engine; every renderer returns markup for (options, state, W, H); 3D prisms |
| `engine-maps.js`, `engine-html.js` | Maps; tables, cards and slicers as HTML |
| `engine-x1.js`, `engine-x2.js` | Renderers for the non-standard visuals |
| `catalog.js`, `catalog-x.js` | `CATS` (19 categories) and `VIS` (84 visuals; each has id, name, category, goals, best use, wells, uses, avoid, and variants `v`) |
| `brand.js` | `BRAND`: palette engine, tokens, `themeObject(look, dark)` / `themeJSON()` (Power BI theme export) |
| `look.js` | `LOOK`: Flat, Soft and 3D gradients and CSS |
| `app.js` | The page UI: navigation, search, lazy rendering, drill, zoom, brush, pan, play, tooltips, focus mode, theme studio |

The gallery is a demo page, not a visual: it uses HTML strings and `innerHTML` freely. The custom-visual rules don't apply to it.

## Themes (`tools/mk_themes.js` → `visuals/themes/`)

`mk_themes.js` runs `gallery/src/brand.js` in a Node vm and writes `themeJSON(look, dark)` for flat, soft, 3d and soft-dark. Set `BRAND_COLOR` / `PALETTE` to generate brand themes. `tools/validate_themes.py` validates them against `tools/schema/reportThemeSchema-2.159.json`.
