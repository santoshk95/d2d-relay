"""Validation shared by the `genbi` CLI and the web app."""
import re
from pathlib import Path

from . import catalog
from . import data as data_mod
from . import definition, prototype, report_builder

from .dax_names import RESERVED

BAD_VAR = re.compile(r"\bVAR\s+(top|low)\b", re.I)
VAR_NAME = re.compile(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.I)


def reserved_vars(expr: str) -> list[str]:
    """Variables named like a DAX function or keyword (ignoring case) — Power BI rejects the measure."""
    body = DAX_ATOMS.sub(" ", str(expr))
    return sorted({m.group(1) for m in VAR_NAME.finditer(body) if m.group(1).upper() in RESERVED})
# strings, 'quoted names', [references] and comments: removed before checking the DAX structure
DAX_ATOMS = re.compile(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'|\[[^\]]*\]|//[^\n]*|--[^\n]*|/\*.*?\*/', re.S)


def dax_lint(expr: str) -> list[str]:
    """Cheap syntax checks for mistakes Power BI would reject (it has no DAX parser here)."""
    body = DAX_ATOMS.sub(" x ", str(expr))
    out = []
    if '"' in body:
        out.append("unterminated string")
    if "'" in body:
        out.append("unterminated 'quoted' table name")
    if "[" in body or "]" in body:
        out.append("unbalanced [ ]")
    depth = 0
    for ch in body:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth < 0:
            break
    if depth:
        out.append("unbalanced parentheses")
    if re.search(r",\s*[,)]|\(\s*,", body):
        out.append("empty argument (stray comma)")
    if re.search(r"\bVAR\b", body, re.I) and not re.search(r"\bRETURN\b", body, re.I):
        out.append("VAR without RETURN")
    if re.search(r"[,+\-*/&|=<>]$", body.strip()):
        out.append("ends with an operator or comma")
    for name in reserved_vars(expr):
        out.append(f"variable '{name}' has the name of a DAX function or keyword ({name.upper()}); Power BI rejects "
                   f"the measure and every measure that uses it — rename the variable (e.g. '{name}Value' is fine)")
    return out


def plan(p: dict) -> list[str]:
    errors = []
    kpis = p.get("kpis") or []
    if not kpis:
        errors.append("plan.yaml needs a non-empty `kpis` list")
    seen = set()
    for i, k in enumerate(kpis):
        for key in ("name", "label", "description", "dax", "format"):
            if key not in k:
                errors.append(f"kpis[{i}] is missing `{key}`")
        name = str(k.get("name", "")).lower()
        if name in seen:
            errors.append(f"duplicate KPI name {k.get('name')}")
        seen.add(name)
        if k.get("format") is not None and not isinstance(k["format"], str):
            errors.append(f"KPI {k.get('name')}: {_unquoted(k['format'])}")
        for problem in dax_lint(k.get("dax", "")):
            errors.append(f"KPI {k.get('name')}: DAX {problem}")
    if not p.get("pages"):
        errors.append("plan.yaml needs `pages` (name, purpose, visuals)")
    return errors + custom_visual_errors(p.get("custom_visuals"))


CHOICES = ("generate", "available")


def custom_visual_errors(items) -> list[str]:
    """plan.yaml `custom_visuals`: new visuals proposed where nothing in the catalog fits; the user decides."""
    from .vfactory import NAME
    if items is None:
        return []
    if not isinstance(items, list):
        return ["`custom_visuals` must be a list (or left out)"]
    errors, seen, cat = [], set(), {n.lower(): e for n, e in catalog().items()}
    for i, v in enumerate(items):
        if not isinstance(v, dict):
            errors.append(f"custom_visuals[{i}] must be a mapping (name, title, need, fields, fallback, recommend)")
            continue
        for key in ("name", "title", "need", "fallback"):
            if not str(v.get(key) or "").strip():
                errors.append(f"custom_visuals[{i}] is missing `{key}`")
        name = str(v.get("name") or "")
        if name and not NAME.match(name):
            errors.append(f"custom_visuals[{i}]: name {name!r} must be camelCase letters and digits (e.g. radialBars)")
        existing = cat.get(name.lower())
        if existing and existing.get("origin") != "project":
            where = "in the visual library" if existing.get("origin") == "library" else "in the catalog"
            errors.append(f"custom_visuals[{i}]: {name} already exists {where} — use it instead of proposing it")
        if name.lower() in seen:
            errors.append(f"custom_visuals: {name} is proposed twice")
        seen.add(name.lower())
        for key in ("recommend", "decision"):
            if v.get(key) is not None and v.get(key) not in CHOICES:
                errors.append(f"custom_visuals[{i}].{key} must be generate or available")
    return errors


def _unquoted(value) -> str:
    return (f"format must be a quoted string — YAML read {value!r} as a number, which loses the format "
            f"(write it in quotes, e.g. format: \"0.0\")")


VISUALS_MODES = {"relay": "Relay custom visuals (and Power BI's own where they fit)",
                 "builtin": "Power BI's built-in visuals only (pbi.*): no custom visual in the report",
                 "mixed": "Power BI's built-in visuals first; a custom visual only where no built-in visual does the job"}
NATIVE = {"slicer", "textbox", "pageNavigator", "table"}       # what the builder writes as Power BI's own visuals already
# the closest built-in visual for each custom visual, for the message when a report must use built-in visuals only
BUILTIN_FOR = {"kpiCard": "pbi.cardVisual (or pbi.kpi with a trend axis)", "trendLine": "pbi.lineChart", "driverBars": "pbi.clusteredBarChart",
               "quadrant": "pbi.scatterChart", "treemap": "pbi.treemap", "heatmap": "pbi.pivotTable with a gradient on values.backColor",
               "funnel": "pbi.funnel", "narrative": "a textbox, or pbi.cardVisual with the insight text measures",
               "atlasColumns": "pbi.clusteredColumnChart / pbi.columnChart / pbi.clusteredBarChart", "atlasLines": "pbi.lineChart / pbi.areaChart",
               "atlasParts": "pbi.donutChart / pbi.pieChart", "atlasGauges": "pbi.cardVisual / pbi.kpi / pbi.gauge",
               "atlasFinance": "pbi.waterfallChart / pbi.funnel", "atlasScatter": "pbi.scatterChart", "atlasHierarchy": "pbi.treemap / pbi.decompositionTreeVisual",
               "atlasTime": "pbi.pivotTable with a gradient (calendar heatmap) / pbi.lineChart", "atlasDistribution": "pbi.scatterChart / pbi.clusteredColumnChart",
               "atlasCompare": "pbi.clusteredBarChart", "atlasFlow": "pbi.decompositionTreeVisual / pbi.pivotTable",
               "atlasProportion": "pbi.treemap / pbi.donutChart", "atlasText": "pbi.tableEx"}


def visuals_mode(workdir: Path | None, raw: dict | None = None) -> str:
    """Which visuals the report may use: the project's choice (project.json `visuals_mode`), else the definition's
    `visuals_mode`, else relay."""
    import json
    mode = None
    pj = Path(workdir) / "project.json" if workdir else None
    if pj is not None and pj.is_file():
        try:
            mode = json.loads(pj.read_text(encoding="utf-8")).get("visuals_mode")
        except (OSError, ValueError):
            mode = None
    mode = mode or (raw or {}).get("visuals_mode") or "relay"
    return mode if mode in VISUALS_MODES else "relay"


def visuals_mode_errors(d: dict, mode: str) -> list[str]:
    """Under `builtin`, every data visual must be one of Power BI's own."""
    if mode != "builtin":
        return []
    from . import stock
    out = []
    for page in d.get("pages", []):
        for v in page.get("visuals", []):
            t = v.get("type")
            if t in NATIVE or stock.is_stock(t):
                continue
            out.append(f"{page['name']} / {v['id']}: {t} is a custom visual, but this report uses Power BI's built-in visuals only "
                       f"(request.md, Visuals) — use {BUILTIN_FOR.get(t, 'a pbi.<visual> type')} (`genbi catalog pbi`)")
    return out


PLAIN_FILE = re.compile(r'^[^\\/:*?"<>|.][^\\/:*?"<>|]*$')       # a file in data/: no folder, drive or leading dot


def source_errors(raw: dict) -> list[str]:
    """Where tables read from. The Power BI file is refreshed on the D2D Relay PC, so a table reads only a file of its
    own data folder (csv / extract), DAX or a generated date table: never Power Query written by hand."""
    out = []
    for t in raw.get("tables") or []:
        if not isinstance(t, dict):
            continue
        if "m" in t:
            out.append(f"table {t.get('name')}: Power Query written by hand (m:) is not allowed; use csv:, extract:, "
                       f"dax: or date_table")
        for key in ("csv", "extract"):
            if key in t and not (isinstance(t[key], str) and PLAIN_FILE.match(t[key])):
                out.append(f"table {t.get('name')}: {key}: must name a file in data/, without a folder: {t[key]!r}")
    return out


def definition_errors(raw: dict, workdir: Path, check_sql: bool = True) -> tuple[list[str], dict | None]:
    """All problems with a definition (model, DAX references, visuals, optional prototype SQL)."""
    errors = [f"[{m.get('name')}]: {_unquoted(m['format'])}" for m in (raw.get("measures") or [])
              if isinstance(m, dict) and m.get("format") is not None and not isinstance(m["format"], str)]
    errors += source_errors(raw)
    if errors:
        return errors, None
    try:
        d = definition.expand(raw)
    except Exception as e:  # noqa: BLE001
        return [f"definition: {e}"], None
    model = report_builder.Model(d)
    try:
        model.validate()
    except report_builder.DefinitionError as e:
        errors += [line.strip() for line in str(e).splitlines()[1:] if line.strip()] or [str(e)]
    for m in d["measures"]:
        errors += [f"[{m['name']}]: DAX {p}" for p in dax_lint(m["expression"])]
    for c in d.get("calculated_columns", []):
        errors += [f"{c.get('table')}[{c.get('name')}]: DAX {p}" for p in dax_lint(c.get("expression", ""))]
    for t in d["tables"]:
        if t.get("dax"):
            errors += [f"table {t['name']}: DAX {p}" for p in dax_lint(t["dax"])]
    for page in d["pages"]:
        ids = [v["id"] for v in page["visuals"]]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            errors.append(f"page {page['name']}: duplicate visual ids {dup}")
    errors += visuals_mode_errors(d, visuals_mode(workdir, raw))
    if not errors and d["pages"]:          # a model-only definition (no pages yet) is a valid first step
        try:
            report_builder._report_files(d, model, catalog(), {})
        except report_builder.DefinitionError as e:
            errors.append(str(e))
    if check_sql and not errors and d["pages"]:
        con = data_mod.connect(Path(workdir), d)
        _, sql_errors = prototype.build_pages(d, con)
        errors += sql_errors
    return errors, d
