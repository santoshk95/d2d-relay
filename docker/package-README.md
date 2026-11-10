# RELAY by PASDACS {{VERSION}}

The whole Relay platform in one Docker container: the web app, the AI engine (Claude Code, plus the Codex, Gemini and
Antigravity CLIs), its PostgreSQL database and the AI gateway. Image `relay:{{VERSION}}`, commit {{COMMIT}}, packaged
{{DATE}}.

| File | What |
|---|---|
| `relay-{{VERSION}}.tar.gz` | the image (check it against `SHA256SUMS`) |
| `docker-compose.yml`, `docker-compose.lan.yml` | how the container runs; the second adds a network address of this PC |
| `.env.example` | every setting (copy to `.env`) |
| `relay.cmd` / `relay.ps1` (Windows), `relay.sh` (Linux, macOS) | start, stop, status, logs, backup, export, import, login |
| `config/` | the model lists |
| `daxcheck/` | the DAX checker, Windows only, for publishing to Power BI |
| `data/` | the projects, backups and visual library |
| `GUIDE.md` | the full guide |

## Start

1. Install Docker Desktop (Windows, macOS) or Docker Engine with the compose plugin (Linux).
2. Open PowerShell or a Command Prompt in this folder:

   ```
   .\relay.cmd load relay-{{VERSION}}.tar.gz
   copy .env.example .env
   .\relay.cmd start
   .\relay.cmd login
   ```

   On Linux or macOS, use `./relay.sh` wherever this says `.\relay.cmd`, and `cp` for `copy`. `.\relay.cmd login` signs the AI engine in to Claude:
   type `/login`, follow the link, then `/exit`.
3. Open http://127.0.0.1:8000.

To bring the dashboards and settings of another Relay along, run `.\relay.cmd export` there and copy the file across.
Then, before the first `.\relay.cmd start` here, run `.\relay.cmd import <file>`. The file holds the key to the saved credentials, so
keep it as safe as the PC.

## Every day

| | |
|---|---|
| `.\relay.cmd status` | the parts and their health |
| `.\relay.cmd logs` | the log (Ctrl+C stops following) |
| `.\relay.cmd backup` | a database dump in `data\backups` |
| `.\relay.cmd stop` / `.\relay.cmd start` | everything Relay keeps stays in the `relay-data` volume and `data\` |

Publishing to Power BI needs the DAX checker on a Windows PC with Power BI Desktop: double-click
`daxcheck\start-daxcheck.cmd`.
