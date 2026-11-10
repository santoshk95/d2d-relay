# Visual Atlas

Power BI custom visuals with Flat, Soft and 3D looks and colors that follow your report theme or brand, plus the HTML gallery they came from.

| Folder | What's in it |
|---|---|
| `CONTENTS.md` | Start here: what is in the package, and the three paths (use, restyle, develop) |
| `release/` | Ready to use: 13 visuals (`Atlas*.pbiviz`), `themes/*.json`, a test report (`report/Visual Atlas Test.pbip`, `VisualAtlasTest.zip`), the gallery page |
| `visuals/` | Source of the 13 custom visuals (`atlas*/`, shared `common/`), themes, the test harness and sample data |
| `CUSTOMIZING.md` | How to change design and colors: Format pane, one theme for every visual, brand themes, code |
| `gallery/` | Source of the Visual Atlas HTML gallery (84 visuals in 19 categories) |
| `docs/` | History, architecture, Power BI notes, testing guide, roadmap |
| `docker/`, `Makefile`, `scripts/`, `tools/` | Build, test and theme tooling |
| `CLAUDE.md` | Project memory for Claude Code (read automatically when you run `claude` in this folder) |

## Build and test with Docker

```bash
docker build -t visual-atlas -f docker/Dockerfile .
docker run --rm -v "$PWD":/work -w /work visual-atlas make all
```

On Windows PowerShell, use `-v "${PWD}:/work"`. `make all` does four things:

1. Packages all 13 visuals into `release/`.
2. Regenerates and validates the themes (they style every Atlas visual).
3. Renders every test setup in a mock Power BI host and runs the click, keyboard, drill, filter and Format pane checks.
4. Writes the test report (`release/report/Visual Atlas Test.pbip`), with every visual on ready-made pages.

Screenshots go to `visuals/test/out/`. Single steps are `make build`, `make test`, `make themes`, `make report` and `make gallery`. `ONLY=lines bash scripts/test.sh` tests one visual. If you have `make` on your machine, `make image` and then `make docker-all` (or `docker-build`, `docker-test`) does the same.

## Use in Power BI

1. Power BI Desktop: **File › Options and settings › Options › Current file › Report settings › Develop a visual** (Microsoft's import guide asks for this; it lasts for the session).
2. In the Visualizations pane, select **…** › **Import a visual from a file**, and pick a `.pbiviz` from `release/`.
3. Themes: **View › Themes › Browse for themes**, and pick a file from `release/themes/`.
4. For quick test data, load the CSV files in `visuals/test/sample-data/` with **Get data › Text/CSV**. Sort Month by MonthNo, and make a Year › Quarter › Month hierarchy to try drill-down.

In the Power BI service, the admin setting **Allow visuals created using the Power BI SDK** must be on. The visuals aren't certified, so they won't export to PowerPoint or show in email subscriptions.

What each visual can do is in `visuals/README.md`; how to change its design and colors is in `CUSTOMIZING.md`.

## Continue with Claude Code

Run `claude` in this folder. `CLAUDE.md` gives it the full context: what was asked, what was built, the decisions, the verified Power BI facts, how to build and test, and what's next. Project commands are in `.claude/commands/`: `/build`, `/test`, `/new-family`, `/brand-theme`.
