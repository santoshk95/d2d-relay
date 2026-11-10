---
description: Scaffold and build the next Atlas visual family as its own .pbiviz
argument-hint: <family name, e.g. Distribution>
---
Build the next Atlas family visual: **$ARGUMENTS**

Read `CLAUDE.md`, `docs/ROADMAP.md` (which charts belong to this family) and `docs/ARCHITECTURE.md` ("Adding a family visual") first. Look at the gallery's variants for these charts in `gallery/src/catalog.js` / `catalog-x.js` and their renderers in `gallery/src/engine*.js`. Every variant there should become a Format pane setting.

Steps (inside the Docker image: `docker run --rm -it -v "$PWD":/work -w /work visual-atlas bash`):

1. `cd visuals && pbiviz new Atlas<Name>`. Then `npm i powerbi-visuals-utils-formattingutils@6.1.2` (+ `powerbi-visuals-utils-dataviewutils@6.1.0` for fx colors). Remove d3 if it isn't needed.
2. Fill in `pbiviz.json`, `capabilities.json` (roles, mapping, objects, tooltips, `supports*` flags, `privileges: []`, drilldown for category roles), `stringResources/en-US/resources.resjson` and `assets/icon.png`.
3. Write `src/settings.ts` (cards + `tidy()`), `src/model.ts`, `src/render.ts` and `src/visual.ts`. Copy the host wiring from `visuals/atlasColumns/src/visual.ts`. Use `visuals/common/` for colors, looks, text measuring and number formats.
4. Add `visuals/test/<name>_cases.js` (each chart type × Flat/Soft/3D, brand and custom palettes, dark, high contrast, highlights, landing page, edge cases) and a step in `scripts/test.sh`.
5. Run `make build test`, look at the screenshot, and iterate until it looks right.
6. Update `docs/HISTORY.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.

Follow the rules in `CLAUDE.md`: no innerHTML, no network, no Math.random, everything configurable.
