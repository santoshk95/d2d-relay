# The module workbench — how to make a catalogue module real

> 2026-11-06. The engine every wave module (W1–W6) is built on. Read `docs/parallel-work.md` first (plug-in points,
> tenancy, the rules that never change); this guide is what you need for one module. The pilot is **Data quality &
> reconciliation** (`webapp/app/packs/quality.py`, `quality_rules.py`) — read it next to this page.

## 1. What you get, and what you write

| Part | File | You |
|---|---|---|
| The engine: work items, journeys, the five step kinds, checkpoints, evidence, outputs, the evidence pack, proof checks, Run & support, APIs | `webapp/app/workbench.py` | use it — do not edit it for one module |
| Prompts around a pack's agent steps (system prompt, fix round, correction) | `webapp/app/workbench_prompts.py` | use it |
| **Your module pack** | `webapp/app/packs/<module id>.py` (+ helpers `<module id>_*.py`) | **write it** — auto-imported, no shared edit |
| The screens (module page, wizard, item page) | `webapp/static/js/33-workbench.js` | nothing: they draw your pack |
| The catalogue line | `webapp/app/registry.py` MODULES (+ `LIVE`) | set `status="available"`, `route="#/m/<id>"`, `links`, `api=["/api/m/<id>"]`; add `"<id>": "#/m/<id>"` to `LIVE`. **`api` is required**: it is the prefix P17 answers 403 under where the module is switched off, and `register()` refuses a pack whose line does not name it |
| Tests | `tests/wb_<module>_test.py` (+ a `.sh` runner if it needs engines) | write them; one `add` line in `tests/run_all.sh` |

A **work item** is one piece of work of one module and one work type (`assess`, `develop`, `change`, `migrate`,
`run`, or `engage` for consulting modules). It is a folder under `store.root()` with kind `work`: `project.json`
(state, steps, results), `activity.jsonl`, `request.md` (the brief and every decision), `WORK.md` (your guide for the
agent), `data/` (uploads), `evidence/<step>/<id>.json`, `outputs/`. The index row is `wb_items`; owner, team and
visibility are the `projects` row, so sharing and permissions are the dashboards' (Viewers never change anything;
private items are their owner's; a named approver gets view access).

## 2. A small, complete pack

`webapp/app/packs/excel.py` — Excel & spreadsheet models, Assess only. `tests/workbench_test.py` reads this page and
runs this exact code (registers it, takes a workbook through the journey), so the example cannot rot:

```python
"""Excel & spreadsheet models (registry id `excel`) — Assess: what the workbooks hold and where they are fragile."""
from __future__ import annotations

from .. import workbench as wb


def connect(ctx: wb.Ctx) -> dict:
    books = ctx.files((".xlsx",))
    if not books:
        raise wb.StepFailed("Upload the workbooks to assess (.xlsx).")
    return {"summary": f"{len(books)} workbook(s) uploaded — a read-only copy.",
            "data": {"columns": ["Workbook", "Size"], "rows": [[f["name"], f["bytes"]] for f in books]}}


def inventory(ctx: wb.Ctx) -> dict:
    import openpyxl
    rows = []
    for f in ctx.files((".xlsx",)):
        book = openpyxl.load_workbook(ctx.dir / "data" / f["name"])          # formulas, not their values
        for ws in book.worksheets:
            cells = [c for row in ws.iter_rows() for c in row if c.value is not None]
            formulas = sum(1 for c in cells if isinstance(c.value, str) and c.value.startswith("="))
            rows.append({"id": f"{f['name']}!{ws.title}", "book": f["name"], "sheet": ws.title, "cells": len(cells), "formulas": formulas, "include": True})
    ctx.put("sheets", rows)
    return {"summary": f"{len(rows)} sheet(s) found.", "records": rows,
            "data": {"columns": ["Workbook", "Sheet", "Cells", "Formulas"], "rows": [[r["book"], r["sheet"], r["cells"], r["formulas"]] for r in rows]}}


def health(ctx: wb.Ctx) -> dict:
    checks = []
    for r in ctx.records("inventory"):
        if not r.get("include"):
            continue
        share = r["formulas"] / r["cells"] if r["cells"] else 0
        checks.append({"name": r["id"], "label": f"{r['book']} › {r['sheet']}", "status": "pass" if share >= 0.1 else "warn",
                       "measured": f"{share:.0%} formulas", "expected": "at least 10 %",
                       "detail": "mostly typed-in numbers: a person re-keys them" if share < 0.1 else "driven by formulas"})
    checks.append(ctx.proof("references_real", label="Every included sheet exists", refs=[c["name"] for c in checks],
                            known=[s["id"] for s in ctx.get("sheets") or []]))
    return {"summary": f"{sum(c['status'] != 'pass' for c in checks)} sheet(s) to look at.", "data": {"checks": checks}}


wb.register(wb.Pack(
    module="excel",
    platforms={"files": wb.FilesPlatform()},
    work={"assess": wb.Work(title="See what the workbooks hold and where they are fragile", steps={
        "Connect": wb.Step(kind="platform", run=connect, agent="Reader"),
        "Inventory": wb.Step(kind="platform", run=inventory, agent="Scanner",
                             edit=wb.Edit(columns=[wb.Column("include", "Include", "bool"), wb.Column("sheet", "Sheet", readonly=True)],
                                          add=False, remove=False, label="sheet")),
        "Health": wb.Step(kind="proof", run=health, view="gates", agent="Checker"),
        # Findings and Estimate have no handler yet: the engine makes them person steps (nothing pretended)
    })}))
```

With its registry line saying so — `status="available", route="#/m/excel", links={"assess": "excel"},
api=["/api/m/excel"]`, and `"excel": "#/m/excel"` in `LIVE` (the test sets `api` in memory before it runs the code
above) — that is a live module: `#/m/excel/assess` lists its items, New work creates one, Connect → Inventory (waits:
"what was found, in the tool's own terms") → Health → Findings and Estimate (a person records what was done) → done,
evidence pack. Then write the test.

## 3. Journeys and confirm points

- The journey of a work type is `registry.plan_for(module, work)["journey"]` — the module's own (PLAN) or the generic
  one (GENERIC) — with the step texts beside it. `Work(journey=[...])` replaces it; then give every Step its `text`.
- A pack's steps are keyed by the **journey name** (`"Hand over"`) or its id (`"hand-over"`). A stage with no handler
  becomes a person step that asks what was done and where its evidence is — never a fake success.
- The person confirms at the registry's **confirm points** (`registry.confirm_for`). They land on the step of the
  same name, or through `ALIASES` (Design → Shape, Diagnosis → Diagnose, Release → Approve / Ship, Findings → Analyse,
  Direction → Agree, Plan → Deliver). `Step(confirm="…")` sets your own text (the label stays the registry's);
  `confirm=False` never pauses; every `kind="person"` step pauses. `confirm_if=fn(ctx, result)` pauses only when it
  returns True (the pilot's Run report pauses only when there were breaks).

## 4. The five step kinds

| Kind | What runs | Where | Typical use |
|---|---|---|---|
| `deterministic` | `run(ctx) -> dict` | the worker lane (job `wb_step`, no AI) | rules first: suggest, compile, estimate, publish |
| `agent` | `prompt(ctx) -> str`, then `check(ctx) -> [problems]` (fix rounds, `worker.FIX_ROUNDS`), then `after(ctx, agent_result) -> dict` | the lane (job `wb_agent`, `worker.agent`, one AI job at a time) | drafting, reading unstructured input |
| `person` | `run(ctx) -> dict` that only *shapes* earlier results (quick, no I/O) | inline, then a checkpoint | decisions, approvals, manual steps |
| `platform` | `run(ctx)` using `ctx.platform()`, `ctx.connections()`, `ctx.reader()`, `ctx.request_write()` | the lane (`wb_step`) | test a connection, scan inventory, read run logs, request a write |
| `proof` | `run(ctx)` returning a `gates` view built from `ctx.proof(...)` rows | the lane (`wb_step`) | counts, checksums, totals, sample diffs, tests run, references real |

**The result dict** a step returns: `summary` (one or two sentences), `data` (the view's payload, §6), `records`
(rows a person may edit, when the step has `edit`), `counts` ({label: number} for the queue), `items` (up to 12
lines the Validation queue shows), `ok` (False stops the journey for a person without a confirm), `next` (a later
step id to jump to; the ones between are skipped — the pilot's Alert jumps to Report when nothing broke). Raise
`wb.StepFailed("a reason a person can act on")` for a clean failure: the step shows it with **Run again**.

Rules and platform runs are recorded in the item's `runs` with model `rules` (no AI cost) so Team & agents shows your
agents at work; agent runs are recorded by `worker.agent` with their stage `<module>.<step>` (and `.<action>`).
`Step.agent` is the name Team & agents shows ("Profiler", "Rule writer").

**Actions** (`Step(actions={"wording": wb.Action(...)})`) are helpers a person starts on a waiting or done step — an
agent draft, a re-read. They update the step (summary, data, records) and never move the journey. The pilot's
"Ask Relay to draft the wording" writes one sentence per rule and leaves the rules untouched.

## 5. `Ctx` — what every step function gets

| Member | What it is |
|---|---|
| `ctx.id`, `ctx.module`, `ctx.work`, `ctx.title`, `ctx.brief`, `ctx.scope`, `ctx.owner`, `ctx.who` | the item, its wizard fields, its owner, who started this run (None for scheduled rounds) |
| `ctx.dir` | the item's folder (`store.root() / id`, computed now — never keep it in a module variable) |
| `ctx.get(k)`, `ctx.put(k, v)` | pack data kept on the item between steps (saved when the step completes) |
| `ctx.result(step_id)`, `ctx.records(step_id)` | an earlier step's stored result / its (confirmed) records |
| `ctx.connections()`, `ctx.connection(id)` | the item's connections as its owner may use them (shared ones included) |
| `ctx.files(exts)` | the uploads (`{"name", "bytes", "table"?}`; an `.xlsx` also gets its first sheet as a CSV table) |
| `ctx.platform()` | the item's Platform adapter |
| `ctx.reader(ref)` | a read-only reader: `{"source": "file", "file": …, "item"?: …}` → DuckDB; `{"source": "connection", "connection": …, "object": …}` → the guarded live query of a warehouse (sqlglot transpiles from DuckDB's dialect) or an SDK platform's records. Readers have `columns()`, `count()`, `stats(cols)`, `dupes(keys)`, `run(sql)`; use `wb.table_sql(r)` in SQL |
| `ctx.evidence(label, payload, kind=…, ok=…)` | one piece of evidence for this step → its id (the screens open it in one click) |
| `ctx.output(name, content, label=…)` | a file in `outputs/` (data, configs, code, documents) |
| `ctx.proof(name, label=…, **kw)` | run a proof check; stores its full result as evidence; returns a `gates` row |
| `ctx.lineage_node(kind, system, name, own=True)`, `ctx.lineage_edge(a, b, kind)` | the lineage graph (P13). `own=False` for nodes other modules share (a warehouse table): not linked to your item |
| `ctx.request_write(connection_id, obj, payload, what)` | the only way to write to a platform: a `connection.write` checkpoint; the adapter writes when it is accepted |
| `ctx.heal(title, what, …)`, `ctx.ticket(title, body, …)` | Run & support hand-offs — call them only after a person approved (a confirm step) |
| `ctx.note(text, level)` | a line in the item's activity |

## 6. Views — the payload `data` has for each

Views are the checkpoint service's: `table` `{"columns": […], "rows": [[…]]}` · `gates` `{"checks": [{"name",
"label", "status": pass|warn|fail|skip|error, "measured", "expected", "detail", "severity"?, "evidence"?, "parts"?}]}` ·
`plan` `{"items": [{"title", "detail", "effort"?}], "total"?, "note"?}` · `text` `{"text"}` · `link` `{"href",
"label", "text"?}` · `fields` `{"fields": [{"name", "type", "rule", "confidence"}]}` · `mapping` `{"pairs": [{"from",
"to", "rule", "status"}]}` · `process` `{"steps": [{"label", "actor", "next": […]}]}` · `kpis` `{"kpis": [{"name",
"value", "formula"}]}` · `prototype` `{"href"}`. A view keeps 500 rows in `project.json`; put the rest in evidence.

## 7. Records a person corrects in place

`Step(edit=wb.Edit(columns=[wb.Column(key, label, type, options, help, required, readonly)], add, remove, validate))`.
Types: `text`, `longtext`, `number`, `select` (options as values or `(value, label)` pairs, or a callable `(ctx)`),
`bool`. Columns you do not list are kept on each row (ids, origins, parsed parameters). `validate(records, ctx)` returns
the problems that stop a save — **rules first: refuse what cannot run** (the pilot parses every rule's check). The same
validation runs before a confirm (in place and from the queue: a row that cannot run re-opens the check). Edits are
counted and audited (`wb.step.edited`). Keep the person's edits when a step runs again (`ctx.records(ctx.step_id)`
first, then your new suggestions).

## 8. Checkpoints

Every confirm opens one checkpoint of kind `wb.<module>` (labelled with the module's short name) for the item's
owner, or — for `Step(approver=True)` — the named approver picked in the wizard. It shows in the Validation queue with
its view, summary, counts and the first rows, and links to the step on the item page (`#/m/<id>/i/<item>?step=…`).
Accept moves on; **send back** needs a comment and runs `back_to` (default: the step itself) again with
`ctx.comment` (agent steps get it in their prompt). Decisions are signed, timed, audited and counted in Team & agents.
`route` (an item's "Hand a problem on") opens an approval of the same kind before a ticket or Self-healing case goes out.

## 9. Platforms and adapters

```python
class MyPlatform(wb.Platform):
    id, label = "uipath", "UiPath Orchestrator"
    kinds = ("uipath",)                  # connection kinds (connectors.KINDS; an SDK adapter: connectors_sdk, one adapter + one mock)
    uploads = (".nupkg", ".xaml")        # what a person may upload instead
    simulator = "tests/mocklab/… UiPath simulator"
    reads = "packages, processes, queues and job history — read-only"
    def logs(self, ctx, since=None): ...  # run logs [{"when", "what", "status", "detail"}]
```
Defaults: `test(ctx)` tests the item's connections of your kinds and lists the uploads; `objects(ctx)` browses them
(`connectors.browse`) and lists uploaded tables; `read(ctx, ref, limit)` reads through `ctx.reader`. `WarehousePlatform`
(Snowflake, BigQuery, Fabric, Redshift, Athena, PostgreSQL, SQL Server) and `FilesPlatform` (CSV, Parquet, Excel) are
ready. A new platform needs a connector adapter (`connectors_sdk.Adapter`, registered at import, + its `connectors.KINDS`
entry) and its mock-lab simulator; writes go through `ctx.request_write` only.

## 10. Proof checks

Built in (`workbench.PROOFS`): `row_count(source, target, tolerance_pct)`, `checksum(source, target, columns)` —
engine-independent fingerprints (count, sum, min, max, distinct, total length per column), so a source in one database
reconciles with a target in another —, `totals(source, target, measures, by, tolerance_pct)`, `sample_diff(source,
target, keys, n)`, `tests_run(results)`, `references_real(refs, known)`. Register more with
`@wb.proof("name", "Label")` → `fn(ctx, **kw) -> {"status", "measured", "expected", "detail", "rows"}`.

## 11. Agent steps and prompts

`prompt(ctx)` returns the stage instructions; the engine wraps them (`workbench_prompts.frame`: the stage, the item,
"write only these files", a short end message) and sends the work item's system prompt (Relay, the folder, CLAUDE.md
is the dashboard guide — ignore it, WORK.md is yours, nothing invented). Write `Pack.guide` (WORK.md): what the module
does and how its files look. `check(ctx)` must be strict (the agent's file parses, ids exist, nothing invented);
`after(ctx, result)` turns the file into the step result. Put the data the agent needs in the folder first (the
pilot writes `rules.json`). Turns and timeouts: `Step(turns=…, timeout_s=…)`.

## 12. Evidence, outputs and the hand-over

Evidence is attached to the step that wrote it and listed on the item page; `GET …/evidence/<id>` returns it. At
hand-over (every step done) `GET …/evidence-pack.zip` holds `summary.md`, `decisions.json`, `steps.json`, every
evidence file, `outputs/`, `activity.jsonl`, `request.md` and `handover/handover.docx` + `twin.html` built by the P11
docs engine (every table sourced from a record in the folder).

## 13. Run & support

- A wizard field named `schedule` of type `cadence` schedules the item (`{"every": hour|day|week, "at", "weekday", "tz"}`);
  `POST/DELETE …/schedule` changes it. Each round re-runs the journey from `Work.schedule_from` (default the first
  step); a round is skipped while the last one waits for a person. The pass is `workbench.tick()`: for each module
  with a pack, every tenant that has it switched on (`db.each_tenant(module)`, P17), every `WB_SCHED_S` seconds (60).
  Where the module is switched off its rounds wait; the first pass after it is back on runs the one that is due. The
  loop starts with the first workbench or Home request after a restart, on the worker's event loop (so a sync
  endpoint can start it) and in a clean context.
- `ctx.heal(...)` opens a Self-healing case (source `workbench`, the item as its subject); `ctx.ticket(...)` writes through
  a write-capable service-desk connection of the item (its own approval), else joins a matching Service desk group
  (its write-back gate), else leaves a ticket draft in the outputs. Both are recorded as hand-offs and audited.
  Call them from a step that follows a person's confirm (the pilot: Run › Fix confirmed → Approve applies).
- Data observability overlap: the item page and your steps can call `wb._observe_overlap(...)`; tables you record with
  `ctx.lineage_node("table", kind, object, own=False)` link to the observability asset and any open incident.

## 14. APIs (all under `/api/m/<module>/`, the prefix P17 switches off per tenant)

`GET overview?work=` · `GET items?work=&status=` · `POST items` (multipart: work, title, brief, platform, connections
JSON, scope JSON, approver, visibility, team_id, files) · `GET items/<id>` · `POST items/<id>/files` ·
`POST items/<id>/steps/<step>/run` (`{comment?, action?}`) · `PUT …/steps/<step>/records` · `POST …/steps/<step>/decide`
(`{decision: accept|send_back, comment}`) · `GET …/evidence/<eid>` · `GET …/outputs/<name>` · `GET …/evidence-pack.zip`
· `POST|DELETE …/schedule` · `POST …/route` · `POST …/visibility` · `POST …/stop` · `POST …/close` · tests only
(`D2D_TEST_HOOKS=1`): `POST …/steps/<step>/hook` (`{files, text}`: stands in for an agent run). Engine-wide:
`GET /api/workbench/packs` (each pack with its `state` here: `off` = switched off, `locked` = not in the edition),
`GET /api/workbench/summary`. A pack's own routes (`Pack.router`) must start with `/api/m/<module>/` (checked at
registration). Where the module is switched off for a workspace, every route under the prefix answers 403 before your
code runs (`tenancy.denied`, matched on the registry line's `api`) — which is why `register()` insists on it.

## 15. The screens you get, and what the pack still provides

You get: the live module page (`#/m/<id>/<work>`: work-type tabs with counts, the journey with each step's kind and
confirm, items with states and filters, an empty state, How it works, Where you confirm, Platforms, Connections, the
rules card), the New work wizard (work type, name, brief, connections of your platforms' kinds, uploads of their types,
your fields, a named approver when a step needs one, who can see it), the item page (journey stepper, each step's view,
confirm / send back in place, records editing with your validator's problems, actions, evidence and outputs one click
away, Run & support, decisions, lineage, Data observability overlap, activity, visibility, close), the Validation
queue entries, Home's Work in flight row, Team & agents names and links, `#/p/wb-…` links redirected. Loading, empty,
error, running, waiting, read-only (viewer), done, scheduled and closed states; switched off for this workspace (P17
state `off`: the module and item pages say so and that nothing is lost, the menu hides it) and not in the plan
(`locked`: the registry's own page); tokens only (dark mode), phone width.

The pack provides: the plain-language `text` of each step when the generic registry line is not true of your module,
your confirm wording, your agents' names, `Pack.cards(u)` for module-page tables (the pilot's Live rule sets), the
wizard `fields`, honest summaries (numbers from the data, never invented), and its tests.

## 16. Tenancy, permissions and the rules that never change

- Every request, job and background pass runs in one tenant (P17, `docs/P17-tenancy.md`): `db.q` / `one` / `run`
  and `store.root()` follow it (the platform's tree is the volume, any other tenant's is `.tenants/<t>/`). So: `db.q`
  only (tables from `db.register_schema` in your pack module); paths from `ctx.dir` / `store.root()` at call time,
  never from `WORKSPACES` and never kept in a module variable; no module-level caches of rows; the agent gets
  `store.rel(id)`.
- Background work only through the engine's schedule. If a pack ever needs its own pass, it loops
  `for t in db.each_tenant("<module>"):` so tenants that have the module switched off are skipped.
- Entitlements: where the module is switched off (or not in the edition), its API prefix answers 403 and the engine
  holds the work — no step starts (a decision taken in the Validation queue is recorded and the item waits with a
  note), no round runs, Home leaves the module out and the packs list marks it `off`. Items, evidence and schedules
  are kept and come back when it is switched on again.
- The engine registers the checkpoint kind `wb.<module>` without `own_admins`: a partner's consultant acting in a
  client's workspace under a grant confirms the steps of the items they can see, like anyone there. A decision only
  the workspace's own admins may take is not a work-item step (P17's `tenancy.access` is the `own_admins=True` kind).
- Read-only by default; every write is `ctx.request_write` (a person approves that very change).
- A person confirms every step that matters; nothing reaches a live system, a buyer or a client without a named
  approval; nothing invented — a figure without a source (the pilot's business totals) waits for the person.

## 17. Testing a pack

- Copy the patterns of `tests/workbench_test.py` (a fake agent HTTP server on `AGENT_URL`, `TestClient(main.app)` so
  the worker runs, `wait()` on the item's status, decisions through `/decide` and `/api/validate/<cid>/accept`) and
  `tests/wb_quality_test.py` (fakesnow for Snowflake, uploads for DuckDB, `tests/wb_quality.sh` for a real PostgreSQL).
- Platforms are mocks (`docs/parallel-work.md` rule 3): an API simulator in the test or `tests/mocklab/`, export
  fixtures written by the test, engines in throwaway containers named `relay-<yours>-*`.
- Assert the journey per work type, every confirm point, a send back, the validator refusing a bad row, the proof
  results and their evidence, the evidence pack, permissions (viewer read-only; private items invisible), a schedule
  round, hand-offs only after approval, Home and Team & agents.
- A second tenant (the engine suite shows how): create a client with `POST /api/tenancy/tenants` as the platform's
  admin, call as its people with the `x-d2d-tenant` header, check the item's folder is under `.tenants/<t>/`, then
  switch your module off with `PUT /api/tenancy/tenants/<t>/modules` and assert 403 under your prefix, state `off`,
  no round, nothing on Home — and that it all comes back when switched on. Call your GET routes across workspaces
  with the other's ids: nothing of it may show, nothing may answer 5xx.
- Shell e2e: add your routes and a flow to `tests/p9_e2e_test.py` behind an env flag your runner sets (the pilot:
  `WB_E2E=1`), axe on your pages.

## 18. A module is done when (build-plan.md)

- [ ] its live screen replaces the placeholder (pack registered; registry line `status="available"`, `route`, `links`, `api`)
- [ ] switched off for a workspace, it answers 403 under its prefix, says so on its page and runs nothing there
- [ ] each work type (or engagement step) has its steps and checkpoints working on the mock lab
- [ ] its connector(s) pass contract tests against their simulators
- [ ] its proof step works (numbers, records, test runs, references)
- [ ] it appears correctly in Home, Team & agents, the Validation queue and the Programme view (when that is built)
- [ ] the quality bar: every state, evidence one click away, plain British English, WCAG 2.2 AA (axe clean), phone to 4K, dark mode with tokens only, white-label safe, audited; `tests/brand_gate_test.py` at 0

## 19. Gotchas

- `ctx.files(())` is every upload; a Platform with no `uploads` must not list files (the engine guards it).
- PostgreSQL has no `round(double precision, integer)`: round in Python, compare with a tolerance.
- Warehouse objects come back as `DB.SCHEMA.TABLE`; match what a person typed by suffix on a dot.
- Snowflake returns upper-case column names: compare columns case-insensitively (`_cname` in the pilot).
- A person step's `run` must be quick (it runs in the request that reached it).
- Return `records` with stable `id`s; the engine keeps columns you do not list.
- In the browser, `h()` sets `value` as a property — Playwright's `input[value=…]` does not match; use `page.evaluate`.
