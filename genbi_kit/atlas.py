"""Visual Atlas: 13 Power BI custom-visual families (about 50 chart types) from the Visual Atlas project
(`visual-atlas/` in this repo). The packaged .pbiviz files sit in custom_visuals/atlas/ and everything the toolkit
needs comes from them: the field wells, data mapping and every Format-pane option (capabilities), and the compiled
visual code that the HTML prototype runs in a mock Power BI host — so the prototype draws exactly what Power BI will.

Custom visuals built by the visual factory (vfactory.py) sit on the same framework and are handled the same way:
those in the visual library (library_dir()/<name>/<name>.pbiviz) and the current project's own
(visuals/dist/<name>.pbiviz) join the catalog after the Atlas families.
"""
import json
import shutil
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path

from . import KIT, library_dir, project_dir, visuals_dir

# Field sets a chart needs (any one of them); capabilities only cap the counts.
REQUIRED = {
    "atlasColumns": [["category", "values"]],
    "atlasLines": [["category", "values"], ["category", "lineValues"]],
    "atlasParts": [["category", "values"]],
    "atlasFlow": [["source", "target", "weight"]],
    "atlasDistribution": [["values", "detail"], ["values", "category"]],
    "atlasCompare": [["category", "values"]],
    "atlasHierarchy": [["levels", "values"], ["nodeId", "parentId"]],
    "atlasProportion": [["category", "values"]],
    "atlasTime": [["time", "values"]],
    "atlasFinance": [["category", "values"], ["category", "open", "high", "low", "close"]],
    "atlasGauges": [["values"]],
    "atlasText": [["category"]],
    "atlasScatter": [["details", "x", "y"], ["task", "start", "end"]],
}
LOOKS = ("flat", "soft", "3d")
PALETTES = ("spectrum", "analogous", "mono", "atlas", "classic", "custom")


def folder() -> Path:
    return visuals_dir() / "atlas"


def _prop_type(t: dict):
    if "enumeration" in t:
        return {"enum": [e["value"] for e in t["enumeration"]]}
    if "fill" in t:
        return "color"
    if "bool" in t:
        return "bool"
    if "numeric" in t or "integer" in t:
        return "number"
    fmt = t.get("formatting") or {}
    if fmt.get("fontSize") or fmt.get("labelDisplayUnits"):
        return "number"
    return "text"


def _roles(items: list) -> list[str]:
    return [x.get("for", {}).get("in") or x.get("bind", {}).get("to") for x in items]


def _shape(mapping: dict) -> dict:
    """Which roles become category columns, which become value columns, and the role values are grouped by."""
    cat, val = mapping.get("categorical", {}).get("categories", {}), mapping.get("categorical", {}).get("values", {})
    categories = _roles(cat["select"]) if "select" in cat else _roles([cat]) if cat else []
    if "group" in val:
        return {"categories": categories, "values": _roles(val["group"]["select"]), "group_by": val["group"]["by"]}
    return {"categories": categories, "values": _roles(val.get("select", [val] if val else [])), "group_by": None}


def _required(name: str, conditions: list) -> list:
    """Field sets a visual needs: the Atlas table, else the wells a data-view condition marks with min >= 1."""
    if name in REQUIRED:
        return REQUIRED[name]
    sets = []
    for c in conditions:
        need = [role for role, rule in c.items() if (rule or {}).get("min", 0) >= 1]
        if need and need not in sets:
            sets.append(need)
    return sets


def _entry(pkg: dict, file: str, origin: str = "atlas") -> dict:
    caps, visual = pkg["capabilities"], pkg["visual"]
    mapping = caps["dataViewMappings"][0]
    conditions = mapping.get("conditions") or []
    roles, info = {}, {}
    for r in caps["dataRoles"]:
        roles[r["name"]] = "Grouping" if r["kind"] == "Grouping" else "Measure"
        caps_ = [c[r["name"]]["max"] for c in conditions if r["name"] in c and "max" in c[r["name"]]]
        unlimited = not caps_ or any(r["name"] not in c for c in conditions)
        info[r["name"]] = {"displayName": r.get("displayName", r["name"]), "description": r.get("description", ""),
                           "max": None if unlimited else max(caps_)}
    objects = {name: {p: _prop_type(d.get("type", {})) for p, d in o.get("properties", {}).items()}
               for name, o in caps.get("objects", {}).items()}
    return {"name": visual["name"], "guid": visual["guid"], "displayName": visual.get("displayName", visual["name"]),
            "description": visual.get("description", ""), "version": visual.get("version"), "family": "atlas",
            "origin": origin, "file": file, "roles": roles, "role_info": info, "objects": objects,
            "chart_types": (objects.get("chart", {}).get("chartType") or {}).get("enum", []),
            "drill": (caps.get("drilldown") or {}).get("roles", []), "sorting": "sorting" in caps,
            "conditions": [{k: v.get("max") for k, v in c.items()} for c in conditions],
            "shape": _shape(mapping), "required": _required(visual["name"], conditions)}


def _newest(paths: list[Path]) -> list[Path]:
    best: dict[str, tuple] = {}
    for p in paths:
        parts = p.name.split(".")
        version = tuple(int(x) for x in parts[1:5] if x.isdigit())
        if parts[0] not in best or version > best[parts[0]][0]:
            best[parts[0]] = (version, p)
    return [p for _, p in best.values()]


def package_paths() -> list[tuple[str, Path]]:
    """(origin, .pbiviz) in precedence order: the Atlas families (newest version of each), the visual library,
    the current project's own custom visuals (a project copy of a library visual wins)."""
    out = [("atlas", p) for p in sorted(_newest(list(folder().glob("Atlas*.pbiviz"))))]
    lib = library_dir()
    if lib.is_dir():
        out += [("library", p) for p in sorted(lib.glob("*/*.pbiviz"))]
    proj = project_dir()
    if proj is not None:
        out += [("project", p) for p in sorted((proj / "visuals" / "dist").glob("*.pbiviz"))]
    return out


@lru_cache(maxsize=256)
def _read(path: str, stamp: tuple, origin: str) -> tuple[dict, str, str]:
    with zipfile.ZipFile(path) as z:
        pkg = json.loads(z.read(next(n for n in z.namelist() if n.endswith(".pbiviz.json"))))
    return _entry(pkg, Path(path).name, origin), pkg["content"]["js"], pkg["content"].get("css", "")


def read_package(path: Path, origin: str = "project") -> tuple[dict, str, str]:
    """(catalog entry, compiled js, css) of one .pbiviz; re-read only when the file changes."""
    st = path.stat()
    return _read(str(path), (st.st_mtime_ns, st.st_size), origin)


def _packages() -> dict:
    """name -> (catalog entry, compiled js, css) for every visual in package_paths(). A library or project visual
    never replaces an Atlas family; a broken package is skipped."""
    out = {}
    for origin, path in package_paths():
        try:
            item = read_package(path, origin)
        except (OSError, KeyError, ValueError, StopIteration, zipfile.BadZipFile):
            continue
        name = item[0]["name"]
        if name in out and out[name][0]["origin"] == "atlas" and origin != "atlas":
            continue
        out[name] = item
    return out


def catalog() -> dict:
    return {name: entry for name, (entry, _, _) in _packages().items()}


def code(guid: str) -> tuple[str, str]:
    """Compiled JS and CSS of one Atlas or custom visual (it registers powerbi.visuals.plugins[guid])."""
    for entry, js, css in _packages().values():
        if entry["guid"] == guid:
            return js, css
    raise KeyError(guid)


def guids() -> list[str]:
    return sorted(e["guid"] for e in catalog().values())


# ---------------------------------------------------------------- data views for the prototype

def _lookup(row: dict, name: str, role: str, single: bool):
    """The SQL column for a field: named after the field (measure or column name), or the role when it has one field."""
    for key in row:
        if key == name or key.lower() == name.lower():
            return key
    if single:
        for key in row:
            if key.lower() == role.lower():
                return key
    return None


def dataview(entry: dict, fields: dict, rows: list[dict], describe) -> dict:
    """Shape SQL rows into the categorical data view this visual's capabilities ask for (as JSON; the page adds
    Date objects and values.grouped()). describe(ref) -> {name, query, type, measure, format}."""
    shape, drill = entry["shape"], set(entry.get("drill") or [])

    def refs(role):
        r = fields.get(role) or []
        r = r if isinstance(r, list) else [r]
        return r[:1] if role in drill else r                     # a drill hierarchy starts at its top level

    cat = [(role, describe(ref), len(refs(role)) == 1) for role in shape["categories"] for ref in refs(role)]
    grp_refs = refs(shape["group_by"]) if shape["group_by"] else []
    grp = (shape["group_by"], describe(grp_refs[0]), True) if grp_refs else None
    val = [(role, describe(ref), len(refs(role)) == 1) for role in shape["values"] for ref in refs(role)]
    if not rows:
        raise ValueError("query returned no rows")
    sample = rows[0]
    missing, cols = [], {}
    for role, d, single in cat + ([grp] if grp else []) + val:
        key = _lookup(sample, d["name"], role, single)
        if key is None:
            missing.append(f'"{d["name"]}"')
        cols[(role, d["name"])] = key
    if missing:
        raise ValueError(f"query must return a column per field, named after it: missing {', '.join(missing)}")

    keys, index, series, sindex, cells = [], {}, [], {}, {}
    for r in rows:
        key = tuple(r.get(cols[(role, d["name"])]) for role, d, _ in cat)
        i = index.setdefault(key, len(keys))
        if i == len(keys):
            keys.append(key)
        s = 0
        if grp:
            sv = r.get(cols[(grp[0], grp[1]["name"])])
            s = sindex.setdefault(sv, len(series))
            if s == len(series):
                series.append(sv)
        for j, (role, d, _) in enumerate(val):
            v = r.get(cols[(role, d["name"])])
            if v is not None:
                prev = cells.get((i, s, j))
                cells[(i, s, j)] = v if prev is None or not isinstance(v, (int, float)) else prev + v

    def source(role, d, group=None):
        src = {"displayName": d["name"], "queryName": d["query"], "roles": {role: True}, "type": {d["type"]: True}}
        if d["measure"]:
            src.update(isMeasure=True, format=d.get("format") or None)
        elif d.get("format"):
            # a date column's format string; the visuals' formatter reads "mm" as minutes, so older
            # models written as "yyyy-mm-dd" are read with the month they meant
            src["format"] = "yyyy-MM-dd" if d["format"] == "yyyy-mm-dd" else d["format"]
        if group is not None:
            src["groupName"] = group
        return src

    categories = [{"source": source(role, d), "values": [k[n] for k in keys]} for n, (role, d, _) in enumerate(cat)]
    column = lambda s, j, role, d, g=None: {"source": source(role, d, g),
                                             "values": [cells.get((i, s, j)) for i in range(len(keys))]}
    if grp:
        groups = [{"name": sv, "values": [column(s, j, role, d, sv) for j, (role, d, _) in enumerate(val)]}
                  for s, sv in enumerate(series)]
        return {"categories": categories, "groups": groups, "groupSource": source(grp[0], grp[1])}
    return {"categories": categories, "values": [column(0, j, role, d) for j, (role, d, _) in enumerate(val)]}


def theme_defaults(entry: dict, look: str) -> dict:
    """What the report theme sets for every Atlas-framework visual — the look and the theme palette — limited to
    the objects this visual has (a custom visual may leave some out)."""
    objs, out = entry.get("objects") or {}, {}
    chart = objs.get("chart") or {}
    if "look" in chart:
        out["chart"] = {"look": look if look in LOOKS else "soft", **({"shadow": 55} if "shadow" in chart else {})}
    if "source" in (objs.get("palette") or {}):
        out["palette"] = {"source": "theme"}
    return out


def objects_for(entry: dict, fmt: dict, defaults: dict | None = None) -> dict:
    """Format options as a data view's metadata.objects (colors as {solid: {color}}), over the theme's defaults."""
    out = {k: dict(v) for k, v in (defaults or {}).items()}
    for obj, props in (fmt or {}).items():
        spec = entry["objects"].get(obj, {})
        for prop, value in (props or {}).items():
            if value in ("", None):
                continue
            out.setdefault(obj, {})[prop] = {"solid": {"color": value}} if spec.get(prop) == "color" else value
    return out


# ---------------------------------------------------------------- themes

def theme(look: str = "soft", dark: bool = False, brand: str | None = None, palette: str | None = None,
          colors: list | None = None) -> dict | None:
    """A Power BI report theme from the Visual Atlas brand engine (palette from a brand color, Flat/Soft/3D
    container look, defaults for every Atlas visual). Needs Node; falls back to the shipped themes."""
    opts = {"look": look if look in LOOKS else "soft", "dark": bool(dark), "brand": brand,
            "mode": palette or ("spectrum" if brand else "atlas"), "colors": colors}
    node = shutil.which("node")
    if node and (folder() / "brand.js").exists():
        try:
            out = subprocess.run([node, str(KIT / "assets" / "atlas_theme.js"), str(folder() / "brand.js"), json.dumps(opts)],
                                 capture_output=True, text=True, timeout=60, check=True).stdout
            return json.loads(out)
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
    shipped = folder() / "themes" / f"atlas-theme-{opts['look']}{'-dark' if dark and opts['look'] == 'soft' else ''}.json"
    return json.loads(shipped.read_text(encoding="utf-8")) if shipped.exists() else None
