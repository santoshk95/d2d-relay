# P17 — Tenants, partners and editions: design

> 2026-11-06. The build-plan item (§ P17) as built. Decisions taken here are logged in `build-plan.md` (D4, D6, D7, D13-D16).

## 1. The hierarchy

```
platform  PASDACS — runs Relay; its own workspace is today's install (nothing moves)
├── partner   a service partner (SI): white-labelled, "Powered by PASDACS Relay"
│   └── client   the partner's customer (B2B2B)
└── client    a direct Enterprise customer (B2B)
         └── teams → people   (inside every tenant, exactly as today)
```

Every tenant is a full workspace: dashboards and every module's subjects, connections, secrets, metrics, ontology,
lineage, schedules, visual library, costs, Admin › Branding (templates, house style), the past-responses library and
rate cards, notifications, audit. A partner also works for itself (its own practice), so it has a workspace too.

## 2. Isolation: one database schema and one folder tree per tenant

| What | Platform tenant (today's install) | Any other tenant `<t>` |
|---|---|---|
| Index database | Postgres schema `public` · SQLite `state/index.db` | Postgres schema `t_<t>` · SQLite `state/tenants/<t>.db` |
| Project folders | `/data/projects/<id>` | `/data/projects/.tenants/<t>/<id>` |
| Visual library | `/opt/genbi/library` | `/opt/genbi/library/.tenants/<t>` |
| Secrets store | `state/secrets.enc` | `state/tenants/<t>/secrets.enc` |
| Rendered reports | `state/reports` | `state/tenants/<t>/reports` |

The tenant is a context variable set once per request (auth middleware), per job (worker) and per background pass
(each scheduler loops over the active tenants). `db.q / one / run` and `store.root()` follow it, so module code
does not change and **a query cannot see another tenant's rows: they are in another schema or file**. Postgres
`search_path` is `t_<t>, relay` (only the control tables live in `relay`, all named `tn_*`), so a tenant table can
never fall through to another tenant; a tenant schema is created before anything runs in it. SQLite opens one file per
tenant with the control file attached as `relay`. The agent gets the project folder relative to the shared volume
(`.tenants/<t>/<id>`) and Claude Code stays inside its working folder.

## 3. The control plane (`relay` schema / `state/control.db`)

`tn_tenants` (id, kind, parent, name, edition, status, deployment, host, partner access, created) ·
`tn_modules` (entitlements) · `tn_accounts` (person → home tenant, email unique across the platform) ·
`tn_access` (time-boxed grants) · `tn_acting` (which tenant a signed-in person is acting in) · `tn_handovers` ·
`tn_audit` (every tenancy action) · `tn_meta` (price book).

## 4. People, sign-in and acting in another tenant

- A person belongs to one **home tenant**. Platform staff → the platform; a partner's consultants → the partner; a
  client's people → the client.
- **Access to another tenant is a grant**: who, which tenant, role (admin / builder / viewer), why, until when
  (1 hour to 30 days, default 8 hours). Platform admins may grant into any tenant; partner admins into their own
  clients; nobody into a tenant that has ended its partner's access. A client may require **its own approval**
  for partner access (a checkpoint in its Validation queue).
- **Switching** (top bar → workspace menu) uses an active grant: the person acts inside the client as a guest
  (a person row in the client marked with their home tenant, the granted role), and every request re-checks the
  grant. When it expires or is revoked the person is back in their home tenant and the guest row is deactivated.
  Every grant, switch, revoke and expiry is in the control-plane audit *and* the client's own audit log; the
  client's admins are notified and see who from the partner can act in their workspace (Admin › Partner access).
- Sign-in: single mode (today's live install) is the platform's bootstrap admin, who switches like any admin.
  SSO mode: the sign-in page takes the tenant from its host name or `?t=`; providers are per tenant; the session
  cookie carries the home tenant; the OIDC state carries it too, so redirect URIs do not change.

## 5. Hand-over (the partner's engagement ends)

A partner or client admin records it (who takes over on the client side, what was delivered). Then, in one
transaction: every grant from the partner's people is revoked, guests are deactivated, their dashboards, visuals,
schedules and subjects move to the named owner (the same transfer as off-boarding a person), stored keys of the
guests are removed, partner access is set to **ended** (only the client's admin can reopen it), and the hand-over
is recorded with its evidence. Optionally the client moves to direct (platform) billing.

## 6. Entitlements: edition + modules

Edition per tenant: **enterprise** (B2B direct) or **partner** (service partner); the platform is **both**. The
edition decides which modules can be switched on (as Admin › Branding's edition did); a client of a partner can only
have modules its partner has. New tenants get every module of their edition switched on; admins above them switch
modules on or off. A module that is off is shown as "Not switched on" (menu hidden, module page explains), its
APIs answer 403, and its schedulers skip that tenant.

## 7. Metering and the statement (D6: per tenant + modules, metered AI cost)

Each tenant's cost records (AI runs, warehouse queries, extracts) stay in its own schema. The platform console rolls
them up per month: per tenant (AI cost, runs, people, dashboards, modules on, storage) and per partner (its own
workspace + all its clients). The price book (platform admins): currency, monthly fee per edition, fee per module,
AI cost mark-up. A statement per tenant and per partner, exportable as CSV. Partners see their own clients only.

## 8. Branding

A partner's Admin › Branding white-labels its workspace **and its clients'** (unless a client saves its own);
"Powered by PASDACS Relay" always shows for partner brands. Direct clients and the platform show RELAY by PASDACS.
The sign-in page shows the tenant's brand. The edition comes from the tenant record (Branding's edition setting is
kept for the platform tenant only).

## 9. Deployment options

`deployment: shared` (this install) or `dedicated` (inside the client's network). For dedicated, the platform
console downloads a **deployment pack**: the tenant's export (its schema as JSON lines + its folders + a re-keyed
secrets file, key shown once), `.env` for a one-tenant install (`D2D_TENANCY=single`, `D2D_PLATFORM_TENANT=<t>`)
and a Kubernetes overlay. `python -m app.tenantmove export|import` does the same from the command line; import into a
fresh install makes the client that install's own tenant. Kubernetes `base/` gains the runner images (Codex, Gemini,
Antigravity) and their volumes (sweep S9) as an optional `runners/` component.

## 10. Screens

- Top bar: the **workspace chip** (tenant name, kind) → switch menu (home, tenants you may enter, active grants with
  time left, "Back to <home>"); a coloured band while acting in another tenant.
- **Platform › Tenants** (`#/tenants`, platform and partner admins): tree of partners and clients, create tenant
  (name, kind, parent, edition, first admin, modules, deployment), and a tenant page with Overview, Modules, Access,
  Hand-over, Usage and Deployment.
- **Platform › Usage & statements** (`#/tenants/usage`): month roll-up, partner subtotals, CSV.
- **Admin › Partner access** (every tenant admin): who from outside can act here, until when, revoke; the approval
  policy.

## 11. As built (2026-11-06)

| Where | What |
|---|---|
| `db.py` | `CONTROL_SCHEMA` (`relay.tn_tenants`, `tn_modules`, `tn_accounts`, `tn_access`, `tn_acting`, `tn_handovers`, `tn_setup`, `tn_audit`, `tn_meta`); `init()` → control plane, the platform (`public` / `index.db`, bootstrap admin), every other tenant (`init_tenant`); Postgres `search_path` per tenant, never switched inside a transaction; SQLite one connection per tenant file with `control.db` attached; `each_tenant(module)`, `drop_tenant`, `backup_control`, `ctl_meta` |
| `store.py` | `ROOT` / `state_dir()` are `TenantPath`s (resolved per use); `rel()` for the agent; the visual library resolver for `genbi_kit.library_dir()` |
| `auth.py`, `identity.py`, `platform.py` | home tenant + acting grant per request (`_tenancy` on the person); cookie `<tenant>~<id>`, OIDC state `<tenant>~…`; `/auth/setup`; guests (`users.home_tenant`) are managed by grant only |
| `worker.py` | one queue over every tenant, each job run in its tenant; `current` shows a job only in its own tenant; the run gets `GENBI_LIBRARY` of its tenant (agent `TOOLKIT_ENV`, checked to stay inside its library mount) |
| `tenancy.py` | console API, entitlements and `denied()` (called by the middleware), grants, approval checkpoint `tenancy.access` (own admins only), switch / return, sweep (every 60 s), hand-over, metering + price book + CSV, `/api/admin/partner-access` |
| `tenantmove.py` | export / import / deployment pack (`python -m app.tenantmove …`) |
| `registry.py` | `api=[…]` per module (entitlements by prefix), state `off`, brand inheritance, edition from the tenant |
| `providers.py`, `litellm/d2d_auth.py` | gateway routes of every tenant (`<tenant>.<alias>`), run keys carry the tenant |
| screens | `js/33-tenants.js`, `css/tenants.css`; chip `#ws` and band `#actband` in `index.html`; routes `#/tenants…`; Admin › Partner access; `login.html` (`?t=`, `?setup=`) |
| Kubernetes | `deploy/kubernetes/runners/` component; the pack's overlay for `deploy/kubernetes/clients/<tenant>/` |

**Upgrade of an existing install** (the live one is Postgres): at start the app creates schema `relay` and its
tables, inserts the platform row (`pasdacs`, "PASDACS"), adds `users.home_tenant` and `users.local_login` (with a
default) in `public`, writes `meta.tenant` / `schema_version` 9 and fills the directory from `public.users`. Nothing in
`public` is moved or rewritten; it is idempotent (every statement is `IF NOT EXISTS` / `OR IGNORE`). Going back to the
previous image ignores `relay` and the two new columns.

## 12. Tests (`tests/p17_tenancy_test.py`, SQLite and Postgres)

Isolation (every GET route of the app called by tenant B with tenant A's object ids → no A data, 404/403; folders,
secrets, library, documents and rate cards per tenant; the control schema holds only `tn_*`), grants (partner → own
client only, expiry, revoke, the client's approval), switching, hand-over (transfer, access ended, cannot re-enter),
entitlements (module off → 403, menu), metering roll-up, worker and schedulers per tenant (a job of A runs in A's
folder and schema), export → import round trip, branding inheritance.
