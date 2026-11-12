# D2D Relay security, privacy and data governance audit - 11 November 2026

The user asked for a full sweep of security, data governance and privacy before D2D Relay is launched to the public.
This covers the live site (image `d2d-relay:442a396`, the one running) and the work folder (`c4aade0`, with item 25,
GST invoices, not yet live). Fixes for the most serious problems are in the work folder, tested, **not deployed and
not committed**.

## The short answer

- **Three ways for the dashboard AI to run code of its own were found, and fixed in the work folder.** Each one
  let a person who signs up (free, with any business email) reach every other organisation's uploaded data and the
  Claude sign-in. They were proven on a throwaway copy of the live image. They must go live before the public launch.
- **Four things for the user to decide or do before launch:** move the AI off the personal Claude plan (P1); publish
  terms, a refund and cancellation policy and a data processing agreement (P2); encrypt the PC's disk and keep backups
  somewhere else (P3); have the privacy notice reviewed for the countries you will sell in (P4).
- The rest of the app held up: sign-in, sessions, keeping organisations apart, payments, file access, the prototype
  sandbox, the database, and secrets (none in the git history). The hardening that is still worth doing is listed
  below, in order.

## What was checked

| Check | How |
|---|---|
| Every API the public site and the admin portal answer | All 509 routes (path and method) listed from the app itself. 129 API routes are reachable on the public site after sign-in (309 are switched off by `edition.py`, 52 are `/api/admin`), plus 19 outside `/api` (sign-in, callbacks, health). The reachable ones were read for their own permission checks. |
| Sign-in, sessions, tenancy | `otp.py`, `identity.py`, `auth.py`, `portal.py`, `tenancy.py`, `orgs.py`, `db.py`, `store.py` |
| Payments and invoices | `payments.py` (signatures, amounts, webhook, idempotence), `invoices.py` |
| The AI engine's confinement | `agent/server.py`, `managed-settings.json`, `bash_guard.py`, every `genbi` command that starts another program (Python, Node, pbiviz/webpack, Less, DuckDB, Chromium) |
| The PC helpers | `pbix/pbix.ps1` (Power Query guard) and `daxcheck/daxcheck.ps1` |
| Data governance | `governance.py`, retention, erasure, "Download my data", `privacy.html`, the sign-in page, what goes to Anthropic, Microsoft, Cloudflare and Razorpay |
| Secrets | the whole git history scanned for keys and tokens (Razorpay, Anthropic, AWS, GitHub, Google, Cloudflare tunnel, private keys, the `.env` names): only AWS's documented example key appears |
| Infrastructure | `docker-compose.yml`, `Dockerfile`, `relay_init.py`, `supervisord.conf`, the database's access rules, response headers of the live site, package versions in the live image |

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| S1 | Critical | A custom visual's `caps.js` (written by the AI) ran in Node with the AI engine's rights | Fixed in the work folder |
| S2 | Critical | A Python file the AI writes in its folder ran as the `genbi` toolkit | Fixed in the work folder |
| S3 | Critical | A visual's style (Less `@plugin`) and imports (webpack loader syntax, files outside the visual) ran code or read files during the build | Fixed in the work folder |
| S4 | High | The AI engine's Linux user can read and write every organisation's folders and holds the Claude login; its API takes any folder, without a key | Open: architecture |
| S5 | High | The DAX checker on the PC loaded any model dropped in its queue (data sources included) | Fixed in the work folder; the helper needs a restart |
| S6 | High | Nothing limits where the containers connect on the internet | Open |
| S7 | Medium | Free starting credits can be collected many times over with subdomains | Addressed in the work folder: starting credits wait for PASDACS's review (work log item 27) |
| S8 | Medium | The first person from a domain owns the organisation and can open every colleague's dashboard | Now in the privacy notice; product decision open |
| S9 | Medium | PASDACS owners get the platform console's cross-organisation views on the public site | Fixed in the work folder |
| S10 | Medium | The admin portal checks Cloudflare Access only for requests that come through Cloudflare | Open |
| S11 | Medium | Starlette 0.41.3 has two known denial-of-service bugs | One mitigated in the work folder; upgrade open |
| S12 | Low | No security headers (framing, sniffing, HSTS) | Fixed in the work folder |
| S13 | Low | Sign-in codes: 30 guesses an hour per address, no daily cap | Fixed in the work folder (20 codes a day) |
| S14 | Low | `/api/health` names the real AI models to everyone signed in | Fixed in the work folder |
| S15 | Low | 129 leftover and current routes are reachable; several belong to RELAY, not D2D Relay | Open |
| S16 | Low | Build supply chain: floating dev dependencies, a CLI checked against its own manifest | Open |
| S17 | Low | A warehouse sign-in started by one person can be finished in another person's browser | Open |
| P1 | High | Customers' data goes through a personal Claude plan | Open: the user's decision (in `LOG.md`) |
| P2 | High | No terms of service, refund and cancellation policy, contact page or data processing agreement | Open |
| P3 | High | Disk not encrypted; backups on the same disk; live secrets in a user's Downloads folder | Open (partly in `LOG.md`) |
| P4 | Medium | The privacy notice is written for India; dollar prices invite customers from the EU and UK | Two corrections made; legal review open |
| P5 | Medium | No end to keeping dashboards, removed people and idle organisations; no self-service account erasure | Open |
| P6 | Low | Small data-sharing details (Razorpay notes, sign-in alert mailbox) | Open |

### S1 Critical - the AI could run its own code through a custom visual's `caps.js` (fixed)

**What.** `genbi visual build` turned `caps.js` into `capabilities.json` by running it with Node
(`node mk_caps.js`, which `require`s the file). The AI writes `caps.js`: it is part of every custom visual. Node ran it
as the AI engine's Linux user, outside Claude Code's confinement, so it could do anything that user can.

**Proof.** In a throwaway container of the live image with no network, a `caps.js` read a CSV in another
organisation's folder, read the Claude sign-in file, and ran `id` (`uid=1000(agent) ... groups=1002(relaydata)`).

**Who could.** Anyone who signs up: they can ask for it in the description, or put it in a CSV or an attachment that
tells the AI what to write. A determined person needs one dashboard (25 of the 50 free credits).

**What it reaches.** Every organisation's uploads, plans, prototypes and Power BI files, read and write (a planted
`.pbix` in another organisation's download would run its Power Query on that customer's PC); other organisations' AI
transcripts; the Claude sign-in (the subscription the whole site runs on); the DAX checker's queue on the PC (S5).

**Fix.** `caps.js` is read as data, never run (`genbi_kit/caps.py`): one shape,
`module.exports = ({ E, num, ... }) => ({ ... });`, holding only texts, numbers, true/false/null, arrays, objects, the
helpers and `E([...])`. Anything else is refused with its line, so the AI rewrites it as plain data. The result is
byte-identical to what `mk_caps.js` wrote for all 26 `caps.js` files in the image and the repository (the Atlas
families, the library visuals and the starter). The agent's guide (`GENBI.md`) says so.

### S2 Critical - a Python file in the AI's folder ran as the toolkit (fixed)

**What.** `genbi` is `python -m genbi_kit.cli`, run in the dashboard's folder. Python puts the current folder first
on its search path, so a `genbi_kit/__init__.py` or a `json.py` that the AI writes there (its Write tool may) ran in place
of the toolkit at the next `genbi sql`.

**Proof.** Same container: a `genbi_kit/__init__.py` in an "attacker" folder printed another organisation's CSV and
the Claude sign-in when `genbi sql "select 1"` ran as the AI engine's user.

**Fix.** `genbi` runs with `python -P` (never the current folder), and the AI engine's environment has
`PYTHONSAFEPATH=1` for any other Python it starts (`Dockerfile`, `agent/Dockerfile`, `docker/relay_init.py`).

### S3 Critical - a visual's build ran code and read files through its style and imports (fixed)

**What.** The build copied the whole visual folder and ran pbiviz (webpack, Less, TypeScript) on it:
- Less runs a `@plugin "file"` with Node's `require`: code execution at build time;
- `data-uri()`, `image-size()` and `@import` of any path read files into the visual;
- webpack treats `import x from "./a.js!./b"` as "run `a.js` as a loader": code execution at build time;
- `import y from "../../../../home/agent/.claude/.credentials.json"`, `require.context("../..")` and `new URL(...,
  import.meta.url)` bundle files from anywhere the AI engine can read; the visual can then show them in its test
  screenshot, which the AI reads;
- `pbiviz.json` could name any file as the icon; a stray `webpack.config.js`, `babel.config.js` or similar sat in
  the build folder.

The existing check only looked at `src/*.ts`, line by line (an import split over two lines, or written with
backticks, passed).

**Fix** (`genbi_kit/vfactory.py`). A build gets only `src/`, `style/`, `assets/` and `stringResources/`, with the kit's
own `tsconfig.json`, `eslint.config.mjs`, `package.json` and a `pbiviz.json` whose file entries are fixed. Before a
build, every code and style file is checked: no links, no loader syntax or queries in an import, relative imports stay
inside the visual's folder, no `require.context` / `import.meta` / `__non_webpack_require__`, no Less `@plugin`,
backticks, file functions or `url()` other than `data:`, and `@import` only of a file of the same folder by its name.
The real visuals still build: the starter, an Atlas family and a library visual, offline, in 3-4 seconds each.

### S4 High - one Linux user for the AI engine, with every organisation's folders (open)

Project folders are shared by the web app and the AI engine through the group `relaydata` (read and write), and the
Claude sign-in sits in the AI engine's home. So keeping organisations apart from each other rests entirely on the AI
never running code of its own (Claude Code's managed settings, `bash_guard.py`, the toolkit's checks: S1-S3 were the
gaps in that). The AI engine's API (`127.0.0.1:8090`: `/runs`, `/display-check`, `/forget`) has no key and takes any
folder under the projects root, so anything that runs in the web container can start a run in any organisation's
folder.

Recommended, in order of effort:
1. The AI engine's API on a Unix socket that only the web app's user may use (checked by the peer's user id).
2. Each job in a short-lived container that mounts only its dashboard's folder (and no Claude sign-in file:
   an API key passed for the run). This is the change that makes S1-S3-type bugs harmless.

### S5 High - the DAX checker on the PC took any model from its queue (fixed; restart the helper)

The DAX checker reads requests from a folder the containers share and loaded the model with a full refresh. The app
only ever sends DAX tables, but the checker did not check: a model with an OLE DB data source, a Power Query partition
or Power Query expressions would have made the PC's Analysis Services engine open files, databases or web addresses
as the signed-in Windows user, after any break-out like S1. (The Power BI file maker already had such a guard for
Power Query, and it held.)

**Fix** (`daxcheck/daxcheck.ps1`). The model is read with Power BI's own library; data sources, Power Query
expressions and any table that is not calculated are refused; the engine gets the model as the library wrote it out
again, so what was checked is what runs. Tested on this PC with Power BI's engine: a model made from the enterprise
sample gave identical results through the new and the old checker (objects, query results and messages), and data
sources, an M partition and expressions were refused. A JSON with `dataSources` written twice was neutralised by the
rewrite. **The running helper keeps the old script until it is closed and started again** (after the deploy folder
has the new file).

### S6 High - no limit on where the containers connect (open)

The web container needs Anthropic, Microsoft Graph and Razorpay; nothing stops anything in it from reaching any
other address. Since S1-S3 are fixed, the AI's own tools cannot reach the internet, as the privacy notice says, but the
container can. Recommended: an egress allowlist (a small forward proxy, or firewall rules on the host for the Docker
network) for `api.anthropic.com`, `login.microsoftonline.com`, `graph.microsoft.com`, `api.razorpay.com` and the
connector hosts PASDACS switches on.

### S7 Medium - free credits can be collected with subdomains (addressed: starting credits are reviewed)

**Update, same day:** the user chose review (work log item 27). A new organisation starts with no credits, PASDACS
gets an email for each one (with organisations from the same network and on the same parent domain, to spot this),
and approves or declines its starting credits. Turnstile and a per-network cap would still reduce the noise.

An organisation is one exact email domain, and every new one gets 50 credits without approval. Someone with a
wildcard mail domain can sign up as `a@x1.example.com`, `a@x2.example.com` and so on: each is a new organisation with
50 credits, about two dashboards of AI time each, paid by PASDACS. The free-mail list (about 200 domains, plus the big
brands' country domains) also cannot cover the tens of thousands of disposable domains. Options: group organisations by the registrable domain (public
suffix list), put Cloudflare Turnstile on "Send code", cap new organisations per day, or start new organisations at 0
credits until PASDACS approves.

### S8 Medium - the first person from a domain owns the organisation (now disclosed; decision open)

Anyone at a company domain who signs in first becomes its owner; everyone after joins automatically. Owners can open
every dashboard in the organisation (with its files), and every member sees the others' names, email addresses and
last sign-in. For a large company that may be a junior employee or someone about to leave. The privacy notice now says
this plainly (section "Who in your organisation sees what"). Options: verify the domain before the first owner gets
owner rights (a DNS record or PASDACS's check), let owners approve people who join, or keep dashboards private from
owners unless shared.

### S9 Medium - PASDACS owners have console views on the public site (fixed)

**Fixed:** `/api/tenancy/audit`, `usage`, `usage.csv`, `prices`, `people`, `packs` and `access` answer 404 on the public
site (`edition.EXTRA_BLOCKED`); `/api/tenancy/me`, `switch` and `return` stay. What follows is the finding as found.

`tenancy.platform_admin` is true for an owner of the PASDACS workspace wherever they sign in, so on the public site
`info@pasdacs.com` can read the control plane's audit across every organisation (`/api/tenancy/audit`: emails,
names, credit requests, payments), usage across organisations and the price book. The README says the public site has
no platform powers; this one bypasses Cloudflare Access. Recommended: on the public site, answer only
`/api/tenancy/me`, `switch` and `return` (add the other `/api/tenancy/*` paths to `edition.EXTRA_BLOCKED`).

### S10 Medium - the admin portal trusts requests that do not come through Cloudflare (open)

`portal.access_refusal` checks the Cloudflare Access token only when `cf-connecting-ip` is present. That is right for
the PC itself, but any container on the same Docker network (the web container included) also arrives without it,
leaving only the email code. Recommended: without `cf-connecting-ip`, accept only the Docker host's own address, and
replace the whole `pasdacs.com` domain with a short list of named admin addresses (in Cloudflare Access too).

### S11 Medium - Starlette 0.41.3 (open; one bug mitigated)

The live image has FastAPI 0.115.6 with Starlette 0.41.3:
- CVE-2025-62727: many ranges in one `Range` header take quadratic time in `FileResponse` and the static files, which
  anyone can request. **Mitigated** in the work folder (`webapp/app/headers.py` drops a `Range` header with several
  ranges; one range still works).
- CVE-2025-54121: a large multipart upload blocks the server while it spills to disk. Only signed-in people reach
  uploads.

Recommended: upgrade FastAPI to a release that allows Starlette 0.49.1 or later, run the suites, and add `pip-audit`
to the release steps.

### S12 Low - security headers (fixed)

The live site sent no security headers. Every answer now carries `X-Content-Type-Options: nosniff`,
`X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, a base
`Content-Security-Policy` (`frame-ancestors 'self'; object-src 'none'; base-uri 'self'`; pages with their own policy,
such as prototypes and invoices, keep theirs) and, on the https sites, `Strict-Transport-Security` for a year.
Checked in headless Chromium: the app's sandboxed prototype frame still loads and reports its height; another site
cannot frame the app. A script policy (`script-src`) is not set yet: it needs the screens' and Razorpay's sources
listed first.

### S13 Low - sign-in code guessing (fixed: a daily cap)

**Fixed:** at most 20 codes a day per address (`otp.PER_DAY`), so at most 100 guesses a day. Turnstile is still worth
adding.

6 codes an hour per address, 5 tries each: about 30 guesses an hour, roughly a 23% chance in a year of trying
non-stop against one address (each code is also emailed to its owner, 144 a day). Recommended: a daily cap per
address (for example 20 codes) and Turnstile on "Send code" (it also protects the sending mailbox's reputation).

### S14 Low - model names on `/api/health` (fixed)

**Fixed:** `/api/health` passes on only whether the AI engine is up and busy (all the screens use).

`/api/health` passes the AI engine's health through, with `models` (the real model ids behind "the Relay Model").
If they are to stay private, keep only `ok` and `busy` for people who are not PASDACS.

### S15 Low - reachable routes from RELAY (open)

The reachable routes check their own permissions, but several are RELAY's, not D2D Relay's: `/api/me/ai` (bring your own AI key), `/api/workbench/*`, `/api/validate/*`, `/api/workspace*`,
`/api/tenancy/prices`, `/api/registry/{id}/interest`, `/auth/github/callback`, `/auth/microsoft/callback`,
`/auth/observe/hook/{id}`, `/gallery`. Recommended: the public site answers an allowlist, as the admin portal does
(`portal.API`), instead of a blocklist.

### S16 Low - build supply chain (open)

The visual kit's dev dependencies use `^` ranges and there is no lockfile, so two builds can get different packages;
the Antigravity CLI is checked against the checksum in the same manifest it is downloaded from (pin it with
`AGY_IMAGE`, as the live build does). Recommended: commit a `package-lock.json` for the kit.

### S17 Low - a warehouse sign-in can be finished in someone else's browser (open)

`/auth/connector/callback` stores the warehouse's token for the person who started the sign-in (from the stored
state), whoever's browser comes back with the code; the "signed in as another person" check runs after the token is
saved. Someone could send a colleague the sign-in link of their own connection and, if the colleague approves the
warehouse's consent screen, query the colleague's warehouse through it. It needs a connector PASDACS switched on and a
person who approves a consent screen they did not start, so the risk is low today. Recommended: keep a hash of the
browser's session with the flow and refuse the callback from any other session, before the token is fetched. (The
Microsoft mail and GitHub callbacks check their state the same way; their features are off in D2D Relay.)

### What was checked and holds

- **Sign-in:** codes are random, stored as salted hashes, 10 minutes, 5 tries, one live code per address;
  sessions are random, stored hashed, `HttpOnly`, `SameSite=Lax`, `Secure` on https, 12 hours, ended when an owner
  removes a person; each site accepts only its own session kind. Cross-site POSTs are refused (Origin check).
- **Organisations apart:** a database schema and a folder tree per organisation; the running job is shown only in
  its own organisation; sharing and Ask Relay check access; credit, payment and receipt queries are tied to the
  organisation.
- **Payments:** prices are the server's; Razorpay's signature (checkout and webhook, HMAC, constant time) is checked
  and the payment is fetched back and matched (order, amount, currency); credits are added once, in one transaction;
  test keys sell only to PASDACS.
- **Files:** every file route checks names against the project's own lists or patterns; uploads are CSV or raster
  images only (no SVG uploads; the SVG logo is shown only through `<img>`).
- **The AI's own tools:** Claude Code's managed settings, the shell guard (`genbi` only, no pipes or substitution),
  DuckDB confined to the dashboard's folder with settings locked, demo-data formulas limited to arithmetic and listed
  functions, headless Chromium offline, the prototype served sandboxed with a strict policy.
- **The PC's Power BI file maker** refuses any Power Query beyond the dashboard's own files.
- **Secrets:** none in the git history; `.env` and `tunnel.env` ignored; the tunnel token kept out of the app
  containers; saved credentials encrypted (Fernet).
- **The database** has no published port and takes the app's role only with its password (SCRAM) on the private
  network.
- **Emails** escape everything they include.

## Data governance and privacy

### P1 High - customers' data on a personal Claude plan (open: the user's decision)

Already in `LOG.md` ("Still open"). The AI engine signs in with a consumer Claude subscription, so customers' uploads,
samples and questions are processed under consumer terms: they may be used for training if "Help improve Claude" is
on, with longer retention, and there is no data processing agreement. A consumer plan is also meant for its
subscriber's own use, not as the engine of a service sold to others (check Anthropic's current terms). Before launch:
an Anthropic API key under the Commercial Terms (no training by default, a DPA available; D2D Relay already supports
the `anthropic_api` provider), with a spend limit set in the Anthropic Console.

### P2 High - no terms, refund policy, contact page or DPA (open)

The site has a privacy notice only. Needed before selling to the public:
- **Terms of service:** who may use it, acceptable use (no unlawful data, no attempts to break the AI's limits),
  liability, the credits' terms, governing law.
- **Cancellation and refund policy:** the "no refunds" rule is shown at purchase; it also needs its own page.
  Razorpay asks for terms, privacy, refund and cancellation, and contact pages on the website before it activates
  live payments (check its current checklist).
- **Contact page:** a postal address and a named person for grievances (DPDP asks for a contact who can answer for
  PASDACS).
- **Data processing agreement:** organisations upload files about their own customers and staff. For that data
  PASDACS is their processor. Business customers will ask for a DPA: what PASDACS does with the data, its
  sub-processors (Anthropic, Microsoft, Cloudflare, Razorpay), security, breach notice and deletion at the end.

### P3 High - the PC: disk, backups, secrets (open)

Already partly in `LOG.md`: BitLocker is off and the backups are on the same disk. Also: the live `.env` (database
password, Razorpay keys and webhook secret, mail app ids) and `tunnel.env` sit in the Downloads folder of the Windows
account that also runs Power BI, UiPath and a browser; anything that runs as that account can read them. The secrets
store's key (it encrypts saved credentials and the mail sign-in) is generated inside the data volume it protects.
Recommended: BitLocker with the recovery key kept apart; an encrypted backup copy off the PC (a nightly upload of the
`data\backups` dumps); a dedicated Windows account or machine for D2D Relay; `RELAY_SECRET_KEY` set in `.env` rather
than generated beside the data.

### P4 Medium - the privacy notice (two corrections made; legal review open)

Changed in the work folder (`webapp/static/privacy.html`):
- a new section, **Who in your organisation sees what**: joining by email domain, owners opening every dashboard,
  members seeing each other's names, addresses and last sign-in (S8);
- **Cloudflare**: it does not just carry encrypted traffic, it decrypts and routes it, so it handles what people
  send.

For the lawyer, beyond the review already in `LOG.md`:
- **Selling abroad.** Prices in dollars outside India invite customers from the EU and the UK, where GDPR applies:
  the lawful basis for each use, transfers out of the EU (to India and the USA), possibly an EU/UK representative,
  and the right to complain to their regulator. Either add these or sell only in India at first.
- **DPDP.** Most of the DPDP Rules' duties apply from about May 2027 (18 months after the Rules of November 2025):
  a named contact for grievances, notice to the Data Protection Board and to the people affected after a breach (write
  the incident steps down now), and the notice in the languages asked for.
- **"PASDACS's own server in India"** is a desktop PC; say so, or move to a server.

### P5 Medium - keeping data with no end (open)

What works: dashboards and conversations can be deleted (with the AI's transcripts), an organisation can be erased by
PASDACS on request (accounting records stay, without people's names), logs go after a year, the answer cache after
7 days, hand-made dumps after 30, AI transcripts after 7, backups after 14 nights; "Download my data" works. What is
missing:
- no way for a person to erase their own account (a removed person's name, address and history stay forever);
  recommended: `python -m app.governance erase-person` for PASDACS, then a "Delete my account" button;
- dashboards of organisations that stopped using D2D Relay are kept for ever; recommended: a rule such as notice
  after 18 months without a sign-in, erasure after 24, written in the privacy notice;
- removed people's rows: anonymise after the log period.

### P6 Low - small data-sharing details (open)

- Razorpay's order notes include the buyer's email and the workspace id. Razorpay already gets the email from the
  checkout form, so the notes can drop it.
- The sign-in alert emails keep names, addresses and networks in the `info@pasdacs.com` mailbox (in `LOG.md`: give
  that folder a one-year retention rule).

## What changed in the work folder

Not deployed, not committed.

| File | Change |
|---|---|
| `genbi_kit/caps.py` (new) | `caps.js` read as data, written out as `mk_caps.js` would (S1) |
| `genbi_kit/vfactory.py` | builds use `caps.py`; only the visual's code, style, icon and translations reach the build, with fixed settings; `check_source` covers every code and style file of the build (S1, S3) |
| `genbi_kit/GENBI.md` | the agent's guide: `caps.js` is plain data; what a build uses; imports and styles |
| `Dockerfile`, `agent/Dockerfile` | `genbi` runs with `python -P` (S2) |
| `docker/relay_init.py` | the AI engine's environment gets `PYTHONSAFEPATH=1` (S2) |
| `daxcheck/daxcheck.ps1` | the model guard and the rewrite (S5) |
| `webapp/app/headers.py` (new), `webapp/app/main.py` | security headers; the `Range` guard (S12, S11); `/api/health` without the AI engine's details (S14) |
| `webapp/app/edition.py` | the console's cross-organisation views off the public site (S9) |
| `webapp/app/otp.py` | 20 codes a day per address (S13); a sign-up that joins at the same moment is "joined" |
| `webapp/static/privacy.html` | "Who in your organisation sees what"; Cloudflare (P4) |
| `webapp/app/orgs.py`, `otp.py`, `signin_alerts.py`, `login.html`, `js/36-org.js` | starting credits reviewed by PASDACS (work log item 27; S7) |

## Tests

All on throwaway copies: the live image with the changed files on top (`d2d-relay-audit:test`, no network), and
copies of the DAX checker on their own queues on this PC. The live site, its containers and its helpers were not
touched.

| Test | Result |
|---|---|
| Before the fixes: S1 and S2 as the AI engine's user (another organisation's CSV, the sign-in file, `id`) | Both worked |
| `caps.js` read as data vs `mk_caps.js` | Byte-identical for all 26 shipped files |
| 14 kinds of code in `caps.js` (require, process, templates, spreads, variables, getters, computed keys, escaped names, code after the object...) | All refused; plain data with comments, trailing commas, shorthand and escapes read |
| S1-S3 end to end with `genbi`, as the AI engine's user | Python modules in the folder ignored; `caps.js`, Less `@plugin` never ran; `data-uri`, loader syntax, imports leaving the folder, `require.context` refused |
| Real builds, offline | Starter, an Atlas family and a library visual built; their `capabilities.json` as `mk_caps.js` writes it; no stray config reached the build |
| The AI engine's service with `PYTHONSAFEPATH=1` | Starts and answers |
| DAX checker guard with Power BI's library | Data sources, an M partition and expressions refused; duplicate-key trick neutralised |
| DAX checker, new vs old, same model on Power BI's engine | Identical objects, query results and messages |
| The web app (SQLite, no network): headers on a page, the privacy notice, an API answer, a redirect | All present; `Range` of 2,000 parts gets the whole file, one range still gets 206 |
| Headless Chromium | The prototype frame loads and reports its height; another site cannot frame the app |

### Launch readiness: every suite, every combination (the user: "Full audit and testing as well all combinations")

On a release candidate built from the work folder with the real Dockerfile (all of the above, plus S9, S13, S14 and
work log item 27), on fresh test stacks (Postgres, the public site and the admin portal in their own containers, the
stand-in Razorpay; never the live site). The end-to-end suites were rebuilt from the session that wrote them (its
transcript replayed in order, 148 events, no problem left) and run as they ran for item 25.

| Suite | Starting-credit review off | Review on (each new organisation approved through `python -m app.orgs approve`) |
|---|---|---|
| `d2d_checks.py`: connectors, admin portal, credits, people, production | 120 of 120 | 120 of 120 |
| `gov_check.py` + `gov_ui_check.py` (Chromium): erasure, Download my data, retention, privacy | 60 + 10 | 60 + 10 |
| `ask_credits_check.py`, `review_fixes_check.py` | 14 + 13 | 14 + 13 |
| `pay_check.py` + `pay_ui_check.py` (Chromium): rupees, dollars, invoices, webhook, receipts | 113 + 37 | 113 + 37 |
| `sec_check.py` (new): the combinations below | 115 of 115 | 132 of 132 (the review's own checks too) |

`sec_check.py` covers: every one of the 129 reachable API routes without a session (401/404, never an answer);
the admin portal without its sign-in, through Cloudflare without Access, and for the public site's APIs; sign-in
(free and disposable mail refused, the admin portal refusing non-PASDACS addresses, one code a minute, 5 wrong tries
kill a code, a code works once, the daily cap, the sign-up cookie's flags); CSRF from another site; session cookies
tampered with (another organisation's workspace, none, an unknown one, a guessed session, a tenant header, `?t=`,
the public cookie on the admin portal and the other way round); owner and member (a member cannot open a colleague's
private dashboard, rename the organisation, add people, promote himself, remove the owner or take the ownership; an
owner opens every dashboard); a removed person (session ended at once, cannot sign in again); another organisation
against Alpha's dashboard (15 routes: the dashboard, its activity and export, data, files, prototype, shares, the
download, feedback, retry, stop, sharing, delete, PDF export, a review: all 404), its list, people, ownership and
requests; platform powers (no `/api/admin` and no console views on the public site, PASDACS's own owner included);
`/api/health` details; uploads (a `../` file name kept inside the folder, non-CSV refused) and 10 path tricks; payments
across organisations (another's order, receipt, a forged webhook, the admin portal's webhook, a member's billing
change); and with review on, the review itself (a joining colleague sees it, dashboards and requests refused meanwhile
with the reason, an owner cannot approve, a decline needs a reason, a different amount, approving twice refused,
the history and the notification, a subdomain sign-up's review naming the organisation on its parent domain, no
second alert, a decline told to the owner and credits asked for after it).

| Other checks on the release candidate | Result |
|---|---|
| The sandbox escapes S1-S3, end to end as the AI engine's user; 26 `caps.js` vs `mk_caps.js`; 14 kinds of code; real builds | All refused; byte-identical; all refused; starter, family and library built offline |
| The new source checks over all 31 shipped visual sources (Atlas families, library, starter, both copies) | 0 problems |
| The shell guard's 64 cases (`guard_cases.py`) | 22 allowed, 42 refused, 0 wrong |
| Cloudflare Access on the admin portal (`access_check.py`: forged, expired, another application's and another team's tokens, a non-PASDACS address, not set up) | 10 of 10 |
| A hostile prototype, on its own and framed in the app, with the new headers (`proto_sandbox_check.py`) | 23 of 23 |
| Upgrade: the live image (`442a396`) with data, then the release candidate on the same database (`upgrade_check.py`) | 21 of 21: sessions, credits and their history, a waiting request (now "more"), the dashboard kept; every new column added; new sign-ups reviewed |
| The DAX checker's guard on Power BI's engine on this PC (above) | Data sources, M and expressions refused; results identical to the old checker |

Found and fixed along the way: two people of a new domain signing up at the same moment made the second one's
sign-in look like a new organisation's (no alert); it is now "joined". Two failures in the first run were the
rebuilt stand-in Razorpay missing its rupee conversion, not the app (the 15:41 edit of item 25 was replayed).

**Not run:** a dashboard build with real Claude (the test stacks have no AI sign-in, and the escapes are closed below
the AI, whatever it is told), a real Razorpay checkout, real email delivery, and the Power BI file maker end to end
(unchanged). The suites, the stack and the replay are in this session's scratchpad (`recovered/`).

### Item 29 tests (2026-11-12): plain characters, the first-time tour, Migration D2D

Two new routes, both behind the session like every other: `POST /api/me/tour` (the person's own flag; the step it
names is cut to 20 letters) and `POST /api/org/migration-request` (an organisation member; the tools must be from the
list; at most 5 an hour per person; the message is cut to 1,500 characters, 500 kept in the log; not an API of the
admin portal). The route list was taken again from the release candidate: 124 reachable API routes on the public site
(129 before: the S9 console views are now switched off; the two new ones and the billing details added), all checked
anonymously by `sec_check.py`. The rest of the change is text (string literals and comments; no regular expression,
guard, setting or query was changed), so the AI engine's confinement suites were not run again.

| Suite, on fresh test stacks from the release candidate | Review off | Review on |
|---|---|---|
| `d2d_checks.py`, `gov_check.py` + `gov_ui_check.py`, `ask_credits_check.py`, `review_fixes_check.py` | 120, 60 + 10, 14, 13 | 120, 60 + 10, 14, 13 |
| `pay_check.py` + `pay_ui_check.py` | 113 + 37 | 113 + 37 (see below) |
| `sec_check.py` (the 124 routes and every combination above) | 115 of 115 | 132 of 132 |
| `item29_check.py` (new): the tour flag per person, people from before 12 November, signed out, the admin portal; Migration D2D requests (the Requests card, refusals, the hourly limit, the log, notifications, 401/404); the agent's words plain and people's words as typed; no long dashes, curly quotes or arrows in the pages and scripts served | 34 of 34 | 34 of 34 |
| `tour_ui_check.py` (new, Chromium): an owner through every step (brand, Dark, Match my device following the device, Light, the basics), not shown again; the menu and sidebar entries; the Migration page, its dialog and a request; a member's tour without the brand step and Skip; a deep link left alone; a phone in dark mode with nothing past the screen's edge; no script errors | 28 of 28 | 28 of 28 |
| The report builder (`builder_plain_check.py`, in the container): page name, title, text box, alt text, descriptions and display folder plain; the measure name and every reference to it kept; the definition untouched; the gate warns, does not fail | 11 of 11 | |
| Upgrade: today's live image (`72b71a1`) with an organisation, a dashboard and a waiting request, then the release (`a84d7c9`) on the same database (`upgrade_check.py`) | 23 of 23 | |

Two expectations were changed because the app's text changed: a shortened Razorpay key id now ends in "..." (`pay_check.py`),
and the upgrade suite now starts from an image that already reviews new organisations. In the first review-on run
`pay_ui_check.py` stopped once at a 15-second wait for the Buy dialog while the PC was busy; on the same stack it then
passed 37 of 37, and 37 of 37 again in the review-off run. Fixed on the way: the tour's organisation card ran past the
screen's edge on a phone (long email addresses), and truncated notes are cut to their length limit including the three
dots.

## To put it live

1. Make sure no dashboard is running, then build and tag the image from the work folder as for earlier items
   (`RELAY_COMMIT=<sha> docker compose build web`, with the live `RELAY_AGY_IMAGE`), keeping `442a396` tagged for
   going back.
2. Restart web and admin (`docker compose up -d --no-deps web admin`): the user's go-ahead.
3. Fast-forward the deploy folder, then close the DAX checker's window and start `daxcheck\start-daxcheck.cmd`
   again, so the PC runs the new `daxcheck.ps1`.
4. Visuals: no live dashboard has a `caps.js` of the AI's own yet (0 found), so nothing needs rebuilding. A
   `caps.js` with code in it now fails to build with its line named, and the AI rewrites it as plain data.

## Suggested order before the public launch

1. Deploy these fixes (S1-S3, S5, S9, S11 mitigation, S12-S14, the notice, the starting-credit review).
2. The AI on an Anthropic API key (P1).
3. Terms, refund and cancellation, contact, DPA; the lawyer's review of the notice (P2, P4).
4. BitLocker, an encrypted backup off the PC, a dedicated account or machine (P3).
5. The AI engine's API on a socket; each job in its own container; an egress allowlist (S4, S6).
6. Abuse: Turnstile on "Send code" (S7, S13).
7. An allowlist of routes for the public site; FastAPI/Starlette upgrade; the warehouse sign-in bound to the
   browser's session; the admin portal checking where a request comes from (S10, S11, S15, S17).
