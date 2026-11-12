"""The source simulator: a small, independent engine that runs a source report's query the way the source tool would
- rows of the package's tables joined through its relationships, filtered, grouped by the visual's attribute items,
aggregated with Cognos semantics (total / average / count / minimum / maximum / percentage, `for` levels, running
and moving aggregates, rank, percentile, if / case, arithmetic calculated after aggregation) - written in plain
Python over the CSVs, so it shares no code with the SQL and DAX the rules emit. The proof compares its numbers with
the converted report's prototype SQL (and, when the DAX checker runs, with Power BI's own engine).
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import re
from pathlib import Path

from . import expr

AGG_FNS = {"total", "sum", "average", "avg", "count", "minimum", "min", "maximum", "max", "percentage"}
WINDOW_FNS = {"running-total", "running-average", "running-count", "running-minimum", "running-maximum", "moving-average", "moving-total", "rank", "percentile", "percent-rank"}


class SimError(Exception):
    pass


def _typed(v: str, typ: str):
    if v is None or v == "":
        return None
    try:
        if typ == "int":
            return int(float(v))
        if typ == "decimal":
            return float(v)
        if typ == "date":
            return dt.date.fromisoformat(v[:10])
        if typ == "bool":
            return v.strip().lower() in ("true", "1", "yes")
    except ValueError:
        return None
    return v


class Source:
    """The dataset's rows, joined: every fact row carries its dimension columns as (table, column) keys."""

    def __init__(self, dataset: dict, data_dir: Path):
        self.dataset, self.data_dir = dataset, Path(data_dir)
        self.tables = {t["name"]: t for t in dataset.get("tables") or []}
        self.fact = next((t["name"] for t in dataset.get("tables") or [] if t.get("role") == "fact"), next(iter(self.tables), None))
        self.date_col = next((c["name"] for c in self.tables[self.fact].get("columns") or [] if c.get("role") == "date" or c.get("type") == "date"), None) if self.fact else None
        self.rows: list[dict] = []
        self._load()

    def _read(self, t: dict) -> list[dict]:
        f = self.data_dir / (t.get("file") or "")
        if not t.get("file") or not f.exists():
            raise SimError(f"no data file for {t['name']} ({t.get('file')})")
        types = {c["name"]: c["type"] for c in t.get("columns") or []}
        out = []
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                out.append({k: _typed(v, types.get(k, "string")) for k, v in row.items()})
        return out

    def _load(self) -> None:
        fact_rows = self._read(self.tables[self.fact])
        joins = []
        for r in self.dataset.get("relationships") or []:
            m1 = re.match(r"^(.+?)\[(.+)\]$", r["from"]); m2 = re.match(r"^(.+?)\[(.+)\]$", r["to"])
            if m1 and m2 and m1.group(1) == self.fact and m2.group(1) in self.tables:
                dim = m2.group(1)
                index = {row[m2.group(2)]: row for row in self._read(self.tables[dim])}
                joins.append((m1.group(2), dim, index))
        for row in fact_rows:
            full = {(self.fact, k): v for k, v in row.items()}
            for fk, dim, index in joins:
                drow = index.get(row.get(fk)) or {}
                for k in (c["name"] for c in self.tables[dim].get("columns") or []):
                    full[(dim, k)] = drow.get(k)
            self.rows.append(full)

    def resolve(self, path: list[str]) -> tuple[str, str] | None:
        if len(path) >= 2:
            t = next((n for n in self.tables if n.lower() == path[-2].lower()), None)
            if t:
                c = next((cc["name"] for cc in self.tables[t].get("columns") or [] if cc["name"].lower() == path[-1].lower()), None)
                if c:
                    return t, c
            return None
        for t in [self.fact] + [x for x in self.tables if x != self.fact]:
            c = next((cc["name"] for cc in self.tables[t].get("columns") or [] if cc["name"].lower() == path[0].lower()), None)
            if c:
                return t, c
        return None


def _num(v):
    return None if v is None else (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)


class Evaluator:
    """Evaluates data items for one visual: row-level expressions per fact row, aggregates per group, then
    calculations after aggregation (Cognos: calculated items are computed on the aggregated rows)."""

    def __init__(self, src: Source, items: list[dict]):
        self.src = src
        self.items = {it["name"]: it for it in items}
        self.asts: dict[str, dict] = {}
        for it in items:
            try:
                self.asts[it["name"]] = expr.parse(it["expression"])
            except expr.ParseError:
                self.asts[it["name"]] = {"t": "macro", "text": it["expression"]}
        self.cache_attr: dict[str, bool] = {}

    # ---- classification
    def is_attribute(self, name: str) -> bool:
        if name in self.cache_attr:
            return self.cache_attr[name]
        it = self.items.get(name)
        node = self.asts.get(name)
        out = False
        if it and node and not it.get("aggregate") and not any(f in AGG_FNS or f in WINDOW_FNS for f in expr.functions(node)) and not expr.has_macro(node):
            refs = expr.refs(node)
            out = bool(refs)
            for p in refs:
                rc = self.src.resolve(p)
                if rc is None:
                    if len(p) == 1 and p[0] in self.items and p[0] != name:
                        out = out and self.is_attribute(p[0])
                    else:
                        out = False
                elif self._role(rc) == "measure":
                    out = False
        self.cache_attr[name] = out
        return out

    def _role(self, rc):
        t, c = rc
        col = next((x for x in self.src.tables[t].get("columns") or [] if x["name"] == c), {})
        return col.get("role") or ("measure" if col.get("type") in ("int", "decimal") else "attribute")

    # ---- row level
    def row_value(self, node, row: dict):
        t = node["t"]
        if t == "ref":
            rc = self.src.resolve(node["path"])
            if rc is None:
                name = node["path"][0]
                if len(node["path"]) == 1 and name in self.asts:
                    return self.row_value(self.asts[name], row)
                raise SimError(f"unknown column {expr.to_text(node)}")
            return row.get(rc)
        if t == "num":
            return node["v"]
        if t == "str":
            return node["v"]
        if t == "null":
            return None
        if t in ("prompt", "macro"):
            return None
        if t == "ident":
            return node["v"]
        if t == "neg":
            v = self.row_value(node["x"], row); return None if v is None else -v
        if t == "not":
            v = self.row_value(node["x"], row); return None if v is None else not v
        if t == "bin":
            return self._bin(node, lambda n: self.row_value(n, row))
        if t == "if":
            c = self.row_value(node["c"], row)
            return self.row_value(node["a"], row) if c else (self.row_value(node["b"], row) if node.get("b") else None)
        if t == "case":
            return self._case(node, lambda n: self.row_value(n, row))
        if t == "in":
            x = self.row_value(node["x"], row); vals = [self.row_value(v, row) for v in node["vals"]]
            r = x in vals
            return (not r) if node.get("neg") else r
        if t == "isnull":
            v = self.row_value(node["x"], row); r = v is None
            return (not r) if node.get("neg") else r
        if t == "between":
            x = self.row_value(node["x"], row); lo = self.row_value(node["lo"], row); hi = self.row_value(node["hi"], row)
            r = x is not None and lo <= x <= hi
            return (not r) if node.get("neg") else r
        if t == "call":
            return self._scalar_fn(node, lambda n: self.row_value(n, row))
        raise SimError(f"cannot evaluate {t} per row")

    def _bin(self, node, ev):
        op = node["op"]
        if op == "and":
            return bool(ev(node["l"])) and bool(ev(node["r"]))
        if op == "or":
            return bool(ev(node["l"])) or bool(ev(node["r"]))
        a, b = ev(node["l"]), ev(node["r"])
        if op == "||":
            return ("" if a is None else str(a)) + ("" if b is None else str(b))
        if op in ("=", "<>", "<", ">", "<=", ">="):
            if a is None or b is None:
                return False
            if isinstance(a, str) != isinstance(b, str):
                a, b = str(a), str(b)
            return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        if a is None or b is None:
            return None
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return None if b == 0 else a / b
        raise SimError(op)

    def _case(self, node, ev):
        subj = ev(node["subject"]) if node.get("subject") else None
        for c, v in node["when"]:
            cv = ev(c)
            if (node.get("subject") is not None and cv == subj) or (node.get("subject") is None and cv):
                return ev(v)
        return ev(node["else"]) if node.get("else") else None

    def _scalar_fn(self, node, ev):
        fn, args = node["fn"], node["args"]
        if fn in AGG_FNS or fn in WINDOW_FNS:
            raise SimError(f"{fn} is not a row function")
        a = [ev(x) for x in args]
        if fn in ("upper", "lower", "trim"):
            return None if a[0] is None else getattr(str(a[0]), {"upper": "upper", "lower": "lower", "trim": "strip"}[fn])()
        if fn == "substring":
            s = "" if a[0] is None else str(a[0])
            start = int(a[1]) - 1 if len(a) > 1 else 0
            return s[start:start + int(a[2])] if len(a) > 2 else s[start:]
        if fn in ("character_length", "char_length", "length"):
            return None if a[0] is None else len(str(a[0]))
        if fn in ("_round", "round"):
            return None if a[0] is None else round(float(a[0]) + 0.0, int(a[1]) if len(a) > 1 else 0)
        if fn == "abs":
            return None if a[0] is None else abs(a[0])
        if fn == "sqrt":
            return None if a[0] is None or a[0] < 0 else math.sqrt(a[0])
        if fn == "power":
            return None if a[0] is None else a[0] ** a[1]
        if fn == "mod":
            return None if a[0] is None or not a[1] else a[0] % a[1]
        if fn in ("floor", "_floor"):
            return None if a[0] is None else math.floor(a[0])
        if fn in ("ceiling", "_ceiling"):
            return None if a[0] is None else math.ceil(a[0])
        if fn == "coalesce":
            return next((x for x in a if x is not None), None)
        if fn in ("_year", "year"):
            return None if a[0] is None else a[0].year
        if fn in ("_month", "month"):
            return None if a[0] is None else a[0].month
        if fn in ("_day", "day"):
            return None if a[0] is None else a[0].day
        if fn == "_days_between":
            return None if a[0] is None or a[1] is None else (a[0] - a[1]).days
        if fn == "_add_days":
            return None if a[0] is None else a[0] + dt.timedelta(days=int(a[1]))
        if fn == "cast":
            typ = expr.to_text(args[1]).lower() if len(args) > 1 else "decimal"
            if a[0] is None:
                return None
            return int(a[0]) if "int" in typ else str(a[0]) if ("char" in typ or "text" in typ) else float(a[0])
        raise SimError(f"no row function {fn}")

    # ---- aggregates
    def aggregate(self, fn: str, node_arg, rows: list[dict], distinct: bool = False):
        vals = [self.row_value(node_arg, r) for r in rows]
        vals = [v for v in vals if v is not None]
        if fn == "count":
            return len(set(vals)) if distinct else len(vals)
        if not vals:
            return None
        if fn in ("total", "sum"):
            return float(sum(vals))
        if fn in ("average", "avg"):
            return float(sum(vals)) / len(vals)
        if fn in ("minimum", "min"):
            return min(vals)
        if fn in ("maximum", "max"):
            return max(vals)
        raise SimError(fn)

    def agg_value(self, node, group: list[dict], groups: list[tuple], gi: int, group_keys: dict, name_stack=()):
        """A calculation after aggregation for group gi (groups = ordered list of (key, rows))."""
        t = node["t"]
        if t == "ref":
            rc = self.src.resolve(node["path"])
            if rc is not None:
                if self._role(rc) == "measure":                      # auto-summarise
                    return self.aggregate("total", node, group)
                return group_keys.get(rc)                             # an attribute: the group's value (if grouped)
            name = node["path"][0]
            if len(node["path"]) == 1 and name in self.asts and name not in name_stack:
                return self.agg_value(self.asts[name], group, groups, gi, group_keys, name_stack + (name,))
            raise SimError(f"unknown reference {expr.to_text(node)}")
        if t in ("num", "str", "null", "prompt", "macro", "ident"):
            return None if t in ("null", "prompt", "macro") else node["v"]
        if t == "neg":
            v = self.agg_value(node["x"], group, groups, gi, group_keys, name_stack); return None if v is None else -v
        if t == "not":
            v = self.agg_value(node["x"], group, groups, gi, group_keys, name_stack); return None if v is None else not v
        if t == "bin":
            return self._bin(node, lambda n: self.agg_value(n, group, groups, gi, group_keys, name_stack))
        if t == "if":
            c = self.agg_value(node["c"], group, groups, gi, group_keys, name_stack)
            return self.agg_value(node["a"], group, groups, gi, group_keys, name_stack) if c else (self.agg_value(node["b"], group, groups, gi, group_keys, name_stack) if node.get("b") else None)
        if t == "case":
            return self._case(node, lambda n: self.agg_value(n, group, groups, gi, group_keys, name_stack))
        if t == "in":
            x = self.agg_value(node["x"], group, groups, gi, group_keys, name_stack); vals = [self.agg_value(v, group, groups, gi, group_keys, name_stack) for v in node["vals"]]
            r = x in vals
            return (not r) if node.get("neg") else r
        if t == "isnull":
            v = self.agg_value(node["x"], group, groups, gi, group_keys, name_stack); r = v is None
            return (not r) if node.get("neg") else r
        if t == "between":
            x = self.agg_value(node["x"], group, groups, gi, group_keys, name_stack)
            lo = self.agg_value(node["lo"], group, groups, gi, group_keys, name_stack); hi = self.agg_value(node["hi"], group, groups, gi, group_keys, name_stack)
            r = x is not None and lo <= x <= hi
            return (not r) if node.get("neg") else r
        if t == "call":
            fn = node["fn"]
            if fn in AGG_FNS and fn != "percentage":
                arg = node["args"][0]
                if node.get("for") is not None:
                    part = self._partition(node["for"], groups, gi, group_keys)
                    rows = [r for _, rs in part for r in rs]
                    return self.aggregate(fn, arg, rows, node.get("distinct", False))
                return self.aggregate(fn, arg, group, node.get("distinct", False))
            if fn == "percentage":
                arg = node["args"][0]
                part = self._partition(node["for"], groups, gi, group_keys) if node.get("for") else groups
                total = self.aggregate("total", arg, [r for _, rs in part for r in rs])
                mine = self.aggregate("total", arg, group)
                return None if not total or mine is None else mine / total
            if fn in WINDOW_FNS:
                return self._window(node, groups, gi, group_keys)
            return self._scalar_fn(node, lambda n: self.agg_value(n, group, groups, gi, group_keys, name_stack))
        raise SimError(f"cannot evaluate {t}")

    def _partition(self, levels, groups, gi, group_keys):
        """The groups sharing this group's values on the `for` levels that the visual groups by."""
        cols = []
        for lv in levels:
            rc = self.src.resolve(lv["path"]) if lv["t"] == "ref" else None
            if rc is None and lv["t"] == "ref" and len(lv["path"]) == 1 and lv["path"][0] in self.asts:
                rc = ("item", lv["path"][0])
            elif rc is not None:
                rc = getattr(self, "cat_items", {}).get(rc)             # the category item that shows this column
            if rc is not None and rc in group_keys:
                cols.append(rc)
        if not cols:
            return groups
        mine = tuple(group_keys[c] for c in cols)
        return [(k, rs) for k, rs in groups if tuple(dict(k).get(c) for c in cols) == mine]

    def _window(self, node, groups, gi, group_keys):
        fn = node["fn"]
        arg = node["args"][0]
        part = self._partition(node["for"], groups, gi, group_keys) if node.get("for") else groups
        series = [self.aggregate("total", arg, rs) for _, rs in part]
        mine_i = next(i for i, (k, _) in enumerate(part) if k == groups[gi][0])
        if fn in ("rank",):
            v = series[mine_i]
            return None if v is None else 1 + sum(1 for x in series if x is not None and x > v)
        if fn in ("percentile", "percent-rank"):
            v = series[mine_i]
            n = len([x for x in series if x is not None])
            return None if v is None or n < 2 else 100.0 * sum(1 for x in series if x is not None and x < v) / (n - 1)
        if fn.startswith("moving-"):
            k = int(node["args"][1]["v"]) if len(node["args"]) > 1 and node["args"][1]["t"] == "num" else 3
            win = [x for x in series[max(0, mine_i - k + 1):mine_i + 1] if x is not None]
            return None if not win else (sum(win) / len(win) if fn == "moving-average" else sum(win))
        win = [x for x in series[:mine_i + 1] if x is not None]
        if not win:
            return None
        return {"running-total": sum(win), "running-average": sum(win) / len(win), "running-count": len(win), "running-minimum": min(win), "running-maximum": max(win)}[fn]


def _filter_rows(ev: Evaluator, rows: list[dict], filters: list[dict]) -> list[dict]:
    """Constant filters on attribute items; prompt filters have no value (no filter); the rest are not applied here."""
    keep = rows
    for f in filters:
        try:
            node = expr.parse(f["expression"])
        except expr.ParseError:
            continue
        if expr.prompts(node) or any(fn in AGG_FNS or fn in WINDOW_FNS for fn in expr.functions(node)):
            continue
        refs = expr.refs(node)
        if not all(ev.src.resolve(p) is not None or (len(p) == 1 and ev.is_attribute(p[0])) for p in refs):
            continue
        keep = [r for r in keep if ev.row_value(node, r)]
    return keep


def _key_value(v):
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def evaluate(dataset: dict, data_dir: Path, query: dict, categories: list[str], measures: list[str], order_by_measure: bool = False, limit: int = 0) -> list[dict]:
    """Rows of one visual: {category item: value, ..., measure item: number, ...}, in the visual's row order."""
    src = Source(dataset, data_dir)
    ev = Evaluator(src, query.get("items") or [])
    rows = _filter_rows(ev, src.rows, query.get("filters") or [])
    cat_nodes = [(c, ev.asts[c]) for c in categories if c in ev.asts]
    ev.cat_items = {}                                   # resolved column -> the category item key, for `for` levels
    for c, n in cat_nodes:
        if n["t"] == "ref":
            rc = src.resolve(n["path"])
            if rc:
                ev.cat_items[rc] = ("item", c)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = tuple((("item", c), _key_value(ev.row_value(n, r))) for c, n in cat_nodes)
        groups.setdefault(key, []).append(r)
    ordered = sorted(groups.items(), key=lambda kv: tuple((v is None, "" if v is None else (str(v) if isinstance(v, str) else v)) for _, v in kv[0]))
    out = []
    for gi, (key, grp) in enumerate(ordered):
        group_keys = dict(key)
        for (_, c), v in key:
            rc = src.resolve([c])
            node = ev.asts.get(c)
            if node and node["t"] == "ref":
                rc = src.resolve(node["path"]) or rc
            if rc:
                group_keys[rc] = v
        row = {c: v for (_, c), v in key}
        for m in measures:
            node = ev.asts.get(m)
            if node is None:
                row[m] = None
                continue
            it = ev.items[m]
            if it.get("aggregate") and node["t"] == "ref":
                node = {"t": "call", "fn": it["aggregate"], "args": [node], "for": None, "distinct": it.get("aggregate") == "count distinct", "reset": None}
            try:
                v = ev.agg_value(node, grp, ordered, gi, group_keys)
            except SimError:
                v = None
            row[m] = _num(v) if not isinstance(v, (str, dt.date)) else v
        out.append(row)
    if order_by_measure and measures:
        out.sort(key=lambda r: (r.get(measures[0]) is None, -(r.get(measures[0]) or 0)))
    return out[:limit] if limit else out
