"""Data warehouse & lakehouse - the estate model and the rules (rules first; the agent only for procedural code).

The estate, the same for every platform:
  tables    [{"name": "DW.FACT_SALES", "kind": "TABLE"|"VIEW", "rows", "bytes", "columns": [{"name", "type", "logical"}],
              "keys": [...], "partitioned": bool, "comment"}]
  views     {"MART.V_SALES_DASHBOARD": select sql}
  routines  [{"name", "type" (PACKAGE BODY, PROCEDURE, MACRO, BTEQ, TRIGGER...), "lines", "text"}]
  history   [{"text", "user", "start", "elapsed_ms", "status", "error", "rows"}]
  jobs      [{"job", "status", "start", "error"}]
read from the source's own data dictionary through its API (Oracle ALL_* / DBA_HIST, Teradata DBC, Db2 SYSCAT,
Snowflake INFORMATION_SCHEMA) or from its exports (ddl/*.sql, views.sql, code/*, history/*.csv - SQL Server, Netezza,
Greenplum and Hive have no HTTP API).

  usage     per table: queries in the history window, the people and services that ran them, the last time
  health    never queried, a copy or backup, an orphan temp table, failing queries, slow queries, procedural code
  decide    Keep / Merge / Retire with the reason, and the wave (staging and dimensions, then facts, then marts)
  convert   DDL by rules from the logical types (each target's own types and clustering), views transpiled by
            sqlglot, the data load as batched INSERTs; procedural code is left for the agent with its size
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

DIALECT = {"oracle": "oracle", "oracle_db": "oracle", "teradata": "teradata", "db2": "postgres", "snowflake_sqlapi": "snowflake", "databricks_sql": "databricks", "snowflake": "snowflake",
           "bigquery": "bigquery", "fabric": "tsql", "redshift": "redshift", "athena": "athena", "postgres": "postgres", "sqlserver": "tsql"}
TARGETS = (("snowflake", "Snowflake"), ("databricks", "Databricks"), ("bigquery", "BigQuery"), ("tsql", "Microsoft Fabric / Synapse"), ("redshift", "Amazon Redshift"))
SOURCES = (("oracle", "Oracle DW / Exadata / Autonomous DW"), ("teradata", "Teradata"), ("tsql", "SQL Server"), ("postgres", "Netezza / Greenplum / Db2"), ("hive", "Hadoop / Hive"))
LEGACY_RX = re.compile(r"(?i)(_\d{4}$|_BKP$|_BAK$|_BACKUP$|_OLD$|_COPY$|^TMP_|_TMP$|_TEMP$|^TEMP_)")
LEGACY_WORDS = re.compile(r"(?i)\b(copy|backup|orphan|retired|deprecated|temp(orary)?|never queried|old)\b")


# ================================================================== reading the estate

ESTATE_SQL = {
    "oracle": {
        "tables": "SELECT t.OWNER AS S, t.TABLE_NAME AS T, t.NUM_ROWS AS N, t.PARTITIONED AS P, g.BYTES AS B FROM ALL_TABLES t LEFT JOIN DBA_SEGMENTS g ON g.OWNER = t.OWNER AND g.SEGMENT_NAME = t.TABLE_NAME WHERE t.OWNER NOT IN ('SYS', 'SYSTEM')",
        "columns": "SELECT OWNER AS S, TABLE_NAME AS T, COLUMN_NAME AS C, DATA_TYPE AS Y, DATA_LENGTH AS L, DATA_PRECISION AS P, DATA_SCALE AS SC FROM ALL_TAB_COLUMNS WHERE OWNER NOT IN ('SYS', 'SYSTEM') ORDER BY OWNER, TABLE_NAME, COLUMN_ID",
        "views": "SELECT OWNER AS S, VIEW_NAME AS T, TEXT AS X FROM ALL_VIEWS",
        "routines": "SELECT OWNER AS S, NAME AS T, TYPE AS Y, LINE AS L, TEXT AS X FROM ALL_SOURCE WHERE OWNER NOT IN ('SYS', 'SYSTEM') ORDER BY OWNER, NAME, TYPE, LINE",
        "history": "SELECT t.SQL_TEXT AS X, s.PARSING_SCHEMA_NAME AS U, s.EXECUTIONS_DELTA AS E, s.ELAPSED_TIME_DELTA AS MS, s.ROWS_PROCESSED_DELTA AS R, n.BEGIN_INTERVAL_TIME AS W "
                   "FROM DBA_HIST_SQLSTAT s JOIN DBA_HIST_SQLTEXT t ON t.SQL_ID = s.SQL_ID JOIN DBA_HIST_SNAPSHOT n ON n.SNAP_ID = s.SNAP_ID",
        "jobs": "SELECT JOB_NAME AS J, STATUS AS ST, ACTUAL_START_DATE AS W, ADDITIONAL_INFO AS E FROM DBA_SCHEDULER_JOB_RUN_DETAILS",
    },
    "teradata": {
        "tables": "SELECT TRIM(t.DatabaseName) AS S, TRIM(t.TableName) AS T, t.TableKind AS K, t.CommentString AS CM, t.RequestText AS X FROM DBC.TablesV t",
        "sizes": "SELECT TRIM(DatabaseName) AS S, TRIM(TableName) AS T, SUM(CurrentPerm) AS B FROM DBC.TableSizeV GROUP BY 1, 2",
        "columns": "SELECT TRIM(DatabaseName) AS S, TRIM(TableName) AS T, TRIM(ColumnName) AS C, ColumnType AS Y, ColumnLength AS L, DecimalTotalDigits AS P, DecimalFractionalDigits AS SC FROM DBC.ColumnsV ORDER BY DatabaseName, TableName, ColumnId",
        "keys": "SELECT TRIM(DatabaseName) AS S, TRIM(TableName) AS T, TRIM(ColumnName) AS C, IndexType AS Y FROM DBC.IndicesV ORDER BY DatabaseName, TableName, ColumnPosition",
        "history": "SELECT QueryText AS X, UserName AS U, StartTime AS W, ErrorCode AS EC, ErrorText AS E, NumResultRows AS R, AMPCPUTime AS CPU FROM DBC.QryLogV",
    },
    "db2": {
        "tables": "SELECT TRIM(TABSCHEMA) AS S, TRIM(TABNAME) AS T, TYPE AS K, CARD AS N, REMARKS AS CM FROM SYSCAT.TABLES",
        "columns": "SELECT TRIM(TABSCHEMA) AS S, TRIM(TABNAME) AS T, TRIM(COLNAME) AS C, TYPENAME AS Y, LENGTH AS L, LENGTH AS P, SCALE AS SC FROM SYSCAT.COLUMNS ORDER BY TABSCHEMA, TABNAME, COLNO",
        "views": "SELECT TRIM(VIEWSCHEMA) AS S, TRIM(VIEWNAME) AS T, TEXT AS X FROM SYSCAT.VIEWS",
        "routines": "SELECT TRIM(ROUTINESCHEMA) AS S, TRIM(ROUTINENAME) AS T, ROUTINETYPE AS Y, TEXT AS X FROM SYSCAT.ROUTINES",
        "history": "SELECT STMT_TEXT AS X, NUM_EXECUTIONS AS E, AVERAGE_EXECUTION_TIME_S AS AVG FROM SYSIBMADM.TOP_DYNAMIC_SQL",
    },
    "snowflake_sqlapi": {
        "tables": "SELECT TABLE_SCHEMA AS S, TABLE_NAME AS T, TABLE_TYPE AS K, ROW_COUNT AS N, BYTES AS B, COMMENT AS CM, CLUSTERING_KEY AS P FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA'",
        "columns": "SELECT TABLE_SCHEMA AS S, TABLE_NAME AS T, COLUMN_NAME AS C, DATA_TYPE AS Y, CHARACTER_MAXIMUM_LENGTH AS L, NUMERIC_PRECISION AS P, NUMERIC_SCALE AS SC FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA <> 'INFORMATION_SCHEMA' ORDER BY 1, 2, ORDINAL_POSITION",
        "views": "SELECT TABLE_SCHEMA AS S, TABLE_NAME AS T, VIEW_DEFINITION AS X FROM INFORMATION_SCHEMA.VIEWS",
        "history": "SELECT QUERY_TEXT AS X, USER_NAME AS U, START_TIME AS W, TOTAL_ELAPSED_TIME AS MS, EXECUTION_STATUS AS ST, ERROR_MESSAGE AS E, ROWS_PRODUCED AS R FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
    },
}
# A direct Oracle Database connection (python-oracledb): the ALL_* views any reader has, no DBA_SEGMENTS (the size comes
# from the statistics' blocks); the query history and scheduler runs only when the sign-in may read them.
_ORA_OWN = "SELECT USERNAME FROM ALL_USERS WHERE ORACLE_MAINTAINED = 'Y'"
ESTATE_SQL["oracle_db"] = {
    "tables": "SELECT t.OWNER AS S, t.TABLE_NAME AS T, t.NUM_ROWS AS N, t.PARTITIONED AS P, t.BLOCKS * 8192 AS B FROM ALL_TABLES t "
              f"WHERE t.OWNER NOT IN ({_ORA_OWN}) AND t.NESTED = 'NO' AND t.SECONDARY = 'N' AND t.DROPPED = 'NO'",
    "columns": "SELECT OWNER AS S, TABLE_NAME AS T, COLUMN_NAME AS C, DATA_TYPE AS Y, DATA_LENGTH AS L, DATA_PRECISION AS P, DATA_SCALE AS SC FROM ALL_TAB_COLUMNS "
               f"WHERE OWNER NOT IN ({_ORA_OWN}) ORDER BY OWNER, TABLE_NAME, COLUMN_ID",
    "views": f"SELECT OWNER AS S, VIEW_NAME AS T, TEXT AS X FROM ALL_VIEWS WHERE OWNER NOT IN ({_ORA_OWN})",
    "routines": f"SELECT OWNER AS S, NAME AS T, TYPE AS Y, LINE AS L, TEXT AS X FROM ALL_SOURCE WHERE OWNER NOT IN ({_ORA_OWN}) ORDER BY OWNER, NAME, TYPE, LINE",
    "history": ESTATE_SQL["oracle"]["history"], "jobs": ESTATE_SQL["oracle"]["jobs"]}
ESTATE_SQL["databricks_sql"] = {
    "tables": "SELECT table_schema AS s, table_name AS t, table_type AS k FROM information_schema.tables WHERE table_schema <> 'information_schema'",
    "columns": "SELECT table_schema AS s, table_name AS t, column_name AS c, data_type AS y FROM information_schema.columns WHERE table_schema <> 'information_schema' ORDER BY 1, 2, ordinal_position",
}


def _rows(a, c, sql: str) -> list[dict]:
    cols, rows = a.execute(c, sql)
    return [{k.upper(): v for k, v in zip(cols, r)} for r in rows]


def logical(src_type: str, length=None, prec=None, scale=None) -> str:
    """A source column type as the lab's logical type: int bigint dec(p,s) str(n) char(n) date ts bool."""
    t = (src_type or "").upper().strip()
    m = re.match(r"([A-Z_ 0-9]+?)\s*(?:\((\d+)(?:\s*,\s*(\d+))?(?:\s+(?:CHAR|BYTE))?\))?$", t)
    base = (m.group(1) if m else t).strip()
    a = int(m.group(2)) if m and m.group(2) else None
    b = int(m.group(3)) if m and m.group(3) else None
    p = prec if prec not in (None, "") else a
    s = scale if scale not in (None, "") else b
    p = int(p) if p not in (None, "") else None
    s = int(s) if s not in (None, "") else None
    L = int(length) if length not in (None, "") else a
    code = {"I": "INTEGER", "I8": "BIGINT", "I1": "BYTEINT", "I2": "SMALLINT", "D": "DECIMAL", "CV": "VARCHAR", "CF": "CHAR", "DA": "DATE", "TS": "TIMESTAMP"}.get(base)
    base = code or base
    if base in ("NUMBER", "NUMERIC", "DECIMAL", "DEC"):
        if p == 1 and not s:
            return "bool" if base == "NUMBER" else "int"
        if not s:
            return "bigint" if (p or 19) > 10 else "int"
        return f"dec({p or 18},{s})"
    if base in ("INTEGER", "INT", "SMALLINT", "BYTEINT", "TINYINT", "INT4", "INT2"):
        return "int"
    if base in ("BIGINT", "INT8", "LONG"):
        return "bigint"
    if base in ("FLOAT", "DOUBLE", "REAL", "BINARY_DOUBLE", "DOUBLE PRECISION", "FLOAT8"):
        return "dec(38,6)"
    if base in ("BOOLEAN", "BOOL", "BIT"):
        return "bool"
    if base.startswith("TIMESTAMP") or base in ("DATETIME", "DATETIME2", "SMALLDATETIME", "TIMESTAMP_NTZ"):
        return "ts"
    if base == "DATE":
        return "date"
    if base in ("CHAR", "NCHAR", "CHARACTER", "NATIONAL CHARACTER", "BPCHAR"):
        return f"char({L or 1})"
    return f"str({min(int(L or 255), 16000)})"


def from_api(a, c) -> dict:
    """The estate from the warehouse's own dictionary, through its API."""
    q = ESTATE_SQL.get(c["kind"]) or {}
    est = {"tables": [], "views": {}, "routines": [], "history": [], "jobs": [], "dialect": DIALECT.get(c["kind"], "ansi"), "where": c["name"]}
    tabs: dict[str, dict] = {}
    for r in _rows(a, c, q["tables"]):
        name = f"{r['S']}.{r['T']}".upper()
        kind = "VIEW" if str(r.get("K") or "").upper() in ("V", "VIEW") else "ROUTINE" if str(r.get("K") or "").upper() in ("P", "M") else "TABLE"
        if kind == "ROUTINE":
            est["routines"].append({"name": name, "type": "PROCEDURE" if r.get("K") == "P" else "MACRO", "text": r.get("X") or "", "lines": len((r.get("X") or "").splitlines())})
            continue
        if kind == "VIEW" and r.get("X"):
            est["views"][name] = re.sub(r"(?is)^\s*(REPLACE|CREATE(\s+OR\s+REPLACE)?)\s+VIEW\s+\S+\s+AS\s+", "", r["X"]).rstrip().rstrip(";")
        tabs[name] = {"name": name, "kind": kind, "rows": r.get("N"), "bytes": r.get("B"), "columns": [], "keys": [], "partitioned": str(r.get("P") or "").upper() in ("YES", "TRUE") or bool(r.get("P") and str(r.get("P")).upper() not in ("NO", "NONE")),
                      "comment": r.get("CM") or ""}
    if q.get("sizes"):
        for r in _rows(a, c, q["sizes"]):
            t = tabs.get(f"{r['S']}.{r['T']}".upper())
            if t:
                t["bytes"] = r.get("B")
    for r in _rows(a, c, q["columns"]):
        t = tabs.get(f"{r['S']}.{r['T']}".upper())
        if t is not None:
            t["columns"].append({"name": str(r["C"]).upper(), "type": str(r.get("Y") or ""), "logical": logical(str(r.get("Y") or ""), r.get("L"), r.get("P"), r.get("SC"))})
    if q.get("keys"):
        for r in _rows(a, c, q["keys"]):
            t = tabs.get(f"{r['S']}.{r['T']}".upper())
            if t is not None and str(r.get("Y")) in ("P", "Q", "U"):
                t["keys"].append(str(r["C"]).upper())
                t["partitioned"] = t["partitioned"] or r.get("Y") == "Q"
    if q.get("views"):
        for r in _rows(a, c, q["views"]):
            est["views"][f"{r['S']}.{r['T']}".upper()] = re.sub(r"(?is)^\s*CREATE(\s+OR\s+REPLACE)?\s+VIEW\s+\S+\s+AS\s+", "", str(r.get("X") or "")).rstrip().rstrip(";")
    if q.get("routines"):
        by: dict[tuple, list] = {}
        for r in _rows(a, c, q["routines"]):
            by.setdefault((f"{r['S']}.{r['T']}".upper(), str(r.get("Y") or "PROCEDURE")), []).append(str(r.get("X") or ""))
        for (n, ty), parts in by.items():
            text = "".join(parts) if c["kind"] in ("oracle", "oracle_db") else "\n".join(parts)
            est["routines"].append({"name": n, "type": ty, "text": text, "lines": len(text.splitlines())})
    if q.get("history"):
        try:
            for r in _rows(a, c, q["history"]):
                ec = r.get("EC")
                err = r.get("E") if (ec not in (None, 0, "0") or str(r.get("ST") or "").upper() in ("FAIL", "FAILED", "FAILED_WITH_ERROR")) else None
                est["history"].append({"text": str(r.get("X") or ""), "user": r.get("U"), "start": r.get("W"), "elapsed_ms": r.get("MS") or (float(r.get("CPU") or 0) * 400 if r.get("CPU") else None),
                                       "status": "FAILED" if err else "SUCCESS", "error": err, "rows": r.get("R"), "executions": r.get("E") if c["kind"] != "teradata" else 1})
        except Exception:  # noqa: BLE001 - a dictionary view the person's role cannot read: the history is simply not there
            est["history_note"] = "the query history is not readable with this sign-in"
    if q.get("jobs"):
        try:
            est["jobs"] = [{"job": r.get("J"), "status": r.get("ST"), "start": r.get("W"), "error": r.get("E")} for r in _rows(a, c, q["jobs"])]
        except Exception:  # noqa: BLE001
            pass
    for t in tabs.values():
        if t["rows"] in (None, "", -1) and t["kind"] == "TABLE" and len(tabs) <= 400:
            try:
                t["rows"] = int(list(_rows(a, c, f"SELECT COUNT(*) AS N FROM {t['name']}")[0].values())[0])
            except Exception:  # noqa: BLE001
                t["rows"] = None
    est["tables"] = list(tabs.values())
    return est


CREATE_RX = re.compile(r"(?is)CREATE\s+(?:MULTISET\s+|SET\s+|OR\s+REPLACE\s+|GLOBAL\s+TEMPORARY\s+|EXTERNAL\s+)*TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"`\[\]]+)\s*\(")


def _split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_ddl(text: str) -> list[dict]:
    """CREATE TABLE statements of any dialect into tables with columns and logical types (no engine needed)."""
    out = []
    for m in CREATE_RX.finditer(text):
        name = re.sub(r"[\"`\[\]]", "", m.group(1)).upper()
        i, depth = m.end(), 1
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body, tail = text[m.end():i - 1], text[i:i + 400].split(";")[0]
        cols, keys = [], []
        for part in _split_top(body):
            pm = re.match(r"(?is)(?:CONSTRAINT\s+\w+\s+)?PRIMARY\s+KEY\s*\(([^)]*)\)", part)
            if pm:
                keys += [x.strip().strip('"').upper() for x in pm.group(1).split(",")]
                continue
            if re.match(r"(?i)(CONSTRAINT|UNIQUE|FOREIGN|CHECK|INDEX|KEY)\b", part):
                continue
            cm = re.match(r"(?is)[\"`\[]?(\w+)[\"`\]]?\s+([A-Za-z_][\w ]*?(?:\([^)]*\))?)(?:\s+(?:NOT\s+NULL|NULL|DEFAULT|CHARACTER|FORMAT|COMPRESS|ENCODE|COLLATE|GENERATED|IDENTITY|CASESPECIFIC|NOT\s+CASESPECIFIC|UNICODE|LATIN)\b.*)?$", part)
            if cm:
                ty = re.sub(r"(?i)\s+(CHARACTER\s+SET.*|NOT\s+CASESPECIFIC.*)$", "", cm.group(2)).strip()
                cols.append({"name": cm.group(1).upper(), "type": ty, "logical": logical(ty)})
        pi = re.search(r"(?i)PRIMARY\s+INDEX\s*\(([^)]*)\)", tail)
        if pi and not keys:
            keys = [x.strip().upper() for x in pi.group(1).split(",")]
        out.append({"name": name, "kind": "TABLE", "rows": None, "bytes": None, "columns": cols, "keys": keys,
                    "partitioned": bool(re.search(r"(?i)PARTITION\s+BY|PARTITIONED\s+BY|ORGANIZE\s+ON|DISTRIBUTE\s+ON\s*\(", tail)), "comment": ""})
    return out


def from_files(paths: list[Path]) -> dict:
    """The estate from the exports: DDL, views, procedural code and the history the tool writes."""
    files: dict[str, bytes] = {}
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if not n.endswith("/"):
                        files[n] = z.read(n)
        else:
            files[p.name] = p.read_bytes()
    est = {"tables": [], "views": {}, "routines": [], "history": [], "jobs": [], "dialect": "ansi", "where": "upload"}
    alltext = ""
    for n, b in sorted(files.items()):
        low, txt = n.lower(), b.decode("utf-8", "replace")
        base = Path(n).name
        if low.endswith("views.sql"):
            for m in re.finditer(r"(?is)(?:CREATE(?:\s+OR\s+REPLACE)?|REPLACE)\s+VIEW\s+([\w.\"`]+)\s+AS\s+(.*?);\s*(?=\n|$)", txt):
                est["views"][re.sub(r"[\"`]", "", m.group(1)).upper()] = m.group(2).strip()
        elif low.endswith((".sql", ".hql")) and "/ddl/" in "/" + low or low.startswith("ddl/"):
            est["tables"] += parse_ddl(txt)
            alltext += txt
        elif low.endswith(("query_history.csv",)):
            for r in csv.DictReader(io.StringIO(txt)):
                est["history"].append({"text": r.get("QUERY_TEXT") or "", "user": r.get("USER_NAME"), "start": r.get("START_TIME"), "elapsed_ms": float(r.get("ELAPSED_MS") or 0),
                                       "status": (r.get("STATUS") or "SUCCESS").upper(), "error": r.get("ERROR_MESSAGE") or None, "rows": r.get("ROWS"), "executions": 1})
        elif low.endswith("job_history.csv"):
            est["jobs"] += [{"job": r.get("JOB_NAME"), "status": r.get("STATUS"), "start": r.get("START_TIME"), "error": r.get("ERROR") or None} for r in csv.DictReader(io.StringIO(txt))]
        elif low.startswith(("code/", "bteq/")) or "/code/" in low or "/bteq/" in low or low.endswith((".pkb", ".pks", ".bteq", ".trg", ".nzplsql")):
            ty = {"pkb": "PACKAGE BODY", "pks": "PACKAGE", "trg": "TRIGGER", "bteq": "BTEQ", "ctl": "NZLOAD", "hql": "HQL"}.get(base.rsplit(".", 1)[-1].lower(), "PROCEDURE")
            est["routines"].append({"name": Path(base).stem.upper(), "type": ty, "text": txt, "lines": len(txt.splitlines())})
    est["dialect"] = sniff(alltext)
    return est


def sniff(ddl: str) -> str:
    if re.search(r"(?i)PRIMARY\s+INDEX|MULTISET", ddl):
        return "teradata"
    if re.search(r"(?i)VARCHAR2|TABLESPACE\s+\w+|NUMBER\(", ddl):
        return "oracle"
    if re.search(r"(?i)NVARCHAR|DATETIME2|\[dbo\]|\bWITH\s*\(\s*DISTRIBUTION", ddl):
        return "tsql"
    if re.search(r"(?i)DISTRIBUTE\s+ON|ORGANIZE\s+ON|NATIONAL\s+CHARACTER", ddl):
        return "postgres"
    if re.search(r"(?i)DISTRIBUTED\s+BY", ddl):
        return "postgres"
    if re.search(r"(?i)STORED\s+AS|ROW\s+FORMAT|\bSTRING\b", ddl):
        return "hive"
    return "ansi"


# ================================================================== usage, health and decisions

def usage(est: dict) -> dict:
    """Per table and view: queries in the history, the users, failures (word match on the object's name)."""
    names = [t["name"] for t in est["tables"]] + [v for v in est["views"] if v not in {t["name"] for t in est["tables"]}]
    pats = {n: re.compile(rf"(?i)(?<![\w.]){re.escape(n)}(?![\w])|(?<![\w.])\"?{re.escape(n.split('.')[0])}\"?\.\"?{re.escape(n.split('.')[-1])}\"?(?![\w])") for n in names}
    out = {n: {"queries": 0, "users": set(), "failed": 0, "last": None, "reads": 0, "writes": 0} for n in names}
    for q in est["history"]:
        text = q.get("text") or ""
        w = re.match(r"(?is)\s*(INSERT|MERGE|UPDATE|DELETE|TRUNCATE|CREATE|REPLACE|COPY|INS)\b", text)
        for n, rx in pats.items():
            if rx.search(text):
                u = out[n]
                u["queries"] += int(q.get("executions") or 1)
                if q.get("user"):
                    u["users"].add(str(q["user"]))
                u["failed"] += 1 if q.get("status") == "FAILED" else 0
                u["writes" if w else "reads"] += 1
                u["last"] = max(filter(None, [u["last"], str(q.get("start") or "")])) if q.get("start") else u["last"]
    for u in out.values():
        u["users"] = sorted(u["users"])
    return out


def health(est: dict, use: dict) -> list[dict]:
    out = []

    def add(obj, kind, sev, issue, measured="", ev=None):
        out.append({"id": f"{kind}-{re.sub(r'[^a-z0-9]+', '-', obj.lower())}", "object": obj, "issue_kind": kind, "severity": sev, "issue": issue, "measured": measured, "evidence": ev or {}, "decision": "keep"})
    have_history = bool(est["history"])
    for t in est["tables"]:
        u = use.get(t["name"]) or {}
        tail = t["name"].split(".")[-1]
        if LEGACY_RX.search(tail) or (t.get("comment") and LEGACY_WORDS.search(t["comment"])):
            add(t["name"], "legacy", "low", f"looks like a copy, backup or temporary table{(' (' + t['comment'] + ')') if t.get('comment') else ''} - retire it rather than move it", t.get("comment") or tail, {"comment": t.get("comment")})
        elif have_history and not u.get("queries") and t["kind"] == "TABLE":
            add(t["name"], "unused", "low", "never queried in the history window - a retire candidate", "0 queries", {})
        if u.get("failed"):
            errs = sorted({q.get("error") or "" for q in est["history"] if q.get("status") == "FAILED" and t["name"].split(".")[-1].lower() in (q.get("text") or "").lower()})[:3]
            add(t["name"], "failing", "medium", f"{u['failed']} quer{'y' if u['failed'] == 1 else 'ies'} on it failed: {'; '.join(e[:120] for e in errs if e) or 'see the history'}", f"{u['failed']} failed", {"errors": errs})
        if t["kind"] == "TABLE" and (t.get("rows") or 0) >= 1_000_000 and not t.get("partitioned"):
            add(t["name"], "unpartitioned", "medium", f"{t['rows']:,} rows and no partitioning or clustering key", f"{t['rows']:,} rows", {})
    for q in sorted(est["history"], key=lambda q: -(q.get("elapsed_ms") or 0))[:3]:
        if (q.get("elapsed_ms") or 0) >= 60_000:
            obj = next((n for n in use if n.split(".")[-1].lower() in (q.get("text") or "").lower()), "the warehouse")
            add(obj, "slow", "low", f"a query took {q['elapsed_ms'] / 1000:.0f} s: {(q.get('text') or '')[:120]}", f"{q['elapsed_ms'] / 1000:.0f} s", {"query": q})
    for r in est["routines"]:
        add(r["name"], "code", "low", f"{r['type'].lower()} with {r['lines']} line(s) of procedural code - Relay's agent drafts it as dbt models or target SQL", f"{r['lines']} lines", {})
    failed_jobs = [j for j in est["jobs"] if str(j.get("status") or "").upper() in ("FAILED", "FAILURE", "ERROR")]
    for name in sorted({j["job"] for j in failed_jobs}):
        js = [j for j in failed_jobs if j["job"] == name]
        add(name, "job", "medium", f"the scheduler job failed {len(js)} time(s): {(js[-1].get('error') or '')[:160]}", f"{len(js)} failed", {"runs": js[-5:]})
    return out


def wave_of(name: str) -> int:
    s, t = (name.split(".") + [""])[:2] if "." in name else ("", name)
    s, t = s.upper(), t.upper()
    if s == "STAGE" or t.startswith(("STG_", "DIM_")):
        return 1
    if t.startswith("FACT_") or s == "DW":
        return 2
    return 3


def decide(est: dict, found: list[dict], use: dict) -> list[dict]:
    fk = {}
    for f in found:
        fk.setdefault(f["object"], []).append(f)
    names = {t["name"] for t in est["tables"]}
    needed: dict[str, str] = {}                     # a table a kept view or piece of code reads is kept with it
    for v, sql in est["views"].items():
        for n in re.findall(r"(?i)\b(?:FROM|JOIN)\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)", sql or ""):
            needed.setdefault(n.upper(), f"read by the view {v}")
    for r in est["routines"]:
        for n in re.findall(r"(?i)\b(?:FROM|JOIN|INTO|UPDATE|MERGE\s+INTO)\s+([A-Za-z_]\w*\.[A-Za-z_]\w*)", r.get("text") or ""):
            needed.setdefault(n.upper(), f"used by {r['name']}")
    out = []
    for t in est["tables"]:
        fs = fk.get(t["name"], [])
        u = use.get(t["name"]) or {}
        base = re.sub(r"(_\d{4}|_BKP|_BAK|_BACKUP|_OLD|_COPY|_TMP|_TEMP)$", "", t["name"], flags=re.I)
        if base != t["name"] and base in names:
            d, into, why = "merge", base, f"a copy of {base}: point anything that still reads it at {base}"
        elif any(f["issue_kind"] == "legacy" for f in fs) or (any(f["issue_kind"] == "unused" for f in fs) and t["name"] not in needed):
            d, into, why = "retire", "", next(f["issue"] for f in fs if f["issue_kind"] in ("legacy", "unused"))
        elif t["name"] in needed and not u.get("queries"):
            d, into, why = "keep", "", f"not queried directly, but {needed[t['name']]}"
        else:
            d, into, why = "keep", "", f"{u.get('queries', 0)} quer{'y' if u.get('queries') == 1 else 'ies'} by {', '.join(u.get('users') or []) or 'its loads'}" if est["history"] else "in use"
        out.append({"id": t["name"], "object": t["name"], "type": t["kind"].lower(), "decision": d, "into": into, "why": why, "wave": wave_of(t["name"]) if t["kind"] == "TABLE" else 3,
                    "rows": t.get("rows"), "users": ", ".join(u.get("users") or [])[:200]})
    for v in sorted(set(est["views"]) - names):
        u = use.get(v) or {}
        out.append({"id": v, "object": v, "type": "view", "decision": "keep", "into": "", "why": f"a view read by {', '.join(u.get('users') or []) or 'reports'}", "wave": 3, "rows": None,
                    "users": ", ".join(u.get("users") or [])[:200]})
    for r in est["routines"]:
        out.append({"id": r["name"], "object": r["name"], "type": r["type"].lower(), "decision": "keep", "into": "", "why": f"{r['lines']} line(s): converted by Relay's agent", "wave": 3, "rows": None, "users": ""})
    return out


# ================================================================== convert: DDL, views, the load

TYPE_MAP = {
    "snowflake": {"int": "INTEGER", "bigint": "BIGINT", "dec": "NUMBER({p},{s})", "str": "VARCHAR({n})", "char": "CHAR({n})", "date": "DATE", "ts": "TIMESTAMP_NTZ", "bool": "BOOLEAN"},
    "databricks": {"int": "INT", "bigint": "BIGINT", "dec": "DECIMAL({p},{s})", "str": "STRING", "char": "STRING", "date": "DATE", "ts": "TIMESTAMP_NTZ", "bool": "BOOLEAN"},
    "bigquery": {"int": "INT64", "bigint": "INT64", "dec": "NUMERIC({p},{s})", "str": "STRING", "char": "STRING", "date": "DATE", "ts": "DATETIME", "bool": "BOOL"},
    "tsql": {"int": "INT", "bigint": "BIGINT", "dec": "DECIMAL({p},{s})", "str": "VARCHAR({n})", "char": "CHAR({n})", "date": "DATE", "ts": "DATETIME2(6)", "bool": "BIT"},
    "redshift": {"int": "INTEGER", "bigint": "BIGINT", "dec": "DECIMAL({p},{s})", "str": "VARCHAR({n4})", "char": "CHAR({n})", "date": "DATE", "ts": "TIMESTAMP", "bool": "BOOLEAN"},
}


def render(target: str, lt: str) -> str:
    m = TYPE_MAP[target]
    t = lt.lower()
    if t.startswith("dec"):
        p, s = t[4:-1].split(",")
        return m["dec"].format(p=min(int(p), 38), s=s)
    if t.startswith(("str", "char")):
        n = int(t[t.index("(") + 1:-1])
        return m["str" if t.startswith("str") else "char"].format(n=n, n4=min(n * 4, 65535))
    return m[t]


def table_ddl(t: dict, target: str) -> str:
    cols = ",\n    ".join(f"{c['name']} {render(target, c['logical'])}" for c in t["columns"])
    date_key = next((c["name"] for c in t["columns"] if c["name"].endswith("DATE_KEY")), None)
    fact = ".FACT_" in f".{t['name'].split('.')[-1]}" or t["name"].split(".")[-1].startswith("FACT_")
    if target == "snowflake":
        tail = f"\nCLUSTER BY ({date_key})" if fact and date_key else ""
        return f"CREATE OR REPLACE TABLE {t['name']} (\n    {cols}\n){tail}"
    if target == "databricks":
        tail = f"\nCLUSTER BY ({date_key})" if fact and date_key else ""
        return f"CREATE OR REPLACE TABLE {t['name']} (\n    {cols}\n){tail}"
    if target == "bigquery":
        tail = f"\nCLUSTER BY {date_key}" if fact and date_key else ""
        return f"CREATE OR REPLACE TABLE {t['name']} (\n    {cols}\n){tail}"
    if target == "redshift":
        key = (t.get("keys") or [None])[0]
        tail = (f"\nDISTKEY ({key})" if key and fact else "\nDISTSTYLE ALL" if not fact else "") + (f"\nSORTKEY ({date_key})" if date_key else "")
        return f"DROP TABLE IF EXISTS {t['name']};\nCREATE TABLE {t['name']} (\n    {cols}\n){tail}"
    tail = f"\nWITH (DISTRIBUTION = HASH({(t.get('keys') or [t['columns'][0]['name']])[0]}), CLUSTERED COLUMNSTORE INDEX)" if fact else ""
    return f"DROP TABLE IF EXISTS {t['name']};\nCREATE TABLE {t['name']} (\n    {cols}\n){tail}"


def view_sql(name: str, sql: str, source: str, target: str) -> tuple[str | None, str]:
    """(CREATE VIEW in the target's dialect | None, problem)."""
    import sqlglot
    read = {"ansi": None, "postgres": "postgres"}.get(source, source)
    odd = re.findall(r"(?i)\bROWNUM\b|\bCONNECT\s+BY\b|\(\+\)|\bQUALIFY\b|\bSAMPLE\b", sql or "")
    if odd and source in ("oracle", "teradata"):
        return None, f"uses {', '.join(sorted({o.upper() for o in odd}))}, which no rule rewrites for {target} - Relay's agent drafts it"
    try:
        body = sqlglot.transpile(sql, read=read, write=target, pretty=True)[0]
    except Exception as e:  # noqa: BLE001 - a view the parser does not read goes to the agent
        return None, f"the view does not parse as {source} SQL: {str(e).splitlines()[0][:160]}"
    return f"CREATE OR REPLACE VIEW {name} AS\n{body}", ""


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def inserts(table: str, rows: list[dict], cols: list[str], batch: int = 200) -> list[str]:
    out = []
    for i in range(0, len(rows), batch):
        vals = ",\n".join("(" + ", ".join(_lit(r.get(c, r.get(c.lower()))) for c in cols) + ")" for r in rows[i:i + batch])
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{vals}")
    return out


def replay(sql: str, source: str, target: str) -> str | None:
    """A history query in the target's dialect, when it is a plain SELECT (the same question asked of both)."""
    import sqlglot
    from sqlglot import exp
    if not re.match(r"(?is)\s*(SELECT|SEL|WITH)\b", sql or ""):
        return None
    try:
        tree = sqlglot.parse_one(re.sub(r"(?i)^\s*SEL\b", "SELECT", sql), read={"ansi": None}.get(source, source))
        if not isinstance(tree, (exp.Select, exp.Union)):
            return None
        return tree.sql(dialect=target)
    except Exception:  # noqa: BLE001
        return None
