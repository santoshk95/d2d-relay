"""Report definition: load (YAML or JSON) and expand into the flat form report_builder writes.

Authoring conveniences handled here, so the AI writes less and gets less wrong:
- pages laid out as `rows` (height + visuals; widths split evenly or by `span`) become absolute
  positions, with a full-width page navigator and the report `filters` as synced slicers on top;
- `date_table: {start, end, is_past_from, events}` becomes a Power Query calendar + `Is Past` column;
- a `Metrics` measures table is added when none is defined;
- KPI cards with a sparkline axis get helper measures that ignore that axis ("<measure> (card)").
"""
import colorsys
import copy
import json
import re
from pathlib import Path

import yaml

from . import atlas, stock

W, MARGIN, GAP = 1280, 24, 16
NAV_Y, NAV_H, FILTER_Y, FILTER_H, BODY_Y = 12, 44, 60, 56, 128
ROW_HEIGHT = {"kpiCard": 150, "narrative": 124, "pbi.cardVisual": 150, "pbi.card": 150, "pbi.kpi": 150, "pbi.multiRowCard": 150}
DEFAULT_ROW_H = 312
DEFAULT_THEME = {
    "page_bg": "#F7F3EE", "card_bg": "#FFFFFF", "card_border": "#E7E0D7", "text": "#1F1A17", "muted": "#6F6761",
    "accent": "#DD7A12", "accent_tint": "#FBE7CC", "font": "Segoe UI", "radius": 10,
    "data_colors": ["#DD7A12", "#9C4F0C", "#F2B166", "#3B78D8", "#6F6761", "#C9A27A", "#2E7D3A", "#B3261E"],
}
COL_REF = re.compile(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$")


def load(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) if str(path).endswith((".yaml", ".yml")) else json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return data


def dax_column(ref: str) -> str:
    """'Date[Month Start]' -> "'Date'[Month Start]"."""
    m = COL_REF.match(ref.strip())
    if not m:
        raise ValueError(f"Not a column reference: {ref}")
    return f"'{m.group(1)}'[{m.group(2)}]"


def _mmdd(value) -> int:
    m, d = str(value).split("-")
    return int(m) * 100 + int(d)


def _date_table(t: dict) -> dict | None:
    """Expand a date_table spec in place; returns the Is Past calculated column (if requested)."""
    spec = t["date_table"]
    start, end = str(spec["start"]), str(spec["end"])
    (y0, m0, d0), (y1, m1, d1) = (map(int, start.split("-")), map(int, end.split("-")))
    events = spec.get("events") or []
    lines = [
        "let",
        f"    Start = #date({y0}, {m0}, {d0}),",
        f"    End = #date({y1}, {m1}, {d1}),",
        "    Dates = List.Dates(Start, Duration.Days(End - Start) + 1, #duration(1, 0, 0, 0)),",
        '    Base = Table.TransformColumnTypes(Table.FromList(Dates, Splitter.SplitByNothing(), {"Date"}), {{"Date", type date}}),',
        '    Year = Table.AddColumn(Base, "Year", each Date.Year([Date]), Int64.Type),',
        '    MonthNumber = Table.AddColumn(Year, "Month Number", each Date.Month([Date]), Int64.Type),',
        '    Month = Table.AddColumn(MonthNumber, "Month", each Date.ToText([Date], [Format = "MMM", Culture = "en-US"]), type text),',
        '    MonthStart = Table.AddColumn(Month, "Month Start", each Date.StartOfMonth([Date]), type date),',
        '    YearMonth = Table.AddColumn(MonthStart, "Year Month", each Date.ToText([Date], [Format = "yyyy-MM", Culture = "en-US"]), type text),',
        '    Quarter = Table.AddColumn(YearMonth, "Quarter", each "Q" & Text.From(Date.QuarterOfYear([Date])), type text),',
        '    WeekdayNumber = Table.AddColumn(Quarter, "Weekday Number", each Date.DayOfWeek([Date], Day.Monday) + 1, Int64.Type),',
        '    Weekday = Table.AddColumn(WeekdayNumber, "Weekday", each Date.ToText([Date], [Format = "ddd", Culture = "en-US"]), type text),',
        '    WeekdayName = Table.AddColumn(Weekday, "Weekday Name", each Date.ToText([Date], [Format = "dddd", Culture = "en-US"]), type text)' + ("," if events else ""),
    ]
    last = "WeekdayName"
    if events:
        conds = [f'if md >= {_mmdd(e["from"])} and md <= {_mmdd(e["to"])} then "{str(e["name"]).replace(chr(34), chr(34) * 2)}"'
                 for e in events]                    # an M text literal: a quote in the name is doubled
        lines.append('    KeyEvent = Table.AddColumn(WeekdayName, "Key Event", each')
        lines.append("        let md = Date.Month([Date]) * 100 + Date.Day([Date]) in")
        lines.append("        " + "\n        else ".join(conds) + "\n        else null, type text)")
        last = "KeyEvent"
    lines += ["in", f"    {last}"]
    t["m"] = "\n".join(lines)
    t["columns"] = [
        {"name": "Date", "type": "date"}, {"name": "Year", "type": "int"},
        {"name": "Month Number", "type": "int", "hidden": True}, {"name": "Month", "type": "string", "sortBy": "Month Number"},
        {"name": "Month Start", "type": "date"}, {"name": "Year Month", "type": "string"},
        {"name": "Quarter", "type": "string"}, {"name": "Weekday Number", "type": "int", "hidden": True},
        {"name": "Weekday", "type": "string", "sortBy": "Weekday Number"},
        {"name": "Weekday Name", "type": "string", "sortBy": "Weekday Number"},
    ] + ([{"name": "Key Event", "type": "string"}] if events else [])
    if spec.get("is_past_from"):
        return {"table": t["name"], "name": "Is Past", "type": "bool", "hidden": True,
                "expression": f"'{t['name']}'[Date] <= MAX ( {dax_column(spec['is_past_from'])} )"}
    return None


def iter_visuals(d: dict):
    for page in d.get("pages", []):
        for row in page.get("rows", []):
            yield from (row["visuals"] if isinstance(row, dict) else row)
        yield from page.get("visuals", [])


def _kpi_helpers(d: dict) -> None:
    measures = {m["name"]: m for m in d["measures"]}
    for v in iter_visuals(d):
        if v.get("type") != "kpiCard":
            continue
        f = v.setdefault("fields", {})
        axis = f.get("axis")
        if not axis:
            continue
        trend = f.get("trend", "")
        guard = trend.strip()[1:-1] if trend.strip().startswith("[") else None
        for role in ("value", "target", "comparison"):
            ref = (f.get(role) or "").strip()
            if not ref.startswith("[") or ref.endswith("(card)]"):
                continue
            base = ref[1:-1]
            helper = f"{base} (card)"
            if helper not in measures and base in measures:
                inner = f"CALCULATE ( [{base}], ALLSELECTED ( {dax_column(axis)} ) )"
                expr = f"IF ( ISBLANK ( [{guard}] ), BLANK (), {inner} )" if guard else inner
                measures[helper] = {"name": helper, "expression": expr, "format": measures[base].get("format", ""),
                                    "folder": "Cards", "description": f"{base} for the KPI card (ignores the sparkline axis)"}
                d["measures"].append(measures[helper])
            if helper in measures:
                f[role] = f"[{helper}]"


def _layout(d: dict) -> None:
    filters = d.get("filters") or []
    for pi, page in enumerate(d.get("pages", [])):
        if "rows" not in page:
            continue
        prefix = (re.sub(r"[^a-z0-9]", "", page["name"].lower())[:6] or "p") + str(pi)
        out = [{"id": f"{prefix}_nav", "type": "pageNavigator", "x": MARGIN, "y": NAV_Y, "w": W - 2 * MARGIN, "h": NAV_H}]
        if filters:
            n = len(filters)
            fw = (W - 2 * MARGIN - GAP * (n - 1)) / n
            for i, f in enumerate(filters):
                out.append({"id": f"{prefix}_filter{i}", "type": "slicer", "x": round(MARGIN + i * (fw + GAP)),
                            "y": FILTER_Y, "w": round(fw), "h": FILTER_H, "field": f["field"], "label": f.get("label"),
                            "default": f.get("default"), "single": f.get("single", f.get("default") is not None),
                            "sync": f.get("sync") or f.get("label") or f["field"]})
        y = BODY_Y if filters else NAV_Y + NAV_H + GAP
        for row in page["rows"]:
            visuals = row["visuals"] if isinstance(row, dict) else row
            h = (row.get("height") if isinstance(row, dict) else None) or \
                max(ROW_HEIGHT.get(v.get("type"), DEFAULT_ROW_H) for v in visuals)
            spans = [v.get("span", 1) for v in visuals]
            free = W - 2 * MARGIN - GAP * (len(visuals) - 1)
            x = MARGIN
            for i, (v, sp) in enumerate(zip(visuals, spans)):
                w = free - sum(round(free * s / sum(spans)) for s in spans[:-1]) if i == len(visuals) - 1 \
                    else round(free * sp / sum(spans))
                out.append({**{k: val for k, val in v.items() if k != "span"}, "x": x, "y": y, "w": w, "h": h})
                x += w + GAP
            y += h + GAP
        page["visuals"] = out
        page["height"] = max(720, y + 16)
        del page["rows"]


ATLAS_KEYS = ("look", "palette", "colors", "dark")
CLASSIC_KEYS = ("page_bg", "card_bg", "card_border", "text", "muted", "data_colors")
RADIUS = {"flat": 4, "soft": 12, "3d": 8}


def _theme(given: dict) -> dict:
    """Theme tokens, made by the Visual Atlas brand engine: a palette from the accent (or a color list, or the Atlas
    preset), Flat/Soft/3D containers, dark or light; the Gen BI tokens are taken from it and keys the definition sets
    itself always win. A report that sets the classic tokens itself (and none of look / palette / colors / dark)
    keeps its own colors."""
    t = {**DEFAULT_THEME, **given}
    t.setdefault("look", "soft")
    if not any(k in given for k in ATLAS_KEYS) and any(k in given for k in CLASSIC_KEYS):
        return t
    at = atlas.theme(look=t["look"], dark=t.get("dark", False), brand=given.get("accent"),
                     palette=given.get("palette") or ("custom" if given.get("colors") else None), colors=given.get("colors"))
    if not at:
        return t
    page = at["visualStyles"]["page"]["*"]["background"][0]["color"]["solid"]["color"]
    derived = {"data_colors": at["dataColors"], "page_bg": page, "card_bg": at["background"], "text": at["foreground"],
               "muted": at.get("fourthLevelElements", DEFAULT_THEME["muted"]),
               "card_border": at.get("thirdLevelElements", DEFAULT_THEME["card_border"]),
               "accent": at["dataColors"][0], "radius": RADIUS.get(t["look"], 10)}
    derived["accent_tint"] = _tint(given.get("accent") or derived["accent"])
    return {**DEFAULT_THEME, **derived, **given, "look": t["look"], "atlas_theme": at}


def _tint(hex_: str, amount: float = 0.82) -> str:
    """A light tint of a color (navigator hover, KPI badges)."""
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(c + (255 - c) * amount):02X}" for c in (r, g, b))


def _shade(hex_: str, amount: float = 0.38) -> str:
    """A darker shade of a color."""
    h = hex_.lstrip("#")
    return "#" + "".join(f"{round(int(h[i:i + 2], 16) * (1 - amount)):02X}" for i in (0, 2, 4))


GENBI_DEFAULT = {"primary": "#DD7A12", "primaryDark": "#9C4F0C", "primaryLight": "#F6D3A3", "negative": "#3B78D8"}


def _hue(hex_: str) -> tuple[float, float]:
    h, s, _ = colorsys.rgb_to_hsv(*(int(hex_.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)))
    return h * 360, s


def genbi_colors(t: dict) -> dict:
    """Colors of the Gen BI visuals from the theme, so they follow the brand like the Atlas visuals do. The
    'negative' color is the palette color furthest in hue from the accent."""
    accent = t["accent"]
    if accent.upper() == GENBI_DEFAULT["primary"]:
        return {**GENBI_DEFAULT, "ink": t["text"], "muted": t["muted"]}           # the original warm design
    ha = _hue(accent)[0]

    def distance(c):
        h, s = _hue(c)
        d = abs(h - ha) % 360
        return min(d, 360 - d) * (1 if s > 0.25 else 0.2)
    others = [c for c in t.get("data_colors", []) if c.upper() != accent.upper()]
    return {"primary": accent, "primaryDark": _shade(accent), "primaryLight": _tint(accent, 0.62),
            "negative": max(others, key=distance) if others else GENBI_DEFAULT["negative"],
            "ink": t["text"], "muted": t["muted"]}


def expand(defn: dict) -> dict:
    """Return the builder-ready definition (the input is left untouched)."""
    d = copy.deepcopy(defn)
    d["theme"] = _theme(d.get("theme") or {})
    d["data"] = {"parameter": "DataFolder", "folder": "C:\\GenBI\\data\\", **(d.get("data") or {})}
    d.setdefault("measures_table", "Metrics")
    for key in ("measures", "calculated_columns", "relationships", "tables", "pages"):
        d[key] = d.get(key) or []
    for t in d["tables"]:
        if isinstance(t.get("date_table"), dict):
            calc = _date_table(t)
            if calc:
                d["calculated_columns"].append(calc)
        for c in t.get("columns", []):
            c.setdefault("source", c["name"])
            c.setdefault("type", "string")
    if not any(t["name"] == d["measures_table"] for t in d["tables"]):
        d["tables"].append({"name": d["measures_table"], "description": "Home of all measures",
                            "dax": 'DATATABLE ( "Metric", STRING, { { "Measures live here" } } )',
                            "columns": [{"name": "Metric", "type": "string", "hidden": True}]})
    d["relationships"] = [r if isinstance(r, dict) else dict(zip(("from", "to"), [s.strip() for s in r.split("->")]))
                          for r in d["relationships"]]
    for m in d["measures"]:
        m["expression"] = str(m.get("expression", "")).strip()
        m.setdefault("format", "")
    _kpi_helpers(d)
    cat = stock.catalog()
    for v in iter_visuals(d):            # Power BI's own visuals: wells by Power BI's role names (aliases resolved)
        if stock.is_stock(v.get("type")):
            v["fields"] = stock.canonical_fields(v, cat[v["type"]])
    _layout(d)
    return d
