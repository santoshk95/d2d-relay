"""The rule engine: deterministic mappings from the source (Cognos expressions, Cognos visuals) to the report
definition schema (DAX measures, calculated columns, slicers, catalogue visuals) and the prototype SQL that proves
them. Every translation names the rules it used, carries a confidence and lists its gaps — the calculations no rule
covers, in one line each ("running-total: no DAX rule yet") — so the converter asks the agent only for those.

Two emitters share one AST (expr.py): DAX for the measure / column, DuckDB SQL for the visual's prototype query.
Window functions carry the SQL for running totals, ranks and moving averages even where the DAX has no rule yet, so
the proof can check what the agent writes. Rules learned from accepted agent answers live in a RulePack (JSON per
tenant / partner) keyed on the normalised expression and are tried after the built-in rules, before the agent.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import expr

AGG = {"total": ("SUM", "SUMX", "SUM"), "sum": ("SUM", "SUMX", "SUM"), "average": ("AVERAGE", "AVERAGEX", "AVG"), "avg": ("AVERAGE", "AVERAGEX", "AVG"),
       "minimum": ("MIN", "MINX", "MIN"), "min": ("MIN", "MINX", "MIN"), "maximum": ("MAX", "MAXX", "MAX"), "max": ("MAX", "MAXX", "MAX"),
       "count": ("COUNT", "COUNTX", "COUNT")}
WINDOW_FNS = {"running-total": "SUM", "running-average": "AVG", "running-count": "COUNT", "running-minimum": "MIN", "running-maximum": "MAX",
              "moving-average": "AVG", "moving-total": "SUM", "rank": None, "percentile": None, "percent-rank": None}
RULES = {
    "cog.agg.total": ("total / sum", "high", "SUM of a column, or SUMX of a row expression"),
    "cog.agg.average": ("average", "high", "AVERAGE / AVERAGEX"),
    "cog.agg.count": ("count, count distinct", "high", "COUNT / DISTINCTCOUNT"),
    "cog.agg.minmax": ("minimum, maximum", "high", "MIN / MAX"),
    "cog.agg.auto": ("auto-summarised measure", "high", "a measure column in a calculation is summed (Cognos auto group & summarise)"),
    "cog.agg.for": ("aggregate … for level", "medium", "CALCULATE ( …, ALLSELECTED ( ), VALUES ( level ) ) — a total at the named level"),
    "cog.agg.report": ("aggregate … for report", "high", "CALCULATE ( …, ALLSELECTED ( ) ) — the total of the whole report"),
    "cog.agg.percentage": ("percentage", "high", "DIVIDE by the report (or level) total"),
    "cog.arith": ("+ − ×", "high", "arithmetic as written"),
    "cog.arith.divide": ("division", "high", "DIVIDE ( a, b ) — blank instead of an error on zero"),
    "cog.if": ("if … then … else", "high", "IF"),
    "cog.case": ("case … when", "high", "SWITCH"),
    "cog.logic": ("and, or, not, comparisons", "high", "&&, ||, NOT and the same operators"),
    "cog.in": ("in (…)", "high", "IN { … }"),
    "cog.isnull": ("is null / is missing", "high", "ISBLANK"),
    "cog.between": ("between", "high", "two comparisons"),
    "cog.str.concat": ("|| concatenation", "high", "&"),
    "cog.str.fn": ("upper, lower, trim, substring, character_length", "high", "UPPER, LOWER, TRIM, MID, LEN"),
    "cog.num.fn": ("_round, abs, power, sqrt, mod", "high", "ROUND, ABS, POWER, SQRT, MOD"),
    "cog.null.coalesce": ("coalesce", "high", "COALESCE"),
    "cog.date.part": ("_year, _month, _day of the fact date", "high", "the Date table's Year / Month / Day column"),
    "cog.date.fn": ("_days_between, _add_days, _year / _month of other dates", "medium", "DATEDIFF, date arithmetic, YEAR, MONTH"),
    "cog.cast": ("cast", "medium", "INT, CONVERT, VALUE"),
    "cog.attr.column": ("attribute item", "high", "the model column"),
    "cog.attr.calc": ("calculated attribute", "medium", "a calculated column on the dimension or Date table"),
    "cog.filter.constant": ("filter: item = constant", "high", "a report slicer with that default value"),
    "cog.filter.prompt": ("filter: item = ?prompt?", "high", "a report slicer (multi-select) with no default"),
    "cog.filter.measure": ("filter: item = constant on one query only", "medium", "CALCULATE ( …, column = value ) on that query's measures and WHERE in its visuals"),
    "cog.viz.list": ("list", "high", "table visual, first measure sorted descending"),
    "cog.viz.crosstab": ("crosstab", "medium", "stacked column chart with the column edge as the legend (Power BI's matrix is the hand-built alternative)"),
    "cog.viz.column": ("column / bar chart", "high", "Relay Columns (clustered)"),
    "cog.viz.line": ("line chart", "high", "Relay Lines"),
    "cog.viz.pie": ("pie chart", "high", "Relay Parts (donut)"),
    "cog.viz.pie.signed": ("pie chart of a signed measure", "high", "Relay Columns (bar): a share needs positive parts and the source data has negative ones"),
    "cog.viz.kpi": ("singleton / KPI", "high", "Relay Gauges (card)"),
    "cog.viz.gauge": ("gauge chart", "medium", "Relay Gauges (gauge)"),
    "cog.viz.repeater": ("repeater table", "low", "table visual"),
    "sql.window": ("running / moving / rank / percentile (SQL side)", "high", "window functions in the prototype SQL, so the proof can check the agent's DAX"),
    "learned": ("learned from an accepted answer", "medium", "a DAX pattern a person accepted on an earlier report"),
}
NO_DAX = {"running-total": "no DAX rule yet for running totals (reset levels differ per report)", "running-average": "no DAX rule yet for running averages",
          "running-count": "no DAX rule yet", "running-minimum": "no DAX rule yet", "running-maximum": "no DAX rule yet",
          "moving-average": "no DAX rule yet for moving averages", "moving-total": "no DAX rule yet", "rank": "no DAX rule yet for rank (ties and scope differ)",
          "percentile": "no DAX rule yet for percentile", "percent-rank": "no DAX rule yet", "lag": "no rule yet", "lead": "no rule yet",
          "first-of-month": "no rule yet", "_first_of_month": "no rule yet", "_last_of_month": "no rule yet", "current_date": "no rule yet (today's date)",
          "_week_of_year": "no rule yet", "quantile": "no rule yet", "standard-deviation": "no rule yet", "variance": "no rule yet"}
UNSUPPORTED_FEATURES = {"active report": "Active Reports (offline interactive decks) are not converted automatically",
                        "custom javascript": "HTML items with scripts are not converted (nothing runs scripts in Power BI)",
                        "HTML item": "HTML items are not converted", "specification could not be read": "the specification could not be read",
                        "section access": "section access needs row-level security designed by a person"}
UNSUPPORTED_VISUALS = {"map": "map visuals need a Power BI map chosen by a person", "html": "HTML items are not converted", "custom": "no rule yet for this visual",
                       "scatter": "no rule yet for scatter charts", "treemap": "no rule yet for treemaps", "heatmap": "no rule yet for heat maps", "filter": None, "text": None}


class RuleError(Exception):
    pass


def _dq(s: str) -> str:
    return '"' + str(s).replace('"', '""') + '"'


def _dax_str(s: str) -> str:
    return '"' + str(s).replace('"', '""') + '"'


def _sql_str(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def dax_col(table: str, col: str) -> str:
    return f"'{table}'[{col}]"


# ------------------------------------------------------------------ the context a translation runs in

class Context:
    """What the translator knows: the dataset's tables and columns, the query's data items, which items became
    measures (and their DAX names), the fact table and its date column, SQL aliases, and — per visual — the columns
    the visual groups by (for `for` levels and window partitions) and its row order (for running aggregates)."""

    def __init__(self, dataset: dict, items: list[dict], fact: str | None = None):
        self.dataset = dataset
        self.tables = {t["name"]: t for t in dataset.get("tables") or []}
        self.lower = {t.lower(): t for t in self.tables}
        self.cols = {t: {c["name"].lower(): c for c in tv.get("columns") or []} for t, tv in self.tables.items()}
        facts = [t["name"] for t in dataset.get("tables") or [] if t.get("role") == "fact"]
        self.fact = fact or (facts[0] if facts else next(iter(self.tables), None))
        self.date_col = next((c["name"] for c in (self.tables.get(self.fact) or {}).get("columns") or [] if c.get("role") == "date" or c.get("type") == "date"), None)
        self.items = {it["name"]: it for it in items}
        self.measure_names: dict[str, str] = {}        # item name -> DAX measure name
        self.column_items: dict[str, tuple[str, str]] = {}   # item name -> (table, column) for attribute items (incl. calculated)
        self.aliases: dict[str, str] = {}
        if self.fact:
            self.aliases[self.fact] = "f"
        for i, t in enumerate(n for n in self.tables if n != self.fact):
            self.aliases[t] = f"d{i + 1}"
        self.aliases["Date"] = "dt"
        self.group_cols: set[tuple[str, str]] = set()  # per visual
        self.order_sql: list[str] = []                 # per visual
        self.used_tables: set[str] = set()
        self.needs_date = False
        self._stack: list[str] = []

    def resolve(self, path: list[str]) -> tuple[str, str] | None:
        """[Pkg].[Table].[Col] / [Table].[Col] -> (table, column) of the dataset; None when not a column."""
        if len(path) >= 2:
            t = self.lower.get(path[-2].lower())
            if t and path[-1].lower() in self.cols[t]:
                return t, self.cols[t][path[-1].lower()]["name"]
            if len(path) == 2 and path[0].lower() not in self.lower:    # [Pkg].[Item]? no; [Item].[x] is not a thing
                return None
            return None
        name = path[0]
        for t in [self.fact] + [x for x in self.tables if x != self.fact] if self.fact else list(self.tables):
            if t and name.lower() in self.cols[t]:
                return t, self.cols[t][name.lower()]["name"]
        return None

    def col_role(self, table: str, col: str) -> str:
        c = self.cols.get(table, {}).get(col.lower()) or {}
        return c.get("role") or ("measure" if c.get("type") in ("int", "decimal") else "attribute")

    def alias(self, table: str) -> str:
        self.used_tables.add(table)
        return self.aliases.get(table, "f")


# ------------------------------------------------------------------ translation

class Translation:
    def __init__(self):
        self.dax: str | None = None
        self.sql: str | None = None
        self.kind = "measure"                 # measure | column | calc_column
        self.table: str | None = None
        self.column: str | None = None
        self.rules: list[str] = []
        self.gaps: list[dict] = []
        self.window = False
        self.ratio = False
        self.text = False
        self.format: str | None = None

    @property
    def confidence(self) -> str:
        if self.gaps:
            return "low"
        levels = [RULES.get(r, ("", "high", ""))[1] for r in self.rules]
        return "low" if "low" in levels else "medium" if "medium" in levels else "high"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "dax": self.dax, "sql": self.sql, "table": self.table, "column": self.column, "rules": sorted(set(self.rules)),
                "confidence": self.confidence, "gaps": self.gaps, "window": self.window, "format": self.format}


class _Emit:
    """Walks the AST once, producing DAX and SQL side by side. mode 'agg' = after aggregation (a measure);
    'row' = inside an aggregate (a row of the fact table)."""

    def __init__(self, ctx: Context, tr: Translation, pack: "RulePack | None" = None, related: bool = True):
        self.ctx, self.tr, self.pack, self.related = ctx, tr, pack, related

    def gap(self, fn: str, reason: str, node) -> tuple[str | None, str | None]:
        self.tr.gaps.append({"function": fn, "reason": reason, "expression": expr.to_text(node)})
        return None, None

    def rule(self, rid: str) -> None:
        self.tr.rules.append(rid)

    # ---- references
    def ref(self, node, mode: str) -> tuple:
        path = node["path"]
        if len(path) == 1 and path[0] in self.ctx.items and self.ctx.resolve(path) is None:
            name = path[0]
            if name in self.ctx._stack:
                raise RuleError(f"data item {name} refers to itself")
            it = self.ctx.items[name]
            if mode == "agg" and name in self.ctx.measure_names:          # another measure of this report
                self.ctx._stack.append(name)
                try:
                    sub = translate_measure(it, self.ctx, self.pack)
                finally:
                    self.ctx._stack.pop()
                self.tr.rules += sub.rules
                self.tr.gaps += sub.gaps
                self.tr.window = self.tr.window or sub.window
                return f"[{self.ctx.measure_names[name]}]", sub.sql
            self.ctx._stack.append(name)
            try:
                return self.node(expr.parse(it["expression"]), mode)
            finally:
                self.ctx._stack.pop()
        rc = self.ctx.resolve(path)
        if rc is None:
            raise RuleError(f"unknown column {expr.to_text(node)}")
        t, c = rc
        role = self.ctx.col_role(t, c)
        a = self.ctx.alias(t)
        if mode == "agg" and role == "measure":                            # auto-summarise
            self.rule("cog.agg.auto")
            return f"SUM ( {dax_col(t, c)} )", f"SUM({a}.{_dq(c)})"
        if mode == "agg" and (t, c) not in self.ctx.group_cols and role != "measure":
            # an attribute inside a measure: the single value in the current context
            return f"SELECTEDVALUE ( {dax_col(t, c)} )", f"{a}.{_dq(c)}"
        if mode == "row" and t != self.ctx.fact and self.related:
            return f"RELATED ( {dax_col(t, c)} )", f"{a}.{_dq(c)}"
        return dax_col(t, c), f"{a}.{_dq(c)}"

    # ---- nodes
    def node(self, n, mode: str) -> tuple:
        t = n["t"]
        if t == "ref":
            return self.ref(n, mode)
        if t == "num":
            v = n["v"]
            s = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
            return s, s
        if t == "str":
            self.tr.text = True
            return _dax_str(n["v"]), _sql_str(n["v"])
        if t == "null":
            return "BLANK ()", "NULL"
        if t == "ident":
            if n["v"].lower() in ("current_date", "current_timestamp", "today"):
                return self.gap(n["v"].lower(), NO_DAX.get("current_date", "no rule yet"), n)
            return _dax_str(n["v"]), _sql_str(n["v"])
        if t == "prompt":
            return self.gap("?prompt?", "a prompt value inside a calculation has no rule (slicers carry prompts; a parameter table is the Power BI way)", n)
        if t == "macro":
            return self.gap("#macro#", "macros (session values, prompt macros) have no rule", n)
        if t == "neg":
            d, s = self.node(n["x"], mode)
            return (f"-{d}" if d else None), (f"-({s})" if s else None)
        if t == "not":
            self.rule("cog.logic")
            d, s = self.node(n["x"], mode)
            return (f"NOT ( {d} )" if d else None), (f"NOT ({s})" if s else None)
        if t == "bin":
            return self.bin(n, mode)
        if t == "if":
            self.rule("cog.if")
            c = self.node(n["c"], mode); a = self.node(n["a"], mode); b = self.node(n["b"], mode) if n.get("b") else ("BLANK ()", "NULL")
            return _join([c[0], a[0], b[0]], lambda x: f"IF ( {x[0]}, {x[1]}, {x[2]} )"), _join([c[1], a[1], b[1]], lambda x: f"CASE WHEN {x[0]} THEN {x[1]} ELSE {x[2]} END")
        if t == "case":
            self.rule("cog.case")
            subj = self.node(n["subject"], mode) if n.get("subject") else None
            parts_d, parts_s = [], []
            for c, v in n["when"]:
                cd, cs = self.node(c, mode); vd, vs = self.node(v, mode)
                parts_d += [cd, vd]; parts_s.append((cs, vs))
            ed, es = self.node(n["else"], mode) if n.get("else") else ("BLANK ()", "NULL")
            if subj:
                dax = _join([subj[0]] + parts_d + [ed], lambda x: f"SWITCH ( {x[0]}, " + ", ".join(x[1:-1]) + f", {x[-1]} )")
                sql = _join([subj[1]] + [p for cs, vs in parts_s for p in (cs, vs)] + [es],
                            lambda x: f"CASE {x[0]} " + " ".join(f"WHEN {x[i]} THEN {x[i + 1]}" for i in range(1, len(x) - 1, 2)) + f" ELSE {x[-1]} END")
            else:
                dax = _join(parts_d + [ed], lambda x: "SWITCH ( TRUE (), " + ", ".join(x[:-1]) + f", {x[-1]} )")
                sql = _join([p for cs, vs in parts_s for p in (cs, vs)] + [es],
                            lambda x: "CASE " + " ".join(f"WHEN {x[i]} THEN {x[i + 1]}" for i in range(0, len(x) - 1, 2)) + f" ELSE {x[-1]} END")
            return dax, sql
        if t == "in":
            self.rule("cog.in")
            x = self.node(n["x"], mode); vals = [self.node(v, mode) for v in n["vals"]]
            dax = _join([x[0]] + [v[0] for v in vals], lambda p: (f"NOT ( {p[0]} IN {{ " if n.get("neg") else f"{p[0]} IN {{ ") + ", ".join(p[1:]) + (" } )" if n.get("neg") else " }"))
            sql = _join([x[1]] + [v[1] for v in vals], lambda p: f"{p[0]} {'NOT ' if n.get('neg') else ''}IN (" + ", ".join(p[1:]) + ")")
            return dax, sql
        if t == "isnull":
            self.rule("cog.isnull")
            d, s = self.node(n["x"], mode)
            return (f"{'NOT ' if n.get('neg') else ''}ISBLANK ( {d} )" if d else None), (f"{s} IS {'NOT ' if n.get('neg') else ''}NULL" if s else None)
        if t == "between":
            self.rule("cog.between")
            x = self.node(n["x"], mode); lo = self.node(n["lo"], mode); hi = self.node(n["hi"], mode)
            dax = _join([x[0], lo[0], hi[0]], lambda p: (f"NOT ( {p[0]} >= {p[1]} && {p[0]} <= {p[2]} )" if n.get("neg") else f"( {p[0]} >= {p[1]} && {p[0]} <= {p[2]} )"))
            sql = _join([x[1], lo[1], hi[1]], lambda p: f"{p[0]} {'NOT ' if n.get('neg') else ''}BETWEEN {p[1]} AND {p[2]}")
            return dax, sql
        if t == "like":
            return self.gap("like", "pattern matching has no rule yet", n)
        if t == "call":
            return self.call(n, mode)
        raise RuleError(f"unknown node {t}")

    def bin(self, n, mode: str) -> tuple:
        op = n["op"]
        ld, ls = self.node(n["l"], mode)
        rd, rs = self.node(n["r"], mode)
        if op in ("and", "or"):
            self.rule("cog.logic")
            return _join([ld, rd], lambda x: f"( {x[0]} {'&&' if op == 'and' else '||'} {x[1]} )"), _join([ls, rs], lambda x: f"({x[0]} {op.upper()} {x[1]})")
        if op in ("=", "<>", "<", ">", "<=", ">="):
            self.rule("cog.logic")
            return _join([ld, rd], lambda x: f"{x[0]} {op} {x[1]}"), _join([ls, rs], lambda x: f"{x[0]} {op} {x[1]}")
        if op == "||":
            self.rule("cog.str.concat")
            self.tr.text = True
            return _join([ld, rd], lambda x: f"{x[0]} & {x[1]}"), _join([ls, rs], lambda x: f"({x[0]} || {x[1]})")
        if op == "/":
            self.rule("cog.arith.divide")
            self.tr.ratio = self.tr.ratio or mode == "agg"
            return _join([ld, rd], lambda x: f"DIVIDE ( {x[0]}, {x[1]} )"), _join([ls, rs], lambda x: f"(CASE WHEN ({x[1]}) = 0 THEN NULL ELSE ({x[0]}) / ({x[1]}) END)")
        self.rule("cog.arith")
        return _join([ld, rd], lambda x: f"( {x[0]} {op} {x[1]} )"), _join([ls, rs], lambda x: f"({x[0]} {op} {x[1]})")

    def partition(self, levels) -> tuple[str, str]:
        """`for` levels -> DAX filter arguments and the SQL window partition (only columns the visual groups by)."""
        dax_parts, sql_parts = [], []
        for lv in levels:
            rc = self.ctx.resolve(lv["path"]) if lv["t"] == "ref" else None
            if rc is None and lv["t"] == "ref" and lv["path"][0] in self.ctx.column_items:
                rc = self.ctx.column_items[lv["path"][0]]
            if rc is None:
                raise RuleError(f"the for clause names {expr.to_text(lv)}, which is not a column")
            t, c = rc
            dax_parts.append(f"VALUES ( {dax_col(t, c)} )")
            if (t, c) in self.ctx.group_cols:
                sql_parts.append(f"{self.ctx.alias(t)}.{_dq(c)}")
        return ", ".join(dax_parts), (" PARTITION BY " + ", ".join(sql_parts)) if sql_parts else ""

    def aggregate(self, n, mode: str) -> tuple:
        fn = n["fn"]
        dax_fn, dax_x, sql_fn = AGG[fn]
        arg = n["args"][0] if n["args"] else None
        if arg is None:
            raise RuleError(f"{fn}() needs an argument")
        plain = arg["t"] == "ref" and self.ctx.resolve(arg["path"]) is not None
        if n.get("distinct"):
            if fn != "count" or not plain:
                return self.gap(fn, f"{fn}(distinct …) is only a rule for a plain column", n)
            self.rule("cog.agg.count")
            t, c = self.ctx.resolve(arg["path"])
            dax, sql = f"DISTINCTCOUNT ( {dax_col(t, c)} )", f"COUNT(DISTINCT {self.ctx.alias(t)}.{_dq(c)})"
        elif plain:
            self.rule({"count": "cog.agg.count", "average": "cog.agg.average", "avg": "cog.agg.average", "minimum": "cog.agg.minmax", "maximum": "cog.agg.minmax",
                       "min": "cog.agg.minmax", "max": "cog.agg.minmax"}.get(fn, "cog.agg.total"))
            t, c = self.ctx.resolve(arg["path"])
            dax, sql = f"{dax_fn} ( {dax_col(t, c)} )", f"{sql_fn}({self.ctx.alias(t)}.{_dq(c)})"
        else:
            self.rule({"count": "cog.agg.count", "average": "cog.agg.average", "avg": "cog.agg.average"}.get(fn, "cog.agg.total"))
            rd, rs = self.node(arg, "row")
            if rd is None or rs is None:
                return None, None
            dax, sql = f"{dax_x} ( '{self.ctx.fact}', {rd} )", f"{sql_fn}({rs})"
        if n.get("for") is not None:
            if not n["for"]:
                self.rule("cog.agg.report")
                return f"CALCULATE ( {dax}, ALLSELECTED ( ) )", f"{sql_fn}({sql}) OVER ()" if sql_fn in ("SUM", "MIN", "MAX") else self.gap(fn, f"{fn} … for report of a non-additive aggregate has no SQL rule", n)
            self.rule("cog.agg.for")
            dax_f, sql_p = self.partition(n["for"])
            self.tr.window = True
            if sql_fn in ("SUM", "MIN", "MAX"):
                return f"CALCULATE ( {dax}, ALLSELECTED ( ), {dax_f} )", f"{sql_fn}({sql}) OVER ({sql_p.strip()})"
            return self.gap(fn, f"{fn} … for level of a non-additive aggregate has no SQL rule", n)
        return dax, sql

    def call(self, n, mode: str) -> tuple:
        fn = n["fn"]
        args = n["args"]
        if fn in AGG:
            return self.aggregate(n, "agg")
        if fn == "percentage":
            self.rule("cog.agg.percentage")
            inner = {"t": "call", "fn": "total", "args": args, "for": None, "distinct": False, "reset": None}
            d, s = self.aggregate(inner, "agg")
            if d is None:
                return None, None
            self.tr.ratio = True
            self.tr.window = True
            if n.get("for"):
                dax_f, sql_p = self.partition(n["for"])
                return f"DIVIDE ( {d}, CALCULATE ( {d}, ALLSELECTED ( ), {dax_f} ) )", f"(CASE WHEN SUM({s}) OVER ({sql_p.strip()}) = 0 THEN NULL ELSE {s} / SUM({s}) OVER ({sql_p.strip()}) END)"
            return f"DIVIDE ( {d}, CALCULATE ( {d}, ALLSELECTED ( ) ) )", f"(CASE WHEN SUM({s}) OVER () = 0 THEN NULL ELSE {s} / SUM({s}) OVER () END)"
        if fn in WINDOW_FNS:
            return self.windowed(n)
        if fn in ("upper", "lower", "trim"):
            self.rule("cog.str.fn"); self.tr.text = True
            d, s = self.node(args[0], mode)
            return _join([d], lambda x: f"{fn.upper()} ( {x[0]} )"), _join([s], lambda x: f"{fn}({x[0]})")
        if fn == "substring":
            self.rule("cog.str.fn"); self.tr.text = True
            parts = [self.node(a, mode) for a in args]
            return _join([p[0] for p in parts], lambda x: f"MID ( {x[0]}, {x[1]}, {x[2]} )" if len(x) > 2 else f"MID ( {x[0]}, {x[1]}, 10000 )"), \
                _join([p[1] for p in parts], lambda x: f"substr({x[0]}, {x[1]}, {x[2]})" if len(x) > 2 else f"substr({x[0]}, {x[1]})")
        if fn in ("character_length", "char_length", "length"):
            self.rule("cog.str.fn")
            d, s = self.node(args[0], mode)
            return _join([d], lambda x: f"LEN ( {x[0]} )"), _join([s], lambda x: f"length({x[0]})")
        if fn in ("_round", "round"):
            self.rule("cog.num.fn")
            parts = [self.node(a, mode) for a in args]
            return _join([p[0] for p in parts], lambda x: f"ROUND ( {x[0]}, {x[1] if len(x) > 1 else 0} )"), _join([p[1] for p in parts], lambda x: f"round({x[0]}, {x[1] if len(x) > 1 else 0})")
        if fn in ("abs", "sqrt", "power", "mod", "floor", "ceiling", "_floor", "_ceiling", "exp", "ln"):
            self.rule("cog.num.fn")
            parts = [self.node(a, mode) for a in args]
            dfn = {"_floor": "FLOOR", "_ceiling": "CEILING", "ln": "LN"}.get(fn, fn.upper())
            if fn in ("floor", "_floor"):
                return _join([p[0] for p in parts], lambda x: f"FLOOR ( {x[0]}, 1 )"), _join([p[1] for p in parts], lambda x: f"floor({x[0]})")
            if fn in ("ceiling", "_ceiling"):
                return _join([p[0] for p in parts], lambda x: f"CEILING ( {x[0]}, 1 )"), _join([p[1] for p in parts], lambda x: f"ceiling({x[0]})")
            return _join([p[0] for p in parts], lambda x: f"{dfn} ( " + ", ".join(x) + " )"), _join([p[1] for p in parts], lambda x: f"{fn}(" + ", ".join(x) + ")")
        if fn == "coalesce":
            self.rule("cog.null.coalesce")
            parts = [self.node(a, mode) for a in args]
            return _join([p[0] for p in parts], lambda x: "COALESCE ( " + ", ".join(x) + " )"), _join([p[1] for p in parts], lambda x: "coalesce(" + ", ".join(x) + ")")
        if fn in ("_year", "_month", "_day", "year", "month", "day", "extract"):
            part = {"_year": "Year", "year": "Year", "_month": "Month", "month": "Month", "_day": "Day", "day": "Day"}.get(fn)
            arg = args[-1]
            rc = self.ctx.resolve(arg["path"]) if arg["t"] == "ref" else None
            if rc and rc == (self.ctx.fact, self.ctx.date_col) and part in ("Year", "Month"):
                self.rule("cog.date.part"); self.ctx.needs_date = True
                col = "Year" if part == "Year" else "Month"
                self.tr.kind = "column"
                return dax_col("Date", col), f"dt.{_dq(col)}"
            self.rule("cog.date.fn")
            d, s = self.node(arg, mode)
            dfn = {"Year": "YEAR", "Month": "MONTH", "Day": "DAY"}.get(part, "YEAR")
            return _join([d], lambda x: f"{dfn} ( {x[0]} )"), _join([s], lambda x: f"{dfn.lower()}({x[0]})")
        if fn == "_days_between":
            self.rule("cog.date.fn")
            a, b = self.node(args[0], mode), self.node(args[1], mode)
            return _join([a[0], b[0]], lambda x: f"DATEDIFF ( {x[1]}, {x[0]}, DAY )"), _join([a[1], b[1]], lambda x: f"date_diff('day', {x[1]}, {x[0]})")
        if fn == "_add_days":
            self.rule("cog.date.fn")
            a, b = self.node(args[0], mode), self.node(args[1], mode)
            return _join([a[0], b[0]], lambda x: f"( {x[0]} + {x[1]} )"), _join([a[1], b[1]], lambda x: f"({x[0]} + INTERVAL ({x[1]}) DAY)")
        if fn == "cast":
            self.rule("cog.cast")
            d, s = self.node(args[0], mode)
            typ = expr.to_text(args[1]).lower() if len(args) > 1 else "decimal"
            if "int" in typ:
                return _join([d], lambda x: f"INT ( {x[0]} )"), _join([s], lambda x: f"CAST({x[0]} AS BIGINT)")
            if "char" in typ or "text" in typ or "string" in typ:
                self.tr.text = True
                return _join([d], lambda x: f"CONVERT ( {x[0]}, STRING )"), _join([s], lambda x: f"CAST({x[0]} AS VARCHAR)")
            return _join([d], lambda x: f"( {x[0]} * 1.0 )"), _join([s], lambda x: f"CAST({x[0]} AS DOUBLE)")
        if fn in NO_DAX:
            return self.gap(fn, NO_DAX[fn], n)
        return self.gap(fn, f"no rule yet for {fn}()", n)

    def windowed(self, n) -> tuple:
        """running-*, moving-*, rank, percentile: SQL by window functions (sql.window); DAX from a learned rule or the agent."""
        fn = n["fn"]
        self.rule("sql.window")
        self.tr.window = True
        arg = n["args"][0] if n["args"] else None
        if arg is None:
            raise RuleError(f"{fn}() needs an argument")
        inner = {"t": "call", "fn": "total", "args": [arg], "for": None, "distinct": False, "reset": None}
        d, s = self.aggregate(inner, "agg")
        learned = self.pack.lookup(expr.to_text(n), self.ctx) if self.pack else None
        dax = None
        if learned:
            self.rule("learned")
            dax = learned
        else:
            self.tr.gaps.append({"function": fn, "reason": NO_DAX.get(fn, "no DAX rule yet"), "expression": expr.to_text(n)})
        if s is None:
            return dax, None
        part = ""
        if n.get("for"):
            _, part = self.partition(n["for"])
        order = ", ".join(self.ctx.order_sql) if self.ctx.order_sql else "1"
        if fn == "rank":
            sql = f"RANK() OVER ({part.strip()}{' ' if part else ''}ORDER BY {s} DESC)"
        elif fn in ("percentile", "percent-rank"):
            sql = f"(100 * PERCENT_RANK() OVER ({part.strip()}{' ' if part else ''}ORDER BY {s}))"
        elif fn.startswith("moving-"):
            k = int(n["args"][1]["v"]) if len(n["args"]) > 1 and n["args"][1]["t"] == "num" else 3
            sql = f"{WINDOW_FNS[fn]}({s}) OVER ({part.strip()}{' ' if part else ''}ORDER BY {order} ROWS BETWEEN {max(0, k - 1)} PRECEDING AND CURRENT ROW)"
        else:
            sql = f"{WINDOW_FNS[fn]}({s}) OVER ({part.strip()}{' ' if part else ''}ORDER BY {order} ROWS UNBOUNDED PRECEDING)"
        return dax, sql


def _join(parts, fmt):
    return None if any(p is None for p in parts) else fmt(parts)


def is_attribute_item(item: dict, ctx: Context) -> bool:
    """An item that groups rows (a column, or a row-level function of attribute / date columns) rather than a number
    to add up."""
    try:
        node = expr.parse(item["expression"])
    except expr.ParseError:
        return False
    if item.get("aggregate"):
        return False
    fns = expr.functions(node)
    if any(f in AGG or f == "percentage" or f in WINDOW_FNS for f in fns):
        return False
    for path in expr.refs(node):
        rc = ctx.resolve(path)
        if rc is None:
            if len(path) == 1 and path[0] in ctx.items and path[0] in ctx.column_items:
                continue
            return False
        if ctx.col_role(*rc) == "measure":
            return False
    return bool(expr.refs(node)) and not expr.has_macro(node)


def translate_attribute(item: dict, ctx: Context) -> Translation:
    """An attribute item -> a model column (or a calculated column on its table / the Date table)."""
    tr = Translation()
    tr.kind = "column"
    node = expr.parse(item["expression"])
    if node["t"] == "ref":
        rc = ctx.resolve(node["path"])
        if rc is None and len(node["path"]) == 1 and node["path"][0] in ctx.column_items:
            rc = ctx.column_items[node["path"][0]]
        if rc is None:
            raise RuleError(f"unknown column {item['expression']}")
        tr.table, tr.column = rc
        tr.rules.append("cog.attr.column")
        tr.dax, tr.sql = dax_col(*rc), f"{ctx.alias(rc[0])}.{_dq(rc[1])}"
        return tr
    em = _Emit(ctx, tr, related=False)             # a calculated column lives on its own table: plain column references
    d, s = em.node(node, "row")
    tr.dax, tr.sql = d, s
    if tr.gaps or d is None:
        tr.kind = "calc_column"
        return tr
    if tr.kind == "column" and d.startswith("'Date'[") and re.fullmatch(r"'Date'\[[^\]]+\]", d):
        tr.table, tr.column = "Date", d[7:-1]
        return tr
    # a calculated column on the table the expression reads (one table only), else on the Date table
    tables = {ctx.resolve(p)[0] for p in expr.refs(node) if ctx.resolve(p)} or ({"Date"} if ctx.needs_date else set())
    if "Date" in d and ctx.needs_date:
        tables.add("Date")
    tr.kind = "calc_column"
    tr.rules.append("cog.attr.calc")
    tr.table = "Date" if "Date" in tables or ctx.needs_date and len(tables) > 1 else (next(iter(tables)) if tables else ctx.fact)
    tr.column = item["name"]
    return tr


def translate_measure(item: dict, ctx: Context, pack: "RulePack | None" = None) -> Translation:
    tr = Translation()
    try:
        node = expr.parse(item["expression"])
    except expr.ParseError as e:
        tr.gaps.append({"function": "?", "reason": f"the expression could not be read ({e})", "expression": item["expression"]})
        return tr
    em = _Emit(ctx, tr, pack)
    if node["t"] == "ref" and ctx.resolve(node["path"]) and item.get("aggregate"):
        node = {"t": "call", "fn": item["aggregate"], "args": [node], "for": None, "distinct": item.get("aggregate") == "count distinct", "reset": None}
    elif item.get("aggregate") and node["t"] != "call":
        node = {"t": "call", "fn": item["aggregate"], "args": [node], "for": None, "distinct": False, "reset": None}
    try:
        d, s = em.node(node, "agg")
    except RuleError as e:
        tr.gaps.append({"function": "?", "reason": str(e), "expression": item["expression"]})
        return tr
    if d is None and not tr.gaps:
        learned = pack.lookup(item["expression"], ctx) if pack else None
        if learned:
            tr.rules.append("learned")
            d = learned
    tr.dax, tr.sql = d, s
    tr.format = "" if tr.text else "0.0%" if tr.ratio else "#,0.00" if ("average" in item["expression"].lower() or "/" in item["expression"]) else "#,0"
    return tr


# ------------------------------------------------------------------ visuals

VISUAL_MAP = {"list": ("table", None, "cog.viz.list"), "crosstab": ("atlasColumns", "stackedColumn", "cog.viz.crosstab"), "column": ("atlasColumns", "clusteredColumn", "cog.viz.column"),
              "bar": ("atlasColumns", "clusteredBar", "cog.viz.column"), "line": ("atlasLines", "line", "cog.viz.line"), "pie": ("atlasParts", "donut", "cog.viz.pie"),
              "kpi": ("atlasGauges", "card", "cog.viz.kpi"), "gauge": ("atlasGauges", "gauge", "cog.viz.gauge"), "repeater": ("table", None, "cog.viz.repeater")}


# When a programme targets Power BI's built-in visuals: the Atlas visual a rule chose -> the built-in visual for it
BUILTIN_MAP = {("atlasColumns", "clusteredColumn"): "pbi.clusteredColumnChart", ("atlasColumns", "stackedColumn"): "pbi.columnChart",
               ("atlasColumns", "clusteredBar"): "pbi.clusteredBarChart", ("atlasColumns", "stackedBar"): "pbi.barChart",
               ("atlasLines", "line"): "pbi.lineChart", ("atlasLines", "area"): "pbi.areaChart",
               ("atlasParts", "donut"): "pbi.donutChart", ("atlasParts", "pie"): "pbi.pieChart",
               ("atlasGauges", "card"): "pbi.cardVisual", ("atlasGauges", "gauge"): "pbi.gauge"}


def builtin_visual(vis: dict) -> dict:
    """The same visual as one of Power BI's own (`pbi.*`): wells renamed, the prototype SQL unchanged (both read one
    column per field, named after the field). Tables stay Power BI's table; anything unmapped is returned as it is."""
    t = BUILTIN_MAP.get((vis.get("type"), vis.get("chart")))
    if not t:
        return vis
    f = vis.get("fields") or {}
    values = f.get("values") if isinstance(f.get("values"), list) else [f["values"]] if f.get("values") else []
    if t == "pbi.cardVisual":
        fields = {"values": values}
    elif t == "pbi.gauge":
        fields = {"value": values[0]} if values else {}
    elif t in ("pbi.donutChart", "pbi.pieChart"):
        fields = {"legend": f.get("category"), "values": values[:1]}
    else:
        fields = {"axis": f.get("category"), "values": values[:1] if f.get("series") else values,
                  **({"legend": f["series"]} if f.get("series") else {})}
    out = {k: v for k, v in vis.items() if k not in ("type", "chart", "fields", "format")}
    return {**out, "type": t, "fields": {k: v for k, v in fields.items() if v}}


def visual_rule(v: dict) -> dict:
    """Which catalogue visual a source visual becomes, with the rule, confidence and reason."""
    k = v.get("kind")
    if k in VISUAL_MAP:
        typ, chart, rid = VISUAL_MAP[k]
        if k == "crosstab" and not v.get("series"):
            typ, chart, rid = "table", None, "cog.viz.list"
        return {"type": typ, "chart": chart, "rule": rid, "confidence": RULES[rid][1], "reason": RULES[rid][2]}
    reason = UNSUPPORTED_VISUALS.get(k, f"no rule yet for {k} visuals")
    return {"type": None, "chart": None, "rule": None, "confidence": "low", "reason": reason, "skip": reason is None}


# ------------------------------------------------------------------ prediction ("Ready to convert")

def predict(report: dict, dataset: dict | None, pack: "RulePack | None" = None) -> dict:
    """Before any conversion: automatic / needs review / not yet — with a confidence and a one-line reason, from the
    rules alone (no AI). auto = every calculation and visual has a rule (or one calculation needs the agent);
    review = 1-3 calculations without a rule, a medium-confidence visual, or a filter without a rule;
    no = an unsupported feature, no dataset, or 4+ calculations without a rule."""
    gaps, notes, low = [], [], []
    feats = [f for f in report.get("features") or [] if f in UNSUPPORTED_FEATURES]
    if not dataset:
        return {"convert": "no", "confidence": "high", "no_rule": 0, "reason": f"its package is missing ({report.get('missing_dataset') or 'unknown'})", "gaps": [], "unsupported": feats}
    for f in feats:
        low.append(UNSUPPORTED_FEATURES[f])
    for q in report.get("queries") or []:
        ctx = Context(dataset, q.get("items") or [])
        for it in q.get("items") or []:
            try:
                if is_attribute_item(it, ctx):
                    ctx.column_items[it["name"]] = (ctx.fact or "", it["name"])
                    tr = translate_attribute(it, ctx)
                else:
                    ctx.measure_names[it["name"]] = it["name"]
                    tr = translate_measure(it, ctx, pack)
            except RuleError as e:
                gaps.append({"function": "?", "reason": str(e), "expression": it["expression"], "item": it["name"]})
                continue
            for g in tr.gaps:
                gaps.append({**g, "item": it["name"]})
        for f in q.get("filters") or []:
            if filter_rule(f["expression"], ctx)[0] is None:
                notes.append(f"filter “{f['expression']}” has no rule")
    unsupported = []
    for p in report.get("pages") or []:
        for v in p.get("visuals") or []:
            vr = visual_rule(v)
            if vr["type"] is None and not vr.get("skip"):
                unsupported.append(vr["reason"])
            elif vr["confidence"] == "medium":
                notes.append(f"{v['kind']}: {vr['reason']}")
    n_gap = len(gaps)
    if low or n_gap >= 4:
        convert = "no"
        reason = low[0] if low else f"{n_gap} calculations have no rule yet"
        conf = "high" if low else "medium"
    elif unsupported:
        convert = "review"; reason = unsupported[0]; conf = "medium"
    elif n_gap >= 2 or (n_gap == 1 and any("filter" in n for n in notes)):
        convert = "review"; reason = f"{n_gap} calculation{'s' if n_gap > 1 else ''} ha{'ve' if n_gap > 1 else 's'} no rule yet ({gaps[0]['function']})"; conf = "medium"
    elif n_gap == 1:
        convert = "auto"; reason = f"1 calculation needs the agent ({gaps[0]['function']}); every other formula and visual has a rule"; conf = "medium"
    elif notes:
        convert = "review" if any("filter" in n for n in notes) else "auto"
        reason = notes[0]; conf = "medium"
    else:
        convert = "auto"; reason = "every formula, filter and visual has a tested rule"; conf = "high"
    return {"convert": convert, "confidence": conf, "no_rule": n_gap, "reason": reason, "gaps": gaps[:12], "unsupported": low + unsupported, "notes": notes[:6]}


def filter_rule(expression: str, ctx: Context) -> tuple[str | None, dict | None]:
    """A query filter -> ("cog.filter.constant", {field, default}) | ("cog.filter.prompt", {field, prompt}) | (None, why)."""
    try:
        node = expr.parse(expression)
    except expr.ParseError as e:
        return None, {"reason": f"could not read the filter ({e})"}
    if node["t"] == "bin" and node["op"] == "=" and node["l"]["t"] == "ref":
        rc = _filter_field(node["l"], ctx)
        if rc is None:
            return None, {"reason": f"the filter's item {expr.to_text(node['l'])} is not a column"}
        t, c = rc
        if node["r"]["t"] == "prompt":
            return "cog.filter.prompt", {"field": f"{t}[{c}]", "prompt": node["r"]["name"], "label": c}
        if node["r"]["t"] in ("num", "str"):
            return "cog.filter.constant", {"field": f"{t}[{c}]", "default": node["r"]["v"], "label": c}
    return None, {"reason": "only item = constant and item = ?prompt? filters have rules; summary and measure filters need a person or the agent"}


def _filter_field(ref, ctx: Context):
    rc = ctx.resolve(ref["path"])
    if rc is not None:
        return rc
    name = ref["path"][0]
    it = ctx.items.get(name) if len(ref["path"]) == 1 else None
    if it and is_attribute_item(it, ctx):
        tr = translate_attribute(it, ctx)
        if tr.kind == "column" and tr.table and tr.column:
            return tr.table, tr.column
    return None


# ------------------------------------------------------------------ rule packs (learned per tenant / partner)

class RulePack:
    """Rules learned from accepted agent answers: normalised Cognos expression pattern -> DAX template with {n}
    placeholders for the column references, who accepted it, on which report, how often reused."""

    def __init__(self, path: Path | None = None, tenant: str = "default"):
        self.path = Path(path) if path else None
        self.tenant = tenant
        self.rules: list[dict] = []
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.rules = data.get("rules") or []
                self.tenant = data.get("tenant") or tenant
            except ValueError:
                self.rules = []

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"tenant": self.tenant, "saved": time.time(), "rules": self.rules}, indent=1), encoding="utf-8")

    def lookup(self, expression: str, ctx: Context) -> str | None:
        pattern, refs = expr.normalise(expression)
        for r in self.rules:
            if r["pattern"] == pattern and len(refs) == len(r.get("refs") or []):
                try:
                    out = r["dax"]
                    for i, ref in enumerate(refs):
                        rc = ctx.resolve(ref.split("."))
                        if rc is None:
                            return None
                        out = out.replace("{" + str(i) + "}", dax_col(*rc))
                    r["uses"] = r.get("uses", 0) + 1
                    return out
                except (KeyError, ValueError):
                    return None
        return None

    def learn(self, expression: str, dax: str, ctx: Context, who: str, report: str | None = None) -> dict | None:
        """Turn an accepted measure into a template: every resolved column of the expression becomes {n} in the DAX."""
        pattern, refs = expr.normalise(expression)
        if not refs or not dax or not dax.strip():
            return None
        template = dax
        for i, ref in enumerate(refs):
            rc = ctx.resolve(ref.split("."))
            if rc is None:
                return None
            t, c = rc
            template = re.sub(r"(?:'%s'|\b%s)\[%s\]" % (re.escape(t), re.escape(t), re.escape(c)), "{" + str(i) + "}", template)
        for r in self.rules:
            if r["pattern"] == pattern:
                r.update(dax=template, refs=refs, accepted_by=who, report=report, when=time.time())
                return r
        rule = {"id": f"learned.{len(self.rules) + 1}", "pattern": pattern, "refs": refs, "dax": template, "accepted_by": who, "report": report,
                "when": time.time(), "uses": 0, "function": (expr.functions(expr.parse(expression)) or ["?"])[0]}
        self.rules.append(rule)
        return rule

    def stats(self) -> dict:
        return {"tenant": self.tenant, "rules": len(self.rules), "uses": sum(r.get("uses", 0) for r in self.rules),
                "functions": sorted({r.get("function") for r in self.rules if r.get("function")})}


def catalogue() -> list[dict]:
    """Every built-in rule for the UI: id, what it covers, confidence, what it produces."""
    return [{"id": k, "covers": v[0], "confidence": v[1], "produces": v[2]} for k, v in RULES.items()]
