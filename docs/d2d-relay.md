# D2D Relay

D2D means Data to Decision: D2D Relay is a product of the Relay Platform by PASDACS (RELAY), run as a separate
product for a client. A person brings CSV files
and describes the dashboard. D2D Relay plans it, agrees the KPIs, builds a prototype and reviews it. The result is a
checked Power BI file (.pbix) with its data. Warehouses and databases are connected by PASDACS for an organisation on
request.

It is separate from RELAY. It lives in its own folder (`Downloads\D2D Relay`) with its own git repository. It has its
own image (`d2d-relay:latest`), containers, volumes, projects folder (`data\projects`), DAX checker and Power BI file
maker queues and sign-in.
Only the Claude sign-in volume (`claude-api-auth`) is shared, so both apps use the same Claude subscription.

| | |
|---|---|
| Public address | https://d2d-relay.pasdacs.com (Cloudflare tunnel) |
| Admin portal | https://admin-d2d.pasdacs.com: PASDACS only, behind Cloudflare Access and its own email code (see "Admin portal") |
| On this PC | public site http://127.0.0.1:8100, admin portal http://127.0.0.1:8102 |
| Sign-in | a 6-digit code emailed to any **business** address (no passwords, no SSO); free and disposable mail refused |
| Organisations | one per email domain, each in its own workspace; the first person creates and owns it |
| Credits | 50 to start, more when PASDACS approves a request; a new dashboard uses 25, a change 10, Ask Relay 10 for up to 5 questions (see "Organisations and credits") |
| Platform admins | every **@pasdacs.com** address, on the admin portal only (every organisation, credits, connectors, requests) |

## Containers

Four containers, split where the trust and the work differ (`docker-compose.yml`). The first three run the same image,
each in its own role (`RELAY_ROLE`, `docker/relay_init.py`), so they always run the same tested build.

| Container | Role | What runs | Reachable |
|---|---|---|---|
| `d2d-relay-db` | database | PostgreSQL 17 (volume `d2d-relay-db-data`) | the private Docker network only, with `RELAY_DB_PASSWORD` |
| `d2d-relay-web` | web | the public site: web app and AI engine (volume `d2d-relay-data`, `data\projects`) | 127.0.0.1:8100, d2d-relay.pasdacs.com |
| `d2d-relay-admin` | admin | the admin portal: web app only, no AI engine or jobs (volume `d2d-relay-admin-data`) | 127.0.0.1:8102, admin-d2d.pasdacs.com |
| `d2d-relay-tunnel` | | Cloudflare tunnel (profile `tunnel`) | outbound only |

Why split this way and not further: the admin portal is a separate trust boundary (the public container has no
admin APIs at all, so a bug on the public side cannot reach them), and both portals need one database, which the old
one-container layout kept behind its own Unix socket. The web app and the AI engine stay together: every build is
streamed from the engine to the web app, so they restart together anyway, and inside the container they already run
as separate Linux users that cannot read each other's keys.
| Code sender | info@pasdacs.com through Microsoft Graph (delegated Mail.Send, signed in once) |
| Data sources | CSV / flat files (New dashboard → upload), or demo data Relay generates. Connectors (BigQuery, Snowflake, Fabric, Redshift, Athena, Oracle) only once PASDACS switches them on for the organisation (see "Connectors") |

## What was kept and what was switched off

`webapp/app/edition.py` is the one place that decides this.

- **Kept:** Dashboards (D2D: plan → KPIs → prototype → review → Power BI file), the review gates and the Power BI engine
  check, the visual library, sample data, Connections (connectors on request), Ask Relay, Branding, organisations
  and credits, sharing a dashboard, and asking a colleague to review a version (the Review card on its Overview).
  There is no administration on the public site: every `/api/admin` path answers 404 there. PASDACS works on the
  admin portal (Organisations, Requests).
- **Switched off:** all other modules (process, automation, systems, AI, consulting), schedules, pages, the
  semantic layer, the service desk, Migrate BI, self-healing, AI SDLC, the workbench and the tenants console, and
  GitHub versioning and Slack / Teams channel posts. Their APIs answer 404 and their background pollers do not
  start. Old links open the dashboards list.

## Start and stop

```
docker compose up -d                       # database, public site and admin portal (this PC)
docker compose --profile tunnel up -d      # plus the public tunnel
docker compose --profile tunnel down       # stop everything (data stays in the volumes and data\)
docker compose restart admin               # one container only (here the admin portal; the public site keeps running)
docker logs -f d2d-relay-web
```

`.env` needs `RELAY_DB_PASSWORD` (letters and digits; `.env.example` says how to make one).

**Backups.** Every night (21:00 UTC, `RELAY_BACKUP_HOUR_UTC`) the public site writes every workspace's data and
project folders to `data\backups` and keeps the last 14 (`RELAY_BACKUP_KEEP`). A full database dump at any time:
`docker exec d2d-relay-db relay-ctl db-dump` writes `data\backups\relay-db-<time>.dump`. A dump goes into a new
install with `relay-ctl stage-import <dump>` in its database container before its first start.

**Moving from the one container** (`d2d-relay`, before 2026-11-11): after `git pull`, run
`powershell -ExecutionPolicy Bypass -File docker\move-to-split.ps1 -Tunnel` in the deploy folder while nobody is
building. It dumps the database into `data\backups`, stops the old container (kept for a rollback), adds
`RELAY_DB_PASSWORD`, loads the dump into the new database container and starts everything. Rollback:
`docker compose down` then `docker start d2d-relay`.

Start the DAX checker for D2D Relay too (it watches `data\projects\.daxcheck`, not RELAY's queue). Run
`daxcheck\start-daxcheck.cmd`. It runs side by side with RELAY's checker. Then start the Power BI file maker (below).
To have both start by themselves after a restart, see "After the PC restarts".

### Power BI file maker

What people download is `<Report>.zip`: `<Report>\<Report>.pbix` and `<Report>\data\*.csv`, nothing else (the CSV
files are left out above 100 MB; the data is inside the `.pbix` anyway). Only Power BI Desktop can save a `.pbix`, so
the app writes and checks the report, then asks the maker on this PC for the file:

- **Start it:** double-click `pbix\start-pbix.cmd` in the deploy folder (a minimised window, "D2D Relay Power BI file
  maker"). It watches `data\projects\.pbix` and makes one file at a time: about 40 seconds for a small dashboard,
  about 3 minutes for 10 million rows. Starting it twice is harmless: the second window says so and closes.
- **It needs a signed-in, unlocked Windows session:** it drives Power BI Desktop's window (open, refresh, Save as),
  so Power BI Desktop windows open and close by themselves while it works. Leave the PC signed in; a locked screen
  or a sign-out stops it. Power BI Desktop must be the Microsoft Download Center version (English), not the Store one.
- **`C:\D2D Relay Data` is its folder:** every `.pbix` is made with its DataFolder parameter at
  `C:\D2D Relay Data\<Report>\data\`, so unzipping a download into `C:\D2D Relay Data` lets Power BI Desktop
  refresh it as it is. The maker made the folder (marked by `.d2d-relay-converter`) and empties each report's
  folder after use; do not keep anything else there. Power BI Desktop works in `C:\D2D Relay Data\.work`, a short
  path on purpose: Save as fails ("Something went wrong") once a report's files lie deeper than Windows' 260
  characters, and the projects folder is too deep for that.
- **When it is not running:** publishing waits two minutes, then stops with "The Power BI file maker is not running
  on the D2D Relay PC", and every PASDACS person gets a notification (at most once an hour). Start it, then press
  Retry on the dashboard. A dashboard published earlier shows "Make the Power BI file" instead of the download.
  The app's watchdog also warns PASDACS when the maker has been offline for 10 minutes (as it does for the DAX
  checker), and says when it is back.
- **When a file fails:** the dashboard shows the reason; the maker keeps that run's log and a picture of Power BI
  Desktop's window in `data\projects\.pbix\work\<id>` for a day.
- It shares a lock (`Local\PbixBot-Convert`) with the UiPath PbixFromZip bot, so the two never drive Power BI
  Desktop at the same time.
- **What a report may do on this PC:** the refresh runs here, on the PC that holds D2D Relay's settings and data, so
  the maker first reads the report's Power Query and refuses it unless it only reads the dashboard's own data files
  (`File.Contents(DataFolder & "<a file of its data folder>")`) with the functions D2D Relay writes: no other folder,
  web address, database, `#shared` or `DataFolder` of its own. The app refuses such definitions too (hand-written
  Power Query, file names with folders). A dashboard on a warehouse is saved without a refresh: nothing of it runs
  here, and its owner presses Refresh in Power BI Desktop and signs in to their warehouse.

### After the PC restarts

Docker Desktop starts when you sign in to Windows, and the containers come back by themselves. The two helpers
start by themselves too once their shortcuts are in the Startup folder (one-time; Windows does not let an app put
them there for you):

1. Press Win+R, type `shell:startup` and press Enter: the Startup folder opens.
2. In another window, open `C:\Users\santosh.k\Downloads\D2D Relay`. Right-drag `daxcheck\start-daxcheck.cmd` into
   the Startup folder and choose **Create shortcuts here**. Do the same with `pbix\start-pbix.cmd`.

Until someone signs in after a restart (a Windows update can restart the PC), the site is down. Keep the PC from
sleeping (a keep-awake script does it) and signed in. A second copy of either helper refuses to start, so a
shortcut plus a double-click never runs two.

## One-time setup

### 1. Email codes (Microsoft 365, info@pasdacs.com)

The codes are sent AS info@pasdacs.com with a delegated sign-in. No client secret is needed (the pasdacs.com tenant
blocks them), and no Exchange policy is needed: a delegated app can only send as the account that signed in.

1. Go to Entra admin center → **App registrations → New registration**. Name it "D2D Relay sign-in mail", choose
   **single tenant**, leave the redirect URI empty, and click Register. Copy the **Application (client) ID** and the
   **Directory (tenant) ID**.
2. Under **Authentication**, set **Allow public client flows** to **Yes**, then Save.
3. Under **API permissions → Add → Microsoft Graph → Delegated permissions**, add **Mail.Send** and **offline_access**
   (User.Read is already there). Then click **Grant admin consent**.
4. Put the two IDs in `.env` (`RELAY_OTP_MS_TENANT`, `RELAY_OTP_MS_CLIENT_ID`) and run `docker compose up -d`.
5. Sign the mailbox in once. Run the command below, open the link it prints, enter the code, and sign in as
   **info@pasdacs.com**:

   ```
   docker exec -it -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.otp_mail login
   ```

   Check it with `... python -m app.otp_mail status`, or send yourself a test with `... python -m app.otp_mail test`.

The sign-in is kept encrypted in the app's secrets store, in the d2d-relay-data volume. The app uses it once a day, so
Microsoft never ends it for being unused. If info@pasdacs.com's password changes, or an admin revokes its sessions,
run `login` again. If a sign-in policy blocks device-code sign-in, an admin can allow it for this one app.

For a local test only, set `RELAY_OTP_DEV_LOG=1` and codes are printed in `docker logs d2d-relay-web` (and
`d2d-relay-admin`) instead. This is ignored once mail is set up. The admin portal sends its codes with the same
settings: app mode (a client secret) needs nothing more; in delegated mode, run the `login` command above in
`d2d-relay-admin` too.

Code rules: 6 digits, valid for 10 minutes, 5 tries. Per address: 1 code a minute and 6 codes an hour. Per network
(Cloudflare's `cf-connecting-ip`): 20 codes an hour. Only a salted hash is stored. A session lasts 12 hours
(`RELAY_SESSION_HOURS`).

`RELAY_OTP_EMAIL` (and `RELAY_ADMIN_EMAIL`) is info@pasdacs.com, the owner of the platform's own workspace, the
organisation "PASDACS". On the public site it is an organisation like any other; platform work is on the admin portal.

## Admin portal

https://admin-d2d.pasdacs.com is PASDACS's own site: **Organisations** (every organisation, its credits and
connectors), **Requests** (credits and connectors organisations asked for) and **Notifications**. It is a container
of its own (`d2d-relay-admin`); the public site answers none of its APIs. Two locks, both required:

1. **Cloudflare Access** in front of the hostname. The admin portal checks Access's signed token on every request that
   comes through Cloudflare (`app/portal.py`): the right application (AUD), the right team, not expired, and an
   @pasdacs.com address. Until `RELAY_ADMIN_ACCESS_TEAM` and `RELAY_ADMIN_ACCESS_AUD` are set, it refuses everything
   from the tunnel, so it works on this PC only (http://127.0.0.1:8102).
2. **The app's own email code**, for `RELAY_ADMIN_DOMAINS` addresses only (pasdacs.com). Every such address is a
   platform admin there; a new one joins the PASDACS workspace on its first sign-in. Its sessions have their own
   cookie and kind, so a session from the public site is not accepted there, and the other way round.

To open it through the internet (Cloudflare dashboard, once):

1. **Zero Trust → Access → Applications → Add an application → Self-hosted.** Name "D2D Relay admin", domain
   `admin-d2d.pasdacs.com`. Add a policy: Action **Allow**, Include **Emails ending in** `@pasdacs.com`. Login method:
   One-time PIN, or PASDACS's Microsoft sign-in if it is set up in Zero Trust.
2. From the application's overview, copy the **Application Audience (AUD) Tag**. The team name is the first part of
   your team domain (`<team>.cloudflareaccess.com`, Zero Trust → Settings).
3. In `.env`: `RELAY_ADMIN_ACCESS_TEAM=<team>` and `RELAY_ADMIN_ACCESS_AUD=<tag>`, then `docker compose up -d admin`.
4. **Networks → Tunnels → d2d-relay → Public hostname → Add:** subdomain `admin-d2d`, domain `pasdacs.com`, service
   **HTTP**, URL `d2d-relay-admin:8000`. Do this last, so the hostname never exists without Access in front of it.

## Organisations and credits

Anyone with a business email address can sign in. Free and disposable mail (Gmail, Outlook, Yahoo, iCloud, Proton,
Mailinator …) is refused; add or allow domains with `RELAY_PUBLIC_DOMAINS_EXTRA` / `RELAY_PUBLIC_DOMAINS_ALLOW`
(comma-separated).

- **The first person from a domain** names their organisation after the code and becomes its main owner. They then
  see the first-time setup: the brand (logo, description, palette), which they can skip. Everyone who signs in later
  from the same domain joins that organisation as a member, and the owners are told.
- **People** (Organisation page). An organisation can have several owners. Owners add people from the
  organisation's own domain as members or owners (each gets an invitation email and signs in with a code), change
  anyone's role, and remove people: a removed person is signed out and cannot sign in again until an owner adds them
  back; their dashboards stay, and owners can open them. The main owner (PASDACS's contact and the one who does the
  first-time setup) cannot be removed or made a member; they hand the main ownership to someone else first (Transfer
  ownership), staying an owner or not.
- **Each organisation is its own workspace.** Dashboards, connections, branding, Ask Relay conversations and people
  are never visible to another organisation. Inside one, each person's dashboards are private until shared; the owner
  can open them all.
- **Credits are shared** by everyone in the organisation. The top bar shows the organisation and its credits;
  Organisation (`#/org`) shows the owner, the people, the costs and the credit history.

| What | Credits |
|---|---|
| Start | 50 (`RELAY_CREDITS_START`); more come only when PASDACS approves a request |
| New dashboard (plan, KPIs and first prototype) | 25 (`RELAY_CREDITS_DASHBOARD`) |
| A change: revise the plan, a change request, building a suggested custom visual, an Ask Relay answer sent to a dashboard | 10 (`RELAY_CREDITS_CHANGE`) |
| Ask Relay: up to 5 answered questions in one conversation (`RELAY_CREDITS_ASK_QUESTIONS`), charged at its 1st, 6th, 11th … question | 10 (`RELAY_CREDITS_ASK`) |
| Confirming the plan, fixing failed review gates, approving and publishing, brand palettes | free |

A request without enough credits is refused before anything starts, with the balance in the message. When a run
fails, is stopped, or is cut off by a restart, its credits come back on their own; Retry then uses them again. Every
AI cost is still recorded on the server (the `usage` table); the screens show no tokens and no cost breakdown. Ask
Relay shows the credits a conversation used and the questions left in them; a question that gets no answer gives
its credits back.

**Getting more credits (PASDACS approves every request).** Anyone with a business mailbox can sign up; a new
organisation gets its 50 starting credits at once, and more only when PASDACS approves them. Online payment is not built yet.

1. Someone in the organisation clicks **Request credits** (top-bar chip, Organisation, Dashboards, or the message
   when credits run short), picks an amount and adds a message. One request can wait at a time; the person who asked,
   or the owner, can withdraw it to ask for a different amount. The request also goes to info@pasdacs.com
   (`RELAY_CREDITS_CONTACT`) by email with Reply-To set to the person, and to every PASDACS person's notifications.
   They can also simply email info@pasdacs.com.
2. On the admin portal, **Requests** lists it as waiting (and Organisations shows what each organisation asks for).
   **Approve** adds the credits at once, the amount asked or another one, with an optional note for their credit
   history. **Decline** needs a reason. Either way the person who asked and the owner are told in the app and by email.
3. For a request that came by email, **Organisations → Credits** adds credits by hand with a note (a negative number
   takes credits back).

### 2. Public address (Cloudflare tunnel)

pasdacs.com's DNS is on Cloudflare, so no port is opened on this PC.

1. In Cloudflare, go to **Zero Trust → Networks → Tunnels → Create a tunnel** (type Cloudflared) and name it
   `d2d-relay`. Copy the token from the "Install connector" step.
2. In the tunnel, go to **Public hostname → Add**. Set subdomain `d2d-relay`, domain `pasdacs.com`, service
   **HTTP**, and URL `d2d-relay:8000` (the public site's container answers to that name too).
3. Create `tunnel.env` next to `docker-compose.yml` with one line, `TUNNEL_TOKEN=<token>`. Git ignores this file, and
   the app container never sees it.
4. Run `docker compose --profile tunnel up -d`. Then open https://d2d-relay.pasdacs.com.

Cloudflare provides the certificate. pasdacs.com sends HSTS includeSubDomains, so the address must be https, and it
is. Optional extra lock: a Cloudflare Access policy (email one-time PIN for the same address) in front of the hostname.

### 3. Connectors (on request)

The public side takes CSV files only. **Connections** lists every connector D2D Relay can read: Google BigQuery,
Snowflake, Microsoft Fabric, Amazon Redshift, Amazon Athena and Oracle Database (`edition.CONNECTORS`). Each one is
"On request" until PASDACS switches it on for that organisation.

1. A person clicks **Ask PASDACS to connect it** (Connections), picks the connectors and adds a message. The request
   goes to info@pasdacs.com (`RELAY_CREDITS_CONTACT`) by email, Reply-To the person, and to the platform admins'
   notifications. A prefilled email link is the fallback.
2. When it is agreed, a platform admin opens **Organisations** on the admin portal, clicks **Connectors** for the
   organisation and ticks the ones to switch on. The owner is told, and the organisation can then add connections for them (and pick
   "From a warehouse" on New dashboard).
3. Switching a connector off stops it at once for that organisation: its connections stay but cannot be tested,
   queried or pulled from, and scheduled refreshes pause with a note on the dashboard. They can still be removed.

PASDACS's own workspace has every connector switched on. For BigQuery, the simplest way in for a client is a
service-account JSON (roles BigQuery Data Viewer + BigQuery Job User). Queries are read-only and limited to 1 GB
scanned by default.

## Updating

Build from a clean commit and restart while nothing is running (a restart of `d2d-relay-web` cuts off a build):

```
git status            # clean
set RELAY_COMMIT=<git rev-parse HEAD> && docker compose build web && docker compose up -d
```

`docker compose up -d` starts again only the containers whose image or settings changed; a change for the admin
portal alone can go out with `docker compose up -d admin` while builds run on the public site.
