# Visual Atlas custom visuals for Power BI

Thirteen Power BI custom visuals, each a family of chart types with a chart-type switch, and report themes that style all of them. Every visual has Flat, Soft and 3D looks, a Style card (font, text color) and a palette from the report theme, a brand color or your own list. `../CUSTOMIZING.md` explains how to change design and colors.

| File | Chart types |
|---|---|
| `../release/AtlasColumns.<version>.pbiviz` | Clustered, stacked and 100% stacked columns and bars, with drill-down |
| `../release/AtlasLines.<version>.pbiviz` | Line, area, stacked and 100% area, line + column combos, with drill-down, forecast, anomalies and a zoom slider |
| `../release/AtlasParts.<version>.pbiviz` | Pie and donut, with drill-down, details ring, top N, half donut, center total |
| `../release/AtlasFlow.<version>.pbiviz` | Sankey, chord and network |
| `../release/AtlasDistribution.<version>.pbiviz` | Histogram, box and whisker, violin and raincloud, parallel coordinates |
| `../release/AtlasCompare.<version>.pbiviz` | Lollipop, dot plot, dumbbell, slope, bump, tornado, radar |
| `../release/AtlasHierarchy.<version>.pbiviz` | Treemap, sunburst, circle packing, org chart / tree (zoom, open and close) |
| `../release/AtlasProportion.<version>.pbiviz` | Mekko, waffle, pictogram, aster, rose, Venn |
| `../release/AtlasTime.<version>.pbiviz` | Calendar heatmap, heat grid / punch card, stream graph, timeline slicer (filters the report) |
| `../release/AtlasFinance.<version>.pbiviz` | Candlestick, waterfall, ribbon, funnel |
| `../release/AtlasGauges.<version>.pbiviz` | Card, multi-row card, KPI, gauge, dial, radial bars, liquid fill, bullet, ticker |
| `../release/AtlasText.<version>.pbiviz` | Word cloud, ranked words |
| `../release/AtlasScatter.<version>.pbiviz` | Scatter, bubble (play axis, quadrants, clusters, zoom), dot plot, Gantt |
| `themes/atlas-theme-*.json` | Report themes (Flat, Soft, 3D and Soft Dark) for built-in visuals and every Atlas visual |
| `common/` | Shared code: colors, looks, Format pane cards, legend, axes, selection, drill buttons |
| `test/` | A mock host that renders the packaged visuals in a browser, with test cases and checks per visual; `test/sample-data/` has CSV files |

## Fields of the newer visuals

| Visual | Fields |
|---|---|
| Atlas Lines | X-axis (a date hierarchy drills), Legend, Y-axis, Line y-axis (combos), Lower and Upper bound (error band), Tooltips |
| Atlas Parts | Legend (slices, drillable), Details (outer ring), Values, Tooltips |
| Atlas Compare | Category, Legend, Values (two measures for dumbbell, slope, tornado), Tooltips |
| Atlas Hierarchy | Levels (Category › Subcategory › Product), or ID, Parent ID and Label for an org chart; Size, Color value, Tooltips |
| Atlas Proportion | Category (Venn: "A & B" for overlaps), Legend, Values (a second measure is the total or weight), Tooltips |
| Atlas Time | Time (a date, or the heat grid columns), Rows (heat grid), Legend (stream), Values, Tooltips |
| Atlas Finance | Category, Legend (ribbon, waterfall breakdown), Values; Open, High, Low, Close and Volume (candlestick); Tooltips |
| Atlas Gauges | Category (one tile per value), Trend axis (KPI), Value, Target, Minimum, Maximum, Band 1, Band 2, Tooltips |
| Atlas Text | Text (phrases or free text), Topic, Weight, Color value (sentiment), Tooltips |
| Atlas Scatter | Values (details), Legend, X-axis category (dot plot), Play axis, X-axis, Y-axis, Size; Task, Start date, End date, Owner, % complete (Gantt); Tooltips |

Every role has a description in the Fields pane, and each visual shows a start screen that says which fields to add.

## Interactions (every visual)

| What you do | What happens |
|---|---|
| Click a mark (bar, slice, point, tile) | Selects it and cross-filters the page. Ctrl+click adds more |
| Click an axis label, category name or legend item | Selects everything it names (a whole month, a product, a series) |
| Click in several visuals | Each keeps its selection, so they filter the page together (Style › *Keep other visuals' selections*, on by default) |
| Select something in another visual | Atlas visuals show the selected part, like a filter: cards, gauges and KPI show the selected numbers, donuts and treemaps redraw from them. When whole items are picked on the same field, the rest fades instead. Lines and scatter points move to their selected values |
| Watch the top-right corner | A colored * shows while the visual has a selection or applies a filter; click it to clear just that visual. Drill buttons and *Reset zoom* sit in the same corner |
| Drill (Columns, Lines, Parts) | Drill up, next level, expand all, **back to the top level**, and **clear selection** buttons; drilled names read "2024 › Qtr 1" |
| Zoom | Hierarchy: click a group to zoom in, **‹ Back** or the path (All › Bikes › Road) to zoom out. Lines: zoom slider, mouse wheel, drag across the plot to select a range; with *Zoom to the selection* it zooms to what's selected here or elsewhere. Scatter: drag a box. *Reset zoom* or double-click shows everything again |
| Hover | Tooltips (default and report-page tooltips); the hand cursor shows only over things a click selects |

Keyboard: Tab to a mark, Enter or Space selects, the context menu key (or right-click) opens Power BI's menu.

## Add a visual to a report

1. Open the report in Power BI Desktop or the Power BI service.
2. In the **Visualizations** pane, select **…** (More options) and then **Import a visual from a file**.
3. Pick the `.pbiviz` file and confirm the import. The visual appears as a new icon in the Visualizations pane.
4. To keep it for future reports, right-click the icon and select **Pin to visualization pane**.

Microsoft's import guide also says to turn on developer mode in Power BI Desktop before importing from a file (it resets each session). In the Power BI service, the tenant setting **Allow visuals created using the Power BI SDK** must be on, or an admin can add the files to the organizational visuals store instead.

These visuals are not certified by Microsoft. Certified visuals can, for example, be exported to PowerPoint and shown in email subscriptions; uncertified ones can't.

## Atlas Columns

**Fields**

- **Category axis**: one field, or a hierarchy such as Year › Quarter › Month.
- **Legend**: optional field that splits each bar into series (with one value).
- **Values**: one or more measures (several measures become several series).
- **Tooltips**: extra measures shown on hover. Report page tooltips work too.

**Drill-down** works the same way as the built-in charts:

- Put a hierarchy (or several fields) in **Category axis**.
- Use the drill icons in the visual header, right-click a bar and pick **Drill down**, or turn on drill mode and click a bar.
- The visual also has its own buttons (top right): **Drill up**, **Go to the next level** and **Expand all down one level**. They use the Drilldown API and can be hidden under **Format › Drill-down**.
- When a level is expanded, the category labels show the hierarchy as tiers (2024 under Qtr 1–4). Turn on **Category axis › Concatenate labels** for "2024 Qtr 1" instead.

**Format pane** (everything is a setting; options that don't apply to the current chart are hidden):

| Card | Settings |
|---|---|
| Chart | Chart type (6), Look (Flat / Soft / 3D), Shadow strength, Bar shape (Rounded ends / Square / Pill / Lollipop), Corner radius, Space between categories, Space between bars |
| Palette | Colors from: Report theme, Brand color (Spectrum / Analogous / Mono), or Custom list (hex codes or a pasted theme JSON); Color each category |
| Colors | One color per series, or per category. With one series, colors support **fx** conditional formatting (rules, gradients, field values) |
| Data labels | Position (Auto, Inside end, Inside center, Inside base, Outside end), Show value / percent / both, Text size, Color, Display units, Decimal places |
| Total labels | Totals on stacked charts |
| Category axis | Text size, Color, Concatenate labels, Maximum label area, Title |
| Value axis | Text size, Color, Display units, Decimal places, Start, End, Title |
| Gridlines | Color, Line style, Width |
| Legend | Position (Top, Top center, Bottom, Bottom center, Right), Text size, Color, Title |
| Reference line (Analytics pane) | Average, Median, Min, Max or a constant value, Color, Line style, Label |
| Drill-down | Drill buttons on the visual, Allow drilling |

Also supported: cross-filtering and cross-highlighting, multi-select with Ctrl, the right-click menu, **Sort axis** from the visual's … menu, keyboard focus (Tab, Enter), high contrast mode, light and dark report backgrounds, and horizontal or vertical scrolling when there are more categories than fit.

## Atlas Flow

**Fields**: **Source**, **Target**, **Weight** (a measure) and optional **Tooltips**.

**Format pane**: Chart type (Sankey / Chord / Network), Look, Shadow strength, Palette (same three sources), one color per node, node width, spacing, corners and alignment (Sankey), node size by value or connections and community coloring (Network), link coloring (source, target, gradient, neutral) and opacity, chord gap, arc width and ribbon opacity, and labels with display units.

Flows that loop back to an earlier stage can't be drawn in a Sankey; the visual skips them and shows a warning icon. Chord and Network show them.

## Atlas Distribution

**Fields**: **Group** (optional, for example Carrier), **Sample by** (the field that identifies one observation, for example Shipment ID), **Values** (a measure; parallel coordinates uses one axis per measure) and optional **Tooltips**. Without Sample by, each Group value is one observation.

**Format pane**:

- **All chart types**: Chart type (Histogram / Box and whisker / Violin / Parallel coordinates), Look, Shadow strength, Palette (the same three sources) and one color per group.
- **Box and violin**: Orientation and Sort.
- **Histogram**: bins (auto, count or width), overlapping or stacked groups, opacity, count or percent, normal curve.
- **Box**: whiskers (1.5 × IQR, min–max, 5th–95th percentile), outliers, mean marker, points (jittered or beside).
- **Violin**: full or half (raincloud), box or quartile lines inside, jittered or barcode points, smoothing, width, trim.
- **Parallel coordinates**: shared or per-axis scales, straight or smooth lines, width, opacity, axis labels.
- **Also**: data labels, group and value axes, gridlines, legend, and mean and median lines in the Analytics pane.

The visual reads up to 30,000 rows and shows a warning icon when there are more.

## Themes

Import a theme in Power BI Desktop with **View › Themes › Browse for themes**.

- Every theme sets the 8 palette colors, text colors, the page background, and the container look of every visual: small corners and a thin border (Flat), larger corners and a soft shadow (Soft), or a deeper offset shadow (3D).
- The themes also set the default look of the two Atlas visuals.
- Built-in visuals only take the container look from a theme. Gradients, 3D bars and rounded bar ends are only possible in the custom visuals, which is why they were rebuilt.

To make a theme in your own brand colors, open the Visual Atlas page, set the brand color, palette and look in the theme studio, and select **Copy theme JSON**. Save the text as a `.json` file and import it the same way.

## Build from source

The easiest way is Docker, from the project root: `docker build -t visual-atlas -f docker/Dockerfile .` and then `docker run --rm -v "$PWD":/work -w /work visual-atlas make all` (see the root README).

Without Docker you need Node.js 18 or later:

```bash
npm install -g powerbi-visuals-tools@7.2.1
./sync.sh                      # copies the shared code in common/ into both visuals
cd atlasColumns && npm install && pbiviz package
cd ../atlasFlow && npm install && pbiviz package
cd ../atlasDistribution && npm install && pbiviz package
# ... and the same in every other atlas* folder (scripts/build.sh does all of them)
```

The packaged file is written to each project's `dist/` folder. To change the colors, looks or labels, edit the files in `common/` and run `./sync.sh` again before packaging.

To run the visual live in a report while editing, use `pbiviz start` and the Developer Visual in the Power BI service. See Microsoft's [developer environment setup](https://learn.microsoft.com/power-bi/developer/visuals/environment-setup).

## How it is built

- `common/color.ts`: the color engine. It generates brand palettes in OKLCH, keeps colors readable on light and dark backgrounds, and checks that neighbouring colors stay apart for color-blind readers.
- `common/look.ts`: the Flat, Soft and 3D looks (gradients, shadows, extruded faces), drawn as SVG.
- Every SVG element is created with `createElementNS` and `textContent`; no HTML strings are parsed and the visuals make no network requests (`privileges: []`).
