"""The KPI dictionary (an organisation's ontology of KPIs): what each KPI means, how it is calculated, and the other
names people use for it. The review checks every model against it: one KPI, one meaning, one value.

An entry (every field but the name is optional):
    name         Gross Margin %
    synonyms     GM%, Gross margin pct              other names for the same KPI (they must mean the same number)
    definition   Gross profit as a share of net revenue
    formula      (Net revenue - Cost of goods sold) / Net revenue     in business words
    dax          DIVIDE ( [Net Revenue] - [COGS], [Net Revenue] )     the reference DAX (other KPIs by [name])
    unit         percent | currency | count | number | ratio | duration
    aggregation  sum | average | count | distinct_count | ratio | min | max | last | custom
    filters      Status = Completed; excludes internal orders        conditions that are part of the meaning
    time         fiscal year ending 30 June | calendar year          (year_end is read from it: 06-30)
    owner, domain, notes

Files people bring: CSV or Excel (one row per KPI, a header row; the usual column titles are recognised: "KPI",
"Metric", "Description", "Calculation", "Aliases" ...), YAML or JSON (a list of entries, or {"kpis": [...]}).
"""
from __future__ import annotations

import csv
import io
import json
import re
from difflib import SequenceMatcher

import yaml

FIELDS = ("name", "synonyms", "definition", "formula", "dax", "unit", "aggregation", "filters", "time", "owner", "domain", "notes")
LIMITS = {"name": 120, "definition": 2000, "formula": 1000, "dax": 8000, "time": 200, "owner": 120, "domain": 120, "notes": 1000}
MAX_KPIS = 2000
MAX_LIST = 30
UNITS = ("percent", "currency", "count", "number", "ratio", "duration")
AGGREGATIONS = ("sum", "average", "count", "distinct_count", "ratio", "min", "max", "last", "custom")

HEADERS = {
    "name": ("kpi", "kpi name", "kpi_name", "name", "metric", "metric name", "measure", "measure name", "indicator", "kpi title"),
    "synonyms": ("synonyms", "synonym", "aliases", "alias", "also called", "also known as", "aka", "other names",
                 "alternate names", "alternative names"),
    "definition": ("definition", "description", "meaning", "business definition", "what it means", "kpi definition"),
    "formula": ("formula", "calculation", "business formula", "logic", "business rule", "calculation logic", "how calculated",
                "computation"),
    "dax": ("dax", "dax formula", "dax expression", "expression", "reference dax", "power bi dax", "measure dax"),
    "unit": ("unit", "units", "unit of measure", "uom", "format", "type", "value type", "data type"),
    "aggregation": ("aggregation", "aggregate", "aggregation type", "summarization", "summarisation", "rollup", "roll up"),
    "filters": ("filters", "filter", "conditions", "condition", "inclusions", "exclusions", "rules", "scope", "criteria"),
    "time": ("time", "time basis", "calendar", "period", "fiscal year", "year end", "time period", "periodicity"),
    "owner": ("owner", "data owner", "kpi owner", "steward", "data steward", "responsible", "accountable"),
    "domain": ("domain", "area", "category", "subject area", "department", "group", "function", "business area"),
    "notes": ("notes", "note", "comments", "comment", "remarks"),
}
_HEADER_OF = {h: f for f, hs in HEADERS.items() for h in hs}

UNIT_WORDS = [("percent", ("%", "percent", "percentage", "pct", "per cent", "rate %")),
              ("currency", ("currency", "$", "usd", "inr", "eur", "gbp", "aed", "sar", "money", "amount", "value", "revenue",
                            "monetary", "rs", "₹", "€", "£")),
              ("count", ("count", "#", "number of", "qty", "quantity", "units", "integer", "whole number")),
              ("ratio", ("ratio", "x", "times", "multiple", "index")),
              ("duration", ("days", "hours", "minutes", "duration", "time", "seconds", "weeks", "months")),
              ("number", ("number", "decimal", "score", "numeric", "float", "rating"))]
AGG_WORDS = [("distinct_count", ("distinct count", "unique count", "count distinct", "dcount", "distinctcount", "unique")),
             ("ratio", ("ratio", "rate", "percentage", "divide", "division", "share", "%")),
             ("average", ("average", "avg", "mean")),
             ("count", ("count", "count rows", "number of rows")),
             ("sum", ("sum", "total", "additive")),
             ("last", ("last", "closing", "end of period", "latest", "semi-additive", "semi additive", "balance", "snapshot")),
             ("min", ("min", "minimum", "lowest")),
             ("max", ("max", "maximum", "highest", "peak"))]
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
DAYS_IN = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


class KpiError(Exception):
    """Shown to the person as it is."""


# ---------------------------------------------------------------- one entry

def _list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        items = [str(x) for x in v]
    else:
        s = str(v)
        sep = "\n" if "\n" in s else ";" if ";" in s else "|" if "|" in s else ","
        items = s.split(sep)
    out = []
    for x in items:
        x = re.sub(r"\s+", " ", x).strip().strip("-*").strip()
        if x and x.lower() not in {o.lower() for o in out}:
            out.append(x[:200])
    return out[:MAX_LIST]


def _pick(text: str | None, table) -> str | None:
    t = f" {str(text or '').strip().lower()} "
    if not t.strip():
        return None
    for value, words in table:
        if t.strip() == value or any((f" {w} " in t) or t.strip() == w for w in words):
            return value
    return None


def unit_of(text: str | None) -> str | None:
    return _pick(text, UNIT_WORDS) if text else None


def aggregation_of(text: str | None) -> str | None:
    if not text:
        return None
    return _pick(text, AGG_WORDS) or "custom"


def year_end_of(text: str | None) -> str | None:
    """The year end a time basis names: "fiscal year ending 30 June" -> 06-30, "April to March" -> 03-31,
    "calendar" -> 12-31; None when it does not say."""
    t = str(text or "").lower()
    if not t.strip():
        return None
    mon = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    found = [(m.start(), m.end(), MONTHS[m.group(1)[:3]]) for m in re.finditer(mon, t)]
    if not found:
        return "12-31" if "calendar" in t else None

    def at(month: int, start: int, end: int) -> str:
        """The month's last day, or the day written right next to it (30 June, June 30th)."""
        near = re.search(r"([0-3]?\d)(?:st|nd|rd|th)?\s*$", t[max(0, start - 8):start]) or \
            re.match(r"\s*([0-3]?\d)(?:st|nd|rd|th)?\b", t[end:end + 8])
        d = int(near.group(1)) if near and 1 <= int(near.group(1)) <= 31 else DAYS_IN[month]
        return f"{month:02d}-{min(d, 29 if month == 2 else DAYS_IN[month]):02d}"
    end = re.search(r"\b(end|ends|ending|ended|close|closes|closing)\b", t)
    if end:                                                 # "... ending 31 March": the first month after that word
        after = [f for f in found if f[0] > end.start()]
        if after:
            return at(after[0][2], after[0][0], after[0][1])
    rng = re.search(mon + r"\s*(?:-|to|through|till|until|/)\s*" + mon, t)
    if rng:                                                 # April to March, Apr-Mar: the year ends with the second month
        second = [f for f in found if f[0] >= rng.start(2)][0]
        return f"{second[2]:02d}-{DAYS_IN[second[2]]:02d}"
    s, e, month = found[0]
    if re.search(r"\b(start|starts|starting|begin|begins|beginning|from)\b", t):
        month = 12 if month == 1 else month - 1             # starting 1 April: it ends in March
        return f"{month:02d}-{DAYS_IN[month]:02d}"
    return at(month, s, e)


def clean(entry: dict) -> dict:
    """One entry as the dictionary keeps it (KpiError when it has no name)."""
    if not isinstance(entry, dict):
        raise KpiError("A KPI must be a set of fields (name, definition, formula ...).")
    e = {}
    for k, v in entry.items():
        f = k if k in FIELDS else _HEADER_OF.get(re.sub(r"[\s_]+", " ", str(k).strip().lower()))
        if f and f not in e and v not in (None, ""):
            e[f] = v
    name = re.sub(r"\s+", " ", str(e.get("name") or "")).strip()
    if not name:
        raise KpiError("Every KPI needs a name.")
    out = {"name": name[:LIMITS["name"]]}
    for f in ("definition", "formula", "dax", "time", "owner", "domain", "notes"):
        v = e.get(f)
        if v is not None and str(v).strip():
            out[f] = str(v).strip()[:LIMITS[f]]
    syn = [s for s in _list(e.get("synonyms")) if s.lower() != name.lower()]
    if syn:
        out["synonyms"] = syn
    flt = _list(e.get("filters")) if not isinstance(e.get("filters"), str) or "\n" in e["filters"] or ";" in e["filters"] \
        else [e["filters"].strip()[:200]]
    if flt:
        out["filters"] = flt
    u = str(e.get("unit") or "").strip().lower()
    out_unit = u if u in UNITS else unit_of(u)
    if out_unit:
        out["unit"] = out_unit
    a = str(e.get("aggregation") or "").strip().lower().replace(" ", "_")
    out_agg = a if a in AGGREGATIONS else aggregation_of(e.get("aggregation"))
    if out_agg:
        out["aggregation"] = out_agg
    ye = year_end_of(out.get("time"))
    if ye:
        out["year_end"] = ye
    return out


# ---------------------------------------------------------------- files

def _rows_csv(data: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise KpiError("The file's text could not be read (save it as UTF-8 CSV).")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]


XLSX_MAX_MEMBER = 24 * 1024 * 1024          # a KPI workbook is small; a zip bomb (shared strings blown up) is not read
XLSX_MAX_TOTAL = 40 * 1024 * 1024


def _xlsx_guard(data: bytes) -> None:
    """Refuse a workbook whose parts would unpack far beyond what a KPI list needs, before openpyxl opens it."""
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise KpiError("The Excel file could not be opened.") from e
    infos = z.infolist()
    if len(infos) > 2000 or sum(i.file_size for i in infos) > XLSX_MAX_TOTAL or any(i.file_size > XLSX_MAX_MEMBER for i in infos):
        raise KpiError("The Excel file unpacks to more than a KPI dictionary needs. Save the KPI sheet alone (or as CSV).")


def _yaml(text: str):
    """YAML without anchors and aliases (&a, *a): a few bytes of them can stand for billions of values."""
    try:
        for ev in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(ev, yaml.AliasEvent):
                raise KpiError("YAML anchors and aliases (& and *) are not read: write each KPI out in full.")
        return yaml.safe_load(text)
    except RecursionError:
        raise KpiError("The file is nested too deeply to read.") from None


def _rows_xlsx(data: bytes) -> list[list[str]]:
    import openpyxl
    _xlsx_guard(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - any broken workbook reads as one message
        raise KpiError("The Excel file could not be opened.") from e
    try:
        best: list[list[str]] = []
        for ws in wb.worksheets[:20]:
            rows = []
            for r in ws.iter_rows(max_row=MAX_KPIS + 50, values_only=True):
                cells = ["" if c is None else str(c) for c in r[:40]]
                if any(c.strip() for c in cells):
                    rows.append(cells)
            if _header_row(rows) is not None and len(rows) > len(best):
                best = rows
        return best
    finally:
        wb.close()


def _header_row(rows: list[list[str]]) -> int | None:
    """The first row (of the first ten) that names a KPI column."""
    for i, r in enumerate(rows[:10]):
        fields = {_HEADER_OF.get(re.sub(r"[\s_]+", " ", c.strip().lower())) for c in r}
        if "name" in fields:
            return i
    return None


def _from_rows(rows: list[list[str]]) -> list[dict]:
    h = _header_row(rows)
    if h is None:
        raise KpiError('No column for the KPI names: the first row should have a "KPI" (or "Name", "Metric") column.')
    head = [re.sub(r"[\s_]+", " ", c.strip().lower()) for c in rows[h]]
    out = []
    for n, r in enumerate(rows[h + 1:], h + 2):
        e = {}
        for i, c in enumerate(r[:len(head)]):
            f = _HEADER_OF.get(head[i])
            if f and c.strip() and f not in e:
                e[f] = c.strip()
        if e.get("name"):
            out.append(e)
        elif e:
            out.append({"_problem": f"Row {n} has no KPI name, so it was left out."})
    return out


def read_file(filename: str, data: bytes) -> tuple[list[dict], list[str]]:
    """A dictionary file -> (entries, problems). Problems are the rows left out and why."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if len(data) > 8 * 1024 * 1024:
        raise KpiError("The file is too big for a KPI dictionary (8 MB at most).")
    if ext in ("csv", "txt", "tsv"):
        raw = _from_rows(_rows_csv(data))
    elif ext in ("xlsx", "xlsm"):
        raw = _from_rows(_rows_xlsx(data))
    elif ext in ("yaml", "yml", "json"):
        try:
            doc = json.loads(data.decode("utf-8-sig")) if ext == "json" else _yaml(data.decode("utf-8-sig"))
        except RecursionError:
            raise KpiError("The file is nested too deeply to read.") from None
        except (ValueError, yaml.YAMLError, UnicodeDecodeError) as e:
            raise KpiError(f"The file could not be read as {ext.upper()}.") from e
        raw = doc.get("kpis") or doc.get("KPIs") or doc.get("metrics") or [] if isinstance(doc, dict) else doc
        if not isinstance(raw, list):
            raise KpiError('The file should hold a list of KPIs (or {"kpis": [...]}).')
    else:
        raise KpiError("Bring the dictionary as CSV, Excel (.xlsx), YAML or JSON.")
    entries, problems, seen = [], [], {}
    for i, r in enumerate(raw[:MAX_KPIS + 1], 1):
        if isinstance(r, dict) and r.get("_problem"):
            problems.append(r["_problem"])
            continue
        try:
            e = clean(r)
        except KpiError as ex:
            problems.append(f"Entry {i}: {ex}")
            continue
        key = norm(e["name"])
        if key in seen:                              # the same KPI twice: one entry, the later row wins where both say something
            problems.append(f'Entry {i}: "{e["name"]}" is in the file twice; its rows were put together (the later one wins where both '
                            "say something).")
            first = entries[seen[key]]
            if "time" in e:
                first.pop("year_end", None)
            entries[seen[key]] = clean({**first, **e})
            continue
        seen[key] = len(entries)
        entries.append(e)
    if len(raw) > MAX_KPIS:
        problems.append(f"Only the first {MAX_KPIS:,} KPIs are read.")
    if not entries:
        raise KpiError("No KPIs found in the file. " + (problems[0] if problems else ""))
    return entries, problems


def to_csv(entries: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["KPI", "Synonyms", "Definition", "Formula", "DAX", "Unit", "Aggregation", "Filters", "Time", "Owner", "Domain", "Notes"])
    for e in entries:
        w.writerow([_cell(e.get("name")), _cell("; ".join(e.get("synonyms") or [])), _cell(e.get("definition")),
                    _cell(e.get("formula")), _cell(e.get("dax")), _cell(e.get("unit")), _cell(e.get("aggregation")),
                    _cell("; ".join(e.get("filters") or [])), _cell(e.get("time")), _cell(e.get("owner")),
                    _cell(e.get("domain")), _cell(e.get("notes"))])
    return buf.getvalue()


def _cell(v) -> str:
    """A CSV cell that a spreadsheet will not run as a formula (=, +, -, @ at the start)."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_yaml(entries: list[dict]) -> str:
    keep = [{k: e[k] for k in FIELDS if e.get(k) not in (None, "", [])} for e in entries]
    return yaml.safe_dump({"kpis": keep}, sort_keys=False, allow_unicode=True, width=120)


TEMPLATE = [
    {"name": "Revenue", "synonyms": ["Net Sales", "Turnover"], "definition": "Sales of completed orders, after discounts and returns.",
     "formula": "Sum of net amount of completed orders", "dax": "CALCULATE ( SUM ( Sales[Net Amount] ), Sales[Status] = \"Completed\" )",
     "unit": "currency", "aggregation": "sum", "filters": ["Status = Completed"], "time": "fiscal year ending 31 March",
     "owner": "Finance", "domain": "Sales"},
    {"name": "Gross Margin %", "synonyms": ["GM %"], "definition": "Gross profit as a share of revenue.",
     "formula": "(Revenue - Cost of goods sold) / Revenue", "dax": "DIVIDE ( [Revenue] - [COGS], [Revenue] )",
     "unit": "percent", "aggregation": "ratio", "owner": "Finance", "domain": "Finance"},
    {"name": "Active Customers", "definition": "Customers with at least one completed order in the period.",
     "formula": "Distinct count of customers with a completed order", "unit": "count", "aggregation": "distinct_count",
     "filters": ["Status = Completed"], "owner": "Sales", "domain": "Customers"},
]


# ---------------------------------------------------------------- names

ABBREV = {"%": "pct", "percent": "pct", "percentage": "pct", "rev": "revenue", "amt": "amount", "qty": "quantity",
          "avg": "average", "num": "number", "no": "number", "cnt": "count", "#": "count", "yr": "year", "mth": "month",
          "mo": "month", "qtr": "quarter", "wk": "week", "cust": "customer", "custs": "customers", "prod": "product",
          "cogs": "cogs", "gm": "gross margin", "nps": "nps", "aov": "aov", "ltv": "ltv", "&": "and", "vs.": "vs",
          "versus": "vs", "ly": "ly", "py": "py", "yoy": "yoy"}
# words that do not change which KPI a name means ("All" and "Overall" do: Sales (All) is the denominator of a share)
FILLER = {"total", "sum", "of", "the", "measure", "kpi", "metric", "value", "calc", "calculated", "m"}
VARIANT = {"ytd", "mtd", "qtd", "wtd", "ly", "py", "ytd ly", "prior", "previous", "prev", "last", "year", "month",
           "quarter", "week", "yoy", "mom", "qoq", "wow", "growth", "change", "delta", "var", "variance", "vs", "budget",
           "target", "plan", "forecast", "fcst", "goal", "rolling", "r12", "ttm", "l12m", "12m", "running", "cumulative",
           "cum", "pct", "trend", "index", "same", "period", "sply", "diff", "difference", "achievement", "attainment",
           "gap", "to", "date", "fy", "cy", "pp", "lw", "lm", "lq", "history", "hist", "act", "actual", "actuals",
           "share", "contribution", "rank", "avg", "average", "max", "min", "prior year", "comparison", "bp",
           # currencies, scales and units in a name: Revenue (USD), Revenue $M, CO2 kg
           "usd", "eur", "gbp", "inr", "aed", "sar", "jpy", "cny", "lc", "local", "reporting", "k", "mn", "bn",
           "thousands", "millions", "billions", "kg", "t", "tonnes", "tons", "km", "hrs", "mins", "days"}
NOT_VARIANT = {"per", "by", "ratio", "rate", "margin", "net", "gross", "cost", "profit", "count", "number", "unit", "units",
               "customer", "customers"}


def tokens_of(name: str) -> list[str]:
    s = str(name or "").lower().replace("%", " % ").replace("#", " # ").replace("&", " & ")
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    toks = re.findall(r"[a-z0-9]+|%|#|&", s)
    out = []
    for t in toks:
        t = ABBREV.get(t, t)
        out.extend(t.split())
    return out


def norm(name: str) -> str:
    """A name as compared: lower case, usual abbreviations spelled one way, filler words (Total, Sum of ...) out."""
    toks = [t for t in tokens_of(name) if t not in FILLER]
    return " ".join(toks) or " ".join(tokens_of(name))


class Matcher:
    """Measure names -> KPIs of the dictionary: exact name or synonym (after norm), a time or target variant of one
    (Revenue YTD, Revenue vs Budget %), or a close spelling (Revenues, Revenue (USD))."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.by_norm: dict[str, int] = {}
        for i, e in enumerate(entries):
            for n in [e["name"]] + list(e.get("synonyms") or []):
                self.by_norm.setdefault(norm(n), i)
        self.names = sorted(self.by_norm.items(), key=lambda x: -len(x[0].split()))

    def match(self, name: str, variants_only: bool = False) -> tuple[int | None, str | None, str | None]:
        """(entry index, how: name | synonym | variant | similar, the variant's words). variants_only: only say
        which entry this name is a variant of (for names matched against each other)."""
        n = norm(name)
        if n in self.by_norm and not variants_only:
            i = self.by_norm[n]
            return i, ("name" if norm(self.entries[i]["name"]) == n else "synonym"), None
        toks = n.split()
        for key, i in self.names:                       # the longest KPI name the measure's name starts with or holds
            kt = key.split()
            if not kt or len(kt) >= len(toks):
                continue
            rest = _minus(toks, kt)
            if rest is None or not rest:
                continue
            if all(t in VARIANT or t.isdigit() for t in rest) and not any(t in NOT_VARIANT for t in rest):
                return i, "variant", " ".join(rest)
        if variants_only:
            return None, None, None
        best, score = None, 0.0
        for key, i in self.by_norm.items():
            if abs(len(key) - len(n)) > 6:
                continue
            r = SequenceMatcher(None, key, n).ratio()
            if r > score:
                best, score = i, r
        if best is not None and score >= 0.9 and len(n) >= 4:
            return best, "similar", None
        return None, None, None


def _minus(toks: list[str], sub: list[str]) -> list[str] | None:
    """toks without the words of sub (all of which must be there, in order); None when sub is not in toks."""
    rest, j = [], 0
    for t in toks:
        if j < len(sub) and t == sub[j]:
            j += 1
        else:
            rest.append(t)
    return rest if j == len(sub) else None
