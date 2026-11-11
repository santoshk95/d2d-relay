# D2D Relay by PASDACS

D2D means **Data to Decision**: D2D Relay is a product of the **Relay Platform** by PASDACS.

D2D Relay turns a company's CSV files into a checked Power BI dashboard. A person signs in with their work email,
uploads CSV files and describes the dashboard they need. D2D Relay plans it, agrees the KPIs with them, builds a
clickable prototype, checks every version (Power BI's own engine included) and hands over a Power BI file (.pbix)
with its data.
Each company is an organisation with its own workspace, people and credits; PASDACS runs the platform from its own
admin portal.

It is the Relay Platform's dashboard product, run as a product of its own. The rest of the platform's code (RELAY) is
still in this repository, switched off in one place (`webapp/app/edition.py`).

| | |
|---|---|
| Public site | https://d2d-relay.pasdacs.com (on the D2D Relay PC: http://127.0.0.1:8100) |
| Admin portal | https://admin-d2d.pasdacs.com, PASDACS only (on the D2D Relay PC: http://127.0.0.1:8102) |
| Setup and operations | [`docs/d2d-relay.md`](docs/d2d-relay.md) |
| Where things stand, what was decided, what is open | [`docs/LOG.md`](docs/LOG.md) |

## Run

Four containers (`docker-compose.yml`); the first three run the same image, one role each:

| Container | What runs |
|---|---|
| `d2d-relay-db` | PostgreSQL 17, on the private Docker network only |
| `d2d-relay-web` | the public site: the web app and the AI engine (Claude Code) |
| `d2d-relay-admin` | the admin portal: organisations, credits, connectors and requests, behind Cloudflare Access |
| `d2d-relay-tunnel` | the Cloudflare tunnel for both addresses |

```
copy .env.example .env                  (then fill it in: docs/d2d-relay.md)
docker compose build web
docker compose --profile tunnel up -d
```

Two helpers run on Windows next to them, because Power BI only runs there. Publishing a dashboard needs both:

- the **DAX checker** (`daxcheck\start-daxcheck.cmd`): Power BI's engine checks every measure and visual query;
- the **Power BI file maker** (`pbix\start-pbix.cmd`): Power BI Desktop makes the `.pbix` people download. It drives
  Power BI Desktop's window, so it needs a signed-in Windows session (docs/d2d-relay.md, Power BI file maker).

## What is where

| Folder | What |
|---|---|
| `webapp/` | the FastAPI app: `app/` (the API; D2D Relay's own parts are `edition.py`, `orgs.py`, `otp.py` and `portal.py`) and `static/` (the screens) |
| `agent/` | the AI engine's service: Claude Code in a project folder, with the `genbi` toolkit |
| `genbi_kit/` | the toolkit: definition schema (`GENBI.md`), data profiling, demo data, prototype, report builder, review gates, DAX checker and Power BI file maker clients, visual factory |
| `visuals/`, `visual-atlas/`, `visual-library/`, `custom_visuals/`, `visual_factory/` | Relay's custom Power BI visuals: sources, the Visual Atlas families, visuals built for earlier reports, packaged copies, and the kit the factory builds new ones with |
| `Dockerfile`, `docker/`, `docker-compose.yml` | the image, its start-up (`relay_init.py`: one role per container), supervisor and tools (`relay_ctl.py`, `move-to-split.ps1`) |
| `daxcheck/` | the Windows-side DAX checker |
| `pbix/` | the Windows-side Power BI file maker (`pbix.ps1`, and `Convert-D2DZip.ps1`, which drives Power BI Desktop) |
| `config/` | the model lists (the Relay Model) |
| `branding/` | the PASDACS brand pack |
| `samples/` | sample CSV files |
| `docs/` | `d2d-relay.md` (setup), `LOG.md` (work log and hand-over), `rls-backlog.md`, and RELAY's design notes, kept for reference |

## How a dashboard is built

1. **Describe:** upload CSV files (or let Relay generate realistic demo data), say what the dashboard should answer,
   and add a picture of a design you like. Warehouses and databases are connected by PASDACS, on request.
2. **Plan:** Relay profiles the data and proposes the model, the KPIs with their DAX, and the pages; you edit and
   confirm them.
3. **Prototype:** a clickable prototype computed from your data; ask for changes until it is right.
4. **Review gates:** every version is checked (definition, prototype, Power Query, data, DAX in Power BI's engine,
   values, report schema, best practice, accessibility, display) before approval and again before publishing.
5. **Publish:** a zip with the Power BI file (`<Report>.pbix`, the data inside) and its CSV files, ready to open in
   Power BI Desktop.

A new organisation starts with 50 credits. A new dashboard uses 25, a change 10, and Ask Relay 10 for up to 5
questions in a conversation. More credits come from PASDACS, which approves every request.

Internal names (`genbi`, `genbi_kit`, and the `D2D_*` settings the code reads) are kept from RELAY; `.env` uses
`RELAY_*` names, which are copied to them.
