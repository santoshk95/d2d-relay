# RELAY by PASDACS

**Relay** is PASDACS's platform where agents do the repeated work of a data & analytics team (and the wider process,
automation, systems, AI and consulting work around it), people validate and decide, and leads see everything —
proven, audited, always with a person in the loop.

- **Six pillars, about 56 modules**: Process · Automation · Systems · Data & Analytics · Artificial Intelligence ·
  Consulting services. Live today: **D2D** (describe a dashboard → plan → confirm KPIs → prototype → review gates →
  Power BI project), **Ask D** (ask your data with your own access), Connections, Ontology & metrics, Visuals,
  Sample data, Reports & alerts, Pages & publishing, and the platform (SSO, teams, sharing, AI runners, monitoring,
  costs, backups). Every other module shows how it will work, step by step, until its phase builds it.
- **Rules that never change**: a person confirms every step that matters; proven before it ships; one AI job at a
  time per lane; read-only by default; nothing invented.
- **Plans**: `build-plan.md` (the plan to build from), `platform-plan.md` (design history), `sweep-20261105.md`
  (the sweep that produced plan v2), `test-report.md` (latest test results). The signed-off clickable mockup is
  `mockup-a2z/a2z-mockup.html`.

## Run

Relay runs as **one container**, `relay`: the web app, the AI engine (Claude Code, plus the Codex, Gemini and
Antigravity CLIs), PostgreSQL and the AI gateway, each part under its own user, run by a supervisor. The DAX checker
is the one part outside it: Power BI's engine is Windows-only, so it runs on this PC. Full guide:
`docs/single-container.md`.

```bash
relay build          # the image, from this folder (relay:latest)
relay start          # start and wait until ready: http://127.0.0.1:8000
relay status         # the parts and their health
relay login          # sign the AI engine in to Claude (first start on a new PC)
```

`relay` is `relay.cmd` (Windows). Elsewhere: `docker compose up -d`. Settings: `.env` (`.env.example`). Sign-in is
single-user until `RELAY_AUTH=sso` and a provider under Admin › Sign-in. Deploy a new version with
`py -3 doctor\doctor.py deploy`.

**DAX checker** (needed to approve and publish): double-click `daxcheck\start-daxcheck.cmd`. The top bar shows
**DAX checker on**; Admin › Monitoring warns when it is off. Relay Doctor starts it when its heartbeat stops.

The one-container-per-part stack (`docker-compose.dev.yml`) builds the images the test suites use
(`docker compose -f docker-compose.dev.yml build`) and is the base for Kubernetes (`deploy/kubernetes`).

## What is where

| Folder | What |
|---|---|
| `webapp/` | FastAPI app: the shell (`static/`), module registry (`app/registry.py`), Home (`app/home.py`), dashboards, identity, connectors, semantic layer, Ask D, publishing, schedules, monitoring, backups |
| `agent/` | Claude Code running as the agent in a project folder, with the `genbi` toolkit only; other runners in `Dockerfile.runner` |
| `genbi_kit/` | the toolkit the agent uses: definition schema (`GENBI.md`), data profiling, demo data, prototype, PBIP builder, review gates, DAX checker client, visual factory |
| `visuals/`, `visual-atlas/`, `visual-library/`, `custom_visuals/` | the 8 Relay visuals (source), the Visual Atlas families (13, 60 chart types), visuals the factory built for earlier reports, and the packaged copies baked into the images |
| `Dockerfile`, `docker/`, `docker-compose.yml`, `relay.cmd` | the one container: image, start-up and supervisor, compose file, the `relay` command |
| `orchestrator/`, `litellm/`, `deploy/kubernetes/` | per-person workspaces, the LiteLLM gateway (Bedrock, Azure, Vertex), Kubernetes manifests |
| `daxcheck/`, `doctor/` | the Windows-side DAX checker and Relay Doctor (finds, fixes and deploys fixes for Relay's own crashes) |
| `branding/` | the PASDACS brand pack for Relay (`pasdacs/`) and the D2D product marks |
| `mockup-a2z/` | the signed-off clickable mockup (v0.12) |
| `tests/` | every suite; `bash tests/run_all.sh` (every suite + brand gate), `bash tests/single_container.sh` (the one container), `bash tests/run_infra.sh` (gateway, orchestrator, k3s, database move) |
| `output/` | projects (`output/projects/<id>/`), backups, test runs — never in git |
| `archive/` | superseded material kept for history |

## How a dashboard is built (the D2D module)

1. **Describe**: upload CSVs, connect a warehouse, or let Relay generate realistic demo data; say what the dashboard
   should answer; add a picture of a design you like.
2. **Plan**: the agent profiles the data and proposes the model, KPIs with their DAX and the pages; you edit and confirm.
3. **Prototype**: a clickable HTML prototype computed from your data; ask for changes until it is right.
4. **Review gates**: every version passes the definition, prototype, custom-visual, Power Query, data, DAX engine,
   values, PBIR schema, consistency, best-practice, accessibility and display checks — before approval and again
   before publishing.
5. **Publish**: the Power BI project (PBIP) with its custom visuals, ready to open in Power BI Desktop; download it,
   push it to GitHub, export pages as PDF / PNG, schedule reports and alerts.

Internal names (`genbi` CLI, `genbi_kit`, `GENBI.md`, the names the code reads, such as `D2D_AUTH`) are unchanged by design
(build-plan v2, decision D7); `.env` uses `RELAY_*` names, which are copied to them.

## Limits (demo)

One agent, one run at a time; jobs queue behind each other. No sub-agents, no web access for the agent. The DAX
checker runs on this PC. Power BI Desktop shows an old project from memory: close without saving before reopening a
regenerated folder, then Refresh.
