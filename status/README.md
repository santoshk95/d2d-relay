# status.pasdacs.com

D2D Relay's status page and alerts (item 91 in `docs/LOG.md`). It is a Cloudflare Worker, `pasdacs-status`, that runs
outside the D2D PC, so it still answers, and still sends email, when the PC, Docker or the tunnel is down.

## What it checks

It checks every three minutes, from Cloudflare (cron `*/3 * * * *`):

| Service | How it is checked |
|---|---|
| D2D Relay website | `https://d2d.pasdacs.com/healthz`: the app and its database |
| Sign-in | `/login.html`, and whether sign-in mail is set up (`/status.json`) |
| Admin portal | `https://admin.pasdacs.com/healthz`: Cloudflare Access's sign-in in front of it also counts as working |
| AI engine, Build runner, DAX checker, Power BI file maker | `https://d2d.pasdacs.com/status.json`: each one up, down or not used; no sign-in needed, and nothing personal |

The state, 90 days of daily uptime, the website's response times and the last 40 incidents are kept in KV
(`d2d-status`, binding `STATUS`). Each run writes once, 480 times a day, which is inside the free plan.

## Alerts

A service down for two checks in a row is an incident.

- **When it starts:** info@pasdacs.com gets an email.
- **While it lasts:** a reminder every `REMIND_HOURS` (6).
- **When it ends:** an email that it is back.

Mail goes through Microsoft Graph as info@pasdacs.com. It uses the same Entra app as D2D's sign-in codes, app-only,
with these Worker secrets:

- `MS_TENANT`
- `MS_CLIENT_ID`
- `MS_CLIENT_SECRET`

If the app's client secret is renewed, update it here too. `POST /api/test-alert`, with the header `x-test-key:
<TEST_KEY>`, sends one test email.

## Deploy

Run these from the corporate site's folder, which has wrangler and the Cloudflare login:

```
cd Downloads\pasdacs-corporate-site
npx wrangler deploy -c ..\d2d.relay\status\wrangler.jsonc
npx wrangler secret put MS_TENANT -c ..\d2d.relay\status\wrangler.jsonc     (and MS_CLIENT_ID, MS_CLIENT_SECRET, TEST_KEY)
```

`GET /` is the page; it refreshes every minute and follows the device's light or dark setting. `GET /api/status` is the
same information as JSON.
