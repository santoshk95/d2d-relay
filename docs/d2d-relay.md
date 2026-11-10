# D2D Relay

D2D Relay is the dashboard part of RELAY by PASDACS, run as a separate product for a client. A person brings CSV files
or connects Google BigQuery and describes the dashboard. D2D Relay plans it, agrees the KPIs, builds a prototype and
reviews it. The result is a checked Power BI project (PBIP).

It is separate from RELAY. It lives in its own folder (`Downloads\D2D Relay`) with its own git repository. It has its
own image (`d2d-relay:latest`), container (`d2d-relay`), database volume (`d2d-relay-data`), projects folder
(`data\projects`), DAX checker queue and sign-in. Only the Claude sign-in volume (`claude-api-auth`) is shared, so both
apps use the same Claude subscription.

| | |
|---|---|
| Public address | https://d2d-relay.pasdacs.com (Cloudflare tunnel) |
| On this PC | http://127.0.0.1:8100 |
| Sign-in | a 6-digit code emailed to **info@pasdacs.com** only (no passwords, no SSO) |
| Code sender | info@pasdacs.com through Microsoft Graph (app-only Mail.Send) |
| Data sources | CSV / flat files (New dashboard → upload) and Google BigQuery (Connections) |

## What was kept and what was switched off

`webapp/app/edition.py` is the one place that decides this.

- **Kept:** Dashboards (D2D: plan → KPIs → prototype → review → PBIP), the review gates and the Power BI engine
  check, the visual library, sample data, Connections (BigQuery only), Settings and Administration.
- **Switched off:** all other modules (process, automation, systems, AI, consulting), Ask D, schedules, pages, the
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

1. In Microsoft Entra admin center, go to **App registrations → New registration**. Name it "D2D Relay sign-in mail",
   single tenant, with no redirect URI.
2. Under **API permissions → Add → Microsoft Graph → Application permissions**, add **Mail.Send**, then click
   **Grant admin consent**.
3. Under **Certificates & secrets → New client secret**, copy the value.
4. Limit the app to the one mailbox. In Exchange Online PowerShell, run:

   ```
   New-DistributionGroup -Name "D2D Relay senders" -Type Security -Members info@pasdacs.com
   New-ApplicationAccessPolicy -AppId <client id> -PolicyScopeGroupId "D2D Relay senders" -AccessRight RestrictAccess -Description "D2D Relay sends codes only as info@pasdacs.com"
   ```

   (Microsoft now also offers RBAC for Applications for this. Either way works.)
5. Put the tenant ID, client ID and secret in `.env`: `RELAY_OTP_MS_TENANT`, `RELAY_OTP_MS_CLIENT_ID` and
   `RELAY_OTP_MS_CLIENT_SECRET`. Then run `docker compose up -d`.

Until these three are set, "Email me a code" answers "The code could not be sent". For a local test only, add
`RELAY_OTP_DEV_LOG=1` and the code is printed in `docker logs d2d-relay` instead. This setting is ignored once mail is
set up.

Code rules: 6 digits, valid for 10 minutes, 5 tries, 1 code a minute and 6 codes an hour. Only a salted hash is stored.
The page gives the same answer for any address, so it does not reveal which address can sign in. A session lasts
12 hours (`RELAY_SESSION_HOURS`).

To allow a different address, change `RELAY_OTP_EMAIL` (and `RELAY_ADMIN_EMAIL`) and restart the container.

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

### 3. Google BigQuery

In **Connections → Add → Google BigQuery**, use one of these:
- **Service account:** paste the client's service-account JSON (roles BigQuery Data Viewer + BigQuery Job User). This
  is the simplest option for a client.
- **Sign in with Google:** first an admin adds a Google OAuth client under Administration → Connections sign-in. Its
  redirect URI is `https://d2d-relay.pasdacs.com/auth/connector/callback` (shown on that screen).

Queries are read-only and limited to 1 GB scanned by default (Administration → guardrails).

## Updating

Build from a clean commit and restart while nothing is running:

```
git status            # clean
set RELAY_COMMIT=<git rev-parse HEAD> && docker compose build && docker compose up -d
```
