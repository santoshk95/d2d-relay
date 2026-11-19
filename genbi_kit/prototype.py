"""Render the HTML prototype of an expanded definition.

Every custom visual (and table) carries `prototype.sql`: a DuckDB query over the model views whose
column aliases are the visual's roles (e.g. category/value for driver bars). Rows are shaped into the
same models the Power BI visuals build, and drawn with the same renderer bundle, so the prototype
and the report look the same. Output: one self-contained HTML file with page tabs.

Visual Atlas visuals run their own packaged code in a mock Power BI host: their SQL returns one column per
field, named after the field (measure or column name), and is shaped into the data view Power BI would send.

Slicers filter as in Power BI. A selection in a report filter (synced on every page) or in a page's pbi.slicer keeps
the rows of the sliced table and, through the relationships (one -> many), of every table on the many side: the
prototype puts those filtered model views in front of a visual's SQL, so the SQL is written for the rows the slicers
let through, like a DAX measure in its filter context. all_dates."<table>" reads a table with the date table's slicers
lifted (last year, other periods) and main."<table>" with no slicer at all. The page opens at the report's default
selection. `render` then runs every visual again for the selections a reviewer is likely to make - one slicer
changed, then two, ... - within a time and size budget (GENBI_PROTOTYPE_SECONDS, GENBI_PROTOTYPE_BYTES), and embeds
the results; the page offers only selections it has results for, says so when the budget cut them short, and shows
"No data" where a selection leaves no rows. SQL written the earlier way - the filter's default value in the query
(WHERE "Year" = 2026) - still draws as before, but cannot follow that slicer: the page marks such a visual.
"""
import concurrent.futures
import datetime
import decimal
import html as html_mod
import itertools
import json
import math
import os
import re
import threading
import time
from pathlib import Path

from . import KIT, atlas, stock, visuals_dir
from .data import _plain, _q
from .data import records as _records

STOCK_ROWS = 5000                      # rows of a built-in visual's prototype SQL kept for the page
SLICE_SECONDS = float(os.environ.get("GENBI_PROTOTYPE_SECONDS") or 20)       # time for the slicer selections
SLICE_BYTES = int(os.environ.get("GENBI_PROTOTYPE_BYTES") or 12_000_000)     # the whole page, results included
SLICE_VALUES = 500                     # values a slicer lists
SLICE_DEPTH = 4                        # the most changes from the default selection the prototype combines
WORKERS = max(1, min(4, os.cpu_count() or 1))

DATA_TYPE = {"int": "numeric", "decimal": "numeric", "date": "dateTime", "bool": "bool", "string": "text"}
DATE_FORMAT = "yyyy-MM-dd"             # the formatString report_builder gives date columns
MEASURE = re.compile(r"^\[([^\]]+)\]$")
COLUMN = re.compile(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$")

# Columns each visual type must return from its prototype SQL.
REQUIRED = {"kpiCard": ["value"], "trendLine": ["axis", "actual"], "driverBars": ["category", "value"],
            "quadrant": ["details", "x", "y"], "treemap": ["category", "size"], "heatmap": ["rows", "columns", "value"],
            "funnel": ["stage", "value"], "narrative": ["item"], "table": []}


def _col(rows, name):
    return [r.get(name) for r in rows]


def _first(rows, name):
    return next((r[name] for r in rows if r.get(name) is not None), None)


def _readable(measure: str) -> str:
    """A title measure's name as a stand-in title: "Title Revenue Trend" -> "Revenue Trend"."""
    return re.sub(r"(?i)^\s*title\b[\s_:-]*", "", measure).strip() or measure


def _no_title(page: dict, v: dict, measure: str) -> str:
    """A visual whose title is a measure needs its sentence in the prototype SQL's "title" column (GENBI.md); without
    it the prototype could only show the measure's name ("Title Revenue Trend"), so it goes back to the agent."""
    return (f"{page['name']} / {v['id']} ({v['type']}): the title is the measure [{measure}], but the prototype SQL returns "
            f"no \"title\" column with its sentence, so the prototype shows \"{_readable(measure)}\" - add that column")


def _has(rows, name):
    return bool(rows) and name in rows[0]


def _name(ref):
    return ref.strip()[1:-1] if isinstance(ref, str) and ref.strip().startswith("[") else ref


def model_for(v: dict, rows: list[dict], fmt) -> dict:
    """Shape SQL rows into the renderer model for this visual type. fmt(field_ref) -> format string."""
    t, f, fields = v["type"], v.get("format") or {}, v.get("fields") or {}
    F = lambda role: fmt(fields.get(role)) if isinstance(fields.get(role), str) else None
    if t == "kpiCard":
        k = f.get("kpi") or {}
        return {"label": k.get("label") or _name(fields.get("value")) or "", "value": _first(rows, "value"),
                "valueFormat": F("value"),
                "target": _first(rows, "target") if _has(rows, "target") else None,
                "comparison": _first(rows, "comparison") if _has(rows, "comparison") else None,
                "spark": _col(rows, "trend") if _has(rows, "trend") else None,
                "lowerIsBetter": bool(k.get("lowerIsBetter")), "signedValue": bool(k.get("signedValue")),
                "comparisonLabel": k.get("comparisonLabel"), "targetLabel": k.get("targetLabel")}
    if t == "trendLine":
        p = f.get("trend") or {}
        return {"categories": [str(c) for c in _col(rows, "axis")], "actual": _col(rows, "actual"),
                "target": _col(rows, "target") if _has(rows, "target") else None,
                "comparison": _col(rows, "comparison") if _has(rows, "comparison") else None,
                "annotations": _col(rows, "annotation") if _has(rows, "annotation") else None, "format": F("actual"),
                "labels": {"actual": p.get("actualLabel", "Actual"), "target": p.get("targetLabel", "Target"),
                           "comparison": p.get("comparisonLabel", "Last year")},
                "showAllAnnotations": bool(p.get("showAllAnnotations"))}
    if t == "driverBars":
        b = f.get("bars") or {}
        return {"rows": [{"label": str(r.get("category")), "value": r.get("value")} for r in rows], "format": F("value"),
                "signed": b.get("signed", True), "sort": "desc" if b.get("sortDescending") else "none"}
    if t == "quadrant":
        q = f.get("quadrant") or {}
        return {"points": [{"label": str(r.get("details")), "x": r.get("x"), "y": r.get("y"), "size": r.get("size")} for r in rows],
                "xRef": _first(rows, "xRef"), "yRef": _first(rows, "yRef"), "xFormat": F("x"), "yFormat": F("y"),
                "sizeFormat": F("size"), "names": {"x": _name(fields.get("x")), "y": _name(fields.get("y")),
                                                   "size": _name(fields.get("size"))},
                "corners": {k: q.get(k) for k in ("topLeft", "topRight", "bottomLeft", "bottomRight")},
                "labelTop": q.get("labelTop", 2), "labelBottom": q.get("labelBottom", 1)}
    if t == "treemap":
        return {"items": [{"label": str(r.get("category")), "size": r.get("size"), "color": r.get("color")} for r in rows],
                "sizeFormat": F("size"), "colorFormat": F("color"),
                "names": {"size": _name(fields.get("size")), "color": _name(fields.get("color"))}}
    if t == "heatmap":
        h = f.get("heatmap") or {}
        rlabels, clabels = [], []
        for r in rows:
            for key, seen in (("rows", rlabels), ("columns", clabels)):
                label = str(r.get(key))
                if label not in seen:
                    seen.append(label)
        grid = {(str(r.get("rows")), str(r.get("columns"))): r.get("value") for r in rows}
        pad = all(c.isdigit() and len(c) <= 2 for c in clabels)
        return {"rows": rlabels, "cols": [c.zfill(2) if pad else c for c in clabels],
                "values": [[grid.get((ri, ci)) for ci in clabels] for ri in rlabels], "format": F("value"),
                "indexMode": h.get("indexMode", True), "showValues": "all" if h.get("showAll") else "peak",
                "legend": {"low": h.get("lowLabel", "Low"), "high": h.get("highLabel", "High")},
                "names": {"value": _name(fields.get("value"))}}
    if t == "funnel":
        stages = fields.get("stages") or []
        stages = stages if isinstance(stages, list) else [stages]
        return {"stages": [{"label": str(r.get("stage")), "value": r.get("value"),
                            "format": fmt(stages[i]) if i < len(stages) else None} for i, r in enumerate(rows)]}
    if t == "narrative":
        n = f.get("narrative") or {}
        items = [str(i) for i in _col(rows, "item") if i] if _has(rows, "item") else str(n.get("lines") or "").split("\n")
        return {"heading": n.get("heading"), "note": n.get("note"), "style": n.get("style", "numbered"), "items": items}
    if t == "table":
        cols = list(rows[0].keys()) if rows else []
        refs = v.get("fields") or []
        return {"columns": cols, "rows": [[r.get(c) for c in cols] for r in rows[:25]],
                "formats": [fmt(refs[i]) if i < len(refs) else None for i in range(len(cols))]}
    return {}


def _describer(d: dict):
    """Field reference -> how a data view names and types it (Visual Atlas visuals)."""
    fmts = {m["name"]: m.get("format") or None for m in d.get("measures", [])}
    additive = stock.additive_measures(d.get("measures", []))
    types = {(t["name"], c["name"]): c.get("type", "string") for t in d["tables"] for c in t.get("columns", [])}
    types.update({(c["table"], c["name"]): c.get("type", "string") for c in d.get("calculated_columns", [])})
    mtable = d.get("measures_table", "Metrics")

    def describe(ref) -> dict:
        ref = str(ref).strip()
        m = MEASURE.match(ref)
        if m:
            return {"name": m.group(1), "query": f"{mtable}.{m.group(1)}", "type": "numeric", "measure": True,
                    "format": fmts.get(m.group(1)), "additive": additive.get(m.group(1), False)}
        c = COLUMN.match(ref)
        if not c:
            raise ValueError(f"field {ref} is neither [Measure] nor Table[Column]")
        kind = DATA_TYPE.get(types.get((c.group(1), c.group(2)), "string"), "text")
        return {"name": c.group(2), "query": f"{c.group(1)}.{c.group(2)}", "measure": False, "type": kind,
                "format": DATE_FORMAT if kind == "dateTime" else None}      # as model.bim sets it
    return describe


# ---------------------------------------------------------------- the theme's font
FONT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,62}")
GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
                 "ui-monospace", "ui-rounded", "-apple-system", "BlinkMacSystemFont"}
FALLBACK_FONTS = ['"Segoe UI"', '"Segoe UI Web (West European)"', "-apple-system", "BlinkMacSystemFont", "system-ui",
                  "Roboto", '"Helvetica Neue"', "Arial", "sans-serif"]


def font_stack(font) -> str:
    """The theme's font family as a CSS font list with system fallbacks: "Trebuchet MS" -> "Trebuchet MS", "Segoe UI",
    ..., sans-serif. Only names (letters, digits, spaces, . _ -) pass: the definition is written by the AI and the list
    goes into the page's style sheet. No web font is loaded (the prototype has no network): a font installed on the
    viewer's PC shows, else the next in the list."""
    names = []
    for part in str(font or "").split(","):
        name = part.strip().strip("'\"").strip()
        if name and FONT_NAME.fullmatch(name):
            names.append(name if name in GENERIC_FONTS else f'"{name}"')
    return ", ".join(dict.fromkeys(names + FALLBACK_FONTS))


def title_style(theme: dict) -> dict:
    """The brand's heading font for every visual's title: theme.styles["*"].title (fontFamily, bold) - bold false for
    a font whose name carries its weight (Segoe UI Semibold)."""
    t = (((theme or {}).get("styles") or {}).get("*") or {}).get("title")
    out: dict = {}
    for e in t if isinstance(t, list) else [t]:
        if isinstance(e, dict) and e.get("for") is None:
            out.update({k: e[k] for k in ("fontFamily", "bold") if k in e})
    return out


def _bold(value) -> bool:
    return str(value).strip().lower() not in ("false", "0", "no", "off", "none")


def _atlas_format(v: dict) -> dict:
    fmt = {k: dict(p or {}) for k, p in (v.get("format") or {}).items()}
    if v.get("chart"):
        fmt.setdefault("chart", {})["chartType"] = v["chart"]
    return fmt


def _theme_defaults(entry: dict, theme: dict) -> dict:
    """What the report theme sets for an Atlas-framework visual (its look and palette), and its Style > Font: the
    theme's font, so a brand font shows in these visuals too."""
    defaults = atlas.theme_defaults(entry, (theme or {}).get("look", "soft"))
    if "fontFamily" in ((entry.get("objects") or {}).get("style") or {}):
        defaults.setdefault("style", {})["fontFamily"] = font_stack((theme or {}).get("font", "Segoe UI"))
    return defaults


def _atlas_item(v: dict, entry: dict, rows: list[dict], describe, theme: dict) -> dict:
    return {"guid": entry["guid"], "dv": atlas.dataview(entry, v.get("fields") or {}, rows, describe),
            "objects": atlas.objects_for(entry, _atlas_format(v), _theme_defaults(entry, theme))}


def _stock_item(v: dict, entry: dict, rows: list[dict], describe, theme: dict) -> dict:
    """A Power BI built-in visual for the page: its fields (with the SQL column each comes from), the rows and the
    Format-pane settings merged over the report theme's styles for this visual."""
    if not rows:
        raise ValueError("query returned no rows")
    fmt = stock.prototype_format(entry["visualType"], v.get("format"), (theme or {}).get("styles"))
    sample, fields, missing = rows[0], {}, []
    for role, refs in (v.get("fields") or {}).items():
        refs = refs if isinstance(refs, list) else [refs]
        refs = stock.shown(entry, role, refs, fmt)              # a drill hierarchy, or a matrix, shows its top level
        for ref in refs:
            dsc = describe(ref)
            col = atlas._lookup(sample, dsc["name"], role, len(refs) == 1)
            if col is None:
                missing.append(f'"{dsc["name"]}"')
                continue
            fields.setdefault(role, []).append({**dsc, "col": col})
    if missing:
        raise ValueError(f"query must return a column per field, named after it: missing {', '.join(missing)}")
    return {"vt": entry["visualType"], "renderer": entry["renderer"], "fields": fields, "rows": rows[:STOCK_ROWS],
            "format": fmt, "sort": v.get("sort")}


def _matrix_problems(v: dict, item: dict) -> list[str]:
    """Where a matrix's prototype SQL does not return one row per row header the matrix shows (stock_visuals.js draws
    it that way, and genbi daxcheck compares those rows): several rows for one header - a finer grain than shown, which
    the prototype could only add up, and a ratio does not add up - and, with Auto expand, a group without its own row
    while one of its measures does not add up."""
    fields, rows = item["fields"], item["rows"]
    levels, cf, values = fields.get("Rows") or [], (fields.get("Columns") or [None])[0], fields.get("Values") or []
    defined = (v.get("fields") or {}).get("Rows") or []
    defined, n = defined if isinstance(defined, list) else [defined], len(levels)
    if not n:
        return []
    blank = lambda x: x is None or x == ""                       # noqa: E731
    key = lambda x: "" if blank(x) else str(x)                   # noqa: E731

    def depth(r) -> int:                                          # n: a detail row; d < n: a group's own row (0: the Total)
        s = [not blank(r.get(f["col"])) for f in levels]
        d = s.index(False) if False in s else n
        return n if any(s[d:]) else d

    def where(path, ck) -> str:
        return " and ".join([f"{f['name']} = {p or '(Blank)'}" for f, p in zip(levels, path)] + ([f"{cf['name']} = {ck or '(Blank)'}"] if cf else []))

    seen: dict = {}
    for r in rows:
        d = depth(r)
        k = (d, tuple(key(r.get(f["col"])) for f in levels[:d]), key(r.get(cf["col"])) if cf else "")
        seen[k] = seen.get(k, 0) + 1
    many = next(((k, c) for k, c in seen.items() if k[0] == n and c > 1), None)
    if many:
        (_, path, ck), c = many
        unit = levels[-1]["name"] + (f" and {cf['name']}" if cf else "")
        if len(defined) > n:
            return [f"the prototype SQL returns {c} rows for {where(path, ck)}, but the matrix opens at its first Rows level: Power BI "
                    f"shows one row per {unit}, with every measure computed for the whole {levels[0]['name']} (a ratio is never added "
                    f"up) - return one row per {unit}, or set rowHeaders: {{autoExpand: true}} to open every level and return the "
                    f"detail rows plus a row per group with the lower Rows columns empty (GROUP BY ROLLUP)"]
        return [f"the prototype SQL returns {c} rows for {where(path, ck)}, but Power BI shows one row per {unit} with every measure "
                f"computed for it (a ratio is never added up) - return one row per {unit}"]
    if n > 1 and any(not f.get("additive") for f in values):
        odd = next(f for f in values if not f.get("additive"))
        for (d, path, ck) in list(seen):
            if d != n:
                continue
            for g in range(1, n):
                if (g, path[:g], ck) not in seen:
                    return [f"with Auto expand Power BI shows every {levels[g - 1]['name']} in its own row with [{odd['name']}] "
                            f"computed for the whole group, but the prototype SQL has no row for {where(path[:g], ck)} with "
                            f"{levels[g]['name']} empty - return a row per group too (GROUP BY ROLLUP)"]
    return []


# ---------------------------------------------------------------- slicers: the filter context of a visual's SQL

def qualify(sql: str, schema: str) -> str:
    """The query with all_dates."<table>" read from `schema` (outside string literals and comments)."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":                                          # a string literal ('' inside)
            j = i + 1
            while j < n and not (sql[j] == "'" and (j + 1 >= n or sql[j + 1] != "'")):
                j += 2 if sql[j] == "'" else 1
            out.append(sql[i:j + 1])
            i = j + 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(sql[i:j])
            i = j
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(sql[i:j])
            i = j
            continue
        m = ALL_DATES.match(sql, i)
        if m and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] in '_."')):
            out.append(schema + ".")
            i = m.end()
            continue
        if c == '"':                                          # a quoted name ("" inside)
            j = i + 1
            while j < n and not (sql[j] == '"' and (j + 1 >= n or sql[j + 1] != '"')):
                j += 2 if sql[j] == '"' else 1
            out.append(sql[i:j + 1])
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


ALL_DATES = re.compile(r'(?:"all_dates"|(?i:all_dates)(?![\w$]))\s*\.')
RANGE_MODES = re.compile(r"^(Between|Before|After|Single|Relative)")      # slicer styles that pick a range
NAME = re.compile(r'"((?:[^"]|"")+)"|\b([A-Za-z_][A-Za-z0-9_]*)\b')


def _code(sql: str) -> str:
    """The query without its string literals and comments."""
    return re.sub(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)


def records(con, sql: str, d: dict | None = None) -> list[dict]:
    """A prototype query's rows. Without d: over all the data, no slicer (all_dates. reads the tables as they are);
    with the expanded definition: at the report's default selection, as the prototype opens and as Power BI evaluates
    the report's default filters (genbi daxcheck compares the two)."""
    if d is None:
        return _records(con, qualify(sql, "main"))
    return _engine(d, con).rows(sql)


_ENGINES: list = []                    # (con, definition, Slicing) of recent records(con, sql, d) calls


def _engine(d: dict, con) -> "Slicing":
    for c, dd, sl in _ENGINES:
        if c is con and dd is d:
            return sl
    sl = Slicing(d, con)
    _ENGINES.insert(0, (con, d, sl))
    del _ENGINES[4:]
    return sl


def _sql_lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if math.isfinite(v) else "NULL"
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, datetime.datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    if isinstance(v, datetime.date):
        return f"DATE '{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def _label(v) -> str:
    """A slicer value as Power BI lists it."""
    if v is None or v == "":
        return "(Blank)"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return f"{v:.10g}"
    if isinstance(v, datetime.datetime):
        return v.isoformat(sep=" ")[:19] if (v.hour, v.minute, v.second) != (0, 0, 0) else v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    return str(v)


def _same_value(x, default) -> bool:
    if x == default and type(x) is not bool:
        return True
    return x is not None and str(_plain(x)) == str(_plain(default))


def _bakes(sql: str, value) -> bool:
    """Whether a query writes this value itself (the way prototype SQL mirrored a report filter's default before the
    prototype applied slicers): 2026 as a number or in a date ('2026-01-01'), 'North' as a string literal."""
    if value is None or isinstance(value, bool):
        return False
    s = f"{value:g}" if isinstance(value, float) else str(_plain(value))
    text = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)
    if "'" + s.replace("'", "''") + "'" in text:
        return True
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", s)) and bool(re.search(r"(?<![\w.])" + re.escape(s) + r"(?![\w])", text))


_SERIAL = 0


class Job:
    """A visual whose query runs again for other selections."""
    __slots__ = ("pi", "item", "sql", "baked", "deps", "shape", "h0", "results", "busy", "has")

    def __init__(self, pi, item, sql, baked, deps, shape, h0, has):
        self.pi, self.item, self.sql, self.baked, self.deps = pi, item, sql, baked, deps
        self.shape, self.h0, self.results, self.busy, self.has = shape, h0, {}, set(), has


class Slicing:
    """The report's slicers and what a selection does to the model views, the way Power BI filters its model: a
    selection keeps the rows of its table and, along every relationship (many -> one), the rows of the tables on the
    many side whose key is still there."""

    def __init__(self, d: dict, con):
        self.d, self.con = d, con
        self.cur = con.cursor()
        self.cols: dict[str, dict[str, str]] = {}
        for t, c, typ in self.cur.execute("SELECT table_name, column_name, data_type FROM duckdb_columns() "
                                          "WHERE schema_name = 'main'").fetchall():
            self.cols.setdefault(t, {})[c] = str(typ)
        self.tables = [t["name"] for t in d.get("tables") or [] if t["name"] in self.cols]
        self.rels = []
        for r in d.get("relationships") or []:
            if not isinstance(r, dict):
                continue
            a, b = COLUMN.match(str(r.get("from", "")).strip()), COLUMN.match(str(r.get("to", "")).strip())
            if a and b and a.group(2) in self.cols.get(a.group(1), {}) and b.group(2) in self.cols.get(b.group(1), {}) \
                    and a.group(1) in self.tables and b.group(1) in self.tables and a.group(1) != b.group(1):
                self.rels.append((a.group(1), a.group(2), b.group(1), b.group(2)))
        self.dates = {t["name"] for t in d.get("tables") or [] if t.get("date_table")} | \
            {one for _, _, one, k in self.rels if re.match(r"(?i)(DATE|TIMESTAMP)", self.cols[one][k])}
        self.sort_by = {(t["name"], c["name"]): c["sortBy"] for t in d.get("tables") or [] for c in t.get("columns") or []
                        if c.get("sortBy")}
        self.slicers: list[dict] = []
        self.of_visual: dict = {}                      # (page index, visual id) -> slicer index
        keys: dict = {}
        styles = (d.get("theme") or {}).get("styles")
        for pi, page in enumerate(d.get("pages") or []):
            for v in page.get("visuals") or []:
                spec = self._spec(v, pi, styles)
                if not spec:
                    continue
                key = spec.pop("key")
                if key not in keys:
                    keys[key] = len(self.slicers)
                    self.slicers.append(spec)
                self.of_visual[(pi, v["id"])] = keys[key]
        for s in self.slicers:
            self._resolve(s)
        self.report = [i for i, s in enumerate(self.slicers) if s["page"] is None]
        self.on_page = {pi: [i for i, s in enumerate(self.slicers) if s["page"] == pi] for pi in range(len(d.get("pages") or []))}
        self.jobs: list[Job] = []
        self._defaults: dict = {}
        self._local, self._lock, self._next, self._cursors, self._schemas = threading.local(), threading.Lock(), 0, [], []
        global _SERIAL
        _SERIAL += 1
        self.ns = f"__relay{_SERIAL}"                 # this object's schemas: another one may work on the same connection

    # ------------------------------------------------------------ the slicers
    @staticmethod
    def _spec(v: dict, pi: int, styles) -> dict | None:
        if v.get("type") == "slicer" and v.get("field"):          # a report filter (definition.filters), synced by `sync`
            sync = v.get("sync")
            return {"key": ("r", str(sync)) if sync else ("p", pi, v["id"]), "field": v["field"], "label": v.get("label"),
                    "default": v.get("default"), "single": bool(v.get("single")), "ctrl": True, "mode": "Dropdown",
                    "page": None if sync else pi}
        if stock.is_stock(v.get("type")) and stock.catalog()[v["type"]].get("renderer") == "slicer":
            refs = (v.get("fields") or {}).get("Values") or []
            refs = refs if isinstance(refs, list) else [refs]
            if not refs:
                return None
            fmt = stock.prototype_format("slicer", v.get("format"), styles)
            part = lambda obj: (fmt.get(obj) or {}).get("_") or {}           # noqa: E731
            m = COLUMN.match(str(refs[0]).strip())
            return {"key": ("p", pi, v["id"]), "field": refs[0], "label": part("header").get("text") or (m.group(2) if m else None),
                    "default": None, "single": bool(part("selection").get("strictSingleSelect")),
                    "ctrl": part("selection").get("singleSelect", True) is not False,
                    "mode": str(part("data").get("mode") or "VerticalList"), "page": pi}
        return None

    def _resolve(self, s: dict) -> None:
        s.update(raw=[], labels=[], d=[], note=None, more=False, table=None, column=None)
        m = COLUMN.match(str(s["field"]).strip())
        if not m or m.group(2) not in self.cols.get(m.group(1), {}) or m.group(1) not in self.tables:
            s["note"] = "Power BI computes this field, so the prototype cannot filter by it"
            return
        t, c = m.group(1), m.group(2)
        by = self.sort_by.get((t, c))
        order = f"{_q(c)} IS NULL, " + (f"MIN({_q(by)}), " if by in self.cols[t] else "") + "1"
        try:
            vals = [r[0] for r in self.cur.execute(f"SELECT {_q(c)} FROM main.{_q(t)} GROUP BY 1 ORDER BY {order} "
                                                   f"LIMIT {SLICE_VALUES + 1}").fetchall()]
        except Exception as e:  # noqa: BLE001 - shown on the slicer
            s["note"] = f"The prototype could not read this field: {str(e).splitlines()[0][:160]}"
            return
        if len(vals) > SLICE_VALUES:
            vals, s["more"] = vals[:SLICE_VALUES], True
        s["table"], s["column"] = t, c
        if s["default"] is not None:
            i = next((k for k, x in enumerate(vals) if _same_value(x, s["default"])), None)
            if i is None:                                  # Power BI keeps the default even when no row has it
                vals.append(s["default"])
                i = len(vals) - 1
            s["d"] = [i]
        elif s["single"] and vals:                         # Single select forces a value: the first one
            s["d"] = [0]
        s["raw"], s["labels"] = vals, [_label(x) for x in vals]
        if RANGE_MODES.match(s["mode"]):                   # its whole range: the lowest and the highest value
            lo, hi = self.cur.execute(f"SELECT MIN({_q(c)}), MAX({_q(c)}) FROM main.{_q(t)}").fetchone()
            s.update(raw=[lo, hi], labels=[_label(lo), _label(hi)], d=[], more=False,
                     note="In Power BI people pick a range here; the prototype shows every value")

    def selection(self, pi: int | None, changes: dict | None = None, baked=()) -> dict:
        """The selection a visual on page pi sees: every report filter and the page's own slicers (pi None: the report
        filters only), at their defaults unless changed; a filter the visual's SQL writes itself (baked) is not
        applied."""
        changes = changes or {}
        return {si: tuple(changes.get(si, self.slicers[si]["d"])) for si in self.report + self.on_page.get(pi, [])
                if si not in baked and not self.slicers[si]["note"]}

    def baked(self, sql: str) -> frozenset:
        return frozenset(si for si in self.report if self.slicers[si]["default"] is not None and not self.slicers[si]["note"]
                         and _bakes(sql, self.slicers[si]["default"]))

    def reach(self, table: str) -> set:
        """The tables a filter on this table filters."""
        out, todo = {table}, [table]
        while todo:
            x = todo.pop()
            for many, _, one, _ in self.rels:
                if one == x and many not in out:
                    out.add(many)
                    todo.append(many)
        return out

    def deps(self, sql: str, pi: int, baked) -> list[int]:
        """The slicers that can change what this query returns: those on a table it reads, or one it reads is related
        to (on its many side)."""
        names = {t.lower(): t for t in self.tables}
        used = {names[n] for m in NAME.finditer(_code(sql)) for n in [(m.group(1) or m.group(2)).replace('""', '"').lower()]
                if n in names}
        return [si for si in self.report + self.on_page.get(pi, []) if si not in baked and not self.slicers[si]["note"]
                and used & self.reach(self.slicers[si]["table"])]

    # ------------------------------------------------------------ filtered views
    def _cond(self, si: int, sel: tuple) -> str:
        s = self.slicers[si]
        vals = [s["raw"][i] for i in sel if i < len(s["raw"])]
        lits = [_sql_lit(x) for x in vals if x is not None]
        parts = [f"{_q(s['column'])} IN ({', '.join(lits)})"] if lits else []
        if any(x is None for x in vals):                   # (Blank)
            parts.append(f"{_q(s['column'])} IS NULL")
        return "(" + " OR ".join(parts) + ")" if parts else "FALSE"

    def _install(self, cur, schema: str, base: str, sel: dict, lift_dates: bool = False) -> None:
        """A view per model table in `schema` with the selection applied (Power BI's filter propagation)."""
        direct: dict = {}
        for si, idx in sel.items():
            s = self.slicers[si]
            if idx and not (lift_dates and s["table"] in self.dates):
                direct.setdefault(s["table"], []).append(self._cond(si, idx))
        semis: dict = {}
        filtered, grew = set(direct), True
        while grew:
            grew = False
            for many, fk, one, k in self.rels:
                if one in filtered and (fk, one, k) not in semis.get(many, []):
                    semis.setdefault(many, []).append((fk, one, k))
                    filtered.add(many)
                    grew = True
        order, state = [], {}

        def visit(t):                                # tables on the one side first; a cycle drops its last link
            state[t] = 1
            for fk, one, k in list(semis.get(t, [])):
                if state.get(one) == 1:
                    semis[t].remove((fk, one, k))
                elif not state.get(one):
                    visit(one)
            state[t] = 2
            order.append(t)
        for t in self.tables:
            if not state.get(t):
                visit(t)
        stmts = []
        for t in order:
            where = direct.get(t, []) + [f"{_q(fk)} IN (SELECT {_q(k)} FROM {schema}.{_q(one)})" for fk, one, k in semis.get(t, [])]
            stmts.append(f"CREATE OR REPLACE VIEW {schema}.{_q(t)} AS SELECT * FROM {base}.{_q(t)}"
                         + (" WHERE " + " AND ".join(where) if where else ""))
        if stmts:
            cur.execute(";\n".join(stmts))

    def _schema(self, cur, name: str) -> str:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
        with self._lock:
            if name not in self._schemas:
                self._schemas.append(name)
        return name

    def rows(self, sql: str, pi: int | None = None, baked=None) -> list[dict]:
        """The query's rows at the default selection of page pi (None: the report filters' defaults only, which is
        what the DAX check gives Power BI)."""
        if not self.slicers:
            return _records(self.cur, qualify(sql, "main"))
        sel = self.selection(pi, None, self.baked(sql) if baked is None else baked)
        key = tuple(sorted((si, idx) for si, idx in sel.items() if idx))
        if key not in self._defaults:
            n = len(self._defaults)
            names = (self._schema(self.cur, f"{self.ns}_d{n}"), self._schema(self.cur, f"{self.ns}_e{n}"))
            self._install(self.cur, names[0], "main", sel)
            self._install(self.cur, names[1], "main", sel, lift_dates=True)
            self._defaults[key] = names
        f, a = self._defaults[key]
        self.cur.execute(f"USE {f}")
        try:
            return _records(self.cur, qualify(sql, a))
        finally:
            self.cur.execute("USE main")

    # ------------------------------------------------------------ other selections
    def _options(self, si: int, c: int):
        """The selections of a slicer `c` changes away from its default (a value picked or dropped)."""
        s = self.slicers[si]
        n, dflt = len(s["raw"]), tuple(s["d"])
        if c == 0:
            yield dflt
            return
        if s["note"] or not n:
            return
        if s["single"]:
            if c == 1:
                yield from ((i,) for i in range(n) if (i,) != dflt)
            return
        rest = [i for i in range(n) if i not in dflt]
        for r in range(min(c, len(dflt)) + 1):
            for drop in itertools.combinations(dflt, r):
                for add in itertools.combinations(rest, c - r):
                    yield tuple(sorted((set(dflt) - set(drop)) | set(add)))

    def _changes(self, sis: list, cost: int, need=()):
        """Every selection `cost` changes away from the defaults over these slicers ({slicer: selection}, changed
        slicers only); with `need`, at least one of those changed. Spread over several slicers first (Year and Region
        and Channel), then several values of one slicer."""
        def rec(k, left, top, hit, acc):
            if left == 0:
                if hit and (not need or any(si in acc for si in need)):
                    yield dict(acc)
                return
            if k == len(sis):
                return
            for c in range(min(left, top, 1 if self.slicers[sis[k]]["single"] else left), -1, -1):
                if c == 0:
                    yield from rec(k + 1, left, top, hit, acc)
                    continue
                for o in self._options(sis[k], c):
                    acc[sis[k]] = o
                    yield from rec(k + 1, left - c, top, hit or c == top, acc)
                    del acc[sis[k]]
        for top in range(1, cost + 1):                 # the most changes on one slicer
            yield from rec(0, cost, top, False, {})

    def _states(self, cost: int):
        """(changes, page or None for every page): the report filters first, then each page's own slicers."""
        for ch in self._changes(self.report, cost):
            yield ch, None
        for pi, own in self.on_page.items():
            if own:
                for ch in self._changes(self.report + own, cost, need=own):
                    yield ch, pi

    def _worker(self):
        w = getattr(self._local, "w", None)
        if w is None:
            with self._lock:                         # a connection is not safe to share: each thread its own cursor
                w, self._next = self._next, self._next + 1
                cur = self.con.cursor()
                self._cursors.append(cur)
            self._schema(cur, f"{self.ns}_f{w}")
            self._schema(cur, f"{self.ns}_a{w}")
            self._local.w, self._local.cur = w, cur
        return w, self._local.cur

    def _task(self, changes: dict, jobs: list) -> list:
        """Run these visuals' queries at a selection (in a worker thread with a cursor and views of its own)."""
        w, cur = self._worker()
        f, a, base = f"{self.ns}_f{w}", f"{self.ns}_a{w}", f"{self.ns}_base"
        out, groups = [], {}
        for j in jobs:
            groups.setdefault((j.pi, j.baked), []).append(j)
        for (pi, baked), js in groups.items():
            sel = self.selection(pi, changes, baked)
            try:
                self._install(cur, f, base, sel)
                self._install(cur, a, base, sel, lift_dates=True)
                cur.execute(f"USE {f}")
            except Exception as e:  # noqa: BLE001 - every visual of this selection says so
                out += [(j, _dump({"e": "Prototype query failed: " + str(e).splitlines()[0][:300]})) for j in js]
                continue
            try:
                for j in js:
                    try:
                        entry = j.shape(_records(cur, qualify(j.sql, a)))
                    except Exception as e:  # noqa: BLE001 - shown on the visual for this selection
                        entry = {"e": "Prototype query failed: " + str(e).splitlines()[0][:300]}
                    out.append((j, _dump(entry)))
            finally:
                cur.execute("USE main")
        return out

    def explore(self, seconds: float, room: int) -> dict:
        """Run the visuals again for other selections, nearest to the default first, until `seconds` have passed or
        the results fill `room` bytes. Results land in each job's `results` ({changes: entry json})."""
        stats = {"states": 0, "runs": 0, "cut": None, "seconds": 0.0}
        jobs = [j for j in self.jobs if j.deps]
        if not jobs:
            return stats
        t0 = time.monotonic()
        soft, hard = t0 + seconds, t0 + max(4 * seconds, 60)      # every single change first, then within `seconds`
        base = self._schema(self.cur, f"{self.ns}_base")
        for t in self.tables:                          # once in memory: every selection reads these
            self.cur.execute(f"CREATE OR REPLACE TABLE {base}.{_q(t)} AS SELECT * FROM main.{_q(t)}")
        seen, used = set(), 0
        mine = lambda j, changes: tuple(sorted((si, sel) for si, sel in changes.items() if si in j.deps))  # noqa: E731

        def take(fut, changes):
            nonlocal used
            try:
                got = fut.result()
            except Exception:  # noqa: BLE001 - a worker that could not start: its selection stays out
                return
            for j, ej in got:
                key = mine(j, changes)
                j.busy.discard(key)
                j.results[key] = ej
                stats["runs"] += 1
                if ej not in seen:
                    seen.add(ej)
                    used += len(ej)
                used += 24                                 # its key in the visual's list

        with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
            for cost in range(1, SLICE_DEPTH + 1):
                states, flying = self._states(cost), {}
                deadline = hard if cost == 1 else soft
                while not stats["cut"]:
                    while len(flying) < WORKERS * 3:
                        nxt = next(states, None)
                        if nxt is None:
                            break
                        changes, pi = nxt
                        todo = []
                        for j in jobs:
                            key = mine(j, changes)
                            if (pi is None or j.pi == pi) and key and key not in j.results and key not in j.busy:
                                todo.append(j)
                                j.busy.add(key)
                        if todo:
                            flying[ex.submit(self._task, changes, todo)] = changes
                            stats["states"] += 1
                    if not flying:
                        break
                    done, _ = concurrent.futures.wait(flying, timeout=max(0.05, deadline - time.monotonic()),
                                                      return_when=concurrent.futures.FIRST_COMPLETED)
                    for fut in done:
                        take(fut, flying.pop(fut))
                    if time.monotonic() > deadline:
                        stats["cut"] = "time"
                    elif used > room:
                        stats["cut"] = "size"
                if flying:                                 # cut short: what already runs still lands
                    for fut in flying:
                        fut.cancel()
                    concurrent.futures.wait(flying)
                    for fut, changes in flying.items():
                        if not fut.cancelled():
                            take(fut, changes)
                if stats["cut"]:
                    break
                if cost == 1:
                    self._refine(jobs)
        stats["seconds"] = round(time.monotonic() - t0, 1)
        return stats

    def _refine(self, jobs: list) -> None:
        """A slicer whose every value leaves a visual as it was does not reach it (a query that reads the table
        unfiltered, a title): drop it from the visual's slicers, so no selection runs it again for that slicer."""
        for j in jobs:
            for si in list(j.deps):
                one = [k for k in j.results if len(k) == 1 and k[0][0] == si]
                if one and len(one) == sum(1 for _ in self._options(si, 1)) and all(j.results[k] == j.h0 for k in one):
                    j.deps.remove(si)
                    for k in [k for k in j.results if any(x == si for x, _ in k)]:
                        del j.results[k]

    def close(self) -> None:
        for cur in self._cursors:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        for name in sorted(self._schemas, key=lambda n: n.endswith("_base")):    # the views first, then their tables
            try:
                self.cur.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
            except Exception:  # noqa: BLE001 - an in-memory leftover, harmless
                pass
        self._schemas.clear()
        self._defaults.clear()
        _ENGINES[:] = [e for e in _ENGINES if e[2] is not self]


def _clean(x):
    """JSON-safe values for the page: no NaN or Infinity (DuckDB divides by zero to Infinity; Power BI shows a blank),
    numbers to 10 significant digits (sums in another order differ in the last bits)."""
    if isinstance(x, float):
        return float(f"{x:.10g}") if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _dump(x) -> str:
    return json.dumps(_clean(x), default=str, separators=(",", ":"))


def _key(deps: list, slicers: list, changes: tuple) -> str:
    """A visual's key for a selection, as the page computes it: per slicer it follows, the selected value indexes
    ("*" for none: All)."""
    ch = dict(changes)
    return "|".join(",".join(str(i) for i in ch.get(si, slicers[si]["d"])) or "*" for si in deps)


# ---------------------------------------------------------------- the pages

def _shaper(kind: str, v: dict, has: dict, fmt, describe, theme: dict, entry: dict | None):
    """rows -> what the page draws for a selection other than the default: {"t": title, "m": a Relay visual's model,
    "d": an Atlas data view (packed when the default has one of the same shape), "r": a built-in visual's rows
    (packed), "s": a whole built-in visual, "n": no rows, "e": an error}."""
    def shape(rows: list[dict]) -> dict:
        out = {}
        if _has(rows, "title") and _first(rows, "title"):
            out["t"] = str(_first(rows, "title"))
        if kind == "relay":
            if not rows:
                return {"n": 1}
            missing = [c for c in REQUIRED[v["type"]] if not _has(rows, c)]
            if missing:
                raise ValueError(f"query must return column(s) {', '.join(missing)}")
            out["m"] = model_for(v, rows, fmt)
            return out
        if not rows:
            return {"n": 1}
        if kind == "atlas":
            dv = atlas.dataview(entry, v.get("fields") or {}, rows, describe)
            base = has.get("dv")
            same = base is not None and len(base.get("categories") or []) == len(dv["categories"])
            if same and "groups" in dv:                        # series: the default's first group gives the sources
                tmpl = (base.get("groups") or [{}])[0].get("values") or []
                same = "groups" in base and all(len(g["values"]) == len(tmpl) for g in dv["groups"]) and bool(tmpl)
            elif same:
                same = "values" in base and len(base["values"]) == len(dv["values"])
            if not same:
                out["d"] = {"f": dv}
            elif "groups" in dv:
                out["d"] = {"c": [c["values"] for c in dv["categories"]],
                            "g": [[g["name"], [c["values"] for c in g["values"]]] for g in dv["groups"]]}
            else:
                out["d"] = {"c": [c["values"] for c in dv["categories"]], "v": [c["values"] for c in dv["values"]]}
            return out
        if has.get("stock"):
            cols = list(rows[0].keys())
            out["r"] = {"c": cols, "v": [[r.get(c) for c in cols] for r in rows[:STOCK_ROWS]]}
        else:
            out["s"] = _stock_item(v, entry, rows, describe, theme)
        return out
    return shape


def build_pages(d: dict, con, slicing: "Slicing | None" = None) -> tuple[list[dict], list[str]]:
    """Run every visual's prototype SQL at the report's default selection; returns (pages for the HTML, error
    messages). The visuals whose SQL can follow a slicer are kept in slicing.jobs for render()."""
    sl = slicing or _engine(d, con)
    sl.jobs = []
    fmts = {m["name"]: m.get("format", "") for m in d.get("measures", [])}
    fmt = lambda ref: fmts.get(_name(ref)) if isinstance(ref, str) and ref.strip().startswith("[") else None
    acat, scat, describe, theme = atlas.catalog(), stock.catalog(), _describer(d), d.get("theme") or {}
    pages, errors = [], []
    for pi, page in enumerate(d["pages"]):
        out = []
        for v in page["visuals"]:
            item = {k: v.get(k) for k in ("id", "type", "x", "y", "w", "h", "label", "default", "paragraphs", "align")}
            if (pi, v.get("id")) in sl.of_visual:
                item["si"] = sl.of_visual[(pi, v["id"])]
            kind = "atlas" if v["type"] in acat else "stock" if stock.is_stock(v["type"]) else "relay" if v["type"] in REQUIRED else None
            sql = (v.get("prototype") or {}).get("sql")
            rows, ran = None, False
            if kind in ("atlas", "stock"):
                title = v.get("title")
                dynamic = MEASURE.match(str(title).strip()) if title else None
                header = {"title": None if dynamic else title, "subtitle": v.get("subtitle")}
                fallback = _readable(dynamic.group(1)) if dynamic else title
                try:
                    if not sql:
                        raise ValueError("missing prototype.sql")
                    rows = sl.rows(sql, pi)
                    ran = True
                    if _has(rows, "title") and _first(rows, "title"):
                        header["title"] = _first(rows, "title")
                    elif dynamic:
                        header["title"] = _readable(dynamic.group(1))
                        errors.append(_no_title(page, v, dynamic.group(1)))
                    if kind == "atlas":
                        item.update(atlas=_atlas_item(v, acat[v["type"]], rows, describe, theme), header=header)
                    else:
                        item.update(stock=_stock_item(v, scat[v["type"]], rows, describe, theme), header=header)
                        if item["stock"]["renderer"] == "matrix":
                            errors += [f"{page['name']} / {v['id']} ({v['type']}): {p}" for p in _matrix_problems(v, item["stock"])]
                except Exception as e:  # noqa: BLE001 - reported to the agent
                    item.update(error=str(e).splitlines()[0][:300], header=header)
                    errors.append(f"{page['name']} / {v['id']} ({v['type']}): {str(e).splitlines()[0][:300]}")
                if fallback != header["title"]:
                    item["tt"] = fallback
                if kind == "atlas" and ran and "atlas" not in item:    # what another selection needs to draw it
                    entry = acat[v["type"]]
                    item["atlas"] = {"guid": entry["guid"],
                                     "objects": atlas.objects_for(entry, _atlas_format(v), _theme_defaults(entry, theme))}
            elif kind == "relay":
                f = v.get("format") or {}
                header = {"title": (f.get("header") or {}).get("title") or v.get("title"),
                          "subtitle": (f.get("header") or {}).get("subtitle"),
                          "showCard": (f.get("card") or {}).get("show", True)}
                fallback = header["title"]
                try:
                    rows = sl.rows(sql, pi) if sql else []
                    ran = bool(sql)
                    if sql:
                        missing = [c for c in REQUIRED[v["type"]] if not _has(rows, c)] if rows else []
                        if missing:
                            raise ValueError(f"query must return column(s) {', '.join(missing)}")
                    elif v["type"] != "narrative":
                        raise ValueError("missing prototype.sql")
                    title = _first(rows, "title") if _has(rows, "title") else None
                    if title:
                        header["title"] = title
                    item.update(model=model_for(v, rows, fmt), header=header)
                    if not rows and sql:
                        errors.append(f"{page['name']} / {v['id']}: query returned no rows")
                except Exception as e:  # noqa: BLE001 - reported to the agent
                    item.update(error=str(e).splitlines()[0][:300], header=header)
                    errors.append(f"{page['name']} / {v['id']} ({v['type']}): {str(e).splitlines()[0][:300]}")
                if fallback != header["title"]:
                    item["tt"] = fallback
            if ran and sql and not (kind == "stock" and scat[v["type"]].get("renderer") == "slicer"):
                baked = sl.baked(sql)
                deps = sl.deps(sql, pi, baked)
                entry = acat.get(v["type"]) if kind == "atlas" else scat.get(v["type"]) if kind == "stock" else None
                has = {"dv": (item.get("atlas") or {}).get("dv"), "stock": item.get("stock")}
                shape = _shaper(kind, v, has, fmt, describe, theme, entry)
                try:
                    h0 = _dump(shape(rows))
                except Exception as e:  # noqa: BLE001
                    h0 = _dump({"e": "Prototype query failed: " + str(e).splitlines()[0][:300]})
                sl.jobs.append(Job(pi, item, sql, baked, deps, shape, h0, has))
                if baked:
                    item["b"] = sorted(baked)
            out.append(item)
        pages.append({"name": page["name"], "height": page.get("height", 720), "visuals": out})
    return pages, errors


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ - prototype</title>
<style>__CSS__
:root{--relay-font:__FONT__;--relay-heading:__HEADFONT__}
html,body{margin:0;background:__BG__;font-family:var(--relay-font);color:__INK__}
button,select,input{font:inherit;color:inherit}
.page{position:relative;width:1280px;margin:0 auto}
.v{position:absolute}
.nav{display:flex;gap:6px;height:100%;box-sizing:border-box;padding:4px;background:__CARD__;border:1px solid __BORDER__;border-radius:22px}
.nav span{flex:1;display:flex;align-items:center;justify-content:center;border-radius:18px;font-size:14px;color:__MUTED__;cursor:pointer}
.nav span:hover{background:__TINT__;color:__INK__}
.nav span.on{background:__ACCENT__;color:#fff;font-weight:700}
.slc{height:100%;display:flex;flex-direction:column;justify-content:flex-end;gap:3px}
.slc-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;min-width:0}
.slc small{font-size:11px;color:__MUTED__;padding-left:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.slc-clear{border:0;background:none;padding:0 2px;font-size:11px;color:__ACCENT__;cursor:pointer;flex:none}
.slc-clear:hover{text-decoration:underline}
.slc-box{display:flex;justify-content:space-between;align-items:center;width:100%;box-sizing:border-box;background:__CARD__;border:1px solid __BORDER__;border-radius:8px;padding:6px 10px;font-size:13px;text-align:left;cursor:pointer}
.slc-box:hover,.slc-box[aria-expanded=true]{border-color:__ACCENT__}
.slc-box:focus-visible{outline:2px solid __ACCENT__;outline-offset:1px}
.slc-box:disabled{cursor:default;color:__MUTED__}
.slc-val{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.slc-chev{flex:none;width:6px;height:6px;margin:-4px 3px 0 10px;border-right:1.5px solid __MUTED__;border-bottom:1.5px solid __MUTED__;transform:rotate(45deg)}
.slc-pop{position:absolute;z-index:60;box-sizing:border-box;min-width:180px;max-width:420px;max-height:340px;overflow:auto;padding:6px 0;background:__CARD__;color:__INK__;border:1px solid __BORDER__;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18);font-size:13px}
.sl-item{display:flex;align-items:center;gap:8px;padding:5px 12px;cursor:pointer;white-space:nowrap;user-select:none}
.sl-item:hover,.sl-item:focus{background:__TINT__;outline:none}
.sl-mk{flex:none;width:13px;height:13px;box-sizing:border-box;border:1px solid __MUTED__;border-radius:2px;background:__CARD__}
.sl-item.radio .sl-mk{border-radius:50%}
.sl-item.on .sl-mk{background:__ACCENT__;border-color:__ACCENT__}
.sl-item.on .sl-mk::after{content:"";display:block;width:3px;height:7px;margin:1px 0 0 4px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg)}
.sl-item.radio.on .sl-mk::after{width:5px;height:5px;margin:3px;border:0;border-radius:50%;background:#fff;transform:none}
.sl-item.off{color:__MUTED__;opacity:.55;cursor:not-allowed}
.sl-item.off:hover{background:none}
.sl-tile{display:inline-flex;align-items:center;margin:0 4px 4px 0;padding:4px 10px;border:1px solid __BORDER__;border-radius:4px;background:__CARD__;cursor:pointer;user-select:none}
.sl-tile.on{background:__ACCENT__;border-color:__ACCENT__;color:#fff}
.sl-tile.off{opacity:.45;cursor:not-allowed}
.pop-hint,.pop-note{padding:3px 12px 5px;font-size:11px;color:__MUTED__;white-space:normal}
.pop-note.warn{color:__ACCENT__}
.pop-foot{display:flex;justify-content:flex-end;gap:10px;margin-top:4px;padding:6px 12px 2px;border-top:1px solid __BORDER__}
.pop-foot button{border:0;background:none;padding:0;font-size:12px;color:__ACCENT__;cursor:pointer}
.vb{position:absolute;height:0;z-index:5;pointer-events:none}
.vbadge{position:absolute;top:-9px;right:10px;max-width:70%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:1px 8px;border:1px solid __BORDER__;border-radius:9px;background:__TINT__;color:__INK__;font-size:10px;line-height:15px;pointer-events:auto;cursor:default}
.notice{height:100%;box-sizing:border-box;display:flex;flex-direction:column;background:__CARD__;border-radius:__RADIUS__px;padding:10px 12px;__FRAME__}
.notice h4{margin:0;font-size:12px;font-weight:700;color:__INK__;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.notice small{display:block;margin-top:2px;font-size:11px;color:__MUTED__;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.notice .nb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;text-align:center;color:__MUTED__;font-size:12px}
.notice .nb b{font-size:13px;font-weight:600}
.foot{width:1280px;margin:0 auto;padding:2px 24px 16px;box-sizing:border-box;display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:12px;color:__MUTED__}
.foot:empty{display:none}
.foot button{border:1px solid __BORDER__;background:__CARD__;border-radius:14px;padding:3px 12px;font-size:12px;color:__INK__;cursor:pointer}
.foot button:hover{border-color:__ACCENT__}
.tbl{height:100%;box-sizing:border-box;background:__CARD__;border:1px solid __BORDER__;border-radius:10px;padding:12px 14px;overflow:auto;font-size:12px}
.tbl h4{margin:0 0 8px;font-size:14px}.tbl table{border-collapse:collapse;width:100%}
.tbl th{text-align:left;color:__MUTED__;font-weight:600;border-bottom:1px solid __BORDER__;padding:4px 6px}
.tbl td{padding:4px 6px;border-bottom:1px solid #F1ECE6}.tbl td.n{text-align:right}
.err{height:100%;box-sizing:border-box;background:#FFF6F5;border:1px dashed #B3261E;border-radius:10px;padding:12px;font-size:12px;color:#B3261E}
.acard{height:100%;box-sizing:border-box;display:flex;flex-direction:column;background:__CARD__;border-radius:__RADIUS__px;padding:10px 12px;__FRAME__}
.acard h4{margin:0;font-size:12px;font-weight:700;color:__INK__;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acard small{display:block;margin-top:2px;font-size:11px;color:__MUTED__;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acard .abody{flex:1;min-height:0;position:relative;margin-top:6px}.acard .aerr{color:#B3261E;font-size:12px}
.acard .atl-landing,.acard .atl-reset,.acard .atl-mark{font-family:var(--relay-font)!important}
.gba-tip{position:fixed;z-index:50;pointer-events:none;background:#fff;border:1px solid #E1DFDD;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.14);padding:6px 9px;font-size:12px;color:#252423}
.gba-tip div{display:flex;gap:14px;justify-content:space-between}.gba-tip b{font-weight:600}
__ATLAS_CSS__
.gb-title,.gb-nar-title,.acard h4,.notice h4,.tbl h4{font-family:var(--relay-heading)}
__HEADWEIGHT__
</style></head><body><div class="page" id="page"></div><div class="foot" id="foot"></div>
<script>__JS__</script>
<script>__ATLAS_JS__</script>
<script>__STOCK_JS__</script>
<script>
const R = __DATA__;
</script>
<script>__PAGE_JS__</script>
</body></html>"""


FRAME ={"flat": "border:1px solid {border}", "soft": "box-shadow:0 3px 12px rgba(31,26,23,.13)",
         "3d": "box-shadow:6px 6px 14px rgba(31,26,23,.28)"}      # Power BI container look per Atlas look
CSS_COLOR = re.compile(r"#[0-9A-Fa-f]{3,8}|[A-Za-z]{3,24}|rgba?\(\s*[\d.]+%?\s*(,\s*[\d.]+%?\s*){2,3}\)")


def _color(value, default: str) -> str:
    """A theme colour for the page's style sheet. The definition is written by the AI, and nothing it read (a data
    file, an attachment) may close the style block and add markup: anything but a colour gets the default."""
    s = str(value).strip() if value is not None else ""
    return s if CSS_COLOR.fullmatch(s) else default


def _radius(value, default: int = 10) -> str:
    try:
        r = float(value)
    except (TypeError, ValueError):
        return str(default)
    return f"{max(0.0, min(r, 60.0)):g}"


def _slicers_for_page(sl: Slicing) -> list[dict]:
    return [{"label": s.get("label") or s.get("column") or str(s["field"]), "values": s["labels"], "d": s["d"],
             "single": s["single"], "ctrl": s["ctrl"], "mode": s["mode"], "page": s["page"], "note": s["note"],
             "more": s["more"]} for s in sl.slicers]


def render(d: dict, con, out: Path) -> list[str]:
    sl = Slicing(d, con)
    try:
        return _render(d, con, out, sl)
    finally:
        sl.close()


def _render(d: dict, con, out: Path, sl: Slicing) -> list[str]:
    pages, errors = build_pages(d, con, sl)
    bundle = visuals_dir() / "prototype"
    t = d.get("theme") or {}
    look = t.get("look", "soft")
    font = font_stack(t.get("font", "Segoe UI"))                         # body text
    heading = title_style(t)                                             # titles and headings, else the body font
    head_font = font_stack(", ".join(str(x) for x in (heading.get("fontFamily"), t.get("font", "Segoe UI")) if x))
    head_weight = "" if "bold" not in heading else \
        f".gb-title,.acard h4,.notice h4,.tbl h4{{font-weight:{700 if _bold(heading['bold']) else 400}}}"
    used = sorted({v["atlas"]["guid"] for p in pages for v in p["visuals"] if v.get("atlas")})
    codes = [atlas.code(g) for g in used]
    atlas_js = "" if not used else ((KIT / "assets" / "atlas_host.js").read_text(encoding="utf-8") + "\n"
                                    + "\n".join(js.replace("</script", "<\\/script") for js, _ in codes))
    from .definition import DEFAULT_THEME, genbi_colors
    tokens = {**genbi_colors({**DEFAULT_THEME, **t}), "card": t.get("card_bg", "#FFFFFF"),
              "border": t.get("card_border", "#E7E0D7"), "font": font}               # Relay visuals in the brand colors
    uses_stock = any(v.get("stock") or v.get("type", "").startswith(stock.PREFIX) for p in pages for v in p["visuals"])
    data = {"name": d.get("name"), "pages": pages, "tokens": tokens,
            "atlas": {"palette": t.get("data_colors"), "dark": bool(t.get("dark")), "look": look},
            "stock": {"palette": t.get("data_colors") or DEFAULT_THEME["data_colors"], "card": t.get("card_bg", "#FFFFFF"),
                      "border": t.get("card_border", "#E7E0D7"), "radius": t.get("radius", 10), "text": t.get("text", "#1F1A17"),
                      "muted": t.get("muted", "#6F6761"), "font": font,
                      "frame": FRAME.get(look, FRAME["soft"]).format(border=t.get("card_border", "#E7E0D7"))},
            "slicers": _slicers_for_page(sl), "pool": [], "budget": None}
    subs = {"NAME": html_mod.escape(str(d.get("name") or "Report")), "BG": _color(t.get("page_bg"), "#F7F3EE"),
            "TINT": _color(t.get("accent_tint"), "#FBE7CC"), "ACCENT": _color(t.get("accent"), "#DD7A12"),
            "CARD": _color(t.get("card_bg"), "#FFFFFF"), "INK": _color(t.get("text"), "#1F1A17"),
            "MUTED": _color(t.get("muted"), "#6F6761"), "BORDER": _color(t.get("card_border"), "#E7E0D7"),
            "RADIUS": _radius(t.get("radius", 10)), "FONT": font, "HEADFONT": head_font, "HEADWEIGHT": head_weight,
            "FRAME": FRAME.get(look, FRAME["soft"]).format(border=_color(t.get("card_border"), "#E7E0D7")),
            "CSS": (bundle / "genbi-visuals.css").read_text(encoding="utf-8"), "ATLAS_CSS": "\n".join(css for _, css in codes),
            "ATLAS_JS": atlas_js,
            "STOCK_JS": (KIT / "assets" / "stock_visuals.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
            if uses_stock else "",
            "PAGE_JS": (KIT / "assets" / "prototype_page.js").read_text(encoding="utf-8").replace("</script", "<\\/script"),
            "JS": (bundle / "genbi-visuals.js").read_text(encoding="utf-8")}

    def page_html() -> str:
        subs["DATA"] = _dump(data).replace("</", "<\\/").replace("<!--", "<\\!--")     # never ends or bends the script
        return re.sub(r"__([A-Z_]+)__", lambda m: subs.get(m.group(1), m.group(0)), PAGE)   # one pass: inserted code is never rescanned

    base = len(page_html().encode("utf-8"))
    stats = sl.explore(SLICE_SECONDS, max(0, SLICE_BYTES - base)) if sl.slicers else {"states": 0, "runs": 0, "cut": None}
    index: dict = {}
    for j in sl.jobs:
        if not j.deps:
            continue
        keys = {}
        for changes, ej in j.results.items():
            if ej == j.h0:                                 # as at the default: drawn from the visual's own data
                keys[_key(j.deps, sl.slicers, changes)] = -1
                continue
            if ej not in index:
                index[ej] = len(data["pool"])
                data["pool"].append(json.loads(ej))
            keys[_key(j.deps, sl.slicers, changes)] = index[ej]
        j.item.update(q=j.deps, k0=_key(j.deps, sl.slicers, ()), k=keys)
    data["budget"] = {"states": stats.get("states", 0), "runs": stats.get("runs", 0), "cut": stats.get("cut"),
                      "seconds": stats.get("seconds", 0)}
    html = page_html()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return errors
