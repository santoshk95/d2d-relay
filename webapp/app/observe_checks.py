"""Data observability (build-plan v2, P14) — the checks themselves: read-only readers over the places data lives,
the maths of every check against a learned baseline, and the readers of other tools' results.

Readers (all read-only; a connection's scope and enabled flag are honoured by the connector layer they call):
  DuckReader   a dashboard's extracts and uploads (DuckDB over output/projects/<id>/data/*.csv|*.parquet)
  SqlReader    a warehouse table through the Connector SDK's warehouse adapters (the guarded SELECT of phase 3:
               one statement, no DML / DDL, a row limit) — Snowflake, BigQuery, Fabric, Redshift, Athena, Oracle, and the
               Postgres / SQL Server adapters registered below for the lab engines
  SdkReader    an object of an SDK platform (the mock, any REST API) read with `read_object`; stats done here
Checks: freshness, volume, schema change, distribution, nulls, duplicates, reconciliation to source, lineage break
(the last one lives in observe.py because it walks the graph). Every threshold has a default in DEFAULTS, a
per-check override (Admin / builder, observe_settings) and a per-asset override (observe_checks.config); none is a
number hidden in the code path. Baselines are learned from the asset's own history, by weekday where the history
has it; what a person marked "expected" widens the band.
"""
from __future__ import annotations

import datetime as dt
import decimal
import math
import re
import statistics
import time
from pathlib import Path

CHECKS = ("freshness", "volume", "schema", "distribution", "nulls", "duplicates", "reconcile", "lineage", "quality")
CHECK_LABEL = {"freshness": "Freshness", "volume": "Volume", "schema": "Schema change", "distribution": "Distribution", "nulls": "Nulls",
               "duplicates": "Duplicate keys", "reconcile": "Reconciliation", "lineage": "Lineage break", "quality": "Quality test"}
# Tunable thresholds — the defaults; Admin › Checks & thresholds overrides per check, an asset overrides per asset.
DEFAULTS = {
    "freshness": {"cadence_h": None, "grace": 1.5, "date_column": None, "min_history": 3},
    "volume": {"drop_pct": 20, "rise_pct": 80, "sigma": 3.5, "min_history": 5, "window_days": 42, "weekday_min": 3},
    "schema": {"removed": "high", "added": "medium", "changed": "high"},
    "distribution": {"sigma": 3.0, "mean_shift_pct": 50, "topk": 8, "topk_shift": 0.3, "min_history": 3, "window_days": 42, "max_columns": 24},
    "nulls": {"null_jump_pp": 10, "key_null_max": 0, "min_history": 2},
    "duplicates": {"keys": None, "max_dupes": 0},
    "reconcile": {"tolerance_pct": 0.5, "columns": None},
    "lineage": {"missed_runs": 2},
    "quality": {},
}
THRESHOLD_HELP = {
    "freshness": {"cadence_h": "Expected hours between loads (blank: learned from history or the schedule)", "grace": "Late when older than cadence × grace", "date_column": "Date column whose maximum is the last load (blank: file time)"},
    "volume": {"drop_pct": "Rows fewer than usual by this % count as a drop", "rise_pct": "Rows more than usual by this % count as a surge", "sigma": "How unusual against the learned spread (robust z)", "min_history": "Observations needed before the check fires", "window_days": "Days of history in the baseline", "weekday_min": "Samples of the same weekday needed to use the weekday baseline"},
    "schema": {"removed": "Severity when a column disappears", "added": "Severity when a column appears", "changed": "Severity when a column changes type"},
    "distribution": {"sigma": "How unusual a mean must be against the learned spread", "mean_shift_pct": "Mean moved by at least this % of its usual value", "topk": "Categories compared for text columns", "topk_shift": "Share of rows that changed category (0–1)", "min_history": "Observations needed before the check fires", "window_days": "Days of history in the baseline", "max_columns": "Columns profiled per table"},
    "nulls": {"null_jump_pp": "Null share up by this many percentage points", "key_null_max": "Nulls allowed in a key column", "min_history": "Observations needed before the check fires"},
    "duplicates": {"keys": "Key columns (comma-separated; blank: unique columns learned from history)", "max_dupes": "Duplicate rows allowed"},
    "reconcile": {"tolerance_pct": "Allowed difference between target and source totals, in %", "columns": "Numeric columns to compare (blank: every column both sides share)"},
    "lineage": {"missed_runs": "Runs missed before a job counts as stopped"},
}
NUMERIC = ("int", "decimal")
WAREHOUSE_SQL = {"snowflake": "snowflake", "bigquery": "bigquery", "fabric": "tsql", "redshift": "redshift", "athena": "athena", "oracle_db": "oracle", "postgres": "postgres", "sqlserver": "tsql"}


def cfg_for(check: str, *overrides: dict | None) -> dict:
    """The effective thresholds: defaults, then each override in turn (None / '' leaves the earlier value)."""
    out = dict(DEFAULTS.get(check) or {})
    for o in overrides:
        for k, v in (o or {}).items():
            if k in out or check == "quality":
                out[k] = v if v not in ("", None) else out.get(k)
    return out


def kind_of(duck_type: str) -> str:
    t = str(duck_type or "").upper()
    if t.startswith(("DATE", "TIMESTAMP")):
        return "date"
    if t == "BOOLEAN" or t == "BOOL":
        return "bool"
    if t.startswith(("DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "REAL", "NUMBER")):
        return "decimal"
    if t.startswith(("TINYINT", "SMALLINT", "INT", "BIGINT", "HUGEINT", "UBIGINT", "UINTEGER", "USMALLINT")):
        return "int"
    return "string"


def kind_of_value(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, (float, decimal.Decimal)):
        return "decimal"
    if isinstance(v, (dt.date, dt.datetime)):
        return "date"
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", v):
        return "date"
    return "string"


def _num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


# ------------------------------------------------------------------ the aggregate SQL every SQL reader shares (DuckDB dialect)

def agg_sql(table_sql: str, cols: list[dict], max_columns: int = 24) -> tuple[str, list[dict]]:
    """One SELECT with the per-column aggregates; returns the SQL and the columns it covers (in order)."""
    parts, used = ["COUNT(*) AS n_rows"], []
    for i, c in enumerate(cols[:max_columns]):
        q = _q(c["name"])
        parts.append(f"COUNT({q}) AS c{i}_nn")
        if c["kind"] in NUMERIC:
            parts += [f"AVG(CAST({q} AS DOUBLE)) AS c{i}_mean", f"STDDEV_SAMP(CAST({q} AS DOUBLE)) AS c{i}_sd", f"MIN({q}) AS c{i}_min", f"MAX({q}) AS c{i}_max", f"SUM(CAST({q} AS DOUBLE)) AS c{i}_sum", f"COUNT(DISTINCT {q}) AS c{i}_nd"]
        elif c["kind"] == "date":
            parts += [f"MIN({q}) AS c{i}_min", f"MAX({q}) AS c{i}_max"]
        else:
            parts.append(f"COUNT(DISTINCT {q}) AS c{i}_nd")
        used.append(c)
    return f"SELECT {', '.join(parts)} FROM {table_sql}", used


def stats_from_row(row: dict, cols: list[dict]) -> dict:
    n = int(row.get("n_rows") or 0)
    out = {"rows": n, "columns": {}}
    for i, c in enumerate(cols):
        nn = int(row.get(f"c{i}_nn") or 0)
        s = {"kind": c["kind"], "nulls": n - nn, "null_pct": round(100.0 * (n - nn) / n, 3) if n else 0.0}
        if c["kind"] in NUMERIC:
            s.update(mean=_num(row.get(f"c{i}_mean")), sd=_num(row.get(f"c{i}_sd")), min=_num(row.get(f"c{i}_min")), max=_num(row.get(f"c{i}_max")), sum=_num(row.get(f"c{i}_sum")))
            nd = row.get(f"c{i}_nd")
            s["distinct"] = int(nd) if nd is not None else None
            s["unique"] = bool(n and nd is not None and int(nd) == nn == n)
        elif c["kind"] == "date":
            s.update(min=str(row.get(f"c{i}_min") or "")[:19] or None, max=str(row.get(f"c{i}_max") or "")[:19] or None)
        else:
            nd = row.get(f"c{i}_nd")
            s["distinct"] = int(nd) if nd is not None else None
            s["unique"] = bool(n and nd is not None and int(nd) == nn == n)
        out["columns"][c["name"]] = s
    return out


def py_stats(rows: list[dict], cols: list[dict], topk: int = 8) -> dict:
    """The same statistics computed in Python, for platforms read as records (the SDK's mock / REST adapters)."""
    n = len(rows)
    out = {"rows": n, "columns": {}}
    for c in cols:
        vals = [r.get(c["name"]) for r in rows]
        nn = [v for v in vals if v is not None and v != ""]
        s = {"kind": c["kind"], "nulls": n - len(nn), "null_pct": round(100.0 * (n - len(nn)) / n, 3) if n else 0.0}
        if c["kind"] in NUMERIC:
            nums = [x for x in (_num(v) for v in nn) if x is not None]
            s.update(mean=statistics.fmean(nums) if nums else None, sd=statistics.stdev(nums) if len(nums) > 1 else 0.0, min=min(nums) if nums else None, max=max(nums) if nums else None, sum=sum(nums) if nums else None,
                     distinct=len(set(nums)), unique=bool(n and len(set(nums)) == len(nn) == n))
        elif c["kind"] == "date":
            ss = sorted(str(v) for v in nn)
            s.update(min=ss[0][:19] if ss else None, max=ss[-1][:19] if ss else None)
        else:
            counts: dict[str, int] = {}
            for v in nn:
                counts[str(v)] = counts.get(str(v), 0) + 1
            s["distinct"] = len(counts)
            s["unique"] = bool(n and len(counts) == len(nn) == n)
            s["top"] = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:topk]
        out["columns"][c["name"]] = s
    return out


def dupes_py(rows: list[dict], keys: list[str]) -> int:
    seen = set()
    for r in rows:
        seen.add(tuple(str(r.get(k)) for k in keys))
    return len(rows) - len(seen)


# ------------------------------------------------------------------ readers

class ReadError(Exception):
    pass


class Reader:
    label = "reader"
    sql = False

    def columns(self) -> list[dict]:          # [{name, kind}]
        raise ReadError("not readable")

    def count(self) -> int:
        raise ReadError("not readable")

    def stats(self, cols: list[dict], topk: int = 8, max_columns: int = 24) -> dict:
        raise ReadError("not readable")

    def dupes(self, keys: list[str]) -> int:
        raise ReadError("not readable")

    def loaded_at(self) -> float | None:
        return None

    def close(self) -> None:
        pass


class DuckReader(Reader):
    """A dashboard's data file (CSV upload or Parquet extract) through genbi_kit.data: raw views by file name."""
    label = "dashboard extract"
    sql = True
    _cons: dict[str, object] = {}

    def __init__(self, workdir: Path, file: str):
        from genbi_kit import data as data_mod
        self.workdir, self.file = Path(workdir), file
        key = str(self.workdir)
        if key not in self._cons:
            self._cons[key] = data_mod.connect(self.workdir)
        self.con = self._cons[key]
        self.view = data_mod.raw_name(Path(file))
        if not (self.workdir / "data" / file).exists():
            raise ReadError(f"{file} is not in the dashboard's data folder any more")

    @classmethod
    def reset(cls) -> None:
        for con in cls._cons.values():
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        cls._cons.clear()

    def run(self, sql: str) -> list[dict]:
        try:
            cur = self.con.execute(sql)
            names = [c[0] for c in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]
        except Exception as e:  # noqa: BLE001 - duckdb.Error and friends
            raise ReadError(str(e).splitlines()[0][:300]) from e

    def columns(self) -> list[dict]:
        return [{"name": r["column_name"], "kind": kind_of(r["column_type"])} for r in self.run(f"DESCRIBE {_q(self.view)}")]

    def count(self) -> int:
        return int(self.run(f"SELECT COUNT(*) AS n FROM {_q(self.view)}")[0]["n"])

    def stats(self, cols: list[dict], topk: int = 8, max_columns: int = 24) -> dict:
        sql, used = agg_sql(_q(self.view), cols, max_columns)
        out = stats_from_row(self.run(sql)[0], used)
        for c in used:
            s = out["columns"][c["name"]]
            if c["kind"] == "string" and s.get("distinct") is not None and 0 < s["distinct"] <= 200:
                s["top"] = [[str(r["v"]), int(r["n"])] for r in self.run(f"SELECT {_q(c['name'])} AS v, COUNT(*) AS n FROM {_q(self.view)} WHERE {_q(c['name'])} IS NOT NULL GROUP BY 1 ORDER BY n DESC, v LIMIT {int(topk)}")]
        return out

    def dupes(self, keys: list[str]) -> int:
        ks = ", ".join(_q(k) for k in keys)
        r = self.run(f"SELECT COUNT(*) - COUNT(*) FILTER (WHERE rn = 1) AS d FROM (SELECT ROW_NUMBER() OVER (PARTITION BY {ks}) AS rn FROM {_q(self.view)}) t")
        return int(r[0]["d"] or 0)

    def max_of(self, col: str):
        return self.run(f"SELECT MAX({_q(col)}) AS m FROM {_q(self.view)}")[0]["m"]

    def loaded_at(self) -> float | None:
        try:
            from . import connectors
            m = connectors.manifest(self.workdir).get(self.file) or {}
            if m.get("extracted"):
                return float(m["extracted"])
            return (self.workdir / "data" / self.file).stat().st_mtime
        except OSError:
            return None


class SqlReader(Reader):
    """A warehouse object through the guarded live query of phase 3 (read-only, one SELECT, a row limit); the SQL is
    written once (DuckDB dialect) and transpiled to the warehouse's own by sqlglot."""
    label = "warehouse"
    sql = True

    def __init__(self, connection: dict, obj: str, who: str = "observe"):
        from . import connectors
        self.c, self.obj, self.who = connection, obj, who
        self.kind = connection["kind"]
        self.dialect = (connectors.KINDS.get(self.kind) or {}).get("dialect") or WAREHOUSE_SQL.get(self.kind) or "duckdb"
        self.table = connectors.quote(self.kind, obj)
        self._cols: list[dict] | None = None

    def run(self, sql_duck: str, lower: bool = True) -> list[dict]:
        """`lower`: the aliases are ours (n_rows, c0_mean, …) and some warehouses upper-case unquoted aliases."""
        import sqlglot

        from . import connectors
        try:
            sql = sqlglot.transpile(sql_duck, read="duckdb", write=self.dialect)[0] if self.dialect != "duckdb" else sql_duck
        except sqlglot.errors.SqlglotError as e:
            raise ReadError(f"The check's SQL does not translate to {self.dialect}: {str(e)[:200]}") from e
        try:
            rows = connectors.query(self.c, sql, self.who)["rows"]
        except connectors.ConnectorError as e:
            raise ReadError(str(e)[:300]) from e
        except Exception as e:  # noqa: BLE001 - the driver's own error, shown plainly
            raise ReadError(str(e).splitlines()[0][:300]) from e
        return [{k.lower(): v for k, v in r.items()} for r in rows] if lower else rows

    def _table_duck(self) -> str:
        parts = [p.strip().strip('"`[]') for p in self.obj.split(".")]
        return ".".join(_q(p) for p in parts)

    def columns(self) -> list[dict]:
        if self._cols is None:
            rows = self.run(f"SELECT * FROM {self._table_duck()} LIMIT 50", lower=False)
            names = list(rows[0].keys()) if rows else []
            out = []
            for n in names:
                kinds = [k for k in (kind_of_value(r.get(n)) for r in rows) if k]
                out.append({"name": n, "kind": max(set(kinds), key=kinds.count) if kinds else "string"})
            self._cols = out
        return list(self._cols)

    def count(self) -> int:
        return int(self.run(f"SELECT COUNT(*) AS n FROM {self._table_duck()}")[0]["n"])

    def stats(self, cols: list[dict], topk: int = 8, max_columns: int = 24) -> dict:
        sql, used = agg_sql(self._table_duck(), cols, max_columns)
        out = stats_from_row(self.run(sql)[0], used)
        for c in used:
            s = out["columns"][c["name"]]
            if c["kind"] == "string" and s.get("distinct") is not None and 0 < s["distinct"] <= 200:
                s["top"] = [[str(r["v"]), int(r["n"])] for r in self.run(f"SELECT {_q(c['name'])} AS v, COUNT(*) AS n FROM {self._table_duck()} WHERE {_q(c['name'])} IS NOT NULL GROUP BY {_q(c['name'])} ORDER BY n DESC, v LIMIT {int(topk)}")]
        return out

    def dupes(self, keys: list[str]) -> int:
        if self.dialect == "oracle":         # Oracle has no CONCAT_WS: the extra rows of every key group that repeats (the same number)
            cols = ", ".join(_q(k) for k in keys)
            r = self.run(f"SELECT COALESCE(SUM(c - 1), 0) AS d FROM (SELECT COUNT(*) AS c FROM {self._table_duck()} GROUP BY {cols} HAVING COUNT(*) > 1) t")
            return int(r[0]["d"] or 0)
        r = self.run(f"SELECT COUNT(*) AS n, COUNT(DISTINCT k) AS d FROM (SELECT CONCAT_WS('|', {', '.join('CAST(' + _q(k) + ' AS VARCHAR)' for k in keys)}) AS k FROM {self._table_duck()}) t")
        return int(r[0]["n"] or 0) - int(r[0]["d"] or 0)

    def max_of(self, col: str):
        return self.run(f"SELECT MAX({_q(col)}) AS m FROM {self._table_duck()}")[0]["m"]


class SdkReader(Reader):
    """An object of an SDK platform (the mock, a REST API): records read through connectors.read_object; the
    statistics are computed here. Row counts are what the platform reports."""
    label = "platform"

    def __init__(self, connection: dict, obj: str, who: str = "observe", limit: int = 5000):
        self.c, self.obj, self.who, self.limit = connection, obj, who, limit
        self._data: dict | None = None

    def _read(self) -> dict:
        from . import connectors
        if self._data is None:
            try:
                self._data = connectors.read_object(self.c, self.obj, self.who, self.limit)
            except connectors.ConnectorError as e:
                raise ReadError(str(e)[:300]) from e
            except Exception as e:  # noqa: BLE001
                raise ReadError(str(e).splitlines()[0][:300]) from e
        return self._data

    def columns(self) -> list[dict]:
        d = self._read()
        out = []
        for n in d.get("columns") or []:
            kinds = [k for k in (kind_of_value(r.get(n)) for r in d.get("rows") or []) if k]
            out.append({"name": n, "kind": max(set(kinds), key=kinds.count) if kinds else "string"})
        return out

    def count(self) -> int:
        d = self._read()
        return int(d.get("row_count") if d.get("row_count") is not None else len(d.get("rows") or []))

    def stats(self, cols: list[dict], topk: int = 8, max_columns: int = 24) -> dict:
        out = py_stats(self._read().get("rows") or [], cols[:max_columns], topk)
        out["rows"] = self.count()
        return out

    def dupes(self, keys: list[str]) -> int:
        return dupes_py(self._read().get("rows") or [], keys)

    def max_of(self, col: str):
        vals = [r.get(col) for r in self._read().get("rows") or [] if r.get(col) not in (None, "")]
        return max(vals, key=str) if vals else None


# ------------------------------------------------------------------ the lab engines as SDK warehouse adapters (Postgres, SQL Server)

def register_lab_engines() -> None:
    """Postgres and SQL Server as read-only warehouse kinds behind the same guarded query (P14's engine tests;
    also usable for a developer database). Registered at import; nothing in connectors.py changes."""
    from . import connectors
    from . import connectors_sdk as sdk

    class _Engine(sdk.Adapter):
        """An SDK adapter whose reads are the guarded live query of phase 3 (the dialect makes `query` work); the
        object list comes from information_schema."""
        sql, can_write, category, signin = True, False, "warehouse", ["password"]

        def __init__(self, kind, spec):
            self.kind, self.label, self.dialect, self.fields, self.secrets = kind, spec["label"], spec["dialect"], list(spec["fields"]), dict(spec["secrets"])

        def test(self, c):
            connectors.query(c, "SELECT 1 AS ok", c.get("_who"))
            return {"ok": True, "sees": "a trivial query ran"}

        def list_objects(self, c, search=""):
            s = search.strip().lower().replace("'", "")
            sql = (f"SELECT table_schema || '.' || table_name AS object, table_type FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND lower(table_name) LIKE '%{s}%' ORDER BY 1 LIMIT 500" if self.dialect == "postgres"
                   else f"SELECT TOP 500 table_schema + '.' + table_name AS object, table_type FROM INFORMATION_SCHEMA.TABLES WHERE table_schema NOT IN ('sys', 'INFORMATION_SCHEMA') AND lower(table_name) LIKE '%{s}%' ORDER BY 1")
            return [{"object": list(r.values())[0], "type": list(r.values())[1]} for r in connectors.query(c, sql, c.get("_who"))["rows"]]

        def read(self, c, obj, limit=100):
            return connectors.query(c, f"SELECT * FROM {connectors.quote(c['kind'], obj)}", c.get("owner_id"))

    specs = {
        "postgres": {"label": "PostgreSQL", "dialect": "postgres", "auth": ["password"], "secrets": {"password": ["password"]},
                     "fields": [("host", "Host", True), ("port", "Port (5432)", False), ("database", "Database", True), ("user", "User name", True)]},
        "sqlserver": {"label": "SQL Server", "dialect": "tsql", "auth": ["password"], "secrets": {"password": ["password"]},
                      "fields": [("host", "Host", True), ("port", "Port (1433)", False), ("database", "Database", True), ("user", "User name", True)]},
    }
    for kind, spec in specs.items():
        if kind in connectors.KINDS:
            continue
        connectors.KINDS[kind] = {**spec, "category": "warehouse", "sdk": True}
        sdk.register(_Engine(kind, spec))
    if not getattr(connectors, "_p14_engines", False):
        connectors._p14_engines = True
        orig_open = connectors._open

        def _open(c: dict):
            k, cfg = c["kind"], c["config"]
            if k == "postgres":
                import psycopg
                return psycopg.connect(host=cfg["host"], port=int(cfg.get("port") or 5432), dbname=cfg["database"], user=cfg["user"],
                                       password=connectors._secret(c, "password"), connect_timeout=15, options="-c default_transaction_read_only=on")
            if k == "sqlserver":
                import pyodbc
                return pyodbc.connect(f"Driver={{ODBC Driver 18 for SQL Server}};Server={cfg['host']},{int(cfg.get('port') or 1433)};Database={cfg['database']};"
                                      f"Uid={cfg['user']};Pwd={connectors._secret(c, 'password')};Encrypt=yes;TrustServerCertificate=yes", timeout=15)
            return orig_open(c)
        connectors._open = _open


# ------------------------------------------------------------------ baselines

def _median(xs: list[float]) -> float:
    return float(statistics.median(xs)) if xs else 0.0


def _mad(xs: list[float], med: float) -> float:
    return float(statistics.median([abs(x - med) for x in xs])) if xs else 0.0


def robust_z(value: float, med: float, mad: float) -> float | None:
    if mad <= 0:
        return None
    return (value - med) / (1.4826 * mad)


def weekday(ts: float) -> int:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).weekday()


def baseline(history: list[tuple[float, float]], now: float, window_days: int, weekday_min: int) -> dict:
    """Median and spread of a measure from (ts, value) history: by weekday when that weekday has enough samples
    (seasonality), else over every day of the window. Values are the history only — never the value under test."""
    hist = [(t, v) for t, v in history if v is not None and t >= now - window_days * 86400]
    same = [v for t, v in hist if weekday(t) == weekday(now)]
    if len(same) >= weekday_min:
        xs, basis = same, f"same weekday ({dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime('%A')}s)"
    else:
        xs, basis = [v for _, v in hist], "all days"
    med = _median(xs)
    return {"median": med, "mad": _mad(xs, med), "n": len(xs), "basis": basis, "min": min(xs) if xs else None, "max": max(xs) if xs else None}


# ------------------------------------------------------------------ the checks (pure functions → a finding or None)

def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _when(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d %b %H:%M") if t else "—"


def _age(seconds: float) -> str:
    return f"{seconds / 60:.0f} min" if seconds < 5400 else f"{seconds / 3600:.1f} h" if seconds < 2 * 86400 else f"{seconds / 86400:.1f} days"


def finding(check: str, severity: str, title: str, what: str, measured: dict, expected: dict, rows: list, column: str | None = None, cause: str | None = None) -> dict:
    return {"check": check, "severity": severity, "title": title[:200], "what": what[:300], "measured": measured, "expected": expected, "rows": rows[:12], "column": column, "cause": cause}


def check_freshness(now: float, loaded_at: float | None, max_date: float | None, cfg: dict, learned_cadence_h: float | None, label: str, expected_ages: list[float] | None = None) -> dict | None:
    """Late when the last load (or the newest date in the data) is older than the cadence × grace. The cadence is
    the asset's own setting, else the learned median gap between loads, else the schedule the caller passed in."""
    cadence = cfg.get("cadence_h") or learned_cadence_h
    last = max_date if cfg.get("date_column") and max_date else loaded_at
    if not cadence or not last:
        return None
    age = now - last
    allowed = float(cadence) * 3600 * float(cfg.get("grace") or 1.5)
    if age <= allowed:
        return None
    if expected_ages and age <= max(expected_ages):
        return None
    late = age - float(cadence) * 3600
    return finding("freshness", "high", f"{label} is {_age(late)} late", f"last load {_when(last)}; expected every {_fmt(float(cadence))} h",
                   {"last_load": last, "age_h": round(age / 3600, 1)}, {"cadence_h": float(cadence), "grace": cfg.get("grace"), "by": last + float(cadence) * 3600},
                   [["Last load", _when(last), f"by {_when(last + float(cadence) * 3600)}"], ["Age", _age(age), f"≤ {_fmt(float(cadence) * float(cfg.get('grace') or 1.5))} h"]],
                   cause="The load that feeds this did not run, or ran and brought nothing new.")


def check_volume(count: int, base: dict, cfg: dict, label: str, expected_values: list[float] | None = None) -> dict | None:
    if base["n"] < int(cfg.get("min_history") or 5) or base["median"] <= 0:
        return None
    med, mad = base["median"], base["mad"]
    change = 100.0 * (count - med) / med
    z = robust_z(count, med, mad)
    drop, rise = float(cfg.get("drop_pct") or 20), float(cfg.get("rise_pct") or 80)
    sigma = float(cfg.get("sigma") or 3.5)
    unusual = z is None or abs(z) >= sigma
    if change <= -drop and unusual:
        if expected_values and count >= min(expected_values):
            return None
        return finding("volume", "high", f"{label} lost {abs(change):.0f} % of its rows", f"{_fmt(count)} rows vs {_fmt(round(med))} usual ({base['basis']})",
                       {"rows": count, "change_pct": round(change, 1), "z": None if z is None else round(z, 1)}, {"median": med, "mad": mad, "basis": base["basis"], "n": base["n"], "drop_pct": drop},
                       [["Rows", _fmt(count), f"{_fmt(round(med))} ± {_fmt(round(1.4826 * mad * sigma))} ({base['basis']}, {base['n']} obs)"]],
                       cause="Fewer rows arrived than on a usual day: a partial load, a filter, or a source that sent less.")
    if change >= rise and unusual:
        if expected_values and count <= max(expected_values):
            return None
        return finding("volume", "medium", f"{label} has {change:.0f} % more rows than usual", f"{_fmt(count)} rows vs {_fmt(round(med))} usual ({base['basis']})",
                       {"rows": count, "change_pct": round(change, 1), "z": None if z is None else round(z, 1)}, {"median": med, "mad": mad, "basis": base["basis"], "n": base["n"], "rise_pct": rise},
                       [["Rows", _fmt(count), f"{_fmt(round(med))} ({base['basis']}, {base['n']} obs)"]], cause="A double load or a source that sent more than usual.")
    return None


def check_schema(cols_now: list[dict], cols_last: list[dict] | None, cfg: dict, label: str) -> dict | None:
    if cols_last is None:
        return None
    now_map = {c["name"]: c["kind"] for c in cols_now}
    last_map = {c["name"]: c["kind"] for c in cols_last}
    added = [n for n in now_map if n not in last_map]
    removed = [n for n in last_map if n not in now_map]
    changed = [(n, last_map[n], now_map[n]) for n in now_map if n in last_map and now_map[n] != last_map[n]]
    if not (added or removed or changed):
        return None
    sev = "low"
    for k, items in (("removed", removed), ("changed", changed), ("added", added)):
        if items and {"high": 3, "medium": 2, "low": 1}[cfg.get(k) or DEFAULTS["schema"][k]] > {"high": 3, "medium": 2, "low": 1}[sev]:
            sev = cfg.get(k) or DEFAULTS["schema"][k]
    bits = ([f"{len(removed)} column{'s' if len(removed) != 1 else ''} removed ({', '.join(removed[:4])})"] if removed else []) + \
           ([f"{len(added)} added ({', '.join(added[:4])})"] if added else []) + ([f"{len(changed)} changed type ({', '.join(n for n, _, _ in changed[:4])})"] if changed else [])
    rows = [[n, "missing", last_map[n]] for n in removed] + [[n, now_map[n], "not there before"] for n in added] + [[n, b, a] for n, a, b in changed]
    first = (removed or [n for n, _, _ in changed] or added)[0]
    return finding("schema", sev, f"Schema of {label} changed: " + "; ".join(bits), f"{len(now_map)} columns now, {len(last_map)} before", {"columns": sorted(now_map)}, {"columns": sorted(last_map)},
                   rows, column=first, cause="The source changed its shape: a renamed, dropped or new column breaks the mappings downstream unless they are updated.")


def _tv_distance(top_now: list, top_base: list) -> float:
    a = {str(k): float(v) for k, v in (top_now or [])}
    b = {str(k): float(v) for k, v in (top_base or [])}
    sa, sb = sum(a.values()) or 1.0, sum(b.values()) or 1.0
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) / sa - b.get(k, 0) / sb) for k in keys)


def check_distribution(stats_now: dict, history: list[tuple[float, dict]], cfg: dict, now: float, label: str, expected_shifts: dict | None = None) -> list[dict]:
    """Numeric columns: today's mean against the learned means (robust z and a relative shift); text columns: how
    much of the top-k category mix moved. One finding per column that moved."""
    out = []
    min_hist = int(cfg.get("min_history") or 3)
    hist = [(t, s) for t, s in history if t >= now - int(cfg.get("window_days") or 42) * 86400]
    if len(hist) < min_hist:
        return out
    for col, s in (stats_now.get("columns") or {}).items():
        past = [(t, (h.get("columns") or {}).get(col)) for t, h in hist]
        past = [(t, p) for t, p in past if p]
        if len(past) < min_hist:
            continue
        exp_shift = (expected_shifts or {}).get(col)
        if s["kind"] in NUMERIC and s.get("mean") is not None:
            means = [p["mean"] for _, p in past if p.get("mean") is not None]
            if len(means) < min_hist:
                continue
            med, mad = _median(means), _mad(means, _median(means))
            shift = abs(s["mean"] - med) / max(abs(med), 1e-9) * 100
            z = robust_z(s["mean"], med, mad)
            if shift >= float(cfg.get("mean_shift_pct") or 50) and (z is None or abs(z) >= float(cfg.get("sigma") or 3)):
                if exp_shift is not None and shift <= exp_shift:
                    continue
                out.append(finding("distribution", "medium", f"{col} in {label} moved: mean {_fmt(s['mean'])} vs {_fmt(med)} usual", f"{shift:.0f} % shift of the mean ({len(means)} earlier observations)",
                                   {"mean": s["mean"], "sd": s.get("sd"), "shift_pct": round(shift, 1), "z": None if z is None else round(z, 1)}, {"mean_median": med, "mad": mad, "n": len(means)},
                                   [[f"Mean of {col}", _fmt(s["mean"]), _fmt(med)], [f"Spread of {col}", _fmt(s.get("sd")), _fmt(_median([p.get("sd") or 0 for _, p in past]))], [f"Min / max", f"{_fmt(s.get('min'))} / {_fmt(s.get('max'))}", f"{_fmt(min(p.get('min') for _, p in past if p.get('min') is not None) if any(p.get('min') is not None for _, p in past) else None)} / {_fmt(max(p.get('max') for _, p in past if p.get('max') is not None) if any(p.get('max') is not None for _, p in past) else None)}"]],
                                   column=col, cause="The values themselves changed — a unit or scale mix-up, a different population, or a source posting differently."))
        elif s["kind"] == "string" and s.get("top"):
            tops = [p.get("top") for _, p in past if p.get("top")]
            if len(tops) < min_hist:
                continue
            dists = [_tv_distance(s["top"], t) for t in tops]
            d = _median(dists)
            if d >= float(cfg.get("topk_shift") or 0.3):
                if exp_shift is not None and d <= exp_shift:
                    continue
                base_top = tops[-1]
                out.append(finding("distribution", "medium", f"Mix of {col} in {label} changed ({d * 100:.0f} % of rows moved category)", f"top categories: {', '.join(k for k, _ in s['top'][:4])}",
                                   {"top": s["top"][:8], "shift": round(d, 3)}, {"top": base_top[:8], "n": len(tops)},
                                   [[k, _fmt(v), _fmt(dict((str(a), b) for a, b in base_top).get(str(k), 0))] for k, v in s["top"][:8]], column=col,
                                   cause="The category mix moved — a new code, a renamed value, or one group missing from the load."))
    return out


def check_nulls(stats_now: dict, history: list[tuple[float, dict]], cfg: dict, now: float, label: str, keys: list[str], expected_pp: dict | None = None) -> list[dict]:
    out = []
    min_hist = int(cfg.get("min_history") or 2)
    hist = [s for t, s in history if t >= now - 42 * 86400]
    for col, s in (stats_now.get("columns") or {}).items():
        if col in keys and s.get("nulls", 0) > int(cfg.get("key_null_max") or 0):
            out.append(finding("nulls", "high", f"Key {col} in {label} has {_fmt(s['nulls'])} empty values", f"{s['null_pct']:.1f} % of rows", {"nulls": s["nulls"], "null_pct": s["null_pct"]}, {"key_null_max": cfg.get("key_null_max") or 0},
                               [[f"Empty {col}", _fmt(s["nulls"]), "0 (key column)"]], column=col, cause="Rows arrived without their key: a join upstream lost its match or the source left the field blank."))
            continue
        past = [(h.get("columns") or {}).get(col, {}).get("null_pct") for h in hist]
        past = [p for p in past if p is not None]
        if len(past) < min_hist:
            continue
        med = _median(past)
        jump = s["null_pct"] - med
        if jump >= float(cfg.get("null_jump_pp") or 10):
            if expected_pp and col in expected_pp and jump <= expected_pp[col]:
                continue
            out.append(finding("nulls", "medium", f"{col} in {label} is {s['null_pct']:.0f} % empty ({med:.0f} % usual)", f"up {jump:.0f} percentage points", {"null_pct": s["null_pct"], "nulls": s["nulls"]}, {"null_pct_median": med, "n": len(past)},
                               [[f"Empty {col}", f"{s['null_pct']:.1f} %", f"{med:.1f} % ({len(past)} obs)"]], column=col, cause="A field stopped being filled: a mapping dropped it or the source changed."))
    return out


def check_duplicates(dupes: int, keys: list[str], cfg: dict, label: str, rows_total: int) -> dict | None:
    if not keys or dupes <= int(cfg.get("max_dupes") or 0):
        return None
    return finding("duplicates", "high", f"{_fmt(dupes)} duplicate key{'s' if dupes != 1 else ''} in {label}", f"on {', '.join(keys)} across {_fmt(rows_total)} rows", {"duplicates": dupes, "keys": keys}, {"max_dupes": cfg.get("max_dupes") or 0},
                   [[f"Duplicate rows on {', '.join(keys)}", _fmt(dupes), str(cfg.get("max_dupes") or 0)]], column=keys[0], cause="The same key loaded twice: a re-run without a delete, or a merge that appended.")


def check_reconcile(target: dict, source: dict, cfg: dict, label: str, source_label: str) -> dict | None:
    """Totals of the target (the extract / mart) against its source along the lineage: row count and the sum of every
    numeric column both sides share, within a tolerance."""
    tol = float(cfg.get("tolerance_pct") or 0.5)
    rows, worst = [], 0.0
    pairs = [("rows", target.get("rows"), source.get("rows"))]
    tcols = {k.lower(): (k, v) for k, v in (target.get("columns") or {}).items() if v.get("kind") in NUMERIC and v.get("sum") is not None}
    scols = {k.lower(): (k, v) for k, v in (source.get("columns") or {}).items() if v.get("kind") in NUMERIC and v.get("sum") is not None}
    want = [c.strip().lower() for c in str(cfg.get("columns") or "").split(",") if c.strip()] or sorted(set(tcols) & set(scols))
    for k in want:
        if k in tcols and k in scols:
            pairs.append((f"sum of {tcols[k][0]}", tcols[k][1]["sum"], scols[k][1]["sum"]))
    for name, t, s in pairs:
        if t is None or s is None:
            continue
        diff = abs(float(t) - float(s)) / max(abs(float(s)), 1e-9) * 100
        rows.append([name, _fmt(t), f"{_fmt(s)} ({source_label})"])
        worst = max(worst, diff)
    if worst <= tol:
        return None
    bad = [r for r in rows if r]
    return finding("reconcile", "high", f"{label} differs from {source_label} by {worst:.1f} %", f"tolerance {tol} %: " + "; ".join(f"{r[0]} {r[1]} vs {r[2]}" for r in bad[:3]),
                   {"worst_diff_pct": round(worst, 3), "rows": target.get("rows")}, {"tolerance_pct": tol, "source_rows": source.get("rows")}, rows,
                   cause="The target no longer agrees with its source: a stale extract, a filter, a lost partition or a changed calculation in between.")


def learned_cadence_h(load_times: list[float], min_history: int = 3) -> float | None:
    """The median gap between distinct observed loads, in hours."""
    ts = sorted(set(round(t) for t in load_times if t))
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b - a > 60]
    if len(gaps) + 1 < min_history:
        return None
    return round(_median(gaps) / 3600, 2)


def learned_keys(history_stats: list[dict], cols_now: list[dict]) -> list[str]:
    """Key columns: the columns that were unique in every earlier observation (and look like keys)."""
    if not history_stats:
        return []
    names = [c["name"] for c in cols_now]
    out = []
    for n in names:
        rows = [(h.get("columns") or {}).get(n) for h in history_stats]
        rows = [r for r in rows if r]
        if rows and sum(1 for r in rows if r.get("unique")) >= 0.8 * len(rows) and (re.search(r"(^|_)(id|key|no|number|code)$", n.lower()) or re.search(r"(id|key)$", n.lower())):
            out.append(n)
    return out[:3]


# ------------------------------------------------------------------ results of other tools → incidents of the same shape

TOOLS = {"openlineage": "OpenLineage", "dbt": "dbt tests", "ge": "Great Expectations", "soda": "Soda", "webhook": "Webhook",
         "montecarlo": "Monte Carlo", "bigeye": "Bigeye", "acceldata": "Acceldata", "metaplane": "Metaplane", "elementary": "Elementary", "datadog": "Datadog"}
_CHECK_WORDS = [("fresh", "freshness"), ("recent", "freshness"), ("stale", "freshness"), ("row_count", "volume"), ("rowcount", "volume"), ("volume", "volume"), ("count", "volume"),
                ("schema", "schema"), ("column_to_exist", "schema"), ("columns_to_match", "schema"), ("not_null", "nulls"), ("missing", "nulls"), ("null", "nulls"),
                ("unique", "duplicates"), ("duplicate", "duplicates"), ("reconcil", "reconcile"), ("match", "reconcile"), ("mean", "distribution"), ("median", "distribution"),
                ("stdev", "distribution"), ("stddev", "distribution"), ("quantile", "distribution"), ("percentile", "distribution"), ("between", "distribution"), ("value_set", "distribution"),
                ("accepted_values", "distribution"), ("in_set", "distribution"), ("distinct", "distribution"), ("avg", "distribution"), ("min", "distribution"), ("max", "distribution"), ("invalid", "distribution"),
                ("relationships", "lineage"), ("referential", "lineage")]


def check_from_name(name: str) -> str:
    n = (name or "").lower()
    for word, check in _CHECK_WORDS:
        if word in n:
            return check
    return "quality"


def _sev(v: str | None, default: str = "medium") -> str:
    v = (v or "").lower()
    return "high" if v in ("high", "critical", "error", "fail", "p1", "sev1", "sev-1", "1") else "low" if v in ("low", "warn", "warning", "info", "p3", "p4") else default if v in ("", "medium", "p2") else default


def _ts(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e11 else 1)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _item(tool: str, asset: str, check: str, title: str, *, system: str | None = None, column: str | None = None, severity: str = "medium", measured=None, expected=None,
          when: float | None = None, external_id: str | None = None, kind: str = "table", rows: list | None = None) -> dict:
    return {"tool": tool, "asset": str(asset)[:300], "system": (system or "")[:200], "kind": kind, "check": check if check in CHECKS else "quality", "title": str(title)[:200], "column": column,
            "severity": severity, "measured": measured if isinstance(measured, dict) else ({"value": measured} if measured is not None else {}),
            "expected": expected if isinstance(expected, dict) else ({"value": expected} if expected is not None else {}), "when": when, "external_id": external_id, "rows": rows or []}


def parse_openlineage(payload) -> list[dict]:
    events = payload if isinstance(payload, list) else (payload.get("events") if isinstance(payload, dict) and isinstance(payload.get("events"), list) else [payload])
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        job, run = ev.get("job") or {}, ev.get("run") or {}
        when = _ts(ev.get("eventTime"))
        if str(ev.get("eventType") or "").upper() in ("FAIL", "ABORT"):
            msg = ((run.get("facets") or {}).get("errorMessage") or {}).get("message") or ev.get("eventType")
            out.append(_item("openlineage", job.get("name") or "job", "lineage", f"{job.get('name') or 'A job'} {str(ev.get('eventType')).lower()}ed: {str(msg)[:120]}", system=job.get("namespace"), severity="high",
                             measured={"status": ev.get("eventType"), "message": str(msg)[:300]}, when=when, external_id=run.get("runId"), kind="job"))
        for ds in (ev.get("inputs") or []) + (ev.get("outputs") or []):
            facets = ds.get("facets") or ds.get("inputFacets") or ds.get("outputFacets") or {}
            for a in ((facets.get("dataQualityAssertions") or {}).get("assertions") or []):
                if a.get("success") is False:
                    chk = check_from_name(a.get("assertion") or "")
                    out.append(_item("openlineage", ds.get("name") or "dataset", chk, f"{ds.get('name')}: assertion {a.get('assertion')} failed" + (f" on {a['column']}" if a.get("column") else ""),
                                     system=ds.get("namespace"), column=a.get("column"), severity="high" if chk in ("freshness", "duplicates", "volume") else "medium",
                                     measured={"assertion": a.get("assertion"), "success": False}, when=when, external_id=run.get("runId")))
    return out


def parse_dbt(payload, known: list[str] | None = None) -> list[dict]:
    results = (payload or {}).get("results") or []
    when = _ts(((payload or {}).get("metadata") or {}).get("generated_at"))
    known_l = sorted({k.lower() for k in (known or [])}, key=len, reverse=True)
    out = []
    for r in results:
        if str(r.get("status") or "").lower() not in ("fail", "error", "warn"):
            continue
        uid = str(r.get("unique_id") or "")
        parts = uid.split(".")
        name = parts[2] if len(parts) > 2 and parts[0] == "test" else (parts[-1] if parts else uid)
        test = name
        for pre in ("source_", "dbt_utils_", "dbt_expectations_"):
            if test.startswith(pre):
                test = test[len(pre):]
        chk = check_from_name(test)
        m = re.match(r"^(not_null|unique|accepted_values|relationships|expect_[a-z_]+?|recency|equal_rowcount|row_count|freshness|[a-z]+)_(.+)$", test)
        rest = m.group(2) if m else test
        model, column = rest, None
        for k in known_l:
            if rest.lower().startswith(k + "_") or rest.lower() == k:
                model, column = rest[:len(k)], rest[len(k) + 1:] or None
                break
        else:
            bits = rest.split("_")
            if len(bits) > 1:
                model, column = bits[0], "_".join(bits[1:])
        if column:
            column = column.split("__")[0]
        sev = "high" if str(r.get("status")).lower() in ("fail", "error") else "low"
        out.append(_item("dbt", model, chk, f"dbt test {name} {r.get('status')}" + (f": {r.get('failures')} failing rows" if r.get("failures") else ""), column=column, severity=sev,
                         measured={"failures": r.get("failures"), "status": r.get("status"), "message": str(r.get("message") or "")[:300]}, when=when, external_id=uid))
    return out


def parse_ge(payload) -> list[dict]:
    meta = (payload or {}).get("meta") or {}
    asset = ((meta.get("active_batch_definition") or {}).get("data_asset_name") or (meta.get("batch_spec") or {}).get("table_name") or (meta.get("batch_kwargs") or {}).get("table")
             or str(meta.get("expectation_suite_name") or "").split(".")[0] or "data asset")
    when = _ts((meta.get("run_id") or {}).get("run_time") if isinstance(meta.get("run_id"), dict) else meta.get("validation_time"))
    out = []
    for r in (payload or {}).get("results") or []:
        if r.get("success") is not False:
            continue
        cfg = r.get("expectation_config") or {}
        typ = cfg.get("expectation_type") or cfg.get("type") or "expectation"
        kw = cfg.get("kwargs") or {}
        res = r.get("result") or {}
        chk = check_from_name(typ)
        col = kw.get("column") or (", ".join(kw.get("column_list")) if kw.get("column_list") else None)
        out.append(_item("ge", asset, chk, f"{typ.replace('expect_', '').replace('_', ' ')} failed" + (f" on {col}" if col else ""), column=col, severity="high" if chk in ("duplicates", "nulls", "volume") else "medium",
                         measured={k: res.get(k) for k in ("observed_value", "unexpected_count", "unexpected_percent", "element_count") if res.get(k) is not None}, expected={k: v for k, v in kw.items() if k not in ("column", "column_list")},
                         when=when, external_id=cfg.get("id") or f"{asset}:{typ}:{col or ''}"))
    return out


def parse_soda(payload) -> list[dict]:
    checks = (payload or {}).get("checks") or ((payload or {}).get("scanResults") or {}).get("checks") or []
    when = _ts((payload or {}).get("scanStartTimestamp") or (payload or {}).get("scanEndTimestamp"))
    out = []
    for c in checks:
        if str(c.get("outcome") or "").lower() not in ("fail", "warn", "error"):
            continue
        chk = check_from_name(f"{c.get('type') or ''} {c.get('name') or ''} {c.get('definition') or ''}")
        diag = c.get("diagnostics") or {}
        out.append(_item("soda", c.get("table") or c.get("dataset") or "table", chk, f"Soda check {c.get('name') or c.get('definition') or c.get('type')} {c.get('outcome')}", system=c.get("dataSource"),
                         column=c.get("column"), severity="high" if str(c.get("outcome")).lower() == "fail" else "low", measured={"value": diag.get("value"), "outcome": c.get("outcome")},
                         expected={k: v for k, v in diag.items() if k in ("fail", "warn")}, when=when, external_id=c.get("identity") or f"{c.get('table')}:{c.get('name')}"))
    return out


def parse_webhook(payload, default_tool: str = "webhook") -> list[dict]:
    """A generic payload: {tool, incidents: [{asset|table|dataset, system, check|type, title|message, severity, column, measured, expected, when, id}]}
    (also one incident at the top level). Monte Carlo, Bigeye, Acceldata, Metaplane, Elementary and Datadog monitors post this shape through their webhooks."""
    if isinstance(payload, list):
        items, tool = payload, default_tool
    else:
        payload = payload or {}
        tool = str(payload.get("tool") or payload.get("source") or default_tool).lower().replace(" ", "")
        items = payload.get("incidents") or payload.get("alerts") or payload.get("events") or [payload]
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        asset = it.get("asset") or it.get("table") or it.get("dataset") or it.get("full_table_id") or it.get("resource") or it.get("entity")
        if not asset:
            continue
        chk = it.get("check") or it.get("check_kind") or it.get("type") or it.get("monitor_type") or it.get("kind") or ""
        chk = chk if chk in CHECKS else check_from_name(str(chk) + " " + str(it.get("title") or it.get("message") or ""))
        out.append(_item(tool if tool in TOOLS else default_tool, asset, chk, it.get("title") or it.get("message") or it.get("description") or f"{tool} incident on {asset}", system=it.get("system") or it.get("warehouse") or it.get("namespace"),
                         column=it.get("column") or it.get("field"), severity=_sev(it.get("severity") or it.get("priority")), measured=it.get("measured") or it.get("value") or it.get("observed"),
                         expected=it.get("expected") or it.get("threshold"), when=_ts(it.get("when") or it.get("time") or it.get("timestamp") or it.get("detected_at")), external_id=str(it.get("id") or it.get("incident_id") or it.get("alert_id") or "") or None))
    return out


PARSERS = {"openlineage": parse_openlineage, "dbt": parse_dbt, "ge": parse_ge, "soda": parse_soda, "webhook": parse_webhook}


def parse_results(tool: str, payload, known: list[str] | None = None) -> list[dict]:
    tool = (tool or "webhook").lower()
    if tool == "dbt":
        return parse_dbt(payload, known)
    if tool in PARSERS:
        return PARSERS[tool](payload)
    return parse_webhook(payload, tool if tool in TOOLS else "webhook")


def utcnow() -> float:
    return time.time()


def day_key(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def math_ok() -> bool:   # keeps `math` referenced for readers that extend this module
    return math.isfinite(1.0)
