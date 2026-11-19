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
| Public address | https://d2d.pasdacs.com (Cloudflare tunnel) until the app was turned down (item 54; a static page there since 2026-11-17); the next deploy serves a client trial at https://demo.pasdacs.com (see "Deployment") |
| Admin portal | https://admin-d2d.pasdacs.com: PASDACS only, behind Cloudflare Access and its own email code (see "Admin portal") |
| On this PC | public site http://127.0.0.1:8100, admin portal http://127.0.0.1:8102 |
| Sign-in | a 6-digit code emailed (no passwords, no SSO), for people with an account only: nobody signs up (item 56) |
| Organisations | each in its own workspace, with one or more email domains of its own (item 60); PASDACS creates each one with its main owner on the admin portal, and its owners add its people |
| Credits | 50 to start (or what PASDACS sets), more only from PASDACS, a request it approves or credits it adds by hand (nothing is sold online since item 59); a new dashboard uses 25 with Power BI's built-in visuals or 50 with custom visuals, a change 10, Ask Relay 10 for up to 5 questions, a Semantic Review 10, a KPI changed in words 1, a Semantic Review fix 1 a finding (see "Organisations and credits") |
| Platform admins | the **@pasdacs.com** people of PASDACS's own workspace, on the admin portal only (every organisation, its people, credits, connectors, requests) |

## Containers

Four containers, split where the trust and the work differ (`docker-compose.yml`). The first three run the same image,
each in its own role (`RELAY_ROLE`, `docker/relay_init.py`), so they always run the same tested build.

| Container | Role | What runs | Reachable |
|---|---|---|---|
| `d2d-relay-db` | database | PostgreSQL 17 (volume `d2d-relay-db-data`) | the private Docker network only, with `RELAY_DB_PASSWORD` |
| `d2d-relay-web` | web | the public site: web app and AI engine (volume `d2d-relay-data`, `data\projects`) | 127.0.0.1:8100, d2d.pasdacs.com |
| `d2d-relay-admin` | admin | the admin portal: web app only, no AI engine or jobs (volume `d2d-relay-admin-data`) | 127.0.0.1:8102, admin-d2d.pasdacs.com |
| `d2d-relay-tunnel` | | Cloudflare tunnel (profile `tunnel`) | outbound only |

Why split this way and not further: the admin portal is a separate trust boundary (the public container has no
admin APIs at all, so a bug on the public side cannot reach them), and both portals need one database, which the old
one-container layout kept behind its own Unix socket. The web app and the AI engine stay together: every build is
streamed from the engine to the web app, so they restart together anyway, and inside the container they already run
as separate Linux users that cannot read each other's keys.
| Code sender | info@pasdacs.com through Microsoft Graph (delegated Mail.Send, signed in once) |
| Data sources | CSV / flat files (New dashboard -> upload), or demo data Relay generates. Connectors (BigQuery, Snowflake, Fabric, Redshift, Athena, Oracle) only once PASDACS switches them on for the organisation (see "Connectors") |

## What was kept and what was switched off

`webapp/app/edition.py` is the one place that decides this.

- **Kept:** Dashboards (D2D: plan -> KPIs -> prototype -> review -> Power BI file), the review gates and the Power BI engine
  check, the visual library, sample data, Connections (connectors on request), Ask Relay, Semantic Review (item 55: Power
  BI models against the organisation's KPI dictionary, see "Semantic Review"), the Ontology (item 61: business terms,
  industry packs and the KPI dictionary, see "Ontology"), Branding, organisations
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
start by themselves too once their shortcuts are in the Startup folder (one-time; on the D2D Relay PC they are there
since 2026-11-14, as "D2D Relay DAX checker" and "D2D Relay Power BI file maker"). To add them on a PC:

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

1. Go to Entra admin center -> **App registrations -> New registration**. Name it "D2D Relay sign-in mail", choose
   **single tenant**, leave the redirect URI empty, and click Register. Copy the **Application (client) ID** and the
   **Directory (tenant) ID**.
2. Under **Authentication**, set **Allow public client flows** to **Yes**, then Save.
3. Under **API permissions -> Add -> Microsoft Graph -> Delegated permissions**, add **Mail.Send** and **offline_access**
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

The email itself is in D2D's look (item 51, `webapp/app/code_email.py`): the sign-in page's dark band with the D2D
lockup and a mint bar, then the code large in a mint panel, how long it lasts, and what to do if nobody asked for it.
It is built as email has to be (tables, inline styles, no pictures or web fonts, so nothing is fetched when it is
opened), with a dark version for mail apps in dark mode; the admin portal's says it is for the admin sign-in page. To
look at it without sending one, write an example and open it in a browser: `python -m app.code_email out.html` in
`webapp` (add `admin` for the admin portal's).

Code rules: 6 digits, valid for 10 minutes, 5 tries. Per address: 1 code a minute and 6 codes an hour. Per network
(Cloudflare's `cf-connecting-ip`): 20 codes an hour. Only a salted hash is stored. A session lasts 12 hours
(`RELAY_SESSION_HOURS`).

`RELAY_OTP_EMAIL` (and `RELAY_ADMIN_EMAIL`) is info@pasdacs.com, the owner of the platform's own workspace, the
organisation "PASDACS". On the public site it is an organisation like any other; platform work is on the admin portal.

**Limit the mail app to info@pasdacs.com** (open, the user's: Microsoft 365 admin). With a client secret
(`RELAY_OTP_MS_CLIENT_SECRET`, as on the live site) the app sends app-only, and Microsoft's Mail.Send application
permission lets it send as any mailbox in the tenant. Exchange Online's RBAC for Applications, which replaces
Application Access Policies, scopes it to one mailbox:

1. Microsoft Entra admin center -> **Enterprise applications** -> the D2D Relay mail app: copy its **Application ID** and
   **Object ID** from this page (not from App registrations, which shows other values).
2. In Exchange Online PowerShell (`Connect-ExchangeOnline` as an Exchange administrator):

   ```
   New-ServicePrincipal -AppId <Application ID> -ObjectId <Object ID> -DisplayName "D2D Relay mail"
   New-ManagementScope -Name "D2D Relay sender" -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'info@pasdacs.com'"
   New-ManagementRoleAssignment -App <Object ID> -Role "Application Mail.Send" -CustomResourceScope "D2D Relay sender"
   Test-ServicePrincipalAuthorization -Identity <Object ID> -Resource info@pasdacs.com
   Test-ServicePrincipalAuthorization -Identity <Object ID> -Resource <another mailbox>
   ```

   The first test shows `InScope` True for Mail.Send, the second False.
3. Entra admin center -> **App registrations** -> the app -> **API permissions**: remove the Microsoft Graph
   *application* permission **Mail.Send** (keep any delegated ones). Until it is removed the scope has no effect:
   Entra's unscoped grant and Exchange's scoped one add up.
4. Wait 30 minutes to 2 hours (Exchange's cache), then sign in to D2D Relay to see a code arrive.

Without a client secret the app sends delegated, as info@pasdacs.com itself (`relay-ctl` mail sign-in with a device
code), and can only ever send from that mailbox. Keep the sign-in alerts a year: in Outlook on the web, a rule that
moves them to their own folder, and the folder's retention policy set to "1 Year Delete".

## Admin portal

https://admin-d2d.pasdacs.com is PASDACS's own site: **Overview** (who is online, everyone in the organisations),
**Organisations** (every organisation, its credits and connectors; **New organisation** creates one with its main owner,
its other email domains and its industry, **Add someone**, the person button on its row, adds someone to one: item 56, as
nobody signs up; the globe button on its row changes its email domains: item 60), **Requests** (credits, connectors and
Migration D2D that organisations asked for), **Payments** (past payments and their GST invoices, read only since item
59) and **Notifications**. It is a container
of its own (`d2d-relay-admin`); the public site answers none of its APIs. Two locks, both required:

1. **Cloudflare Access** in front of the hostname. The admin portal checks Access's signed token on every request that
   comes through Cloudflare (`app/portal.py`): the right application (AUD), the right team, not expired, and an
   @pasdacs.com address. Until `RELAY_ADMIN_ACCESS_TEAM` and `RELAY_ADMIN_ACCESS_AUD` are set, it refuses everything
   from the tunnel, so it works on this PC only (http://127.0.0.1:8102). A request that does not come through
   Cloudflare is accepted only from this PC (the published port), never from another container on the Docker network
   (security audit S10); each refusal is in the admin container's log ("[portal] refused a request from ...").
2. **The app's own email code**, for `RELAY_ADMIN_DOMAINS` addresses only (pasdacs.com), and only those with an
   account in PASDACS's own workspace (item 56): an owner of PASDACS adds a colleague on the public site
   (Organisation, People), and from then on that colleague is a platform admin there. Its sessions have their own
   cookie and kind, so a session from the public site is not accepted there, and the other way round.
   `RELAY_ADMIN_EMAILS` (comma-separated), when set, narrows this to the addresses it names; name the same ones in the
   Cloudflare Access policy.

To open it through the internet (Cloudflare dashboard, once):

1. **Zero Trust -> Access -> Applications -> Add an application -> Self-hosted.** Name "D2D Relay admin", domain
   `admin-d2d.pasdacs.com`. Add a policy: Action **Allow**, Include **Emails ending in** `@pasdacs.com`. Login method:
   One-time PIN, or PASDACS's Microsoft sign-in if it is set up in Zero Trust.
2. From the application's overview, copy the **Application Audience (AUD) Tag**. The team name is the first part of
   your team domain (`<team>.cloudflareaccess.com`, Zero Trust -> Settings).
3. In `.env`: `RELAY_ADMIN_ACCESS_TEAM=<team>` and `RELAY_ADMIN_ACCESS_AUD=<tag>`, then `docker compose up -d admin`.
4. **Networks -> Tunnels -> d2d-relay -> Public hostname -> Add:** subdomain `admin-d2d`, domain `pasdacs.com`, service
   **HTTP**, URL `d2d-relay-admin:8000`. Do this last, so the hostname never exists without Access in front of it.

## Organisations and credits

**Nobody signs up** (item 56, the user, 2026-11-18: "Remove signup and bring login directly as internal team
management"; D2D is licensed to client organisations, not offered to the public). Only people with an account can sign
in, and accounts come from two places:

- **PASDACS creates each organisation** on the admin portal (Organisations, **New organisation**): its name, its main
  owner's work address and name, and its starting credits (50, `RELAY_CREDITS_START`, unless another number is set; 0
  gives none). The organisation is that address's email domain, which only one organisation can have, plus any **Other
  email domains** its people use (item 60, below); a free mail
  (Gmail, Outlook, Yahoo, iCloud, Proton ...: `public_domains.FREE`) or throw-away address (Mailinator, temp mail,
  Yopmail ...) cannot own one (refuse more domains with `RELAY_PUBLIC_DOMAINS_EXTRA`, or treat a listed domain as a
  business with `RELAY_PUBLIC_DOMAINS_ALLOW`, comma-separated). **Industry** picks the industry pack its ontology starts
  from (item 61, "Ontology"; "Not now" leaves the choice to the owners). The main owner is emailed, signs in with a
  code and gets the first-time tour (below), with the brand (logo, description, palette) as one of its steps, all of
  it skippable.
  PASDACS can also add someone to any organisation (Organisations, **Add someone**: the person button on its row), as a
  member or an owner, for instance a new owner when the owners have left; that organisation's owners are told.
- **The organisation's owners add its people** (Organisation page, People, **Add people**): addresses at any of the
  organisation's email domains, as members or owners; each gets an invitation email and signs in with a code.
- **Several email domains** (item 60: one organisation for a company whose people use more than one domain). Besides
  the main domain it was created with, an organisation can have up to 19 more (`relay.tn_org_domains`; 20 in all,
  `orgs.MAX_DOMAINS`), each belonging to one organisation only, none a free mail or throw-away service's. PASDACS
  gives them on the admin portal: **Other email domains** on New organisation (comma-separated), or later the globe
  button on its row (**Email domains of ...**: add one, or remove one; `POST /api/admin/orgs/<id>/domains`,
  `DELETE /api/admin/orgs/<id>/domains/<domain>`). The owners are told when one is added. The main domain stays;
  taking another away keeps the accounts made with it, and nobody new can be added with it. The organisation shows
  every domain (`@a.com, @b.com`) on its page, the tour and the admin portal; the audit has `d2d.org_domain_added` and
  `d2d.org_domain_removed`. A personal workspace has no domains to add.

An address without an account that asks for a code gets the same answer as one with an account ("If ... has a D2D
Relay account, we sent it a sign-in code"), but no code, after about as long as sending one takes; the code limits
count it the same way. So the sign-in page never tells anyone which addresses have accounts; the audit records it as
`auth.otp_no_account`.

- **People** (Organisation page). An organisation can have several owners. Owners add people, change anyone's role,
  and remove people. **Removing someone deletes their account at once**, after a warning (the user's decision of
  2026-11-12; `governance.delete_person`): their name, email address, sign-ins, sessions, Ask Relay conversations,
  notifications, tokens, connections (signed in as them) and schedules go, and the logs and accounting records keep no
  name or address of theirs. Their work stays with the organisation: dashboards, saved visuals and pages pass to the
  main owner, and a dashboard says it was made by a former member. With the account gone they cannot sign in until an
  owner adds them again, as a new person. The main owner (PASDACS's contact and the one who does the first-time setup)
  cannot be removed or made a member; they hand the main ownership to someone else first (Transfer ownership), staying
  an owner or not.
- **Personal workspaces** (item 39, while anyone could sign up: a free mail address got a workspace of its own, which
  bought its credits online). No new one is made; the ones there keep working: that one person only (no
  Add people), and since item 59 they ask for credits with Request credits like any organisation; PASDACS can still
  add credits by hand. On the admin portal they show as
  Personal, with their address (`relay.tn_orgs.personal = 1`, the full address as `domain`).
- **Delete my account** (Organisation > Your data): anyone but the main owner deletes their own account the same way,
  after typing DELETE; the owners are told. **Delete the organisation**: the main owner deletes it with everything in
  it (every dashboard, person, conversation, connection and the brand; the credits left are lost), after typing its
  name (`governance.erase_org`, the same as `python -m app.governance erase-org`). Payments and their GST invoices stay,
  without names, as tax law requires. PASDACS is told, and can create it again later as a new organisation.
- **Owners see every dashboard**, with who made it (Dashboards and each dashboard's page: "Created ... by ...").
- **Each organisation is its own workspace.** Dashboards, connections, branding, Ask Relay conversations and people
  are never visible to another organisation. Inside one, each person's dashboards are private until shared; the owner
  can open them all.
- **Credits are shared** by everyone in the organisation. The top bar shows the organisation and its credits;
  Organisation (`#/org`) shows the owner, the people, the costs and the credit history.

| What | Credits |
|---|---|
| Start | 50 (`RELAY_CREDITS_START`), or what PASDACS sets when it creates the organisation; more come only when PASDACS approves a request or adds them by hand (nothing is sold online since item 59) |
| New dashboard (plan, KPIs and first prototype) with Power BI's built-in visuals only | 25 (`RELAY_CREDITS_DASHBOARD`) |
| New dashboard with custom visuals: built-in first with custom where needed, or Relay custom visuals (item 44) | 50 (`RELAY_CREDITS_DASHBOARD_CUSTOM`) |
| Moving a dashboard made with built-in visuals to custom visuals (its Details tab), once | the difference, 25 |
| A change: revise the plan, a change request, building a suggested custom visual, an Ask Relay answer sent to a dashboard | 10 (`RELAY_CREDITS_CHANGE`) |
| Ask Relay: up to 5 answered questions in one conversation (`RELAY_CREDITS_ASK_QUESTIONS`), charged at its 1st, 6th, 11th ... question | 10 (`RELAY_CREDITS_ASK`) |
| A Semantic Review of up to 5 models, or Review again | 10 (`RELAY_CREDITS_REVIEW`) |
| A KPI changed in plain words: a plan's KPI at Confirm KPIs, or a KPI dictionary entry (item 63); given back when nothing changes | 1 (`RELAY_CREDITS_KPI`) |
| Semantic Review fixes (item 65), shown before anything is charged; given back for a fix that does not check out | 1 a finding (`RELAY_CREDITS_FIX`) |
| Confirming the plan, fixing failed review gates, approving and publishing, brand palettes, Relay's review team (item 68), tagging a column with a business term, the ontology | free |

A request without enough credits is refused before anything starts, with the balance in the message. Every
AI cost is still recorded on the server (the `usage` table); the screens show no tokens and no cost breakdown. Ask
Relay shows the credits a conversation used and the questions left in them; a question that gets no answer gives
its credits back.

**Starting credits** are given when PASDACS creates the organisation, as "Starting credits" in its history. (Before
item 56 an organisation that signed up waited for PASDACS to approve them, item 27: a request marked "New
organisation" under Requests. None is made any more; one still waiting is approved or declined like any request.)

Credit requests can also be answered from the command line, in the web container (it sends the emails):

```
docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.orgs requests
docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.orgs approve <request id> [credits] ["note"]
docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.orgs decline <request id> "<reason>"
```

**Getting more credits.** Only from PASDACS (item 59, the user, 2026-11-19: "remove payment all and have only as
request credits"; buying online is gone, "Payments (removed, item 59)"): PASDACS approves a request, or adds credits by
hand. Every organisation and personal workspace has Request credits:

1. Someone in the organisation clicks **Request credits** (top-bar chip, Organisation, Dashboards, or the message
   when credits run short), picks an amount and adds a message. One request can wait at a time; the person who asked,
   or the owner, can withdraw it to ask for a different amount. The request also goes to info@pasdacs.com
   (`RELAY_CREDITS_CONTACT`) by email with Reply-To set to the person, and to every PASDACS person's notifications.
   They can also simply email info@pasdacs.com.
2. On the admin portal, **Requests** lists it as waiting (and Organisations shows what each organisation asks for).
   **Approve** adds the credits at once, the amount asked or another one, with an optional note for their credit
   history. **Decline** needs a reason. Either way the person who asked and the owner are told in the app and by email.
3. For a request that came by email, **Organisations -> Credits** adds credits by hand with a note (a negative number
   takes credits back).

### 2. Public address (Cloudflare tunnel)

pasdacs.com's DNS is on Cloudflare, so no port is opened on this PC.

1. In Cloudflare, go to **Zero Trust -> Networks -> Tunnels -> Create a tunnel** (type Cloudflared) and name it
   `d2d-relay`. Copy the token from the "Install connector" step.
2. In the tunnel, go to **Public hostname -> Add**. Set subdomain `d2d`, domain `pasdacs.com`, service **HTTP**, and
   URL `d2d-relay:8000` (the public site's container answers to that name too). Keep the name one level under
   pasdacs.com: Cloudflare's free certificate covers `d2d.pasdacs.com`, not `app.d2d.pasdacs.com` (that needs its paid
   Advanced Certificate Manager).
3. Create `tunnel.env` next to `docker-compose.yml` with one line, `TUNNEL_TOKEN=<token>`. Git ignores this file, and
   the app container never sees it.
4. Set `RELAY_PUBLIC_URL=https://d2d.pasdacs.com` in `.env` (the address in emails and invitations), run
   `docker compose --profile tunnel up -d`, then open https://d2d.pasdacs.com. Since item 59 every email from either
   site names the public site's address (`portal.site()`: invitations, approvals, the sign-in code email's footer):
   the admin portal gets it as `RELAY_SITE_URL`, which `docker-compose.yml` takes from `RELAY_PUBLIC_URL`; the admin
   portal's own address is never used in an email, as nobody but PASDACS signs in there.

Cloudflare provides the certificate. pasdacs.com sends HSTS includeSubDomains, so the address must be https, and it
is. Optional extra lock: a Cloudflare Access policy (email one-time PIN for the same address) in front of the hostname.

**Changing the address** (as on 2026-11-12, from `d2d-relay.pasdacs.com` to `d2d.pasdacs.com`): add the new public
hostname to the same tunnel and keep the old one, set `RELAY_PUBLIC_URL` and restart web and admin
(`docker compose up -d --no-deps web admin`), add the new hostname to the Turnstile widget ("Bot check"), and later,
if wanted, a Cloudflare redirect rule from the old address to the new one (there is no Razorpay webhook to move since
item 59). People sign in again on the new address (a sign-in
belongs to one address), and links in emails already sent keep working while the old hostname stays.

The old address is being retired (the user, 2026-11-12): delete its public hostname in Cloudflare (Zero Trust ->
Networks -> Tunnels -> the D2D tunnel -> Public hostname -> `d2d-relay.pasdacs.com` -> Delete), and its DNS record if
Cloudflare leaves one. Nothing in the app, `.env` or `docker-compose.yml` uses it; sign-ins made on it and links in
emails sent before 12 November stop working, and people sign in again on https://d2d.pasdacs.com.

### 3. Connectors (on request)

The public side takes CSV files only. **Connections** lists every connector D2D Relay can read: Google BigQuery,
Snowflake, Microsoft Fabric, Amazon Redshift, Amazon Athena and Oracle Database (`edition.CONNECTORS`). Each one is
"On request" until PASDACS switches it on for that organisation.

An organisation's own warehouse or database, and row-level security, come as a **turnkey deployment** that PASDACS
sets up after the organisation gets in touch (decided on 2026-11-11); the Connections page and its request say so.
Switching a connector on for an organisation on the shared site, below, stays possible.

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

## First-time tour

Someone new who opens the front page gets a short tour (`#/welcome`, `js/38-tour.js`), skippable at every step:

1. **Welcome**: what Dashboards, Ask Relay and the brand are, and the organisation (owner, who is in it: the people
   its owners add, and its credits).
2. **Your brand** (owners only): Branding inside the tour (logo, a few words, palettes). For a new organisation's main
   owner this is the organisation's first-time setup; skipping it is fine, Branding stays in the sidebar.
3. **Light or dark**: Light, Dark or Match my device (follows the computer or phone, also when it changes). Kept in
   that browser; the sun or moon button in the top bar changes it any time. Reports keep their brand colours.
4. **The basics**: how a dashboard is made, the credits (Request credits), Migration D2D, where to ask.

Finished or skipped, it is not shown on its own again (`POST /api/me/tour`, one flag per person). It is shown only to
people who started on or after 2026-11-12 (`platform.TOUR_SINCE`); everyone can open it again from the organisation
menu (the organisation's name in the top bar -> **Take the tour**). A link to anything else, such as a shared
dashboard, opens what it points to, not the tour. `#/setup`, the old setup address, opens the brand step.

## Migration D2D

"Migrate any dashboard to any dashboard": moving an organisation's dashboards from one BI tool to another (Cognos,
Qlik, Looker, Tableau, Power BI, MicroStrategy, SAP BusinessObjects, SSRS and more, in any direction). It is not
self-service: the page (`#/migration`, in the sidebar and the organisation menu; `js/39-migration.js`) says what it
does and how, and **Contact PASDACS** asks which tools the dashboards are in and should go to, roughly how many, and a
message.

1. The request goes to info@pasdacs.com (`RELAY_CREDITS_CONTACT`) by email, Reply-To the person, to the platform
   admins' notifications, and to **Migration D2D requests** on the admin portal's **Requests** page
   (`POST /api/org/migration-request`, at most 5 an hour per person; the tools are `orgs.BI_TOOLS`). A prefilled email
   link is the fallback.
2. PASDACS replies by email to agree what moves and when, and does the work with the organisation (the migration
   toolkit is `genbi_kit/migrate`: readers for Cognos and Qlik, the conversion to Power BI, and the proof that the
   numbers match).

## Semantic Review

One KPI, one meaning, one value (item 55): an organisation's Power BI semantic models checked against its own KPI
dictionary. Every measure that calculates a KPI differently from the others, or not the way the organisation defined
it, is flagged with what to change, and so is DAX that gives a wrong or unstable number. Self-service, for every
organisation (personal workspaces too), in the sidebar under Ask Relay (`#/review`, `js/40-review.js`). Code:
`webapp/app/semreview.py` (the API, the runs, credits), `webapp/app/semreview_pbi.py` (Power BI), `genbi_kit/semreview/`
(reading models and DAX, the rules).

**The KPI dictionary** (`#/review/kpis`, the organisation's ontology of KPIs): per KPI its name, other names (synonyms),
definition, formula in words, reference DAX (other KPIs by `[name]`), unit, aggregation, the rules that are part of its
meaning (for example `Status = Completed`) and time basis (for example "fiscal year ending 31 March", read as year end
03-31). One name stands for one KPI: a name or synonym can belong to one KPI only, and reference DAX must be readable.
People add KPIs in the app, import a file (CSV or Excel with a header row, the usual titles understood: KPI, Metric,
Description, Calculation, Aliases ...; or YAML / JSON; a preview first, then merge or replace), download it (CSV,
YAML) or a template, or pick measures of a review to start it. BI Devs and owners change it; everyone reads it.
Since item 61 it is part of the organisation's ontology (also at `#/ontology/kpis`, "Ontology"): industry packs add
KPIs to it, new dashboards plan their KPIs from it, and an entry can be changed in plain words (the wand button, 1
credit, "Changing a KPI in words").

**A review** (`POST /api/semreview/runs`) reads up to 5 models (`RELAY_REVIEW_MAX_FILES`) at once and compares them
with each other too:
- files: `.pbix`, `.pbit`, `model.bim` (or a TMSL `.json`), a zipped Power BI project (`*.SemanticModel` with
  `model.bim` or TMDL), up to 500 MB each since item 64 (`RELAY_REVIEW_MAX_MB`; files over 4 MB go up in parts, past
  Cloudflare's 100 MB a request: "Large data"). A `.pbix` over the limit can be saved as a template (`.pbit`, no data,
  small). A `.pbix` connected live to a model in the
  service holds no model: the review says so.
- models in the Power BI service, through the organisation's own Entra app (below).
It uses 10 credits (`RELAY_CREDITS_REVIEW`), charged when it starts and given back when it does not finish (a file that
cannot be read, a restart). Runs in the web app's background, at most 2 per organisation, one `.pbix` read at a time:
1. **Read.** Metadata only: tables, columns (types, summarisation, formats), measures (DAX, formats, descriptions,
   folders), relationships, calculation groups, and which visuals show which fields and with which titles (the report
   part of a `.pbix`, `.pbit` or project). Never the data, Power Query or roles. Each uploaded file is deleted as soon
   as it is read; its folder (`.semreview` under the organisation's projects folder, never in backups) after the review.
   A `.pbix` model is XPress9-compressed: PBIXRay (MIT, pinned in `webapp/requirements.txt`) reads it in a process of
   its own (`genbi_kit/semreview/pbix_read.py`: `python -I`, an empty environment, 3 GB of memory, 240 s of processor
   time, 6 GB of spill file at most, its output at most 128 MB; `D2D_PBIX_READ_*`), because it is native code
   reading a file someone uploaded. It still runs as the web app's user inside the web container (its files and
   network): moving it into a job container of its own, with no network and only the upload, is the next hardening
   (`docs/LOG.md`, Still open).
2. **Check** (`genbi_kit/semreview/analyze.py`): each measure's DAX is read, its measure references and variables put in
   place and written one canonical way (`dax.py`), so two formulas that compute the same thing compare equal (each
   measure is worked out once, so deep chains of references stay fast). The dictionary's DAX is read in each model:
   its `[KPI]` references are the dictionary's own definitions, any other `[name]` that model's measure or column. The
   rules:
   a KPI calculated more than one way (in one model or across models), a measure that does not compute what the
   dictionary's DAX computes (with that DAX written for the model), the wrong aggregation, an average of ratios, a YTD /
   LY / vs-budget variant not built on its KPI, another year end, a percentage not shown as one (or one KPI in
   different formats), a visual titled with one KPI showing another, visuals that add up a column a KPI measure covers,
   DAX that cannot be read or refers to something not in the model, CALCULATE around a variable, SUMX without
   CALCULATE, ALL / REMOVEFILTERS on a KPI, two names for one number, a variant repeating its KPI's formula, ids /
   years / rates that visuals add up by default, fixed numbers in a KPI, "/" instead of DIVIDE, both-way relationships,
   and the dictionary's KPIs no model has and measures no KPI has.
3. **Meaning** (when the dictionary has definitions in words): Claude, through the AI engine's chat lane with no tools
   (`askd.ask_json`), judges each KPI's measures against its definition and says which measures in no KPI compute one;
   its answer is checked before it is shown (only measures and KPIs it was given, plain text). It sees the KPI
   definitions, the measures' DAX and the models' table and column names, never data. When it cannot run, the review is
   complete without it and **Check meaning again** runs that step once more, at no cost.
4. **Values** (Power BI service models): the value of each measure of a KPI that disagrees, over the whole model
   (`EVALUATE ROW`), side by side.
The report: KPIs with one meaning (x of y), findings by severity with what to do and the DAX to copy, the KPI table
(each KPI's measures by version), every measure, the models; findings download as CSV (spreadsheet formulas
neutralised). **Review again** reads the kept models against today's dictionary (no upload, 10 credits). A review is
deleted by whoever ran it or an owner, with the models it kept; "Download my data" lists the reviews a person ran.

**Fixing the findings** (item 65, the user, 2026-11-19: "semantic review should be action as well rather than showing
only finding, it should be able to fix and suggest credits for consumption"; `webapp/app/semreview_fix.py`). A finished
review shows **Fix the findings** with what fixing uses before anything is charged: how many findings can be fixed in
the model's measures, how many with the DAX the review's rules already wrote, and the credits, 1 a finding
(`RELAY_CREDITS_FIX`): all of them, or only the high ones. **Pick all**, **Only the high ones** or **Choose findings**
(a box on each fixable finding), then **Fix N** (BI Devs and owners; up to 60 at a time;
`POST /api/semreview/runs/<id>/fixes`). The credits are charged, then in the web app's background:
- a finding the rules already wrote the fix for (the dictionary's definition written for the model, DIVIDE instead of
  "/", a ratio of sums ...) is ready as it is;
- the others are written by Relay through the AI engine's chat lane with no tools (`askd.ask_json`, 15 findings a
  request): it sees the findings, the measures' DAX, the model's table, column and measure names and the dictionary's
  entries, never data. A KPI no model has gets a new measure, in the table that holds most of the model's measures;
- every fix is checked against the model the review kept before it is kept: readable DAX (Semantic Review's parser),
  only tables, columns and measures the model has, no measure that refers to itself. A fix that does not check out
  gives its credit back (`orgs.give_back_part`); if the work stops, all of them come back.
Findings about visuals (titles, visuals that add up a column), relationships and calculation groups have no measure
to fix and are fixed in the report by hand; measures in no KPI go to the dictionary instead. The **Fixes** tab shows
each fixed measure with its DAX now and fixed (copy), who wrote it (the review's rules or Relay), and what could not be
fixed, and downloads per model a **TMDL** script (Power BI Desktop: View > TMDL view, paste, Apply; or Fabric and
Tabular Editor 3; `fixes.tmdl`), a **Tabular Editor** C# script (`fixes.csx`) and all fixes as **CSV** (`fixes.csv`,
spreadsheet formulas neutralised). The uploaded model files are never kept, so D2D Relay cannot write a fixed `.pbix`:
the scripts apply the fixes to the person's own model. To check the fixed model, review it as a new review (upload it
again, or pick it in the Power BI service): **Review again** re-reads what this review kept (`kind: stored`), without
the fixes, although the Fixes tab says "save and Review again". Kept in the review (`semreview_runs.fixes`), deleted
with it; audited as `semreview.fixes`.

**Power BI (Azure).** An owner enters the organisation's own Microsoft Entra app (tenant, client id, client secret; the
secret encrypted with the workspace's secrets, never shown again). What the organisation sets up on its side, in the
dialog: register an app with a client secret; in the Fabric admin portal allow service principals to use Fabric APIs
(and the Execute queries REST API for the values); add the app to each workspace to review as **Contributor** (Power BI
shows a model's DAX only to identities that may change it). D2D Relay only reads: workspaces and their semantic models
(Fabric REST API), each model's definition (`getDefinition?format=TMSL`, a long-running operation followed only on the
Fabric API's own host), else the INFO.VIEW functions (`executeQueries`), and the values. Ids must be GUIDs and the
addresses are fixed (`D2D_ENTRA_LOGIN`, `D2D_FABRIC_API`, `D2D_POWERBI_API` exist for the test stack's stand-in,
`tests/checks/fake_powerbi.py`). Not covered: Azure Analysis Services, models with an encrypted sensitivity label, and
DirectLake models whose definition Fabric does not export.

## A dashboard from a DAWB hand-off

DAWB, the lakehouse builder, writes a D2D project after every lakehouse build (item 58): the data is in and profiled
and a plan is proposed, so the dashboard starts at Confirm KPIs with DAWB's plan instead of Relay planning from
scratch. On **New dashboard**, **From a DAWB hand-off** takes the hand-off folder as one `.zip`
(`POST /api/projects/import`, `webapp/app/handoff.py`); the visuals, custom visuals and style choices are the usual
ones, and it uses what any new dashboard uses (25 credits with Power BI's built-in visuals, 50 with custom visuals).

**The hand-off** (format 1): `project.json` (`kind` "d2d-project", `format` 1: name, description, audience, refresh,
privacy, lineage, quality; `inputs`, each CSV with its table, description, rows and columns with name, type and
description, the types text, whole number, decimal, date, date and time, true or false; `plan` with `model` (tables
as names or `{name, role, grain}`, `relationships` as `"many_table[column] -> one_table[column]"`, a note), `kpis`
(`{name, dax, description, format}`, format currency, percent or whole number, or a Power BI `format_string`) and
`pages` (`{name, purpose, visuals}`, each visual with a title, a kind, a query on the gold tables and its place on a
24-column grid)), `data/<table>.csv`, and `manifest.json`, written last (`run`, `release`, every file with its sha256,
rows and columns). The zip holds the folder as it is, or its files at the top; Windows backslashes are fine.

**Checked before anything is saved or charged**, each problem named in the refusal: every file the manifest lists is in
the zip with its sha256; each input is `data/<table>.csv` with its columns in order and its rows; D2D's own profile
reads every CSV (`profile.md`, `profile.json`, as Relay's planning makes them); each relationship joins columns of the
same type, its one side has a value in every row, each value once, and no table reaches another along two filter
paths; the plan passes D2D's plan check (KPIs with readable DAX, pages). At most 2,000 files and 8 GB unpacked
(`RELAY_HANDOFF_MAX_GB`); an upload cut off by a restart is tidied a day later.

**What the dashboard gets**: `plan.yaml` from DAWB's plan (a KPI's label is its name; formats currency `\$#,0`,
percent `0.0%`, whole number `#,0`; a KPI with the name of a column, which Power BI refuses, becomes "Total ..." with
the old name as its label, and the KPIs that use it follow); `request.md` for the build, which keeps the KPIs' DAX and
the table and column names they use, gives the tables and columns DAWB's descriptions (columns carry a `description`
in definition.yaml since item 58) and treats DAWB's visuals, queries and grid as guidance, not as the report's layout;
DAWB's `project.json` and `manifest.json` as written, in `handoff/`. The plan screen says "DAWB's plan" until Relay
revises it; from Confirm KPIs on, the dashboard is like any other.

## Ontology

The organisation's business vocabulary, so Relay reads any of its data the same way (item 61, the user, 2026-11-19:
"ontology layer as well where we bring default ontology and kpi as per industry and user can also configure and
change"). In the sidebar under Semantic Review (`#/ontology`, `js/42-ontology.js`). Code: `genbi_kit/ontology.py`
(terms, tagging columns, the agent's guide), `genbi_kit/ontology_packs/*.yaml` (the industry packs),
`webapp/app/ontology.py` (the organisation's copy, its API, a dashboard's files).

- **Business terms** (`#/ontology/terms`): what the columns of the organisation's data mean. A term has a name (Sales),
  a kind (measure, key, date or attribute), what it belongs to (Store, Product, Customer ...), for a measure its unit
  and how it adds up, a family (Net Sales and Digital Sales are both Sales: shown together, never added up) and its
  other names in columns (sls, sales_amt, net_sls ...). Up to 1,500 terms with 40 other names each, in the
  organisation's own schema (`onto_terms`). One name tags one kind of column: a name or other name that two terms of
  one kind share is refused.
- **The KPI dictionary** (`#/ontology/kpis`): the one Semantic Review checks models against ("Semantic Review"), which
  new dashboards now plan their KPIs from.
- **Industry packs**: an industry's business terms, its usual KPIs (definition, formula in words, and reference DAX for
  a KPI built from other KPIs) and example questions for Ask Relay. 13 ship: Grocery and retail, Consumer goods,
  E-commerce, Healthcare, Manufacturing, Software and subscriptions, Supply chain and logistics, Hotels and
  restaurants, Banking and lending, Insurance, Telecom, Energy and utilities, and General business (69 to 80 terms and
  38 to 55 KPIs each; General business 41 and 17). **Look inside** shows a pack; **Use it** (BI Devs and owners) adds
  what the organisation does not have yet and keeps what it has, unless "use the pack's version" is ticked; a KPI
  whose name belongs to another of its KPIs is left out. PASDACS can apply one when it creates the organisation (New
  organisation, **Industry**), or later in the web container (pack ids: `grocery-retail`, `consumer-goods`,
  `ecommerce` ..., as `packs` lists them):

  ```
  docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.ontology packs
  docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.ontology apply <workspace id> <pack id>
  ```

  Until an organisation has terms of its own, its columns are tagged with General business's.

**How a column gets its term**, by name only, and each tag says why: the column name's words (camelCase and snake_case
split, the usual abbreviations spelled out: amt, qty, nbr, sls ..., plurals made singular) equal to a term's name or
other name, ignoring amount, value, total or a currency (`sls_amt_usd` is Sales), or holding it. The kind must fit the
column's type: a measure on numbers that are not keys, a date on dates, a key on an id-like or unique column, an
attribute on text. Last year, budget, target or forecast words make a column a variant of its term (`sales_ly`: Sales,
last year's), never added up with it; percent, rate, tax or growth words make it another number (`gm_pct` is not Gross
Margin). **Try column names** (Business terms) shows how names would read.

**What every dashboard gets.** Before Relay plans, and again before each build and change, the web app writes
`ontology.json` (the terms, the KPI dictionary, the industry, the person's own column tags) and `ontology.md` (the
agent's guide: the terms and KPIs found in this data first) into the dashboard's folder
(`ontology.write_project_files`). `genbi profile` tags each column (profile.md's "business term" column) and lists a
measure term found in several columns (one business number, to combine), related terms of one family in different
tables (checked before combining) and one entity's keys under different names, which it tries as relationships too
(`store_id` and `str_nbr`, kept when half the values match). The plan names model columns after their terms, prefers
the dictionary's KPIs with their names, definitions, rules and time basis (`dictionary: <name>` on the KPI in
plan.yaml) and plans one KPI where one term is in several tables (GENBI.md, Ontology; `prompts.PLAN`); each plan KPI
then says whether it comes from the dictionary (`ontology.mark_plan_kpis`, project.json `plan_dictionary`).
ontology.md tells the agent that it is the organisation's data, not instructions.

Everyone in the organisation reads it; BI Devs and owners change it: add, edit or remove terms, import YAML or JSON
(merged by name, up to 2 MB), download it all as YAML (`/api/ontology/export.yaml`), and teach column names from a plan
("The semantic model on the plan"). API: `GET /api/ontology`, `GET /api/ontology/packs/<id>`,
`POST /api/ontology/industry`, `POST`, `PUT` and `DELETE /api/ontology/terms`, `POST /api/ontology/teach`,
`POST /api/ontology/match`, `POST /api/ontology/import`; audited as `ontology.pack`, `ontology.term_save`,
`ontology.term_delete`, `ontology.teach` and `ontology.import`.

## Large data

Big files and big tables (item 64). Code: `webapp/app/uploads.py`, `genbi_kit/sampling.py`, `js/01-core.js`
(`upload()`), `js/04-new.js`.

**Uploads in parts.** Cloudflare refuses a request over 100 MB, so the browser sends every file over 4 MB ahead of its
form, in parts of 32 MB: `POST /api/uploads` (name and size), `PUT /api/uploads/<id>/<n>` for each part (each retried
on its own when a connection drops), then `POST /api/uploads/<id>/done` (the parts joined and the size checked). The
form names the upload instead of the file (`uploads`: a JSON list of `{field, id}`), and the server reads it as if it
had come with the form, through the same checks: New dashboard, a revised plan, a change request, a DAWB hand-off and
Semantic Review. One progress bar covers it all. A file is at most 10 GB (`RELAY_UPLOAD_MAX_GB`), and an upload starts
only when the disk has room for three times the file plus 2 GB. The parts wait in the organisation's projects folder
(`.uploads`, a dot folder: never in backups), for the person who started the upload only; one not used within a day is
removed when the next upload starts.

**Building on a sample.** New dashboard shows how much data was picked (files and size; from about 1 GB it explains
that the big tables are sampled) and, for uploaded files, **Data used to build**:
- Automatic (the default): a sample of each table over 2 million rows (`GENBI_SAMPLE_OVER`);
- a sample of every table over 1 million rows;
- every row (slower for big files);

and **How to sample**: random rows (a reservoir sample of 1,000,000 rows, `GENBI_SAMPLE_ROWS`, with a fixed seed: the
same rows every time, the whole date range and the mix of stores and products kept, totals smaller by the share
sampled) or the most recent rows by the table's first date column (exact totals for the latest weeks, a shorter
history; random when the table has no date column). Credits do not depend on the size. Smaller tables (stores,
products) are always used in full, so every key in a sample finds its row.

Before planning, the worker takes the sample once (`worker.read_data`, `sampling.prepare`): `sample.json`, the samples
in `.genbi/cache/<file>.sample.parquet`, and `data_sample/` (the samples as CSV, the other tables beside them). Every
build step then reads the sample: `genbi profile` and `genbi sql`, the prototype, the review gates and the DAX check
(which samples on its own as well). profile.md, the activity and the plan screen say which tables are a sample (x of y
rows), and the agent is told that totals are the sample's (GENBI.md, Large data). Ask Relay always answers from every
row (`data.connect(full=True)`). The report's DataFolder points at `data_sample/` and the file gates check those
files; as the code stands, the Power BI file maker on this PC is still handed the full `data` folder (`pbix.py`), so
the .pbix it makes is refreshed with every row, although New dashboard says the Power BI file loads the sample (see
the code).

Semantic Review takes files up to 500 MB each, as they go up in parts.

## The semantic model on the plan

The dashboard shows its semantic model while Relay reads the data and on the plan (item 62; `js/41-semantic.js`,
`css/semantic.css`; `GET /api/projects/<id>/semantic`, `ontology.semantic_view`). Before planning, the worker reads
the data first (`worker.read_data`: the ontology's files, the sample of big tables, the profile with every column's
term), keeps how much was read (project.json `data_size`) and when (`semantic_ready`), and says what it found in the
activity ("Read your data: N tables, X of Y columns matched to your ontology, Z likely relationships"). The
**Semantic model** card is then on the Overview while Relay plans, and on the plan screen in place of the plan's table
list:
- how many columns matched a business term, the industry (or "General business terms"), how many KPIs come from the
  KPI dictionary, and a link to the ontology;
- how much data is used: all of it, or which tables are a sample ("Large data");
- a diagram: the plan's tables and relationships once there is a plan (before it, the files and the relationships
  found in them), facts in the middle and the tables they point to on either side, `*` and `1` at the ends of each
  line with its key; a relationship found through a business term is drawn differently;
- what the terms showed: a term in several columns (one number, combined), related terms in different tables (checked
  before combining), one entity's keys under different names (linked);
- each table, folded: its columns with their type, unique or not, and business term (why it was given, a variant,
  "(yours)" for a person's own).

While the plan waits at Confirm KPIs, a column's term can be changed, or set to none, and **Save the tags** keeps them
(free; `PUT /api/projects/<id>/semantic`): project.json `semantic_overrides`, the profile made again, ontology.json
written again, and the build uses them. BI Devs and owners can also teach the ontology (ticked by default): the column
name becomes another name of that term (`POST /api/ontology/teach`; the organisation's own copy of a General business
term when it has none), so the next data with that column is tagged on its own. A dashboard from a DAWB hand-off gets
the same card: its data is read with the ontology when it is imported.

## Changing a KPI in words

Item 63 (the user, 2026-11-19: "each kpi can be fixed or change by natural language as well each 1 credit";
`webapp/app/kpi_words.py`). 1 credit a change (`RELAY_CREDITS_KPI`), in two places:
- **A plan's KPI**, while the plan waits at Confirm KPIs: under each KPI card, a line ("exclude returns", "make it
  weekly") and **Change**, or **Fix it** (the DAX made valid and doing what the description says;
  `POST /api/projects/<id>/kpis/change`). Relay rewrites that KPI's name, label, description, DAX and format, starting
  from the card as shown (edits not saved yet included), and saves it into plan.yaml at once. Each card says whether
  its KPI comes from the KPI dictionary, differs from it ("Approvals before the build") or is new. A KPI added on the
  screen is not in the plan yet: it is edited by hand.
- **A KPI dictionary entry** (the wand button in the KPI dictionary, under Ontology or Semantic Review; BI Devs and
  owners; `POST /api/semreview/kpis/<id>/change`): its name, other names, definition, formula, reference DAX, unit,
  aggregation, rules or time basis.

The credit is charged before Relay is asked and given back when nothing changes: Relay cannot be reached, it says the
data cannot do it, or its answer does not check out. The answer is checked before it is saved: plain text, DAX that
the plan's own lint and Semantic Review's parser can read, only the planned model's tables, no other KPI's name; for
the dictionary, its own rules (one name, one KPI). Relay answers through the AI engine's chat lane with no tools
(`askd.ask_json`): it sees the KPI, the other KPIs' names and DAX, the data's tables and columns with their business
terms, and the dictionary entries close to it, never data rows. A plan change goes into the activity and request.md;
both kinds are audited (`kpi.words`, `kpi.words_dictionary`).

## Approvals before the build

Item 73 (the user, 2026-11-19: "data needs to be reviewed and let them know if any gaps or assumptions made ... any
deviation or assumption or calculation needs to be approved"; `ontology.approval_items`, `KpiReview.approved` in
`main.py`, `js/45-team.js`). The plan now lists its `assumptions:` (how Relay read the data or the request: which
column is the sales amount, a currency, a date basis, a filter) and `gaps:` (what the request or the KPI dictionary
asks for that this data cannot give), and the analyst review ("Relay's review team") adds its own and every KPI that
differs from the dictionary. At Confirm KPIs, **Review and approve** lists them in three groups (Different from your
KPI dictionary, Gaps, Assumptions), each saying where it came from (the plan or the analyst review), with a box to tick
and **Approve all**. **Confirm & build prototype** stays off until every one is approved, and the server refuses a
confirmation that leaves one out (400, with how many are left). Not approving one means saying what to change and
**Ask Relay to revise the plan** (a change, 10 credits), which brings a new list. What was approved is kept with the
dashboard (project.json `approvals`: the items, who, when) and written into request.md for the build ("The person
approved these before the build"). A plan with nothing to approve says so.

## Relay's review team

Item 68 (the user, 2026-11-19: "a multi agent where there is a developer, analyst, qa and ui/ux, story agent" and
"always there should be a ring fenced agents review on each thing prepared and approved before coming to end users.
always a multi model to ensure what comes out is 100% accurate and interactive and business ready";
`worker.team_review`, `prompts.REVIEW_*`, `js/45-team.js`). The analyst plans and the developer builds (the usual
runs), QA is the review gates, and then independent reviewers check each plan and each version before the person
sees it:

| Reviewer | When | What it checks | Model |
|---|---|---|---|
| Analyst review | each plan, before Confirm KPIs | every KPI can be computed from this data; a KPI the dictionary has matches its definition, formula, rules and time basis (else a deviation); gaps; assumptions; the model (one filter path, keys unique on the one side) | the second |
| UI/UX review | each version | a picture of every prototype page: layout, hierarchy, the right chart, readable labels and formats, the brand palette and the theme's font, titles, slicers, contrast | the builder's |
| Story review | each version | the pages tell a story in order, each answers its purpose, titles and text in business words, KPI cards with context, names from the dictionary | the second |
| Accuracy review | each version | each KPI's headline value by its own SQL against the prototype and Power BI's values (more than 0.5% apart is a must), DAX against the definitions, totals across visuals | the second |

- Each reviewer is a run of its own: a fresh session that never saw the build, in the AI engine's own `review` lane (4
  at once, `D2D_REVIEW_PARALLEL`; relay-init does not pass that setting to the AI engine yet, and a reviewer that
  finds the lane full does not wait but shows as could not run), up to 40 turns and 20 minutes; a version's three run
  side by side. Reviewers only read: the runs ask for Read, Glob, Grep and read-only
  `genbi` commands, but the AI engine gives a run that names its tools no shell (`_tool_args` in `agent/server.py`),
  so as the code stands they read files only (see the code). Anything a reviewer changed anyway is put back afterwards
  (the fence: plan.yaml, definition.yaml, the prototype, request.md, the ontology and profile files, sample.json), and
  the version says so.
- Each answers in JSON: approve or fix, a summary, what it checked, and issues marked **must** or **should** (the
  analyst also lists gaps, assumptions and deviations: "Approvals before the build").
- A **must** goes back for one fix round: the analyst's to the plan (the plan checks run again and the analyst looks
  once more); the version reviewers' to the developer, then the gates run again and those reviewers look once more. If
  the fixed version fails the gates, the version before the fixes is kept.
- A version is reviewed only once it passed the gates. The UI/UX reviewer reads a full-page picture of each prototype
  page (`.review/shots/page-N.png`, taken by the Display check: `display.check(shots=)`), the accuracy reviewer Power
  BI's values from the DAX check (`.review/values.json`).
- The **Review team** gate, after the Display check: passed when every reviewer approved; a warning for each must still
  open and for a reviewer that could not run (approval stays possible); skipped when the team did not run. A reviewer
  that cannot run never stops the build.
- On screen: the plan's **Review and approve** card, and under each version **Relay's team on this version**:
  Developer, QA (the gates), then each reviewer with what it asked for, its suggestions and what it checked.
- No credits. `RELAY_REVIEW_MODELS` (default `relay,relay-review`): the UI/UX reviewer uses the first, the others the
  second ("The AI's login and effort"). `RELAY_TEAM_REVIEW=off` (then recreate web) switches the team off.

## Ask Relay

Questions about the organisation's data in plain words (`#/askd`; `js/14-askd.js`, `css/askd.css`; `app/askd.py`,
`app/askd_routes.py`). The app runs every query itself, read-only and on every row (a dashboard built on a sample
too); the AI only writes the answer around the rows, with no tools, in the AI engine's chat lane. 10 credits pay for
up to 5 answered questions in one conversation ("Organisations and credits").

The page since item 66 (the user, 2026-11-19: "ask relay should be able to have more better ui and navigations"):
- **Your conversations**, on the left: **New question**, a search (Ctrl+K), pinned ones first, then Today, Yesterday,
  This week, This month and Earlier; each can be pinned, renamed (`PATCH /api/askd/threads/<id>`) or deleted. Pins,
  the data last chosen and the side panel's tab are kept in that browser only.
- **The conversation**, in the middle, under its own header: its name, what it asks about (all my data or one
  dashboard, fixed once it starts), when it started and how many questions, **Jump to a question** once there are two,
  rename and delete. Below it, the question box ("/" goes there; Enter asks, Shift+Enter starts a new line) and a
  meter of the questions left in the credits paid.
- **A side panel**: **Ideas** (the example questions of the organisation's industry packs, then questions from its
  dashboards' KPIs; a click puts one in the box, its send button asks it at once), **KPIs** (the KPI dictionary and the
  dashboards' KPIs, with a search) and **Data** (all my data, or one dashboard); `GET /api/askd/options` gives them.
- A new question opens on a welcome card with the same ideas and a tip on what to ask. On a phone the conversations
  and the panel open over the page (Esc closes them).

## Also in this release

- **A guided New dashboard** (item 71; the user, 2026-11-19: "title first and then data is uploaded and then what needs
  to done or built is prefilled and user can change it and confirm and it will be a guided way rather then all visible
  and one step is done then the next shows"): six steps, one on the screen at a time (`webapp/static/js/04-new.js`,
  `css/newdash.css`): **Name**, **Your data** (each file goes up in parts as soon as it is picked, with its progress,
  Cancel, Try again and Remove; the data size and the sample choice; demo data, warehouse tables and DAWB hand-offs as
  before), **What to build** (prefilled by `POST /api/projects/suggest`, `webapp/app/newdash.py`: the tables, each
  column's business term and the KPI dictionary's KPIs the data supports; no AI, no credits, seconds even for a 5 GB
  file), **Theme** (the organisation's brand; it blocks until there is one, and an owner can set it in the step),
  **Visuals** (two choices only: Power BI's built-in visuals, or built-in plus custom; a dashboard's Details tab offers
  the same two, and one made with Relay custom visuals only keeps its own) and **Check and start** (every choice and its
  credits). The draft, uploads included, is kept in the browser's session storage, so leaving for Branding and coming
  back resumes it.
- **A brand every dashboard must have** (item 72; the user: "prototype and theme needs to be set mandate before
  starting so its a step for branding and maintaining across the reporting and including fonts family";
  `webapp/app/branding.py`, `35-branding.js`): a palette (made by the Relay Model from the logo and a description, or
  one of three standard ones) and a font family (a body font and an optional heading font, from the fonts Power BI's
  Format pane lists, `POST /api/branding/fonts`). New dashboard and a DAWB import are refused (400) until the
  organisation has one; only its owners change it; the first-time tour's brand step cannot be skipped by an owner;
  `#/branding?return=new` goes back to New dashboard. request.md carries the fonts (`font`, and a heading font through
  the theme's `styles`), the build keeps them in every version, and the prototype draws in them.
- **"Relay Model" wording** (item 74; the user: "instead of mentioned like power bi desktop and running all show it
  more confidential like relay model is working, is churning data, identity and context it with the data and dashboard
  being built"): what people read says "Relay Model is reading your data", "... checking every number", "...
  packaging your Power BI file" and the like, never Power BI Desktop, this PC, the DAX checker, queues or the AI's
  vendor; a run that stops gets a plain message (`worker.friendly`), the full text staying in the server's log. The
  model's name on the screens is "Relay Model" (`config/house-models.json`; it was "Relay Model powered by Claude").
- **A guided Semantic Review** (item 75; the user: "same with semantic or existing review, uploaded or connection
  established and then a review and guide way on what is configured and fixes as well"; `40-review.js`,
  `css/review.css`): a new review in three steps (**Your KPIs**: what the dictionary holds, or continue without KPIs to
  compare models only; **Your models**: files or Power BI service models; **Check and start**: what is read, metadata
  only, and the credits), and each review as stages (Read, Check, Meaning, Values, Findings, Fix, Apply and review again)
  under a **What was configured** summary. After fixes, **Review the fixed models** starts a new review of the fixed
  files or the same Power BI models read fresh; **Review again** reads the kept models against today's dictionary.
- **The custom visuals say Relay** (item 69; the user: "review the custom visual i think its calling atlas visual, it
  should be relay and also review all custom visual possible or used in any way in retail specific and build all have
  it ready and tested"): every customer-visible "Atlas" is gone (each visual's empty-state title in Power BI, the
  package files, now `Relay<Family>.<version>.pbiviz`, the theme names, the gallery); the 13 families were rebuilt with
  their GUIDs unchanged and their versions raised; a retail set was added and tested (`visual-atlas/visuals/test/retail_*`:
  120 stores, 8 divisions, 52 weeks, billions, negative comps, blanks and long names, light and dark, checked for
  overlaps, cut text, NaN, "$0M", doubled units and contrast): the gauges' Comparison (last year) role and a
  leaderboard, and fixes to the waterfall, bullet, heat grid, calendar, columns, donut, lollipop and timeline. The one
  retail chart without its own visual is a Pareto (a Lines combo with a cumulative-percent measure does it).
- **The prototype's filters work like Power BI's** (item 76; the user: "the prototype filters and other dont work as
  expecting"; `genbi_kit/prototype.py`, `assets/prototype_page.js`, `assets/stock_visuals.js`, GENBI.md "Prototype SQL
  patterns"). A slicer or report filter now filters the model the way Power BI does (the sliced table, then the tables
  on the many side of its relationships), and each visual's SQL is written for the rows the slicers let through, like a
  DAX measure (`all_dates."T"` lifts the date slicers for last year's numbers, `main."T"` ignores every slicer). The
  page opens at the report's default selection; `genbi prototype` works out the selections a reviewer is likely to make
  (each slicer's values, then pairs, deeper) within a time and size budget (`GENBI_PROTOTYPE_SECONDS` 20,
  `GENBI_PROTOTYPE_BYTES` 12 MB), and a value outside it is greyed with the reason: the page never shows numbers it did
  not compute. Single select, Ctrl+click for several, Clear, Reset to default, keyboard; "No data" for a selection with
  no rows; no Infinity or NaN from a division by zero. Prototypes written the old way (the default year in the SQL) draw
  as before, with a badge when the selection moves. The theme's fonts are used (body, and the heading font for titles),
  and the Relay visuals get the brand's font in Power BI too (`atlas.theme_defaults`). The DAX check compares at the
  default selection (`prototype.records(con, sql, dd)`). Click to cross-filter, drill and sort are not in the prototype
  (they are in the Power BI file).

## Text people read

Everything D2D Relay shows, emails or writes into a Power BI file uses plain keyboard characters (the user's request
of 2026-11-12): a hyphen for a long dash, straight quotes, three dots, "->" for an arrow, "-" for a bullet or a
middle dot, ">" between the parts of a path. Check marks, crosses, up and down arrows, ×, ≈, ± and currency signs stay.

- New text in the code follows the same rule.
- What the AI writes is shown the same way (`genbi_kit/plaintext.py`): its notes and summaries, review notes, Ask
  Relay's answers. What people typed is shown as they typed it.
- The Power BI file gets page names, titles, subtitles, labels, text boxes, alt text, descriptions and display folders
  in plain characters (`report_builder`). Measure, column and table names are left as they are, because the report
  refers to them; the Report & accessibility gate warns about them, and the AI is told (`GENBI.md`).

## The logo

D2D has its own mark, the Striped D (the user's go-ahead of 2026-11-12): a D cut into five rows of data, the middle
row in the logo mint `#00C48C` (the decision), in the PASDACS tile. The lockup reads D2D with DATA TO DECISION under
it. The source files and rules are in `branding/pasdacs/assets/D2D` (README there).

- The rail shows the lockup (`D2D_LOGO` in `02-shell.js`); collapsed, and in the phone bar, the three-row mark
  (`D2D_MARK`) that the brand uses below 48 px. The foot of the rail names the platform: the PASDACS mark and "A Relay
  Platform product by PASDACS".
- The sign-in page shows the lockup on its dark band (`login.html`, same SVG), with the same platform line.
- Browser tabs and installed apps: `d2d-mark.svg`, `favicon.ico` (16, 32 and 48 px), `icons/d2d-180|192|512.png`,
  and `manifest.webmanifest` (D2D Relay, short name D2D). The SVG favicon is open without signing in (`auth.OPEN_PATHS`).
- Shared links (item 38): the sign-in page has a description and Open Graph and X tags, so LinkedIn, WhatsApp,
  Facebook, X and Slack show "D2D Relay: your data to a Power BI dashboard" with the share image `og/d2d-relay.png`
  (1200 x 630; source `branding/pasdacs/assets/D2D/d2d-share.html`). The tags name https://d2d.pasdacs.com, and
  `og:url` is `/login.html` itself, because `/` redirects there. `robots.txt` keeps crawlers off `/api/` and `/auth/`.
  Both are open without signing in. Any path with a `./` or `../` segment gets 404 before the sign-in check: through
  an open folder (`/fonts/../js/...`) it used to reach the signed-in app's files.
- Partner (white-label) workspaces are unchanged: their own logo, and "Powered by PASDACS Relay" with the PASDACS mark.
- The old RELAY files (`relay-mark.svg`, `relay-logo*.svg`, `icons/relay-*.png`) stay for apps installed before.

## Payments (removed, item 59)

Nothing is sold online any more (item 59, the user, 2026-11-19: "remove payment all and have only as request credits";
D2D is licensed to client organisations). More credits come only from PASDACS: Request credits, which every
organisation and personal workspace has, approved on the admin portal, or credits added by hand ("Organisations and
credits"). `app/payments.py` no longer talks to Razorpay: no checkout, no webhook (`/api/payments/webhook` is gone and
needs a sign-in like the rest of the API), no billing details, no selling settings, and no Buy credits anywhere.
Razorpay keys left in an install's `.env` are ignored; Razorpay's own account and its webhook were not touched.

What stays, as accounting records (tax law asks for eight years):
- `relay.tn_payments`, one row per checkout made while credits were sold, each paid one with its GST invoice
  (`app/invoices.py`), and PASDACS's invoice details as they were (`relay.tn_meta`, `d2d_payments`); "Bought online"
  stays in the credit history.
- **Organisation page** (`js/37-payments.js`): **Past payments**, only for an organisation that bought credits online
  before, each with its invoice (or receipt, for one paid before invoices) to print or save
  (`GET /api/payments/<id>/receipt`); owners see all of them, others their own.
- **Admin portal, Payments** (read only): every past payment with its organisation, who paid, the credits, amount,
  status, invoice and Razorpay's ids, the real ones' totals, and **Invoices for GST returns**: a financial year's
  invoices as CSV for the accountant (`/api/admin/payments/invoices.csv?fy=26-27`; test invoices only when asked).
- Checkouts never paid are still deleted after a year (the nightly sweep); an erased organisation's payments stay
  without names; each person's own payments are in Download my data.

How selling worked (from item 23: Razorpay's checkout and webhook, GST invoices, rupees in India and dollars
elsewhere, test and live keys) is in this guide's git history before item 59 and in the work log (`docs/LOG.md`,
"Selling credits online"). The terms of service, the refund and cancellation policy and the privacy notice still
describe buying online and Razorpay: they are the lawyer-reviewed pages, for the user and the lawyer to update ("Legal
pages").

## The AI's login and effort

(Until item 67 this section was "The AI's Claude account".)

**The Relay Model, Claude Opus 5.5** (item 47, the user, 2026-11-14: "in API use opus 5.5 as default and same in
personal as well dont use any other model for Relay Model powered by claude"): every run, dashboards, changes, Ask
Relay and Relay Doctor, asks for the Relay Model, which the AI engine serves with `claude-opus-5-5`
(`config/house-models.json`) on the subscription and on the API key alike; a run that names no model gets it too (the
engine's default, `relay`), and the catalog's own default is `claude-opus-5-5`. Opus 5.5 costs $4 / $20 per million
input / output tokens on the API, twice Sonnet 5.5, so the key's monthly limit ($150) lasts for about half as many
builds. **A second model reviews** (item 68): `relay-review` ("Relay Model (reviewer)"), served with
`claude-sonnet-5-5` and hidden from every model picker (`"hidden": true`; the AI engine still accepts it), runs the
analyst, story and accuracy reviews ("Relay's review team"). `config/house-models.json` is mounted from the deploy
folder (`./config`, read only), so it changes with the deploy folder's git.

**Builds side by side** (item 46, the user, 2026-11-14: "Add parallel builds"): up to `RELAY_BUILD_PARALLEL` (3)
dashboard runs at once, each in a job container of its own, never two of one dashboard; more wait in the queue, which
shows each organisation only its own jobs (item 45). Publishing (the DAX check and the .pbix, Power BI on this
PC) runs one at a time on its own lane, outside those three. Customers cannot stop a waiting or running build.
Relay's reviewers have a lane of their own on the AI engine, `review` (4 at once, each in a job container too), and
Ask Relay's chat lane takes one at a time.

**The login first, the key as its backup** (item 67, the user, 2026-11-19: "internally switch the agent to use
subscription from docker on opus 5.5 max"). The AI engine runs Claude Code, signed in to the Claude subscription in
Docker (the `claude-api-auth` volume; `docs/LOG.md`, "The AI's Claude plan"). Every dashboard run and Ask Relay
question runs on that login first (`app/providers.py`). `RELAY_ANTHROPIC_API_KEY` in the live `.env` is the backup:
when the subscription fails with an authentication, limit or outage error, the run goes once more on the key, given to
that run only as its own `ANTHROPIC_API_KEY` (dashboards: `worker.agent`; Ask Relay: `askd._claude`), with an
`ai.fallback` audit record and a note in the dashboard's activity. Each run records which one answered (`provider`:
"Claude (this installation's login)" or "Anthropic API (this installation's key)"). From item 42 (2026-11-13: "claude
api key ... as primary and personal as backup") to item 67 it was the other way round; `RELAY_AI_PRIMARY=api` puts the
key first again. Without a key there is no backup.

**Effort** (item 67). Each run carries Claude Code's effort level (`--effort`, `agent/server.py`): every dashboard run
(plans, builds, changes and the reviewers) at `max` (`RELAY_AGENT_EFFORT`: low, medium, high, xhigh or max), and Ask
Relay and the other answers someone waits for (a KPI changed in words, Semantic Review's meaning check and fixes,
brand palettes) at `high` (`RELAY_CHAT_EFFORT`).

The key: create one in the Anthropic Console (API keys), set a monthly spend limit there (the API bills per token), add
`RELAY_ANTHROPIC_API_KEY=sk-ant-...` to the live `.env` by hand, then
`docker compose up -d --no-deps --force-recreate web admin`. Never name it `ANTHROPIC_API_KEY` in the `.env`: the AI
engine takes `ANTHROPIC_*` variables for itself (`relay_init.AGENT_PREFIXES`), would then use the key for every run,
and the subscription would never be used. Empty again = the subscription only, with no backup.

## Bot check

Since item 40 (the user, 2026-11-13: "bot check add back", while anyone could sign up; it still keeps scripts from
asking for codes) "Email me a code" on the public site can need Cloudflare Turnstile (`app/otp.py`, `login.html`): the widget sits under the form, and the server checks
its token with Cloudflare (siteverify) before a code is made or sent. A token works once (the page resets the widget
after each ask). A missing or refused token gets 403 and no code; if Cloudflare cannot be asked, 503 and no code. The
per-address and per-network limits below still apply. The admin portal never shows it.

To switch it on:

1. Cloudflare dashboard, **Turnstile**, **Add widget**: a name (e.g. "D2D Relay sign-in"), hostname
   `d2d.pasdacs.com`, widget mode **Managed**, no pre-clearance. Create it and copy its two keys.
2. In the live `.env`: `RELAY_TURNSTILE_SITE_KEY=` (public: it is sent to every browser) and `RELAY_TURNSTILE_SECRET=`
   (secret: typed in by hand, never in commits).
3. `docker compose up -d --no-deps --force-recreate web` (a plain `restart` keeps the old values). Both keys empty
   switches it off the same way.

The test stack runs with Cloudflare's published test keys (always pass: `1x00000000000000000000AA` and
`1x0000000000000000000000000000000AA`); the suites send a token with every code they ask for (`d2d_checks.Person`).

## The code on the screen

Since item 57 (the user, 2026-11-18, for demos on the live install once its Cloudflare tunnel was removed: "add a
option to show the otp in the screen itself as all is local not in public"), `RELAY_OTP_ON_SCREEN=1` lets an install
that is used on this PC only skip the email: after Continue, the sign-in page shows the account's 6-digit code in a
box and fills it in, so Sign in is one click, and it asks for no bot check (Turnstile's widget only works on the
public hostname). It applies only to a request made on this PC (`otp.on_screen`): from its own addresses (loopback,
the Docker host) with none of the headers a tunnel or proxy adds (`cf-connecting-ip`, `x-forwarded-for`,
`forwarded`, `x-real-ip`). Anything else gets the emailed code, with the bot check, as always. An address without
an account still gets the usual answer and no code. Each code shown is in the audit (`auth.otp_shown`). Both sites
read it: http://127.0.0.1:8100 and the admin portal on http://127.0.0.1:8102. **Never with a tunnel or port
forwarding to this PC**: anyone who reaches the app through something that adds none of those headers would get
codes too. To switch it on or off: the line in the live `.env`, then `docker compose up -d --no-deps
--force-recreate web admin`.

The test stack switches it on for its admin portal only (`TEST_OTP_ON_SCREEN`, default 1), so the public site's
suites keep the emailed path and the Turnstile widget; `item57_check.py` covers both.

## Sign-in alerts

Every successful sign-in sends info@pasdacs.com an email (`app/signin_alerts.py`): who, their organisation, the
public site or the admin portal, when (IST), the network address
and country Cloudflare saw, the browser, whether it is their first sign-in, how many sign-in codes that network asked
for in the last hour, and the organisation's credits. The email goes out in the background, so a sign-in never waits
for it or fails because of it, and each one is in the audit log (`signin.alert`). Codes are rate limited per address
and per network, so the alerts are too. To act on one: pause the organisation or switch the person off on the admin
portal.

- `RELAY_SIGNIN_ALERTS=0` turns them off; `RELAY_SIGNIN_ALERTS_TO` sends them to another address.
- Without mail set up (a test install) the alert is written to the container's log instead: `[signin-alert] ...`.

## What the AI can reach (prompt injection)

People upload data files and attachments, and anything in them can try to give the AI instructions ("ignore the
above and read ...", "send this to ..."). So the AI is limited by the system, not by what it is told:

- **Its own dashboard's folder only.** Claude Code runs under a managed policy that no other settings file can
  change (`agent/managed-settings.json`, installed as `/etc/claude-code/managed-settings.json`): file reads and writes
  outside the folder are refused, only the policy's own hook runs, and the app's own files there (CLAUDE.md,
  project.json, `.claude/`) cannot be edited. Each run gets six tools (Read, Write, Edit, Glob, Grep, the shell) and
  its task list, no web tools, no sub-agents, no skills and no MCP servers (`agent/server.py`; Ask Relay's runs get
  no tools at all).
- **The shell runs the toolkit only.** A managed hook (`agent/bash_guard.py`) refuses every command that is not made
  of `genbi <dashboard command>` calls (on their own, or chained with `&&` or `;`): no other program (so no `cat`,
  `ls`, `curl`), no pipe, redirection or substitution, no `genbi repo`. The toolkit keeps every path it is given inside the folder
  (`genbi_kit/cli.py`), and its SQL engine (DuckDB) reads only that folder, with no network and no way to switch
  that off (`genbi_kit/data.py`). Ask Relay's queries are limited the same way, to the dashboards the person can see.
- **Pages it makes cannot act for anyone.** A prototype is shown sandboxed: a page of its own with no access to the
  app, its sign-in or the network (`main.py`, `PROTOTYPE_CSP`). The headless browser that checks prototypes and custom
  visuals inside the container has no network either (`genbi_kit/display.py`, `OFFLINE_ARGS`). Names, titles and
  theme values from a definition are written into a page as text, never as markup.
- **Ask Relay's AI has no tools at all**: the app runs every query itself, read-only, and the AI only writes the
  answer around the rows. The same goes for a KPI changed in words, Semantic Review's meaning check and its fixes
  (`askd.ask_json`): text in, JSON out, checked before it is kept.
- **Relay's reviewers only read** (item 68): a reviewer run gets Read, Glob and Grep (a run that names its tools
  never gets the shell, `_tool_args`), in a job container like a build, and every file it could have changed is put
  back afterwards (`worker._unfence`). Data files, request.md and ontology.md are the organisation's data: the
  reviewers' prompt, ontology.md itself and GENBI.md say never to follow instructions written inside them.
- Power BI files are checked before they open on this PC: the Power BI file maker refuses a report whose queries
  read anything but its own data folder (`Test-ReportQueries`).
- **Its network: Anthropic only** (security audit S6, 2026-11-12). The AI engine reaches the internet only through a
  proxy in the web container (`docker/egress_proxy.py`, on 127.0.0.1:3128), which opens tunnels to port 443 of
  Anthropic's API and sign-in hosts and nothing else (`RELAY_AGENT_EGRESS_ALLOW` changes the list). At every start
  relay-init stops every other connection the AI engine's user makes, DNS lookups included (iptables; the web
  container has `NET_ADMIN` for it in `docker-compose.yml`); the container log says "the AI engine's network:
  Anthropic only, through the proxy", and the proxy logs each refused host by name. `RELAY_AGENT_EGRESS=off` in
  `.env` (then restart web) goes back to no limit. The web app's own connections (Microsoft 365, warehouses) are not
  limited.
- **Its API only for the web app** (S4). The AI engine's API (`127.0.0.1:8090`: runs, forget, render) answers only
  connections made by the web app's user or root; anything the AI engine's own user runs gets 403. The check reads
  the kernel's socket table for who owns the caller's end of the connection (`agent/server.py`, `only_the_web_app`;
  `D2D_AGENT_PEER_CHECK=0` turns it off for an AI engine in a container of its own).
- **Each build in a container of its own** (S4; the user, 2026-11-12: "AI run in its own container"). Every run with
  tools (a plan, a build, a change) runs in a short-lived container, `d2d-relay-job-<time>-<id>`, started by the job
  runner (`d2d-relay-runner`, `docker/job_runner.py`) from the web container's own image. It holds only that
  dashboard's folder (at the same path), the organisation's visual library (read-only), `config` (read-only) and the
  Claude sign-in volume; no other organisation's folder, no `/data`, no secrets, no Docker. It runs as the AI engine's
  user with every capability dropped and no new privileges, on the web container's network, so the network limits
  above and the API guard apply to it too. The runner is the only part with Docker's socket: it has no network at
  all and answers only on a Unix socket that the web container's AI engine alone can open (`runner-sock` volume, mode
  600, owner agent); it accepts only a `claude` command in a dashboard folder, streams the run back, and stops and
  removes the container when the run ends or is stopped (and, at its start, any left from a crash). Its log names
  every job and what it holds. Ask Relay's runs (no tools at all) stay in the AI engine. `RELAY_JOB_CONTAINERS=off`
  (then restart web) runs builds in the AI engine as before. Still shared between runs: the Claude sign-in volume,
  which also keeps the run transcripts (a long-lived token from `claude setup-token` would let jobs run without it).

## Legal pages

Four pages open without signing in, written from what the app does (not by a lawyer: have them reviewed):

| Page | Says |
|---|---|
| `/terms.html` Terms of service | the service, accounts and organisations, credits and payment, your data (with data processing terms), fair use, availability, liability (at most what was paid in the last 12 months), ending, changes; Indian law, courts at Bengaluru, Karnataka (the user's choice, 2026-11-12) |
| `/refunds.html` Refund and cancellation policy | no refunds and no cancellations (the user's rule); delivery of credits; credits back when a run does not finish; payment errors put right within 30 days |
| `/contact.html` Contact | info@pasdacs.com, the requests made from inside the app, privacy requests and complaints |
| `/privacy.html` Privacy notice | (item 22) |

They are linked from the sign-in page ("By signing in you accept the terms of service"), each other's footers and the
organisation menu (Terms, refunds and contact). The invoices and receipts of past payments say "Credits are not
refundable, and a purchase cannot be cancelled once paid." Since item 59 nothing is sold online: the contact page no
longer mentions payments or Buy credits, but the terms, the refund and cancellation policy and the privacy notice
still describe buying credits online through Razorpay (and Semantic Review, the ontology and the AI's newer work are
not in them yet). They are the lawyer-reviewed pages: for the user and the lawyer to update, with the client licences.

## Data governance

What D2D Relay keeps, who sees it, and how it goes (`app/governance.py`; the customer-facing version is the privacy
notice, `/privacy.html`, linked from the sign-in page, the profile menu and Organisation > Your data).

| What | Where | Who sees it | Kept | How it goes |
|---|---|---|---|---|
| People, organisations, roles | database: the organisation's schema; accounts and credits in the control plane | the person, their organisation's owners; PASDACS on the admin portal (organisations, credits, requests only) | while the organisation exists | an owner removes a person; PASDACS erases an organisation (below) |
| Dashboards: uploads, extracts, plan, versions, prototypes, Power BI files, activity log | `data\projects\.tenants\<organisation>\<dashboard>` | the owner, people it is shared with, the organisation's owners | until deleted | Delete on the dashboard page (its owner or an owner of the organisation) |
| Ask Relay conversations | database | the person who asked | until deleted | Delete conversation in Ask Relay; deleting a dashboard deletes the conversations about it |
| Ask Relay's answer cache | database | nobody (reused for the same question) | 7 days | nightly sweep; deleted with its conversation or dashboard |
| Semantic Review (item 55): files uploaded for a review | `data\projects\.tenants\<organisation>\.semreview\<review>` (never in backups) | nobody | until read: seconds | deleted as soon as the model is read; the folder after the review; all of them when the site starts |
| Semantic Review: the KPI dictionary, reviews (findings) and the models they read (metadata: names, DAX, formats; no data, Power Query or roles) | database: the organisation's schema | everyone in the organisation | until deleted | Delete on the review (whoever ran it or an owner); KPIs deleted one by one or replaced by an import |
| Semantic Review's Power BI app secret | `secrets.enc` of the organisation, encrypted | nobody: the app uses it | while connected | Remove under Semantic Review > Connection (an owner) |
| The AI engine's transcripts (Claude Code) | `claude-api-auth` volume, `/home/agent/.claude/projects` | PASDACS, on this PC | Ask Relay: deleted once the answer is given; dashboards: at most 7 days | deleted with the dashboard; nightly sweep; Claude Code's own `cleanupPeriodDays` (managed settings, which also switch auto-memory off) |
| Audit trail, sign-in records, sign-in codes (hashed) | database | the person (Download my data); PASDACS | 1 year | nightly sweep |
| Warehouse passwords and keys | `data\state\tenants\<organisation>\secrets.enc`, encrypted | nobody: the app uses them | while the connection exists | removing the connection |
| Payments for credits, made before item 59 stopped selling (no card or bank details: those stayed with Razorpay) | control plane, `relay.tn_payments` | the buyer, the organisation's owners; PASDACS on the admin portal | paid: eight years (accounting); never paid: 1 year | nightly sweep for the unpaid; an erased organisation's stay without names |
| The ontology (item 61): business terms and the industry packs applied | database: the organisation's schema (`onto_terms`, meta `ontology`) | everyone in the organisation | until changed | a BI Dev or owner removes terms; erasing the organisation |
| Uploads in parts (item 64) | `data\projects\.tenants\<organisation>\.uploads\<id>` (never in backups) | nobody: the form that names it reads it | until the form uses it, at most a day | removed by the form; one older than a day when the next upload starts |
| Nightly backups | `data\backups\d2d-*` | PASDACS | 14 nights | rotated |
| Database copies made by hand (`relay-ctl db-dump`, `export`) | `data\backups\*.dump`, `relay-export-*` | PASDACS | 30 days | nightly sweep: copy one elsewhere first if it must stay |
| Container logs | Docker | PASDACS | 5 × 20 MB per container | rotated; they hold user ids, never query strings, bodies or codes |
| Sign-in alert emails | the info@pasdacs.com mailbox | PASDACS | the mailbox's own rules | set a retention rule on that folder in Microsoft 365 |

Settings: `RELAY_LOG_KEEP_DAYS` (365), `RELAY_ASKD_CACHE_DAYS` (7), `RELAY_DUMP_KEEP_DAYS` (30). The sweep runs every
night after the backup, and on demand:

```
docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.governance sweep
```

Requests from people (India's DPDP Act 2023 and its Rules of 2025; most duties apply from 13 May 2027; answer within
30 days and settle every grievance within 90):

- **See my data:** Organisation > Your data > Download my data (a JSON file: profile, sign-ins, dashboards,
  conversations, credit requests, payments, a year of activity). Each dashboard's Power BI file and data download
  from it.
- **Delete a dashboard or a conversation:** the person does it themselves.
- **Remove a person:** an owner removes them on the Organisation page; they can no longer sign in. Their name and
  address stay in the audit trail for the year the law asks for.
- **Erase an organisation** (only on a written request from its main owner's address): on the admin portal, note
  its id and exact name (Organisations), then, in the D2D Relay folder:

  ```
  docker exec -u relay -w /srv d2d-relay-web /opt/relay/bin/launch web python -m app.governance erase-org <id> "<exact name>"
  ```

  It refuses while a dashboard run is in progress or waiting, and refuses the platform's own workspace. It drops the
  organisation's database schema, its folders, secrets, visual library and the AI engine's transcripts, removes its
  people's accounts (they are signed out, and their addresses are free to be added again), keeps the credit history
  and its payments without names, emails or messages, and records `d2d.org_erased`. The nightly backups hold it for
  14 more days.

If personal data may have leaked: report to CERT-In within 6 hours of noticing (incident@cert-in.org.in, in force
today), tell the people affected without delay, and from 13 May 2027 report to the Data Protection Board within 72
hours. What happened is in the audit trail, the sign-in alert emails and the container logs.

## Deployment

**This install, for a client trial (planned, items 59 to 68 and 73).** The release goes out from this PC as before
("Updating", below), and the app is then reachable again through the Cloudflare tunnel, at https://demo.pasdacs.com,
with the sign-in code by email:
1. In the live `.env`: delete `RELAY_OTP_ON_SCREEN` before the tunnel starts (never with a tunnel: "The code on the
   screen"); set `RELAY_PUBLIC_URL=https://demo.pasdacs.com` (the address in every email from both sites; the admin
   portal gets it as `RELAY_SITE_URL`); the Razorpay keys are no longer read (item 59).
2. In Cloudflare (the user): the tunnel's public hostname `demo`, domain `pasdacs.com`, service HTTP, URL
   `d2d-relay:8000` (the web container), and `demo.pasdacs.com` added to the Turnstile widget's hostnames ("Bot
   check"), or the sign-in page's bot check fails there.
3. `config/house-models.json` has the reviewers' model, `relay-review` (item 68); it comes with the deploy folder's
   fast-forward, as `./config` is mounted from there. New tables and columns (`relay.tn_org_domains`, `onto_terms`,
   `semreview_runs.fixes`) are made at start.
4. `docker compose --profile tunnel up -d`; then, on the admin portal on this PC, New organisation for the trial:
   its main owner, its second email domain, its starting credits and its industry pack.

The steps as they stand, with what to check, are in the work log (`docs/LOG.md`, "Waiting for the next deploy").

**Dashboards to the Power BI service and GitHub (item 70, `webapp/app/deploy.py`).** Today a published dashboard
is a .pbix to download ("Power BI file maker"). Being added for this release, set up once by an owner
(`/api/deploy/settings`), no credits:
- **The Power BI service:** the dashboard's .pbix uploaded to a workspace the owner picks, with the Power BI REST API's
  Imports, as the organisation's own Entra app (the one Semantic Review uses, with Member or Contributor on the
  workspace; `POST /api/projects/<id>/deploy/powerbi`). A model made from uploaded files carries its data as it was
  when the file was made: a refresh in the service needs the data reachable from there (a warehouse, or a gateway).
- **GitHub CI/CD:** a repository, branch, folder and fine-grained token (kept in the secrets store, never shown
  again). **Push to GitHub** commits the dashboard's Power BI project (Fabric's Git format, never data files) under
  `<folder>/<dashboard>/` (`POST /api/projects/<id>/deploy/github`), and once per repository a GitHub Actions workflow
  (`.github/workflows/d2d-relay-deploy.yml`, from `templates_deploy/`) that deploys changed dashboards to a Fabric
  workspace with Microsoft's fabric-cicd and a service principal from the repository's secrets.
- Both can also run on their own once a Power BI file is made (an owner's setting; the worker calls `deploy.after_pbix`
  after every .pbix, which never stops the dashboard: a failure is shown on it). Each publish or push is recorded
  (`deploy_runs`; deleting a dashboard deletes them), and the hosts are fixed (`D2D_POWERBI_API`, `D2D_GITHUB_API`).
  The screens: two connectors on the Connections page, **Power BI service** and **GitHub**, under Deployment (item 77;
  the user, 2026-11-19: "github is a connector [that] needs to be available for the customer to configure ci/cd and
  auto deployment to power bi service"): every organisation has them, without PASDACS switching them on; owners set
  them up (the Entra app, the workspace and automatic publishing; the repository, its token and automatic pushing),
  everyone else reads them; the Organisation page points there. And a Publish / Push card on a finished dashboard with
  its history (`44-deploy.js` `deployConnectorCards`, `12-connections.js`, `css/deploy.css`). A token needs Contents read and write,
  and Workflows read and write for the workflow file (without it the dashboard is still pushed, and the run says why).

## Updating

Build from a clean commit and restart while nothing is running (a restart of `d2d-relay-web` cuts off a build):

```
git status            # clean
set RELAY_COMMIT=<git rev-parse HEAD> && docker compose build web && docker compose up -d
```

`docker compose up -d` starts again only the containers whose image or settings changed; a change for the admin
portal alone can go out with `docker compose up -d admin` while builds run on the public site.
