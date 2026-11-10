# P15 — Migrate BI: status note

Built 2026-11-05 on branch `worktree-agent-a22963224452964db` (build-plan v2, P15). Everything below runs on the mock
lab: the sample estate (a seeded, synthetic IBM Cognos Analytics estate written as real export files), a Cognos REST
simulator, and a fake `claude` standing in for the agent where the rules do not cover. No real BI server was used.

## What is built and where

| Piece | Where |
|---|---|
| Neutral model (datasets, reports, queries, calculations, filters, prompts, pages, visuals, usage, owners, folders, dependencies; counts and the inventory CSV derived from it) | `genbi_kit/migrate/model.py` |
| Cognos expression parser (one AST for the rules and the simulator) | `genbi_kit/migrate/expr.py` |
| Readers: IBM Cognos Analytics — export folders and deployment archives (report spec XML across the namespaces, dashboard / story JSON, package and data module JSON, content listing, Audit database CSV; paged reads with progress, pause / stop, a resume cursor) and the REST thin client (CAM sign-in, content paging, specifications, audit rows, HTTP 429 waits said plainly) that downloads into the same layout; Qlik Sense `unbuild` folders and QlikView `-prj` folders with load-script parsing; MicroStrategy, Tableau, SSRS, BusinessObjects as stubs (status "next", what they will read) | `genbi_kit/migrate/readers/` |
| Sample estate: 1,842 objects (1,604 reports, 137 report views, 83 dashboards, 18 stories), 83 packages / data modules, 2.5 years of audit runs, nine reports on a missing package, Active Reports, HTML items with scripts, maps; the CSV data behind its five datasets; twelve "Executive" showcase reports | `genbi_kit/migrate/sample_estate.py` |
| Rule engine: Cognos → DAX and SQL from one AST (aggregates, `for` levels, percentage, DIVIDE, if / case, strings, dates on the Date table, casts, filters → slicers or CALCULATE, visuals → catalogue types), every translation with rules, confidence and one-line gaps; window SQL for running / moving / rank / percentile with no DAX rule; "Ready to convert" prediction with a reason; rule packs learned from accepted answers (JSON per tenant / partner under `output/projects/.migbi/`) | `genbi_kit/migrate/rules.py` |
| Decide: retire / merge / needs-a-decision rules with the defaults beside them, similarity pairs cached once per estate, a preview that answers in milliseconds, overrides signed by name | `genbi_kit/migrate/decide.py` |
| Source simulator: an independent Cognos-semantics engine over the CSVs (the proof's source side) | `genbi_kit/migrate/source_sim.py` |
| Converter: neutral model → `definition.yaml` (the existing schema), gaps as `BLANK ()` with a description, the plan (rules used, lineage, decisions), the project folder with `request.md` and `migrate_brief.json` | `genbi_kit/migrate/convert.py` |
| Proof: numbers vs source per visual (source simulator vs the converted definition's prototype SQL), evidence for the checkpoint | `genbi_kit/migrate/proof.py` |
| Web module: tables `migbi_projects`, `migbi_reports`, `migbi_lineage`, `migbi_schedules` (`db.register_schema`); job kinds `migbi_scan`, `migbi_convert` (llm), `migbi_drift`; checkpoint kinds `migbi.decide`, `migbi.prove`, `migbi.handover`; routes `/api/migrate-bi/…` | `webapp/app/migrate.py` |
| Prompts: fill the gaps only (rules first) or rework every calculation (AI-led); fix rounds reuse `prompts.fix` | `webapp/app/migrate_prompts.py` |
| Screen `#/migrate-bi` (start: source / version / target / where the estate lives / mode / AI calls, programmes) and `#/migrate-bi/<id>/<step>`: Discover (Where it lives · Agents & AI · Scan with live activity, pause / resume / stop · What we found with every number clickable and the reason behind "Ready to convert"), Decide (rules with live preview, tiles, before → after, rows with reasons, your call, apply = signed), Convert (select & plan with the estimate, waves with the four groups Understand · Build · Prove · Package, per-report tabs incl. the log), Prove (numbers table, gates, accept / convert again), Hand over (pack, owner sign-off, download after it), Run (nightly checks), Agent log, Lineage drawer | `webapp/static/js/27-migrate.js` |
| Catalogue: `migbi` available at `#/migrate-bi`; `LIVE["migbi"]` so the `bi` module's Assess / Migrate and `metrics` Migrate work types open it | `webapp/app/registry.py` (two lines) |
| Mock lab: Cognos REST simulator; fake `claude` CLI; fake agent service (in-process, for the convert suite) and the launcher that runs the real agent service with the fake on its PATH (for the e2e, so the display gate draws for real); an API driver that runs a programme end to end without a browser | `tests/mocklab/cognos_sim.py`, `fake_claude.py`, `fake_agent.py`, `fake_agent_server.py`, `migbi_drive.py` |
| Tests | `tests/p15_readers_test.py`, `tests/p15_decide_test.py`, `tests/p15_convert_test.py` (lines in `run_all.sh`), `tests/p15_e2e.sh` (+ the routes and flow in `tests/p9_e2e_test.py`, behind `MIGBI_E2E`) |

## Done-when evidence

- **The 1,842-object sample estate goes through the full journey** — `tests/p15_convert_test.py` (77 checks): a
  programme on the sample estate → test connection (writes the estate: 1,842 objects, 83 shared packages / data
  modules, 913 days of audit runs) → scan as a `migbi_scan` job with live activity, pause / resume / stop and a
  resume from the cursor → what we found (every number from the model; ready-to-convert prediction with a reason)
  → inventory (filters, paging, CSV, object detail) → Decide (live preview, an override signed by name, apply =
  `migbi.decide` checkpoint accepted in the same signed step, or asked of the queue) → a wave of 21 reports with the
  estimate (time, AI calls, cost, datasets, budget) → convert → prove → accept (a rule learned, reused on the next
  conversion with no AI call) → hand-over pack (download refused before the owner's sign-off, open after it) → nightly
  drift checks registered and run.
- **≥ 20 sample reports convert and pass every gate** — the 21 reports of wave 1 (the twelve Executive showcase
  reports and nine automatic ones) all reach `converted / proven`: no gate fails; the DAX gate is `skip` because the
  checker is off (asserted: never `pass`); one conversion goes through a fix round after the fake agent's first
  answer breaks a gate (`VAR Month`), the second run resumes the same session.
- **Numbers match the source simulator** — every converted report: `matched == compared`, `differences == 0`, no
  open measures (the fake agent's running totals, ranks, moving averages and percentiles included); the proof's
  numbers are the `migbi.prove` checkpoint's evidence, one per report, all open in the Validation queue.
- **Every step's checkpoint is a real checkpoint** — `migbi.decide` (table view), `migbi.prove` (table view, per
  report), `migbi.handover` (link view, assigned to the owner, accepted from the queue); decisions carry
  `decided_by`, the history shows the withdrawn and accepted ones.
- **Readers and rules** — `tests/p15_readers_test.py` (73 checks): the Cognos expression parser, export fixtures with
  edge cases (archive, mixed namespaces, malformed XML, missing spec, orphan view, inferred prompts, scripts, Active
  Report, missing package, failed runs, cursor resume, stop), the REST client against the simulator (sign-in, paging,
  a seeded 429), Qlik Sense and QlikView fixtures, the stubs, the sample estate generated and read back.
  `tests/p15_decide_test.py` (68 checks): translations to DAX and SQL, the prediction, rule packs learned and reused,
  the converter on a small dataset, the source simulator, the Decide rule maths, weights, thresholds, overrides and the
  live preview on the full estate (< 1 s).
- **Brand gate** — 0 problems in 43 files.
- **E2E** — `tests/p15_e2e.sh` (the P9 Playwright sweep with the Migrate BI routes and flow, the real agent service
  with the fake `claude` on its PATH so the display gate draws every page in headless Chromium): 91 pages, 653
  checks, 0 failures, 151.6 s; flow "Migrate BI: connect → scan → decide with live preview → convert → prove → hand
  over" PASS (three showcase reports converted and proven in the browser, proof accepted, pack refused before and
  served after the owner's sign-off, nightly checks registered); axe clean on `#/migrate-bi`; the ten step pages
  of the programme pass the same sweep as the shell's routes (light, no retired brand text, no script errors).

### Test commands (all in throwaway containers over the shared images, this checkout mounted)

| Command | Result |
|---|---|
| `docker run --rm -w /srv -e PYTHONPATH=/srv:/opt/genbi -v "$T:/tests:ro" -v "$ROOT/genbi_kit:/opt/genbi/genbi_kit:ro" gen-bi-webapp python /tests/p15_readers_test.py` | 73 checks passed |
| `… gen-bi-webapp python /tests/p15_decide_test.py` (same mounts) | 68 checks passed |
| `docker run --rm -w /srv -e PYTHONPATH=/srv:/opt/genbi -e D2D_AUTH=header -e WORKSPACES=/tmp/p -e D2D_STATE=/tmp/s -e D2D_BACKUPS=/tmp/b -e GENBI_LIBRARY=/tmp/lib -e MIGBI_SCAN_PACE_S=0.25 -v "$T:/tests:ro" -v "$ROOT/webapp/app:/srv/app:ro" -v "$ROOT/genbi_kit:/opt/genbi/genbi_kit:ro" gen-bi-webapp python /tests/p15_convert_test.py` | 78 checks passed (21 reports converted and proven, one fix round, DAX gate skipped, signed pie → bar) |
| `docker run --rm -v "$ROOT:/repo:ro" --entrypoint python3 gen-bi-agent /repo/tests/brand_gate_test.py` | 0 problems in 43 files |
| `bash tests/p15_e2e.sh` (containers `relay-p15-web`, `relay-p15-agent`, network `relay-p15-net`; output under `output/test-runs/<stamp>-p15-e2e/`) | 91 pages · 653 checks · 0 failures; Migrate BI flow PASS; axe clean |

The three suites are lines in `tests/run_all.sh` (before `mocklab_platforms`); the e2e is its own script like
`tests/p12_e2e.sh`. `tests/mocklab/migbi_drive.py` runs a programme end to end through the API without a browser
(with `MIGBI_DRIVE_POLL=1` it polls like the page does) — the quickest way to reproduce a conversion problem.

## Design notes (for the merge and the next phases)

- **Rules first, agent for the gaps.** `convert.build` writes a complete `definition.yaml`; calculations without a
  rule become `BLANK ()` measures with a "NO RULE YET" description and are listed in `migrate_brief.json`. The
  convert job asks the agent only then (never in rules-only mode), runs `worker._check_definition` with the usual
  fix rounds, then the proof, then the package. Window SQL exists for running totals, ranks, moving averages and
  percentiles even without a DAX rule, so the proof checks what the agent writes; when the person accepts the proof,
  every gap measure becomes a learned rule (DAX template with column placeholders) in the tenant's pack and the
  next report with the same shape needs no AI.
- **Data-aware visual rules.** The e2e (real display gate, headless Chromium) found that a pie of a signed measure
  (GL budgets, negative in every department) makes the Parts visual throw while drawing. The converter now asks the
  source simulator for the pie's parts and, when any is negative, draws a bar chart instead (`cog.viz.pie.signed`,
  high confidence, reason in the plan); the convert suite asserts it on the sample estate. The convert suite's
  in-process fake agent cannot draw, so the display gate runs for real only in `tests/p15_e2e.sh`.
- **Filters.** A constant filter every query shares becomes a report slicer with that default; one that only some
  queries have is folded into those queries' measures (`CALCULATE`) and their visuals' SQL, so the other visuals keep
  their numbers (Cognos filters are per query; Power BI slicers are per report). Prompts become multi-select slicers.
- **The DAX gate is never a pass without the checker.** `worker._check_definition` marks it skipped when the DAX
  checker on the Windows host is off; the screens say so plainly; the proof compares source vs prototype SQL and the
  values gate compares prototype vs DAX when the checker runs.
- **Folders.** A programme is `output/projects/<mig id>/` (`kind: migbi`); each converted report is
  `<mig id>-<slug>/` (`kind: migbi_report`) — a dashboard-style folder the project page can open. One line was added
  to `store.all_projects()` so folders with a `kind` other than dashboard stay out of the Dashboards list (P12's
  `servicedesk` folder would benefit from `kind` too).
- **Lineage.** Edges go to `migbi_lineage`; `migrate.push_lineage` hands the same edges to the shared store (P13 `app.lineage.upsert_node` / `upsert_edge`, source `migbi`): source tables and query items (system = the source BI) feed the converted tables, columns and measures (system = the target); the converted report reads its tables and contains its measures. Wired at the merge into main.
  source, subject, edges)` when that module exists (P13). The merge should check P13's actual function name and
  shape and adjust the three-line adapter.
- **Run.** Nightly drift checks are `migbi_schedules` rows (registered at sign-off) plus the `migbi_drift` job that
  re-runs the proof; `migrate.run_due_drift()` queues the due ones — the merge may call it from
  `schedules.scheduler()`'s tick, or leave "Run now" only until P16's Self-healing takes over.
- **Live server.** `CognosRest` follows the Cognos Analytics 11.1+ REST shapes for sign-in and the content store and
  invents nothing beyond `/api/v1/{reports,dashboards,stories,modules,packages}/{id}/specification` and an audit
  endpoint the simulator serves; a pilot against a real server will need those two checked (D5).
- Untouched: `main.py`, `connectors.py`, `build-plan.md`, `platform-plan.md`, `test-report.md`, `README.md`, the live
  install, the agent image (no new packages). Shared files touched with one line each: `phases.py`, `registry.py`
  (two), `index.html`, `02-shell.js`, `store.py`, `run_all.sh` (three suite lines), `p9_e2e_test.py` (routes and one
  flow behind `MIGBI_E2E`).
