"""Project folders on the volume shared with the agent: /data/projects/<id>/

project.json     state (status, versions, output ...) - only the web app writes it
activity.jsonl   everything that happened, one event per line: agent events + app notes
request.md       the user's request and every later decision (the agent reads it)
data/ images/    uploads; CLAUDE.md, reference/ the agent's guide and example
plan.yaml, definition.yaml, prototype/, versions/vN/, powerbi/   written during the run

P17: each tenant has its own tree - the platform's is the volume itself (nothing moved), any other tenant's is
/data/projects/.tenants/<tenant>/. ROOT follows the current tenant (db.tenant()) every time it is used.
"""
import json
import os
import re
import secrets
import time
from pathlib import Path

from . import db

BASE = Path(os.environ.get("WORKSPACES", "/data/projects"))       # the shared volume (the platform tenant's tree)
BASE.mkdir(parents=True, exist_ok=True)
TENANTS_DIR = ".tenants"
ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_seq: dict[str, int] = {}
_made: set[str] = set()


def root() -> Path:
    """The project folders of the current tenant (db.tenant()): the shared volume for the platform, its own folder
    under .tenants/ for any other tenant. Call it (or use ROOT) when the path is needed - never keep a tenant's
    folder in a module-level variable."""
    t = db.tenant()
    if t == db.PLATFORM:
        return BASE
    d = BASE / TENANTS_DIR / t
    if t not in _made:
        d.mkdir(parents=True, exist_ok=True)
        _made.add(t)
    return d


def tenant_root(tid: str) -> Path:
    """One tenant's tree, whichever tenant is current (exports, backups, the platform console)."""
    with db.use(tid):
        return root()


def rel(pid: str) -> str:
    """A project folder relative to the volume shared with the agent: what POST /runs and /display-check take as
    `workdir` (`.tenants/<tenant>/<id>` outside the platform). Never send a bare project id to the agent."""
    r = root()
    return pid if r == BASE else f"{r.relative_to(BASE).as_posix()}/{pid}"


class TenantPath(os.PathLike):
    """A folder that follows the current tenant, resolved at each use (`X / name`, `X.glob(...)`, `X.mkdir()`,
    `Path(X)`, `os.fspath(X)` ...): store.ROOT and the other per-tenant folders, so modules written for the one
    shared folder work inside their tenant without a change."""

    def __init__(self, resolve):
        self._resolve = resolve

    def __fspath__(self) -> str:
        return str(self._resolve())

    def __truediv__(self, other) -> Path:
        return self._resolve() / other

    def __getattr__(self, name):
        return getattr(self._resolve(), name)

    def __str__(self) -> str:
        return str(self._resolve())

    def __repr__(self) -> str:
        return f"<tenant folder {self._resolve()}>"

    def __eq__(self, other) -> bool:
        return self._resolve() == (Path(other) if isinstance(other, (str, os.PathLike)) else other)

    def __hash__(self) -> int:
        return hash(self._resolve())


ROOT = TenantPath(root)


def _library(base: Path) -> Path:
    """The current tenant's visual library: the shared folder for the platform, base/.tenants/<t> for the others."""
    t = db.tenant()
    return base if t == db.PLATFORM else base / TENANTS_DIR / t


try:
    import genbi_kit
    genbi_kit.set_library_resolver(_library)
except ImportError:                     # tests that load the app without the toolkit on the path
    pass


def state_dir(name: str) -> TenantPath:
    """A per-tenant folder in the state volume: db.STATE/<name> for the platform, db.STATE/tenants/<t>/<name> else."""
    def resolve() -> Path:
        t = db.tenant()
        return db.STATE / name if t == db.PLATFORM else db.STATE / "tenants" / t / name
    return TenantPath(resolve)


def new_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "dashboard"
    return f"{slug}-{secrets.token_hex(2)}"


def project_dir(pid: str) -> Path:
    d = ROOT / pid
    if not ID.match(pid) or not (d / "project.json").exists():
        raise KeyError(pid)
    return d


def read_json(path: Path, tries: int = 6):
    """A project.json read that survives a save racing it: on a Windows bind mount the swap of the new file can make a
    read fail for a moment (OSError Errno 61, or a half-read file) - try again, briefly, before giving up."""
    for i in range(tries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            if i == tries - 1 or not path.exists():
                raise
            time.sleep(0.02 * 2 ** i)


def load(pid: str) -> dict:
    return read_json(project_dir(pid) / "project.json")


def save(st: dict) -> dict:
    st["updated"] = time.time()
    path = ROOT / st["id"] / "project.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(path)
    return st


def update(pid: str, **changes) -> dict:
    st = load(pid)
    st.update(changes)
    return save(st)


def all_projects() -> list[dict]:
    """Every project folder - dashboards and the module subjects (starts, studio items, RFPs, heal cases, change
    requests, migrations and their converted reports ...) - newest first, each with its `kind`. Callers that mean
    dashboards only use dashboards(). (The worker's restart recovery, owners, usage and Team & agents need them all.)"""
    out = []
    for f in ROOT.glob("*/project.json"):
        try:
            st = read_json(f, tries=3)
        except (OSError, json.JSONDecodeError):
            continue
        versions = st.get("versions") or []
        latest = versions[-1] if versions else {}
        out.append({**{k: st.get(k) for k in ("id", "name", "status", "created", "updated", "approved", "model")},
                    "kind": st.get("kind") or "dashboard",           # P10+: starts and other phase subjects share the folder
                    "prompt": (st.get("prompt") or "")[:240], "versions": len(versions),
                    "pages": len(latest.get("pages") or []), "visuals": latest.get("visuals"),
                    "published": bool(st.get("output")),
                    "published_v": ((st.get("publishes") or [{}])[-1].get("v") or st.get("approved")) if st.get("output") else None,
                    "gates": {s: sum(g.get("status") == s for g in latest.get("gates") or []) for s in ("pass", "warn", "fail")}
                    if latest.get("gates") else None,
                    "cost_usd": round(sum(r.get("cost_usd") or 0 for r in st.get("runs") or []), 2)})
    return sorted(out, key=lambda s: s["created"] or 0, reverse=True)


def dashboards() -> list[dict]:
    """The dashboards only (module folders have their own screens)."""
    return [p for p in all_projects() if (p.get("kind") or "dashboard") == "dashboard"]


AGENT_KINDS = {"start", "say", "tool", "result", "done", "error"}
INSTANCE = os.environ.get("D2D_INSTANCE", "local")


def _who(event: dict) -> str:
    """Who an event belongs to: the signed-in person for their own actions, else the agent or the app."""
    if event.get("kind") == "user":
        from . import auth                      # late import: auth -> db, no cycle with store
        return auth.who() or "unknown"
    return "agent" if event.get("kind") in AGENT_KINDS else "app"


def log(pid: str, event: dict) -> None:
    """Append one activity event (numbered, timestamped, with who did it and on which instance)."""
    path = ROOT / pid / "activity.jsonl"
    key = str(path)                         # per folder: project ids may repeat across tenants
    if key not in _seq:
        _seq[key] = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    _seq[key] += 1
    event = {"who": _who(event), "instance": INSTANCE, **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"seq": _seq[key], "ts": time.time(), **event}) + "\n")


_OLD_WORDS = ((re.compile(r"\bPower BI project \(PBIP\)", re.I), "Power BI file (.pbix)"),
              (re.compile(r"\bPower BI project\b", re.I), "Power BI file"),
              (re.compile(r"\.pbip\b", re.I), ".pbix"),
              (re.compile(r"\bPBIP\b", re.I), "Power BI file"),
              (re.compile(r" See Review gates\.txt\."), ""))          # a file the old download had


# D2D Relay (the user, 2026-11-12: "humanize it ... ensure all characters look human"): what the AI and the app write is
# shown with keyboard characters only (genbi_kit.plaintext has the map). What people typed stays as they typed it.
from genbi_kit.plaintext import human  # noqa: E402


def _today_words(text):
    """D2D Relay: people get a Power BI file (.pbix). Notes written before it (and any stray sentence of the agent's)
    said PBIP or Power BI project: shown with today's words."""
    if not isinstance(text, str) or ("pbip" not in text.lower() and "power bi project" not in text.lower()):
        return text
    for rx, new in _OLD_WORDS:
        text = rx.sub(new, text)
    return text


def plain(text):
    """A note of the app's or the agent's as people see it: today's words, plain keyboard characters."""
    return human(_today_words(text))


def activity(pid: str, after: int = 0, limit: int = 400) -> list[dict]:
    path = project_dir(pid) / "activity.jsonl"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i > after:
                e = json.loads(line)
                fix = _today_words if e.get("kind") == "user" else plain     # people's own words keep their characters
                if "text" in e:
                    e["text"] = fix(e["text"])
                if isinstance(e.get("detail"), list):
                    e["detail"] = [fix(x) for x in e["detail"]]
                if isinstance(e.get("items"), list):
                    e["items"] = [fix(x) for x in e["items"]]
                out.append(e)
                if len(out) >= limit:
                    break
    return out


def note(pid: str, heading: str, body: str) -> None:
    """Add a dated section to request.md - the agent's record of what the user decided."""
    with (ROOT / pid / "request.md").open("a", encoding="utf-8") as f:
        f.write(f"\n\n## {heading} ({time.strftime('%Y-%m-%d %H:%M')})\n\n{body.strip()}\n")
