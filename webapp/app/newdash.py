"""New dashboard, the guided way (the user, 2026-11-19: "title first and then data is uploaded and then what needs to
done or built is prefilled and user can change it and confirm"): what Relay suggests building from the files the person
has just uploaded, before anything is planned or charged (webapp/static/js/04-new.js, step 3 "What to build").

POST /api/projects/suggest {uploads: [upload ids], prompt?: the person's own words so far} reads each of the person's
completed uploads (uploads.py), profiles every CSV with DuckDB, tags its columns with the organisation's business terms
(ontology.py), finds the KPIs of its KPI dictionary that the data supports (the general pack's KPIs while it has none)
and answers with a request in plain words for the person to change: who the dashboard is for, the KPIs, the breakdowns
(store, product, region ...) and the time comparisons; with the tables it read, their business terms and the KPIs.
Deterministic: no AI, no credits, nothing saved.

The work is capped so a 5 GB file answers in seconds: the columns, types and tags come from the file's first HEAD_BYTES;
a file up to FULL_BYTES is then read whole once (its exact row count and date range), a bigger one gives an estimated
row count (from its size) and the dates in its last TAIL_BYTES too. After BUDGET_S seconds the files left get the
estimate as well.

A KPI fits the data when (in this order): its name or another name of it is a business term the data has (Revenue,
Sales; "Customers" counts the Customer key); every KPI or term its reference DAX names fits ([Revenue] / [Orders]);
every part of its formula in words is one (Discounts / (Revenue + Discounts)); or it is a time or target version of a
KPI that fits (Revenue LY needs a date column, Revenue vs Budget % a budget or target column).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import duckdb
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from genbi_kit import ontology as O
from genbi_kit.data import _lit, _q
from genbi_kit.profile import _kind                  # noqa: PLC2701 - the profile's own column types: int, decimal, string, date, bool
from genbi_kit.semreview import kpis as K

from . import auth, ontology, uploads

router = APIRouter()
MAX_FILES = 40
HEAD_BYTES = 8 * 1024 * 1024                         # what the columns, types and tags are read from
TAIL_BYTES = 2 * 1024 * 1024                         # where a big file's dates end
FULL_BYTES = int(float(os.environ.get("D2D_SUGGEST_FULL_MB") or 256) * 1024 * 1024)   # read whole up to this size
BUDGET_S = 10.0
THREADS = 4
MAX_COLUMNS = 300                                    # columns listed for one table
MAX_KPIS = 40
MAX_PROMPT = 4000

TIME_WORDS = {"ly", "py", "ytd", "mtd", "qtd", "wtd", "last", "prior", "previous", "prev", "year", "month", "quarter",
              "week", "yoy", "mom", "qoq", "wow", "growth", "change", "delta", "trend", "rolling", "r12", "ttm", "l12m",
              "12m", "sply", "same", "period", "fy", "cy", "lw", "lm", "lq", "running", "cumulative", "cum", "history",
              "hist", "date", "to", "comparison", "pp"}
TARGET_WORDS = {"budget", "target", "plan", "forecast", "fcst", "goal", "achievement", "attainment", "bp", "gap"}
TIME_UNITS = {"day", "week", "month", "quarter", "year", "period", "fiscal", "calendar", "date"}
AGG_WORDS = {"count", "distinct", "number", "unique", "average", "avg", "mean", "all", "each", "every", "a", "an"}
EVENTS = {"order", "invoice", "transaction", "receipt", "ticket", "basket", "line", "order line", "shipment", "delivery",
          "payment", "claim", "visit", "encounter", "admission", "trip", "flight", "session", "event", "call", "case",
          "incident", "batch", "test", "date", "booking", "reservation", "application", "loan", "policy", "account"}
PREFERRED = ["region", "country", "state", "city", "division", "district", "banner", "location", "store", "site", "plant",
             "warehouse", "hospital", "depot", "channel", "department", "category", "subcategory", "brand", "product",
             "customer segment", "segment", "customer", "supplier", "employee"]
AUDIENCE = {"store": "store managers", "region": "regional managers", "district": "district managers",
            "division": "division leaders", "category": "category managers", "department": "department heads",
            "channel": "channel managers", "product": "product managers", "brand": "brand managers",
            "location": "site managers", "site": "site managers", "plant": "plant managers", "hospital": "hospital managers",
            "depot": "depot managers", "warehouse": "warehouse managers", "customer segment": "the customer teams",
            "customer": "the customer teams", "supplier": "the buying team", "employee": "team leads"}


class SuggestBody(BaseModel):
    uploads: list[str] = []
    prompt: str = ""


def _me() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in to D2D Relay.")
    if not auth.is_dev(u):
        raise HTTPException(403, "Your account cannot create dashboards in this organisation.")
    return u


def upload_file(uid: str, u: dict) -> tuple[Path, dict]:
    """One of the person's completed uploads: (its file, its meta.json). Someone else's, an unknown or a removed upload
    is not found (uploads._mine: it never says whose it is); one still arriving is a 409."""
    d, m = uploads._mine(str(uid or ""), u)          # noqa: SLF001 - the uploads' own ownership rule
    f = d / "file"
    if not m.get("done") or not f.is_file():
        raise HTTPException(409, f'"{m.get("name")}" has not finished uploading.')
    return f, m


# ---------------------------------------------------------------- reading the files

def _connect(tmp: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for s in ("SET autoinstall_known_extensions = false", "SET autoload_known_extensions = false",
              f"SET threads = {THREADS}", "SET memory_limit = '1GB'", f"SET temp_directory = {_lit(tmp)}"):
        con.execute(s)
    return con


def _day(v) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return None


def _cut(path: Path, size: int, tmp: Path) -> tuple[Path, int, bytes, bool]:
    """The file's first HEAD_BYTES, cut after its last whole line: (what to read, its bytes, the header line, cut?)."""
    with path.open("rb") as f:
        raw = f.read(HEAD_BYTES)
    header = raw.split(b"\n", 1)[0] + b"\n"
    if size <= HEAD_BYTES:
        return path, size, header, False
    nl = raw.rfind(b"\n")
    if nl <= 0:
        raise ValueError("its first line is longer than 8 MB")
    head = tmp / "head.csv"
    head.write_bytes(raw[:nl + 1])
    return head, nl + 1, header, True


def _tail(path: Path, size: int, header: bytes, tmp: Path) -> Path | None:
    """The file's last TAIL_BYTES with its header line, for where its dates end (None when it has no whole line)."""
    with path.open("rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        raw = f.read()
    nl = raw.find(b"\n")
    if nl < 0 or nl + 1 >= len(raw):
        return None
    tail = tmp / "tail.csv"
    tail.write_bytes(header + raw[nl + 1:])
    return tail


def _date_cols(con, src: str, names: list[str]) -> list[str]:
    """The date columns among names that src has (by DuckDB's own reading of src)."""
    have = {r[0]: str(r[1]).upper() for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
    return [c for c in names if have.get(c, "").startswith(("DATE", "TIMESTAMP"))]


def _scan(con, src: str, names: list[str]) -> tuple[int, dict[str, list[str | None]]]:
    """One pass over src: its rows and {column: [first day, last day]} of the date columns among names."""
    cols = _date_cols(con, src, names)
    row = con.execute("SELECT " + ", ".join(["COUNT(*)"] + [f"MIN({_q(c)}), MAX({_q(c)})" for c in cols]) + f" FROM {src}").fetchone()
    return int(row[0]), {c: [_day(row[1 + 2 * i]), _day(row[2 + 2 * i])] for i, c in enumerate(cols)}


def _merge(a: list, b: list) -> list:
    lo, hi = [x for x in (a[0], b[0]) if x], [x for x in (a[1], b[1]) if x]
    return [min(lo) if lo else None, max(hi) if hi else None]


def _about(x: float) -> int:
    """An estimate rounded to 3 significant digits (48,213,377 -> 48,200,000)."""
    x = int(round(x))
    k = max(0, len(str(abs(x))) - 3)
    return int(round(x, -k)) if k else x


def _profile(con, path: Path, size: int, tmp: Path, whole: bool) -> dict:
    """One CSV: {rows, estimated, columns: [{name, type, unique, distinct, nulls}], dates: {column: [from, to]}}."""
    head, head_bytes, header, cut = _cut(path, size, tmp)
    opts = "header = true, sample_size = -1" + (", ignore_errors = true" if cut else "")
    con.execute(f"CREATE OR REPLACE TEMP TABLE nd_head AS SELECT * FROM read_csv_auto({_lit(head)}, {opts})")
    n = con.execute("SELECT COUNT(*) FROM nd_head").fetchone()[0]
    described = con.execute("DESCRIBE nd_head").fetchall()
    cols = []
    if described:
        agg = ", ".join(f"COUNT({_q(r[0])}), COUNT(DISTINCT {_q(r[0])})" for r in described)
        stats = con.execute(f"SELECT {agg} FROM nd_head").fetchone()
        for i, r in enumerate(described):
            nonnull, distinct = int(stats[2 * i]), int(stats[2 * i + 1])
            cols.append({"name": r[0], "type": _kind(str(r[1])), "distinct": distinct, "nulls": int(n - nonnull),
                         "unique": bool(n) and nonnull == n and distinct == n})
    names = [c["name"] for c in cols if c["type"] == "date"]
    _, dates = _scan(con, "nd_head", names)
    rows, estimated = int(n), False
    if cut and whole:                       # read whole once: the exact row count and date range
        try:
            rows, full = _scan(con, f"read_csv_auto({_lit(path)}, header = true, ignore_errors = true)", names)
            dates = {c: _merge(dates.get(c) or [None, None], v) for c, v in full.items()} or dates
        except duckdb.Error:                # the head was readable: give the estimate rather than nothing
            rows, estimated = _about(n * size / max(1, head_bytes)), True
    elif cut:                               # estimated from the size, and the dates at the end of the file too
        rows, estimated = _about(n * size / max(1, head_bytes)), True
        tail = _tail(path, size, header, tmp) if names else None
        if tail is not None:
            try:
                _, end = _scan(con, f"read_csv_auto({_lit(tail)}, header = true, ignore_errors = true)", names)
                dates = {**dates, **{c: _merge(dates.get(c) or [None, None], v) for c, v in end.items()}}
            except duckdb.Error:
                pass
    con.execute("DROP TABLE IF EXISTS nd_head")
    return {"rows": rows, "estimated": estimated, "columns": cols, "dates": dates}


# ---------------------------------------------------------------- what the data supports

QUALIFIERS = {"net": 0, "gross": 1}                   # Net Sales stands for Sales and Revenue when the data has no plain Sales


def _key(text: str, drop: frozenset | set = frozenset()) -> tuple[str, ...]:
    """A name as compared: its words (ontology.words: abbreviations spelled out, plurals singular) without decorations
    such as amount, value or total (and without `drop`), sorted."""
    ws = O.words(text)
    core = tuple(sorted(w for w in ws if w not in O.DECOR and w not in drop))
    return core or tuple(sorted(ws))


def _term_names(t: dict) -> list[str]:
    return [t["name"]] + list(t.get("synonyms") or [])


def _and(items: list[str]) -> str:
    items = [str(x) for x in items if x]
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


class _Fit:
    """Which KPI entries the tagged data supports, and why."""

    def __init__(self, entries: list[dict], terms: list[dict], tags: dict[str, dict], has_date: bool):
        self.entries, self.has_date = entries, has_date
        by_name = {t["name"]: t for t in terms}
        self.have: dict[tuple, str] = {}             # name key -> what the data has: a term, or a "Sales budget"
        self.loose: dict[tuple, tuple[int, str]] = {}   # ("sales",) -> Net Sales, when the data has no plain Sales
        self.cols: dict[str, list[str]] = {}         # what the data has -> its columns ("file: column")
        self.kind: dict[str, str] = {}               # what the data has -> measure | key | date | attribute
        self.targets = False                         # a budget, target or plan column
        for ref, tg in tags.items():
            term, variant = tg["term"], (tg.get("variant") or "").strip()
            label = f"{term} {variant}" if variant else term       # sales_budget is a Sales budget, not Sales
            self.cols.setdefault(label, []).append(ref.replace("[", ": ", 1).rstrip("]"))
            self.kind.setdefault(label, tg["kind"])
            if variant:
                for v in set(variant.split()) & TARGET_WORDS:
                    self.targets = True
                    self.have.setdefault(_key(v), label)
                self.have.setdefault(_key(label), label)
                continue
            if set(O.words(term)) & TARGET_WORDS:
                self.targets = True
            for n in _term_names(by_name.get(term) or {"name": term}) + ([tg["entity"]] if tg.get("entity") else []):
                k = _key(n)
                self.have.setdefault(k, term)
                q = [w for w in k if w in QUALIFIERS]
                if tg["kind"] == "measure" and len(q) == 1 and len(k) > 1:
                    rest = tuple(w for w in k if w != q[0])
                    if rest not in self.loose or QUALIFIERS[q[0]] < self.loose[rest][0]:
                        self.loose[rest] = (QUALIFIERS[q[0]], term)
        self.kpi_of: dict[tuple, int] = {}
        for i, e in enumerate(entries):
            for n in [e["name"]] + list(e.get("synonyms") or []):
                self.kpi_of.setdefault(_key(n), i)
        self.matcher = K.Matcher(entries) if entries else None
        self.memo: dict[int, dict | None] = {}

    def _find(self, k: tuple) -> str | None:
        return self.have.get(k) or (self.loose.get(k) or (0, None))[1]

    def term(self, text: str, part: bool = False) -> str | None:
        """What the data has for a name (or, part=True, a piece of a formula: "count of distinct orders")."""
        return self._find(_key(text, AGG_WORDS if part else frozenset()))

    def resolve(self, text: str, depth: int) -> str | None:
        """What one name in a DAX reference or a formula is, when the data has it: a KPI that fits, a term, the dates."""
        text = text.strip()
        if not text:
            return None
        if re.fullmatch(r"[\d.,%\s]+", text):
            return text
        k = _key(text, AGG_WORDS)
        i = self.kpi_of.get(_key(text), self.kpi_of.get(k))
        if i is not None and self.fit(i, depth + 1):
            return self.entries[i]["name"]
        hit = self._find(k)
        if hit:
            return hit
        if k and set(k) <= TIME_UNITS and self.has_date:
            return "dates"
        return None

    def fit(self, i: int, depth: int = 0) -> dict | None:
        """{how, from, why} when entry i fits the data, else None."""
        if i in self.memo:
            return self.memo[i]
        if depth > 6:
            return None
        self.memo[i] = None                          # a KPI built from itself does not fit
        e = self.entries[i]
        out = None
        for n in [e["name"]] + list(e.get("synonyms") or []):
            got = self.term(n)
            if got:
                cols = ", ".join((self.cols.get(got) or [])[:2])
                said = f"counts each {got.lower()}" if self.kind.get(got) == "key" else f"the data has {got}"
                out = {"how": "term", "from": [got], "why": said + (f" ({cols})" if cols else "")}
                break
        if out is None and e.get("dax"):
            refs = list(dict.fromkeys(r.strip() for r in re.findall(r"\[([^\]]+)\]", str(e["dax"]))))
            got = [self.resolve(r, depth) for r in refs]
            if refs and all(got):
                names = list(dict.fromkeys(got))
                out = {"how": "built", "from": names, "why": "worked out from " + _and(names)}
        if out is None and e.get("formula") and not e.get("dax"):
            parts = [p for p in re.split(r"\s[-+*x]\s|[()/*+]|\bminus\b|\bplus\b|\bdivided by\b|\btimes\b|\bless\b",
                                         str(e["formula"]), flags=re.I) if p and p.strip()]
            got = [self.resolve(p, depth) for p in parts]
            if parts and all(got):
                names = [g for g in dict.fromkeys(got) if not re.fullmatch(r"[\d.,%\s]+", g)]
                out = {"how": "formula", "from": names, "why": "worked out from " + _and(names)}
        if out is None and self.matcher is not None:
            j, _, rest = self.matcher.match(e["name"], variants_only=True)
            words = set((rest or "").split())
            if j is not None and j != i and self.fit(j, depth + 1):
                base = self.entries[j]["name"]
                if words & TARGET_WORDS:
                    out = {"how": "target", "from": [base], "why": f"{base} against its budget or target"} if self.targets else None
                elif words & TIME_WORDS:
                    out = {"how": "time", "from": [base], "why": f"{base} compared over time"} if self.has_date else None
                elif not e.get("dax") and not e.get("formula"):      # a share or a rate needs what its own formula names
                    out = {"how": "variant", "from": [base], "why": f"another form of {base}"}
        self.memo[i] = out
        return out


CLASS = {"term": 0, "formula": 0, "built": 1, "variant": 2, "time": 3, "target": 3}


def _rank(kpis: list[dict], order: dict[str, int], said: set[str]) -> list[dict]:
    """The KPIs in the order to show them, the first ones marked lead: those the person named, then one of each role -
    the headline value (Net Sales), its margin or rate (Gross Margin %), the volume (Transactions), the average value
    (Average Basket Value), the growth (Sales Growth %) - and more up to six; then the rest. Among KPIs of one role, the
    one more KPIs are built from comes first (Net Sales before Discounts), then the data's own column order."""
    by = {k["name"]: k for k in kpis}
    used: dict[str, int] = {}
    for k in kpis:
        for x in k["from"]:
            if x in by and x != k["name"]:
                used[x] = used.get(x, 0) + 1
    roots: dict[str, int] = {}

    def root(k: dict, seen: tuple = ()) -> int:
        if k["name"] not in roots:
            got = [order.get(x, 999) if x not in by or x in seen else root(by[x], seen + (k["name"],)) for x in k["from"]]
            roots[k["name"]] = min(got or [999])
        return roots[k["name"]]

    def growth(k: dict) -> bool:
        return k["how"] == "built" and any(by[x]["how"] == "time" for x in k["from"] if x in by)

    def named(k: dict) -> bool:
        return any(set(O.words(n)) and set(O.words(n)) <= said for n in k["_names"])

    def key(k: dict) -> tuple:
        return (-used.get(k["name"], 0), root(k), k["_i"])

    roles = [lambda k: k.get("unit") == "currency" and k["how"] in ("term", "formula"),
             lambda k: k.get("unit") in ("percent", "ratio") and k["how"] in ("built", "formula") and not growth(k),
             lambda k: k.get("unit") == "count" and k["how"] in ("term", "formula"),
             lambda k: k.get("unit") == "currency" and k["how"] in ("built", "formula") and k.get("_agg") == "ratio",
             growth]
    lead = sorted((k for k in kpis if named(k)), key=key)[:6]
    for role in roles:
        pick = sorted((k for k in kpis if role(k) and k not in lead), key=key)
        if pick and len(lead) < 6:
            lead.append(pick[0])
    for k in sorted((k for k in kpis if k not in lead and k["how"] in ("term", "formula", "built")), key=key):
        if len(lead) >= 6:
            break
        lead.append(k)
    rest = sorted((k for k in kpis if k not in lead), key=lambda k: (CLASS[k["how"]],) + key(k))
    return [{**{f: v for f, v in k.items() if not f.startswith("_")}, "lead": k in lead} for k in lead + rest]


def _breakdowns(tables: list[dict], tags: dict[str, dict]) -> list[str]:
    """What the dashboard can be cut by: the attributes and the keys of things (stores, products), not of events."""
    found: list[str] = []
    for t in tables:
        for c in t["columns"]:
            tg = tags.get(f"{t['file']}[{c['name']}]")
            if not tg or tg.get("variant"):
                continue
            name, entity = tg["term"], tg.get("entity")
            if tg["kind"] == "attribute":
                if entity and re.search(r"\b(name|description|desc|title|label)$", name, re.I):
                    name = entity
            elif tg["kind"] == "key":
                name = entity or name
            else:
                continue
            low = name.lower()
            if low not in EVENTS and low not in found:
                found.append(low)
    rank = {n: i for i, n in enumerate(PREFERRED)}
    return sorted(found, key=lambda n: (rank.get(n, len(rank)), found.index(n)))[:6]


def _span(tables: list[dict]) -> tuple[int | None, bool]:
    """The days the biggest table's dates cover, and whether any table has a date column."""
    has = any(c["type"] == "date" for t in tables for c in t["columns"])
    for t in sorted(tables, key=lambda t: -(t.get("rows") or 0)):
        for lo, hi in (t.get("dates") or {}).values():
            if lo and hi:
                return (date.fromisoformat(hi) - date.fromisoformat(lo)).days, True
    return None, has


def _text(prompt: str, lead: list[str], measures: list[str], breakdowns: list[str], span: int | None,
          has_date: bool) -> str:
    """The request in plain words, for the person to change."""
    if lead:
        kpi_line = f"Lead with {_and(lead)}."
    elif measures:
        kpi_line = f"Lead with the main numbers in the data: {_and(measures[:5])}."
    else:
        kpi_line = "Lead with counts of the records in the data."
    by_line = f"Break them down by {_and(breakdowns)}." if breakdowns else ""
    if not has_date:
        time_line = "The data has no dates, so compare totals rather than trends."
    elif span is None:
        time_line = "Show the trend by month, and this year against last year where the data goes back that far."
    elif span >= 395:
        time_line = "Compare this year with last year, and show the trend by month."
    elif span >= 60:
        time_line = "Show the trend by week and by month."
    else:
        time_line = "Show the trend day by day."
    if prompt:
        return prompt + "\n\nFrom the data: " + " ".join(x for x in (kpi_line, by_line, time_line) if x)
    who = next((AUDIENCE[b] for b in breakdowns if b in AUDIENCE), "")
    act = f"which {breakdowns[0]}s are behind or ahead" if breakdowns else "where results are behind or ahead"
    lines = [f"A dashboard for the leadership team{' and ' + who if who else ''}.", kpi_line, by_line, time_line,
             f"Point out {act}, what is driving the change, and where to act first."]
    return "\n".join(x for x in lines if x)


def _why(e: Exception, name: str) -> str:
    """Why a file could not be read, in words and without the server's paths."""
    if isinstance(e, ValueError):
        return str(e)
    msg = re.sub(r'"/[^"]*"', f'"{name}"', (str(e).splitlines() or [""])[0])
    msg = re.sub(r"^[A-Z][A-Za-z ]* Error: ", "", msg).strip()[:200]
    return "it could not be read as a CSV" + (f" ({msg})" if msg else "")


def suggest_files(files: list[tuple[str, Path, str, int]], prompt: str = "") -> dict:
    """The suggestion for these uploads: [(upload id, its file, its name, its bytes)]."""
    started = time.monotonic()
    prompt = str(prompt or "").strip()[:MAX_PROMPT]
    tables, unreadable, skipped, taken = [], [], [], set()
    tmp = Path(tempfile.mkdtemp(prefix="d2d-suggest-"))
    try:
        con = _connect(tmp)
        for uid, path, name, size in files:
            if Path(name).suffix.lower() != ".csv":
                skipped.append(name)
                continue
            shown = name
            while shown in taken:                     # as main._stage names a second file of the same name
                shown = "_" + shown
            taken.add(shown)
            whole = size <= FULL_BYTES and time.monotonic() - started < BUDGET_S
            try:
                p = _profile(con, path, size, tmp, whole)
            except (duckdb.Error, ValueError, OSError) as e:
                unreadable.append({"file": shown, "upload": uid, "why": _why(e, shown)})
                continue
            tables.append({"file": shown, "upload": uid, "bytes": size, **p})
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    terms = ontology.effective_terms()
    tags = O.tag_tables(tables, terms)["tags"] if tables else {}
    span, has_date = _span(tables)
    has_date = has_date or any(t["kind"] == "date" for t in tags.values())
    entries, source = ontology.kpis(), "dictionary"
    if not entries:                                   # no dictionary of its own yet: the general pack's KPIs
        try:
            entries, source = O.pack("general")["kpis"], "general"
        except O.OntologyError:
            entries = []
    fit = _Fit(entries, terms, tags, has_date)
    order: dict[str, int] = {}
    measures: list[str] = []
    for t in tables:
        for c in t["columns"]:
            tg = tags.get(f"{t['file']}[{c['name']}]")
            if tg:
                order.setdefault(f"{tg['term']} {tg['variant']}" if tg.get("variant") else tg["term"], len(order))
            if tg and tg["kind"] == "measure" and not tg.get("variant"):
                measures.append(tg["term"])
            elif not tg and c["type"] in ("int", "decimal") and not c["unique"] \
                    and not (O.KEY_WORDS | O.DATE_WORDS) & set(O.words(c["name"])):
                measures.append(" ".join(O.words(c["name"])) or c["name"])
    measures = list(dict.fromkeys(measures))
    found = []
    for i, e in enumerate(entries):
        f = fit.fit(i)
        if f:
            found.append({"name": e["name"], **{k: e[k] for k in ("definition", "unit", "domain") if e.get(k)}, **f,
                          "_i": i, "_agg": e.get("aggregation"), "_names": [e["name"]] + list(e.get("synonyms") or [])})
    kpis = _rank(found, order, set(O.words(prompt)))[:MAX_KPIS]
    lead = [k["name"] for k in kpis if k["lead"]]
    breakdowns = _breakdowns(tables, tags)
    head = lead[0] if lead else measures[0] if measures else ""
    name = f"{head[:1].upper()}{head[1:]} performance" if head else \
        Path(tables[0]["file"]).stem.replace("_", " ").strip().title() if tables else ""

    def column(t: dict, c: dict) -> dict:
        tg = tags.get(f"{t['file']}[{c['name']}]")
        return {"name": c["name"], "type": c["type"], **({"term": tg["term"], "kind": tg["kind"]} if tg else {}),
                **({"variant": tg["variant"]} if tg and tg.get("variant") else {})}
    return {
        "suggestion": _text(prompt, lead, [m.lower() for m in measures], breakdowns, span, has_date) if tables else prompt,
        "name_suggestion": name,
        "tables": [{"file": t["file"], "upload": t["upload"], "bytes": t["bytes"], "rows": t["rows"], "estimated": t["estimated"],
                    "columns": [column(t, c) for c in t["columns"][:MAX_COLUMNS]],
                    "more_columns": max(0, len(t["columns"]) - MAX_COLUMNS),
                    "dates": {c: {"from": lo, "to": hi} for c, (lo, hi) in (t.get("dates") or {}).items()}}
                   for t in tables],
        "kpis": kpis, "kpi_source": source, "dictionary": len(entries) if source == "dictionary" else 0,
        "breakdowns": breakdowns, "industry": ontology.industry_name(), "unreadable": unreadable, "skipped": skipped,
        "seconds": round(time.monotonic() - started, 2)}


@router.post("/api/projects/suggest")
def suggest(body: SuggestBody):
    """What to build, prefilled from the person's uploaded CSVs (New dashboard, step 3). Free; nothing is saved."""
    u = _me()
    ids = list(dict.fromkeys(i.strip() for i in body.uploads if isinstance(i, str) and i.strip()))
    if not ids:
        raise HTTPException(400, "Upload at least one CSV file first.")
    if len(ids) > MAX_FILES:
        raise HTTPException(400, f"Relay reads up to {MAX_FILES} files at a time.")
    picked = []
    for uid in ids:                                   # every id is checked before any file is read
        f, m = upload_file(uid, u)
        picked.append((uid, f, str(m.get("name") or "data.csv"), int(m.get("size") or f.stat().st_size)))
    return suggest_files(picked, body.prompt)
