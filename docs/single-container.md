# Relay in one container

> **D2D Relay** runs this image as four containers, one role each (`docs/d2d-relay.md`, "Containers"). This guide is
> RELAY's: the parts inside the image, the users they run as and the tools below still apply, and `RELAY_ROLE=all`
> still runs everything in one container.

Relay runs as **one Docker container, `relay`**, from one image (`Dockerfile` at the repository root). The web app,
the AI engine, the database and the AI gateway all run inside it, each part under its own Linux user, started and
watched by a process supervisor. On a Windows PC, two helpers run next to it: the **DAX checker** and **Relay Doctor**.
The DAX checker has to stay outside the container because Power BI's engine only runs on Windows.

## Day to day (this PC)

| | |
|---|---|
| `relay start` | starts Relay and waits until it is ready. It adds the office address (`RELAY_LAN_IP`) when that address is on the PC right now |
| `relay stop` | stops Relay. Everything it keeps stays: database, settings, projects |
| `relay status` | the parts inside the container, their health, the version |
| `relay logs` | follows the log (Ctrl+C stops following, not Relay) |
| `relay backup` | writes a database dump to the backups folder |
| `relay export` | puts everything Relay keeps (database, keys, gateway settings, projects, library) in one file in the backups folder, for another PC |
| `relay import <file>` | loads such a file into a new install, before its first start |
| `relay login` | signs the AI engine in to Claude (first start on a new PC, or after the sign-in expires) |
| `relay open` | opens Relay in the browser |
| `relay build` | builds the image from this folder (about 15 minutes the first time) |
| `relay load <file>` | loads the image from a package file |

`relay` is `relay.cmd` in the repository root: type `relay start` in a Command Prompt, or `.\relay.cmd start` in
PowerShell (PowerShell does the work: `relay.ps1`). Relay is at
http://127.0.0.1:8000, and on the office network at http://10.20.0.100:8000 when this PC has that address.

To deploy a new version, use `py -3 doctor\doctor.py deploy`. It builds the image from a clean copy of the commit,
labels it with that commit, backs up the database, tries the new image on a copy of the live data, swaps it in at a
quiet moment and rolls back by itself if the new version is not healthy. Close Relay Doctor's window first; start it
again afterwards with `doctor\start-doctor.cmd`.

## Before a demo

1. `relay status`: every part shows `RUNNING` and the health line says `healthy`.
2. The top bar in Relay shows **DAX checker on**. If it doesn't, double-click `daxcheck\start-daxcheck.cmd`. Relay
   Doctor also starts the checker when its heartbeat stops. Nothing can be approved or published without it.
3. The AI engine is signed in: Admin › Monitoring shows the AI engine up. If a run fails because the sign-in has
   expired, run `relay login`.
4. Away from the office: `relay start` again. It leaves out the office address when that address isn't on the PC.
   Otherwise Docker can't start the container.
5. With `RELAY_AUTH=single`, anyone who opens Relay is the admin. On a shared network, use `sso` (Admin › Sign-in) or
   show Relay from this PC only.
6. Relay Doctor on **Only report crashes** (mode `watch`) for the length of the demo: Admin › Relay Doctor. On *Fix
   and deploy by itself* (`auto`), a crash starts a fix run that holds new jobs while it works and may swap the
   container at a quiet moment. Its routine work goes on in every mode: the DAX checker, a stopped queue, a version
   that does not start. Switch it back afterwards.
7. The bell: mark old warnings as read (for example a DAX checker warning that has since been resolved), so the
   audience doesn't see them.

## What is inside

| Part | Runs as | Where | What it is |
|---|---|---|---|
| web | `relay` (uid 1001) | port 8000 | the web app people use |
| agent | `agent` (uid 1000) | 127.0.0.1:8090 | Claude Code, plus the Codex, Gemini and Antigravity CLIs, behind one service; one run at a time per lane |
| database | `postgres` | Unix socket only | PostgreSQL 17. No TCP listener: each Linux user signs in as its own role (peer) |
| gateway | `relay` | 127.0.0.1:4000 | LiteLLM for Amazon Bedrock, Azure AI Foundry and Google Vertex AI. It starts once such a provider has routes |
| watchdog | root | – | stops the container if a part can't start (Docker then starts it fresh), and restarts a part that has stopped answering for 5 minutes |

Each part gets only its own settings: `relay-init` writes one environment per part at every start, and the
launcher gives a part exactly that one. The AI engine never sees the web app's keys or passwords. It can't read
`/data/state` (the key for saved credentials) or `/data/llm` (the gateway's credentials), can't sign in to the
database, and can't control the supervisor. `tests/single_container.sh` checks each of these.

What it keeps, and where:

| Inside the container | Comes from | Holds |
|---|---|---|
| `/data` | volume `relay-data` | `state/` (key, encrypted secrets), `llm/` (gateway settings), `postgres/` (the database), `import/` (dumps to load) |
| `/data/projects` | folder `RELAY_PROJECTS` (this PC: `output\projects`) | every project. Power BI Desktop opens them and the DAX checker serves their queue |
| `/data/backups` | folder `RELAY_BACKUPS` (this PC: `output\backups`) | the app's nightly backups and database dumps |
| `/opt/genbi/library` | folder `RELAY_LIBRARY` (this PC: `visual-library`) | the visual library. A new install starts with the visuals the image ships |
| `/home/agent/.claude` | volume `RELAY_CLAUDE_VOLUME` (this PC: `claude-api-auth`) | the AI engine's Claude sign-in |
| `/opt/agy-login` | volume `RELAY_AGY_VOLUME` (this PC: `antigravity-api-auth`), read only | the Antigravity CLI's Google sign-in |
| `/opt/genbi/config` | folder `config` | the model lists (`models.json`, `house-models.json`). Edits apply without a restart |

Settings are in `.env` (`.env.example` lists every one). The `RELAY_*` names are copied to the names the code reads
(`D2D_*`), so either spelling works.

## A new PC

1. Install Docker Desktop. Copy the package folder (`dist\relay-<version>\`) to the PC.
2. `relay load relay-<version>.tar.gz`, then copy `.env.example` to `.env`.
3. To bring this PC's dashboards and settings along: run `relay export` here, copy the file across, and on the new
   PC run `relay import <file>` before the first start. The file holds the key to the saved credentials, so keep it
   as safe as the PC.
4. `relay start`, then `relay login`, then open http://127.0.0.1:8000.
5. To publish to Power BI, also install Power BI Desktop and start the DAX checker:
   `daxcheck\start-daxcheck.cmd`. In the package it serves `data\projects`.

## Going back to one container per part

The per-part stack (`docker-compose.dev.yml`, project `gen-bi`) is still there for development, the test suites and
Kubernetes. Its data from before the move (volumes `d2d-pg`, `d2d-state`, `d2d-llm`) is untouched. To run it instead
of the one container:

```bash
docker compose -f docker-compose.yml stop
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d
```

Anything done in the one container after the move is not in that older database.

Project folders are shared differently in the two layouts. The per-part web app ran as uid 1000 and owned every
folder. In the one container the web app is uid 1001, and both it and the AI engine share the folders through the
group `relaydata`. At every start, `relay-init` gives older folders this shared layout: group `relaydata`, group read
and write, setgid folders. Owners stay as they are and nothing is rewritten. It also hands the library and the backups
to the web app. Going back, the per-part web app can still read what the one container wrote but can't change it.

## Tests

`bash tests/single_container.sh` runs a new install of the image on an internal network (no internet). It checks
the parts, their users and settings, folders left as the per-part stack left them (uid 1000, not group-writable) and
whether the web app can save in them, the watchdog's sign-in to the supervisor, every GET endpoint, a killed part
coming back, and a container restart.

`bash tests/single_container.sh <dump>` does the same for a move: the dump plus copies of the keys, projects and
library. Add `AI=1` for one real Claude run, a Chromium render and every CLI, with internet but without the web app.
The per-part images (`docker compose -f docker-compose.dev.yml build`) are still what `bash tests/run_all.sh` tests.
