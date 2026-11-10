# P14 — Data observability: status note

Built on branch `worktree-agent-a2750869dd207932c` (2026-11-05), against build-plan v2 §6 "P14" and
docs/parallel-work.md, on top of P10 (connections, checkpoints), P12 (service desk) and P13 (lineage, Integration
analytics). Everything runs on the mock lab; no real platform account was used.

## What is built

**Checks and baselines** — `webapp/app/observe_checks.py` (readers and the maths) and `webapp/app/observe.py`
(tables via `db.register_schema`: `observe_sources`, `observe_assets`, `observe_checks`, `observe_observations`,
`observe_incidents`, `observe_work`, `observe_warnings`, `observe_settings`). Watched assets = every lineage node of
kind table / column / report / page / measure / flow / job / bot (P13's graph, never a second one) plus what the
watched connections expose (their objects join the graph as table nodes). Readers are read-only: DuckDB over the
dashboards' uploads and extracts (`genbi_kit.data`), the Connector SDK for warehouses (phase 3's guarded SELECT,
written once in DuckDB dialect and transpiled by sqlglot — the connection owner's stored login, its scope and
enabled flag honoured) and for SDK platforms (the mock, any REST API: records read, statistics computed here), and
P13's runs for integrations. Checks: freshness (last load or the max of a date column vs the cadence — the asset's
setting, else learned from its load history, else the dashboard's daily extract schedule / the integration's
schedule), volume (rows vs a learned baseline by weekday, robust z + relative drop / rise), schema change (columns
and types vs last seen), distribution (numeric means vs the learned means; top-k category mix shift), nulls (per
column vs usual; any null in a key column), duplicates (key columns configured or learned: unique in history and
named like a key), reconciliation to source (row count and the sum of every shared numeric column of a target
against the table that feeds it along the lineage `feeds` edge — dashboard extracts vs their warehouse source
included), lineage breaks (a node that vanished while things depend on it; an integration that stopped running,
failed its last run or is no longer listed — from P13's runs). Every threshold has a default (`DEFAULTS`), a global
override (Admin › Checks & thresholds, `observe_settings`) and a per-asset override (`observe_checks.config`);
nothing is a number hidden in the code path. An anomaly never teaches the baseline; a reading a person marks
"expected" joins it and widens that asset's band. Registered job kind `observe_check` (not an LLM run) per source /
per set of assets, on request and from a lazy `ensure_scheduler()` started by the router (`main.py` untouched).
PostgreSQL and SQL Server are registered as read-only lab warehouse kinds (`register_lab_engines`, psycopg / pyodbc)
for the engine tests and developer databases.

**Incidents with impact** — an incident = check, asset, measured vs expected (rows for the drawer), severity,
first / last seen, likely cause, suggested route, source tool, and its impact from the graph: everything
downstream (reports, pages, measures, tables, jobs), the affected dashboards' owners and the people they are shared
with, schedules targeting them and their recipients, Ask D answers that used the data (30 days), agent runs on those
dashboards (30 days) — with the path (nodes + edges, consumers as virtual nodes) the drawer draws on the P13 map.
One upstream break is one incident: a new finding whose cause sits upstream (same check, or a stopped job above a
stale table) folds into that incident's "also affected" list. The same finding seen again updates its incident; a
finding that no longer recurs resolves it (time to fix). Actions, each through `checkpoints.open` (kind
`observe.action`, view `table`, evidence = the incident, measurements, the impact path): **warn report users** (on
accept: `observe_warnings` rows per affected dashboard + a notification to owners, shared viewers and schedule
recipients; `GET /api/observe/warnings?pid=` is read by the project page), **raise a ticket** (the draft with
summary, cause, evidence, priority; when open service-desk tickets talk about the asset the incident joins that
P12 group and, on accept, `itsm.open_checkpoint` opens P12's own `itsm.writeback` checkpoint — Jira / Freshservice
are written only when *that* is accepted; P12's adapters have no create-issue call, so a draft with no matching
ticket waits in the work list), **Self-healing** and **AI SDLC** fix drafts (`observe_work` rows for P16). "Mark as
expected" (reason required, audited) tunes the baseline; "Resolved" closes and clears banners. Imports:
`POST /api/observe/import` (signed in) and the webhook `POST /auth/observe/hook/{source}` (token by name in the
secrets store, never shown) parse OpenLineage events, dbt `run_results.json`, Great Expectations validation results,
Soda scan results and a generic `{incidents: […]}` shape (Monte Carlo, Bigeye, Acceldata, Metaplane, Elementary,
Datadog) into the same incident table with the tool named, matched to the assets on the map.

**Screen** `#/observability` — `webapp/static/js/27-observe.js`, ported from `mockup-a2z/screens-observe.js`:
KPIs (data health, open incidents, assets watched, caught before users, time to fix), health across the six layers
(counts and status, click to filter), on-time trend, incidents by check, how incidents were fixed, the incidents
table (severity, asset, what moved, affects, age, status, route, source tool), the incident drawer (status,
impact chips, the path on the lineage map component, measured vs expected, likely cause, the four actions each with
a confirm "nothing changes yet", Mark as expected, Resolved), watched assets with checks and thresholds editable
per asset (builders / admins), global thresholds, sources and imports (watch a connection — scope shown, read-only;
add a tool's results with a webhook token or a JSON upload). Empty / loading / error / read-only states, dark mode
through tokens, every control named. Registry: `observe` is `available` at `#/observability` with `links`
assess / run; Home has a small "Data health" card (empty state when nothing is watched); the project page shows
the "Numbers under review" banner through one added line in `js/06-project.js`.

## Done-when evidence

- `tests/p14_observability_test.py` (93 checks, run on `gen-bi-webapp` + fakesnow): a Snowflake warehouse
  (fakesnow), a dashboard with a DuckDB extract of one of its tables, the SDK mock platform and P13's sample estate
  (the ADF pipeline that writes the warehouse table). Six seeded incident types detected on the right asset with
  measurements and the impact path table → extract → report → schedule → people: stale load (extract 3 days old,
  daily cadence), volume drop (240 vs ~400 against the learned baseline), schema change (TAX_TYPE added),
  distribution shift (DISCOUNT_PCT mean 16 vs 4, column named), duplicate keys (3 duplicate INVOICE_IDs, key
  learned), reconciliation break (extract vs warehouse ~40 %); plus the lineage break (the pipeline stopped running,
  impact down to the report) and nulls through the SDK mock. A Sunday-sized suppliers table on a Sunday is not an
  incident (weekday baseline); "expected" tunes the baseline so the same reading no longer fires; one upstream break
  is one incident (the stale upload's model table folded in); every action opens a checkpoint and nothing is written
  before acceptance (no banner, no notification, no service-desk checkpoint, no work row); the ticket action goes
  through P12's gate; imports from OpenLineage, dbt, GE, Soda and the webhook land as incidents; secrets never
  returned (API answers and audit); roles; audit; the `observe_check` job through the worker lane.
- `tests/p14_engines.sh` + `tests/p14_engines_test.py`: PostgreSQL 17.6 in a container through the lab warehouse
  adapter — 21 checks (connection test, browse, guarded query, volume drop, schema change, distribution shift,
  duplicate keys, nulls, stale date column). SQL Server developer and Oracle Free are skipped with a note when the
  image is not present locally (no large downloads); the script runs them when it is (`P14_PULL=1` pulls).
- `tests/p14_e2e.sh` (the P9 Playwright sweep with `#/observability` for every role, light / dark, axe, and the
  flow "Data observability: incident → warn report users" seeded through the test hook under `D2D_TEST_HOOKS=1`).
- `tests/brand_gate_test.py`: 0 problems.

## Shared files touched (one line each, as docs/parallel-work.md allows)

`webapp/app/phases.py` (import + router), `webapp/app/registry.py` (the `observe` module line and `LIVE`),
`webapp/static/index.html` (one script tag), `webapp/static/js/02-shell.js` (one route line),
`webapp/static/js/06-project.js` (the banner hook — one added line in the header), `webapp/static/js/19-home.js`
(one extra fetch and the Data health card), `tests/run_all.sh` (one suite line), `tests/p9_e2e_test.py` (route, axe
page, flow). `main.py`, `connectors.py`, `lineage.py`, `intan.py`, `itsm.py` are untouched; the lab engine kinds are
registered from `observe_checks.py` at import (`connectors.KINDS` entries + a wrapped `connectors._open`).

## Open

- P12's adapters cannot create a Jira / Freshservice issue; the ticket action joins an existing group or waits as a
  draft in the work list. A create-issue call in `itsm_adapters` (behind the same accepted-checkpoint gate) is the
  natural P12 follow-up.
- Oracle Free needs the `oracledb` driver in the web app image (consolidation item).
- The DuckDB reader profiles the raw file; model-column names map to raw names through the definition only when
  they match, so a column incident on a model table names the raw column.
