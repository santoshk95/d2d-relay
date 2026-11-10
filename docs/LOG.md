# D2D Relay: work log and hand-over

Last updated: 2026-11-10 (IST). This file says where the project stands for anyone who clones it.

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
8. **AI cost.** `GET /api/askd/costs` returns the month by work type and the cost of one conversation. Today Ask
   Relay shows the cost on each answer plus a cost panel, and the Dashboards page has a cost line. This is to be
   changed; see the next section.

Test data in the live install: the dashboards "D2D smoke test" and "Brand palette test". A user uploaded their own logo
(JPEG) on Branding but has not picked a palette yet; leave it.

## NEXT: the user's request of 2026-11-10 (not started)

The user's words, condensed:

1. **AI cost display.** Do not show the cost of each answer. Show only the conversation's overall cost. Show no tokens
   and no cost breakdowns anywhere (also remove "2.29M tokens · $2.14" on the dashboard page and the cost line on the
   Dashboards list). Costs are logged on the backend only (the `usage` table already records them).
2. **First sign-in setup.** On a person's first sign-in, ask them to **create an organisation**, then show **brand
   setup** (the Branding flow), so everything is configured once at the start.
3. **Credits.**
   - Every organisation starts with **100 credits**.
   - A **new dashboard costs 30 credits**. A **change** (change request / revision) **costs 15 credits**.
   - Refuse with a clear message when there are not enough credits, and show the balance.
4. **Add credits.** A button that will later go to payment. For now it says "coming soon" and offers a contact
   form/mail to info@pasdacs.com, prefilled with the organisation, the person and the amount.
5. **Organisations.**
   - People from the **same organisation pool their credits**, and the screen shows **who the organisation's owner
     is** (the first person from that organisation).
   - **Do not allow public email domains** (gmail, yahoo, outlook/hotmail/live, icloud, aol, proton, gmx, yandex,
     zoho mail, rediffmail, qq/163, disposable mail …) to sign in or sign up.
   - This replaces the single allowed address: sign-up becomes open to business email domains. Keep
     info@pasdacs.com as the platform admin.

### Design notes from the first look (2026-11-10)

- **Isolation matters.** Today every user is in the platform tenant and the Default team. Admins see all projects,
  `/api/directory` lists everyone, and Ask Relay's "team" scope covers the team's dashboards. Two client
  organisations in one tenant could see each other.
- **Recommended: one tenant per organisation**, using the P17 tenancy that already exists.
  - `tenancy.create()` (webapp/app/tenancy.py ~334) makes the tenant row, its own schema (`db.init_tenant`) and its
    own project folder (`store.root()` gives `.tenants/<tid>`).
  - It needs a platform-admin user and an `admin_email`, and returns a setup link. Factor out a function that makes
    an organisation's tenant from the OTP sign-up (no setup link; the first person becomes the org owner as
    `org_role 'admin'` of THAT tenant only).
- **Sign-in in the right tenant.** OTP verify must look up the organisation by email domain, `db.use(tid)`, create or
  find the user there, and call `identity.create_session` inside that tenant, so the cookie carries `<tid>~<sid>`
  (`identity.cookie_value`). `auth.home_of` already handles the `otp` mode like `sso`.
- **Credits.** Keep them in a platform-level table (for example `relay.d2d_orgs(tenant_id, name, domain unique,
  owner_user_id, credits, created)` plus `relay.d2d_credit_log(org, user, delta, reason, object, ts, balance)`).
  - Charge 30 in `main.create_project` and 15 where a change request or revision is accepted (find the revise route
    in main.py / worker; charge only when the run is queued).
  - Refund when a run fails before producing a version (decide and log).
- **Branding per organisation.** `branding.py` keeps one brand per install (meta key) and must become per tenant. The
  meta table is per tenant schema, so it may already work inside `db.use(tid)`; check this.
- **Check per-tenant behaviour:** the DAX checker queue, the agent workdir (`store.rel`), Ask Relay, and module
  entitlements (`tenancy.effective` for the new tenant's edition must keep the dashboard modules on).

## Hand-over rules for this repository

- Work in this repository only; never change RELAY (the `Gen BI` folder) to serve D2D Relay.
- AI work runs one at a time; do not start several agents in parallel.
- Before a redeploy, check that nothing is running for a user. A restart kills a running dashboard build.
- Secrets live only in `.env` and `tunnel.env` (both git-ignored), never in commits.
