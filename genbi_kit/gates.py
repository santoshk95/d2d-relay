"""Review gates: the checks a report passes before it moves on — to the user's review, then into Power BI.

Every gate is {"id", "name", "standard", "status", "summary", "items": [{"level", "text"}]}. Its status is the worst
item level: fail (blocks — Claude fixes it in the fix rounds; Approve and publishing wait for it), warn (advice) or
pass; skip says why a gate could not run. The file gates read the report's files exactly as they are written:

  power_query   each table's Power Query steps replayed on its CSV header: every column a step uses exists and no
                rename or copy lands on a name that is taken ("The field 'x' already exists in the record")
  data          every CSV value converts to its Power BI type (en-US); keys on the one side of a relationship are
                unique and not blank, and the many side finds them
  pbir_schema   every report file against Microsoft's published PBIR JSON schemas (copies in schemas/)
  coherence     the files agree: .pbip -> report -> semantic model; pages, visuals, fields, custom visuals, themes
  model_rules   the rules of Microsoft's Best Practice Analyzer (Tabular Editor) that apply to a generated model
  report_rules  the report layer and accessibility, as PBI Inspector checks it: titles, alt text, layout, contrast
The display gate (display.py) draws every prototype page in headless Chromium and reads the labels back.
"""
import copy
import csv
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parent / "schemas"
LEVEL = {"fail": 3, "warn": 2, "info": 1}
GATES = {   # id: (name, what it checks) — in the order a report passes them
    "kpis": ("Plan confirmed", "you confirmed the KPIs and their formulas"),
    "definition": ("Report definition", "model, DAX references, visuals and fields (genbi validate)"),
    "prototype": ("Prototype", "every visual's query runs on your data"),
    "custom_visuals": ("Custom visuals", "built from their current code and tested in a browser"),
    "power_query": ("Power Query", "each table's load steps replayed on its CSV"),
    "data": ("Data loads cleanly", "values convert to their types; relationship keys are unique and found"),
    "dax": ("DAX in Power BI's engine", "Power BI Desktop's engine evaluates every measure and visual query"),
    "values": ("Values match the prototype", "Power BI's numbers and titles against the prototype SQL"),
    "pbir_schema": ("Report files", "Microsoft's PBIR JSON schemas"),
    "coherence": ("Report consistency", "pages, visuals, fields, custom visuals and themes all resolve"),
    "model_rules": ("Model best practices", "Microsoft's Best Practice Analyzer rules"),
    "report_rules": ("Report & accessibility", "titles, alt text, layout and contrast (WCAG 2.1)"),
    "display": ("Display check", "every page drawn in a headless browser, labels read back"),
    "approval": ("Approved by you", "you approved this prototype for Power BI"),
}


def fail(text: str) -> dict:
    return {"level": "fail", "text": text}


def warn(text: str) -> dict:
    return {"level": "warn", "text": text}


def info(text: str) -> dict:
    return {"level": "info", "text": text}


def _n(k: int, word: str) -> str:
    if k == 1:
        return f"1 {word}"
    return f"{k:,} " + (word[:-1] + "ies" if word.endswith("y") and word[-2:-1] not in "aeiou" else word + "s")


def gate(gid: str, items=(), ok: str = "", skip: str | None = None) -> dict:
    """One gate result. Plain strings in `items` are failures; `ok` is the summary when nothing failed or warned."""
    name, standard = GATES[gid]
    items = [i if isinstance(i, dict) else fail(str(i)) for i in items]
    if skip is not None:
        return {"id": gid, "name": name, "standard": standard, "status": "skip", "summary": skip, "items": items}
    n = {lv: sum(i["level"] == lv for i in items) for lv in LEVEL}
    status = "fail" if n["fail"] else "warn" if n["warn"] else "pass"
    summary = ", ".join(p for p in (_n(n["fail"], "problem") if n["fail"] else "",
                                    _n(n["warn"], "warning") if n["warn"] else "") if p)
    if not summary:
        summary = ok + (f" · {_n(n['info'], 'note')}" if n["info"] else "")
    return {"id": gid, "name": name, "standard": standard, "status": status, "summary": summary, "items": items}


def ordered(gates: list[dict]) -> list[dict]:
    order = list(GATES)
    return sorted(gates, key=lambda g: order.index(g["id"]) if g["id"] in order else len(order))


def problems(gates: list[dict]) -> list[str]:
    """What blocks: every failed item, named by its gate (this is what Claude gets in a fix round)."""
    return [f"{g['name']}: {i['text']}" for g in gates for i in g["items"] if i["level"] == "fail"]


def failed(gates: list[dict] | None) -> list[dict]:
    return [g for g in gates or [] if g.get("status") == "fail"]


def compact(gates: list[dict]) -> list[dict]:
    """What project.json keeps per version (the items stay in versions/vN/gates.json)."""
    return [{"id": g["id"], "name": g["name"], "status": g["status"], "summary": g["summary"],
             "fails": sum(i["level"] == "fail" for i in g["items"]),
             "warns": sum(i["level"] == "warn" for i in g["items"])} for g in gates]


MARK = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}


def text_report(gates: list[dict], title: str, when: float | None = None) -> str:
    """Review gates.txt: every gate, its result and what it found."""
    counts = {s: sum(g["status"] == s for g in gates) for s in MARK}
    lines = [f"{title} — review gates",
             time.strftime("Checked %Y-%m-%d %H:%M %Z", time.localtime(when or time.time()))
             + f" · {counts['pass']} passed, {counts['warn']} with warnings, {counts['fail']} failed"
             + (f", {counts['skip']} skipped" if counts["skip"] else ""), ""]
    for g in gates:
        lines.append(f"[{MARK[g['status']]}] {g['name']} — {g['summary']}  ({g.get('standard', '')})")
        for i in g["items"]:
            lines.append(f"         {i['level']}: {i['text']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Power Query replay

MTYPES = {"type text": "text", "Int64.Type": "int", "Int32.Type": "int", "Int16.Type": "int", "type number": "number",
          "Currency.Type": "number", "Percentage.Type": "number", "type date": "date", "type datetime": "datetime",
          "type datetimezone": "datetime", "type logical": "bool", "type time": "time", "type any": "any"}
MODEL_M = {"int64": {"int"}, "double": {"number"}, "decimal": {"number"}, "string": {"text"},
           "dateTime": {"date", "datetime"}, "boolean": {"bool"}}


class _Stop(Exception):
    pass


def _scan(s: str, sep: str, maxsplit: int = -1) -> list[str]:
    """Split M text at top-level `sep` (outside strings, #"quoted names", brackets and comments)."""
    parts, depth, start, i, n = [], 0, 0, 0, len(s)
    while i < n:
        c = s[i]
        if c == '"':
            i += 1
            while i < n and not (s[i] == '"' and s[i + 1:i + 2] != '"'):
                i += 2 if s[i] == '"' else 1
            i += 1
            continue
        if s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == sep and depth == 0 and maxsplit != 0 and s[i + 1:i + 2] != ">":     # not =>
            parts.append(s[start:i].strip())
            start, maxsplit = i + 1, maxsplit - 1
        i += 1
    parts.append(s[start:].strip())
    return [p for p in parts if p]


def _ident(s: str) -> str:
    m = re.fullmatch(r'\s*#"((?:[^"]|"")*)"\s*', s)
    return m.group(1).replace('""', '"') if m else s.strip()


def _text(s: str) -> str | None:
    m = re.fullmatch(r'\s*"((?:[^"]|"")*)"\s*', s)
    return m.group(1).replace('""', '"') if m else None


def _items(s: str) -> list[str]:
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise _Stop(f"expected a list, got {s[:40]}")
    return _scan(s[1:-1], ",")


def _texts(s: str) -> list[str]:
    out = [_text(x) for x in _items(s)]
    if any(x is None for x in out):
        raise _Stop("a column list that is not plain text")
    return out


def _call(s: str) -> tuple[str | None, list[str]]:
    m = re.fullmatch(r"\s*([A-Za-z][\w.]*)\s*\((.*)\)\s*", s, re.S)
    return (m.group(1), _scan(m.group(2), ",")) if m else (None, [])


def _record(s: str) -> dict:
    s = s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return {}
    out = {}
    for kv in _scan(s[1:-1], ","):
        k, _, v = kv.partition("=")
        out[k.strip()] = v.strip()
    return out


def _let(text: str):
    m = re.fullmatch(r"\s*let\b(.*)\bin\b\s*(.+?)\s*", text, re.S)
    if not m:
        return None
    steps = []
    for step in _scan(m.group(1), ","):
        parts = _scan(step, "=", 1)
        if len(parts) != 2:
            return None
        steps.append((_ident(parts[0]), parts[1]))
    return steps, _ident(m.group(2))


def replay(query: str, data_dir: Path, table: str) -> dict:
    """Replay one Power Query on column names, with the step functions the report builder writes (and the date
    table's). Returns {"columns", "origin": {column: csv column}, "types", "file", "header", "problems"}, or
    {"unknown": why} for a query it cannot follow (custom M)."""
    parsed = _let(query)
    if parsed is None:
        return {"unknown": "not a let … in query"}
    steps, result = parsed
    env: dict = {}
    out: dict = {"problems": [], "file": None, "header": None, "delimiter": ","}

    def stop(text: str):
        out["problems"].append(fail(f"{table}: {text}"))
        raise _Stop()

    def table_arg(arg: str) -> dict:
        t = evaluate(arg) if _call(arg)[0] else env.get(_ident(arg))
        if not isinstance(t, dict):
            raise _Stop(f"{arg[:40]} is not a table step")
        return {"cols": list(t["cols"]), "origin": dict(t["origin"]), "types": dict(t["types"]), "header": t.get("header")}

    def need(t: dict, col: str, step: str):
        if col not in t["cols"]:
            have = ", ".join(f'"{c}"' for c in t["cols"][:12]) + (" …" if len(t["cols"]) > 12 else "")
            stop(f'{step} uses column "{col}", which is not there (columns at that step: {have}) — the refresh stops '
                 f'with "The column \'{col}\' of the table wasn\'t found"')

    def evaluate(expr: str):
        fn, args = _call(expr)
        if fn is None or not fn.startswith(("Table.", "Csv.")):
            return "scalar"
        if fn == "Csv.Document":
            m = re.search(r'"((?:[^"]|"")*\.(?:csv|txt))"', args[0] if args else "", re.I)
            if not m:
                raise _Stop("Csv.Document without a file name")
            opts = _record(args[1]) if len(args) > 1 else {}
            delim = _text(opts.get("Delimiter", '","')) or ","
            name = m.group(1).replace('""', '"')
            path = data_dir / name
            if not path.is_file():
                stop(f'{name} is not in the data folder — the refresh stops ("could not find file")')
            with open(path, encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f, delimiter=delim), [])
            if "Columns" in opts and opts["Columns"].isdigit():
                header = (header + [""] * int(opts["Columns"]))[:int(opts["Columns"])]
            out.update(file=name, header=header, delimiter=delim)
            cols = [f"Column{i}" for i in range(1, len(header) + 1)]
            return {"cols": cols, "origin": {c: None for c in cols}, "types": {}, "header": header}
        if fn == "Table.FromList":
            cols = _texts(args[2]) if len(args) > 2 else ["Column1"]
            return {"cols": cols, "origin": {c: None for c in cols}, "types": {}}
        t = table_arg(args[0]) if args else None
        if t is None:
            raise _Stop(fn)
        if fn == "Table.PromoteHeaders":
            if t.get("header") is None:
                raise _Stop("headers promoted from a step that is not the CSV")
            names = []
            for i, h in enumerate(t["header"]):
                nm = h if h != "" else f"Column{i + 1}"
                if nm in names:
                    k = 1
                    while f"{nm}_{k}" in names:
                        k += 1
                    out["problems"].append(warn(f'{table}: {out["file"]} has two columns named "{nm}" — Power Query '
                                                f'renames the second one to "{nm}_{k}"'))
                    nm = f"{nm}_{k}"
                names.append(nm)
            return {"cols": names, "origin": {nm: t["header"][i] for i, nm in enumerate(names)}, "types": {}}
        if fn in ("Table.SelectColumns", "Table.RemoveColumns", "Table.ReorderColumns"):
            cols = _texts(args[1])
            if "MissingField.Ignore" not in "".join(args[2:]) and "MissingField.UseNull" not in "".join(args[2:]):
                for c in cols:
                    need(t, c, fn)
            if fn == "Table.SelectColumns":
                dup = sorted({c for c in cols if cols.count(c) > 1})
                if dup:
                    stop(f'Table.SelectColumns lists "{dup[0]}" twice — "The field \'{dup[0]}\' already exists in the record"')
                t["cols"] = cols if "MissingField.UseNull" in "".join(args[2:]) else [c for c in cols if c in t["cols"]]
            elif fn == "Table.RemoveColumns":
                t["cols"] = [c for c in t["cols"] if c not in cols]
            return t
        if fn == "Table.RenameColumns":
            renames = {}
            for pair in _items(args[1]):
                a, b = _texts(pair)
                if "MissingField.Ignore" not in "".join(args[2:]):
                    need(t, a, fn)
                renames[a] = b
            new = [renames.get(c, c) for c in t["cols"]]
            for c in new:
                if new.count(c) > 1:
                    src = next((a for a, b in renames.items() if b == c), c)
                    stop(f'renaming "{src}" to "{c}" clashes with another column named "{c}" — the refresh stops with '
                         f'"The field \'{c}\' already exists in the record"')
            t["origin"] = {renames.get(c, c): t["origin"].get(c) for c in t["cols"]}
            t["types"] = {renames.get(c, c): v for c, v in t["types"].items()}
            t["cols"] = new
            return t
        if fn in ("Table.DuplicateColumn", "Table.AddColumn"):
            if fn == "Table.DuplicateColumn":
                src, new = _text(args[1]), _text(args[2])
                need(t, src, fn)
            else:
                src, new = None, _text(args[1])
            if new is None:
                raise _Stop(f"{fn} with a computed name")
            if new in t["cols"]:
                stop(f'{fn} adds "{new}", but that column already exists — "The field \'{new}\' already exists in the record"')
            t["cols"].append(new)
            t["origin"][new] = t["origin"].get(src) if src else None
            typ = args[3].strip() if fn == "Table.AddColumn" and len(args) > 3 else None
            t["types"][new] = MTYPES.get(typ, "any") if typ else t["types"].get(src)
            return t
        if fn == "Table.ReplaceValue":
            for c in _texts(args[4]) if len(args) > 4 and args[4].strip().startswith("{") else []:
                need(t, c, fn)
            return t
        if fn == "Table.TransformColumnTypes":
            seen = set()
            for pair in _items(args[1]):
                parts = _items(pair)
                c, typ = _text(parts[0]), parts[1].strip()
                if c is None:
                    raise _Stop("a typed column with a computed name")
                need(t, c, fn)
                if c in seen:
                    stop(f'Table.TransformColumnTypes types "{c}" twice — "The field \'{c}\' already exists in the record"')
                seen.add(c)
                t["types"][c] = MTYPES.get(typ, "any")
            out["culture"] = _text(args[2]) if len(args) > 2 else None
            return t
        raise _Stop(fn)

    try:
        for name, expr in steps:
            env[name] = evaluate(expr)
        final = env.get(result)
        if not isinstance(final, dict):
            return {"unknown": f"the result {result} is not a table step"}
    except _Stop as e:
        if any(p["level"] == "fail" for p in out["problems"]):
            return {**out, "columns": None, "origin": {}, "types": {}}
        return {"unknown": str(e) or "a step it cannot follow"}
    return {**out, "columns": final["cols"], "origin": final["origin"], "types": final["types"]}


def _model(sdir: Path) -> dict:
    return json.loads((sdir / "model.bim").read_text(encoding="utf-8"))["model"]


def _expr(obj: dict) -> str:
    e = obj.get("expression", "")
    return "\n".join(e) if isinstance(e, list) else str(e)


def power_query(sdir: Path, data_dir: Path) -> tuple[dict, dict]:
    """(gate, {table: replay}) for every Power Query table of the semantic model."""
    items, tables = [], {}
    for t in _model(sdir).get("tables") or []:
        src = ((t.get("partitions") or [{}])[0].get("source") or {})
        if src.get("type") != "m":
            continue
        r = replay(_expr(src), data_dir, t["name"])
        native = re.search(r"\b(Snowflake\.Databases|GoogleBigQuery\.Database|Sql\.Database|AmazonRedshift\.Database|"
                           r"AmazonAthena\.Databases|Parquet\.Document)\b", _expr(src))
        if native:
            items.append(info(f"{t['name']}: warehouse table ({native.group(1)}) — Power BI refreshes it from the "
                              f"warehouse; its keys and values are checked on the extract"))
            continue
        if r.get("unknown"):
            items.append(info(f"{t['name']}: custom Power Query — not replayed ({r['unknown']})"))
            continue
        items += r["problems"]
        if r["columns"] is None:
            continue
        tables[t["name"]] = r
        for c in t.get("columns") or []:
            if c.get("type") in ("calculated", "calculatedTableColumn"):
                continue
            col = c.get("sourceColumn") or c["name"]
            if col not in r["columns"]:
                items.append(fail(f"{t['name']}[{c['name']}]: the query has no column \"{col}\" — the refresh stops with "
                                  f"\"The column '{col}' of the table wasn't found\""))
                continue
            mt = r["types"].get(col)
            if mt and mt != "any" and c.get("dataType") in MODEL_M and mt not in MODEL_M[c["dataType"]]:
                items.append(warn(f"{t['name']}[{c['name']}]: Power Query types it as {mt}, the model as {c['dataType']}"))
    n = len(tables)
    return gate("power_query", items, ok=f"{_n(n, 'table')} replayed on their CSVs — every step finds its columns"), tables


# ---------------------------------------------------------------- data

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
                "%B %d, %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p"]
TYPE_WORD = {"int": "whole numbers", "number": "numbers", "date": "dates", "datetime": "dates", "bool": "true/false"}


def _sql_lit(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _examples(xs) -> str:
    return ", ".join(repr(x) for x in (xs or [])[:3])


def data(tables: dict, data_dir: Path, sdir: Path, con=None) -> dict:
    """Every typed CSV value converts the way Power Query converts it (en-US), and every relationship's keys hold up:
    unique and not blank on the one side, found from the many side."""
    import duckdb
    items, checked = [], 0
    db = duckdb.connect()
    for tname, r in tables.items():
        if not r.get("file"):
            continue
        hdr = r["header"]
        names = [f"c{i}" for i in range(len(hdr))]
        src = (f"read_csv({_sql_lit(data_dir / r['file'])}, header = true, all_varchar = true, names = {names!r}, "
               f"delim = {_sql_lit(r['delimiter'])}, quote = '\"', escape = '\"', null_padding = true)")
        checks = []
        for col, csv_col in r["origin"].items():
            mt = r["types"].get(col)
            if mt not in TYPE_WORD or csv_col not in hdr:
                continue
            v = f"trim(c{hdr.index(csv_col)})"
            num = f"try_cast(replace(replace({v}, ',', ''), '%', '') AS DOUBLE)"
            if mt in ("int", "number"):
                bad = f"{v} <> '' AND {num} IS NULL"
            elif mt in ("date", "datetime"):
                bad = f"{v} <> '' AND try_strptime({v}, {DATE_FORMATS!r}) IS NULL"
            else:
                bad = f"{v} <> '' AND lower({v}) NOT IN ('true', 'false')"
            checks.append((col, mt, f"count(*) FILTER (WHERE {bad})", f"list_slice(list(DISTINCT {v}) FILTER (WHERE {bad}), 1, 3)"))
            if mt == "int":
                frac = f"{num} IS NOT NULL AND {num} <> round({num})"
                checks.append((col, "round", f"count(*) FILTER (WHERE {frac})",
                               f"list_slice(list(DISTINCT {v}) FILTER (WHERE {frac}), 1, 3)"))
        if not checks:
            continue
        try:
            row = db.execute(f"SELECT {', '.join(a + ', ' + b for _, _, a, b in checks)} FROM {src}").fetchone()
        except duckdb.Error as e:
            items.append(warn(f"{tname}: could not read {r['file']} to check its values ({str(e).splitlines()[0][:160]})"))
            continue
        checked += 1
        for k, (col, mt, _, _) in enumerate(checks):
            n, ex = row[2 * k], row[2 * k + 1]
            if not n:
                continue
            if mt == "round":
                items.append(warn(f"{tname}[{col}]: {_n(n, 'value')} in {r['file']} have decimals ({_examples(ex)}) but the "
                                  f"column is a whole number — Power BI rounds them"))
            else:
                items.append(warn(f"{tname}[{col}]: {_n(n, 'value')} in {r['file']} are not {TYPE_WORD[mt]} "
                                  f"({_examples(ex)}) — Power BI loads them as errors, shown as blanks"))
    rels = _model(sdir).get("relationships") or []
    if con is not None:
        for rel in rels:
            ft, fc, tt, tc = rel["fromTable"], rel["fromColumn"], rel["toTable"], rel["toColumn"]
            try:
                dup, dup_ex = con.execute(
                    f"SELECT count(*), list_slice(list(k), 1, 3) FROM (SELECT {_q(tc)} AS k FROM {_q(tt)} "
                    f"WHERE {_q(tc)} IS NOT NULL GROUP BY 1 HAVING count(*) > 1)").fetchone()
                blank = con.execute(f"SELECT count(*) FROM {_q(tt)} WHERE {_q(tc)} IS NULL").fetchone()[0]
                orphan, orphan_ex = con.execute(
                    f"SELECT count(*), list_slice(list(DISTINCT f.{_q(fc)}), 1, 3) FROM {_q(ft)} f WHERE f.{_q(fc)} IS NOT "
                    f"NULL AND NOT EXISTS (SELECT 1 FROM {_q(tt)} u WHERE u.{_q(tc)} = f.{_q(fc)})").fetchone()
            except Exception:  # noqa: BLE001 - a table the prototype data has no view for (DAX tables)
                continue
            if dup:
                items.append(fail(f"{tt}[{tc}] is the one side of the relationship from {ft}[{fc}] but has {_n(dup, 'duplicate value')} "
                                  f"({_examples(dup_ex)}) — the refresh stops: \"contains a duplicate value … not allowed for "
                                  f"columns on the one side of a many-to-one relationship\""))
            if blank:
                items.append(warn(f"{tt}[{tc}] (one side of the relationship from {ft}[{fc}]) has {_n(blank, 'blank key')} — "
                                  f"Power BI may refuse the refresh (\"contains blank values\")"))
            if orphan:
                items.append(warn(f"{_n(orphan, 'value')} of {ft}[{fc}] are not in {tt}[{tc}] ({_examples(orphan_ex)}) — those "
                                  f"rows show as (Blank) in visuals that use {tt}"))
    return gate("data", items, ok=f"{_n(checked, 'CSV')} scanned: every value converts; {_n(len(rels), 'relationship')} "
                                  f"with unique, matching keys")


# ---------------------------------------------------------------- report files: Microsoft's PBIR schemas

def _schema(url: str) -> dict:
    f = SCHEMAS / url.split("/json-schemas/")[-1].replace("/", "_")
    if not f.is_file():
        raise LookupError(url)
    return json.loads(f.read_text(encoding="utf-8"))


def pbir_schema(rdir: Path) -> dict:
    try:
        from jsonschema import Draft7Validator, validators
        from referencing import Registry, Resource
    except ImportError:
        return gate("pbir_schema", skip="the jsonschema package is not installed")
    registry = Registry(retrieve=lambda uri: Resource.from_contents(_schema(uri)))
    items, checked, cache = [], 0, {}
    for f in [rdir / "definition.pbir"] + sorted((rdir / "definition").rglob("*.json")):
        rel = f.relative_to(rdir).as_posix()
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            items.append(fail(f"{rel}: not valid JSON ({e})"))
            continue
        url = doc.get("$schema") if isinstance(doc, dict) else None
        if not url:
            items.append(warn(f"{rel}: has no $schema, so it was not checked"))
            continue
        try:
            if url not in cache:
                schema = _schema(url)
                cache[url] = validators.validator_for(schema, default=Draft7Validator)(schema, registry=registry)
            errors = sorted(cache[url].iter_errors(doc), key=lambda e: list(e.absolute_path))
        except Exception as e:  # noqa: BLE001 - a schema (part) with no offline copy
            items.append(warn(f"{rel}: Microsoft's schema is not available offline, so it was not checked ({e})"))
            continue
        checked += 1
        for e in errors[:5]:
            where = "/".join(map(str, e.absolute_path)) or "(top)"
            items.append(fail(f"{rel}: {where}: {e.message[:240]}"))
    return gate("pbir_schema", items, ok=f"{_n(checked, 'file')} match Microsoft's PBIR schemas")


# ---------------------------------------------------------------- project consistency

BUILTIN = {"slicer", "textbox", "pageNavigator", "bookmarkNavigator", "tableEx", "pivotTable", "card", "cardVisual",
           "multiRowCard", "kpi", "gauge", "lineChart", "areaChart", "stackedAreaChart", "barChart", "columnChart",
           "clusteredBarChart", "clusteredColumnChart", "hundredPercentStackedBarChart",
           "hundredPercentStackedColumnChart", "lineClusteredColumnComboChart", "lineStackedColumnComboChart",
           "ribbonChart", "waterfallChart", "funnel", "pieChart", "donutChart", "treemap", "scatterChart", "map",
           "filledMap", "shapeMap", "azureMap", "shape", "basicShape", "image", "actionButton", "advancedSlicerVisual",
           "listSlicer", "textSlicer", "decompositionTreeVisual", "keyDriversVisual", "qnaVisual", "scriptVisual",
           "pythonVisual", "aiNarratives", "hundredPercentStackedAreaChart"}
BUILTIN |= set(__import__("genbi_kit.stock", fromlist=["SPECS"]).SPECS)      # every Power BI visual Relay places (pbi.*)


def refs(o, aliases: dict | None = None) -> list[tuple[str, str, str]]:
    """(Column|Measure, table, name) of every field a PBIR object uses (filters resolve their From aliases)."""
    out = []
    if isinstance(o, dict):
        if isinstance(o.get("From"), list):
            aliases = {**(aliases or {}), **{f.get("Name"): f.get("Entity") for f in o["From"] if isinstance(f, dict)}}
        for kind in ("Column", "Measure"):
            x = o.get(kind)
            if isinstance(x, dict) and "Property" in x:
                sr = (x.get("Expression") or {}).get("SourceRef") or {}
                out.append((kind, sr.get("Entity") or (aliases or {}).get(sr.get("Source")), x["Property"]))
        for v in o.values():
            out += refs(v, aliases)
    elif isinstance(o, list):
        for v in o:
            out += refs(v, aliases)
    return out


def _load(path: Path, items: list, root: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        items.append(fail(f"{path.relative_to(root).as_posix()}: cannot be read ({e})"))
        return None


def coherence(out: Path, data_dir: Path | None = None) -> dict:
    """The files agree with each other: what Power BI Desktop resolves when it opens the project."""
    items: list = []
    pbips = sorted(out.glob("*.pbip"))
    if len(pbips) != 1:
        return gate("coherence", [fail(f"the folder should hold one report, it holds {len(pbips)}")])
    pbip = _load(pbips[0], items, out) or {}
    arts = [((a or {}).get("report") or {}).get("path") for a in pbip.get("artifacts") or []]
    rdir = out / arts[0] if arts and arts[0] else None
    if rdir is None or not (rdir / "definition.pbir").is_file():
        return gate("coherence", items + [fail(f"the report {pbips[0].stem} points to a report folder without definition.pbir")])
    pbir = _load(rdir / "definition.pbir", items, out) or {}
    path = ((pbir.get("datasetReference") or {}).get("byPath") or {}).get("path")
    sdir = (rdir / path).resolve() if path else None
    if sdir is None or not (sdir / "definition.pbism").is_file() or not (sdir / "model.bim").is_file():
        return gate("coherence", items + [fail(f"definition.pbir points to {path!r}, which is not a semantic model folder "
                                               f"with definition.pbism and model.bim")])
    model = (_load(sdir / "model.bim", items, out) or {}).get("model") or {}

    # the semantic model on its own
    tables = {t["name"]: t for t in model.get("tables") or []}
    cols = {t: {c["name"]: c for c in tv.get("columns") or []} for t, tv in tables.items()}
    measures: dict[str, str] = {}
    lower: dict[str, str] = {}
    for t in tables:
        if t.lower() in lower:
            items.append(fail(f"two tables named {lower[t.lower()]!r} and {t!r} (Power BI ignores case)"))
        lower[t.lower()] = t
        seen: dict[str, str] = {}
        for c in cols[t]:
            if c.lower() in seen:
                items.append(fail(f"{t} has two columns named {seen[c.lower()]!r} and {c!r}"))
            seen[c.lower()] = c
            sb = cols[t][c].get("sortByColumn")
            if sb and sb not in cols[t]:
                items.append(fail(f"{t}[{c}] sorts by {sb!r}, which is not a column of {t}"))
        for m in tables[t].get("measures") or []:
            if m["name"].lower() in {k.lower() for k in measures}:
                items.append(fail(f"two measures named [{m['name']}]"))
            if m["name"].lower() in seen:
                items.append(fail(f"measure [{m['name']}] has the name of a column of {t}"))
            measures[m["name"]] = t
    params = {e.get("name") for e in model.get("expressions") or []}
    for r in model.get("relationships") or []:
        for t, c in ((r.get("fromTable"), r.get("fromColumn")), (r.get("toTable"), r.get("toColumn"))):
            if t not in cols or c not in cols[t]:
                items.append(fail(f"relationship {r.get('fromTable')}[{r.get('fromColumn')}] -> {r.get('toTable')}"
                                  f"[{r.get('toColumn')}] uses {t}[{c}], which does not exist"))
    queries = set(params)
    for t, tv in tables.items():
        src = ((tv.get("partitions") or [{}])[0].get("source") or {})
        if src.get("type") != "m":
            continue
        queries.add(t)
        text = _expr(src)
        for p in re.findall(r"File\.Contents\(\s*([A-Za-z_]\w*)\s*&", text):
            if p not in params:
                items.append(fail(f"{t}: its query uses the parameter {p}, which the model does not define"))
        if data_dir is not None:
            for f in re.findall(r'File\.Contents\([^)]*?"((?:[^"]|"")+)"\s*\)', text):
                if not (data_dir / f.replace('""', '"')).is_file():
                    items.append(fail(f"{t}: reads {f}, which is not in the data folder"))
    order = next((a.get("value") for a in model.get("annotations") or [] if a.get("name") == "PBI_QueryOrder"), None)
    for q in json.loads(order) if order else []:
        if q not in queries:
            items.append(warn(f"the query order lists {q!r}, which is not a query of the model"))

    # the report
    report = _load(rdir / "definition" / "report.json", items, out) or {}
    packages = {p.get("name"): p for p in report.get("resourcePackages") or []}
    custom = {n for n, p in packages.items() if p.get("type") == "CustomVisual"}
    for pname, p in packages.items():
        for it in p.get("items") or []:
            if p.get("type") == "CustomVisual":
                f = rdir / "CustomVisuals" / pname / "resources" / it.get("path", "")
                if not (rdir / "CustomVisuals" / pname / "package.json").is_file() or not f.is_file():
                    items.append(fail(f"custom visual {pname}: its files are missing from CustomVisuals/{pname}"))
            elif not (rdir / "StaticResources" / pname / it.get("path", "")).is_file():
                items.append(fail(f"{pname} item {it.get('name')} points to a missing file StaticResources/{pname}/{it.get('path')}"))
    themes = report.get("themeCollection") or {}
    for key in ("baseTheme", "customTheme"):
        th = themes.get(key)
        if th and not any(it.get("name") == th.get("name") for it in (packages.get(th.get("type")) or {}).get("items") or []):
            items.append(fail(f"the {key} {th.get('name')!r} is not among the report's {th.get('type')}"))
    pages_meta = _load(rdir / "definition" / "pages" / "pages.json", items, out) or {}
    page_order = pages_meta.get("pageOrder") or []
    folders = sorted(p.name for p in (rdir / "definition" / "pages").iterdir() if p.is_dir()) \
        if (rdir / "definition" / "pages").is_dir() else []
    for p in sorted(set(page_order) ^ set(folders)):
        items.append(fail(f"page {p} is {'listed in pages.json but has no folder' if p in page_order else 'not listed in pages.json'}"))
    if pages_meta.get("activePageName") not in page_order:
        items.append(fail(f"the active page {pages_meta.get('activePageName')!r} is not one of the pages"))
    used_custom, n_vis, n_fields = set(), 0, 0
    for pid in folders:
        pdir = rdir / "definition" / "pages" / pid
        page = _load(pdir / "page.json", items, out) or {}
        if page.get("name") != pid:
            items.append(fail(f"page folder {pid} holds page {page.get('name')!r}"))
        for vdir in sorted((pdir / "visuals").iterdir()) if (pdir / "visuals").is_dir() else []:
            v = _load(vdir / "visual.json", items, out) or {}
            n_vis += 1
            where = f"{page.get('displayName', pid)} / {vdir.name}"
            if v.get("name") != vdir.name:
                items.append(fail(f"{where}: the folder holds visual {v.get('name')!r}"))
            vt = (v.get("visual") or {}).get("visualType")
            if vt in custom:
                used_custom.add(vt)
            elif vt and vt not in BUILTIN:
                items.append(fail(f"{where}: visual type {vt} is neither a Power BI visual nor a custom visual of the report"))
            for kind, t, prop in refs(v) + refs(page.get("filterConfig")):
                n_fields += 1
                if t not in tables:
                    items.append(fail(f"{where}: uses table {t!r}, which is not in the model"))
                elif kind == "Column" and prop not in cols[t]:
                    items.append(fail(f"{where}: uses column {t}[{prop}], which is not in the model"))
                elif kind == "Measure" and measures.get(prop) != t:
                    items.append(fail(f"{where}: uses measure {t}[{prop}], which is not in the model"
                                      + (f" (it lives in {measures[prop]})" if prop in measures else "")))
    for kind, t, prop in refs(report.get("filterConfig")):
        if t not in tables or (kind == "Column" and prop not in cols[t]) or (kind == "Measure" and prop not in measures):
            items.append(fail(f"a report filter uses {t}[{prop}], which is not in the model"))
    for g in sorted(custom - used_custom):
        items.append(info(f"custom visual {g} is packaged but not used on any page"))
    return gate("coherence", items, ok=f"{_n(len(folders), 'page')}, {_n(n_vis, 'visual')} and {_n(n_fields, 'field reference')} "
                                       f"resolve against {_n(len(tables), 'table')} and {_n(len(measures), 'measure')}")


# ---------------------------------------------------------------- model best practices (Microsoft BPA rules)

MONTHS = {m.lower() for m in ("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec January February March April June July "
                              "August September October November December Mon Tue Wed Thu Fri Sat Sun Monday Tuesday "
                              "Wednesday Thursday Friday Saturday Sunday").split()}


def dax_code(expr: str) -> str:
    """DAX without string literals, comments, quoted table names and [names] — for operator and function rules."""
    s = re.sub(r'"(?:[^"]|"")*"', '""', expr)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"(//|--)[^\n]*", " ", s)
    s = re.sub(r"'(?:[^']|'')*'", "T", s)
    return re.sub(r"\[[^\]]*\]", "[c]", s)


def _text_measure(expr: str) -> bool:
    """A measure that returns text: concatenation, FORMAT, … or an IF / SWITCH whose results are string literals
    (status words, or the hex colors of format-by-field-value measures)."""
    if re.search(r'&\s*"|"\s*&|\bFORMAT\s*\(|\bCONCATENATEX\s*\(|\bUNICHAR\s*\(', expr, re.I):
        return True
    return bool(re.search(r'\b(IF|SWITCH)\s*\(', expr, re.I) and re.search(r',\s*"[^"]*"\s*[,)]', expr)
                and not re.search(r'\b(CONTAINSSTRING|CONTAINSSTRINGEXACT|SEARCH|FIND|PATHCONTAINS|LOOKUPVALUE)\s*\(', expr, re.I))


def _list(names: list[str], k: int = 6) -> str:
    return ", ".join(names[:k]) + (f" and {len(names) - k} more" if len(names) > k else "")


def model_rules(sdir: Path, rdir: Path | None = None, con=None, text_measures=()) -> dict:
    """Microsoft's Best Practice Analyzer rules (as Tabular Editor runs them) that apply to a generated model.
    `text_measures`: measures Power BI's engine returned text for (titles, labels, statuses: no format string)."""
    model = _model(sdir)
    tables = model.get("tables") or []
    rels = model.get("relationships") or []
    items = []
    measures = [(t["name"], m) for t in tables for m in t.get("measures") or []]
    exprs = [(f"[{m['name']}]", _expr(m)) for _, m in measures]
    exprs += [(f"{t['name']}[{c['name']}]", _expr(c)) for t in tables for c in t.get("columns") or []
              if c.get("type") == "calculated"]
    divide, iferror, intersect = [], [], []
    for owner, e in exprs:
        code = dax_code(e)
        if re.search(r"(?<![/*])/(?![/*])", code):
            divide.append(owner)
        if re.search(r"\b(IFERROR|ISERROR)\s*\(", code, re.I):
            iferror.append(owner)
        if re.search(r"\bINTERSECT\s*\(", code, re.I):
            intersect.append(owner)
    if divide:
        items.append(warn(f"Use DIVIDE for division: {_list(divide)} divide with '/' — a blank or zero denominator then "
                          f"shows an error or ∞ instead of a blank (BPA: Use the DIVIDE function for division)"))
    if iferror:
        items.append(warn(f"Avoid IFERROR / ISERROR: {_list(iferror)} — they slow every query (BPA: Avoid using the IFERROR function)"))
    if intersect:
        items.append(info(f"{_list(intersect)} use INTERSECT for a virtual relationship — TREATAS is faster (BPA)"))
    unformatted = [f"[{m['name']}]" for _, m in measures if not m.get("formatString") and m["name"] not in text_measures
                   and not _text_measure(_expr(m))]
    if unformatted:
        items.append(warn(f"Give measures a format string: {_list(unformatted)} — visuals show raw numbers "
                          f"(BPA: Provide format string for measures)"))
    seen: dict[str, str] = {}
    for _, m in measures:
        key = re.sub(r"\s+", "", _expr(m)).lower()
        if key in seen:
            items.append(info(f"[{m['name']}] has the same DAX as [{seen[key]}] (BPA: No two measures should have the same definition)"))
        seen.setdefault(key, m["name"])
    col_of = {(t["name"], c["name"]): c for t in tables for c in t.get("columns") or []}
    for r in rels:
        a, b = col_of.get((r["fromTable"], r["fromColumn"])), col_of.get((r["toTable"], r["toColumn"]))
        if a and b and a.get("dataType") != b.get("dataType"):
            items.append(fail(f"relationship {r['fromTable']}[{r['fromColumn']}] ({a.get('dataType')}) -> {r['toTable']}"
                              f"[{r['toColumn']}] ({b.get('dataType')}) joins different data types — Power BI refuses it"))
        if r.get("crossFilteringBehavior") == "bothDirections":
            items.append(info(f"relationship {r['fromTable']} -> {r['toTable']} filters both ways — slower and can be "
                              f"ambiguous (BPA: Avoid excessive bi-directional relationships)"))
        if r.get("fromCardinality") == "many" and r.get("toCardinality") == "many":
            items.append(warn(f"relationship {r['fromTable']} -> {r['toTable']} is many-to-many (BPA: Avoid many-to-many relationships)"))
    fks = sorted(f"{t}[{c}]" for t, c in {(r["fromTable"], r["fromColumn"]) for r in rels}
                 if not (col_of.get((t, c)) or {}).get("isHidden"))
    if fks:
        items.append(info(f"Hide foreign keys: {_list(fks)} — users should filter by the related table (BPA: Hide foreign keys)"))
    ann = {a.get("name"): a.get("value") for a in model.get("annotations") or []}
    if ann.get("__PBI_TimeIntelligenceEnabled") != "0":
        items.append(warn("Auto date/time is on — Power BI adds a hidden date table for every date column "
                          "(BPA: Remove auto-date table)"))
    related = {r["fromTable"] for r in rels} | {r["toTable"] for r in rels}
    date_keys = [r for r in rels if (col_of.get((r["toTable"], r["toColumn"])) or {}).get("dataType") == "dateTime"]
    if date_keys and not any(t.get("dataCategory") == "Time" for t in tables):
        items.append(info("No table is marked as the date table (BPA: Date/calendar tables should be marked as a date table)"))
    for t in tables:
        src = ((t.get("partitions") or [{}])[0].get("source") or {})
        if t["name"] not in related and not t.get("measures") and src.get("type") == "m":
            items.append(warn(f"{t['name']} has no relationship — slicers and the other tables do not filter it "
                              f"(BPA: Ensure tables have relationships)"))
        for c in t.get("columns") or []:
            for name in (c["name"],):
                if re.search(r"[\x00-\x1f]", name) or name != name.strip():
                    items.append(warn(f"{t['name']}[{name!r}] has a line break, tab or leading/trailing space in its name "
                                      f"(BPA: Object names must not contain special characters)"))
            if c.get("dataType") == "string" and not c.get("sortByColumn") and con is not None \
                    and re.search(r"month|weekday|day", c["name"], re.I):
                try:
                    vals = [str(x[0]).lower() for x in con.execute(
                        f"SELECT DISTINCT {_q(c['name'])} FROM {_q(t['name'])} WHERE {_q(c['name'])} IS NOT NULL LIMIT 40").fetchall()]
                except Exception:  # noqa: BLE001 - no prototype view for this table
                    vals = []
                if vals and all(v in MONTHS for v in vals):
                    items.append(warn(f"{t['name']}[{c['name']}] holds month or day names but is not sorted by a number "
                                      f"column — visuals list them alphabetically (BPA: Month (as a string) must be sorted)"))
        calc_filter = [c["name"] for c in t.get("columns") or [] if c.get("type") == "calculated"
                       and re.search(r"\bFILTER\s*\(", dax_code(_expr(c)), re.I)]
        if calc_filter:
            items.append(info(f"{t['name']}: calculated column(s) {_list(calc_filter)} use FILTER — slow to refresh "
                              f"(BPA: Reduce usage of calculated columns that use the FILTER function)"))
    floats = [f"{t['name']}[{c['name']}]" for t in tables for c in t.get("columns") or [] if c.get("dataType") == "double"]
    if floats:
        items.append(info(f"{_n(len(floats), 'column')} use floating point (Decimal number), e.g. {_list(floats, 3)} — "
                          f"BPA prefers Fixed decimal for amounts (Do not use floating point data types)"))
    # hidden columns nothing uses: measures, calculated columns, relationships, sorting or the report
    used = {(r["fromTable"], r["fromColumn"]) for r in rels} | {(r["toTable"], r["toColumn"]) for r in rels}
    used |= {(t["name"], c["sortByColumn"]) for t in tables for c in t.get("columns") or [] if c.get("sortByColumn")}
    for _, e in exprs:
        s = re.sub(r'"(?:[^"]|"")*"', '""', e)
        used |= {(a.replace("''", "'") or b, c) for a, b, c in re.findall(r"(?:'((?:[^']|'')+)'|\b([A-Za-z_]\w*))\s*\[([^\]]+)\]", s)}
    if rdir is not None:
        for f in (rdir / "definition").rglob("*.json"):
            try:
                used |= {(t, p) for k, t, p in refs(json.loads(f.read_text(encoding="utf-8"))) if k == "Column"}
            except (OSError, ValueError):
                pass
    unused = [f"{t['name']}[{c['name']}]" for t in tables for c in t.get("columns") or []
              if c.get("isHidden") and (t["name"], c["name"]) not in used and not t.get("measures")]
    if unused:
        items.append(info(f"{_n(len(unused), 'hidden column')} nothing uses, e.g. {_list(unused, 4)} — removing them makes "
                          f"the model smaller (BPA: Remove unnecessary columns)"))
    return gate("model_rules", items, ok=f"{_n(len(measures), 'measure')} and {_n(len(tables), 'table')} follow the rules")


# ---------------------------------------------------------------- report & accessibility (PBI Inspector style)

def _lum(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hex(x) -> str | None:
    if isinstance(x, dict):
        x = (x.get("solid") or {}).get("color")
    return x if isinstance(x, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", x) else None


def _literal(x):
    v = ((x or {}).get("expr") or {}).get("Literal", {}).get("Value") if isinstance(x, dict) else None
    return v.strip("'") if isinstance(v, str) else v


def _has_title(v: dict) -> bool:
    for e in (v.get("visualContainerObjects") or {}).get("title") or []:
        p = e.get("properties") or {}
        if _literal(p.get("show")) == "true" and p.get("text"):
            return True
    objs = v.get("objects") or {}
    return any((e.get("properties") or {}).get(prop) for obj, prop in (("header", "title"), ("kpi", "label"),
               ("narrative", "heading"), ("title", "text")) for e in objs.get(obj) or [])


DECOR = {"textbox", "pageNavigator", "bookmarkNavigator", "shape", "basicShape", "image", "actionButton"}


def report_rules(rdir: Path) -> dict:
    """Layout, titles, alt text and colour contrast of the report pages."""
    items = []
    report = json.loads((rdir / "definition" / "report.json").read_text(encoding="utf-8"))
    custom = (report.get("themeCollection") or {}).get("customTheme") or {}
    theme = {}
    for p in report.get("resourcePackages") or []:
        for it in p.get("items") or []:
            if p.get("name") == custom.get("type") and it.get("name") == custom.get("name"):
                try:
                    theme = json.loads((rdir / "StaticResources" / p["name"] / it["path"]).read_text(encoding="utf-8"))
                except (OSError, ValueError, KeyError):
                    pass
    bg = _hex(theme.get("background")) or "#FFFFFF"
    for what, color in (("Text", _hex(theme.get("foreground"))),
                        ("Label text", _hex(((theme.get("textClasses") or {}).get("label") or {}).get("color")))):
        if color and contrast(color, bg) < 4.5:
            items.append(warn(f"{what} {color} on {bg} has a contrast of {contrast(color, bg):.1f}:1 — WCAG 2.1 AA asks "
                              f"for 4.5:1"))
    weak = [c for c in theme.get("dataColors") or [] if _hex(c) and contrast(c, bg) < 3]
    if weak:
        items.append(info(f"Data colours {', '.join(weak[:5])} have less than 3:1 contrast with the {bg} background — "
                          f"fine for fills next to labels, too light for thin lines (WCAG 2.1 non-text contrast)"))
    for name, tc in (theme.get("textClasses") or {}).items():
        if isinstance(tc, dict) and isinstance(tc.get("fontSize"), (int, float)) and tc["fontSize"] < 9:
            items.append(warn(f"The theme's {name} text is {tc['fontSize']} pt — 9 pt or more stays readable"))
    meta = json.loads((rdir / "definition" / "pages" / "pages.json").read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    n_vis = 0
    for pid in meta.get("pageOrder") or []:
        pdir = rdir / "definition" / "pages" / pid
        page = json.loads((pdir / "page.json").read_text(encoding="utf-8"))
        pname = page.get("displayName", pid)
        if pname.lower() in names:
            items.append(warn(f"Two pages are named {pname!r}"))
        names[pname.lower()] = pname
        if re.fullmatch(r"(Page|Seite|Página)\s*\d+", pname, re.I):
            items.append(warn(f"Page {pname!r} has a default name — name it after what it shows"))
        boxes = []
        for vdir in sorted((pdir / "visuals").iterdir()) if (pdir / "visuals").is_dir() else []:
            v = json.loads((vdir / "visual.json").read_text(encoding="utf-8"))
            vis, pos = v.get("visual") or {}, v.get("position") or {}
            vt = vis.get("visualType")
            label = _visual_label(vis) or vdir.name
            n_vis += 1
            x, y, w, h = (float(pos.get(k, 0)) for k in ("x", "y", "width", "height"))
            if x < 0 or y < 0 or x + w > page.get("width", 1280) + 1 or y + h > page.get("height", 720) + 1:
                items.append(warn(f"{pname}: {label} reaches outside the page ({page.get('width')}×{page.get('height')})"))
            boxes.append((label, x, y, w, h))
            if vt in DECOR:
                continue
            general = (vis.get("visualContainerObjects") or {}).get("general") or []
            if not any((e.get("properties") or {}).get("altText") for e in general):
                items.append(warn(f"{pname}: {label} has no alt text — screen readers announce only its type"))
            if vt not in ("slicer", "cardVisual", "card", "multiRowCard") and not _has_title(vis):   # cards label each value
                items.append(warn(f"{pname}: a {vt} visual has no title"))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                ox = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                oy = min(a[2] + a[4], b[2] + b[4]) - max(a[2], b[2])
                if ox > 2 and oy > 2:
                    items.append(warn(f"{pname}: {a[0]} and {b[0]} overlap"))
        if len(boxes) > 20:
            items.append(warn(f"{pname} has {len(boxes)} visuals — pages with more than 20 load slowly"))
    return gate("report_rules", items, ok=f"{_n(len(names), 'page')} and {_n(n_vis, 'visual')}: titled, described, "
                                         f"inside the page, readable contrast")


def _visual_label(vis: dict) -> str | None:
    """How a person knows a visual: its title, or its alt text."""
    for e in (vis.get("visualContainerObjects") or {}).get("general") or []:
        t = _literal((e.get("properties") or {}).get("altText"))
        if isinstance(t, str) and t:
            return f'"{t.split(" — ")[0][:60]}"'
    for obj, prop in (("header", "title"), ("kpi", "label"), ("narrative", "heading")):
        for e in (vis.get("objects") or {}).get(obj) or []:
            t = _literal((e.get("properties") or {}).get(prop))
            if isinstance(t, str) and t:
                return f'"{t[:60]}"'
    return None


# ---------------------------------------------------------------- running them

def custom_visuals(d: Path, dd: dict) -> dict:
    """Every custom visual the report uses is built from its current source and passed `genbi visual test`."""
    from . import vfactory
    used, items, n = {v["type"] for p in dd["pages"] for v in p["visuals"]}, [], 0
    for v in vfactory.status(d) if (d / "visuals").is_dir() else []:
        name = v["name"]
        if name not in used:
            continue
        n += 1
        if v["stale"]:
            items.append(fail(f"custom visual {name}: its source changed after the last build — run `genbi visual build "
                              f"{name}` and `genbi visual test {name}`"))
        elif not v["tested"]:
            last = "; ".join((v.get("test_problems") or [])[:3])
            items.append(fail(f"custom visual {name}: run `genbi visual test {name}` on the current build, Read "
                              f"visuals/{name}/test.png and fix what it finds" + (f" (last test: {last})" if last else "")))
    if not n:
        return gate("custom_visuals", skip="no new custom visuals in this report")
    return gate("custom_visuals", items, ok=f"{_n(n, 'custom visual')} built and tested")


def dax_gates(s: dict | None) -> list[dict]:
    """The DAX check (daxcheck.summary) as two gates: the engine accepts everything; values match the prototype."""
    if not s or not s.get("checked"):
        why = (s or {}).get("reason") or "it did not run"
        return [gate("dax", skip=f"not checked: {why}"), gate("values", skip="needs the DAX check")]
    dax = gate("dax", s.get("problems") or [], ok=f"{_n(s['measures'], 'measure')} and {_n(s['visuals'], 'visual query')} "
                                                   f"accepted (Power BI Desktop {s.get('engine') or ''})".replace(" )", ")"))
    if not s.get("compared"):
        return [dax, gate("values", skip="large tables were checked on a sample, so values are not compared")]
    return [dax, gate("values", [warn(x) for x in s.get("differences") or []],
                      ok="every visual's values and title match the prototype")]


def file_gates(d: Path, dd: dict, catalog: dict, visuals_dir: Path | None, con=None, out: Path | None = None,
               dax: dict | None = None) -> list[dict]:
    """The gates that read the report's files: built into a temporary folder, or `out` when publishing. `dax` is
    the DAX check summary, when there is one (it tells which measures return text)."""
    from . import report_builder
    texts = {v["name"] for v in (dax or {}).get("values") or [] if isinstance(v.get("value"), str)}
    tmp = None
    try:
        if out is None:
            tmp = Path(tempfile.mkdtemp(prefix="genbi-gates-"))
            report_builder.build(copy.deepcopy(dd), catalog, tmp, visuals_dir=visuals_dir)
            out = tmp
        name = next(out.glob("*.pbip")).stem
        rdir, sdir = out / f"{name}.Report", out / f"{name}.SemanticModel"
        try:
            pq, tables = power_query(sdir, d / "data")
        except Exception as e:  # noqa: BLE001
            pq, tables = gate("power_query", [fail(f"the check crashed: {e}")]), {}
        found = [pq]
        for gid, fn in (("data", lambda: data(tables, d / "data", sdir, con)), ("pbir_schema", lambda: pbir_schema(rdir)),
                        ("coherence", lambda: coherence(out, d / "data")),
                        ("model_rules", lambda: model_rules(sdir, rdir, con, texts)), ("report_rules", lambda: report_rules(rdir))):
            try:
                found.append(fn())
            except Exception as e:  # noqa: BLE001 - one broken check never hides the others
                found.append(gate(gid, [fail(f"the check crashed: {e.__class__.__name__}: {e}")]))
        return found
    except Exception as e:  # noqa: BLE001 - the project could not even be written
        return [gate("coherence", [fail(f"the Power BI report could not be written: {str(e).splitlines()[0][:300]}")])]
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
