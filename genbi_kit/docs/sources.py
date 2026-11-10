"""Source references: where a figure, table, chart or quote comes from, and whether it resolves.

  dashboard:<project id>[/<measure>]   sources/dashboard-<id>.json (the web app's snapshot of a dashboard: its
                                       measures with the values Power BI's engine returned, pages, KPIs)
  record:<name>[#<key.path>]           sources/<name>.json | .yaml | .md | .csv — an Assess / Programme / RFP /
                                       Start / practice record the web app copied in; #key reads into a JSON record
  attachment:<file>[#<sheet or page>]  sources/<file> or attachments/<file> (read with `genbi read`)
  library:<id>                         an item of the tenant's past-responses library, listed in sources/library.json
  module:<id>                          a module of the registry, listed in sources/registry.json
  <path>                               any file inside the project folder

A reference that points outside the project folder (…/ or an absolute path elsewhere) crosses the tenant boundary
and is refused; nothing is read from another folder."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import yaml

SCHEMES = ("dashboard", "record", "attachment", "library", "module", "file")
REF_RE = re.compile(r"^(?P<scheme>[a-z]+):(?P<rest>[^#]*)(?:#(?P<frag>.*))?$")


def split(ref: str) -> tuple[str, str, str]:
    """(scheme, rest, fragment); a bare path is scheme 'file'."""
    m = REF_RE.match(ref.strip())
    if not m or m.group("scheme") not in SCHEMES:
        rest, _, frag = ref.strip().partition("#")
        return "file", rest, frag
    return m.group("scheme"), m.group("rest").strip(), (m.group("frag") or "").strip()


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = re.sub(r"[₹$€£,\s%]", "", v)
        try:
            return float(s)
        except ValueError:
            return None
    return None


def dig(obj, path: str):
    """record#a.b.0.c -> the value at that path (None when absent)."""
    cur = obj
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:                                           # case-insensitive key match helps 'Reports' vs 'reports'
                k = next((k for k in cur if str(k).lower() == part.lower()), None)
                if k is None:
                    return None
                cur = cur[k]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


class Resolver:
    """Resolves references against one project folder; `workspace` is the tenant's projects root (a path outside it
    is refused), by default the project's parent."""

    def __init__(self, root: Path | str, workspace: Path | str | None = None):
        self.root = Path(root).resolve()
        self.workspace = Path(workspace).resolve() if workspace else self.root.parent
        self._cache: dict[str, dict | None] = {}

    # ---- the tenant boundary
    def inside(self, path: Path | str) -> bool:
        try:
            p = (self.root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        except OSError:
            return False
        return p == self.root or self.root in p.parents

    def _file(self, rel: str) -> Path | None:
        if not rel or not self.inside(rel):
            return None
        p = (self.root / rel) if not Path(rel).is_absolute() else Path(rel)
        return p if p.is_file() else None

    def _json(self, rel: str) -> dict | None:
        if rel in self._cache:
            return self._cache[rel]
        p = self._file(rel)
        data = None
        if p:
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else yaml.safe_load(p.read_text(encoding="utf-8"))
            except (ValueError, yaml.YAMLError, OSError):
                data = None
        self._cache[rel] = data if isinstance(data, (dict, list)) else None
        return self._cache[rel]

    # ---- resolution
    def resolve(self, ref: str) -> dict:
        """{"ok", "kind", "path", "value", "why", "link"} — value is the scalar the reference names, when it names one."""
        ref = (ref or "").strip()
        if not ref:
            return {"ok": False, "kind": "", "path": "", "value": None, "why": "no source given"}
        scheme, rest, frag = split(ref)
        if ".." in Path(rest).parts or (rest.startswith("/") and scheme == "file"):
            return {"ok": False, "kind": scheme, "path": rest, "value": None, "why": "points outside the project folder (tenant boundary)"}
        if scheme == "dashboard":
            pid, _, measure = rest.partition("/")
            data = self._json(f"sources/dashboard-{pid}.json")
            if not data:
                return {"ok": False, "kind": scheme, "path": f"sources/dashboard-{pid}.json", "value": None, "why": f"dashboard {pid} is not among the sources"}
            if measure:
                m = next((x for x in data.get("measures") or [] if str(x.get("name", "")).lower() == measure.lower() or str(x.get("label", "")).lower() == measure.lower()), None)
                if not m:
                    return {"ok": False, "kind": scheme, "path": f"sources/dashboard-{pid}.json", "value": None, "why": f"dashboard {pid} has no measure {measure!r}"}
                return {"ok": True, "kind": scheme, "path": f"sources/dashboard-{pid}.json", "value": _num(m.get("value")), "why": "", "name": m.get("label") or m.get("name")}
            return {"ok": True, "kind": scheme, "path": f"sources/dashboard-{pid}.json", "value": None, "why": "", "name": data.get("name")}
        if scheme == "record":
            base = rest if rest.startswith(("sources/", "attachments/")) else f"sources/{rest}"
            found = next((self._file(base + ext) for ext in ("", ".json", ".yaml", ".yml", ".md", ".csv", ".txt") if self._file(base + ext)), None)
            if not found:
                return {"ok": False, "kind": scheme, "path": base, "value": None, "why": f"record {rest!r} is not among the sources"}
            rel = found.relative_to(self.root).as_posix()
            value = None
            if frag:
                data = self._json(rel) if found.suffix in (".json", ".yaml", ".yml") else None
                if data is None:
                    return {"ok": False, "kind": scheme, "path": rel, "value": None, "why": f"{rel} is not a JSON / YAML record, so #{frag} cannot be read"}
                v = dig(data, frag)
                if v is None:
                    return {"ok": False, "kind": scheme, "path": rel, "value": None, "why": f"{rel} has no {frag!r}"}
                value = _num(v) if not isinstance(v, (dict, list)) else None
            return {"ok": True, "kind": scheme, "path": rel, "value": value, "why": ""}
        if scheme == "attachment":
            found = self._file(f"sources/{rest}") or self._file(f"attachments/{rest}") or self._file(rest)
            if not found:
                return {"ok": False, "kind": scheme, "path": rest, "value": None, "why": f"attachment {rest!r} is not in sources/ or attachments/"}
            rel = found.relative_to(self.root).as_posix()
            value = None
            if frag and found.suffix.lower() == ".csv":
                value = self._csv_cell(found, frag)
            return {"ok": True, "kind": scheme, "path": rel, "value": value, "why": ""}
        if scheme == "library":
            data = self._json("sources/library.json")
            items = (data.get("items") if isinstance(data, dict) else data) or []
            item = next((x for x in items if isinstance(x, dict) and str(x.get("id")) == rest), None)
            if not item:
                return {"ok": False, "kind": scheme, "path": "sources/library.json", "value": None, "why": f"library item {rest!r} is not among the items picked for this work"}
            return {"ok": True, "kind": scheme, "path": "sources/library.json", "value": None, "why": "", "name": item.get("title")}
        if scheme == "module":
            data = self._json("sources/registry.json")
            mods = (data.get("modules") if isinstance(data, dict) else None) or {}
            if isinstance(mods, list):
                mods = {m.get("id"): m for m in mods if isinstance(m, dict)}
            if rest not in mods:
                return {"ok": False, "kind": scheme, "path": "sources/registry.json", "value": None, "why": f"module {rest!r} is not in the registry facts"}
            return {"ok": True, "kind": scheme, "path": "sources/registry.json", "value": None, "why": "", "name": mods[rest].get("name")}
        found = self._file(rest)
        if not found:
            why = "points outside the project folder (tenant boundary)" if rest and not self.inside(rest) else f"{rest!r} is not a file in the project"
            return {"ok": False, "kind": "file", "path": rest, "value": None, "why": why}
        return {"ok": True, "kind": "file", "path": found.relative_to(self.root).as_posix(), "value": None, "why": ""}

    def _csv_cell(self, path: Path, frag: str):
        """attachment:x.csv#<column>=<key>:<value column>  or  #<column>:sum — a value read from a CSV."""
        try:
            with path.open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except (OSError, csv.Error):
            return None
        m = re.match(r"^(?P<col>[^=:]+)=(?P<key>[^:]+):(?P<val>.+)$", frag)
        if m:
            row = next((r for r in rows if str(r.get(m.group("col"), "")).strip() == m.group("key").strip()), None)
            return _num(row.get(m.group("val"))) if row else None
        m = re.match(r"^(?P<col>[^:]+):(?P<agg>sum|count|max|min)$", frag)
        if m:
            vals = [_num(r.get(m.group("col"))) for r in rows]
            vals = [v for v in vals if v is not None]
            if m.group("agg") == "count":
                return float(len(rows))
            return {"sum": sum, "max": max, "min": min}[m.group("agg")](vals) if vals else None
        return None

    def link(self, ref: str, base: str = "") -> str:
        """Where the evidence opens in the app (the web app passes its base, e.g. '#/studio/<id>/sources?ref=')."""
        return f"{base}{ref}" if base else ref
