"""Profile the CSVs in data/: tables, columns, types, keys, likely relationships and date coverage.

Writes profile.md (read by the agent) and profile.json; returns the markdown.
"""
import json
from pathlib import Path

import duckdb

from .data import _q, _source, raw_name

NUMERIC = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "DOUBLE", "FLOAT", "DECIMAL", "UBIGINT", "UINTEGER")


def _kind(duck_type: str) -> str:
    t = duck_type.upper()
    if t.startswith(("DATE", "TIMESTAMP")):
        return "date"
    if t == "BOOLEAN":
        return "bool"
    if t.startswith(("DOUBLE", "FLOAT", "DECIMAL")):
        return "decimal"
    if t.startswith(NUMERIC):
        return "int"
    return "string"


def _table(con, f: Path, cache: Path) -> dict:
    source = f"read_parquet('{str(f).replace(chr(39), chr(39) * 2)}')" if f.suffix == ".parquet" else _source(con, f, cache)
    con.execute(f"CREATE OR REPLACE TEMP TABLE {_q(raw_name(f))} AS SELECT * FROM {source}")
    src = _q(raw_name(f))
    n = con.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
    cols = []
    for name, dtype, *_ in con.execute(f"DESCRIBE {src}").fetchall():
        c = _q(name)
        count = f"COUNT(DISTINCT {c})" if n <= 500_000 else f"approx_count_distinct({c})"
        distinct, nonnull, lo, hi = con.execute(
            f"SELECT {count}, COUNT({c}), MIN({c}), MAX({c}) FROM {src}").fetchone()
        info = {"name": name, "type": _kind(dtype), "duckdb_type": dtype, "distinct": int(distinct),
                "nulls": int(n - nonnull), "min": None if lo is None else str(lo), "max": None if hi is None else str(hi)}
        if info["type"] == "string" and distinct <= 40:
            info["values"] = [r[0] for r in con.execute(
                f"SELECT {c}, COUNT(*) k FROM {src} WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY k DESC LIMIT 12").fetchall()]
        elif info["type"] == "string":
            info["examples"] = [r[0] for r in con.execute(f"SELECT DISTINCT {c} FROM {src} WHERE {c} IS NOT NULL LIMIT 4").fetchall()]
        if nonnull == n and distinct >= n * 0.97:
            exact = con.execute(f"SELECT COUNT(DISTINCT {c}) FROM {src}").fetchone()[0]
            info["unique"] = exact == n
        cols.append(info)
    return {"file": f.name, "view": raw_name(f), "rows": int(n), "columns": cols}


def profile(workdir: Path) -> str:
    workdir = Path(workdir)
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    tables, unreadable = [], []
    files = sorted((workdir / "data").glob("*.csv")) + sorted((workdir / "data").glob("*.parquet"))   # + warehouse extracts
    for f in files:
        try:
            tables.append(_table(con, f, workdir / ".genbi" / "cache"))
        except duckdb.Error as e:            # one bad file must not hide the others
            unreadable.append(f"{f.name}: {str(e).splitlines()[0][:200]}")

    # likely relationships: same column name (case-insensitive), unique on the "one" side
    rels = []
    for one in tables:
        for key in (c for c in one["columns"] if c.get("unique")):
            for many in tables:
                if many is one:
                    continue
                match = next((c for c in many["columns"] if c["name"].lower() == key["name"].lower()), None)
                if not match or many["rows"] < one["rows"]:
                    continue
                share = con.execute(
                    f"SELECT AVG(CASE WHEN o.k IS NULL THEN 0 ELSE 1 END) FROM (SELECT DISTINCT {_q(match['name'])} AS v "
                    f"FROM {_q(many['view'])}) m LEFT JOIN (SELECT DISTINCT {_q(key['name'])} AS k FROM {_q(one['view'])}) o "
                    f"ON CAST(m.v AS VARCHAR) = CAST(o.k AS VARCHAR)").fetchone()[0]
                rels.append({"many": f"{many['file']}[{match['name']}]", "one": f"{one['file']}[{key['name']}]",
                             "matched": round(float(share or 0), 3)})

    lines = ["# Data profile", ""]
    for t in tables:
        dates = [c for c in t["columns"] if c["type"] == "date"]
        lines.append(f"## {t['file']}  ({t['rows']:,} rows; SQL view `{t['view']}`)")
        if dates:
            lines.append("Date coverage: " + "; ".join(f"{c['name']} {c['min'][:10]} {c['max'][:10]}" for c in dates))
        lines.append("")
        lines.append("| column | type | distinct | nulls | min | max | notes |")
        lines.append("|---|---|---|---|---|---|---|")
        for c in t["columns"]:
            notes = []
            if c.get("unique"):
                notes.append("unique (key)")
            if c.get("values"):
                notes.append("values: " + ", ".join(map(str, c["values"])))
            elif c.get("examples"):
                notes.append("e.g. " + ", ".join(map(str, c["examples"])))
            short = lambda v: "" if v is None else (v[:10] if c["type"] == "date" else v[:24])
            lines.append(f"| {c['name']} | {c['type']} | {c['distinct']:,} | {c['nulls']:,} | {short(c['min'])} | "
                         f"{short(c['max'])} | {'; '.join(notes)} |")
        lines.append("")
    if unreadable:
        lines += ["## Files that could not be read (no SQL view)", ""] + [f"- {u}" for u in unreadable] + [""]
    lines.append("## Likely relationships (many -> one)")
    lines += [f"- {r['many']} {r['one']}  ({r['matched']:.0%} of values match)" for r in rels] or ["- none found by name"]
    md = "\n".join(lines) + "\n"
    (workdir / "profile.md").write_text(md, encoding="utf-8")
    (workdir / "profile.json").write_text(json.dumps({"tables": tables, "relationships": rels, "unreadable": unreadable},
                                                     indent=2, default=str), encoding="utf-8")
    return md
