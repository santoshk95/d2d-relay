"""Warehouse connectors (platform plan, phase 3): Snowflake, Google BigQuery, Microsoft Fabric, Amazon Redshift and
Amazon Athena, next to CSV upload - and Oracle Database (python-oracledb in thin mode: no Oracle client in the image;
plain TCP, TLS with tcps://, or mutual TLS with an Autonomous Database wallet).

Each person connects with their own login, so the warehouse's own permissions apply; D2D never uses a shared
service account. Where the warehouse offers it, sign-in is OAuth (authorization code + PKCE) with offline access,
so scheduled extracts keep working while the person is signed out; a refresh that fails marks the connection
"Sign in again". Otherwise the person stores their own credentials (encrypted, secrets store).

Two data paths, as decided in Round 4:
  extract   SELECT * of a configured table into data/<alias>.parquet in the project folder (streamed in batches),
            for dashboards, prototypes, review gates and the DAX checker; a manifest records where it came from
  live      a guarded read-only query for Ask Relay: one SELECT, parsed with sqlglot in the warehouse's dialect, no
            DML/DDL anywhere, a row limit, a timeout, and on BigQuery a dry run that refuses big scans
"""
import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import sqlglot
from sqlglot import exp

from . import checkpoints, db, secrets_store
from . import connectors_sdk as sdk

PUBLIC_URL = os.environ.get("D2D_PUBLIC_URL", "").rstrip("/")
EXTRACT_MAX_ROWS = int(os.environ.get("D2D_EXTRACT_MAX_ROWS", "50000000"))
EXTRACT_TIMEOUT_S = int(os.environ.get("D2D_EXTRACT_TIMEOUT_S", "3600"))
MANIFEST = ".extracts.json"
ALIAS = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
BLOCKED = tuple(getattr(exp, n) for n in ("Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command",
                                          "TruncateTable", "Grant", "Copy", "Set", "Use", "Transaction", "Commit",
                                          "Rollback", "LoadData") if hasattr(exp, n))


class ConnectorError(Exception):
    pass


class Reconsent(ConnectorError):
    """The stored sign-in no longer works: the person must sign in to the warehouse again."""


# ---------------------------------------------------------------- what each warehouse needs

KINDS = {
    "snowflake": {"label": "Snowflake", "dialect": "snowflake", "auth": ["oauth", "password", "keypair"],
                  "fields": [("account", "Account identifier (orgname-account)", True), ("warehouse", "Warehouse", True),
                             ("database", "Database", True), ("role", "Role", False), ("user", "User name", False)],
                  "secrets": {"password": ["password"], "keypair": ["private_key"]}},
    "bigquery": {"label": "Google BigQuery", "dialect": "bigquery", "auth": ["oauth", "service_account"],
                 "fields": [("project", "Project id", True), ("billing_project", "Billing project (optional)", False),
                            ("location", "Location (optional, e.g. EU)", False)],
                 "secrets": {"service_account": ["service_account_json"]}},
    "fabric": {"label": "Microsoft Fabric", "dialect": "tsql", "auth": ["oauth"],
               "fields": [("server", "SQL endpoint (....datawarehouse.fabric.microsoft.com)", True),
                          ("database", "Warehouse or lakehouse name", True)], "secrets": {}},
    "redshift": {"label": "Amazon Redshift", "dialect": "redshift", "auth": ["password"],
                 "fields": [("host", "Host", True), ("port", "Port (5439)", False), ("database", "Database", True),
                            ("user", "User name", True)], "secrets": {"password": ["password"]}},
    "athena": {"label": "Amazon Athena", "dialect": "athena", "auth": ["aws_keys"],
               "fields": [("region", "Region", True), ("s3_staging_dir", "Query results location (s3://...)", True),
                          ("workgroup", "Workgroup (optional)", False), ("database", "Database", True),
                          ("dsn", "Power BI ODBC DSN name (for the Power BI file)", False)],
               "secrets": {"aws_keys": ["aws_access_key_id", "aws_secret_access_key"]}},
    "oracle_db": {"label": "Oracle Database", "dialect": "oracle", "auth": ["password", "wallet"],
                  "fields": [("host", "Host (add tcps:// for TLS, e.g. tcps://adb.uk-london-1.oraclecloud.com)", True),
                             ("port", "Port (1521; 1522 for Autonomous Database)", False),
                             ("service_name", "Service name (e.g. ORCLPDB1, or mydb_high.adb.oraclecloud.com)", True), ("user", "User name", True)],
                  "secrets": {"password": ["password"], "wallet": ["password", "wallet_pem", "wallet_password"]}},
}
OAUTH = {   # authorize / token endpoints; {tenant} and {account} come from the admin's app settings / the connection
    "bigquery": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
                 "scope": "https://www.googleapis.com/auth/bigquery.readonly", "extra": {"access_type": "offline", "prompt": "consent"}},
    "fabric": {"authorize": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
               "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
               "scope": "https://database.windows.net/.default offline_access", "extra": {}},
    "snowflake": {"authorize": "https://{account}.snowflakecomputing.com/oauth/authorize",
                  "token": "https://{account}.snowflakecomputing.com/oauth/token-request",
                  "scope": "refresh_token", "extra": {}, "basic_auth": True},
}


# ---------------------------------------------------------------- P10: the hub's vocabulary - categories, sign-in kinds, scopes, sharing

CATEGORIES = [("erp", "ERP & PLM"), ("finance", "Finance & HR"), ("crm", "CRM & ITSM"), ("warehouse", "Warehouses & databases"),
              ("integration", "Integration & automation"), ("bi", "BI tools"), ("files", "Files & content"), ("code", "Code & cloud")]
CATEGORY_LABEL = dict(CATEGORIES)
SIGNIN = {"sso": "Single sign-on (Entra ID / Google)", "oauth": "OAuth - sign in as me", "service_account": "Service account",
          "password": "User name and password", "api_key": "API key or token", "exports": "Upload exports instead"}
SIGNIN_OF = {"oauth": "oauth", "password": "password", "keypair": "api_key", "service_account": "service_account", "aws_keys": "api_key", "wallet": "password"}
SCOPES = {"read": "Read-only", "comment": "Read & comment", "write": "Read & write - with approval"}
SHARING = {"me": "Only me", "team": "My teams", "org": "The whole organisation"}
WRITE_KIND = "connection.write"
for _k, _v in KINDS.items():                         # the warehouses, wrapped by the SDK without a change in behaviour
    _v["category"] = "warehouse"
    sdk.register(sdk.OracleDbAdapter(_k, _v) if _k == "oracle_db" else sdk.WarehouseAdapter(_k, _v))
for _k, _a in sdk.REGISTRY.items():                  # SDK adapters (mock, rest_api, and every later platform) join the catalogue
    if _k not in KINDS:
        _d = _a.describe()
        KINDS[_k] = {"label": _d["label"], "dialect": _d["dialect"], "auth": list(_d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in _d["fields"]],
                     "secrets": _d["secrets"], "category": _d["category"], "sdk": True}
db.register_schema("-- P10: connection scope, limits, sharing, enabled, category, last test and re-consent (added columns)",
                   added_columns={"connections": {"scope": "TEXT NOT NULL DEFAULT 'read'", "limits": "TEXT", "sharing": "TEXT NOT NULL DEFAULT 'me'",
                                                  "enabled": "INTEGER NOT NULL DEFAULT 1", "category": "TEXT", "last_test": "REAL", "consented": "REAL"}})


def extractable(kind: str) -> bool:
    """Whether a kind's objects can be pulled into a dashboard: every SQL warehouse, and the API platforms that say so."""
    return bool(KINDS.get(kind, {}).get("dialect")) or bool(getattr(sdk.get(kind), "extract", False))


def native_pbip(kind: str) -> bool:
    """Whether the PBIP refreshes from the source itself (a Power BI connector), not from the pulled Parquet file."""
    from genbi_kit.report_builder import NATIVE_KINDS
    return kind in NATIVE_KINDS


def kinds_public() -> dict:
    apps = oauth_apps()
    return {k: {"label": v["label"], "auth": v["auth"], "fields": [{"key": f, "label": l, "required": r} for f, l, r in v["fields"]],
                "secrets": v["secrets"], "oauth_ready": k in OAUTH and bool(apps.get(k, {}).get("client_id")),
                "category": v.get("category") or "integration", "signin": list(dict.fromkeys(SIGNIN_OF.get(a, a) for a in v["auth"])),
                "sql": bool(v.get("dialect")), "can_write": bool(getattr(sdk.get(k), "can_write", False)), "sdk": bool(v.get("sdk")),
                "extract": extractable(k), "native": native_pbip(k)}
            for k, v in KINDS.items()}


def may_write(c: dict) -> bool:
    """Writes happen only on a connection whose scope is 'write' and that is enabled - and even then only after a
    person approved that very change (request_write opens the checkpoint; the adapter's write needs its id)."""
    return (c.get("scope") or "read") == "write" and bool(c.get("enabled", 1))


def may_comment(c: dict) -> bool:
    return (c.get("scope") or "read") in ("comment", "write") and bool(c.get("enabled", 1))


def _check_enabled(c: dict) -> None:
    if not c.get("enabled", 1):
        raise ConnectorError(f"{c['name']} is disabled. Enable it under Connections first.")


# ---------------------------------------------------------------- connections (rows) and their secrets

def _row(cid: str) -> dict:
    c = db.one("SELECT * FROM connections WHERE id = ?", (cid,))
    if not c:
        raise ConnectorError("Unknown connection")
    c["config"] = json.loads(c["config"] or "{}")
    return c


def _teams(uid: str) -> set[str]:
    return {r["team_id"] for r in db.q("SELECT team_id FROM memberships WHERE user_id = ?", (uid,))}


def shared_with(c: dict, uid: str) -> bool:
    """P10 sharing: the owner always; 'team' = anyone in one of the owner's teams; 'org' = everyone."""
    if c["owner_id"] == uid:
        return True
    s = c.get("sharing") or "me"
    if s == "org":
        return True
    return s == "team" and bool(_teams(c["owner_id"]) & _teams(uid))


def connection(cid: str, uid: str) -> dict:
    """A connection this person may use: their own, or one shared with their team or the organisation (P10).
    It runs with the stored sign-in of its owner; every use is audited with who asked."""
    c = _row(cid)
    if not shared_with(c, uid):
        raise ConnectorError("Unknown connection")
    return c


def owned(cid: str, uid: str, admin_ok: bool = False) -> dict:
    """A connection this person may change: its owner (or an admin, for sharing / disabling)."""
    c = _row(cid)
    if c["owner_id"] != uid and not (admin_ok and (db.user(uid) or {}).get("org_role") == "admin"):
        raise ConnectorError("Only the connection's owner can change it.")
    return c


def usage_map() -> dict[str, list[dict]]:
    """Which dashboards (data/.extracts.json, or the warehouse they were created from) and which module folders that
    list their `connections` (starts, the workbench's work items ...) use each connection - derived, never stored."""
    from . import agents, store
    out: dict[str, list[dict]] = {}
    for p in store.all_projects():
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        if p.get("kind", "dashboard") != "dashboard":    # a start, a workbench work item, any module folder that lists its connections
            here = agents.place(p["id"], st) if st.get("connections") else None
            for cid in st.get("connections") or []:
                if isinstance(cid, str):
                    out.setdefault(cid, []).append({"kind": p.get("kind"), "id": p["id"], "name": p["name"], "module": here["module"], "link": here["link"]})
            continue
        ids = {m.get("connection_id") for m in manifest(store.project_dir(p["id"])).values()}
        if (st.get("warehouse") or {}).get("connection_id"):
            ids.add(st["warehouse"]["connection_id"])
        for cid in ids:
            if cid:
                out.setdefault(cid, []).append({"kind": "dashboard", "id": p["id"], "name": p["name"], "module": "D2D dashboards", "link": f"#/p/{p['id']}"})
    return out


def used_by(cid: str) -> list[dict]:
    return usage_map().get(cid, [])


def public(c: dict, uid: str | None = None, uses: dict | None = None) -> dict:
    names = KINDS[c["kind"]]["secrets"].get(c["auth_mode"], [])
    tables = db.q("SELECT object, alias, object_type, rows, added FROM connection_tables WHERE connection_id = ? ORDER BY object", (c["id"],))
    owner = db.one("SELECT name FROM users WHERE id = ?", (c["owner_id"],))
    return {**{k: c[k] for k in ("id", "kind", "name", "config", "auth_mode", "status", "error", "created", "last_used")},
            "label": KINDS[c["kind"]]["label"], "tables": tables,
            "has_secret": {n: secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{n}") is not None for n in names},
            # P10: category, sign-in kind, scope, sharing, enabled, used by
            "category": c.get("category") or KINDS[c["kind"]].get("category") or "integration", "signin": SIGNIN_OF.get(c["auth_mode"], c["auth_mode"]),
            "scope": c.get("scope") or "read", "limits": c.get("limits") or "", "sharing": c.get("sharing") or "me", "enabled": bool(c.get("enabled", 1)),
            "last_test": c.get("last_test"), "consented": c.get("consented"), "owner_id": c["owner_id"], "owner": owner["name"] if owner else c["owner_id"],
            "own": uid is None or c["owner_id"] == uid, "sql": bool(KINDS[c["kind"]].get("dialect")), "sdk": bool(KINDS[c["kind"]].get("sdk")),
            "can_write": bool(getattr(sdk.get(c["kind"]), "can_write", False)), "extract": extractable(c["kind"]), "native": native_pbip(c["kind"]),
            "used_by": (uses if uses is not None else usage_map()).get(c["id"], [])}


def mine(uid: str) -> list[dict]:
    """The connections this person may use: their own and the ones shared with them (P10)."""
    uses = usage_map()
    return [public({**c, "config": json.loads(c["config"] or "{}")}, uid, uses)
            for c in db.q("SELECT * FROM connections ORDER BY created") if shared_with(c, uid)]


def save(uid: str, body: dict, cid: str | None = None) -> dict:
    kind = body.get("kind")
    if cid:
        c = owned(cid, uid)
        kind = c["kind"]
    if kind not in KINDS:
        raise ConnectorError("Choose a system.")
    spec = KINDS[kind]
    auth = body.get("auth_mode") or (c["auth_mode"] if cid else spec["auth"][0])
    if auth not in spec["auth"]:
        raise ConnectorError(f"{spec['label']} sign-in must be one of: {', '.join(spec['auth'])}.")
    if auth == "oauth" and not oauth_apps().get(kind, {}).get("client_id"):
        raise ConnectorError(f"Your administrator has not set up {spec['label']} sign-in yet; use another method.")
    config = {f: str((body.get("config") or {}).get(f, "")).strip() for f, _, _ in spec["fields"]}
    if kind == "oracle_db":
        config = oracle_normalise(config)
    missing = [l for f, l, r in spec["fields"] if r and not config[f] and not (auth == "oauth" and f == "user")]
    if kind == "snowflake" and auth in ("password", "keypair") and not config["user"]:
        missing.append("User name (needed for this sign-in method)")
    if missing:
        raise ConnectorError("Fill in: " + ", ".join(missing))
    if kind == "oracle_db":
        bad = oracle_config_problems(config)
        if bad:
            raise ConnectorError("; ".join(bad))
    name = (body.get("name") or f"{spec['label']} - {config.get('database') or config.get('service_name') or config.get('project') or config.get('site') or ''}").strip(" -")[:80]
    scope = body.get("scope") or (c.get("scope") if cid else None) or "read"
    sharing = body.get("sharing") or (c.get("sharing") if cid else None) or "me"
    if scope not in SCOPES:
        raise ConnectorError("Scope must be read, comment or write.")
    if sharing not in SHARING:
        raise ConnectorError("Share with me, team or org.")
    limits = " ".join(str(body.get("limits") if body.get("limits") is not None else (c.get("limits") if cid else "") or "").split())[:300]
    category = body.get("category") if body.get("category") in CATEGORY_LABEL else (spec.get("category") or "integration")
    if cid:
        db.run("UPDATE connections SET name = ?, config = ?, auth_mode = ?, scope = ?, limits = ?, sharing = ?, category = ? WHERE id = ?",
               (name, json.dumps(config), auth, scope, limits, sharing, category, cid))
    else:
        cid = "c-" + secrets.token_hex(6)
        db.run("INSERT INTO connections (id, owner_id, kind, name, config, auth_mode, status, created, scope, limits, sharing, category, enabled) "
               "VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, 1)", (cid, uid, kind, name, json.dumps(config), auth, time.time(), scope, limits, sharing, category))
    for n in spec["secrets"].get(auth, []):
        v = (body.get("secrets") or {}).get(n)
        if v:
            secrets_store.put(f"user:{uid}", f"conn:{cid}:{n}", v, uid)
            db.run("UPDATE connections SET consented = ? WHERE id = ?", (time.time(), cid))
    db.audit("connection.save", cid, {"kind": kind, "auth": auth, "config": config, "scope": scope, "sharing": sharing}, uid)
    return public(_row(cid), uid)


def set_scope(cid: str, uid: str, scope: str, limits: str | None = None) -> dict:
    c = owned(cid, uid)
    if scope not in SCOPES:
        raise ConnectorError("Scope must be read, comment or write.")
    db.run("UPDATE connections SET scope = ?, limits = ? WHERE id = ?", (scope, " ".join((limits if limits is not None else c.get("limits") or "").split())[:300], cid))
    db.audit("connection.scope", cid, {"scope": scope, "limits": (limits or "")[:300]}, uid)
    return public(_row(cid), uid)


def set_sharing(cid: str, uid: str, sharing: str) -> dict:
    owned(cid, uid, admin_ok=True)
    if sharing not in SHARING:
        raise ConnectorError("Share with me, team or org.")
    db.run("UPDATE connections SET sharing = ? WHERE id = ?", (sharing, cid))
    db.audit("connection.sharing", cid, {"sharing": sharing}, uid)
    return public(_row(cid), uid)


def set_enabled(cid: str, uid: str, enabled: bool) -> dict:
    """Disable: nothing may use it until it is enabled again (what stops working is in used_by, shown before)."""
    owned(cid, uid, admin_ok=True)
    db.run("UPDATE connections SET enabled = ? WHERE id = ?", (1 if enabled else 0, cid))
    db.audit("connection.enable" if enabled else "connection.disable", cid, {"used_by": [u["name"] for u in used_by(cid)]}, uid)
    return public(_row(cid), uid)


def renew(cid: str, uid: str, new_secrets: dict | None = None) -> dict:
    """Re-consent: OAuth kinds sign in again (the caller redirects to oauth_start); key / password kinds take the new
    secret here. Without one the connection waits in 'reconsent' until it arrives."""
    c = owned(cid, uid)
    names = KINDS[c["kind"]]["secrets"].get(c["auth_mode"], [])
    if c["auth_mode"] == "oauth":
        _status(c, "reconsent", "Sign in again to renew the connection.")
        db.audit("connection.renew", cid, {"kind": c["kind"], "how": "oauth"}, uid)
        return {"redirect": f"/api/connections/{cid}/oauth/start", **public(_row(cid), uid)}
    given = {n: v for n, v in (new_secrets or {}).items() if n in names and v}
    for n, v in given.items():
        secrets_store.put(f"user:{uid}", f"conn:{cid}:{n}", v, uid)
    if given:
        db.run("UPDATE connections SET consented = ?, status = 'new', error = NULL WHERE id = ?", (time.time(), cid))
    else:
        _status(c, "reconsent", "Renew: enter the new " + " and ".join(n.replace("_", " ") for n in names) + ".")
    db.audit("connection.renew", cid, {"kind": c["kind"], "how": "secret", "renewed": sorted(given)}, uid)
    return public(_row(cid), uid)


# ---------------------------------------------------------------- writes: scope + a person's approval, never direct (P10)

WRITE_HOOKS: dict = {}     # consolidation: origin prefix (payload "from", e.g. studio:<id>:v2) -> fn(checkpoint, event, result)


def register_write_hook(prefix: str, fn) -> None:
    """The module that asked hears what happened: event = written (result = what the adapter returned) | failed
    (result = the reason) | sent_back (result = the comment)."""
    WRITE_HOOKS[prefix] = fn


def _write_hook(cp: dict, event: str, result) -> None:
    origin = str(((cp.get("evidence") or {}).get("payload") or {}).get("from") or "")
    fn = WRITE_HOOKS.get(origin.split(":", 1)[0])
    if fn:
        try:
            fn(cp, event, result)
        except Exception:  # noqa: BLE001 - the write's own outcome is recorded and audited either way
            pass


def request_write(c: dict, obj: str, payload: dict, who: str, module: str = "Connections", what: str | None = None, items: list[str] | None = None,
                  link: str | None = None) -> dict:
    """The only way anything is written to a connected system: the scope must allow writes, and a checkpoint opens
    for a named person; the adapter writes when (and only when) it is accepted. `items` (optional) is what the
    approver reads in the Validation queue, in plain words (by default the payload's fields); `link` where the
    work that asked lives (by default the Connections hub)."""
    _check_enabled(c)
    if not may_write(c):
        raise sdk.ScopeError(f"{c['name']} is {SCOPES.get(c.get('scope') or 'read')}: writes are not allowed on it. Change its scope to 'Read & write - with approval' first.")
    adapter = sdk.get(c["kind"])
    if not adapter or not adapter.can_write:
        raise sdk.ScopeError(f"{KINDS[c['kind']]['label']} connections are read-only in Relay.")
    name = what or f"Write to {c['name']}: {obj} ({secrets.token_hex(3)})"
    cp = checkpoints.open(WRITE_KIND, c["id"], module, name, "table",
                          {"summary": f"{obj} on {c['name']} ({KINDS[c['kind']]['label']}) - nothing is written until you accept",
                           "items": items or [f"{k}: {v}" for k, v in list(payload.items())[:8]], "counts": {"fields": len(payload)}, "object": obj, "payload": payload},
                          link=link or "#/connections", assignee=who, agent="Relay", opened_by=who)
    db.audit("connection.write_requested", c["id"], {"object": obj, "checkpoint": cp["id"], "fields": sorted(payload)}, who)
    return cp


def _on_write_decision(cp: dict, decision: str, comment: str | None, who: str) -> None:
    ev = cp.get("evidence") or {}
    if decision != "accept":
        db.audit("connection.write_refused", cp["subject"], {"object": ev.get("object"), "comment": (comment or "")[:300]}, who)
        _write_hook(cp, "sent_back", comment)
        return
    try:
        c = _row(cp["subject"])
        adapter = sdk.get(c["kind"])
        result = adapter.write(c, ev.get("object"), ev.get("payload") or {}, approval=cp["id"])
        db.audit("connection.write", c["id"], {"object": ev.get("object"), "checkpoint": cp["id"], "result": str(result)[:300]}, who)
        from . import usage
        usage.record("warehouse", who, step=c["kind"], obj=c["id"])
    except (sdk.ScopeError, ConnectorError, Exception) as e:  # noqa: BLE001 - the decision is recorded; the failure too
        db.audit("connection.write_failed", cp["subject"], {"object": ev.get("object"), "error": str(e)[:300]}, who)
        from . import notify
        notify.add(who, "alert", "The approved write did not go through", str(e)[:300], "#/connections")
        _write_hook(cp, "failed", str(e))
        return
    _write_hook(cp, "written", result)


checkpoints.register_kind(WRITE_KIND, "Write to a connected system", _on_write_decision)


def remove(cid: str, uid: str) -> None:
    c = owned(cid, uid, admin_ok=True)
    for s in secrets_store.names():
        if s["scope"] == f"user:{uid}" and s["name"].startswith(f"conn:{cid}:"):
            secrets_store.delete(s["scope"], s["name"], uid)
    db.run("DELETE FROM connection_tables WHERE connection_id = ?", (cid,))
    db.run("DELETE FROM connections WHERE id = ?", (cid,))
    db.audit("connection.remove", cid, {"kind": c["kind"]}, uid)


def _secret(c: dict, name: str) -> str | None:
    return secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}")


def _status(c: dict, status: str, error: str | None = None) -> None:
    db.run("UPDATE connections SET status = ?, error = ?, last_used = ? WHERE id = ?", (status, error, time.time(), c["id"]))


def _sdk(c: dict):
    """The SDK adapter of a non-warehouse kind (None for the five warehouses, which keep their own code paths)."""
    a = sdk.get(c["kind"])
    return a if a is not None and not isinstance(a, sdk.WarehouseAdapter) else None


# ---------------------------------------------------------------- OAuth sign-in to a warehouse (offline access)

def oauth_apps() -> dict:
    """Admin settings per warehouse: client id, tenant (Entra), ... - client secrets are in the secrets store."""
    return json.loads(db.meta("connector_oauth") or "{}")


def save_oauth_apps(apps: dict, secrets_by_kind: dict, who: str | None) -> dict:
    clean = {}
    for kind, a in (apps or {}).items():
        if kind not in OAUTH:
            continue
        clean[kind] = {"client_id": str(a.get("client_id", "")).strip(), "tenant": str(a.get("tenant", "")).strip(),
                       "role": str(a.get("role", "")).strip()}
        if kind == "fabric" and clean[kind]["client_id"] and not clean[kind]["tenant"]:
            raise ConnectorError("Microsoft Fabric sign-in needs your Entra tenant id.")
    for kind, secret in (secrets_by_kind or {}).items():
        if kind in OAUTH and secret:
            secrets_store.put("org", f"connector_oauth:{kind}:client_secret", secret, who)
    db.set_meta("connector_oauth", json.dumps(clean))
    db.audit("connector.oauth", None, {"kinds": [k for k, v in clean.items() if v["client_id"]]}, who)
    return {k: {**v, "has_secret": secrets_store.get("org", f"connector_oauth:{k}:client_secret") is not None} for k, v in clean.items()}


def _endpoints(c: dict) -> tuple[dict, dict]:
    spec, app = OAUTH[c["kind"]], oauth_apps().get(c["kind"]) or {}
    fill = lambda u: u.format(tenant=app.get("tenant", ""), account=c["config"].get("account", ""))  # noqa: E731
    return {**spec, "authorize": fill(spec["authorize"]), "token": fill(spec["token"])}, app


def redirect_uri(base_url: str) -> str:
    return f"{PUBLIC_URL or base_url.rstrip('/')}/auth/connector/callback"


def oauth_start(cid: str, uid: str, base_url: str) -> str:
    c = owned(cid, uid)
    if c["auth_mode"] != "oauth":
        raise ConnectorError("This connection does not use sign-in.")
    ep, app = _endpoints(c)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.run("INSERT INTO auth_flows (state, provider, verifier, nonce, return_to, created) VALUES (?, ?, ?, ?, ?, ?)",
           (state, f"conn:{cid}", verifier, uid, "#/connections", time.time()))
    scope = ep["scope"] + (f" session:role:{app['role']}" if c["kind"] == "snowflake" and app.get("role") else "")
    q = {"response_type": "code", "client_id": app["client_id"], "redirect_uri": redirect_uri(base_url), "scope": scope,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256", **ep["extra"]}
    return ep["authorize"] + "?" + urlencode(q)


def _token_request(c: dict, form: dict) -> dict:
    ep, app = _endpoints(c)
    secret = secrets_store.get("org", f"connector_oauth:{c['kind']}:client_secret")
    headers, form = {"Accept": "application/json"}, {**form, "client_id": app["client_id"]}
    if ep.get("basic_auth") and secret:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{app['client_id']}:{secret}".encode()).decode()
    elif secret:
        form["client_secret"] = secret
    r = httpx.post(ep["token"], data=form, headers=headers, timeout=20)
    if r.status_code != 200:
        raise Reconsent(f"The warehouse did not accept the sign-in ({r.status_code}).")
    t = r.json()
    return {"access_token": t["access_token"], "refresh_token": t.get("refresh_token"),
            "expires_at": time.time() + float(t.get("expires_in") or 3600), "scope": t.get("scope")}


def oauth_callback(state: str, code: str, base_url: str) -> tuple[str, str]:
    flow = db.one("SELECT * FROM auth_flows WHERE state = ? AND provider LIKE 'conn:%'", (state,))
    db.run("DELETE FROM auth_flows WHERE state = ?", (state,))
    if not flow or time.time() - flow["created"] > 900:
        raise ConnectorError("The sign-in took too long or was already used. Try again.")
    cid, uid = flow["provider"][5:], flow["nonce"]
    c = connection(cid, uid)
    tok = _token_request(c, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(base_url),
                             "code_verifier": flow["verifier"]})
    secrets_store.put(f"user:{uid}", f"conn:{cid}:oauth", json.dumps(tok), uid)
    _status(c, "connected" if tok.get("refresh_token") else "connected_no_offline",
            None if tok.get("refresh_token") else "No offline access: scheduled extracts will need you signed in.")
    db.run("UPDATE connections SET consented = ? WHERE id = ?", (time.time(), cid))
    db.audit("connection.signin", cid, {"kind": c["kind"], "offline": bool(tok.get("refresh_token"))}, uid)
    return cid, uid


def access_token(c: dict) -> str:
    raw = _secret(c, "oauth")
    if not raw:
        raise Reconsent("Sign in to the warehouse first.")
    tok = json.loads(raw)
    if tok["expires_at"] - 60 > time.time():
        return tok["access_token"]
    if not tok.get("refresh_token"):
        _status(c, "reconsent", "Your sign-in expired. Sign in again.")
        raise Reconsent("Your sign-in to the warehouse expired. Sign in again.")
    try:
        new = _token_request(c, {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    except (Reconsent, httpx.HTTPError) as e:
        _status(c, "reconsent", "The warehouse no longer accepts your sign-in. Sign in again.")
        raise Reconsent("The warehouse no longer accepts your sign-in. Sign in again.") from e
    new["refresh_token"] = new.get("refresh_token") or tok["refresh_token"]
    secrets_store.put(f"user:{c['owner_id']}", f"conn:{c['id']}:oauth", json.dumps(new), "system")
    return new["access_token"]


# ---------------------------------------------------------------- Oracle Database: Easy Connect, the wallet, typed batches

ORACLE_HOST = re.compile(r"^(?:(tcps?)://)?([A-Za-z0-9][\w.\-]*|\[[0-9A-Fa-f:.]+\])$", re.I)
ORACLE_EZ = re.compile(r"^(?:(tcps?)://)?([^:/\s\[\]]+|\[[0-9A-Fa-f:.]+\])(?::(\d+))?(?:/([^\s/?]+))?/?$", re.I)
ORACLE_OWN = "SELECT username FROM all_users WHERE oracle_maintained = 'Y'"      # SYS, SYSTEM, XDB, MDSYS ... (12c and later)
ORACLE_SEES = (f"SELECT (SELECT COUNT(*) FROM all_tables WHERE owner NOT IN ({ORACLE_OWN})) AS t, (SELECT COUNT(*) FROM all_views WHERE owner NOT IN ({ORACLE_OWN})) AS v, "
               "(SELECT version FROM product_component_version WHERE ROWNUM = 1) AS ver FROM dual")
PROBE_SQL = {"oracle_db": "SELECT 1 AS ok FROM dual"}


def oracle_normalise(cfg: dict) -> dict:
    """An Easy Connect string typed into Host (db1:1521/ORCLPDB1, tcps://adb...:1522/svc) is split into its fields."""
    m = ORACLE_EZ.match(cfg.get("host", "").strip())
    if not m or not (m.group(3) or m.group(4)):
        return cfg
    out = {**cfg, "host": ("tcps://" if (m.group(1) or "").lower() == "tcps" else "") + m.group(2)}
    if m.group(3) and not out.get("port"):
        out["port"] = m.group(3)
    if m.group(4) and not out.get("service_name"):
        out["service_name"] = m.group(4)
    return out


def oracle_config_problems(cfg: dict) -> list[str]:
    out = []
    if not ORACLE_HOST.match(cfg.get("host", "").strip()):
        out.append("Host must be a host name or address, optionally starting with tcps:// (the port and the service name have their own fields)")
    if cfg.get("port") and not str(cfg["port"]).strip().isdigit():
        out.append("Port must be a number (1521; 1522 for Autonomous Database)")
    if not re.fullmatch(r"[\w.$#\-]+", cfg.get("service_name", "").strip()):
        out.append("Service name must be one word such as ORCLPDB1 (an SID alone is not enough: ask the DBA for the service name)")
    return out


def oracle_dsn(cfg: dict) -> str:
    """Easy Connect for python-oracledb and Power BI: [tcps://]host:port/service_name (TLS on port 1522 by default)."""
    m = ORACLE_HOST.match(cfg.get("host", "").strip())
    tls = bool(m and (m.group(1) or "").lower() == "tcps")
    host = m.group(2) if m else cfg.get("host", "").strip()
    port = str(cfg.get("port") or "").strip() or ("1522" if tls else "1521")
    return f"{'tcps://' if tls else ''}{host}:{port}/{cfg.get('service_name', '').strip()}"


def _oracle_wallet(c: dict) -> str:
    """Mutual TLS (an Autonomous Database wallet): the connection's ewallet.pem in a folder only this process may read,
    rewritten at every connect so a renewed wallet replaces the old one; python-oracledb reads it from there."""
    pem = (_secret(c, "wallet_pem") or "").replace("\r\n", "\n")
    if "-----BEGIN" not in pem:
        raise ConnectorError("The wallet must be the text of ewallet.pem from the database's wallet zip (it starts with -----BEGIN).")
    d = Path(tempfile.gettempdir()) / "relay-oracle-wallets" / f"{db.tenant()}-{c['id']}"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    f = d / "ewallet.pem"
    with open(f, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(pem)
    os.chmod(f, 0o600)
    return str(d)


def _oracle_schema(desc) -> pa.Schema:
    """Arrow types from the cursor's description, so every batch of an extract has the same schema: NUMBER(p, 0) and
    INTEGER are whole numbers, other NUMBERs and BINARY_* doubles, DATE / TIMESTAMP timestamps, RAW / BLOB bytes, the
    rest (VARCHAR2, CHAR, CLOB, LONG, INTERVAL, JSON, ROWID ...) text."""
    import oracledb as o
    stamps = (o.DB_TYPE_DATE, o.DB_TYPE_TIMESTAMP, o.DB_TYPE_TIMESTAMP_TZ, o.DB_TYPE_TIMESTAMP_LTZ)
    fields = []
    for d in desc:
        t, prec, scale = d[1], d[4], d[5]
        if t == o.DB_TYPE_NUMBER:
            at = pa.int64() if scale == 0 and (prec or 0) > 0 else pa.float64()
        elif t == o.DB_TYPE_BINARY_INTEGER:
            at = pa.int64()
        elif t in (o.DB_TYPE_BINARY_DOUBLE, o.DB_TYPE_BINARY_FLOAT):
            at = pa.float64()
        elif t in stamps:
            at = pa.timestamp("us")
        elif t in (o.DB_TYPE_RAW, o.DB_TYPE_LONG_RAW, o.DB_TYPE_BLOB):
            at = pa.binary()
        elif t == getattr(o, "DB_TYPE_BOOLEAN", None):
            at = pa.bool_()
        else:
            at = pa.string()
        fields.append(pa.field(d[0], at))
    return pa.schema(fields)


def _oracle_table(rows: list, schema: pa.Schema) -> pa.Table:
    cols = list(zip(*rows))
    arrays = []
    for i, f in enumerate(schema):
        vals = cols[i]
        if pa.types.is_string(f.type):
            vals = [v if v is None or isinstance(v, str) else json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v) for v in vals]
        elif pa.types.is_floating(f.type):
            vals = [None if v is None else float(v) for v in vals]
        arrays.append(pa.array(vals, type=f.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _sees(c: dict) -> str:
    """What a database sign-in can read, in words (best effort: the test itself already passed)."""
    if c["kind"] != "oracle_db":
        return ""
    try:
        r = [list(x.values()) for t in _batches(c, ORACLE_SEES, 30, 1) for x in t.to_pylist()][0]
        return f"{int(r[0]):,} table(s) and {int(r[1]):,} view(s) this sign-in can read - Oracle Database {r[2]}"
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- adapters: open, list, stream

def _open(c: dict):
    """A DB-API connection (or a BigQuery client) with the person's own credentials."""
    k, cfg = c["kind"], c["config"]
    if k == "oracle_db":
        import oracledb
        oracledb.defaults.fetch_lobs = False                # CLOB / NCLOB as text, BLOB as bytes (no LOB handles to read later)
        args = {"user": cfg["user"], "password": _secret(c, "password"), "dsn": oracle_dsn(cfg), "tcp_connect_timeout": 20.0}
        if c["auth_mode"] == "wallet":
            args.update(wallet_location=_oracle_wallet(c), wallet_password=_secret(c, "wallet_password") or None)
        conn = oracledb.connect(**args)
        try:                                                # the database's own session views show who asked, through Relay
            conn.module, conn.client_identifier = "Relay", str(c.get("_who") or c["owner_id"])[:64]
        except Exception:  # noqa: BLE001
            pass
        return conn
    if k == "snowflake":
        import snowflake.connector
        args = {"account": cfg["account"], "warehouse": cfg["warehouse"], "database": cfg["database"],
                "role": cfg.get("role") or None, "login_timeout": 30, "network_timeout": 600, "application": "D2D"}
        if c["auth_mode"] == "oauth":
            args.update(authenticator="oauth", token=access_token(c))
        elif c["auth_mode"] == "keypair":
            from cryptography.hazmat.primitives import serialization
            key = serialization.load_pem_private_key(_secret(c, "private_key").encode(), password=None)
            args.update(user=cfg["user"], private_key=key.private_bytes(serialization.Encoding.DER,
                                                                        serialization.PrivateFormat.PKCS8,
                                                                        serialization.NoEncryption()))
        else:
            args.update(user=cfg["user"], password=_secret(c, "password"))
        return snowflake.connector.connect(**{k2: v for k2, v in args.items() if v is not None})
    if k == "bigquery":
        from google.cloud import bigquery
        if c["auth_mode"] == "oauth":
            from google.oauth2.credentials import Credentials
            creds = Credentials(token=access_token(c))
        else:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(json.loads(_secret(c, "service_account_json")))
        return bigquery.Client(project=cfg.get("billing_project") or cfg["project"], credentials=creds,
                               location=cfg.get("location") or None)
    if k == "fabric":
        import struct

        import pyodbc
        raw = access_token(c).encode("utf-16-le")
        conn = pyodbc.connect(f"Driver={{ODBC Driver 18 for SQL Server}};Server={cfg['server']},1433;Database={cfg['database']};"
                              "Encrypt=yes;TrustServerCertificate=no", attrs_before={1256: struct.pack(f"<I{len(raw)}s", len(raw), raw)},
                              timeout=30)
        return conn
    if k == "redshift":
        import redshift_connector
        return redshift_connector.connect(host=cfg["host"], port=int(cfg.get("port") or 5439), database=cfg["database"],
                                          user=cfg["user"], password=_secret(c, "password"), timeout=30)
    if k == "athena":
        from pyathena import connect
        from pyathena.arrow.cursor import ArrowCursor
        return connect(region_name=cfg["region"], s3_staging_dir=cfg["s3_staging_dir"], work_group=cfg.get("workgroup") or None,
                       schema_name=cfg["database"], aws_access_key_id=_secret(c, "aws_access_key_id"),
                       aws_secret_access_key=_secret(c, "aws_secret_access_key"), cursor_class=ArrowCursor)
    raise ConnectorError("Unknown warehouse")


def _timeout_sql(kind: str, seconds: int) -> str | None:
    return {"snowflake": f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {int(seconds)}",
            "redshift": f"SET statement_timeout TO {int(seconds) * 1000}"}.get(kind)


def _batches(c: dict, sql: str, timeout: int, max_rows: int, max_bytes: int | None = None):
    """Run one query and yield Arrow tables, batch by batch (never the whole result in memory at once)."""
    conn = _open(c)
    try:
        if c["kind"] == "bigquery":
            from google.cloud import bigquery
            cfg = bigquery.QueryJobConfig(maximum_bytes_billed=max_bytes) if max_bytes else None
            job = conn.query(sql, job_config=cfg, timeout=timeout)
            rows = job.result(timeout=timeout, page_size=50_000)
            n = 0
            for t in rows.to_arrow_iterable():
                tbl = pa.Table.from_batches([t]) if isinstance(t, pa.RecordBatch) else t
                n += tbl.num_rows
                yield tbl
                if n >= max_rows:
                    break
            return
        cur = conn.cursor()
        pre = _timeout_sql(c["kind"], timeout)
        if pre:
            try:
                cur.execute(pre)
            except Exception:  # noqa: BLE001 - some engines (and test doubles) do not know the setting
                pass
        if c["kind"] == "fabric":
            conn.timeout = timeout
        if c["kind"] == "oracle_db":
            conn.call_timeout = int(timeout) * 1000          # milliseconds per round trip: the database cancels the call past it
            cur.arraysize = 5000
        cur.execute(sql)
        n = 0
        if c["kind"] == "oracle_db":
            schema = _oracle_schema(cur.description)
            while n < max_rows:
                rows = cur.fetchmany(min(50_000, max_rows - n))
                if not rows:
                    break
                n += len(rows)
                yield _oracle_table(rows, schema)
            return
        if c["kind"] == "snowflake" and hasattr(cur, "fetch_arrow_batches"):
            try:
                batches = cur.fetch_arrow_batches()
            except (NotImplementedError, AttributeError):
                batches = None                      # a driver without Arrow batches: plain row batches below
            if batches is not None:
                for tbl in batches:
                    n += tbl.num_rows
                    yield tbl
                    if n >= max_rows:
                        return
                return
        if c["kind"] == "athena":
            tbl = cur.as_arrow()
            yield tbl.slice(0, max_rows)
            return
        names = [d[0] for d in cur.description]
        while n < max_rows:
            rows = cur.fetchmany(50_000)
            if not rows:
                break
            n += len(rows)
            yield pa.Table.from_pylist([dict(zip(names, r)) for r in rows])
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def quote(kind: str, obj: str) -> str:
    """A fully qualified object name as SQL for that warehouse (each part quoted)."""
    dialect = KINDS[kind]["dialect"]
    parts = [p.strip().strip('"`[]') for p in obj.split(".")]
    if not all(re.fullmatch(r"[\w$\- ]+", p) for p in parts):
        raise ConnectorError(f"Not a table name: {obj}")
    return exp.table_(parts[-1], db=parts[-2] if len(parts) > 1 else None, catalog=parts[-3] if len(parts) > 2 else None,
                      quoted=True).sql(dialect=dialect)


def browse(c: dict, search: str = "") -> list[dict]:
    """Tables and views the person's login can see (the warehouse decides); objects of an SDK platform."""
    _check_enabled(c)
    a = _sdk(c)
    if a:
        return a.list_objects(c, search)
    k, cfg = c["kind"], c["config"]
    s = f"%{search.strip().lower()}%"
    if k == "bigquery":
        conn = _open(c)
        out = []
        for ds in conn.list_datasets(cfg["project"]):
            for t in conn.list_tables(ds.reference):
                name = f"{t.project}.{t.dataset_id}.{t.table_id}"
                if search.strip().lower() in name.lower():
                    out.append({"object": name, "type": t.table_type})
                if len(out) >= 500:
                    return out
        return out
    if k == "oracle_db":                                  # its own branch: the others' SQL below reads cfg['database'], which Oracle does not have
        like = s.replace(chr(39), "")
        sql = (f"SELECT owner || '.' || table_name AS obj, 'TABLE' AS t FROM all_tables WHERE owner NOT IN ({ORACLE_OWN}) AND nested = 'NO' "
               f"AND secondary = 'N' AND dropped = 'NO' AND LOWER(table_name) LIKE '{like}' UNION ALL "
               f"SELECT owner || '.' || view_name, 'VIEW' FROM all_views WHERE owner NOT IN ({ORACLE_OWN}) AND LOWER(view_name) LIKE '{like}' "
               "ORDER BY 1 FETCH FIRST 500 ROWS ONLY")
        return [{"object": r["OBJ"], "type": r["T"]} for t in _batches(c, sql, 60, 500) for r in t.to_pylist()]
    sql = {"snowflake": f"SELECT table_catalog || '.' || table_schema || '.' || table_name, table_type FROM "
                        f"{quote(k, cfg['database'] + '.INFORMATION_SCHEMA.TABLES')} WHERE table_schema <> 'INFORMATION_SCHEMA' "
                        f"AND lower(table_name) LIKE '{s.replace(chr(39), '')}' ORDER BY 1 LIMIT 500",
           "fabric": "SELECT TOP 500 table_schema + '.' + table_name, table_type FROM INFORMATION_SCHEMA.TABLES "
                     f"WHERE table_schema NOT IN ('sys', 'INFORMATION_SCHEMA') AND lower(table_name) LIKE '{s.replace(chr(39), '')}' ORDER BY 1",
           "redshift": "SELECT table_schema || '.' || table_name, table_type FROM information_schema.tables WHERE table_schema NOT IN "
                       f"('pg_catalog', 'information_schema') AND lower(table_name) LIKE '{s.replace(chr(39), '')}' ORDER BY 1 LIMIT 500",
           "athena": "SELECT table_catalog || '.' || table_schema || '.' || table_name, table_type FROM information_schema.tables "
                     f"WHERE table_schema = '{cfg['database'].replace(chr(39), '')}' AND lower(table_name) LIKE '{s.replace(chr(39), '')}' LIMIT 500"}[k]
    out = []
    for tbl in _batches(c, sql, 60, 500):
        for row in tbl.to_pylist():
            v = list(row.values())
            out.append({"object": v[0], "type": v[1]})
    return out


def test(c: dict) -> dict:
    """Sign in and run a trivial query (or the adapter's own test); the connection's status and last test follow."""
    _check_enabled(c)
    a = _sdk(c)
    try:
        sees = a.test(c).get("sees", "") if a else ""
        if not a:
            for _ in _batches(c, PROBE_SQL.get(c["kind"], "SELECT 1 AS ok"), 30, 1):
                pass
            sees = _sees(c)
    except Reconsent as e:
        _status(c, "reconsent", str(e))
        raise
    except (sdk.ScopeError, ConnectorError) as e:
        _status(c, "error", str(e)[:300])
        raise ConnectorError(str(e)[:300]) from e
    except Exception as e:  # noqa: BLE001 - shown to the person
        _status(c, "error", str(e).splitlines()[0][:300])
        raise ConnectorError(str(e).splitlines()[0][:300]) from e
    _status(c, "connected")
    db.run("UPDATE connections SET last_test = ? WHERE id = ?", (time.time(), c["id"]))
    db.audit("connection.test", c["id"], {"kind": c["kind"], "sees": sees[:200]}, c.get("_who"))
    return {**public(_row(c["id"]), c.get("_who")), "sees": sees}


def read_object(c: dict, obj: str, who: str | None, limit: int = 100) -> dict:
    """One object of an SDK platform (tickets, projects, an endpoint), read-only and audited; warehouses use query()."""
    _check_enabled(c)
    a = _sdk(c)
    if not a:
        return query(c, f"SELECT * FROM {quote(c['kind'], obj)}", who)
    try:
        out = a.read(c, obj, limit)
    except Reconsent as e:
        _status(c, "reconsent", str(e))
        raise
    except sdk.ScopeError as e:
        raise ConnectorError(str(e)) from e
    _status(c, "connected")
    db.audit("query", c["id"], {"kind": c["kind"], "object": obj, "rows": out.get("row_count")}, who)
    return out


# ---------------------------------------------------------------- configured tables

def alias_for(obj: str) -> str:
    a = re.sub(r"[^a-z0-9_]+", "_", obj.split(".")[-1].lower()).strip("_") or "table"
    return ("t_" + a if not a[0].isalpha() else a)[:60]


def set_tables(c: dict, objects: list[str]) -> dict:
    """The tables this person allows Relay to use from this connection (dashboards and Ask Relay)."""
    known = {r["object"]: r for r in db.q("SELECT * FROM connection_tables WHERE connection_id = ?", (c["id"],))}
    a = _sdk(c)
    offered = {o["object"] for o in a.list_objects(c)} if a is not None and getattr(a, "extract", False) else None
    taken: set[str] = set()
    rows = []
    for obj in dict.fromkeys(o.strip() for o in objects if o.strip()):
        if offered is not None:                        # an API platform: only the objects it offers
            if obj not in offered:
                raise ConnectorError(f"{obj} is not one of the objects {KINDS[c['kind']]['label']} offers: {', '.join(sorted(offered))}.")
        else:
            quote(c["kind"], obj)                      # refuses anything that is not a plain object name
        alias = known.get(obj, {}).get("alias") or alias_for(obj)
        base, i = alias, 2
        while alias in taken:
            alias, i = f"{base}_{i}", i + 1
        taken.add(alias)
        rows.append((c["id"], obj, alias, known.get(obj, {}).get("object_type"), known.get(obj, {}).get("rows"),
                     known.get(obj, {}).get("added") or time.time()))
    db.run("DELETE FROM connection_tables WHERE connection_id = ?", (c["id"],))
    for r in rows:
        db.run("INSERT INTO connection_tables (connection_id, object, alias, object_type, rows, added) VALUES (?, ?, ?, ?, ?, ?)", r)
    db.audit("connection.tables", c["id"], {"tables": [r[1] for r in rows]}, c["owner_id"])
    return public(_row(c["id"]))


# ---------------------------------------------------------------- extracts (Parquet in the project's data/ folder)

def manifest(project_dir: Path) -> dict:
    try:
        return json.loads((project_dir / "data" / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def extracts_for_pbip(project_dir: Path) -> dict:
    """{file: {kind, connection (non-secret settings), object}} for report_builder's native connectors."""
    return {f: {"kind": m["kind"], "connection": m["connection"], "object": m["object"]} for f, m in manifest(project_dir).items()}


def _lit(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def comments(c: dict, obj: str) -> dict[str, str]:
    """The warehouse's own descriptions of a table: {"": table comment, column: comment}. Best effort: a catalogue
    the login cannot read simply gives nothing."""
    k = c["kind"]
    parts = [p.strip().strip('"`[]') for p in obj.split(".")]
    table, schema = parts[-1], (parts[-2] if len(parts) > 1 else None)
    out: dict[str, str] = {}
    try:
        if k == "bigquery":
            t = _open(c).get_table(obj)
            out[""] = t.description or ""
            out.update({f.name: f.description or "" for f in t.schema})
            return {x: y for x, y in out.items() if y}
        owner = _lit(schema) if schema else "USER"            # Oracle: its own list (the dict below reads cfg['database'], which Oracle does not have)
        q = [f"SELECT NULL AS col, comments FROM all_tab_comments WHERE table_name = {_lit(table)} AND owner = {owner}",
             f"SELECT column_name, comments FROM all_col_comments WHERE table_name = {_lit(table)} AND owner = {owner}"] if k == "oracle_db" else [] if k not in (
                 "snowflake", "redshift", "athena", "fabric") else {
            "snowflake": [f"SELECT '' AS col, comment FROM {quote(k, (parts[0] if len(parts) > 2 else c['config']['database']) + '.INFORMATION_SCHEMA.TABLES')} "
                          f"WHERE table_name = {_lit(table)}" + (f" AND table_schema = {_lit(schema)}" if schema else ""),
                          f"SELECT column_name, comment FROM {quote(k, (parts[0] if len(parts) > 2 else c['config']['database']) + '.INFORMATION_SCHEMA.COLUMNS')} "
                          f"WHERE table_name = {_lit(table)}" + (f" AND table_schema = {_lit(schema)}" if schema else "")],
            "redshift": [f"SELECT column_name, remarks FROM svv_columns WHERE table_name = {_lit(table)}" + (f" AND table_schema = {_lit(schema)}" if schema else "")],
            "athena": [f"SELECT column_name, comment FROM information_schema.columns WHERE table_name = {_lit(table)}"
                       + (f" AND table_schema = {_lit(schema)}" if schema else "")],
            "fabric": [f"SELECT '' AS col, CAST(ep.value AS NVARCHAR(4000)) FROM sys.extended_properties ep WHERE ep.major_id = OBJECT_ID({_lit(obj)}) "
                       "AND ep.minor_id = 0 AND ep.name = 'MS_Description'",
                       f"SELECT c.name, CAST(ep.value AS NVARCHAR(4000)) FROM sys.columns c JOIN sys.extended_properties ep ON ep.major_id = c.object_id "
                       f"AND ep.minor_id = c.column_id AND ep.name = 'MS_Description' WHERE c.object_id = OBJECT_ID({_lit(obj)})"],
        }.get(k, [])
        for sql in q:
            for tbl in _batches(c, sql, 60, 5000):
                for row in tbl.to_pylist():
                    col, text = list(row.values())[:2]
                    if text:
                        out[str(col or "")] = str(text)
    except Exception:  # noqa: BLE001 - descriptions are a bonus; the extract itself succeeded
        return out
    return out


ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def _utc(s: str):
    import datetime as _dt
    d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    return d.astimezone(_dt.timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def records_table(rows: list[dict]) -> pa.Table:
    """An API platform's records as one Arrow table: a column per field (first-seen order), typed from every value -
    whole numbers, numbers, true / false, ISO dates, ISO date-times (as UTC); the rest text, nested values as JSON."""
    import datetime as _dt
    cols = list(dict.fromkeys(k for r in rows for k in r))
    fields, arrays = [], []
    for k in cols:
        vals = [r.get(k) for r in rows]
        nn = [v for v in vals if v is not None and v != ""]
        blank = lambda v: v is None or v == ""  # noqa: E731
        if nn and all(isinstance(v, bool) for v in nn):
            t, vals = pa.bool_(), [None if blank(v) else v for v in vals]
        elif nn and all(isinstance(v, int) and not isinstance(v, bool) and abs(v) < 2 ** 63 for v in nn):
            t, vals = pa.int64(), [None if blank(v) else v for v in vals]
        elif nn and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in nn):
            t, vals = pa.float64(), [None if blank(v) else float(v) for v in vals]
        elif nn and all(isinstance(v, str) and ISO_DAY.match(v) for v in nn):
            t, vals = pa.date32(), [None if blank(v) else _dt.date.fromisoformat(v) for v in vals]
        elif nn and all(isinstance(v, str) and (ISO_TIME.match(v) or ISO_DAY.match(v)) for v in nn):
            t, vals = pa.timestamp("us"), [None if blank(v) else _utc(v) for v in vals]
        else:
            t, vals = pa.string(), [None if v is None else v if isinstance(v, str) else json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v) for v in vals]
        fields.append(pa.field(k, t))
        arrays.append(pa.array(vals, type=t))
    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def extract(c: dict, obj: str, alias: str, project_dir: Path, who: str | None) -> dict:
    """SELECT * of one configured table into data/<alias>.parquet, streamed batch by batch; for an API platform that
    can be extracted (Oracle Retail MFCS), every record of the object, typed from its values."""
    _check_enabled(c)
    if not ALIAS.match(alias):
        raise ConnectorError(f"Bad extract name {alias}")
    if not db.one("SELECT 1 FROM connection_tables WHERE connection_id = ? AND object = ?", (c["id"], obj)):
        raise ConnectorError(f"{obj} is not one of the tables configured on {c['name']}")
    a = _sdk(c)
    if a is not None and not getattr(a, "extract", False):
        raise ConnectorError(f"{KINDS[c['kind']]['label']} objects cannot be pulled into a dashboard.")
    data = project_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    final, tmp = data / f"{alias}.parquet", data / f".{alias}.parquet.tmp"
    started, rows, writer = time.time(), 0, None
    try:
        if a is not None:                              # an API platform: its records, typed once over all of them
            recs = [r for page in a.rows(c, obj, EXTRACT_MAX_ROWS) for r in page][:EXTRACT_MAX_ROWS]
            if not recs:
                raise ConnectorError(f"{obj} has no records to pull on {c['name']}")
            tbl = records_table(recs)
            pq.write_table(tbl, tmp, compression="zstd")
            rows = tbl.num_rows
        else:
            for tbl in _batches(c, f"SELECT * FROM {quote(c['kind'], obj)}", EXTRACT_TIMEOUT_S, EXTRACT_MAX_ROWS):
                if writer is None:
                    writer = pq.ParquetWriter(tmp, tbl.schema, compression="zstd")
                elif tbl.schema != writer.schema:
                    tbl = tbl.cast(writer.schema)
                writer.write_table(tbl)
                rows += tbl.num_rows
            if writer is None:
                raise ConnectorError(f"{obj} returned no columns")
            writer.close()
            writer = None
        os.replace(tmp, final)
    except Reconsent:
        raise
    except (sdk.ScopeError, ConnectorError) as e:
        raise ConnectorError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        _status(c, "error", str(e).splitlines()[0][:300])
        raise ConnectorError(f"Extract of {obj} failed: {str(e).splitlines()[0][:300]}") from e
    finally:
        if writer is not None:
            writer.close()
        tmp.unlink(missing_ok=True)
    m = manifest(project_dir)
    m[final.name] = {"connection_id": c["id"], "kind": c["kind"], "object": obj, "rows": rows,
                     "bytes": final.stat().st_size, "extracted": time.time(), "seconds": round(time.time() - started, 1),
                     "by": who, "connection": {k: v for k, v in c["config"].items() if k not in ("user", "client_id")}}
    (data / MANIFEST).write_text(json.dumps(m, indent=2), encoding="utf-8")
    db.run("UPDATE connection_tables SET rows = ? WHERE connection_id = ? AND object = ?", (rows, c["id"], obj))
    _status(c, "connected")
    db.audit("extract", f"{project_dir.name}/{final.name}", {"connection": c["id"], "object": obj, "rows": rows}, who)
    from . import usage
    usage.record("extract", who or c["owner_id"], step=c["kind"], bytes_=final.stat().st_size, obj=f"{project_dir.name}/{final.name}")
    try:                                                   # the source's own table / column comments become descriptions
        from genbi_kit.data import raw_name
        from . import describe
        describe.store_source_comments(f"{c['kind']}:{obj}", raw_name(final), comments(c, obj), who)
    except Exception:  # noqa: BLE001
        pass
    return m[final.name] | {"file": final.name}


def refresh_project(project_dir: Path, uid: str | None, only_owner: bool = True) -> list[dict]:
    """Pull every warehouse table of a project again, with each connection's owner's login."""
    out = []
    for f, m in manifest(project_dir).items():
        c = _row(m["connection_id"])
        if only_owner and uid and c["owner_id"] != uid:
            raise ConnectorError(f"{f} comes from {c['name']}, which belongs to someone else: they refresh it.")
        out.append(extract(c, m["object"], f[:-len(".parquet")], project_dir, uid or "schedule"))
    return out


# ---------------------------------------------------------------- live queries (Ask Relay) with guardrails

DEFAULT_GUARDS = {"row_limit": 10000, "timeout_s": 60, "bigquery_max_gb": 1.0}


def guardrails() -> dict:
    return {**DEFAULT_GUARDS, **json.loads(db.meta("query_guardrails") or "{}")}


def save_guardrails(g: dict, who: str | None) -> dict:
    clean = {"row_limit": max(1, min(int(g.get("row_limit", 10000)), 1_000_000)),
             "timeout_s": max(5, min(int(g.get("timeout_s", 60)), 1800)),
             "bigquery_max_gb": max(0.01, min(float(g.get("bigquery_max_gb", 1.0)), 10_000.0))}
    db.set_meta("query_guardrails", json.dumps(clean))
    db.audit("query.guardrails", None, clean, who)
    return clean


def read_only(sql: str, kind: str):
    """The parsed statement when `sql` is exactly one read-only SELECT in the warehouse's dialect (else ConnectorError)."""
    dialect = KINDS[kind]["dialect"]
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.ParseError as e:
        raise ConnectorError(f"The SQL does not parse as {KINDS[kind]['label']} SQL: {str(e).splitlines()[0][:200]}") from e
    if len(statements) != 1:
        raise ConnectorError("Send exactly one statement.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)):
        raise ConnectorError("Only SELECT queries are allowed.")
    for node in tree.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, BLOCKED):
            raise ConnectorError(f"{type(node).__name__} is not allowed: queries are read-only.")
    return tree


def guard(sql: str, kind: str, limit: int) -> str:
    """One read-only SELECT, nothing else; returned with the row limit applied in the warehouse's own dialect."""
    tree = read_only(sql, kind)
    return exp.select("*").from_(tree.subquery("d2d_q")).limit(limit).sql(dialect=KINDS[kind]["dialect"])


def query(c: dict, sql: str, who: str | None) -> dict:
    _check_enabled(c)
    if not KINDS[c["kind"]].get("dialect"):
        raise ConnectorError(f"{KINDS[c['kind']]['label']} is not a SQL warehouse: read one of its objects instead.")
    g = guardrails()
    safe = guard(sql, c["kind"], g["row_limit"])
    estimate = None
    if c["kind"] == "bigquery":
        from google.cloud import bigquery
        job = _open(c).query(safe, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        estimate = job.total_bytes_processed
        if estimate > g["bigquery_max_gb"] * 1e9:
            raise ConnectorError(f"This query would scan {estimate / 1e9:.2f} GB; the limit is {g['bigquery_max_gb']:g} GB.")
    started = time.time()
    tables = list(_batches(c, safe, g["timeout_s"], g["row_limit"], int(g["bigquery_max_gb"] * 1e9)))
    tbl = pa.concat_tables(tables) if tables else pa.table({})
    db.audit("query", c["id"], {"kind": c["kind"], "rows": tbl.num_rows, "sql": sql[:2000], "bytes_estimate": estimate}, who)
    from . import usage
    usage.record("warehouse", who, step=c["kind"], bytes_=estimate, cost_usd=usage.warehouse_cost(estimate), obj=c["id"])
    return {"sql": safe, "columns": tbl.column_names, "rows": tbl.slice(0, g["row_limit"]).to_pylist(),
            "row_count": tbl.num_rows, "limited": tbl.num_rows >= g["row_limit"], "seconds": round(time.time() - started, 2),
            "bytes_estimate": estimate, "guardrails": g}
