# Visual Atlas: Power BI custom visuals (project memory)

This file is the working memory for Claude Code. It was written at the hand-off from a Claude.ai session (3 Nov 2026), so you can continue the work without the earlier conversation. Read it fully before changing anything. The deeper notes are in `docs/`:

- `docs/HISTORY.md`: every request from the user (verbatim), what was built, decisions and corrections
- `docs/ARCHITECTURE.md`: how the code is organized, data flow, rendering, Format pane
- `docs/POWERBI-NOTES.md`: Power BI API facts that were checked against Microsoft docs and the SDK typings (drill-down, conditional formatting, analytics pane, themes, certification)
- `docs/TESTING.md`: the mock-host test harness, Docker, and how to test in real Power BI
- `docs/ROADMAP.md`: what's left (the remaining visual families) and known gaps

## What this project is

The user asked for an attractive, modern gallery of every Power BI visual (built-in and AppSource/custom) with all variations, then for those visuals as real Power BI custom visuals: data-bound, "100% configurable" in the Format pane, color-agnostic (report theme, a brand color or a pasted palette), with Flat, Soft and 3D looks.

Three deliverables exist:

1. **Gallery page** (`gallery/`): one self-contained HTML page, "Power BI Visual Atlas": 84 visuals in 19 categories, each with variants, drill-down and zoom, a theme studio (brand color, palette, look) and "Copy theme JSON". Published as a claude.ai artifact (private to the user): https://claude.ai/artifact/KJMpGZiS7QoPx6XoGGtQjK (version 3).
2. **Custom visuals** (`visuals/`), one `.pbiviz` per family (the user's choice). The pilot has two:
   - **Atlas Flow** (`visuals/atlasFlow`): Sankey, chord and network in one visual (chart-type switch).
   - **Atlas Columns** (`visuals/atlasColumns`): the six built-in column/bar charts rebuilt (clustered, stacked, 100% stacked × column, bar) **with drill-down**, to compare against the built-ins.
3. **Report themes** (`visuals/themes/*.json`): Flat, Soft, 3D and Soft Dark, generated from the gallery's brand engine and validated against Microsoft's theme schema.

Update (3 Nov 2026, Claude Code): the user asked for all families, one at a time, with no subagents or parallel sessions, fully configurable in design and color, plus a guide. **All 13 visuals are built** (Columns, Lines, Parts, Flow, Distribution, Compare, Hierarchy, Proportion, Time, Finance, Gauges with Cards merged in, Text, Scatter), each tested in the mock host. Design and color work the same way in all of them (shared Style, Palette, Colors, labels, axes, gridlines, legend cards; themes style every visual by GUID). `CUSTOMIZING.md` is the guide. The newer visuals share `visuals/common/family.ts` (see `docs/ARCHITECTURE.md`). `make report` builds a test report with every visual on a related model.

Status (3 Nov 2026): all 13 visuals have been tested by the user in real Power BI Desktop through the test report (`release\VisualAtlasTest`). The feedback rounds are in `docs/HISTORY.md` sections 11–16: drill reset and clear, zoom out, label legibility, cross-filtering (highlight values drawn as a filter), the * selection marker, clickable axis labels, honest cursors, zoom to the selection, and keeping other visuals' selections. The user confirmed "all ok" after section 16.

## The user

- Builds Power BI reports and wants visuals that look better than the built-ins and adapt to any brand palette.
- Choices made so far: one `.pbiviz` per family with a chart-type switch; pilot first (Flow family, then the rest after testing); deliver both a theme for built-in visuals and rebuilt built-in visuals, so they can compare.
- Asked "why can't it have drill down?" after an earlier wrong statement that rebuilt visuals lose drill-down. Custom visuals can drill down (see `docs/POWERBI-NOTES.md`); Atlas Columns does it. Don't repeat the mistake.
- Writes informally and with typos ("configirabke", "pbib" = pbiviz); read intent, not spelling.
- Has Docker on their machine and wants to generate the `.pbiviz` and run the same tests there.

## Commands

Everything runs in Docker (Node 22, pbiviz 7.2.1, Python + Playwright Chromium):

```bash
docker build -t visual-atlas -f docker/Dockerfile .                     # once
docker run --rm -v "$PWD":/work -w /work visual-atlas make all          # build + themes + tests
docker run --rm -v "$PWD":/work -w /work visual-atlas make build        # just the .pbiviz files
docker run --rm -v "$PWD":/work -w /work visual-atlas make test         # mock-host tests + screenshots
docker run --rm -v "$PWD":/work -w /work visual-atlas make themes       # regenerate + validate themes
docker run --rm -v "$PWD":/work -w /work visual-atlas make gallery      # rebuild the gallery page
docker run --rm -v "$PWD":/work -w /work visual-atlas make report       # .pbip test report with every visual (release/report, release/VisualAtlasTest.zip)
```

With `make` on the host: `make image`, then `make docker-all` (or `docker-build`, `docker-test`, ...). On Windows PowerShell use `-v "${PWD}:/work"`.

Outputs: `release/*.pbiviz`, `release/themes/*.json`, `release/power-bi-visual-atlas.html`, screenshots in `visuals/test/out/`.

**After every change to a visual: run `make build test` (or `VISUALS=atlasX ONLY=x` for one) and look at `visuals/test/out/<prefix>_test.png` yourself (Read the PNG).** The checks catch crashes and broken interactions, not ugly layouts.

## Repository map

```
CLAUDE.md               this file
CONTENTS.md             start-here guide for the packaged project (use, restyle, develop)
README.md               human quick start
docs/                   history, architecture, Power BI notes, testing, roadmap
docker/Dockerfile       build/test image
Makefile, scripts/      build.sh, test.sh, themes.sh, gallery.sh
tools/                  extract_bundle.py, mk_themes.js, validate_themes.py, schema/ (Microsoft theme schema, MIT)
visuals/
  common/               shared TypeScript + LESS (color engine, looks, formatting helpers) - edit HERE
  sync.sh               copies common/ into each visual (src/common, style/atlas.less) - build.sh runs it
  atlasFlow/            pbiviz project (src/, capabilities.json, pbiviz.json, stringResources/, assets/)
  atlasColumns/         pbiviz project
  themes/               generated theme JSON
  test/                 mock Power BI host, sample data, test cases, checks, screenshot runner
gallery/                the HTML gallery: src/ (engines, catalog, brand.js, look.js, app.js), scripts/build.mjs, dist/
release/                last built artifacts (pbiviz, themes, gallery html, screenshots)
```

## Rules for this codebase

- **Shared code lives in `visuals/common/`.** Never edit `visuals/*/src/common/*` or `visuals/*/style/atlas.less` directly; they are overwritten by `sync.sh`.
- **Certification-friendly code** (so the visuals could be certified later):
  - Build DOM with `document.createElementNS` / `createElement` + `textContent` (helper `el()` in `common/look.ts`). No `innerHTML`, no HTML strings, no `eval`.
  - No network access; `"privileges": []` in capabilities.
  - No `Math.random`; layouts must be deterministic (Flow's network uses d3-force with its own deterministic start).
- **Every visual must have:** landing page (`supportsLandingPage`), rendering events (`renderingStarted/Finished/Failed`), tooltips (default + report page tooltips), selection + context menu + keyboard (Enter/Space) + `allowInteractions` checks, highlight support, high contrast mode, light and dark backgrounds, localization strings in `stringResources/en-US/resources.resjson`, a 20×20 `assets/icon.png`.
- **Format pane:** build with `powerbi-visuals-utils-formattingmodel` (cards in `src/settings.ts`), and hide what doesn't apply in a `tidy()` method called from `getFormattingModel()`. Every option the gallery shows as a variant should be a setting.
- **Colors:** use `colorer()` from `common/util.ts` (sources: report theme / brand / custom) and keep per-item overrides via `dataColors`-style objects with selectors. Text never uses series colors; inside-bar labels use `inkOn(color)`.
- **Looks:** `Look` class in `common/look.ts` (gradients and filters in the visual's own `<defs>`, id prefix includes an instance counter so several visuals on one page don't clash). Flat = solid, Soft = gradient + soft shadow, 3D = extruded faces + deeper shadow.
- **Text measuring:** `textW()` measures with a canvas (semibold); use `trunc()` for ellipses. Don't guess widths.
- **Numbers:** `labelFormatter()` (about 3 significant digits) for data labels, `axisFormatter()` for ticks; both respect the column's format string, display units and decimals.
- Keep TypeScript strict-clean: `npx tsc --noEmit -p .` inside a visual folder, and `pbiviz package` runs ESLint.
- Version bumps: change `visual.version` in `pbiviz.json` (4-part, e.g. 1.0.1.0) when shipping a new build; the GUID must never change (themes and reports reference it).

## Key facts (verified; details and sources in docs/POWERBI-NOTES.md)

- API 5.11.1, powerbi-visuals-tools 7.2.1, formattingmodel 6.0.4, formattingutils 6.1.2, dataviewutils 6.1.0 (Columns), d3 7.9.0 (Flow uses d3-force).
- Drill-down: `"drilldown": {"roles": ["category"]}`; the role must be Grouping with `max: 1` in conditions; `host.drill({roleName, drillType})` with DrillType Up = 1, Down = 2 (expand all one level), MoveToNextlevel = 3; available types per role in `dataViews[0].metadata.dataRoles.drillableRoles[role]`. Expanded levels arrive as several category columns.
- Conditional formatting (fx): ColorPicker with `selector: dataViewWildcard.createDataViewWildcardSelector(InstancesAndTotals)`, `altConstantSelector`, `instanceKind: ConstantOrRule`; evaluated colors arrive in `categories[k].objects[i]`.
- Analytics pane: card `analyticsPane = true` and `"objectCategory": 2` on that object in capabilities.
- Theme `visualStyles` can target a custom visual by its GUID (e.g. `atlasColumns9A01238C3D0249F7B4F9DFBEA84D3599`). Built-in column charts can't get gradients/rounded bars from a theme, only container styles.
- GUIDs: Atlas Flow `atlasFlowBA37FC4A61814B33BF815C11D35148B1`, Atlas Columns `atlasColumns9A01238C3D0249F7B4F9DFBEA84D3599`, Atlas Distribution `atlasDistribution1C4252B29C654CC1BF16155962622408`.

## Next steps

1. Wait for the user's feedback from real Power BI (import both `.pbiviz` files). Fix what they report first.
2. Things only real Power BI can confirm are listed in `docs/TESTING.md` ("Not covered by the mock host"). Ask the user to check those.
3. Then build the remaining families one at a time (order and contents in `docs/ROADMAP.md`), each as its own pbiviz project in `visuals/` (`sync.sh` and `scripts/build.sh` pick up every folder with a `pbiviz.json`), reusing `common/`, with test cases in `visuals/test/` and a step in `scripts/test.sh`. The `/new-family` command in `.claude/commands/` walks through it.
4. Keep `docs/HISTORY.md` updated with each request and decision, so the next hand-off is easy.
