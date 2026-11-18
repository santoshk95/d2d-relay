"""DAX for the semantic review: read a formula into a small syntax tree, expand it (variables and measure references
put in place, the usual shorthands written one way), and describe it.

    parse(text)              -> a tree of tuples (see NODE KINDS below); DaxError when the formula cannot be read
    Resolver                 what [Name] means in a model: a measure (its own tree) or a column
    expand(tree, resolver)   -> the formula with every variable and measure reference in place
    canon(expanded, loose)   -> one text per meaning: two formulas that compute the same thing get the same text
    fingerprint(...)         -> a short hash of canon
    signature(expanded)      -> what the formula does: aggregations, filters, filter removal, time intelligence,
                                its shape (ratio, difference ...), constants, divisions with "/", known pitfalls
    show(tree)               -> the tree as DAX text again (for findings)

Canonical rules (all of them hold in DAX, so they never make two different numbers look the same):
  - names ignore case and quotes ('Sales'[Amount] = Sales[amount]); comments and spacing do not count
  - SUMX(T, T[c]) = SUM(T[c]) (likewise AVERAGEX, MINX, MAXX, COUNTX, COUNTAX); COUNTROWS(VALUES(c)) and
    COUNTROWS(DISTINCT(c)) = DISTINCTCOUNT(c)
  - TOTALYTD(e, d, f, ye) = CALCULATE(e, DATESYTD(d, ye), f) (likewise QTD, MTD); a year end of "12/31" is the default
  - CALCULATE's filters in any order; FILTER(ALL(T[c]), <a test of T[c] only>) = <that test>; CALCULATE(e) = e
  - DIVIDE(a, b) and a / b read the same (the "/" is reported on its own); DIVIDE(a, b, 0) = DIVIDE(a, b)
  - a + b = b + a, (a + b) + c = a + (b + c), a - b = a + (-b); the same for *, && and ||; x = y = y = x
  - a measure reference is its formula; in a row context (inside SUMX, FILTER ...) it keeps its implicit CALCULATE
  - a variable is its value where it was defined: one used inside a later CALCULATE stays "frozen" (and is reported:
    CALCULATE cannot change a variable's value)
  - loose: column names without their table (two models that name their tables differently)

NODE KINDS
  ('num', float) ('str', text) ('bool', b) ('col', table|None, column) ('ref', name)   [Name] on its own
  ('table', name) ('name', identifier) ('kw', KEYWORD) ('call', FN, [args]) ('bin', op, left, right)
  ('un', op, x) ('not', x) ('in', x, set) ('var', [(name, expr)], body) ('ctor', [items]) ('tuple', [items]) ('empty',)
  after expand: ('mref', name, body) ('frozen', value) ('ctxtrans', calculate) ('cycle', name) ('missing', name)
"""
from __future__ import annotations

import hashlib
import re
import threading

MAX_CANON = 4000               # an inlined measure longer than this is replaced by a hash of itself in canon()
MAX_NODES = 40000              # signature(): nodes visited at most
_LOCAL = threading.local()     # describe(): canon()'s memo of measure bodies (Resolver.canon_memo), per thread


class DaxError(Exception):
    """The formula cannot be read."""


TOKEN = re.compile(r'''
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|--[^\n]*|/\*.*?(?:\*/|\Z))
  | (?P<str>"(?:[^"]|"")*")
  | (?P<quoted>'(?:[^']|'')*')
  | (?P<bracket>\[(?:[^\]]|\]\])*\])
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<date>[dD][tT]"[^"]*")
  | (?P<ident>[^\W\d][\w.]*)
  | (?P<op>==|<>|!=|<=|>=|&&|\|\||[-+*/^&=<>(),{};!:@.])
''', re.S | re.X)

# words that are keywords where a table name could stand (DATEADD(d, -1, YEAR), RANKX(..., DESC, DENSE) ...)
KEYWORDS = {"YEAR", "QUARTER", "MONTH", "WEEK", "DAY", "HOUR", "MINUTE", "SECOND", "ASC", "DESC", "SKIP", "DENSE",
            "ABS", "REL", "BLANKS", "FIRST", "LAST", "DEFAULT", "KEEP", "PARTITIONBY", "ORDERBY", "INTEGER", "DOUBLE",
            "STRING", "BOOLEAN", "CURRENCY", "DATETIME", "BOTH", "ONEWAY", "NONE", "ONEWAY_RIGHTFILTERSLEFT",
            "ONEWAY_LEFTFILTERSRIGHT", "NONVISUAL"}

AGG = {"SUM", "AVERAGE", "AVERAGEA", "MIN", "MINA", "MAX", "MAXA", "COUNT", "COUNTA", "COUNTBLANK", "COUNTROWS",
       "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "APPROXIMATEDISTINCTCOUNT", "MEDIAN", "PRODUCT", "STDEV.S", "STDEV.P",
       "VAR.S", "VAR.P", "GEOMEAN", "PERCENTILE.INC", "PERCENTILE.EXC"}
# iterators: the arguments evaluated row by row (a row context)
ITER = {"SUMX": (1,), "AVERAGEX": (1,), "MINX": (1,), "MAXX": (1,), "COUNTX": (1,), "COUNTAX": (1,), "PRODUCTX": (1,),
        "MEDIANX": (1,), "GEOMEANX": (1,), "STDEVX.S": (1,), "STDEVX.P": (1,), "VARX.S": (1,), "VARX.P": (1,),
        "PERCENTILEX.INC": (1,), "PERCENTILEX.EXC": (1,), "CONCATENATEX": (1, 3), "RANKX": (1,), "FILTER": (1,),
        "FIRSTNONBLANK": (1,), "LASTNONBLANK": (1,), "FIRSTNONBLANKVALUE": (1,), "LASTNONBLANKVALUE": (1,)}
ITER_AGG = {"SUMX": "SUM", "AVERAGEX": "AVERAGE", "MINX": "MIN", "MAXX": "MAX", "COUNTX": "COUNT", "COUNTAX": "COUNTA"}
TIME = {"DATESYTD", "DATESQTD", "DATESMTD", "SAMEPERIODLASTYEAR", "DATEADD", "PARALLELPERIOD", "PREVIOUSYEAR",
        "PREVIOUSQUARTER", "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
        "DATESINPERIOD", "DATESBETWEEN", "STARTOFYEAR", "ENDOFYEAR", "STARTOFQUARTER", "ENDOFQUARTER", "STARTOFMONTH",
        "ENDOFMONTH", "FIRSTDATE", "LASTDATE", "OPENINGBALANCEYEAR", "OPENINGBALANCEQUARTER", "OPENINGBALANCEMONTH",
        "CLOSINGBALANCEYEAR", "CLOSINGBALANCEQUARTER", "CLOSINGBALANCEMONTH", "TOTALYTD", "TOTALQTD", "TOTALMTD"}
YEAR_END_ARG = {"DATESYTD": 1, "PREVIOUSYEAR": 1, "NEXTYEAR": 1, "STARTOFYEAR": 1, "ENDOFYEAR": 1,
                "OPENINGBALANCEYEAR": 3, "CLOSINGBALANCEYEAR": 3}
REMOVERS = {"ALL", "REMOVEFILTERS", "ALLEXCEPT", "ALLSELECTED", "ALLNOBLANKROW", "ALLCROSSFILTERED"}
RELATION = {"USERELATIONSHIP", "CROSSFILTER", "TREATAS"}
TOTAL = {"TOTALYTD": "DATESYTD", "TOTALQTD": "DATESQTD", "TOTALMTD": "DATESMTD"}
# numeric arguments that are positions, counts or offsets, never business constants
COUNT_ARGS = {"DATEADD": (1,), "PARALLELPERIOD": (1,), "DATESINPERIOD": (2,), "ROUND": (1,), "ROUNDUP": (1,),
              "ROUNDDOWN": (1,), "FIXED": (1,), "LEFT": (1,), "RIGHT": (1,), "MID": (1, 2), "TOPN": (0,),
              "RANKX": (2, 3), "EDATE": (1,), "EOMONTH": (1,), "DATE": (0, 1, 2), "TIME": (0, 1, 2), "REPT": (1,),
              "INDEX": (0,), "OFFSET": (0,), "WINDOW": (0, 2), "MOVINGAVERAGE": (1,), "PATHITEM": (1,), "MROUND": (1,)}


# ---------------------------------------------------------------- read

def tokens(text: str) -> list[tuple[str, str, int]]:
    out, i, s = [], 0, str(text or "")
    while i < len(s):
        m = TOKEN.match(s, i)
        if not m:
            raise DaxError(f"cannot read the formula at character {i + 1} ({s[i:i + 12]!r})")
        kind = m.lastgroup
        if kind not in ("ws", "comment"):
            out.append((kind, m.group(0), i))
        i = m.end()
    return out


class _Parser:
    def __init__(self, text: str):
        self.toks = tokens(text)
        self.i = 0

    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else ("eof", "", -1)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def op(self, s: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t[0] == "op" and t[1] == s

    def kw(self, s: str, k: int = 0) -> bool:
        t = self.peek(k)
        return t[0] == "ident" and t[1].upper() == s

    def need(self, s: str) -> None:
        if not self.op(s):
            t = self.peek()
            raise DaxError(f"expected '{s}' but found {t[1]!r}" if t[0] != "eof" else f"expected '{s}' before the end")
        self.take()

    def parse(self):
        if not self.toks:
            raise DaxError("the formula is empty")
        n = self.expr()
        if self.peek()[0] != "eof":
            raise DaxError(f"unexpected {self.peek()[1]!r} at character {self.peek()[2] + 1}")
        return n

    def expr(self):
        n = self.and_()
        while self.op("||"):
            self.take()
            n = ("bin", "||", n, self.and_())
        return n

    def and_(self):
        n = self.not_()
        while self.op("&&"):
            self.take()
            n = ("bin", "&&", n, self.not_())
        return n

    def not_(self):
        if self.kw("NOT") and not self.op("(", 1):
            self.take()
            return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        n = self.concat()
        while True:
            t = self.peek()
            if t[0] == "op" and t[1] in ("=", "==", "<>", "!=", "<", ">", "<=", ">="):
                self.take()
                n = ("bin", {"!=": "<>"}.get(t[1], t[1]), n, self.concat())
            elif self.kw("IN"):
                self.take()
                n = ("in", n, self.concat())
            elif self.kw("NOT") and self.kw("IN", 1):
                self.take(), self.take()
                n = ("not", ("in", n, self.concat()))
            else:
                return n

    def concat(self):
        n = self.add()
        while self.op("&"):
            self.take()
            n = ("bin", "&", n, self.add())
        return n

    def add(self):
        n = self.mul()
        while self.op("+") or self.op("-"):
            o = self.take()[1]
            n = ("bin", o, n, self.mul())
        return n

    def mul(self):
        n = self.unary()
        while self.op("*") or self.op("/"):
            o = self.take()[1]
            n = ("bin", o, n, self.unary())
        return n

    def unary(self):
        if self.op("-") or self.op("+"):
            o = self.take()[1]
            return ("un", o, self.unary())
        return self.power()

    def power(self):
        n = self.primary()
        if self.op("^"):
            self.take()
            return ("bin", "^", n, self.unary())
        return n

    def primary(self):
        kind, s, pos = self.take()
        if kind == "num":
            return ("num", float(s))
        if kind == "str":
            return ("str", s[1:-1].replace('""', '"'))
        if kind == "date":                                         # dt"2024-01-01", a date (and time) literal
            return ("date", s[3:-1].strip())
        if kind == "bracket":
            return ("ref", s[1:-1].replace("]]", "]"))
        if kind == "quoted":
            name = s[1:-1].replace("''", "'")
            if self.peek()[0] == "bracket":
                return self.variation(("col", name, self.take()[1][1:-1].replace("]]", "]")))
            return ("table", name)
        if kind == "op":
            if s == "(":
                items = [self.expr()]
                while self.op(","):
                    self.take()
                    items.append(self.expr())
                self.need(")")
                return items[0] if len(items) == 1 else ("tuple", items)
            if s == "{":
                items = []
                if not self.op("}"):
                    items.append(self.expr())
                    while self.op(","):
                        self.take()
                        items.append(self.expr())
                self.need("}")
                return ("ctor", items)
            raise DaxError(f"unexpected {s!r} at character {pos + 1}")
        if kind == "ident":
            up = s.upper()
            if up == "VAR":
                return self.var_block()
            if self.op("("):
                self.take()
                args = []
                if self.op(")"):
                    self.take()
                else:
                    while True:
                        args.append(("empty",) if self.op(",") or self.op(")") else self.expr())
                        if self.op(","):
                            self.take()
                            continue
                        self.need(")")
                        break
                if up == "NOT" and len(args) == 1:
                    return ("not", args[0])
                return ("call", up, args)
            if self.peek()[0] == "bracket":
                return self.variation(("col", s, self.take()[1][1:-1].replace("]]", "]")))
            if up in ("TRUE", "FALSE"):
                return ("bool", up == "TRUE")
            return ("name", s)
        raise DaxError("the formula ends too early")

    def variation(self, col):
        """Sales[OrderDate].[Date]: a column's variation (Power BI's automatic date tables). The column it starts from is
        what the review compares, so the variation is read and passed over."""
        while self.op(".") and self.peek(1)[0] == "bracket":
            self.take(), self.take()
        return col

    def var_block(self):
        defs = []
        while True:
            t = self.take()
            if t[0] != "ident":
                raise DaxError("a VAR needs a name")
            name = t[1]
            self.need("=")
            defs.append((name, self.expr()))
            if self.kw("VAR"):
                self.take()
                continue
            if self.kw("RETURN"):
                self.take()
                break
            raise DaxError(f"VAR {name} has no RETURN")
        return ("var", defs, self.expr())


def parse(text: str):
    """The formula as a tree (DaxError when it cannot be read)."""
    try:
        return _Parser(text).parse()
    except RecursionError:
        raise DaxError("the formula is nested too deeply to read") from None


def walk(n):
    """Every node of a tree, depth first (expanded trees included). A measure referred to many times is walked once:
    expanded trees share each measure's body, and walking it at every reference would grow exponentially with the
    depth of the measures' references (Mi = [Mi-1] + [Mi-1])."""
    stack, seen = [n], set()
    while stack:
        x = stack.pop()
        if not isinstance(x, tuple) or not x:
            continue
        if x[0] == "mref":
            key = x[1].lower()
            if key in seen:
                yield x
                continue
            seen.add(key)
        yield x
        k = x[0]
        if k == "call":
            stack.extend(reversed(x[2]))
        elif k == "bin":
            stack.extend((x[3], x[2]))
        elif k in ("un",):
            stack.append(x[2])
        elif k in ("not", "frozen", "ctxtrans"):
            stack.append(x[1])
        elif k == "in":
            stack.extend((x[2], x[1]))
        elif k in ("ctor", "tuple"):
            stack.extend(reversed(x[1]))
        elif k == "var":
            stack.append(x[2])
            stack.extend(reversed([e for _, e in x[1]]))
        elif k == "mref":
            stack.append(x[2])


def references(tree) -> dict:
    """What a formula names directly (before expansion): [Name] references, Table[Column] columns, tables, functions."""
    refs, cols, tables, fns = [], [], [], []
    for x in walk(tree):
        k = x[0]
        if k == "ref":
            refs.append(x[1])
        elif k == "col":
            cols.append((x[1], x[2]))
        elif k == "table":
            tables.append(x[1])
        elif k == "call":
            fns.append(x[1])
    return {"refs": _uniq(refs), "columns": _uniq(cols), "tables": _uniq(tables), "functions": _uniq(fns)}


def _uniq(xs):
    seen, out = set(), []
    for x in xs:
        key = tuple(v.lower() if isinstance(v, str) else v for v in x) if isinstance(x, tuple) else str(x).lower()
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


# ---------------------------------------------------------------- what [Name] means

class Resolver:
    """A model's measures and columns, as expand() needs them. measures: name -> DAX text; columns: (table, column)
    pairs; tables: table names. Parsed trees are kept (each measure is read once); errors are kept by name."""

    def __init__(self, measures: dict[str, str] | None = None, columns=(), tables=()):
        self.measures = {str(k).lower(): (str(k), v) for k, v in (measures or {}).items()}
        self.cols: dict[str, dict[str, str]] = {}
        for t, c in columns:
            self.cols.setdefault(str(t).lower(), {})[str(c).lower()] = str(c)
        self.tables = {str(t).lower(): str(t) for t in tables} | {t: t for t in self.cols if t not in {str(x).lower() for x in tables}}
        self.trees: dict[str, tuple] = {}
        self.errors: dict[str, str] = {}
        self.expanded: dict[str, tuple] = {}          # each measure expanded once, in its own scope
        self.active: set[str] = set()                 # the measures being expanded right now (a cycle check)
        self.canon_memo: dict = {}                    # canon() of each measure's expanded body, by (name, loose)

    def tree(self, name: str):
        key = name.lower()
        if key in self.trees:
            return self.trees[key]
        if key in self.errors or key not in self.measures:
            return None
        try:
            self.trees[key] = parse(self.measures[key][1])
        except DaxError as e:
            self.errors[key] = str(e)
            return None
        except RecursionError:
            self.errors[key] = "the formula is nested too deeply to read"
            return None
        return self.trees[key]

    def measure_name(self, name: str) -> str | None:
        m = self.measures.get(name.lower())
        return m[0] if m else None

    def column(self, name: str, table: str | None = None) -> tuple[str, str] | None:
        """[name] as a column: of the row context's table first, else the one table that has such a column."""
        low = name.lower()
        if table and low in self.cols.get(table.lower(), {}):
            return (self.tables.get(table.lower(), table), self.cols[table.lower()][low])
        hits = [(t, cs[low]) for t, cs in self.cols.items() if low in cs]
        if len(hits) == 1:
            return (self.tables.get(hits[0][0], hits[0][0]), hits[0][1])
        return None

    def is_table(self, name: str) -> bool:
        return name.lower() in self.tables


# ---------------------------------------------------------------- expand

NAMED_COLUMNS = {"ADDCOLUMNS": 1, "SELECTCOLUMNS": 1, "SUMMARIZE": None, "SUMMARIZECOLUMNS": None, "GROUPBY": None,
                 "ROW": 0, "DATATABLE": 0, "ADDMISSINGITEMS": None, "NATURALINNERJOIN": None, "SUBSTITUTEWITHINDEX": 1}


def virtual_columns(tree) -> set[str]:
    """Columns a formula makes itself, which [Name] may then refer to: ADDCOLUMNS ( T, "@v", ... ) -> [@v], ROW, the
    named columns of SUMMARIZE / SUMMARIZECOLUMNS / GROUPBY / SELECTCOLUMNS / DATATABLE, and the fixed names of
    {table constructors} ([Value], [Value1] ...), GENERATESERIES ([Value]) and CALENDAR ([Date])."""
    out = {"value", "date"} | {f"value{i}" for i in range(1, 10)}
    for x in walk(tree):
        if x[0] == "call" and x[1] in NAMED_COLUMNS:
            start = NAMED_COLUMNS[x[1]]
            for i, a in enumerate(x[2]):
                if a[0] == "str" and (start is None or i >= start):
                    out.add(a[1].lower())
    return out


class _Ctx:
    __slots__ = ("vars", "frozen", "row", "row_table", "calc", "notes", "own", "virtual")

    def __init__(self, notes: dict, own: bool = True, virtual: set | None = None):
        self.vars: dict = {}
        self.frozen: frozenset = frozenset()
        self.row = False
        self.row_table: str | None = None
        self.calc = False
        self.notes = notes
        self.own = own                                # expanding the formula itself, not a measure it refers to
        self.virtual = virtual or set()               # columns the formula makes itself (virtual_columns)

    def but(self, **kw) -> "_Ctx":
        c = _Ctx(self.notes, self.own, self.virtual)
        for k in self.__slots__:
            setattr(c, k, kw[k] if k in kw else getattr(self, k))
        return c

    def note(self, what: str, value: str) -> None:
        if self.own:
            self.notes.setdefault(what, []).append(value)


def expand(tree, resolver: Resolver | None = None, *, notes: dict | None = None):
    """The tree with variables and measure references in place and the shorthands rewritten (see the module's
    canonical rules). notes collects what expansion noticed in this formula itself (not in the measures it refers
    to): frozen variables (a variable used inside a later CALCULATE), cycles, references to nothing ('missing',
    'broken': a measure that cannot be read)."""
    notes = notes if notes is not None else {}
    return _exp(tree, _Ctx(notes, virtual=virtual_columns(tree)), resolver or Resolver())


def expand_measure(name: str, resolver: Resolver, notes: dict | None = None):
    """A measure of the model, expanded in its own scope; None when it cannot be read. Each measure is expanded once
    (deep chains stay linear); notes get what the measure's own formula shows."""
    key = name.lower()
    if key in resolver.expanded and notes is None:
        return resolver.expanded[key]
    tree = resolver.tree(name)
    if tree is None:
        return None
    resolver.active.add(key)
    try:
        out = _exp(tree, _Ctx(notes if notes is not None else {}, virtual=virtual_columns(tree)), resolver)
    finally:
        resolver.active.discard(key)
    resolver.expanded[key] = out
    return out


def _measure_body(mname: str, c: _Ctx, res: Resolver):
    """A referenced measure's expanded formula (its own scope: no variables, no row context)."""
    key = mname.lower()
    if key in res.expanded:
        return res.expanded[key]
    if key in res.active:
        c.note("cycle", mname)
        return ("cycle", mname)
    tree = res.tree(mname)
    if tree is None:
        c.note("broken", mname)
        return ("missing", mname)
    res.active.add(key)
    try:
        body = _exp(tree, _Ctx(c.notes, own=False, virtual=virtual_columns(tree)), res)
    finally:
        res.active.discard(key)
    res.expanded[key] = body
    return body


def _row_args(fn: str, n: int) -> set:
    if fn in ("ADDCOLUMNS", "SELECTCOLUMNS"):
        return {i for i in range(2, n) if i % 2 == 0}
    if fn == "TOPN":
        return {i for i in range(2, n) if i % 2 == 0}
    if fn in ("GENERATE", "GENERATEALL"):
        return {1}
    return set(ITER.get(fn, ()))


def _table_name(n, res: Resolver) -> str | None:
    """The table an iterator walks, when it is plain: T, 'T', FILTER(T, ...), ALL(T), VALUES(T), RELATEDTABLE(T) ..."""
    if n[0] == "table":
        return n[1]
    if n[0] == "name" and res.is_table(n[1]):
        return n[1]
    if n[0] == "call" and n[2] and n[1] in ("FILTER", "ALL", "ALLSELECTED", "ALLNOBLANKROW", "VALUES", "DISTINCT",
                                            "RELATEDTABLE", "CALCULATETABLE", "KEEPFILTERS", "TOPN"):
        return _table_name(n[2][1] if n[1] == "TOPN" and len(n[2]) > 1 else n[2][0], res)
    return None


def _exp(n, c: _Ctx, res: Resolver):
    k = n[0]
    if k == "var":
        vars_, frozen = dict(c.vars), set(c.frozen)
        for name, e in n[1]:
            low = name.lower()
            vars_[low] = _exp(e, c.but(vars=vars_, frozen=frozenset(frozen)), res)
            frozen.discard(low)                      # defined here: no longer the outer variable of that name
        return _exp(n[2], c.but(vars=vars_, frozen=frozenset(frozen)), res)
    if k == "name":
        low = n[1].lower()
        if low in c.vars:
            v = c.vars[low]
            if low in c.frozen:
                if any(y[0] == "call" and (y[1] in AGG or y[1] in ITER) or y[0] in ("mref", "ctxtrans") for y in walk(v)):
                    c.note("frozen", n[1])            # CALCULATE cannot change it: the filters do nothing to it
                return ("frozen", v)
            return v
        up = n[1].upper()
        if up in KEYWORDS and not res.is_table(n[1]):
            return ("kw", up)
        return ("table", res.tables.get(low, n[1])) if res.is_table(n[1]) or not res.tables else ("name", n[1])
    if k == "table":
        if res.cols and n[1].lower() not in res.tables:            # the model is known and has no such table
            c.note("missing", "'" + n[1] + "'")
            return ("missing", "'" + n[1] + "'")
        return ("table", res.tables.get(n[1].lower(), n[1]))
    if k == "col":
        t = n[1]
        if t is not None:
            hit = res.column(n[2], t)
            if hit:
                return ("col", hit[0], hit[1])
            if res.measure_name(n[2]) is not None:                 # 'Sales'[Revenue]: a measure named with its table
                return _exp(("ref", n[2]), c, res)
            if res.cols and t.lower() not in c.vars:               # the model is known and has no such column
                c.note("missing", f"'{t}'[{n[2]}]")
                return ("missing", f"'{t}'[{n[2]}]")
            return ("col", res.tables.get(t.lower(), t), n[2])
        return n
    if k == "ref":
        mname = res.measure_name(n[1])
        if mname is not None:
            m = ("mref", mname, _measure_body(mname, c, res))
            return ("ctxtrans", ("call", "CALCULATE", [m])) if c.row else m
        hit = res.column(n[1], c.row_table) if res.cols else None
        if hit:
            return ("col", hit[0], hit[1])
        if n[1].lower() in c.virtual:
            return ("vcol", n[1])
        if res.measures or res.cols:
            c.note("missing", f"[{n[1]}]")
            return ("missing", n[1])
        return n
    if k == "call":
        return _exp_call(n, c, res)
    if k == "bin":
        return ("bin", n[1], _exp(n[2], c, res), _exp(n[3], c, res))
    if k == "un":
        return ("un", n[1], _exp(n[2], c, res))
    if k == "not":
        return ("not", _exp(n[1], c, res))
    if k == "in":
        return ("in", _exp(n[1], c, res), _exp(n[2], c, res))
    if k in ("ctor", "tuple"):
        return (k, [_exp(x, c, res) for x in n[1]])
    return n


def _exp_call(n, c: _Ctx, res: Resolver):
    fn, args = n[1], n[2]
    if fn in TOTAL and args:                        # TOTALYTD(e, d, [filter], [year end]) -> CALCULATE(e, DATESYTD(d, ye), filter)
        dates = [args[1]] if len(args) > 1 else []
        ye = [a for a in args[2:] if a[0] == "str"]
        flt = [a for a in args[2:] if a[0] not in ("str", "empty")]
        return _exp(("call", "CALCULATE", [args[0], ("call", TOTAL[fn], dates + ye[:1])] + flt), c, res)
    if fn in ("CALCULATE", "CALCULATETABLE"):
        if not args:
            return ("call", fn, [])
        inner = c.but(calc=True, row=False, frozen=frozenset(c.vars))
        out = ("call", fn, [_exp(args[0], inner, res)] + [_exp(a, c.but(calc=False, row=False), res) for a in args[1:]])
        return ("ctxtrans", out) if c.row and fn == "CALCULATE" else out
    rows = _row_args(fn, len(args))
    row_table = _table_name(args[0], res) if rows and args else None
    out = []
    for i, a in enumerate(args):
        if i in rows:
            out.append(_exp(a, c.but(row=True, row_table=row_table or c.row_table), res))
        else:
            out.append(_exp(a, c, res))
    # SUMX(T, T[c]) -> SUM(T[c]) when the row expression is just a column of the walked table
    if fn in ITER_AGG and len(out) == 2 and out[1][0] == "col" and row_table and out[1][1] \
            and out[1][1].lower() == row_table.lower() and _plain_table(args[0], res):
        return ("call", ITER_AGG[fn], [out[1]])
    if fn == "COUNTROWS" and len(out) == 1 and out[0][0] == "call" and out[0][1] in ("VALUES", "DISTINCT") \
            and len(out[0][2]) == 1 and out[0][2][0][0] == "col":
        return ("call", "DISTINCTCOUNT", [out[0][2][0]])
    return ("call", fn, out)


def _plain_table(n, res: Resolver) -> bool:
    return n[0] == "table" or (n[0] == "name" and res.is_table(n[1]))


# ---------------------------------------------------------------- canonical form

def _num(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(float(v))


def year_end(text: str | None) -> str:
    """A year-end date as MM-DD ("6/30", "30/6", "06-30" -> 06-30); December 31 when there is none."""
    if not text:
        return "12-31"
    nums = [int(x) for x in re.findall(r"\d+", str(text))][:2]
    months = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
    word = re.search(r"[a-z]{3}", str(text).lower())
    if word and word.group(0) in months and nums:
        return f"{months[word.group(0)]:02d}-{nums[0]:02d}"
    if len(nums) == 2:
        a, b = nums
        m, d = (b, a) if a > 12 else (a, b)
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{m:02d}-{d:02d}"
    return str(text).strip().lower()


def loose_table(name: str | None) -> str:
    """A table name as two models may spell it differently: no Fact / Dim / tbl prefix or suffix, no spaces or
    underscores, no plural s ('Fact Sales', 'FactSales', 'sales', 'Sale' -> sale). Never just dropped: 'Budget'[Amount]
    and 'Sales'[Amount] stay apart."""
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name or ""))          # FactSales -> Fact Sales
    t = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    t = re.sub(r"^(fact|dim|tbl|vw|fct|f|d|t|v)\s+", "", t)
    t = re.sub(r"\s+(table|tbl|fact|dim|data)$", "", t)
    t = t.replace(" ", "")
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


def canon(n, loose: bool = False) -> str:
    """One text per meaning (see the module's canonical rules)."""
    k = n[0]
    if k == "num":
        return _num(n[1])
    if k == "str":
        return '"' + n[1].lower() + '"'
    if k == "bool":
        return "true" if n[1] else "false"
    if k == "col":
        col = n[2].lower()
        if not n[1]:
            return "c:" + col
        return "c:" + (f"{loose_table(n[1])}.{col}" if loose else f"{n[1].lower()}.{col}")
    if k == "ref":
        return "r:" + n[1].lower()
    if k == "vcol":
        return "v:" + n[1].lower()
    if k == "missing":
        return "missing:" + n[1].lower()
    if k == "table":
        return "t:" + (loose_table(n[1]) if loose else n[1].lower())
    if k == "name":
        return "n:" + n[1].lower()
    if k == "kw":
        return n[1].lower()
    if k == "empty":
        return "_"
    if k == "tuple":
        return "(tuple " + " ".join(canon(x, loose) for x in n[1]) + ")"
    if k == "ctor":
        return "{" + " ".join(sorted(canon(x, loose) for x in n[1])) + "}"
    if k == "un":
        return canon(n[2], loose) if n[1] == "+" else "(neg " + canon(n[2], loose) + ")"
    if k == "not":
        return "(not " + canon(n[1], loose) + ")"
    if k == "in":
        return "(in " + canon(n[1], loose) + " " + canon(n[2], loose) + ")"
    if k == "bin":
        return _canon_bin(n, loose)
    if k == "call":
        return _canon_call(n, loose)
    if k == "mref":                                 # a measure's expanded body is the same wherever it is used: its text once
        memo = getattr(_LOCAL, "memo", None)
        key = (n[1].lower(), loose)
        if memo is not None and key in memo:
            return memo[key]
        body = canon(n[2], loose)
        out = body if len(body) <= MAX_CANON else "(m " + hashlib.sha1(body.encode()).hexdigest()[:16] + ")"
        if memo is not None:
            memo[key] = out
        return out
    if k == "date":
        return "d:" + n[1]
    if k == "frozen":
        return "(frozen " + canon(n[1], loose) + ")"
    if k == "ctxtrans":
        inner = n[1]
        e = canon(inner[2][0], loose) if inner[2] else "_"
        fl = sorted(_canon_filter(a, loose) for a in inner[2][1:] if a[0] != "empty")
        return "(ctx " + e + (" [" + " ".join(fl) + "]" if fl else "") + ")"
    if k == "cycle":
        return "(cycle " + n[1].lower() + ")"
    if k == "var":                                  # only when canon() is given a tree that was not expanded
        return canon(expand(n), loose)
    return "?"


def _terms(n, op: str, sign: bool = False):
    """The operands of a chain of one associative operator; for "+" a "-" becomes "+ (neg ...)"."""
    if n[0] == "bin" and (n[1] == op or (op == "+" and n[1] == "-")):
        left = list(_terms(n[2], op, sign))
        right = list(_terms(n[3], op, sign != (n[1] == "-")))
        return left + right
    return [(n, sign)]


def _canon_bin(n, loose: bool) -> str:
    op = n[1]
    if op in ("+", "-"):
        parts = sorted(("(neg " + canon(x, loose) + ")") if neg else canon(x, loose) for x, neg in _terms(n, "+"))
        return "(+ " + " ".join(parts) + ")"
    if op in ("*", "&&", "||"):
        parts = sorted(canon(x, loose) for x, _ in _terms(n, op))
        return f"({op} " + " ".join(parts) + ")"
    a, b = canon(n[2], loose), canon(n[3], loose)
    if op == "/":
        return f"(div {a} {b})"
    if op in ("=", "==", "<>"):
        a, b = sorted((a, b))
    if op in (">", ">=") :                        # a > b is b < a
        return f"({'<' if op == '>' else '<='} {b} {a})"
    return f"({op} {a} {b})"


def _canon_filter(a, loose: bool) -> str:
    if a[0] == "call" and a[1] == "KEEPFILTERS" and len(a[2]) == 1:
        return "(keepfilters " + _canon_filter(a[2][0], loose) + ")"
    # FILTER(ALL(T[c]), <a test of T[c] only>) is what the shorthand T[c] = x means
    if a[0] == "call" and a[1] == "FILTER" and len(a[2]) == 2:
        src, pred = a[2]
        if src[0] == "call" and src[1] == "ALL" and len(src[2]) == 1 and src[2][0][0] == "col":
            col = src[2][0]
            used = [x for x in walk(pred) if x[0] in ("col", "mref", "ctxtrans", "call") and not (x[0] == "col" and _same_col(x, col))]
            if not [x for x in used if x[0] != "call" or x[1] in AGG or x[1] in ITER]:
                return canon(pred, loose)
    return canon(a, loose)


def _same_col(a, b) -> bool:
    return (a[1] or "").lower() == (b[1] or "").lower() and a[2].lower() == b[2].lower()


def _canon_call(n, loose: bool) -> str:
    fn, args = n[1], n[2]
    if fn in ("CALCULATE", "CALCULATETABLE"):
        if not args:
            return f"({fn.lower()})"
        e = canon(args[0], loose)
        fl = sorted(_canon_filter(a, loose) for a in args[1:] if a[0] != "empty")
        if not fl and fn == "CALCULATE":
            return e
        return f"({fn.lower()} {e} [" + " ".join(fl) + "])"
    if fn == "DIVIDE":
        a = canon(args[0], loose) if args else "_"
        b = canon(args[1], loose) if len(args) > 1 else "_"
        alt = canon(args[2], loose) if len(args) > 2 and args[2][0] != "empty" else None
        return f"(div {a} {b})" if alt in (None, "0", "blank") else f"(div {a} {b} {alt})"
    if fn == "BLANK" and not args:
        return "blank"
    if fn in ("TRUE", "FALSE") and not args:
        return fn.lower()
    if fn in YEAR_END_ARG:
        i = YEAR_END_ARG[fn]
        parts = [canon(a, loose) for a in args[:i]]
        ye = args[i] if len(args) > i and args[i][0] == "str" else None
        rest = [canon(a, loose) for a in args[i + 1:]] if len(args) > i + 1 else []
        return f"({fn.lower()} " + " ".join(parts + [f'ye:{year_end(ye[1] if ye else None)}'] + rest) + ")"
    return f"({fn.lower()}" + "".join(" " + canon(a, loose) for a in args) + ")"


def fingerprint(n, loose: bool = False) -> str:
    return hashlib.sha1(canon(n, loose).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- show

def _q(table: str) -> str:
    return "'" + str(table).replace("'", "''") + "'"


def show(n, depth: int = 0) -> str:
    """The tree as DAX again (expanded trees show measure references as [Name])."""
    if depth > 60:
        return "..."
    k, d = n[0], depth + 1
    if k == "num":
        return _num(n[1])
    if k == "str":
        return '"' + n[1].replace('"', '""') + '"'
    if k == "bool":
        return "TRUE ()" if n[1] else "FALSE ()"
    if k == "col":
        return (_q(n[1]) if n[1] else "") + "[" + n[2].replace("]", "]]") + "]"
    if k == "date":
        return 'dt"' + n[1] + '"'
    if k in ("ref", "missing", "vcol"):
        return "[" + n[1].replace("]", "]]") + "]"
    if k == "table":
        return _q(n[1])
    if k in ("name", "kw"):
        return n[1]
    if k == "empty":
        return ""
    if k == "call":
        return n[1] + " ( " + ", ".join(show(a, d) for a in n[2]) + " )" if n[2] else n[1] + " ()"
    if k == "bin":
        wrap = lambda x: f"( {show(x, d)} )" if x[0] == "bin" and x[1] != n[1] else show(x, d)   # noqa: E731
        return f"{wrap(n[2])} {n[1]} {wrap(n[3])}"
    if k == "un":
        return n[1] + show(n[2], d)
    if k == "not":
        return "NOT " + show(n[1], d)
    if k == "in":
        return show(n[1], d) + " IN " + show(n[2], d)
    if k == "ctor":
        return "{ " + ", ".join(show(x, d) for x in n[1]) + " }"
    if k == "tuple":
        return "( " + ", ".join(show(x, d) for x in n[1]) + " )"
    if k == "var":
        return " ".join(f"VAR {name} = {show(e, d)}" for name, e in n[1]) + " RETURN " + show(n[2], d)
    if k == "mref":
        return "[" + n[1].replace("]", "]]") + "]"
    if k in ("frozen", "ctxtrans"):
        return show(n[1], d)
    if k == "cycle":
        return "[" + n[1] + "]"
    return "?"


# ---------------------------------------------------------------- signature

def _strip(n):
    """The node under the wrappers that do not change what a formula is: an inlined measure, CALCULATE with filters
    (those are reported separately), a context transition."""
    while True:
        if n[0] == "mref":
            n = n[2]
        elif n[0] == "ctxtrans":
            n = n[1]
        elif n[0] == "call" and n[1] == "CALCULATE" and n[2]:
            n = n[2][0]
        elif n[0] == "frozen":
            n = n[1]
        else:
            return n


def shape(n) -> str:
    """ratio | difference | sum | product | aggregate:<FN> | iterate:<FN> | conditional | constant | time | other"""
    x = _strip(n)
    k = x[0]
    if k == "call":
        if x[1] == "DIVIDE":
            return "ratio"
        if x[1] in AGG:
            return "aggregate:" + x[1]
        if x[1] in ITER:
            return "iterate:" + x[1]
        if x[1] in ("IF", "SWITCH", "IF.EAGER", "COALESCE"):
            return "conditional"
        if x[1] in TIME:
            return "time"
        return "function:" + x[1]
    if k == "bin":
        return {"/": "ratio", "-": "difference", "+": "sum", "*": "product"}.get(x[1], "other")
    if k in ("num", "str", "bool"):
        return "constant"
    if k == "un" and x[1] == "-":
        return "negative"
    return "other"


def _target(a, loose: bool) -> str:
    if a[0] == "col":
        if not a[1]:
            return a[2]
        return f"{loose_table(a[1])}[{a[2]}]" if loose else f"{a[1]}[{a[2]}]"
    if a[0] in ("table", "name"):
        return loose_table(a[1]) if loose else a[1]
    return show(a)


def signature(n) -> dict:
    """What an expanded formula does. aggs, filters, removers and time cover the whole logic (the measures it refers
    to included: that is what the number means); constants, divisions, iterator_aggregates and notes only the
    formula's own text (a problem in a measure it refers to is that measure's finding). Plain values, JSON-ready."""
    aggs, filters, removers, time, consts, notes = [], [], [], [], [], []
    iter_agg = []
    count = {"divisions": 0, "seen": 0}
    seen_measures: set[str] = set()

    def visit(x, row: bool, in_filter: bool, parent, own: bool):
        count["seen"] += 1
        if count["seen"] > MAX_NODES:
            return
        k = x[0]
        if k == "call":
            fn, args = x[1], x[2]
            if fn in AGG and args:
                t = args[0]
                aggs.append({"fn": fn, "of": _target(t, False), "loose": _target(t, True).lower(),
                             "kind": "column" if t[0] == "col" else "table"})
                if row and own and fn != "COUNTROWS":
                    iter_agg.append(show(x))
            if fn in ITER and args:
                body = args[1] if len(args) > 1 else ("empty",)
                aggs.append({"fn": fn, "of": show(args[0])[:200], "loose": canon(args[0], True)[:200], "kind": "iterator",
                             "row": show(body)[:300]})
            if fn in REMOVERS:
                removers.append({"fn": fn, "of": [show(a) for a in args][:6], "own": own, "in_filter": in_filter,
                                 "whole_table": (not args) or all(a[0] in ("table", "name") for a in args)})
            if fn in TIME:
                item = {"fn": fn}
                if fn in YEAR_END_ARG:
                    i = YEAR_END_ARG[fn]
                    ye = args[i] if len(args) > i and args[i][0] == "str" else None
                    item["year_end"] = year_end(ye[1] if ye else None)
                if fn in ("DATEADD", "PARALLELPERIOD") and len(args) >= 3:
                    item["shift"] = f"{show(args[1])} {show(args[2]).lower()}"
                if fn == "DATESINPERIOD" and len(args) >= 4:
                    item["shift"] = f"{show(args[2])} {show(args[3]).lower()}"
                time.append(item)
            if fn in ("CALCULATE", "CALCULATETABLE"):
                for a in args[1:]:
                    if a[0] != "empty":
                        filters.append({**_filter_item(a), "own": own})
                if args:
                    visit(args[0], False, False, fn, own)
                for a in args[1:]:
                    visit(a, False, True, fn, own)
                return
            rows = _row_args(fn, len(args))
            skip = COUNT_ARGS.get(fn, ())
            for i, a in enumerate(args):
                if a[0] == "num" and i in skip:
                    continue
                visit(a, row or i in rows, in_filter, fn, own)
            return
        if k == "num":
            if own and _constant_worth_noting(x[1]) and parent != "FORMAT":
                consts.append(_num(x[1]))
            return
        if k == "bin":
            right = x[3]
            literal = right[0] == "num" or (right[0] == "un" and right[2][0] == "num")
            if x[1] == "/" and own and not literal:
                count["divisions"] += 1
            visit(x[2], row, in_filter, parent, own)
            if not (x[1] in ("*", "/") and right[0] == "num" and right[1] in (100, 1000, 1e6, 1e9)):
                visit(right, row, in_filter, parent, own)
            return
        if k == "mref":                             # each measure it refers to, once (their bodies are shared)
            if x[1].lower() in seen_measures:
                return
            seen_measures.add(x[1].lower())
            visit(x[2], False, False, parent, False)
            return
        if k == "ctxtrans":
            visit(x[1], False, in_filter, parent, own)
            return
        if k == "frozen":
            visit(x[1], row, in_filter, parent, own)
            return
        if k == "un":
            visit(x[2], row, in_filter, parent, own)
            return
        if k == "not":
            visit(x[1], row, in_filter, parent, own)
            return
        if k == "in":
            visit(x[1], row, in_filter, parent, own)
            visit(x[2], row, in_filter, parent, own)
            return
        if k in ("ctor", "tuple"):
            for y in x[1]:
                visit(y, row, in_filter, parent, own)
            return
        if k == "cycle" and own:
            notes.append("cycle")

    visit(n, False, False, None, True)
    top = _strip(n)
    out = {"shape": shape(n), "aggs": _uniq_dicts(aggs)[:40], "filters": _uniq_dicts(filters)[:40],
           "removers": _uniq_dicts(removers)[:20], "time": _uniq_dicts(time)[:20],
           "constants": sorted(set(consts), key=float)[:12], "divisions": count["divisions"],
           "iterator_aggregates": iter_agg[:5], "notes": sorted(set(notes)),
           "measures": sorted({x[1] for x in walk(n) if x[0] == "mref"})[:40]}
    if out["shape"] == "ratio":
        parts = top[2] if top[0] == "call" else [top[2], top[3]]
        if len(parts) >= 2:
            out["ratio"] = {"numerator": _side(parts[0]), "denominator": _side(parts[1])}
    return out


def _side(n) -> dict:
    aggs = []
    for x in walk(n):
        if x[0] == "call" and x[1] in AGG and x[2]:
            aggs.append(f"{x[1]}({_target(x[2][0], False)})")
        elif x[0] == "call" and x[1] in ITER and x[2]:
            aggs.append(f"{x[1]}({show(x[2][0])})")
    return {"dax": show(n)[:300], "aggs": sorted(set(aggs))[:6], "measures": sorted({x[1] for x in walk(n) if x[0] == "mref"})[:6]}


def _uniq_dicts(xs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for x in xs:
        key = repr(sorted(x.items()))
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _constant_worth_noting(v: float) -> bool:
    """A number in a formula that looks like a business constant (a rate, a target, an exchange rate), not a 0, 1,
    a scale (10, 100, 1000 ...) or a small whole count."""
    a = abs(v)
    if a in (0, 1, 2, 10, 100, 1000, 1e6, 1e9, 0.5) or v == -1:
        return False
    if a == int(a):
        return a >= 10000 and str(int(a)).rstrip("0") not in ("1",)
    return True


def _filter_item(a) -> dict:
    """One CALCULATE filter: what kind of filter it is, its DAX, the columns it touches."""
    inner = a[2][0] if a[0] == "call" and a[1] == "KEEPFILTERS" and a[2] else a
    kind = "predicate"
    if inner[0] == "call":
        fn = inner[1]
        kind = ("remove" if fn in REMOVERS else "relationship" if fn in RELATION else "time" if fn in TIME
                else "table" if fn in ("FILTER", "VALUES", "DISTINCT", "CALCULATETABLE", "TOPN", "SUMMARIZE",
                                         "DATATABLE", "INTERSECT", "EXCEPT", "UNION") else "other")
    cols = sorted({f"{x[1]}[{x[2]}]" if x[1] else f"[{x[2]}]" for x in walk(inner) if x[0] == "col"})
    return {"kind": kind, "dax": show(a)[:300], "columns": cols[:8], "keep": inner is not a,
            "key": _canon_filter(a, True)[:400]}


# ---------------------------------------------------------------- one call for a measure

def describe(name: str, resolver: Resolver) -> dict:
    """Everything the rules need about one measure of a model: its fingerprints (strict and loose), signature, what
    it names directly, and what expanding its own formula noticed (frozen variables, cycles, references to nothing,
    measures that cannot be read)."""
    tree = resolver.tree(name)
    if tree is None:
        return {"error": resolver.errors.get(name.lower()) or "not found"}
    notes: dict = {}
    prev = getattr(_LOCAL, "memo", None)
    _LOCAL.memo = resolver.canon_memo
    try:
        resolver.expanded.pop(name.lower(), None)
        ex = expand_measure(name, resolver, notes=notes)
        sig = signature(ex)
        strict, loose = canon(ex), canon(ex, loose=True)
    except RecursionError:
        return {"error": "the formula is nested too deeply to read", "refs": references(tree)}
    finally:
        _LOCAL.memo = prev
    return {"fp": hashlib.sha1(strict.encode()).hexdigest()[:12], "fp_loose": hashlib.sha1(loose.encode()).hexdigest()[:12],
            "canon": strict[:2000], "sig": sig, "refs": references(tree),
            "notes": {k: sorted(set(v))[:10] for k, v in notes.items()}, "tree": tree, "expanded": ex}
