"""DuckDB over the project's CSVs and warehouse extracts.

Two kinds of views:
- raw: one per file in data/ (CSV, or a Parquet extract of a warehouse table), named after the file (e.g.
  fact_sales), all columns as detected;
- model: once a definition exists, one per model table with the model's names and types
  (e.g. "Sales" with "Unit Count"), plus the generated date table — so prototype SQL is written
  against the same tables and columns as the DAX.
"""
import datetime
import decimal
import os
import re
import sys
from pathlib import Path

import duckdb

DUCK_TYPE = {"int": "BIGINT", "decimal": "DOUBLE", "string": "VARCHAR", "date": "DATE", "bool": "BOOLEAN"}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def raw_name(path: Path) -> str:
    return re.sub(r"\W+", "_", path.stem).strip("_").lower() or "data"


def _source(con, f: Path, cache: Path) -> str:
    """Parquet copy of a CSV (or a TSV), made once and refreshed when the file changes, so repeated queries over
    millions of rows stay fast. Falls back to reading the file directly."""
    tsv = f.suffix.lower() == ".tsv"
    opts = "header = true, sample_size = -1" + (", delim = '\\t'" if tsv else "")
    pq = cache / (f.stem + (".tsv" if tsv else "") + ".parquet")
    try:
        if not pq.exists() or pq.stat().st_mtime < f.stat().st_mtime:
            cache.mkdir(parents=True, exist_ok=True)
            tmp = cache / (pq.name + ".tmp")
            con.execute(f"COPY (SELECT * FROM read_csv_auto({_lit(f)}, {opts})) "
                        f"TO {_lit(tmp)} (FORMAT parquet)")
            os.replace(tmp, pq)
        return f"read_parquet({_lit(pq)})"
    except (duckdb.Error, OSError):
        return f"read_csv_auto({_lit(f)}, {opts})"


def connect(workdir: Path, defn: dict | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    data = Path(workdir) / "data"
    cache = Path(workdir) / ".genbi" / "cache"
    sources = {}
    csvs = sorted(data.glob("*.csv"))
    have = {raw_name(f) for f in csvs}
    for f in csvs + [t for t in sorted(data.glob("*.tsv")) if raw_name(t) not in have]:   # a TSV upload too, unless a CSV holds its name
        try:
            source = _source(con, f, cache)
            con.execute(f"CREATE OR REPLACE VIEW {_q(raw_name(f))} AS SELECT * FROM {source}")
            sources[f.name] = source
        except duckdb.Error as e:              # one unreadable file must not take the other views down
            print(f"warning: data/{f.name} could not be read, no view for it: {str(e).splitlines()[0][:200]}",
                  file=sys.stderr)
    for f in sorted(data.glob("*.parquet")):      # warehouse extracts (the app pulls them with the person's login)
        try:
            source = f"read_parquet({_lit(f)})"
            con.execute(f"CREATE OR REPLACE VIEW {_q(raw_name(f))} AS SELECT * FROM {source}")
            sources[f.name] = source
        except duckdb.Error as e:
            print(f"warning: data/{f.name} could not be read, no view for it: {str(e).splitlines()[0][:200]}",
                  file=sys.stderr)
    if defn:
        _model_views(con, sources, defn)
    return con


def _model_views(con, sources: dict, d: dict) -> None:
    for t in d.get("tables", []):
        src = t.get("csv") or t.get("extract")
        if src in sources:
            cols = ", ".join(f"TRY_CAST({_q(c.get('source', c['name']))} AS {DUCK_TYPE.get(c.get('type', 'string'), 'VARCHAR')}) "
                             f"AS {_q(c['name'])}" for c in t.get("columns", []))
            con.execute(f"CREATE OR REPLACE VIEW {_q(t['name'])} AS SELECT {cols} FROM {sources[src]}")
    for t in d.get("tables", []):
        spec = t.get("date_table")
        if isinstance(spec, dict):
            events = spec.get("events") or []
            md = "(month(d) * 100 + day(d))"
            event_sql = ("CASE " + " ".join(
                f"WHEN {md} BETWEEN {int(str(e['from']).replace('-', ''))} AND {int(str(e['to']).replace('-', ''))} "
                f"THEN '{str(e['name']).replace(chr(39), chr(39) * 2)}'" for e in events) + " END") if events else "NULL"
            past = "NULL"
            if spec.get("is_past_from"):
                m = re.match(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$", spec["is_past_from"])
                if m:
                    past = f"d::DATE <= (SELECT max({_q(m.group(2))}) FROM {_q(m.group(1))})"
            con.execute(f"""CREATE OR REPLACE VIEW {_q(t['name'])} AS
                SELECT d::DATE AS "Date", year(d) AS "Year", month(d) AS "Month Number", strftime(d, '%b') AS "Month",
                       date_trunc('month', d)::DATE AS "Month Start", strftime(d, '%Y-%m') AS "Year Month",
                       'Q' || quarter(d) AS "Quarter", isodow(d) AS "Weekday Number", strftime(d, '%a') AS "Weekday",
                       strftime(d, '%A') AS "Weekday Name", {event_sql} AS "Key Event", {past} AS "Is Past"
                FROM range(DATE '{spec['start']}', DATE '{spec['end']}' + INTERVAL 1 DAY, INTERVAL 1 DAY) r(d)""")


def _plain(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, datetime.datetime):
        return v.isoformat(sep=" ")[:19]
    if isinstance(v, datetime.date):
        return v.isoformat()
    return v


def query(con, sql: str, limit: int | None = None) -> tuple[list[str], list[list]]:
    cur = con.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = cur.fetchmany(limit) if limit else cur.fetchall()
    return cols, [[_plain(v) for v in r] for r in rows]


def records(con, sql: str) -> list[dict]:
    cols, rows = query(con, sql)
    return [dict(zip(cols, r)) for r in rows]


def as_text(cols: list[str], rows: list[list], width: int = 32) -> str:
    def cell(v):
        s = "" if v is None else (f"{v:,.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
        return s if len(s) <= width else s[: width - 1] + "…"
    table = [[cell(c) for c in cols]] + [[cell(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(cols))]
    lines = [" | ".join(r[i].ljust(widths[i]) for i in range(len(cols))) for r in table]
    lines.insert(1, "-+-".join("-" * w for w in widths))
    return "\n".join(lines)
