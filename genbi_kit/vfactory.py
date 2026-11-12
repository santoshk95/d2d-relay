"""Visual factory: the agent builds a new Power BI custom visual when nothing in the catalog fits.

    genbi visual new <name> --title "Radial Bars" [--like starter|<Atlas family>|<library visual>]
    genbi visual edit <library visual>    copy a library visual into the project to change it (same name and GUID)
    genbi visual build <name>             pbiviz package (TypeScript + ESLint) -> visuals/dist/<name>.pbiviz
    genbi visual test <name>              headless Chromium: sample data and every use in definition.yaml
                                          -> visuals/<name>/test.png and the problems found
    genbi visual list                     this project's custom visuals and the visual library
    genbi visual source <name> [file]     print the starter, an Atlas family, the framework (common) or a library visual

A visual's source lives in the project (visuals/<name>/); builds run in the kit (GENBI_VKIT) on one shared
node_modules. Every visual sits on the Visual Atlas framework (src/common: palette, looks, selection, tooltips,
landing page, Format-pane cards), so it behaves like the Atlas families in the prototype and in Power BI.
The web app adds the visuals a report uses (built and tested) to the visual library after each run.

The AI writes a visual's source, so nothing in it may run while the visual is built (security audit, 2026-11-11):
caps.js is read as data (caps.py), never run; a build gets only src/, style/, assets/ and stringResources/ with the
kit's own build settings (no config file of the visual's own); and check_source refuses what would make webpack or Less
run code or read files outside the visual (loader syntax in an import, a relative import leaving the visual's folder,
require.context, import.meta, @plugin, url() and data-uri() in a style, links).
"""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
import uuid
import zlib
from pathlib import Path

from . import KIT, atlas, caps, catalog, library_dir

VKIT = Path(os.environ.get("GENBI_VKIT", "/opt/genbi/vkit"))
NAME = re.compile(r"^[a-z][A-Za-z0-9]{2,39}$")
API_VERSION = "5.11.1"
# written by `new`, `build` and `test` - never edited by hand, and not part of the source a build depends on
MANAGED = ("src/common", "style/atlas.less", "capabilities.json", "test.png", "test.json")
MODULE = re.compile(r"^(powerbi-visuals-api|powerbi-visuals-utils-[a-z]+|powerbi-models|d3(-[a-z]+)?)$")
IMPORT = re.compile(r"""(?:\bfrom\s+|^\s*import\s+|\brequire\s*\()\s*["'`]([^"'`]+)["'`]""", re.M)
REFERENCE = re.compile(r"""^\s*///\s*<reference\s+path\s*=\s*["']([^"']+)["']""", re.M)
# What a build gets of a visual's folder: the code, the style, the icon and the translations. Anything else there
# (a webpack, Babel, PostCSS or ESLint config, a package.json) never reaches the build.
BUILD_PARTS = ("src", "style", "assets", "stringResources")
CODE = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
STYLE = {".less", ".css"}
LESS_IMPORT = re.compile(r"@import\b([^;]*)", re.I)
LESS_PLAIN_IMPORT = re.compile(r"""^\s*(?:\([a-z, ]*\)\s*)?["']([A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:less|css))["']\s*$""", re.I)
LESS_BANNED = [
    (re.compile(r"@plugin\b", re.I), "a Less plugin - it would run code while the visual is built"),
    (re.compile(r"`"), "JavaScript in a style (backticks)"),
    (re.compile(r"\b(data-uri|image-size|image-width|image-height)\s*\(", re.I),
     "a function that reads a file into the style - draw it in code, or keep the icon in assets/"),
    (re.compile(r"""\burl\s*\(\s*(?!["']?data:)""", re.I), "url() - a visual's style loads nothing (data: URLs only)"),
]
BANNED = [
    (re.compile(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write"),
     "builds markup from a string - create nodes with el() or document.createElement"),
    (re.compile(r"\beval\s*\(|\bnew\s+Function\s*\("), "runs code from a string"),
    (re.compile(r"\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon"),
     "network access - a visual gets all its data from the data view"),
    (re.compile(r"\b(localStorage|sessionStorage|indexedDB)\b|document\.cookie"), "browser storage is not available in Power BI"),
    (re.compile(r"\bset(Timeout|Interval)\s*\(\s*['\"`]"), "a timer with a code string"),
    (re.compile(r"\bimport\s*\("), "dynamic import - import modules at the top of the file"),
    (re.compile(r"Math\.random\s*\("), "random numbers - a visual must draw the same on every render (certification flags it)"),
    (re.compile(r"""["'`]https?://(?!www\.w3\.org/)"""), "an external URL - a visual loads nothing from the web"),
    (re.compile(r"\brequire\s*\.\s*(context|resolve)\b|\bwebpackContext\b|\bimport\s*\.\s*meta\b|__non_webpack_require__"),
     "a build-time module lookup - import each module by name at the top of the file"),
]


class VisualError(Exception):
    pass


def source_dir(project: Path, name: str) -> Path:
    return project / "visuals" / name


def package_path(project: Path, name: str) -> Path:
    return project / "visuals" / "dist" / f"{name}.pbiviz"


def families() -> list[str]:
    return sorted(p.name for p in (VKIT / "families").glob("atlas*") if p.is_dir())


# ---------------------------------------------------------------- new / edit

def _template(like: str | None) -> tuple[Path, str]:
    """The folder a new visual starts from and the display name in it to replace with the new title."""
    like = like or "starter"
    if like == "starter":
        return VKIT / "starter", "__TITLE__"
    for folder in (VKIT / "families" / like, library_dir() / like / "source"):
        if (folder / "caps.js").exists():
            return folder, json.loads((folder / "pbiviz.json").read_text(encoding="utf-8"))["visual"]["displayName"]
    raise VisualError(f"unknown template {like!r}: use starter, an Atlas family ({', '.join(families())}) "
                      f"or a library visual (`genbi visual list`)")


def _copy_source(src: Path, dest: Path) -> None:
    """caps.js, src/ and style/*.less of a visual, without the framework copy and build outputs."""
    dest.mkdir(parents=True)
    shutil.copy2(src / "caps.js", dest / "caps.js")
    shutil.copytree(src / "src", dest / "src", ignore=shutil.ignore_patterns("common"))
    (dest / "style").mkdir()
    for f in (src / "style").glob("*.less"):
        if f.name != "atlas.less":
            shutil.copy2(f, dest / "style" / f.name)


def _sync_framework(dest: Path) -> None:
    """src/common and style/atlas.less: the Visual Atlas framework, refreshed at every build."""
    shutil.rmtree(dest / "src" / "common", ignore_errors=True)
    shutil.copytree(VKIT / "common", dest / "src" / "common", ignore=shutil.ignore_patterns("*.less"))
    (dest / "style").mkdir(exist_ok=True)
    shutil.copy2(VKIT / "common" / "atlas.less", dest / "style" / "atlas.less")


def _icon(path: Path, seed: str) -> None:
    """20x20 PNG icon for the Visualizations pane: three bars in a color picked from the name."""
    hue = int(hashlib.md5(seed.encode()).hexdigest()[:4], 16) % 360
    import colorsys
    r, g, b = (round(c * 255) for c in colorsys.hls_to_rgb(hue / 360, 0.45, 0.65))
    px = [[(0, 0, 0, 0)] * 20 for _ in range(20)]
    for x0, y0 in ((2, 10), (8, 4), (14, 8)):
        for y in range(y0, 18):
            for x in range(x0, x0 + 4):
                px[y][x] = (r, g, b, 255)
    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in px)
    chunk = lambda t, data: struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20, 20, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _pbiviz(name: str, title: str, description: str) -> dict:
    return {"visual": {"name": name, "displayName": title, "guid": name + uuid.uuid4().hex.upper(),
                       "visualClassName": "Visual", "version": "1.0.0.0", "description": description or title,
                       "supportUrl": "https://learn.microsoft.com/power-bi/developer/visuals/", "gitHubUrl": ""},
            "apiVersion": API_VERSION, "author": {"name": "RELAY by PASDACS", "email": "info@pasdacs.com"},
            "assets": {"icon": "assets/icon.png"}, "externalJS": None, "style": "style/visual.less",
            "capabilities": "capabilities.json", "dependencies": None, "stringResources": [], "version": "1.0.0.0"}


def new(project: Path, name: str, title: str, description: str = "", like: str | None = None) -> Path:
    if not NAME.match(name):
        raise VisualError("the name must be camelCase letters and digits, 3-40 characters, starting with a lower-case "
                          "letter (e.g. radialBars)")
    dest = source_dir(project, name)
    if dest.exists():
        raise VisualError(f"visuals/{name} already exists - change it there, or pick another name")
    taken = {n.lower(): e for n, e in catalog().items()}
    if name.lower() in taken:
        lib = taken[name.lower()].get("origin") == "library"
        raise VisualError(f"{name} is already a visual" + (f" in the visual library - use it as it is (`genbi catalog {name}`), "
                                                           f"or `genbi visual edit {name}` to change it" if lib
                                                           else " in the catalog") + "; pick another name")
    src, old_title = _template(like)
    title = title.strip() or name
    _copy_source(src, dest)
    prefix = "g" + re.sub(r"[^a-z0-9]", "", name.lower())[:12]
    for f in [dest / "caps.js", *(dest / "src").rglob("*.ts"), *(dest / "style").glob("*.less")]:
        text = f.read_text(encoding="utf-8").replace("__TITLE__", title).replace("__PREFIX__", prefix)
        if old_title != "__TITLE__":
            text = text.replace(old_title, title)
            # its own prefix for SVG ids: visuals share one page in the prototype
            text = re.sub(r'(super\(options,\s*"[^"]+",\s*)"[^"]+"', rf'\1"{prefix}"', text)
        f.write_text(text, encoding="utf-8")
    (dest / "pbiviz.json").write_text(json.dumps(_pbiviz(name, title, description), indent=2) + "\n", encoding="utf-8")
    _icon(dest / "assets" / "icon.png", name)
    _sync_framework(dest)
    return dest


def edit(project: Path, name: str) -> Path:
    """Copy a library visual into the project with its name and GUID: once built, the project copy replaces the
    library one in this report, and the app updates the library entry after the run."""
    lib = library_dir() / name / "source"
    if not (lib / "pbiviz.json").exists():
        raise VisualError(f"{name} is not in the visual library (see `genbi visual list`)")
    dest = source_dir(project, name)
    if dest.exists():
        raise VisualError(f"visuals/{name} already exists in this project - change it there")
    _copy_source(lib, dest)
    shutil.copy2(lib / "pbiviz.json", dest / "pbiviz.json")
    if (lib / "assets" / "icon.png").exists():
        (dest / "assets").mkdir()
        shutil.copy2(lib / "assets" / "icon.png", dest / "assets" / "icon.png")
    else:
        _icon(dest / "assets" / "icon.png", name)
    _sync_framework(dest)
    return dest


# ---------------------------------------------------------------- build

def _inside(folder: Path, base: Path, spec: str) -> bool:
    """Whether a relative path written in a file of `folder` stays inside `base` (read as written, .. included)."""
    target = os.path.normpath(os.path.join(str(folder), spec))
    root = os.path.normpath(str(base))
    return target == root or target.startswith(root + os.sep)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _check_code(f: Path, rel: str, code_root: Path) -> list[str]:
    text = f.read_text(encoding="utf-8", errors="replace")
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(("//", "*", "/*")):
            continue
        out += [f"{rel}:{i}: {why}" for rx, why in BANNED if rx.search(line)]
    for m in IMPORT.finditer(text):                    # the whole file: an import may span lines
        mod, i = m.group(1), _line_of(text, m.start(1))
        if any(c in mod for c in "!?\\") or "${" in mod:
            out.append(f"{rel}:{i}: '{mod[:80]}' - no webpack loaders, queries or expressions in an import: name the "
                       "module or the file itself")
        elif mod.startswith("."):
            if not _inside(f.parent, code_root, mod):
                out.append(f"{rel}:{i}: '{mod[:80]}' leaves the visual's folder - import only the visual's own files")
        elif not MODULE.match(mod):
            out.append(f"{rel}:{i}: module '{mod[:80]}' is not installed (available: powerbi-visuals-api, "
                       "powerbi-visuals-utils-*, powerbi-models, d3 and d3-*)")
    for m in REFERENCE.finditer(text):
        if not _inside(f.parent, code_root, m.group(1)):
            out.append(f"{rel}:{_line_of(text, m.start(1))}: a /// <reference> to a file outside the visual's folder")
    return out


def _check_style(f: Path, rel: str) -> list[str]:
    text = f.read_text(encoding="utf-8", errors="replace")
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        out += [f"{rel}:{i}: {why}" for rx, why in LESS_BANNED if rx.search(line)]
    for m in LESS_IMPORT.finditer(text):
        plain = LESS_PLAIN_IMPORT.match(m.group(1))
        if not plain or not (plain.group(1) == "atlas.less" or (f.parent / plain.group(1)).is_file()):
            out.append(f"{rel}:{_line_of(text, m.start())}: @import{m.group(1)[:60]} - import only a .less or .css file of "
                       "the same folder, by its name (\"atlas.less\")")
    return out


def check_source(src: Path) -> list[str]:
    """What a visual must not do (APIs Power BI refuses, modules that are not installed), and what would make its
    build run code or read files outside the visual: links, webpack loader syntax, imports leaving the visual's
    folder, Less plugins and file functions (before spending a build on it). The framework (src/common,
    style/atlas.less) is the kit's own."""
    problems = [f"{p.relative_to(src).as_posix()}: a link - keep the visual's own files in its folder"
                for p in sorted(src.rglob("*")) if p.is_symlink()]
    for part in BUILD_PARTS:
        for f in sorted((src / part).rglob("*")) if (src / part).is_dir() else []:
            rel = f.relative_to(src).as_posix()
            if f.is_symlink() or not f.is_file() or rel.startswith("src/common/") or rel == "style/atlas.less":
                continue
            if f.suffix.lower() in CODE:
                problems += _check_code(f, rel, src)       # imports stay inside the visual's folder (src/, style/ ...)
            elif f.suffix.lower() in STYLE:
                problems += _check_style(f, rel)
    return problems


def _bump(version: str) -> str:
    parts = [int(x) if x.isdigit() else 0 for x in str(version).split(".")][:4]
    parts += [0] * (4 - len(parts))
    parts[3] += 1
    return ".".join(map(str, parts))


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
NOISE = re.compile(r"^\s*(info|warn|done)\s{2,}|^\s*$|Certificate|pbiviz-certs|Run `pbiviz package`|can be improved")


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1"}
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise VisualError(f"{cmd[0]} took longer than {timeout // 60} minutes") from None
    except FileNotFoundError:
        raise VisualError(f"{cmd[0]} is not installed here - custom visuals are built in the agent container") from None


def _report(out: str, work: Path, name: str, limit: int = 120) -> str:
    """Build output with the noise removed and paths shown as the project sees them."""
    text = ANSI.sub("", out).replace(str(work) + "/", f"visuals/{name}/").replace(str(work), f"visuals/{name}")
    lines = [ln.rstrip() for ln in text.splitlines() if not NOISE.search(ln)]
    return "\n".join(lines[:limit] + ([f"... {len(lines) - limit} more lines"] if len(lines) > limit else []))


def build(project: Path, name: str) -> dict:
    src = source_dir(project, name)
    if not (src / "pbiviz.json").exists():
        raise VisualError(f"visuals/{name}/pbiviz.json not found - start the visual with `genbi visual new {name}`")
    pv = json.loads((src / "pbiviz.json").read_text(encoding="utf-8"))
    vis = pv.get("visual") or {}
    if vis.get("name") != name or not str(vis.get("guid", "")).startswith(name):
        raise VisualError("pbiviz.json: keep visual.name and visual.guid as `genbi visual new` wrote them")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{2,80}", str(vis.get("guid"))) \
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", str(vis.get("visualClassName") or "Visual")):
        raise VisualError("pbiviz.json: visual.guid is letters and digits, visual.visualClassName a class name (Visual)")
    for need in ("caps.js", "src/visual.ts"):
        if not (src / need).exists():
            raise VisualError(f"visuals/{name}/{need} is missing")
    problems = check_source(src)
    if problems:
        raise VisualError("fix these first:\n" + "\n".join(f"  {p}" for p in problems))
    try:
        spec = caps.read_file(src / "caps.js")           # read as data, never run (caps.py)
    except caps.CapsError as e:
        raise VisualError(f"caps.js: {e}") from None
    _sync_framework(src)                      # the framework copy Claude reads is always the current one
    work = VKIT / "builds" / name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    for part in BUILD_PARTS:                  # the visual's code, style, icon and translations; never a config of its own
        if (src / part).is_dir():
            shutil.copytree(src / part, work / part, symlinks=True,
                            ignore=shutil.ignore_patterns("dist", ".tmp", "node_modules"))
    for f in ("tsconfig.json", "eslint.config.mjs"):
        shutil.copy2(VKIT / f, work / f)
    (work / "package.json").write_text(json.dumps({"name": name.lower(), "private": True, "version": "1.0.0"}), encoding="utf-8")
    (work / "node_modules").symlink_to(VKIT / "node_modules", target_is_directory=True)   # pbiviz wants it right here
    if not (work / "assets" / "icon.png").exists():
        _icon(work / "assets" / "icon.png", name)
    pv["visual"]["version"] = _bump(vis.get("version", "1.0.0.0"))
    pv.update(apiVersion=API_VERSION, externalJS=None, capabilities="capabilities.json", style="style/visual.less",
              assets={"icon": "assets/icon.png"}, dependencies=None, stringResources=[])
    (work / "pbiviz.json").write_text(json.dumps(pv, indent=2), encoding="utf-8")
    (work / "capabilities.json").write_text(caps.text(spec), encoding="utf-8")
    started = time.time()
    res = _run(["pbiviz", "package", "--skip-api", "--no-stats"], work, 900)
    built = sorted((work / "dist").glob("*.pbiviz"))
    if res.returncode or not built:
        raise VisualError("build failed:\n" + _report(res.stdout + res.stderr, work, name))
    # the version and generated capabilities go back to the source; the package is written last (newest file)
    (src / "pbiviz.json").write_text(json.dumps(pv, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(work / "capabilities.json", src / "capabilities.json")
    dest = package_path(project, name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built[-1], dest)
    entry = atlas.read_package(dest)[0]
    warnings = [ln for ln in _report(res.stdout + res.stderr, work, name).splitlines() if re.search(r"warn|warning", ln, re.I)]
    return {"name": name, "guid": entry["guid"], "version": entry["version"], "bytes": dest.stat().st_size,
            "seconds": round(time.time() - started, 1), "roles": entry["roles"], "required": entry["required"],
            "objects": list(entry["objects"]), "warnings": warnings[:20]}


# ---------------------------------------------------------------- test

NAMES = ["North", "South", "East", "West", "Central", "Online"]
INNER = ["Bikes", "Clothing", "Accessories", "Components"]
SERIES = ["2024", "2025", "2026"]
TIMELIKE = re.compile(r"date|time|month|period|day|week|year", re.I)


def _sample(entry: dict, every: bool):
    """(fields, rows, describe) with made-up data for the wells the visual needs (or all of them)."""
    shape, info = entry["shape"], entry.get("role_info") or {}
    need = set(entry["required"][0]) if entry.get("required") else set(shape["categories"][:1] + shape["values"][:1])
    use = set(entry["roles"]) if every else need
    cats = [r for r in shape["categories"] if r in use]
    group = shape["group_by"] if shape["group_by"] in use else None
    vals = [r for r in shape["values"] if r in use]
    if not cats and not vals:
        return None
    labels, seen = {}, set()
    for r in cats + ([group] if group else []) + vals:
        label = (info.get(r) or {}).get("displayName") or r
        labels[r] = label if label.lower() not in seen else f"{label} ({r})"
        seen.add(labels[r].lower())
    types, keys = {}, [[]]
    for k, r in enumerate(cats):
        if TIMELIKE.search(r) or TIMELIKE.search(labels[r]):
            opts, types[labels[r]] = [f"2026-{m:02d}-01" for m in range(1, 13)], "dateTime"
        else:
            opts = (NAMES, INNER, SERIES)[min(k, 2)]
        keys = [kk + [o] for kk in keys for o in opts][:48]
    rows = []
    for kk in keys:
        for g in (SERIES if group else [None]):
            row = {labels[r]: kk[i] for i, r in enumerate(cats)}
            if group:
                row[labels[group]] = g
            for r in vals:
                row[labels[r]] = 40 + int(hashlib.md5(f"{kk}{g}{r}".encode()).hexdigest()[:6], 16) % 960
            rows.append(row)
    fields = {r: [f"Sample[{labels[r]}]"] for r in cats + ([group] if group else [])}
    fields.update({r: [f"[{labels[r]}]"] for r in vals})

    def describe(ref):
        measure, name = ref.startswith("["), ref[ref.index("[") + 1:-1]
        kind = "numeric" if measure else types.get(name, "text")
        return {"name": name, "query": f"Sample.{name}", "measure": measure, "type": kind,
                "format": "#,0" if measure else "yyyy-MM-dd" if kind == "dateTime" else None}
    return fields, rows, describe


TEST_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>__NAME__ test</title><style>
body{margin:0;padding:14px;background:#e9ecef;font:12px 'Segoe UI',Arial,sans-serif;color:#252423}
#cases{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}
.case{background:#fff;border:1px solid #d0d5dc;border-radius:8px;padding:8px 8px 10px}
.case.dark{background:#1f1f1f;border-color:#3b3b3b;color:#e8e8e8}
.cap{font-weight:600;margin:0 0 6px}
.vbox{position:relative;overflow:hidden}
.gba-tip{position:fixed;z-index:9;background:#fff;border:1px solid #ccc;border-radius:4px;padding:4px 6px}
__CSS__
</style></head><body><div id="cases"></div>
<script>__HOST__</script>
<script>__JS__</script>
<script>
const GUID = __GUID__, CASES = __CASES__, BOXES = [], RESULTS = [];
for (const c of CASES) {
  const wrap = document.createElement('div'), cap = document.createElement('div'), box = document.createElement('div');
  wrap.className = 'case' + (c.theme.dark ? ' dark' : ''); cap.className = 'cap'; box.className = 'vbox';
  cap.textContent = c.title + '  (' + c.w + ' x ' + c.h + ')';
  box.style.width = c.w + 'px'; box.style.height = c.h + 'px'; box.style.background = c.theme.dark ? '#1f1f1f' : '#ffffff';
  wrap.append(cap, box); document.getElementById('cases').appendChild(wrap);
  const r = {title: c.title, data: !!c.item, errors: []};
  try {
    let v;
    if (c.item) v = GenBIAtlas.render(box, c.item, c.theme);
    else {
      v = window.powerbi.visuals.plugins[GUID].create({element: box, host: GenBIAtlas.makeHost(c.theme)});
      v.update({dataViews: [], viewport: {width: c.w, height: c.h}, type: 2});
    }
    if (v && v.getFormattingModel) { const fm = v.getFormattingModel(); r.cards = fm && fm.cards ? fm.cards.length : 0; }
  } catch (e) { r.errors.push(String((e && e.stack) || e).split('\n').slice(0, 4).join(' | ')); }
  BOXES.push(box); RESULTS.push(r);
}
window.measure = function () {
  return RESULTS.map((r, i) => {
    const box = BOXES[i], b = box.getBoundingClientRect(), out = Object.assign({}, r);
    out.landing = !!box.querySelector('.atl-landing');
    const shapes = [...box.querySelectorAll('svg rect, svg path, svg circle, svg ellipse, svg line, svg polygon, svg polyline, svg text, svg image')]
      .filter(e => !e.closest('defs, clipPath, mask, pattern, marker'));
    out.marks = shapes.filter(e => e.tagName !== 'text').length;
    out.texts = shapes.filter(e => e.tagName === 'text' && e.textContent.trim()).length;
    const scrolls = box.style.overflow === 'auto', over = {right: 0, bottom: 0, left: 0, top: 0}, texts = [];
    for (const e of shapes) {
      const q = e.getBoundingClientRect();
      if ((!q.width && !q.height) || e.getAttribute('fill') === 'transparent' || e.classList.contains('hit')) continue;
      if (!scrolls) {
        over.right = Math.max(over.right, q.right - b.right); over.bottom = Math.max(over.bottom, q.bottom - b.bottom);
        over.left = Math.max(over.left, b.left - q.left); over.top = Math.max(over.top, b.top - q.top);
      }
      if (e.tagName === 'text' && e.textContent.trim()) texts.push(q);
    }
    out.overflow = over;
    let overlaps = 0;
    for (let a = 0; a < texts.length && a < 400; a++) for (let k = a + 1; k < texts.length && k < 400; k++) {
      const p = texts[a], q = texts[k];
      const w = Math.min(p.right, q.right) - Math.max(p.left, q.left), h = Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top);
      if (w > 1 && h > 1 && w * h > 0.4 * Math.min(p.width * p.height, q.width * q.height)) overlaps++;
    }
    out.overlaps = overlaps;
    return out;
  });
};
window.DONE = true;
</script></body></html>"""


def _cases(project: Path, entry: dict) -> tuple[list[dict], list[str], list[str]]:
    """Every use of the visual in definition.yaml (prototype data, its size on the page), then sample data at a normal
    and a small size, on a dark report, with every well filled, and with no data at all."""
    from . import data as data_mod
    from . import definition, prototype
    cases, problems, notes = [], [], []
    d = None
    if (project / "definition.yaml").exists():
        try:
            d = definition.expand(definition.load(project / "definition.yaml"))
        except Exception as e:  # noqa: BLE001 - the test still runs on sample data
            notes.append(f"definition.yaml not used: {str(e).splitlines()[0][:200]}")
    t = d["theme"] if d else definition._theme({})
    light = {"palette": t.get("data_colors"), "dark": bool(t.get("dark"))}
    if d:
        uses = [(p, v) for p in d["pages"] for v in p["visuals"] if v["type"] == entry["name"]]
        con = data_mod.connect(project, d) if uses else None
        describe = prototype._describer(d)
        for page, v in uses:
            try:
                sql = (v.get("prototype") or {}).get("sql")
                if not sql:
                    raise ValueError("missing prototype.sql")
                item = prototype._atlas_item(v, entry, prototype.records(con, sql), describe, t)
                cases.append({"title": f"{page['name']} / {v['id']}", "w": max(120, int(v["w"]) - 24),
                              "h": max(90, int(v["h"]) - 56), "item": item, "theme": light})
            except Exception as e:  # noqa: BLE001 - reported
                problems.append(f"{page['name']} / {v['id']}: {str(e).splitlines()[0][:300]}")
    for every in (False, True):
        sample = _sample(entry, every)
        if not sample or (every and set(sample[0]) == set((_sample(entry, False) or ({},))[0])):
            continue
        fields, rows, describe = sample
        item = prototype._atlas_item({"fields": fields, "format": {}}, entry, rows, describe, t)
        if every:
            cases.append({"title": "sample data, every field well", "w": 560, "h": 340, "item": item, "theme": light})
            continue
        cases += [{"title": "sample data", "w": 560, "h": 340, "item": item, "theme": light},
                  {"title": "sample data, small", "w": 280, "h": 170, "item": item, "theme": light},
                  {"title": "sample data, dark report", "w": 560, "h": 340, "item": item,
                   "theme": {**light, "dark": not light["dark"]}}]
    cases.append({"title": "no data (landing page)", "w": 360, "h": 200, "item": None, "theme": light})
    return cases, problems, notes


def _browse(page_path: Path, png: Path) -> tuple[list[dict], list[str]]:
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    with sync_playwright() as pw:
        from .display import OFFLINE_ARGS, offline
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", *OFFLINE_ARGS])
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            offline(page, page_path.as_uri())       # the visual's code is the AI's: it loads nothing (BANNED) and reaches nothing
            page.on("pageerror", lambda e: errors.append(f"uncaught: {e}"))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" or (
                m.type == "warning" and m.text.startswith("render failed")) else None)
            page.goto(page_path.as_uri())
            page.wait_for_function("window.DONE === true", timeout=60000)
            page.wait_for_timeout(500)                      # mark transitions settle
            results = page.evaluate("window.measure()")
            page.screenshot(path=str(png), full_page=True)
        finally:
            browser.close()
    return results, errors


def test(project: Path, name: str) -> dict:
    src, pkg = source_dir(project, name), package_path(project, name)
    if not pkg.exists():
        raise VisualError(f"{name} is not built yet - run `genbi visual build {name}`")
    if _source_mtime(src) > pkg.stat().st_mtime:
        raise VisualError(f"visuals/{name} changed after the last build - run `genbi visual build {name}` first")
    entry, js, css = atlas.read_package(pkg)
    cases, problems, notes = _cases(project, entry)
    html = (TEST_PAGE.replace("__NAME__", name).replace("__CSS__", css)
            .replace("__HOST__", (KIT / "assets" / "atlas_host.js").read_text(encoding="utf-8"))
            .replace("__GUID__", json.dumps(entry["guid"]))
            .replace("__CASES__", json.dumps(cases, default=str).replace("</", "<\\/"))
            .replace("__JS__", js.replace("</script", "<\\/script")))
    work = VKIT / "builds" if (VKIT / "builds").is_dir() else src
    page_path = work / f"{name}-test.html"
    page_path.write_text(html, encoding="utf-8")
    png = src / "test.png"
    results, errors = _browse(page_path, png)
    problems += [f"browser: {e[:300]}" for e in dict.fromkeys(errors)]
    for r in results:
        where = r["title"]
        problems += [f"{where}: {e[:400]}" for e in r["errors"]]
        if r["data"]:
            if r["landing"]:
                problems.append(f"{where}: shows the landing page instead of the chart - the data did not reach the "
                                "field wells it needs (check the roles, mappings and `min` conditions in caps.js)")
            elif not r["marks"] and not r["texts"]:
                problems.append(f"{where}: drew nothing")
            o = r["overflow"]
            side = max(o, key=o.get)
            if o[side] > 3:
                notes.append(f"{where}: drawn {round(o[side])} px past the {side} edge - it will be cut off")
            if r["overlaps"]:
                notes.append(f"{where}: {r['overlaps']} pair(s) of labels overlap")
        elif not r["landing"] and not r["errors"]:
            notes.append(f"{where}: no landing page with empty data")
    summary = {"name": name, "version": entry["version"], "package": _sha(pkg), "ok": not problems,
               "cases": [r["title"] for r in results], "problems": problems, "notes": notes, "when": time.time()}
    (src / "test.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {**summary, "screenshot": f"visuals/{name}/test.png"}


# ---------------------------------------------------------------- state, library

def _source_mtime(src: Path) -> float:
    latest = 0.0
    for f in src.rglob("*"):
        rel = f.relative_to(src).as_posix()
        if f.is_file() and not any(rel == m or rel.startswith(m + "/") for m in MANAGED):
            latest = max(latest, f.stat().st_mtime)
    return latest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def status(project: Path) -> list[dict]:
    """The project's custom visuals: built, changed since the build, tested on the current package."""
    out = []
    for src in sorted(p for p in (project / "visuals").glob("*") if (p / "pbiviz.json").exists()):
        name = src.name
        try:
            vis = json.loads((src / "pbiviz.json").read_text(encoding="utf-8"))["visual"]
        except (ValueError, KeyError):
            vis = {}
        pkg = package_path(project, name)
        built = pkg.exists()
        sha = _sha(pkg) if built else None
        try:
            tested = json.loads((src / "test.json").read_text(encoding="utf-8")) if (src / "test.json").exists() else None
        except ValueError:
            tested = None
        current = bool(tested and tested.get("package") == sha)
        out.append({"name": name, "title": vis.get("displayName", name), "description": vis.get("description", ""),
                    "guid": vis.get("guid"), "version": vis.get("version"), "built": built,
                    "stale": built and _source_mtime(src) > pkg.stat().st_mtime,
                    "tested": current and bool(tested.get("ok")), "test_problems": tested.get("problems") if current else None})
    return out


def library() -> list[dict]:
    """Records of the visuals in the visual library, newest first."""
    out = []
    for f in library_dir().glob("*/visual.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda r: r.get("updated", 0), reverse=True)


def promote(project: Path, name: str, origin: dict) -> tuple[str, dict]:
    """Copy a built, tested custom visual into the visual library (package, source, preview, record).
    Returns ("added" | "updated" | "unchanged", record)."""
    src, pkg = source_dir(project, name), package_path(project, name)
    entry = atlas.read_package(pkg)[0]
    lib = library_dir()
    dest = lib / name
    old = json.loads((dest / "visual.json").read_text(encoding="utf-8")) if (dest / "visual.json").exists() else None
    if old and old.get("guid") != entry["guid"]:
        raise VisualError(f"a different visual named {name} is already in the visual library")
    sha = _sha(pkg)
    if old and old.get("sha") == sha:
        return "unchanged", old
    tmp = lib / f".{name}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copyfile(pkg, tmp / f"{name}.pbiviz")
    _copy_source(src, tmp / "source")
    shutil.copy2(src / "pbiviz.json", tmp / "source" / "pbiviz.json")
    if (src / "assets" / "icon.png").exists():
        (tmp / "source" / "assets").mkdir()
        shutil.copy2(src / "assets" / "icon.png", tmp / "source" / "assets" / "icon.png")
    if (src / "test.png").exists():
        shutil.copy2(src / "test.png", tmp / "preview.png")
    now = time.time()
    record = {"name": name, "title": entry["displayName"], "description": entry["description"], "guid": entry["guid"],
              "version": entry["version"], "sha": sha, "roles": entry["roles"], "role_info": entry["role_info"],
              "required": entry["required"], "created": (old or {}).get("created", now), "updated": now, **origin}
    (tmp / "visual.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    return ("updated" if old else "added"), record


def remove(name: str) -> None:
    if not NAME.match(name) or not (library_dir() / name / "visual.json").exists():
        raise VisualError(f"{name} is not in the visual library")
    shutil.rmtree(library_dir() / name)


def source_files(name: str) -> list[Path]:
    """The source files of the starter, an Atlas family, the framework (common) or a library visual."""
    if name == "common":
        return sorted((VKIT / "common").glob("*.ts"))
    folder, _ = _template(name)
    return [folder / "caps.js"] + sorted(p for p in (folder / "src").rglob("*.ts") if "common" not in p.parts) \
        + sorted((folder / "style").glob("*.less"))
