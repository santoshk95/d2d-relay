"""W1 Data & Analytics — the SQL warehouses reached over their documented HTTP APIs (beside Oracle REST-enabled SQL in
_w1): Teradata Query Service, IBM Db2 REST (dbapi v4), the Snowflake SQL API v2 and Databricks SQL Statement Execution.
Each is a `_w1.SqlKind`: one `execute(c, sql)` that runs a statement and returns (columns, rows) with the vendor's
types decoded, its data dictionary as SQL, and writes only with an approval id. The mock lab's simulators
(tests/mocklab/sims: teradata, db2, snowflake, databricks_sql) stand in for each.

The dialect each kind declares is sqlglot's (connectors.query parses and limits every read in it): Db2 has none in
sqlglot, so it reads as PostgreSQL (the subset a guarded SELECT uses is the same).
"""
from __future__ import annotations

import datetime as dt
import time

from .. import connectors
from . import _w1
from ._w1 import cfg, secret


class Teradata(_w1.SqlKind):
    """Teradata Vantage through the Teradata Query Service REST API (basic auth as the database user)."""
    kind, label, dialect = "teradata", "Teradata Vantage (Query Service)", "teradata"
    signin = ["password"]
    fields = [("base_url", "Query Service address (https://<host>:1443)", True), ("system", "System name", True), ("user", "Database user", True)]
    secrets = {"password": ["password"]}
    simulator = "teradata"
    probe = "SELECT COUNT(*) AS N FROM DBC.TablesV"
    tables_sql = "SELECT TRIM(DatabaseName) || '.' || TRIM(TableName) AS OBJ, CASE TableKind WHEN 'V' THEN 'VIEW' ELSE 'TABLE' END AS T FROM DBC.TablesV WHERE TableKind IN ('T', 'V', 'O')"
    columns_sql = "SELECT TRIM(DatabaseName) || '.' || TRIM(TableName) AS T, TRIM(ColumnName) AS C FROM DBC.ColumnsV ORDER BY DatabaseName, TableName, ColumnId"

    def auth(self, c):
        return self.basic(cfg(c, "user"), secret(c, "password"))

    def execute(self, c, sql, approval=None):
        r = self.call(c, "POST", f"/systems/{cfg(c, 'system')}/queries", json_body={"query": sql, "format": "ARRAY", "rowLimit": 50000}, approval=approval)
        res = (r.get("results") or [{}])[-1] if isinstance(r, dict) else {}
        if not res.get("resultSet"):
            return [], []
        return [x["name"] for x in res.get("columns") or []], [list(x) for x in res.get("data") or []]


class Db2(_w1.SqlKind):
    """IBM Db2 Warehouse / Db2 on Cloud through the Db2 REST API v4 (a token from the user's password; SQL jobs)."""
    kind, label, dialect = "db2", "IBM Db2 (REST)", "postgres"
    signin = ["password"]
    fields = [("base_url", "REST address (…/dbapi/v4)", True), ("deployment_id", "Deployment id (CRN)", True), ("user", "User id", True)]
    secrets = {"password": ["password"]}
    simulator = "db2"
    probe = "SELECT COUNT(*) AS N FROM SYSCAT.TABLES"
    tables_sql = "SELECT TRIM(TABSCHEMA) || '.' || TRIM(TABNAME) AS OBJ, CASE TYPE WHEN 'V' THEN 'VIEW' ELSE 'TABLE' END AS T FROM SYSCAT.TABLES"
    columns_sql = "SELECT TRIM(TABSCHEMA) || '.' || TRIM(TABNAME) AS T, TRIM(COLNAME) AS C FROM SYSCAT.COLUMNS ORDER BY TABSCHEMA, TABNAME, COLNO"

    def auth(self, c):
        def fetch():
            r = self.call(c, "POST", "/auth/tokens", json_body={"userid": cfg(c, "user"), "password": secret(c, "password")}, auth=False,
                          headers={"x-deployment-id": cfg(c, "deployment_id")})
            return r["token"], 3000
        return {"Authorization": f"Bearer {self.token(c, fetch)}", "x-deployment-id": cfg(c, "deployment_id")}

    def execute(self, c, sql, approval=None):
        r = self.call(c, "POST", "/sql_jobs", json_body={"commands": sql, "limit": 50000, "separator": ";", "stop_on_error": "yes"}, approval=approval)
        jid = r["id"]
        for _ in range(60):
            j = self.call(c, "GET", f"/sql_jobs/{jid}")
            if j.get("status") in ("completed", "failed"):
                break
            time.sleep(0.2)
        res = (j.get("results") or [{}])[-1]
        if res.get("error"):
            raise connectors.ConnectorError(f"Db2: {res['error']}")
        return list(res.get("columns") or []), [[_w1._num(v) for v in row] for row in res.get("rows") or []]


SF_EPOCH = dt.date(1970, 1, 1)


def _sf(v, t: dict):
    if v is None:
        return None
    ty = (t.get("type") or "text").lower()
    if ty == "fixed":
        return int(v) if not t.get("scale") else float(v)
    if ty == "real":
        return float(v)
    if ty == "date":
        return (SF_EPOCH + dt.timedelta(days=int(v))).isoformat()
    if ty.startswith("timestamp"):
        return dt.datetime.fromtimestamp(float(v), dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if ty == "boolean":
        return str(v).lower() == "true"
    return v


class SnowflakeApi(_w1.SqlKind):
    """Snowflake through the SQL API v2 (a programmatic access token; results in partitions)."""
    kind, label, dialect = "snowflake_sqlapi", "Snowflake (SQL API)", "snowflake"
    signin = ["api_key"]
    fields = [("base_url", "Account address (https://<account>.snowflakecomputing.com)", True), ("warehouse", "Warehouse", True), ("database", "Database", True),
              ("role", "Role", False)]
    secrets = {"api_key": ["token"]}
    simulator = "snowflake"
    probe = "SELECT COUNT(*) AS N FROM INFORMATION_SCHEMA.TABLES"
    tables_sql = "SELECT TABLE_SCHEMA || '.' || TABLE_NAME AS OBJ, TABLE_TYPE AS T FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA'"
    columns_sql = "SELECT TABLE_SCHEMA || '.' || TABLE_NAME AS T, COLUMN_NAME AS C FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA' ORDER BY 1, ORDINAL_POSITION"

    def auth(self, c):
        return {"Authorization": f"Bearer {secret(c, 'token')}", "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"}

    def execute(self, c, sql, approval=None):
        body = {"statement": sql, "warehouse": cfg(c, "warehouse"), "database": cfg(c, "database"), "timeout": 120,
                **({"role": cfg(c, "role")} if cfg(c, "role") else {}), "parameters": {"MULTI_STATEMENT_COUNT": "0"}}
        r = self.call(c, "POST", "/api/v2/statements", json_body=body, approval=approval)
        for _ in range(60):
            if r.get("data") is not None or r.get("resultSetMetaData"):
                break
            time.sleep(0.2)
            r = self.call(c, "GET", f"/api/v2/statements/{r['statementHandle']}")
        meta = r.get("resultSetMetaData") or {}
        types = meta.get("rowType") or []
        rows = list(r.get("data") or [])
        for i in range(1, len(meta.get("partitionInfo") or [])):
            rows += self.call(c, "GET", f"/api/v2/statements/{r['statementHandle']}", params={"partition": i}).get("data") or []
        return [t["name"] for t in types], [[_sf(v, t) for v, t in zip(row, types)] for row in rows]


def _dbx(v, ty: str):
    if v is None:
        return None
    t = (ty or "STRING").upper()
    if t in ("INT", "BIGINT", "SMALLINT", "TINYINT", "LONG", "SHORT", "BYTE"):
        return int(v)
    if t in ("DOUBLE", "FLOAT", "DECIMAL"):
        return float(v)
    if t == "BOOLEAN":
        return str(v).lower() == "true"
    return v


class Databricks(_w1.SqlKind):
    """Databricks SQL through the Statement Execution API 2.0 (a personal access token; JSON_ARRAY chunks)."""
    kind, label, dialect = "databricks_sql", "Databricks SQL (Statement Execution)", "databricks"
    signin = ["api_key"]
    fields = [("base_url", "Workspace address (https://adb-….azuredatabricks.net)", True), ("warehouse_id", "SQL warehouse id", True), ("catalog", "Catalog", False)]
    secrets = {"api_key": ["token"]}
    simulator = "databricks_sql"
    probe = "SELECT COUNT(*) AS n FROM information_schema.tables"
    tables_sql = "SELECT table_schema || '.' || table_name AS obj, table_type AS t FROM information_schema.tables WHERE table_schema <> 'information_schema'"
    columns_sql = "SELECT table_schema || '.' || table_name AS t, column_name AS c FROM information_schema.columns WHERE table_schema <> 'information_schema' ORDER BY 1, ordinal_position"

    def auth(self, c):
        return {"Authorization": f"Bearer {secret(c, 'token')}"}

    def uc_tables(self, c) -> list[dict]:
        """Every table of the catalog with its columns, from Unity Catalog (the workspace's own metadata API)."""
        out, token = [], None
        while True:
            r = self.call(c, "GET", "/api/2.1/unity-catalog/tables", params={"catalog_name": cfg(c, "catalog") or "main", "max_results": 50, **({"page_token": token} if token else {})})
            out += r.get("tables") or []
            token = r.get("next_page_token")
            if not token or len(out) > 5000:
                return out

    def dictionary(self, c):
        return {f"{t['schema_name']}.{t['name']}".upper(): [x["name"].upper() for x in sorted(t.get("columns") or [], key=lambda x: x.get("position") or 0)] for t in self.uc_tables(c)}

    def execute(self, c, sql, approval=None):
        body = {"statement": sql, "warehouse_id": cfg(c, "warehouse_id"), "wait_timeout": "30s", "format": "JSON_ARRAY", "disposition": "INLINE",
                **({"catalog": cfg(c, "catalog")} if cfg(c, "catalog") else {})}
        r = self.call(c, "POST", "/api/2.0/sql/statements", json_body=body, approval=approval)
        for _ in range(60):
            st = (r.get("status") or {}).get("state")
            if st in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
                break
            time.sleep(0.2)
            r = self.call(c, "GET", f"/api/2.0/sql/statements/{r['statement_id']}")
        if (r.get("status") or {}).get("state") != "SUCCEEDED":
            raise connectors.ConnectorError(f"Databricks: {((r.get('status') or {}).get('error') or {}).get('message') or 'the statement did not succeed'}")
        cols = (r.get("manifest") or {}).get("schema", {}).get("columns") or []
        res = r.get("result") or {}
        rows = list(res.get("data_array") or [])
        while res.get("next_chunk_internal_link"):
            res = self.call(c, "GET", res["next_chunk_internal_link"])
            rows += res.get("data_array") or []
        names = [x["name"] for x in cols]
        types = [x.get("type_name") for x in cols]
        if names == ["num_affected_rows"]:
            return [], []
        return names, [[_dbx(v, t) for v, t in zip(row, types)] for row in rows]


TERADATA = _w1.register(Teradata())
DB2 = _w1.register(Db2())
SNOWFLAKE = _w1.register(SnowflakeApi())
DATABRICKS = _w1.register(Databricks())
LEGACY_KINDS = ("oracle", "teradata", "db2")
CLOUD_KINDS = ("snowflake_sqlapi", "databricks_sql")
