# P13 — Lineage store + Integration analytics: status note

Built on branch `worktree-agent-ae825d5e04ed91a3d` (2026-11-05), against build-plan v2 §6 "P13" and
docs/parallel-work.md. Everything runs on the mock lab; no real platform account was used.

## What is built

**The lineage & asset graph** — `webapp/app/lineage.py`, tables `lineage_nodes` / `lineage_edges`
(`db.register_schema`). Node kinds: table, column, job, flow, bot, report, page, measure, api, file_drop, queue,
system, owner (+ `entity` for phase 4's ontology); edge kinds reads, writes, feeds, calls, owns, contains,
schedules (+ `identifies` for key mappings and `relates` for entity relations and model relationships). Upserts are
idempotent, keyed by (kind, system, name); properties merge; `first_seen` is kept. Edges are stored in data-flow
direction; `contains` (parent → child) is walked the other way for impact, so a changed page or measure counts its
report as downstream. Today's data is loaded on demand (at most every 5 min, or `POST /api/lineage/sync`): the
ontology (entities, key columns per source, relations) and every dashboard's published definition (upload / warehouse
source tables and columns → model tables and columns → measures → pages → report, plus relationships). API:
`/api/lineage/summary | search | slice | graph | path | table | impact/{id} | node/{id} | sync | node/{id}/tags`.

**Screens** `#/lineage` and `#/graph` — `webapp/static/js/25-lineage.js`: one SVG map component (data-flow
columns by hop, network, radial, fixed columns; colour by type / status / direction; upstream orange / downstream
blue; search with suggestions; depth, direction, kind filters; focus, impact panel "if this changes: N downstream";
path finder; personal-data tags; PNG export; keyboard reachable — Tab between items, Enter opens, arrows move, Esc
clears; labels never go below 11 px on screen; table relief under every map).

**Integration analytics** — `webapp/app/intan.py` (+ `intan_adapters/`): sources per platform with credentials by
name in the secrets store; discovery as the registered job kind `intan_scan` on the worker lane, on request and from
a lazy scheduler started by the router (`main.py` untouched); runs history; owners from the tool, else the RACI
table (`intan_owners`); health rules with learned baselines (median of the integration's own earlier runs):
failing, screen change (bots), credential expired / expiring (≤ 14 days), dependency ("waits on"), slow (×3),
slowing (×2), unstable (≥ 3 retries a week at ≥ 10 %), volume drop (≥ 15 %), message-pack / licence usage (≥ 85 %),
announced schema change, no owner — every risk with its reason, cause and evidence rows. The graph is fed on every
scan (system / tool / owner / warehouse-table / report nodes and edges). "Act before it breaks": one proposal per
risk (ticket with summary, cause, evidence, priority; configuration fix → Self-healing; code fix → AI SDLC; owner to
assign); `POST /api/intan/risks/{id}/act` opens a checkpoint (kind `intan.action`, view `table`) — nothing is written
until a person accepts it in the Validation queue, then an `intan_work` row (ticket draft / fix draft) is recorded;
send back reopens the risk with the comment; dismiss needs a reason; an accepted owner is written to the integration
and the RACI table. Screen `#/integrations` — `webapp/static/js/26-integrations.js`, ported from the mockup: KPIs,
the full-width map coloured by health (dashes failing, dots no owner, issue badges), the at-risk list, runs per day,
success-rate trend, found by type, the full table with filters, per-source status, source editor, RACI editor.

**Adapters** (read-only, vendor API shapes): Oracle Integration Cloud, SSIS catalog (SQL on SQL Server through
pyodbc, or SQLite for the lab), Azure Data Factory, Airflow, SAP CPI / PI-PO, MuleSoft Anypoint, Boomi, Azure Logic
Apps, AWS Glue (boto3 when present), n8n, Power Automate, UiPath Orchestrator, Blue Prism, Automation Anywhere, API
gateways (Azure APIM / Kong), SFTP drops (paramiko when present / folder / lab listing), mail drops (imaplib / lab
listing), system logs, and the Sample estate (no server). Shared client: 429 retried with Retry-After, 401 / 403 →
"sign in again", 5xx retried then a plain error; no secret ever reaches a message or an API answer.

**Simulators** — `tests/mocklab/intan_sims.py`: one per platform shape, built from `intan_adapters/estate.py`
(the mockup's 17-integration map across nine sources + one or two integrations per other platform), seeded 429 /
401 / 500 on demand.

## Done-when evidence

- `tests/p13_integrations_test.py` (96 checks): the 17 integrations are found from nine simulators between the
  same 16 systems as the mockup's map, in four columns; every seeded risk is detected with its reason and health —
  token expiry (I-022), duration ×3 since a date (I-031), screen change (I-040) and the bot waiting on it (I-041),
  file 18 % smaller (I-058), announced schema change (I-063), message pack at 92 % (I-090), SSIS 2.6× slower with
  3 retries (I-095), orphan job found in logs with no owner (I-084); KPIs 17 / 8 / 4 / 4 / 1; the action opens a
  checkpoint and nothing is written before it is accepted; secrets never returned; audit; every other adapter
  against its simulator with its seeded failure.
- `tests/p13_lineage_test.py` (46 checks): upserts idempotent, dashboards and ontology loaded, slices, hops,
  impact, path, tags, pruning.
- Playwright e2e (`tests/p9_e2e_test.py`, run with the worktree mounted over `gen-bi-webapp`, p13-suffixed
  container names): 86 pages × roles × light / dark / phone, 617 checks, 0 failures, 9 flows passed including
  "Integration analytics: at-risk item → action drafted for approval" and "Lineage and knowledge map: keyboard,
  impact panel, layouts, path finder"; axe clean on 7 screens including `#/integrations`.
- Brand gate 0 problems; `p9_shell` (43), `p10_checkpoints` (29), `phase4_semantic` (48), `phase0_webapp` (35)
  still pass on this branch.

## Conventions the adapters rely on (where a vendor does not expose the fact)

- Owner: `owner:<team>` in annotations / tags / descriptions (ADF, Airflow owners, n8n tags, OIC / Boomi / UiPath /
  Blue Prism / AA descriptions, Kong tags, APIM contact); otherwise the RACI table.
- Credential expiry: APIM subscription `expirationDate` and Power Automate / Logic Apps connection status are native;
  elsewhere `expires:YYYY-MM-DD` in the linked service / credential description (ADF, Airflow, CPI, UiPath assets).
- Systems moved: OIC endpoints, CPI Sender / Receiver, ADF datasets → linked services (`system:` annotation or type),
  n8n node types, Logic Apps / Power Automate connectors, SSIS data statistics components; otherwise "<from> → <to>" in
  the description and `writes: <warehouse>:<object>` for the warehouse objects an integration loads.
- OIC message-pack usage comes from a monitoring summary endpoint modelled on the OIC monitoring dashboard (not a
  documented REST path); SSIS schedules from the package description (SQL Agent is not in SSISDB).

## What the merge should wire

- The worker's subject folder `output/projects/integration-analytics/` (`project.json` with `"kind": "intan"`) is
  created by the first scan; `store.all_projects()` and `/api/projects` list every folder, so it shows on the
  Dashboards page as "Integration analytics" (status idle / scanning). Filter non-dashboard kinds there once P10's
  Start subjects land the same way.
- Accepted actions are `intan_work` rows (`GET /api/intan/work`: kind ticket / heal / sdlc / owner, title, body with
  summary, cause, evidence, priority, target). Service desk (P12) should raise the ticket from a `ticket` row;
  Self-healing / AI SDLC (P16) should pick up `heal` / `sdlc` rows; set `status` from `drafted` to the real state.
- Sources live in `intan_sources` (not in `connectors.py`, which P10 owns); the Connections hub can list them from
  `GET /api/intan/sources` under "Integration & automation" and open the editor at `#/integrations`.
- Shared files touched: `webapp/app/phases.py` (one line), `webapp/app/registry.py` (the `intan` and `knowledge`
  lines and two `LIVE` entries), `webapp/static/js/02-shell.js` (three route lines), `webapp/static/index.html`
  (two script lines), `tests/run_all.sh` (two `add` lines), `tests/p9_e2e_test.py` (routes, two flows, axe),
  `tests/p9_shell_test.py` (the preview check now uses `observe`, since `intan` is live).
