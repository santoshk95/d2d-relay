"""Data pipelines & ETL — expressions in the ETL tools' own languages, translated to SQL by rules (rules first: an
expression the rules cannot translate is left for Relay's agent, with the reason).

Languages: `adf` (Azure Data Factory data flow expressions), `ssis` (SSIS expression language), `infa` (Informatica
PowerCenter / IICS transformation language) and `sql` (already SQL). One Pratt parser reads all of them into a small
tree; `to_sql(tree, resolve)` writes DuckDB SQL (what dbt-duckdb runs; sqlglot transpiles it to the target warehouse
for the dbt project), calling `resolve(name)` for every column so the caller can qualify it or inline a derived one.

    tree = parse("ROUND((QTY * UNIT_PRICE), 2)", "infa")
    to_sql(tree, lambda c: f"l.{c}")     ->  ROUND((l.QTY * l.UNIT_PRICE), 2)
    columns(tree)                        ->  {"QTY", "UNIT_PRICE"}
"""
from __future__ import annotations

import re


class Untranslatable(ValueError):
    """The rules do not know this construct (the agent drafts it)."""


TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+\.\d+|\d+)
  | (?P<str1>'(?:[^']|'')*')
  | (?P<str2>"(?:[^"\\]|\\.)*")
  | (?P<ssiscast>\(\s*DT_[A-Z0-9]+(?:\s*,\s*\d+)*\s*\))
  | (?P<ssisparam>@\[\$?[\w]+::[\w]+\])
  | (?P<bracket>\[[^\]]+\])
  | (?P<param>\$\$\w+|\$\w+|:\w+)
  | (?P<name>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:@[A-Za-z_]\w*)?)
  | (?P<op>==|!=|<>|<=|>=|&&|\|\||[-+*/%<>=!?:,()])
""", re.X)

PREC = {"?": 1, "||": 2, "or": 2, "&&": 3, "and": 3, "==": 4, "!=": 4, "<>": 4, "=": 4, "<": 5, ">": 5, "<=": 5, ">=": 5, "+": 6, "-": 6, "*": 7, "/": 7, "%": 7}


def tokens(text: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(text):
        m = TOKEN.match(text, i)
        if not m:
            raise Untranslatable(f"cannot read “{text[i:i + 20]}”")
        i = m.end()
        k = m.lastgroup
        if k == "ws":
            continue
        v = m.group(k)
        if k == "name" and v.lower() in ("and", "or", "not", "true", "false", "null"):
            k = "kw"
            v = v.lower()
        out.append((k, v))
    out.append(("end", ""))
    return out


class _P:
    def __init__(self, toks, lang):
        self.t, self.i, self.lang = toks, 0, lang

    def peek(self):
        return self.t[self.i]

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, v):
        k, x = self.take()
        if x != v:
            raise Untranslatable(f"expected “{v}”, found “{x or 'the end'}”")

    def expr(self, rbp: int = 0):
        left = self.prefix()
        while True:
            k, v = self.peek()
            op = v if k in ("op", "kw") else None
            p = PREC.get(op or "", 0) if op not in (",", ")", ":") else 0
            if op == "||" and self.lang in ("infa", "sql"):
                p = 6                                         # string concatenation there, not OR
            if p <= rbp:
                return left
            self.take()
            if op == "?":
                a = self.expr(0)
                self.expect(":")
                b = self.expr(0)
                left = ("tern", left, a, b)
            else:
                right = self.expr(p)
                left = ("bin", {"&&": "and", "||": "or" if self.lang in ("adf", "ssis") else "||", "==": "=", "!=": "<>"}.get(op, op), left, right)

    def prefix(self):
        k, v = self.take()
        if k == "num":
            return ("num", v)
        if k == "str1":
            return ("str", v[1:-1].replace("''", "'"))
        if k == "str2":
            return ("str", v[1:-1].replace('\\"', '"'))
        if k == "ssisparam":
            return ("param", v.split("::")[1].rstrip("]"))
        if k == "param":
            return ("param", v.lstrip("$:"))
        if k == "bracket":
            return ("col", v[1:-1])
        if k == "ssiscast":
            parts = [p.strip() for p in v.strip("()").split(",")]
            return ("cast", parts[0], tuple(int(x) for x in parts[1:]), self.expr(8))
        if k == "kw":
            if v == "not":
                return ("not", self.expr(8))
            if v in ("true", "false"):
                return ("lit", v.upper())
            if v == "null":
                return ("lit", "NULL")
        if k == "op":
            if v == "(":
                e = self.expr(0)
                self.expect(")")
                return e
            if v == "-":
                return ("neg", self.expr(8))
            if v == "!":
                return ("not", self.expr(8))
        if k == "name":
            if self.peek()[1] == "(":
                self.take()
                args = []
                if self.peek()[1] != ")":
                    while True:
                        args.append(self.expr(0))
                        if self.peek()[1] == ",":
                            self.take()
                            continue
                        break
                self.expect(")")
                return ("call", v.lower(), args)
            name = v.split("@")[-1] if "@" in v else v
            return ("col", name.split(".")[-1] if self.lang != "sql" else name)
        raise Untranslatable(f"unexpected “{v or 'end'}”")


def parse(text: str, lang: str):
    p = _P(tokens(text), lang)
    e = p.expr(0)
    if p.peek()[0] != "end":
        raise Untranslatable(f"unexpected “{p.peek()[1]}”")
    return e


def columns(tree) -> set[str]:
    k = tree[0]
    if k == "col":
        return {tree[1]}
    if k == "call":
        return set().union(*(columns(a) for a in tree[2])) if tree[2] else set()
    if k == "bin":
        return columns(tree[2]) | columns(tree[3])
    if k in ("not", "neg"):
        return columns(tree[1])
    if k == "tern":
        return columns(tree[1]) | columns(tree[2]) | columns(tree[3])
    if k == "cast":
        return columns(tree[3])
    return set()


def _fmt(f: str) -> str:
    """A tool's date format ('YYYYMMDD', 'yyyyMMdd', 'DD-MON-YYYY HH24:MI:SS') as strftime."""
    s = f
    for a, b in (("YYYY", "%Y"), ("yyyy", "%Y"), ("HH24", "%H"), ("MI", "%M"), ("SS", "%S"), ("MON", "%b"), ("MM", "%m"), ("DD", "%d"), ("dd", "%d"), ("HH", "%H"),
                 ("mm", "%M"), ("ss", "%S"), ("YY", "%y")):
        s = s.replace(a, b)
    return s


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _is_text(t) -> bool:
    return t[0] == "str" or (t[0] == "cast" and t[1] in ("DT_WSTR", "DT_STR", "DT_TEXT", "DT_NTEXT")) or (t[0] == "call" and t[1] in ("upper", "lower", "trim", "concat", "tostring", "to_char", "substring"))


def to_sql(tree, resolve, lang: str = "sql") -> str:
    """DuckDB SQL for one expression tree; resolve(column) gives each column's SQL."""
    f = lambda t: to_sql(t, resolve, lang)  # noqa: E731
    k = tree[0]
    if k == "num":
        return tree[1]
    if k == "str":
        return _q(tree[1])
    if k == "lit":
        return tree[1]
    if k == "col":
        return resolve(tree[1])
    if k == "param":
        return "{{ var('" + tree[1].lower() + "') }}"
    if k == "neg":
        return f"(-{f(tree[1])})"
    if k == "not":
        return f"(NOT {f(tree[1])})"
    if k == "tern":
        return f"CASE WHEN {f(tree[1])} THEN {f(tree[2])} ELSE {f(tree[3])} END"
    if k == "cast":
        typ, args, e = tree[1], tree[2], tree[3]
        sql_t = {"DT_WSTR": "VARCHAR", "DT_STR": "VARCHAR", "DT_TEXT": "VARCHAR", "DT_NTEXT": "VARCHAR", "DT_I4": "INTEGER", "DT_I8": "BIGINT", "DT_I2": "SMALLINT",
                 "DT_DBDATE": "DATE", "DT_DATE": "DATE", "DT_DBTIMESTAMP": "TIMESTAMP", "DT_BOOL": "BOOLEAN", "DT_R8": "DOUBLE"}.get(typ)
        if typ == "DT_NUMERIC" or typ == "DT_DECIMAL":
            sql_t = f"DECIMAL({args[0] if args else 18}, {args[1] if len(args) > 1 else 2})"
        if not sql_t:
            raise Untranslatable(f"the SSIS cast {typ} has no rule")
        return f"CAST({f(e)} AS {sql_t})"
    if k == "bin":
        op, a, b = tree[1], tree[2], tree[3]
        if op == "+" and lang in ("ssis", "adf") and (_is_text(a) or _is_text(b)):
            return f"({f(a)} || {f(b)})"
        return f"({f(a)} {op.upper() if op in ('and', 'or') else op} {f(b)})"
    if k == "call":
        return _call(tree[1], tree[2], f, lang)
    raise Untranslatable(f"no rule for {k}")


def _arg_str(t) -> str:
    if t[0] != "str":
        raise Untranslatable("expected a text argument")
    return t[1]


def _call(name: str, args: list, f, lang: str) -> str:
    n = len(args)
    a = [f(x) for x in args] if name not in ("hashbytes", "datediff", "date_diff", "to_char", "tostring", "to_date", "todate", "trunc", "replacestr", "count") else None
    simple = {"upper": "UPPER", "lower": "LOWER", "trim": "TRIM", "ltrim": "LTRIM", "rtrim": "RTRIM", "round": "ROUND", "coalesce": "COALESCE", "replace": "REPLACE",
              "md5": "MD5", "abs": "ABS", "length": "LENGTH", "len": "LENGTH", "substring": "SUBSTRING", "substr": "SUBSTRING", "right": "RIGHT", "left": "LEFT",
              "floor": "FLOOR", "ceil": "CEIL", "ceiling": "CEIL", "greatest": "GREATEST", "least": "LEAST", "nullif": "NULLIF"}
    if name in simple:
        return f"{simple[name]}({', '.join(a)})"
    if name == "concat":
        return "(" + " || ".join(a) + ")"
    if name == "count" and n == 2 and args[1] == ("col", "DISTINCT"):            # Informatica COUNT(x, DISTINCT)
        return f"COUNT(DISTINCT {f(args[0])})"
    if name == "count" and n == 1:
        return f"COUNT({f(args[0])})"
    if name in ("countdistinct", "countd") and n == 1:
        return f"COUNT(DISTINCT {a[0]})"
    if name in ("sum", "avg", "min", "max") and n == 1:
        return f"{name.upper()}({a[0]})"
    if name in ("isnull",) and n == 1:
        return f"({a[0]} IS NULL)"
    if name == "replacenull" and n == 2:
        return f"COALESCE({a[0]}, {a[1]})"
    if name in ("iif", "if") and n == 3:
        return f"CASE WHEN {a[0]} THEN {a[1]} ELSE {a[2]} END"
    if name in ("getdate", "systimestamp", "sysdate", "currenttimestamp", "currentdate", "current_timestamp", "now") and n == 0:
        return "CAST(CURRENT_TIMESTAMP AS TIMESTAMP)"
    if name in ("year", "month", "day") and n == 1:
        return f"EXTRACT({name.upper()} FROM CAST({a[0]} AS DATE))"
    if name in ("to_integer", "tointeger", "toint") and n >= 1:
        return f"CAST({a[0]} AS BIGINT)"
    if name in ("to_decimal", "todecimal") and n >= 1:
        scale = args[-1][1] if n >= 2 and args[-1][0] == "num" else "2"
        return f"CAST({a[0]} AS DECIMAL(18, {scale}))"
    if name in ("tostring", "to_char"):
        if len(args) == 1:
            return f"CAST({f(args[0])} AS VARCHAR)"
        return f"strftime(CAST({f(args[0])} AS DATE), {_q(_fmt(_arg_str(args[1])))})"
    if name in ("to_date", "todate"):
        if len(args) == 1:
            return f"CAST({f(args[0])} AS DATE)"
        return f"CAST(strptime(CAST({f(args[0])} AS VARCHAR), {_q(_fmt(_arg_str(args[1])))}) AS DATE)"
    if name == "trunc" and len(args) == 2 and args[1][0] == "str":
        unit = {"MM": "month", "MON": "month", "MONTH": "month", "YYYY": "year", "YEAR": "year", "DD": "day", "Q": "quarter"}.get(args[1][1].upper())
        if not unit:
            raise Untranslatable(f"TRUNC to {args[1][1]} has no rule")
        return f"CAST(date_trunc('{unit}', {f(args[0])}) AS DATE)"
    if name == "hashbytes" and len(args) == 2 and _arg_str(args[0]).upper() == "MD5":
        return f"MD5({f(args[1])})"
    if name == "datediff" and len(args) == 3 and args[0][0] == "str":          # SSIS DATEDIFF("dd", start, end)
        unit = {"dd": "day", "d": "day", "mm": "month", "m": "month", "yy": "year", "yyyy": "year", "hh": "hour"}.get(args[0][1].lower())
        if not unit:
            raise Untranslatable(f"DATEDIFF in {args[0][1]} has no rule")
        return f"date_diff('{unit}', CAST({f(args[1])} AS DATE), CAST({f(args[2])} AS DATE))"
    if name == "date_diff" and len(args) == 3 and args[2][0] == "str":         # Informatica DATE_DIFF(later, earlier, 'DD')
        unit = {"DD": "day", "D": "day", "MM": "month", "YYYY": "year", "HH": "hour"}.get(args[2][1].upper())
        if not unit:
            raise Untranslatable(f"DATE_DIFF in {args[2][1]} has no rule")
        return f"date_diff('{unit}', CAST({f(args[1])} AS DATE), CAST({f(args[0])} AS DATE))"
    if name == "replacestr" and len(args) == 4:                                  # REPLACESTR(case, s, old, new)
        return f"REPLACE({f(args[1])}, {f(args[2])}, {f(args[3])})"
    raise Untranslatable(f"{name.upper()}() with {n} argument(s) has no rule in {lang}")


def translate(text: str, lang: str, resolve=lambda c: c) -> tuple[str | None, set[str], str]:
    """(sql | None, columns it reads, problem) — never raises."""
    try:
        if lang == "sql":
            return text, set(), ""
        tree = parse(text, lang)
        return to_sql(tree, resolve, lang), columns(tree), ""
    except Untranslatable as e:
        return None, set(), str(e)
    except RecursionError:
        return None, set(), "the expression is nested too deeply"
