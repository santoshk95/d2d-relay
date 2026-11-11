# D2D Relay

D2D Relay is the dashboard part of RELAY by PASDACS, run as a separate product for a client. A person brings CSV files
and describes the dashboard. D2D Relay plans it, agrees the KPIs, builds a prototype and reviews it. The result is a
checked Power BI project (PBIP). Warehouses and databases are connected by PASDACS for an organisation on request.

It is separate from RELAY. It lives in its own folder (`Downloads\D2D Relay`) with its own git repository. It has its
own image (`d2d-relay:latest`), container (`d2d-relay`), database volume (`d2d-relay-data`), projects folder
(`data\projects`), DAX checker queue and sign-in. Only the Claude sign-in volume (`claude-api-auth`) is shared, so both
apps use the same Claude subscription.

| | |
|---|---|
| Public address | https://d2d-relay.pasdacs.com (Cloudflare tunnel) |
| On this PC | http://127.0.0.1:8100 |
| Sign-in | a 6-digit code emailed to any **business** address (no passwords, no SSO); free and disposable mail refused |
| Organisations | one per email domain, each in its own workspace; the first person creates and owns it |
| Credits | 100 per organisation to start; a new dashboard uses 30, a change 15 (see "Organisations and credits") |
| Platform admin | **info@pasdacs.com**: Administration and Organisations (every organisation, adding credits) |
| Code sender | info@pasdacs.com through Microsoft Graph (delegated Mail.Send, signed in once) |
| Data sources | CSV / flat files (New dashboard → upload), or demo data Relay generates. Connectors (BigQuery, Snowflake, Fabric, Redshift, Athena, Oracle) only once PASDACS switches them on for the organisation (see "Connectors") |

## What was kept and what was switched off

`webapp/app/edition.py` is the one place that decides this.

- **Kept:** Dashboards (D2D: plan → KPIs → prototype → review → PBIP), the review gates and the Power BI engine
  check, the visual library, sample data, Connections (connectors on request), Ask Relay, Branding, organisations
  and credits.
  Administration's APIs stay for the platform admin only (not in the menu).
- **Switched off:** all other modules (process, automation, systems, AI, consulting), schedules, pages, the
  semantic layer, the service desk, Migrate BI, self-healing, AI SDLC, the workbench and the tenants console. Their APIs
  answer 404 and their background pollers do not start. Old links open the dashboards list.

## Start and stop

```
docker compose up -d                       # the app only (this PC)
docker compose --profile tunnel up -d      # the app + the public tunnel
docker compose --profile tunnel down       # stop both (data stays in the volume and data\)
docker logs -f d2d-relay
```

Start the DAX checker for D2D Relay too (it watches `data\projects\.daxcheck`, not RELAY's queue). Run
`daxcheck\start-daxcheck.cmd`. It runs side by side with RELAY's checker.

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
   docker exec -it -u relay -w /srv d2d-relay /opt/relay/bin/launch web python -m app.otp_mail login
   ```

   Check it with `... python -m app.otp_mail status`, or send yourself a test with `... python -m app.otp_mail test`.

The sign-in is kept encrypted in the app's secrets store, in the d2d-relay-data volume. The app uses it once a day, so
Microsoft never ends it for being unused. If info@pasdacs.com's password changes, or an admin revokes its sessions,
run `login` again. If a sign-in policy blocks device-code sign-in, an admin can allow it for this one app.

For a local test only, set `RELAY_OTP_DEV_LOG=1` and codes are printed in `docker logs d2d-relay` instead. This is
ignored once mail is set up.

Code rules: 6 digits, valid for 10 minutes, 5 tries. Per address: 1 code a minute and 6 codes an hour. Per network
(Cloudflare's `cf-connecting-ip`): 20 codes an hour. Only a salted hash is stored. A session lasts 12 hours
(`RELAY_SESSION_HOURS`).

`RELAY_OTP_EMAIL` (and `RELAY_ADMIN_EMAIL`) is the platform admin's address, info@pasdacs.com. It signs in to the
platform's own workspace, the organisation "PASDACS".

## Organisations and credits

Anyone with a business email address can sign in. Free and disposable mail (Gmail, Outlook, Yahoo, iCloud, Proton,
Mailinator …) is refused; add or allow domains with `RELAY_PUBLIC_DOMAINS_EXTRA` / `RELAY_PUBLIC_DOMAINS_ALLOW`
(comma-separated).

- **The first person from a domain** names their organisation after the code and becomes its owner. They then see the
  first-time setup: the brand (logo, description, palette), which they can skip. Everyone who signs in later from
  the same domain joins that organisation, and the owner is told.
- **Each organisation is its own workspace.** Dashboards, connections, branding, Ask Relay conversations and people
  are never visible to another organisation. Inside one, each person's dashboards are private until shared; the owner
  can open them all.
- **Credits are shared** by everyone in the organisation. The top bar shows the organisation and its credits;
  Organisation (`#/org`) shows the owner, the people, the costs and the credit history.

| What | Credits |
|---|---|
| Start | 100 (`RELAY_CREDITS_START`) |
| New dashboard (plan, KPIs and first prototype) | 30 (`RELAY_CREDITS_DASHBOARD`) |
| A change: revise the plan, a change request, building a suggested custom visual, an Ask Relay answer sent to a dashboard | 15 (`RELAY_CREDITS_CHANGE`) |
| Confirming the plan, fixing failed review gates, approving and publishing, Ask Relay questions, brand palettes | free |

A request without enough credits is refused before anything starts, with the balance in the message. When a run
fails, is stopped, or is cut off by a restart, its credits come back on their own; Retry then uses them again. Every
AI cost is still recorded on the server (the `usage` table); the screens show no tokens and no cost breakdown. Ask
Relay shows only a conversation's overall cost.

**Adding credits.** Online payment is not built yet. "Add credits" sends a request to info@pasdacs.com
(`RELAY_CREDITS_CONTACT`) from the code mailbox, with the organisation, the person and the amount, and Reply-To set
to the person. It also shows a prefilled email link. When the payment is agreed, the platform admin opens
**Organisations** (`#/orgs`), clicks **+ Credits** for the organisation and writes why (for example the invoice);
the organisation sees it in its credit history. A negative number takes credits back.

### 2. Public address (Cloudflare tunnel)

pasdacs.com's DNS is on Cloudflare, so no port is opened on this PC.

1. In Cloudflare, go to **Zero Trust → Networks → Tunnels → Create a tunnel** (type Cloudflared) and name it
   `d2d-relay`. Copy the token from the "Install connector" step.
2. In the tunnel, go to **Public hostname → Add**. Set subdomain `d2d-relay`, domain `pasdacs.com`, service
   **HTTP**, and URL `d2d-relay:8000`.
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
2. When it is agreed, the platform admin opens **Organisations**, clicks **Connectors** for the organisation and ticks
   the ones to switch on. The owner is told, and the organisation can then add connections for them (and pick
   "From a warehouse" on New dashboard).
3. Switching a connector off stops it at once for that organisation: its connections stay but cannot be tested,
   queried or pulled from, and scheduled refreshes pause with a note on the dashboard. They can still be removed.

PASDACS's own workspace has every connector switched on. For BigQuery, the simplest way in for a client is a
service-account JSON (roles BigQuery Data Viewer + BigQuery Job User). Queries are read-only and limited to 1 GB
scanned by default.

## Updating

Build from a clean commit and restart while nothing is running:

```
git status            # clean
set RELAY_COMMIT=<git rev-parse HEAD> && docker compose build && docker compose up -d
```
