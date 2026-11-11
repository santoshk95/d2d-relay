# D2D Relay: work log and hand-over

Last updated: 2026-11-11 (IST). This file says where the project stands for anyone who clones it.

## What D2D Relay is

D2D Relay is a separate product cut from RELAY by PASDACS (copied from Relay commit 8f3d9a0) for a client who wanted
Power BI dashboard generation from CSV files and Google BigQuery. It has its own repository, image, container, data and
sign-in. The setup guide is `docs/d2d-relay.md`.

- Live at https://d2d-relay.pasdacs.com, served through a Cloudflare tunnel (container `d2d-relay-tunnel`, token in the
  git-ignored `tunnel.env`). On the host PC it is http://127.0.0.1:8100.
- One container, `d2d-relay` (image `d2d-relay:latest`, volume `d2d-relay-data`, projects in `./data/projects`). It
  shares the Claude sign-in volume `claude-api-auth` with RELAY.
- Its own DAX checker runs on the host: `daxcheck\start-daxcheck.cmd`, with the queue `data\projects\.daxcheck`.
- Deploy: `docker compose build` (with `RELAY_COMMIT=<sha>`), then `docker compose --profile tunnel up -d`.

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

Test data in the live install: the dashboards "D2D smoke test" and "Brand palette test". A user uploaded their own logo
(JPEG) on Branding but has not picked a palette yet; leave it.

## How items 9-10 were checked (2026-11-10)

Not deployed yet: the live container still runs commit 3a23b25 until someone redeploys.

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

## TEMPORARY: test login (delete when testing is done)

Added on 2026-11-10 at the user's request, to test organisations without real mailboxes. It is off unless
`RELAY_TEST_LOGIN=1` is in `.env`. When on, it works only on this PC (http://127.0.0.1:8100): a request through the
Cloudflare tunnel always carries `cf-connecting-ip` and still needs the emailed code.

- With it on, no code is emailed (so test addresses at made-up domains get no mail). The sign-in page fills the code
  in, the per-address and per-network limits are skipped, and every use is in the platform audit as
  `auth.test_login`.
- `/login.html?as=name@company.com` signs in as that address in one step, including "Create your organisation"
  for a new domain. Public domains are still refused.
- **To delete it:** `git revert` the commit "D2D Relay: TEMPORARY test login …" (it holds the test login and this
  section only), then remove `RELAY_TEST_LOGIN` from `.env`.
  - By hand instead: in `webapp/app/otp.py`, delete the "TEMPORARY TEST LOGIN" block (`TEST_LOGIN`, `_test_login`),
    the two "TEMPORARY" parts of `start()` and `test_login_state()`.
  - In `webapp/static/login.html`, delete the `.test` styles, the `testbanner` div, the `test_code` line in `ask()`
    and the "TEMPORARY test login" script block.

## Still open

- **The admin portal through the internet needs two steps in Cloudflare** (an Access application, then the public
  hostname admin-d2d.pasdacs.com; `docs/d2d-relay.md`, "Admin portal"), and the team name and AUD tag in `.env`.
  Until then the admin portal works on the D2D Relay PC only: http://127.0.0.1:8102.
- **Payments.** Add credits is a request by email until online payment exists; a platform admin adds the credits.
- **Abuse.** Anyone with a business mailbox can still sign up and create an organisation (as asked), but since item
  13 it gets no credits, and so no AI time, until PASDACS approves a request.
- **Ask Relay questions and brand palettes cost no credits** (as asked). Their AI cost is recorded in `usage` only.
- **Connector sign-in for clients.** BigQuery's "Sign in with Google", and the OAuth options of Snowflake and Fabric,
  need an OAuth client in that organisation's own workspace, and nobody can set one up there yet. Client
  organisations use a service-account key, a password or a key pair instead.
- People management for owners (remove a colleague, transfer ownership) is not built. A platform admin can do it in
  the database.
- **NOT DONE (from item 2):** an Exchange ApplicationAccessPolicy that limits the mail app to info@pasdacs.com. Codes
  now go to any business address; the sender stays info@pasdacs.com.
- **Row-level security (backlog, 2026-11-10).** D2D can't set up RLS yet. The plan has no roles and the Power BI project
  it writes has none, so everyone who opens a report sees every row. Large organisations will ask for it. What to build,
  and when it counts as done, is in `docs/rls-backlog.md`. The enterprise demo in the PASDACS workspace, Global Ports
  Enterprise (demo), has two roles added by hand. A change request on that dashboard would drop them.

## Hand-over rules for this repository

- Work in this repository only; never change RELAY (the `Gen BI` folder) to serve D2D Relay.
- AI work runs one at a time; do not start several agents in parallel.
- Before a redeploy, check that nothing is running for a user. A restart kills a running dashboard build.
- Secrets live only in `.env` and `tunnel.env` (both git-ignored), never in commits.
