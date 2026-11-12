"""Power BI's own visuals ("stock" or built-in visuals) with every Format-pane option.

A definition uses one as `type: pbi.<visualType>` (pbi.clusteredColumnChart, pbi.lineChart, pbi.cardVisual, pbi.kpi, ...).
Nothing is embedded in the PBIP: Power BI draws them itself, so they work in every tenant (including those that block
custom visuals), in exports, subscriptions, mobile and Copilot.

Where everything comes from:
- The field wells (data roles), their limits and the field combinations each visual accepts are Power BI's own: read
  from Power BI Desktop 2.159 (dataRoles / dataViewMappings conditions in its bundles) and checked against
  Microsoft's PBIR authoring references. Friendly aliases (axis, legend, values, smallMultiples, ...) map to them.
- Every formatting object and property, with its type and allowed values, comes from Power BI's report-theme schema
  (`schemas/powerbi/reportThemeSchema.json`, version 5.78, extracted from the same Desktop install; Microsoft also
  publishes it under MIT in microsoft/powerbi-desktop-samples). Objects of the visual itself go to `objects`, the
  shared container objects (title, subTitle, background, border, dropShadow, padding, visualHeader, visualTooltip, ...)
  to `visualContainerObjects`, exactly as Power BI Desktop writes them.
- Value encoding follows what Desktop writes: typed literals (`12D`, `3L`, `'Top'`), colors as solid fills or theme
  colors (ThemeDataColor), selectors per series (metadata), per category value (scopeId), per data point
  (dataViewWildcard) or per instance (`id`, e.g. the new card's objects need `id: default`), conditional formatting
  by field value (a measure that returns a color or a text) and by gradient (FillRule linearGradient2 / 3).

The HTML prototype draws these visuals with assets/stock_visuals.js from the same prototype SQL convention as the
Visual Atlas visuals: one column per field, named after the field.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import KIT

SCHEMA_FILE = KIT / "schemas" / "powerbi" / "reportThemeSchema.json"
SCHEMA_VERSION = "5.78"
PREFIX = "pbi."
G, M, GM = "Grouping", "Measure", "GroupingOrMeasure"
MEASURE = re.compile(r"^\[([^\]]+)\]$")
COLUMN = re.compile(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class FormatError(ValueError):
    pass


def _r(name, kind, max_=None, label=None, aliases=(), description=""):
    return {"name": name, "kind": kind, "max": max_, "label": label or name, "aliases": list(aliases),
            "description": description}


def _cartesian(horizontal: bool, y2: bool = False, series_label: str = "Legend", y_label: str | None = None,
               small_multiples: bool = True, gradient: bool = False) -> list[dict]:
    axis, values = ("Y-axis", "X-axis") if horizontal else ("X-axis", "Y-axis")
    roles = [_r("Category", G, None, axis, ("axis", "category", "categories"),
                "the categories or dates along the axis; several fields make a drill hierarchy (top level first)"),
             _r("Y", M, None, y_label or values, ("values", "value", "y" if not horizontal else "x"),
                "one or more measures; each measure is a series (or one measure split by the legend)"),
             _r("Series", G, 1, series_label, ("legend", "series"), "splits one measure into a series per value")]
    if y2:
        roles.append(_r("Y2", M, None, "Line y-axis" if y_label else "Secondary y-axis",
                        ("lineValues", "line", "lineY", "y2", "secondaryValues"), "measures drawn as lines on the secondary axis"))
    if small_multiples:
        roles.append(_r("Rows", G, 1, "Small multiples", ("smallMultiples", "multiples"), "one small chart per value"))
    if gradient:
        roles.append(_r("Gradient", M, 1, "Color saturation", ("colorSaturation", "gradient"), "colors the bars by a measure"))
    roles.append(_r("Tooltips", M, None, "Tooltips", ("tooltips", "tooltip"), "extra measures shown on hover"))
    return roles


def _spec(label, group, roles, required, drill=(), notes="", conditions=(), sorting=True, renderer=None, first_only=()):
    """first_only: wells of which the prototype draws the first field only (its SQL returns just that column)."""
    return {"label": label, "group": group, "roles": roles, "required": [list(x) for x in required], "drill": list(drill),
            "notes": notes, "conditions": [dict(c) for c in conditions], "sorting": sorting, "renderer": renderer,
            "first_only": list(first_only)}


# One measure per series when a legend splits it (Desktop: Series used -> Y max 1).
ONE_Y_WITH_SERIES = ({"Series": 0}, {"Series": 1, "Y": 1})

SPECS = {
    # cards
    "cardVisual": _spec("Card (new)", "Cards", [
        _r("Data", M, None, "Data", ("values", "value", "data", "fields", "measures"), "one or more measures: one callout each"),
        _r("ReferenceLabels", M, None, "Reference labels", ("referenceLabels", "reference", "comparison", "comparisons"),
           "measures shown under the callout (vs last year, vs target)")],
        [["Data"]], notes="Microsoft's current card: several measures in one visual, reference labels, accent bar, "
                          "images. Most of its objects need `state: default` (added for you).", sorting=False, renderer="cardVisual"),
    "card": _spec("Card (classic)", "Cards", [_r("Values", GM, 1, "Fields", ("value", "values", "field", "measure"), "one value")],
                  [["Values"]], notes="Legacy card; prefer pbi.cardVisual.", sorting=False, renderer="card"),
    "multiRowCard": _spec("Multi-row card", "Cards", [_r("Values", GM, None, "Fields", ("values", "fields", "columns"), "the values per row")],
                          [["Values"]], notes="Legacy; prefer pbi.cardVisual with several measures.", renderer="multiRowCard"),
    "kpi": _spec("KPI", "Cards", [
        _r("Indicator", M, 1, "Value", ("value", "indicator", "actual"), "the measure"),
        _r("TrendLine", G, 1, "Trend axis", ("trend", "trendline", "axis", "date"), "a date or month column: the trend behind the value"),
        _r("Goal", M, 2, "Target", ("target", "goal", "goals"), "one or two targets the value is compared with")],
        [["Indicator", "TrendLine"]], sorting=False, renderer="kpi"),
    "gauge": _spec("Gauge", "Cards", [
        _r("Y", M, 1, "Value", ("value", "values"), "the measure"),
        _r("MinValue", M, 1, "Minimum value", ("min", "minimum")), _r("MaxValue", M, 1, "Maximum value", ("max", "maximum")),
        _r("TargetValue", M, 1, "Target value", ("target",)), _r("Tooltips", M, None, "Tooltips", ("tooltips",))],
        [["Y"]], sorting=False, renderer="gauge"),
    # columns and bars
    "clusteredColumnChart": _spec("Clustered column chart", "Columns & bars", _cartesian(False, gradient=True), [["Y"]],
                                  drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar"),
    "columnChart": _spec("Stacked column chart", "Columns & bars", _cartesian(False, gradient=True), [["Y"]],
                         drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar"),
    "hundredPercentStackedColumnChart": _spec("100% stacked column chart", "Columns & bars", _cartesian(False, gradient=True), [["Y"]],
                                              drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar"),
    "clusteredBarChart": _spec("Clustered bar chart", "Columns & bars", _cartesian(True, gradient=True), [["Y"]],
                               drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar"),
    "barChart": _spec("Stacked bar chart", "Columns & bars", _cartesian(True, gradient=True), [["Y"]],
                      drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar"),
    "hundredPercentStackedBarChart": _spec("100% stacked bar chart", "Columns & bars", _cartesian(True, gradient=True), [["Y"]],
                                           drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar"),
    "ribbonChart": _spec("Ribbon chart", "Columns & bars", _cartesian(False, small_multiples=False), [["Category", "Y"]],
                         drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="bar",
                         notes="Stacked columns joined by ribbons that show the rank changing."),
    "waterfallChart": _spec("Waterfall chart", "Columns & bars", [
        _r("Category", G, 1, "Category", ("axis", "category"), "the steps (months, drivers)"),
        _r("Breakdown", G, 1, "Breakdown", ("breakdown",), "splits each step's change into its contributors"),
        _r("Y", M, 1, "Y-axis", ("value", "values"), "the measure whose changes are shown"),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["Category", "Y"], ["Breakdown", "Y"]], renderer="waterfall"),
    # lines and areas
    "lineChart": _spec("Line chart", "Lines & areas", _cartesian(False, y2=True), [["Category", "Y"], ["Category", "Y2"]],
                       drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="line"),
    "areaChart": _spec("Area chart", "Lines & areas", _cartesian(False), [["Category", "Y"]], drill=["Category"],
                       conditions=ONE_Y_WITH_SERIES, renderer="line"),
    "stackedAreaChart": _spec("Stacked area chart", "Lines & areas", _cartesian(False), [["Category", "Y"]], drill=["Category"],
                              conditions=ONE_Y_WITH_SERIES, renderer="line"),
    "hundredPercentStackedAreaChart": _spec("100% stacked area chart", "Lines & areas", _cartesian(False), [["Category", "Y"]],
                                            drill=["Category"], conditions=ONE_Y_WITH_SERIES, renderer="line"),
    "lineClusteredColumnComboChart": _spec("Line and clustered column chart", "Lines & areas",
                                           _cartesian(False, y2=True, series_label="Column legend", y_label="Column y-axis"),
                                           [["Category", "Y"], ["Category", "Y2"]], drill=["Category"], conditions=ONE_Y_WITH_SERIES,
                                           renderer="combo", notes="Columns on the primary axis (Y), lines on the secondary (Y2)."),
    "lineStackedColumnComboChart": _spec("Line and stacked column chart", "Lines & areas",
                                         _cartesian(False, y2=True, series_label="Column legend", y_label="Column y-axis"),
                                         [["Category", "Y"], ["Category", "Y2"]], drill=["Category"], conditions=ONE_Y_WITH_SERIES,
                                         renderer="combo"),
    # parts of a whole
    "pieChart": _spec("Pie chart", "Parts of a whole", [
        _r("Category", G, 1, "Legend", ("legend", "category", "slices"), "one slice per value"),
        _r("Series", G, 1, "Details", ("details",), "splits each slice"),
        _r("Y", M, None, "Values", ("values", "value"), "the measure (several measures = one slice each, without a legend)"),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["Y"]], conditions=ONE_Y_WITH_SERIES, renderer="pie"),
    "donutChart": _spec("Donut chart", "Parts of a whole", [
        _r("Category", G, 1, "Legend", ("legend", "category", "slices"), "one slice per value"),
        _r("Series", G, 1, "Details", ("details",), "splits each slice"),
        _r("Y", M, None, "Values", ("values", "value"), "the measure (several measures = one slice each, without a legend)"),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["Y"]], conditions=ONE_Y_WITH_SERIES, renderer="pie"),
    "treemap": _spec("Treemap", "Parts of a whole", [
        _r("Group", G, 1, "Category", ("category", "group"), "the rectangles"),
        _r("Details", G, 1, "Details", ("details",), "smaller rectangles inside each"),
        _r("Values", M, None, "Values", ("values", "value", "size"), "the size of each rectangle"),
        _r("Gradient", M, 1, "Color saturation", ("colorSaturation", "gradient")),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["Values"]],
        conditions=({"Details": 0}, {"Details": 1, "Values": 1}), renderer="treemap"),
    "funnel": _spec("Funnel", "Parts of a whole", [
        _r("Category", G, 1, "Category", ("category", "stage", "stages"), "the stages"),
        _r("Y", M, None, "Values", ("values", "value"), "the measure (several measures = one stage each, without a category)"),
        _r("Gradient", M, 1, "Color saturation", ("colorSaturation", "gradient")),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["Y"]],
        conditions=({"Category": 0}, {"Category": 1, "Y": 1}), renderer="funnel"),
    # relationships and flows
    "scatterChart": _spec("Scatter chart", "Relationships", [
        _r("Category", G, None, "Values", ("details", "values", "category"), "one bubble per value"),
        _r("Series", G, 1, "Legend", ("legend", "series")),
        _r("X", M, 1, "X-axis", ("x", "xAxis")), _r("Y", M, 1, "Y-axis", ("y", "yAxis")),
        _r("Size", M, 1, "Size", ("size", "bubbleSize")), _r("Play", G, 1, "Play axis", ("play", "playAxis"), "animates over time"),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["X", "Y"]], renderer="scatter"),
    "decompositionTreeVisual": _spec("Decomposition tree", "AI visuals", [
        _r("Analyze", M, 1, "Analyze", ("analyze", "value", "measure"), "the measure to break down"),
        _r("ExplainBy", G, None, "Explain by", ("explainBy", "breakdowns", "by"), "the columns a person can split by"),
        _r("Tooltips", M, None, "Tooltips", ("tooltips",))], [["Analyze", "ExplainBy"]], sorting=False, renderer="decomposition",
        first_only=["ExplainBy"], notes="People expand it level by level in Power BI; the prototype shows the first split "
                                         "(its SQL returns the first Explain by column and the measure)."),
    "keyDriversVisual": _spec("Key influencers", "AI visuals", [
        _r("Target", GM, 1, "Analyze", ("analyze", "target"), "the outcome to explain"),
        _r("ExplainBy", GM, None, "Explain by", ("explainBy", "factors")),
        _r("Details", G, None, "Expand by", ("expandBy", "details"))], [["Target", "ExplainBy"]], sorting=False, renderer="keyDrivers",
        notes="Power BI runs the analysis itself; the prototype shows the inputs only."),
    # tables and slicers
    "tableEx": _spec("Table", "Tables", [_r("Values", GM, None, "Columns", ("columns", "fields", "values"), "the columns, in order")],
                     [["Values"]], renderer="table"),
    "pivotTable": _spec("Matrix", "Tables", [
        _r("Rows", G, None, "Rows", ("rows",), "row headers; several fields make a stepped hierarchy"),
        _r("Columns", G, None, "Columns", ("columns",), "column headers"),
        _r("Values", M, None, "Values", ("values", "value", "measures"), "the measures in the cells")],
        [["Values"], ["Rows"]], renderer="matrix"),
    "slicer": _spec("Slicer", "Tables", [_r("Values", G, None, "Field", ("field", "values"), "the column to filter by (several = hierarchy)")],
                    [["Values"]], sorting=False, renderer="slicer",
                    notes="A slicer on one page; report-wide synced slicers come from `filters`."),
    # maps
    "map": _spec("Map (bubbles)", "Maps", [
        _r("Category", G, None, "Location", ("location", "category")), _r("Series", G, 1, "Legend", ("legend",)),
        _r("Y", G, 1, "Latitude", ("latitude",)), _r("X", G, 1, "Longitude", ("longitude",)),
        _r("Size", M, 1, "Bubble size", ("size", "values", "value")), _r("Tooltips", M, None, "Tooltips", ("tooltips",))],
        [["Category"], ["X", "Y"]], sorting=False, renderer="map",
        notes="Power BI geocodes locations online (Bing); set the column's data category in the model for best results."),
    "filledMap": _spec("Filled map", "Maps", [
        _r("Category", G, None, "Location", ("location", "category")), _r("Series", G, 1, "Legend", ("legend",)),
        _r("Y", G, 1, "Latitude", ("latitude",)), _r("X", G, 1, "Longitude", ("longitude",)),
        _r("Tooltips", M, None, "Tooltips", ("tooltips", "values"))], [["Category"]], sorting=False, renderer="map",
        notes="Shades countries, states or regions; Power BI geocodes them online."),
}

# Objects of the new card that only apply with an instance selector (Desktop silently drops them otherwise).
ID_OBJECTS = {"cardVisual": {"outline", "accentBar", "fillCustom", "shape", "label", "value", "layout", "spacing", "padding",
                             "divider", "image", "shadowCustom", "glowCustom", "referenceLabelTitle", "referenceLabelValue",
                             "referenceLabelDetail"}}
CONTAINER_SKIP = {"*", "actionButtonSection"}
# display units: Desktop writes them as doubles
DOUBLE_INTS = {"labelDisplayUnits", "displayUnits", "detailLabelDisplayUnits", "indicatorDisplayUnits", "secLabelDisplayUnits"}
WILDCARD = {"all": 1, "instances": 1, "totals": 2, "everything": 0}


# ---------------------------------------------------------------- the schema

@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _resolve(s: dict) -> dict:
    ref = s.get("$ref")
    if ref:
        target = schema()["definitions"].get(ref.split("/")[-1], {})
        return {**target, **{k: v for k, v in s.items() if k != "$ref"}, "_ref": ref.split("/")[-1]}
    return s


def _ptype(s: dict) -> dict:
    """A theme-schema property -> {kind: bool|number|int|enum|color|text|complex, values?, labels?, min?, max?, title}."""
    s = _resolve(s)
    out = {"title": s.get("title") or "", "description": s.get("description") or ""}
    ref = s.get("_ref")
    if ref == "fill" or ref in ("colorOrThemeColor", "color"):
        return {**out, "kind": "color"}
    one = s.get("oneOf") or s.get("anyOf")
    if one and all("const" in o for o in one):
        return {**out, "kind": "enum", "values": [o["const"] for o in one], "labels": [o.get("title") or str(o["const"]) for o in one]}
    t = s.get("type")
    t = t if isinstance(t, list) else [t]
    if "boolean" in t and len(t) == 1:
        return {**out, "kind": "bool"}
    if "integer" in t and len(t) == 1:
        return {**out, "kind": "int"}
    if "number" in t:
        return {**out, "kind": "number", **({"min": s["minimum"]} if "minimum" in s else {}), **({"max": s["maximum"]} if "maximum" in s else {})}
    if "integer" in t:
        return {**out, "kind": "int"}
    if "string" in t and len(t) == 1:
        return {**out, "kind": "text"}
    return {**out, "kind": "complex", "ref": ref or "/".join(x for x in t if x)}


def _objects_of(defn: dict) -> dict:
    out = {}
    for part in defn.get("allOf") or [defn]:
        for obj, o in (part.get("properties") or {}).items():
            if obj in CONTAINER_SKIP or "$ref" in o and "items" not in o:
                continue
            props = ((o.get("items") or {}).get("properties")) or {}
            props = {p: s for p, s in props.items() if not p.startswith("$")}      # "$id" is theme syntax: use `state`
            if props:
                out[obj] = {p: _ptype(s) for p, s in props.items()}
    return out


@lru_cache(maxsize=1)
def container() -> dict:
    """The container objects every visual shares (visualContainerObjects)."""
    return _objects_of(schema()["definitions"]["commonCards"])


@lru_cache(maxsize=64)
def objects(vt: str) -> dict:
    """The visual's own formatting objects (objects), from the theme schema."""
    d = schema()["definitions"].get(f"visual-{vt}")
    if not d:
        return {}
    return {o: p for o, p in _objects_of({"allOf": [x for x in d.get("allOf", []) if "$ref" not in x]}).items()}


# ---------------------------------------------------------------- the catalog

@lru_cache(maxsize=1)
def catalog() -> dict:
    """`pbi.<visualType>` -> catalog entry (same shape as the Visual Atlas entries, family "powerbi")."""
    out = {}
    for vt, s in SPECS.items():
        roles = {r["name"]: r["kind"] for r in s["roles"]}
        info = {r["name"]: {"displayName": r["label"], "description": r["description"], "max": r["max"], "aliases": r["aliases"]}
                for r in s["roles"]}
        out[PREFIX + vt] = {
            "name": PREFIX + vt, "visualType": vt, "guid": vt, "family": "powerbi", "origin": "powerbi",
            "displayName": s["label"], "description": s["notes"], "group": s["group"], "roles": roles, "role_info": info,
            "required": s["required"], "drill": s["drill"], "sorting": s["sorting"], "conditions": s["conditions"],
            "renderer": s["renderer"], "first_only": s["first_only"], "objects": objects(vt), "container": container(), "chart_types": [],
            "id_objects": sorted(ID_OBJECTS.get(vt, ()))}
    return out


def is_stock(vtype) -> bool:
    return isinstance(vtype, str) and vtype.startswith(PREFIX) and vtype[len(PREFIX):] in SPECS


def role_of(entry: dict, well: str) -> str | None:
    """A well name or one of its aliases (any case) -> the Power BI role name."""
    w = str(well).strip()
    for r in entry["roles"]:
        if r.lower() == w.lower():
            return r
    for r, i in entry["role_info"].items():
        if w.lower() in (a.lower() for a in i["aliases"]):
            return r
    return None


def canonical_fields(v: dict, entry: dict) -> dict:
    """The visual's `fields` with Power BI's role names (aliases resolved); unknown wells raise FormatError."""
    out = {}
    for well, refs in (v.get("fields") or {}).items():
        role = role_of(entry, well)
        if not role:
            wells = ", ".join(f"{r} ({i['displayName']})" for r, i in entry["role_info"].items())
            raise FormatError(f"{v.get('id')}: {entry['name']} has no field well '{well}' (wells: {wells})")
        refs = refs if isinstance(refs, list) else [refs]
        out.setdefault(role, []).extend(refs)
    return {r: (x if len(x) > 1 or entry["role_info"][r]["max"] != 1 else x[0]) for r, x in out.items()}


def check_fields(v: dict, entry: dict, kind_of) -> None:
    """Power BI's rules for the wells: column vs measure, limits, the combinations it accepts, the fields it needs.
    kind_of(ref) -> "Column" | "Measure"."""
    counts = {}
    for role, refs in (v.get("fields") or {}).items():
        refs = refs if isinstance(refs, list) else [refs]
        counts[role] = len(refs)
        want, cap = entry["roles"][role], entry["role_info"][role]["max"]
        for ref in refs:
            kind = kind_of(ref)
            if want == G and kind != "Column":
                raise FormatError(f"{v['id']}: well {role} ({entry['role_info'][role]['displayName']}) takes a column, got {ref}")
            if want == M and kind != "Measure":
                raise FormatError(f"{v['id']}: well {role} ({entry['role_info'][role]['displayName']}) takes a measure, got {ref} - "
                                  f"make a measure for it")
        if cap is not None and len(refs) > cap and role not in entry["drill"]:
            raise FormatError(f"{v['id']}: well {role} ({entry['role_info'][role]['displayName']}) takes at most {cap} field"
                              f"{'s' if cap != 1 else ''}, got {len(refs)}")
    if entry["conditions"]:
        ok = False
        for c in entry["conditions"]:
            if all((counts.get(r, 0) <= n) if n else counts.get(r, 0) == 0 for r, n in c.items()):
                ok = True
                break
        if not ok:
            rule = " or ".join("(" + ", ".join(f"{r} {'≤ ' + str(n) if n else 'empty'}" for r, n in c.items()) + ")" for c in entry["conditions"])
            raise FormatError(f"{v['id']}: Power BI does not accept this combination of fields in {entry['name']}: {rule}")
    need = entry["required"]
    if need and not any(all(counts.get(r) for r in group) for group in need):
        raise FormatError(f"{v['id']}: {entry['name']} needs the fields " + " or ".join(" + ".join(g) for g in need))


# ---------------------------------------------------------------- format -> PBIR objects

def _lit(value, kind: str = "auto") -> dict:
    if isinstance(value, bool):
        v = "true" if value else "false"
    elif kind == "int" and isinstance(value, (int, float)):
        v = f"{int(value)}L"
    elif isinstance(value, (int, float)):
        v = f"{int(value) if float(value).is_integer() else value}D"
    else:
        v = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": v}}}


def _scalar(value) -> dict:
    """A literal for a selector or a rule bound (strings quoted, integers L, decimals D)."""
    if isinstance(value, bool):
        return {"Literal": {"Value": "true" if value else "false"}}
    if isinstance(value, int):
        return {"Literal": {"Value": f"{value}L"}}
    if isinstance(value, float):
        return {"Literal": {"Value": f"{value}D"}}
    text = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return {"Literal": {"Value": f"datetime'{text}T00:00:00'"}}
    return {"Literal": {"Value": "'" + text.replace("'", "''") + "'"}}


class Ctx:
    """What the format compiler needs from the model: field expressions and query names."""

    def __init__(self, field, vid: str):
        self.field = field          # ref -> (kind, queryRef, PBIR field expression)
        self.vid = vid

    def expr(self, ref: str) -> dict:
        return self.field(ref)[2]

    def query(self, ref: str) -> str:
        return self.field(ref)[1]


def _color(value, ctx: Ctx, where: str) -> tuple[dict, bool]:
    """(PBIR fill value, data_bound). Hex, theme color, a measure returning a color, or a gradient rule."""
    if isinstance(value, str) and HEX.match(value):
        return {"solid": {"color": _lit(value.upper())}}, False
    if isinstance(value, str) and re.fullmatch(r"theme:\d+(?:[+-]\d+(?:\.\d+)?)?", value.strip()):
        m = re.fullmatch(r"theme:(\d+)([+-]\d+(?:\.\d+)?)?", value.strip())
        return {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": int(m.group(1)), "Percent": float(m.group(2) or 0)}}}}}, False
    if isinstance(value, dict) and "theme" in value:
        return {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": int(value["theme"]), "Percent": float(value.get("percent", 0))}}}}}, False
    if isinstance(value, str) and MEASURE.match(value.strip()):
        return {"solid": {"color": {"expr": ctx.expr(value.strip())}}}, True
    if isinstance(value, dict) and "gradient" in value:
        g = value["gradient"]
        if not isinstance(g, dict) or not g.get("input") or not g.get("min") or not g.get("max"):
            raise FormatError(f"{ctx.vid}: {where}: a gradient needs input (a measure), min and max colors (and optional mid)")
        stops = {}
        for stop in ("min", "mid", "max"):
            if g.get(stop) is None:
                continue
            if not (isinstance(g[stop], str) and HEX.match(g[stop])):
                raise FormatError(f"{ctx.vid}: {where}: gradient {stop} must be a hex color like \"#1F6FEB\" (theme colors render black in gradients)")
            stops[stop] = {"color": {"Literal": {"Value": f"'{g[stop].upper()}'"}}}
            if g.get(f"{stop}Value") is not None:
                stops[stop]["value"] = {"Literal": {"Value": f"{g[stop + 'Value']}D"}}
        nulls = g.get("nulls", "asZero")
        if nulls not in ("asZero", "noColor", "specificColor"):
            raise FormatError(f"{ctx.vid}: {where}: gradient nulls must be asZero or noColor")
        rule = {"linearGradient3" if "mid" in stops else "linearGradient2": {**stops, "nullColoringStrategy": {"strategy": {"Literal": {"Value": f"'{nulls}'"}}}}}
        return {"solid": {"color": {"expr": {"FillRule": {"Input": ctx.expr(str(g["input"]).strip()), "FillRule": rule}}}}}, True
    raise FormatError(f"{ctx.vid}: {where} needs a color: \"#RRGGBB\", theme:N (a palette color, e.g. theme:0 or theme:2-0.25), "
                      f"a measure returning a color (\"[Bar Color]\") or {{gradient: {{input, min, max}}}}; got {value!r}")


def _value(spec: dict, value, ctx: Ctx, where: str) -> tuple[dict, bool]:
    """One property value -> (PBIR value, data_bound)."""
    if isinstance(value, dict) and "raw" in value:                    # escape hatch: exact PBIR value
        return value["raw"], False
    kind = spec["kind"]
    if kind == "color":
        return _color(value, ctx, where)
    if isinstance(value, str) and MEASURE.match(value.strip()) and kind in ("text", "number", "int", "enum"):
        return {"expr": ctx.expr(value.strip())}, True             # field value: a measure returns the text / number
    if kind == "bool":
        if not isinstance(value, bool):
            raise FormatError(f"{ctx.vid}: {where} needs true or false, got {value!r}")
        return _lit(value), False
    if kind == "enum":
        values, labels = spec["values"], spec["labels"]
        for v, label in zip(values, labels):
            if value == v or (isinstance(value, str) and (str(v).lower() == value.lower() or label.lower() == value.lower())):
                return (_lit(v, "number") if isinstance(v, (int, float)) and not isinstance(v, bool) else _lit(v)), False
        shown = ", ".join(f"{v}" + (f" ({lab})" if str(v) != lab else "") for v, lab in zip(values, labels))
        raise FormatError(f"{ctx.vid}: {where} must be one of {shown}; got {value!r}")
    if kind in ("number", "int"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FormatError(f"{ctx.vid}: {where} needs a number, got {value!r}")
        lo, hi = spec.get("min"), spec.get("max")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise FormatError(f"{ctx.vid}: {where} must be between {lo} and {hi}, got {value}")
        prop = where.split(".")[-1]
        return _lit(value, "number" if prop in DOUBLE_INTS else kind), False
    if kind == "text":
        return _lit(str(value)), False
    raise FormatError(f"{ctx.vid}: {where} is a structured property ({spec.get('ref')}); give the exact Power BI value as "
                      f"{{raw: ...}} (see `genbi catalog` for the object) or leave it out")


def _selector(entry_vt: str, obj: str, item: dict, ctx: Ctx, data_bound: bool, is_container: bool, gradient: bool) -> dict | None:
    target, state = item.get("for"), item.get("state")
    if is_container:
        if target is not None or state is not None:
            raise FormatError(f"{ctx.vid}: {obj} is part of the visual's container - it takes no `for` / `state`")
        return None
    sel: dict = {}
    if isinstance(target, str) and target.strip().lower() in WILDCARD:
        sel["data"] = [{"dataViewWildcard": {"matchingOption": WILDCARD[target.strip().lower()]}}]
    elif isinstance(target, str) and (MEASURE.match(target.strip()) or COLUMN.match(target.strip())):
        sel["metadata"] = ctx.query(target.strip())
    elif isinstance(target, dict):
        if len(target) != 1:
            raise FormatError(f"{ctx.vid}: {obj}: `for` names one field and its value, e.g. for: {{\"Store[Region]\": North}}")
        (ref, val), = target.items()
        if not COLUMN.match(str(ref).strip()):
            raise FormatError(f"{ctx.vid}: {obj}: `for` needs a column, got {ref}")
        sel["data"] = [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left": ctx.expr(str(ref).strip()), "Right": _scalar(val)}}}]
    elif target is not None:
        raise FormatError(f"{ctx.vid}: {obj}: `for` is a measure (\"[Net Sales]\"), a column value ({{\"Store[Region]\": North}}) "
                          f"or all / totals / everything; got {target!r}")
    if data_bound and "data" not in sel:
        # a measure-driven or gradient value is evaluated per data point (Desktop's own wildcard selector): per cell
        # of one column in a table or matrix (with its metadata), per bar / slice in a chart
        sel["data"] = [{"dataViewWildcard": {"matchingOption": 1 if "metadata" in sel or not gradient else 0}}]
    if state is not None:
        sel["id"] = str(state)
    elif obj in ID_OBJECTS.get(entry_vt, ()):
        sel["id"] = "default"
    return sel or None


def compile_format(vt: str, fmt: dict | None, ctx: Ctx) -> tuple[dict, dict]:
    """A definition's `format` -> (objects, visualContainerObjects) in Power BI's JSON.

    Each object is a mapping of properties, or a list of them; an entry may add `for` (a measure, a column value or
    all / totals) and `state` (an instance id such as default, hover, Row)."""
    own, shared = objects(vt), container()
    objs, vco = {}, {}
    for obj, body in (fmt or {}).items():
        if obj not in own and obj not in shared:
            near = sorted(set(own) | set(shared))
            raise FormatError(f"{ctx.vid}: pbi.{vt} has no format object '{obj}' (objects: {', '.join(near)})")
        is_container = obj not in own
        props_spec = own.get(obj) or shared[obj]
        items = body if isinstance(body, list) else [body]
        out = []
        for item in items:
            if not isinstance(item, dict):
                raise FormatError(f"{ctx.vid}: format.{obj} must be a mapping of properties (or a list of them)")
            values, bound, gradient = {}, False, False
            for prop, value in item.items():
                if prop in ("for", "state"):
                    continue
                spec = props_spec.get(prop)
                if spec is None:
                    raise FormatError(f"{ctx.vid}: unknown property {obj}.{prop} for pbi.{vt} "
                                      f"(properties: {', '.join(sorted(props_spec))})")
                if value is None or value == "":
                    continue
                pbir, data_bound = _value(spec, value, ctx, f"{obj}.{prop}")
                values[prop] = pbir
                bound |= data_bound
                gradient |= isinstance(value, dict) and "gradient" in value
            if is_container and bound:
                bound = False                                           # containers evaluate a measure for the whole visual
            entry = {"properties": values}
            sel = _selector(vt, obj, item, ctx, bound, is_container, gradient)
            if sel:
                entry["selector"] = sel
            if values or sel:
                out.append(entry)
        if out:
            (vco if is_container else objs)[obj] = out
    return objs, vco


# ---------------------------------------------------------------- report theme (visualStyles for built-in visuals)

def theme_value(spec: dict, value, where: str):
    """A value for the report theme's visualStyles (plain JSON, not PBIR expressions)."""
    if spec["kind"] == "color":
        if isinstance(value, str) and HEX.match(value):
            return {"solid": {"color": value.upper()}}
        raise FormatError(f"theme.styles {where} needs a hex color like \"#1F6FEB\", got {value!r}")
    if spec["kind"] == "enum":
        for v, label in zip(spec["values"], spec["labels"]):
            if value == v or (isinstance(value, str) and (str(v).lower() == value.lower() or label.lower() == value.lower())):
                return v
        raise FormatError(f"theme.styles {where} must be one of {', '.join(map(str, spec['values']))}; got {value!r}")
    if spec["kind"] == "bool" and not isinstance(value, bool):
        raise FormatError(f"theme.styles {where} needs true or false, got {value!r}")
    if spec["kind"] in ("number", "int") and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise FormatError(f"theme.styles {where} needs a number, got {value!r}")
    if spec["kind"] == "complex":
        if isinstance(value, dict) and "raw" in value:
            return value["raw"]
        raise FormatError(f"theme.styles {where} is structured; give it as {{raw: ...}}")
    return value


def theme_styles(styles: dict | None) -> dict:
    """`theme.styles` -> report theme visualStyles: {visualType | "*": {object: {prop: value} | [..]}}."""
    out = {}
    for vt, objs in (styles or {}).items():
        key = vt[len(PREFIX):] if str(vt).startswith(PREFIX) else str(vt)
        if key != "*" and key not in SPECS:
            raise FormatError(f"theme.styles: unknown visual {vt} (use pbi.<visual> names from `genbi catalog pbi`, or \"*\")")
        own = objects(key) if key != "*" else {}
        shared = container()
        styled = {}
        for obj, body in (objs or {}).items():
            spec = own.get(obj) or shared.get(obj)
            if spec is None:
                raise FormatError(f"theme.styles {vt}: no format object '{obj}'")
            items = body if isinstance(body, list) else [body]
            rows = []
            for item in items:
                row = {}
                for prop, value in item.items():
                    if prop == "state":
                        row["$id"] = str(value)
                        continue
                    if prop not in spec:
                        raise FormatError(f"theme.styles {vt}: unknown property {obj}.{prop}")
                    row[prop] = theme_value(spec[prop], value, f"{vt}.{obj}.{prop}")
                if key in ID_OBJECTS and obj in ID_OBJECTS[key] and "$id" not in row:
                    row["$id"] = "default"
                rows.append(row)
            styled[obj] = rows
        out[key] = {"*": styled}
    return out


# ---------------------------------------------------------------- the prototype

def plain(spec: dict, value):
    """A format value as the prototype renderer reads it (hex colors, enum consts, numbers, measure refs as-is)."""
    if spec["kind"] == "enum":
        for v, label in zip(spec["values"], spec["labels"]):
            if value == v or (isinstance(value, str) and (str(v).lower() == value.lower() or label.lower() == value.lower())):
                return v
    return value


def prototype_format(vt: str, fmt: dict | None, styles: dict | None = None) -> dict:
    """{object: {"_": {prop: value}, "for": [{target, props}]}} merged over the theme's styles for this visual."""
    own, shared = objects(vt), container()
    out: dict = {}

    def add(obj, item):
        spec = own.get(obj) or shared.get(obj) or {}
        props = {p: plain(spec.get(p, {"kind": "text"}), v) for p, v in item.items() if p not in ("for", "state", "$id")}
        slot = out.setdefault(obj, {"_": {}, "for": []})
        target = item.get("for")
        if target is None or (isinstance(target, str) and target.strip().lower() in WILDCARD):
            slot["_"].update(props)
        else:
            slot["for"].append({"target": target, "props": props})

    for src in ((styles or {}).get("*"), (styles or {}).get(vt), (styles or {}).get(PREFIX + vt), fmt):
        for obj, body in (src or {}).items():
            for item in (body if isinstance(body, list) else [body]):
                if isinstance(item, dict):
                    add(obj, item)
    return out


def describe(entry: dict) -> list[str]:
    """`genbi catalog pbi.<visual>`: wells, rules and every format object with its properties and allowed values."""
    lines = [f"{entry['name']}: {entry['displayName']} - Power BI's built-in visual '{entry['visualType']}'"
             + (f". {entry['description']}" if entry.get("description") else "")]
    lines.append("  fields (well: what it takes - aliases):")
    for r, k in entry["roles"].items():
        i = entry["role_info"][r]
        cap = i["max"]
        what = {"Grouping": "column", "Measure": "measure", "GroupingOrMeasure": "column or measure"}[k]
        lines.append(f"    {r} - {i['displayName']} ({what}{', max ' + str(cap) if cap is not None else ', several'}"
                     f"{', drill hierarchy' if r in entry['drill'] else ''}){': ' + i['description'] if i['description'] else ''}"
                     + (f" - also: {', '.join(i['aliases'])}" if i["aliases"] else ""))
    lines.append("  needs: " + " or ".join(" + ".join(g) for g in entry["required"]))
    if entry["conditions"]:
        lines.append("  Power BI's combinations: " + " or ".join(
            "(" + ", ".join(f"{r} {'≤ ' + str(n) if n else 'empty'}" for r, n in c.items()) + ")" for c in entry["conditions"]))
    if entry["sorting"]:
        lines.append("  sort: supported (`sort: [\"[Measure]\", desc]` or a column)")
    if entry["id_objects"]:
        lines.append(f"  objects applied per instance (state: default is added for you): {', '.join(entry['id_objects'])}")

    def show(name, props):
        parts = []
        for p, s in sorted(props.items()):
            k = s["kind"]
            if k == "enum":
                vals = [str(v) if str(v).lower() == str(lab).lower() else f"{v}={lab}" for v, lab in zip(s["values"], s["labels"])]
                parts.append(f"{p} ({' | '.join(vals)})")
            elif k in ("number", "int") and ("min" in s or "max" in s):
                parts.append(f"{p} ({k} {s.get('min', '')}-{s.get('max', '')})")
            else:
                parts.append(f"{p} ({'structured: ' + str(s.get('ref')) if k == 'complex' else k})")
        return f"    {name}: " + ", ".join(parts)

    lines.append("  format - the visual's own objects:")
    lines += [show(o, p) for o, p in sorted(entry["objects"].items())]
    lines.append("  format - container objects (shared by every visual):")
    lines += [show(o, p) for o, p in sorted(entry["container"].items())]
    return lines
