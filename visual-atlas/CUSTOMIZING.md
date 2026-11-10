# Customizing the Atlas visuals

Every Atlas visual is built from the same parts. The same settings, with the same names, control design and color in all of them. You can change them at four levels, from a single visual to the code:

| Level | Changes | Where | Who |
|---|---|---|---|
| 1. Format pane | One visual on one page | Power BI: select the visual › Format pane | Report authors |
| 2. Report theme | Every Atlas visual (and the built-in visuals) in a report | A theme `.json` file: View › Themes › Browse for themes | Report authors |
| 3. Brand theme generator | Themes for a new brand color, font or look | `make themes` with options, or the gallery's theme studio | Whoever owns the brand |
| 4. Code | Defaults, new options, new chart types | `visuals/common/` and each `visuals/atlas*/` | Developers |

Format pane settings (level 1) override the theme (level 2). The theme overrides the visual's built-in defaults (level 4).

---

## 1. In the Format pane

### Cards every Atlas visual has

| Card | Settings | Notes |
|---|---|---|
| **Chart** | Chart type, Look (Flat / Soft / 3D), Shadow strength, plus the chart's own layout options | Shadow is hidden for Flat |
| **Style** | Font, Text color, Keep other visuals' selections, Selection marker (*), Marker color, Also when another visual highlights it | *Keep other visuals' selections* (on by default): a plain click selects in this visual and leaves the selections in other visuals in place, so several visuals can filter the page at once (off: Power BI's usual behavior, where a click replaces the other visuals' selections; Ctrl+click still adds). Font and text color apply to every label, axis and legend in the visual (text color is ignored in high contrast mode). The marker is a small colored * in the top-right corner while you have something selected in the visual, or while it filters the report (Atlas Time's timeline slicer). Click the * to clear the selection or filter. Turn on the last option to also show a faded * while another visual's selection highlights this one |
| **Palette** | Colors from: *Report theme*, *Brand color* (+ Palette style: Spectrum, Analogous, Mono) or *Custom list* | Custom list: hex codes separated by commas or spaces, **or paste a whole theme JSON** (its `dataColors` are used) |
| **Colors** | One color picker per series, group or category | Overrides the palette for that item. It's stored with the report, so it survives refreshes |
| **Data labels** | On/off, text size, color, display units, decimal places | Decimals *Auto* (−1) gives about 3 significant digits |
| **Category axis**, **Value axis** | On/off, text size, color, title; value axis: display units, decimals, start, end | Start and end accept numbers like `1,200`; leave empty for Auto |
| **Gridlines** | On/off, color, style (solid, dashed, dotted), width | |
| **Legend** | On/off, position (top, top center, bottom, bottom center, right), text size, color, title | Only shown when there is more than one series |

Settings that don't apply to the current chart type are hidden, so the pane only shows what changes the picture.

### Cards per visual

| Visual | Chart types | Its own cards |
|---|---|---|
| **Atlas Columns** | Clustered, stacked, 100% stacked × column, bar | Bar shape (rounded, square, pill, lollipop), corner radius, spacing; Total labels; Reference line (Analytics pane); Drill-down; conditional formatting (fx) on Colors |
| **Atlas Lines** | Line, area, stacked area, 100% stacked area, line + stacked column, line + clustered column | Line shape (straight, smooth, stepped), zoom slider, zoom to the selection; Lines and columns (width, markers, dashed series, area opacity, names at line ends, focus, secondary axis, column spacing); Analytics pane (trend, min/max, average, target zone, forecast, anomalies); Drill-down |
| **Atlas Parts** | Pie, donut | Inner radius, start angle, half circle, order, top N + Other, gap; Slices and labels (outside with leader lines or inside, content, center total, progress-ring track); Drill-down |
| **Atlas Flow** | Sankey, chord, network | Nodes (width, padding, radius, alignment, size by), Links (color by source/target/gradient/neutral, opacity), Chord, Network |
| **Atlas Distribution** | Histogram, box and whisker, violin/raincloud, parallel coordinates | Histogram (bins, overlap/stacked, %, normal curve), Box (whiskers, outliers, mean, points), Violin (half, inner box/quartiles, points, smoothing), Data points, Parallel coordinates; Mean and median (Analytics pane) |
| **Atlas Compare** | Lollipop, dot plot, dumbbell, slope, bump, tornado, radar | Markers and lines (shape, size, stem/line width, color by series/category/sign, up/down colors), Tornado (mirror or base value), Radar (grid shape, levels, fill, max, one radar per series); Chart › Sort and Focus on |
| **Atlas Hierarchy** | Treemap, sunburst, circle packing, org chart / tree | Levels shown, click to zoom or select, label content; Color rules (branch, level, value gradient); Treemap (tiling, padding, headers, radius); Sunburst (hole, gap); Circle packing; Org chart (orientation, levels open, links, card size, badges, value bars) |
| **Atlas Proportion** | Mekko, waffle, pictogram, aster, rose, Venn | Label content, empty color, one per category; Waffle (grid, cell shape, gap, big number); Pictogram (icon, units per icon, per row, out of); Aster and rose (hole, gap, maximum, outline, center score, shade by value); Mekko (gap, radius, totals); Venn (opacity, separator) |
| **Atlas Time** | Calendar heatmap, heat grid / punch card, stream graph, timeline slicer | Color scale (by value or rank, low/high/no-data colors, steps, gap, radius); Calendar (year or month pages, week start, names); Heat grid (cells or punch-card circles); Stream (wiggle, silhouette, stacked, 100%, smooth, opacity); Timeline slicer (granularity, bars, selection color) — **it filters the report** |
| **Atlas Finance** | Candlestick, waterfall, ribbon, funnel | Candlestick (candles/OHLC/close line, up/down colors, volume, moving average, min width); Waterfall (start/end totals, total label, subtotals, increase/decrease/total colors, connectors, radius); Ribbon (opacity, column width, largest on top); Funnel (bars or tapered, label content, conversion rate, colors) |
| **Atlas Gauges** | Card, multi-row card, KPI, gauge, dial, radial bars, liquid fill, bullet, ticker | Columns, accent bar; Target and status (higher/lower is better, amber tolerance, good/close/off colors, color the value, show target); Trend (area, line, columns); Scale and bands (min, max, arc, width, bands, needle, ticks); Liquid fill; Bullet orientation; Ticker speed and direction |
| **Atlas Text** | Word cloud, ranked words | Words (keep phrases or split, remove common words, also remove, minimum length, maximum words, lowercase); Word cloud (rotation, smallest/largest text, size scale, spacing); Color rules (a color per word, one color, topic, value gradient) |
| **Atlas Scatter** | Scatter / bubble, dot plot, Gantt | Markers (shape, size, largest bubble, opacity, color by legend/one/clusters); Play axis (speed, loop); Gantt (progress fill/overlay, today line, weekends, bar height, owner and % columns, milestone color, radius); Guides and axes in the Analytics pane (quadrants, trend, ratio, symmetry, log X/Y, drag to zoom) |

### Colors in detail

- **Report theme** (default): the visual uses the report's theme colors, in the same order as the built-in visuals. Change the theme and the visual follows.
- **Brand color**: pick one color. The visual generates a 12-color palette from it:
  - *Spectrum*: distinct hues around the brand color
  - *Analogous*: neighboring hues
  - *Mono*: shades of the brand color

  Colors are spaced so neighbors stay distinguishable, including for color-blind readers.
- **Custom list**: paste `#0f766e, #d97706, #be123c` or a full theme JSON. If you give fewer than 12 colors, the visual adds generated ones.
- **Dark backgrounds**: brand and theme colors are pulled into a readable lightness range automatically. A custom list is used as typed on light backgrounds.
- **High contrast mode** (Windows): all marks use the system foreground and background colors, and the look switches to Flat. Series are told apart by position, labels and the legend.
- **Text on colored marks** (labels inside bars) switches between white and near-black for contrast. Text never uses series colors.

### Looks

| Look | What it does |
|---|---|
| **Flat** | Solid fills, no shadow |
| **Soft** | Gentle gradients, glossy markers, soft drop shadow (strength set by Shadow strength) |
| **3D** | Extruded side and top faces on bars and boxes, deeper shadow |

---

## 2. One theme for every Atlas visual

A Power BI report theme can set defaults for custom visuals, keyed by the visual's GUID. The themes in `release/themes/` already do this for **every** Atlas visual. Import one with **View › Themes › Browse for themes**, and every Atlas visual in the report takes:

- the theme's palette (Palette › Colors from = Report theme)
- the look (Flat, Soft or 3D) and shadow strength
- the font, when the theme was generated with one

The same themes also give the built-in visuals the matching container look: corners, border and shadow.

### Theme file structure

The Atlas part of a theme lives under `visualStyles`. Each key is a visual's GUID; `"*"` means "every style preset". Each object name and property name matches a Format pane card and setting:

```json
{
  "name": "My brand",
  "dataColors": ["#0F766E", "#D97706", "#BE123C", "#4338CA", "#15803D", "#7C3AED", "#0E7490", "#B45309"],
  "visualStyles": {
    "atlasColumns9A01238C3D0249F7B4F9DFBEA84D3599": {
      "*": {
        "chart":   [{ "look": "3d", "shadow": 70 }],
        "style":   [{ "fontFamily": "Georgia", "textColor": { "solid": { "color": "#1F2937" } } }],
        "palette": [{ "source": "theme" }],
        "legend":  [{ "position": "bottomCenter", "fontSize": 11 }],
        "labels":  [{ "show": true, "fontSize": 9 }],
        "gridlines": [{ "style": "dotted" }]
      }
    }
  }
}
```

Repeat the block for each GUID you want to style. Any setting from the tables above can go in, using the object and property names in the visual's `capabilities.json`:
- `chart.chartType`, `chart.look`, `chart.shadow`
- `style.fontFamily`, `style.textColor`
- `palette.source` / `brand` / `mode` / `custom`
- `labels.*`, `categoryAxis.*`, `valueAxis.*`, `gridlines.*`, `legend.*`
- each visual's own cards, such as `histogram.normalCurve`, `radar.grid`, `marks.shape`

Value formats:
- **Colors:** `{ "solid": { "color": "#hex" } }`
- **Enumerations:** their value as a string, for example `"look": "soft"` or `"position": "bottomCenter"`
- **Numbers and booleans:** plain JSON

### GUIDs

| Visual | GUID |
|---|---|
| Atlas Columns | `atlasColumns9A01238C3D0249F7B4F9DFBEA84D3599` |
| Atlas Lines | `atlasLines36E69B273DB443A5AF8E62CB16DB4547` |
| Atlas Parts | `atlasPartsA0676FD0579D44EFB545170E4799ADC9` |
| Atlas Flow | `atlasFlowBA37FC4A61814B33BF815C11D35148B1` |
| Atlas Distribution | `atlasDistribution1C4252B29C654CC1BF16155962622408` |
| Atlas Compare | `atlasCompare1934AF42622F4D63BF12168C02806AC8` |
| Atlas Hierarchy | `atlasHierarchy21AE4CB2A0F74216862D09F0C9A3BF2E` |
| Atlas Proportion | `atlasProportion74F95B1AE3CB4D9195CC248A3EC140A4` |
| Atlas Time | `atlasTime657C41A78B0A405A998ADA36387448E9` |
| Atlas Finance | `atlasFinance8C601CA9CAF44ADCB6574FA21FDDE583` |
| Atlas Gauges | `atlasGauges797C4E4189814B78AD7FCCDFF53CBC47` |
| Atlas Text | `atlasTextC961F02E238E426A825D8355E3503AA9` |
| Atlas Scatter | `atlasScatter0B23674C661C4797A349BBC2B0AD313A` |

The GUID of any visual is in `visuals/<visual>/pbiviz.json` (`visual.guid`). GUIDs never change, so themes and reports keep working across versions.

---

## 3. Make themes for your brand

The theme generator builds four themes (Flat, Soft, 3D, Soft Dark) from one brand color. It writes them for every Atlas visual in `visuals/`, plus the built-in visuals:

```bash
docker run --rm -v "$PWD":/work -w /work -e BRAND_COLOR=#0f766e -e PALETTE=analogous -e ATLAS_FONT="Segoe UI Semibold" -e ATLAS_SHADOW=40 visual-atlas make themes
```

| Variable | Meaning | Default |
|---|---|---|
| `BRAND_COLOR` | Your main color, `#rrggbb` | the Atlas blue |
| `PALETTE` | `spectrum`, `analogous` or `mono` | `spectrum` |
| `ATLAS_FONT` | Font for every Atlas visual's text (a font available in Power BI) | the report font (Segoe UI) |
| `ATLAS_SHADOW` | Shadow strength 0–100 for Soft and 3D | 55 |

On Windows PowerShell, use `-v "${PWD}:/work"`. The files land in `visuals/themes/` and `release/themes/`, and are validated against Microsoft's theme schema. In Claude Code, `/brand-theme #0f766e analogous` does the same.

Without Docker, open the gallery page (`release/power-bi-visual-atlas.html`) and use its theme studio: set the brand color, palette and look, then click **Copy theme JSON**.

---

## 4. Change the code

Shared code lives in `visuals/common/`. `visuals/sync.sh` copies it into each visual at build time. **Edit `visuals/common/`, never the copies in `visuals/*/src/common/`.**

| To change… | Edit |
|---|---|
| The palette generator (Spectrum / Analogous / Mono), color contrast rules | `visuals/common/color.ts` (`generate`, `adapt`, `inkOn`) |
| Gradients, shadows and 3D faces of the looks | `visuals/common/look.ts` (`Look.reset`, `fill`, `side`, `top`) |
| The default font, label halo, dimming of unselected marks | `visuals/common/look.ts` (`FONT_STACK`), `visuals/common/atlas.less` |
| Defaults of the shared cards (text sizes, legend position, gridlines) | `visuals/common/cards.ts` |
| Number formats of labels and axes | `visuals/common/util.ts` (`labelFormatter`, `axisFormatter`) |
| Legend layout, value axis, ticks | `visuals/common/chart.ts` |
| Selection, tooltips, keyboard | `visuals/common/interact.ts` |
| A visual's own chart options | `visuals/<visual>/caps.js` (or `capabilities.json` for Columns, Flow, Distribution), `src/settings.ts`, `src/render.ts` |

A new setting needs three things:
1. the property in `caps.js` (or `capabilities.json`)
2. the slice in `src/settings.ts`, plus a `tidy()` rule if it only applies to some chart types
3. its use in `src/render.ts`

Then build, test and look:

```bash
docker run --rm -v "$PWD":/work -w /work visual-atlas make build test
```

The screenshots land in `visuals/test/out/<prefix>_test.png`. Look at them; the checks catch crashes and broken interactions, not ugly layouts.

When you ship a change, raise `visual.version` in the visual's `pbiviz.json` (for example `1.0.1.0` → `1.0.2.0`) so Power BI loads the new code. **Never change the GUID.**

### Test everything in Power BI

```bash
docker run --rm -v "$PWD":/work -w /work visual-atlas make report
```

This writes `release/report/Visual Atlas Test.pbip` (and `release/VisualAtlasTest.zip`): all 13 Atlas visuals on 12 ready-made pages, on one related sample model (Orders with Date, Carrier, Channel, Device and Product, plus small tables for the org chart, prices, pipeline, reviews and project plan), with the Atlas Soft theme applied. Open it in Power BI Desktop, click **Refresh**, and try the slicers, selection, Format pane and themes.
