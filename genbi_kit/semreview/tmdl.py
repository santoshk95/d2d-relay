"""TMDL (Tabular Model Definition Language) read into the review's neutral model: what a Power BI project folder
(<name>.SemanticModel/definition/*.tmdl) and the Fabric "get definition" API hand over.

Only what the review needs is read: tables, columns, measures (with their descriptions, the /// lines above them),
calculation groups and their items, calculated tables, and relationships. Anything else (annotations, partitions'
Power Query, roles, cultures, perspectives) is passed over.

The format, as far as it matters here: one object per line, `<type> <name>` with an optional ` = <expression>`;
its properties one level deeper (`name: value`, or a bare flag such as `isHidden`); an expression that spans lines
sits two levels deeper than the object (or between ``` fences); names with spaces or symbols in single quotes ('')
for a quote). Indentation is tabs (four spaces are read as one tab too).
"""
from __future__ import annotations

import re

OBJECT = re.compile(r"^(?P<type>[A-Za-z]+)(?:\s+(?P<name>'(?:[^']|'')*'|[^\s=:']+(?:\.[^\s=:']+)*))?\s*(?:=\s*(?P<expr>.*))?$")
PROPERTY = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9]*)\s*:\s*(?P<value>.*)$")
TYPES = {"model", "database", "table", "column", "measure", "partition", "relationship", "calculationgroup",
         "calculationitem", "hierarchy", "level", "annotation", "expression", "role", "tablepermission", "perspective",
         "perspectivetable", "perspectivecolumn", "perspectivemeasure", "culture", "linguisticmetadata", "variation",
         "datasource", "ref", "kpi", "detailrowsdefinition", "formatstringdefinition", "extendedproperty",
         "calendar", "function", "queryGroup".lower(), "alternateof", "refreshpolicy", "member", "columnpermission",
         "translation", "cultureinfo", "objecttranslation", "calendarcolumngroup", "source", "attributehierarchy"}


def _unquote(name: str | None) -> str:
    if not name:
        return ""
    name = name.strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


def _level(raw: str) -> int:
    tabs = len(raw) - len(raw.lstrip("\t"))
    rest = raw[tabs:]
    spaces = len(rest) - len(rest.lstrip(" "))
    return tabs + spaces // 4


def parse(text: str) -> list[dict]:
    """One TMDL file as a tree of {type, name, expr, props, children, desc, level}."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    roots: list[dict] = []
    stack: list[dict] = []
    desc: list[str] = []
    open_expr: dict | None = None             # the object whose (multi-line) expression is being read
    fence: dict | None = None                 # inside ``` ... ```
    for raw in lines:
        if fence is not None:
            if raw.strip() == "```":
                fence = None
            else:
                fence["_lines"].append(raw)
            continue
        if not raw.strip():
            if open_expr is not None:
                open_expr["_lines"].append("")
            continue
        lvl, content = _level(raw), raw.strip()
        if open_expr is not None:
            if lvl >= open_expr["level"] + 2:
                open_expr["_lines"].append(raw)
                continue
            open_expr = None
        if content.startswith("///"):
            desc.append(content[3:].strip())
            continue
        if content.startswith("//"):
            continue
        while stack and stack[-1]["level"] >= lvl:
            stack.pop()
        parent = stack[-1] if stack else None
        prop = PROPERTY.match(content)
        obj = OBJECT.match(content)
        is_obj = obj is not None and obj.group("type").lower() in TYPES and not (prop and parent is not None
                                                                               and obj.group("name") is None
                                                                               and obj.group("expr") is None)
        if prop and not (is_obj and obj.group("name")) and parent is not None:
            parent["props"][prop.group("key")] = prop.group("value").strip()
            desc = []
            continue
        if not is_obj:
            if parent is not None and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", content):
                parent["props"][content] = "true"                  # a bare flag: isHidden, isActive ...
            elif parent is not None and "=" in content:            # a property with an expression: source = ...
                key, _, value = content.partition("=")
                node = {"type": key.strip(), "name": "", "props": {}, "children": [], "desc": [], "level": lvl,
                        "_lines": [value.strip()] if value.strip() and value.strip() != "```" else []}
                parent["children"].append(node)
                if value.strip() == "```":
                    fence = node
                else:
                    open_expr = node
            desc = []
            continue
        node = {"type": obj.group("type"), "name": _unquote(obj.group("name")), "props": {}, "children": [],
                "desc": desc, "level": lvl, "_lines": []}
        desc = []
        expr = obj.group("expr")
        if expr is not None:
            if expr.strip() == "```":
                fence = node
            else:
                if expr.strip():
                    node["_lines"].append(expr.strip())
                open_expr = node
        (parent["children"] if parent is not None else roots).append(node)
        stack.append(node)
    return [_finish(n) for n in roots]


def _finish(n: dict) -> dict:
    lines = n.pop("_lines", [])
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        base = min((_level(x) for x in lines[1:] if x.strip()), default=0)
        body = [lines[0].strip()] + [_dedent(x, base) for x in lines[1:]]
        n["expr"] = "\n".join(x for x in body if x is not None).strip()
    else:
        n["expr"] = None
    n["children"] = [_finish(c) for c in n["children"]]
    return n


def _dedent(line: str, levels: int) -> str:
    out = line
    for _ in range(levels):
        if out.startswith("\t"):
            out = out[1:]
        elif out.startswith("    "):
            out = out[4:]
    return out.rstrip()


def _col_ref(value: str) -> tuple[str, str]:
    """Sales.DateKey, 'Fact Sales'.'Date Key' -> (table, column)."""
    m = re.match(r"^\s*('(?:[^']|'')*'|[^.']+)\.('(?:[^']|'')*'|.+?)\s*$", value or "")
    if not m:
        return ("", value or "")
    return (_unquote(m.group(1)), _unquote(m.group(2)))


def _flag(props: dict, key: str, default: bool = False) -> bool:
    v = props.get(key)
    if v is None:
        return default
    return str(v).strip().lower() not in ("false", "0", "no")


def model(files: dict[str, str], name: str = "") -> dict:
    """The neutral model from a set of TMDL files (path -> text): tables, measures, relationships."""
    tables, measures, rels, groups = [], [], [], []
    for path, text in sorted(files.items()):
        if not path.lower().endswith(".tmdl"):
            continue
        for node in parse(text):
            t = node["type"].lower()
            if t == "table":
                _table(node, tables, measures, groups)
            elif t == "relationship":
                rels.append(_relationship(node))
            elif t in ("model", "database"):
                for c in node["children"]:
                    if c["type"].lower() == "relationship":
                        rels.append(_relationship(c))
                    elif c["type"].lower() == "table":
                        _table(c, tables, measures, groups)
                name = name or node.get("name") or ""
    return {"name": name, "tables": tables, "measures": measures, "relationships": rels, "calc_groups": groups}


def _table(node: dict, tables: list, measures: list, groups: list) -> None:
    tname = node["name"]
    t = {"name": tname, "hidden": _flag(node["props"], "isHidden"), "description": " ".join(node["desc"]) or None,
         "columns": [], "expression": None}
    for c in node["children"]:
        ct = c["type"].lower()
        if ct == "column":
            p = c["props"]
            t["columns"].append({"name": c["name"], "type": p.get("dataType"), "summarize": p.get("summarizeBy"),
                                 "format": _unquote(p.get("formatString")) or None, "hidden": _flag(p, "isHidden"),
                                 "expression": c.get("expr"), "category": p.get("dataCategory"),
                                 "description": " ".join(c["desc"]) or None})
        elif ct == "measure":
            p = c["props"]
            measures.append({"table": tname, "name": c["name"], "expression": c.get("expr") or "",
                             "format": _unquote(p.get("formatString")) or None, "description": " ".join(c["desc"]) or None,
                             "folder": _unquote(p.get("displayFolder")) or None, "hidden": _flag(p, "isHidden")})
        elif ct == "partition" and (c.get("expr") or "").strip().lower() == "calculated":
            src = next((x for x in c["children"] if x["type"].lower() == "source"), None)
            t["expression"] = src.get("expr") if src else None
        elif ct == "calculationgroup":
            items = [{"name": i["name"], "expression": i.get("expr") or ""} for i in c["children"]
                     if i["type"].lower() == "calculationitem"]
            groups.append({"table": tname, "items": items})
    tables.append(t)


def _relationship(node: dict) -> dict:
    p = node["props"]
    ft, fc = _col_ref(p.get("fromColumn", ""))
    tt, tc = _col_ref(p.get("toColumn", ""))
    return {"from": [ft, fc], "to": [tt, tc], "active": _flag(p, "isActive", True),
            "cross": "both" if str(p.get("crossFilteringBehavior", "")).lower() == "bothdirections" else "single",
            "card": f"{'M' if str(p.get('fromCardinality', 'many')).lower() == 'many' else '1'}:"
                    f"{'M' if str(p.get('toCardinality', 'one')).lower() == 'many' else '1'}"}
