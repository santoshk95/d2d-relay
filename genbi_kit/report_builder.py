"""Power BI Project (PBIP) builder for multi-page reports using the Relay custom visuals.

Input: a report definition (schema: see samples/global_retail/reference.py) and the custom
visual catalog (custom_visuals/catalog.json, written by visuals/scaffold.py).
Output: <out>/<Name>.pbip + <Name>.SemanticModel/model.bim + <Name>.Report in Power BI's PBIR format
(definition/pages/<page>/visuals/<visual>/visual.json) with the custom visuals embedded under
CustomVisuals/, so the report opens without importing anything.

All modelling happens in the semantic model: CSV tables load through a DataFolder parameter in
Power Query; relationships, the date table, calculated columns and measures are model objects.
Everything is validated (DAX references, fields, visual roles, format properties) before writing.
"""
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from . import stock
from .dax import quote_tables, refers_to, uses_whole_table
from .plaintext import human

ASSETS = Path(__file__).resolve().parent / "assets"
BASE_THEME = "CY24SU10"            # Power BI's own base theme, shipped inside the report
THEME_FILE = "GenBI_Theme.json"
DTYPE = {"int": "int64", "decimal": "double", "string": "string", "date": "dateTime", "bool": "boolean"}
MTYPE = {"int": "Int64.Type", "decimal": "type number", "string": "type text", "date": "type date", "bool": "type logical"}
COL_REF = re.compile(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$")
MEASURE_REF = re.compile(r"^\[([^\]]+)\]$")
# Power BI column data categories (model.bim dataCategory), by their names without spaces, any case
DATA_CATEGORIES = {k.lower(): k for k in ("Address", "City", "Continent", "Country", "County", "Latitude", "Longitude", "Place",
                                          "PostalCode", "StateOrProvince", "WebUrl", "ImageUrl", "Barcode")}
DATA_CATEGORIES.update({"countryregion": "Country", "state": "StateOrProvince", "province": "StateOrProvince",
                        "postcode": "PostalCode", "zip": "PostalCode", "url": "WebUrl", "image": "ImageUrl"})
# a format that scales the number itself (#,0.0,,"M"): commas after the last digit placeholder divide by 1000 each
SCALED_FORMAT = re.compile(r'[0#](?:\.[0#]+)?,+(?![0#])')
NO_CHROME = {"background": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
             "border": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
             "dropShadow": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
             "title": [{"properties": {"show": {"expr": {"Literal": {"Value": "false"}}}}}],
             "padding": [{"properties": {k: {"expr": {"Literal": {"Value": "0D"}}} for k in ("top", "bottom", "left", "right")}}]}


class DefinitionError(ValueError):
    pass


def _lit(value) -> dict:
    if isinstance(value, bool):
        v = "true" if value else "false"
    elif isinstance(value, int):
        v = f"{value}D"
    elif isinstance(value, float):
        v = f"{value}D"
    else:
        v = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": v}}}


def _color(hex_: str) -> dict:
    return {"solid": {"color": _lit(hex_)}}


# ---------------------------------------------------------------- model
class Model:
    def __init__(self, defn: dict):
        self.defn = defn
        self.mtable = defn["measures_table"]
        self.columns: dict[str, dict[str, dict]] = {t["name"]: {c["name"]: c for c in t["columns"]} for t in defn["tables"]}
        for cc in defn.get("calculated_columns", []):
            self.columns[cc["table"]][cc["name"]] = {**cc, "calculated": True}
        self.measures = {m["name"]: m for m in defn["measures"]}

    def field(self, ref: str) -> tuple[str, str, str]:
        """'[Measure]' -> ('Measure', measures table, name); "Table[Col]" / "'My Table'[Col]" -> ('Column', table, col)."""
        mm = MEASURE_REF.match(ref.strip())
        if mm:
            if mm.group(1) not in self.measures:
                raise DefinitionError(f"Unknown measure {ref}")
            return "Measure", self.mtable, mm.group(1)
        cm = COL_REF.match(ref.strip())
        if not cm or cm.group(1) not in self.columns or cm.group(2) not in self.columns[cm.group(1)]:
            raise DefinitionError(f"Unknown column {ref}")
        return "Column", cm.group(1), cm.group(2)

    def validate(self) -> None:
        errors = []
        seen = {}
        all_cols = {c.lower(): f"{t}[{c}]" for t, cols in self.columns.items() for c in cols}
        for m in self.defn["measures"]:
            key = m["name"].lower()
            if key in seen:
                errors.append(f"Duplicate measure name {m['name']}")
            if key in all_cols:
                errors.append(f"Measure [{m['name']}] has the same name as column {all_cols[key]}")
            seen[key] = m
        exprs = [(f"[{m['name']}]", m["expression"]) for m in self.defn["measures"]]
        exprs += [(f"{c['table']}[{c['name']}]", c["expression"]) for c in self.defn.get("calculated_columns", [])]
        for owner, expr in exprs:
            code = re.sub(r'"(?:[^"]|"")*"', '""', expr)            # ignore string literals
            quoted = r"'((?:[^']|'')+)'(?:\[([^\]]+)\])?"               # 'Table' or 'Table'[Column]
            for table, col in re.findall(quoted, code):
                table = table.replace("''", "'")
                if table not in self.columns:
                    errors.append(f"{owner}: unknown table '{table}'")
                elif col and col not in self.columns[table]:
                    errors.append(f"{owner}: unknown column '{table}'[{col}]")
            code = re.sub(quoted, " ", code)
            bare = r"\b([A-Za-z_]\w*)\[([^\]]+)\]"                       # Table[Column]
            for table, col in re.findall(bare, code):
                if table not in self.columns or col not in self.columns[table]:
                    errors.append(f"{owner}: unknown column {table}[{col}]")
            for name in re.findall(r"\[([^\]]+)\]", re.sub(bare, " ", code)):
                if not name.startswith("@") and name not in self.measures:
                    errors.append(f"{owner}: unknown measure [{name}]")
        for r in self.defn["relationships"]:
            for ref in (r["from"], r["to"]):
                try:
                    self.field(ref)
                except DefinitionError as e:
                    errors.append(f"relationship {r['from']} -> {r['to']}: {e}")
        for t in self.defn["tables"]:
            names: dict[str, str] = {}
            calc = {cc["name"]: cc for cc in self.defn.get("calculated_columns", []) if cc["table"] == t["name"]}
            for c in t["columns"] + list(calc.values()):
                if c.get("sortBy") and c["sortBy"] not in self.columns[t["name"]]:
                    errors.append(f"{t['name']}[{c['name']}] sorts by unknown column {c['sortBy']}")
                elif c.get("sortBy") in calc:              # Power BI: "A circular dependency was detected"
                    expr = calc[c["sortBy"]]["expression"]
                    if uses_whole_table(expr, t["name"]) or refers_to(expr, t["name"], c["name"]):
                        errors.append(f"{t['name']}[{c['name']}] is sorted by {t['name']}[{c['sortBy']}], whose DAX depends on "
                                      f"{t['name']}[{c['name']}] (it reads it, uses the whole {t['name']} table, or CALCULATE) "
                                      f"- Power BI reports a circular dependency. Compute {c['sortBy']} from the columns it needs "
                                      f"only, e.g. ALL ( {t['name']}[col1], {t['name']}[col2] ) instead of ALL ( {t['name']} ), or "
                                      f"sort by a column from the CSV")
                if c["name"].lower() in names:          # Power BI column names ignore case
                    errors.append(f"{t['name']} has two columns named {names[c['name'].lower()]!r} and {c['name']!r} "
                                  f"(Power BI ignores case in names)")
                names.setdefault(c["name"].lower(), c["name"])
        if errors:
            raise DefinitionError("Invalid definition:\n  " + "\n  ".join(errors))


def _m(text: str) -> str:
    """An M text literal."""
    return '"' + str(text).replace('"', '""') + '"'


def _csv_m(table: dict, parameter: str) -> list[str]:
    """Power Query for a CSV table. Every model column comes out under its model name, whatever the mapping: only
    the CSV columns the model uses are kept, a CSV column used by several model columns is duplicated for each
    extra use, the first use is renamed, and each column is typed once under its final name (M rejects a column
    listed twice, or a new name that is already taken). Empty cells of text columns become blank (null), as in
    the prototype and the DAX check - Csv.Document reads them as "" and ISBLANK ( "" ) is FALSE in DAX
    (`blanks_to_null: false` on a table keeps them as empty text)."""
    lines = ["let",
             f'    Source = Csv.Document(File.Contents({parameter} & {_m(table["csv"])}), [Delimiter = ",", '
             'Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
             "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),"]
    return _shape(table, lines, "Promoted", table.get("blanks_to_null", True))


def _shape(table: dict, lines: list[str], step: str, blanks: bool) -> list[str]:
    """Shared by every source: keep the columns the model uses, rename them to model names, type them."""
    first, copies, seen = [], [], set()
    for c in table["columns"]:
        (copies if c["source"] in seen else first).append(c)
        seen.add(c["source"])
    sources = {c["source"] for c in first}
    # a new name that is another column's source name: move every source column out of the way first
    clash = any(c["name"] in sources and c["name"] != c["source"] for c in table["columns"])
    now = {c["source"]: (f"__genbi_{i}" if clash else c["source"]) for i, c in enumerate(first, 1)}
    lines = lines + [f"    Selected = Table.SelectColumns({step}, {{{', '.join(_m(c['source']) for c in first)}}}),"]
    step = "Selected"
    pairs = lambda items: ", ".join(f"{{{_m(a)}, {_m(b)}}}" for a, b in items)
    if clash:
        lines.append(f"    Unclashed = Table.RenameColumns({step}, {{{pairs((s, now[s]) for s in now)}}}),")
        step = "Unclashed"
    for i, c in enumerate(copies, 1):
        lines.append(f"    Copy{i} = Table.DuplicateColumn({step}, {_m(now[c['source']])}, {_m(c['name'])}),")
        step = f"Copy{i}"
    renames = [(now[c["source"]], c["name"]) for c in first if now[c["source"]] != c["name"]]
    if renames:
        lines.append(f"    Renamed = Table.RenameColumns({step}, {{{pairs(renames)}}}),")
        step = "Renamed"
    text = [c["name"] for c in first + copies if c["type"] == "string"]
    if text and blanks:
        lines.append(f'    Blanks = Table.ReplaceValue({step}, "", null, Replacer.ReplaceValue, {{{", ".join(_m(n) for n in text)}}}),')
        step = "Blanks"
    types = ", ".join(f"{{{_m(c['name'])}, {MTYPE[c['type']]}}}" for c in first + copies)
    lines.append(f'    Typed = Table.TransformColumnTypes({step}, {{{types}}}, "en-US")')
    return lines + ["in", "    Typed"]


def _parts(obj: str, n: int) -> list[str]:
    """'DB.SCHEMA.TABLE' -> ['DB', 'SCHEMA', 'TABLE'] (quotes and backticks dropped), padded on the left."""
    parts = [p.strip().strip('"`[]') for p in str(obj).split(".")]
    return [""] * (n - len(parts)) + parts[-n:]


NATIVE_KINDS = ("snowflake", "bigquery", "fabric", "redshift", "athena", "oracle_db")   # sources the PBIP refreshes from itself (else: the pulled Parquet file)


def _oracle_server(c: dict) -> str:
    """Easy Connect for Power BI's Oracle connector: [tcps://]host:port/service (the same string Relay connects with)."""
    host = str(c.get("host") or "").strip()
    tls = host.lower().startswith("tcps://")
    host = re.sub(r"(?i)^tcps?://", "", host)
    port = str(c.get("port") or "").strip() or ("1522" if tls else "1521")
    return f"{'tcps://' if tls else ''}{host}:{port}/{str(c.get('service_name') or '').strip()}"


def _warehouse_m(table: dict, ext: dict | None, parameter: str) -> list[str]:
    """Power Query for a warehouse table: the native Power BI connector of that warehouse, navigated to the object,
    then the same column shaping as CSV tables. Without connection details (built outside the app), or for a source
    Power BI has no connector for (an API such as Oracle Retail MFCS), the extract's Parquet file is read from the
    data folder instead, so the project still opens and refreshes."""
    kind = (ext or {}).get("kind")
    c = (ext or {}).get("connection") or {}
    obj = (ext or {}).get("object", "")
    if kind == "oracle_db" and not (c.get("host") and c.get("service_name") and "." in str(obj)):
        kind = None                                      # no schema-qualified object or no address: the Parquet copy
    if kind == "oracle_db":
        schema, name = _parts(obj, 2)
        nav = [f"    Source = Oracle.Database({_m(_oracle_server(c))}, [HierarchicalNavigation = true]),",
               f"    Schema = Source{{[Schema = {_m(schema)}]}}[Data],",
               f"    Data = Schema{{[Name = {_m(name)}]}}[Data],"]
    elif kind == "snowflake":
        db, schema, name = _parts(obj, 3)
        nav = [f"    Source = Snowflake.Databases({_m(c.get('host') or c.get('account', '') + '.snowflakecomputing.com')}, "
               f"{_m(c.get('warehouse', ''))}),",
               f"    Database = Source{{[Name = {_m(db or c.get('database', ''))}, Kind = \"Database\"]}}[Data],",
               f"    Schema = Database{{[Name = {_m(schema or c.get('schema', 'PUBLIC'))}, Kind = \"Schema\"]}}[Data],",
               f"    Data = Schema{{[Name = {_m(name)}]}}[Data],"]
    elif kind == "bigquery":
        project, dataset, name = _parts(obj, 3)
        project = project or c.get("project", "")
        nav = [f"    Source = GoogleBigQuery.Database([BillingProject = {_m(c.get('billing_project') or project)}]),",
               f"    Project = Source{{[Name = {_m(project)}]}}[Data],",
               f"    Dataset = Project{{[Name = {_m(dataset)}, Kind = \"Schema\"]}}[Data],",
               f"    Data = Dataset{{[Name = {_m(name)}]}}[Data],"]
    elif kind == "fabric":
        schema, name = _parts(obj, 2)
        nav = [f"    Source = Sql.Database({_m(c.get('server', ''))}, {_m(c.get('database', ''))}),",
               f"    Data = Source{{[Schema = {_m(schema or 'dbo')}, Item = {_m(name)}]}}[Data],"]
    elif kind == "redshift":
        schema, name = _parts(obj, 2)
        nav = [f"    Source = AmazonRedshift.Database({_m(c.get('host', '') + ':' + str(c.get('port') or 5439))}, "
               f"{_m(c.get('database', ''))}),",
               f"    Schema = Source{{[Name = {_m(schema or 'public')}]}}[Data],",
               f"    Data = Schema{{[Name = {_m(name)}]}}[Data],"]
    elif kind == "athena":
        catalog, database, name = _parts(obj, 3)
        nav = [f"    Source = AmazonAthena.Databases({_m(c.get('dsn') or 'Athena')}),",
               f"    Catalog = Source{{[Name = {_m(catalog or 'AwsDataCatalog')}]}}[Data],",
               f"    Database = Catalog{{[Name = {_m(database or c.get('database', ''))}]}}[Data],",
               f"    Data = Database{{[Name = {_m(name)}]}}[Data],"]
    else:
        nav = [f"    Data = Parquet.Document(File.Contents({parameter} & {_m(table['extract'])})),"]
    return _shape(table, ["let", *nav], "Data", False)


def _model_bim(defn: dict, model: Model) -> dict:
    param = defn["data"]["parameter"]
    names = [t["name"] for t in defn["tables"]]
    dax = lambda expr: quote_tables(expr, names)        # 'Batch'[Yield]: bare names can be reserved words
    keys = set()
    for r in defn["relationships"]:
        for ref in (r["from"], r["to"]):
            _, t, c = model.field(ref)
            keys.add((t, c))
    tables = []
    for t in defn["tables"]:
        cols = []
        for c in t["columns"]:
            numeric = c["type"] in ("int", "decimal") and (t["name"], c["name"]) not in keys
            col = {"name": c["name"], "dataType": DTYPE[c["type"]], "sourceColumn": c["name"],
                   "summarizeBy": "sum" if numeric else "none"}
            if t.get("dax"):              # calculated table (DAX): columns come from the table expression
                col = {"type": "calculatedTableColumn", "name": c["name"], "dataType": DTYPE[c["type"]],
                       "isNameInferred": True, "isDataTypeInferred": True, "sourceColumn": f"[{c['name']}]",
                       "summarizeBy": "none"}
            if c.get("hidden"):
                col["isHidden"] = True
            if c.get("sortBy"):
                col["sortByColumn"] = c["sortBy"]
            if c.get("category"):         # data category: maps geocode City / Country / ..., tables show links and images
                cat = DATA_CATEGORIES.get(str(c["category"]).replace(" ", "").lower())
                if not cat:
                    raise DefinitionError(f"{t['name']}[{c['name']}]: category must be one of {', '.join(sorted(set(DATA_CATEGORIES.values())))}")
                col["dataCategory"] = cat
            if c["type"] == "date":
                col["formatString"] = "yyyy-MM-dd"
            if t.get("date_table") and c["name"] == "Date":
                col["isKey"] = True
            cols.append(col)
        for cc in defn.get("calculated_columns", []):
            if cc["table"] == t["name"]:
                col = {"type": "calculated", "name": cc["name"], "dataType": DTYPE[cc["type"]], "isDataTypeInferred": True,
                       "expression": dax(cc["expression"]), "summarizeBy": "none"}
                if cc.get("hidden"):
                    col["isHidden"] = True
                cols.append(col)
        if t.get("dax"):
            source = {"type": "calculated", "expression": dax(t["dax"])}
        else:
            extracts = (defn.get("data") or {}).get("extracts") or {}
            expr = (_csv_m(t, param) if t.get("csv") else _warehouse_m(t, extracts.get(t["extract"]), param)
                    if t.get("extract") else t["m"].split("\n"))
            source = {"type": "m", "expression": expr}
        table = {"name": t["name"], "columns": cols,
                 "partitions": [{"name": t["name"], "mode": "import", "source": source}]}
        if t.get("description"):
            table["description"] = human(t["description"])
        if t.get("date_table"):
            table["dataCategory"] = "Time"
        if t["name"] == defn["measures_table"]:
            table["measures"] = []
            for m in defn["measures"]:
                mj = {"name": m["name"], "expression": dax(m["expression"]).split("\n")}
                if m.get("format"):
                    mj["formatString"] = m["format"]
                if m.get("folder"):
                    mj["displayFolder"] = human(m["folder"])
                if m.get("description"):
                    mj["description"] = human(m["description"])
                table["measures"].append(mj)
        tables.append(table)
    rels = []
    for r in defn["relationships"]:
        _, ft, fc = model.field(r["from"])
        _, tt, tc = model.field(r["to"])
        rels.append({"name": uuid.uuid5(uuid.NAMESPACE_URL, f"{ft}.{fc}->{tt}.{tc}").hex, "fromTable": ft,
                     "fromColumn": fc, "toTable": tt, "toColumn": tc})
    folder = defn["data"]["folder"]
    return {
        "name": "SemanticModel",
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": rels,
            "expressions": [{
                "name": param, "kind": "m",
                "expression": [f'"{folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]'],
                "annotations": [{"name": "PBI_ResultType", "value": "Text"}],
            }],
            "annotations": [
                # Power Query queries only (calculated tables are not queries).
                {"name": "PBI_QueryOrder", "value": json.dumps([param] + [t["name"] for t in defn["tables"] if not t.get("dax")])},
                # We ship our own date table, so no hidden auto date/time tables.
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
            ],
        },
    }


# ---------------------------------------------------------------- report (PBIR)
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
REPORT_VERSION_AT_IMPORT = {"visual": "1.8.97", "report": "2.0.97", "page": "1.3.97"}


def _field(model: Model, ref: str) -> tuple[str, str, dict]:
    """Field reference -> (kind, queryRef, PBIR field expression)."""
    kind, table, prop = model.field(ref)
    return kind, f"{table}.{prop}", {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": prop}}


def _projection(model: Model, ref: str, **extra) -> dict:
    _, qref, field = _field(model, ref)
    return {"field": field, "queryRef": qref, **extra}


TEXT_PROPS = {"title", "subtitle", "subTitle", "label", "heading", "text", "altText", "caption"}


def _plain_visual(v: dict) -> dict:
    """The visual with the words people read in plain keyboard characters (plaintext.human): its title (unless a
    measure gives it), subtitle, label, text box runs and the Format pane's text. Fields, filters, sorts and values
    are data and stay exactly as they are."""
    out = dict(v)
    for k in ("title", "subtitle", "label"):
        if isinstance(out.get(k), str) and not MEASURE_REF.match(out[k].strip()):
            out[k] = human(out[k])
    if isinstance(out.get("paragraphs"), list):
        out["paragraphs"] = [[{**r, "text": human(r["text"])} if isinstance(r, dict) and "text" in r else r for r in runs]
                             if isinstance(runs, list) else runs for runs in out["paragraphs"]]
    if isinstance(out.get("format"), dict):
        out["format"] = {obj: {p: human(x) if p in TEXT_PROPS else x for p, x in props.items()}
                         if isinstance(props, dict) else props for obj, props in out["format"].items()}
    return out


def _visual_name(vid: str) -> str:
    return vid.replace("_", "")[:20] + uuid.uuid5(uuid.NAMESPACE_URL, vid).hex[:8]


def _alt_text(v: dict) -> str | None:
    """What a screen reader announces for a visual: its title, subtitle and the fields it shows."""
    fmt = v.get("format") if isinstance(v.get("format"), dict) else {}
    part = lambda obj, key: fmt[obj].get(key) if isinstance(fmt.get(obj), dict) else None
    title = v.get("title") if isinstance(v.get("title"), str) and not MEASURE_REF.match(v["title"].strip()) else None
    name = part("header", "title") or part("kpi", "label") or part("narrative", "heading") or title or v.get("label")
    fields = v.get("fields") or ([v["field"]] if v.get("field") else [])
    wells = fields.items() if isinstance(fields, dict) else [("values", fields)]
    refs = [r for role, x in wells if str(role).lower() not in ("title", "annotation", "tooltips", "xref", "yref")   # not the data
            for r in (x if isinstance(x, list) else [x])]
    shown = list(dict.fromkeys(m.group(2) or m.group(1) for r in refs
                               for m in [re.match(r"^\s*(?:\[([^\]]+)\]|'?[^'\[]+'?\[([^\]]+)\])\s*$", str(r))] if m))
    if v["type"] == "slicer":
        return f"Filter by {name or (shown[0] if shown else 'a field')}"
    text = " - ".join(str(x) for x in (name, part("header", "subtitle") or v.get("subtitle")) if x)
    if shown:
        text += (". " if text else "") + "Shows " + ", ".join(shown[:6])
    return text[:250] or None


def _format_value(vid: str, obj: str, prop: str, kind, value):
    """One Format-pane value as a PBIR literal, checked against the property's type."""
    if kind == "color":
        if not (isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value)):
            raise DefinitionError(f"{vid}: {obj}.{prop} needs a color like \"#1F6FEB\", got {value!r}")
        return _color(value)
    if isinstance(kind, dict):                                       # enumeration
        if str(value) not in kind["enum"]:
            raise DefinitionError(f"{vid}: {obj}.{prop} must be one of {', '.join(kind['enum'])}, got {value!r}")
        return _lit(str(value))
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DefinitionError(f"{vid}: {obj}.{prop} needs a number, got {value!r}")
        return _lit(int(value) if float(value).is_integer() else float(value))
    if kind == "bool":
        if not isinstance(value, bool):
            raise DefinitionError(f"{vid}: {obj}.{prop} needs true or false, got {value!r}")
        return _lit(value)
    return _lit(str(value))


def _check_fields(v: dict, entry: dict, counts: dict) -> None:
    """Visual Atlas field rules: limits per well, the combinations the visual accepts, the fields it needs."""
    drill = set(entry.get("drill") or [])
    for role, n in counts.items():
        cap = entry["role_info"][role]["max"]
        if cap is not None and n > cap and role not in drill:
            raise DefinitionError(f"{v['id']}: well '{role}' takes at most {cap} field{'s' if cap != 1 else ''}, got {n}")
    eff = {r: (1 if r in drill and n else n) for r, n in counts.items()}
    conds = entry.get("conditions") or []
    if conds and not any(all(eff.get(r, 0) <= (cap if cap is not None else 10 ** 6) for r, cap in c.items())
                         for c in conds):
        rules = " or ".join("(" + ", ".join(f"{r} ≤ {cap}" for r, cap in c.items() if cap is not None) + ")" for c in conds)
        raise DefinitionError(f"{v['id']}: this combination of fields doesn't fit {v['type']}: allowed {rules}")
    need = entry.get("required") or []
    if need and not any(all(counts.get(r) for r in group) for group in need):
        raise DefinitionError(f"{v['id']}: {v['type']} needs the fields " + " or ".join("+".join(g) for g in need))


def _container(v: dict, model: Model) -> dict:
    """Visual Atlas visuals sit in Power BI's own container (styled by the theme) with a title and subtitle.
    A title written as "[Measure]" is dynamic, so it can state the finding."""
    out = {}
    title = v.get("title")
    if title:
        mm = MEASURE_REF.match(str(title).strip())
        if mm:
            _field(model, title)
            text = {"expr": {"Measure": {"Expression": {"SourceRef": {"Entity": model.mtable}}, "Property": mm.group(1)}}}
        else:
            text = _lit(str(title))
        out["title"] = [{"properties": {"show": _lit(True), "text": text}}]
    else:
        out["title"] = [{"properties": {"show": _lit(False)}}]
    if v.get("subtitle"):
        out["subTitle"] = [{"properties": {"show": _lit(True), "text": _lit(str(v["subtitle"]))}}]
    return out


def _custom_visual(v: dict, model: Model, catalog: dict) -> dict:
    entry = catalog.get(v["type"])
    if not entry:
        from . import project_dir
        proj = project_dir()
        if proj is not None and (proj / "visuals" / str(v["type"]) / "pbiviz.json").exists():
            raise DefinitionError(f"{v['id']}: custom visual {v['type']} is not built yet - run "
                                  f"`genbi visual build {v['type']}`")
        if str(v["type"]).startswith(stock.PREFIX):
            raise DefinitionError(f"{v['id']}: {v['type']} is not one of the Power BI visuals Relay places - "
                                  f"`genbi catalog pbi` lists them")
        raise DefinitionError(f"{v['id']}: unknown visual type {v['type']}")
    atlas = entry.get("family") == "atlas"
    drill = set(entry.get("drill") or [])
    state: dict = {}
    counts: dict = {}
    for role, refs in v.get("fields", {}).items():
        if role not in entry["roles"]:
            raise DefinitionError(f"{v['id']}: {v['type']} has no field well '{role}' "
                                  f"(wells: {', '.join(entry['roles'])})")
        refs = refs if isinstance(refs, list) else [refs]
        counts[role] = len(refs)
        for i, ref in enumerate(refs):
            kind = _field(model, ref)[0]
            want = entry["roles"][role]
            if (kind == "Column") != (want == "Grouping"):
                raise DefinitionError(f"{v['id']}: well '{role}' expects a "
                                      f"{'column' if want == 'Grouping' else 'measure'}, got {ref}")
            extra = {"active": i == 0} if role in drill and len(refs) > 1 else {}      # drill hierarchy: top level shows
            state.setdefault(role, {"projections": []})["projections"].append(_projection(model, ref, **extra))
    if not state:
        raise DefinitionError(f"{v['id']}: a custom visual needs at least one field (it never renders without one)")
    if atlas:
        _check_fields(v, entry, counts)
        for role, refs in v.get("fields", {}).items():          # Atlas-framework visuals add K / M units themselves
            for ref in (refs if isinstance(refs, list) else [refs]) if entry["roles"].get(role) == "Measure" else []:
                mm = MEASURE_REF.match(str(ref).strip())
                fmt_ = str(model.measures.get(mm.group(1), {}).get("format") or "") if mm else ""
                if SCALED_FORMAT.search(re.sub(r'"[^"]*"|\\.', "x", fmt_.split(";")[0])):
                    raise DefinitionError(f"{v['id']}: [{mm.group(1)}] has a pre-scaled format ({fmt_}); {v['type']} adds "
                                          f"display units (K, M) itself, so labels would read like $0MM. Bind a measure "
                                          f"with a plain format (e.g. \\$#,0 or 0.0%) - a copy of [{mm.group(1)}] if other "
                                          f"visuals need the scaled one")
    fmt = {k: dict(p or {}) for k, p in (v.get("format") or {}).items()}
    if v.get("chart"):
        if v["chart"] not in entry.get("chart_types", []):
            raise DefinitionError(f"{v['id']}: {v['type']} chart must be one of {', '.join(entry['chart_types'])}, "
                                  f"got {v['chart']!r}")
        fmt.setdefault("chart", {})["chartType"] = v["chart"]
    if v["type"] == "atlasFinance" and fmt.get("chart", {}).get("chartType") == "waterfall":
        values = v.get("fields", {}).get("values") or []
        for ref in values if isinstance(values, list) else [values]:
            mm = MEASURE_REF.match(str(ref).strip())
            signed = mm and str(model.measures.get(mm.group(1), {}).get("format", "")).split(";")[0].strip().startswith("+")
            if signed:
                raise DefinitionError(f"{v['id']}: the waterfall adds +/- signs itself, but [{mm.group(1)}] has a signed "
                                      f"format, so labels would read '++'. Bind a measure with a plain format (e.g. a copy "
                                      f"of [{mm.group(1)}] formatted \\$#,0)")
    objects = {}
    for obj, props in fmt.items():
        spec = entry["objects"].get(obj)
        if spec is None:
            raise DefinitionError(f"{v['id']}: {v['type']} has no format object '{obj}' "
                                  f"(objects: {', '.join(entry['objects'])})")
        values = {}
        for prop, value in props.items():
            if prop not in spec:
                raise DefinitionError(f"{v['id']}: unknown format property {obj}.{prop} "
                                      f"(properties: {', '.join(spec)})")
            if value in ("", None):
                continue
            values[prop] = _format_value(v["id"], obj, prop, spec[prop], value)
        if values:
            objects[obj] = [{"properties": values}]
    visual = {"visualType": entry["guid"], "query": {"queryState": state}}
    if v.get("sort") and entry.get("sorting"):
        field, direction = (v["sort"] + ["asc"])[:2] if isinstance(v["sort"], list) else (v["sort"], "asc")
        visual["query"]["sortDefinition"] = {"sort": [{"field": _field(model, field)[2],
                                                       "direction": "Descending" if str(direction).lower().startswith("d")
                                                       else "Ascending"}], "isDefaultSort": False}
    if objects:
        visual["objects"] = objects
    visual["visualContainerObjects"] = _container(v, model) if atlas else NO_CHROME
    visual["drillFilterOtherVisuals"] = True
    return visual


def _stock_visual(v: dict, model: Model, entry: dict) -> dict:
    """Power BI's own visual (`type: pbi.<visualType>`): its wells by Power BI's role names, every Format-pane option
    from `format` (validated against Power BI's theme schema), Power BI's container with title and subtitle."""
    vt = entry["visualType"]
    ctx = stock.Ctx(lambda ref: _field(model, str(ref).strip()), v["id"])
    try:
        stock.check_fields(v, entry, lambda ref: _field(model, str(ref).strip())[0])
        objects, vco = stock.compile_format(vt, v.get("format"), ctx)
    except stock.FormatError as e:
        raise DefinitionError(str(e)) from e
    state: dict = {}
    drill = set(entry["drill"])
    for role, refs in (v.get("fields") or {}).items():
        refs = refs if isinstance(refs, list) else [refs]
        for i, ref in enumerate(refs):
            extra = {"active": i == 0} if role in drill and len(refs) > 1 else {}      # a drill hierarchy starts at its top
            state.setdefault(role, {"projections": []})["projections"].append(_projection(model, str(ref).strip(), **extra))
    visual = {"visualType": vt, "query": {"queryState": state}}
    if v.get("sort"):
        if not entry["sorting"]:
            raise DefinitionError(f"{v['id']}: {v['type']} has no sort order to set")
        field, direction = (list(v["sort"]) + ["asc"])[:2] if isinstance(v["sort"], list) else (v["sort"], "asc")
        visual["query"]["sortDefinition"] = {"sort": [{"field": _field(model, str(field).strip())[2],
                                                       "direction": "Descending" if str(direction).lower().startswith("d")
                                                       else "Ascending"}], "isDefaultSort": False}
    container = _container(v, model)
    if not v.get("subtitle"):            # a titled chart otherwise gets Power BI's automatic "X and Y by Z" subtitle
        container["subTitle"] = [{"properties": {"show": _lit(False)}}]
    for obj, entries in vco.items():     # the format's container settings win over title / subtitle
        if obj in container and len(entries) == 1 and "selector" not in entries[0]:
            props = {**container[obj][0]["properties"], **entries[0]["properties"]}
            if obj in ("title", "subTitle") and "text" in entries[0]["properties"] and "show" not in entries[0]["properties"]:
                props["show"] = _lit(True)
            container[obj] = [{"properties": props}]
        else:
            container[obj] = entries
    banded = any(p in (e.get("properties") or {}) for e in objects.get("values") or []
                 for p in ("backColorPrimary", "backColorSecondary", "fontColorPrimary", "fontColorSecondary"))
    if vt in ("tableEx", "pivotTable") and banded and "stylePreset" not in container:
        container["stylePreset"] = [{"properties": {"name": _lit("None")}}]   # Power BI ignores row colors under a style preset
    if objects:
        visual["objects"] = objects
    visual["visualContainerObjects"] = container
    visual["drillFilterOtherVisuals"] = True
    return visual


def _state(props: dict, state: str | None = None) -> dict:
    """One formatting entry; `state` targets a button state (default, hover, press, selected)."""
    return {"properties": props, **({"selector": {"id": state}} if state else {})}


def _slicer(v: dict, model: Model, theme: dict) -> dict:
    """Dropdown slicer drawn as one clean control: small muted label over a white rounded box,
    no card behind it (the card plus the dropdown's own box looked like a double border)."""
    font = theme.get("font", "Segoe UI")
    extra = {"active": True, **({"displayName": v["label"]} if v.get("label") else {})}
    general = {"outlineColor": _color(theme["card_border"]), "outlineWeight": _lit(1)}
    objects = {
        "data": [_state({"mode": _lit("Dropdown")})],
        "header": [_state({"show": _lit(True), "fontColor": _color(theme["muted"]), "textSize": _lit(9),
                           "fontFamily": _lit(font), "outline": _lit("None")})],
        "items": [_state({"fontColor": _color(theme["text"]), "textSize": _lit(10), "fontFamily": _lit(font),
                          "background": _color(theme["card_bg"]), "outline": _lit("Frame")})],
        # newer dropdown styling (Power BI base theme CY26SU10): rounded box, no accent bar
        "dropdown": [_state({"borderColor": _color(theme["card_border"]), "borderRadius": _lit(8),
                             "accentBarShow": _lit(False)})],
    }
    if v.get("single"):
        objects["selection"] = [_state({"strictSingleSelect": _lit(True)})]
    if v.get("default") is not None:
        _, table, prop = model.field(v["field"])
        value = v["default"]
        literal = f"{value}L" if isinstance(value, int) else "'" + str(value).replace("'", "''") + "'"
        general["filter"] = {"filter": {
            "Version": 2, "From": [{"Name": "d", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": prop}}],
                "Values": [[{"Literal": {"Value": literal}}]]}}}]}}
    objects["general"] = [_state(general)]
    visual = {"visualType": "slicer",
              "query": {"queryState": {"Values": {"projections": [_projection(model, v["field"], **extra)]}}},
              "objects": objects, "visualContainerObjects": NO_CHROME}
    if v.get("sync"):
        visual["syncGroup"] = {"groupName": v["sync"], "fieldChanges": True, "filterChanges": True}
    visual["drillFilterOtherVisuals"] = True
    return visual


def _page_navigator(theme: dict) -> dict:
    """Segmented control: a white rounded track with evenly spaced pill tabs; the current page is a solid
    accent pill with bold white text. Property names follow Power BI's navigator: `show` for fill, outline
    and accent bar is global (no state selector); colours/transparency/shape are per state."""
    font = theme.get("font", "Segoe UI")
    tint = theme.get("accent_tint", "#FBE7CC")
    pill = {"tileShape": _lit("pill")}
    return {"visualType": "pageNavigator",
            "objects": {
                "shape": [_state(pill, s) for s in ("default", "hover", "press", "selected")],
                "shapeCustomRectangle": [_state(pill, s) for s in ("default", "hover", "press", "selected")],
                "fill": [_state({"show": _lit(True)}),
                         _state({"fillColor": _color(theme["card_bg"]), "transparency": _lit(100)}, "default"),
                         _state({"fillColor": _color(tint), "transparency": _lit(0)}, "hover"),
                         _state({"fillColor": _color(tint), "transparency": _lit(0)}, "press"),
                         _state({"fillColor": _color(theme["accent"]), "transparency": _lit(0)}, "selected")],
                "text": [_state({"show": _lit(True)}),
                         _state({"fontColor": _color(theme["muted"]), "fontSize": _lit(11), "fontFamily": _lit(font),
                                 "bold": _lit(False)}, "default"),
                         _state({"fontColor": _color(theme["text"])}, "hover"),
                         _state({"fontColor": _color(theme["text"])}, "press"),
                         _state({"fontColor": _color("#FFFFFF"), "bold": _lit(True)}, "selected")],
                "outline": [_state({"show": _lit(False)})],
                "accentBar": [_state({"show": _lit(False)})],
                "layout": [_state({"cellPadding": _lit(6)})],
            },
            "visualContainerObjects": {
                "background": [_state({"show": _lit(True), "color": _color(theme["card_bg"]), "transparency": _lit(0)})],
                "border": [_state({"show": _lit(True), "color": _color(theme["card_border"]), "radius": _lit(22)})],
                "dropShadow": [_state({"show": _lit(False)})],
                "title": [_state({"show": _lit(False)})],
                "padding": [_state({k: _lit(4) for k in ("top", "bottom", "left", "right")})],
            },
            "drillFilterOtherVisuals": True}


def _textbox(v: dict, theme: dict) -> dict:
    paragraphs = []
    for runs in v["paragraphs"]:
        p = {"textRuns": [{"value": r["text"], "textStyle": {
            "fontFamily": theme.get("font", "Segoe UI"), "fontSize": r.get("size", "10pt"),
            "color": r.get("color", theme.get("text", "#1F1A17")), **({"fontWeight": "bold"} if r.get("bold") else {})}}
            for r in runs]}
        if v.get("align"):
            p["horizontalTextAlignment"] = v["align"]
        paragraphs.append(p)
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": NO_CHROME, "drillFilterOtherVisuals": True}


def _table(v: dict, model: Model) -> dict:
    query: dict = {"queryState": {"Values": {"projections": [_projection(model, f) for f in v["fields"]]}}}
    if v.get("sort"):
        ref, direction = v["sort"]
        query["sortDefinition"] = {"sort": [{"field": _field(model, ref)[2],
                                             "direction": "Descending" if direction == "desc" else "Ascending"}]}
    visual = {"visualType": "tableEx", "query": query, "drillFilterOtherVisuals": True}
    if v.get("title"):
        visual["visualContainerObjects"] = {"title": [{"properties": {"show": _lit(True), "text": _lit(v["title"])}}]}
    return visual


def _theme(t: dict) -> dict:
    """The report theme: Relay's own styles (page, slicers, navigator, tables) on top of the Visual Atlas theme
    when the definition picks a look or palette; every Atlas visual gets the look (Flat / Soft / 3D) as default."""
    from . import atlas
    theme = _base_theme(t)
    at = t.get("atlas_theme")
    if at:
        theme["name"] = at.get("name", "Relay")
        for key in ("good", "neutral", "bad", "maximum", "center", "minimum", "null", "firstLevelElements",
                    "secondLevelElements", "thirdLevelElements", "fourthLevelElements", "secondaryBackground"):
            if key in at:
                theme[key] = at[key]
        container = dict(at["visualStyles"]["*"]["*"])
        container["title"] = [{**(container.get("title") or [{}])[0], "fontFamily": t.get("font", "Segoe UI")}]
        theme["visualStyles"]["*"]["*"] = container
    for entry in atlas.catalog().values():          # Atlas families and custom visuals on the same framework
        defaults = atlas.theme_defaults(entry, t.get("look", "soft"))
        if defaults:
            theme["visualStyles"][entry["guid"]] = {"*": {obj: [props] for obj, props in defaults.items()}}
    from . import catalog
    from .definition import genbi_colors
    colors = {k: {"solid": {"color": c}} for k, c in genbi_colors(t).items()}   # Relay visuals follow the brand too
    for entry in catalog().values():
        if entry.get("family") not in ("atlas", "powerbi") and "colors" in entry.get("objects", {}):
            theme["visualStyles"][entry["guid"]] = {"*": {"colors": [colors]}}
    try:                                  # theme.styles: defaults for Power BI's own visuals, every Format-pane option
        styles = stock.theme_styles(t.get("styles"))
    except stock.FormatError as e:
        raise DefinitionError(str(e)) from e
    for vt, body in styles.items():
        slot = theme["visualStyles"].setdefault(vt, {"*": {}})["*"]
        for obj, rows in body["*"].items():
            slot[obj] = [{**((slot.get(obj) or [{}])[0] if obj in slot and len(slot[obj]) == 1 else {}), **rows[0]}] + rows[1:] \
                if rows else slot.get(obj, [])
    return theme


def _base_theme(t: dict) -> dict:
    font = t.get("font", "Segoe UI")
    solid = lambda c: {"solid": {"color": c}}
    return {
        "name": "Relay",
        "dataColors": t["data_colors"],
        "background": t["card_bg"], "foreground": t["text"], "tableAccent": t["accent"],
        "textClasses": {
            "callout": {"fontFace": font, "fontSize": 24, "color": t["text"]},
            "title": {"fontFace": font, "fontSize": 12, "color": t["text"]},
            "header": {"fontFace": font, "fontSize": 11, "color": t["text"]},
            "label": {"fontFace": font, "fontSize": 10, "color": t["muted"]},
        },
        "visualStyles": {
            "page": {"*": {"background": [{"color": solid(t["page_bg"]), "transparency": 0}],
                           "outspace": [{"color": solid(t["page_bg"]), "transparency": 0}]}},
            "*": {"*": {
                "background": [{"show": True, "color": solid(t["card_bg"]), "transparency": 0}],
                "border": [{"show": True, "color": solid(t["card_border"]), "radius": t.get("radius", 10)}],
                "dropShadow": [{"show": False}],
                "title": [{"show": True, "fontColor": solid(t["text"]), "fontSize": 12, "fontFamily": font, "bold": True}],
                "padding": [{"top": 10, "bottom": 10, "left": 12, "right": 12}],
            }},
            "slicer": {"*": {
                "data": [{"mode": "Dropdown"}],
                "header": [{"show": True, "fontColor": solid(t["muted"]), "fontFamily": font, "textSize": 9}],
                "items": [{"fontColor": solid(t["text"]), "fontFamily": font, "textSize": 10}],
                "padding": [{"top": 4, "bottom": 4, "left": 8, "right": 8}],
            }},
            "tableEx": {"*": {
                "grid": [{"gridVertical": False, "gridHorizontal": True, "gridHorizontalColor": solid(t["card_border"]),
                          "rowPadding": 4}],
                "columnHeaders": [{"fontColor": solid(t["muted"]), "backColor": solid(t["card_bg"]), "bold": True}],
                "values": [{"fontColorPrimary": solid(t["text"]), "backColorPrimary": solid(t["card_bg"]),
                            "fontColorSecondary": solid(t["text"]), "backColorSecondary": solid(t["page_bg"])}],
            }},
            "pageNavigator": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
        },
    }


def _load_visual_packages(visuals_dir: Path | None) -> dict[str, dict[str, bytes]]:
    """guid -> {relative path: bytes} for every .pbiviz: the Relay visuals in visuals_dir (newest version wins),
    then the Visual Atlas families, the visual library and the project's own custom visuals."""
    from . import atlas
    packages: dict[str, dict[str, bytes]] = {}
    found = list(visuals_dir.glob("*.pbiviz")) if visuals_dir and visuals_dir.is_dir() else []
    found = sorted(found, key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")[1:5]])
    for path in found + [path for _, path in atlas.package_paths()]:
        with zipfile.ZipFile(path) as z:
            guid = json.loads(z.read("package.json"))["visual"]["guid"]
            packages[guid] = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    return packages


def _report_files(defn: dict, model: Model, catalog: dict, packages: dict) -> tuple[dict[str, object], list[str]]:
    """All files of the PBIR report folder as {relative path: json object or bytes}; plus guids to import by hand."""
    files: dict[str, object] = {}
    used: set[str] = set()
    page_ids = []
    for page in defn["pages"]:
        pid = "ReportSection" + uuid.uuid5(uuid.NAMESPACE_URL, page["name"]).hex[:12]
        page_ids.append(pid)
        files[f"definition/pages/{pid}/page.json"] = {
            "$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": pid, "displayName": human(page["name"]),
            "displayOption": page.get("displayOption", "FitToWidth"), "height": page["height"], "width": 1280}
        names = set()
        for z, v in enumerate(page["visuals"]):
            v = _plain_visual(v)
            if v["type"] == "slicer":
                visual = _slicer(v, model, defn["theme"])
            elif v["type"] == "textbox":
                visual = _textbox(v, defn["theme"])
            elif v["type"] == "pageNavigator":
                visual = _page_navigator(defn["theme"])
            elif v["type"] == "table":
                visual = _table(v, model)
            elif stock.is_stock(v["type"]):
                visual = _stock_visual(v, model, stock.catalog()[v["type"]])
            else:
                visual = _custom_visual(v, model, catalog)
                used.add(visual["visualType"])
            alt = _alt_text(v) if v["type"] not in ("textbox", "pageNavigator") else None
            own_general = ((visual.get("visualContainerObjects") or {}).get("general") or [{}])[0].get("properties") or {}
            if alt and "altText" not in own_general:   # accessibility: Power BI's alt text (visualContainerObjects.general.altText)
                visual["visualContainerObjects"] = {**(visual.get("visualContainerObjects") or {}),
                                                    "general": [{"properties": {**own_general, "altText": _lit(alt)}}]}
            name = _visual_name(v["id"])
            if name in names:
                raise DefinitionError(f"Duplicate visual id {v['id']} on page {page['name']}")
            names.add(name)
            files[f"definition/pages/{pid}/visuals/{name}/visual.json"] = {
                "$schema": f"{SCHEMA}/visualContainer/2.13.0/schema.json", "name": name,   # newest published schema
                "position": {"x": v["x"], "y": v["y"], "z": (z + 1) * 1000, "height": v["h"], "width": v["w"]},
                "visual": visual}
    files["definition/pages/pages.json"] = {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json",
                                            "pageOrder": page_ids, "activePageName": page_ids[0]}
    files["definition/version.json"] = {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}
    resource_packages = [
        {"name": "SharedResources", "type": "SharedResources",
         "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
        {"name": "RegisteredResources", "type": "RegisteredResources",
         "items": [{"name": THEME_FILE, "path": THEME_FILE, "type": "CustomTheme"}]},
    ]
    for guid in sorted(used & packages.keys()):
        resource_packages.append({"name": guid, "type": "CustomVisual", "items": [
            {"name": f"{guid}.pbiviz.json", "path": f"{guid}.pbiviz.json", "type": "CustomVisualMetadata"}]})
        for rel, data in packages[guid].items():
            files[f"CustomVisuals/{guid}/{rel}"] = data
    files["definition/report.json"] = {
        "$schema": f"{SCHEMA}/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": REPORT_VERSION_AT_IMPORT, "type": "SharedResources"},
            "customTheme": {"name": THEME_FILE, "reportVersionAtImport": REPORT_VERSION_AT_IMPORT,
                            "type": "RegisteredResources"}},
        "resourcePackages": resource_packages,
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
    }
    files[f"StaticResources/RegisteredResources/{THEME_FILE}"] = _theme(defn["theme"])
    files[f"StaticResources/SharedResources/BaseThemes/{BASE_THEME}.json"] = (ASSETS / f"{BASE_THEME}.json").read_bytes()
    files["definition.pbir"] = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                                           "definitionProperties/2.0.0/schema.json", "version": "4.0",
                                "datasetReference": {"byPath": {"path": f"../{defn['name']}.SemanticModel"}}}
    return files, sorted(used - packages.keys())


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")


def build(defn: dict, catalog: dict, out: Path, visuals_dir: Path | None = None) -> Path:
    """Validate the definition and write the PBIP (PBIR report format, custom visuals embedded when
    their .pbiviz files are in visuals_dir). Returns the .pbip path."""
    model = Model(defn)
    model.validate()
    packages = _load_visual_packages(visuals_dir)
    report_files, missing = _report_files(defn, model, catalog, packages)   # validates visuals before writing
    name = defn["name"]
    semantic = {"definition.pbism": {"version": "1.0", "settings": {}}, "model.bim": _model_bim(defn, model)}
    out.mkdir(parents=True, exist_ok=True)
    for folder, files in ((out / f"{name}.Report", report_files), (out / f"{name}.SemanticModel", semantic)):
        shutil.rmtree(folder, ignore_errors=True)
        for rel, content in files.items():
            _write(folder / rel, content)
    _write(out / f"{name}.pbip", {"version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}],
                                  "settings": {"enableAutoRecovery": True}})
    if missing:
        print(f"note: import these custom visuals by hand (no .pbiviz found): {', '.join(missing)}")
    return out / f"{name}.pbip"
