"""Render the HTML prototype of an expanded definition.

Every custom visual (and table) carries `prototype.sql`: a DuckDB query over the model views whose
column aliases are the visual's roles (e.g. category/value for driver bars). Rows are shaped into the
same models the Power BI visuals build, and drawn with the same renderer bundle, so the prototype
and the report look the same. Output: one self-contained HTML file with page tabs.

Visual Atlas visuals run their own packaged code in a mock Power BI host: their SQL returns one column per
field, named after the field (measure or column name), and is shaped into the data view Power BI would send.
"""
import html as html_mod
import json
import re
from pathlib import Path

from . import KIT, atlas, stock, visuals_dir
from .data import records

STOCK_ROWS = 5000                      # rows of a built-in visual's prototype SQL kept for the page

DATA_TYPE = {"int": "numeric", "decimal": "numeric", "date": "dateTime", "bool": "bool", "string": "text"}
DATE_FORMAT = "yyyy-MM-dd"             # the formatString report_builder gives date columns
MEASURE = re.compile(r"^\[([^\]]+)\]$")
COLUMN = re.compile(r"^'?([^'\[\]]+?)'?\[([^\]]+)\]$")

# Columns each visual type must return from its prototype SQL.
REQUIRED = {"kpiCard": ["value"], "trendLine": ["axis", "actual"], "driverBars": ["category", "value"],
            "quadrant": ["details", "x", "y"], "treemap": ["category", "size"], "heatmap": ["rows", "columns", "value"],
            "funnel": ["stage", "value"], "narrative": ["item"], "table": []}


def _col(rows, name):
    return [r.get(name) for r in rows]


def _first(rows, name):
    return next((r[name] for r in rows if r.get(name) is not None), None)


def _has(rows, name):
    return bool(rows) and name in rows[0]


def _name(ref):
    return ref.strip()[1:-1] if isinstance(ref, str) and ref.strip().startswith("[") else ref


def model_for(v: dict, rows: list[dict], fmt) -> dict:
    """Shape SQL rows into the renderer model for this visual type. fmt(field_ref) -> format string."""
    t, f, fields = v["type"], v.get("format") or {}, v.get("fields") or {}
    F = lambda role: fmt(fields.get(role)) if isinstance(fields.get(role), str) else None
    if t == "kpiCard":
        k = f.get("kpi") or {}
        return {"label": k.get("label") or _name(fields.get("value")) or "", "value": _first(rows, "value"),
                "valueFormat": F("value"),
                "target": _first(rows, "target") if _has(rows, "target") else None,
                "comparison": _first(rows, "comparison") if _has(rows, "comparison") else None,
                "spark": _col(rows, "trend") if _has(rows, "trend") else None,
                "lowerIsBetter": bool(k.get("lowerIsBetter")), "signedValue": bool(k.get("signedValue")),
                "comparisonLabel": k.get("comparisonLabel"), "targetLabel": k.get("targetLabel")}
    if t == "trendLine":
        p = f.get("trend") or {}
        return {"categories": [str(c) for c in _col(rows, "axis")], "actual": _col(rows, "actual"),
                "target": _col(rows, "target") if _has(rows, "target") else None,
                "comparison": _col(rows, "comparison") if _has(rows, "comparison") else None,
                "annotations": _col(rows, "annotation") if _has(rows, "annotation") else None, "format": F("actual"),
                "labels": {"actual": p.get("actualLabel", "Actual"), "target": p.get("targetLabel", "Target"),
                           "comparison": p.get("comparisonLabel", "Last year")},
                "showAllAnnotations": bool(p.get("showAllAnnotations"))}
    if t == "driverBars":
        b = f.get("bars") or {}
        return {"rows": [{"label": str(r.get("category")), "value": r.get("value")} for r in rows], "format": F("value"),
                "signed": b.get("signed", True), "sort": "desc" if b.get("sortDescending") else "none"}
    if t == "quadrant":
        q = f.get("quadrant") or {}
        return {"points": [{"label": str(r.get("details")), "x": r.get("x"), "y": r.get("y"), "size": r.get("size")} for r in rows],
                "xRef": _first(rows, "xRef"), "yRef": _first(rows, "yRef"), "xFormat": F("x"), "yFormat": F("y"),
                "sizeFormat": F("size"), "names": {"x": _name(fields.get("x")), "y": _name(fields.get("y")),
                                                   "size": _name(fields.get("size"))},
                "corners": {k: q.get(k) for k in ("topLeft", "topRight", "bottomLeft", "bottomRight")},
                "labelTop": q.get("labelTop", 2), "labelBottom": q.get("labelBottom", 1)}
    if t == "treemap":
        return {"items": [{"label": str(r.get("category")), "size": r.get("size"), "color": r.get("color")} for r in rows],
                "sizeFormat": F("size"), "colorFormat": F("color"),
                "names": {"size": _name(fields.get("size")), "color": _name(fields.get("color"))}}
    if t == "heatmap":
        h = f.get("heatmap") or {}
        rlabels, clabels = [], []
        for r in rows:
            for key, seen in (("rows", rlabels), ("columns", clabels)):
                label = str(r.get(key))
                if label not in seen:
                    seen.append(label)
        grid = {(str(r.get("rows")), str(r.get("columns"))): r.get("value") for r in rows}
        pad = all(c.isdigit() and len(c) <= 2 for c in clabels)
        return {"rows": rlabels, "cols": [c.zfill(2) if pad else c for c in clabels],
                "values": [[grid.get((ri, ci)) for ci in clabels] for ri in rlabels], "format": F("value"),
                "indexMode": h.get("indexMode", True), "showValues": "all" if h.get("showAll") else "peak",
                "legend": {"low": h.get("lowLabel", "Low"), "high": h.get("highLabel", "High")},
                "names": {"value": _name(fields.get("value"))}}
    if t == "funnel":
        stages = fields.get("stages") or []
        stages = stages if isinstance(stages, list) else [stages]
        return {"stages": [{"label": str(r.get("stage")), "value": r.get("value"),
                            "format": fmt(stages[i]) if i < len(stages) else None} for i, r in enumerate(rows)]}
    if t == "narrative":
        n = f.get("narrative") or {}
        items = [str(i) for i in _col(rows, "item") if i] if _has(rows, "item") else str(n.get("lines") or "").split("\n")
        return {"heading": n.get("heading"), "note": n.get("note"), "style": n.get("style", "numbered"), "items": items}
    if t == "table":
        cols = list(rows[0].keys()) if rows else []
        refs = v.get("fields") or []
        return {"columns": cols, "rows": [[r.get(c) for c in cols] for r in rows[:25]],
                "formats": [fmt(refs[i]) if i < len(refs) else None for i in range(len(cols))]}
    return {}


def _describer(d: dict):
    """Field reference -> how a data view names and types it (Visual Atlas visuals)."""
    fmts = {m["name"]: m.get("format") or None for m in d.get("measures", [])}
    types = {(t["name"], c["name"]): c.get("type", "string") for t in d["tables"] for c in t.get("columns", [])}
    types.update({(c["table"], c["name"]): c.get("type", "string") for c in d.get("calculated_columns", [])})
    mtable = d.get("measures_table", "Metrics")

    def describe(ref) -> dict:
        ref = str(ref).strip()
        m = MEASURE.match(ref)
        if m:
            return {"name": m.group(1), "query": f"{mtable}.{m.group(1)}", "type": "numeric", "measure": True,
                    "format": fmts.get(m.group(1))}
        c = COLUMN.match(ref)
        if not c:
            raise ValueError(f"field {ref} is neither [Measure] nor Table[Column]")
        kind = DATA_TYPE.get(types.get((c.group(1), c.group(2)), "string"), "text")
        return {"name": c.group(2), "query": f"{c.group(1)}.{c.group(2)}", "measure": False, "type": kind,
                "format": DATE_FORMAT if kind == "dateTime" else None}      # as model.bim sets it
    return describe


def _atlas_item(v: dict, entry: dict, rows: list[dict], describe, theme: dict) -> dict:
    fmt = {k: dict(p or {}) for k, p in (v.get("format") or {}).items()}
    if v.get("chart"):
        fmt.setdefault("chart", {})["chartType"] = v["chart"]
    defaults = atlas.theme_defaults(entry, theme.get("look", "soft"))      # as the report theme sets them
    return {"guid": entry["guid"], "dv": atlas.dataview(entry, v.get("fields") or {}, rows, describe),
            "objects": atlas.objects_for(entry, fmt, defaults)}


def _stock_item(v: dict, entry: dict, rows: list[dict], describe, theme: dict) -> dict:
    """A Power BI built-in visual for the page: its fields (with the SQL column each comes from), the rows and the
    Format-pane settings merged over the report theme's styles for this visual."""
    if not rows:
        raise ValueError("query returned no rows")
    sample, fields, missing = rows[0], {}, []
    for role, refs in (v.get("fields") or {}).items():
        refs = refs if isinstance(refs, list) else [refs]
        drill = role in entry["drill"] or role in entry.get("first_only", ())
        for ref in refs[:1] if drill else refs:                # a drill hierarchy shows its top level
            dsc = describe(ref)
            col = atlas._lookup(sample, dsc["name"], role, len(refs) == 1 or drill)
            if col is None:
                missing.append(f'"{dsc["name"]}"')
                continue
            fields.setdefault(role, []).append({**dsc, "col": col})
    if missing:
        raise ValueError(f"query must return a column per field, named after it: missing {', '.join(missing)}")
    return {"vt": entry["visualType"], "renderer": entry["renderer"], "fields": fields, "rows": rows[:STOCK_ROWS],
            "format": stock.prototype_format(entry["visualType"], v.get("format"), (theme or {}).get("styles")),
            "sort": v.get("sort")}


def build_pages(d: dict, con) -> tuple[list[dict], list[str]]:
    """Run every visual's prototype SQL; returns (pages for the HTML, error messages)."""
    fmts = {m["name"]: m.get("format", "") for m in d.get("measures", [])}
    fmt = lambda ref: fmts.get(_name(ref)) if isinstance(ref, str) and ref.strip().startswith("[") else None
    acat, describe = atlas.catalog(), _describer(d)
    pages, errors = [], []
    for page in d["pages"]:
        out = []
        for v in page["visuals"]:
            item = {k: v.get(k) for k in ("id", "type", "x", "y", "w", "h", "label", "default", "paragraphs", "align")}
            if v["type"] in acat:
                sql, title = (v.get("prototype") or {}).get("sql"), v.get("title")
                dynamic = MEASURE.match(str(title).strip()) if title else None
                header = {"title": None if dynamic else title, "subtitle": v.get("subtitle")}
                try:
                    if not sql:
                        raise ValueError("missing prototype.sql")
                    rows = records(con, sql)
                    if _has(rows, "title") and _first(rows, "title"):
                        header["title"] = _first(rows, "title")
                    elif dynamic:
                        header["title"] = dynamic.group(1)
                    item.update(atlas=_atlas_item(v, acat[v["type"]], rows, describe, d.get("theme") or {}), header=header)
                except Exception as e:  # noqa: BLE001 - reported to the agent
                    item.update(error=str(e).splitlines()[0][:300], header=header)
                    errors.append(f"{page['name']} / {v['id']} ({v['type']}): {str(e).splitlines()[0][:300]}")
            elif stock.is_stock(v["type"]):
                sql, title = (v.get("prototype") or {}).get("sql"), v.get("title")
                dynamic = MEASURE.match(str(title).strip()) if title else None
                header = {"title": None if dynamic else title, "subtitle": v.get("subtitle")}
                try:
                    if not sql:
                        raise ValueError("missing prototype.sql")
                    rows = records(con, sql)
                    if _has(rows, "title") and _first(rows, "title"):
                        header["title"] = _first(rows, "title")
                    elif dynamic:
                        header["title"] = dynamic.group(1)
                    item.update(stock=_stock_item(v, stock.catalog()[v["type"]], rows, describe, d.get("theme") or {}), header=header)
                except Exception as e:  # noqa: BLE001 - reported to the agent
                    item.update(error=str(e).splitlines()[0][:300], header=header)
                    errors.append(f"{page['name']} / {v['id']} ({v['type']}): {str(e).splitlines()[0][:300]}")
            elif v["type"] in REQUIRED:
                sql = (v.get("prototype") or {}).get("sql")
                f = v.get("format") or {}
                header = {"title": (f.get("header") or {}).get("title") or v.get("title"),
                          "subtitle": (f.get("header") or {}).get("subtitle"),
                          "showCard": (f.get("card") or {}).get("show", True)}
                try:
                    rows = records(con, sql) if sql else []
                    if sql:
                        missing = [c for c in REQUIRED[v["type"]] if not _has(rows, c)] if rows else []
                        if missing:
                            raise ValueError(f"query must return column(s) {', '.join(missing)}")
                    elif v["type"] != "narrative":
                        raise ValueError("missing prototype.sql")
                    title = _first(rows, "title") if _has(rows, "title") else None
                    if title:
                        header["title"] = title
                    item.update(model=model_for(v, rows, fmt), header=header)
                    if not rows and sql:
                        errors.append(f"{page['name']} / {v['id']}: query returned no rows")
                except Exception as e:  # noqa: BLE001 - reported to the agent
                    item.update(error=str(e).splitlines()[0][:300], header=header)
                    errors.append(f"{page['name']} / {v['id']} ({v['type']}): {str(e).splitlines()[0][:300]}")
            out.append(item)
        pages.append({"name": page["name"], "height": page.get("height", 720), "visuals": out})
    return pages, errors


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ - prototype</title>
<style>__CSS__
html,body{margin:0;background:__BG__;font-family:'Segoe UI',system-ui,sans-serif;color:#1F1A17}
.page{position:relative;width:1280px;margin:0 auto}
.v{position:absolute}
.nav{display:flex;gap:6px;height:100%;box-sizing:border-box;padding:4px;background:#fff;border:1px solid #E7E0D7;border-radius:22px}
.nav span{flex:1;display:flex;align-items:center;justify-content:center;border-radius:18px;font-size:14px;color:#6F6761;cursor:pointer}
.nav span:hover{background:__TINT__;color:#1F1A17}
.nav span.on{background:__ACCENT__;color:#fff;font-weight:700}
.slc{height:100%;display:flex;flex-direction:column;justify-content:flex-end;gap:3px}
.slc small{font-size:11px;color:#6F6761;padding-left:2px}
.slc b{display:flex;justify-content:space-between;background:#fff;border:1px solid #E7E0D7;border-radius:8px;padding:6px 10px;font-size:13px;font-weight:400}
.tbl{height:100%;box-sizing:border-box;background:#fff;border:1px solid #E7E0D7;border-radius:10px;padding:12px 14px;overflow:auto;font-size:12px}
.tbl h4{margin:0 0 8px;font-size:14px}.tbl table{border-collapse:collapse;width:100%}
.tbl th{text-align:left;color:#6F6761;font-weight:600;border-bottom:1px solid #E7E0D7;padding:4px 6px}
.tbl td{padding:4px 6px;border-bottom:1px solid #F1ECE6}.tbl td.n{text-align:right}
.err{height:100%;box-sizing:border-box;background:#FFF6F5;border:1px dashed #B3261E;border-radius:10px;padding:12px;font-size:12px;color:#B3261E}
.acard{height:100%;box-sizing:border-box;display:flex;flex-direction:column;background:__CARD__;border-radius:__RADIUS__px;padding:10px 12px;__FRAME__}
.acard h4{margin:0;font-size:12px;font-weight:700;color:__INK__;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acard small{display:block;margin-top:2px;font-size:11px;color:__MUTED__;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.acard .abody{flex:1;min-height:0;position:relative;margin-top:6px}.acard .aerr{color:#B3261E;font-size:12px}
.gba-tip{position:fixed;z-index:50;pointer-events:none;background:#fff;border:1px solid #E1DFDD;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.14);padding:6px 9px;font-size:12px;color:#252423}
.gba-tip div{display:flex;gap:14px;justify-content:space-between}.gba-tip b{font-weight:600}
__ATLAS_CSS__
</style></head><body><div class="page" id="page"></div>
<script>__JS__</script>
<script>__ATLAS_JS__</script>
<script>__STOCK_JS__</script>
<script>
const R = __DATA__;
let current = 0;
// Table cells use the measure's format string, like the visuals do ("\\$#,0", "0.0%", "+0.0%;-0.0%;0.0%").
// Commas right after the last digit divide by 1,000 each: \\$#,0.0,,"M" shows millions.
function fmtNum(v, f) {
  if (typeof v !== 'number') return v ?? '';
  if (!f) return v.toLocaleString('en-US', {maximumFractionDigits: 2});
  const sec = f.split(';')[0].trim(), lits = sec.match(/"[^"]*"/g) || [];
  const suffix = lits.length && sec.endsWith(lits[lits.length - 1]) ? lits[lits.length - 1].slice(1, -1) : '';
  const core = sec.replace(/"[^"]*"/g, '').split(String.fromCharCode(92)).join('');
  const cur = (core.match(/[$€£¥₹]/) || [''])[0], pct = core.includes('%'), dm = core.match(/[.](0+)/);
  const sm = core.replace(/[$€£¥₹% ]/g, '').match(/[0#](?:[.][0#]+)?(,+)$/), scale = sm ? Math.pow(1000, sm[1].length) : 1;
  const d = dm ? dm[1].length : 0, signed = f.includes(';') && sec.startsWith('+');
  const s = v < 0 ? '-' : (signed && v > 0 ? '+' : '');
  return s + cur + (Math.abs(pct ? v * 100 : v) / scale).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) + (pct ? '%' : '') + suffix;
}
function draw() {
  const page = R.pages[current], root = document.getElementById('page');
  root.innerHTML = ''; root.style.height = page.height + 'px';
  for (const v of page.visuals) {
    const box = document.createElement('div'); box.className = 'v';
    Object.assign(box.style, {left: v.x + 'px', top: v.y + 'px', width: v.w + 'px', height: v.h + 'px'});
    root.appendChild(box);
    if (v.type === 'pageNavigator') {
      const nav = document.createElement('div'); nav.className = 'nav'; box.appendChild(nav);
      R.pages.forEach((p, i) => { const s = document.createElement('span'); s.textContent = p.name;
        if (i === current) s.className = 'on'; s.onclick = () => { current = i; draw(); window.scrollTo(0, 0); }; nav.appendChild(s); });
    } else if (v.type === 'slicer') {
      box.innerHTML = '<div class="slc"><small></small><b><span></span><span>⌄</span></b></div>';
      box.querySelector('small').textContent = v.label || '';
      box.querySelector('b span').textContent = v.default ?? 'All';
    } else if (v.type === 'textbox') {
      (v.paragraphs || []).forEach(rs => { const p = document.createElement('div');
        p.textContent = (rs || []).map(r => (r && r.text != null) ? r.text : '').join(''); box.appendChild(p); });
    } else if (v.error) {
      box.innerHTML = '<div class="err"><b></b><div></div></div>';
      box.querySelector('b').textContent = (v.header && v.header.title) || v.id;
      box.querySelector('div div').textContent = 'Prototype query failed: ' + v.error;
    } else if (v.atlas) {
      // Visual Atlas: Power BI's themed container (title, subtitle) around the visual's own packaged code
      const card = document.createElement('div'); card.className = 'acard';
      if (v.header && v.header.title) { const h = document.createElement('h4'); h.textContent = v.header.title; card.appendChild(h); }
      if (v.header && v.header.subtitle) { const s = document.createElement('small'); s.textContent = v.header.subtitle; card.appendChild(s); }
      const body = document.createElement('div'); body.className = 'abody'; card.appendChild(body); box.appendChild(card);
      try { GenBIAtlas.render(body, v.atlas, R.atlas); }
      catch (e) { body.className += ' aerr'; body.textContent = 'Could not draw this visual: ' + e.message; }
    } else if (v.stock) {
      // Power BI's own visual: drawn with Power BI's layout and its Format-pane settings
      try { RelayStock.render(box, v, Object.assign({fmtNum}, R.stock)); }
      catch (e) { box.innerHTML = '<div class="err"><b></b><div></div></div>'; box.querySelector('b').textContent = (v.header && v.header.title) || v.id;
        box.querySelector('div div').textContent = 'Could not draw this visual: ' + e.message; }
    } else if (v.type === 'table') {
      const m = v.model, t = document.createElement('div'); t.className = 'tbl';
      t.innerHTML = '<h4></h4><table><thead><tr></tr></thead><tbody></tbody></table>';
      t.querySelector('h4').textContent = (v.header && v.header.title) || '';
      m.columns.forEach(c => { const th = document.createElement('th'); th.textContent = c; t.querySelector('tr').appendChild(th); });
      m.rows.forEach(r => { const tr = document.createElement('tr');
        r.forEach((c, i) => { const td = document.createElement('td'); td.textContent = fmtNum(c, (m.formats || [])[i]); if (typeof c === 'number') td.className = 'n'; tr.appendChild(td); });
        t.querySelector('tbody').appendChild(tr); });
      box.appendChild(t);
    } else {
      GenBIVisuals.render(v.type, box, v.model, v.header || {}, R.tokens);
    }
  }
}
draw();
</script></body></html>"""


FRAME ={"flat": "border:1px solid {border}", "soft": "box-shadow:0 3px 12px rgba(31,26,23,.13)",
         "3d": "box-shadow:6px 6px 14px rgba(31,26,23,.28)"}      # Power BI container look per Atlas look
CSS_COLOR = re.compile(r"#[0-9A-Fa-f]{3,8}|[A-Za-z]{3,24}|rgba?\(\s*[\d.]+%?\s*(,\s*[\d.]+%?\s*){2,3}\)")


def _color(value, default: str) -> str:
    """A theme colour for the page's style sheet. The definition is written by the AI, and nothing it read (a data
    file, an attachment) may close the style block and add markup: anything but a colour gets the default."""
    s = str(value).strip() if value is not None else ""
    return s if CSS_COLOR.fullmatch(s) else default


def _radius(value, default: int = 10) -> str:
    try:
        r = float(value)
    except (TypeError, ValueError):
        return str(default)
    return f"{max(0.0, min(r, 60.0)):g}"


def render(d: dict, con, out: Path) -> list[str]:
    pages, errors = build_pages(d, con)
    bundle = visuals_dir() / "prototype"
    t = d.get("theme") or {}
    look = t.get("look", "soft")
    used = sorted({v["atlas"]["guid"] for p in pages for v in p["visuals"] if v.get("atlas")})
    codes = [atlas.code(g) for g in used]
    atlas_js = "" if not used else ((KIT / "assets" / "atlas_host.js").read_text(encoding="utf-8") + "\n"
                                    + "\n".join(js.replace("</script", "<\\/script") for js, _ in codes))
    from .definition import DEFAULT_THEME, genbi_colors
    tokens = {**genbi_colors({**DEFAULT_THEME, **t}), "card": t.get("card_bg", "#FFFFFF"),
              "border": t.get("card_border", "#E7E0D7")}                       # Relay visuals in the brand colors
    uses_stock = any(v.get("stock") for p in pages for v in p["visuals"])
    data = {"name": d.get("name"), "pages": pages, "tokens": tokens,
            "atlas": {"palette": t.get("data_colors"), "dark": bool(t.get("dark")), "look": look},
            "stock": {"palette": t.get("data_colors") or DEFAULT_THEME["data_colors"], "card": t.get("card_bg", "#FFFFFF"),
                      "border": t.get("card_border", "#E7E0D7"), "radius": t.get("radius", 10), "text": t.get("text", "#1F1A17"),
                      "muted": t.get("muted", "#6F6761"), "font": t.get("font", "Segoe UI"),
                      "frame": FRAME.get(look, FRAME["soft"]).format(border=t.get("card_border", "#E7E0D7"))}}
    subs = {"NAME": html_mod.escape(str(d.get("name") or "Report")), "BG": _color(t.get("page_bg"), "#F7F3EE"),
            "TINT": _color(t.get("accent_tint"), "#FBE7CC"), "ACCENT": _color(t.get("accent"), "#DD7A12"),
            "CARD": _color(t.get("card_bg"), "#FFFFFF"), "INK": _color(t.get("text"), "#1F1A17"),
            "MUTED": _color(t.get("muted"), "#6F6761"), "RADIUS": _radius(t.get("radius", 10)),
            "FRAME": FRAME.get(look, FRAME["soft"]).format(border=_color(t.get("card_border"), "#E7E0D7")),
            "CSS": (bundle / "genbi-visuals.css").read_text(encoding="utf-8"), "ATLAS_CSS": "\n".join(css for _, css in codes),
            "DATA": json.dumps(data, default=str).replace("</", "<\\/"), "ATLAS_JS": atlas_js,
            "STOCK_JS": (KIT / "assets" / "stock_visuals.js").read_text(encoding="utf-8").replace("</script", "<\\/script") if uses_stock else "",
            "JS": (bundle / "genbi-visuals.js").read_text(encoding="utf-8")}
    html = re.sub(r"__([A-Z_]+)__", lambda m: subs.get(m.group(1), m.group(0)), PAGE)   # one pass: inserted code is never rescanned
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return errors
