"""Excel & spreadsheet models — the rules (no agent): reading workbooks (formulas with their cached values, names,
external links, hidden sheets), VBA modules and Power Query M; the findings; a formula parser that evaluates a
workbook again (so a fix is proven before it is kept) and translates a sheet's column formulas into SQL (so a model
leaves Excel and is proven against the workbook's own numbers). The mock lab's workbooks stand in
(tests/mocklab/fixtures/excel_models: a budget model, an AR tie-out, a pricing calculator with VBA, a supplier
master, Power Query M).
"""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

ERRORS = ("#REF!", "#N/A", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#NULL!")
VOLATILE = re.compile(r"(?i)\b(INDIRECT|OFFSET|NOW|TODAY|RAND|RANDBETWEEN)\s*\(")
PERSONAL_PATH = re.compile(r"(?i)([A-Z]:\\{1,2}Users\\{1,2}[^\\\"]+|\\\\[A-Za-z0-9.\-]+\\[^\"]+)")


class XlError(Exception):
    """An Excel error value (#REF!, #N/A …) travelling through an evaluation."""


class External(Exception):
    """A reference into another workbook: not evaluated here."""


# ================================================================== addresses

def col_n(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def col_l(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split(ref: str) -> tuple[int, int]:
    m = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", ref.upper())
    return col_n(m.group(1)), int(m.group(2))


# ================================================================== reading

def read_book(name: str, data: bytes) -> dict:
    """{name, sheets {title: {hidden, max_row, max_col, cells {A1: {f, v}}}}, names {NAME: 'Sheet!$B$2'}, links [file]}."""
    import openpyxl
    fwb = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    vwb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    sheets = {}
    for ws in fwb.worksheets:
        wv = vwb[ws.title]
        cells = {}
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                if isinstance(c.value, str) and c.value.startswith("="):
                    cells[c.coordinate] = {"f": c.value, "v": wv[c.coordinate].value}
                else:
                    cells[c.coordinate] = {"f": None, "v": c.value}
        sheets[ws.title] = {"name": ws.title, "hidden": ws.sheet_state != "visible", "max_row": ws.max_row, "max_col": ws.max_column, "cells": cells}
    names = {}
    dn = fwb.defined_names
    try:
        for n, d in dn.items():
            names[n] = d.attr_text
    except AttributeError:
        for d in getattr(dn, "definedName", []):
            names[d.name] = d.attr_text
    links = []
    for lk in getattr(fwb, "_external_links", None) or []:
        try:
            links.append(lk.file_link.Target)
        except AttributeError:
            links.append("")
    return {"name": name, "sheets": sheets, "names": names, "links": links}


def read_files(paths: list[Path]) -> dict:
    """Every workbook, VBA module (.bas) and Power Query (.pq / .m) uploaded, a .zip opened."""
    import zipfile
    out = {"books": [], "vba": [], "pq": []}
    blobs: list[tuple[str, bytes]] = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                blobs += [(n, z.read(n)) for n in z.namelist() if not n.endswith("/")]
        else:
            blobs.append((p.name, p.read_bytes()))
    for n, b in blobs:
        low = n.lower()
        if low.endswith((".xlsx", ".xlsm")):
            out["books"].append(read_book(Path(n).name, b))
        elif low.endswith((".bas", ".cls", ".vba")):
            out["vba"].append({"name": Path(n).name, "text": b.decode("utf-8", errors="replace")})
        elif low.endswith((".pq", ".m")):
            out["pq"].append({"name": Path(n).name, "text": b.decode("utf-8", errors="replace")})
    return out


# ================================================================== the formula parser

TOK = re.compile(r"""
 (?P<ws>\s+)
|(?P<str>"(?:[^"]|"")*")
|(?P<ref>(?:(?:'(?:[^']|'')+'|\[\d+\][A-Za-z_][\w.]*|[A-Za-z_][\w.]*)!)?(?:\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![\w(])|\$?[A-Z]{1,3}:\$?[A-Z]{1,3}(?![\w(])|\#REF!))
|(?P<err>\#(?:REF!|N/A|DIV/0!|VALUE!|NAME\?|NUM!|NULL!))
|(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
|(?P<func>[A-Za-z_][\w.]*(?=\s*\())
|(?P<name>[A-Za-z_][\w.]*)
|(?P<op><>|<=|>=|[-+*/^&=<>%(),;])
""", re.X)
PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}


def tokens(text: str) -> list[tuple[str, str]]:
    out, i = [], 0
    s = text[1:] if text.startswith("=") else text
    while i < len(s):
        m = TOK.match(s, i)
        if not m:
            raise ValueError(f"cannot read the formula at “{s[i:i + 12]}”")
        i = m.end()
        if m.lastgroup != "ws":
            out.append((m.lastgroup, m.group(m.lastgroup)))
    return out


def parse(text: str):
    toks = tokens(text)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else (None, None)

    def take():
        t = peek()
        pos[0] += 1
        return t

    def primary():
        k, v = take()
        if k == "num":
            return ("num", float(v))
        if k == "str":
            return ("str", v[1:-1].replace('""', '"'))
        if k == "err":
            return ("err", v)
        if k == "ref":
            if v.endswith("#REF!"):
                sheet, ref = (v[:-6] or None), "#REF!"
            else:
                sheet, ref = (v.rsplit("!", 1) if "!" in v else (None, v))
            ext = None
            if sheet and sheet.startswith("["):
                ext, sheet = re.match(r"\[(\d+)\](.*)", sheet).groups()
            if sheet and sheet.startswith("'"):
                sheet = sheet[1:-1].replace("''", "'")
            return ("ref", sheet, ref.replace("$", "") if ref != "#REF!" else ref, ext, "$" in ref)
        if k == "name":
            if v.upper() in ("TRUE", "FALSE"):
                return ("bool", v.upper() == "TRUE")
            return ("name", v)
        if k == "func":
            take()                                       # (
            args = []
            if peek() != ("op", ")"):
                while True:
                    args.append(expr(0))
                    if peek() in (("op", ","), ("op", ";")):
                        take()
                        continue
                    break
            if take() != ("op", ")"):
                raise ValueError("a function is not closed")
            return ("call", v.upper(), args)
        if (k, v) == ("op", "("):
            e = expr(0)
            if take() != ("op", ")"):
                raise ValueError("a bracket is not closed")
            return e
        if (k, v) == ("op", "-"):
            return ("neg", unary())
        if (k, v) == ("op", "+"):
            return unary()
        raise ValueError(f"unexpected {v!r}")

    def unary():
        e = primary()
        while peek() == ("op", "%"):
            take()
            e = ("bin", "/", e, ("num", 100.0))
        return e

    def expr(minp):
        left = unary()
        while True:
            k, v = peek()
            if k != "op" or v not in PREC or PREC[v] < minp:
                return left
            take()
            right = expr(PREC[v] + (0 if v == "^" else 1))
            left = ("bin", v, left, right)
    tree = expr(0)
    if pos[0] != len(toks):
        raise ValueError(f"unexpected {toks[pos[0]][1]!r}")
    return tree


def refs(tree) -> list[tuple]:
    out = []

    def walk(t):
        if t[0] == "ref":
            out.append(t)
        elif t[0] == "call":
            for a in t[2]:
                walk(a)
        elif t[0] == "bin":
            walk(t[2])
            walk(t[3])
        elif t[0] == "neg":
            walk(t[1])
    walk(tree)
    return out


# ================================================================== evaluating a workbook again

class Book:
    """Evaluates cells of a workbook from their formulas (the subset finance models use), so a fix is proven before it
    is kept and a model's numbers are checked independently of the values Excel cached."""

    def __init__(self, book: dict, override: dict | None = None):
        self.b = book
        self.memo: dict = {}
        self.override = override or {}               # {(sheet, A1): formula}
        self.names = {}
        for n, t in book["names"].items():
            m = re.fullmatch(r"'?([^'!]+)'?!\$?([A-Z]{1,3})\$?(\d+)", t or "")
            if m:
                self.names[n.upper()] = (m.group(1), f"{m.group(2)}{m.group(3)}")

    def raw(self, sheet: str, a1: str):
        return ((self.b["sheets"].get(sheet) or {}).get("cells") or {}).get(a1)

    def cell(self, sheet: str, a1: str):
        k = (sheet, a1)
        if k in self.memo:
            v = self.memo[k]
            if isinstance(v, XlError):
                raise v
            return v
        self.memo[k] = XlError("#REF!")             # a circular reference ends as an error
        f = self.override.get(k)
        c = self.raw(sheet, a1)
        if f is None:
            f = c["f"] if c else None
        try:
            v = self.eval(parse(f), sheet) if f else (c["v"] if c else None)
            if isinstance(v, str) and v in ERRORS:
                raise XlError(v)
        except XlError as e:
            self.memo[k] = e
            raise
        self.memo[k] = v
        return v

    def area(self, sheet: str, ref: str) -> list[list]:
        s = self.b["sheets"].get(sheet)
        if not s:
            raise XlError("#REF!")
        if re.fullmatch(r"[A-Z]{1,3}:[A-Z]{1,3}", ref):
            a, b = ref.split(":")
            c1, c2, r1, r2 = col_n(a), col_n(b), 1, s["max_row"]
        else:
            p, q = (ref.split(":") + [ref])[:2]
            (c1, r1), (c2, r2) = split(p), split(q)
        return [[self._safe(sheet, f"{col_l(c)}{r}") for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]

    def _safe(self, sheet, a1):
        try:
            return self.cell(sheet, a1)
        except XlError as e:
            return e

    def eval(self, t, sheet):
        k = t[0]
        if k in ("num", "str", "bool"):
            return t[1]
        if k == "err":
            raise XlError(t[1])
        if k == "ref":
            _, sh, ref, ext, _ = t
            if ext:
                raise External(f"[{ext}]{sh}!{ref}")
            if ref == "#REF!":
                raise XlError("#REF!")
            sh = sh or sheet
            if ":" in ref:
                return self.area(sh, ref)
            return self.cell(sh, ref)
        if k == "name":
            n = self.names.get(t[1].upper())
            if not n:
                raise XlError("#NAME?")
            return self.cell(*n)
        if k == "neg":
            return -num(self.eval(t[1], sheet))
        if k == "bin":
            op = t[1]
            a, b = self.eval(t[2], sheet), self.eval(t[3], sheet)
            if op == "&":
                return f"{text(a)}{text(b)}"
            if op in ("=", "<>", "<", ">", "<=", ">="):
                x, y = (a.lower(), b.lower()) if isinstance(a, str) and isinstance(b, str) else (a, b)
                return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
            x, y = num(a), num(b)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    raise XlError("#DIV/0!")
                return x / y
            try:
                return x ** y
            except (OverflowError, ValueError) as e:
                raise XlError("#NUM!") from e
        if k == "call":
            return self.call(t[1], t[2], sheet)
        raise XlError("#VALUE!")

    def call(self, fn, args, sheet):
        ev = lambda a: self.eval(a, sheet)  # noqa: E731
        if fn == "IF":
            return ev(args[1]) if truthy(ev(args[0])) else (ev(args[2]) if len(args) > 2 else False)
        if fn == "IFERROR":
            try:
                return ev(args[0])
            except (XlError, ZeroDivisionError):
                return ev(args[1])
        vals = [ev(a) for a in args]
        if fn in ("SUM", "AVERAGE", "MIN", "MAX", "COUNT"):
            ns = [x for x in flat(vals) if isinstance(x, (int, float)) and not isinstance(x, bool)]
            return {"SUM": sum(ns), "AVERAGE": (sum(ns) / len(ns)) if ns else 0.0, "MIN": min(ns, default=0), "MAX": max(ns, default=0), "COUNT": len(ns)}[fn]
        if fn == "COUNTA":
            return sum(1 for x in flat(vals) if x not in (None, ""))
        if fn == "ROUND":
            x, n = num(vals[0]), int(num(vals[1]) if len(vals) > 1 else 0)
            return math.copysign(math.floor(abs(x) * 10 ** n + 0.5 + 1e-9) / 10 ** n, x)
        if fn == "ABS":
            return abs(num(vals[0]))
        if fn == "COUNTIF":
            return sum(1 for x in flat([vals[0]]) if meets(x, vals[1]))
        if fn == "SUMIF":
            rng, crit = flat([vals[0]]), vals[1]
            srng = flat([vals[2]]) if len(vals) > 2 else rng
            return sum(num(s) for x, s in zip(rng, srng) if meets(x, crit) and isinstance(s, (int, float)))
        if fn == "SUMIFS":
            srng = flat([vals[0]])
            pairs = [(flat([vals[i]]), vals[i + 1]) for i in range(1, len(vals) - 1, 2)]
            return sum(num(s) for i, s in enumerate(srng) if isinstance(s, (int, float)) and all(i < len(r) and meets(r[i], c) for r, c in pairs))
        if fn == "INDEX":
            rng = vals[0] if isinstance(vals[0], list) else [[vals[0]]]
            r, c = int(num(vals[1])), int(num(vals[2])) if len(vals) > 2 else 1
            if r < 1 or r > len(rng) or c < 1 or c > len(rng[0]):
                raise XlError("#REF!")
            v = rng[r - 1][c - 1]
            if isinstance(v, XlError):
                raise v
            return v
        if fn == "MATCH":
            look, rng = vals[0], flat([vals[1]])
            mt = int(num(vals[2])) if len(vals) > 2 else 1
            if mt == 0:
                for i, x in enumerate(rng):
                    if same(x, look):
                        return i + 1
                raise XlError("#N/A")
            best = None
            for i, x in enumerate(rng):
                if isinstance(x, (int, float)) and isinstance(look, (int, float)) and x <= look:
                    best = i + 1
            if best is None:
                raise XlError("#N/A")
            return best
        if fn == "VLOOKUP":
            look, table, ci = vals[0], vals[1], int(num(vals[2]))
            approx = truthy(vals[3]) if len(vals) > 3 else True
            hit = None
            for row in table:
                x = row[0]
                if approx:
                    if isinstance(x, (int, float)) and isinstance(look, (int, float)) and x <= look:
                        hit = row
                elif same(x, look):
                    hit = row
                    break
            if hit is None:
                raise XlError("#N/A")
            v = hit[ci - 1]
            if isinstance(v, XlError):
                raise v
            return v
        if fn in ("AND", "OR"):
            bs = [truthy(x) for x in flat(vals)]
            return all(bs) if fn == "AND" else any(bs)
        if fn == "NOT":
            return not truthy(vals[0])
        raise XlError("#NAME?")


def flat(vals) -> list:
    out = []
    for v in vals:
        if isinstance(v, list):
            for row in v:
                out += row if isinstance(row, list) else [row]
        else:
            out.append(v)
    return out


def num(v) -> float:
    if isinstance(v, XlError):
        raise v
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except ValueError as e:
        raise XlError("#VALUE!") from e


def text(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "" if v is None else str(v)


def truthy(v) -> bool:
    if isinstance(v, str):
        return v.upper() == "TRUE"
    return bool(v)


def same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def meets(x, crit) -> bool:
    if isinstance(crit, str):
        m = re.fullmatch(r"(<>|<=|>=|<|>|=)?(.*)", crit)
        op, rhs = m.group(1) or "=", m.group(2)
        try:
            r = float(rhs)
            xv = float(x) if isinstance(x, (int, float)) else None
        except ValueError:
            r, xv = rhs, None
        if xv is None:
            a, b = str(x or "").lower(), str(rhs).lower()
            return {"=": a == b, "<>": a != b}.get(op, False)
        return {"=": xv == r, "<>": xv != r, "<": xv < r, ">": xv > r, "<=": xv <= r, ">=": xv >= r}[op]
    return same(x, crit)


def close(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= max(0.006, abs(float(b)) * 1e-9)
    return str(a if a is not None else "").strip().lower() == str(b if b is not None else "").strip().lower()


# ================================================================== the findings

def _named_values(book: dict) -> dict[str, float]:
    bk = Book(book)
    out = {}
    for n, (sh, a1) in bk.names.items():
        try:
            v = bk.cell(sh, a1)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[n] = float(v)
        except (XlError, External):
            pass
    return out


def findings(src: dict) -> list[dict]:
    """[{id, kind, book, where, issue, route, minutes, fix?}] — every finding of the workbooks, VBA and Power Query."""
    out = []

    def add(kind, book, where, issue, route, minutes, **kw):
        out.append({"id": f"{kind}:{book}!{where}", "kind": kind, "book": book, "where": where, "issue": issue, "route": route, "minutes": minutes, **kw})
    for b in src["books"]:
        named = _named_values(b)
        used = set()
        for sh in b["sheets"].values():
            for a1, c in sh["cells"].items():
                if not c["f"]:
                    continue
                f = c["f"]
                for m in re.finditer(r"(?:'([^']+)'|([A-Za-z_][\w.]*))!", f):
                    used.add(m.group(1) or m.group(2))
                where = f"{sh['name']}!{a1}"
                if "#REF!" in f or (isinstance(c["v"], str) and c["v"] in ERRORS):
                    add("error", b["name"], where, f"{where} is {c['v'] if isinstance(c['v'], str) and c['v'] in ERRORS else '#REF!'}: {f}", "change", 10, formula=f)
                for m in re.finditer(r"(?<![\w.$:])(\d+\.\d+|\d+)(?![\w.(:!])", f):
                    x = float(m.group(1))
                    hit = next((n for n, v in named.items() if x not in (0, 1) and (abs(x - v) < 1e-9 or abs(x - (1 + v)) < 1e-9)), None)
                    if hit:
                        add("hardcoded", b["name"], where, f"{where} types {m.group(1)} where the input {hit} ({named[hit]:g}) is meant: {f}", "change", 5, name=hit, literal=m.group(1), formula=f)
                        break
                ext = re.search(r"\[(\d+)\]([A-Za-z_][\w.]*)!", f)
                if ext:
                    target = b["links"][int(ext.group(1)) - 1] if int(ext.group(1)) - 1 < len(b["links"]) else f"link {ext.group(1)}"
                    add("external", b["name"], where, f"{where} reads another workbook ({target}): {f}", "change", 15, link=target, formula=f)
                if VOLATILE.search(f):
                    add("volatile", b["name"], where, f"{where} uses a volatile function: {f}", "change", 5, formula=f)
        for sh in b["sheets"].values():
            if sh["hidden"] and sh["name"] not in used:
                add("unused", b["name"], sh["name"], f"the hidden sheet {sh['name']} feeds nothing", "retire", 5)
            breaks = [a1 for a1, c in sh["cells"].items() if c["f"] and c["v"] == "BREAK"]
            if breaks:
                add("breaks", b["name"], sh["name"], f"{len(breaks)} row(s) of {sh['name']} do not tie out ({', '.join(sorted(breaks, key=lambda x: split(x)[1])[:6])})", "ticket", 15, cells=breaks)
    for v in src["vba"]:
        for m in PERSONAL_PATH.finditer(v["text"]):
            add("vba_path", v["name"], m.group(1)[:60], f"the macro writes to a personal path: {m.group(1)}", "change", 15)
            break
        if re.search(r"(?i)Application\.Calculation\s*=\s*xlCalculationManual", v["text"]) and not re.search(r"(?i)On Error", v["text"]):
            add("vba_calc", v["name"], "Calculation", "the macro turns calculation off without an error handler to turn it back on", "change", 10)
    for q in src["pq"]:
        for m in re.finditer(r'(?i)File\.Contents\("([^"]+)"\)', q["text"]):
            add("pq_path", q["name"], m.group(1)[:60], f"the query reads a file on a personal or local path: {m.group(1)}", "change", 10)
    return out


LABEL = {"error": "Formula errors", "hardcoded": "Numbers typed in place of an input", "external": "Links to other workbooks", "volatile": "Volatile functions",
         "unused": "Hidden sheets that feed nothing", "breaks": "Tie-outs that do not tie out", "vba_path": "Macros writing to personal paths",
         "vba_calc": "Macros that turn calculation off", "pq_path": "Queries reading local files"}


# ================================================================== a fix proposed by the column's pattern

def relative(f: str, row: int) -> str:
    """A formula with its same-row references written relative to its row (R), so rows compare."""
    return re.sub(r"(?<![\w$'\]])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\w(])", lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{'R' if not m.group(3) and int(m.group(4)) == row else m.group(4)}", f)


def at_row(pattern: str, row: int) -> str:
    return re.sub(r"(?<![\w$'\]])(\$?)([A-Z]{1,3})(\$?)R(?![\w(])", lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{row}", pattern)


def pattern_fix(book: dict, sheet: str, a1: str) -> tuple[str | None, str]:
    """The formula this cell should hold: the one its column's other rows share, written for its row."""
    sh = book["sheets"][sheet]
    c, r = split(a1)
    pats = {}
    for x, cc in sh["cells"].items():
        cx, rx = split(x)
        if cx == c and rx != r and cc["f"] and "#REF!" not in cc["f"]:
            p = relative(cc["f"], rx)
            pats[p] = pats.get(p, 0) + 1
    if not pats:
        return None, "no other row of the column has a formula to follow"
    p, n = max(pats.items(), key=lambda kv: kv[1])
    if n < 2:
        return None, "the column's rows do not share one formula"
    return at_row(p, r), f"the formula the column's other {n} row(s) share"


def literal_fix(f: str, literal: str, name: str, value: float) -> str:
    """1.18 where (1 + GST_RATE) is meant, 0.18 where GST_RATE is."""
    lit = float(literal)
    rep = name if abs(lit - value) < 1e-9 else f"(1+{name})"
    return re.sub(rf"(?<![\w.$:]){re.escape(literal)}(?![\w.(:!])", rep, f, count=1)


# ================================================================== a sheet's column formulas as SQL

def snake(s: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(s or "").strip()).strip("_").lower()
    return ("c_" + s) if not s or s[0].isdigit() else s


def table_of(book: dict, sheet: str) -> dict:
    """A sheet as a table: the header row's names, the data rows' input values, the column formulas (one pattern per
    column) and the rows that are not data (a totals row)."""
    sh = book["sheets"][sheet]
    head = {split(a1)[0]: str(c["v"]) for a1, c in sh["cells"].items() if split(a1)[1] == 1 and c["v"] not in (None, "")}
    cols = {n: snake(h) for n, h in head.items()}
    seen = set()
    for n in sorted(cols):
        while cols[n] in seen:
            cols[n] += "_2"
        seen.add(cols[n])
    rows = sorted({split(a1)[1] for a1 in sh["cells"]} - {1})
    first = min(cols) if cols else 1
    data = [r for r in rows if not (str((sh["cells"].get(f"{col_l(first)}{r}") or {}).get("v") or "").strip().lower() in ("total", "totals", "grand total"))]
    formulas: dict[int, dict] = {}
    for n in cols:
        pats = {}
        for r in data:
            c = sh["cells"].get(f"{col_l(n)}{r}")
            if c and c["f"]:
                pats.setdefault(relative(c["f"], r), []).append(r)
        if pats:
            p, rs = max(pats.items(), key=lambda kv: len(kv[1]))
            formulas[n] = {"pattern": p, "rows": rs, "other": {k: v for k, v in pats.items() if k != p}}
    return {"sheet": sheet, "cols": cols, "head": head, "data": data, "formulas": formulas, "totals": [r for r in rows if r not in data]}


def table_name(sheet: str) -> str:
    return snake(sheet)


class Untranslated(Exception):
    pass


SENT = 999999                                           # the row a column pattern is parsed at


def to_sql(book: dict, sheet: str, tables: dict, named: dict[str, float]) -> dict[str, str]:
    """{column: SQL expression} for the sheet's column formulas, over `t` (the sheet's own rows); other sheets are read
    by aligned rows or by key lookups; a formula no rule translates raises Untranslated with the reason."""
    tb = tables[sheet]
    out: dict[str, str] = {}
    errors: dict[str, str] = {}

    def colname(sh: str, letters: str) -> str:
        t = tables.get(sh)
        if not t:
            raise Untranslated(f"the sheet {sh} is not read")
        n = col_n(letters)
        if n not in t["cols"]:
            raise Untranslated(f"{sh}!{letters} has no header")
        return t["cols"][n]

    def view_of(sh: str, col: str) -> str:
        t = tables[sh]
        n = next(k for k, v in t["cols"].items() if v == col)
        return f'"{table_name(sh)}__model"' if n in t["formulas"] else f'"{table_name(sh)}"'

    def ref_sql(node, scalar=True) -> str:
        _, sh, ref, ext, _ = node
        if ext:
            raise Untranslated(f"it reads another workbook ([{ext}]{sh}!{ref})")
        if ref == "#REF!":
            raise Untranslated("it holds #REF!")
        sh = sh or sheet
        m = re.fullmatch(r"([A-Z]{1,3})(\d+)", ref)
        if m and int(m.group(2)) == SENT:
            c = colname(sh, m.group(1))
            if sh == sheet:
                return f"t.{c}"
            return f'(SELECT x.{c} FROM {view_of(sh, c)} x WHERE x._row = t._row)'
        raise Untranslated(f"{sh}!{ref} is not a same-row reference")

    def col_of_range(node) -> tuple[str, str]:
        _, sh, ref, ext, _ = node
        sh = sh or sheet
        m = re.fullmatch(r"([A-Z]{1,3})(?:\d+)?:([A-Z]{1,3})(?:\d+)?", ref)
        if not m or m.group(1) != m.group(2):
            raise Untranslated(f"{sh}!{ref} is not one column")
        return sh, colname(sh, m.group(1))

    def sql(t) -> str:
        k = t[0]
        if k == "num":
            v = t[1]
            for n, val in named.items():                 # a typed-in input becomes the input it means
                if v not in (0, 1) and abs(v - val) < 1e-9:
                    return f"{val!r} /* {n} */"
                if v not in (0, 1) and abs(v - (1 + val)) < 1e-9:
                    return f"(1 + {val!r} /* {n} */)"
            return repr(int(v)) if float(v).is_integer() else repr(v)
        if k == "str":
            return "'" + t[1].replace("'", "''") + "'"
        if k == "bool":
            return "TRUE" if t[1] else "FALSE"
        if k == "name":
            if t[1].upper() in named:
                return f"{named[t[1].upper()]!r} /* {t[1].upper()} */"
            raise Untranslated(f"the name {t[1]} is not an input")
        if k == "err":
            raise Untranslated(f"it holds {t[1]}")
        if k == "ref":
            if ":" in t[2]:
                raise Untranslated("a range outside a function")
            return ref_sql(t)
        if k == "neg":
            return f"(-{sql(t[1])})"
        if k == "bin":
            a, b = sql(t[2]), sql(t[3])
            op = t[1]
            if op == "&":
                return f"(CAST({a} AS VARCHAR) || CAST({b} AS VARCHAR))"
            if op == "/":
                return f"({a} / NULLIF({b}, 0))"
            if op == "^":
                return f"POWER({a}, {b})"
            return f"({a} {op if op != '<>' else '<>'} {b})"
        if k == "call":
            fn, args = t[1], t[2]
            if fn == "SUM" and len(args) == 1 and args[0][0] == "ref" and ":" in args[0][2]:
                _, sh, ref, ext, _ = args[0]
                m = re.fullmatch(rf"([A-Z]{{1,3}}){SENT}:([A-Z]{{1,3}}){SENT}", ref)
                if m and (sh or sheet) == sheet:
                    return "(" + " + ".join(f"COALESCE(t.{colname(sheet, col_l(n))}, 0)" for n in range(col_n(m.group(1)), col_n(m.group(2)) + 1)) + ")"
                raise Untranslated("SUM over a range that is not this row's")
            if fn in ("SUM", "MIN", "MAX") and all(a[0] != "ref" or ":" not in a[2] for a in args):
                xs = [sql(a) for a in args]
                return {"SUM": "(" + " + ".join(f"COALESCE({x}, 0)" for x in xs) + ")", "MIN": f"LEAST({', '.join(xs)})", "MAX": f"GREATEST({', '.join(xs)})"}[fn]
            if fn == "ROUND":
                return f"ROUND({sql(args[0])}, {sql(args[1]) if len(args) > 1 else 0})"
            if fn == "ABS":
                return f"ABS({sql(args[0])})"
            if fn == "IF":
                return f"(CASE WHEN {sql(args[0])} THEN {sql(args[1])} ELSE {sql(args[2]) if len(args) > 2 else 'FALSE'} END)"
            if fn == "IFERROR":
                return f"COALESCE({sql(args[0])}, {sql(args[1])})"
            if fn == "INDEX" and len(args) == 2 and args[1][0] == "call" and args[1][1] == "MATCH":
                sh, col = col_of_range(args[0])
                msh, mcol = col_of_range(args[1][2][1])
                if msh != sh:
                    raise Untranslated("INDEX and MATCH over two sheets")
                return f"(SELECT x.{col} FROM {view_of(sh, col)} x WHERE x.{mcol} = {sql(args[1][2][0])} LIMIT 1)"
            if fn == "VLOOKUP":
                _, sh, ref, ext, _ = args[1]
                sh = sh or sheet
                m = re.fullmatch(r"([A-Z]{1,3})(\d+)?:([A-Z]{1,3})(\d+)?", ref)
                if not m:
                    raise Untranslated("VLOOKUP over an unknown range")
                key = colname(sh, m.group(1))
                val = colname(sh, col_l(col_n(m.group(1)) + int(sql(args[2])) - 1))
                approx = len(args) < 4 or sql(args[3]) in ("TRUE", "1")
                if approx:
                    return f"(SELECT x.{val} FROM {view_of(sh, val)} x WHERE x.{key} <= {sql(args[0])} ORDER BY x.{key} DESC LIMIT 1)"
                return f"(SELECT x.{val} FROM {view_of(sh, val)} x WHERE x.{key} = {sql(args[0])} LIMIT 1)"
            if fn in ("SUMIFS", "SUMIF"):
                if fn == "SUMIF":
                    args = [args[2] if len(args) > 2 else args[0], args[0], args[1]]
                sh, col = col_of_range(args[0])
                conds = []
                for i in range(1, len(args) - 1, 2):
                    csh, ccol = col_of_range(args[i])
                    if csh != sh:
                        raise Untranslated("SUMIFS over two sheets")
                    conds.append(f"x.{ccol} = {sql(args[i + 1])}")
                return f"(SELECT COALESCE(SUM(x.{col}), 0) FROM {view_of(sh, col)} x WHERE {' AND '.join(conds) or 'TRUE'})"
            raise Untranslated(f"no rule translates {fn}")
        raise Untranslated("an unknown part")

    for n, f in sorted(tb["formulas"].items()):
        col = tb["cols"].get(n)
        if not col:
            continue
        try:
            out[col] = sql(parse(at_row(f["pattern"], SENT)))
        except Untranslated as e:
            errors[col] = str(e)
        except ValueError as e:
            errors[col] = f"the formula does not parse: {e}"
    return {"sql": out, "untranslated": errors}


def order(tables: dict) -> list[str]:
    """Sheets in the order their models can be built: a sheet reading another's computed column comes after it."""
    deps = {s: set() for s in tables}
    for s, t in tables.items():
        for f in t["formulas"].values():
            for m in re.finditer(r"(?:'([^']+)'|([A-Za-z_][\w.]*))!", f["pattern"]):
                o = m.group(1) or m.group(2)
                if o in tables and o != s:
                    deps[s].add(o)
    out, left = [], dict(deps)
    while left:
        ready = sorted(s for s, d in left.items() if not (d - set(out)))
        if not ready:
            out += sorted(left)
            break
        out += ready
        for s in ready:
            left.pop(s)
    return out


def model_sql(sheet: str, tb: dict, exprs: dict[str, str]) -> str:
    """The sheet's model: its input columns and each computed column, in dependency order inside the sheet."""
    inputs = [c for n, c in sorted(tb["cols"].items()) if n not in tb["formulas"]]
    comp = [(c, e) for c, e in exprs.items()]
    # a computed column read by another computed column of the same sheet is expanded in place
    done = {c: e for c, e in comp}
    for _ in range(4):
        for c in list(done):
            for o, e in done.items():
                if o != c:
                    done[c] = re.sub(rf"\bt\.{re.escape(o)}\b", f"({e})", done[c])
    cols = ["t._row"] + [f"t.{c}" for c in inputs] + [f"{e} AS {c}" for c, e in done.items()]
    return f'CREATE OR REPLACE VIEW "{table_name(sheet)}__model" AS\nSELECT ' + ",\n       ".join(cols) + f'\nFROM "{table_name(sheet)}" t'
