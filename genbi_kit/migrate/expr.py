"""The Cognos report expression language, parsed into a small AST shared by the rules (-> DAX and SQL) and the source
simulator (-> values). Covers what report authors write: [Package].[Query subject].[Item] and [Data item] references,
numbers, strings, ?prompt? tokens, #macro# blocks, arithmetic, || (concatenation), comparisons, and / or / not,
in (...), is null / is missing, between, like, if (…) then (…) else (…), case … when … then … else … end, function
calls — aggregates with `for` clauses (`total([Revenue] for [Region])`, `for report`) and `distinct`
(`count(distinct [Customer])`), running / moving aggregates with `auto reset at`.

AST nodes are dicts with a "t" key:
  ref {path}  num {v}  str {v}  prompt {name}  macro {text}  call {fn, args, for, distinct, reset}
  bin {op, l, r}  neg {x}  not {x}  if {c, a, b}  case {subject, when: [[c, v]], else}  in {x, vals, neg}
  isnull {x, neg}  between {x, lo, hi, neg}  like {x, pattern, neg}
"""
from __future__ import annotations

import re

TOKEN = re.compile(r"""
    (?P<ws>\s+) |
    (?P<macro>\#.*?\#) |
    (?P<prompt>\?[A-Za-z_][\w ]*\?) |
    (?P<ref>\[[^\]]*\](?:\s*\.\s*\[[^\]]*\])*) |
    (?P<str>'(?:[^']|'')*') |
    (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?) |
    (?P<op>\|\||<>|<=|>=|!=|[-+*/=<>(),]) |
    (?P<ident>[A-Za-z_][\w-]*)
""", re.X | re.S)
KEYWORDS = {"if", "then", "else", "case", "when", "end", "and", "or", "not", "in", "is", "null", "missing", "for", "report",
            "distinct", "between", "like", "auto", "reset", "at", "true", "false"}


class ParseError(ValueError):
    pass


def tokenize(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ParseError(f"cannot read the expression at: {text[pos:pos + 30]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        val = m.group(kind)
        if kind == "ident" and val.lower() in KEYWORDS:
            out.append(("kw", val.lower()))
        else:
            out.append((kind, val))
    return out


def _ref_path(text: str) -> list[str]:
    return [p.strip() for p in re.findall(r"\[([^\]]*)\]", text)]


class _Parser:
    def __init__(self, text: str):
        self.toks = tokenize(text)
        self.i = 0

    def peek(self, k=0):
        return self.toks[self.i + k] if self.i + k < len(self.toks) else (None, None)

    def take(self, kind=None, val=None):
        t = self.peek()
        if kind and t[0] != kind or val and (t[1] or "").lower() != val:
            raise ParseError(f"expected {val or kind}, found {t[1]!r}")
        self.i += 1
        return t

    def at(self, kind, val=None) -> bool:
        t = self.peek()
        return t[0] == kind and (val is None or (t[1] or "").lower() == val)

    def expr(self):
        return self.or_()

    def or_(self):
        x = self.and_()
        while self.at("kw", "or"):
            self.take(); x = {"t": "bin", "op": "or", "l": x, "r": self.and_()}
        return x

    def and_(self):
        x = self.not_()
        while self.at("kw", "and"):
            self.take(); x = {"t": "bin", "op": "and", "l": x, "r": self.not_()}
        return x

    def not_(self):
        if self.at("kw", "not"):
            self.take(); return {"t": "not", "x": self.not_()}
        return self.cmp()

    def cmp(self):
        x = self.concat()
        neg = False
        if self.at("kw", "not") and self.peek(1)[0] == "kw" and self.peek(1)[1] in ("in", "between", "like"):
            self.take(); neg = True
        if self.at("op") and self.peek()[1] in ("=", "<>", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            return {"t": "bin", "op": "<>" if op == "!=" else op, "l": x, "r": self.concat()}
        if self.at("kw", "in"):
            self.take(); self.take("op", "(")
            vals = [self.expr()]
            while self.at("op", ","):
                self.take(); vals.append(self.expr())
            self.take("op", ")")
            return {"t": "in", "x": x, "vals": vals, "neg": neg}
        if self.at("kw", "between"):
            self.take(); lo = self.concat(); self.take("kw", "and"); hi = self.concat()
            return {"t": "between", "x": x, "lo": lo, "hi": hi, "neg": neg}
        if self.at("kw", "like"):
            self.take(); return {"t": "like", "x": x, "pattern": self.concat(), "neg": neg}
        if self.at("kw", "is"):
            self.take()
            if self.at("kw", "not"):
                self.take(); neg = True
            if self.at("kw", "null") or self.at("kw", "missing"):
                self.take(); return {"t": "isnull", "x": x, "neg": neg}
            raise ParseError("expected null or missing after is")
        return x

    def concat(self):
        x = self.add()
        while self.at("op", "||"):
            self.take(); x = {"t": "bin", "op": "||", "l": x, "r": self.add()}
        return x

    def add(self):
        x = self.mul()
        while self.at("op") and self.peek()[1] in ("+", "-"):
            op = self.take()[1]; x = {"t": "bin", "op": op, "l": x, "r": self.mul()}
        return x

    def mul(self):
        x = self.unary()
        while self.at("op") and self.peek()[1] in ("*", "/"):
            op = self.take()[1]; x = {"t": "bin", "op": op, "l": x, "r": self.unary()}
        return x

    def unary(self):
        if self.at("op", "-"):
            self.take(); return {"t": "neg", "x": self.unary()}
        if self.at("op", "+"):
            self.take(); return self.unary()
        return self.primary()

    def primary(self):
        kind, val = self.peek()
        if kind is None:
            raise ParseError("the expression ends too early")
        if kind == "num":
            self.take(); return {"t": "num", "v": float(val) if "." in val or "e" in val.lower() else int(val)}
        if kind == "str":
            self.take(); return {"t": "str", "v": val[1:-1].replace("''", "'")}
        if kind == "ref":
            self.take(); return {"t": "ref", "path": _ref_path(val)}
        if kind == "prompt":
            self.take(); return {"t": "prompt", "name": val[1:-1].strip()}
        if kind == "macro":
            self.take(); return {"t": "macro", "text": val[1:-1].strip()}
        if kind == "op" and val == "(":
            self.take(); x = self.expr(); self.take("op", ")"); return x
        if kind == "kw" and val == "if":
            return self.if_()
        if kind == "kw" and val == "case":
            return self.case_()
        if kind == "kw" and val in ("true", "false"):
            self.take(); return {"t": "num", "v": 1 if val == "true" else 0}
        if kind == "kw" and val == "null":
            self.take(); return {"t": "null"}
        if kind == "ident":
            if self.peek(1)[0] == "op" and self.peek(1)[1] == "(":
                return self.call()
            self.take()
            return {"t": "ident", "v": val}              # a bare word: a type name in cast(x, integer), a constant such as current_date
        raise ParseError(f"unexpected {val!r}")

    def if_(self):
        self.take("kw", "if")
        c = self.expr()
        self.take("kw", "then")
        a = self.expr()
        b = None
        if self.at("kw", "else"):
            self.take(); b = self.expr()
        return {"t": "if", "c": c, "a": a, "b": b}

    def case_(self):
        self.take("kw", "case")
        subject = None if self.at("kw", "when") else self.expr()
        when = []
        while self.at("kw", "when"):
            self.take(); c = self.expr(); self.take("kw", "then"); when.append([c, self.expr()])
        else_ = None
        if self.at("kw", "else"):
            self.take(); else_ = self.expr()
        self.take("kw", "end")
        return {"t": "case", "subject": subject, "when": when, "else": else_}

    def call(self):
        fn = self.take("ident")[1].lower()
        self.take("op", "(")
        node = {"t": "call", "fn": fn, "args": [], "for": None, "distinct": False, "reset": None}
        if self.at("op", ")"):
            self.take(); return node
        if self.at("kw", "distinct"):
            self.take(); node["distinct"] = True
        node["args"].append(self.expr())
        while self.at("op", ","):
            self.take(); node["args"].append(self.expr())
        if self.at("kw", "for"):
            self.take()
            if self.at("kw", "report"):
                self.take(); node["for"] = []
            else:
                refs = [self.expr()]
                while self.at("op", ","):
                    self.take(); refs.append(self.expr())
                node["for"] = refs
        if self.at("kw", "auto"):
            self.take()
        if self.at("kw", "reset"):
            self.take(); self.take("kw", "at")
            node["reset"] = [self.expr()]
            while self.at("op", ","):
                self.take(); node["reset"].append(self.expr())
        self.take("op", ")")
        return node


def parse(text: str) -> dict:
    p = _Parser(text)
    node = p.expr()
    if p.i != len(p.toks):
        raise ParseError(f"unexpected {p.peek()[1]!r} after the expression")
    return node


# ------------------------------------------------------------------ walking

def walk(node):
    """Every node, depth first."""
    if not isinstance(node, dict):
        return
    yield node
    for k, v in node.items():
        if k == "t":
            continue
        if isinstance(v, dict):
            yield from walk(v)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    yield from walk(x)
                elif isinstance(x, list):
                    for y in x:
                        yield from walk(y)


def refs(node) -> list[list[str]]:
    return [n["path"] for n in walk(node) if n["t"] == "ref"]


def functions(node) -> list[str]:
    return sorted({n["fn"] for n in walk(node) if n["t"] == "call"})


def prompts(node) -> list[str]:
    return sorted({n["name"] for n in walk(node) if n["t"] == "prompt"})


def has_macro(node) -> bool:
    return any(n["t"] == "macro" for n in walk(node))


def to_text(node) -> str:
    """The expression back as Cognos text (normalised spacing)."""
    t = node["t"]
    if t == "ref":
        return ".".join(f"[{p}]" for p in node["path"])
    if t == "num":
        v = node["v"]
        return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    if t == "str":
        return "'" + node["v"].replace("'", "''") + "'"
    if t == "null":
        return "null"
    if t == "ident":
        return node["v"]
    if t == "prompt":
        return f"?{node['name']}?"
    if t == "macro":
        return f"#{node['text']}#"
    if t == "neg":
        return "-" + to_text(node["x"])
    if t == "not":
        return "not " + to_text(node["x"])
    if t == "bin":
        return f"({to_text(node['l'])} {node['op']} {to_text(node['r'])})"
    if t == "if":
        return f"if ({to_text(node['c'])}) then ({to_text(node['a'])})" + (f" else ({to_text(node['b'])})" if node.get("b") else "")
    if t == "case":
        s = "case " + (to_text(node["subject"]) + " " if node.get("subject") else "")
        s += " ".join(f"when {to_text(c)} then {to_text(v)}" for c, v in node["when"])
        return s + (f" else {to_text(node['else'])}" if node.get("else") else "") + " end"
    if t == "in":
        return f"{to_text(node['x'])} {'not ' if node.get('neg') else ''}in ({', '.join(to_text(v) for v in node['vals'])})"
    if t == "isnull":
        return f"{to_text(node['x'])} is {'not ' if node.get('neg') else ''}null"
    if t == "between":
        return f"{to_text(node['x'])} {'not ' if node.get('neg') else ''}between {to_text(node['lo'])} and {to_text(node['hi'])}"
    if t == "like":
        return f"{to_text(node['x'])} {'not ' if node.get('neg') else ''}like {to_text(node['pattern'])}"
    if t == "call":
        inner = ("distinct " if node.get("distinct") else "") + ", ".join(to_text(a) for a in node["args"])
        if node.get("for") is not None:
            inner += " for " + (", ".join(to_text(r) for r in node["for"]) if node["for"] else "report")
        if node.get("reset"):
            inner += " auto reset at " + ", ".join(to_text(r) for r in node["reset"])
        return f"{node['fn']}({inner})"
    raise ValueError(t)


def normalise(text: str) -> tuple[str, list[str]]:
    """The expression with every [reference] replaced by a numbered placeholder — the pattern a learned rule keys on.
    Returns (pattern, references in order)."""
    try:
        node = parse(text)
    except ParseError:
        return re.sub(r"\s+", " ", text.strip().lower()), []
    seen: list[str] = []

    def sub(n):
        if n["t"] == "ref":
            key = ".".join(n["path"])
            if key not in seen:
                seen.append(key)
            return {"t": "ref", "path": [f"{{{seen.index(key)}}}"]}
        out = {}
        for k, v in n.items():
            if isinstance(v, dict):
                out[k] = sub(v)
            elif isinstance(v, list):
                out[k] = [sub(x) if isinstance(x, dict) else [sub(y) for y in x] if isinstance(x, list) else x for x in v]
            else:
                out[k] = v
        return out
    return to_text(sub(node)).lower(), seen
