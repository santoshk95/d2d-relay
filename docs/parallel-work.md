# Working on RELAY in parallel (build-plan v2, P10 onwards)

Several agents build phases at the same time, each in its own git worktree and branch. These rules keep the
branches mergeable and the live install safe. Read them in full before touching anything.

## Where things are

- The plan to build from: `build-plan.md` (your phase's section says what it is, done-when and its tests);
  design detail and history: `platform-plan.md`; the signed-off clickable design: `mockup-a2z/a2z-mockup.html`
  (source `mockup-a2z/*.js`, one `routeOn(...)` per screen — port its screens, wording and states, never its
  made-up numbers). Project memory with every gotcha found so far:
  `C:\Users\santosh.k\.claude\projects\C--Users-santosh-k-Downloads-Gen-BI\memory\genbi-project-state.md` and
  `powerbi-pbip-gotchas.md` (read both).
- Web app: `webapp/app/*.py` (FastAPI, SQLite / Postgres through `db.py`), static UI `webapp/static/js/NN-*.js`
  (classic scripts, one global scope, `h()` element helper, `api()` fetch helper, `pageHead()`, `kpiTile()`,
  `skel()`, `modal()`, `notify()`, `confirmBox()`), tokens in `css/app.css`, components in `css/relay.css`.
- The agent (Claude Code in a project folder with the `genbi` toolkit): `agent/server.py` (`POST /runs`),
  `genbi_kit/` (toolkit + `GENBI.md` guide), `webapp/app/worker.py` (the one sequential job lane).
- Tests: `tests/` — every suite runs in a throwaway container, never against the live app or `output/projects`.

## Plug-in points (use these; do not restructure shared files)

| Need | How |
|---|---|
| New tables / columns | in your module: `db.register_schema("""CREATE TABLE IF NOT EXISTS …;""", added_columns={"table": {"col": "TEXT"}})` at import time. Never edit `SCHEMA` in `db.py`. |
| A new job for the sequential worker | `worker.register_job("kind", handler, status="…ing", done="… ready", llm=True, turns=80, timeout_s=2400)`; `async def handler(pid, args)`; queue with `worker.enqueue(pid, "kind", **args)`; call the agent with `worker.agent(pid, stage, prompt, turns, target)`; your subject is a folder under `output/projects/<id>/` with a `project.json` (`store.save/load/update`), like dashboards. |
| A step a person must confirm | `checkpoints.open(kind, subject, module, name, view, evidence, link=…, assignee=…, team=…, agent=…)`; `checkpoints.register_kind(kind, label, on_decision)` at import — the Validation queue (`#/validate`) shows it, `on_decision(checkpoint, "accept"|"send_back", comment, who)` continues your flow; `checkpoints.withdraw(kind, subject)` when the subject moves on. Views: process, fields, plan, kpis, prototype, gates, mapping, table, text, link. |
| Routes | one `APIRouter` in your module; add **one line** to `webapp/app/phases.py` (import + append to `ROUTERS`) in alphabetical order of the phase. |
| A screen | `webapp/static/js/NN-<name>.js` with `renderX()`; add **one** `<script>` line in `index.html` before `08-boot.js`; route it in `02-shell.js` `route()` with one `if (location.hash …) return renderX();` line, placed just before `if (!pid) return renderHome();`; menu entries come from the module registry (below) — do not add ad-hoc nav groups except the ones your phase section names. |
| The catalogue | your module's line in `webapp/app/registry.py` MODULES: set `status="available"` (or `"partly"`), `route="#/<your-route>"`, `links={work: "<LIVE key>"}` and, when needed, one entry in `LIVE`. Nothing else in the file. |
| Agent image packages | append to the pip line in `agent/Dockerfile` (one `RUN /opt/venv/bin/pip install --no-cache-dir …` line of your own after the existing ones, pinned versions). Build your own tag for tests: `docker build -t gen-bi-agent-<phase> -f agent/Dockerfile .` — never retag `gen-bi-agent` / `gen-bi-webapp`. |
| Web app packages | append to `webapp/requirements.txt`; build `gen-bi-webapp-<phase>` for your tests. |
| Prompts | your own module (e.g. `app/<phase>_prompts.py`); reuse `prompts.SYSTEM`, `prompts.attached`, `prompts.fix` patterns. |
| Toolkit commands | `genbi_kit/<name>.py` + a sub-parser in `genbi_kit/cli.py` (append at the end of the sub-parser list). |
| Tests in the runner | append one `add <suite> "…"` line to `tests/run_all.sh` before `add mocklab_platforms`; infrastructure-heavy suites get their own `tests/<phase>_*.sh` runner. |

## Tenancy (P17) — every branch, from 2026-11-06

Relay is multi-tenant (platform → partner → client; `docs/P17-tenancy.md`). Each tenant has its own database
schema / file and its own folder tree, chosen by a context variable, so **module code never names a tenant** — as
long as it follows these rules:

| Do | Never |
|---|---|
| Read and write through `db.q / one / run / transaction` and tables from `db.register_schema` (created in every tenant) | open your own database connection, or keep rows in module-level caches without the tenant in the key (`db.tenant()`) |
| Use `store.root()` (or `store.ROOT / …` evaluated at call time) for anything under the projects volume | keep a folder path in a module-level variable at import time (it would be one tenant's) |
| Send `store.rel(pid)` as the agent's `workdir` (POST /runs, /display-check) | send a bare project id to the agent |
| Wrap every background pass: `for t in db.each_tenant(): …` (sync or async body) | run a scheduler / watcher pass once for "the" database |
| Keep credentials in `secrets_store` and settings in `db.meta` (both per tenant) | write files into `db.STATE` directly |
| Put your module's APIs under their own prefix and list it on your registry line: `api=["/api/<prefix>"]` (P17 switches a module off per tenant by prefix) | serve a module's API from a shared prefix |

Jobs inherit the tenant they were queued in (the worker sets it); `asyncio.to_thread` and FastAPI's thread pool carry
it; `loop.run_in_executor` and `threading.Thread` do not — do not use them.

## Rules that apply to every branch

1. **Never touch the live install**: no `docker compose up/down/restart/build`, no `docker rm` of `gen-bi-*`
   containers, no writes to `output/projects/` (copy a project into a scratch folder if you need a fixture — only
   small ones), no `.env` changes. Unique names for anything Docker you create: suffix them with your phase
   (`relay-p12-web`, `relay-p12-net`, image tags `gen-bi-webapp-p12`). Remove them when done.
2. **Test your code without rebuilding shared images**: mount your worktree over the image:
   `docker run --rm -w /srv -e PYTHONPATH=/srv:/opt/genbi -e D2D_AUTH=header -e WORKSPACES=/tmp/p -e D2D_STATE=/tmp/s -e D2D_BACKUPS=/tmp/b -e GENBI_LIBRARY=/tmp/lib -e AGENT_URL=http://127.0.0.1:9 -v "<worktree>/tests:/tests:ro" -v "<worktree>/webapp/app:/srv/app:ro" -v "<worktree>/webapp/static:/srv/static:ro" gen-bi-webapp python /tests/<your>_test.py`
   (Git Bash: `export MSYS_NO_PATHCONV=1`, paths from `pwd -W`, quote them — the folder has a space). For a
   browser check, run a throwaway web app the same way with `-d --name relay-<phase>-web --network relay-<phase>-net`
   and Playwright from `--entrypoint python3 gen-bi-agent` on that network (see `tests/p9_e2e.sh`).
3. **Mocks, not accounts**: every platform is stood in for by the mock lab (`tests/mocklab/`, `build-plan.md` §6):
   API simulators (a small FastAPI/http.server in the test), export fixtures, engines in containers, synthetic
   media. A fake `claude` CLI stands in for the agent (see `tests/phase5_agent_test.py`). No real credentials.
4. **The rules that never change** (`build-plan.md` §2): a person confirms every step that matters (open a
   checkpoint, never auto-apply); proven before it ships; one AI job at a time in the lane; read-only by default,
   writes only with a per-change approval; secrets by name in `secrets_store`; nothing invented.
5. **Quality bar** (`build-plan.md` §8): every screen has its states (empty, loading, error, success, read-only,
   placeholder), evidence one click away, plain British English, WCAG 2.2 AA (axe clean), phone to 4K, dark mode
   (tokens only — never a hard-coded colour), white-label safe (no hard-coded brand text; use `brandName()` /
   `S.brand`), audited. Wording: the platform and agent are "Relay"; "D2D" only names the dashboard module.
   `tests/brand_gate_test.py` must stay at 0 problems.
6. **Line endings**: files that go into Linux images must be LF (`.gitattributes` keeps bytes as committed; write
   LF explicitly from Python on Windows).
7. **Commit on your branch** as you complete each coherent step (messages end with
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`); do not merge, rebase or push; do not switch branches.
   When done, make sure `git status` is clean and your last commit message summarises the phase.
8. **Report** (your final message): what is built and where, the done-when evidence, every test with its command
   and result, what you could not do and why, and anything the merge must watch (shared files you touched).
