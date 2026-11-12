"""Data quality & reconciliation - the rules, rules first: profiles, suggestions from what the data shows, the rule
kinds and their checks, the Excel tie-out reader and the exports to dbt tests, Soda checks and Great Expectations.

A rule is a record a person can read and edit:
  {"id", "kind", "dataset" (a dataset key), "column", "check" (the plain-text parameter), "severity" (high | medium |
   low), "active", "description", "why", "origin" (profile | tie-out | person | agent | ruleset)}
`check` per kind:
  not_null        blank, or "allow 5" (that many blanks are fine)
  unique          blank - `column` may name several columns, comma-separated
  range           "0..1000", ">= 0", "<= 100", or "in Open, Closed" (accepted values)
  referential     "in customers.customer_id" (every value exists in that dataset's column)
  freshness       "48 h" or "2 days" (the newest value is at most that old)
  business_total  "sum = 1250000 ± 0.5%" (also count / avg / min / max), optionally "where region = North"
  reconcile       "with SALES.ORDERS on order_id; totals amount, tax; by region; sample 20"
Checks are SQL in DuckDB's dialect run through the readers of observe_checks (DuckDB for uploads; the guarded,
read-only live query for warehouses, transpiled by sqlglot); platforms read as records are checked in Python.
Reconciliation uses the workbench's proof checks (row counts, checksums, business totals, sample diffs).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

from .. import observe_checks as oc
from .. import workbench as wb

KINDS = {"not_null": "Not null", "unique": "Unique", "range": "Range or accepted values", "referential": "Exists in (referential)",
         "freshness": "Freshness", "business_total": "Business total", "reconcile": "Reconciliation"}
SEVERITIES = ("high", "medium", "low")
CHECK_HELP = ("not null: blank or \"allow 5\" - unique: blank (several columns comma-separated) - range: \"0..1000\", \">= 0\" or \"in Open, Closed\" - "
              "exists in: \"in customers.customer_id\" - freshness: \"48 h\" - total: \"sum = 1250000 ± 0.5%\" - reconcile: \"with SALES.ORDERS on order_id; totals amount\"")
MONEY = re.compile(r"(amount|price|total|value|revenue|sales|cost|qty|quantity|net|gross|balance|tax|spend|fee)", re.I)
KEYISH = re.compile(r"(^id$|_id$|^key$|_key$|_code$|^code$|_no$|_num$|_number$|_ref$)", re.I)
DATEISH = re.compile(r"(date|_at$|_on$|^ts$|timestamp|updated|loaded|created|_day$)", re.I)
AGGS = ("sum", "count", "avg", "min", "max")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40] or "x"


# ------------------------------------------------------------------ datasets

def dkey(ref: dict) -> str:
    if ref["source"] == "file":
        return f"file:{ref.get('item')}:{ref['file']}"
    return f"conn:{ref['connection']}:{ref['object']}"


def dataset(ref: dict, name: str, label: str, where: str = "") -> dict:
    return {"key": dkey(ref), "name": name, "label": label, "ref": ref, "where": where}


def is_tieout(path: Path) -> bool:
    """An Excel tie-out workbook: its header names an `expected` column (it holds figures to check, not data)."""
    try:
        import openpyxl
        wbk = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wbk.worksheets[0]
        head = next(ws.iter_rows(values_only=True, max_row=1), ()) or ()
        wbk.close()
        return any(str(h or "").strip().lower() == "expected" for h in head)
    except Exception:  # noqa: BLE001
        return False


def tieouts(ctx) -> list[dict]:
    """Business-total rules from the Excel tie-outs the person uploaded (one rule per row, the row cited)."""
    out = []
    for f in ctx.files((".xlsx",)):
        p = ctx.dir / "data" / f["name"]
        if not is_tieout(p):
            continue
        import openpyxl
        wbk = openpyxl.load_workbook(p, read_only=True, data_only=True)
        ws = wbk.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        wbk.close()
        head = [str(h or "").strip().lower() for h in rows[0]]
        col = lambda *names: next((head.index(n) for n in names if n in head), None)  # noqa: E731
        it, ic, ia, ie, itol, ig, iv = col("table", "dataset"), col("column"), col("aggregate", "agg"), col("expected"), col("tolerance", "tolerance %", "tolerance_pct"), col("where_column", "group_column"), col("where_value", "group_value")
        for n, r in enumerate(rows[1:], 2):
            if not r or ie is None or r[ie] in (None, ""):
                continue
            agg = str(r[ia] or "sum").strip().lower() if ia is not None else "sum"
            tol = r[itol] if itol is not None and r[itol] not in (None, "") else 0.5
            check = f"{agg} = {r[ie]} ± {tol}%"
            if ig is not None and r[ig] not in (None, "") and iv is not None:
                check += f" where {r[ig]} = {r[iv]}"
            out.append({"id": f"business_total-{slug(r[it] if it is not None else 'x')}-{slug(r[ic] if ic is not None else 'x')}-{n}", "kind": "business_total",
                        "dataset_name": str(r[it] or "").strip() if it is not None else "", "column": str(r[ic] or "").strip() if ic is not None else "", "check": check,
                        "severity": "high", "active": True, "description": "", "why": f"tie-out {f['name']}, row {n}", "origin": "tie-out"})
    return out


# ------------------------------------------------------------------ profiles and suggestions

def profile(r, max_columns: int = 40) -> dict:
    cols = r.columns()[:max_columns]
    stats = r.stats(cols, 5, max_columns)
    out = {"rows": stats.get("rows") or 0, "columns": []}
    for c in cols:
        s = stats["columns"].get(c["name"]) or {}
        out["columns"].append({"name": c["name"], "kind": c["kind"], **{k: s.get(k) for k in ("nulls", "null_pct", "distinct", "unique", "min", "max", "mean", "sum")},
                               "top": s.get("top")})
    return out


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1e15 else f"{v:.3g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _num(v):
    return oc._num(v)


def _parse_time(v) -> dt.datetime | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day, tzinfo=dt.timezone.utc) + dt.timedelta(days=1)       # a date is fresh until its day ends
    s = str(v).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            d = dt.date.fromisoformat(s)
            return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def suggest(ds: dict, prof: dict, all_ds: list[tuple[dict, dict]], now: float) -> list[dict]:
    """Rules from what the data shows today, each with the reason (rules first: no AI, nothing invented - a business
    total waits for the person's figure)."""
    out, n = [], prof["rows"]
    name = ds["name"]

    def rule(kind, column, check, severity, why, active=True):
        out.append({"id": f"{kind}-{slug(name)}-{slug(column)}", "kind": kind, "dataset": ds["key"], "column": column, "check": check, "severity": severity,
                    "active": active, "description": "", "why": why, "origin": "profile"})
    if not n:
        return out
    for c in prof["columns"]:
        col, kind = c["name"], c["kind"]
        nn = n - (c.get("nulls") or 0)
        keyish, dateish, money = bool(KEYISH.search(col)), bool(DATEISH.search(col)) or kind == "date", bool(MONEY.search(col))
        if not c.get("nulls"):
            rule("not_null", col, "", "high" if keyish or dateish else "medium", f"no blanks in {n:,} rows today")
        elif keyish:
            rule("not_null", col, "", "high", f"{c['nulls']:,} blank(s) in a key column ({c.get('null_pct')} %) - the rule fails until they are filled")
        elif (c.get("null_pct") if c.get("null_pct") is not None else 100) < 5:
            rule("not_null", col, "", "medium", f"{c['nulls']:,} blank(s) in {n:,} rows ({c.get('null_pct')} %) - few enough to be a mistake; the rule fails until they are filled")
        if keyish and c.get("distinct") is not None and nn > 1:
            if c["distinct"] == nn:
                rule("unique", col, "", "high", f"every one of the {nn:,} values is different")
            elif not _refers(col, ds, all_ds):
                rule("unique", col, "", "high", f"{nn - c['distinct']:,} repeated value(s) in a key column - the rule fails until they are fixed")
        if kind in ("int", "decimal") and c.get("min") is not None and not keyish:
            lo, hi = _num(c["min"]), _num(c["max"])
            if money:
                rule("range", col, ">= 0", "medium", "never negative today" if lo >= 0 else f"{_fmt(lo)} is the smallest value today: negative amounts are usually an error")
            elif lo is not None and hi is not None:
                rule("range", col, f"{_fmt_num(math.floor(lo))}..{_fmt_num(math.ceil(hi))}", "low", f"the values today run from {_fmt(lo)} to {_fmt(hi)}")
        if kind == "string" and c.get("top") and c.get("distinct") and 1 < c["distinct"] <= 8 and not keyish and nn >= 20:
            vals = [t[0] for t in c["top"]]
            if len(vals) == c["distinct"]:
                rule("range", col, "in " + ", ".join(vals), "low", f"only these {len(vals)} values today")
        if dateish and c.get("max"):
            t = _parse_time(c["max"])
            if t:
                age_h = max(0.0, (now - t.timestamp()) / 3600)
                if age_h <= 24 * 7:
                    rule("freshness", col, f"{max(48, int(math.ceil(age_h * 2 / 24)) * 24)} h", "medium", f"the newest value is {_age(age_h)} old")
                else:
                    rule("freshness", col, "48 h", "medium", f"the newest value is {_age(age_h)} old - stale for a daily load, or a history table (switch it off)", active=False)
        if money and kind in ("int", "decimal"):
            rule("business_total", col, "sum = ? ± 0.5%", "high", "a total to tie out against the finance figure - enter it (or upload an Excel tie-out)", active=False)
    for c in prof["columns"]:                                    # referential: a key column that is another dataset's unique key
        if not KEYISH.search(c["name"]) or c.get("unique"):
            continue
        cands = [(o, x) for o, op in all_ds if o["key"] != ds["key"] for x in op["columns"] if x["name"].lower() == c["name"].lower() and x.get("unique")]
        if not cands:
            continue
        cands.sort(key=lambda t: 0 if _place(t[0]) == _place(ds) else 1)       # the dimension in the same place first
        oc_, other = cands[0]
        out.append({"id": f"referential-{slug(name)}-{slug(c['name'])}", "kind": "referential", "dataset": ds["key"], "column": c["name"],
                    "check": f"in {oc_['name']}.{other['name']}", "severity": "high", "active": True, "description": "",
                    "why": f"{c['name']} is the unique key of {oc_['name']}: every value here should exist there", "origin": "profile"})
    return out


def _place(d: dict) -> tuple:
    r = d["ref"]
    return ("conn", r.get("connection")) if r["source"] == "connection" else ("file", r.get("item"))


def _refers(col: str, ds: dict, all_ds) -> bool:
    return any(o["key"] != ds["key"] and any(x["name"].lower() == col.lower() and x.get("unique") for x in p["columns"]) for o, p in all_ds)


def _fmt_num(v) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _age(h: float) -> str:
    return f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} days"


def reconcile_suggestions(dsets: list[dict], profiles: dict) -> list[dict]:
    """Two datasets with the same name in different places (an upload and a warehouse table, two engines): reconcile
    the target against the source on their shared unique key and numeric columns."""
    out = []
    by = {}
    for d in dsets:
        by.setdefault(d["name"].split(".")[-1].lower().replace(".xlsx", "").replace(".csv", "").replace(".parquet", ""), []).append(d)
    for stem, group in by.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda d: 0 if d["ref"]["source"] == "file" else 1)   # an upload is the extract a copy is proven against
        src, tgt = group[0], group[1]
        ps, pt = profiles.get(src["key"]), profiles.get(tgt["key"])
        if not ps or not pt:
            continue
        cols_t = {c["name"].lower(): c for c in pt["columns"]}
        keys = [c["name"] for c in ps["columns"] if c.get("unique") and c["name"].lower() in cols_t]
        nums = [c["name"] for c in ps["columns"] if c["kind"] in ("int", "decimal") and c["name"].lower() in cols_t and not KEYISH.search(c["name"])]
        if not keys:
            continue
        check = f"with {tgt['name']} on {keys[0]}" + (f"; totals {', '.join(nums[:4])}" if nums else "")
        out.append({"id": f"reconcile-{slug(src['name'])}-{slug(tgt['name'])}", "kind": "reconcile", "dataset": src["key"], "column": "", "check": check, "severity": "high",
                    "active": True, "description": "", "why": f"{src['label']} and {tgt['label']} hold the same table: prove they agree", "origin": "profile"})
    return out


# ------------------------------------------------------------------ parsing a rule (rules first: refuse what cannot run)

def parse(rule: dict, dsets: dict[str, dict]) -> tuple[dict, list[str]]:
    """{params}, [problems] for one rule against the item's datasets (key -> dataset)."""
    k, chk, col = rule.get("kind"), str(rule.get("check") or "").strip(), str(rule.get("column") or "").strip()
    where = f"{KINDS.get(k, k)} on {col or '-'}"
    probs: list[str] = []
    if k not in KINDS:
        return {}, [f"unknown kind {k!r}"]
    ds = dsets.get(rule.get("dataset") or "")
    if not ds:
        return {}, [f"{where}: pick one of the datasets"]
    names = {d["name"].lower(): d for d in dsets.values()}
    p: dict = {"columns": [c.strip() for c in col.split(",") if c.strip()]}
    if k != "reconcile" and not p["columns"]:
        probs.append(f"{where}: name the column")
    if k == "not_null":
        m = re.fullmatch(r"(?:allow\s+(\d+))?", chk, re.I)
        if not m:
            probs.append(f"{where}: write nothing, or \"allow 5\"")
        else:
            p["allow"] = int(m.group(1) or 0)
    elif k == "unique":
        if chk:
            probs.append(f"{where}: leave the check blank - list several columns in Column, comma-separated")
    elif k == "range":
        m = re.fullmatch(r"(-?[\d.,]+)\s*\.\.\s*(-?[\d.,]+)", chk)
        if m:
            p["min"], p["max"] = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
            if p["min"] > p["max"]:
                probs.append(f"{where}: the minimum is above the maximum")
        elif re.fullmatch(r">=\s*-?[\d.,]+", chk):
            p["min"] = float(chk.split(">=")[1].replace(",", ""))
        elif re.fullmatch(r"<=\s*-?[\d.,]+", chk):
            p["max"] = float(chk.split("<=")[1].replace(",", ""))
        elif chk.lower().startswith("in "):
            p["values"] = [v.strip() for v in chk[3:].split(",") if v.strip()]
            if not p["values"]:
                probs.append(f"{where}: list the accepted values after \"in\"")
        else:
            probs.append(f"{where}: write \"0..1000\", \">= 0\", \"<= 100\" or \"in A, B, C\"")
    elif k == "referential":
        m = re.fullmatch(r"in\s+(.+)\.([^.\s]+)", chk, re.I)
        if not m:
            probs.append(f"{where}: write \"in <dataset>.<column>\"")
        else:
            other = names.get(m.group(1).strip().lower())
            if not other:
                probs.append(f"{where}: {m.group(1).strip()} is not one of this item's datasets ({', '.join(sorted(names))[:200]})")
            else:
                p["ref_dataset"], p["ref_column"] = other["key"], m.group(2).strip()
    elif k == "freshness":
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|hours?|d|days?)", chk, re.I)
        if not m:
            probs.append(f"{where}: write \"48 h\" or \"2 days\"")
        else:
            p["max_age_h"] = float(m.group(1)) * (24 if m.group(2).lower().startswith("d") else 1)
    elif k == "business_total":
        m = re.fullmatch(r"(sum|count|avg|min|max)\s*=\s*(-?[\d.,]+|\?)\s*(?:±\s*([\d.]+)\s*%)?(?:\s+where\s+(\S+)\s*=\s*(.+))?", chk, re.I)
        if not m:
            probs.append(f"{where}: write \"sum = 1250000 ± 0.5%\", optionally \"where region = North\"")
        elif m.group(2) == "?":
            if rule.get("active"):
                probs.append(f"{where}: enter the expected figure (from your tie-out) before switching it on")
            p.update(agg=m.group(1).lower(), expected=None)
        else:
            p.update(agg=m.group(1).lower(), expected=float(m.group(2).replace(",", "")), tolerance_pct=float(m.group(3) or 0),
                     where_column=m.group(4), where_value=(m.group(5) or "").strip() or None)
    elif k == "reconcile":
        parts = [x.strip() for x in chk.split(";") if x.strip()]
        m = re.fullmatch(r"with\s+(.+?)\s+on\s+(.+)", parts[0] if parts else "", re.I)
        if not m:
            probs.append(f"{where}: write \"with <target dataset> on <key>[; totals <columns>][; by <column>]\"")
        else:
            tgt = names.get(m.group(1).strip().lower())
            if not tgt:
                probs.append(f"Reconciliation: {m.group(1).strip()} is not one of this item's datasets")
            elif tgt["key"] == ds["key"]:
                probs.append("Reconciliation: the target must be another dataset")
            else:
                p.update(target=tgt["key"], keys=[x.strip() for x in m.group(2).split(",") if x.strip()], measures=[], by=None, sample=20)
                for part in parts[1:]:
                    if part.lower().startswith("totals "):
                        p["measures"] = [x.strip() for x in part[7:].split(",") if x.strip()]
                    elif part.lower().startswith("by "):
                        p["by"] = part[3:].strip()
                    elif part.lower().startswith("sample "):
                        try:
                            p["sample"] = max(1, min(200, int(part[7:].strip())))
                        except ValueError:
                            probs.append("Reconciliation: \"sample 20\" takes a number")
                    else:
                        probs.append(f"Reconciliation: \"{part}\" is not \"totals ...\", \"by ...\" or \"sample ...\"")
    if rule.get("severity") not in SEVERITIES:
        probs.append(f"{where}: severity is high, medium or low")
    return p, probs


def validate(rules: list[dict], dsets: dict[str, dict]) -> list[str]:
    """The problems of the rules that are on (a rule switched off may stay unfinished)."""
    out = []
    seen = set()
    for r in rules:
        if not r.get("active"):
            continue
        _, probs = parse(r, dsets)
        out += probs
        key = (r.get("kind"), r.get("dataset"), str(r.get("column") or "").lower(), str(r.get("check") or "").lower())
        if key in seen and r.get("active"):
            out.append(f"{KINDS.get(r.get('kind'), r.get('kind'))} on {r.get('column')}: the same rule is there twice")
        seen.add(key)
    return out


# ------------------------------------------------------------------ evaluating rules

class Readers:
    """One reader per dataset for a run of checks (closed at the end)."""

    def __init__(self, ctx, dsets: dict[str, dict]):
        self.ctx, self.dsets, self.open = ctx, dsets, {}

    def get(self, key: str):
        if key not in self.open:
            self.open[key] = self.ctx.reader(self.dsets[key]["ref"])
        return self.open[key]

    def close(self):
        for r in self.open.values():
            wb._close(r)
        self.open.clear()


def _cname(r, name: str) -> str:
    cols = {c["name"].lower(): c["name"] for c in r.columns()}
    if name.lower() not in cols:
        raise oc.ReadError(f"there is no column {name} (it has {', '.join(list(cols.values())[:12])})")
    return cols[name.lower()]


def _rows(r) -> list[dict]:
    return r._read().get("rows") or []


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _sample(r, sql: str) -> list[dict]:
    try:
        return [{k: wb._norm(v) for k, v in row.items()} for row in r.run(sql)[:5]]
    except oc.ReadError:
        return []


def evaluate(ctx, rule: dict, params: dict, rd: Readers, now: float) -> dict:
    """One rule against the data now: {"status": pass | fail | error, "measured", "expected", "detail", "bad", "sample"}."""
    k = rule["kind"]
    out = {"status": "error", "measured": None, "expected": None, "detail": "", "bad": None, "sample": []}
    try:
        r = rd.get(rule["dataset"])
        t = wb.table_sql(r) if not isinstance(r, oc.SdkReader) else None
        cols = [_cname(r, c) for c in params.get("columns") or []] if k != "reconcile" else []
        q = oc._q(cols[0]) if cols else None
        if k == "not_null":
            kind = next((c["kind"] for c in r.columns() if c["name"] == cols[0]), "string")
            if t:
                blank = f"{q} IS NULL" + (f" OR TRIM(CAST({q} AS VARCHAR)) = ''" if kind == "string" else "")
                row = r.run(f"SELECT COUNT(*) AS n, SUM(CASE WHEN {blank} THEN 1 ELSE 0 END) AS bad FROM {t}")[0]
                n, bad = int(row.get("n") or 0), int(row.get("bad") or 0)
                out["sample"] = _sample(r, f"SELECT * FROM {t} WHERE {blank} LIMIT 5") if bad else []
            else:
                rows = _rows(r)
                n, bad = len(rows), sum(1 for x in rows if x.get(cols[0]) in (None, ""))
            ok = bad <= params.get("allow", 0)
            out.update(status="pass" if ok else "fail", measured=f"{bad:,} blank", expected=f"at most {params.get('allow', 0)}", bad=bad, detail=f"{bad:,} of {n:,} rows have no {cols[0]}")
        elif k == "unique":
            if t:
                kexpr = f"CONCAT_WS('|', {', '.join('CAST(' + oc._q(c) + ' AS VARCHAR)' for c in cols)})" if len(cols) > 1 else q
                row = r.run(f"SELECT COUNT({kexpr}) AS n, COUNT({kexpr}) - COUNT(DISTINCT {kexpr}) AS bad FROM {t}")[0]
                n, bad = int(row.get("n") or 0), int(row.get("bad") or 0)
                cl = ", ".join(oc._q(c) for c in cols)
                out["sample"] = _sample(r, f"SELECT {cl}, COUNT(*) AS copies FROM {t} GROUP BY {cl} HAVING COUNT(*) > 1 ORDER BY copies DESC LIMIT 5") if bad else []
            else:
                vals = [tuple(str(x.get(c)) for c in cols) for x in _rows(r) if all(x.get(c) not in (None, "") for c in cols)]
                n, bad = len(vals), len(vals) - len(set(vals))
            out.update(status="pass" if not bad else "fail", measured=f"{bad:,} repeated", expected="0", bad=bad, detail=f"{bad:,} repeated value(s) among {n:,} in {', '.join(cols)}")
        elif k == "range":
            if params.get("values") is not None:
                lits = ", ".join(_lit(v) for v in params["values"])
                cond = f"{q} IS NOT NULL AND CAST({q} AS VARCHAR) NOT IN ({lits})"
                expect = "one of " + ", ".join(params["values"])[:120]
            else:
                parts = []
                if params.get("min") is not None:
                    parts.append(f"CAST({q} AS DOUBLE) < {params['min']}")
                if params.get("max") is not None:
                    parts.append(f"CAST({q} AS DOUBLE) > {params['max']}")
                cond = f"{q} IS NOT NULL AND (" + " OR ".join(parts) + ")"
                expect = rule["check"]
            if t:
                row = r.run(f"SELECT COUNT({q}) AS n, SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS bad FROM {t}")[0]
                n, bad = int(row.get("n") or 0), int(row.get("bad") or 0)
                out["sample"] = _sample(r, f"SELECT * FROM {t} WHERE {cond} LIMIT 5") if bad else []
            else:
                vals = [x.get(cols[0]) for x in _rows(r) if x.get(cols[0]) not in (None, "")]
                if params.get("values") is not None:
                    bad = sum(1 for v in vals if str(v) not in params["values"])
                else:
                    nums = [_num(v) for v in vals]
                    bad = sum(1 for v in nums if v is None or (params.get("min") is not None and v < params["min"]) or (params.get("max") is not None and v > params["max"]))
                n = len(vals)
            out.update(status="pass" if not bad else "fail", measured=f"{bad:,} outside", expected=expect, bad=bad, detail=f"{bad:,} of {n:,} values of {cols[0]} outside {expect}")
        elif k == "referential":
            r2 = rd.get(params["ref_dataset"])
            c2 = _cname(r2, params["ref_column"])
            a_ref, b_ref = rd.dsets[rule["dataset"]]["ref"], rd.dsets[params["ref_dataset"]]["ref"]
            same = (a_ref["source"] == b_ref["source"] == "file" and a_ref.get("item") == b_ref.get("item")) or \
                   (a_ref["source"] == b_ref["source"] == "connection" and a_ref["connection"] == b_ref["connection"] and isinstance(r, oc.SqlReader))
            if same:
                t2 = wb.table_sql(r2)
                base = f"FROM {t} a LEFT JOIN (SELECT DISTINCT CAST({oc._q(c2)} AS VARCHAR) AS k FROM {t2}) b ON CAST(a.{q} AS VARCHAR) = b.k WHERE a.{q} IS NOT NULL"
                row = r.run(f"SELECT COUNT(*) AS n, SUM(CASE WHEN b.k IS NULL THEN 1 ELSE 0 END) AS bad {base}")[0]
                n, bad = int(row.get("n") or 0), int(row.get("bad") or 0)
                out["sample"] = _sample(r, f"SELECT DISTINCT a.{q} AS missing {base} AND b.k IS NULL LIMIT 5") if bad else []
                note = ""
            else:
                def distinct(rr, col):
                    if isinstance(rr, oc.SdkReader):
                        return {str(wb._norm(x.get(col))) for x in _rows(rr) if x.get(col) not in (None, "")}
                    return {str(wb._norm(x.get("v"))) for x in rr.run(f"SELECT DISTINCT {oc._q(col)} AS v FROM {wb.table_sql(rr)} WHERE {oc._q(col)} IS NOT NULL")}
                va, vb = distinct(r, cols[0]), distinct(r2, c2)
                missing = sorted(va - vb)
                n, bad = len(va), len(missing)
                out["sample"] = [{"missing": m} for m in missing[:5]]
                note = " (compared as distinct values: the two datasets live in different places)" + (" - the first 10,000 distinct values were compared" if max(len(va), len(vb)) >= 10000 else "")
            out.update(status="pass" if not bad else "fail", measured=f"{bad:,} not found", expected="0", bad=bad,
                       detail=f"{bad:,} {'row' if same else 'value'}(s) of {cols[0]} have no match in {rd.dsets[params['ref_dataset']]['name']}.{c2}" + note)
        elif k == "freshness":
            if t:
                m = r.run(f"SELECT MAX({q}) AS m FROM {t}")[0].get("m")
            else:
                vals = [x.get(cols[0]) for x in _rows(r) if x.get(cols[0])]
                m = max(vals, key=str) if vals else None
            ts = _parse_time(m)
            if not ts:
                out.update(status="fail", detail=f"{cols[0]} holds no date the check can read ({m!r})")
            else:
                age = max(0.0, (now - ts.timestamp()) / 3600)
                ok = age <= params["max_age_h"]
                out.update(status="pass" if ok else "fail", measured=_age(age), expected=f"at most {_age(params['max_age_h'])}", bad=0 if ok else 1,
                           detail=f"the newest {cols[0]} is {wb._norm(m)} - {_age(age)} old")
        elif k == "business_total":
            if params.get("expected") is None:
                out.update(status="skip", detail="no expected figure yet")
                return out
            agg = params["agg"]
            expr = "COUNT(*)" if agg == "count" else f"{agg.upper()}(CAST({q} AS DOUBLE))"
            wcol = _cname(r, params["where_column"]) if params.get("where_column") else None
            if t:
                sql = f"SELECT {expr} AS v FROM {t}" + (f" WHERE CAST({oc._q(wcol)} AS VARCHAR) = {_lit(params['where_value'])}" if wcol else "")
                v = _num(r.run(sql)[0].get("v")) or 0.0
            else:
                rows = [x for x in _rows(r) if not wcol or str(x.get(wcol)) == params["where_value"]]
                nums = [_num(x.get(cols[0])) for x in rows if _num(x.get(cols[0])) is not None]
                v = {"sum": sum(nums), "count": len(rows), "avg": (sum(nums) / len(nums)) if nums else 0.0, "min": min(nums, default=0.0), "max": max(nums, default=0.0)}[agg]
            exp, tol = params["expected"], params.get("tolerance_pct") or 0
            ok = abs(v - exp) <= max(0.005, abs(exp) * tol / 100.0)
            out.update(status="pass" if ok else "fail", measured=_fmt(round(v, 2)), expected=f"{_fmt(exp)} ± {tol:g} %", bad=0 if ok else 1,
                       detail=f"{agg} of {cols[0]}" + (f" where {wcol} = {params['where_value']}" if wcol else "") + f" is {_fmt(round(v, 2))}; the figure to tie out to is {_fmt(exp)}"
                       + ("" if ok else f" - off by {_fmt(round(v - exp, 2))}"))
        elif k == "reconcile":
            src, tgt = rd.dsets[rule["dataset"]]["ref"], rd.dsets[params["target"]]["ref"]
            checks = [ctx.proof("row_count", source=src, target=tgt), ctx.proof("checksum", source=src, target=tgt)]
            if params.get("measures"):
                checks.append(ctx.proof("totals", source=src, target=tgt, measures=params["measures"], by=params.get("by")))
            checks.append(ctx.proof("sample_diff", source=src, target=tgt, keys=params["keys"], n=params.get("sample") or 20))
            bad = [c for c in checks if c["status"] == "fail"]
            out.update(status="fail" if bad else "pass", measured=f"{len(checks) - len(bad)} of {len(checks)} agree", expected="all agree", bad=len(bad),
                       detail="; ".join(f"{c['label']}: {c['detail']}" for c in checks)[:900], parts=checks)
    except oc.ReadError as e:
        out.update(status="error", detail=f"could not check: {e}")
    except wb.StepFailed as e:
        out.update(status="error", detail=str(e))
    return out


def run_rules(ctx, rules: list[dict], dsets: dict[str, dict], now: float, label: str = "check") -> list[dict]:
    """Every active rule now; each result is stored as evidence and returned as a gate row."""
    rd = Readers(ctx, dsets)
    rows = []
    try:
        for r in rules:
            if not r.get("active"):
                continue
            params, probs = parse(r, dsets)
            if probs:
                res = {"status": "error", "detail": "; ".join(probs)}
            else:
                res = evaluate(ctx, r, params, rd, now)
            ds = dsets.get(r.get("dataset") or "", {})
            gate = {"name": r["id"], "label": f"{KINDS[r['kind']]} - {ds.get('name', '?')}" + (f".{r['column']}" if r.get("column") else ""), "status": res["status"],
                    "measured": res.get("measured"), "expected": res.get("expected"), "detail": res.get("detail") or "", "severity": r.get("severity"), "kind": r["kind"],
                    "dataset": r.get("dataset"), "column": r.get("column"), "parts": [{k: p.get(k) for k in ("label", "status", "detail", "evidence")} for p in res.get("parts") or []]}
            gate["evidence"] = ctx.evidence(f"{label}: {gate['label']}", {"rule": r, "params": params, "result": {k: v for k, v in res.items() if k != "parts"}, "sample": res.get("sample") or []},
                                            kind="proof", ok=res["status"] in ("pass", "skip"))
            rows.append(gate)
    finally:
        rd.close()
    return rows


def tally(rows: list[dict]) -> dict:
    return {"rules": len(rows), "pass": sum(1 for r in rows if r["status"] == "pass"), "fail": sum(1 for r in rows if r["status"] == "fail"),
            "high fail": sum(1 for r in rows if r["status"] == "fail" and r.get("severity") == "high"), "error": sum(1 for r in rows if r["status"] == "error"),
            "skip": sum(1 for r in rows if r["status"] == "skip")}


# ------------------------------------------------------------------ compiling and exporting (Build)

def compile_sql(rule: dict, params: dict, ds: dict, dialect: str, ref_name: str | None = None) -> str:
    """The check as SQL in the dataset's own dialect (what the warehouse runs; shown to the person and exported)."""
    import sqlglot
    tname = ds["ref"].get("object") or Path(ds["ref"].get("file") or "data").stem
    t = ".".join(oc._q(p) for p in tname.split("."))
    cols = params.get("columns") or []
    q = oc._q(cols[0]) if cols else None
    k = rule["kind"]
    if k == "not_null":
        sql = f"SELECT COUNT(*) AS bad FROM {t} WHERE {q} IS NULL"
    elif k == "unique":
        cl = ", ".join(oc._q(c) for c in cols)
        sql = f"SELECT {cl}, COUNT(*) AS copies FROM {t} GROUP BY {cl} HAVING COUNT(*) > 1"
    elif k == "range":
        if params.get("values") is not None:
            sql = f"SELECT COUNT(*) AS bad FROM {t} WHERE {q} IS NOT NULL AND CAST({q} AS VARCHAR) NOT IN ({', '.join(_lit(v) for v in params['values'])})"
        else:
            cond = " OR ".join(x for x in ((f"{q} < {params['min']}" if params.get("min") is not None else ""), (f"{q} > {params['max']}" if params.get("max") is not None else "")) if x)
            sql = f"SELECT COUNT(*) AS bad FROM {t} WHERE {cond}"
    elif k == "referential":
        rt = ".".join(oc._q(p) for p in (ref_name or "ref").split("."))
        sql = f"SELECT COUNT(*) AS bad FROM {t} a WHERE a.{q} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {rt} b WHERE b.{oc._q(params['ref_column'])} = a.{q})"
    elif k == "freshness":
        sql = f"SELECT MAX({q}) AS newest FROM {t}"
    elif k == "business_total":
        agg = params.get("agg") or "sum"
        sql = f"SELECT {'COUNT(*)' if agg == 'count' else agg.upper() + '(' + q + ')'} AS total FROM {t}" + (f" WHERE {oc._q(params['where_column'])} = {_lit(params['where_value'])}" if params.get("where_column") else "")
    else:
        return "-- reconciliation: row counts, column checksums, totals and a sample compared between source and target (Relay runs it)"
    try:
        return sqlglot.transpile(sql, read="duckdb", write=dialect)[0] if dialect != "duckdb" else sql
    except Exception:  # noqa: BLE001
        return sql


def exports(rules: list[dict], dsets: dict[str, dict], name: str) -> dict[str, str]:
    """The rule set as files for the tools teams already run: dbt tests, Soda checks, a Great Expectations suite."""
    import yaml
    by: dict[str, list] = {}
    for r in rules:
        if r.get("active"):
            by.setdefault(r["dataset"], []).append(r)
    models, sources, singular, soda, suites = [], [], [], [], []
    for key, rs in by.items():
        ds = dsets.get(key) or {}
        mname = re.sub(r"\W+", "_", (ds.get("name") or "t").split(".")[-1]).lower()
        cols: dict[str, list] = {}
        sc: list = []
        ge = []
        fresh = None
        for r in rs:
            p, probs = parse(r, dsets)
            if probs:
                continue
            c = (p.get("columns") or [""])[0]
            if r["kind"] == "not_null":
                cols.setdefault(c, []).append("not_null")
                sc.append(f"missing_count({c}) <= {p.get('allow', 0)}")
                ge.append({"expectation_type": "expect_column_values_to_not_be_null", "kwargs": {"column": c}})
            elif r["kind"] == "unique":
                if len(p["columns"]) == 1:
                    cols.setdefault(c, []).append("unique")
                    sc.append(f"duplicate_count({c}) = 0")
                    ge.append({"expectation_type": "expect_column_values_to_be_unique", "kwargs": {"column": c}})
                else:
                    sc.append(f"duplicate_count({', '.join(p['columns'])}) = 0")
                    ge.append({"expectation_type": "expect_compound_columns_to_be_unique", "kwargs": {"column_list": p["columns"]}})
            elif r["kind"] == "range":
                if p.get("values") is not None:
                    cols.setdefault(c, []).append({"accepted_values": {"values": p["values"]}})
                    sc.append({f"invalid_count({c}) = 0": {"valid values": p["values"]}})
                    ge.append({"expectation_type": "expect_column_values_to_be_in_set", "kwargs": {"column": c, "value_set": p["values"]}})
                else:
                    rng = {k2: v for k2, v in (("min_value", p.get("min")), ("max_value", p.get("max"))) if v is not None}
                    cols.setdefault(c, []).append({"dbt_utils.accepted_range": rng})
                    if p.get("min") is not None:
                        sc.append(f"min({c}) >= {p['min']:g}")
                    if p.get("max") is not None:
                        sc.append(f"max({c}) <= {p['max']:g}")
                    ge.append({"expectation_type": "expect_column_values_to_be_between", "kwargs": {"column": c, **rng}})
            elif r["kind"] == "referential":
                other = dsets.get(p["ref_dataset"]) or {}
                oname = re.sub(r"\W+", "_", (other.get("name") or "ref").split(".")[-1]).lower()
                cols.setdefault(c, []).append({"relationships": {"to": f"ref('{oname}')", "field": p["ref_column"]}})
                sc.append(f"values in ({c}) must exist in {oname} ({p['ref_column']})")
            elif r["kind"] == "freshness":
                fresh = {"loaded_at_field": c, "freshness": {"error_after": {"count": int(p["max_age_h"]), "period": "hour"}}}
                sc.append(f"freshness({c}) < {int(p['max_age_h'])}h")
            elif r["kind"] == "business_total" and p.get("expected") is not None:
                tol = abs(p["expected"]) * (p.get("tolerance_pct") or 0) / 100.0
                agg = p["agg"]
                where = f" where {p['where_column']} = {_lit(p['where_value'])}" if p.get("where_column") else ""
                singular.append(f"-- {r['id']}: {agg} of {c}{where} ties out to {p['expected']:g} ± {p.get('tolerance_pct') or 0:g} %\n"
                                f"select 1 from (select {'count(*)' if agg == 'count' else agg + '(' + c + ')'} as total from {{{{ ref('{mname}') }}}}{where}) t "
                                f"where abs(total - {p['expected']:g}) > {tol:g}")
                sc.append(f"{agg}({c}) between {p['expected'] - tol:g} and {p['expected'] + tol:g}")
        models.append({"name": mname, "columns": [{"name": k2, "tests": v} for k2, v in cols.items()]})
        if fresh:
            sources.append({"name": mname, **fresh})
        soda.append((mname, sc))
        suites.append({"expectation_suite_name": f"relay_{slug(name)}_{mname}", "expectations": ge, "meta": {"generated_by": "Relay", "dataset": ds.get("label")}})
    dbt = {"version": 2, "models": models}
    if sources:
        dbt["sources"] = [{"name": "relay_checked", "tables": sources}]
    soda_text = "".join(f"checks for {m}:\n" + "".join(("  - " + yaml.safe_dump(x, sort_keys=False, allow_unicode=True).strip().replace("\n", "\n    ") + "\n") if isinstance(x, dict) else f"  - {x}\n" for x in sc) + "\n" for m, sc in soda)
    return {"dbt_schema.yml": "# dbt tests generated by Relay from the confirmed rule set (accepted_range needs the dbt_utils package)\n" + yaml.safe_dump(dbt, sort_keys=False, allow_unicode=True),
            "dbt_tests.sql": "\n\n".join(singular) + ("\n" if singular else "-- no business-total tie-outs in this rule set\n"),
            "soda_checks.yml": "# SodaCL checks generated by Relay from the confirmed rule set\n" + soda_text,
            "great_expectations_suites.json": json.dumps(suites, indent=1)}
