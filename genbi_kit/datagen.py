"""Demo data: turn a dataset recipe (datagen.yaml) into CSVs in data/ - realistic, joined and reproducible.

The recipe lists the tables in order (lookup tables first) and how every column is made: ids, weighted choices,
numbers with a distribution, dates with a trend and seasonality, references to other tables (foreign keys),
lookups through them, formulas, and per-row rules (`when`) that plant the stories a dashboard should find. The
same recipe and seed always give the same files. Claude writes the recipe (its sandbox has no Python);
`genbi datagen` checks and runs it, and the app runs it again after the data stage.

    seed: 7
    period: {start: 2025-11-01, end: 2026-10-31}
    story: [TRIKAFTA is 70% of order value and growing, OTIF dips in September in APAC]
    tables:
      - name: products                                   # -> data/products.csv
        rows: [{product_id: P01, brand: TRIKAFTA, list_price: 26000}, ...]
      - name: customers
        count: 300
        columns:
          customer_id: {id: "C", width: 4}               # C0001 ...
          customer_name: {fake: company}
          region: {choice: {North America: 50, Europe: 35, APAC: 15}}
      - name: orders
        count: 20000
        columns:
          order_id: {id: "SO-", width: 6}
          order_date: {date: {trend: 0.25, weekdays: true}}
          customer_id: {ref: customers.customer_id, skew: 0.8}
          product_id: {ref: products.product_id, weights: {P01: 60}}
          region: {lookup: customers.region, by: customer_id}
          quantity: {int: {median: 6, spread: 0.6, min: 1, max: 60}}
          unit_price: {lookup: products.list_price, by: product_id, noise: 0.03}
          order_value: {formula: "quantity * unit_price", decimals: 2}
          on_time: {bool: 0.95, labels: [1, 0], when: [{if: "region == 'APAC' and month(order_date) == 9", p: 0.7}]}
"""
import ast
import bisect
import csv
import datetime as dt
import json
import math
import random
import re
import time
from pathlib import Path

import yaml

MAX_TABLE_ROWS = 1_000_000
MAX_TOTAL_ROWS = 2_000_000
MANIFEST = ".generated.json"
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KINDS = ("id", "choice", "int", "number", "date", "bool", "ref", "lookup", "formula", "fake", "pattern", "value")
COMMON = {"blank", "when", "decimals", "unique"}   # blank: share of empty cells (YAML reads a key named null as None)
EXTRA = {"id": {"width", "start"}, "ref": {"weights", "skew"}, "lookup": {"by", "noise"}, "bool": {"labels"}}   # labels: [true, false] values; YAML reads yes/no keys as booleans
PARAMS = {"int": {"min", "max", "mean", "sd", "median", "spread"}, "number": {"min", "max", "mean", "sd", "median", "spread"},
          "date": {"start", "end", "trend", "seasonality", "weekdays", "after", "days", "until"}}
FAKES = ("person", "first_name", "last_name", "company", "city", "email")
FIRST = ("Olivia Liam Emma Noah Ava Oliver Sophia Elijah Isabella James Mia William Amelia Benjamin Harper Lucas Evelyn "
         "Henry Abigail Theo Emily Jack Ella Leo Sofia Mateo Aria Ethan Chloe Daniel Priya Arjun Ananya Rohan Meera Wei "
         "Mei Hiro Yuki Lena Jonas Clara Felix Ines Pablo Lucia Omar Layla Kofi Amara Sean Niamh Erik Freya Luca Giulia "
         "Diego Valentina Ravi Kavya").split()
LAST = ("Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez Hernandez Lopez Wilson Anderson "
        "Thomas Taylor Moore Jackson Martin Lee Thompson White Harris Clark Lewis Walker Hall Young King Wright Patel "
        "Sharma Iyer Reddy Chen Wang Tanaka Sato Muller Schmidt Fischer Weber Dubois Moreau Rossi Bianchi Silva Santos "
        "Costa Kowalski Nowak Novak Jensen Larsen Murphy Kelly O'Brien Okafor Mensah Haddad").split()
COMPANY = (("North", "Blue", "Summit", "Harbor", "Pioneer", "Evergreen", "Silver", "Granite", "Cedar", "Atlas", "Meridian",
            "Crescent", "Riverside", "Golden", "Lakeside", "Sterling", "Bright", "Union", "Prime", "Apex", "Coastal",
            "Highland", "Keystone", "Liberty", "Oak", "Redwood", "Beacon", "Horizon", "Vista", "Allied"),
           ("Health", "Medical", "Pharma", "Retail", "Foods", "Logistics", "Supply", "Systems", "Labs", "Care", "Clinics",
            "Distribution", "Outfitters", "Markets", "Energy", "Motors", "Analytics", "Biotech", "Hospitality", "Freight"),
           ("Inc", "LLC", "Ltd", "Group", "Co", "Partners", "Holdings", "GmbH", "AG", "SA"))
CITIES = ("New York, Chicago, Houston, Phoenix, Boston, Seattle, Denver, Atlanta, Miami, Dallas, San Diego, Toronto, "
          "Vancouver, Montreal, Mexico City, Sao Paulo, Buenos Aires, London, Manchester, Dublin, Paris, Lyon, Berlin, "
          "Munich, Hamburg, Amsterdam, Brussels, Zurich, Vienna, Milan, Rome, Madrid, Barcelona, Lisbon, Stockholm, Oslo, "
          "Copenhagen, Helsinki, Warsaw, Prague, Istanbul, Dubai, Riyadh, Cairo, Lagos, Nairobi, Johannesburg, Mumbai, "
          "Delhi, Bengaluru, Chennai, Singapore, Bangkok, Jakarta, Manila, Hong Kong, Shanghai, Tokyo, Osaka, Seoul, "
          "Sydney, Melbourne, Auckland").split(", ")


class RecipeError(ValueError):
    pass


class _Loader(yaml.SafeLoader):
    """YAML 1.2 booleans: only true / false. PyYAML's YAML 1.1 also turns Yes, No, On, Off into booleans, which
    breaks labels like [Yes, No], rules like from_hub == 'Yes' and the country code NO."""


_Loader.yaml_implicit_resolvers = {k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
                                   for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def load(path: Path) -> dict:
    data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_Loader) or {}  # noqa: S506 - a SafeLoader
    if not isinstance(data, dict):
        raise RecipeError("datagen.yaml must be a mapping with seed, period, story and tables")
    return data


# ---------------------------------------------------------------- expressions (formulas and `when` rules)

FUNCS = ("month", "year", "quarter", "day", "weekday", "week", "t", "days", "date", "round", "min", "max", "abs",
         "rand", "randint", "normal", "int", "float", "str", "len", "lower", "upper", "replace", "season", "weekly")
NODES = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add,
         ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
         ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.IfExp, ast.Call, ast.Name, ast.Load, ast.Constant,
         ast.Tuple, ast.List)


def compile_expr(text, names: set[str], where: str):
    """A formula or rule: Python syntax over this row's earlier columns and FUNCS - nothing else."""
    try:
        tree = ast.parse(str(text), mode="eval")
    except SyntaxError as e:
        raise RecipeError(f"{where}: {text!r} is not a valid expression ({e.msg})") from None
    for node in ast.walk(tree):
        if not isinstance(node, NODES):
            raise RecipeError(f"{where}: {text!r} uses {node.__class__.__name__}, which recipes do not allow")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords):
            raise RecipeError(f"{where}: {text!r} calls something other than {', '.join(FUNCS)}")
        if isinstance(node, ast.Name) and node.id not in FUNCS and node.id not in names and node.id not in ("True", "False", "None"):
            raise RecipeError(f"{where}: {text!r} uses {node.id!r}, which is not an earlier column of this table "
                              f"(columns so far: {', '.join(sorted(names)) or 'none'})")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and not (
                isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)) and abs(node.right.value) <= 100):
            raise RecipeError(f"{where}: {text!r} - ** needs a constant exponent up to 100")
    return compile(tree, where, "eval")


def _helpers(rng: random.Random, start: dt.date, end: dt.date) -> dict:
    span = max((end - start).days, 1)
    asdate = lambda d: d.date() if isinstance(d, dt.datetime) else d
    return {"__builtins__": {}, "month": lambda d: d.month, "year": lambda d: d.year, "day": lambda d: d.day,
            "quarter": lambda d: (d.month - 1) // 3 + 1, "weekday": lambda d: d.isoweekday(),
            "week": lambda d: d.isocalendar()[1], "t": lambda d: (asdate(d) - start).days / span,
            "days": lambda a, b: (asdate(b) - asdate(a)).days, "date": dt.date, "round": round, "min": min, "max": max,
            "abs": abs, "rand": rng.random, "randint": rng.randint, "normal": rng.gauss, "int": int, "float": float,
            "str": str, "len": len, "lower": lambda s: str(s).lower(), "upper": lambda s: str(s).upper(),
            "replace": lambda s, a, b: str(s).replace(str(a), str(b)),
            "season": lambda d, w: float(w[d.month - 1]) if len(w) == 12 else 1.0,          # 12 monthly factors
            "weekly": lambda d, w: float(w[d.isoweekday() - 1]) if len(w) == 7 else 1.0,    # Monday ... Sunday
            "True": True, "False": False, "None": None}


# ---------------------------------------------------------------- checking the recipe

def _date(v, where: str) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError:
        raise RecipeError(f"{where}: {v!r} is not a date (write 2026-01-31)") from None


def default_period(months: int = 12, today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """The last `months` full months before today."""
    today = today or dt.date.today()
    end = today.replace(day=1) - dt.timedelta(days=1)
    y, m = end.year, end.month - months + 1
    while m < 1:
        y, m = y - 1, m + 12
    return dt.date(y, m, 1), end


def _ref(text, tables: dict, where: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*", str(text))
    if not m:
        raise RecipeError(f"{where}: write the reference as table.column, got {text!r}")
    t, c = m.groups()
    if t not in tables or t == "__current__":
        earlier = [k for k in tables if k != "__current__"]
        raise RecipeError(f"{where}: {t!r} is not an earlier table (tables so far: {', '.join(earlier) or 'none'})")
    if c not in tables[t]["names"]:
        raise RecipeError(f"{where}: {t} has no column {c!r} (it has {', '.join(tables[t]['names'])})")
    return t, c


def _pair(v, where: str) -> tuple[float, float]:
    if isinstance(v, dict):
        v = [v.get("min"), v.get("max")]
    if isinstance(v, (int, float)):
        v = [v, v]
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v) and v[0] <= v[1]):
        raise RecipeError(f"{where}: give a range like [1, 7] or {{min: 1, max: 7}}")
    return v[0], v[1]


def _column(tname: str, cname: str, spec, names: list[str], tables: dict) -> dict:
    where = f"{tname}.{cname}"
    if not NAME.match(cname):
        raise RecipeError(f"{where}: column names are letters, digits and _ (they become the CSV header)")
    if not isinstance(spec, dict):
        spec = {"value": spec}
    kinds = [k for k in spec if k in KINDS]
    if len(kinds) != 1:
        raise RecipeError(f"{where}: give exactly one of {', '.join(KINDS)} (got {', '.join(spec) or 'nothing'})")
    kind = kinds[0]
    col = {"name": cname, "kind": kind, "arg": spec[kind], "where": where}
    for k, v in spec.items():
        if k == kind:
            continue
        if k not in COMMON | EXTRA.get(kind, set()):
            raise RecipeError(f"{where}: unknown option {k!r} for {kind} (options: "
                              f"{', '.join(sorted(COMMON | EXTRA.get(kind, set())))})")
        col[k] = v
    arg, known = col["arg"], set(names)
    if kind == "id" and not isinstance(arg, str):
        raise RecipeError(f"{where}: id takes a prefix, e.g. {{id: \"C\", width: 4}}")
    if kind == "choice":
        if not isinstance(arg, (list, dict)) or not arg:
            raise RecipeError(f"{where}: choice takes a list of values or {{value: weight}}")
        col["values"] = list(arg) if isinstance(arg, dict) else list(arg)
        col["weights"] = [float(w) for w in arg.values()] if isinstance(arg, dict) else [1.0] * len(arg)
    if kind in ("int", "number"):
        if not isinstance(arg, dict) or not (set(arg) <= PARAMS[kind]):
            raise RecipeError(f"{where}: {kind} takes {{min, max}}, {{mean, sd}} or {{median, spread}} (plus min/max limits)")
        if not ({"min", "max"} <= set(arg) or "mean" in arg or "median" in arg):
            raise RecipeError(f"{where}: {kind} needs min and max, a mean (and sd) or a median (and spread)")
    if kind == "date":
        arg = col["arg"] = arg if isinstance(arg, dict) else {}
        if not set(arg) <= PARAMS["date"]:
            raise RecipeError(f"{where}: date options are {', '.join(sorted(PARAMS['date']))}")
        if "after" in arg:
            if arg["after"] not in known:
                raise RecipeError(f"{where}: after must name an earlier date column of this table")
            _pair(arg.get("days", [0, 0]), where + ".days")
        season = arg.get("seasonality")
        if season is not None and not (isinstance(season, list) and len(season) == 12) and not isinstance(season, dict):
            raise RecipeError(f"{where}: seasonality is 12 monthly weights [Jan ... Dec] or {{month number: weight}}")
    if kind == "bool":
        p = arg.get("p") if isinstance(arg, dict) else arg
        if not isinstance(p, (int, float)) or not 0 <= p <= 1:
            raise RecipeError(f"{where}: bool takes the probability of true, e.g. {{bool: 0.93}}")
        if "labels" in col and not (isinstance(col["labels"], list) and len(col["labels"]) == 2):
            raise RecipeError(f"{where}: labels is [value when true, value when false], e.g. [1, 0] or [Member, Guest]")
        col["arg"] = {"p": p}
    if kind == "ref":
        col["target"] = _ref(arg, tables, where)
    if kind == "lookup":
        col["source"] = _ref(arg, tables, where)
        by = col.get("by")
        by_col = tables["__current__"]["cols"].get(by)
        if by_col is None:
            raise RecipeError(f"{where}: lookup needs by: <an earlier column of this table that refers to "
                              f"{col['source'][0]}>")
        target = by_col.get("target")
        if not target or target[0] != col["source"][0]:
            raise RecipeError(f"{where}: by: {by} must be a ref to {col['source'][0]} (it is {by_col['kind']})")
        col["key"] = target
    if kind == "formula":
        col["code"] = compile_expr(arg, known, where)
    if kind == "fake" and arg not in FAKES:
        raise RecipeError(f"{where}: fake is one of {', '.join(FAKES)}")
    if kind == "pattern":
        for ref in re.findall(r"\{([A-Za-z_]\w*)", str(arg)):
            if ref != "n" and ref not in known:
                raise RecipeError(f"{where}: pattern uses {{{ref}}}, which is not n or an earlier column")
    if col.get("blank") is not None and not (isinstance(col["blank"], (int, float)) and 0 <= col["blank"] < 1):
        raise RecipeError(f"{where}: blank is the share of empty cells, e.g. 0.02")
    whens = col.get("when") or []
    if not isinstance(whens, list):
        raise RecipeError(f"{where}: when is a list of rules, e.g. [{{if: \"region == 'APAC'\", p: 0.8}}]")
    allowed = (PARAMS.get(kind, set()) | {"p", "times", "plus", "choice", "weights", "skew", "blank"}) - {"after"}
    col["whens"] = []
    for i, w in enumerate(whens):
        if not isinstance(w, dict) or "if" not in w:
            raise RecipeError(f"{where}: when[{i}] needs an if: condition")
        extra = set(w) - {"if"} - allowed
        if extra:
            raise RecipeError(f"{where}: when[{i}] cannot set {', '.join(sorted(extra))} (it can set {', '.join(sorted(allowed))})")
        rule = {k: v for k, v in w.items() if k != "if"}
        if "choice" in rule and not isinstance(rule["choice"], (list, dict)):
            raise RecipeError(f"{where}: when[{i}].choice takes a list or {{value: weight}}")
        col["whens"].append({"code": compile_expr(w["if"], known, f"{where}.when[{i}]"), **rule})
    return col


def check(recipe: dict, data_dir: Path) -> tuple[list[str], dict | None]:
    """Problems with a recipe (each names its table.column), and the checked plan to generate from."""
    try:
        return [], _plan(recipe, data_dir)
    except RecipeError as e:
        return [str(e)], None


def _plan(recipe: dict, data_dir: Path) -> dict:
    period = recipe.get("period") or {}
    if not isinstance(period, dict):
        raise RecipeError("period is {start: 2025-11-01, end: 2026-10-31} or {months: 12} (the last full months)")
    start, end = default_period(int(period.get("months") or 12))
    start = _date(period["start"], "period.start") if period.get("start") else start
    end = _date(period["end"], "period.end") if period.get("end") else end
    if end <= start:
        raise RecipeError("period: end must be after start")
    tables: dict = {}
    total = 0
    for i, t in enumerate(recipe.get("tables") or []):
        if not isinstance(t, dict) or not NAME.match(str(t.get("name", ""))):
            raise RecipeError(f"tables[{i}]: every table needs a name of letters, digits and _ (it becomes <name>.csv)")
        name = t["name"]
        if name in tables:
            raise RecipeError(f"tables[{i}]: two tables are named {name}")
        modes = [m for m in ("rows", "file", "count", "grid", "per") if m in t]
        if len(modes) != 1:
            raise RecipeError(f"{name}: give exactly one of rows (explicit rows), count (generated rows), grid "
                              f"(every combination), per (child rows for each parent row) or file (an uploaded CSV)")
        mode = modes[0]
        tab = {"name": name, "mode": mode, "file": t.get("file") or f"{name}.csv", "names": [], "cols": {}, "columns": []}
        tables["__current__"] = tab
        if mode == "file":
            path = data_dir / str(t["file"])
            if not path.is_file():
                raise RecipeError(f"{name}: {t['file']} is not in data/ (file: is for CSVs the user uploaded)")
            with open(path, encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f), [])
            tab["names"] = header
            tab["rows"] = sum(1 for _ in open(path, encoding="utf-8-sig")) - 1
        elif mode == "rows":
            if not isinstance(t["rows"], list) or not t["rows"] or not all(isinstance(r, dict) for r in t["rows"]):
                raise RecipeError(f"{name}: rows is a list of {{column: value}} rows")
            tab["names"] = list(dict.fromkeys(k for r in t["rows"] for k in r))
            for c in tab["names"]:
                if not NAME.match(str(c)):
                    raise RecipeError(f"{name}: column {c!r} - names are letters, digits and _")
            tab["rows"], tab["_rows"] = len(t["rows"]), t["rows"]
        elif mode == "count":
            if not isinstance(t["count"], int) or not 1 <= t["count"] <= MAX_TABLE_ROWS:
                raise RecipeError(f"{name}: count is a whole number of rows up to {MAX_TABLE_ROWS:,}")
            tab["rows"] = t["count"]
        elif mode == "grid":
            if not isinstance(t["grid"], dict) or not t["grid"]:
                raise RecipeError(f"{name}: grid is {{column: source}} - sources are months, weeks, days, a list or table.column")
            n = 1
            tab["grid"] = []
            for c, src in t["grid"].items():
                if not NAME.match(str(c)):
                    raise RecipeError(f"{name}.grid: column {c!r} - names are letters, digits and _")
                if isinstance(src, list):
                    k = len(src)
                elif src in ("months", "weeks", "days"):
                    k = len(_calendar(src, start, end))
                else:
                    src = _ref(src, tables, f"{name}.grid.{c}")
                    k = tables[src[0]]["rows"]                # distinct values: at most this many
                tab["grid"].append((c, src))
                tab["names"].append(c)
                tab["cols"][c] = {"kind": "grid", "target": src if isinstance(src, tuple) else None}
                n *= max(k, 1)
            if n > MAX_TABLE_ROWS:
                raise RecipeError(f"{name}: the grid makes {n:,} rows - at most {MAX_TABLE_ROWS:,}")
            tab["rows"] = n
        else:
            per = t["per"]
            if not isinstance(per, dict) or "ref" not in per:
                raise RecipeError(f"{name}: per is {{ref: parent.key, count: [min, max]}}")
            target = _ref(per["ref"], tables, f"{name}.per")
            lo, hi = _pair(per.get("count", [1, 1]), f"{name}.per.count")
            key = per.get("as") or target[1]
            tab["per"] = {"target": target, "count": (int(lo), int(hi)), "as": key}
            tab["names"].append(key)
            tab["cols"][key] = {"kind": "ref", "target": target}
            tab["rows"] = int(tables[target[0]]["rows"] * hi)
        cols = t.get("columns") or {}
        if mode == "file" and cols:
            raise RecipeError(f"{name}: a file table is used as it is (no columns)")
        if not isinstance(cols, dict):
            raise RecipeError(f"{name}: columns is a mapping {{column: how it is made}}")
        for cname, spec in cols.items():
            if cname in tab["names"]:
                raise RecipeError(f"{name}.{cname}: this column is already defined")
            col = _column(name, str(cname), spec, tab["names"], tables)
            if col.get("unique") and col["kind"] == "choice" and tab["rows"] > len(col["values"]):
                raise RecipeError(f"{name}.{cname}: unique choice needs at least as many values as rows ({tab['rows']})")
            tab["columns"].append(col)
            tab["cols"][cname] = col
            tab["names"].append(str(cname))
        if mode not in ("rows", "file") and not tab["columns"] and mode != "grid":
            raise RecipeError(f"{name}: add columns")
        total += tab["rows"]
        del tables["__current__"]
        tables[name] = tab
    if not tables:
        raise RecipeError("the recipe has no tables")
    if total > MAX_TOTAL_ROWS:
        raise RecipeError(f"the tables add up to about {total:,} rows - keep a demo under {MAX_TOTAL_ROWS:,}")
    files = [t["file"] for t in tables.values()]
    if len(set(files)) != len(files):
        raise RecipeError("two tables write the same file")
    keep = {}                       # columns other tables refer to: kept in memory while generating
    for t in tables.values():
        for c in t["cols"].values():
            for key in ("target", "source", "key"):
                if c.get(key):
                    keep.setdefault(c[key][0], set()).add(c[key][1])
    for name, t in tables.items():
        t["keep"] = keep.get(name, set())
    return {"seed": recipe.get("seed", 1), "start": start, "end": end, "tables": tables,
            "story": [story_text(s) for s in recipe.get("story") or []]}


def story_text(item) -> str:
    """A story line; YAML reads an unquoted "Seattle dips in September: longer waits" as a mapping."""
    if isinstance(item, dict):
        return "; ".join(f"{k}: {v}" for k, v in item.items())
    return str(item)


def _calendar(kind: str, start: dt.date, end: dt.date) -> list[dt.date]:
    if kind == "months":
        out, d = [], start.replace(day=1)
        while d <= end:
            out.append(d)
            d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return out
    step = 7 if kind == "weeks" else 1
    d = start - dt.timedelta(days=start.weekday()) if kind == "weeks" else start
    out = []
    while d <= end:
        out.append(d)
        d += dt.timedelta(days=step)
    return out


# ---------------------------------------------------------------- generating

def _cum(weights) -> list[float]:
    out, total = [], 0.0
    for w in weights:
        total += max(float(w), 0.0)
        out.append(total)
    if not out or out[-1] <= 0:
        raise RecipeError("all weights are zero")
    return out


def _pick(rng, values, cum):
    return values[bisect.bisect_right(cum, rng.random() * cum[-1])]


class _Table:
    """One table being generated: the columns other tables need stay in memory, the rest streams to the CSV."""

    def __init__(self, spec: dict):
        self.spec, self.n = spec, 0
        self.store = {c: [] for c in spec["keep"]}
        self.index: dict[str, dict] = {}

    def key_index(self, col: str) -> dict:
        if col not in self.index:
            idx = {}
            for i, v in enumerate(self.store[col]):
                if v is not None and v not in idx:
                    idx[v] = i
            self.index[col] = idx
        return self.index[col]


def generate(plan: dict, data_dir: Path) -> dict:
    """Write every table of a checked plan to data/<name>.csv. Returns a summary."""
    t0 = time.time()
    start, end = plan["start"], plan["end"]
    done: dict[str, _Table] = {}
    summary, warnings = [], []
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in plan["tables"].items():
        rng = random.Random(f"{plan['seed']}:{name}")
        table = _Table(spec)
        if spec["mode"] == "file":
            with open(data_dir / spec["file"], encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
                pos = {c: header.index(c) for c in table.store}
                for row in reader:
                    for c, i in pos.items():
                        table.store[c].append(row[i] if i < len(row) and row[i] != "" else None)
                    table.n += 1
        else:
            table.n = _write(spec, table, done, rng, plan, data_dir / spec["file"], warnings)
        for c in table.store:
            vals = [v for v in table.store[c] if v is not None]
            if spec_col_is_key(plan, name, c) and len(set(vals)) != len(vals):
                warnings.append(f"{name}.{c}: lookups go through it, but it has duplicate values - they take the first "
                                f"match (make it unique if it is a key)")
        done[name] = table
        summary.append({"table": name, "file": spec["file"], "rows": table.n, "columns": spec["names"],
                        "generated": spec["mode"] != "file",
                        "bytes": (data_dir / spec["file"]).stat().st_size})
    return {"tables": summary, "rows": sum(t["rows"] for t in summary), "seconds": round(time.time() - t0, 1),
            "seed": plan["seed"], "period": [start.isoformat(), end.isoformat()], "story": plan["story"],
            "warnings": warnings}


def spec_col_is_key(plan: dict, table: str, col: str) -> bool:
    """A column some lookup goes through (its values must identify one row)."""
    return any(c.get("key") == (table, col) for t in plan["tables"].values() for c in t["cols"].values())


def _sampler(col: dict, params: dict, rng: random.Random, plan: dict, done: dict):
    """A function row -> value for one column with one set of parameters."""
    kind = col["kind"]
    if kind == "choice":
        choice = params.get("choice", col["arg"])
        values = list(choice) if isinstance(choice, (list, dict)) else col["values"]
        weights = [float(w) for w in choice.values()] if isinstance(choice, dict) else [1.0] * len(values)
        cum = _cum(weights)
        return lambda row: _pick(rng, values, cum)
    if kind in ("int", "number"):
        p = {**col["arg"], **{k: v for k, v in params.items() if k in PARAMS[kind]}}
        lo, hi = p.get("min"), p.get("max")
        if "mean" in p:
            base = lambda: rng.gauss(p["mean"], p.get("sd", abs(p["mean"]) * 0.15 or 1))
        elif "median" in p:
            base = lambda: p["median"] * math.exp(rng.gauss(0, p.get("spread", 0.5)))
        elif kind == "int":
            base = lambda: rng.randint(int(lo), int(hi))
        else:
            base = lambda: rng.uniform(lo, hi)

        def num(row):
            x = base()
            if lo is not None:
                x = max(x, lo)
            if hi is not None:
                x = min(x, hi)
            return x
        return num
    if kind == "date":
        p = {**col["arg"], **{k: v for k, v in params.items() if k in PARAMS["date"]}}
        if "after" in p:
            lo, hi = _pair(p.get("days", [0, 0]), col["where"])

            def after(row):
                base = row.get(p["after"])
                if isinstance(base, str):                   # a date from an uploaded file
                    base = dt.date.fromisoformat(base[:10])
                if base is None:
                    return None
                d = base + dt.timedelta(days=rng.randint(int(lo), int(hi)))
                while p.get("weekdays") and d.weekday() >= 5:
                    d += dt.timedelta(days=1)
                return None if until and d > until else d          # not happened yet by `until`: blank
            until = _date(p["until"], col["where"] + ".until") if p.get("until") else None
            return after
        s = _date(p["start"], col["where"] + ".start") if p.get("start") else plan["start"]
        e = _date(p["end"], col["where"] + ".end") if p.get("end") else plan["end"]
        days = [s + dt.timedelta(days=i) for i in range((e - s).days + 1)]
        season = p.get("seasonality")
        month_w = (lambda m: float(season[m - 1])) if isinstance(season, list) else \
            (lambda m: float(season.get(m, 1))) if isinstance(season, dict) else (lambda m: 1.0)
        span = max(len(days) - 1, 1)
        trend = float(p.get("trend", 0))
        weights = [0.0 if p.get("weekdays") and d.weekday() >= 5 else month_w(d.month) * max(1 + trend * i / span, 0.01)
                   for i, d in enumerate(days)]
        cum = _cum(weights)
        return lambda row: _pick(rng, days, cum)
    if kind == "bool":
        pr = float(params.get("p", col["arg"]["p"]))
        yes, no = col.get("labels") or (True, False)
        return lambda row: yes if rng.random() < pr else no
    if kind == "ref":
        t, c = col["target"]
        keys = [v for v in dict.fromkeys(done[t].store[c]) if v is not None]
        if not keys:
            raise RecipeError(f"{col['where']}: {t}.{c} has no values to refer to")
        skew = float(params.get("skew", col.get("skew", 0)) or 0)
        weights = [1 / (i + 1) ** skew for i in range(len(keys))]
        given = params.get("weights", col.get("weights")) or {}
        for k, w in given.items():
            for i, key in enumerate(keys):
                if str(key) == str(k):
                    weights[i] = float(w)
        cum = _cum(weights)
        return lambda row: _pick(rng, keys, cum)
    raise RecipeError(f"{col['where']}: {kind} cannot be sampled")


def _fake(kind: str, rng: random.Random) -> str:
    if kind == "first_name":
        return rng.choice(FIRST)
    if kind == "last_name":
        return rng.choice(LAST)
    if kind == "person":
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    if kind == "company":
        a, b, c = COMPANY
        return f"{rng.choice(a)} {rng.choice(b)} {rng.choice(c)}"
    if kind == "city":
        return rng.choice(CITIES)
    first, last = rng.choice(FIRST), rng.choice(LAST)
    return f"{first}.{last}".lower().replace("'", "") + "@" + rng.choice(("example.com", "mail.example", "corp.example"))


def _cell(v, decimals) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        return f"{v:.{decimals}f}" if decimals else str(int(round(v)))
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def _write(spec: dict, table: _Table, done: dict, rng: random.Random, plan: dict, path: Path, warnings: list) -> int:
    helpers = _helpers(rng, plan["start"], plan["end"])
    cols = spec["columns"]
    samplers: dict = {}
    whens = {c["name"]: c["whens"] for c in cols}
    ids = {c["name"]: c.get("start", 1) for c in cols if c["kind"] == "id"}
    lookups = {}
    for c in cols:
        if c["kind"] == "lookup":
            (st, sc), (kt, kc) = c["source"], c["key"]
            lookups[c["name"]] = (done[st].key_index(kc), done[st].store[sc])
    uniques = {}
    for c in cols:
        if c.get("unique") and c["kind"] == "choice":
            pool = list(c["values"])
            rng.shuffle(pool)
            uniques[c["name"]] = iter(pool)

    def base_rows():
        mode = spec["mode"]
        if mode == "count":
            for _ in range(spec_rows):
                yield {}
        elif mode == "rows":
            for r in raw_rows:
                yield {k: (_date(v, f"{spec['name']}.rows") if isinstance(v, dt.date) else v) for k, v in r.items()}
        elif mode == "grid":
            axes = []
            for c, src in spec["grid"]:
                if isinstance(src, list):
                    axes.append(src)
                elif isinstance(src, str):
                    axes.append(_calendar(src, plan["start"], plan["end"]))
                else:
                    axes.append([v for v in dict.fromkeys(done[src[0]].store[src[1]]) if v is not None])
            names = [c for c, _ in spec["grid"]]

            def combos(i, acc):
                if i == len(axes):
                    yield dict(zip(names, acc))
                    return
                for v in axes[i]:
                    yield from combos(i + 1, acc + [v])
            yield from combos(0, [])
        else:
            per = spec["per"]
            t, c = per["target"]
            lo, hi = per["count"]
            for key in [v for v in done[t].store[c] if v is not None]:
                for _ in range(rng.randint(lo, hi)):
                    yield {per["as"]: key}

    spec_rows = spec.get("rows") if spec["mode"] == "count" else 0
    raw_rows = spec.get("_rows", [])
    names = spec["names"]
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(names)
        for row in base_rows():
            n += 1
            for c in cols:
                name = c["name"]
                matched = tuple(i for i, rule in enumerate(whens[name]) if _truth(rule["code"], helpers, row))
                params = {}
                times, plus = 1.0, 0.0
                for i in matched:
                    rule = whens[name][i]
                    params.update({k: v for k, v in rule.items() if k not in ("code", "times", "plus")})
                    times *= float(rule.get("times", 1))
                    plus += float(rule.get("plus", 0))
                blank = params.get("blank", c.get("blank"))         # a rule can blank a column for some rows
                if blank and rng.random() < float(blank):
                    row[name] = None
                    continue
                kind = c["kind"]
                try:
                    if kind == "id":
                        v = f"{c['arg']}{str(ids[name]).zfill(int(c.get('width', 0) or 0))}"
                        ids[name] += 1
                    elif kind == "value":
                        v = c["arg"]
                    elif kind == "formula":
                        v = eval(c["code"], helpers, row)  # noqa: S307 - compile_expr allows arithmetic only
                    elif kind == "lookup":
                        idx, values = lookups[name]
                        i = idx.get(row.get(c["by"]))
                        v = values[i] if i is not None else None
                        if c.get("noise") and isinstance(v, (int, float)) and not isinstance(v, bool):
                            v = v * (1 + rng.gauss(0, float(c["noise"])))
                    elif kind == "fake":
                        v = _fake(c["arg"], rng)
                    elif kind == "pattern":
                        v = re.sub(r"\{([A-Za-z_]\w*)(?::([^}]*))?\}",
                                   lambda m: format(n if m.group(1) == "n" else row.get(m.group(1), ""), m.group(2) or ""),
                                   str(c["arg"]))
                    elif name in uniques:
                        v = next(uniques[name])
                    else:
                        key = (name, matched)
                        if key not in samplers:
                            samplers[key] = _sampler(c, params, rng, plan, done)
                        v = samplers[key](row)
                except (TypeError, ValueError, ZeroDivisionError, KeyError):
                    v = None                    # a formula over a blank, or an impossible value: leave it blank
                if isinstance(v, (int, float)) and not isinstance(v, bool) and (times != 1 or plus):
                    v = v * times + plus
                if kind == "int" and isinstance(v, float):
                    v = int(round(v))
                elif kind in ("number", "formula", "lookup") and isinstance(v, float) and c.get("decimals") is not None:
                    v = round(v, int(c["decimals"]))
                row[name] = v
            for c in table.store:
                table.store[c].append(row.get(c))
            w.writerow([_cell(row.get(c), _decimals(spec, c)) for c in names])
    if n == 0:
        warnings.append(f"{spec['name']}: no rows were generated")
    return n


def _truth(code, helpers, row) -> bool:
    try:
        return bool(eval(code, helpers, row))  # noqa: S307 - compile_expr allows arithmetic and comparisons only
    except (TypeError, ValueError, ZeroDivisionError):
        return False                            # a rule over a blank value does not apply


def _decimals(spec: dict, col: str) -> int:
    c = spec["cols"].get(col) or {}
    if c.get("decimals") is not None:
        return int(c["decimals"])
    return 0 if c.get("kind") == "int" else 2


# ---------------------------------------------------------------- the files of a project

def run(workdir: Path, recipe_file: str = "datagen.yaml") -> dict:
    """Check and generate a project's recipe into data/; files the previous run generated but this one does not
    are removed (uploaded files are never touched). Raises RecipeError with every problem."""
    recipe = load(workdir / recipe_file)
    problems, plan = check(recipe, workdir / "data")
    if problems:
        raise RecipeError("; ".join(problems))
    manifest = workdir / "data" / MANIFEST
    before = set(json.loads(manifest.read_text(encoding="utf-8")).get("files", [])) if manifest.exists() else set()
    summary = generate(plan, workdir / "data")
    made = [t["file"] for t in summary["tables"] if t["generated"]]
    for stale in before - set(made):
        (workdir / "data" / stale).unlink(missing_ok=True)
    manifest.write_text(json.dumps({"recipe": recipe_file, "seed": plan["seed"], "files": made,
                                    "when": time.time()}, indent=1), encoding="utf-8")
    return summary


def generated_files(workdir: Path) -> set[str]:
    manifest = workdir / "data" / MANIFEST
    try:
        return set(json.loads(manifest.read_text(encoding="utf-8")).get("files", []))
    except (OSError, ValueError):
        return set()
