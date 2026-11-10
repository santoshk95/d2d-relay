# P16 — Self-healing + AI SDLC: notes

**Done and merged into `main` on 2026-11-05 night** (merges 46aebee and 954247d). It was stopped mid-build once at
the user's request ("log all and stop") and then finished one step at a time, with no parallel agents.

## What it is
- **Self-healing** (`webapp/app/heal.py`, `heal_prompts.py`, `webapp/static/js/31-heal.js`, `#/heal`, `#/heal/<id>`):
  cases from dashboard refresh and gate failures, expired sign-ins, the DAX checker heartbeat, paused schedules,
  retry-able integration runs and the heal work rows of P12 / P13 / P14. Built-in and learned rules are keyed by
  signature. Jobs: `heal_diagnose` (LLM), `heal_fix` (on a copy, validated by the owning module), `heal_apply`
  (through the owning module only). Checkpoints: `heal.diagnosis`, `heal.apply`.
- **AI SDLC** (`webapp/app/sdlc.py`, `sdlc_git.py`, `sdlc_prompts.py`, `genbi_kit/repo.py`, `webapp/static/js/32-sdlc.js`,
  `#/sdlc`, `#/sdlc/<id>`): Request → Plan → Develop → QA → UAT → Release → Run. Jobs: `sdlc_plan`, `sdlc_dev`,
  `sdlc_qa`, `sdlc_review`, `sdlc_release`. Checkpoints: `sdlc.plan`, `sdlc.review`, `sdlc.uat`, `sdlc.release`.
  Hosts: GitHub, Gitea / generic Git over HTTP, GitLab, Azure DevOps, Bitbucket, plus a local path host for tests.
  Trackers: Jira (through P12) and Azure Boards. `genbi repo` is git for the agent (dulwich). The credential is
  injected per run and never written. Relay opens the pull request and never merges it.

## Tests
- `tests/p16_heal_test.py`: 58 checks (the command is in its docstring; also `run_all.sh p16_heal`).
- `bash tests/p16_sdlc.sh`: 46 checks. It runs Gitea 1.22 and the real agent service with the fake `claude` in
  `tests/p16_bin/`, and QA runs in `python:3.12-slim` via the Docker socket.
- Shell e2e (`MOUNT_SRC=1 bash tests/p9_e2e.sh`): `#/heal` and `#/sdlc` for every role, plus two flows that click
  through the UI.

## Gotchas found while finishing it
- The agent image runs Python 3.11: no f-strings that nest the same kind of quote (3.12 allows it, 3.11 does not).
- `api()` in `01-core.js` sends JSON only for `{json: …}`; `body: JSON.stringify(…)` arrives without a Content-Type
  header, and FastAPI rejects it.
- A job handler that queues the next step must not reset the folder's `job` afterwards. If it does, the worker
  treats the queued row as replaced and skips it.
- `store.all_projects()` lists dashboards only (since P13). A module reads its own subjects from its own table.

## Open
- No real-model smoke run of plan / develop / review yet (only the fake agent).
- The PR link is written back to Jira through P12, which cannot create issues yet.
- The live install has not been redeployed with P16. The images were rebuilt from `main`; the deploy belongs to
  the consolidation step.
