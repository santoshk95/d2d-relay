"""Move the D2D index into Postgres (phase 8).

    D2D_DATABASE_URL=postgresql://d2d:...@postgres:5432/d2d python -m app.dbmove            # from /data/state/index.db
    ... python -m app.dbmove --from-sqlite /path/index.db
    ... python -m app.dbmove --from-dump /backups/d2d-.../index.jsonl.gz                    # a Postgres backup

Creates the schema, copies every table in dependency order in one transaction, resets the id sequences and checks
that every table has the same number of rows as the source. The target must be empty (only the bootstrap rows the
app writes at start); --force replaces whatever is there. The source is never changed, so going back to SQLite is
just removing D2D_DATABASE_URL.

P17: this moves the platform's own workspace (index.db -> schema public). Other tenants of a SQLite install move one
by one with `python -m app.tenantmove export <tenant>` there and `... import <file>` here (same ids, same partner).
"""
import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

from . import db

BATCH = 500
SERIAL = ("audit", "usage")


def _source_sqlite(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        raise SystemExit(f"No SQLite index at {path}")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    out = {t: [dict(r) for r in src.execute(f"SELECT * FROM {t}")] if t in have else [] for t in db.tables()}
    src.close()
    return out


def _source_dump(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {t: [] for t in db.tables()}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            out.setdefault(rec["table"], []).append(rec["row"])
    return out


def move(rows: dict[str, list[dict]], force: bool = False) -> dict[str, int]:
    if db.BACKEND != "postgres":
        raise SystemExit("Set D2D_DATABASE_URL=postgresql://... (the target) first.")
    db.init()
    c = db.conn()
    db._pg_path()                     # P17: the platform's own schema (public), whichever tenant init() ended in
    busy = [t for t in db.tables() if t not in ("users", "teams", "memberships", "meta", "audit")
            and c.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()]
    if busy and not force:
        raise SystemExit(f"The Postgres database already has data ({', '.join(busy[:5])}); use --force to replace it.")
    counts = {}
    with db.transaction():
        c.execute("TRUNCATE " + ", ".join(reversed(db.tables())) + " RESTART IDENTITY CASCADE")
        for t in db.tables():
            data = rows.get(t) or []
            cols_here = {r["column_name"] for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = current_schema()", (t,)).fetchall()}
            if data:
                cols = [k for k in data[0] if k in cols_here]
                sql = f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
                with c.cursor() as cur:
                    for i in range(0, len(data), BATCH):
                        cur.executemany(sql, [tuple(r.get(k) for k in cols) for r in data[i:i + BATCH]])
            counts[t] = len(data)
        for t in SERIAL:
            c.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)")
    for t, n in counts.items():
        got = c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
        if got != n:
            raise SystemExit(f"{t}: copied {got} rows, expected {n}")
    db.run("INSERT OR REPLACE INTO meta (key, value) VALUES ('database', 'postgres')")
    db.audit("database.move", None, {"tables": len(counts), "rows": sum(counts.values())}, "system")
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-sqlite", type=Path, default=db.PATH)
    ap.add_argument("--from-dump", type=Path)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    rows = _source_dump(a.from_dump) if a.from_dump else _source_sqlite(a.from_sqlite)
    counts = move(rows, a.force)
    print(f"Moved {sum(counts.values())} rows in {len(counts)} tables into Postgres:")
    for t, n in counts.items():
        if n:
            print(f"  {t:20} {n}")


if __name__ == "__main__":
    main(sys.argv[1:])
