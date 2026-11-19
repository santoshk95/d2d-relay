# D2D Relay: work log and hand-over

Last updated: 2026-11-12 (IST). This file says where the project stands for anyone who clones it.

## What D2D Relay is

D2D means Data to Decision. D2D Relay is a product of the Relay Platform by PASDACS: cut from RELAY, the platform
(copied from Relay commit 8f3d9a0), as a product of its own for a client who wanted
Power BI dashboard generation from CSV files and Google BigQuery. It has its own repository, image, container, data and
sign-in. The setup guide is `docs/d2d-relay.md`.

**Turned down on 2026-11-17 (item 54).** The app is switched off: its five containers are stopped, not removed, and its
data is kept. d2d.pasdacs.com is now a static page about D2D (how it works, a 79-second video, contact), served by a
Cloudflare Worker from the PASDACS site repository (`d2d-page/`). Since 2026-11-18 the app runs again on this PC only,
for client demos, with its tunnel removed (item 57). The rest of this section describes the app as it ran.

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

36. **KPI names clear of their values; measure titles in the prototype** (the user, 2026-11-12: "can you fix and deploy
    and publish all you can"; what item 35's end-to-end run showed next). Code `53fb6ad`, **live since 19:20 IST** the
    same day.
    - **Relay Gauges' KPI tile** under a title and subtitle (a low tile, as the AI lays them out) printed the measure's
      name top left and the value centred on the same line: "Revenue Growth %+11.3%". Now, where the two would meet,
      the value moves right of the name when the tile has room (the usual case), else under it while it stays 14 px or
      more, else the name is shortened. Relay Gauges 1.0.7.0, rebuilt offline with the toolchain pinned in the image,
      GUID unchanged; mock-host cases 18 and 19, whose checks fail on the old code (`visual-atlas/docs/HISTORY.md`
      section 19).
    - **A visual titled by a measure** needs its sentence in its prototype SQL's "title" column (the agent's manual).
      Without it the app's prototype showed the measure's name ("Title Revenue Trend"; the .pbix shows the sentence).
      Now `genbi prototype` and `genbi validate` report it to the agent like its other SQL problems, so a fix round adds
      the column, and until then the prototype shows a readable stand-in ("Revenue Trend"). The manual states the rule
      for Power BI's own visuals and Relay's alike.
    - **Tests** on `d2d-relay:53fb6ad`: every suite, 737 checks with the starting-credit review on and 720 off, all
      passing, with the new `item36_check.py` (10: four KPI tiles laid out like the AI's, about 280 px each, two charts
      titled by a measure, the version shipped; against `e05f035` it fails on the overlaps, the titles and the
      version). Upgrade from `e05f035`: 23 of 23. End to end with real Claude, one report per Visuals mode to the .pbix:
      41 of 41, now also checking every page of each report in Chromium for a Relay Gauges name on top of its value and
      for a visual titled by a measure that does not show its sentence (both caught on `e05f035`'s prototype, neither
      on `53fb6ad`'s). The Relay report's 12 KPI tiles kept name and value apart ("Revenue Growth", then "+11.3%");
      the 52 visuals titled by a measure in the three reports all had their sentence from the first build, so the new
      report to the agent was not needed.
    - **Afterwards:** the test stack, its helpers and their data folder removed; the test runs' transcripts deleted
      from `claude-api-auth`. Live was not touched.
    - **Deployed at 19:20 IST**: live idle (no job container, the AI engine not busy, no dashboard); deploy folder
      fast-forwarded to `53fb6ad` (no compose, `pbix\`, `daxcheck\` or `config\` change); `d2d-relay:53fb6ad` tagged
      latest; web, admin and the job runner restarted. Checked on live: healthy on `53fb6ad`; healthz, sign-in page
      and admin portal 200; Relay Gauges 1.0.7.0, the title rule and the manual's line served; the runner probe job
      labelled and removed; no errors. `d2d-relay:e05f035` kept for going back.
    - **Seen in that run, next (item 37):** the Relay Hierarchy sunburst writes labels on slices too thin for them:
      in the Relay report the labels of Clothing's two outer slices (2.5% and 2.4%) overlap each other, as do the
      inner labels of Clothing (4.9%) and Accessories (3.7%), and they run over their slices' edges.

37. **A sunburst's labels stay inside their own slices** (the user, 2026-11-12: "Yes, fix it", for what item 36's
    end-to-end run showed next). Code `334b493`; release image `d2d-relay:334b493`, built from the clean commit and
    tested; **live since 20:45 IST** the same day, on the user's "Yes, deploy" (Claude Code's auto mode had refused
    the restart on "Yes, fix it").
    - **Relay Hierarchy's sunburst** wrote the labels of its thin slices over each other: in the Relay report "Online
      2.5%" lay on "Retail 2.4%", and the inner "Clothing 4.9%" on "Accessories 3.7%". A thin slice's label runs along
      the radius, so its two lines sit side by side across the slice, and only one line's room was checked. Now a label
      is measured as a block of lines and drawn only when all of it stays inside its own slice, clear of the gaps: name
      and value, else the name alone, else nothing. A label that does not fit one way (along the radius or across the
      slice) tries the other, so the report's 15% Components slice, unlabelled before, now gets one. Relay Hierarchy
      1.0.7.0, rebuilt offline with the toolchain pinned in the image, GUID unchanged; a mock-host case with the
      report's slices, and checks on every sunburst case that fail on the old code, which had the same fault in the
      mock host's own sunbursts (`visual-atlas/docs/HISTORY.md` section 20).
    - **Tests** on `d2d-relay:334b493`: every suite, 747 checks with the starting-credit review on and 730 off, all
      passing, with the new `item37_check.py` (10: such a sunburst in the app's prototype, wide and small, in
      Chromium; against `53fb6ad` it fails on the overlaps, the slices, the Components label and the version).
      Upgrade from `53fb6ad`: 23 of 23. End to end with real Claude, one report per Visuals mode to the .pbix: 44 of
      44, now also checking every page of each report for a sunburst label on another or outside its slice. The
      Relay report's sunburst showed Bikes 77%, its channels 39% and 37%, Components' channels 7.6% and 7.2%, and
      Components, with nothing on the thin slices; no new fault seen on its three pages.
    - **Afterwards:** the test stack, its helpers and their data folder removed; the test runs' transcripts deleted
      from `claude-api-auth`. Live was not touched.
    - **Deployed at 20:45 IST** after the user's "Yes, deploy": live idle (no job container, the AI engine not busy,
      no dashboard); deploy folder fast-forwarded to `e41bea0` (no compose, `pbix\`, `daxcheck\` or `config\`
      change); `d2d-relay:334b493` tagged latest; web, admin and the job runner restarted. Checked on live: healthy on
      `334b493`; healthz, sign-in page and admin portal 200; Relay Hierarchy 1.0.7.0 served; the runner probe job
      labelled and removed; no errors. `d2d-relay:53fb6ad` kept for going back.

38. **Ready to be posted: shared links show a picture and a description; robots.txt; no ./ or ../ past the sign-in
    check** (the user, 2026-11-12: "final check before posting in social media and ads", then "Fix and deploy" for
    what the check found). Code `189ccac`; release image `d2d-relay:189ccac`, built from the clean commit and tested;
    **live since 21:53 IST** the same day.
    - **The check** (read-only, before any change): live healthy, both PC helpers running, every public page open
      to anyone and fine on phones (390, 360 and 320 px, emulated in Chromium), plain characters on all five. Found:
      a shared d2d.pasdacs.com link showed only "Sign in - D2D Relay" (no description, Open Graph or X tags, no
      image); `/robots.txt` redirected to the sign-in page; pasdacs.com/platform/ said "D2D (Data to Decisions)" and
      "a Power BI project", and no page on pasdacs.com linked to D2D Relay. Left with the user (not changed): the AI
      on a personal Claude plan (audit P1), work email only (Gmail, Outlook, Yahoo refused), new organisations
      waiting for PASDACS's review with the admin portal on this PC only, no tracking on either site (the privacy
      notice promises none; lead-form ads ask for a privacy policy link, which pasdacs.com has not had since
      2026-11-06), and overnight restarts while ads run.
    - **Shared links:** `login.html` has a description and Open Graph and X tags: "D2D Relay: your data to a Power BI
      dashboard", the sign-in page's line, and the share image `og/d2d-relay.png` (1200 x 630, the sign-in page's dark
      band; source `branding/pasdacs/assets/D2D/d2d-share.html`). `og:url` is `/login.html` itself, because `/`
      redirects there (a preview would loop otherwise). `robots.txt` keeps crawlers off `/api/` and `/auth/`. Both
      are open without signing in (`auth.OPEN_PATHS`).
    - **Found on the way:** a path with a `./` or `../` segment walked past the sign-in check through any open folder
      (`/fonts/../js/36-org.js`, also as `%2e%2e`, also through Cloudflare) and got the signed-in app's static files
      (scripts and pages; the API was never reachable that way). Such a path now gets 404 before the check
      (`auth.middleware`).
    - **Tests** on `d2d-relay:189ccac`: every suite, 788 checks with the starting-credit review on and 771 off, all
      passing, with the new `item38_check.py` (41: the tags, the image, robots.txt, ten dot paths refused, and ten
      paths still open or closed as before). The first run with the review on had one miss, pay_check's "a checkout
      never paid goes after the log period": the test stack's own start-up backup and sweep (`ops.nightly`, about a
      minute after start) ran in the same seconds and deleted the test's backdated checkout first, so the test's
      sweep found none (in the run with the review off the stack's sweep came 7 seconds after the test's); the rerun
      passed 788 of 788. Not run, as nothing they cover changed: the upgrade check and the real-Claude end-to-end run.
    - **pasdacs.com** (the corporate site's repository, `Downloads\pasdacs-corporate-site`, branch
      `redesign/lean-startup-site`, commits `00b7d37` and `b06a865`; Worker version `2a4151fb`, deployed with
      `npx wrangler deploy`): the Platform page says "D2D (Data to Decision)", its last step "a Power BI file (.pbix)
      with its data", and the note under the steps links to https://d2d.pasdacs.com/ ("Try D2D Relay at
      d2d.pasdacs.com"). Checked live: 12 sitemap URLs 200, the page's files identical to the build, nothing scrolls
      sideways at 320, 375 and 1440 px; IndexNow accepted 12 URLs. Not pushed.
    - **Deployed at 21:53 IST** after the user's "Fix and deploy": live idle (no job container, the AI engine not
      busy, no dashboard); deploy folder fast-forwarded to `189ccac` (no compose, `pbix\`, `daxcheck\` or `config\`
      change); `d2d-relay:189ccac` tagged latest; web, admin and the job runner restarted. Checked on live: healthy on
      `189ccac`; the sign-in, legal and health pages 200; `/`, `/index.html` and `/js/...` still 303 to sign in;
      `/og/d2d-relay.png` (1200 x 630, the committed file) and `/robots.txt` 200; LinkedIn's, Facebook's, X's and
      WhatsApp's preview bots get the new title and image; the five dot paths 404 through Cloudflare and on this PC;
      the admin portal answers on this PC; no errors. `d2d-relay:334b493` kept for going back. Not pushed then (GitHub
      stayed on `df65429`); pushed on 2026-11-13.
    - **Afterwards, on pasdacs.com and in the social pack** (the corporate repository; details in its
      `docs/STATUS.md`): the D2D page `/platform/d2d/` (the user: "add a d2d static page in the corporate site under
      platform relay as a sub project d2d", then "Yes publish, do a full test"; commit `14ed57a`, Worker version
      `8750ac8d`, 2026-11-12 late evening; tested live, 42 of 42) and D2D's own band with its logo right under the
      Platform page's hero (D2D needs "its own logo and section", then "Yes, publish"; commit `4371db7`, Worker version
      `2b6c0556`, 2026-11-13 morning; tested live, 26 of 26). Neither shows prices, and their "Try D2D" buttons open
      https://d2d.pasdacs.com/. The social pack (its own private repository) has had a Platform post, a Relay and a D2D
      story, WhatsApp catalogue items 8 and 9 and their copy since 2026-11-13 (`8bbd128`; the user: "yeah add").

39. **Anyone can sign up: a personal address (Gmail, Outlook, Yahoo ...) gets a personal workspace that buys its
    credits** (the user, 2026-11-13: "can you allow gmail and all emails but no credits and request credit options,
    they can only buy online so i get larger base"; then, asked: organisations keep Request credits and PASDACS can
    still give anyone credits on the admin portal, a personal workspace is just its person, throw-away inboxes stay
    refused, PASDACS hears of personal sign-ups as of organisations). Code `96ea48a`; release image
    `d2d-relay:96ea48a`, built from the clean commit and tested; **live since 22:21 IST** the same day.
    - **Who signs in** (`public_domains.py`, `otp.py`): free mail (`is_free`: the FREE list and the FAMILY brands'
      country domains) signs in; disposable mail (`is_disposable`) is still refused, with its own message. A business
      domain makes or joins its organisation as before.
    - **A personal workspace** (`orgs.py`): an organisation of its own, `personal = 1` (a new `relay.tn_orgs` column),
      whose `domain` is the full address, so nobody ever joins it by domain. Its person names it after the code
      ("Create your workspace"). No starting credits and no starting-credit request; Request credits and Add people
      are refused (403); out of credits, it is told to buy. PASDACS adds credits by hand as for any organisation, sees
      it as Personal on the admin portal, and gets the sign-in alert for each new one (for an organisation the review
      mail stands in for that alert; a personal workspace has nothing to review).
    - **Screens and pages**: the sign-in page (any email), the Organisation page, its menu, the tour and New dashboard
      without Request credits or people for a personal workspace; the terms, privacy notice and contact page say so
      (effective 13 November 2026). Plain characters throughout.
    - **Tests** on `d2d-relay:96ea48a`: every suite, 825 checks with the starting-credit review on and 808 off, all
      passing, with the new `item39_check.py` (37: who signs in, two Gmail addresses in two workspaces, Yahoo and
      Outlook, a business domain unchanged, the refusals, the admin portal, a checkout at the stand-in Razorpay, the
      alert, and the Organisation page in Chromium). `d2d_checks` and `sec_check` now expect free mail to get a code
      and throw-away mail to be refused. The first run's screenshots showed a stray "null" where a personal
      workspace's cards are left out (Element.append writes null as text): fixed before the release, and checked.
      Upgrade from `189ccac`: 23 of 23 (with `OLD_HAS_PURPOSE=1`, as for any old image from item 27 on).
    - **Deployed at 22:21 IST** after the user's "once tests pass, deploy it": live idle; deploy folder fast-forwarded
      to `96ea48a` (no compose, `pbix\`, `daxcheck\`, `config\` or Docker change); `d2d-relay:96ea48a` tagged latest;
      web, admin and the job runner restarted (down about 9 seconds). Checked on live: all three on `96ea48a`; the
      sign-in page, terms and privacy notice new; a throw-away address refused with the new message; the `personal`
      column there (PASDACS 0); payments still live and selling on; the webhook and the admin portal answer; no
      errors. No personal sign-up was tried on live (it would email a real address). `d2d-relay:189ccac` kept for
      going back. Pushed the same evening ("Push all").
    - **pasdacs.com and the social pack** (the user's "Update and publish", the same evening; details in the corporate
      repository's `docs/STATUS.md`): the D2D page's sign-in, credits and closing lines and the Platform band's line
      say anyone with an email address (commit `668d763`, Worker version `6cfdc583`, 22:31 IST; tested live: the new
      lines and none of the old, the pages' code chunks identical to the build, the 13 sitemap URLs 200, nothing
      sideways at 320 to 1440 px; IndexNow accepted 13 URLs). The social pack was regenerated from it (`678bf60`:
      the Platform posts, the D2D stories, the WhatsApp status and the copy). Pushed the same evening: both site
      branches at `622377c`, the pack's `main` at `678bf60`. Posts already published
      (the WhatsApp Business profile and catalogue, social posts) are the user's to edit.

40. **A bot check before a sign-in code is emailed: Cloudflare Turnstile** (the user, 2026-11-13: "bot check add back",
    once item 39 let anyone sign up; security audit S7, S13). Code `d1882f7`; release image `d2d-relay:d1882f7`, built
    from the clean commit and tested; **live since 22:56 IST** the same day, on with the user's own Turnstile keys.
    - **How** (`otp.py`, `login.html`; `docs/d2d-relay.md`, "Bot check"): with both keys set (`RELAY_TURNSTILE_SITE_KEY`,
      `RELAY_TURNSTILE_SECRET`) the public sign-in page shows the widget under the form, and `/auth/otp/start` checks
      its token with Cloudflare (siteverify, action `otp-start`) before a code is made or sent: no token or a refused
      one, 403; Cloudflare out of reach, 503; no code either way, and the address's limits are not used up. A token
      works once (the page resets the widget after each ask). Without the keys nothing changes; the admin portal never
      asks. The privacy notice names the check under Cloudflare.
    - **Tests** on `d2d-relay:d1882f7`: every suite, 846 checks with the starting-credit review on and 829 off, all
      passing, with the bot check on throughout (the stack runs Cloudflare's published test keys, and
      `d2d_checks.Person` sends a token with every code it asks for), and the new `item40_check.py` (21: the site key
      on the public page only; no token, no code and no limit used; Cloudflare's no, Cloudflare out of reach and a
      token for another action refused; the admin portal; the widget in Chromium at 320 and 1280 px). Upgrade from
      `96ea48a`: 23 of 23.
    - **The keys:** the user made the widget in Cloudflare (hostname d2d.pasdacs.com, Managed) and typed both keys into
      the live `.env`; checked before the deploy: both lines well formed, and Cloudflare knows the secret.
    - **Deployed at 22:56 IST** after the user's "Yes, deploy": live idle; deploy folder fast-forwarded to `d1882f7` (no
      compose, `pbix\`, `daxcheck\`, `config\` or Docker change); `d2d-relay:d1882f7` tagged latest; web, admin and the
      job runner restarted (down about 8 seconds). Checked on live: all three on `d1882f7`; the public sign-in page gets
      the site key, the admin portal none; a code asked for without a token is refused (403, nothing sent); in
      Chromium the live page shows Cloudflare's widget under the form at 1280 and 375 px (Turnstile's requests 200,
      nothing sideways; a headless browser is asked to tick "Verify you are human", as a bot should be); payments
      still live and selling on; no errors. `d2d-relay:96ea48a` kept for going back. The check alone off: empty both
      keys in the live `.env`, then `docker compose up -d --no-deps --force-recreate web`. The user tried it in a
      private window the same night: the check passed on its own (no click), and the code came.

41. **A clean, minimal sign-in page** (the user, 2026-11-13: "too much wordings, make it clean and minimal and
    professional"). Code `2686fc4` (+ `f981608`, a test's wording); release image `d2d-relay:2686fc4`, built from the
    clean commit and tested; **live since 23:15 IST** the same day.
    - **Sign in:** one line ("Enter your email to receive a sign-in code."), Email, the security check above the
      button, Continue, and one line for the terms, the privacy notice and help. The code step: "Sign-in code", "We
      sent a sign-in code to ... It expires in 10 minutes.", and Resend code (with the check on: back to the email step
      for a fresh check) or a different email. Shorter first-sign-up steps (organisation, personal workspace) and
      messages. How organisations and personal workspaces work is told at the first sign-up step, on pasdacs.com and in
      the terms.
    - **Tests** on `d2d-relay:2686fc4`, review on: 847 of 847. The first run had 846: `item30_check` looked for
      "accept" on the sign-in page; it now also takes "agree to the" (the new line's wording) and passed 54 of 54 on
      the same stack. `item40_check` also checks Resend code (22). Wording and layout only, so no review-off run.
    - **Deployed at 23:15 IST** after the user's "Yes, deploy": live idle; deploy folder fast-forwarded to `f981608`
      (no compose, `pbix\`, `daxcheck\`, `config\` or Docker change); `d2d-relay:2686fc4` tagged latest; web, admin and
      the job runner restarted (down about 9 seconds). Checked on live: all three on `2686fc4`; the new wording served
      and the old gone; a code asked for without a token refused with the new message (403); the widget at 1280 and
      375 px, nothing sideways; payments live; no errors. `d2d-relay:d1882f7` kept for going back.
    - **Follow-up `baf70e5`** (the user: "fix need help wrap and deploy"): on a wide screen "Need help?" broke across
      two lines; the small print's links now stay whole (`.fine a`). Tested 847 of 847 (review on); **live since 23:27
      IST** (`d2d-relay:baf70e5`; `2686fc4` kept), checked: the rule served, "Need help?" whole on its own line at 1280
      px, the widget at 1280 and 375 px, the bot check refusing a request without a token, payments live, no errors.

42. **The AI on PASDACS's Anthropic API key first, the Claude subscription as its backup** (the user, 2026-11-13: "i
    have claude api key, how to enable it as primary and personal as backup"; audit P1). Code `01559b6` (+ `6592bb6`,
    the new test's fix); release image `d2d-relay:01559b6`, built from the clean commit and tested; **live since 23:49
    IST** the same day, with the user's key.
    - **How** (`providers.py`, `askd.py`; `docs/d2d-relay.md`, "The AI's Claude account"): with
      `RELAY_ANTHROPIC_API_KEY` in the live `.env`, every AI run whose owner has no provider of their own goes to
      Anthropic with the key, given to that run only. When the key is refused, out of credit or rate-limited, or
      Anthropic is down, the run is tried once more on the AI engine's own Claude sign-in, with an `ai.fallback`
      record. Dashboards and changes already fell back this way; Ask Relay now does too. Each run records which one
      answered. Never name the line `ANTHROPIC_API_KEY`: the AI engine would then hold the key itself and use it for
      every run, so the backup could never answer. Without the line nothing changes.
    - **Tests** on `d2d-relay:01559b6`, review on: 858 of 858. The first run had 857: the new `item42_check` read the
      AI engine's environment as root, which may not read it; it now reads it as the engine's own user and counts only
      its own run's fallback records (`6592bb6`), 11 of 11 on the same stack. The provider does not touch the
      starting-credit review, so no review-off run. With real Claude on the test stack (live's sign-in volume, the
      user's key for that run only): the key answered, a deliberately wrong key fell back to the sign-in, which
      answered, and one fallback record; both answers forgotten, the test's folder removed from the volume, and the
      stack's `.env` (which held the key) deleted. When the first try fails, Ask Relay cannot forget that try's
      transcript (its session is not known); the nightly sweep removes it after 7 days.
    - **The key:** the user typed it into the live `.env`. Checked before the deploy: one well-formed
      `RELAY_ANTHROPIC_API_KEY` line, no plain `ANTHROPIC_API_KEY`, and Anthropic accepts the key (a model list, no
      cost).
    - **Deployed at 23:49 IST** after the user's "Key added, deploy": live idle (no job, no project, the AI engine not
      busy); deploy folder fast-forwarded to `6592bb6` (no compose, `pbix\`, `daxcheck\`, `config\` or Docker change);
      `d2d-relay:01559b6` tagged latest; web, admin and the job runner recreated (down about 8 seconds). Checked on
      live, with no AI call: all three on `01559b6`; in web and admin a run's main provider is "Anthropic API (this
      installation's key)" and its backup "Claude (this installation's login)"; the AI engine's own environment and
      the job runner hold no Anthropic key; health and the sign-in page 200; the bot check still refuses a request
      without a token; payments live and selling on; no errors. `d2d-relay:baf70e5` kept for going back. The key alone
      off: empty the line in the live `.env`, then `docker compose up -d --no-deps --force-recreate web admin`.

43. **The contact page gives PASDACS's address: "Bangalore, India"** (the user, 2026-11-14, after the lawyer's review:
    "address you can put as Bangalore, India"). One line under the email box on `contact.html`; `item30_check` looks
    for it. Code `a871751`. The first build also showed a phone number the user had given; release tests 858 of 858
    (review on); it went live at 09:33 IST, and on the user's "remove number, its not required" it came out again:
    that commit was never pushed and was replaced by `a871751` (legal pages 54 of 54 on its image), live since
    09:36 IST, its old image deleted. Checked on live: the contact page has the address and no number (Cloudflare does
    not cache it), health and the sign-in page 200, the webhook still refuses an unsigned call (400), the AI engine
    idle, no errors. `d2d-relay:01559b6` kept for going back.
44. **A dashboard's credits follow its visuals: 25 with Power BI's built-in visuals, 50 with custom visuals** (the user,
    2026-11-14: "25 credits in dashboard is for default visual and 50credits for custom visuals(fully custom/default plus
    custom)"). `orgs.COST["dashboard_custom"]` (`RELAY_CREDITS_DASHBOARD_CUSTOM`, 50) beside `COST["dashboard"]` (25); a
    new dashboard is charged by its visuals (built-in first with custom where needed, or Relay custom visuals: 50, noted
    "custom visuals" in its history) and refused before anything is saved when the organisation cannot pay it. A built-in
    dashboard moved to custom visuals on its Details tab pays the difference (25) once ("custom visuals" in its history);
    back and forth after that is free; dashboards from before count as paid for the visuals they had. Retry charges what
    the charge that came back was. Screens: the New dashboard form's choices carry their credits and its Uses line follows
    the choice; the Organisation page, a dashboard's Credits card, Buy credits, the tour and the admin portal give both
    prices; the Visuals switch says what custom visuals add. The first page now waits for the signed-in person (a page
    opened directly drew before the organisation was known).
45. **The queue shows each organisation only its own jobs, and builds cannot be stopped** (the user, 2026-11-14, on a
    dashboard saying "1 job(s) ahead of this one": "Why to public it shows other job details?", then "Just accept detials
    and show queue" and, of the Stop button, "Hide it everywhere, so customers can't stop a waiting or running build"). A
    waiting dashboard says "In the queue: It starts shortly. You can leave this page; it keeps its place."; its position,
    /api/health's queue and the agent's busy flag count the organisation's own jobs only (which job runs was already
    private, P17); no Stop button, and `POST /api/projects/<id>/stop` answers 403 inside an organisation.
46. **Builds side by side, up to 3** (the user, 2026-11-14: "Add parallel builds", and "power bi pbix file will be sequence
    only as it run in the same windows machine"). The worker starts the oldest waiting job whenever one of
    `RELAY_BUILD_PARALLEL` (3) slots is free, never two of one dashboard (`worker.ACTIVE`; `worker.current` is the oldest
    one a tenant may see, as before; `running_job`, `is_running`, `running_since`, `all_running`, `busy_owners` for the
    rest); publishing (`pbi`, `pbix`: the DAX checker and the Power BI file maker on this PC) runs one at a time outside
    those slots. The AI engine's build lane takes as many runs (a semaphore; relay_init passes the setting), the chat lane
    one; /health and /metrics say how many run and the capacity. Each build still runs in a job container of its own
    (8 GB cap each; the Docker VM has 15.5 GB). **Items 44-48 tested and live:** release image `d2d-relay:777f30c`
    (code 7619e16, 16e38c3, 56af6e7, 1d23630, 9725b54, 777f30c; tests 470d90b), 935 of 935 checks with the review on
    (item44 37, item45 15, item46 13, item48 12). Real Claude on the test stack (the subscription, no API key): the
    three Visuals modes built **side by side** (3 runs at once; planned in about a minute, published with their .pbix at
    8.9, 10.1 and 11.4 minutes: about 11 minutes for all three, where one at a time took about 30), 45 of 45, and
    `real_build_check` 20 of 20. Every job container ran `--model claude-opus-5-5` with Claude Code's helper models set to
    it; each build peaked at 134 to 382 MiB, 549 MiB for all at once. The first build of item 46 did not start (its job
    list took the name of the status set `worker.RUNNING`; renamed `ACTIVE`). Live since 11:09 IST after the user's "ok if
    all tested deploy and publish it", live idle at the time: the AI engine takes 3 builds and 1 chat run, defaults to
    the Relay Model, prices 25 and 50, the screens and terms as tested, no errors. A finished live job
    container the runner had not removed (exited 0 at 10:13 IST) was removed by hand: it blocked the test stack.
47. **One model: Claude Opus 5.5** (the user, 2026-11-14: "in API use opus 5.5 as default and same in personal as well dont
    use any other model for Relay Model powered by claude"). Every run already asked for the Relay Model
    (`config/house-models.json`: `claude-opus-5-5`, on the API key and the Claude login alike); now nothing falls back to
    Sonnet either: the AI engine's default is the Relay Model, Ask Relay no longer prefers Sonnet, the catalog's default and
    the worker's last fallback are `claude-opus-5-5`, and a Relay run sets Claude Code's own helper models (its background
    tasks, Haiku unless told, and its subagents: `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`,
    `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`) to `claude-opus-5-5`.
    Opus 5.5 is $4 / $20 per million input / output tokens on the API, twice Sonnet 5.5. The Console's usage page showed
    only a tiny Haiku 5.5 entry that day (2,286 tokens in, 4 out, from before any D2D run on the key; its data lagged by
    hours); the live runs' own records showed the Relay Model only (a dashboard's data and plan: about $0.97).
48. **The user's rule for builds that do not finish** (2026-11-14; not shown to customers, at the user's request; see
    `worker.give_back`). The sentence that credits come back when a run fails or is stopped is gone from the Organisation
    page, a dashboard's Credits card, the Stop refusal, `docs/d2d-relay.md` and the Terms of Service (the terms changed
    after the lawyer's review of the same day).
49. **The job runner removes its own finished jobs left behind, every two minutes** (found 2026-11-14 while testing
    items 44-48: a finished live job container, exited 0 at 10:13 IST, had been left after its stream went away, and
    the runner removed leftovers only when it started; the leftover kept the test stack from starting). `tidy_once`
    runs every two minutes beside the runner's API and removes this stack's job containers that ended, or were created
    but never started, more than five minutes before (`D2D_JOB_STALE_S`); a running job and another stack's are never
    touched. Code `1c841da`; `item49_check` 8 of 8 (stand-in containers); all suites 943 of 943 (review on). Live since
    11:25 IST, live idle at the time: the runner serves with the tidy beside it, its first rounds without an error; the
    site, the webhook, the AI engine's 3 build slots and the Relay Model as before. Also checked that day: the
    corporate site and its social pack were clean and pushed; Relay's paused wording work stays uncommitted and its
    GitHub backup branch was still identical (34 files and one new file).
50. **The admin portal opens on an Overview: who is online now and who has signed up** (the user, 2026-11-14: "can you
    put a small dashboard in the admin like live users and who are have signed up"). `GET /api/admin/overview` (admin
    portal only; the public site answers 404): who is online now (a public-site session seen in the last five minutes;
    the admin portal's own sessions never count), everyone who signed up, newest first, with their workspace (business
    or personal), sign-up time, last seen, dashboards and credits left, and the totals (sign-ups today and this week,
    workspaces by kind, dashboards made). The Overview is the admin portal's first page and menu item, refreshed every
    30 seconds; PASDACS's own people show among the online but are not sign-ups. Code `22c7464`; `item50_check` 19 of 19,
    all suites 962 of 962 (review on). Live since 11:51 IST on the user's "Yes, deploy when tests pass" (live idle): the
    API answers only after an admin sign-in; on live it counted 2 sign-ups that day, both personal workspaces, 1 dashboard.
51. **The sign-in code email in D2D's look** (the user, 2026-11-14: "can you give me nice email for otp rather than
    plain, in D2D theme"). It was three plain paragraphs; `app/code_email.py` now renders it like the sign-in page:
    the dark band with the D2D lockup (the three-row mark drawn with table cells on a white tile) and a mint bar, then
    "Your sign-in code", the code large in a mint panel, how long it lasts, what to do with an email nobody asked for,
    and a short footer with the site and the help address. Built as email has to be (tables, inline styles, no
    pictures or web fonts, so nothing is fetched when it is opened), with a dark version for mail apps in dark mode;
    the admin portal's says it is for the admin sign-in page. The subject is unchanged. Code `8029415`;
    `item51_check` 25 of 25, all suites 987 of 987 (review on). Live since 17:51 IST on the user's "Yes, deploy" (live
    idle): the live web and admin containers render it, each with its own wording, and nothing was sent. Not yet seen
    in a real mail app (Gmail, Outlook): no test email was sent, so the next sign-in code is the first in the new look.
52. **The three display bugs a real build showed, fixed** (the user, 2026-11-15: "fix all the bugs"; found that day
    while taking the marketing kit's screens, Engineering below). The .pbix was never wrong; the prototype people
    approve, the gates and Ask Relay were.
    - **The prototype's matrix no longer adds up ratios.** Power BI computes every measure once per row header, and a
      matrix with several Rows fields opens at its first level unless Row headers > Auto expand is on (Microsoft:
      "When disabled, row headers start collapsed"). `matrix()` in `genbi_kit/assets/stock_visuals.js` now draws
      that: one row per first-level value from SQL at that level, or with `rowHeaders.autoExpand` every level, each
      group's row bold with its own values above its indented children (Row subtotal position Top, the default; Bottom
      puts a Total row after them), in the visual's sort order. The prototype SQL returns a row per row header shown:
      group rows and the Total line come from `GROUP BY ROLLUP` (lower Rows columns empty; a blank member as
      '(Blank)'); GENBI.md and `genbi catalog pbi.pivotTable` say so. Where the SQL has no row for a header, a measure
      that adds up adds up its detail rows and any other stays blank: `stock.additive_measures()` reads each measure's
      DAX (ratios, averages, distinct counts, minimums and maximums, ranks, running totals and ALL-fixed values do not
      add up), which also fixes the table's Total line for a measure like an average order value. `genbi prototype`
      reports SQL that returns more rows than the matrix shows (both scorecards of the evidence: "returns 3 rows for
      Category = Electronics ...") and, with Auto expand, a group without its own row. The DAX check asks Power BI for
      the level the matrix opens at, and compares two Rows levels by position: before, both shared one key, so a
      stepped matrix was never compared at all (one reason the gates passed it).
    - **Card text.** Power BI's multi-row card never wraps a value: it cuts it with "..." (values side by side, as
      many to a line as fit). The prototype measured its values at 15 px and drew them at 16 px, so a cut sentence ran
      into the next; now each value is measured as drawn and cut inside its own place, and a cut text value is marked:
      the Display check fails it ("3 text values cut with ... - Power BI cuts them the same way ... pbi.cardVisual
      does, with value: {textWrap: true}"). The new card draws `value.textWrap` (word wrap over the lines it has room
      for). GENBI.md: sentences go in `pbi.cardVisual` with text wrap, never a multi-row card.
    - **Ask Relay.** A rate, share, margin or growth column holding fractions (nearly all values between -1.5 and 1.5,
      not all whole numbers) reads as a percentage everywhere: the chips ("Growth Pct avg 9.9%"), axis, bar labels,
      tooltips, Table view, "See the numbers" and the snapshot image, whose table showed raw floats and whose bars
      could not show a fall (both fixed). Such a column averages in the chips like other ratios and never gets a
      currency sign. The count says "8 cities" (city -> cities, status -> statuses, products stays). The prompt asks
      the AI for a percentage as a fraction in a pct-named column. A stored answer keeps a decimal as text; both read
      the same.
    - Tried on the evidence (`marketing/demo/sales-performance-64a3`, re-drawn with the new code): both scorecards are
      reported and their ratios stay blank; rewritten the new way (Auto expand and ROLLUP, the insights in a wrapped
      new card) it shows Electronics at a 32.9% margin and +9.8% growth (was 100.3% and -9.0%), North at +23.2%, the
      sentences whole, and passes the Display check. Not looked at: Power BI Desktop drawing an auto-expanded matrix
      and a wrapped new card (the checks cover the prototype, the files and the DAX queries).
    - Code `b77f38e`; `item52_check` 37 of 37, all suites 1024 of 1024 (review on). Live since 15:48 IST on the
      user's "commit and deploy once tests pass" (live idle: no runs, two dashboards waiting on their owners): web,
      admin and the job runner report `b77f38e`, the public site answers. Dashboards built before it keep their
      prototypes until their next change; then `genbi prototype` reports a stepped matrix whose SQL returns the detail
      rows, and the agent rewrites it. Pushed at 17:42 IST on the user's "Yes, push".
53. **The tunnel on cloudflared 2026.11.0** (the user, 2026-11-16: "Yes, update and deploy", after the check that
    followed their restart of the PC). The restart (08:57 IST, from the Start menu, not a crash) needed nothing by
    hand: Docker Desktop started the five containers at sign-in (09:03) and the Startup-folder shortcuts the two
    helpers (09:01), so the site was down about 5 minutes. The check found one gap: the tunnel held 3 of its 4
    connections to Cloudflare, because one Cloudflare server (198.41.192.77) refused the fourth at every try ("control
    stream encountered a failure while serving") and cloudflared 2025.11.1 keeps retrying the same server after that
    error. That version was also a year old, and Cloudflare supports releases from within a year of its newest
    (2026.11.0, out 2026-11-12). `docker-compose.yml` now pins `cloudflare/cloudflared:2026.11.0`; the command
    (`tunnel --no-autoupdate run`), the token in `tunnel.env` and the image's user stay the same, and the image now
    also sets `NO_AUTOUPDATE`. The release notes in between remove no flag we use; 2026.5.2 checks DNS and port 7844
    when it starts, and 2026.9.0 classifies the edge's registration errors better. Checked before the switch: the
    live command line parses on the new image (offline). Count the tunnel's connections with `docker exec
    d2d-relay-web curl -s http://d2d-relay-tunnel:20241/ready` (`readyConnections`, normally 4). **Going back:** set
    the pin to `2025.11.1` (image kept on this PC), then `docker compose --profile tunnel up -d --no-deps tunnel` in
    the deploy folder. Code `151f02e`; live since 09:29 IST (live idle): the tunnel was replaced in about a second and
    registered all 4 connections within 3 seconds (two in Bangalore, two in Mumbai), its new start-up checks all
    passed, no warnings or request errors, and the public site answers. Pushed at 09:32 IST on the user's "Yes, push".

Clean-up of 2026-11-16 (the user asked for a marketing session's stopped test stack to be removed and everything
cleaned): that stack from 2026-11-15 (two containers, four volumes and its network; no Claude login among them) is
gone, Docker's untagged build leftovers were pruned (49 MB), and the last test run's leftovers (`tests/out`,
`tests/stack/test-projects` and `tests/stack/.env`, which the next stack.sh makes again) went to the Recycle Bin.
Kept on purpose: the rollback images named under Still open, the cloudflared 2025.11.1 image (item 53), Docker's build
cache (it keeps release builds fast) and `tests/stack/.env.real`. GitHub, this folder and the deploy folder were then
on the same commit, and every other repository on this PC was committed and pushed (Relay's paused wording changes
stay uncommitted on purpose, identical to their backup branch).

54. **The app turned down; d2d.pasdacs.com a static page** (the user, 2026-11-17: "remove and turn down d2d platform
    from the live site d2d.pasdacs.com, keep a static page and video on how it works and content and contact us for
    more info via email or contact form"). Done in this order, at about 23:25 IST:
    - **The static page first.** A Cloudflare Worker, `pasdacs-d2d-page`, from the PASDACS site repository
      (`d2d-page/`, `wrangler.d2d.jsonc`, `worker/d2d-page.ts`; `d2d-page/README.md` says how to build, deploy and
      undo it), took the hostname as the route `d2d.pasdacs.com/*`. The tunnel's DNS record and public hostname are
      unchanged: the route answers before a request could reach the tunnel. (A custom domain was refused because the
      hostname has that record, and the deploy login can't edit DNS.) The page: what D2D is, the how-to video with a
      contact end card (the marketing kit's `video/how-it-works/`), the five steps, the 12 checks, what comes with it,
      a contact form (handed to the site's own form handler: its D1 table and info@pasdacs.com) and a note for people
      who had an account (their data is kept, switched off; email info@pasdacs.com for a copy or deletion).
      `privacy.html`, `terms.html`, `refunds.html` and `contact.html` stay online as they stood at `b15d40b`, each
      with a note that the app closed. `/login.html`, `/login` and `/gallery` redirect to the page, the app's API
      answers 410, and admin-d2d.pasdacs.com (still behind Access) has no origin now.
    - **Before stopping:** nothing was building (no job containers, both helper queues empty) and nobody had signed
      in for two hours. In the install: 3 accounts, 2 outside PASDACS (both personal workspaces whose credits PASDACS
      gave, 50 each; one used its 50 on two builds), no credit request pending, and one live payment, PASDACS's own
      Rs 2,950 test of 2026-11-14 (a second Rs 2,950 checkout by PASDACS was never paid).
    - **Backup:** `relay-ctl db-dump` to `data\backups\relay-db-20261117-175615.dump` (1.06 MB), beside the nightly
      backups.
    - **Stopped:** `docker compose --profile tunnel stop` (runner and tunnel, then web and admin, then the database).
      The containers and the volumes `d2d-relay-db-data`, `d2d-relay-data`, `d2d-relay-admin-data`,
      `d2d-relay-agy-login` and `d2d-relay-runner-sock` are kept, as are `data\projects` and the shared Claude
      sign-in. With `unless-stopped`, Docker does not start stopped containers again after a restart.
    - **Host helpers:** the DAX checker and the Power BI file maker were stopped, and their Startup-folder shortcuts
      moved to the Start menu folder "D2D Relay helpers (off)", so nothing starts at logon.
    - **Not changed:** Razorpay (the live keys stay in `.env`; no checkout can start without the app, and its webhook
      would now get the page's 410), the Entra mail app and its secret, the Turnstile widget, Cloudflare Access for
      admin-d2d, the tunnel and its token. Account holders were not emailed.
    - **Bringing it back:** take the Worker's route off (`npx wrangler delete -c wrangler.d2d.jsonc` in the site
      repository, or remove the route in the Cloudflare dashboard), `docker compose --profile tunnel up -d` in the deploy
      folder, and start the two helpers from "D2D Relay helpers (off)" (back in Startup for logon). The DNS record was
      never touched, so the tunnel serves the hostname again at once.
55. **Semantic Review: Power BI models checked against the organisation's KPI dictionary** (the user, 2026-11-17: "add
    another feature which is semantic and dax reviewer in the existing environemnt by connecting via azure or
    uploading pbix file, against the ontology/kpi definination any orgnaistion and flag any inconsisnet dax/formula
    used which can have issues with the intent of one kpi one meaning/value, as analyzer"). A new screen for every
    organisation, **Semantic Review** (`#/review`, under Ask Relay; `docs/d2d-relay.md`, "Semantic Review"): the
    organisation's KPI dictionary (its ontology of KPIs: name, other names, definition, formula in words, reference
    DAX, unit, aggregation, rules, time basis; added in the app, imported from CSV / Excel / YAML / JSON with a preview,
    downloaded, or started from a review's measures), and reviews of up to 5 models at once: uploaded `.pbix` (read by
    PBIXRay 0.15.5 in a process of its own, with limits), `.pbit`, `model.bim`, zipped Power BI projects (TMDL), or
    models in the Power BI service through the organisation's own Entra app (Fabric getDefinition, the INFO.VIEW
    functions when that is refused; Contributor is needed, as Power BI shows DAX only to identities that may change a
    model). Every measure's DAX is read, expanded and written one canonical way (`genbi_kit/semreview`), so the rules
    find a KPI calculated more than one way (in one model or across models), measures that do not compute what the
    dictionary defines, the wrong aggregation, averages of ratios, YTD / LY / vs-budget variants not built on their
    KPI, another year end, percentages not shown as such, visual titles naming another KPI, visuals adding up a
    column a KPI measure covers, and DAX that gives a wrong or unstable number (references to nothing, CALCULATE around
    a variable, SUMX without CALCULATE, ALL on a KPI, ids or rates added up by default ...). Claude then checks the
    measures against the definitions in words (no tools, its answer checked; it sees definitions and DAX, never data),
    and for service models the disagreeing measures' values are shown side by side. 10 credits a review
    (`RELAY_CREDITS_REVIEW`; the price is my default, for the user to confirm), given back when a review does not
    finish; the meaning check may run once more at no cost when the AI could not answer. Uploaded files are deleted as
    soon as they are read; only metadata is kept. An independent review of the code (a separate agent, 2026-11-18)
    found 14 problems, all fixed and covered by tests: a YAML alias bomb and a zip-bombed workbook in the dictionary
    import, exponential work on deeply layered measures (31 levels of doubling references now take a moment; 3,000
    measures 2 s), false "differs" when the dictionary's DAX uses the model's own measures, `Table[Measure]` and
    `dt"..."` read as broken, a failed meaning retry that wiped a finished review, a malformed AI answer that failed the
    review, "All" / "Overall" read as filler, Indian fiscal-year phrasing, a non-Latin review name breaking the CSV
    download, and two start-up races. Tests: `item55_check` 90 and `item55_ui_check` 18 (the stack has stand-in
    Microsoft APIs, `fake_powerbi.py`, on 127.0.0.1:8106; their people sign in from 203.0.113.x, as sign-in codes are
    limited per address); every suite passes in both review modes, and `upgrade_check` 23 of 23 from live's
    `b77f38e`. The real .pbix of the Global Ports dashboard (86 measures, 9 tables) is read in under a second with no
    DAX finding. Committed in the work folder; **not deployed, not pushed**. Built as item 54 and renumbered 55: the
    user turned the live app down meanwhile (item 54, above) and intends to license D2D to client organisations
    rather than offer it to the public (the user, 2026-11-18: "i have removed d2d from the live site, intent is to go
    license based for clients not to public"), so there is no live site to deploy it to. Open for the user: the price
    (10 credits a review); the privacy notice and the terms do not mention Semantic Review yet (Claude now also sees
    KPI definitions and DAX; models can come from the customer's Power BI): for the lawyer, or the client licences,
    before any organisation uses it. Open in engineering: the `.pbix` reader runs as the web app's user in the web
    container (limits and a clean environment only); a job container of its own (no network, only the upload, like
    the AI builds) is the next hardening.
56. **Nobody signs up: PASDACS creates each organisation, its owners add its people** (the user, 2026-11-18: "Remove
    signup and bring login directly as internal team management", after taking D2D off the live site to license it to
    client organisations, item 54). The sign-in page is now only that: email, code, in. A code goes only to an address
    with an account; any other address gets the same answer ("If ... has a D2D Relay account, we sent it a sign-in
    code"), after about as long as sending one takes, and the code limits count it the same way, so the page never
    tells anyone which addresses have accounts (the audit records `auth.otp_no_account`, with the domain only).
    Accounts come from two places. **PASDACS creates each organisation** on the admin portal (Organisations, **New
    organisation**: its name, its main owner's work address and name, and its starting credits, 50 unless another
    number is set; one organisation a domain; no free mail or throw-away owner), and the main owner is emailed. **Its
    owners add its people** (Organisation, People, as before). PASDACS can also add someone to any organisation
    (Organisations, **Add someone**, the person button on its row: a new owner when the owners have left, say; the
    owners are told). The admin portal now takes only pasdacs.com people with an account in PASDACS's own workspace (a
    PASDACS owner adds colleagues on the public site), no longer every pasdacs.com address. Gone with the sign-up:
    joining an organisation by email domain; the step that named a new organisation (`/auth/otp/organisation`, and
    its table `otp_signup`, dropped at start); new personal workspaces for free mail (item 39; the two on live keep
    working as they did); the blocked list of removed addresses (item 32: removing someone deletes their account, so
    nothing is left to block); and the starting-credit review with its emails (item 27; a request from before that
    is still waiting can be approved, as starting credits, and `RELAY_CREDITS_START_REVIEW` is ignored). The sign-in
    alerts, the admin portal's Overview ("People", "Added"), the Organisation page, the tour, the README,
    `.env.example` and `docs/d2d-relay.md` say so.
    Found by the tests and fixed: creating an organisation on the admin portal could fail (500) when the public site
    set the same new workspace up at that moment on first use, as two processes created its tables at once;
    `db.init_tenant` now takes the advisory lock `db.init` takes at start. The admin portal's Organisations table
    gained a person button rather than a third text button. Tests: one mode now (the starting-credit review was
    the second); the suites have PASDACS create their organisations and people first
    (`d2d_checks.provision_account`, in `Person.sign_in`); `item56_check` (62) replaces `item39_check`; `sec_check`,
    `accounts_check`, `item50_check`, `item40_check` and `upgrade_check` follow the app. Every suite passes, 1160 of
    1160 on the candidate image, and `upgrade_check` 27 of 27 from live's `b77f38e`.
    Not changed: the privacy notice and the terms still describe joining by domain and personal workspaces; they are
    the lawyer-reviewed pages, for the user and the lawyer to update with the client licences. Committed as `64d2e28`;
    running on the live install, on this PC only, since item 57; not pushed.
57. **The sign-in code on the screen, for an install used on this PC only** (the user, 2026-11-18, for a client demo on
    the live install once they had removed its Cloudflare tunnel: "add a option to show the otp in the screen itself as
    all is local not in public"). With `RELAY_OTP_ON_SCREEN=1`, after Continue the sign-in page shows the account's code
    in a box and fills it in, and asks for no Turnstile check (its widget only works on the public hostname), for a
    request made on this PC only: from loopback or the Docker host (`portal.LOCAL`) with none of the headers a tunnel
    or proxy adds (`cf-connecting-ip`, `x-forwarded-for`, `forwarded`, `x-real-ip`). Anything else gets the emailed
    code with the bot check, as before; an address without an account still gets no code; each code shown is audited
    (`auth.otp_shown`). Off by default (`.env.example`; `docs/d2d-relay.md`, "The code on the screen"). Found while
    preparing the demo: the start page ("/") said "No dashboards yet" in a workspace with dashboards whenever their
    list arrived after the page was drawn (since `8e4a862`); it now redraws when the list arrives, as `#/d2d` did
    (`02-shell.js`). Tests: `item57_check` (23; the test stack turns the code on the screen on for its admin portal
    only, so the public site's suites keep the emailed path and the Turnstile widget; its start-page check holds the
    dashboard list back 1.5 s in Chromium and fails on the old `02-shell.js`); every suite passes, 1183 of 1183 on
    `d2d-relay:item57-test2` (the start-page check was corrected to finish the owner's first-time tour first, then
    rerun). **Live, on this PC only, since 2026-11-18 about 10:00 IST**, on the user's "use the live instance itself
    as i have removed the cloudflare tunnel, so all will be local only": the database backed up first
    (`data\backups\relay-db-20261118-042839.dump`), the deploy folder fast-forwarded to `64d2e28` (items 55 and 56),
    web, admin, runner and the database (which had stayed on `8689305`'s image) on the tested image built from the work
    folder with item 57 (`d2d-relay:latest`), `RELAY_OTP_ON_SCREEN=1` added to its `.env`, the tunnel left stopped, and
    the two PC helpers started again. A client demo with sample data was then seeded into PASDACS's own workspace. The
    start-page fix was copied into the running web and admin containers at about 10:10 IST; the image rebuilt with it
    and tested, `d2d-relay:item57-test2`, waits for the user to put live on it
    (`docker tag d2d-relay:item57-test2 d2d-relay:latest`, then `docker compose up -d`): until then a restart keeps the
    fix but a recreated web or admin loses it. **Going back:** delete the `RELAY_OTP_ON_SCREEN` line,
    `docker tag d2d-relay:b77f38e d2d-relay:latest` (kept), `git reset --keep b15d40b` in the deploy folder, then
    `docker compose up -d`. Not pushed.
58. **A dashboard from a DAWB hand-off, with its plan** (2026-11-18). DAWB, the user's lakehouse builder, now writes a
    D2D project after every lakehouse build: the data in and profiled, a plan proposed. Until now every New dashboard
    had Relay plan from scratch, even when the CSVs came with a ready plan. The user's choices: the hand-off folder as
    one .zip on New dashboard (no watched folder), DAWB adding shared date and store tables with relationships while
    D2D takes either shape, and the price of any new dashboard. **From a DAWB hand-off** on New dashboard
    (`POST /api/projects/import`, `webapp/app/handoff.py`) takes `project.json` (kind "d2d-project", format 1),
    `data/*.csv` and `manifest.json`, zipped as the folder or as its files (Windows backslashes too). Before anything is
    saved or charged it checks every file the manifest lists against its sha256, each CSV's columns in order and rows,
    reads the data with D2D's own profile (`profile.md`, `profile.json`, as Relay's planning makes them), each
    relationship's types and one-side keys (a value in every row, each once) and that no table reaches another along
    two filter paths, and D2D's plan check; a problem is refused with what is wrong (the first six named), with no
    credits used and nothing left behind (at most 2,000 files and 8 GB unpacked, `RELAY_HANDOFF_MAX_GB`). The
    dashboard then waits at Confirm KPIs with DAWB's plan in `plan.yaml`: its KPIs (label = name; currency `\$#,0`,
    percent `0.0%`, whole number `#,0`, or the KPI's own format string), pages, tables with role, grain and description,
    relationships and note. A KPI with the name of a column, which Power BI refuses, becomes "Total ..." with its old
    name as its label, and the KPIs that use it follow (strings and comments untouched). `request.md` tells the build
    to keep the KPIs' DAX and the table and column names they use, to give tables and columns DAWB's descriptions, and
    to treat DAWB's visuals, queries and 24-column grid as guidance, not as the report's layout (the build prompt says
    so too, `prompts.HANDOFF`). DAWB's `project.json` and `manifest.json` are kept as written in `handoff/`. It costs
    what a new dashboard costs (25 with Power BI's built-in visuals, 50 with custom visuals); the charge rides with the
    first build, as a planned dashboard's does. The plan screen says "DAWB's plan", with a "From a DAWB hand-off" tag,
    until Relay revises it. Columns now carry a `description` into Power BI's model (`report_builder`, GENBI.md).
    `create_project`'s option parsing and request.md style sections moved, unchanged, into `_options` and
    `_style_lines`, which the import shares. Agreed with the DAWB session by message: relationships written
    `many_table[column] -> one_table[column]`, tables as names or `{name, role, grain}`, every column described, an
    optional `format_string`, no KPI named like a column. DAWB regenerated its Pinecrest Markets example to match within
    the hour (12 tables with `dim_date` and `dim_store`, 48,515 rows, 11 KPIs, 4 pages, 12 relationships), and it
    imports as it is. Found while building: the first path check took any loop as two paths, which refused a star with
    two shared dimensions; it now follows filter direction. Seen in the tests and left as it was (not this item): a
    desktop window shrunk to 360 px keeps the wide sidebar state (`d2d.rail`), so its top bar scrolls sideways; a phone
    opening the app at its own width does not. Tests: `item58_check` (76), the hand-off DAWB writes on this PC included
    when it is there (`TEST_HANDOFF_DIR`); `sec_check`'s route list taken again (`POST /api/projects/import`). Every
    suite passes on `d2d-relay:item58-test`: 1258 of 1259 in the full run, and the one failure, item 56's admin-portal
    screen check, passed when run again on the same stack (62 of 62). It is a timing race in that check: the New
    organisation dialog's own focus on its first field (30 ms after it opens) came while the browser was typing the
    starting credits, so "30" went to the end of the name and the credits kept their default, 50. Fixed in the commit
    after this one (item56_check and pay_ui_check wait for a dialog to settle before typing; 62 of 62 and 37 of 37,
    five runs each). **Live, on this PC only, since 2026-11-18 14:29 IST**, on the user's "comit all and publish"
    and their choice of both a push and a deploy: live was idle; the database was dumped first
    (`data\backups\relay-db-20261118-085838.dump`); the deploy folder was fast-forwarded to `f754035` (no change to
    the compose file, `config` or the PC helpers' scripts); web, admin and runner run `d2d-relay:f754035`, built from
    the clean commit with the pinned Antigravity image, whose app and toolkit files match the tested image's but for
    a comment in `auth.py`; the database container stays on item 57's image; the tunnel stays stopped
    (`RELAY_OTP_ON_SCREEN=1` is kept). Checked afterwards: healthz 200 on both sites, the import refuses a request
    without a sign-in (401), no errors in the logs, both PC helpers idle. Pushed: GitHub `main` is `f754035` (items 55
    to 58, the item 54 log and the test fix; scanned first against the live `.env` and `tunnel.env`: only the Claude
    volume's name matched, already public). **Going back** to item 57: `docker tag d2d-relay:item57-test2
    d2d-relay:latest` (item 57 with its start-page fix, 1183 of 1183), `git reset --keep 1896c3a` in the deploy
    folder, then `docker compose up -d --no-deps web admin runner`.

The release of 2026-11-19 (items 59 to 68 and 73 below, and the work in progress between them): all asked for by the
user that day, for a client trial; in the work folder, which other sessions edit at the same time. **Not committed, not
deployed, not pushed.** Its release tests are being written alongside (`item59_check`, `item60_check` and
`item61_check` so far, and a stand-in GitHub, `fake_github.py`; the Razorpay suites are deleted). One deploy later, at
https://demo.pasdacs.com from this PC through the Cloudflare tunnel, with the sign-in code by email ("Waiting for the
next deploy", under Still open). `docs/d2d-relay.md` describes each item.

59. **No buying online: Request credits only; past payments and their GST invoices kept** (the user, 2026-11-19:
    "remove payment all and have only as request credits"). D2D is licensed to client organisations, so credits come
    only from PASDACS. `webapp/app/payments.py` is cut down to past payments: no checkout, no webhook (its sign-in
    exemption in `auth.py` is gone), no billing details, no packs or Sell credits online; Razorpay keys left in a
    `.env` are ignored. Every screen offers Request credits only (`36-org.js`: the chip's menu, the Organisation page,
    the not-enough-credits message, New dashboard; `38-tour.js`), personal workspaces too (they could only buy before:
    `orgs.credit_request` no longer refuses them, and the not-enough-credits text is the same for all). Kept as
    accounting records: `relay.tn_payments` with the GST invoices. The Organisation page lists **Past payments** only
    when the organisation has any, each with its invoice or receipt (`37-payments.js`, `payments.past`,
    `GET /api/payments/<id>/receipt`); the admin portal's **Payments** is read only: every past payment, the real ones'
    totals, and a financial year's invoices as CSV for the accountant. The contact page no longer mentions payments or
    Buy credits. Emails from either site now name the public site's address, `portal.site()`: `RELAY_SITE_URL` (which
    `docker-compose.yml` gives the admin portal from `RELAY_PUBLIC_URL`), else the public site's own
    `RELAY_PUBLIC_URL`, else https://d2d.pasdacs.com; never the admin portal's own address. It is used by the
    invitation (`orgs._invite_mail`), the starting-credit approval and the sign-in code email's footer
    (`code_email.render`). Not changed: the terms of service, the refund policy and the privacy notice still describe
    buying online through Razorpay (the lawyer-reviewed pages, for the user and the lawyer); Razorpay's own account and
    its live webhook (nothing calls them; the webhook's address is d2d.pasdacs.com's, now the static page). Tests: the
    Razorpay suites (`pay_check`, `pay_ui_check`, `rzp_real_check`, `rzp_real_ui`, `fake_razorpay.py`, `rzp_stub.js`)
    are deleted; `item59_check` covers what replaces them (past payments still open, every API needs a sign-in,
    Request credits for a personal workspace).
60. **One organisation, several email domains** (the user, 2026-11-19, for a client trial whose people use two
    domains). Besides the main domain it was created with, an organisation can have other email domains
    (`relay.tn_org_domains`: domain, tenant, added, by; 20 in all at most, `orgs.MAX_DOMAINS`), each one organisation's
    only, never a free mail or throw-away service's (`orgs.clean_domain`). PASDACS gives them on the admin portal:
    **Other email domains** on New organisation (comma-separated; `orgs.create(domains=...)`), or the globe button on
    an organisation's row (**Email domains of ...**: add, remove; `orgs.add_domain`, `orgs.remove_domain`,
    `POST /api/admin/orgs/<id>/domains`, `DELETE /api/admin/orgs/<id>/domains/<domain>`; audited as
    `d2d.org_domain_added` and `d2d.org_domain_removed`). The owners are told when one is added; the main domain stays;
    taking another away keeps the accounts made with it. Owners add people at any of the domains (`orgs._add`);
    `orgs.by_domain` finds an organisation by any of them and `orgs.domains_of` lists them, the main one first, for
    `/api/me`, the Organisation page, the tour and the admin portal; erasing an organisation removes its domains. A
    personal workspace has none.
61. **The ontology layer: business terms, industry packs and the KPI dictionary** (the user, 2026-11-19: "ontology layer
    as well where we bring default ontology and kpi as per industry and user can also configure and change"). A new
    screen, **Ontology** (`#/ontology`, under Semantic Review; `js/42-ontology.js`): the organisation's business terms
    (what its columns mean: name, kind, entity, unit, aggregation, family, other names in columns; `onto_terms` in its
    schema; add, edit, remove, import YAML or JSON, download, "Try column names"), its KPI dictionary (item 55's, also
    at `#/ontology/kpis`) and 13 industry packs written for it (`genbi_kit/ontology_packs/*.yaml`): Grocery and retail
    (80 terms, 55 KPIs), Consumer goods, E-commerce, Healthcare, Manufacturing, Software and subscriptions, Supply
    chain and logistics, Hotels and restaurants, Banking and lending, Insurance, Telecom, Energy and utilities (69 to 80
    terms and 38 to 55 KPIs each) and General business (41 and 17), which tags columns until an organisation has terms
    of its own. Owners and BI Devs apply a pack (what the organisation has stays unless the pack's versions are asked
    for; a KPI whose name belongs to another is left out); PASDACS can pick one when it creates an organisation (New
    organisation, **Industry**; `ontology.apply_pack_cli`) or run `python -m app.ontology apply <workspace> <pack>`.
    Columns are tagged by name only, and each tag says why (`genbi_kit/ontology.py`: words split, abbreviations spelled
    out, plurals singular, amount or a currency ignored, the kind fitting the column's type; variants such as
    `sales_ly`; modifiers such as `gm_pct`). Before planning, and before each build and change, the worker writes
    `ontology.json` and `ontology.md` into the dashboard's folder; `genbi profile` tags every column (a "business term"
    column in profile.md), lists measure terms found in several columns, related terms of one family and one entity's
    keys under different names, and tries those keys as relationships (kept when half the values match); the plan
    prompt and GENBI.md tell the agent to name model columns after their terms, prefer the dictionary's KPIs
    (`dictionary: <name>` in plan.yaml) and combine one term found in several tables; `ontology.mark_plan_kpis` marks
    which plan KPIs are the dictionary's (`plan_dictionary`). Ask Relay's ideas come from the packs' example questions
    (item 66). API under `/api/ontology`; audited as `ontology.*`.
62. **The semantic model on the plan screen** (the user, 2026-11-19). Before Relay plans, `worker.read_data` reads the
    data (the ontology files, the sample of big tables, the profile with every column's term), records `data_size`
    and `semantic_ready`, and notes in the activity what it found; a DAWB hand-off is read the same way when it is
    imported. The **Semantic model** card (`js/41-semantic.js`, `css/semantic.css`; `GET /api/projects/<id>/semantic`,
    `ontology.semantic_view`) is on the Overview while Relay plans, and replaces the plan's table list at Confirm KPIs:
    the columns matched and the industry, the KPIs from the dictionary, how much data is used, a diagram of the tables
    and relationships (facts in the middle, `*` and `1` on each line, the key on it), the terms found in several
    columns or tables and the keys of one entity, and each table's columns with type and term. While the plan waits,
    a column's term can be changed for free (`PUT /api/projects/<id>/semantic`: `semantic_overrides`, the profile and
    ontology.json made again, used by the build), and BI Devs and owners can teach the ontology the column name at the
    same time (`POST /api/ontology/teach`).
63. **A KPI changed in plain words, 1 credit** (the user, 2026-11-19: "each kpi can be fixed or change by natural
    language as well each 1 credit"). `webapp/app/kpi_words.py`; `orgs.COST["kpi"]` (`RELAY_CREDITS_KPI`, read as
    `D2D_CREDITS_KPI`, 1). On the plan, while it waits at Confirm KPIs, each KPI card has a line to say what to change,
    **Change** and **Fix it** (`POST /api/projects/<id>/kpis/change`): Relay rewrites that KPI's name, label,
    description, DAX and format, saved into plan.yaml at once; each card says whether its KPI is from the dictionary,
    differs from it, or is new. In the KPI dictionary (Ontology or Semantic Review) the wand button does the same for
    an entry (`POST /api/semreview/kpis/<id>/change`; BI Devs and owners). The credit is charged first and given back
    when nothing changes: Relay unreachable, "cannot be done with this data", or an answer that fails the checks (plain
    text; DAX the plan's lint and Semantic Review's parser can read; only the planned model's tables; no other KPI's
    name; the dictionary's own rules). Relay answers on the chat lane with no tools (`askd.ask_json`) and sees no data
    rows. Audited as `kpi.words` and `kpi.words_dictionary`.
64. **Large data: uploads in parts, and building on a sample** (the user, 2026-11-19). **Uploads in parts**
    (`webapp/app/uploads.py`, `01-core.js` `upload()`): Cloudflare refuses a request over 100 MB, so files over 4 MB go
    up ahead of their form in 32 MB parts (`POST /api/uploads`, `PUT /api/uploads/<id>/<n>`, each part retried on its
    own, `POST /api/uploads/<id>/done`) and the form names them (`uploads`); New dashboard, a revised plan, a change
    request, a DAWB hand-off and Semantic Review take them through the same checks as before. Up to 10 GB a file
    (`RELAY_UPLOAD_MAX_GB`), only with room on the disk for three times the file plus 2 GB, kept for the person who
    started it in the organisation's `.uploads` folder (not backed up), removed once used, or a day later.
    **Sampling** (`genbi_kit/sampling.py`): New dashboard shows the size of the data and asks **Data used to build**
    (Automatic: tables over 2 million rows sampled, `GENBI_SAMPLE_OVER`; every table over 1 million; every row) and
    **How to sample** (random: a reservoir of 1,000,000 rows, `GENBI_SAMPLE_ROWS`, seed 42; or the most recent rows by
    the first date column), kept as project.json `data_policy`. The worker samples once before planning
    (`sample.json`, `.genbi/cache/*.sample.parquet`, `data_sample/`); the profile, `genbi sql`, the prototype, the gates
    and the DAX check read the sample, smaller tables stay whole, the agent is told totals are the sample's (GENBI.md),
    and Ask Relay reads every row (`data.connect(full=True)`). The report's DataFolder points at `data_sample/` and the
    file gates check those files. Semantic Review takes files up to 500 MB (`RELAY_REVIEW_MAX_MB`, was 100). **Open**,
    found while writing this: `pbix.py` still hands the Power BI file maker the full `data` folder, so a sampled
    dashboard's .pbix is refreshed with every row, although New dashboard says the Power BI file loads the sample.
65. **Semantic Review fixes, with their credits shown first** (the user, 2026-11-19: "semantic review should be action
    as well rather than showing only finding, it should be able to fix and suggest credits for consumption").
    `webapp/app/semreview_fix.py`; `orgs.COST["fix"]` (`RELAY_CREDITS_FIX`, 1 a finding). A finished review shows what
    fixing uses (the fixable findings, how many the rules already wrote, the credits for all of them or only the high
    ones); the person picks findings (60 at most) and presses Fix (`POST /api/semreview/runs/<id>/fixes`, BI Devs and
    owners). The credits are charged, then in the background: the rules' own fixes are ready, the others are written
    by Relay on the chat lane with no tools (15 findings a request; it sees the findings, the DAX, the model's names
    and the dictionary, never data), and every fix is checked against the model the review kept (readable DAX, only
    its own tables, columns and measures, never itself); a fix that does not check out gives its credit back
    (`orgs.give_back_part`, new), and an error gives all of them back. A Fixes tab shows each measure's DAX now and
    fixed, and downloads per model a TMDL script (Power BI Desktop's TMDL view), a Tabular Editor C# script and a CSV
    (`/api/semreview/runs/<id>/fixes.tmdl`, `.csx`, `.csv`). Findings on visuals, relationships and calculation groups
    have no measure to fix. Kept in `semreview_runs.fixes`; audited as `semreview.fixes`. **Open**, found while
    writing this: the Fixes tab says "save and Review again to check", but Review again re-reads what the review kept,
    not the fixed model; a fixed model is checked by a new review of it.
66. **Ask Relay redesigned** (the user, 2026-11-19: "ask relay should be able to have more better ui and navigations").
    `js/14-askd.js`, `css/askd.css`: the conversations on the left (a search, Ctrl+K; pinned first, then Today,
    Yesterday, This week, This month, Earlier; pin, rename, delete), the conversation in the middle under its own header
    (its name, what it asks about, when it started, its questions, "Jump to a question", rename, delete) with the
    question box ("/" to reach it) and a meter of the questions left, and a side panel: Ideas (the industry packs'
    example questions, then the dashboards' suggestions), KPIs (the dictionary's and the dashboards', with a search)
    and Data. `PATCH /api/askd/threads/<id>` renames a conversation; `GET /api/askd/options` also gives the KPIs, the
    industry and its questions. Pins and the panel's tab are kept in that browser (localStorage). On a phone the
    conversations and the panel open over the page.
67. **The AI on the Claude subscription first, the API key as its backup; builds at the highest effort** (the user,
    2026-11-19: "internally switch the agent to use subscription from docker on opus 5.5 max"). `providers.py`: the
    installation's Claude login in Docker (the `claude-api-auth` volume) now runs first for everyone, and
    `RELAY_ANTHROPIC_API_KEY` answers only when it fails (an authentication, limit or outage error), with the
    `ai.fallback` record as before; `RELAY_AI_PRIMARY=api` puts the key first again (item 42's order). The Relay Model
    stays Claude Opus 5.5. Every dashboard run asks Claude Code for effort `max` (`worker.AGENT_EFFORT`,
    `RELAY_AGENT_EFFORT`), Ask Relay and the other chat answers for `high` (`askd.CHAT_EFFORT`, `RELAY_CHAT_EFFORT`);
    the AI engine passes `--effort` (`Run.effort` in `agent/server.py`; the job runner only checks that the command is
    `claude`). Customer-facing text still names no AI vendor. Not checked here: the pinned Claude Code (2.1.318)
    running with `--effort max`. Once live, every run goes through the Claude plan first again ("The AI's Claude plan",
    Still open).
68. **Relay's ring-fenced review team** (the user, 2026-11-19: "a multi agent where there is a developer, analyst, qa
    and ui/ux, story agent" and "always there should be a ring fenced agents review on each thing prepared and
    approved before coming to end users. always a multi model to ensure what comes out is 100% accurate and
    interactive and business ready"). The analyst plans, the developer builds, QA is the review gates; then independent
    reviewers (`worker.team_review`; `prompts.REVIEW_SYSTEM`, `REVIEW_ROLES`, `REVIEW_JSON`): the **analyst review** of
    each plan (KPIs computable from the data, deviations from the KPI dictionary, gaps, assumptions, the model) and,
    once a version passes the gates, the **UI/UX** (a picture of every page: `/display-check` with `shots`,
    `display.check(shots=)`, into `.review/shots/`), **story** and **accuracy** reviews (its own SQL against the
    prototype and Power BI's values, `.review/values.json`), side by side. Each is its own read-only run in the AI
    engine's new `review` lane (4 at once, `D2D_REVIEW_PARALLEL`), 40 turns and 20 minutes at most, on two models
    (`RELAY_REVIEW_MODELS`, default `relay,relay-review`: UI/UX on the builder's Relay Model, the others on
    `relay-review`, a new house model served with `claude-sonnet-5-5` in `config/house-models.json`, hidden from every
    picker); files it changed anyway are put back (`worker._fence`, `_unfence`). A "must" gets one fix round (the
    plan; or the version, with the gates run again, and a fixed version that fails them is dropped for the one before)
    and that reviewer looks once more. The new **Review team** gate (`gates.GATES["team"]`) passes when all approved
    and warns on what is still open or could not run; approval stays possible. On screen: **Relay's team on this
    version** (`js/45-team.js`: developer, QA, each reviewer with its asks, suggestions and checks) and the plan's
    analyst review (item 73). No credits. `RELAY_TEAM_REVIEW=off` switches it off. **Open**, found while writing this:
    (1) a run that names its tools never gets the shell (`_tool_args` in `agent/server.py` drops every `Bash(...)`), so
    the reviewers' `Bash(genbi:*)` is dropped and they cannot run the `genbi sql` their prompts ask for; (2)
    `D2D_REVIEW_PARALLEL` is not in relay_init's `AGENT_PASS`, so the AI engine never gets it and its review lane stays
    at 4; (3) a full lane answers 409 instead of queueing, and that is not a failover error, so with several builds
    reviewing at once (up to 9 reviewers with 3 builds) the ones past 4 show as "could not run".

In progress for the same release, by other engineers; their entries come with their code (see the code). In the tree
so far: a guided New dashboard (the user: "title first and then data is uploaded and then what needs to done or built
is prefilled and user can change it and confirm"; `POST /api/projects/suggest` in `webapp/app/newdash.py` prefills the
request from the uploads, the ontology and the KPI dictionary, with no AI and no credits; the screen is still being
written; the visuals become two choices, built-in or built-in plus custom, as a dashboard's Details tab already offers:
`07-tabs.js`); a brand every dashboard must have (`branding.require_style`: a palette and a font family from Power
BI's own list, set by owners, drawn in the prototype too: `prototype.font_stack`); "Relay Model" wording that keeps the
machinery confidential (`worker.friendly`, "Packaging the Power BI file" in `pbix.py`); a guided Semantic Review; the
prototype's filters fixed; the custom visuals reworded from Atlas to Relay, with a retail test set
(`visual-atlas/visuals/test/retail_*`, `ONLY=retail bash scripts/test.sh`) and a Comparison (last year) role and a
leaderboard in the gauges; publishing to the Power BI service and GitHub CI/CD (`webapp/app/deploy.py`, the Imports API
and a fabric-cicd workflow; its automatic run after a Power BI file, `after_pbix`, is not called by the worker yet).
Two of these call themselves item 70 in the code (`deploy.py`, and the wording in `worker.py`): to settle when they are
committed.

69. **The custom visuals say Relay, and a retail set is ready and tested** (the user, 2026-11-19: "review the custom
    visual i think its calling atlas visual, it should be relay and also review all custom visual possible or used in
    any way in retail specific and build all have it ready and tested"). Every customer-visible "Atlas" is gone: each
    family's empty-state title in Power BI ("Relay Columns" ...), the packages (`Relay<Family>.<version>.pbiviz` in
    `custom_visuals/atlas/` and `visual-atlas/release/`; `genbi_kit/atlas.py` reads old and new names, the newest
    version wins), theme names ("Relay - Soft"), the gallery and the scaffold; plain characters in labels. All 13
    families rebuilt (pbiviz 7.2.1, GUIDs unchanged): Columns 1.0.10.0, Compare 1.0.8.0, Distribution 1.0.9.0, Finance
    1.0.8.0, Flow 1.0.9.0, Gauges 1.0.8.0, Hierarchy 1.0.8.0, Lines 1.0.8.0, Parts 1.0.8.0, Proportion 1.0.8.0, Scatter
    1.0.7.0, Text 1.0.7.0, Time 1.0.7.0; the five library visuals rebuilt too. Retail: the gauges' Comparison (last
    year) role (changes between rates in points) and a leaderboard (sort, top N, 120+ rows), and about 25 defects fixed
    (waterfall axis and labels, bullet scrolling, heat grid colours and a middle value, timeline months, columns ticks
    and labels, donut labels and units, lollipop and dumbbell labels, aster petals). Tested: 11 retail pages, 109 cases
    (`visual-atlas/visuals/test/retail_*`), light and dark, small and wide; the 13 earlier mock-host pages; `genbi visual
    test` on the library. Left: a Pareto chart (a Lines combo instead), and plain characters in the 8 older Relay visuals
    (`custom_visuals/genbi*`, their own build).
70. **Dashboards published to the Power BI service, and GitHub CI/CD** (the user, 2026-11-19: "add a ci/cd deployment via
    github and auto publish to power bi service as well on azure/fabric"). `webapp/app/deploy.py`, `44-deploy.js`,
    `css/deploy.css`, the workflow template `webapp/app/templates_deploy/d2d-relay-deploy.yml`; table `deploy_runs`;
    settings in meta "deploy", the GitHub token in the secrets store. Publish: the .pbix through Power BI's Imports API
    as the organisation's Entra app (Member or Contributor on the workspace). Push: the Power BI project only (no data,
    nothing secret) through GitHub's git data API, never forced, plus once per repository a fabric-cicd 1.4.0 workflow.
    Automatic after every .pbix when an owner switches it on (`deploy.after_pbix`, called by the worker; never stops the
    dashboard). Tests: `tests/checks/item70_check.py`, the Imports API in `fake_powerbi.py`, a GitHub stand-in
    `fake_github.py`; 128 offline checks. Not yet tried against a real tenant, repository or Fabric workspace.
71. **A guided New dashboard** (the user, 2026-11-19: "title first and then data is uploaded and then what needs to done
    or built is prefilled and user can change it and confirm and it will be a guided way rather then all visible and one
    step is done then the next shows"). Six steps (`04-new.js` rewritten, `css/newdash.css`), files uploaded in parts as
    they are picked, the request prefilled by `POST /api/projects/suggest` (`webapp/app/newdash.py`, no AI, no credits),
    the theme step blocking until the brand is set, two visual choices. 44 server and 146 browser checks offline.
72. **A brand every dashboard must have, with its fonts** (the user, 2026-11-19: "prototype and theme needs to be set
    mandate before starting so its a step for branding and maintaining across the reporting and including fonts family").
    `webapp/app/branding.py` (`require_style`, body and heading fonts, three standard palettes, owners only),
    `35-branding.js`, `38-tour.js` (an owner cannot skip the brand step), `main.py` `_options` / `_style_lines` (fonts
    into request.md), GENBI.md's theme section. 51 offline and 29 browser checks.
73. **Every gap, assumption and difference from the KPI dictionary approved before the build** (the user, 2026-11-19:
    "data needs to be reviewed and let them know if any gaps or assumptions made ... any deviation or assumption or
    calculation needs to be approved"). The plan now writes `assumptions:` and `gaps:` (`prompts.PLAN`), and the
    analyst review (item 68) adds its own and the KPIs that differ from the dictionary (`deviations`).
    `ontology.approval_items` turns them into items with stable ids (kind and text), sent with the dashboard at Confirm
    KPIs (`approval_items`). **Review and approve** (`approvalsCard` in `js/45-team.js`, on the plan screen) lists them
    by kind, each with where it came from, a box to tick and **Approve all**; Confirm & build prototype stays off
    until all are ticked, and `POST /api/projects/<id>/kpis` refuses a confirmation whose `approved`
    (`KpiReview.approved`) misses one (400, with how many are left). What was approved is kept (project.json
    `approvals`: the items, who, when) and noted in request.md for the build; a revised plan brings a new list. A KPI
    card the analyst found different says "Differs from your KPI dictionary".

74. **"Relay Model" wording that keeps the machinery confidential** (the user, 2026-11-19: "instead of mentioned like
    power bi desktop and running all show it more confidential like relay model is working, is churning data, identity
    and context it with the data and dashboard being built"). About 75 text changes across the screens and the server's
    messages (no Power BI Desktop, PC, DAX checker, queue or vendor), plain messages for a run that stops
    (`worker.friendly`), the model's name "Relay Model" (`config/house-models.json`; was "Relay Model powered by Claude",
    the user's item 34 wording: changed for this ask, to be confirmed).
75. **A guided Semantic Review** (the user, 2026-11-19: "same with semantic or existing review, uploaded or connection
    established and then a review and guide way on what is configured and fixes as well"). `40-review.js` rebuilt,
    `css/review.css`; after fixes, a new review of the fixed models (Review again reads the kept ones). 63 browser checks
    offline.

76. **The prototype's filters work like Power BI's** (the user, 2026-11-19: "the prototype filters and other dont work as
    expecting"). Root causes: slicers and report filters were drawn with no click handling, each visual's SQL ran once,
    unfiltered, and GENBI.md told the agent to write the default year into the SQL; division by zero reached the page as
    Infinity or NaN; fonts were fixed to Segoe UI. Now a selection filters the model views as Power BI's relationships
    do, the SQL is written for the filtered rows, the likely selections are computed within a budget, and the theme's
    fonts are used (`prototype.py`, new `assets/prototype_page.js`, `stock_visuals.js`, GENBI.md; `daxcheck.differences`
    and `vfactory` read at the default selection; `atlas.theme_defaults` sets the brand font in the Relay visuals).
    Tested offline: 84 checks against independent DuckDB queries (75,000 and 1,000,000 rows), 25 edge cases, the
    sandboxed iframe (7), a tiny budget (7), the display check, the kit's gallery example identical at the default.
77. **GitHub and the Power BI service are connectors the customer sets up** (the user, 2026-11-19: "github is a connector
    [that] needs to be available for the customer to configure ci/cd and auto deployment to power bi service"). Item
    70's settings moved from the Organisation page to the Connections page, as two connectors under Deployment
    (`44-deploy.js` `deployConnectorCards`, `12-connections.js` `deploySection`, `css/deploy.css`): Power BI service
    (the organisation's Entra app, connected right there with the dialog Semantic Review uses, the workspace and
    automatic publishing) and GitHub (repository, branch, folder, token, automatic pushing, the fabric-cicd workflow and
    its repository secrets). Every organisation has them (no PASDACS switch, unlike the warehouses); owners set them
    up, everyone else reads them; the Organisation page points there; messages that named Semantic Review or "the
    deployment settings" name Connections. Also: a version without its page list no longer stops a dashboard's
    Overview from drawing (item70_check's planted dashboard lacked one: the one failing check of the release run,
    1569 of 1570, on d2d-relay:tests-snap4).
78. **More retail abbreviations tagged** (item 62's tagger, found while making the trial preview's sample POS file):
    `str_nbr` / `str_nm` (store), `shrnk_amt` (shrink), `promo_flg` (flag), `fy` / `fw` (fiscal year and week) are read
    as their business terms (`genbi_kit/ontology.py` ABBREV), and a column named exactly as a date term's own synonym
    (`fp` for Fiscal Period) is that date term even without a date word in it. Checked on the 137 columns of the demo
    data, the samples and the tests' files, before and after: only those columns changed.
79. **Two prototype drawing defects the review team found** (in the release's real-Claude test). The scatter chart: with
    Details and Legend both set, the prototype drew one point per Details value with the legend's values added up (a
    "category in each region" scatter showed 4 points at 125% to 275% margin instead of 16 at 30% to 70%; the accuracy
    reviewer flagged it); now one point per Details value in each Legend value, as Power BI. And the new card's reference
    labels (found by the review team in the
    release's real-Claude test: the UI/UX, story and accuracy reviewers each flagged a card reading "Latest Month Name:
    February 2026" with its second reference missing, a "must" the builder could not fix). `stock_visuals.js`
    cardVisual now takes a reference's own settings (`referenceLabelTitle` / `referenceLabelValue` with `for:
    "[Measure]"`) before the visual's, and with the label off the references start right under the value, so the
    second one fits: "Month: February 2026", "vs prior month: +8.3%", as Power BI draws it.
80. **Preview smoke check fixes** (every screen opened as an owner of the real-Claude test's organisation and as a colleague
    of the preview organisation, with a hook that reports any null handed to the page): Ask Relay's credit meter wrote
    "null" under a new question (`14-askd.js`: `replaceChildren` writes null as text); the Activity tab and the exported
    log name Relay Model and Relay where a step's text or output said Claude or Atlas (the kit's files and tool help;
    `07-tabs.js` `brandSay` on every step, `main.py` `_scrub` on exports; the runner's instruction files read as "its
    instructions"; `genbi`'s help no longer names the vendor). No script error and no other stray text on any screen.
81. **A mandatory, guided organisation setup** (the user, 2026-11-19: "make the intial configuration and business/org
    context mandate so the we can generate the intial understandinga and theme and kpi/metric standard and ontology and
    disctornaries ready and they can fine tune it, it must be a guided way"). An organisation's owners set it up once,
    step by step, before its first dashboard (`#/setup`, `webapp/static/js/47-setup.js`, `css/setup.css`): Your business
    (industry pack, what the business does, brands, regions, currency, fiscal calendar, audiences, priorities, naming
    conventions), Prepare (Relay Model drafts it in the background, free, up to 5 a day, or "use the industry standard as
    it is" by rules alone), Understanding, KPI standard, Ontology and dictionaries (keep or drop each proposal, accepted
    with `replace` so the adapted versions win), Theme (Branding), Check and finish. Until it is finished new dashboards,
    DAWB imports and new Semantic Review runs are refused (400; `orgsetup.require_setup` in `main._options` and
    `semreview`), with a notice in New dashboard and Semantic Review; organisations from before (a dashboard, or the old
    setup done with a brand) are not blocked. Server `webapp/app/orgsetup.py` (meta `org_profile`; routes under
    `/api/org/profile`; `/api/me` `org.setup`); the accepted understanding goes into every plan and build (ontology.json
    `organisation`, ontology.md "Your organisation", `genbi_kit/ontology.py`) and into Ask Relay's context
    (`askd.context_pack`). The tour sends a new organisation's main owner to the setup; the Organisation page has a
    Business context card. Built by three agents to one contract; tested offline (server 118 checks, screens 150
    assertions over 114 screenshots, release suite `tests/checks/item81_check.py` 71 checks against a stand-in);
    `d2d_checks.Person.ensure_setup` finishes a test organisation's setup without AI. NOT YET run against the real app
    on the test stack (next step), and `tour_ui_check` still expects the old brand step.
82. **Notifications show a person's own: the platform's notices only on the admin portal** (the user, 2026-11-19, on
    PASDACS's Notifications page full of other organisations' credit requests and the job runner's health: "only org or
    their task or their platform relation notification must be here not all"). Notices about the platform itself
    (another organisation's request or deletion, the job runner's and the PC helpers' health, a self-healing hold) are
    kind "platform" (`monitor.py`, `heal.py`; older ones are the ones that link into the admin portal: `#/requests`,
    `#/orgs`, `#/admin/`), and `notify.mine` shows them only on the admin portal, which shows nothing else; the public
    site shows the organisation's news, the person's own work and what PASDACS answered them. Users are per
    organisation, so these never reached a customer: they were in the wrong place for PASDACS's own people. Check:
    `tests/checks/item82_check.py`.
83. **Organisations only: personal workspaces are closed** (the user, 2026-11-19: "only orgnisations are allowed to sign in
    and perosnal will be blocked"; with payments coming back, below). A personal workspace (item 39: one free-mail
    address) gets no sign-in code (the answer looks like an unknown address's), a code is refused with "D2D Relay is for
    organisations: personal workspaces are closed. Sign in with your work address" (`otp.py` `_known`, `_account`,
    `PERSONAL_TEXT`), and a session of one signs nobody in on its next request (`auth.py` `personal_tenant` in
    `home_of`). Their data stays until PASDACS deletes them on the admin portal.
84. **One guided start in place of repeated New dashboard buttons** (the user, 2026-11-19, on the dashboards page: "so
    many time new dashboard and thing repeated rather than visual guide the user to start from a point"). Until the
    organisation's first dashboard is published, the page starts with a Start here journey: Set up your organisation,
    Start your first dashboard, Confirm the plan, Review the prototype, Publish; each step done, now or later (from the
    organisation's setup, item 81, and its latest dashboard's status) and one button, for the step it is on
    (`03-home.js` `homeJourney`, `css/app.css`). The empty list's button and the How it works card are gone, the
    header's New dashboard shows once there are dashboards, and the sidebar keeps only its button above the menu (the
    menu's own New dashboard item is gone, `02-shell.js`).
85. **Buying credits online comes back, next to requesting them** (the user, 2026-11-19: "add back payment as well, let
    both options be, either they can add credits or request credits as well"; and the trial goes to d2d.pasdacs.com
    itself, not demo.pasdacs.com). Item 59's removal undone from git HEAD cb63657: `payments.py` (HEAD's checkout,
    verify, webhook, billing, packs, currencies, waiting checkouts, admin settings and Check, plus today's `past()`; the
    webhook URL from `portal.site()`), `37-payments.js` (HEAD's screens plus `pastPayments`, one shared `paymentsCard`),
    the webhook's exemption in `auth.py`, `orgs.py` `me_info` "pay" and the out-of-credits message offering both
    ("Buy credits, or ask PASDACS for some (Request credits)" while selling is on), `contact.html`; the Organisation page,
    its menu and the Dashboards page's credits line offer Buy credits next to Request credits, the request dialog points
    to buying and `creditsDialog` buys when selling is on (`36-org.js`); payment pack cards scoped (`.packs .pack`, the
    ontology's industry cards share `.pack`); payment notices to PASDACS link `#/payments`, a platform link (item 82).
    Personal workspaces' buying cases are gone with them (item 83). Tests: `fake_razorpay.py`, `pay_check.py`,
    `pay_ui_check.py`, `rzp_real_*`, `rzp_stub.js` back from HEAD, the 8105 stand-in in `tests/stack`, both suites back
    in `run_all.sh`; `item59_check.py` and `sec_check.py` reworked for the rules; `upgrade_check.py` expects buying back.
    Not yet run on the stack. DEPLOY NOTE: live's `.env` still has the live Razorpay keys and selling was on, so buying
    goes live at once on deploy; PASDACS switches it off on the admin portal's Payments page if wanted; Razorpay's live
    webhook points at d2d.pasdacs.com.
86. **A view-only Visual gallery in the app** (the user, 2026-11-19: "can you add all approved custom visual as library to
    view only in the d2d site as well, so user can get an idea"). The Relay visual gallery (`custom_visuals/atlas/
    gallery.html`: every family of this release, tested and approved in item 69, drawn live on sample data with its
    variants and looks; nothing to download) is served again at `/gallery`, to signed-in people only (`edition.py`
    PAGES_OFF), and framed in the app at `#/visuals` ("Visual gallery" in the menu; `03-home.js` `renderVisualGallery`: `#/library` and
    `renderLibrary` are `05-library.js`'s, an organisation's own visuals;
    `02-shell.js`, `css/app.css` `.libframe`). Its one visible "Atlas" (the theme studio's help) now says Relay, in the
    gallery and its sources. `item30_check` expects it: not served signed out, served view only signed in. The six new
    families of the custom visuals session (branch `claude/relay-visuals-library-2fc3c5`, paused) join it once that
    branch finishes its re-reviews and is merged. Then (the user: "add filters as well to browse visual library and
    block download options"; "is it possible to add built in as well so they can view all?"): `/gallery` is served view
    only by `main.gallery` (built-in visuals included: 84 in all, 48 built-in in 12 categories, 36 custom in 7): a Browse
    bar (All visuals, Power BI's built-in visuals, Custom visuals; Every category or one; the count shown) above the
    first category, next to the gallery's own search; the theme studio's Copy theme JSON and its JSON box hidden; right
    click on a chart does nothing; typographic characters made plain (middle dots, dashes, arrows, bullets, ellipses;
    14 curly quotes stay, inside the page's script strings). The gallery has no `</head>`/`</body>`, so the additions go
    at the end of the page. Checked in Chromium: no script errors. Then (the user: "make it Relay Visual by PASDACS same,
    and suggest a logo as well"): it is "Relay Visual by PASDACS" in the menu, the page ("by PASDACS" over "Relay
    Visual"), the gallery's header and title (`custom_visuals/atlas/gallery.html`, `visual-atlas/gallery/src/shell.html`),
    with a suggested mark `webapp/static/relay-visual-mark.svg` in the D2D mark's family (the dark rounded square, white
    and #00C48C): three rising bars, the tallest green, and a green arc with a dot handing off to it (the relay). The
    user confirmed the logo ("yeah proceed with that logo").
87. **Other BI platforms shown as coming soon** (the user, 2026-11-19: "Visual Gallery is with power BI, but will be added
    other platform as well like tableau, qlik, metabase, looker as well as coming soon, and in D2D as well"). One row,
    `platformChips` (`03-home.js`, `css/app.css` `.platforms`): Power BI today (ticked), Tableau, Qlik, Metabase and Looker
    "Coming soon" (shown, never clickable), on the Dashboards page under its introduction ("Built for"), in New
    dashboard's Visuals step ("Built for", `04-new.js`) and above the Relay Visual gallery ("Visuals for"). Checked in
    Chromium, no script errors.
88. **Home, a cleaner Dashboards page, and the gallery's Browse bar pinned** (the user, 2026-11-19, on the gallery's
    Visualizations side panel and the Dashboards page: "this is not require and freeze the filter on the top and reset
    option as well and ease of navigations, dashboards can look more better as well and there should be a home page as
    well"). Home is the front page (`#/`, first in the menu; `03-home.js` `renderD2DHome`, not `renderHome`: RELAY's
    `19-home.js` has one): a greeting, the platforms, credits (Buy and Request), the Start here guide (moved from the
    Dashboards page; buttons "Set up now" / "Start now"), quick actions (New dashboard only once the guide is done),
    the latest dashboards as cards (`dashCard`, shared with the Dashboards page; item 57's "the start page lists the
    dashboards" still holds). The Dashboards page with none yet: one card, "Start your first dashboard" and "Go to
    Home". The gallery (`main.gallery`): the Visualizations side panel (`#pane`, with Get more visuals and the
    Build your own builder) and its header button are gone; the Browse bar is pinned under the gallery's header, takes
    the page's background in light and dark, has Reset (all visuals, every category, search cleared) and a category jumps
    to its section. Checked in Chromium: no script errors, plain characters. Then (the user: "start here should be initial configuration
    rather than building a dashboard, like org details, kpis, metrics, formula, about organisation, branding"): Start here
    is the organisation's one-time setup (item 81) in five steps: About your organisation, KPIs metrics and formulas,
    Business terms and dictionaries, Branding, Check and finish; each done, now or later from `/api/me` `org.setup.next`,
    the step on now opening that step of `#/setup` (owners) or saying an owner is setting it up (colleagues); gone once
    the setup is finished, when New dashboard joins Home's quick actions.
89. **Relay Visual inside the app, the tour as guides, DAWB, one Migration contact, single sign-on on request** (the
    user, 2026-11-19):
    - "relay visual instead on new tab and all, can you make it part of D2D itself": `#/visuals` is a D2D page
      (`03-home.js` `renderVisualGallery`): the logo, "Relay Visual", the platforms, and D2D's own toolbar pinned on top
      (search, kind, category, Flat/Soft/3D, Reset, the count) driving the framed gallery through its `d2dGallery` API
      (`main.gallery`: when framed, the gallery hides its own header, introduction and Browse bar and follows D2D's
      light or dark). No Open in a new tab. Then "dont need by pasdacs": it is "Relay Visual" everywhere (the page, the
      gallery's title and header in `custom_visuals/atlas/gallery.html` and `visual-atlas/gallery/src/shell.html`).
    - "have option to start tutorial or guide always above this": Take the tour (Step-by-step guides) sits above the
      foot of the menu (`02-shell.js`, `#tourlink`).
    - "take tour should explain all ... in a guide way ... quick actions like what they want to do", "like a callout
      background dim and focused on what to do with next/skip", "a full guide on how to build dashboard, kpi
      configuration, ask relay using, semantic review, ontology, relay visual": `38-tour.js` rewritten. The tour is a
      layer over the app (`#coach`): the screen dims, one part is lit (`.coach-hole`), and a callout beside it says what
      it is and what to do, with Next, Back and Skip the tour (arrow keys and Escape too; the keyboard stays in the
      callout). It opens with "What would you like to do?": six guides (Build a dashboard, Set up your KPIs, Ask Relay,
      Semantic Review, Ontology, Relay Visual) that open the pages and light each part in turn (New dashboard's six
      steps; the KPI standard in `#/setup`; Ask Relay's question box, scope, suggestions, tabs and history; Semantic
      Review's three steps and Reviews; the Ontology's cards; Relay Visual's toolbar and gallery), or Show me around:
      the 16 parts of D2D one at a time (the menu, New dashboard, credits, light or dark with its three choices, Take
      the tour). An owner whose organisation still needs its setup (item 81) is offered it first, and the walk ends
      there. On a phone the callout sits at the top or the foot, and the menu opens as a drawer. As before, it shows
      once on the front page to someone new (`/api/me/tour`); finished or skipped it does not show again, and Take the
      tour (menu foot, organisation menu) opens it any time. A finished setup goes to Dashboards, no longer back to the
      tour (`47-setup.js`).
    - "Like Migration D2D, have DAWB as well as coming soon and explanation of it and contact and in migration remove
      contact which is twice": Migration D2D keeps one contact, the Ready to move? card. DAWB (`#/dawb`,
      `39-migration.js` `renderDawb`, in the menu after Migration D2D with a Soon tag): the Data Analytics Work Bench,
      coming soon. The page says how it works (connect sources, agents do the work, people approve, it runs and hands
      each build to D2D at Confirm KPIs) and what it covers, and has one contact (an email to PASDACS).
    - "when anyone enter email and clicks login where they enter otp show below SSO of google and MS as well contact to
      enable and secure so they can bypass otp login": the sign-in page's code step shows Sign in with Google and Sign
      in with Microsoft, each marked Contact to enable. Each writes to info@pasdacs.com with the address's domain, and a
      line says why single sign-on is safer: no code, the organisation's own two-step sign-in, leavers shut out. Not on
      the admin portal. Sign-in itself is still by code only: single sign-on is not built.
    - Tests: `tour_ui_check.py` rewritten for the guides, 69 checks:
      - the welcome and its guides, and the walk lit part by part;
      - light and dark, Back, and the Ask Relay and Build guides;
      - the setup offered and reached, the tour not shown again, Take the tour and Escape;
      - Migration's one contact and its dialog, and DAWB;
      - a phone with the drawer, a member's Skip, and single sign-on on the code step.
      `item56_check.py` reads who is in the organisation from the tour's welcome; `item30_check.py` checks the gallery's
      title. Checked on the test stack with the working copy mounted: tour_ui 69/69, item56 62/62.
90. **Guides with sample pages; a new dashboard's credits taken in its steps** (the user, 2026-11-19: "instead showing
    the same screen can you prepare a sample screen and details of the same like prefilled, when the data is upload and
    next is clicked deducted the credits as non refundable as default built in visual and if customs visual is selected
    deduct additional credits"):
    - **Guides:** each guide (`38-tour.js`) first lights where the task starts in the app, then shows sample pages, filled
      in (`48-samples.js`). The sample is a grocer's monthly store dashboard, "Retail performance 2026". The pages:
      - New dashboard's six steps: four CSV files checked, what to build, the theme, the visuals, Check and start;
      - Confirm KPIs, then the prototype and the Power BI file;
      - the KPI standard;
      - an Ask Relay conversation;
      - a Semantic Review's findings;
      - the Ontology's industry pack and business terms.

      They are drawn on `#/welcome` under the tour (`renderTour`), read only, and marked "Sample: nothing here is
      saved or charged"; their prices come from the organisation's costs. Each guide ends on the real page.
    - **When credits are taken:**
      - Going on from Your data takes the dashboard's credits at the built-in visuals' price.
      - Going on from Visuals with custom visuals takes the difference.
      - Neither is refunded.
    - **One open draft per person** (`orgs.draft_pay`, tenant meta `newdash:<user id>`, GET and POST
      `/api/new-dashboard/credits`):
      - Going back and forth, or opening the page again, takes nothing more.
      - Starting uses the draft: nothing more is taken, or only the custom difference if custom visuals are first chosen
        at the start. The draft's charges move onto the dashboard.
      - The first run carries `kept`, so a failed plan keeps the credits (`worker.give_back`) and Retry is free.
      - A dashboard started by the API alone still pays at the start, as before.
    - **What the screens say before the click** (at the user's word, these screens say the credits are not refunded):
      - Your data: "Going on takes 25 credits ... They are not refunded. Custom visuals, if you choose them, take 25
        more."
      - Its Next button: "Next: What to build - 25 credits".
      - Visuals: built-in Included, custom +25, with the same note and on Next.
      - Check and start: "taken in the steps: starting uses no more".
    - **Tests:**
      - `item90_check.py` (new, in `run_all.sh`), 30 checks: the API, and the real steps in Chromium (back and forth,
        custom visuals, the page opened again).
      - `tour_ui_check.py`, 72 checks with the sample guides.

      Both pass on the test stack with the working copy mounted and no Claude. The tour's callout now re-places
      itself when it grows (a `ResizeObserver`), which fixes the last step sometimes sitting below the screen.
91. **status.pasdacs.com, and D2D back on d2d.pasdacs.com with admin.pasdacs.com** (the user, 2026-11-19: "looks good, go
    ahead, deploy and publish and commit, i need to configure the network tunnel as well, remove all container from the
    docker and have only this one running and admin.pasdacs.com as well and also build a status.pasdacs.com (if possible
    to be outside from this docker may be in cloudflare directly) as well do view all the status of the d2d application
    and services and alerts as well to info@pasdacs.com in case of any issues"):
    - **`GET /status.json`** (no sign-in; `auth.OPEN_PATHS`): each service up, down or not used:
      - the app and the database;
      - the AI engine and the job runner (asked over its socket);
      - the DAX checker, the Power BI file maker, and sign-in mail.

      It also gives how many alerts the monitor has open (counts only), server errors in the last 15 minutes, the
      version and the time. Nothing about anyone's work, data or organisation. `item91_check.py` (new, in
      `run_all.sh`) covers it. `tests/audit/routes-public.txt` is regenerated: it now has `/status.json` and item 90's
      `/api/new-dashboard/credits`.
    - **`status/`: the `pasdacs-status` Cloudflare Worker on status.pasdacs.com**, outside the PC (`status/README.md`):
      - Every three minutes it checks the site, its sign-in, the admin portal and `/status.json`.
      - It keeps the state and 90 days of uptime in KV (`d2d-status`).
      - It emails info@pasdacs.com through Microsoft Graph (the sign-in mail app, app-only) when something is down for
        two checks in a row, every 6 hours while it lasts, and when it is back.
    - **Docker on this PC:** every container but live D2D's was removed, on the user's word: the DAWB demo,
      family-vault, plinth and rfp-copilot (40 containers), then the test stack after the release run. Their volumes
      and images are kept.
    - **Live again, 2026-11-19 (IST)** (the user: "looks good, go ahead, deploy and publish and commit"):
      - **Tests:**
        - Release run on 9ac50a5: 1845 of 1851. Its misses: the tour's layer stayed over pages it did not open (fixed in
          434287e); item44 expected the old Visuals wording (test updated); item59's admin Payments screen check (open,
          as before).
        - Upgrade check from live's f754035 to bc64327: 30 of 30.
        - On 434287e: sec 117/117, item44 37/37, tour 72/72, pay_ui 37/37, item91 8/9 (the test read a header with the
          wrong case: fixed), gov_ui 10/11.
      - **Deploy:**
        - About 23:14: database dump `relay-db-20261119-174358.dump`, `RELAY_OTP_ON_SCREEN` taken out of the live `.env`,
          then web, admin and runner on bc64327.
        - About 23:22: 434287e. It is `latest`; bc64327 and f754035 are kept for going back.
      - **The tunnel:** the user deleted the old one and made a new one: its token is in `tunnel.env`, and its public
        hostnames are `d2d` to `web:8000` and `admin` to `admin:8000`. The corporate site's temporary Worker
        `pasdacs-d2d-page` was deleted (`wrangler delete -c wrangler.d2d.jsonc`), so d2d.pasdacs.com reaches the app
        again (about 23:20).
      - **admin.pasdacs.com:** the user's Cloudflare Access application `admin-pasdacs` (30-minute sessions), with
        `RELAY_ADMIN_ACCESS_TEAM` and `RELAY_ADMIN_ACCESS_AUD` read from Access's sign-in redirect into the live `.env`.
        The portal then asks for its own email code.
      - **status.pasdacs.com:** `pasdacs-status` deployed (KV `d2d-status`, cron `*/3`) with secrets `MS_TENANT`,
        `MS_CLIENT_ID`, `MS_CLIENT_SECRET` and `TEST_KEY`; one test alert sent to info@pasdacs.com.
      - **Docker:** only live D2D's five containers run.
      - **Still open:**
        - After Delete, the Dashboards list can still show the deleted dashboard until it refreshes (gov_ui_check).
        - item59's admin Payments screen check.
        - The user to confirm Razorpay's live webhook is on.
        - The trial organisation and its credits: the user makes them on the admin portal (the user, 2026-11-19).

92. **Organisations sign up again; the first person names theirs** (the user, 2026-11-19: "they will create on their own
    as sign up and then i get notification and i will handle credits", "whoever first signs in org, they will put the
    meta data of the organisation like name"; item 56's "nobody signs up" ends here, the rest of item 56 holds):
    - **Who signs up** (`otp._can_sign_up`): a work address whose domain no organisation has gets a code. The code makes
      the organisation (`orgs.create`, 0 credits, named from the domain) with that person as main owner.
    - **PASDACS is told** (`orgs.signed_up`): a starting-credits request (purpose start, 50, any number on approval)
      under the admin portal's Requests, an email to info@pasdacs.com, and a notification there.
    - **Who does not:**
      - Colleagues are still added by the owners: an address at a domain that has an organisation gets the usual answer
        and no code.
      - Free mail and throw-away addresses are told to use a work address (403; that says nothing about accounts).
      - `RELAY_SIGNUP=0` closes sign-up again.
    - **The first person names it:** the setup's first step (Your business) starts with Organisation name, prefilled
      from the domain, saved with `PATCH /api/org`. The sign-in page says how it works.
    - **Tests:** `item56_check.py` (70: the sign-up, Requests, the notification, approval with 30, the name in the setup,
      a colleague with no code, Gmail and throw-away told why), `sec_check.py` (117) and `upgrade_check.py` updated;
      item81 71/71, accounts 48/48, item60 41/41.

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

Updated 2026-11-16 09:30 IST, after items 44-53, the first real purchase, the crash of 2026-11-14 (the site down from
about 07:26 to 08:52 IST, "Overnight restarts" below) and the user's restart of 2026-11-16. **Live:** web, admin and
the job runner run `d2d-relay:b77f38e` (= latest, since 2026-11-15 15:48 IST, item 52, the three display bugs fixed; item 51 since
2026-11-14 17:51 IST, the sign-in code email in D2D's look; item 50
since 11:51, the admin Overview; item 49 since 11:25; items 44-48 since 11:09:
credits by visuals, the private queue without Stop, builds side by side, one model, and the user's rule for builds
that do not finish), with the Turnstile
bot check on and the AI on PASDACS's Anthropic API key first (Claude Opus 5.5), the Claude subscription as its backup
(item 42); the database container runs `d2d-relay:8689305`'s image and the tunnel `cloudflare/cloudflared:2026.11.0`
(item 53, since 2026-11-16 09:29 IST); live holds PASDACS and the first sign-ups of that
day, and sells credits online with the live
Razorpay keys (since 21:35 IST; the first real purchase at 00:04 IST; Cloudflare's Bot Fight Mode is off for the
whole pasdacs.com zone since about 02:38 IST, as it blocked Razorpay's webhook: "Selling credits online" below). This
folder, the deploy folder and **GitHub** carry this log entry: item 53 went live on the user's "Yes, update and
deploy" and was pushed on their "Yes, push"; item 52 went live on the user's "commit and deploy once
tests pass" and was pushed on their "Yes, push" (item 51 went live on "Yes, deploy" and was pushed on "Yes, push";
item 50 was pushed on "Yes, deploy when tests pass", item 49 on "close what all
you can do and pblish all live and update it", items 44-48 on "ok if all tested deploy and publish it"). **Going back**
to item 51 (`d2d-relay:8029415`, kept): in the deploy folder `git reset --keep 1a2638f`, `docker tag
d2d-relay:8029415 d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner` (the prototype's matrix
adds up ratios again, the multi-row card's text runs together, Ask Relay shows 0.845). **Going back** to item 50 (`d2d-relay:22c7464`, kept): in the deploy folder `git reset --keep 2c3fdf5`, `docker
tag d2d-relay:22c7464 d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner` (the plain sign-in code
email again). **Going back** to item 49 (`d2d-relay:1c841da`, kept): in the deploy folder `git reset --keep
318e248`, `docker tag d2d-relay:1c841da d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner` (no
Overview). **Going back** to items 44-48 (`d2d-relay:777f30c`, kept): in the deploy folder `git reset --keep c410d9d`, `docker tag
d2d-relay:777f30c d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner` (only the runner's tidy
differs). **Going back** to item 43 (`d2d-relay:a871751`, kept): in the deploy folder `git reset --keep
c948af2` (it takes `config/models.json` back too), `docker tag d2d-relay:a871751 d2d-relay:latest`, then `docker
compose up -d --no-deps web admin runner` (one build at a time again, one price for every dashboard).
**Going back** to item 42 (`d2d-relay:01559b6`, kept): the same with `git reset --keep 13c387a`.
**Going back** to item 41 (`d2d-relay:baf70e5`, kept): in the deploy folder `git reset
--keep d63c052`, `docker tag d2d-relay:baf70e5 d2d-relay:latest`, then `docker compose up -d --no-deps web admin
runner` (older code ignores `RELAY_ANTHROPIC_API_KEY`: every run on the subscription again). **Going back** to item 41
as first deployed (`d2d-relay:2686fc4`, kept): the same with `docker tag d2d-relay:2686fc4 d2d-relay:latest` (only
the small print's wrapping differs from `baf70e5`).
**Going back** to item 40 (`d2d-relay:d1882f7`, kept): in the deploy
folder `git reset --keep 93e2a8a`, `docker tag d2d-relay:d1882f7 d2d-relay:latest`, then `docker compose up -d
--no-deps web admin runner`. **Going back** to item 39 (`d2d-relay:96ea48a`,
kept): in the deploy folder `git reset --keep 5fbd0a7`, `docker tag d2d-relay:96ea48a d2d-relay:latest`, then
`docker compose up -d --no-deps web admin runner` (the Turnstile lines in the `.env` are then ignored). **Going back**
to item 38 (`d2d-relay:189ccac`, kept): in the deploy folder `git reset --keep c8d0f0f`,
`docker tag d2d-relay:189ccac d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner`; the
`personal` column stays (older code ignores it), but older code refuses free mail at sign-in, so anyone with a
personal workspace is locked out until item 39 is back. **Going back** to item 37
(`d2d-relay:334b493`, kept): in the deploy folder `git reset --keep df65429`, `docker tag d2d-relay:334b493
d2d-relay:latest`, then `docker compose up -d --no-deps web admin runner`; to item 36 (`d2d-relay:53fb6ad`, kept)
the same with `cec5ed2`; to item 35 (`d2d-relay:e05f035`, kept) with `8bbfd7e`; to item 34 (`d2d-relay:aa4531e`,
kept) with `520e88e`; to item 33 (`d2d-relay:54f6ed7`, kept) with `2cd493e` (it takes `config/house-models.json`
back too). No older release
image is kept on this PC (item 33): any other version is a commit on
GitHub (in the deploy folder: `git checkout <sha>`, `RELAY_COMMIT=<sha> docker compose build web`), then `docker
compose up -d --no-deps web admin runner` (only `web admin` for a version before item 31); going back before item 31
also takes the deploy folder to `7ecd8b4` first (`git reset --keep 7ecd8b4`) and `docker rm -f d2d-relay-runner` after.

### Waiting for the next deploy (items 59 to 68 and 73, 2026-11-19)

The release goes to the live install on this PC (now `d2d-relay:f754035`, item 58, with `RELAY_OTP_ON_SCREEN=1` and the
tunnel stopped) and opens it for a client trial at https://demo.pasdacs.com, through the Cloudflare tunnel, with the
sign-in code by email. Never restart live without the user. The steps known so far, in order:

1. **Before it:** the release committed (only its own files and hunks: other sessions share the work folder), the
   in-progress work finished or left out, the release suites run on the candidate image, live idle, and the database
   dumped (`relay-ctl db-dump`, as for item 58).
2. **The live `.env`** (the deploy folder's): delete `RELAY_OTP_ON_SCREEN` before the tunnel starts (item 57: never
   with a tunnel or port forwarding; from then on the admin portal on this PC asks for the emailed code too); set
   `RELAY_PUBLIC_URL=https://demo.pasdacs.com` (the address in every email from both sites: `docker-compose.yml` gives
   the admin portal the same address as `RELAY_SITE_URL`); the Razorpay keys are no longer read (item 59) and can be
   removed. `RELAY_ANTHROPIC_API_KEY` stays, as the backup now (item 67).
3. **Cloudflare (the user):** in the d2d-relay tunnel, the public hostname `demo`, domain `pasdacs.com`, service HTTP,
   URL `d2d-relay:8000` (the web container). Also, found while writing this: the Turnstile widget was made for
   `d2d.pasdacs.com` (item 40), so add `demo.pasdacs.com` to its hostnames, or the bot check fails on the new address
   and nobody gets a code. d2d.pasdacs.com stays the static page (item 54).
4. **The deploy folder:** fast-forward to the release commit. `config/house-models.json` now has `relay-review` (item
   68) and is read from the deploy folder (`./config`, mounted read only); `docker-compose.yml` gives the admin portal
   `RELAY_SITE_URL`. Both come with the fast-forward, and `docker compose up -d` recreates admin for the second. The new
   table and columns (`relay.tn_org_domains`, `onto_terms` in each workspace, `semreview_runs.fixes`) are made at
   start: nothing by hand.
5. **Start:** the image built from the clean commit, `docker compose up -d`, then
   `docker compose --profile tunnel up -d`, with both PC helpers running. Check: healthz on both sites, the AI engine's
   Claude login (it answers first now, item 67), https://demo.pasdacs.com's sign-in page with its bot check, and a code
   email naming demo.pasdacs.com.
6. **The trial organisation**, on the admin portal on this PC (http://127.0.0.1:8102), **New organisation**: its name,
   its main owner's work address and name, **Other email domains** with its second domain, **Starting credits** 300,
   **Industry** Grocery and retail. The main owner is emailed, with https://demo.pasdacs.com in the invitation.
7. **Optional (the user):** switch Razorpay's live webhook off in the Razorpay Dashboard; nothing calls it.

Open points found while writing the docs (items 64, 65 and 68 above): a sampled dashboard's .pbix is refreshed with every
row; "Review again" does not check a fixed model; the reviewers get no shell, their lane's setting does not reach the AI
engine, and a full review lane refuses rather than queues.

**Going back** to item 58: `docker tag d2d-relay:f754035 d2d-relay:latest`, `git reset --keep` in the deploy folder to
its commit before the release (that takes `config/house-models.json` and `docker-compose.yml` back too), then
`docker compose up -d`. The new table and columns stay; older code ignores them. Older code sells credits again while
the live Razorpay keys are in `.env` and Sell credits online is on: remove the keys first. `RELAY_OTP_ON_SCREEN=1` goes
back only with the tunnel stopped.

### Before the public launch (the user)

- **The Power BI file maker stopped once (2026-11-13): running again.** Its process ended at 10:13 IST with no error
  in its heartbeat (its queue was empty; the DAX checker kept running), and the watchdog raised `pbix_offline` at
  10:24 IST; its email may not have arrived (the mail outage below). Restarted at 10:56 IST on the user's "Start it
  for me" (`pbix\start-pbix.cmd` through `Invoke-CimMethod Win32_Process Create`; Claude Code's auto mode had refused
  it before that word, "Modify Shared Resources"): heartbeat fresh, idle, no error, and live's watchdog logged
  `pbix_offline` resolved at 10:56 IST (32 minutes). The cause is unknown. If it stops
  again, check `data\projects\.pbix\heartbeat.json` in the deploy folder and start `pbix\start-pbix.cmd`.
- **Sign-in mail failed during Microsoft's outage (2026-11-13): working again.** Microsoft Graph refused the last code
  asked for (09:49 IST, on the admin portal) with 502 "UnknownError" after 21 seconds. The mailbox's own sign-in still
  worked, so the fault was Microsoft's. The public site logged no failed sign-in. The watchdog's alerts are sent the
  same way, so the ones raised during the outage may not have arrived. At 20:02 IST, on the user's "Yes, send it",
  `python -m app.otp_mail test` emailed info@pasdacs.com in about a second, with nothing in the logs after it. If
  codes fail again, look for MailError in `docker logs d2d-relay-web` and `d2d-relay-admin`. A Graph 5xx while the
  token still works is Microsoft's and clears by itself; a refused token means the mailbox signs in again (`python -m
  app.otp_mail login`). `otp_mail status` only checks the token (it passed during the outage too); `otp_mail test`
  proves mail goes out. Sign-in stays email code only (Decided, below).
- **The first trial organisation (2026-11-13)** has not signed in yet. When its first person signs in and names the
  organisation, its starting-credit request waits for PASDACS: approve it on the admin portal's Requests, or ask
  Claude to run `python -m app.orgs approve <request id>`. The trial guide (PowerPoint and PDF) is outside git, in
  `Downloads\D2D Trial Guide`.
- **The AI's Claude plan** (audit P1): **mitigated since item 42 (2026-11-13, 23:49 IST).** Runs go to Anthropic with
  PASDACS's API key (commercial terms: not used for training, a data processing addendum). The AI engine's Claude
  subscription ("Ultra", no team seat, which Anthropic treats as a consumer plan) is now only the backup: it answers a
  run only when the key fails (refused, out of credit, rate-limited, Anthropic down), and each such run leaves an
  `ai.fallback` record. On it, customers' data may be used to train models if the account's "Help improve Claude"
  setting is on (then kept up to 5 years; otherwise 30 days). **That setting is off since 2026-11-12 (the user).**
  The key has a monthly spend limit of $150 in the Anthropic Console (the user, 2026-11-14; the API bills per token,
  `docs/d2d-relay.md`, "The AI's login and effort", until item 67 "The AI's Claude account"). A Team or Enterprise plan
  would put the backup under commercial terms too. The privacy notice says Anthropic handles the data, and nothing
  about training. **Item 67 (2026-11-19, not deployed yet) turns this round:** the subscription answers first and the
  key is the backup, so once it is live every run goes through the subscription's plan again, with the setting above
  keeping training off; `RELAY_AI_PRIMARY=api` keeps the key first.
- **Terms and policies** (P2, P4): published on 2026-11-12 (item 30): terms of service, refund and cancellation
  (none), contact. **The lawyer has reviewed them** (the user, 2026-11-14), and the contact page gives PASDACS's
  address as "Bangalore, India" since item 43 (no phone number, the user's choice). The terms changed later that day
  (item 48: one sentence removed): the user may show the lawyer. Still: a signed data processing agreement when a
  customer asks.
- **The PC** (P3): BitLocker is skipped for now (the user, 2026-11-12). The nightly backup (02:30 IST) is on the
  same disk as the data: keep an encrypted copy somewhere else. (Every older backup was deleted on 2026-11-12, on the
  user's word.)
- **Overnight restarts:** the user handles them (2026-11-12). (The PC restarted at 02:38 IST that day and the live
  site was down until ~09:17 IST: Docker Desktop starts only when someone signs in to Windows.) **2026-11-14: the PC
  crashed** with a blue screen (stop code 0x154, UNEXPECTED_STORE_EXCEPTION; Windows logged an unexpected shutdown)
  at about 07:26 IST (the helpers' last heartbeats; Windows' own last record says 07:08) and started again at 08:51;
  the containers came back at 08:52 (Docker Desktop starts at sign-in; the database cleared the lock file the crash
  left), so the live site was down for about an hour and a half. The crash left both helpers' heartbeat files full of
  zero bytes; Claude started both at 08:58 IST on the user's "Start them for me" (heartbeats fresh and idle, no
  watchdog alert, no errors). Checked the same morning: the four SSDs report healthy, Windows logged no disk errors
  in 14 days, and every drive has room; Windows could not write a crash dump (volmgr 161), so the cause is unknown
  (the one earlier unexpected shutdown, 2026-10-29 13:55, had no stop code: a power cut or a forced reset). If 0x154
  comes back: update the SSDs' firmware with Samsung Magician (it also shows the health data that needs admin) and
  run Windows Memory Diagnostic. **2026-11-16:** the user restarted the PC from the Start menu at 08:57 IST and
  everything came back on its own (the containers at 09:03, both helpers from their Startup-folder shortcuts at 09:01;
  the site down about 5 minutes), so a planned restart needs nothing by hand; only the tunnel came back with 3 of its
  4 connections, fixed by item 53.
- **The two PC helpers start by themselves since 2026-11-14:** on the user's "Yes, add them", Claude put shortcuts to
  `daxcheck\start-daxcheck.cmd` and `pbix\start-pbix.cmd` in the user's Startup folder ("D2D Relay DAX checker" and
  "D2D Relay Power BI file maker", minimised; `docs/d2d-relay.md`, "After the PC restarts"), so both start at sign-in.
  Someone still has to sign in after a restart (Docker Desktop and the helpers start then); the watchdog warns
  PASDACS after 10 minutes without either.
- **The admin portal stays on this PC until revenue reaches ₹2 lakh** (the user, 2026-11-14): http://127.0.0.1:8102.
  Then, to reach it through the internet: two steps in Cloudflare (an Access application, then the public hostname
  admin-d2d.pasdacs.com; `docs/d2d-relay.md`, "Admin portal") and the team name and AUD tag in `.env` (optionally
  `RELAY_ADMIN_EMAILS`).
- **The old address** d2d-relay.pasdacs.com: done. The user removed its public hostname in Cloudflare; the name no
  longer resolves (checked 2026-11-12, ~13:30 IST). https://d2d.pasdacs.com is the only address.
- **Social media and ads** (item 38's check, 2026-11-12; item 39, 2026-11-13). Overtaken by items 54 and 56: the app
  is off the public site and nobody signs up any more (PASDACS creates each licensed organisation); the rest of this
  point is how it stood before. Since item 39 anyone can sign up: a
  work email joins its company's organisation (whose starting credits wait for PASDACS's review), a personal address
  (Gmail, Outlook, Yahoo ...) gets a personal workspace that buys its credits; throw-away inboxes stay refused.
  pasdacs.com and the social pack say so since the same evening; nothing has been posted yet (the user, 2026-11-13),
  so nothing published needs changing. New organisations wait for PASDACS's review, and the
  admin portal works only on this PC until the Cloudflare Access step above. Neither site counts visitors (D2D
  Relay's privacy notice promises no tracking cookies): use UTM-tagged links and the ad platforms' own counts, and
  change the notice before adding any pixel or tag. LinkedIn and Meta lead-form ads ask for a privacy policy link;
  pasdacs.com has had none since 2026-11-06. Ads running overnight pay for clicks while a restart has the site down.

### Selling credits online (done on 2026-11-13: live keys, both websites verified, selling on; steps below)

Buying credits online is off on live since 2026-11-12 (the user: "from the live site remove buy credits for now as its
in test, allow only request credits, once razorpay is activated we can allow production to buy credits"): the Razorpay
test keys are parked as comments in the live `.env` (with a note there), so payments are "off" and everyone, PASDACS
included, sees Request credits only; the webhook secret stays, so the webhook still answers. Going live:

1. The live keys (rzp_live_...) into the live `.env` (the deploy folder's) in place of the parked test keys: the
   lines `# RELAY_RAZORPAY_KEY_ID=...` and `# RELAY_RAZORPAY_KEY_SECRET=...` become `RELAY_RAZORPAY_KEY_ID=rzp_live_...`
   and `RELAY_RAZORPAY_KEY_SECRET=...` (no `# `, no quotes or spaces). `RELAY_RAZORPAY_WEBHOOK_SECRET` stays as it is.
2. A live-mode webhook in the Razorpay Dashboard: URL https://d2d.pasdacs.com/api/payments/webhook, events
   payment.captured, order.paid, payment.failed and refund.processed, its secret as `RELAY_RAZORPAY_WEBHOOK_SECRET`.
3. Restart web and admin so they read the `.env` again: `docker compose up -d --no-deps --force-recreate web admin`
   in the deploy folder (`docker compose restart` keeps the old values; the job runner does not read the keys).
4. On the admin portal, Payments: PASDACS's invoice details (legal name, registered address, state, PIN and GSTIN; the
   SAC code from the accountant, the setting suggests 998314; the LUT's ARN if one is filed for 2026-27, else dollar
   sales carry IGST, included in the price), and GST 18% added on top (the user's decision of 2026-11-11, "₹100 + 18%
   GST": 25 credits ₹2,500 + ₹450 GST = ₹2,950; dollar prices abroad unchanged). Live keys cannot sell before the
   invoice details are complete. Then switch Sell credits online on. **The LUT** (the user, 2026-11-13): filed once
   revenue passes about ₹2 lakh; until then dollar sales carry IGST inside the price. Then add its ARN on Payments.
5. For buyers abroad: International payments in the Razorpay Dashboard (Account & Settings; Razorpay reviews it).
   Until then only Indian cards go through, though people abroad see dollar prices ($1 a credit; ₹100 in India).
6. Razorpay takes live payments only from websites registered on the account: **done on 2026-11-13.**
   https://pasdacs.com is approved, and https://d2d.pasdacs.com, where the checkout opens, was verified the same
   evening (the user added it under Account & Settings, Business website detail; Razorpay's form asks how a reviewer
   signs in: with their own work email and the emailed code, as anyone does). API keys belong to the account, not to
   a website, so the live keys already in use cover it: checked afterwards, Razorpay accepts them (HTTP 200).
   Regenerating keys would expire the ones in use (as the test keys did on 2026-11-13).

2026-11-13: the user regenerated the test keys (the same Razorpay account, so the test keys parked in the live `.env`
no longer work; harmless while parked), and Razorpay's real test mode was checked again on a test stack running live's
image `d2d-relay:189ccac`: `rzp_real_check.py` 18 of 18, and `rzp_real_ui.py pay` paid ₹1,178.82 with Razorpay's
test Visa (`pay_TzhhKsntjyR2sT`, captured; 100 credits and a GST invoice). Two test fixes came with it: an order's
`workspace` note is `pasdacs` (`db.PLATFORM`), not `platform`; and Razorpay's checkout now asks "Save your card as per
RBI guidelines?" after Continue, which `rzp_real_ui.py` answers with Maybe later. The test keys are in git-ignored
`tests/stack/.env.real`.

**Live keys since 2026-11-13 20:55 IST (steps 1 to 3 done).** The user typed the live keys into the live `.env` and
added the live-mode webhook in Razorpay; the `# ` left on both key lines was taken off (every other line checked
unchanged; the old "Parked" note replaced), Razorpay accepted the pair (a read-only look-up, HTTP 200), and web and
admin were recreated after the user's "Yes, deploy now" (live idle; down about 9 seconds; the image unchanged,
`d2d-relay:189ccac`). Checked on live: payments mode `live` in web and admin, the webhook answers an unsigned call with
400 "The signature does not match." through Cloudflare, healthz and the sign-in page 200, no errors. Nobody could buy
yet: Sell credits online was off, GST 0 and PASDACS's invoice details empty. Going back: put `# ` before the two key
lines in the live `.env` and recreate web and admin the same way (payments go "off").

**Selling online since 2026-11-13 21:35 IST (step 4 done).** The user signed in to the admin portal in the app's
browser and Claude filled in Payments from PASDACS's GST registration certificate (REG-06, sent by the user): the legal
name, the principal place of business, Karnataka (from the GSTIN), the PIN and the GSTIN; SAC 998314 (the portal's
suggestion; **confirmed by the user the same night**); invoices `D2D/26-27/00001`
on. GST 18% added on top: 25 credits ₹2,950, 50 ₹5,900, 100 ₹11,800, 250 ₹29,500, 500 ₹59,000; abroad $25 to $500.
The packs and "owners can buy" are unchanged. Saved at 21:34 with selling off, then switched on at 21:35 after the
user's "Switch it on". No LUT for 2026-27 yet (the user files it later, "its ok for dollar"): until its ARN is set,
dollar sales carry IGST inside the dollar price. Checked on live: mode `live`, selling on, nothing missing for
invoices, PASDACS's own organisation offered real payments, healthz 200, no errors. Switching off: untick Sell
credits online on the admin portal and save.

**The first real purchase: 2026-11-14, 00:04 IST** (the user, from PASDACS's own workspace): 25 credits, ₹2,950 by
UPI. The checkout confirmed it at once: credits added (PASDACS 75), invoice `D2D/26-27/00001` (₹2,500 + CGST 9%
₹225 + SGST 9% ₹225, place of supply Karnataka, SAC 998314), no mail error. It is a real tax invoice in the series:
the user told the accountant it was PASDACS's own test purchase (2026-11-14). **Razorpay's webhook was blocked at
first:** the site
logs every POST, and none came to `/api/payments/webhook` after the payment. The payment did not need it; it is the
safety net for a buyer who closes the tab after paying (then the credits come when someone in that organisation next
opens Organisation or Buy credits, for 2 days, or when the admin portal's Payments looks the checkout up), and the
only way a refund made on the Razorpay Dashboard is recorded. The webhook's settings were right (Live mode, the URL
exactly https://d2d.pasdacs.com/api/payments/webhook, enabled, the four events) and a call signed with the live
secret got 200 through Cloudflare from the PC. The cause was Cloudflare's **Bot Fight Mode**, which challenges
automated calls from cloud servers such as Razorpay's: the user saw it stopping the webhook in Cloudflare's security
events (Security, Analytics, Events). It cannot be skipped for one path by WAF or page rules, so the user turned it
**off** by 02:38 IST (a setting for the whole pasdacs.com zone; sign-in keeps its Turnstile check). Checked at 02:55
IST: two calls from Razorpay arrived, its retry of the payment's two events (no other payment was made), and both got
200 (so the secret in Razorpay matches the live `.env`); no credits were added twice (one credit entry that night,
PASDACS still 75). A test checkout started at 02:41 was left before any payment and stays unpaid. Before Bot Fight
Mode is turned back on, add IP Access rules (Allow) for Razorpay's webhook addresses, which it then leaves alone
(Razorpay's docs list them; in November 2026: 52.66.75.174, 52.66.76.63, 52.66.151.218, 35.154.217.40, 35.154.22.73,
35.154.143.15, 13.126.199.247, 13.126.238.192, 13.232.194.134, 18.96.225.0/26 and 18.99.161.0/26). Razorpay retries
a refused call for 24 hours, then disables the webhook and mails its alert address; its delivery log (Accounts &
Settings, Webhooks) keeps 3 hours.

**Dollars, checked in Razorpay's test mode the same night** (no money): a test stack on the live image
`d2d-relay:01559b6` with the user's test keys (`tests/stack/.env.real`, still valid): `rzp_real_check.py` 18 of 18,
then `rzp_real_ui.py pay-usd`: a buyer billed in the United States paid $100 in Razorpay's own checkout with its
international test Visa; 100 credits added, export invoice issued (the stack's seller has a LUT; live has none, and
that case, 18% IGST inside the dollar price, is in `pay_check.py` on every release). A real dollar payment on live
needs a buyer whom Cloudflare places outside India (or a VPN), billed outside India, with a card issued outside India
(an Indian card does not test it: Razorpay's international payments are for cards from abroad); the smallest pack is
$25, a real export sale.

**Step 5 was already done:** the user's Razorpay page (Account & Settings, International payments) shows international
cards enabled and active on the payment gateway (up to ₹5,00,000 a payment, settled T+0; non-3D Secure cards not
requested, so such cards are declined). A live order in US dollars is accepted: one $25 order made to check it
(`order_TzijB63N8cG4pa`, receipt `d2d-usd-check`, never paid) on 2026-11-13. Later that evening the user shortened the
invoice address to the district alone (saved 21:37); as GST invoices (rule 46) ask for the supplier's address, the
full address from the GST registration went back at 21:41 on the user's "Restore full address" (no payment in between,
so every invoice carries it).

Refunds: none (item 25); any made by hand on Razorpay are recorded.

### Engineering still open (details in the audit)

Done on 2026-11-12 (item 30): S10, S11, S15, S16, S17, P6, the AI engine's API (S4) and its network (S6). Left:

- **Found while documenting the release of 2026-11-19** (details in items 64, 65 and 68): `pbix.py` hands the Power BI
  file maker the full `data` folder, so a dashboard built on a sample gets a .pbix refreshed with every row; the
  Semantic Review Fixes tab's "save and Review again" re-reads the kept models, not the fixed one; the reviewers'
  `Bash(genbi:*)` is dropped by the AI engine (`_tool_args`), `D2D_REVIEW_PARALLEL` is not passed to the AI engine
  (`relay_init.AGENT_PASS`), and a full review lane answers 409, which shows as a reviewer that could not run. Also in
  the code, not the docs: the admin portal's domain fields show a real company's domain as their example
  (`36-org.js`, "Other email domains" and "Add a domain"); this repository is public.
- **Semantic Review's `.pbix` reader** (item 55): PBIXRay's native XPress9 code reads uploaded files in a process of its
  own with memory, time and file limits and an empty environment, but as the web app's user inside the web container
  (its files, its network). Next: run it as a job of the job runner (a container with no network that holds only the
  upload), as the AI builds are.
- **S4, the rest:** each build now runs in a container of its own (item 31); the Claude sign-in volume, with its run
  transcripts, is still shared by the jobs. A long-lived token (`claude setup-token`, the user's, once) would let each
  job run without the shared sign-in.
- **S6, the rest:** the web app's own connections are not limited: the user's decision of 2026-11-12, to review later.
- **A removed person cannot come back on their own** (item 32): their address is blocked until an owner unblocks it.
- **Abuse:** Turnstile on "Send code" (S7, S13): done in item 40 (2026-11-13, live with the user's keys), after the user
  had chosen not now on 2026-11-12. New organisations wait for PASDACS's review of their starting credits (item 27),
  and PASDACS gets an email for every sign-in (item 21).
- **Never run on the test stacks:** a real Razorpay checkout and real email delivery (Razorpay's real test mode is
  checked by hand with `rzp_real_check.py` and `rzp_real_ui.py`: last on 2026-11-13). Since item 34 the end-to-end
  run covers real Claude, Power BI's engine (the DAX check) and the Power BI file maker, on the test stack's own copies
  of this PC's helpers (`tests/stack/helpers.ps1`).
- **pay_check's race with the test stack's own start-up sweep** (item 38, test only): **fixed on 2026-11-14.**
  `ops.nightly` backs up and sweeps about a minute after the stack starts, which is when pay_check backdates a
  checkout and sweeps it; the check now adds up what every sweep since the backdating removed (their
  `retention.sweep` audit rows), so it passes whichever sweep comes first. Forced on a test stack of `01559b6`: the
  old check fails, the new one passes; pay_check 114 of 114.
- **The job runner's start-up sweep** (found while moving the release tests into `tests/`, 2026-11-12) is fixed in
  item 34, live since 17:05 IST: each runner removes only its own stack's jobs. A test stack from an image before
  item 34 (`upgrade_check.py` starts one) would still remove live's, so `tests/stack/stack.sh` refuses to start while
  any job container exists and warns if its runner removed one.
- **The release test suite is in `tests/`** since 2026-11-12 (on GitHub; nothing in the image
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
- **Three display bugs found by a real build (2026-11-15; fixed as item 52 above, live since 15:48 IST):** seen while taking screens for the marketing
  kit on the test stack (`d2d-relay:8029415`, review on, real Claude; a made-up organisation, "Sample Retail", with
  `samples/sales.csv` and `samples/products.csv`, Power BI's built-in visuals). The dashboard's folder (definition,
  prototype, versions, .pbix) is kept on this PC in `marketing/demo/sales-performance-64a3/`, its screens in
  `marketing/screens/` (`proto/p1.png`, `proto/p2.png`, `proto/p3.png`, `ask/05-answer-more.png`); `marketing/` is
  not in git. The kit keeps all three out of its images and videos.
  1. **The prototype's matrix adds up ratios.** `matrix()` in `genbi_kit/assets/stock_visuals.js` uses only the first
     `Rows` field, so a stepped matrix (Rows `Sales[Category]`, `Sales[Product]`) shows only its top level, and every
     cell is the sum of the detail rows, ratio measures included (only the Total row leaves non-additive measures
     blank). "Product scorecard against target" showed Electronics at a 100.3% profit margin and a 102% target margin
     (Office 98.9% and 120%); "Scorecard by region and city" showed its region rows the same way. Power BI's own matrix
     computes each measure per row, so the .pbix should be right (not opened to check), but the prototype people
     approve is wrong, and the review gates passed it (11 passed, custom visuals skipped).
  2. **A multi-row card cuts long text values.** `multiRowCard()` in the same file puts the values side by side and
     shortens each with `fit()` at an assumed size, so the Overview's "Key insights" (`pbi.multiRowCard` with three
     sentence measures) showed each sentence cut mid-word and running into the next. The same build's Relay-visuals
     version drew its insights properly.
  3. **Ask Relay's numbers and plurals.** In `webapp/static/js/14-askd.js` a value under 1 is shown as a plain
     decimal (line 18), so a growth rate read 0.845 for 84.5% and its average "Growth Pct avg 0.096", although `RATIO`
     (line 9) already recognises such columns; and the row count adds an "s" (line 118): "8 citys".
  Fix as one item, with checks in `tests/checks/`: a stepped matrix with a ratio measure, a multi-row card of long
  sentences, and an Ask Relay answer with a percentage column on a "city" axis.

### Decided (nothing to do)

- **Sign-in stays email code only** (the user, 2026-11-13, during Microsoft's mail outage: "ignore it we will not
  break the flow"): no one-time sign-in link or other way round the emailed code. **No password sign-in either** (the
  user, 2026-11-13 night: "password sign in not required remove it"; the idea came up when Razorpay's website check
  asked for a test login, and Razorpay verified the site without one).
- **The user's answers of 2026-11-12:** no refunds and no cancellations; disputes at the courts of Bengaluru,
  Karnataka; BitLocker skipped for now; overnight restarts handled by the user; no bot check on sign-in for now (item
  40 added one on 2026-11-13, once anyone could sign up);
  owners see every dashboard with who made it (S8); deleting is immediate, after a warning (P5); the web app's
  outbound traffic is not limited for now (S6).

- **The mailbox stays as it is** (the user, 2026-11-14: "mailbox restriction ignore it"): the mail app keeps sending
  app-only, which Microsoft lets it do as any mailbox of the tenant; no RBAC for Applications limit to info@pasdacs.com
  (`docs/d2d-relay.md`, "Limit the mail app to info@pasdacs.com", if that changes) and no retention tag on the folder
  of sign-in alerts and review emails.
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
