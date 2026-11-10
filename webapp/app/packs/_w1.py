"""W1 Data & Analytics — the connection kinds the wave's packs read through, and the small kit they share.

Every platform is one SDK adapter (connectors_sdk.Adapter) that speaks the vendor's documented API; in the mock lab a
simulator in tests/mocklab/sims stands in for each (the adapter's `simulator`). The rules every adapter inherits:
read-only by default; a write happens only through connectors.request_write (the connection's scope must allow it and a
named person approves that very change) and carries the approval id as X-Relay-Approval; secrets come from the secrets
store by name; sign-in tokens are kept per tenant and connection (never rows).

SQL warehouses reached over HTTP (Oracle REST-enabled SQL, Teradata Query Service, Db2 REST, the Snowflake SQL API,
Databricks Statement Execution) are `SqlKind`s: a DB-API shim lets connectors.query (the guarded, read-only live query
of phase 3) and observe_checks.SqlReader run on them unchanged, so the workbench's proof checks and the quality rules
work on every one of them.

Not auto-imported (the leading underscore): each W1 pack imports what it uses.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import threading
import time
from pathlib import Path

import httpx

from .. import connectors, db, secrets_store
from .. import connectors_sdk as sdk

APPROVAL = "X-Relay-Approval"
_TOKENS: dict = {}                     # (tenant, connection id) -> (token, expiry): sign-in tokens only
_TLOCK = threading.Lock()


def secret(c: dict, name: str) -> str:
    return secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}") or ""


def cfg(c: dict, key: str, default: str = "") -> str:
    return str((c.get("config") or {}).get(key) or default).strip()


def register(a: sdk.Adapter) -> sdk.Adapter:
    """One adapter into the SDK registry and the connection catalogue (as observe_checks registers its lab engines)."""
    sdk.register(a)
    connectors.KINDS[a.kind] = {"label": a.label, "dialect": a.dialect, "auth": list(a.signin), "fields": list(a.fields), "secrets": dict(a.secrets),
                                "category": a.category, "sdk": True}
    return a


class Kind(sdk.Adapter):
    """A vendor API reached over HTTP. Subclasses set the sign-in (`auth`) and the calls the packs need."""
    category = "integration"
    simulator = ""                     # the mock-lab simulator id (tests/mocklab/sims)
    base_field = "base_url"
    TIMEOUT = 30

    # ---- plumbing
    def base(self, c: dict) -> str:
        u = cfg(c, self.base_field).rstrip("/")
        if not u.startswith(("http://", "https://")):
            raise connectors.ConnectorError(f"{self.label}: the address must start with http:// or https://.")
        return u

    def auth(self, c: dict) -> dict:
        return {}

    def token(self, c: dict, fetch) -> str:
        key = (db.tenant(), c["id"])
        with _TLOCK:
            t = _TOKENS.get(key)
            if t and t[1] > time.time() + 30:
                return t[0]
        tok, ttl = fetch()
        with _TLOCK:
            _TOKENS[key] = (tok, time.time() + float(ttl or 600))
        return tok

    def forget(self, c: dict) -> None:
        with _TLOCK:
            _TOKENS.pop((db.tenant(), c["id"]), None)

    def message(self, r: httpx.Response) -> str:
        try:
            b = r.json()
        except ValueError:
            return (r.text or "")[:200]
        if isinstance(b, dict):
            for path in (("error", "message"), ("status", "user_message"), ("message",), ("detail",), ("description",), ("error_description",), ("error",), ("title",)):
                v = b
                for k in path:
                    v = v.get(k) if isinstance(v, dict) else None
                if isinstance(v, str) and v:
                    return v[:300]
        return json.dumps(b)[:200]

    def call(self, c: dict, method: str, path: str, *, params=None, json_body=None, data=None, form=None, headers=None, approval: str | None = None,
             raw: bool = False, auth: bool = True):
        url = path if path.startswith(("http://", "https://")) else self.base(c) + path
        h = {"Accept": "application/json", **(self.auth(c) if auth else {}), **(headers or {})}
        if approval:
            h[APPROVAL] = approval
        again = auth
        r = None
        for attempt in range(5):
            try:
                r = httpx.request(method, url, params=params, json=json_body, content=data, data=form, headers=h, timeout=self.TIMEOUT)
            except httpx.HTTPError as e:
                if attempt < 1:
                    continue
                raise connectors.ConnectorError(f"{self.label} did not answer ({e.__class__.__name__}).") from e
            if r.status_code == 429 and attempt < 3:
                time.sleep(min(float(r.headers.get("Retry-After") or 1), 3))
                continue
            if r.status_code in (502, 503, 504) and attempt < 1:
                time.sleep(0.3)
                continue
            if r.status_code == 401 and again:
                again = False
                self.forget(c)
                h.update(self.auth(c))
                continue
            break
        if r.status_code == 401:
            raise connectors.Reconsent(f"{self.label} refused the stored sign-in: {self.message(r)}. Renew the connection.")
        if r.status_code == 403:
            raise connectors.ConnectorError(f"{self.label} refused: {self.message(r)}")
        if r.status_code >= 400:
            raise connectors.ConnectorError(f"{self.label} answered {r.status_code}: {self.message(r)}")
        if raw:
            return r
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return r.text

    def basic(self, user: str, password: str) -> dict:
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}

    # ---- the SDK calls (defaults; most adapters override)
    def test(self, c: dict) -> dict:
        objs = self.list_objects(c)
        return {"ok": True, "sees": f"{len(objs)} object(s)"}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        """An approved change: payload {"method", "path", "body"} (or the adapter's own ops)."""
        if payload.get("method") and payload.get("path"):
            r = self.call(c, payload["method"], payload["path"], json_body=payload.get("body"), params=payload.get("params"), approval=approval)
            return {"ok": True, "result": r if isinstance(r, dict) else str(r)[:500]}
        raise sdk.ScopeError(f"{self.label}: this change is not one Relay knows how to make")


# ================================================================== SQL over HTTP: a DB-API shim for connectors.query

class SqlKind(Kind):
    sql = True
    category = "warehouse"
    can_write = True                   # DDL / DML only through request_write (scope + a person's approval)
    probe = "SELECT 1 AS ok"
    tables_sql = ""                    # the dictionary query: object, type
    columns_sql = ""                   # the dictionary query: table, column (in column order)

    def dictionary(self, c: dict) -> dict[str, list[str]]:
        """{"SCHEMA.TABLE": ["COLUMN", …]} from the warehouse's own data dictionary."""
        _, rows = self.execute(c, self.columns_sql)
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(str(r[0]).upper(), []).append(str(r[1]).upper())
        return out

    def execute(self, c: dict, sql: str, approval: str | None = None) -> tuple[list[str], list[list]]:
        raise NotImplementedError

    def test(self, c: dict) -> dict:
        self.execute(c, self.probe)
        n = len(self.list_objects(c))
        return {"ok": True, "sees": f"{n} table(s) and view(s); a trivial query ran"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        cols, rows = self.execute(c, self.tables_sql)
        s = search.strip().lower()
        return [{"object": r[0], "type": r[1]} for r in rows if not s or s in str(r[0]).lower()][:2000]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        return connectors.query(c, f"SELECT * FROM {connectors.quote(c['kind'], obj)}", c.get("owner_id"))

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        if payload.get("ops") and not payload.get("statements"):         # the platform's own metadata API (e.g. Unity Catalog)
            for op in payload["ops"]:
                self.call(c, op["method"], op["path"], json_body=op.get("body"), params=op.get("params"), approval=approval)
            return {"ok": True, "done": [op.get("what") or op["path"] for op in payload["ops"]]}
        done = 0
        for stmt in payload.get("statements") or []:
            self.execute(c, stmt, approval=approval)
            done += 1
        return {"ok": True, "statements": done}


class _Cur:
    def __init__(self, a: SqlKind, c: dict):
        self.a, self.c, self.description, self._rows = a, c, None, []

    def execute(self, sql, *args):  # noqa: ARG002
        cols, rows = self.a.execute(self.c, sql)
        self.description = [(n, None, None, None, None, None, None) for n in cols]
        self._rows = [tuple(r) for r in rows]

    def fetchmany(self, n: int = 50000):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out

    def fetchall(self):
        return self.fetchmany(len(self._rows))

    def close(self):
        pass


class _Con:
    def __init__(self, a: SqlKind, c: dict):
        self.a, self.c, self.timeout = a, c, None

    def cursor(self):
        return _Cur(self.a, self.c)

    def close(self):
        pass


def _patch_open() -> None:
    if getattr(connectors, "_w1_sql", False):
        return
    connectors._w1_sql = True
    orig = connectors._open

    def _open(c: dict):
        a = sdk.get(c["kind"])
        if isinstance(a, SqlKind):
            return _Con(a, c)
        return orig(c)
    connectors._open = _open


def _num(v):
    if v is None or isinstance(v, (int, float)):
        return v
    s = str(v)
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d*\.\d+(e-?\d+)?", s, re.I):
        return float(s)
    return v


class OracleOrds(SqlKind):
    """Oracle Database / Exadata / Autonomous DW through Oracle REST Data Services' REST-enabled SQL (basic auth as the
    schema's database user)."""
    kind, label, dialect = "oracle", "Oracle Database (REST-enabled SQL)", "oracle"
    signin = ["password"]
    fields = [("base_url", "ORDS schema address (…/ords/<schema alias>)", True), ("user", "Database user", True)]
    secrets = {"password": ["password"]}
    simulator = "oracle_dw"
    probe = "SELECT COUNT(*) AS N FROM ALL_TABLES"
    tables_sql = ("SELECT OWNER || '.' || TABLE_NAME AS OBJ, 'TABLE' AS T FROM ALL_TABLES WHERE OWNER NOT IN ('SYS', 'SYSTEM') "
                  "UNION ALL SELECT OWNER || '.' || VIEW_NAME, 'VIEW' FROM ALL_VIEWS")
    columns_sql = "SELECT OWNER || '.' || TABLE_NAME AS T, COLUMN_NAME AS C FROM ALL_TAB_COLUMNS WHERE OWNER NOT IN ('SYS', 'SYSTEM') ORDER BY OWNER, TABLE_NAME, COLUMN_ID"

    def auth(self, c):
        return self.basic(cfg(c, "user"), secret(c, "password"))

    def execute(self, c, sql, approval=None):
        cols, rows, off = [], [], 0
        while True:
            r = self.call(c, "POST", "/_/sql", json_body={"statementText": sql.rstrip().rstrip(";"), "offset": off, "limit": 5000}, approval=approval)
            items = r.get("items") or [] if isinstance(r, dict) else []
            it = items[-1] if items else {}
            if it.get("errorCode"):
                raise connectors.ConnectorError(it.get("errorMessage") or f"ORA-{it['errorCode']}")
            rs = it.get("resultSet")
            if not rs:
                return cols, rows
            cols = [m["columnName"] for m in rs.get("metadata") or []]
            keys = [m.get("jsonColumnName") or m["columnName"].lower() for m in rs.get("metadata") or []]
            rows += [[row.get(k) for k in keys] for row in rs.get("items") or []]
            if not rs.get("hasMore") or len(rows) >= 50000:
                return cols, rows
            off += int(rs.get("count") or len(rs.get("items") or [])) or 5000


# ================================================================== W1 pipeline and ETL platforms

class ADF(Kind):
    """Azure Data Factory through the Azure Resource Manager REST API (api-version 2018-06-01), signed in with an Entra ID
    app registration (client credentials, scope https://management.azure.com/.default)."""
    kind, label, category = "adf", "Azure Data Factory", "integration"
    signin = ["service_account"]
    fields = [("base_url", "Management endpoint (https://management.azure.com)", True), ("token_url", "Entra ID token endpoint (…/oauth2/v2.0/token)", True),
              ("client_id", "App registration (client) id", True), ("factory_path", "Factory (/subscriptions/…/factories/<name>)", True)]
    secrets = {"service_account": ["client_secret"]}
    can_write = True
    simulator = "adf"
    API = "2018-06-01"

    def auth(self, c):
        def fetch():
            r = self.call(c, "POST", cfg(c, "token_url"), form={"grant_type": "client_credentials", "client_id": cfg(c, "client_id"), "client_secret": secret(c, "client_secret"),
                                                                "scope": "https://management.azure.com/.default"}, auth=False)
            return r["access_token"], r.get("expires_in") or 3599
        return {"Authorization": "Bearer " + self.token(c, fetch)}

    def fp(self, c) -> str:
        return cfg(c, "factory_path").rstrip("/")

    def items(self, c, kind: str) -> list[dict]:
        out, url, params = [], self.fp(c) + f"/{kind}", {"api-version": self.API}
        while url:
            r = self.call(c, "GET", url, params=params)
            out += r.get("value") or []
            url, params = r.get("nextLink"), None
        return out

    def item(self, c, kind: str, name: str) -> dict:
        return self.call(c, "GET", self.fp(c) + f"/{kind}/{name}", params={"api-version": self.API})

    def runs(self, c, since: float, until: float | None = None) -> list[dict]:
        body = {"lastUpdatedAfter": _iso(since), "lastUpdatedBefore": _iso(until or time.time() + 60)}
        out = []
        while True:
            r = self.call(c, "POST", self.fp(c) + "/queryPipelineRuns", params={"api-version": self.API}, json_body=body)
            out += r.get("value") or []
            if not r.get("continuationToken"):
                return out
            body["continuationToken"] = r["continuationToken"]

    def activity_error(self, c, run_id: str, start: float) -> str:
        r = self.call(c, "POST", self.fp(c) + f"/pipelineruns/{run_id}/queryActivityruns", params={"api-version": self.API},
                      json_body={"lastUpdatedAfter": _iso(start - 86400), "lastUpdatedBefore": _iso(time.time() + 60)})
        return "; ".join(a["error"]["message"] for a in r.get("value") or [] if (a.get("error") or {}).get("message"))

    def test(self, c):
        f = self.call(c, "GET", self.fp(c), params={"api-version": self.API})
        return {"ok": True, "sees": f"factory {f.get('name')}: {len(self.items(c, 'pipelines'))} pipeline(s)"}

    def list_objects(self, c, search=""):
        return [{"object": p["name"], "type": "pipeline"} for p in self.items(c, "pipelines") if search.lower() in p["name"].lower()]

    def read(self, c, obj, limit=100):
        rows = [{"run": r["runId"], "status": r["status"], "start": r.get("runStart"), "end": r.get("runEnd"), "message": r.get("message")}
                for r in self.runs(c, time.time() - 30 * 86400) if r.get("pipelineName") == obj][-limit:]
        return {"columns": ["run", "status", "start", "end", "message"], "rows": rows, "row_count": len(rows)}

    def _write(self, c, obj, payload, approval):
        op = payload.get("op")
        if op in ("put_dataflow", "put_pipeline"):
            kind = "dataflows" if op == "put_dataflow" else "pipelines"
            r = self.call(c, "PUT", self.fp(c) + f"/{kind}/{payload['name']}", params={"api-version": self.API}, json_body={"properties": payload["properties"]}, approval=approval)
            return {"ok": True, "name": r.get("name")}
        if op == "run":
            r = self.call(c, "POST", self.fp(c) + f"/pipelines/{payload['name']}/createRun", params={"api-version": self.API}, json_body=payload.get("parameters") or {}, approval=approval)
            return {"ok": True, "run": r.get("runId")}
        return super()._write(c, obj, payload, approval)


class DbtCloud(Kind):
    """dbt Cloud through its Administrative API v2 (a service token)."""
    kind, label = "dbt_cloud", "dbt Cloud"
    signin = ["api_key"]
    fields = [("base_url", "Access URL (https://cloud.getdbt.com)", True), ("account_id", "Account id", True)]
    secrets = {"api_key": ["token"]}
    can_write = True
    simulator = "dbt"

    def auth(self, c):
        return {"Authorization": f"Token {secret(c, 'token')}"}

    def acct(self, c) -> str:
        return f"/api/v2/accounts/{cfg(c, 'account_id')}"

    def paged(self, c, path: str, params: dict | None = None) -> list[dict]:
        out, off = [], 0
        while True:
            r = self.call(c, "GET", self.acct(c) + path, params={**(params or {}), "limit": 100, "offset": off})
            data = r.get("data") or []
            out += data
            total = ((r.get("extra") or {}).get("pagination") or {}).get("total_count")
            off += len(data)
            if not data or (total is not None and off >= total) or len(out) > 5000:
                return out

    def jobs(self, c) -> list[dict]:
        return self.paged(c, "/jobs/")

    def runs(self, c) -> list[dict]:
        return self.paged(c, "/runs/", {"order_by": "id"})

    def artifact(self, c, run_id, path: str):
        return self.call(c, "GET", self.acct(c) + f"/runs/{run_id}/artifacts/{path}")

    def test(self, c):
        return {"ok": True, "sees": f"{len(self.jobs(c))} job(s)"}

    def list_objects(self, c, search=""):
        return [{"object": j["name"], "type": "job"} for j in self.jobs(c) if search.lower() in j["name"].lower()]

    def read(self, c, obj, limit=100):
        jid = next((j["id"] for j in self.jobs(c) if j["name"] == obj), None)
        rows = [{"run": r["id"], "status": r.get("status_humanized"), "start": r.get("started_at"), "end": r.get("finished_at"), "message": r.get("status_message")}
                for r in self.runs(c) if r.get("job_definition_id") == jid][-limit:]
        return {"columns": ["run", "status", "start", "end", "message"], "rows": rows, "row_count": len(rows)}

    def _write(self, c, obj, payload, approval):
        op = payload.get("op")
        if op == "create_job":
            r = self.call(c, "POST", self.acct(c) + "/jobs/", json_body=payload["job"], approval=approval)
            return {"ok": True, "job": (r.get("data") or {}).get("id")}
        if op == "run":
            r = self.call(c, "POST", self.acct(c) + f"/jobs/{payload['job_id']}/run/", json_body={"cause": payload.get("cause") or "Run by Relay after an approval"}, approval=approval)
            return {"ok": True, "run": (r.get("data") or {}).get("id")}
        return super()._write(c, obj, payload, approval)


class Airflow(Kind):
    """Apache Airflow 2 through its stable REST API v1 (basic auth)."""
    kind, label = "airflow", "Apache Airflow"
    signin = ["password"]
    fields = [("base_url", "REST API (…/api/v1)", True), ("user", "User name", True)]
    secrets = {"password": ["password"]}
    can_write = True
    simulator = "airflow"

    def auth(self, c):
        return self.basic(cfg(c, "user"), secret(c, "password"))

    def paged(self, c, path: str, key: str, params: dict | None = None) -> list[dict]:
        out, off = [], 0
        while True:
            r = self.call(c, "GET", path, params={**(params or {}), "limit": 100, "offset": off})
            page = r.get(key) or []
            out += page
            off += len(page)
            if not page or off >= int(r.get("total_entries") or 0) or len(out) > 5000:
                return out

    def dags(self, c) -> list[dict]:
        return self.paged(c, "/dags", "dags")

    def dag_runs(self, c, dag_id: str) -> list[dict]:
        return self.paged(c, f"/dags/{dag_id}/dagRuns", "dag_runs")

    def source(self, c, file_token: str) -> str:
        r = self.call(c, "GET", f"/dagSources/{file_token}", raw=True, headers={"Accept": "text/plain"})
        return r.text

    def failed_log(self, c, dag_id: str, run_id: str) -> str:
        tis = self.call(c, "GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances").get("task_instances") or []
        bad = next((t for t in tis if t.get("state") == "failed"), None)
        if not bad:
            return ""
        r = self.call(c, "GET", f"/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{bad['task_id']}/logs/{bad.get('try_number') or 1}", raw=True, headers={"Accept": "text/plain"})
        exc = [ln for ln in r.text.splitlines() if re.match(r"^[\w.]+(Error|Exception|Failure)\b:", ln.strip())]      # the exception line of the traceback
        lines = exc or [ln for ln in r.text.splitlines() if re.search(r"error|exception", ln, re.I)]
        return (lines[-1] if lines else r.text[-300:]).strip()[:500]

    def test(self, c):
        return {"ok": True, "sees": f"{len(self.dags(c))} DAG(s)"}

    def list_objects(self, c, search=""):
        return [{"object": d["dag_id"], "type": "DAG"} for d in self.dags(c) if search.lower() in d["dag_id"].lower()]

    def read(self, c, obj, limit=100):
        rows = [{"run": r["dag_run_id"], "status": r.get("state"), "start": r.get("start_date"), "end": r.get("end_date")} for r in self.dag_runs(c, obj)][-limit:]
        return {"columns": ["run", "status", "start", "end"], "rows": rows, "row_count": len(rows)}

    def _write(self, c, obj, payload, approval):
        if payload.get("op") == "pause":
            r = self.call(c, "PATCH", f"/dags/{payload['dag_id']}", params={"update_mask": "is_paused"}, json_body={"is_paused": bool(payload.get("paused", True))}, approval=approval)
            return {"ok": True, "paused": r.get("is_paused")}
        if payload.get("op") == "run":
            r = self.call(c, "POST", f"/dags/{payload['dag_id']}/dagRuns", json_body={"conf": payload.get("conf") or {}}, approval=approval)
            return {"ok": True, "run": r.get("dag_run_id")}
        return super()._write(c, obj, payload, approval)


class IICS(Kind):
    """Informatica Intelligent Cloud Services — Cloud Data Integration (REST v3 sign-in and objects, v2 mapping tasks and
    the activity log)."""
    kind, label = "iics", "Informatica Cloud (IICS)"
    signin = ["password"]
    fields = [("base_url", "Pod address (https://dm-<region>.informaticacloud.com)", True), ("user", "User name", True)]
    secrets = {"password": ["password"]}
    can_write = True
    simulator = "informatica_iics"

    def auth(self, c):
        def fetch():
            r = self.call(c, "POST", "/saas/public/core/v3/login", json_body={"username": cfg(c, "user"), "password": secret(c, "password")}, auth=False)
            return r["userInfo"]["sessionId"], 1500
        sid = self.token(c, fetch)
        return {"INFA-SESSION-ID": sid, "icSessionId": sid}

    def tasks(self, c) -> list[dict]:
        r = self.call(c, "GET", "/saas/api/v2/mttask")
        return r if isinstance(r, list) else []

    def mappings(self, c) -> list[dict]:
        r = self.call(c, "GET", "/saas/api/v2/mapping")
        return r if isinstance(r, list) else []

    def activity(self, c) -> list[dict]:
        out, off = [], 0
        while True:
            r = self.call(c, "GET", "/saas/api/v2/activity/activityLog", params={"rowLimit": 200, "offset": off})
            page = r if isinstance(r, list) else []
            out += page
            off += len(page)
            if len(page) < 200 or len(out) > 5000:
                return out

    def test(self, c):
        return {"ok": True, "sees": f"{len(self.tasks(c))} mapping task(s)"}

    def list_objects(self, c, search=""):
        return [{"object": t["name"], "type": "mapping task"} for t in self.tasks(c) if search.lower() in t["name"].lower()]

    def read(self, c, obj, limit=100):
        rows = [{"run": a.get("runId") or a.get("id"), "status": a.get("state"), "start": a.get("startTime"), "end": a.get("endTime"), "message": a.get("errorMsg")}
                for a in self.activity(c) if a.get("objectName") == obj][-limit:]
        return {"columns": ["run", "status", "start", "end", "message"], "rows": rows, "row_count": len(rows)}

    def _write(self, c, obj, payload, approval):
        if payload.get("op") == "update_task":
            r = self.call(c, "POST", f"/saas/api/v2/mttask/{payload['id']}", json_body={"@type": "mtTask", **payload["task"]}, approval=approval)
            return {"ok": True, "task": r.get("id") if isinstance(r, dict) else None}
        if payload.get("op") == "run":
            r = self.call(c, "POST", "/saas/api/v2/job", json_body={"@type": "job", "taskId": payload["id"], "taskType": "MTT"}, approval=approval)
            return {"ok": True, "run": r.get("runId") if isinstance(r, dict) else None}
        return super()._write(c, obj, payload, approval)


class TalendTmc(Kind):
    """Talend Management Console (orchestration, processing and observability APIs) with a personal access token."""
    kind, label = "talend", "Talend Cloud (Management Console)"
    signin = ["api_key"]
    fields = [("base_url", "API address (https://api.<region>.cloud.talend.com)", True), ("environment_id", "Environment id", True)]
    secrets = {"api_key": ["token"]}
    can_write = True
    simulator = "talend"

    def auth(self, c):
        return {"Authorization": f"Bearer {secret(c, 'token')}"}

    def tasks(self, c) -> list[dict]:
        out, off = [], 0
        while True:
            r = self.call(c, "GET", "/orchestration/executables/tasks", params={"environmentId": cfg(c, "environment_id"), "limit": 100, "offset": off})
            items = r.get("items") or []
            out += items
            off += len(items)
            if not items or off >= int(r.get("total") or 0):
                return out

    def executions(self, c, since: float) -> list[dict]:
        out, off = [], 0
        while True:
            r = self.call(c, "POST", "/monitoring/observability/executions/search",
                          json_body={"environmentId": cfg(c, "environment_id"), "from": int(since * 1000), "to": int((time.time() + 60) * 1000), "limit": 100, "offset": off})
            items = r.get("items") or []
            out += items
            off += len(items)
            if not items or off >= int(r.get("total") or 0) or len(out) > 5000:
                return out

    def test(self, c):
        return {"ok": True, "sees": f"{len(self.tasks(c))} task(s)"}

    def list_objects(self, c, search=""):
        return [{"object": t["name"], "type": "task"} for t in self.tasks(c) if search.lower() in t["name"].lower()]

    def _write(self, c, obj, payload, approval):
        if payload.get("op") == "run":
            r = self.call(c, "POST", "/processing/executions", json_body={"executable": payload["id"]}, approval=approval)
            return {"ok": True, "run": r.get("executionId")}
        return super()._write(c, obj, payload, approval)


class Fivetran(Kind):
    """Fivetran REST API v1 (API key and secret, basic auth)."""
    kind, label = "fivetran", "Fivetran"
    signin = ["api_key"]
    fields = [("base_url", "API address (https://api.fivetran.com)", True), ("api_key", "API key", True), ("group_id", "Group (destination) id", True)]
    secrets = {"api_key": ["api_secret"]}
    can_write = True
    simulator = "fivetran"

    def auth(self, c):
        return {**self.basic(cfg(c, "api_key"), secret(c, "api_secret")), "Accept": "application/json;version=2"}

    def connections(self, c) -> list[dict]:
        out, cursor = [], None
        while True:
            r = self.call(c, "GET", f"/v1/groups/{cfg(c, 'group_id')}/connectors", params={"limit": 100, **({"cursor": cursor} if cursor else {})})
            d = r.get("data") or {}
            out += d.get("items") or []
            cursor = d.get("next_cursor")
            if not cursor or len(out) > 2000:
                return out

    def test(self, c):
        return {"ok": True, "sees": f"{len(self.connections(c))} connection(s)"}

    def list_objects(self, c, search=""):
        return [{"object": f"{x['service']}.{x['schema']}", "type": "connection"} for x in self.connections(c) if search.lower() in x["schema"].lower()]

    def _write(self, c, obj, payload, approval):
        if payload.get("op") == "sync":
            self.call(c, "POST", f"/v1/connectors/{payload['id']}/sync", json_body={"force": False}, approval=approval)
            return {"ok": True}
        if payload.get("op") == "pause":
            self.call(c, "PATCH", f"/v1/connectors/{payload['id']}", json_body={"paused": bool(payload.get("paused", True))}, approval=approval)
            return {"ok": True}
        return super()._write(c, obj, payload, approval)


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ts(v) -> float | None:
    """Seconds since the epoch from the vendors' many time formats (ISO 8601, epoch ms, '/Date(ms)/', 'YYYY-MM-DD HH:MM:SS')."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e11 else 1)
    s = str(v).strip()
    m = re.match(r"^/Date\((-?\d+)", s)
    if m:
        return int(m.group(1)) / 1000
    if re.fullmatch(r"\d{12,}", s):
        return int(s) / 1000
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()


# ================================================================== helpers the packs share

def lc(s: str) -> str:
    """'Every day at 06:00 (UTC)' -> 'every day at 06:00 (UTC)' (only the first letter)."""
    return s[:1].lower() + s[1:]


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:n] or "x"


def kinds_of(*adapters) -> tuple:
    return tuple(a.kind for a in adapters)


def extract_parquet(ctx, rows: list[dict], name: str) -> str:
    """Rows into the work item's data/ as Parquet (a read-only copy the proof checks read with DuckDB); returns the
    file name for a {"source": "file", "file": …} reference."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    fname = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:80] + ".parquet"
    d = Path(ctx.dir) / "data"
    d.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    clean = [{k: _cell(r.get(k)) for k in cols} for r in rows]
    for k in cols:                                  # 1.0 and 1 are the same number: a column of whole numbers is kept as integers on every side
        vals = [r[k] for r in clean if r[k] is not None]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and abs(v) < 2 ** 53 for v in vals) and any(isinstance(v, float) for v in vals):
            for r in clean:
                if r[k] is not None:
                    r[k] = int(r[k])
    tbl = pa.Table.from_pylist(clean) if clean and cols else pa.table({k: pa.array([], pa.string()) for k in cols or ["no_columns"]})
    pq.write_table(tbl, d / fname)
    return fname


def _cell(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    try:
        import decimal
        if isinstance(v, decimal.Decimal):
            return float(v)
    except ImportError:
        pass
    return v


def sql_rows(ctx, cid: str, sql: str) -> list[dict]:
    """One guarded, read-only SELECT through an item connection (the person's own sign-in), as dicts."""
    c = ctx.connection(cid)
    try:
        return connectors.query(c, sql, ctx.who or ctx.owner)["rows"]
    except connectors.ConnectorError as e:
        from .. import workbench as wb
        raise wb.StepFailed(f"{c['name']}: {e}") from e


def sign_v4(method: str, url: str, region: str, service: str, key: str, secret_key: str, body: bytes = b"", headers: dict | None = None, token: str | None = None) -> dict:
    """AWS Signature Version 4 headers for one request (Glue, Redshift Data API)."""
    from urllib.parse import quote, urlsplit
    u = urlsplit(url)
    now = dt.datetime.now(dt.timezone.utc)
    amz, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    h = {k.lower(): v for k, v in (headers or {}).items()}
    h.update({"host": u.netloc, "x-amz-date": amz, "x-amz-content-sha256": hashlib.sha256(body).hexdigest()})
    if token:
        h["x-amz-security-token"] = token
    signed = sorted(h)
    q = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(p.split("=", 1) if "=" in p else (p, "") for p in u.query.split("&") if p))
    creq = "\n".join([method, quote(u.path or "/", safe="/-_.~"), q, "".join(f"{k}:{str(h[k]).strip()}\n" for k in signed), ";".join(signed), h["x-amz-content-sha256"]])
    scope = f"{day}/{region}/{service}/aws4_request"
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = hmac.new(("AWS4" + secret_key).encode(), day.encode(), hashlib.sha256).digest()
    for part in (region, service, "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    out = {**{k2: v for k2, v in h.items() if k2 != "host"}, "Authorization": f"AWS4-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={';'.join(signed)}, Signature={sig}"}
    return out


ORACLE = register(OracleOrds())
ADF_ = register(ADF())
DBT = register(DbtCloud())
AIRFLOW = register(Airflow())
IICS_ = register(IICS())
TALEND = register(TalendTmc())
FIVETRAN = register(Fivetran())
_patch_open()
