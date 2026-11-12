"""Connector SDK (build-plan v2, P10): every platform Relay can reach is one adapter behind the same six calls, so a
new platform is **one adapter + one mock** - nothing else in the app changes.

    class MyPlatform(Adapter):
        kind = "myplatform"                 # the id stored on the connection row
        label = "My Platform"               # what people see
        category = "crm"                    # one of connectors.CATEGORIES
        signin = ["api_key", "oauth"]       # sign-in kinds (connectors.SIGNIN); the first is the default
        fields = [("base_url", "Base URL", True)]           # non-secret settings (key, label, required)
        secrets = {"api_key": ["api_key"]}  # secret names per sign-in kind - stored in the secrets store, never returned
        can_write = True                    # the adapter knows how to write (still only with scope + approval)

        def describe(self) -> dict                     # the kind as the wizard shows it (label, category, sign-in, fields)
        def test(self, c) -> dict                      # sign in and touch the platform; {"ok": True, "sees": "3 projects"}
        def list_objects(self, c, search="") -> list   # [{"object": "...", "type": "..."}]
        def read(self, c, obj, limit=100) -> dict      # {"columns": [...], "rows": [...], "row_count": n}
        def write(self, c, obj, payload, approval) -> dict   # guarded: Adapter.write refuses without scope + approval
        def close(self) -> None

    register(MyPlatform())

    The mock: a tiny API simulator in the tests (tests/mocklab, or an http.server in the suite) that answers the
    documented endpoints with synthetic records, rejects a missing sign-in with 401 and a write without an
    approval with 403 - the contract tests/mocklab/mocklab_test.py checks for every platform. `MockAdapter` below
    is the in-process stand-in the platform tests use; `RestApiAdapter` reads any platform that publishes an
    OpenAPI document (the mock-lab simulators included) with an API key, read-only.

Rules every adapter inherits (build-plan §2): read-only by default; `write` runs only when the connection's scope is
"write" **and** the call carries an approval (a checkpoint a named person accepted, see connectors.request_write);
secrets come from the secrets store by name; every use is audited by the caller. The five warehouses of phase 3
(Snowflake, BigQuery, Fabric, Redshift, Athena) are wrapped by `WarehouseAdapter` without changing their behaviour;
Oracle Database (python-oracledb) by `OracleDbAdapter`, which adds the data dictionary the warehouse modules read.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC
from urllib.parse import urljoin

import httpx


class ScopeError(Exception):
    """A write (or comment) the connection's scope does not allow, or one without a person's approval."""


class Adapter(ABC):
    kind: str = ""
    label: str = ""
    category: str = "integration"
    signin: list[str] = ["api_key"]
    fields: list[tuple[str, str, bool]] = []
    secrets: dict[str, list[str]] = {}
    dialect: str | None = None          # SQL dialect for the guarded live query (warehouses only)
    can_write: bool = False
    sql: bool = False
    extract: bool = False               # its objects can be pulled whole into a dashboard (rows() below); SQL kinds always can

    def describe(self) -> dict:
        return {"label": self.label, "category": self.category, "signin": list(self.signin), "auth": list(self.signin),
                "fields": [{"key": k, "label": l, "required": r} for k, l, r in self.fields], "secrets": dict(self.secrets),
                "dialect": self.dialect, "can_write": self.can_write, "sql": self.sql, "extract": self.extract}

    def rows(self, c: dict, obj: str, max_rows: int):
        """Every record of one object, as pages (lists) of flat dicts - what an extract writes to Parquet. Only for
        adapters with `extract = True`."""
        raise ScopeError(f"{self.label} objects cannot be pulled into a dashboard")

    def test(self, c: dict) -> dict:      # noqa: ARG002
        return {"ok": True, "sees": ""}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:  # noqa: ARG002
        return []

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:  # noqa: ARG002
        raise ScopeError(f"{self.label} does not read {obj}")

    def write(self, c: dict, obj: str, payload: dict, approval: str | None = None) -> dict:
        """Guarded: the connection must allow writes and a person must have approved this very change."""
        from . import connectors
        if not connectors.may_write(c):
            raise ScopeError(f"{c.get('name') or self.label} is {connectors.SCOPES.get(c.get('scope') or 'read', 'read-only')}: writes are not allowed.")
        if not approval:
            raise ScopeError("A write needs a person's approval first (connectors.request_write opens the checkpoint).")
        if not self.can_write:
            raise ScopeError(f"{self.label} connections are read-only in Relay.")
        return self._write(c, obj, payload, approval)

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:  # noqa: ARG002
        raise ScopeError(f"{self.label} does not write")

    def close(self) -> None:
        pass


REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    REGISTRY[adapter.kind] = adapter
    return adapter


def get(kind: str) -> Adapter | None:
    return REGISTRY.get(kind)


# ---------------------------------------------------------------- the five warehouses of phase 3, unchanged behind the SDK

class WarehouseAdapter(Adapter):
    """Wraps connectors._open / browse / test / query for one warehouse kind (behaviour unchanged)."""
    sql = True

    def __init__(self, kind: str, spec: dict, category: str = "warehouse"):
        self.kind, self.label, self.category = kind, spec["label"], category
        self.signin = list(dict.fromkeys({"oauth": "oauth", "password": "password", "keypair": "api_key", "service_account": "service_account", "aws_keys": "api_key",
                                          "wallet": "password"}.get(a, a) for a in spec["auth"]))
        self.auth_modes = list(spec["auth"])
        self.fields, self.secrets, self.dialect = list(spec["fields"]), dict(spec["secrets"]), spec["dialect"]

    def describe(self) -> dict:
        return {**super().describe(), "auth": list(self.auth_modes)}

    def test(self, c: dict) -> dict:
        from . import connectors
        connectors.test(c)
        return {"ok": True, "sees": "a trivial query ran"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        from . import connectors
        return connectors.browse(c, search)

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        from . import connectors
        return connectors.query(c, f"SELECT * FROM {connectors.quote(c['kind'], obj)}", c.get("owner_id"))


class OracleDbAdapter(WarehouseAdapter):
    """Oracle Database through python-oracledb (thin mode): the phase-3 paths unchanged, plus what the warehouse
    modules read - the data dictionary (pipelines) and `execute` for dictionary SQL (the data warehouse module's
    estate). Read-only: `execute` runs one SELECT that passes the phase-3 read-only check, never a change."""
    MAX_ROWS = 200_000

    def execute(self, c: dict, sql: str, approval: str | None = None) -> tuple[list[str], list[list]]:
        from . import connectors, db
        if approval:
            raise ScopeError(f"{self.label} connections are read-only in Relay.")
        connectors.read_only(sql, c["kind"])           # one SELECT, no DML / DDL (run as written: LONG columns cannot sit in an inline view)
        connectors._check_enabled(c)                   # noqa: SLF001
        cols, rows = [], []
        for t in connectors._batches(c, sql.strip().rstrip(";"), connectors.guardrails()["timeout_s"] * 4, self.MAX_ROWS):  # noqa: SLF001
            cols = t.column_names
            rows += [list(r.values()) for r in t.to_pylist()]
        db.audit("query", c["id"], {"kind": c["kind"], "rows": len(rows), "sql": sql[:2000], "via": "dictionary"}, c.get("_who") or c.get("owner_id"))
        return cols, rows

    def dictionary(self, c: dict) -> dict[str, list[str]]:
        """{"SCHEMA.TABLE": ["COLUMN", ...]} for every table and view the sign-in can read (Oracle's own schemas left out)."""
        from . import connectors
        _, rows = self.execute(c, "SELECT owner || '.' || table_name AS t, column_name AS c FROM all_tab_columns "
                                  f"WHERE owner NOT IN ({connectors.ORACLE_OWN}) ORDER BY owner, table_name, column_id")
        out: dict[str, list[str]] = {}
        for t, col in rows:
            out.setdefault(str(t).upper(), []).append(str(col).upper())
        return out


# ---------------------------------------------------------------- the mock used by the tests

class MockAdapter(Adapter):
    """An in-process stand-in: objects and rows in memory, writes recorded, a failure the test can switch on."""
    kind, label, category = "mock", "Mock platform (tests)", "integration"
    signin = ["api_key", "password"]
    fields = [("site", "Site", True)]
    secrets = {"api_key": ["api_key"], "password": ["password"]}
    can_write = True

    def __init__(self):
        self.objects = {"ticket": [{"id": "T-1", "title": "Refresh fails", "status": "open"}, {"id": "T-2", "title": "Access request", "status": "open"}],
                        "project": [{"id": "DATA", "name": "Data team"}]}
        self.writes: list[dict] = []
        self.fail: str | None = None       # "expired" -> sign in again; "down" -> error

    def _check(self, c: dict) -> None:
        from . import connectors, secrets_store
        if self.fail == "expired":
            raise connectors.Reconsent("The platform no longer accepts the stored key. Sign in again.")
        if self.fail == "down":
            raise connectors.ConnectorError("The platform did not answer.")
        name = (self.secrets.get(c.get("auth_mode") or "api_key") or ["api_key"])[0]
        if not secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}"):
            raise connectors.Reconsent(f"No {name.replace('_', ' ')} stored for this connection.")

    def test(self, c: dict) -> dict:
        self._check(c)
        return {"ok": True, "sees": f"{len(self.objects)} object types, {sum(len(v) for v in self.objects.values())} records"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        self._check(c)
        return [{"object": k, "type": "list", "rows": len(v)} for k, v in self.objects.items() if search.lower() in k]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        self._check(c)
        rows = self.objects.get(obj)
        if rows is None:
            from . import connectors
            raise connectors.ConnectorError(f"No object {obj} on {c['name']}")
        cols = sorted({k for r in rows for k in r})
        return {"columns": cols, "rows": rows[:limit], "row_count": len(rows)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        self._check(c)
        self.writes.append({"connection": c["id"], "object": obj, "payload": payload, "approval": approval, "when": time.time()})
        self.objects.setdefault(obj, []).append({"id": f"{obj[:1].upper()}-{len(self.objects.get(obj, [])) + 1}", **payload})
        return {"ok": True, "written": payload}


# ---------------------------------------------------------------- any platform with an OpenAPI document, read-only

class RestApiAdapter(Adapter):
    """A generic REST adapter: the OpenAPI document lists the GET endpoints (the objects); `read` calls one with the
    API key; writes are refused - a vendor-faithful adapter replaces it when a platform needs more."""
    kind, label, category = "rest_api", "REST API (OpenAPI)", "integration"
    signin = ["api_key"]
    fields = [("openapi_url", "OpenAPI document URL (.../openapi.json)", True), ("base_url", "Base URL (optional: taken from the document)", False),
              ("header", "Header carrying the key (default Authorization: Key ...)", False)]
    secrets = {"api_key": ["api_key"]}
    can_write = False
    TIMEOUT = 20

    def _headers(self, c: dict) -> dict:
        from . import secrets_store
        key = secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:api_key") or ""
        header = (c["config"].get("header") or "").strip()
        if header and ":" in header:
            name, prefix = header.split(":", 1)
            return {name.strip(): f"{prefix.strip()} {key}".strip()}
        return {"Authorization": f"Key {key}"}

    def _spec(self, c: dict) -> tuple[dict, str]:
        from . import connectors
        url = (c["config"].get("openapi_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise connectors.ConnectorError("The OpenAPI document URL must start with http:// or https://.")
        try:
            r = httpx.get(url, headers=self._headers(c), timeout=self.TIMEOUT)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"The OpenAPI document could not be fetched: {e.__class__.__name__}") from e
        if r.status_code == 401:
            raise connectors.Reconsent("The platform refused the API key. Sign in again.")
        if r.status_code != 200:
            raise connectors.ConnectorError(f"The OpenAPI document answered {r.status_code}.")
        try:
            spec = r.json()
        except ValueError as e:
            raise connectors.ConnectorError("The OpenAPI document is not JSON.") from e
        base = (c["config"].get("base_url") or "").strip() or next((s.get("url") for s in spec.get("servers") or [] if s.get("url")), None) or url.rsplit("/", 1)[0] + "/"
        if not base.endswith("/"):
            base += "/"
        return spec, base

    def test(self, c: dict) -> dict:
        spec, _ = self._spec(c)
        gets = [p for p, ops in (spec.get("paths") or {}).items() if "get" in ops and "{" not in p]
        return {"ok": True, "sees": f"{len(gets)} GET endpoint(s) in {spec.get('info', {}).get('title') or 'the API'}"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        spec, _ = self._spec(c)
        out = []
        for path, ops in (spec.get("paths") or {}).items():
            if "get" in ops and "{" not in path and search.lower() in path.lower():
                out.append({"object": path, "type": (ops["get"].get("summary") or "GET")[:80]})
        return out

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        from . import connectors
        _, base = self._spec(c)
        if not re.fullmatch(r"/[\w\-./]*", obj):
            raise connectors.ConnectorError(f"Not an endpoint path: {obj}")
        try:
            r = httpx.get(urljoin(base, obj.lstrip("/")), headers=self._headers(c), timeout=self.TIMEOUT)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"{obj} could not be read: {e.__class__.__name__}") from e
        if r.status_code == 401:
            raise connectors.Reconsent("The platform refused the API key. Sign in again.")
        if r.status_code >= 400:
            raise connectors.ConnectorError(f"{obj} answered {r.status_code}.")
        try:
            body = r.json()
        except ValueError:
            return {"columns": ["text"], "rows": [{"text": r.text[:2000]}], "row_count": 1}
        items = body if isinstance(body, list) else next((v for v in body.values() if isinstance(v, list)), [body]) if isinstance(body, dict) else [body]
        rows = [i if isinstance(i, dict) else {"value": i} for i in items[:limit]]
        cols = sorted({k for row in rows for k in row})
        return {"columns": cols, "rows": [{k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()} for row in rows], "row_count": len(items)}


register(MockAdapter())
register(RestApiAdapter())
from . import files_adapters  # noqa: E402,F401 - consolidation: SharePoint, OneDrive, Google Drive (where the studio files a final)
