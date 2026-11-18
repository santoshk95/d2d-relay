"""Item 58 (the user, 2026-11-18): a new dashboard from a DAWB hand-off, with DAWB's plan as given.

DAWB, the lakehouse builder, writes a D2D project after every lakehouse build: project.json (kind "d2d-project",
format 1: the description, the inputs with their columns and types, and the plan: model, KPIs and pages with their
visuals), data/<table>.csv, and manifest.json (every file with its rows and sha256, written last). The person uploads
the folder as one .zip on New dashboard. Before anything is saved or charged, stage() checks it against its manifest
and reads it as D2D reads any upload (every file's checksum, each CSV's columns and rows, D2D's own profile, the
relationships' keys in the data, D2D's plan check). The staged folder then becomes the dashboard (main.import_project):
profile.md / profile.json as Relay's planning makes them, plan.yaml from DAWB's plan (its KPIs and pages; its visual
queries and 24-column grid go to the build as guidance in request.md), waiting at Confirm KPIs. It costs what any new
dashboard costs (the user's choice): only the planning run is skipped.
"""
import contextlib
import csv
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
import zlib
from pathlib import Path

import duckdb

from genbi_kit import validate as checks
from genbi_kit.data import _q, _source
from genbi_kit.plaintext import human
from genbi_kit.profile import profile

KIND, FORMAT = "d2d-project", 1
# DAWB's column types, and the model type each becomes in D2D's build (definition.yaml)
TYPES = {"text": "string", "whole number": "int", "decimal": "decimal", "date": "date", "date and time": "date",
         "true or false": "bool"}
# DAWB's KPI formats as Power BI format strings; a KPI's own format_string wins. A percent KPI returns a fraction.
FORMATS = {"currency": "\\$#,0", "percent": "0.0%", "whole number": "#,0", "decimal": "#,0.00"}
ROLES = ("fact", "dimension", "date table")
TABLE = re.compile(r"[a-z][a-z0-9_]{0,62}")
REL = re.compile(r"\s*([a-z][a-z0-9_]{0,62})\[([^\[\]]+)\]\s*->\s*([a-z][a-z0-9_]{0,62})\[([^\[\]]+)\]\s*")
BAD_NAME = re.compile(r"[\[\]\x00-\x1f]")
LIMIT_GB = float(os.environ.get("D2D_HANDOFF_MAX_GB") or 8)
MAX_BYTES = int(LIMIT_GB * 1024 ** 3)            # the upload, and everything in it unpacked
MAX_JSON = 8 * 1024 * 1024                       # project.json, manifest.json
MAX_MEMBERS = 2000
CHUNK = 1024 * 1024
STALE_S = 24 * 3600                              # an import's leftovers after a restart
SHOWN = 6                                        # problems named in one refusal


class HandoffError(Exception):
    """Why a hand-off cannot be imported, in words for the person (HTTP 400): each problem, the first few named."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else [p for p in problems if p]
        super().__init__(self.text())

    def text(self) -> str:
        shown, more = self.problems[:SHOWN], len(self.problems) - SHOWN
        return ("This hand-off cannot be imported: " + "; ".join(shown)
                + (f"; and {more} more problem{'s' if more > 1 else ''}." if more > 0 else "."))


def sweep(root: Path) -> None:
    """Leftovers of imports a restart cut off (a staging folder or an upload older than a day)."""
    now = time.time()
    for p in Path(root).glob(".import-*"):
        with contextlib.suppress(OSError):
            if now - p.stat().st_mtime > STALE_S:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


def _text(v, limit: int = 2000) -> str:
    """One line of DAWB's words (a description, a purpose, a title), in plain keyboard characters."""
    return human(" ".join(str(v).split())[:limit]) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _name_ok(name) -> bool:
    return isinstance(name, str) and bool(name) and name == name.strip() and len(name) <= 128 and not BAD_NAME.search(name)


# ---------------------------------------------------------------- the zip

def _norm(name: str) -> str | None:
    """A path in the zip or the manifest as a/b/c (None: it would leave the folder)."""
    raw = name.replace("\\", "/")              # Windows PowerShell 5.1's Compress-Archive writes backslashes
    if raw.startswith("/") or re.match(r"[A-Za-z]:", raw):
        return None
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    return None if ".." in parts else "/".join(parts)


def _members(z: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS:
        raise HandoffError(f"the zip holds {len(infos):,} files, more than a hand-off has (at most {MAX_MEMBERS:,})")
    out: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if info.filename.replace("\\", "/").endswith("/"):
            continue                            # a folder
        name = _norm(info.filename)
        if name is None:
            raise HandoffError(f"the zip names a file outside its folder ({info.filename})")
        if not name or name.split("/")[0] == "__MACOSX":
            continue
        if name in out:
            raise HandoffError(f"the zip holds {name} twice")
        if info.flag_bits & 0x1:
            raise HandoffError("the zip is password-protected: zip the folder again without a password")
        out[name] = info
    return out


def _root(names) -> str:
    """Where project.json is: at the top of the zip, or in one folder (the hand-off folder zipped as it is)."""
    found = [n for n in names if n == "project.json" or (n.count("/") == 1 and n.endswith("/project.json"))]
    if not found:
        raise HandoffError("the zip has no project.json at its top or in one folder: zip the hand-off folder DAWB wrote, "
                           "as it is")
    if len(found) > 1:
        raise HandoffError("the zip holds more than one hand-off: zip one hand-off folder at a time")
    return found[0][: -len("project.json")]


def _read_json(z: zipfile.ZipFile, info: zipfile.ZipInfo, label: str) -> tuple[dict, bytes]:
    if info.file_size > MAX_JSON:
        raise HandoffError(f"{label} is {info.file_size:,} bytes, too large for a hand-off")
    try:
        raw = z.read(info)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as e:
        raise HandoffError(f"{label} cannot be read from the zip ({e.__class__.__name__})") from e
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise HandoffError(f"{label} is not valid JSON ({str(e).splitlines()[0][:120]})") from e
    if not isinstance(data, dict):
        raise HandoffError(f"{label} must hold an object")
    return data, raw


# ---------------------------------------------------------------- project.json

def _check_project(p: dict) -> list[str]:
    if p.get("kind") != KIND or p.get("format") != FORMAT:
        return [f"project.json is not a D2D project hand-off of format {FORMAT} (it says kind {p.get('kind')!r}, "
                f"format {p.get('format')!r})"]
    out = [] if _text(p.get("name")) else ["project.json has no name"]
    inputs = p.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        return out + ["project.json lists no inputs (the CSV files)"]
    tables: dict[str, dict] = {}
    for i, inp in enumerate(inputs):
        t = inp.get("table") if isinstance(inp, dict) else None
        if not isinstance(t, str) or not TABLE.fullmatch(t):
            out.append(f"input {i + 1}: the table name {t!r} must be lowercase letters, digits and _, starting with a letter")
            continue
        if t in tables:
            out.append(f"the table {t} is listed twice")
            continue
        if inp.get("file") != f"data/{t}.csv":
            out.append(f"{t}: its file must be data/{t}.csv (it says {inp.get('file')!r})")
        rows = inp.get("rows")
        if not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
            out.append(f"{t}: its rows must be a whole number")
        cols = inp.get("columns")
        if not isinstance(cols, list) or not cols:
            out.append(f"{t}: no columns are listed")
            continue
        seen: set[str] = set()
        for j, col in enumerate(cols):
            name = col.get("name") if isinstance(col, dict) else None
            if not _name_ok(name):
                out.append(f"{t}: column {j + 1} has no usable name ({name!r})")
                continue
            if name.lower() in seen:
                out.append(f"{t}: the column {name} is listed twice")
            seen.add(name.lower())
            if col.get("type") not in TYPES:
                out.append(f"{t}[{name}]: the type {col.get('type')!r} is not one of {', '.join(TYPES)}")
        tables[t] = inp
    plan = p.get("plan")
    if not isinstance(plan, dict):
        return out + ["project.json has no plan"]
    model = plan.get("model") if plan.get("model") is not None else {}
    if not isinstance(model, dict):
        out.append("the plan's model must be an object")
        model = {}
    listed = model.get("tables")
    if listed is not None and not isinstance(listed, list):
        out.append("the plan's model tables must be a list")
        listed = []
    for x in listed or []:
        name = x if isinstance(x, str) else x.get("name") if isinstance(x, dict) else None
        if name not in tables:
            out.append(f"the plan's model names the table {name!r}, which is not one of the inputs")
        elif isinstance(x, dict) and x.get("role") is not None and x.get("role") not in ROLES:
            out.append(f"{name}: its role must be fact, dimension or date table")
    kpis = plan.get("kpis")
    if not isinstance(kpis, list) or not kpis:
        out.append("the plan has no KPIs")
    else:
        names: set[str] = set()
        for i, k in enumerate(kpis):
            n = k.get("name") if isinstance(k, dict) else None
            if not _name_ok(n) or len(n) > 100:
                out.append(f"KPI {i + 1} has no usable name ({n!r})")
                continue
            if n.lower() in names:
                out.append(f"the KPI {n} is listed twice")
            names.add(n.lower())
            if not isinstance(k.get("dax"), str) or not k["dax"].strip() or len(k["dax"]) > 20000:
                out.append(f"the KPI {n} has no DAX")
            fs = k.get("format_string")
            if fs is not None and (not isinstance(fs, str) or not fs.strip() or len(fs) > 100):
                out.append(f"the KPI {n}: its format_string must be a Power BI format string")
            elif fs is None and k.get("format") not in FORMATS:
                out.append(f"the KPI {n}: its format {k.get('format')!r} is not one of {', '.join(FORMATS)}")
    pages = plan.get("pages")
    if not isinstance(pages, list) or not pages:
        out.append("the plan has no pages")
    else:
        seen = set()
        for i, pg in enumerate(pages):
            n = pg.get("name") if isinstance(pg, dict) else None
            if not isinstance(n, str) or not n.strip():
                out.append(f"page {i + 1} has no name")
                continue
            if n.strip().lower() in seen:
                out.append(f"the page {n.strip()} is listed twice")
            seen.add(n.strip().lower())
            visuals = pg.get("visuals")
            if visuals is not None and not (isinstance(visuals, list) and all(isinstance(v, (dict, str)) for v in visuals)):
                out.append(f"the page {n.strip()}: its visuals must be a list")
    return out


def _filter_paths(rels: list[tuple[str, str, str, str]]) -> list[str]:
    """What Power BI would find ambiguous: filters flow from a relationship's one side to its many side, and no table
    may reach another along two such paths (it makes one of them inactive), nor come back to itself. A star with
    shared dimensions (dates and stores over several marts) is fine: each dimension reaches each mart once."""
    down: dict[str, list[str]] = {}
    for a, _ac, b, _bc in rels:
        down.setdefault(b, []).append(a)
    out, budget = [], 200_000
    for start in sorted(down):
        reached: dict[str, int] = {}
        stack = [(start, (start,))]
        while stack:
            budget -= 1
            if budget < 0:
                return ["the relationships are too many to check for a single filter path between tables"]
            node, trail = stack.pop()
            for nxt in down.get(node, []):
                if nxt in trail:
                    loop = " -> ".join(trail[trail.index(nxt):] + (nxt,))
                    msg = f"the relationships go round in a circle ({loop}); Power BI needs filters to flow one way"
                    return out + [msg] if msg not in out else out
                reached[nxt] = reached.get(nxt, 0) + 1
                stack.append((nxt, trail + (nxt,)))
        out += [f"the relationships give {start} {n} filter paths to {t}; Power BI needs a single one"
                for t, n in sorted(reached.items()) if n > 1]
    return out


def _relationships(p: dict) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """The plan's relationships as (many table, column, one table, column), and what is wrong with them: each written
    "many_table[column] -> one_table[column]", both columns in the inputs with the same type, and a single filter
    path from any table to another (_filter_paths)."""
    raw = ((p.get("plan") or {}).get("model") or {}).get("relationships")
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list):
        return [], ["the plan's model relationships must be a list"]
    cols = {i["table"]: {c["name"]: c["type"] for c in i["columns"]} for i in p["inputs"]}
    rels, out = [], []
    for r in raw:
        m = REL.fullmatch(r) if isinstance(r, str) else None
        if not m:
            out.append(f"the relationship {r!r} must read many_table[column] -> one_table[column]")
            continue
        a, ac, b, bc = m.groups()
        text = f"{a}[{ac}] -> {b}[{bc}]"
        missing = [f"{t}[{c}]" for t, c in ((a, ac), (b, bc)) if c not in cols.get(t, {})]
        if missing:
            out.append(f"the relationship {text} names {' and '.join(missing)}, not in the inputs")
            continue
        if a == b:
            out.append(f"the relationship {text} joins a table to itself")
            continue
        if cols[a][ac] != cols[b][bc]:
            out.append(f"the relationship {text} joins a {cols[a][ac]} column to a {cols[b][bc]} column; both sides need "
                       "the same type")
            continue
        if any(x[0] == a and x[2] == b for x in rels):
            out.append(f"the relationship {text} is a second one between {a} and {b}; Power BI needs a single one")
            continue
        rels.append((a, ac, b, bc))
    return rels, out + (_filter_paths(rels) if not out else [])


# ---------------------------------------------------------------- manifest.json and the files

def _check_manifest(m: dict, members: dict, root: str, p: dict) -> tuple[dict, list[str]]:
    files = m.get("files")
    if not isinstance(files, dict) or not files:
        return {}, ["manifest.json lists no files"]
    out: dict[str, dict] = {}
    problems = [] if str(m.get("run") or "").strip() else ["manifest.json has no run"]
    named = set()
    for path, info in files.items():
        norm = _norm(str(path))
        if not norm:
            problems.append(f"manifest.json names a file outside the folder ({path})")
            continue
        named.add(norm)
        sha = str(info.get("sha256") or "").lower() if isinstance(info, dict) else ""
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            problems.append(f"manifest.json gives {norm} no sha256")
            continue
        member = members.get(root + norm)
        if member is None:
            problems.append(f"{norm} is in the manifest but not in the zip")
            continue
        out[norm] = {"member": member, "sha256": sha, "rows": info.get("rows"), "columns": info.get("columns")}
    if "project.json" not in named:
        problems.append("manifest.json does not list project.json")
    for inp in p["inputs"]:
        f = out.get(inp["file"])
        if f is None:
            if inp["file"] not in named:
                problems.append(f"{inp['file']} is not in the manifest")
            continue
        if f["rows"] is not None and f["rows"] != inp["rows"]:
            problems.append(f"{inp['file']}: project.json says {inp['rows']:,} rows and the manifest {f['rows']}")
        if isinstance(f["columns"], dict) and list(f["columns"].items()) != [(c["name"], c["type"]) for c in inp["columns"]]:
            problems.append(f"{inp['file']}: the manifest's columns differ from project.json's")
    return out, problems


def _extract(z: zipfile.ZipFile, listed: dict, p: dict, staging: Path) -> list[str]:
    """Every file the manifest lists is checked against its sha256 as it is read; the inputs' CSVs go to data/."""
    total = sum(f["member"].file_size for f in listed.values())
    if total > MAX_BYTES:
        raise HandoffError(f"the hand-off unpacks to {total / 1024 ** 3:.1f} GB, more than this D2D Relay takes "
                           f"({LIMIT_GB:g} GB)")
    wanted = {inp["file"]: staging / "data" / f"{inp['table']}.csv" for inp in p["inputs"]}
    (staging / "data").mkdir(parents=True, exist_ok=True)
    problems, used = [], 0
    for path, f in listed.items():
        digest, target = hashlib.sha256(), wanted.get(path)
        try:
            with z.open(f["member"]) as src, (open(target, "wb") if target else contextlib.nullcontext()) as dst:
                while chunk := src.read(CHUNK):
                    used += len(chunk)
                    if used > MAX_BYTES:
                        raise HandoffError(f"the hand-off unpacks to more than this D2D Relay takes ({LIMIT_GB:g} GB)")
                    digest.update(chunk)
                    if dst is not None:
                        dst.write(chunk)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as e:
            problems.append(f"{path} cannot be read from the zip ({e.__class__.__name__})")
            continue
        if digest.hexdigest() != f["sha256"]:
            problems.append(f"{path} does not match the manifest (sha256): the folder changed after DAWB wrote "
                            "manifest.json, or the zip is incomplete")
    return problems


def _check_csvs(staging: Path, p: dict) -> tuple[list[dict], list[str]]:
    """Each CSV's header is its columns in order, and it holds the rows project.json says."""
    csv.field_size_limit(max(csv.field_size_limit(), 64 * 1024 * 1024))
    files, problems = [], []
    for inp in p["inputs"]:
        path = staging / "data" / f"{inp['table']}.csv"
        want = [c["name"] for c in inp["columns"]]
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                rows = sum(1 for r in reader if r)
        except (UnicodeDecodeError, csv.Error) as e:
            problems.append(f"{inp['file']} cannot be read as a UTF-8 CSV ({str(e).splitlines()[0][:120]})")
            continue
        if header != want:
            problems.append(f"{inp['file']}: its columns are {', '.join(header or [])[:240]}, but project.json lists "
                            f"{', '.join(want)[:240]}")
        if rows != inp["rows"]:
            problems.append(f"{inp['file']} holds {rows:,} rows, but project.json says {inp['rows']:,}")
        files.append({"name": path.name, "bytes": path.stat().st_size, "rows": rows, "table": inp["table"]})
    return files, problems


def _check_keys(staging: Path, rels: list[tuple[str, str, str, str]]) -> tuple[list[dict], list[str]]:
    """In the data: the one side of each relationship has a value in every row, each value once; and how many of the
    many side's values it has (the rest show as (Blank) in Power BI)."""
    if not rels:
        return [], []
    con = duckdb.connect()
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    cache = staging / ".genbi" / "cache"
    info, problems = [], []
    try:
        for a, ac, b, bc in rels:
            text = f"{a}[{ac}] -> {b}[{bc}]"
            try:
                one, many = _source(con, staging / "data" / f"{b}.csv", cache), _source(con, staging / "data" / f"{a}.csv", cache)
                n, distinct, filled = con.execute(f"SELECT COUNT(*), COUNT(DISTINCT {_q(bc)}), COUNT({_q(bc)}) FROM {one}").fetchone()
                share = con.execute(
                    f"SELECT AVG(CASE WHEN o.k IS NULL THEN 0 ELSE 1 END) FROM (SELECT DISTINCT {_q(ac)} AS v FROM {many} "
                    f"WHERE {_q(ac)} IS NOT NULL) m LEFT JOIN (SELECT DISTINCT {_q(bc)} AS k FROM {one}) o "
                    f"ON CAST(m.v AS VARCHAR) = CAST(o.k AS VARCHAR)").fetchone()[0]
            except duckdb.Error as e:
                problems.append(f"the relationship {text} could not be checked ({str(e).splitlines()[0][:120]})")
                continue
            if filled < n:
                problems.append(f"{b}[{bc}] is blank in {n - filled:,} rows; the one side of a relationship ({text}) "
                                "needs a value in every row")
            elif distinct < n:
                problems.append(f"{b}[{bc}] repeats values ({n:,} rows, {distinct:,} values); the one side of a "
                                f"relationship ({text}) needs each value once")
            info.append({"relationship": text, "matched": 1.0 if share is None else round(float(share), 3)})
    finally:
        con.close()
    return info, problems


# ---------------------------------------------------------------- DAWB's plan as D2D's plan.yaml

_DAX_TOKEN = re.compile(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'|//[^\n]*|--[^\n]*|/\*.*?\*/|\[[^\]]*\]', re.S)


def rename_measure(dax: str, old: str, new: str) -> str:
    """The DAX with every reference to the measure [old] made [new] (DAX names ignore case). A bracket right after a
    table name (Table[old], 'My table'[old]) is a column and stays, as do strings and comments."""
    out, last = [], 0
    for m in _DAX_TOKEN.finditer(dax):
        tok = m.group(0)
        if tok.startswith("[") and tok[1:-1].strip().lower() == old.lower():
            prev = dax[m.start() - 1] if m.start() else ""
            if not (prev.isalnum() or prev in "_'"):
                out.append(dax[last:m.start()] + "[" + new + "]")
                last = m.end()
    out.append(dax[last:])
    return "".join(out)


def _free_name(old: str, taken: set[str]) -> str:
    first = old[0].lower() + old[1:] if old[:1].isupper() and not old[1:2].isupper() else old
    for name in (f"Total {first}", f"{old} total", f"{old} (KPI)", *(f"{old} {n}" for n in range(2, 99))):
        if name.lower() not in taken:
            return name
    return f"{old} {time.time_ns()}"


def rename_clashes(kpis: list[dict], columns: set[str]) -> list[list[str]]:
    """Power BI refuses a measure with the name of a column (D2D's build too): such a KPI gets a free name ("Total
    transactions" for "Transactions"), keeps its old name as the card's label, and the KPIs that use it follow.
    Returns [old, new] pairs."""
    taken = {k["name"].lower() for k in kpis} | columns
    renamed = []
    for k in kpis:
        if k["name"].lower() in columns:
            new = _free_name(k["name"], taken)
            taken.add(new.lower())
            renamed.append([k["name"], new])
            k["name"] = new
    for old, new in renamed:
        for k in kpis:
            k["dax"] = rename_measure(k["dax"], old, new)
    return renamed


def _visual_line(v) -> str:
    if isinstance(v, str):
        return _text(v, 300)
    title, kind = _text(v.get("title"), 200), _text(v.get("visual"), 60)
    return f"{title} ({kind})" if title and kind else title or kind or "visual"


def to_plan(p: dict, rels: list[tuple[str, str, str, str]]) -> tuple[dict, list[list[str]]]:
    """plan.yaml as Relay's planning writes it (summary, model, kpis, pages), from DAWB's plan."""
    inputs = {i["table"]: i for i in p["inputs"]}
    plan = p["plan"]
    model = plan.get("model") or {}
    ones = {r[2] for r in rels}
    tables = []
    for x in model.get("tables") or list(inputs):
        spec = x if isinstance(x, dict) else {"name": x}
        name = spec["name"]
        t = {"name": name, "csv": f"{name}.csv", "role": spec.get("role") or ("dimension" if name in ones else "fact")}
        if _text(spec.get("grain")):
            t["grain"] = _text(spec["grain"], 200)
        if _text(inputs[name].get("description")):
            t["description"] = _text(inputs[name]["description"], 500)
        tables.append(t)
    kpis = []
    for k in plan["kpis"]:
        fs = k.get("format_string")
        kpis.append({"name": k["name"], "label": k["name"], "description": _text(k.get("description"), 1000),
                     "dax": k["dax"].strip(), "format": fs.strip() if isinstance(fs, str) and fs.strip() else FORMATS[k["format"]]})
    renamed = rename_clashes(kpis, {c["name"].lower() for i in p["inputs"] for c in i["columns"]})
    pages = [{"name": pg["name"].strip(), "purpose": _text(pg.get("purpose"), 500),
              "visuals": [_visual_line(v) for v in pg.get("visuals") or []]} for pg in plan["pages"]]
    summary = _text(p.get("description"), 3000) or _text(p.get("name"))
    if _text(p.get("audience")):
        summary += f" For: {_text(p['audience'], 500)}."
    out = {"summary": summary,
           "model": {"tables": tables, "relationships": [f"{a}[{ac}] -> {b}[{bc}]" for a, ac, b, bc in rels]},
           "kpis": kpis, "pages": pages}
    if _text(model.get("note")):
        out["model"]["note"] = _text(model["note"], 1000)
    return out, renamed


# ---------------------------------------------------------------- the whole check

def stage(zip_path: Path, staging: Path) -> dict:
    """Check the hand-off in the uploaded zip and unpack it into `staging` (a new folder beside the dashboards, which
    becomes the dashboard's): data/<table>.csv, profile.md and profile.json, handoff/project.json and manifest.json as
    DAWB wrote them. HandoffError says what is wrong; the caller removes `staging` then. Returns what the dashboard is
    made from: project, manifest, plan (for plan.yaml), files, rows, keys, renamed."""
    staging.mkdir(parents=True)
    try:
        z = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        raise HandoffError("the file is not a .zip that can be read") from e
    with z:
        members = _members(z)
        root = _root(members)
        p, p_raw = _read_json(z, members[root + "project.json"], "project.json")
        if root + "manifest.json" not in members:
            raise HandoffError("there is no manifest.json beside project.json (DAWB writes it last: zip the folder once "
                               "DAWB has finished)")
        m, m_raw = _read_json(z, members[root + "manifest.json"], "manifest.json")
        problems = _check_project(p)
        if problems:
            raise HandoffError(problems)
        rels, problems = _relationships(p)
        if problems:
            raise HandoffError(problems)
        listed, problems = _check_manifest(m, members, root, p)
        if problems:
            raise HandoffError(problems)
        problems = _extract(z, listed, p, staging)
        if problems:
            raise HandoffError(problems)
    files, problems = _check_csvs(staging, p)
    if problems:
        raise HandoffError(problems)
    profile(staging)                            # profile.md / profile.json, as `genbi profile` makes them for Relay's plan
    unreadable = json.loads((staging / "profile.json").read_text(encoding="utf-8")).get("unreadable") or []
    if unreadable:
        raise HandoffError([f"D2D cannot read {u}" for u in unreadable])
    keys, problems = _check_keys(staging, rels)
    if problems:
        raise HandoffError(problems)
    plan, renamed = to_plan(p, rels)
    problems = checks.plan(plan)
    if problems:
        raise HandoffError([f"the plan does not pass D2D's plan check ({x})" for x in problems])
    (staging / "handoff").mkdir()
    (staging / "handoff" / "project.json").write_bytes(p_raw)
    (staging / "handoff" / "manifest.json").write_bytes(m_raw)
    made = p.get("made_by") if isinstance(p.get("made_by"), dict) else {}
    return {"project": p, "manifest": m, "plan": plan, "name": _text(p.get("name"), 120), "files": files, "rows": sum(f["rows"] for f in files),
            "keys": keys, "renamed": renamed, "product": _text(made.get("product"), 40) or "DAWB",
            "release": _text(m.get("release") or made.get("release"), 40), "run": _text(m.get("run"), 80),
            "made": _text(made.get("at"), 40)}


# ---------------------------------------------------------------- what people and the build read

def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def origin(h: dict) -> str:
    """"release R-1, 2026-11-18 04:39 UTC" (what the hand-off says of itself)."""
    return ", ".join(x for x in (f"release {h['release']}" if h["release"] else "", h["made"]) if x) or f"run {h['run']}"


def prompt_text(h: dict, added: str) -> str:
    """The dashboard's request (project.json prompt, "Your request"): what the hand-off says it should answer, for
    whom, and what the person importing it added."""
    p = h["project"]
    text = _text(p.get("description"), 3000) or _text(p.get("name"))
    if _text(p.get("audience")):
        text += f" For: {_text(p['audience'], 500)}."
    return text + (f"\n\n{added}" if added else "")


def summary(h: dict) -> str:
    """The plan's notes on Confirm KPIs (project.json plan_summary): where it came from, then any renamed KPI and how
    the tables are related."""
    plan = h["plan"]
    first = (f"{h['product']}'s plan from its hand-off ({origin(h)}): {len(plan['kpis'])} KPIs on {len(plan['pages'])} "
             f"pages, over {len(h['files'])} tables with {h['rows']:,} rows. Every file matches the hand-off's manifest. "
             "Check the KPIs and their formulas, then confirm: Relay builds the prototype next, with these pages as its guide.")
    if h["renamed"]:                            # in the first paragraph: the screen folds the others away
        n = len(h["renamed"])
        first += (f" D2D renamed {n} KPI{'s' if n > 1 else ''}, as Power BI does not allow a KPI with the name of a column: "
                  + "; ".join(f"{a} is now {b}" for a, b in h["renamed"])
                  + (". Its card still reads the old name" if n == 1 else ". The cards still read the old names")
                  + ", and the KPIs that use it are changed to match.")
    parts = [first]
    if h["keys"]:
        low = [k for k in h["keys"] if k["matched"] < 1]
        parts.append(f"{len(h['keys'])} relationships join the tables, so one slicer filters every table it reaches."
                     + ("" if not low else " Some values have no match on the one side, and show as (Blank) in Power BI: "
                        + "; ".join(f"{k['relationship']} {k['matched']:.0%} matched" for k in low) + "."))
    else:
        parts.append("The hand-off has no relationships: each table is sliced by its own columns.")
    return "\n\n".join(parts)


def request_lines(h: dict, title: str, added: str) -> list[str]:
    """request.md up to the visual style: what the dashboard should answer, where it came from, how the build uses
    DAWB's plan, the data with DAWB's descriptions, the relationships and DAWB's proposed visuals."""
    p, plan = h["project"], h["plan"]
    lines = [f"# {title}", "", "## What the user asked for", "", _text(p.get("description"), 3000) or _text(p.get("name")), ""]
    if _text(p.get("audience")):
        lines += [f"For: {_text(p['audience'], 500)}", ""]
    if added:
        lines += ["The person who imported it added:", "", added, ""]
    lines += [f"## From a {h['product']} hand-off", "",
              f"This dashboard started from a hand-off of {h['product']}, the lakehouse builder ({origin(h)}; run {h['run']}). "
              "D2D checked every file against its manifest (sha256, rows, columns) and wrote its plan to plan.yaml; the "
              "user confirms or edits it at Confirm KPIs. As it was written: handoff/project.json and handoff/manifest.json.",
              "",
              "- The KPIs are proven against these tables: keep each KPI's DAX logic and the table and column names it uses "
              "(name each model table after its CSV and keep its column names), so the numbers match the lakehouse's.",
              "- The pages and visuals under \"Planned visuals\" are a proposal: use them as guidance (what each visual answers, "
              "about where it sits on a 24-column grid), not as a fixed layout. Their queries are DuckDB SQL on the gold "
              "tables: gold.<table> is the raw view <table> here (`genbi sql`).",
              "- Put the table and column descriptions below in definition.yaml (`description:` on tables and columns).", ""]
    for key, label in (("refresh", "Refresh"), ("privacy", "Privacy"), ("quality", "Quality")):
        if _text(p.get(key)):
            lines.append(f"- {label}: {_text(p[key], 1000)}")
    lineage = [x for x in p.get("lineage") or [] if isinstance(x, dict) and _text(x.get("system"))]
    if lineage:
        lines.append("- Lineage: " + "; ".join(
            f"{_text(x['system'], 120)}" + (f" ({_text(x.get('kind'), 40)})" if _text(x.get("kind")) else "")
            + (": " + ", ".join(_text(t, 80) for t in x.get("lands") or [] if _text(t)) if x.get("lands") else "")
            for x in lineage))
    inputs = {i["table"]: i for i in p["inputs"]}
    lines += ["", "## Data (in data/)", ""]
    for f in h["files"]:
        inp = inputs[f["table"]]
        lines.append(f"- {f['name']} ({_size(f['bytes'])}, {f['rows']:,} rows)"
                     + (f": {_text(inp['description'], 500)}" if _text(inp.get("description")) else ""))
        for col in inp["columns"]:
            lines.append(f"  - {col['name']} ({col['type']} -> {TYPES[col['type']]})"
                         + (f": {_text(col['description'], 500)}" if _text(col.get("description")) else ""))
    if plan["model"]["relationships"]:
        matched = {k["relationship"]: k["matched"] for k in h["keys"]}
        lines += ["", "## Relationships (many -> one)", ""] + [
            f"- {r}" + (f" ({matched[r]:.0%} of the many side's values are on the one side)" if matched.get(r, 1) < 1 else "")
            for r in plan["model"]["relationships"]]
    if plan["model"].get("note"):
        lines += ["", "## Model note", "", plan["model"]["note"]]
    if h["renamed"]:
        lines += ["", "## KPIs renamed on import", "",
                  "Power BI does not allow a measure with the name of a column, so D2D renamed these KPIs (their label keeps "
                  "the old name) and changed the DAX of the KPIs that use them:", ""] + [
            f"- {a} -> {b}" for a, b in h["renamed"]]
    lines += ["", "## Planned visuals (a proposal, guidance for the build)", ""]
    for pg in p["plan"]["pages"]:
        lines += [f"### {pg['name'].strip()}", ""] + ([_text(pg.get("purpose"), 500), ""] if _text(pg.get("purpose")) else [])
        for v in pg.get("visuals") or []:
            if isinstance(v, str):
                lines.append(f"- {_text(v, 300)}")
                continue
            box = [v.get(k) for k in ("x", "y", "w", "h")]
            where = f"; x {box[0]}, y {box[1]}, w {box[2]}, h {box[3]}" if all(isinstance(b, int) for b in box) else ""
            query = " ".join(str(v.get("query") or "").split())
            lines.append(f"- {_visual_line(v)}{where}" + (f": `{query[:2000]}`" if query else ""))
        lines.append("")
    return lines
