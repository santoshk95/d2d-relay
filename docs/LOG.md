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
   "Relay …").
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
     iCloud, AOL, Proton, GMX, Yandex, Zoho Mail, Rediffmail, QQ/163, Mailinator …, plus their country variants)
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
     shows "Retry · 30 credits".
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
    - **Admin portal → Requests:** Approve (the amount may differ; the credits are added in the same transaction that
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
      questions left in them instead of its AI cost; the Ask button shows " · 10 credits" when the next question is
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
    to Decision, and D2D Relay is a product of the Relay Platform by PASDACS. Said under the RELAY logo ("D2D · Data to
    Decision" / "a Relay Platform product · PASDACS"), on the sign-in page, on the Dashboards page ("D2D · Data to
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
        (`agent/managed-settings.json` → `/etc/claude-code/managed-settings.json`, above every other settings file):
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
      Data Protection Board), linked from the sign-in page, the profile menu and Organisation › Your data; and
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

Test data in the live install: none since the fresh start (item 18).

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

- **The two PC helpers do not start by themselves yet (one-time, for the user).** Put shortcuts to
  `daxcheck\start-daxcheck.cmd` and `pbix\start-pbix.cmd` in the Startup folder (`docs/d2d-relay.md`, "After the PC
  restarts"); Claude Code may not add them. Until then, after a restart of the PC someone signs in and starts both
  by hand; the watchdog warns PASDACS after 10 minutes without either.
- **Going back, if ever needed.** The code: every version is a commit on GitHub; build it in the deploy folder
  (`git checkout <sha>`, `RELAY_COMMIT=<sha> docker compose build web`), then `docker compose up -d --no-deps web
  admin`. The data before the fresh start: `data\backups\relay-db-20261111-064453.dump` (no dashboards are left
  from then but the sample below). Since item 22 the nightly sweep deletes hand-made dumps after 30 days: this one
  and the three others of 10-11 November go around 10-11 December; move any that must stay out of `data\backups`.
- **Images:** since 2026-11-11 (item 21) all three containers run the current image; older images were removed.
- **The admin portal through the internet needs two steps in Cloudflare** (an Access application, then the public
  hostname admin-d2d.pasdacs.com; `docs/d2d-relay.md`, "Admin portal"), and the team name and AUD tag in `.env`.
  Until then the admin portal works on the D2D Relay PC only: http://127.0.0.1:8102.
- **Payments: Razorpay** is next (the user will provide test keys). Until then an organisation requests credits
  and PASDACS approves them (item 13). Needed to build it: the test Key ID and Key Secret, a webhook secret (all
  three go in `.env`, never in commits), the credit packs and their prices in ₹ (GST included or added), who may pay
  (owners only, or anyone in the organisation), invoices (Razorpay's receipt, or a GST invoice from D2D Relay) and
  the refund rule.
- **Abuse.** Anyone with a business mailbox can sign up and create an organisation (as asked). Since item 19 it gets
  50 credits at once (about two dashboards' AI time) without anyone's approval; more need PASDACS's approval. Since
  item 21 PASDACS gets an email for every sign-in, and pauses an organisation or switches a person off on the admin
  portal.
- **Brand palettes cost no credits** (as asked; Ask Relay has cost credits since item 19). Their AI cost is recorded in
  `usage` only.
- **Turnkey deployments (the user's decision of 2026-11-11):** an organisation that wants its own warehouse or
  database connected, or row-level security, gets a turnkey deployment after it contacts PASDACS. Neither is built
  into the shared D2D Relay (the backlog items for client connector sign-in and RLS are dropped); the Connections
  page and its request say so.
- **NOT DONE (from item 2):** an Exchange ApplicationAccessPolicy that limits the mail app to info@pasdacs.com. Codes
  now go to any business address; the sender stays info@pasdacs.com.
- **Data governance: the user's decisions (item 22).**
  - **The AI runs on a personal Claude plan.** The AI engine signs in with a Claude subscription ("Ultra", no team
    seat), which Anthropic treats as a consumer plan: customers' data in it may be used to train models if the
    account's "Help improve Claude" setting is on (then kept up to 5 years; otherwise 30 days). At once: switch that
    setting off (claude.ai › Settings › Privacy). For customers' data: an Anthropic API key (commercial terms: not
    used for training, a data processing addendum; D2D Relay supports it, provider `anthropic_api`) or a Team or
    Enterprise plan. The privacy notice says Anthropic handles the data, and nothing about training until then.
  - **The disk is not encrypted.** Windows reports BitLocker on C: as "waiting for activation": the database,
    uploads and backups sit on it unprotected if the PC or disk is taken. Turn BitLocker (or Device encryption) on
    and keep the recovery key somewhere safe.
  - **Backups are on the same disk** as the data: keep an encrypted copy somewhere else.
  - **The privacy notice is written from what the app does**, not by a lawyer: have it reviewed; check "PASDACS's own
    server in India"; name a grievance officer if wanted. A customer agreement (terms, data processing) is not part of
    the app.
  - **The sign-in alert emails** keep names, addresses and networks in the info@pasdacs.com mailbox: give that folder
    a retention rule (a year matches the app).
- **The enterprise sample:** Global Ports Enterprise (demo), with two row-level security roles added by hand, is
  kept in `data\samples\global-ports-enterprise-demo-10c1` (its README says how to use it); its .pbix with both
  roles is also in `C:\Users\santosh.k\PbixBot\Output\Global Ports Enterprise Stress`.

## Hand-over rules for this repository

- Work in this repository only; never change RELAY (the `Gen BI` folder) to serve D2D Relay.
- AI work runs one at a time; do not start several agents in parallel.
- Before a redeploy, check that nothing is running for a user. A restart kills a running dashboard build.
- Secrets live only in `.env` and `tunnel.env` (both git-ignored), never in commits.
