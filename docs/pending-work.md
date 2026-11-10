# RELAY by PASDACS — what is still to be developed

As of 2026-11-07 (late evening), after the PASDACS rebrand and the merge of every wave branch into `main`. Module counts come from the
module registry (`webapp/app/registry.py`); "live" means the module has a working screen on the workbench or its own
page. Unfinished code that was on the wave branches is kept in `webapp/wip/` (not loaded by the app).

## 1. Modules not built yet (none of the 56 catalogue modules)

| Pillar | Live | Still to build |
|---|---|---|
| Process | 6 of 6 | — (Test plans & UAT scripts finished 2026-11-06; it writes the cases to Xray, Zephyr Scale or TestRail after an approval and reads them back, 2026-11-07) |
| Automation | 6 of 6 | — (Workflows & iPaaS, RPA, Document processing and Job scheduling finished 2026-11-07; what is still to build inside them is listed below) |
| Systems | 14 of 14 | — (CRM & sales, HR & payroll, Identity & access, PLM, Collaboration & content, Integration & APIs, Cloud & CI/CD finished 2026-11-06; Apps & products and Connections finished 2026-11-07; what is still to build inside them is listed below) |
| Data & Analytics | 12 of 12 | — |
| Artificial Intelligence | 8 of 8 | — (AI governance & evaluation finished 2026-11-06) |
| Consulting Services | 10 of 10 | — |

### Still to build inside the modules

- **Building new things (Develop)**: Integration & APIs (a new flow), Cloud & CI/CD (a new pipeline), Apps & products (a
  new app), RPA (a new bot) — today these modules assess, fix and watch what runs; Develop
  writes to the customer's repository or studio and needs its own design. Moving a flow or a pipeline between
  platforms (Migrate) for Integration & APIs and Cloud & CI/CD likewise.
- **RPA on Blue Prism and Automation Anywhere**: read, assessed and moved; fixing a bot there is not offered — both
  import a changed bot only through their own desktop tools (the API has no import), so Relay hands the change to a
  person. UiPath (a new package) and Power Automate Desktop (the script through Dataverse) are fixed after approval.

Closed 2026-11-07 (late evening):
- **Job scheduling**: AutoSys jobs move to Control-M (Migrate takes cron and AutoSys): the JIL converted by rules — the
  schedule (a box's for its jobs), conditions as events, envvars as variables, file watchers, alarms — and proven: the
  next five runs on both, every condition an event, jobs started by their conditions ordered daily and waiting for them;
  a job on an AutoSys calendar is flagged for a person to check the calendar's dates on Control-M.
- **Document processing**: a Change work changes a live document type — its fields, checks and confidence lines — or
  moves it to another engine, measured against today on a labelled sample before the Run item switches (the type as it
  was is kept). The Run item also takes documents from an Outlook mailbox (Microsoft Graph, read-only) and a SharePoint
  or OneDrive folder, each round taking only what is new.
- **Job scheduling Develop** (closed later the same evening): a new job on Control-M or AutoSys — defined in a table (rules
  refuse a taken name, an unknown host, a password on the command line, a wait on a job that is not there), written as a
  Control-M folder or JIL, proven (the scheduler's build, the next five runs, every wait real), deployed after its own
  approval and read back from the scheduler.
- **Process mining**: the "what-if" — Estimate's "Run the what-if" replays the event log with the share a bot takes, the
  cut in each wait and the re-work stopped, and shows today against the what-if (throughput, re-work, people's hours).
- **Test plans**: Xray, Zephyr Scale and TestRail connections; Run (and Change's Learn) writes the new cases after an
  approval and reads them back case by case. A case changed after it was written is listed for a person, not rewritten.

From the earlier product plan, not yet in the registry: **Build from video** (screen recording → process map / SOP →
automation and tests) as its own module, and **self-healing for automations** beyond what Self-healing covers today.

## 2. Follow-ups in what is built

Closed 2026-11-07: project reads retry briefly when a save races them on the Windows mount (the occasional Errno 61);
the Service desk, Integration analytics, Data observability and workbench schedulers start with the app; Team & agents
counts every agent's run time (workbench steps and rules included); schedules can run monthly (a day 1–28 or the last
day); one Boomi or MuleSoft connection serves both Integration & APIs and Workflows; the house-style check keeps
product names (Unity Catalog, Partner Center …); the `_switched_on` alias is gone; the Tenants e2e flow waits for the
page instead of a fixed time.

- Closed 2026-11-07: `tests/wb_w4readers_test.py` runs an item of each W4 module through the generic readers (CSV, TSV, Excel; a
  Celonis connection) and the generic item screens — it found that a TSV upload had no view; the data layer now reads TSV.
- `wb_plm` started failing on 2026-11-07 at 10:00 UTC: its Teamcenter simulator ran on the fixed lab clock (2026-11-02) while the
  rule counts aborted workflows over the last 7 days of the real clock. The PLM suite now runs its simulators on the live clock.
  Closed for every suite: the look-back windows (Job scheduling 30 days, Workflows and RPA 60, PLM 7, the "inactive for
  60 days" rule) read `wb.lab_now()`, which in test mode only (D2D_TEST_HOOKS=1) is moved to the lab's date by
  D2D_LAB_SHIFT (set by tests/w3_kit.py and tests/w3_e2e.sh); the PLM suite is back on the fixed clock.
- Closed: `wb_assist`'s worded-answers check read the item before the queued action had run; it now waits for the action
  to finish (wb_w5_kit.settle).
- The projects folder stays on the Windows bind mount (reads now retry); moving it to a Docker volume is an operations
  choice for the live install.
- Oracle connections (2026-11-10): Oracle Database and Oracle Retail MFCS are in the Connections hub and on the main
  branch, proven on a real Oracle Database 23ai Free and on the `oracle_mfcs` simulator, and deployed live on 2026-11-10
  (webapp and agent images rebuilt; the webapp image now carries python-oracledb). Not built yet: writes to MFCS
  (its supplier / item create and update services), MFCS batch history from Process Orchestration and Monitoring (POM)
  for the ERP module's Run work, the Retail Data Store (RDS) as a SQL source (today through the Oracle Database
  (REST-enabled SQL) connection to its ORDS workspace), pulling other systems' objects into dashboards (one flag on
  their adapter: `extract = True`), and the data warehouse module's query history from a direct Oracle connection
  (DBA_HIST needs DBA rights; it says so and goes on).

- UX audit (2026-11-10, `docs/ux-audit-2026-11-10.md`). Still open:
  - Usage & statements takes about 13 s on the live data: each request walks every project folder. Caching the
    folder sizes would fix it. The page now says what it is doing while it loads.
  - Admin › Monitoring shows rule codes (`daxcheck_offline`, `backup_old`), "build lane" and "Ask D lane", and the
    runner id `claude-code`.
  - A few rare server messages are terse ("Unknown version", "Bad request: …", "(status: …)").
  - Non-admins no longer see model names on screen, but the API responses that list runs still carry model ids.

## 3. Platform gaps (P17 tenants and operations)

- Single sign-on per tenant, tested with a real identity provider (needs a pilot IdP).
- A real Kubernetes apply (only the manifest check runs today). Closed 2026-11-07: a monthly AI limit for a whole workspace
  (Admin › Costs & quotas) and a watchdog pass per workspace (its overdue schedules, its AI budget, work items stopped on an
  error — to that workspace's own admins).
- Relay Doctor (built 2026-11-10, doctor/README.md). Still open:
  - Browser (JavaScript) errors are not reported yet.
  - Crashes inside the agent service only get the routine restart, not an AI fix.
  - A version that does not start after a person's deploy is rolled back and handed to a person.
  - Starting it with Windows (a scheduled task at sign-in) needs the user's OK. Today `doctor\start-doctor.cmd` starts it.
- Relay in one container (2026-11-10, `docs/single-container.md`). Still open:
  - Closed 2026-11-10 11:31: Relay Doctor restarted on the user's word with the one-container settings. It reads the
    live commit from the image label and watches the `relay` container (good image kept as `relay:doctor-good`).
    `doctor-loop.cmd` restarts it after a crash (exit code 1), not after a forced stop (exit code -1). To restart it,
    close its window and run `doctor\start-doctor.cmd`.
  - The stopped per-part containers (`gen-bi-*`) and their volumes (`d2d-pg`, `d2d-state`, `d2d-llm`, `d2d-orch`) are
    kept for a rollback. Removing them, and the old image tags (`:deploy-*`, `:doctor-prev`, `:doctor-good`, the three
    runner images), needs the user's OK.
  - The test suites still use the per-part images under their old names (`gen-bi-webapp`, `gen-bi-agent`), built by
    `docker-compose.dev.yml` (project `gen-bi`). Renaming them touches about 75 test files.
  - Per-person workspaces (the orchestrator) need the multi-container deployment. The one container uses the shared
    AI engine, as the live install did.
  - The image is 5.8 GB. Most of it is Chromium, the AI CLIs, LiteLLM and the data connectors.
  - Demo readiness check (2026-11-10 afternoon, test-report.md §23). The web app could not save in folders from
    before the move (they belong to uid 1000). The live folders were repaired at 13:50 on the user's word, and
    relay-init now repairs them at every start (eafc8e5). Still not live until the next deploy: the watchdog's
    sign-in to the supervisor, so a hung part is not restarted yet, and the start-up repair itself.
  - Small things seen on the way: Ask D says "your 0 connection(s)", and the bell still holds three DAX checker
    warnings from the morning (resolved since). A dashboard's Overview shows the Windows path of its Power BI project,
    which still contains the folder name "Gen BI" (decision D7 keeps the folder's name). Admin › Relay Doctor shows
    "live commit a888cae2", its record of the last `doctor.py deploy`. The running image is fe1980f, the one-container
    move, which bypassed `doctor.py deploy`. Fixes start from the image's label (fe1980f), so only the page is stale.
    Admin › Monitoring's database tile shows a setting name, "Relay_DATABASE_URL".

## 4. Needs a real account or a pilot (everything is proven on the mock lab today)

Jira / Freshservice / ServiceNow, an ERP, a BI tool and a procurement portal (decision D5); Microsoft Graph licence
reports, Azure Cost Management, Snowflake account usage, UiPath Orchestrator licences, the Power BI admin activity API;
real-model runs of the agents' wording drafts and of reading requirement documents; audio transcripts (speech-model
download); an Oracle Retail MFCS environment (an OAuth client made in Retail Home) and an Autonomous Database with
mutual TLS — the wallet hand-over to python-oracledb is checked, a real TCPS listener with a wallet is not.

## 5. Brand (decision D1)

Done 2026-11-06: the PASDACS brand pack and the contact address info@pasdacs.com. Still open: whether "by PASDACS"
shows on every Enterprise screen or only on sign-in and PDFs. Client Power BI report themes follow each client's brand
and were left unchanged on purpose.

## 6. House-keeping

- Closed 2026-11-07: the 11 finished worktrees under `.claude/worktrees` and their merged local branches are deleted.
  Their six copies on GitHub (all merged into main) are deleted too.
- Old projects keep their old visual names until they are rebuilt (decision D10).
