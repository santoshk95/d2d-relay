"""A custom visual's caps.js, read as data: its field wells (roles), data mapping and Format-pane objects become
capabilities.json without the file being run (security audit, 2026-11-11).

The AI writes caps.js, and whatever a data file or an attachment told it, nothing it writes may run on the server:
Node would run caps.js with the AI engine's own rights (every organisation's folders, the Claude login). So it is read
here instead, in the one shape every caps.js has:

    module.exports = ({ E, num, bool, text, color }) => ({ roles: [...], mappings: [...], objects: {...}, ... });

Inside the object: texts ('...', "...", or `...` without ${}), numbers, true / false / null, arrays and objects (keys
plain or quoted; trailing commas and comments allowed), the helpers the first line names (num, bool, text, color, fsz,
units, font, LINE) and E([value, name], ...) for a list of choices. Anything else (a variable, another call, a spread,
a template with ${...}, `undefined`) is refused with its line, so the AI rewrites it as plain data.

capabilities() and text() give what Visual Atlas's tools/mk_caps.js writes for the same file, byte for byte: the shared
objects (style, palette, dataColors, labels, axes, gridlines, legend) plus the visual's own.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

MAX_BYTES = 256 * 1024
MAX_DEPTH = 64
_MISSING = object()                     # a property the object does not have (JavaScript's undefined)


class CapsError(ValueError):
    """Why caps.js cannot be read; the text says where (line) and what to write instead."""


def _E(*pairs) -> dict:
    out = []
    for p in pairs:
        if not (isinstance(p, list) and len(p) == 2):
            raise CapsError("E(...) takes pairs: E(['value', 'Display name'], ...)")
        out.append({"value": p[0], "displayName": p[1]})
    return {"type": {"enumeration": out}}


def _helpers() -> dict:
    """mk_caps.js's helpers, as data (a new copy each time)."""
    return {"num": {"type": {"numeric": True}}, "bool": {"type": {"bool": True}}, "text": {"type": {"text": True}},
            "color": {"type": {"fill": {"solid": {"color": True}}}}, "fsz": {"type": {"formatting": {"fontSize": True}}},
            "units": {"type": {"formatting": {"labelDisplayUnits": True}}},
            "font": {"type": {"formatting": {"fontFamily": True}}},
            "LINE": _E(["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"])}


HELPERS = ("E",) + tuple(_helpers())


def _shared() -> dict:
    """The objects every Atlas family shares (the cards in common/cards.ts), as mk_caps.js lists them."""
    h = _helpers()
    num, bool_, text, color, fsz, units, font, line = (h[k] for k in ("num", "bool", "text", "color", "fsz", "units", "font", "LINE"))
    return {
        "style": {"properties": {"fontFamily": font, "textColor": color, "keepOthers": bool_, "marker": bool_, "markerColor": color,
                                 "markerHighlight": bool_}},
        "palette": {"properties": {"source": _E(["theme", "Report theme"], ["brand", "Brand color"], ["custom", "Custom list"]),
                                   "brand": color, "mode": _E(["spectrum", "Spectrum"], ["analogous", "Analogous"], ["mono", "Mono"]),
                                   "custom": text}},
        "dataColors": {"properties": {"fill": color}},
        "labels": {"properties": {"show": bool_, "fontSize": fsz, "color": color, "displayUnits": units, "decimals": num}},
        "categoryAxis": {"properties": {"show": bool_, "fontSize": fsz, "color": color, "title": bool_}},
        "valueAxis": {"properties": {"show": bool_, "fontSize": fsz, "color": color, "displayUnits": units, "decimals": num,
                                     "start": text, "end": text, "title": bool_}},
        "gridlines": {"properties": {"show": bool_, "color": color, "style": line, "width": num}},
        "legend": {"properties": {"show": bool_, "position": _E(["top", "Top"], ["topCenter", "Top center"], ["bottom", "Bottom"],
                                                              ["bottomCenter", "Bottom center"], ["right", "Right"]),
                                  "fontSize": fsz, "color": color, "title": bool_}},
    }


# ---------------------------------------------------------------- reading caps.js

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?(?![A-Za-z0-9_$]))
  | (?P<str>'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\$]|\\.|\$(?!\{))*`)
  | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<arrow>=>)
  | (?P<punct>[{}\[\](),:;.=])
""", re.S | re.X)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _unquote(raw: str, line: int) -> str:
    body, out, i = raw[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt == "\n":                                  # a line continuation
            i += 2
        elif nxt == "x" and re.fullmatch(r"[0-9A-Fa-f]{2}", body[i + 2:i + 4]):
            out.append(chr(int(body[i + 2:i + 4], 16)))
            i += 4
        elif nxt == "u" and body[i + 2:i + 3] == "{":
            end = body.find("}", i + 3)
            if end < 0 or not re.fullmatch(r"[0-9A-Fa-f]{1,6}", body[i + 3:end]):
                raise CapsError(f"line {line}: a \\u{{...}} escape is not complete")
            out.append(chr(int(body[i + 3:end], 16)))
            i = end + 1
        elif nxt == "u":
            if not re.fullmatch(r"[0-9A-Fa-f]{4}", body[i + 2:i + 6]):
                raise CapsError(f"line {line}: a \\u escape needs four hex digits")
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        else:
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
    # "😀" is one character in JavaScript: join escaped surrogate pairs (a lone one stays)
    return "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _tokens(text: str) -> list[tuple[str, object, int]]:
    out, i, line = [], 0, 1
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise CapsError(f"line {line}: {text[i:i + 20]!r} is not allowed in caps.js - it holds plain data only "
                            "(texts, numbers, true/false/null, arrays, objects and the helpers)")
        kind, raw = m.lastgroup, m.group()
        if kind == "num":
            v = float(raw) if any(ch in raw for ch in ".eE") else int(raw)
            out.append(("value", v, line))
        elif kind == "str":
            out.append(("value", _unquote(raw, line), line))
        elif kind in ("ident", "arrow", "punct"):
            out.append((kind if kind == "ident" else "p", raw, line))
        line += raw.count("\n")
        i = m.end()
    return out


class _Reader:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def _line(self) -> int:
        return self.t[min(self.i, len(self.t) - 1)][2] if self.t else 1

    def _peek(self):
        return self.t[self.i] if self.i < len(self.t) else ("end", None, self._line())

    def _is(self, value) -> bool:
        k, v, _ = self._peek()
        return k == "p" and v == value

    def take(self, value) -> None:
        k, v, line = self._peek()
        if not (k in ("p", "ident") and v == value):
            raise CapsError(f"line {line}: expected {value!r}, found {v if k != 'end' else 'the end of the file'!r}. caps.js is "
                            "module.exports = ({ E, num, bool, text, color }) => ({ roles: [...], mappings: [...], objects: {...} });")
        self.i += 1

    def accept(self, value) -> bool:
        if self._is(value):
            self.i += 1
            return True
        return False

    def ident(self) -> str:
        k, v, line = self._peek()
        if k != "ident":
            raise CapsError(f"line {line}: expected a name, found {v!r}")
        self.i += 1
        return v

    def value(self, scope: dict, depth: int = 0):
        if depth > MAX_DEPTH:
            raise CapsError(f"line {self._line()}: caps.js nests too deeply")
        k, v, line = self._peek()
        if k == "value":
            self.i += 1
            return v
        if k == "p" and v == "{":
            self.i += 1
            obj: dict = {}
            while not self.accept("}"):
                kk, key, kline = self._peek()
                if kk == "ident" or (kk == "value" and isinstance(key, str)):
                    self.i += 1
                elif kk == "value":                          # a number as a key: JavaScript names it as text
                    self.i += 1
                    key = _js_number(key)
                else:
                    raise CapsError(f"line {kline}: expected a property name, found {key!r}")
                if self.accept(":"):
                    obj[key] = self.value(scope, depth + 1)
                elif kk == "ident" and (self._is(",") or self._is("}")):      # { color } is { color: color }
                    obj[key] = self._name(key, scope, kline)
                else:
                    raise CapsError(f"line {kline}: expected ':' after {key!r}")
                if not self.accept(","):
                    self.take("}")
                    break
            return obj
        if k == "p" and v == "[":
            self.i += 1
            arr = []
            while not self.accept("]"):
                arr.append(self.value(scope, depth + 1))
                if not self.accept(","):
                    self.take("]")
                    break
            return arr
        if k == "ident":
            self.i += 1
            if v in ("true", "false", "null"):
                return {"true": True, "false": False, "null": None}[v]
            if v == "E" and "E" in scope and self._is("("):
                self.i += 1
                args = []
                while not self.accept(")"):
                    args.append(self.value(scope, depth + 1))
                    if not self.accept(","):
                        self.take(")")
                        break
                try:
                    return _E(*args)
                except CapsError as e:
                    raise CapsError(f"line {line}: {e}") from None
            return self._name(v, scope, line)
        raise CapsError(f"line {line}: {v if k != 'end' else 'the end of the file'!r} is not a value caps.js may hold")

    @staticmethod
    def _name(name: str, scope: dict, line: int):
        if name in scope and name != "E":
            return scope[name]
        known = ", ".join(n for n in scope if n != "E") or "none"
        raise CapsError(f"line {line}: {name!r} is not a helper caps.js receives (it names: {known}); write the value itself")


def read(text: str) -> dict:
    """The object caps.js gives, read without running it. CapsError says why it cannot be read."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CapsError(f"caps.js is larger than {MAX_BYTES // 1024} KB")
    r = _Reader(_tokens(text))
    for word in ("module", ".", "exports", "=", "(", "{"):
        r.take(word)
    names = []
    while not r.accept("}"):
        k, v, line = r._peek()                                            # noqa: SLF001
        name = r.ident()
        if name not in HELPERS:
            raise CapsError(f"line {line}: caps.js receives only {', '.join(HELPERS)}, not {name!r}")
        names.append(name)
        if not r.accept(","):
            r.take("}")
            break
    for word in (")", "=>", "("):
        r.take(word)
    h = _helpers()
    spec = r.value({n: (h[n] if n != "E" else None) for n in names})
    r.take(")")
    r.accept(";")
    k, v, line = r._peek()                                                # noqa: SLF001
    if k != "end":
        raise CapsError(f"line {line}: caps.js holds something after its object ({v!r}); keep only module.exports = ...")
    if not isinstance(spec, dict):
        raise CapsError("caps.js must give an object: ({ roles: [...], mappings: [...], objects: {...} })")
    return spec


def read_file(path: Path) -> dict:
    try:
        return read(Path(path).read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise CapsError("caps.js is not UTF-8 text") from None


# ---------------------------------------------------------------- capabilities.json, as mk_caps.js writes it

def _truthy(v) -> bool:
    """JavaScript's idea of true: an empty object or array is true; undefined, null, false, 0, NaN and '' are not."""
    if v is _MISSING or v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


def capabilities(spec: dict) -> dict:
    """mk_caps.js: the shared objects the visual asks for (all of them unless it lists some), its own objects, and
    the settings every Relay visual has."""
    get = lambda k: spec.get(k, _MISSING)                                 # noqa: E731
    shared = _shared()
    pick = get("shared") if _truthy(get("shared")) else list(shared)
    if not isinstance(pick, list):
        raise CapsError("shared must be a list of names, for example ['labels', 'legend']")
    objects: dict = {}
    for k in pick:
        if not isinstance(k, str):
            raise CapsError("shared must be a list of names, for example ['labels', 'legend']")
        objects[k] = shared.get(k, _MISSING)
    own = get("objects") if _truthy(get("objects")) else {}
    if not isinstance(own, dict):
        raise CapsError("objects must be an object: { chart: { properties: { ... } } }")
    objects.update(own)
    caps: dict = {"dataRoles": get("roles")}
    if _truthy(get("drilldown")):
        caps["drilldown"] = get("drilldown")
    if _truthy(get("sorting")):
        caps["sorting"] = get("sorting")
    caps.update({"dataViewMappings": get("mappings"), "objects": objects,
                 "tooltips": {"supportedTypes": {"default": True, "canvas": True}, "roles": ["tooltips"]},
                 "supportsHighlight": get("supportsHighlight") is not False, "supportsLandingPage": True,
                 "supportsEmptyDataView": True, "supportsKeyboardFocus": True, "supportsMultiVisualSelection": True})
    extra = get("extra") if _truthy(get("extra")) else {}
    if not isinstance(extra, dict):
        raise CapsError("extra must be an object")
    caps.update(extra)
    caps["privileges"] = []
    return caps


def _js_number(v) -> str:
    """A number as JavaScript writes it (JSON.stringify): 1 not 1.0, 1e-7 not 1e-07, 0.00001 not 1e-05."""
    if isinstance(v, bool):
        raise TypeError(v)
    if isinstance(v, int):
        if abs(v) <= 2 ** 53:
            return str(v)
        v = float(v)                                    # JavaScript has doubles only
    if math.isnan(v) or math.isinf(v):
        return "null"
    if v == 0:
        return "0"
    sign, a = ("-" if v < 0 else ""), abs(v)
    mant, _, exp = repr(a).partition("e")
    whole, _, frac = mant.partition(".")
    digits = (whole + frac).lstrip("0")
    point = len(whole) + int(exp or 0) - (len(whole + frac) - len((whole + frac).lstrip("0")))
    digits = digits.rstrip("0") or "0"
    k, n = len(digits), point
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * -n + digits
    else:
        e = n - 1
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + s


def _string(s: str) -> str:
    """A JSON text as JSON.stringify writes it: Unicode as it is, a lone surrogate escaped."""
    return re.sub(r"[\ud800-\udfff]", lambda m: "\\u%04x" % ord(m.group()), json.dumps(s, ensure_ascii=False))


def _key_order(d: dict) -> list:
    """JavaScript's property order: array-index keys ("0", "1", ...) first, ascending, then the rest as written."""
    idx = sorted((k for k in d if re.fullmatch(r"0|[1-9][0-9]{0,9}", k) and int(k) < 2 ** 32 - 1), key=int)
    return idx + [k for k in d if k not in set(idx)]


def _dump(v, indent: str = "") -> str | None:
    """JSON.stringify(v, null, 2): None for undefined (left out of objects, null in arrays)."""
    if v is _MISSING:
        return None
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return _js_number(v)
    if isinstance(v, str):
        return _string(v)
    inner = indent + "  "
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + ",\n".join(inner + (_dump(x, inner) or "null") for x in v) + "\n" + indent + "]"
    if isinstance(v, dict):
        parts = []
        for k in _key_order(v):
            s = _dump(v[k], inner)
            if s is not None:
                parts.append(inner + _string(str(k)) + ": " + s)
        return "{\n" + ",\n".join(parts) + "\n" + indent + "}" if parts else "{}"
    raise TypeError(type(v).__name__)


def text(spec: dict) -> str:
    """capabilities.json's text for this caps.js object, as mk_caps.js writes it."""
    return _dump(capabilities(spec)) + "\n"


def write(caps_js: Path, out: Path) -> dict:
    """Read caps_js (never run it) and write capabilities.json to out. Returns the capabilities."""
    spec = read_file(caps_js)
    out.write_text(text(spec), encoding="utf-8")
    return capabilities(spec)
