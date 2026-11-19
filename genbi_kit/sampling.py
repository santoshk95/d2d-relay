"""Large data (item 64): build a dashboard on a sample of its big tables.

The person's files stay as they are in data/. When a table has more rows than OVER (or the person asked for a sample),
D2D takes a sample of it once and every build step reads the sample instead: `genbi profile`, `genbi sql`, the
prototype, the review gates and the DAX check (which samples on its own as well). Tables with fewer rows (lookups such
as stores or products) are used in full, so every key in a sampled table still finds its row. Ask Relay keeps reading
every row (data.connect(full=True)).

sample.json in the project folder says what was sampled:
    {"method": "random" | "recent", "rows": 1000000, "over": 2000000, "files": {"sales.csv": {"of": 48213000,
     "rows": 1000000, "date": "txn_date"}}, "when": ...}
  random   a reservoir sample of `rows` rows (DuckDB's, seed 42: the same rows every time): it keeps the whole date range
           and the mix of stores and products; totals are smaller than the real ones by the share sampled
  recent   the `rows` most recent rows by the table's first date column: exact totals for the latest weeks, a shorter
           history (random when the table has no date column)

The samples: .genbi/cache/<file>.sample.parquet (what DuckDB reads) and data_sample/<file> (CSV, with every table that
was not sampled copied beside it): the Power BI file's DataFolder points there, so Power BI Desktop loads the sample
quickly; the person points the parameter at the full files and refreshes to load every row.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import duckdb

from .data import _lit, _q, _source

SAMPLE_FILE = "sample.json"
SAMPLE_DIR = "data_sample"
ROWS = int(os.environ.get("GENBI_SAMPLE_ROWS") or 1_000_000)
OVER = int(os.environ.get("GENBI_SAMPLE_OVER") or 2_000_000)
METHODS = ("random", "recent")


def spec(workdir: Path) -> dict | None:
    """sample.json, or None when nothing is sampled."""
    p = Path(workdir) / SAMPLE_FILE
    if not p.is_file():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return s if isinstance(s, dict) and s.get("files") else None


def _sample_path(workdir: Path, name: str) -> Path:
    return Path(workdir) / ".genbi" / "cache" / (name + ".sample.parquet")


def source(workdir: Path, f: Path, s: dict | None) -> str | None:
    """What DuckDB reads for a data file that was sampled (None: read the file itself). A sample older than its file
    (new data came with a change request) is not used: the file is read in full until the sample is made again."""
    if not s or f.name not in (s.get("files") or {}):
        return None
    p = _sample_path(workdir, f.name)
    try:
        return f"read_parquet({_lit(p)})" if p.is_file() and p.stat().st_mtime >= f.stat().st_mtime else None
    except OSError:
        return None


def stale(workdir: Path) -> bool:
    """Whether the samples need making again: a data file changed or came since sample.json was written."""
    s = spec(workdir)
    if not s:
        return False
    when = float(s.get("when") or 0)
    files = sorted((Path(workdir) / "data").glob("*.csv")) + sorted((Path(workdir) / "data").glob("*.tsv")) + \
        sorted((Path(workdir) / "data").glob("*.parquet"))
    have = {f.name for f in (Path(workdir) / SAMPLE_DIR).glob("*")}
    return any(f.stat().st_mtime > when or f.name not in have for f in files)


def _full_source(con, f: Path, cache: Path) -> str:
    return f"read_parquet({_lit(f)})" if f.suffix.lower() == ".parquet" else _source(con, f, cache)


def _date_column(con, src: str) -> str | None:
    for name, dtype, *_ in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall():
        if str(dtype).upper().startswith(("DATE", "TIMESTAMP")):
            return name
    return None


def measure(workdir: Path) -> list[dict]:
    """Every data file with its rows and bytes (reading a CSV makes its Parquet copy once, as the build would)."""
    workdir = Path(workdir)
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    cache = workdir / ".genbi" / "cache"
    out = []
    for f in sorted((workdir / "data").glob("*.csv")) + sorted((workdir / "data").glob("*.tsv")) + sorted((workdir / "data").glob("*.parquet")):
        try:
            n = con.execute(f"SELECT count(*) FROM {_full_source(con, f, cache)}").fetchone()[0]
        except duckdb.Error as e:
            out.append({"file": f.name, "bytes": f.stat().st_size, "rows": None, "error": str(e).splitlines()[0][:200]})
            continue
        out.append({"file": f.name, "bytes": f.stat().st_size, "rows": int(n)})
    return out


def prepare(workdir: Path, policy: str = "auto", rows: int | None = None, method: str = "random",
            over: int | None = None) -> dict:
    """Decide and make the samples. policy: auto (sample tables over `over` rows), sample (sample every table over
    `rows` rows) or all (no sample; an old one is removed). Returns {"files": measure(), "sampled": {...}, "method",
    "rows", "over"}; writes sample.json (or removes it) and the samples."""
    workdir = Path(workdir)
    rows = max(10_000, int(rows or ROWS))
    over = max(rows, int(over or OVER))
    method = method if method in METHODS else "random"
    files = measure(workdir)
    limit = None if policy == "all" else rows if policy == "sample" else over
    big = [f for f in files if limit is not None and f.get("rows") and f["rows"] > limit]
    # a big table far smaller than the biggest is a lookup (customers, items): kept whole, so every key in a sampled
    # table still finds its row
    most = max((f.get("rows") or 0) for f in files) if files else 0
    big = [f for f in big if f["rows"] >= most * 0.2]
    sp = workdir / SAMPLE_FILE
    sdir = workdir / SAMPLE_DIR
    if not big:
        sp.unlink(missing_ok=True)
        shutil.rmtree(sdir, ignore_errors=True)
        for f in (workdir / ".genbi" / "cache").glob("*.sample.parquet"):
            f.unlink(missing_ok=True)
        return {"files": files, "sampled": {}, "method": method, "rows": rows, "over": over}
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    cache = workdir / ".genbi" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(sdir, ignore_errors=True)
    sdir.mkdir(parents=True, exist_ok=True)
    sampled = {}
    for f in files:
        path = workdir / "data" / f["file"]
        if f not in big:
            if f.get("rows") is not None:                       # used in full: the same file beside the samples
                shutil.copy2(path, sdir / f["file"])        # a copy, never a link: a replaced file must not leave the old rows
            continue
        src = _full_source(con, path, cache)
        date = _date_column(con, src) if method == "recent" else None
        how = "recent" if date else "random"
        pick = (f"SELECT * FROM {src} ORDER BY {_q(date)} DESC NULLS LAST LIMIT {rows}" if date else
                f"SELECT * FROM {src} USING SAMPLE {rows} ROWS (reservoir, 42)")
        out, tmp = _sample_path(workdir, f["file"]), cache / (f["file"] + ".sample.tmp")
        con.execute(f"COPY ({pick}) TO {_lit(tmp)} (FORMAT parquet)")
        os.replace(tmp, out)
        target = sdir / f["file"]
        if path.suffix.lower() == ".parquet":
            con.execute(f"COPY (SELECT * FROM read_parquet({_lit(out)})) TO {_lit(target)} (FORMAT parquet)")
        else:
            con.execute(f"COPY (SELECT * FROM read_parquet({_lit(out)})) TO {_lit(target)} (HEADER, DELIMITER ',')")
        sampled[f["file"]] = {"of": f["rows"], "rows": min(rows, f["rows"]), "method": how,
                              **({"date": date} if date else {})}
    sp.write_text(json.dumps({"method": method, "rows": rows, "over": over, "policy": policy, "files": sampled,
                              "when": time.time()}, indent=2), encoding="utf-8")
    return {"files": files, "sampled": sampled, "method": method, "rows": rows, "over": over}


def note(s: dict | None) -> str:
    """profile.md's lines about the sample, for the agent ('' when nothing is sampled)."""
    if not s:
        return ""
    lines = ["## Built on a sample (large data)", "",
             "These tables are big, so this dashboard is built and checked on a sample of them; every other table is used in "
             "full. Totals from `genbi sql` and the prototype are the sample's: never present them as the business's real "
             "totals (ratios, averages, shares and trends are fine). The Power BI file loads the sample too, and the person "
             "refreshes it on the full files.", ""]
    for name, f in sorted((s.get("files") or {}).items()):
        share = f["rows"] / f["of"] if f.get("of") else 1
        how = (f"the {f['rows']:,} most recent rows by {f['date']}" if f.get("method") == "recent" else
               f"a random sample of {f['rows']:,} rows")
        lines.append(f"- data/{name}: {how} of {f['of']:,} ({share:.1%})")
    return "\n".join(lines) + "\n"
