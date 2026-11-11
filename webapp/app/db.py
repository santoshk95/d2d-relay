"""The index database: who owns what, the durable job queue and the audit log.

Project folders (/data/projects/<id>/) stay the unit of work and keep their own files; this database is the index
and the permission source around them (platform plan, phase 0).

Two backends behind the same calls (q / one / run / transaction): SQLite (the default, one file in the state volume)
and Postgres (phase 8: set D2D_DATABASE_URL=postgresql://...). The app's SQL is written once, SQLite-flavoured; for
Postgres it is translated (placeholders, INSERT OR IGNORE / OR REPLACE -> ON CONFLICT, IS NOT -> IS DISTINCT FROM,
column types) and cached. `python -m app.dbmove` copies an existing SQLite index into Postgres.

users         people (single-user mode: one bootstrap admin)
teams         groups of people; a role is held per team membership
memberships   user x team -> role: 'dev' (BI Dev / Analyst) or 'viewer'
projects      project id -> owner, team, visibility ('private' | 'team' | 'org')
library       custom visual name -> owner, team
jobs          the durable queue: one row per job, with its lane, owner and state
audit         platform-level events: who, on which instance, did what to which object
meta          key/value: schema version, last backup, settings
phase 7       notifications, usage (LLM / warehouse / extract cost records), quotas, email_accounts, schedules

P17 (docs/P17-tenancy.md): every tenant has its own copy of all of the above — Postgres schema `public` for the
platform tenant (this install's own workspace, where the data always was) and `t_<id>` for the others; SQLite
`index.db` and `tenants/<id>.db`. The control plane (tenants, entitlements, the people directory, access grants,
hand-overs, its audit, the price book) lives in schema `relay` / `control.db`, all tables named `tn_*`.
"""
import contextlib
import contextvars
import functools
import gzip
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

STATE = Path(os.environ.get("D2D_STATE", "/data/state"))
PATH = STATE / "index.db"
INSTANCE = os.environ.get("D2D_INSTANCE", "local")
DATABASE_URL = os.environ.get("D2D_DATABASE_URL", "")
BACKEND = "postgres" if DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite"
SCHEMA_VERSION = 9                     # v9 (P17): tenants; users.home_tenant / local_login

ADMIN_ID = "u-admin"
DEFAULT_TEAM = "t-default"

_lock = threading.RLock()
_conn = None

# ---------------------------------------------------------------- P17: tenants (the contract every branch builds on)
# Every tenant (the platform, a partner, a client) has its own database schema / file and its own folder tree
# (docs/P17-tenancy.md). The tenant is a context variable: set per request (auth middleware), per job (worker) and per
# background pass (each_tenant()). db.q / one / run and store.root() follow it, so module code never names a tenant.
PLATFORM = os.environ.get("D2D_PLATFORM_TENANT", "pasdacs")      # the root tenant: this install's own workspace
TENANT: contextvars.ContextVar[str | None] = contextvars.ContextVar("relay_tenant", default=None)


def tenant() -> str:
    """The tenant this request, job or background pass works in (the platform's own workspace when none is set)."""
    return TENANT.get() or PLATFORM


@contextlib.contextmanager
def use(tid: str):
    """with db.use(tid): … — work inside one tenant (its schema, folders and secrets), then back to the caller's."""
    token = TENANT.set(tid)
    try:
        yield tid
    finally:
        TENANT.reset(token)


def tenants() -> list[str]:
    """Every active tenant, the platform first (from the control plane; the platform only until init() ran)."""
    if not _control_ready:
        return [PLATFORM]
    rows = q("SELECT id FROM relay.tn_tenants WHERE status = 'active' AND id != ? ORDER BY created, id", (PLATFORM,))
    return [PLATFORM] + [r["id"] for r in rows]


_module_check = None                    # tenancy.py registers fn(tenant, module id) -> bool (entitlements)


def each_tenant(module: str | None = None):
    """for t in db.each_tenant(): … — one background pass per active tenant, with that tenant set inside the body.
    Every scheduler / watcher loop wraps its pass in this (sync or async bodies alike). With a module id, tenants
    that have that module switched off are skipped."""
    prev = TENANT.get()
    for t in tenants():
        if module and _module_check is not None and not _module_check(t, module):
            continue
        TENANT.set(t)
        try:
            yield t
        finally:
            TENANT.set(prev)

PLATFORM_NAME = os.environ.get("D2D_PLATFORM_NAME", "PASDACS")
TENANT_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
RESERVED_IDS = {"relay", "public", "platform", "admin", "api", "auth", "tenants", "pg-catalog", "information-schema"}
CONTROL_PATH = STATE / "control.db"
_conns: dict[str, sqlite3.Connection] = {}            # SQLite: one connection per tenant file, the control file attached
_pg = {"path": None, "tx": 0}                         # Postgres: the tenant search_path is set to; open transactions
_ready: set[str] = set()                              # tenants whose schema is up to date in this process
_initialising: set[str] = set()
_control_ready = False


class UnknownTenant(LookupError):
    """A tenant id that is not in the control plane (or not set up in this database)."""


def schema_of(tid: str) -> str:
    """Postgres schema of a tenant: the platform keeps `public` (nothing moves); others `t_<id>`."""
    return "public" if tid == PLATFORM else "t_" + tid.replace("-", "_")


def sqlite_path(tid: str) -> Path:
    return PATH if tid == PLATFORM else STATE / "tenants" / f"{tid}.db"


# The control plane: every table is `relay.tn_*` (schema-qualified, so it is created in `relay` whatever the current
# tenant is; tenant schemas never hold a tn_* table and the control schema never holds a tenant table).
CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS relay.tn_tenants (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('platform', 'partner', 'client')), parent_id TEXT,
  name TEXT NOT NULL, edition TEXT NOT NULL DEFAULT 'enterprise' CHECK (edition IN ('enterprise', 'partner', 'both')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'closed')),
  deployment TEXT NOT NULL DEFAULT 'shared' CHECK (deployment IN ('shared', 'dedicated')), host TEXT UNIQUE,
  partner_access TEXT NOT NULL DEFAULT 'open' CHECK (partner_access IN ('open', 'approval', 'ended')),
  region TEXT, notes TEXT, created REAL NOT NULL, created_by TEXT, updated REAL NOT NULL, updated_by TEXT);
CREATE TABLE IF NOT EXISTS relay.tn_modules (
  tenant_id TEXT NOT NULL, module_id TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, updated REAL NOT NULL,
  updated_by TEXT, PRIMARY KEY (tenant_id, module_id));
CREATE TABLE IF NOT EXISTS relay.tn_accounts (
  user_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, home_tenant TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS relay.tn_access (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, home_tenant TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'dev', 'viewer')), reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'revoked', 'expired', 'refused', 'ended')),
  hours REAL NOT NULL, requested_by TEXT, granted_by TEXT, created REAL NOT NULL, starts REAL, expires REAL,
  ended REAL, ended_by TEXT, end_reason TEXT, last_used REAL, checkpoint_id TEXT);
CREATE TABLE IF NOT EXISTS relay.tn_acting (
  skey TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, grant_id TEXT NOT NULL, since REAL NOT NULL);
CREATE TABLE IF NOT EXISTS relay.tn_handovers (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, partner_id TEXT, owner_id TEXT NOT NULL, delivered TEXT,
  evidence TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '{}', move_direct INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL, created_by TEXT);
CREATE TABLE IF NOT EXISTS relay.tn_setup (
  token TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
  used REAL);
CREATE TABLE IF NOT EXISTS relay.tn_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, who TEXT, who_tenant TEXT, tenant_id TEXT,
  action TEXT NOT NULL, object TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS relay.tn_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS relay.tn_orgs (
  tenant_id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT UNIQUE NOT NULL, owner_id TEXT NOT NULL,
  credits INTEGER NOT NULL DEFAULT 0, setup_done INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, created_by TEXT);
CREATE TABLE IF NOT EXISTS relay.tn_credits (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, ts REAL NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('start', 'charge', 'refund', 'adjust')), delta INTEGER NOT NULL,
  balance INTEGER NOT NULL, what TEXT, user_id TEXT, user_name TEXT, project_id TEXT, project_name TEXT, note TEXT,
  ref TEXT);
"""
# D2D Relay (orgs.py): tn_orgs = an organisation per tenant (its email domain, owner and pooled credits);
# tn_credits = every change to those credits (starting credits, charges, refunds, admin adjustments).
CONTROL_TABLES = re.findall(r"CREATE TABLE IF NOT EXISTS relay\.(\w+)", CONTROL_SCHEMA)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  org_role TEXT NOT NULL DEFAULT 'member' CHECK (org_role IN ('admin', 'member')),
  active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (
  user_id TEXT NOT NULL REFERENCES users(id), team_id TEXT NOT NULL REFERENCES teams(id),
  role TEXT NOT NULL CHECK (role IN ('dev', 'viewer')), PRIMARY KEY (user_id, team_id));
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), team_id TEXT REFERENCES teams(id),
  visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team', 'org')),
  created REAL NOT NULL, imported INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS library (
  name TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), team_id TEXT REFERENCES teams(id),
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, pid TEXT NOT NULL, kind TEXT NOT NULL, args TEXT NOT NULL DEFAULT '{}',
  model TEXT, lane TEXT NOT NULL DEFAULT 'build', owner_id TEXT,
  state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'error', 'stopped', 'skipped')),
  created REAL NOT NULL, started REAL, ended REAL, error TEXT);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (lane, state, created);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, who TEXT, instance TEXT NOT NULL,
  action TEXT NOT NULL, object TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS audit_ts ON audit (ts);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- phase 1: sign-in and sharing
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), provider TEXT NOT NULL,
  created REAL NOT NULL, expires REAL NOT NULL, last_seen REAL NOT NULL, ip TEXT, agent TEXT);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);
CREATE TABLE IF NOT EXISTS auth_flows (
  state TEXT PRIMARY KEY, provider TEXT NOT NULL, verifier TEXT NOT NULL, nonce TEXT NOT NULL,
  return_to TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS shares (
  project_id TEXT NOT NULL, principal_type TEXT NOT NULL CHECK (principal_type IN ('user', 'team', 'org')),
  principal_id TEXT NOT NULL, permission TEXT NOT NULL CHECK (permission IN ('view', 'edit')),
  expires REAL, created REAL NOT NULL, created_by TEXT, PRIMARY KEY (project_id, principal_type, principal_id));
-- phase 3: warehouse connections (each person's own login) and the tables they configured
CREATE TABLE IF NOT EXISTS connections (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, name TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}', auth_mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
  error TEXT, created REAL NOT NULL, last_used REAL);
CREATE TABLE IF NOT EXISTS connection_tables (
  connection_id TEXT NOT NULL REFERENCES connections(id), object TEXT NOT NULL, alias TEXT NOT NULL,
  object_type TEXT, rows INTEGER, added REAL NOT NULL, PRIMARY KEY (connection_id, object));
-- phase 4: semantic layer — team metrics (versioned, reviewed), terms, context notes, organisation ontology
CREATE TABLE IF NOT EXISTS metrics (
  id TEXT PRIMARY KEY, team_id TEXT NOT NULL REFERENCES teams(id), name TEXT NOT NULL, created REAL NOT NULL,
  created_by TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS metrics_team_name ON metrics (team_id, lower(name));
CREATE TABLE IF NOT EXISTS metric_versions (
  metric_id TEXT NOT NULL REFERENCES metrics(id), version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft', 'review', 'published', 'rejected', 'superseded')),
  body TEXT NOT NULL, author_id TEXT, created REAL NOT NULL, reviewer_id TEXT, decided REAL, note TEXT, source TEXT,
  PRIMARY KEY (metric_id, version));
CREATE TABLE IF NOT EXISTS terms (
  id TEXT PRIMARY KEY, team_id TEXT, term TEXT NOT NULL, meaning TEXT NOT NULL, synonyms TEXT NOT NULL DEFAULT '[]',
  kind TEXT NOT NULL DEFAULT 'term', updated REAL NOT NULL, updated_by TEXT);
CREATE TABLE IF NOT EXISTS context_notes (
  source TEXT NOT NULL, tbl TEXT NOT NULL, col TEXT NOT NULL, description TEXT, sensitive INTEGER NOT NULL DEFAULT 0,
  updated REAL NOT NULL, updated_by TEXT, PRIMARY KEY (source, tbl, col));
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, synonyms TEXT NOT NULL DEFAULT '[]', owner_team_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')), created REAL NOT NULL, updated REAL NOT NULL,
  updated_by TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS entities_name ON entities (lower(name));
CREATE TABLE IF NOT EXISTS entity_keys (
  entity_id TEXT NOT NULL REFERENCES entities(id), source TEXT NOT NULL, tbl TEXT NOT NULL, col TEXT NOT NULL,
  PRIMARY KEY (entity_id, source, tbl, col));
CREATE TABLE IF NOT EXISTS entity_relations (
  from_id TEXT NOT NULL REFERENCES entities(id), verb TEXT NOT NULL, to_id TEXT NOT NULL REFERENCES entities(id),
  PRIMARY KEY (from_id, verb, to_id));
CREATE TABLE IF NOT EXISTS suggestions (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'dismissed')), created REAL NOT NULL,
  decided_by TEXT, decided REAL);
CREATE TABLE IF NOT EXISTS org_defaults (
  term TEXT PRIMARY KEY, metric_id TEXT NOT NULL REFERENCES metrics(id), decided_by TEXT, decided REAL NOT NULL);
-- phase 5: Ask D
CREATE TABLE IF NOT EXISTS askd_threads (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), scope TEXT NOT NULL, title TEXT NOT NULL,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS askd_threads_user ON askd_threads (user_id, updated);
CREATE TABLE IF NOT EXISTS askd_messages (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES askd_threads(id), role TEXT NOT NULL, body TEXT NOT NULL,
  created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS askd_messages_thread ON askd_messages (thread_id, created);
CREATE TABLE IF NOT EXISTS askd_feedback (
  message_id TEXT NOT NULL REFERENCES askd_messages(id), user_id TEXT NOT NULL, rating INTEGER NOT NULL,
  corrected_sql TEXT, comment TEXT, created REAL NOT NULL, PRIMARY KEY (message_id, user_id));
CREATE TABLE IF NOT EXISTS askd_cache (key TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
-- phase 6: insight pages (shared like dashboards)
CREATE TABLE IF NOT EXISTS pages (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), team_id TEXT, title TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team', 'org')),
  body TEXT NOT NULL DEFAULT '[]', source TEXT, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS page_shares (
  page_id TEXT NOT NULL REFERENCES pages(id), principal_type TEXT NOT NULL CHECK (principal_type IN ('user', 'team', 'org')),
  principal_id TEXT NOT NULL, permission TEXT NOT NULL CHECK (permission IN ('view', 'edit')), expires REAL,
  created REAL NOT NULL, created_by TEXT, PRIMARY KEY (page_id, principal_type, principal_id));
-- phase 7: notifications, cost records and quotas, email sending accounts, scheduled reports and alerts
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT, link TEXT, created REAL NOT NULL, read REAL);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications (user_id, created);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_id TEXT, team_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('llm', 'warehouse', 'extract')), step TEXT, model TEXT, provider TEXT,
  tokens INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0, bytes INTEGER, object TEXT, source TEXT UNIQUE);
CREATE INDEX IF NOT EXISTS usage_ts ON usage (ts);
CREATE TABLE IF NOT EXISTS quotas (
  scope TEXT NOT NULL CHECK (scope IN ('user', 'team')), target_id TEXT NOT NULL, monthly_usd REAL NOT NULL,
  soft_pct INTEGER NOT NULL DEFAULT 80, updated REAL NOT NULL, updated_by TEXT, PRIMARY KEY (scope, target_id));
CREATE TABLE IF NOT EXISTS email_accounts (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL CHECK (kind IN ('gmail', 'microsoft')),
  address TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', error TEXT, created REAL NOT NULL, last_used REAL);
CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL CHECK (kind IN ('report', 'alert')),
  name TEXT NOT NULL, target TEXT NOT NULL, cadence TEXT NOT NULL, tz TEXT NOT NULL, email_account_id TEXT,
  recipients TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
  paused_reason TEXT, next_run REAL, last_run REAL, last_status TEXT, last_error TEXT, state TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS schedules_due ON schedules (status, next_run);
"""
# columns added after a table was first created (each migration adds what is missing)
ADDED_COLUMNS = {
    # v8: where a column / table description came from (person, warehouse comment, AI draft) and whether it is confirmed
    "context_notes": {"origin": "TEXT NOT NULL DEFAULT 'person'", "status": "TEXT NOT NULL DEFAULT 'confirmed'"},
    # v8: an entity's business definition, examples, and whether they are an AI draft awaiting review
    "entities": {"definition": "TEXT", "examples": "TEXT NOT NULL DEFAULT '[]'", "drafted_by": "TEXT", "drafted": "REAL"},
}
# D2D Relay: columns added to control-plane tables (relay.<table>) after they were first created; _init_control adds
# the missing ones at every start (orgs.py registers its own)
CONTROL_ADDED_COLUMNS: dict[str, dict[str, str]] = {}


def register_control_columns(table: str, cols: dict[str, str]) -> None:
    """Columns a module adds to a control-plane table, e.g. ("tn_orgs", {"connectors": "TEXT NOT NULL DEFAULT '[]'"})."""
    CONTROL_ADDED_COLUMNS.setdefault(table, {}).update(cols)


USER_COLUMNS = {"password_hash": "TEXT", "last_login": "REAL", "auth_provider": "TEXT", "deactivated": "REAL",
                "deactivated_by": "TEXT", "tz": "TEXT",
                # P17: a guest from another tenant (their home tenant id; NULL = this tenant's own person) and whether
                # this person may sign in with a local password (each tenant's first admin, set through a setup link)
                "home_tenant": "TEXT", "local_login": "INTEGER NOT NULL DEFAULT 0"}


def _check_ready(t: str) -> None:
    """The tenant's schema must exist before anything runs in it (fail closed). A tenant made by another process since
    this one started (e.g. `python -m app.tenantmove import`) is set up here on first use."""
    if t in _ready or t in _initialising or t == PLATFORM:    # the platform's database is the one it always was
        return
    if _control_ready:
        with use(PLATFORM):
            known = one("SELECT 1 AS x FROM relay.tn_tenants WHERE id = ?", (t,))
        if known:
            init_tenant(t)
            return
    raise UnknownTenant(t)


def conn():
    """The connection for the current tenant; every use goes through `_lock` (uvicorn runs one worker).
    SQLite: one connection per tenant file with the control file attached as `relay`. Postgres: one connection
    whose search_path follows the tenant (_pg_path)."""
    global _conn
    if BACKEND == "postgres":
        if _conn is None:
            import psycopg
            from psycopg.rows import dict_row
            _conn = psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row, connect_timeout=15)
            _pg.update(path=None, tx=0)
        return _conn
    t = tenant()
    c = _conns.get(t)
    if c is None:
        _check_ready(t)
        path = sqlite_path(t)
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA busy_timeout = 30000")
        c.execute("ATTACH DATABASE ? AS relay", (str(CONTROL_PATH),))
        _conns[t] = c
    return c


def _pg_path() -> None:
    """Postgres: point the connection's search_path at the current tenant's schema (then `relay` for tn_* tables).
    Never inside a transaction: a rolled-back SET would leave the connection in another tenant."""
    t = tenant()
    if _pg["path"] == t:
        return
    if _pg["tx"]:
        raise RuntimeError(f"Tenant switch to {t} inside a transaction.")
    _check_ready(t)
    _conn.execute(f'SET search_path TO "{schema_of(t)}", relay')
    _pg["path"] = t


# Build-plan v2 (P10+): phase modules add their own tables and columns without touching SCHEMA — one call each at
# import time (main.py imports every phase module through phases.py before the app starts).
SCHEMA_PARTS: list[str] = []


def register_schema(sql: str, added_columns: dict[str, dict[str, str]] | None = None) -> None:
    """A phase's DDL (CREATE TABLE IF NOT EXISTS …, indexes) and the columns it adds to existing tables."""
    if sql not in SCHEMA_PARTS:
        SCHEMA_PARTS.append(sql)
    for table, cols in (added_columns or {}).items():
        ADDED_COLUMNS.setdefault(table, {}).update(cols)
    primary_keys.cache_clear()


def full_schema() -> str:
    return SCHEMA + "\n" + "\n".join(SCHEMA_PARTS)


@functools.lru_cache(maxsize=1)
def primary_keys() -> dict[str, list[str]]:
    """table -> primary key columns, read from the schema (the ON CONFLICT targets)."""
    out = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (?:relay\.)?(\w+) \((.*?)\);", full_schema() + "\n" + CONTROL_SCHEMA, re.S):
        body = m.group(2)
        pk = re.search(r"PRIMARY KEY \(([^)]*)\)", body)
        if pk:
            out[m.group(1)] = [c.strip() for c in pk.group(1).split(",")]
        else:
            col = re.search(r"(?:^|[(,\n])\s*(\w+) [A-Z]+ PRIMARY KEY", body)
            out[m.group(1)] = [col.group(1)] if col else []
    return out


def _outside_quotes(sql: str, fn) -> str:
    """fn applied to the parts of sql outside '...' literals."""
    parts = re.split(r"('(?:[^']|'')*')", sql)
    return "".join(x if i % 2 else fn(x) for i, x in enumerate(parts))


@functools.lru_cache(maxsize=2048)
def pg(sql: str) -> str:
    """SQLite-flavoured SQL as Postgres understands it."""
    s = sql.replace("%", "%%")
    s = _outside_quotes(s, lambda x: x.replace("?", "%s"))
    s = re.sub(r"\bIS NOT %s", "IS DISTINCT FROM %s", s)
    if re.match(r"\s*INSERT OR IGNORE INTO", s, re.I):
        return re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", s, count=1, flags=re.I).rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    m = re.match(r"\s*INSERT OR REPLACE INTO ([\w.]+) \(([^)]*)\)", s, re.I)
    if m:
        table, cols = m.group(1).split(".")[-1], [c.strip() for c in m.group(2).split(",")]
        keys = primary_keys().get(table) or []
        rest = [c for c in cols if c not in keys]
        body = re.sub(r"INSERT OR REPLACE INTO", "INSERT INTO", s, count=1, flags=re.I).rstrip().rstrip(";")
        return body + f" ON CONFLICT ({', '.join(keys)}) " + (
            "DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in rest) if rest else "DO NOTHING")
    return s


def pg_schema(schema: str) -> list[str]:
    """The DDL for Postgres: 64-bit integers, doubles for times and money, BIGSERIAL ids."""
    s = re.sub(r"--[^\n]*", "", schema)
    s = s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    s = re.sub(r"\bINTEGER\b", "BIGINT", s)
    s = re.sub(r"\bREAL\b", "DOUBLE PRECISION", s)
    return [x.strip() for x in s.split(";") if x.strip()]


def _args(args: tuple) -> tuple:
    return tuple(int(x) if isinstance(x, bool) else x for x in args)


def _exec(sql: str, args: tuple = ()):
    if BACKEND == "postgres":
        c = conn()
        _pg_path()
        return c.execute(pg(sql), _args(args))
    return conn().execute(sql, args)


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        cur = _exec(sql, args)
        return [dict(r) for r in cur.fetchall()] if cur.description else []


def one(sql: str, args: tuple = ()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def run(sql: str, args: tuple = ()) -> int:
    with _lock:
        return _exec(sql, args).rowcount


@contextlib.contextmanager
def transaction():
    """Several writes as one: all or nothing (both backends)."""
    with _lock:
        if BACKEND == "postgres":
            c = conn()
            _pg_path()                                  # set before BEGIN: no tenant switch inside the transaction
            _pg["tx"] += 1
            try:
                with c.transaction():
                    yield
            finally:
                _pg["tx"] -= 1
            return
        c = conn()                                      # the tenant's connection (its file + the control file)
        c.execute("BEGIN")
        try:
            yield
        except BaseException:
            c.execute("ROLLBACK")
            raise
        c.execute("COMMIT")


def tables() -> list[str]:
    """Every tenant table, in the order the schema creates them (parents before children). Not the control plane."""
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", full_schema())


def _columns(table: str) -> set[str]:
    """The columns of a table in the current tenant (Postgres: its schema only — every tenant has a `users`)."""
    if BACKEND == "postgres":
        return {r["column_name"] for r in q("SELECT column_name FROM information_schema.columns WHERE table_name = ? "
                                              "AND table_schema = current_schema()", (table,))}
    return {r["name"] for r in conn().execute(f"PRAGMA table_info({table})").fetchall()}


def init() -> None:
    """The control plane, then every tenant's schema (so tables added by a new phase reach every tenant), the
    platform first with the bootstrap organisation: one admin, one default team (single-user mode)."""
    with _lock:
        if BACKEND == "postgres":            # D2D Relay: the public site and the admin portal start together; one at a time
            conn().execute("SELECT pg_advisory_lock(735105)")
        try:
            _init_control()
            init_tenant(PLATFORM, bootstrap=True)
            with use(PLATFORM):
                others = [r["id"] for r in q("SELECT id FROM relay.tn_tenants WHERE id != ? ORDER BY created, id", (PLATFORM,))]
            for t in others:
                init_tenant(t)
            if BACKEND == "postgres":
                with use(PLATFORM):
                    _pg_path()               # leave the connection in the platform's schema, as it always was
        finally:
            if BACKEND == "postgres":
                conn().execute("SELECT pg_advisory_unlock(735105)")


def _init_control() -> None:
    global _control_ready
    with use(PLATFORM):
        _initialising.add(PLATFORM)
        try:
            if BACKEND == "postgres":
                c = conn()
                c.execute("CREATE SCHEMA IF NOT EXISTS relay")
                for stmt in pg_schema(CONTROL_SCHEMA):
                    c.execute(stmt)
            else:
                STATE.mkdir(parents=True, exist_ok=True)
                conn().executescript(CONTROL_SCHEMA)
            for table, cols in CONTROL_ADDED_COLUMNS.items():          # D2D Relay: columns added since (orgs.py)
                if BACKEND == "postgres":
                    have = {r["column_name"] for r in q("SELECT column_name FROM information_schema.columns "
                                                        "WHERE table_schema = 'relay' AND table_name = ?", (table,))}
                else:
                    have = {r["name"] for r in conn().execute(f"PRAGMA relay.table_info({table})").fetchall()}
                for col, kind in cols.items():
                    if col not in have:
                        if BACKEND == "postgres":
                            kind = re.sub(r"\bREAL\b", "DOUBLE PRECISION", re.sub(r"\bINTEGER\b", "BIGINT", kind))
                        conn().execute(f"ALTER TABLE relay.{table} ADD COLUMN {col} {kind}")
            now = time.time()
            run("INSERT OR IGNORE INTO relay.tn_tenants (id, kind, parent_id, name, edition, status, deployment, partner_access, created, "
                "created_by, updated) VALUES (?, 'platform', NULL, ?, 'both', 'active', 'shared', 'open', ?, 'system', ?)",
                (PLATFORM, PLATFORM_NAME, now, now))
        finally:
            _initialising.discard(PLATFORM)
    _control_ready = True


def init_tenant(tid: str, bootstrap: bool = False) -> None:
    """Create or bring up to date one tenant's schema: every table, the columns added since, the default team and
    the directory entries of its own people; the platform also gets the bootstrap admin. Idempotent."""
    if tid != PLATFORM and (not TENANT_ID.match(tid) or tid in RESERVED_IDS):
        raise ValueError(f"Not a tenant id: {tid!r}")
    with _lock, use(tid):
        _initialising.add(tid)
        try:
            if BACKEND == "postgres":
                c = conn()
                if _pg["tx"]:
                    raise RuntimeError("init_tenant inside a transaction")
                sch = schema_of(tid)
                if tid != PLATFORM:
                    c.execute(f'CREATE SCHEMA IF NOT EXISTS "{sch}"')
                c.execute(f'SET search_path TO "{sch}"')   # only the tenant's schema while its tables are created
                _pg["path"] = None
                for stmt in pg_schema(full_schema()):
                    c.execute(stmt)
            else:
                sqlite_path(tid).parent.mkdir(parents=True, exist_ok=True)
                conn().executescript(full_schema())
            have = _columns("users")
            for col, kind in USER_COLUMNS.items():          # migration v1 -> v2 (+ v9): new user columns
                if col not in have:
                    kind = {"REAL": "DOUBLE PRECISION"}.get(kind, kind) if BACKEND == "postgres" else kind
                    conn().execute(f"ALTER TABLE users ADD COLUMN {col} {kind}")
            for table, cols in ADDED_COLUMNS.items():
                have = _columns(table)
                for col, kind in cols.items():
                    if col not in have:
                        kind = kind.replace("REAL", "DOUBLE PRECISION") if BACKEND == "postgres" else kind
                        conn().execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
            run("DELETE FROM auth_flows WHERE created < ?", (time.time() - 900,))
            run("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            now = time.time()
            if bootstrap:
                email = os.environ.get("D2D_ADMIN_EMAIL", "admin@local")
                name = os.environ.get("D2D_ADMIN_NAME", "Admin")
                run("INSERT OR IGNORE INTO users (id, email, name, org_role, created) VALUES (?, ?, ?, 'admin', ?)", (ADMIN_ID, email, name, now))
            run("INSERT OR IGNORE INTO teams (id, name, created) VALUES (?, 'Default', ?)", (DEFAULT_TEAM, now))
            if bootstrap:
                run("INSERT OR IGNORE INTO memberships (user_id, team_id, role) VALUES (?, ?, 'dev')", (ADMIN_ID, DEFAULT_TEAM))
            run("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            run("INSERT OR REPLACE INTO meta (key, value) VALUES ('database', ?)", (BACKEND,))
            run("INSERT OR REPLACE INTO meta (key, value) VALUES ('tenant', ?)", (tid,))
            for u in q("SELECT id, email, created FROM users WHERE home_tenant IS NULL"):
                run("INSERT OR IGNORE INTO relay.tn_accounts (user_id, email, home_tenant, created) VALUES (?, ?, ?, ?)",
                    (u["id"], (u["email"] or "").lower(), tid, u["created"]))
        finally:
            _initialising.discard(tid)
        _ready.add(tid)


def drop_tenant(tid: str) -> None:
    """Remove a tenant's schema / file (tests, and undoing a creation that failed; closing a tenant keeps its data)."""
    if tid == PLATFORM:
        raise ValueError("The platform's own workspace cannot be dropped.")
    with _lock:
        _ready.discard(tid)
        if BACKEND == "postgres":
            conn()
            if _pg["path"] == tid:
                _conn.execute("SET search_path TO public, relay")
                _pg["path"] = PLATFORM
            _conn.execute(f'DROP SCHEMA IF EXISTS "{schema_of(tid)}" CASCADE')
        else:
            c = _conns.pop(tid, None)
            if c is not None:
                c.close()
            sqlite_path(tid).unlink(missing_ok=True)


def ctl_meta(key: str, default: str | None = None) -> str | None:
    """A control-plane setting (the price book …): the same whichever tenant asks."""
    row = one("SELECT value FROM relay.tn_meta WHERE key = ?", (key,))
    return row["value"] if row else default


def set_ctl_meta(key: str, value: str) -> None:
    run("INSERT OR REPLACE INTO relay.tn_meta (key, value) VALUES (?, ?)", (key, value))


def meta(key: str, default: str | None = None) -> str | None:
    row = one("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    run("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


# ---------------------------------------------------------------- people

def user(uid: str) -> dict | None:
    u = one("SELECT * FROM users WHERE id = ? AND active = 1", (uid,))
    if u:
        u["teams"] = q("SELECT t.id, t.name, m.role FROM memberships m JOIN teams t ON t.id = m.team_id "
                       "WHERE m.user_id = ? ORDER BY t.name", (uid,))
    return u


# ---------------------------------------------------------------- ownership

def import_existing(project_ids: list[str], created: dict[str, float], library_names: list[str]) -> dict:
    """One-time (and idempotent) import: every project folder and library visual without an owner is assigned to
    the bootstrap admin and the default team. Nothing on disk moves."""
    now, added = time.time(), {"projects": 0, "library": 0}
    with _lock:
        for pid in project_ids:
            added["projects"] += run("INSERT OR IGNORE INTO projects (id, owner_id, team_id, visibility, created, imported) "
                                     "VALUES (?, ?, ?, 'private', ?, 1)", (pid, ADMIN_ID, DEFAULT_TEAM, created.get(pid) or now))
        for name in library_names:
            added["library"] += run("INSERT OR IGNORE INTO library (name, owner_id, team_id, created) VALUES (?, ?, ?, ?)",
                                    (name, ADMIN_ID, DEFAULT_TEAM, now))
    return added


def add_project(pid: str, owner_id: str, team_id: str | None = None, visibility: str = "private") -> None:
    run("INSERT OR IGNORE INTO projects (id, owner_id, team_id, visibility, created) VALUES (?, ?, ?, ?, ?)",
        (pid, owner_id, team_id or DEFAULT_TEAM, visibility, time.time()))


def project(pid: str) -> dict | None:
    return one("SELECT * FROM projects WHERE id = ?", (pid,))


def add_library(name: str, owner_id: str, team_id: str | None = None) -> None:
    run("INSERT OR IGNORE INTO library (name, owner_id, team_id, created) VALUES (?, ?, ?, ?)",
        (name, owner_id, team_id or DEFAULT_TEAM, time.time()))


def library_item(name: str) -> dict | None:
    return one("SELECT * FROM library WHERE name = ?", (name,))


def remove_library(name: str) -> None:
    run("DELETE FROM library WHERE name = ?", (name,))


# ---------------------------------------------------------------- jobs (the durable queue)

def add_job(pid: str, kind: str, args: dict, model: str | None, owner_id: str | None, lane: str = "build") -> str:
    jid = secrets.token_hex(4)
    run("INSERT INTO jobs (id, pid, kind, args, model, lane, owner_id, state, created) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
        (jid, pid, kind, json.dumps(args), model, lane, owner_id, time.time()))
    return jid


def queued(lane: str = "build") -> list[dict]:
    """Jobs waiting in this lane, oldest first."""
    return q("SELECT * FROM jobs WHERE lane = ? AND state = 'queued' ORDER BY created, id", (lane,))


def job(jid: str) -> dict | None:
    return one("SELECT * FROM jobs WHERE id = ?", (jid,))


def set_job(jid: str, state: str, error: str | None = None) -> None:
    now = time.time()
    if state == "running":
        run("UPDATE jobs SET state = 'running', started = ? WHERE id = ?", (now, jid))
    else:
        run("UPDATE jobs SET state = ?, ended = ?, error = COALESCE(?, error) WHERE id = ?", (state, now, error, jid))


def skip_queued(pid: str, keep: str | None = None) -> None:
    """A newer request replaces whatever this project still had waiting."""
    run("UPDATE jobs SET state = 'skipped', ended = ? WHERE pid = ? AND state = 'queued' AND id IS NOT ?",
        (time.time(), pid, keep))


def interrupted() -> list[dict]:
    """Jobs that were running when the app stopped (a half-finished agent run cannot be resumed)."""
    return q("SELECT * FROM jobs WHERE state = 'running'")


# ---------------------------------------------------------------- audit

def audit(action: str, obj: str | None = None, detail: dict | None = None, who: str | None = None) -> None:
    run("INSERT INTO audit (ts, who, instance, action, object, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), who, INSTANCE, action, obj, json.dumps(detail) if detail else None))


def audit_log(limit: int = 200, action: str | None = None) -> list[dict]:
    rows = q("SELECT * FROM audit " + ("WHERE action = ? " if action else "") + "ORDER BY id DESC LIMIT ?",
             ((action, limit) if action else (limit,)))
    for r in rows:
        r["detail"] = json.loads(r["detail"]) if r["detail"] else None
    return rows


def backup(dest: Path) -> Path:
    """A consistent copy, safe while the app is running: SQLite's online backup, or (Postgres) every table as JSON
    lines in one gzip file, read in one transaction (restore with `python -m app.dbmove --from-dump FILE`)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if BACKEND == "postgres":
        dest = dest.with_suffix(".jsonl.gz")
        with _lock:
            c = conn()
            _pg_path()                                   # the current tenant's schema
            _pg["tx"] += 1
            try:
                with c.transaction(), gzip.open(dest, "wt", encoding="utf-8") as f:
                    for t in tables():
                        for row in c.execute(f"SELECT * FROM {t}").fetchall():
                            f.write(json.dumps({"table": t, "row": dict(row)}, default=str) + "\n")
            finally:
                _pg["tx"] -= 1
        return dest
    with _lock:
        target = sqlite3.connect(dest)
        try:
            conn().backup(target)                        # "main" only: the tenant's own file, not the control plane
        finally:
            target.close()
    return dest


def backup_control(dest: Path) -> Path:
    """The control plane (tenants, entitlements, directory, grants, hand-overs, its audit, the price book)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if BACKEND == "postgres":
        dest = dest.with_suffix(".jsonl.gz")
        with _lock, use(PLATFORM):
            c = conn()
            _pg_path()
            _pg["tx"] += 1
            try:
                with c.transaction(), gzip.open(dest, "wt", encoding="utf-8") as f:
                    for t in CONTROL_TABLES:
                        for row in c.execute(f"SELECT * FROM relay.{t}").fetchall():
                            f.write(json.dumps({"table": t, "row": dict(row)}, default=str) + "\n")
            finally:
                _pg["tx"] -= 1
        return dest
    with _lock:
        src, target = sqlite3.connect(CONTROL_PATH), sqlite3.connect(dest)
        try:
            src.backup(target)
        finally:
            src.close()
            target.close()
    return dest
