# P10 — the core loop: status note (branch `worktree-agent-ac94547945b2b65d9`, 2026-11-05)

Built on top of the P10 base commit (checkpoint service + Validation queue). Everything below runs on mocks in
throwaway containers; the live install was not touched.

## What is built and where

**1. Start from an idea or a plan** — `webapp/app/start.py`, `webapp/app/start_prompts.py`, `webapp/static/js/21-start.js`,
routes `#/start` and `#/start/<id>`, menu "Start from an idea" (top group, after Home) and "Team & agents" (Your practice).
- A start is a folder `output/projects/<id>/` with `kind: start` in `project.json` (the shared `store`): `request.md`
  (brief + every correction appended, newest last), `attachments/` (+ `.read/` caches: extracted text, sheet profiles,
  video frames), `connections.json`, `analysis.yaml`, `plan.yaml`.
- API: `POST /api/start` (multipart: brief, name, links, connections, delete_recordings_after, files), `GET /api/start`,
  `GET /api/start/{id}`, `/activity`, `/file/{path}` (attachments and frames, tenant folder only), `POST …/views/{view}/confirm|correct`,
  `POST …/retry`, `POST …/recordings/delete`, `POST …/dashboard` (creates a dashboard through the existing `main.create_project`,
  spreadsheets → CSV), `DELETE /api/start/{id}`, and a test hook `POST …/analysis` (only with `D2D_TEST_HOOKS=1`).
- Job `start_read` (`worker.register_job`, llm=True): the agent runs in the start folder with `start_prompts.SYSTEM` /
  `READ` (a `system` keyword was added to `worker.agent` / `_stream` for this), reads every attachment with the new
  toolkit command `genbi read <path>` (`genbi_kit/reader.py`: docx → markdown, xlsx/csv → column profile + sample rows,
  pptx → slide texts, pdf → text, images → size, video → key frames with ffmpeg, audio → metadata + "transcripts need a
  speech model (planned)") and its own Read tool for images / frames / PDFs, then writes `analysis.yaml` (views
  `process`, `fields`, `plan`). `start.check_analysis` validates it (unknown module ids against `registry.BY_ID`,
  confidences outside 0-1, empty views, missing keys) with fix rounds on the resumed session like `worker._plan`.
- Three checkpoints of kind `start.view` (views process / fields / plan, evidence = rows + counts, link `#/start/<id>`,
  assignee = the person who started it). `on_decision`: accept = view confirmed (signed, audited); send_back = the
  comment goes to `request.md`, the other open views are withdrawn, `start_read` re-runs with the correction and the
  three views reopen. All three confirmed → status `planned`, `plan.yaml` final, every promised checkpoint is a row in
  `start_plan_checkpoints` (status `upcoming`; `start.link_checkpoint()` is for the modules that open them later),
  "Next:" links to live modules, "Start the dashboard" for the BI item, "Delete the recordings now" (audited).
- The web app's own readers fill the `.read` caches at upload, so the page shows the extracted text at once; the
  agent's `genbi read` (ffmpeg) refreshes them. Packages: `python-docx`, `openpyxl`, `python-pptx`, `pypdf` in both
  images; `ffmpeg` (apt) in the agent image.

**2. Team & agents** — `webapp/app/team.py` (`GET /api/team?period=7d|30d|6m`), `webapp/static/js/23-team.js`, route `#/team`.
Who is on what now (the running job, open checkpoints by assignee, the last decision), waiting for a person (count,
oldest, median), hours of agent work vs people's time to decide, agent quality (accepted without changes, sent back,
fix rounds, runs right first time) per agent role (stage → Planner / Builder / Fixer / Data designer / Extractor /
Publisher / Reader) matched to the checkpoints it opened, per person table, hours and FTE saved vs AI cost from the
hourly rate / currency / USD rate in Admin › Branding, six-month series. Charts with `colChart` / `lineChart` /
`asTable`. Viewers get a "for builders and leads" state (API 403).

**3. Connections hub + Connector SDK** — `webapp/app/connectors.py` (extended), `webapp/app/connectors_sdk.py` (new),
`webapp/app/data_routes.py` (extended), `webapp/static/js/12-connections.js` (hub, detail dialog, `connectionWizard`,
`connPicker`, `connectionsCard`), one line in `js/20-modules.js` (the module page's Connections card).
- Eight categories, six sign-in kinds, scopes `read` (default) / `comment` / `write` (+ limits text), sharing
  `me` / `team` / `org`, enabled flag, last test, consented — as added columns on `connections` (`db.register_schema`).
- `connectors.may_write(c)` / `may_comment(c)`; the only write path is `connectors.request_write()` → a checkpoint of
  kind `connection.write` (Validation queue); the adapter writes only when a named person accepts (approval = the
  checkpoint id), audited (`connection.write`, `connection.write_refused`, `connection.write_failed`).
- Sharing: a shared connection runs with its owner's stored sign-in; only the owner edits / renews / changes scope;
  owner or admin changes sharing, disables, removes. Used-by is derived from dashboards' `data/.extracts.json` (or
  the warehouse they were created from) and starts' `connections.json`. Disabled connections refuse every use.
  Renew: OAuth → sign in again; key / password → the new secret is stored (never returned).
- SDK: `Adapter` base (describe, test, list_objects, read, guarded write, close) + `REGISTRY`; `WarehouseAdapter`
  wraps the five phase-3 kinds without changing their code paths; `MockAdapter` (tests; records writes, switchable
  failures) and `RestApiAdapter` (OpenAPI URL + API key: lists GET endpoints, reads one, never writes). The docstring
  says how a new platform = one adapter + one mock.
- New endpoints: `PUT …/scope`, `PUT …/sharing`, `POST …/disable|enable|renew`, `GET …/used-by`, `POST …/read`,
  `POST …/write` (202 + checkpoint); `GET /api/connectors` and `GET /api/connections` carry the vocabulary.

## Tests (all in throwaway containers; images `gen-bi-agent-p10` / `gen-bi-webapp-p10` built from this branch)

| Suite | Command | Result |
|---|---|---|
| `tests/p10_connections_test.py` | `docker run … gen-bi-webapp python /tests/p10_connections_test.py` (run_all line) | 53 checks pass |
| `tests/p10_team_test.py` | `docker run … gen-bi-webapp python /tests/p10_team_test.py` (run_all line) | 22 checks pass |
| `tests/p10_start.sh` → `p10_fixtures.py` (agent image: fixtures + readers) + `p10_start_test.py` (driver) | `AGENT_IMG=gen-bi-agent-p10 WEB_IMG=gen-bi-webapp-p10 bash tests/p10_start.sh` | 14 + 60 checks pass |
| `tests/p9_e2e.sh` (routes `#/start`, `#/team`, viewer states; flows Start / Team / Connections wizard; axe on `#/start`, `#/team`, `#/connections`) | `AGENT_IMG=gen-bi-agent-p10 WEB_IMG=gen-bi-webapp-p10 bash tests/p9_e2e.sh` | 81 pages, 584 checks, 0 failures, 10/10 flows, axe clean |
| `tests/p10_checkpoints_test.py` (unchanged) | run_all line | 29 checks pass |
| `tests/brand_gate_test.py` | `docker run … --entrypoint python3 gen-bi-agent /repo/tests/brand_gate_test.py` | 0 problems |

The done-when evidence is `p10_start.sh`: the invoice-matching example (docx procedure, xlsx PO extract, pptx, pdf,
PNG invoice drawn with Playwright, 3-second WebM recorded by Playwright) goes through the real agent service with a
fake `claude` (`tests/p10_bin/claude`) that runs `genbi read` and writes a valid, then an invalid (fix round), then
a corrected analysis; three checkpoints appear in the queue; two views confirmed, one sent back; all three confirmed
→ planned with 12 promised checkpoints; Team & agents shows the Reader's three runs; recordings deleted (audited);
the dashboard starts from the brief and the xlsx (as CSV); a viewer can neither start nor see it.

## Shared files touched (for the merge)

`webapp/app/worker.py` (`system=` keyword on `agent` / `_stream`, default unchanged), `webapp/app/store.py` (`kind` in
`all_projects`), `webapp/app/main.py` + `webapp/app/home.py` (dashboards lists skip `kind != dashboard`),
`webapp/app/phases.py` (start, team), `webapp/static/js/02-shell.js` (two menu lines, two route lines),
`webapp/static/index.html` (two script lines), `webapp/static/css/relay.css` (one appended block),
`webapp/static/js/20-modules.js` (one line: the Connections card), `agent/Dockerfile` (one pip line, one apt line),
`webapp/requirements.txt` (four packages), `genbi_kit/cli.py` (the `read` sub-parser at the end), `tests/run_all.sh`
(three lines), `tests/p9_e2e.sh` (`D2D_TEST_HOOKS=1`, image names from `AGENT_IMG` / `WEB_IMG`), `tests/p9_e2e_test.py`.
The images need a rebuild after the merge (new packages, ffmpeg).

## Open points

- The agent's folder guide (`CLAUDE.md`) is still the dashboard guide; the Start stage prompt tells the agent to
  ignore it. A per-kind guide in `worker.refresh_guide` would be cleaner.
- Audio transcripts need a speech model (reader notes it; planned). Links are noted, not opened (access comes through
  Connections).
- `start_plan_checkpoints` rows become `open` / `done` only through `start.link_checkpoint()`; P12+ modules that run a
  plan's items should call it (the dashboard path does).
- The Team & agents "where time goes" mix (doing / validating / with the business) is limited to what is recorded:
  agent hours and people's time to decide; no invented split.
- Real-model smoke run of `start_read` not done on this branch (no live install use); the prompt and the YAML shape
  are exercised by the fake agent only.
