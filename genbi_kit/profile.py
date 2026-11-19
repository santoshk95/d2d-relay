"""Profile the CSVs in data/: tables, columns, types, keys, likely relationships and date coverage.

Writes profile.md (read by the agent) and profile.json; returns the markdown.

Item 61: each column is tagged with its business term from the organisation's ontology (ontology.json in the project
folder, else the general pack): profile.md shows the tags, the measure terms found in more than one column (to combine)
and one entity's keys under different column names, which are tried as relationships too (store_id -> str_nbr).
"""
import json
from pathlib import Path

import duckdb

from . import ontology, sampling
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


def _table(con, f: Path, cache: Path, sampled: str | None = None) -> dict:
    """One file's columns. sampled: what DuckDB reads for a big table built on a sample (item 64)."""
    source = sampled or (f"read_parquet('{str(f).replace(chr(39), chr(39) * 2)}')" if f.suffix == ".parquet" else _source(con, f, cache))
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
    sample = sampling.spec(workdir)                                       # item 64: big tables read as their sample
    for f in files:
        try:
            tables.append(_table(con, f, workdir / ".genbi" / "cache", sampling.source(workdir, f, sample)))
            got = (sample or {}).get("files", {}).get(f.name)
            if got:
                tables[-1]["sample_of"] = got["of"]
        except duckdb.Error as e:            # one bad file must not hide the others
            unreadable.append(f"{f.name}: {str(e).splitlines()[0][:200]}")

    # item 61: business terms from the organisation's ontology (or the general pack)
    onto = ontology.load_project(workdir) or {}
    sem = ontology.tag_tables(tables, onto.get("terms") or ontology.default_terms(), onto.get("overrides"))
    for t in tables:
        for c in t["columns"]:
            tag = sem["tags"].get(f"{t['file']}[{c['name']}]")
            if tag:
                c["tag"] = tag

    def overlap(many: dict, mcol: str, one: dict, ocol: str) -> float:
        share = con.execute(
            f"SELECT AVG(CASE WHEN o.k IS NULL THEN 0 ELSE 1 END) FROM (SELECT DISTINCT {_q(mcol)} AS v "
            f"FROM {_q(many['view'])}) m LEFT JOIN (SELECT DISTINCT {_q(ocol)} AS k FROM {_q(one['view'])}) o "
            f"ON CAST(m.v AS VARCHAR) = CAST(o.k AS VARCHAR)").fetchone()[0]
        return round(float(share or 0), 3)

    # likely relationships: same column name (case-insensitive), unique on the "one" side
    rels, seen = [], set()
    for one in tables:
        for key in (c for c in one["columns"] if c.get("unique")):
            for many in tables:
                if many is one:
                    continue
                match = next((c for c in many["columns"] if c["name"].lower() == key["name"].lower()), None)
                if not match or (many.get("sample_of") or many["rows"]) < (one.get("sample_of") or one["rows"]):
                    continue
                rels.append({"many": f"{many['file']}[{match['name']}]", "one": f"{one['file']}[{key['name']}]",
                             "matched": overlap(many, match["name"], one, key["name"])})
                seen.add((rels[-1]["many"], rels[-1]["one"]))
    # ... and one entity's keys under different names (the ontology's key terms): tried the same way
    by_ref = {f"{t['file']}[{c['name']}]": (t, c) for t in tables for c in t["columns"]}
    for group in sem["keys"]:
        refs = [r for r in group["columns"] if r in by_ref]
        for o_ref in refs:
            one, key = by_ref[o_ref]
            if not key.get("unique"):
                continue
            for m_ref in refs:
                many, col = by_ref[m_ref]
                if many is one or (many.get("sample_of") or many["rows"]) < (one.get("sample_of") or one["rows"]) or (m_ref, o_ref) in seen:
                    continue
                try:
                    share = overlap(many, col["name"], one, key["name"])
                except duckdb.Error:
                    continue
                if share >= 0.5:
                    rels.append({"many": m_ref, "one": o_ref, "matched": share, "by": f"business term {group['entity']}"})
                    seen.add((m_ref, o_ref))

    lines = ["# Data profile", ""]
    if sample:
        lines += [sampling.note(sample)]
    for t in tables:
        dates = [c for c in t["columns"] if c["type"] == "date"]
        size = f"a sample of {t['rows']:,} of {t['sample_of']:,} rows" if t.get("sample_of") else f"{t['rows']:,} rows"
        lines.append(f"## {t['file']}  ({size}; SQL view `{t['view']}`)")
        if dates:
            lines.append("Date coverage: " + "; ".join(f"{c['name']} {c['min'][:10]} {c['max'][:10]}" for c in dates))
        lines.append("")
        lines.append("| column | type | business term | distinct | nulls | min | max | notes |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for c in t["columns"]:
            tag = c.get("tag") or {}
            term = (f"{tag['term']} ({tag['kind']}" + (f", {tag['variant']}" if tag.get("variant") else "") + ")") if tag else ""
            notes = []
            if c.get("unique"):
                notes.append("unique (key)")
            if c.get("values"):
                notes.append("values: " + ", ".join(map(str, c["values"])))
            elif c.get("examples"):
                notes.append("e.g. " + ", ".join(map(str, c["examples"])))
            short = lambda v: "" if v is None else (v[:10] if c["type"] == "date" else v[:24])
            lines.append(f"| {c['name']} | {c['type']} | {term} | {c['distinct']:,} | {c['nulls']:,} | {short(c['min'])} | "
                         f"{short(c['max'])} | {'; '.join(notes)} |")
        lines.append("")
    if unreadable:
        lines += ["## Files that could not be read (no SQL view)", ""] + [f"- {u}" for u in unreadable] + [""]
    lines.append("## Likely relationships (many -> one)")
    lines += [f"- {r['many']} {r['one']}  ({r['matched']:.0%} of values match" + (f"; {r['by']})" if r.get("by") else ")")
              for r in rels] or ["- none found by name"]
    c = sem["counts"]
    lines += ["", f"## Business terms (ontology{': ' + onto['industry'] if onto.get('industry') else ''})", "",
              f"{c['tagged']} of {c['columns']} columns have a business term (ontology.md: what each term means)."]
    if sem["combine"]:
        lines += ["", "### Same business term in several columns (one business number: combine them, ontology.md)"]
        lines += [f"- {g['term']}: {', '.join(g['columns'])}" for g in sem["combine"]]
    if sem["related"]:
        lines += ["", "### Related business terms in different tables (maybe one number under two names: check before combining)"]
        lines += [f"- {g['family']}: {', '.join(g['columns'])} ({', '.join(g['terms'])})" for g in sem["related"]]
    if sem["keys"]:
        lines += ["", "### Keys of one entity under different column names (likely relationships)"]
        lines += [f"- {g['entity']}: {', '.join(g['columns'])}" for g in sem["keys"]]
    md = "\n".join(lines) + "\n"
    (workdir / "profile.md").write_text(md, encoding="utf-8")
    (workdir / "profile.json").write_text(json.dumps({"tables": tables, "relationships": rels, "unreadable": unreadable,
                                                      "semantic": {k: sem[k] for k in ("combine", "related", "keys", "counts")},
                                                      "industry": onto.get("industry") or ""},
                                                     indent=2, default=str), encoding="utf-8")
    return md
