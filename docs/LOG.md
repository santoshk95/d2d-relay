# D2D Relay: work log and hand-over

Last updated: 2026-11-11 (IST). This file says where the project stands for anyone who clones it.

## What D2D Relay is

D2D means Data to Decision. D2D Relay is a product of the Relay Platform by PASDACS: cut from RELAY, the platform
(copied from Relay commit 8f3d9a0), as a product of its own for a client who wanted
Power BI dashboard generation from CSV files and Google BigQuery. It has its own repository, image, container, data and
sign-in. The setup guide is `docs/d2d-relay.md`.

- Live at https://d2d-relay.pasdacs.com, served through a Cloudflare tunnel (container `d2d-relay-tunnel`, token in the
  git-ignored `tunnel.env`). On the host PC it is http://127.0.0.1:8100.
- The admin portal, https://admin-d2d.pasdacs.com (PASDACS only; on the host PC http://127.0.0.1:8102).
- Four containers from one image (item 12): `d2d-relay-db` (volume `d2d-relay-db-data`), `d2d-relay-web` (volume
  `d2d-relay-data`, projects in `./data/projects`), `d2d-relay-admin` (volume `d2d-relay-admin-data`) and the tunnel.
  The public site shares the Claude sign-in volume `claude-api-auth` with RELAY.
- Two helpers run on the host PC: its own DAX checker (`daxcheck\start-daxcheck.cmd`, queue `data\projects\.daxcheck`)
  and the Power BI file maker (`pbix\start-pbix.cmd`, queue `data\projects\.pbix`; item 16).
- Deploy (in the deploy folder `Downloads\D2D Relay`, while nobody is building): `git fetch <repo> main` + `git merge
  --ff-only FETCH_HEAD`, `RELAY_COMMIT=<sha> docker compose build web`, `docker tag d2d-relay:latest d2d-relay:<sha>`,
  then `docker compose up -d --no-deps web admin` (the database container is left running).
- Code: GitHub `santoshk95/d2d-relay`, branch `main`. Items 11-20 were kept on this PC at the user's wish and pushed
  on 2026-11-11 when the user asked.

## Done so far (in commit order)

1. **Trimmed to dashboards.** `webapp/app/edition.py` keeps the modules d2d, bi, connect, gates, visuals, demodata,
   runners, ops and govern, and Google BigQuery is the only connection type. Every other module's API returns 404 and
   its background pollers are off.
2. **Email-code sign-in** (`webapp/app/otp.py`, `D2D_AUTH=otp`).
   - A 6-digit code, valid 10 minutes, 5 tries. One code a minute and 6 an hour. Only a salted hash is stored.
   - It is allowed for ONE address: `RELAY_OTP_EMAIL=info@pasdacs.com`.
   - Codes are mailed by `webapp/app/otp_mail.py` through Microsoft Graph. It runs in app mode (a client secret plus
     the application permission Mail.Send) when a secret is set, otherwise in delegated mode (device-code sign-in
     with `python -m app.otp_mail login`).
   - LIVE: app mode with a secret; a test mail was sent on 2026-11-10. NOT DONE: an Exchange ApplicationAccessPolicy
     that limits the app to info@pasdacs.com, so it can still send as any mailbox in the pasdacs.com tenant.
3. **Menu.** Dashboards, New dashboard, Ask Relay / Branding, Connections, Notifications. Settings, Administration
   and Visual library are gone, and their routes redirect to `#/d2d`.
4. **Relay Model only.** `worker.model_catalog()` returns only the house models (`config/house-models.json`, id
   `relay`), for admins too.
5. **No "Atlas" wording** on screens or in the agent's text (`prompts.py` forbids the word; the visuals are named
   "Relay ...").
6. **Branding** (`webapp/app/branding.py`, `static/js/35-branding.js`).
   - The user uploads a logo (Pillow reads its colours) and describes the brand.
   - The Relay Model makes 3 palettes (`askd.ask_json`) and the user picks one. It is stored in meta key `d2d_brand`.
   - New dashboards use it: `create_project` with `use_brand=1` gives `style` palette custom plus the colours, and
     those reach the theme in `request.md`.
   - Verified end to end: "Brand palette test" has the exact colours in the PBIP `GenBI_Theme.json`.
7. **Ask Relay** (the Ask D module re-enabled, `static/js/14-askd.js`).
   - A conversation page with an "Asking about" drop-down (All my data / one dashboard) and suggested questions built
     from each dashboard's `plan.yaml` KPIs (`askd_routes._suggestions`).
   - Progress steps while it works, and plain labels with a CSV download.
   - Charts are interactive, use the brand palette, and show value labels only when there are 12 points or fewer.
   - The model is told to write for business readers.
8. **AI cost** (changed by item 10). `GET /api/askd/costs` returned the month by work type and the cost of one
   conversation, shown on each answer, in a cost panel and on the Dashboards page.
9. **Organisations, credits and open sign-up** (`webapp/app/orgs.py`, `otp.py`, `public_domains.py`,
   `static/js/36-org.js`, `css/org.css`; the user's request of 2026-11-10).
   - **One tenant per organisation** (the P17 tenancy): its own schema and folders, so organisations never see each
     other's dashboards, connections, branding, Ask Relay conversations or people. `relay.tn_orgs` holds the
     organisation (tenant, name, email domain, owner, credits, setup done) and `relay.tn_credits` every change to its
     credits (start, charge, refund, adjust). Both are control-plane tables, so the nightly backup includes them.
   - **Sign-in** is open to business email domains. Public and disposable domains (Gmail, Outlook/Hotmail/Live, Yahoo,
     iCloud, AOL, Proton, GMX, Yandex, Zoho Mail, Rediffmail, QQ/163, Mailinator ..., plus their country variants)
     are refused at both steps. `RELAY_PUBLIC_DOMAINS_EXTRA` / `_ALLOW` adjust the list.
   - The first person from a domain gets "Create your organisation" after the code (name prefilled from the domain,
     their own name). They own it as the admin of that workspace only, and go to the first-time setup `#/setup`
     (step 2 is the Branding flow; "Skip for now" or "Finish"). Later people from the domain join it as BI Devs
     and the owner is notified.
   - `info@pasdacs.com` (`RELAY_OTP_EMAIL`) stays the platform admin. The platform's own workspace is the organisation
     "PASDACS" (pasdacs.com), with 100 credits from the upgrade and setup marked done. Other pasdacs.com addresses join it.
   - Code limits: 1 a minute and 6 an hour per address (as before), plus 20 an hour per network (`cf-connecting-ip`).
     A session is created in the person's own workspace, so the cookie is `<tenant>~<id>`.
   - **Administration is the platform admin's only.** `/api/admin/*` answers 403 to everyone else, organisation
     owners included (people, AI providers, monitoring, backups, Relay Doctor). An owner sees every dashboard of
     their own organisation, as Relay's admins always did.
   - **Credits** are pooled per organisation. The amounts are set by `RELAY_CREDITS_START` (100),
     `RELAY_CREDITS_DASHBOARD` (30) and `RELAY_CREDITS_CHANGE` (15). A change is: asking Relay to revise the plan, a
     change request on a prototype, "Build it" on a custom visual Relay suggested, or an Ask Relay answer sent to a
     dashboard.
     - **Free:** confirming the plan (the first build is part of the new dashboard), "Ask Relay to fix them" for
       failed review gates (the server writes that request from `gates.json`, so it cannot carry other changes),
       approving and publishing, Ask Relay questions, brand palettes.
     - Every request checks the balance before anything is saved. Not enough credits gives HTTP 402 with a clear
       message, and the screen opens Add credits.
   - **Refunds (decided here).** A run carries the id of the charge it delivers (job args `charge`). When that run
     fails, is stopped, or is cut off by a restart, the credits go back automatically: `worker._finish`, `worker.stop`
     and `worker.recover` call `give_back`, and the activity log says so. Retry then charges again, and the button
     shows "Retry - 30 credits".
     - A new dashboard's charge rides on through data/extract, plan and the first build until v1 exists, so a failed
       first build gives back the 30.
     - Runs from before this change carry no charge and retry for free.
   - **Add credits** (top-bar chip, Organisation page, Dashboards, and any 402) is "Paying online is coming soon".
     It sends a request to `RELAY_CREDITS_CONTACT` (info@pasdacs.com) by email through the same Microsoft Graph
     mailbox, with Reply-To set to the person. The request is prefilled with the organisation, the person and the
     amount, and a prefilled mailto link is the fallback. Requests also notify the platform admins in the app.
   - **Organisations** (`#/orgs`, platform admins): every organisation with its owner, people, dashboards, credits
     used and left, plus the credit requests. "+ Credits" adds or takes back credits; a note is required and is shown
     in the organisation's history.
   - **Organisation** (`#/org`, everyone): owner, people, credits and costs, and the credit history. The owner can
     rename it.
10. **AI cost display.** No tokens and no cost breakdown anywhere. The tokens/$ on the dashboard header, plan,
    versions, Details tab and activity log are gone, as are the Dashboards cost line and the per-answer cost in Ask
    Relay. Ask Relay shows only the open conversation's overall cost (`/api/askd/costs?thread=` returns just
    `thread_usd`). The APIs no longer send costs (`get_project` drops `usage` and run costs; activity events,
    answers and the list strip them). `/api/home` and `/api/me/usage` are blocked. Every cost is still recorded in
    the `usage` table on the server. The Details tab shows the credits the dashboard used instead.
11. **Connectors on request** (the user's request of 2026-11-11). The public side takes CSV files (and demo data
    Relay generates). Connections lists every connector D2D Relay can read (`edition.CONNECTORS`: Google BigQuery,
    Snowflake, Microsoft Fabric, Amazon Redshift, Amazon Athena, Oracle Database), each marked "On request".
    - **Asking:** "Ask PASDACS to connect it" emails the request to info@pasdacs.com and notifies the platform admins
      (`POST /api/org/connector-request`, audited as `d2d.connector_request`). A prefilled email link is the fallback.
    - **Switching on:** a platform admin ticks connectors per organisation on Organisations
      (`PUT /api/admin/orgs/{id}/connectors`, column `relay.tn_orgs.connectors`), and the owner is told. PASDACS's
      own workspace has all of them.
    - **Enforced on the server** (`orgs.require_connector`): adding, testing, browsing, querying, choosing tables,
      signing in again, pulling and refreshing need the connector switched on. Switched off, connections stay but are
      marked so, scheduled refreshes pause with a note, and Ask Relay leaves them out. Listing, sharing, disabling and
      removing still work. New dashboard offers "From a warehouse" only when a connector is on.
    - Checked on an isolated container: 28 API checks, and the screens (Connections, the request dialog, New
      dashboard, Organisations).
12. **Admin portal and split containers** (the user's request of 2026-11-11).
    - **Containers** (`docker-compose.yml`): `d2d-relay-db` (PostgreSQL 17, private network only, password
      `RELAY_DB_PASSWORD`), `d2d-relay-web` (the public site: web app and AI engine, also answers to `d2d-relay` so
      the tunnel's route still works), `d2d-relay-admin` (the admin portal: web app only) and `d2d-relay-tunnel`. One
      image, one role each (`RELAY_ROLE` in `docker/relay_init.py`: database | web | admin | all); the supervisor
      starts only that role's parts and `relay-ctl health` checks only those. The reasons are in `docs/d2d-relay.md`
      ("Containers"). `docker/move-to-split.ps1` moves the one-container install: dump, stop (kept for a rollback),
      password, load, start.
    - **Admin portal** (`app/portal.py`, `D2D_PORTAL=admin`): https://admin-d2d.pasdacs.com, PASDACS only.
      Organisations, Requests (credit and connector requests) and Notifications. Two locks: Cloudflare Access (its
      signed token is checked on every request through the tunnel: application, team, expiry, @pasdacs.com; until
      `RELAY_ADMIN_ACCESS_TEAM` / `_AUD` are set, nothing gets through the tunnel) and the app's own email code for
      `RELAY_ADMIN_DOMAINS` addresses, each of them a platform admin. Admin sessions have their own cookie
      (`d2d_admin`) and kind (`otp-admin`): neither site accepts the other's sessions. The portal answers only its
      own APIs and runs no AI engine, queue or schedules.
    - **The public site has no platform powers any more:** every `/api/admin` path answers 404 there, the
      Organisations page and menu item are gone, and info@pasdacs.com is the PASDACS workspace's owner like any
      other owner. `orgs.platform_admin` is true only on the admin portal.
    - `db.init` takes a PostgreSQL advisory lock, so the two sites starting together never change the schema at once.
    - Checked on an isolated split stack built from this code: 56 API checks (the admin portal and the connectors
      again), 10 checks of the Cloudflare Access token with a stand-in key (team, application, expiry, signature,
      address; fail closed), the screens of both sites, and a rehearsal of the move with a copy of the live database
      (126 tables loaded; PASDACS with its 70 credits and 4 dashboards).
13. **Credits only with PASDACS's approval** (the user's request of 2026-11-11, against abuse). A new organisation
    starts with no credits (`RELAY_CREDITS_START` empty = 0), so it cannot spend AI time until PASDACS says yes.
    - **Request credits** (was "Add credits") makes a request in `relay.tn_credit_requests` (pending, approved,
      declined, withdrawn); one can wait per organisation, and the person who asked or the owner can withdraw it. It
      is still emailed to info@pasdacs.com and notified to every PASDACS person. The Organisation page lists the
      requests and their answers; the chip shows one that is waiting.
    - **Admin portal -> Requests:** Approve (the amount may differ; the credits are added in the same transaction that
      marks the request approved, so never twice) or Decline (a reason is required). The person who asked and the
      owner are told in the app and by email. Organisations shows what each organisation asks for; adding credits by
      hand stays, for requests that came by email.
    - Checked on the split test stack: 26 API checks (no credits at the start, 402, one request at a time,
      withdrawing, approving another amount, once only, declining with a reason, a charge after approval), and the
      screens on both sites.
14. **People management** (the user's request of 2026-11-11; Organisation page, `/api/org/people`, `/api/org/transfer`).
    - **Several owners** (the workspace's admins, `users.org_role = 'admin'`) and one **main owner**
      (`relay.tn_orgs.owner_id`: PASDACS's contact and the first-time setup). Owners are told when someone joins.
    - **Owners** add people from the organisation's own domain as members or owners (an invitation email; they sign in
      with a code), change roles, and remove people (signed out at once; they cannot sign in again until an owner adds
      them back, from "Removed"; their dashboards stay). An owner can leave.
    - **The main owner** cannot be made a member or removed; only they hand the main ownership over (Transfer
      ownership), staying an owner or not, and the new main owner is told.
    - Checked on the split test stack: 27 API checks (roles, the domain rule, members refused, the main owner's
      protection, removing and signing in again refused, adding back, transfer, leaving), and the screens. With the
      earlier groups, 109 checks pass.
15. **Production clean-up** (the user's request of 2026-11-11).
    - **The temporary test login is gone** (`otp.py`, `login.html`, its section here): the per-address and
      per-network code limits always apply, and nobody signs in without an emailed code. Local tests read the code
      from the container's log instead (`RELAY_OTP_DEV_LOG=1`, only when no mail is set up).
    - `README.md` describes D2D Relay (it described RELAY, with folders and commands this repository does not have).
      `docs/single-container.md` says it is RELAY's guide; the setup guide's commands use the new container names.
    - An owner can add at most 30 people an hour (each one is emailed). The database container sees `data\backups`,
      so `docker exec d2d-relay-db relay-ctl db-dump` lands there (`docs/d2d-relay.md`, "Backups").
    - Checked on a test stack from the final image (no code mounted) with a fresh copy of the live database, signing
      in the real way (codes read from the container log): 121 API checks (the copied data, the clean-up and the code
      limits, the admin portal, connectors, credits, people) and the 10 Cloudflare Access token checks.
    - **Deployed on 2026-11-11 at 09:00 IST** (image `d2d-relay:aec0d13`, built from `aec0d13`), with
      `docker\move-to-split.ps1`. The live database was dumped (`data\backups\pre-split-20261111-090052.dump`) and
      loaded into `d2d-relay-db` (126 tables); the three containers came up healthy in about a minute. Checked
      afterwards: https://d2d-relay.pasdacs.com answers through the tunnel from `d2d-relay-web`; the admin portal
      answers on this PC and refuses requests through Cloudflare until Access is set up; the test login is gone;
      PASDACS has its 70 credits, all six connectors and its 4 dashboards; the DAX checker's heartbeat is seen; both
      sites got a token from Microsoft for the sign-in mail (nothing sent); no errors in the logs. The old container
      was removed. Its database files stay in the volume `d2d-relay-data` (`/data/postgres`, 67 MB) until someone
      deletes them; the dump above is the backup.

16. **The download is a Power BI file** (the user's request of 2026-11-11: only the .pbix and its data in the zip,
    and no mention of PBIP or a Power BI project anywhere).
    - What people download is `<Report>.zip` holding `<Report>/<Report>.pbix` and `<Report>/data/*.csv`, nothing
      else (the CSVs only up to 100 MB; the data is inside the .pbix anyway). No report folder, README, prototype or
      check reports.
    - Only Power BI Desktop can save a .pbix, so the app writes and checks the report as before (it stays in the
      project's `powerbi/` folder, never offered), then asks the new **Power BI file maker** on the D2D Relay PC for
      the file: `pbix/pbix.ps1` (started with `pbix\start-pbix.cmd`), the same queue-folder pattern as the DAX
      checker (`webapp/app/pbix.py` is the app's side). It opens the report in Power BI Desktop, refreshes it from the
      CSVs, checks that every table loaded and saves the .pbix (`pbix/Convert-D2DZip.ps1`, from the UiPath
      PbixFromZip bot). Every .pbix refreshes from `C:\D2D Relay Data\<Report>\data\`, so unzipping the download into
      `C:\D2D Relay Data` lets Power BI Desktop refresh it as it is.
    - Power BI Desktop works in `C:\D2D Relay Data\.work`: under the projects folder a report's files passed
      Windows' 260 characters and Save as failed ("Something went wrong"); the converter now stops at once when
      Power BI shows that box instead of waiting 15 minutes.
    - Publishing: DAX check, review gates, then the .pbix; the dashboard says "Power BI file ready". When the maker
      is not running, publishing stops with a plain message, PASDACS is notified (once an hour) and Retry finishes it.
      A dashboard published before shows "Make the Power BI file" (the `pbix` job: no new checks, no credits), and
      every published one has "Make the Power BI file again".
    - No "PBIP" or "Power BI project" on any screen, note or download: the screens, the server's messages, the gate
      name ("Report consistency"), the module texts and the agent's instructions (`prompts.py` forbids the words;
      `GENBI.md` says "report"). Older notes and gate names are shown with today's words (`store.plain`,
      `main._today_names`), and Relay's guide (the agent's CLAUDE.md) is no longer offered on the Details tab.
      "Version to GitHub" and "Make a page" are gone from Publish & share (both led nowhere in D2D Relay), and the
      API no longer returns the server's own project folder (`host_dir`).
    - Checked on an isolated test stack (port 8105, built from this code, its projects folder on this PC served by
      test copies of the DAX checker and the maker) with copies of the four live dashboards:
      - "D2D smoke test", 24 API checks: the old download refused until the file is made, "Make the Power BI file",
        the zip's contents, the .pbix's data and DataFolder, approving v1 again through the DAX check and the 13
        gates, and nothing the page gets says PBIP or Power BI project. 35 s for the file, 46 s for a full publish.
      - "Brand palette test" and "Retail Performance 360", 15 checks each (about 40 s); "Global Ports Enterprise
        (demo)", 15 checks in 196 s: a 170 MB .pbix with its 30 pages and both RLS roles, the 961 MB of CSVs left
        out of the zip.
      - Each .pbix opened in Power BI Desktop: every table has its rows and DataFolder is
        `C:\D2D Relay Data\<Report>\data\`.
      - The maker stopped: the run stops after two minutes with a plain message, PASDACS is notified, and Retry
        finishes it. A second maker for the same data folder refuses to start.
      - The screens in a browser: the banners while making and when ready, "not made yet", the download card, the
        Versions, Activity and Details tabs, the sign-in page.
    - **Deployed on 2026-11-11 at 10:55 IST** (image `d2d-relay:335c2b7`; `docker compose up -d --no-deps web admin`,
      the database container untouched; the user's go-ahead). The Power BI file maker was started on the D2D Relay
      PC first, from the deploy folder. Then the four dashboards published before got their .pbix through the `pbix`
      job, queued without signing in: `docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -c
      "from app import worker; worker.enqueue('<dashboard id>', 'pbix')"`. All four done by 11:01. Each live download holds
      only `<Report>/<Report>.pbix` and its CSVs (Global Ports: the .pbix only, 170.2 MB) and refreshes from
      `C:\D2D Relay Data\<Report>\data\`. The sign-in page says "Power BI file (.pbix)"; no errors in the logs.
    - **Production readiness** (the user's request, same day):
      - the app's watchdog warns PASDACS when the Power BI file maker has been offline for 10 minutes (critical when
        a file is waiting), with the maker's own reason when it stopped on an error, and says when it is back; the
        metrics have `d2d_pbix_up` and its queue (`monitor.py`, checked against a fake heartbeat in a throwaway
        container: online, 5 and 11 minutes offline, a waiting request, an error, back again);
      - the DAX checker refuses a second copy on the same queue, like the maker (checked);
      - backups in the split layout: a backup taken in `d2d-relay-web` at 11:03 IST holds the control plane, the
        database, the projects and the secrets (48 s, 13 MB; the demo's two big CSVs and its 170 MB download are
        left out, as designed); the nightly one runs at 02:30 IST;
      - the PC does not sleep (the user runs a keep-awake script). Adding the two helpers to the Startup folder was
        refused to Claude Code as persistence, so that one-time step is the user's (`docs/d2d-relay.md`, "After the
        PC restarts").
      - **Redeployed at 11:05 IST** (image `d2d-relay:ae18feb`, web and admin only): healthy, no errors, and the
        watchdog sees both helpers online. The D2D DAX checker was restarted on its guarded version from the deploy
        folder; RELAY's checker (`Gen BI`) was not touched. Running on the PC now: the D2D DAX checker and the Power
        BI file maker, both started from `Downloads\D2D Relay`.
17. **Full clean-up and review** (the user's request of 2026-11-11, after item 16).
    - **Security: what a report may do on the D2D Relay PC.** Since item 16 the file maker refreshes reports on the PC
      that holds D2D Relay's settings and data, and nothing stopped a definition from carrying its own Power Query
      (`m:`), a `csv:` name with folders, or a date-table event name with a quote (it went into the query unescaped),
      so a dashboard could have been made to read this PC's files (`.env`, other organisations' data) into its .pbix.
      Nobody did (only PASDACS has credits). Closed on both sides:
      - the maker (`pbix.ps1`, `Test-ReportQueries`) reads the report's Power Query before Power BI Desktop opens it
        and refuses anything but `File.Contents(DataFolder & "<a file of its data folder>")` and the functions the
        report builder writes (no other folder, web, database, ODBC, `#shared`, `Expression.Evaluate`, or a
        `DataFolder` of its own, however written: comments, quoted names, records, functions);
      - the app refuses such definitions (`validate.source_errors`) and escapes event names (`definition.py`);
      - a dashboard on a warehouse is saved without a refresh (`-NoRefresh`): nothing of it runs on the PC; its
        owner presses Refresh in Power BI Desktop and signs in to the warehouse (the page and the note say so).
    - **The file maker** stops at once when Power BI shows "Issues were found" while opening (it waited 5 minutes),
      refuses a report whose files would lie past Windows' 260 characters with that reason, and keeps only the log
      and the picture of a failed run (PowerShell 5.1 had ignored the filter and kept the whole report).
    - **Dead ends removed:** "Post to a channel" (it sent people to a Settings page D2D does not have; Slack/Teams
      and GitHub APIs now answer 404), the unreachable GitHub dialog, and library visuals linking to a library page
      (they open their preview now). The schedule APIs whose names start `/api/schedules-` were still reachable.
    - **Reviews work:** a reviewer's Approve / Request changes was blocked with the rest of `/api/reviews`; it is
      allowed now (the list of everyone's reviews stays off), the reviewer's notification opens the Overview where
      the buttons are, and the person who asked is told the answer. Unknown dashboards answer 404 instead of 500
      there and on PDF/PNG export.
    - **Words:** people are Owners and Members (not "Builder / Analyst", "BI Dev", "Viewer" or the "Default" team) in
      the header, profile, Share dialog, read-only note, Review card and messages.
    - **Checked** on fresh test stacks built from this code: the 118 API checks (organisations, admin portal,
      connectors, credits, people, production) twice, 13 checks of the fixes, 27 checks of the maker's guard (the four
      live reports pass in about 0.1 s each; every attack is refused), and through Power BI Desktop: a publish (23
      checks), a warehouse dashboard (made in 30 s without a refresh), a tampered report (refused in 10 s, no
      download), a too-deep report (refused in 10 s) and an ordinary file again (14 checks).
    - **Cleaned up:** the superseded image `d2d-relay:335c2b7`, the test stacks, images, volumes and copies of live
      dashboards (about 1.9 GB of scratch files), Python caches, and the merged `orgs-credits` branch (work is on
      `main`). No secrets in git or its history (scanned). Docker's build cache (about 10 GB) is kept: it makes a
      deploy build take minutes instead of much longer.
18. **Deployed, cleaned up and reset to a fresh application** (the user's request of 2026-11-11: "deploy and clean up
    and delete all organisations and making it fresh application").
    - Before: one organisation (PASDACS, the platform's own), one person (info@pasdacs.com), four dashboards (Global
      Ports Enterprise (demo), Retail Performance 360, Brand palette test, D2D smoke test), an uploaded logo. No
      client organisation had signed up.
    - Backed up first: the database (`data\backups\relay-db-20261111-064453.dump`), and the four dashboards and the
      Ask Relay folder moved, not deleted, to `data\backups\pre-fresh-20261111-121538\projects` (1.3 GB; delete it
      once nobody needs the old dashboards).
    - **Deployed at 12:16 IST**, image `d2d-relay:5f59c2e` (item 17), web and admin only. While they were stopped,
      the database `relay` was dropped and created again as a new install creates it (`CREATE DATABASE relay OWNER
      relay_app ENCODING 'UTF8' TEMPLATE template0`); the app then set it up itself. The old single container's
      database files (67 MB, `/data/postgres` in the volume `d2d-relay-data`) were deleted.
    - Kept, as the site needs them: `.env`, `tunnel.env`, the state volumes (the encryption key, the sign-in mailbox's
      token, the AI gateway's settings), the Claude sign-in, the visual library (the five visuals the image ships),
      the helpers' queue folders and every backup.
    - Checked afterwards: one organisation, PASDACS, made by the app (0 credits, all six connectors), one person,
      info@pasdacs.com (its owner), no dashboards, sessions, requests or notifications; both sites answer; Microsoft
      gives both sites a token for the sign-in mail (nothing sent); the Power BI file maker was restarted on its
      guarded version and the watchdog sees it and the DAX checker online; no errors in the logs. Everyone signs in
      again; PASDACS gives itself credits on the admin portal when it needs them.

19. **New prices** (the user's request of 2026-11-11: "by default grant 50 credits only and 25 for new dashboard and
    10 for changes or enhancements and 10 for Ask Relay upto 5 messages").
    - A new organisation starts with 50 credits (`RELAY_CREDITS_START`); more still only with PASDACS's approval. A new
      dashboard uses 25, a change 10.
    - Ask Relay was free; now 10 credits (`RELAY_CREDITS_ASK`) pay for up to 5 answered questions in one conversation
      (`RELAY_CREDITS_ASK_QUESTIONS`): its 1st, 6th, 11th ... question is charged (`askd_routes.ask`), and the credits
      come back when that question gets no answer. Without enough credits a new conversation is refused (402, with
      the reason); a conversation with questions left goes on. Its page shows the conversation's credits and the
      questions left in them instead of its AI cost; the Ask button shows " - 10 credits" when the next question is
      charged; the credits chip updates after every answer. The credit history says "Ask Relay questions".
    - Every screen that lists prices (Organisation, the chip's menu, Add credits, Organisations on the admin portal)
      and the docs list all four.
    - Checked on a fresh test stack: the 120 API checks (two new: the prices, and running out after PASDACS takes
      the 50 back) and 14 Ask Relay credit checks (charged and given back when unanswered; the 2nd question free,
      the 6th charged; credits used and questions left after 1, 5 and 6 answers; 402 with the reason; a
      conversation with questions left goes on with 5 credits). The screens: the chip, Ask Relay, Organisation.
    - **Deployed on 2026-11-11 at 13:20 IST** (image `d2d-relay:939b135`, web and admin; the user's go-ahead). PASDACS,
      made in the fresh start with 0, got the new default as a "Starting credits" entry of 50. Checked afterwards:
      the prices on the server (25, 10, 10 for 5 questions, 50 to start), both sites answer, the new screens are
      served, the watchdog sees both helpers online, the sign-in mail works, no errors in the logs.

20. **The name** (the user's words of 2026-11-11: "D2D is a sub product of Relay Platform", and D2D means "Data to
    Decision"; a first message said "Data to Dashboard" and was corrected before anything went live). D2D means Data
    to Decision, and D2D Relay is a product of the Relay Platform by PASDACS. Said under the RELAY logo ("D2D - Data to
    Decision" / "a Relay Platform product - PASDACS"), on the sign-in page, on the Dashboards page ("D2D - Data to
    Decision"; it said "BI & dashboards"), in the sign-in code email and the other emails' footer, the module's
    description (it said "Data to Decisions dashboards"), the brand's tagline (it said "Data to dashboards"), the Ask
    Relay export footer (it said "Ask D"), the agent's instructions and the docs. The screens checked on a test stack.
    Asked which was better, Claude Code recommended Data to Decision (what the product is for, the platform's own
    meaning, room to grow) and the user chose it as written, singular. **Deployed on 2026-11-11 at 13:47 IST** (image
    `d2d-relay:8689305`, web and admin); the live sign-in page and screens show it, no errors in the logs.

21. **Turnkey deployments, sign-in alerts, prompt injection** (the user's request of 2026-11-11: "drop rls and client
    own warehouse it will be handle as turnkey deployment after their contact me, abuse monitor send me alerts when
    ever a user logs in and ensure its safe from prompt injection in all places ... delete the old files, but keep the
    large dashboard as sample").
    - **Turnkey.** An organisation's own warehouse or database, and row-level security, are no longer backlog items
      for the shared product: PASDACS sets them up as a turnkey deployment after the organisation gets in touch. The
      Connections page, its request (email and notification) and the 403 for a switched-off connector say so;
      `docs/rls-backlog.md` is marked dropped.
    - **Sign-in alerts** (`app/signin_alerts.py`, called from `otp._signed_in` for every sign-in: public site, admin
      portal, a colleague joining, a new organisation). One email to info@pasdacs.com per sign-in, sent in the
      background, with who, organisation, site, time, network and country, browser, first sign-in or not, codes asked
      from that network in the last hour and credits; audit `signin.alert`. `RELAY_SIGNIN_ALERTS=0` turns them off,
      `RELAY_SIGNIN_ALERTS_TO` changes the address; without mail they go to the log (`docs/d2d-relay.md`).
    - **Prompt injection** (data files and attachments are untrusted; `docs/d2d-relay.md`, "What the AI can reach"):
      - Claude Code ran with Read/Glob/Grep allowed on every path, and Claude Code lets read-only shell commands
        (`cat`, `ls`, `grep` ...) run without asking: an injected instruction could read another organisation's
        dashboards (all project folders share one group) or the Claude sign-in. Runs also had Claude Code's
        scheduling, remote-trigger, messaging and workflow tools and about 17 skills. Now a managed policy
        (`agent/managed-settings.json` -> `/etc/claude-code/managed-settings.json`, above every other settings file):
        reads and writes outside the dashboard's folder refused, only its own hook runs, CLAUDE.md, project.json and
        `.claude/` not editable; and `--tools` gives a run Read, Write, Edit, Glob, Grep, the shell and its task list
        only, with `--strict-mcp-config` and `--disable-slash-commands` (no MCP servers, no skills). A managed hook
        (`agent/bash_guard.py`) lets the shell run `genbi` dashboard commands, on their own or chained with `&&`/`;`
        as the agent often does, and nothing else: no other program, pipe, redirection or substitution, no `repo`,
        `deck` or `doc`. Replayed on the 49 shell commands of the Global Ports build, it refuses none of them.
        (`--restricted` confines the same way but stops Claude Code loading the folder's CLAUDE.md, the agent's
        manual, so it is not used.)
      - The toolkit refused nothing: `genbi read /any/file`, `genbi visual source ../../..`, `--out` anywhere. Every
        path it is given must now be inside the folder (`cli._inside_project`), visual names must be names.
      - `genbi sql`, the prototype queries and Ask Relay ran DuckDB with full file and network access (any file,
        any URL). Each connection is now confined to its folders, without network, locked (`data.confine`;
        DuckDB 1.2.2, which has `allowed_directories`).
      - The prototype (HTML from the AI) was served on the app's own origin with no sandbox, so a script in it could
        have used the viewer's session. Now it is sandboxed (CSP `sandbox allow-scripts`, no network, framed by the
        app only, and `sandbox` on every frame); it reports its height by message. The dashboard name and theme
        values are written into it as text (a theme value that is not a colour gets the default), text boxes as text.
      - Headless Chromium in the container (display check, custom-visual test, renders) had network: now none (no
        name lookups, a dead proxy for everything including this container's services, WebSockets refused).
      - A home-page tooltip put labels in as HTML: escaped.
      - Checked and fine as they were: Ask Relay's AI has no tools and its SQL is checked read-only; the branding
        palettes are validated hex colours; the other screens build text with `textContent` or escape it; customers
        cannot pick the Codex, Gemini or Antigravity engines (the AI policy allows Claude-based providers only and
        `/api/admin` answers 404 on the public site); the DAX checker runs DAX over inline tables only.
    - **Database reconnect** (`db.py`): after the database container is recreated, the web app's connection is closed;
      it answered 500 until a restart. A query outside a transaction now reconnects and retries once.
    - **Housekeeping:** the old archive folders are deleted; the Global Ports enterprise dashboard is kept as a sample
      (`data\samples\global-ports-enterprise-demo-10c1`, with a README); old images removed, all containers on the
      current image.
    - **Checked** (a test image from this code; a fresh test stack, removed afterwards):
      - the 120 API checks and the 14 Ask Relay credit checks pass; 13 sign-ins gave 13 alerts (3 from the admin
        portal) and 13 audit entries;
      - real Claude Code through the agent service, with files planted outside the folder: all 14 ways out refused
        (Read, Glob and Grep outside, `cat`, `ls`, `curl`, `genbi profile; cat ...`, `genbi read` and `genbi sql`
        on another folder, writes to /tmp, `~/.claude`, `.claude/settings.json`, an edit of CLAUDE.md, `genbi repo`),
        the normal steps work, and CLAUDE.md is loaded; another session's transcript and saved output: 5 ways in,
        all refused (a run reads only its own saved output); Claude Code's start-up report: Read, Write, Edit, Glob,
        Grep, Bash and the task list, no MCP servers, no skills; Ask Relay's runs: no tools;
      - the shell guard: 64 cases, and the 49 shell commands of the Global Ports build: none refused;
      - a hostile prototype (23 checks): no cookie, no use of the app's API as the person (read or write), no
        internet, no storage, its height still reported, nobody added to the organisation;
      - one real dashboard build with Claude on the test stack: plan in 45 s, prototype in 6.5 min, 38 `genbi`
        commands, nothing refused; the gates pass, the display check included (3 pages, 25 visuals drawn, no
        network); the DAX check was skipped (the test stack cannot reach this PC's DAX checker);
      - the dashboard page shows that prototype sandboxed and sized from its height message (7 checks, Chromium).
        Claude's built-in browser pane refuses every frame with a `sandbox` attribute (ERR_BLOCKED_BY_CLIENT): a
        quirk of that pane, not of the site.

22. **Data governance** (the user's request of 2026-11-11: "Check all from data governance as well"). What was
    found, and what changed (`app/governance.py`; `docs/d2d-relay.md`, "Data governance"; `/privacy.html`):
    - **Nothing could be deleted.** No one could delete a dashboard (its uploads, extracts, versions, Power BI files
      and activity log stayed for ever), an Ask Relay conversation, or an organisation. Now: Delete on the dashboard
      page (its owner or an owner of the organisation; refused while a run is going) removes the folder, index rows,
      shares, queued jobs, the conversations about it, cached answers that used it, notifications pointing at it and
      the AI engine's transcripts of its runs, and is audited (`project.deleted`); the credit history stays. Delete
      conversation in Ask Relay (the person who asked). PASDACS erases a whole organisation on its owner's written
      request with `python -m app.governance erase-org <id> "<name>"`: schema, folders, secrets, visual library,
      transcripts, accounts; the credit history stays without names (`d2d.org_erased`). The admin portal's container
      holds neither the folders nor the AI engine, so this runs in the web container.
    - **The AI engine kept everything it read.** Claude Code saves every run's transcript, tool output included
      (samples and query results of customers' data), in the `claude-api-auth` volume: 30 folders and 65 MB on live,
      among them the transcripts of every dashboard deleted at the fresh start (item 18). Now: Ask Relay's are deleted
      as soon as the answer is given; a dashboard's with the dashboard; every night those of folders that no longer
      exist and any older than 7 days (the agent service's new `POST /forget`); and the managed settings set
      `cleanupPeriodDays` 7 and switch Claude Code's auto-memory off (no notes carried between runs).
    - **Nothing expired.** Sign-in codes (address and network) and the audit trail were kept for ever, Ask Relay's
      answer cache never expired, and database copies made by hand stayed in `data\backups` for good. Now a nightly
      sweep (after the backup): audit trail, sign-in records and codes after a year (India's DPDP Rules 2025, rule
      8(3): at least a year, then erase), the answer cache after 7 days, hand-made dumps and exports after 30 days.
    - **No notice, no way to see one's data.** Now: a privacy notice (`/privacy.html`: what is held, why, who else
      handles it (Anthropic in the USA, Microsoft 365, Cloudflare), how long, rights, grievances within 90 days, the
      Data Protection Board), linked from the sign-in page, the profile menu and Organisation > Your data; and
      Download my data (`GET /api/me/data`: profile, sign-ins, dashboards, conversations, credit requests, a year of
      activity, nobody else's), audited as `privacy.export`.
    - **Two routes left from RELAY could send data out:** pushing a dashboard to GitHub and writing back into a
      warehouse. Both answer 404 now (`edition.EGRESS`); D2D Relay only reads warehouses.
    - **A closed organisation's schema came back** (empty) the moment anything wrote to it, such as the audit row of
      its own erasure: `db._check_ready` set up any tenant it knew. It now refuses closed ones.
    - **Checked and fine:** organisations are kept apart (schemas, folders, secrets, the people directory and sharing
      are per organisation); the admin portal shows organisations, credits and requests, never anyone's dashboards;
      sign-in codes are salted hashes and sessions expire (12 h); the container logs carry user ids, never query
      strings, bodies or codes, and rotate (5 x 20 MB); warehouse secrets are encrypted and backups never hold the key;
      no tracking cookies.
    - **Checked** (a test image from this code; a fresh test stack, removed afterwards): 60 data-governance checks
      (deleting a dashboard as owner, editor and stranger, with what goes and what stays; deleting a conversation;
      Download my data; the egress routes; the sweep on old and new records, dumps and transcripts; erasing an
      organisation, a wrong name, the platform; the AI engine refusing paths outside its folder; the managed
      settings), 10 in Chromium (the Delete dialog, Delete conversation, Your data and its download, the notice from
      the sign-in page), and the earlier suites: 121 API checks (the 2 rehearsal checks need a copy of the live
      database), 14 Ask Relay credit checks, 13 review checks.
      The release image `d2d-relay:8f39265` passed the same checks again, and the real-Claude lockdown test of item 21
      with the new managed settings (Claude Code loads them and its CLAUDE.md; all 11 ways out refused; Ask Relay's
      runs have no tools; no auto-memory written).
    - **Deployed on 2026-11-11 at 17:11 IST together with item 21** (image `d2d-relay:8f39265`; `docker compose up -d
      --no-deps web admin`, the database container untouched; the user's go-ahead: "Yeah deploy all"). Nothing was
      running. Checked afterwards: web and admin healthy on 8f39265; the managed settings (transcripts 7 days, no
      auto-memory) and DuckDB 1.2.2 in place; `/privacy.html` opens through Cloudflare and the sign-in page links it;
      signed-out API calls get 401; no errors in the logs. The sweep, run once by hand, removed 83 of the AI engine's
      records: its transcript folders went from 30 (65 MB) to 7 (3.3 MB: set-up runs and model probes outside the
      projects folder, which Claude Code's own 7-day clean-up removes). Pushed to GitHub with the work log.

23. **Buying credits online with Razorpay** (the user's request of 2026-11-11: "online payments will add it today or
    tomorrow with razorpay and will provide test keys"; built while the keys are on their way: "Keys coming").
    `app/payments.py`, `js/37-payments.js`; `docs/d2d-relay.md`, "Payments (Razorpay)". Committed as c8e615f; not
    deployed.
    - **Buy credits** (Organisation, the menu under the organisation chip, Dashboards, and the message when credits run
      out): the packs with their price, GST and price per credit; Pay opens Razorpay's own checkout (card, UPI,
      netbanking, wallet: those details never reach D2D Relay). The amount is always the server's: one Razorpay order
      per checkout, reused when Pay is pressed again for the same pack. The credits are added once Razorpay has
      captured the payment, through whichever comes first, and only once (one transaction marks the checkout paid and
      writes the credit row): the checkout's answer (Razorpay's signature checked with the key secret, then the payment
      fetched from Razorpay: order, amount and currency must match; captured here when only authorised), the signed
      webhook (`POST /api/payments/webhook`, no sign-in: payment.captured, order.paid, payment.failed,
      refund.processed), or a look at Razorpay when the Organisation page opens (and Check on the admin portal) for
      checkouts of the last two days still waiting.
    - **Receipts:** by email to the buyer, and a printable page from Organisation -> Payments (a payment receipt, not a
      tax invoice). The owners are told in the app, PASDACS by email and notification. The credit history says "Bought
      online" with the amount and Razorpay's payment id. Owners see all of the organisation's payments, others their own.
    - **The admin portal's Payments page:** which keys are in use, the webhook URL and the events to give Razorpay; the
      packs (credits and a price in whole rupees, up to 6), GST added on top (0: none), a note under the prices, who
      may buy (owners, the default, or everyone) and Sell credits online (off until switched on); every payment, with
      Check for one still waiting; this month's and all-time takings, refunds taken off.
    - **Safety:** test keys (`rzp_test_`) move no money, so with them only PASDACS's own workspace can buy; with live
      keys every organisation can once selling is on. A payment that does not match its checkout, or a second one for
      an order already paid, adds nothing and alerts PASDACS. 10 checkouts an hour per person. The keys reach the web
      app only, not the AI engine's environment. Refunds are made on the Razorpay Dashboard: the webhook records them
      and tells PASDACS; the credits are taken back by hand when that is the rule.
    - **Data governance:** `relay.tn_payments`, amounts in paise, no card or bank details. Paid ones are kept
      (accounting: eight years), without names once an organisation is erased; checkouts never paid go after a year
      (the nightly sweep). Each person's payments are in Download my data. The privacy notice names Razorpay (India)
      and says how long payments are kept. `governance.py` and `privacy.html` were committed with CRLF line endings in
      item 22; they are LF again.
    - **Defaults until the user decides** (all on the admin portal, no code change): owners buy; the packs and prices
      are empty until set; GST as set there (0: the price is what people pay); a receipt, not a GST invoice (one needs
      PASDACS's GSTIN, an invoice series and the buyer's GSTIN: a follow-up if wanted); refunds by hand.
    - **Checked** on the release image `d2d-relay:c8e615f` (a fresh test stack with a stand-in Razorpay API,
      `fake_razorpay.py`, inside it, and a stand-in checkout window in Chromium): 70 payment checks (selling off, the
      settings and what they refuse, who may buy, orders for the server's price, wrong and unknown signatures, paid
      through the answer, the webhook and a later look, authorised then captured, failed then paid on a retry, a wrong
      amount, a second payment, refunds whole and in part, receipts, lists, news, the admin's Check, Razorpay down,
      the hourly limit, test keys, Download my data, erasing an organisation, the sweep), 29 in Chromium (Buy credits
      with GST, a blocked script, a closed window, a failed payment, paying, the receipt, a phone, a member, the admin
      portal's page and saving a price), and the earlier suites: 120 API checks, 60 data-governance checks and 10 in
      Chromium, 14 Ask Relay credit checks, 13 review checks.
    - **Against Razorpay's real test mode** (the user's test keys, given 2026-11-11 with Razorpay's own setup prompt; on
      the test stack, release image `d2d-relay:c8e615f`): Razorpay's "test transaction" made through Buy credits as
      PASDACS with Razorpay's test card, payment `pay_TytOtJWL3mSE5o`, ₹1,178.82, captured, 11 Nov 2026 19:27 IST;
      Razorpay's dashboard then said "Transaction successful". Also: orders read back from Razorpay with the right
      amount, receipt and notes; a made-up signature and a payment Razorpay does not know are refused; wrong keys get
      Razorpay's own "Authentication failed"; test keys let only PASDACS buy; a failed payment (Razorpay's demo bank,
      Failure) adds nothing and is recorded as failed (`pay_TytTPQeSXuHdRs`); a payment whose answer never reached the
      app (the request blocked, as with a closed tab) is found by the next look-up and its credits added
      (`pay_TytUHj3Zh277OD`). Seen there: Razorpay's checkout asks every buyer for a mobile number; this account
      offers cards, netbanking and wallets, not UPI (switched on in the Razorpay Dashboard if wanted). Not checked yet:
      the webhook, which Razorpay cannot reach on the test stack (after the deploy).
    - **Deployed on 2026-11-11 at about 19:45 IST with the test keys** (the user: "each credit is 1$ and INR 100, so
      plan accordingly and deploy"). The deploy folder fast-forwarded to 93de489; the keys and a new webhook secret
      added to the live `.env`; web and admin on the tested image `d2d-relay:c8e615f` (`docker compose up -d
      --no-deps web admin`; the database container untouched; nothing was running). The packs, at ₹100 a credit with
      no GST added (one setting if GST is to be added): 25 credits ₹2,500, 50 ₹5,000, 100 ₹10,000, 250 ₹25,000, 500
      ₹50,000; who may buy: owners; selling switched off (with test keys only PASDACS's own workspace can buy anyway).
      Checked afterwards: test mode, both secrets set, PASDACS offered the packs, no other organisation; signed-out
      payment calls get 401; through Cloudflare an unsigned webhook call is refused (400) and a signed one is accepted
      (200, an order it does not know ignored), so Razorpay's webhook reaches the app; the privacy notice names
      Razorpay; no errors in the logs. The $1 a credit the user also named needs a US-dollar checkout: Razorpay's
      international payments switched on for the account, then a USD price beside the rupee one (not built).

24. **Prices in US dollars outside India** (the user, 2026-11-11: "each credit is 1$ and INR 100", then "Yes, add USD",
    "cannot it be decided based on the user location for India show inr and for others show usd ?" and "usd as
    fallback and inr only for india"). `app/payments.py`, `js/37-payments.js`; `docs/d2d-relay.md`, "Currencies".
    Committed as 442a396; deployed on 2026-11-11 at about 20:13 IST (below).
    - Each pack can have a dollar price beside the rupee one (whole dollars; the admin portal's Payments page, one more
      box per pack). Where the buyer is decides, by Cloudflare's country header: rupees only in India, US dollars
      everywhere else, unknown included. The server offers and accepts only that currency (an order for the other
      currency's pack is refused), so the dollar price, which carries no GST, is not open to buyers in India. A pack
      without a dollar price is not sold outside India; with no dollar prices at all everyone pays in rupees.
    - Orders, the checkout, the credit history ("$100.00 paid online"), receipts and emails are in the pack's
      currency; GST and the admin's note under the prices are for India only; dollar buyers are told "by card". The
      admin portal shows the takings per currency. Download my data gives amounts with their currency.
    - Razorpay's test mode takes dollar orders as they are (an order for $25 and one for $0.50 were accepted). With live
      keys, dollars need Razorpay's international payments switched on for the account.
    - **Checked** on a test stack with the stand-in Razorpay: 84 payment checks (the earlier 70 plus where the buyer is:
      India, the United States, unknown, an address Cloudflare cannot place; a pack in the other currency refused
      both ways; a dollar order, its payment, history, receipt without GST; a payment in the wrong currency refused;
      the admin's totals per currency; a negative dollar price refused) and 32 in Chromium (a buyer in India sees
      rupees with GST, one in the United States sees dollars with no switch and no GST, pays and sees $100.00 listed;
      the admin page's dollar boxes).
      The release image `d2d-relay:442a396` on a fresh test stack passed those and the earlier suites: 120 API checks,
      60 data-governance checks and 10 in Chromium, 14 Ask Relay credit checks, 13 review checks (333 in all).
    - **Against Razorpay's test mode** (the same image, the user's test keys): orders in rupees and in dollars made and
      read back; a $100 payment by Razorpay's domestic test card captured (`pay_TytyfBY4iaybCO`), its 100 credits
      added ("$100.00 paid online"); Razorpay's international test card refused by Razorpay: "this business accepts
      domestic (Indian) card payments only" (`pay_TytxhcZVTiaARu`), which the app showed, adding nothing and
      recording the payment as failed. So buyers abroad, who pay with international cards, can pay only once
      international payments are switched on for the Razorpay account.
    - **Deployed on 2026-11-11 at about 20:13 IST** (the user: "Yes, deploy"). Nothing was running; no payment had been
      made on live yet and Razorpay had sent no webhook (it is not added in the Razorpay Dashboard yet). The deploy
      folder fast-forwarded to 475e4f7; web and admin on the tested image `d2d-relay:442a396` (`docker compose up -d
      --no-deps web admin`; the database container untouched). Each live pack got its dollar price, $1 a credit:
      25 credits ₹2,500 or $25, 50 ₹5,000 or $50, 100 ₹10,000 or $100, 250 ₹25,000 or $250, 500 ₹50,000 or $500.
      Checked afterwards: the rule on live (India rupees; the United States, the United Kingdom, the UAE, an unknown
      country and no country, dollars); still test keys, so only PASDACS can buy; through Cloudflare signed-out payment
      calls get 401, an unsigned webhook call 400 and a signed one 200; no errors in the logs.

25. **GST invoices, no refunds, exports as the law says** (the user, 2026-11-11: "GST invoice is required, no refunds,
    dollar sales as per govt"). `app/invoices.py` (new), `app/payments.py`, `js/37-payments.js`; `docs/d2d-relay.md`,
    "GST invoices"; `/privacy.html`.
    - **Invoices:** every payment that adds credits gets a tax invoice with the fields of the CGST Rules' rule 46:
      PASDACS's name, address, state and GSTIN, a consecutive number (`PREFIX/YY-YY/00001`, one series per financial
      year, at most 16 characters, taken in the transaction that marks the payment paid, so never lost or repeated;
      test-key payments get `TEST/...`), the date, the buyer's name, address, state or country and GSTIN, the place of
      supply, the SAC code, quantity, taxable value, CGST and SGST (UTGST in a union territory without a legislature)
      or IGST, the total, reverse charge "No", and a signature line. Kept as a snapshot on the payment; emailed to the
      buyer (and PASDACS); printable from Organisation -> Payments; a year's invoices as CSV for GSTR-1 on the admin
      portal.
    - **Tax:** the buyer's state decides CGST and SGST (PASDACS's own state) or IGST (another state, or a buyer abroad
      paying rupees). Dollar sales to buyers abroad are exports of services: zero-rated with the LUT's ARN on the
      admin portal ("SUPPLY MEANT FOR EXPORT UNDER LETTER OF UNDERTAKING WITHOUT PAYMENT OF INTEGRATED TAX"), else on
      payment of IGST, included in the dollar price; the rupee value is Razorpay's conversion (the payment's
      `base_amount`: $100 was ₹9,367.41 in test mode). Rupee prices include GST or have it added (a setting).
    - **Billing details** are asked for once, before the first purchase (owners change them on the Organisation page):
      legal name and address; in India the state and PIN, or a GSTIN (checked: format, state and its check
      character); abroad the country. A billing address in India means rupees wherever the buyer is.
    - **No refunds:** Buy credits, the invoice and the Payments card say credits are not refundable.
    - **Live selling** (live keys) stays shut until PASDACS's invoice details are complete and a GST rate is set.
    - **Checked** on a test stack with the stand-in Razorpay: 113 payment checks (the earlier ones, plus billing details
      asked first and what they refuse, invoices numbered one after another, CGST and SGST in PASDACS's state, IGST
      in another state with the buyer's GSTIN, an export under the LUT and one without it, GST included in the
      price, the invoice page and email, the CSV, test payments in their own series, invoices kept when an
      organisation is erased) and 37 in Chromium (the billing form in Buy credits, who the invoices go to, no
      refunds, the GST invoice page, a foreign organisation paying dollars, the admin's Tax invoices card).
      The release image `d2d-relay:7d28ea7` (commit 7d28ea7) passed those and the earlier suites on a fresh test
      stack: 120 API checks, 60 data-governance checks and 10 in Chromium, 14 Ask Relay credit checks, 13 review
      checks (367 in all).
    - **Against Razorpay's test mode** (the same image, the user's test keys): 18 order checks (rupees and dollars), then
      two real payments in Razorpay's checkout, each with its invoice in the TEST series: `TEST/26-27/00001`, $100
      (`pay_TyvKUxl6GOexvU`), an export under the LUT without IGST, ₹9,373.07 at Razorpay's 93.7307; and
      `TEST/26-27/00002`, ₹1,178.82 (`pay_TyvLLaIUUclUBj`), ₹999 + CGST ₹89.91 + SGST ₹89.91, place of supply
      Karnataka (29). Not deployed: committed as 7d28ea7.

26. **Security, data governance and privacy audit** (the user's request of 2026-11-11: "do a full sweep audit and data
    goverance and privacy as i will be launching this in the public domain", "security check as well"). The findings,
    what was fixed, the tests and what is open: `docs/security-privacy-audit-2026-11-11.md`. Fixed in the work folder:
    three ways for the AI to run code of its own outside its confinement (a custom visual's `caps.js` run by Node, a
    Python module in the project folder run as the toolkit, a visual's Less `@plugin` and webpack loader imports), each
    proven on a throwaway copy of the live image to reach another organisation's data and the Claude sign-in; the DAX
    checker on the PC now refuses models with data sources or Power Query; security headers; a guard for Starlette's
    Range bug; the privacy notice says who in an organisation sees what. `genbi_kit/caps.py` (new), `vfactory.py`,
    `GENBI.md`, `Dockerfile`, `agent/Dockerfile`, `docker/relay_init.py`, `daxcheck/daxcheck.ps1`,
    `webapp/app/headers.py` (new), `main.py`, `/privacy.html`. Then (the user: "Full audit and testing as well all
    combinations to be secure and confident for launch"): the console's cross-organisation views off the public site
    (`edition.py`), 20 sign-in codes a day per address (`otp.py`), `/api/health` without the AI engine's details. On a
    release candidate built from the work folder, on fresh test stacks: every end-to-end suite (rebuilt from the
    session that wrote them) with the starting-credit review off and on, 367 of 367 each; a new security suite
    (`sec_check.py`: anonymous access to every route, sign-in, CSRF, tampered cookies, owner/member/removed, one
    organisation against another, platform powers, uploads and paths, payments, the review) 115 and 132 of 132; the
    sandbox escapes refused and real visual builds; the shell guard's 64 cases; Cloudflare Access 10 of 10; a hostile
    prototype 23 of 23; an upgrade from the live image on the same database 21 of 21. The results table is in the
    audit's "Tests". Not committed, not deployed.
27. **Starting credits reviewed by PASDACS** (the user, 2026-11-11: "Instead of free credits on the go, when user sign
    ups send me a email and i will review and confirm you whether to add credits or no"). A new organisation starts
    with no credits; its "starting credits" request (50) waits on the admin portal's Requests, and info@pasdacs.com
    gets one email per new organisation with what helps to judge it (owner, network, country, organisations from the
    same network or on the same parent domain), instead of the sign-in alert. Approve adds the credits as starting
    credits and emails the owner; Decline tells the owner why. Also from the command line (`python -m app.orgs
    requests | approve | decline`, `docs/d2d-relay.md`, "Starting credits are reviewed"), so PASDACS can answer by
    telling Claude. `RELAY_CREDITS_START_REVIEW=0` brings back the credits at sign-up. `app/orgs.py`, `otp.py`,
    `signin_alerts.py`, `login.html`, `js/36-org.js`, `.env.example`, `README.md`. Live since 2026-11-12 (09:21 IST).
28. **The public site moves to d2d.pasdacs.com** (the user, 2026-11-12: "can we host this in app.d2d.pasdacs.com ?",
    then "d2d.pasdacs.com": a name two levels under pasdacs.com needs Cloudflare's paid Advanced Certificate Manager,
    one level is covered by the free certificate). The old address d2d-relay.pasdacs.com keeps answering through the
    same tunnel. The guide (`docs/d2d-relay.md`, "Public address", with "Changing the address"), `README.md`,
    `.env.example`, `docker-compose.yml`'s notes and the public site's address the admin portal uses in emails and for
    the webhook (`payments._site`) name the new address. The switch: (1) the user adds the public hostname `d2d` on the
    D2D tunnel in Cloudflare (Zero Trust -> Networks -> Tunnels -> the tunnel -> Public hostname -> Add: subdomain `d2d`,
    domain `pasdacs.com`, HTTP, `d2d-relay:8000`); (2) Claude checks https://d2d.pasdacs.com answers, sets
    `RELAY_PUBLIC_URL=https://d2d.pasdacs.com` in the live `.env` and restarts web and admin on this item's image;
    (3) the user changes Razorpay's webhook to https://d2d.pasdacs.com/api/payments/webhook.
    **Live since 2026-11-12, ~09:58 IST:** the user added the hostname in Cloudflare; `RELAY_PUBLIC_URL` is
    https://d2d.pasdacs.com in the live `.env`; web and admin run `d2d-relay:72b71a1` (= latest; `e2be1d2` kept for
    going back). Checked through Cloudflare on both addresses: the site, the sign-in API (same-site requests pass,
    cross-site ones are refused), the security headers; the admin portal names the new address. Left for the user:
    Razorpay's webhook; later, if wanted, a Cloudflare redirect from d2d-relay.pasdacs.com to d2d.pasdacs.com.
29. **Plain characters, a first-time tour, Migration D2D** (the user, 2026-11-12: "humanize it, eg "—" replace these
    with small or remove it and ensure all characters look human"; then "a small tutorial for first time login where
    they can setup branding all and basic things if required or skip it as well. and theme and dark/light mode, also
    add a static option as Migration D2D, which mean Migrate any Dashboard to Dashboard ... add a button to conect me
    and explain via email so we can enable it"). The rules are in `docs/d2d-relay.md` ("First-time tour", "Migration
    D2D", "Text people read").
    - **Plain characters.** Every text people read in the app, its emails and pages is in keyboard characters: a hyphen
      for a long dash, straight quotes, three dots, "->" for an arrow, "-" for a bullet or a middle dot, ">" in paths.
      Converted by a script over the string literals and comments of every tracked Python and JavaScript file (never
      regular expressions or code), the pages and guides by hand. Kept: check marks, crosses, up and down arrows, ×,
      ≈, ± and currency signs. What the AI writes is shown the same way: the agent's notes, summaries and review notes
      (`store.plain`), Ask Relay's headline, summary, suggestions and follow-up questions (`askd._finish`), brand
      palette names; what people typed is shown as typed. The Power BI file gets page names, titles, subtitles,
      labels, text boxes, alt text, descriptions and display folders in plain characters (`report_builder`); measure,
      column and table names stay (the report refers to them) and the Report & accessibility gate warns about them.
      The AI is told (`GENBI.md`, Ask Relay's instructions). The map: `genbi_kit/plaintext.py` (new).
    - **First-time tour** (`#/welcome`, `js/38-tour.js`, new): Welcome; Your brand (owners, Branding inside it);
      Light or dark (Light, Dark, or Match my device, which follows the device as it changes); The basics (how a
      dashboard is made, credits, Migration D2D, help). Skip the tour at any step. Shown once per person
      (`POST /api/me/tour`), to people who start on or after 2026-11-12; Take the tour in the organisation menu opens
      it again; a link to anything else opens as asked. It replaces the owner's one-page setup (`#/setup` opens its
      brand step).
    - **Migration D2D** (`#/migration`, `js/39-migration.js`, new; in the sidebar and the organisation menu): migrate
      any dashboard to any dashboard (Cognos, Qlik, Looker, Tableau, Power BI, MicroStrategy, SAP BusinessObjects,
      SSRS and more, any direction), how it works, what moves. **Contact PASDACS** sends the tools from and to,
      roughly how many dashboards and a message to info@pasdacs.com (Reply-To the person), to the platform admins'
      notifications and to a new **Migration D2D requests** card on the admin portal's Requests
      (`POST /api/org/migration-request`, 5 an hour per person). Not self-service: PASDACS replies and switches it on.
    - The privacy notice names requests sent to PASDACS in the app under Usage.
    - Tests (`docs/security-privacy-audit-2026-11-11.md`, "Item 29 tests"): every suite on fresh test stacks from the
      release candidate, with the starting-credit review off and on, all passing (544 and 561 checks), two new suites
      for the tour and Migration D2D (34 and 28, one of them in Chromium), the report builder 11 of 11, and an upgrade
      from today's live image on the same database, 23 of 23. Committed as a84d7c9.
    **Live since 2026-11-12, ~10:46 IST** (the user's "Yes, deploy"): web and admin run `d2d-relay:a84d7c9` (= latest;
    `72b71a1` kept for going back). Checked on live: both addresses answer through Cloudflare (not cached there), the
    container's 43 pages and scripts have no long dashes, curly quotes or arrows, the tour and Migration D2D scripts
    are loaded, the new routes refuse anonymous requests and the admin portal does not answer them, no errors in either
    log, both PC helpers alive.
30. **Legal pages, the user's answers on the open list, and the engineering items** (the user, 2026-11-12: "claude
    plan is turned off for trainng, legal pages, confirmed nad no refund or cancellation, skip bitlocker for now, skip
    overnigh restrat as well i will handle it, how to do admin portal and mailbox restru=iction, delete all the backups,
    i shall remove this "d2d-relay.pasdacs.com"", then "and complete all the engineering which you can do"; asked:
    delete all 9 backups including last night's, deploy when every test passes, courts at Bengaluru, no bot check for
    now).
    - **Legal pages** (`webapp/static/terms.html`, `refunds.html`, `contact.html`, new; open without signing in,
      `auth.OPEN_PATHS`): Terms of service (Indian law, courts at Bengaluru, Karnataka; data processing terms; liability
      at most what was paid in the last 12 months), Refund and cancellation policy (no refunds, no cancellations;
      delivery; credits back when a run does not finish; payment errors put right), Contact. Linked from the sign-in
      page ("By signing in you accept the terms of service"), the privacy notice, the organisation menu and Buy
      credits; invoices and receipts say "Credits are not refundable, and a purchase cannot be cancelled once paid."
      (`docs/d2d-relay.md`, "Legal pages").
    - **Backups:** all 9 in `data\backups` were deleted on the user's word (the dumps and backups of 10-11 November and
      the nightly backup of 12 November 02:30 IST); the nightly job makes a new one at 02:30.
    - **The old address** d2d-relay.pasdacs.com is removed by the user in Cloudflare; nothing in the code or `.env`
      used it (`docs/d2d-relay.md`, "Changing the address").
    - **Engineering (security audit):** S4, the AI engine's API answers only the web app's user and root (the kernel's
      socket table names the caller; `agent/server.py`); S6, the AI engine reaches only Anthropic: a proxy in the web
      container (`docker/egress_proxy.py`) and iptables rules for its user set by relay-init (the web container gets
      `NET_ADMIN`; `RELAY_AGENT_EGRESS=off` lifts it; tested with real Claude through it); S10, the admin portal takes a
      request without Cloudflare's header only from this PC, and `RELAY_ADMIN_EMAILS` can narrow the admins to named
      addresses; S11, FastAPI 0.120.4 on Starlette 0.49.3; S15, RELAY's leftover routes and pages are off (111 API
      routes reachable, 124 before); S16, the visual kit is installed from a committed lockfile with `npm ci` (the
      exact packages of the image live on 2026-11-12); S17, a warehouse sign-in is finished only in the browser
      session and by the person that started it, checked before the code is used; P6, no email address in Razorpay's
      order notes.
    - **Tests**, on fresh test stacks from the release candidate: every suite with the starting-credit review off and
      on, 599 and 616 checks, all passing (three expectations changed for the new refund wording and the sign-in
      page's second link); the new `item30_check.py`, 54 of 54 (the legal pages, and S4, S6, S10, S11, S15, S16, S17
      checked inside the containers: another container refused by the admin portal, the AI engine's user refused by
      its API and stopped from connecting out or looking names up, Anthropic reached through the proxy); real Claude
      answering through the new network limits in a throwaway container with the live sign-in volume (its test
      transcript removed).
    - **Shipped with the Ask Relay rename** (`4c595c9`, from another Claude session, which asked the next deploying agent
      to review, merge and deploy it): reviewed (39 files, text only, no identifiers changed), item 30 rebased onto it,
      and the merged code tested again: every suite with the review on and off, and `rename_check.py` (the Ask Relay
      page in Chromium; an answer sent to a dashboard gives "Change request (from Ask Relay)" and "From Ask Relay: ...").
    - **Live since 2026-11-12, ~11:31 IST** (the user's "Yes, when all tests pass"): web and admin run
      `d2d-relay:d6be664` (= latest; `a84d7c9` kept for going back). The web container was recreated with `NET_ADMIN`
      (`docker-compose.yml`). Checked on live: the legal pages public through Cloudflare (Cloudflare's email obfuscation rewrites the address on them, as on every page), RELAY's leftover pages off, the admin portal answering this PC and refusing another container, both containers on d6be664, the AI engine's network limited (no direct connection, Anthropic through the proxy, one real Claude prompt answered through it, its transcript removed), its API refusing its own user, FastAPI 0.120.4 on Starlette 0.49.3, no errors in either log.

31. **Each AI build in its own container; accounts deleted at once; who made each dashboard; the D2D logo** (the user,
    2026-11-12: "AI run in ite own container, for now do not limit outbound traffic will review later, owner can see all
    dashboard in the organization with user created it, delete immeidately with a warning/confirmation"; asked: a
    deleted person's dashboards stay with the organisation; removing someone deletes them at once; the main owner can
    delete the organisation after typing its name).
    - **Job containers** (security audit S4): every run with tools (plan, build, change) runs in a short-lived container
      `d2d-relay-job-...` from the web container's image, holding only that dashboard's folder (plus the organisation's
      visual library and `config` read-only, and the Claude sign-in volume), as the AI engine's user with every
      capability dropped, on the web container's network (so the Anthropic-only limits and the API guard apply). The
      job runner (`d2d-relay-runner`, `docker/job_runner.py`, new) is the only part with Docker's socket: no network, a
      Unix socket only the AI engine can open, `claude` commands in a dashboard folder only; it streams the run back
      and removes the container when the run ends or is stopped. `agent/server.py` (JobProc), `docker/job_run.py` (new),
      `docker-compose.yml` (service `runner`, volume `runner-sock`), `RELAY_JOB_CONTAINERS` (auto, on, off). Ask Relay's
      runs (no tools) stay in the AI engine. Still shared: the Claude sign-in volume (and its run transcripts).
    - **Accounts** (`governance.delete_person`, `orgs.py`): Remove deletes the person at once after a warning; Delete my
      account (Organisation > Your data, type DELETE); the main owner deletes the organisation (type its name;
      `governance.erase_org`). A deleted person's name, address, sign-ins (codes, account mapping), sessions, Ask Relay
      conversations, notifications, connections, schedules and tokens go; their dashboards, saved visuals and pages
      pass to the main owner, marked as made by a former member; logs and accounting records keep no name or address.
      The address is free again: it can sign up again or be added back as a new person. The privacy notice says so.
    - **Who made each dashboard**: on Dashboards (every card) and on each dashboard's page ("Created ... by ...").
    - **Not limited, for now:** the web app's own outbound traffic (the user: "will review later").
    - **Reviewed before commit** by the "Final review and deployment" session, which found and had fixed: the job
      containers' umask (the web app could not rewrite what the AI wrote: KPI confirm failed), the account mapping and
      sign-in codes on deletion (in the platform's tables), a deleted person's connections; and deleting the
      organisation from the owner's own request (its last log line ran in the dropped workspace).
    - **The D2D logo** (`e07a6c1`, from the "D2D logo" session): the Striped D in the brand pack and the app (favicon,
      app icons, sign-in page, rail); reviewed (static files and one public path, `/d2d-mark.svg`) and shipped with this
      item.
    - **Tests:** every suite on fresh test stacks from the release candidate, with the starting-credit review on and off, 673 and 656 checks, all passing, among them the new jobs_check.py (17: a run goes through a job container holding only its dashboard's folder, is removed after, the runner refuses anything else and has no network) and accounts_check.py (33: makers, Remove, Delete my account, Delete the organisation, the address free again); and real Claude, with the live sign-in volume mounted as external on the test stack: a plan (1.2 min) and a build (2.4 min) in job containers, every review gate that runs there passing, each job container inspected from outside while running (only its own dashboard's folder, no /data/state, no Docker or runner socket, agent, all capabilities dropped), its transcripts removed after. Older expectations changed for the user's decision: a removed person is deleted, not switched off (d2d_checks.py people, sec_check.py).
    - **Live since 2026-11-12, ~12:46 IST** (the user's "ok, deploy once tests pass"), deployed by the "Final review and
      deployment" session: web, admin and the new job runner run `d2d-relay:8b18e3f` (= latest; `d6be664` kept for
      going back), built from the clean commit; `docker compose up -d --no-deps web admin runner` (the web container was
      recreated for the runner's socket). Checked on live: all three healthy; the runner serving for d2d-relay-web, its
      socket `agent 600` (the web app's user cannot open it) and the runner reaching Docker; one job (`claude --version`,
      no AI call) in a throwaway dashboard folder ran in a job container holding only that folder, the Claude sign-in
      and `config` (read-only), with the space in the live folder's path, and was removed (the folder too); the AI
      engine's API still refusing its own user and its network still limited; the D2D icons, manifest and privacy
      notice served through Cloudflare; Delete my account and Delete the organisation asking for sign-in; no errors in
      any log. Live had no dashboards and no queued jobs at the restart. Way back without going back a version:
      `RELAY_JOB_CONTAINERS=off` in `.env`, then `docker compose up -d --no-deps web`.

32. **A blocked list, so people an owner removes cannot rejoin** (the user, 2026-11-12: "Yes, add it", to the question
    after item 31: everyone at an organisation's domain joins it, so someone removed could sign in again as a new member).
    Removing someone (item 31) now also puts their address on the organisation's blocked list (its own `meta` table,
    `blocked:<address>`): both ways of joining refuse it ("An owner of ... removed this address. Ask one of its owners
    to add you back.", 403) until an owner unblocks it (Organisation > People > Blocked, `POST /api/org/unblock`) or adds
    the person back (which lifts the block; they come back as a new person). Leaving, or Delete my account, blocks
    nothing. Owners see the list in `/api/org` (`blocked`). `orgs.py` (is_blocked, block, unblock, blocked_list),
    `otp.py`, `js/36-org.js`, the privacy notice (the address is kept on the list until unblocked), the guide.
    - **Tests:** every suite on fresh test stacks from the release candidate, with the starting-credit review on and off, 680 and 663 checks, all passing; accounts_check.py now 40 (a removed address refused with the reason, listed under Blocked for owners, nobody else at the domain affected, unblocking needs an owner and works once, an unblocked or added-back address joins as a new person, Delete my account blocks nothing); sec_check.py expects 403 again for a removed person.
    - **Live since 2026-11-12, ~12:59 IST** (the user's "Deploy bdf370e now"), deployed by the "Final review and
      deployment" session: web, admin and the job runner run `d2d-relay:bdf370e` (= latest; `8b18e3f` kept for going
      back), built from the clean commit; no compose change. Checked on live: all three healthy on bdf370e; the privacy
      notice with the blocked list served through Cloudflare; Unblock asking for sign-in; the runner answering, its
      socket `agent 600`, one `claude --version` job in a throwaway folder run in a job container and removed (the folder
      too); the AI engine's API still refusing its own user and its network still limited; no errors in any log.
    - **The follow-up** for three small gaps the "Final review and deployment" session found (item 32 went live before
      it): the admin portal's sign-in now refuses a blocked PASDACS address instead of joining it to PASDACS
      (`otp._admin_signed_in`); an address added through `platform.py` comes off the Blocked list; single sign-on's
      auto-provision refuses a blocked address (`identity.py`; live signs in with codes only). Tests: every suite on fresh test stacks, with the starting-credit review on and off, 685 and 668 checks, all passing; accounts_check.py 45 (a PASDACS address its main owner removed is refused on the admin portal too).
    - **The follow-up is live since 2026-11-12, ~13:11 IST** (the user's "Yes, deploy"), deployed by the "Deployment
      and publishing verification" session: web, admin and the job runner run `d2d-relay:54f6ed7` (= latest; `bdf370e`
      kept for going back), built from the clean commit; the image differs from bdf370e only in identity.py, otp.py and
      platform.py; no compose change. Live had no dashboards, no queued jobs and an idle AI engine at the restart.
      Checked on live: all three healthy on 54f6ed7 with the three fixes in place; one `claude --version` job in a
      throwaway folder run in a job container and removed (the folder too); the AI engine's API still refusing its own
      user (403) and its direct connections out refused; https://d2d.pasdacs.com/healthz 200; no errors in any log.

33. **Cleaned up for the public launch** (the user, 2026-11-12: "Clean and delete all as well and fresh as I will be
    planning to go live to all public"; asked what that covers, all three: the test leftovers, the old images and
    live's data).
    - **Test leftovers:** the release suite's backup folder `Downloads\d2d-relay-test-suite` (the suite is in `tests/`
      since `dbe57e5`) and the test runs' logs, screenshots, projects folder and settings under `tests/` (git-ignored)
      went to the Recycle Bin.
    - **Images:** the five release candidates (`rc-*`) and the eleven older releases kept for going back (`bdf370e`,
      `8b18e3f`, `d6be664`, `15d894e`, `a84d7c9`, `72b71a1`, `e2be1d2`, `7d28ea7`, `442a396`, `c8e615f`, `8f39265`)
      were removed: 20 images (12 GB) down to 4 (8.9 GB). Kept: `d2d-relay:54f6ed7` (= latest, live), `8689305` (the
      database container runs it) and `d2d-relay-agy:pinned` (a build input).
    - **Live's data:** live had no client organisation and no dashboard, only PASDACS's own test traces from that
      morning. Backed up first (`data\backups\relay-db-20261112-091920.dump`, made with `relay-ctl db-dump`), then
      removed in one transaction after the user's "Yes, and sign me out": the declined request for 100 credits, the
      unpaid ₹5,000 test checkout (no money moved), 56 audit entries, 3 notifications, 2 sign-in codes and both
      sessions (info@pasdacs.com signs in again). Kept: PASDACS with its billing details and its 50 starting credits
      (and their one history line), info@pasdacs.com, the prices, packs and settings, the five library visuals and
      the enterprise sample in `data\samples`. Nothing was restarted. The Claude sign-in volume `claude-api-auth` was
      left alone: its seven transcript folders date from 2 to 10 November and none is a D2D Relay dashboard's (none
      under `/data/projects`).
    - **Checked afterwards:** one organisation and one person; no requests, payments, notifications, audit entries
      or sessions; every container healthy; https://d2d.pasdacs.com/healthz 200; no errors in the logs.

34. **Built-in visuals first; the AI model named Relay Model powered by Claude; each job runner sweeps only its own
    stack** (the user, 2026-11-12: "What all you can close do it and do a full end to end testing and default power bi
    built in visual first and the built in plus custom id needed and last full custom, and name the AI model as Relay
    Model powered by Claude"). Code `aa4531e`; release image `d2d-relay:aa4531e`, built from the clean commit and
    tested; **live since 2026-11-12, 17:05 IST** (the user's "Yes, deploy").
    - **Visuals:** a new dashboard uses Power BI's built-in visuals unless its owner picks another. The New dashboard
      form offers Power BI's built-in visuals (chosen), then Built-in first, custom where needed, then Relay custom
      visuals; Custom visuals is off with built-in and back to its own choice with the others; the dashboard page's
      switch is in the same order; a dashboard made through the API without a choice is builtin; the agent's manual
      lists builtin first. Dashboards from before the choice existed stay relay (`main.py`, `04-new.js`, `07-tabs.js`,
      `genbi_kit/GENBI.md`).
    - **The AI model's name:** "Relay Model powered by Claude" in the model list (`config/house-models.json`, which
      live reads from the deploy folder), on a dashboard's header and Details tab, and on Branding.
    - **The job runner** labels each job container with its web container (`d2d-relay.web`) and, when it starts,
      removes only its own stack's jobs (from runners before the label: those in its web container's network, or whose
      network container is gone). Before, a test stack starting during a live build would have stopped the build.
    - **Pushed first** (the same request): `dbe57e5` and `2cd493e` went to GitHub and the deploy folder (nothing in the
      image changed; both were scanned for the live `.env` and `tunnel.env` values and key patterns before committing).
    - **Tests**, on fresh test stacks from `d2d-relay:aa4531e`: every suite, 718 checks with the starting-credit review
      on and 701 with it off, all passing, among them the new `item34_check.py` (32: the defaults and order through the
      API and in Chromium, the model's name, the sweep with five stand-in jobs: this stack's and older ones removed,
      another stack's left alone) and `jobs_check.py`, now 18 (a job carries the label). In the review-off run
      `pay_ui_check.py` timed out once waiting for the Buy dialog and passed 37 of 37 when run again on the same stack.
      Upgrade from live's `54f6ed7` on the same data: 23 of 23.
    - **End to end with real Claude** (`visuals_e2e_check.py`, new, with the test stack's own DAX checker and Power BI
      file maker from this repository, `tests/stack/helpers.ps1`, never live's): one dashboard per Visuals mode from the
      same made-up sales data, each planned and built by real Claude in job containers, every review gate passing,
      approved, its DAX checked by Power BI's engine and made into a .pbix: 29 of 29 checks. Built-in: 18 visuals, all
      Power BI's own, no custom visual in the .pbix. Mixed: 27 visuals, 25 built-in plus a comparison and a narrative
      custom visual (both embedded). Relay: 27 visuals, 26 custom of 13 kinds (all embedded). Plans took about a
      minute, builds about 8 minutes each, publishing with the .pbix under a minute. `real_build_check.py`: 20 of 20
      (every job container saw only its own dashboard's folder; the check now compares each job with its own folder,
      as the other organisation's plan runs in one too). Seen in the prototypes, not caught by any gate: in the Relay
      report the dumbbell chart's end labels (-131% to -141%) match neither its axis nor its title, and the waterfall
      labels most steps "$0M"; in the mixed report the longest bar's label is cut at the edge. The built-in report
      showed none of this.
    - **Afterwards:** the test stack, its helpers and their data folder removed; the test runs' transcripts deleted from
      `claude-api-auth`. Claude Code's own 7-day clean-up (`cleanupPeriodDays`) also removed six transcript folders from
      2 November there when the test jobs started (none a D2D Relay dashboard's); live's next AI run would have done the
      same. Live was not touched: healthy throughout, its helpers idle.
    - **Deployed at 17:05 IST** after the user's "Yes, deploy": live was idle (no job container, the AI engine not busy,
      no queued job, no dashboard); the deploy folder fast-forwarded to `eb78e91` (no compose, `pbix\` or `daxcheck\`
      change; it brings `config/house-models.json`), `d2d-relay:aa4531e` tagged latest, `docker compose up -d
      --no-deps web admin runner`; the database container still runs `d2d-relay:8689305`'s image. Checked on live: web,
      admin and the job runner healthy on `aa4531e` within seconds; https://d2d.pasdacs.com/healthz and the sign-in page
      200, the admin portal 200 on this PC; the model list says "Relay Model powered by Claude", the New dashboard form
      offers built-in visuals first, the API's default is builtin; the runner started for `d2d-relay-web` with nothing
      to sweep; one `claude --version` job in a throwaway folder ran in a job container labelled
      `d2d-relay.web=d2d-relay-web` and was removed, the folder too; no errors in any log. `d2d-relay:54f6ed7` is kept
      for going back.

35. **Labels that mean what they say** (the user, 2026-11-12: "can you fix and deploy and publish all you can", after
    item 34's end-to-end run showed three label faults). Code `e05f035`, **live since 18:24 IST** the same day.
    - **Relay Compare's dumbbell** labelled the relative change b/a - 1 between its two dots, so two growth rates of
      opposite sign read "-140%" against a -15% to +30% axis. Now the % change only between two positive values, the
      difference in points between percentages ("-35 pts"), otherwise the difference itself ("-$150K").
    - **Every Relay visual** (Visual Atlas `common/util.ts`): a label never shows a value that is not zero as zero. With
      labels fixed to millions, a waterfall's +$33K step read "$0M" (the old build even printed "$M"); such a label is
      now shown in its own unit. All 13 visuals rebuilt offline with the toolchain pinned in the image (pbiviz 7.2.1),
      versions bumped, GUIDs unchanged (`custom_visuals/atlas/`, `visual-atlas/release/`); every mock-host check
      passing, new cases for both faults (`visual-atlas/docs/HISTORY.md` section 18).
    - **The prototype's Power BI built-in visuals** (`stock_visuals.js`): a bar's label goes inside the bar's end when
      the plot has no room after it, a column's inside its top (Power BI's Auto position); a scatter's point name
      flips to the point's left near the right edge (found by the new check).
    - **The agent's manual**: label units and decimals stay Auto; what a dumbbell's end label means.
    - **Tests** on `d2d-relay:e05f035`: every suite, 727 checks with the starting-credit review on and 710 off, all
      passing, with the new `item35_check.py` (9: the built-in visuals gallery's prototype plus a page of the three
      cases, no label past its visual's edge on any page, the dumbbell and waterfall labels, the rebuilt visuals
      shipped; against the image before the change it fails on every fault). Upgrade from `aa4531e`: 23 of 23. End to
      end with real Claude, one report per Visuals mode to the .pbix: 35 of 35, now also checking every page of each
      report in Chromium: no label past its visual's edge, no Relay data label reading $0M or a bare unit. The Relay
      report's waterfall read $5.91M, +$524K, +$165K, -$284K, -$75K, $6.24M; its dumbbells +7.0%, +3.9%.
    - **Deployed at 18:24 IST**: live idle; deploy folder fast-forwarded to `e05f035` (no compose, `pbix\`,
      `daxcheck\` or `config\` change); `d2d-relay:e05f035` tagged latest; web, admin and the job runner restarted.
      Checked on live: healthy on `e05f035`; healthz, sign-in page and admin portal 200; the 13 rebuilt visuals,
      the label fixes and the manual's rule served; the runner probe job labelled and removed; no errors.
      `d2d-relay:aa4531e` kept for going back.
    - **Seen in that run, next (item 36):** the Relay Gauges KPI card writes a long field label into its value
      ("Revenue Growth %+11.3%"); and when the AI gives a visual a measure as its title but no title column in its
      prototype SQL, the app's prototype shows the measure's name ("Title Revenue Trend"; the .pbix shows the
      sentence).

Test data in the live install: none since the fresh start (item 18); PASDACS's own test traces went too (item 33).

## How items 9-10 were checked (2026-11-10)

(Deployed on 2026-11-10 with the second sweep, commit `eff2f2d`.)

- An isolated container from the live image with this code mounted (port 8101, its own empty volume, codes printed
  in its log with `RELAY_OTP_DEV_LOG=1`, no Claude sign-in, so every AI run fails, which exercises the refunds).
  81 end-to-end API checks pass:
  - public domains refused;
  - the platform admin;
  - a new organisation and a colleague joining;
  - isolation between organisations and the platform;
  - `/api/admin` refused to owners;
  - charges, refunds on failure, stop and retry;
  - a change request, a free gate fix, 402 with too few credits;
  - credit requests and admin top-ups;
  - the per-network code limit.
- Upgrade: a container started with the live code made a session, a dashboard and a logo, then restarted with this
  code on the same volume. The session, dashboard and logo stayed, PASDACS became an organisation with 100 credits,
  and a second restart did not add credits again.
- The screens in a browser: sign-in with the "Create your organisation" step, `#/setup`, the chip, Add credits,
  Organisation, Organisations, the credits on New dashboard and on a failed dashboard, dark mode, and 375 px width
  with no sideways scroll.

## Second sweep (2026-11-10)

Every screen was walked in a browser on an isolated container, signed in as several people with a temporary test
login. The API checks were run again: the 81 above plus 10 for the test login, all passing. Fixed on the way:
- the credits chip did not update when a failed run gave credits back;
- the search palette offered schedules and Administration links that lead nowhere;
- an organisation's owner was shown the AI models behind the Relay Model, and was labelled "Admin" instead of
  "Owner";
- the credit history linked a colleague's private dashboard;
- the notification texts promised pages, alerts and schedules that D2D Relay does not have;
- every dashboard page asked the switched-off data observability API.

## Still open

Updated 2026-11-12, after item 35's deploy. **Live:** web, admin and the job runner run `d2d-relay:e05f035`
(= latest, since 18:24 IST); the database container runs `d2d-relay:8689305`'s image; live holds only PASDACS and
info@pasdacs.com. **GitHub**, this folder and the deploy folder are all on this log entry (items 34 and 35 and their
logs pushed after their deploys; every commit scanned for the live `.env` and `tunnel.env` values and key patterns:
none). **Going back** to item 34 (`d2d-relay:aa4531e`, kept): in the deploy folder `git reset --keep 520e88e`,
`docker tag d2d-relay:aa4531e d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner`; to item 33
(`d2d-relay:54f6ed7`, kept) the same with `2cd493e` (it takes `config/house-models.json` back too). No older release
image is kept on this PC (item 33): any other version is a commit on
GitHub (in the deploy folder: `git checkout <sha>`, `RELAY_COMMIT=<sha> docker compose build web`), then `docker
compose up -d --no-deps web admin runner` (only `web admin` for a version before item 31); going back before item 31
also takes the deploy folder to `7ecd8b4` first (`git reset --keep 7ecd8b4`) and `docker rm -f d2d-relay-runner` after.

### Before the public launch (the user)

- **The AI runs on a personal Claude plan** (audit P1). The AI engine signs in with a Claude subscription ("Ultra", no
  team seat), which Anthropic treats as a consumer plan: customers' data in it may be used to train models if the
  account's "Help improve Claude" setting is on (then kept up to 5 years; otherwise 30 days). **That setting is off
  since 2026-11-12 (the user).** For customers' data, still recommended: an Anthropic API key (commercial terms: not used
  for training, a data processing addendum; D2D Relay supports it, provider `anthropic_api`) or a Team or Enterprise
  plan. The privacy notice says Anthropic handles the data, and nothing about training until then.
- **Terms and policies** (P2, P4): published on 2026-11-12 (item 30): terms of service, refund and cancellation
  (none), contact. Still: a lawyer's review of them and of the privacy notice (check "PASDACS's own server in India",
  name a grievance officer if wanted); PASDACS's registered address and phone on the contact page (Razorpay's website
  review usually asks for them); a signed data processing agreement when a customer asks.
- **The PC** (P3): BitLocker is skipped for now (the user, 2026-11-12). The nightly backup (02:30 IST) is on the
  same disk as the data: keep an encrypted copy somewhere else. (Every older backup was deleted on 2026-11-12, on the
  user's word.)
- **Overnight restarts:** the user handles them (2026-11-12). (The PC restarted at 02:38 IST that day and the live
  site was down until ~09:17 IST: Docker Desktop starts only when someone signs in to Windows.)
- **The two PC helpers do not start by themselves (one-time).** Put shortcuts to `daxcheck\start-daxcheck.cmd` and
  `pbix\start-pbix.cmd` in the Startup folder (`docs/d2d-relay.md`, "After the PC restarts"); Claude Code may not add
  them. Until then, after a restart someone signs in and starts both by hand; the watchdog warns PASDACS after 10
  minutes without either.
- **The admin portal through the internet** needs two steps in Cloudflare (an Access application, then the public
  hostname admin-d2d.pasdacs.com; `docs/d2d-relay.md`, "Admin portal") and the team name and AUD tag in `.env`
  (optionally `RELAY_ADMIN_EMAILS`). Until then it works on the D2D Relay PC only: http://127.0.0.1:8102.
- **The mailbox.** The mail app sends app-only (a client secret), which Microsoft lets it do as any mailbox: limit
  it to info@pasdacs.com with Exchange Online's RBAC for Applications, which replaces Application Access Policies
  (`docs/d2d-relay.md`, "Limit the mail app to info@pasdacs.com"). The sign-in alerts and the review emails keep
  names, addresses and networks in that mailbox: give their folder a one-year retention tag (P6).
- **The old address** d2d-relay.pasdacs.com: done. The user removed its public hostname in Cloudflare; the name no
  longer resolves (checked 2026-11-12, ~13:30 IST). https://d2d.pasdacs.com is the only address.

### Selling credits online (the user, when Razorpay activates the account)

Buying credits online is off on live since 2026-11-12 (the user: "from the live site remove buy credits for now as its
in test, allow only request credits, once razorpay is activated we can allow production to buy credits"): the Razorpay
test keys are parked as comments in the live `.env` (with a note there), so payments are "off" and everyone, PASDACS
included, sees Request credits only; the webhook secret stays, so the webhook still answers. Going live:

1. The live keys (rzp_live_...) into the live `.env` in place of the parked test keys.
2. A live-mode webhook in the Razorpay Dashboard: URL https://d2d.pasdacs.com/api/payments/webhook, events
   payment.captured, order.paid, payment.failed and refund.processed, its secret as `RELAY_RAZORPAY_WEBHOOK_SECRET`.
3. Restart web and admin.
4. On the admin portal, Payments: PASDACS's invoice details (legal name, registered address, state, PIN and GSTIN; the
   SAC code from the accountant, the setting suggests 998314; the LUT's ARN if one is filed for 2026-27, else dollar
   sales carry IGST, included in the price), and GST 18% added on top (the user's decision of 2026-11-11, "₹100 + 18%
   GST": 25 credits ₹2,500 + ₹450 GST = ₹2,950; dollar prices abroad unchanged). Live keys cannot sell before the
   invoice details are complete. Then switch Sell credits online on.
5. For buyers abroad: International payments in the Razorpay Dashboard (Account & Settings; Razorpay reviews it).
   Until then only Indian cards go through, though people abroad see dollar prices ($1 a credit; ₹100 in India).

Refunds: none (item 25); any made by hand on Razorpay are recorded.

### Engineering still open (details in the audit)

Done on 2026-11-12 (item 30): S10, S11, S15, S16, S17, P6, the AI engine's API (S4) and its network (S6). Left:

- **S4, the rest:** each build now runs in a container of its own (item 31); the Claude sign-in volume, with its run
  transcripts, is still shared by the jobs. A long-lived token (`claude setup-token`, the user's, once) would let each
  job run without the shared sign-in.
- **S6, the rest:** the web app's own connections are not limited: the user's decision of 2026-11-12, to review later.
- **A removed person cannot come back on their own** (item 32): their address is blocked until an owner unblocks it.
- **Abuse:** Turnstile on "Send code" (S7, S13): the user chose not now (2026-11-12). New organisations wait for
  PASDACS's review of their starting credits (item 27), and PASDACS gets an email for every sign-in (item 21).
- **Never run on the test stacks:** a real Razorpay checkout and real email delivery. Since item 34 the end-to-end
  run covers real Claude, Power BI's engine (the DAX check) and the Power BI file maker, on the test stack's own copies
  of this PC's helpers (`tests/stack/helpers.ps1`).
- **The job runner's start-up sweep** (found while moving the release tests into `tests/`, 2026-11-12) is fixed in
  item 34, live since 17:05 IST: each runner removes only its own stack's jobs. A test stack from an image before
  item 34 (`upgrade_check.py` starts one) would still remove live's, so `tests/stack/stack.sh` refuses to start while
  any job container exists and warns if its runner removed one.
- **The release test suite is in `tests/`** since 2026-11-12 (committed here; not pushed, and nothing in the image
  changes): the suites, the test stack's compose file and `stack.sh`, the stand-in Razorpay and the audit's route list.
  `tests/README.md` says how to start the stack, run the suites in both review modes and tear down, and the real-Claude
  rule. Run from the repository against live's image `d2d-relay:54f6ed7`: 685 checks with the starting-credit review
  on and 668 with it off, all passing; also `upgrade_check.py` from `bdf370e` (23), `proto_sandbox_check.py` (23),
  `access_check.py` (10) and `guard_cases.py` (64 cases, 0 wrong). The route list was taken again from 54f6ed7:
  `/api/me/delete`, `/api/org/delete` (item 31) and `/api/org/unblock` (item 32) were missing, so `sec_check.py` now
  tries 114 routes without a session (111 before). `real_build_check.py` has since run from the repository (item 34,
  20 of 20); the real Razorpay test-mode checks still need Razorpay TEST keys in `tests/stack/.env.real` (the user's,
  never live keys). Not carried over, and sent to the Recycle Bin
  with the backup folder `Downloads\d2d-relay-test-suite` on the user's word (item 33): one-off scripts that edited
  the app, the guide, the work log and the suites for items 22-25 (their changes are in git), read-only scripts for
  live's data, Power BI Desktop and older .pbix helpers, the item 21 lockdown probes, the audit's proof kit (overlay
  image, sandbox-escape proofs, the DAX checker's test models), the older split-test compose files, and past runs'
  logs and screenshots.

### Decided (nothing to do)

- **The user's answers of 2026-11-12:** no refunds and no cancellations; disputes at the courts of Bengaluru,
  Karnataka; BitLocker skipped for now; overnight restarts handled by the user; no bot check on sign-in for now;
  owners see every dashboard with who made it (S8); deleting is immediate, after a warning (P5); the web app's
  outbound traffic is not limited for now (S6).

- **Migration D2D is a contact form** (item 29): PASDACS does the migration with the organisation; it is not
  self-service. Requests arrive at info@pasdacs.com and on the admin portal's Requests page.
- **The first-time tour** shows on its own only to people who start on or after 2026-11-12; Take the tour (the
  organisation's name in the top bar) shows it to anyone.
- **Brand palettes cost no credits** (as asked; Ask Relay has cost credits since item 19). Their AI cost is recorded in
  `usage` only.
- **Turnkey deployments (the user's decision of 2026-11-11):** an organisation that wants its own warehouse or
  database connected, or row-level security, gets a turnkey deployment after it contacts PASDACS. Neither is built
  into the shared D2D Relay (the backlog items for client connector sign-in and RLS are dropped); the Connections
  page and its request say so.
- **The enterprise sample:** Global Ports Enterprise (demo), with two row-level security roles added by hand, is
  kept in `data\samples\global-ports-enterprise-demo-10c1` (its README says how to use it); its .pbix with both
  roles is also in `C:\Users\santosh.k\PbixBot\Output\Global Ports Enterprise Stress`.

## Hand-over rules for this repository

- Work in this repository only; never change RELAY (the `Gen BI` folder) to serve D2D Relay.
- AI work runs one at a time; do not start several agents in parallel.
- Before a redeploy, check that nothing is running for a user. A restart kills a running dashboard build.
- Secrets live only in `.env` and `tunnel.env` (both git-ignored), never in commits.
