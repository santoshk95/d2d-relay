# P12 — Service desk (ITSM): status note

Built 2026-11-05 on branch `worktree-agent-a1caf82b8b96df649` (build-plan v2, P12). Everything below runs on the
mock lab; no real Jira or Freshservice account was used.

## What is built and where

| Piece | Where |
|---|---|
| Sources, ticket cache, groups, decisions, work items (own tables via `db.register_schema`), the sync job kind `itsm_sync`, the lazy scheduler, the checkpoint kind `itsm.writeback`, the write-back gate, hand-offs, send-to-a-person, summary KPIs, quality (precision / recall), optional LLM pass, routes `/api/servicedesk/…` | `webapp/app/itsm.py` |
| Jira Cloud REST v3 adapter (search/jql with `nextPageToken`, issue, comments in ADF, transitions, edit fields; JSM "Time to resolution" SLA field) and Freshservice API v2 adapter (tickets paged by `Link`, notes, update); shared retry rules: 429 + Retry-After back-off, 5xx retried, 401 → "sign in again", 403 / 404 named | `webapp/app/itsm_adapters/` |
| Triage: category, summary per ticket and per group, grouping (TF-IDF over words and word pairs, cosine, average linkage, same-problem / same-report / same-metric rules), priority from business impact with the reason, route (agent / person) with the reason, target module | `webapp/app/itsm_triage.py` |
| Prompt for the optional LLM pass (`ITSM_LLM=1` or meta `itsm_llm`) | `webapp/app/itsm_prompts.py` |
| Screen `#/servicedesk` (and `#/servicedesk/<group>`): KPIs, groups by business impact with filter, group dialog (summary, why the priority, route, tickets, decisions, Accept & write back, Ask the queue, Send to a person, Turn into work), per-source cards (status, last / next read, errors, sign-in state, Test / Read now / Pause / Edit / Remove), source editor, ServiceNow "next" card, Quality card, work items | `webapp/static/js/24-servicedesk.js` (+ one script line in `index.html`, one route line in `02-shell.js`) |
| Home card "Service desk" (reads `/api/servicedesk/summary`; empty state "Connect Jira or Freshservice") | `webapp/static/js/19-home.js` |
| Catalogue: `servicedesk` available at `#/servicedesk`, `links={"run","change"}`, `LIVE["servicedesk"]` | `webapp/app/registry.py` |
| Simulators: Jira + Freshservice, stdlib only, 520 seeded tickets each (≈ 435 open) with the true duplicate groups as `fx-g<n>` labels, seeded 429 / 401 / 500, a write log | `tests/mocklab/itsm_sim.py` |
| Tests | `tests/p12_itsm_test.py` (85 checks) via `tests/p12_itsm.sh` or `run_all.sh`; `tests/p12_e2e.sh` runs `tests/p9_e2e_test.py` with the `#/servicedesk` route and the flow "Service desk: group → accept → write back" |

## Done-when evidence

- 400+ mock tickets per source → groups with reasons: 438 open Jira tickets → 136 groups; with Freshservice 870 → 258-ish true groups; every group carries summary, priority + reason, route + reason, target.
- Write-back only after a confirmed checkpoint: `itsm.write_back()` raises `WriteBackRefused` without an accepted `itsm.writeback` checkpoint for exactly these tickets (fingerprint of the member ids); the simulators' write logs stay empty until a person accepts (screen button or Validation queue); an approval whose tickets changed is refused.
- Precision / recall on the labelled fixture (pairwise): Jira fixture precision 1.000 / recall 0.917 (F1 0.957); both fixtures 0.998 / 0.944 (F1 0.970). Reported on the screen's Quality card and by the test.
- All tests pass: `p12_itsm` 85 checks; `p12_e2e` 79 pages · 568 checks · 0 failures · 8 flows · axe clean on 7 screens incl. `#/servicedesk`; brand gate 0 problems.

## Design notes (for the merge and the next phases)

- **Reading is not an LLM run.** `itsm_sync` is registered with the worker (`worker.HANDLERS`, status `reading_tickets`) so it can be queued in the lane against a subject folder; the scheduler and "Read now" call the same `sync_source()` directly (through `asyncio.to_thread`, never overlapping) because a 5-minute poll must not wait behind a 40-minute dashboard build. A read is a few HTTP calls and a rules pass (≈ 1 s for 900 tickets).
- **Checkpoints per group** are opened by the triage for groups worth a person's eye (2+ tickets or P1 / P2) so they appear in the Validation queue (`ITSM_AUTO_CHECKPOINT=0` turns that off); singletons get one when a person presses "Accept & write back" (opened and accepted in the same signed step). A group whose tickets change loses its open checkpoint (withdrawn) and goes back to "to act on".
- **Hand-offs**: D2D creates the dashboard change request for real through `main.feedback` (the existing `/api/projects/{id}/feedback` logic); AI SDLC, Self-healing, Ontology & semantics and Govern are recorded as `itsm_work` rows with a link to the module page until P16 lands.
- **Connections hub**: sources live in `itsm_sources` with the credential at secrets-store name `org/itsm:<source id>:token`. After the P10 merge the hub should list them as category "ITSM", sign-in kind "service account (API token / key)", scope "read; write per approved group", used by "Service desk" — a one-line adapter over `itsm.sources()`.
- **Jira SLA**: `duedate` is a date; the adapter prefers Jira Service Management's "Time to resolution" (`customfield_10030.ongoingCycle.breachTime`), which the simulator serves. A real site may use another custom field id — make `SLA_FIELD` a source setting if a pilot needs it.
- **ServiceNow** is listed (`KINDS["servicenow"].connectable = False`) and refused on save; the Table API adapter comes with a pilot.
- **Optional LLM pass** (`ITSM_LLM=1`): one agent run in the subject folder `output/projects/servicedesk` rewrites summaries (and priorities with a reason); groups never change. Tested with a fake `worker.agent`. Note that the folder appears in the Dashboards list for admins (folders without an index row are admin-visible by design) — leave the flag off unless wanted.
- Untouched: `main.py`, `connectors.py`, `build-plan.md`, `platform-plan.md`, `test-report.md`, `README.md`, the live install. Shared files touched with one line each: `phases.py`, `registry.py`, `index.html`, `02-shell.js`, `run_all.sh`; `19-home.js` (one fetch + one card) and `p9_e2e_test.py` (routes, axe list, one flow).
