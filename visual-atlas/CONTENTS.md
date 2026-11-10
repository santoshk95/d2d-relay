# Visual Atlas: start here

This package holds everything from the Visual Atlas project: 13 ready-built Power BI custom visuals, report themes, a test report, the HTML gallery, the full source, the build and test tooling, and the documentation.

Pick the path that fits your project:

| I want to... | Go to |
|---|---|
| Use the visuals in a Power BI report | [1. Use the visuals](#1-use-the-visuals) |
| Make them match my brand (colors, font, look) | [2. Restyle](#2-restyle-for-your-brand) and `CUSTOMIZING.md` |
| Change the visuals or add new ones | [3. Develop](#3-develop) and `docs/ARCHITECTURE.md` |
| See every visual and variant first | Open `release/power-bi-visual-atlas.html` in a browser |

---

## What's in the package

```
CONTENTS.md                  this file
README.md                    quick start: build, test, use in Power BI
CUSTOMIZING.md               how to change design and colors (Format pane, themes, brand themes, code)
CLAUDE.md                    project memory for Claude Code (read automatically when you run `claude` here)

release/                     READY TO USE
  Atlas*.pbiviz              the 13 custom visuals (import into Power BI)
  themes/                    report themes: Flat, Soft, 3D, Soft Dark (style built-in and Atlas visuals)
  report/                    test report: Visual Atlas Test.pbip, 12 pages, 50 visuals on a star-schema model
  power-bi-visual-atlas.html the gallery: 84 visuals in 19 categories, with a theme studio
  screenshots/               screenshots of the visuals

visuals/                     SOURCE OF THE VISUALS
  README.md                  what each visual does, its fields, interactions, how to build
  common/                    shared code: colors, looks, Format pane cards, legend, axes, selection,
                             drill buttons, corner buttons, data readers (edit shared code HERE)
  atlas<Name>/               one Power BI visual project per family (pbiviz.json, capabilities, src/)
  themes/                    generated theme JSON
  test/                      mock Power BI host, test cases and checks per visual, sample-data/*.csv
  sync.sh                    copies common/ into every visual (the build runs it)

gallery/                     source of the HTML gallery (engines, catalog, brand and look engines)
docs/                        HISTORY (every request and decision), ARCHITECTURE, POWERBI-NOTES
                             (verified API facts), TESTING, ROADMAP
docker/  Makefile  scripts/  build, test, theme and report tooling (all runs in Docker)
tools/                       theme generator, capabilities generator, report generator, validators,
                             Microsoft's theme and report schemas
.claude/commands/            Claude Code commands: /build, /test, /new-family, /brand-theme
```

Not included (each is rebuilt by the tools): `node_modules/`, build output (`dist/`, `.tmp/`), test screenshots (`visuals/test/out/`).

## The 13 visuals

| Visual | Chart types | GUID | Version |
|---|---|---|---|
| Atlas Columns | Clustered, stacked, 100% stacked columns and bars; drill-down | `atlasColumns9A01238C3D0249F7B4F9DFBEA84D3599` | 1.0.8.0 |
| Atlas Lines | Line, area, stacked areas, line + column combos; drill-down, forecast, anomalies, zoom | `atlasLines36E69B273DB443A5AF8E62CB16DB4547` | 1.0.6.0 |
| Atlas Parts | Pie, donut; drill-down, details ring, top N | `atlasPartsA0676FD0579D44EFB545170E4799ADC9` | 1.0.6.0 |
| Atlas Flow | Sankey, chord, network | `atlasFlowBA37FC4A61814B33BF815C11D35148B1` | 1.0.7.0 |
| Atlas Distribution | Histogram, box and whisker, violin and raincloud, parallel coordinates | `atlasDistribution1C4252B29C654CC1BF16155962622408` | 1.0.7.0 |
| Atlas Compare | Lollipop, dot plot, dumbbell, slope, bump, tornado, radar | `atlasCompare1934AF42622F4D63BF12168C02806AC8` | 1.0.6.0 |
| Atlas Hierarchy | Treemap, sunburst, circle packing, org chart / tree | `atlasHierarchy21AE4CB2A0F74216862D09F0C9A3BF2E` | 1.0.5.0 |
| Atlas Proportion | Mekko, waffle, pictogram, aster, rose, Venn | `atlasProportion74F95B1AE3CB4D9195CC248A3EC140A4` | 1.0.6.0 |
| Atlas Time | Calendar heatmap, heat grid / punch card, stream graph, timeline slicer | `atlasTime657C41A78B0A405A998ADA36387448E9` | 1.0.5.0 |
| Atlas Finance | Candlestick, waterfall, ribbon, funnel | `atlasFinance8C601CA9CAF44ADCB6574FA21FDDE583` | 1.0.6.0 |
| Atlas Gauges | Card, multi-row card, KPI, gauge, dial, radial bars, liquid fill, bullet, ticker | `atlasGauges797C4E4189814B78AD7FCCDFF53CBC47` | 1.0.5.0 |
| Atlas Text | Word cloud, ranked words | `atlasTextC961F02E238E426A825D8355E3503AA9` | 1.0.5.0 |
| Atlas Scatter | Scatter and bubble (play axis), dot plot, Gantt | `atlasScatter0B23674C661C4797A349BBC2B0AD313A` | 1.0.5.0 |

Themes target the visuals by GUID. Never change a GUID: themes and reports that use the visual would lose it.

---

## 1. Use the visuals

1. In Power BI Desktop, select **…** in the Visualizations pane › **Import a visual from a file**, and pick a `.pbiviz` from `release/`. Right-click the new icon › **Pin to visualization pane** to keep it.
2. Apply a theme: **View › Themes › Browse for themes** › a file in `release/themes/` (Soft is the default look).
3. Drag fields onto the visual. Each one shows a start screen listing the fields it needs, and every field has a description. The fields per visual are in `visuals/README.md`.
4. Want a working example first? Open `release/report/Visual Atlas Test.pbip` and select **Refresh**. It has every visual on ready-made pages, on one sample model.

Power BI service: the admin setting **Allow visuals created using the Power BI SDK** must be on, or an admin adds the files to the organizational visuals. The visuals aren't certified by Microsoft, so they don't export to PowerPoint or appear in email subscriptions.

What users can do in a report (click, Ctrl+click, axis labels, selections in several visuals, drill, zoom, the * marker) is in `visuals/README.md` › *Interactions*.

## 2. Restyle for your brand

Four levels, from one visual to the code (details in `CUSTOMIZING.md`):

| Level | Changes | How |
|---|---|---|
| Format pane | One visual | Select the visual › Format pane: Chart (type, look), Style (font, marker, selection behavior), Palette, Colors, labels, axes, gridlines, legend |
| Report theme | Every visual in a report | Apply a theme from `release/themes/` |
| Brand theme | New themes for your brand color, font and look | `docker run --rm -v "$PWD":/work -w /work -e BRAND_COLOR=#0f766e visual-atlas make themes`, or the gallery's theme studio and **Copy theme JSON** |
| Code | Defaults, new options | `visuals/common/` (shared) and `visuals/atlas*/` |

Every visual takes colors from the report theme by default, so applying your brand theme restyles all 13 at once.

## 3. Develop

Everything runs in Docker (Node 22, pbiviz 7.2.1, Python with Playwright):

```bash
docker build -t visual-atlas -f docker/Dockerfile .
docker run --rm -v "$PWD":/work -w /work visual-atlas make all
```

`make all` packages the visuals into `release/`, regenerates the themes, runs every test in the mock Power BI host, and writes the test report. On Windows PowerShell use `-v "${PWD}:/work"`. `README.md` has the single steps.

Before changing code, read:

- `docs/ARCHITECTURE.md`: how the code is organized, data flow, rendering, the Format pane
- `docs/POWERBI-NOTES.md`: Power BI API facts checked against Microsoft's docs (drill-down, highlights, filters, themes, certification)
- `docs/TESTING.md`: the mock host, adding test cases, and what only real Power BI can confirm
- `CLAUDE.md` › *Rules for this codebase*: shared code lives in `visuals/common/`, certification-friendly code (no innerHTML, network or randomness), what every visual must have
- `docs/HISTORY.md`: every request and decision, including the feedback rounds from real Power BI

To add a chart family: `docs/ROADMAP.md` and the `/new-family` command (`tools/scaffold.py`).

After every change: `make build test`, then look at the screenshots in `visuals/test/out/` yourself. The checks catch broken interactions, not ugly layouts. When shipping, raise `visual.version` in that visual's `pbiviz.json`; Power BI only reloads a visual whose version changed.

### Use with Claude Code

Run `claude` in this folder. `CLAUDE.md` gives it the full context, and `/build`, `/test`, `/new-family` and `/brand-theme` are ready to use.
