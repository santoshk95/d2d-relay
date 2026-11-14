"""The module workbench: one engine that makes the catalogue's modules real (docs/workbench.md is the guide).

A **work item** is one piece of work of one module and one work type - Assess, Develop, Fix / change, Migrate, Run &
support, or an engagement for the consulting modules. It is a subject folder under store.root() with kind `work`
(project.json through store; activity.jsonl; request.md; data/ for uploads; evidence/; outputs/), a row in `wb_items`
(the index: module, work type, status, current step, schedule) and a row in `projects` (owner, team, visibility: the
same permission model as dashboards - Viewers never change anything, private items are their owner's).

Its journey comes from the module registry (registry.plan_for: the names and texts of the steps; registry.confirm_for:
where a person confirms) unless the module's pack overrides it. Every step has a handler kind:

  deterministic  rules first: a Python function over the item's data (a worker job, no AI)
  agent          a worker job with the pack's prompt in the sequential lane (worker.agent), checked by the pack and
                 fixed in rounds, like every other agent stage
  person         a checkpoint (checkpoints.open) with the view that fits; the person confirms or corrects in place
  platform       an adapter call through a connection: test, read / scan inventory, read run logs; a write only through
                 connectors.request_write (its own per-change approval)
  proof          pluggable checks - counts, checksums, business totals, sample diffs, tests run, references real -
                 whose results are stored as evidence
A step whose journey name is one of the registry's confirm points pauses for a person after it runs (kind
`wb.<module>` in the Validation queue); accept moves on, send back runs the step again with the comment.

Evidence is attached to the step that produced it (evidence/<step>/<id>.json) and listed one click away; outputs are
files in outputs/; at hand-over the evidence pack (evidence, outputs, decisions, activity, a summary and a hand-over
document built by the P11 docs engine) downloads as one zip. Run & support hooks: a schedule re-runs the journey
(one pass per tenant that has the module switched on: db.each_tenant(module)), a break can raise a ticket or go to
Self-healing after a person approves.

Packs live in app/packs/<module>.py and call `register(Pack(...))`; their APIs sit under /api/m/<module>/... and the
module's registry line names that prefix (`api=["/api/m/<id>"]`): P17 answers 403 under it where the module is switched
off, and the engine itself holds the work there (no step starts, no round runs, Home leaves it out, the packs list
marks it off).
The module page #/m/<id>/<work> is live as soon as a pack exists (33-workbench.js).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import re
import secrets as _secrets
import shutil
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from . import auth, checkpoints, connectors, db, lineage, notify, registry, store, worker
from . import observe_checks as oc
from . import workbench_prompts as wp

router = APIRouter()
KIND = "work"                                   # project.json kind of a work item's folder
JOB_STEP, JOB_AGENT = "wb_step", "wb_agent"     # the two job kinds in the sequential lane
STEP_KINDS = ("deterministic", "agent", "person", "platform", "proof")
KIND_LABEL = {"deterministic": "Rules", "agent": "Agent", "person": "Person", "platform": "Platform", "proof": "Proof"}
DEFAULT_AGENT = {"deterministic": "Rule checker", "agent": "Relay agent", "person": "", "platform": "Platform reader", "proof": "Prover"}
VIEWS = checkpoints.VIEWS
WORK_NAME = dict(registry.WORK) | {"engage": "Engagement"}
STATUS_LABEL = {"new": "New", "queued": "Queued", "working": "Working", "agent_working": "Relay is working", "waiting": "Waiting for a person",
                "attention": "Needs attention", "error": "Needs attention", "done": "Done", "scheduled": "Live - scheduled", "closed": "Closed"}
STEP_LABEL = {"pending": "To do", "queued": "Queued", "running": "Working", "waiting": "Waiting for a person", "done": "Done", "sent_back": "Sent back",
              "error": "Needs attention", "skipped": "Skipped"}
OPEN = ("new", "queued", "working", "agent_working", "waiting", "attention", "error", "scheduled")
RUNNING = ("queued", "working", "agent_working")
# Where a confirm point of the registry lands when the journey has no step of that name (the generic journeys).
ALIASES = {"Design": ("Shape",), "Diagnosis": ("Diagnose",), "Release": ("Approve", "Ship"), "Findings": ("Analyse",),
           "Direction": ("Agree",), "Plan": ("Deliver",)}
UPLOAD_MAX = 200 * 1024 * 1024
DATA_EXT = (".csv", ".parquet", ".xlsx", ".json", ".yaml", ".yml", ".xml", ".txt", ".md", ".sql", ".pdf", ".docx", ".pptx", ".zip")
CADENCES = {"hour": "Every hour", "day": "Every day", "week": "Every week", "month": "Every month"}
SCHED_EVERY_S = int(os.environ.get("WB_SCHED_S", "60"))
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
ROWS_KEPT = 500                                  # rows of a view kept in project.json (the rest stay in the evidence file)
_sched_task = None
_LOCKS: dict[tuple[str, str], threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

db.register_schema("""
CREATE TABLE IF NOT EXISTS wb_items (
  id TEXT PRIMARY KEY, module TEXT NOT NULL, work TEXT NOT NULL, title TEXT NOT NULL, platform TEXT, status TEXT NOT NULL,
  step TEXT, step_index INTEGER NOT NULL DEFAULT 0, steps INTEGER NOT NULL DEFAULT 0, owner_id TEXT, approver_id TEXT, parent TEXT,
  schedule TEXT, next_run REAL, last_run REAL, rounds INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL, closed REAL);
CREATE INDEX IF NOT EXISTS wb_items_module ON wb_items (module, work, status);
CREATE INDEX IF NOT EXISTS wb_items_due ON wb_items (next_run);
""")


class StepFailed(Exception):
    """A step could not do its work for a reason a person can act on (shown as is, with Run again)."""


# ================================================================== the pack contract

@dataclass
class Column:
    """One column of the records a person edits in place (rules, mappings, decisions...)."""
    key: str
    label: str
    type: str = "text"              # text | longtext | number | select | bool
    options: tuple = ()             # select: values, or (value, label) pairs; a callable(ctx) gives them per item
    help: str = ""
    required: bool = False
    readonly: bool = False


@dataclass
class Edit:
    """The records of a step a person may change before confirming. `validate(records, ctx)` returns the problems that
    stop a save (rules first: refuse what cannot run); it may also normalise the records in place."""
    columns: list
    add: bool = True
    remove: bool = True
    validate: Callable | None = None
    label: str = "row"


@dataclass
class Action:
    """A helper a person can start on a step (an agent draft, a re-read). It updates the step and never moves the
    journey on. `run` (rules / platform) or `prompt` + `check` + `after` (agent)."""
    label: str
    kind: str = "agent"
    run: Callable | None = None
    prompt: Callable | None = None
    check: Callable | None = None
    after: Callable | None = None
    agent: str = ""
    turns: int = 30
    timeout_s: int = 1200
    help: str = ""


@dataclass
class Step:
    """One step of a journey. `run(ctx) -> dict` does the work (see Ctx and docs/workbench.md for the result keys)."""
    kind: str = "person"
    run: Callable | None = None
    view: str = "table"
    agent: str = ""                 # who does it, as Team & agents shows it ("Profiler", "Rule writer")
    confirm: Any = None             # None: the registry decides; False: never pauses; a string: pause with this text
    approver: bool = False          # the item's named approver confirms (not the owner)
    edit: Edit | None = None
    prompt: Callable | None = None  # agent steps: fn(ctx) -> the stage instructions
    check: Callable | None = None   # agent steps: fn(ctx) -> problems in what the agent wrote (fix rounds)
    after: Callable | None = None   # agent steps: fn(ctx, agent_result) -> the step result
    confirm_if: Callable | None = None   # fn(ctx, result) -> bool: pause only when it returns True
    back_to: str | None = None      # send back re-runs this step id (default: the step itself)
    actions: dict = field(default_factory=dict)
    turns: int = 40
    timeout_s: int = 1800
    text: str = ""                  # the "how it works" line (default: the registry's)
    # filled in by the engine
    id: str = ""
    name: str = ""
    confirm_label: str = ""
    confirm_text: str = ""


@dataclass
class Field:
    """A field of the New work wizard (the item's scope). Types: text, longtext, number, select, bool, person,
    cadence (a schedule), ruleset-like selects take `options` as a callable(u) returning (value, label) pairs."""
    key: str
    label: str
    type: str = "text"
    options: Any = ()
    help: str = ""
    required: bool = False
    default: Any = None


@dataclass
class Work:
    """What a pack does for one work type: step handlers by journey name, the wizard's fields, the platforms offered."""
    steps: dict
    journey: list | None = None     # replaces the registry's journey (names, in order)
    fields: list = field(default_factory=list)
    platforms: tuple = ()           # platform ids for this work type (default: all of the pack's)
    schedule_from: str | None = None   # a scheduled round re-runs the journey from this step (default: the first)
    title: str = ""                 # one line in the wizard
    needs_source: bool = True       # a connection or an upload is required to create the item
    sources: bool = True            # the wizard shows the connection picker and the upload box


class Platform:
    """How a pack reaches one platform - read-only by default; a write only through connectors.request_write.
    Subclass and override what the platform needs; the defaults work for any connection kind and for uploads."""
    id = "files"
    label = "Upload files"
    kinds: tuple = ()               # connection kinds (connectors.KINDS) this platform reads through
    uploads: tuple = ()             # file types a person may upload instead (".csv", ".parquet", ".xlsx", ".json")
    simulator = ""                  # what stands in for it in the mock lab (docs and tests name it)
    reads = ""                      # one line: what Relay reads there

    def describe(self) -> dict:
        return {"id": self.id, "label": self.label, "kinds": list(self.kinds), "uploads": list(self.uploads), "reads": self.reads,
                "kind_labels": [connectors.KINDS[k]["label"] for k in self.kinds if k in connectors.KINDS]}

    def test(self, ctx: "Ctx") -> list[dict]:
        out = []
        for c in ctx.connections():
            if c["kind"] not in self.kinds:
                continue
            try:
                r = connectors.test({**c, "_who": ctx.who or ctx.owner})
                out.append({"source": c["name"], "kind": connectors.KINDS[c["kind"]]["label"], "ok": True, "sees": r.get("sees") or "connected", "scope": connectors.SCOPES.get(r.get("scope") or "read")})
            except connectors.ConnectorError as e:
                out.append({"source": c["name"], "kind": connectors.KINDS[c["kind"]]["label"], "ok": False, "sees": str(e)[:300], "scope": ""})
        for f in ctx.files(self.uploads) if self.uploads else []:
            out.append({"source": f["name"], "kind": "Upload", "ok": True, "sees": f"{_size(f['bytes'])} uploaded", "scope": "Read-only copy"})
        return out

    def objects(self, ctx: "Ctx", search: str = "") -> list[dict]:
        out = []
        for c in ctx.connections():
            if c["kind"] not in self.kinds:
                continue
            for o in connectors.browse(c, search)[:500]:
                out.append({"object": o["object"], "type": o.get("type") or "", "ref": {"source": "connection", "connection": c["id"], "object": o["object"]}, "where": c["name"]})
        for f in ctx.files(self.uploads) if self.uploads else []:
            if f.get("table"):
                out.append({"object": f["table"], "type": "file", "ref": {"source": "file", "item": ctx.id, "file": f["table"]}, "where": "upload"})
        return out

    def read(self, ctx: "Ctx", ref: dict, limit: int = 100) -> dict:
        r = ctx.reader(ref)
        try:
            if isinstance(r, oc.SdkReader):
                d = r._read()
                return {"columns": d.get("columns") or [], "rows": (d.get("rows") or [])[:limit], "row_count": d.get("row_count")}
            rows = r.run(f"SELECT * FROM {table_sql(r)} LIMIT {int(limit)}")
            return {"columns": list(rows[0].keys()) if rows else [c["name"] for c in r.columns()], "rows": rows, "row_count": r.count()}
        finally:
            _close(r)

    def logs(self, ctx: "Ctx", since: float | None = None) -> list[dict]:  # noqa: ARG002
        """Run logs from the platform: [{"when", "what", "status", "detail"}] (none by default)."""
        return []


class WarehousePlatform(Platform):
    id = "warehouse"
    label = "A warehouse or database connection"
    kinds = ("snowflake", "bigquery", "fabric", "redshift", "athena", "oracle_db", "postgres", "sqlserver")
    simulator = "fakesnow (Snowflake) in the web app image; postgres:17.6-alpine in a throwaway container"
    reads = "tables and views through the person's own connection: one guarded, read-only SELECT at a time"


class FilesPlatform(Platform):
    id = "files"
    label = "Uploaded files"
    uploads = (".csv", ".parquet", ".xlsx")
    simulator = "export fixtures the tests write (CSV, Parquet, an Excel workbook)"
    reads = "the files you upload: a copy in this work item's folder, read with DuckDB"


@dataclass
class Pack:
    """A module pack: everything the engine needs to make one catalogue module real."""
    module: str                     # the registry id
    work: dict                      # work type -> Work
    platforms: dict                 # platform id -> Platform
    guide: str = ""                 # WORK.md for the agent (what the module does, the files it reads and writes)
    lineage: str = ""               # one line: what the pack records in the lineage graph
    schemas: dict = field(default_factory=dict)   # inventory / finding record shapes: name -> [Column]
    cards: Callable | None = None   # fn(u) -> extra module-page cards [{"title", "columns", "rows", "empty"}]
    on_done: Callable | None = None # fn(ctx) when an item finishes
    router: APIRouter | None = None # extra routes; their paths start with /api/m/<module>
    _steps: dict = field(default_factory=dict, repr=False)

    def steps(self, work: str) -> list[Step]:
        if work not in self._steps:
            self._steps[work] = _plan_steps(self, work)
        return self._steps[work]

    def step(self, work: str, sid: str) -> Step | None:
        return next((s for s in self.steps(work) if s.id == sid), None)


PACKS: dict[str, Pack] = {}
PROOFS: dict[str, dict] = {}


def _sid(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "step"


def _manual(name: str, text: str) -> Step:
    """A journey stage the pack has no handler for yet: a person does it and records what was done (nothing automatic,
    nothing pretended)."""
    def run(ctx):
        return {"summary": "A person does this step for now: record what was done and where its evidence is, then confirm.",
                "data": {"text": text or name}, "records": ctx.records(ctx.step_id) or [{"id": "r-1", "what": "", "evidence": ""}]}
    return Step(kind="person", run=run, view="text", confirm="what was done, with where its evidence is",
                edit=Edit(columns=[Column("what", "What was done", "longtext", required=True), Column("evidence", "Where the evidence is", "text")], label="note"))


def _plan_steps(pack: Pack, work: str) -> list[Step]:
    m = registry.BY_ID[pack.module]
    w = pack.work[work]
    plan = registry.plan_for(m, work)
    names = list(w.journey or plan["journey"])
    texts = [] if w.journey else list(plan.get("steps") or [])
    confirms = {}
    for label, text in registry.confirm_for(m, work):
        cands = [label, *ALIASES.get(label, ())]
        hit = next((n for c in cands for n in names if n.lower() == c.lower() and n not in confirms), None)
        if hit:
            confirms[hit] = (label, text)
    out = []
    for i, name in enumerate(names):
        base = w.steps.get(name) or w.steps.get(_sid(name))
        text = (base.text if base and base.text else "") or (texts[i] if i < len(texts) else "")
        s = base or _manual(name, text)
        s = Step(**{k: getattr(s, k) for k in Step.__dataclass_fields__})            # a copy per work type
        s.id, s.name, s.text = _sid(name), name, text
        s.agent = s.agent or DEFAULT_AGENT.get(s.kind, "")
        if s.confirm is False:
            s.confirm_label, s.confirm_text = "", ""
        elif isinstance(s.confirm, str):
            s.confirm_label, s.confirm_text = confirms.get(name, (name, ""))[0], s.confirm
        elif name in confirms:
            s.confirm_label, s.confirm_text = confirms[name]
        elif s.kind == "person":
            s.confirm_label, s.confirm_text = name, "this step, before the next one starts"
        out.append(s)
    return out


def register(pack: Pack) -> Pack:
    """Called by each pack at import. Checks the pack against the registry and wires its agents into Team & agents."""
    m = registry.BY_ID.get(pack.module)
    if not m:
        raise ValueError(f"No module {pack.module!r} in the registry")
    allowed = set(m["work"]) or {"engage"}
    bad = [w for w in pack.work if w not in allowed]
    if bad:
        raise ValueError(f"{pack.module}: the registry lists no work type {', '.join(bad)} for this module")
    for k, p in pack.platforms.items():
        p.id = k
    if pack.router is not None:
        bad = [r.path for r in pack.router.routes if not getattr(r, "path", "").startswith(f"/api/m/{pack.module}/")]
        if bad:
            raise ValueError(f"{pack.module}: every route of a pack sits under /api/m/{pack.module}/ (P17 switches a module off by prefix): {bad}")
    prefix = f"/api/m/{pack.module}"
    if prefix not in (m.get("api") or []):
        raise ValueError(f'{pack.module}: its registry line needs api=["{prefix}"] - P17 answers 403 under that prefix where the module is switched off')
    if pack.router is not None:
        router.include_router(pack.router)
    PACKS[pack.module] = pack
    pack._steps.clear()
    from . import home, team
    for w in pack.work:
        for s in pack.steps(w):
            if s.kind not in STEP_KINDS:
                raise ValueError(f"{pack.module}/{w}/{s.name}: unknown step kind {s.kind!r}")
            if s.view not in VIEWS:
                raise ValueError(f"{pack.module}/{w}/{s.name}: unknown view {s.view!r}")
            stage = f"{pack.module}.{s.id}"
            team.AGENTS[stage] = s.agent or "Relay agent"
            helpers = [(stage, s)] + [(f"{stage}.{aid}", a) for aid, a in s.actions.items() if a.kind == "agent"]
            for st_name, spec in helpers:
                if spec.kind == "agent":
                    worker.TIMEOUT_S[st_name] = spec.timeout_s
                    team.AGENTS[st_name] = spec.agent or s.agent or "Relay agent"
                    for coll in (getattr(team, "LLM_STAGES", None), getattr(team, "WORK_STAGES", None), getattr(home, "LLM_STAGES", None)):
                        if isinstance(coll, set):
                            coll.add(st_name)
    checkpoints.register_kind(f"wb.{pack.module}", m.get("short") or m["name"], _on_decision)
    return pack


def proof(name: str, label: str):
    """Register a proof check: fn(ctx, **kw) -> {"status": pass|warn|fail|skip, "measured", "expected", "detail", "rows"}."""
    def deco(fn):
        PROOFS[name] = {"label": label, "fn": fn}
        return fn
    return deco


def pack_of(mid: str) -> Pack | None:
    return PACKS.get(mid)


def module_state(mid: str) -> str | None:
    """The module's state in the current workspace, as the registry shows it: 'locked' (not in its edition), 'off'
    (switched off for it, P17), else the registry's own (available, partly ...)."""
    m = registry.BY_ID.get(mid)
    if not m:
        return None
    try:
        return registry.state_of(m, registry.brand()["edition"], registry.switched_on())
    except Exception:  # noqa: BLE001 - before the control plane exists: the registry's status
        return m.get("status")


def module_on(mid: str) -> bool:
    """P17 entitlements: the module is in this workspace's edition and switched on for it. Its API prefix already
    answers 403 otherwise (tenancy.denied); the engine checks too, for what does not come through that prefix (a
    decision in the Validation queue, the next step of a running item, Home, the packs list)."""
    return module_state(mid) not in (None, "locked", "off")


def _off(mid: str) -> HTTPException:
    return HTTPException(403, f"{registry.BY_ID[mid]['name']} is not switched on for this workspace. Ask your administrator.")


# ================================================================== small helpers

def lab_now() -> float:
    """The clock an estate is read against (how far back "the last 30 days" reaches): the real one - except in the test
    lab (D2D_TEST_HOOKS=1), where D2D_LAB_SHIFT seconds move it to the simulators' fixed "now", so a look-back window
    keeps covering the lab's dated runs however long after that date the suite runs."""
    t = time.time()
    if os.environ.get("D2D_TEST_HOOKS") == "1":
        try:
            t += float(os.environ.get("D2D_LAB_SHIFT") or 0)
        except ValueError:
            pass
    return t


def _now() -> float:
    return time.time()


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1048576 else f"{n / 1048576:.1f} MB"


def _when(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d %b %Y %H:%M UTC") if t else "-"


def _lock(pid: str) -> threading.RLock:
    key = (db.tenant(), pid)
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.RLock()
        return _LOCKS[key]


def folder(pid: str) -> Path:
    return store.root() / pid


def route_of(st: dict) -> str:
    return f"#/m/{st['module']}/i/{st['id']}"


def _jsonable(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    try:
        import decimal
        if isinstance(v, decimal.Decimal):
            return float(v)
    except ImportError:
        pass
    return str(v)


def _dumps(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, default=_jsonable)


def _load(pid: str) -> dict:
    st = store.load(pid)
    if st.get("kind") != KIND:
        raise KeyError(pid)
    return st


def _step(st: dict, sid: str) -> dict:
    s = next((x for x in st["steps"] if x["id"] == sid), None)
    if s is None:
        raise HTTPException(404, "No such step.")
    return s


def current_step(st: dict) -> dict | None:
    return next((s for s in st["steps"] if s["status"] not in ("done", "skipped")), None)


def _close(r) -> None:
    try:
        if r is not None and hasattr(r, "con") and isinstance(r, FileReader):
            r.con.close()
    except Exception:  # noqa: BLE001
        pass


# ================================================================== readers (DuckDB over uploads; warehouses and platforms through connectors)

class FileReader(oc.DuckReader):
    """A data file in a work item's folder, read with DuckDB (a fresh connection per reader: uploads change)."""
    label = "upload"

    def __init__(self, workdir: Path, file: str):  # noqa: D401 - not calling DuckReader.__init__ (it caches connections)
        from genbi_kit import data as data_mod
        self.workdir, self.file = Path(workdir), file
        if not (self.workdir / "data" / file).exists():
            raise oc.ReadError(f"{file} is not in the work item's data folder")
        self.con = data_mod.connect(self.workdir)
        self.view = data_mod.raw_name(Path(file))


def table_sql(r) -> str:
    """The table expression a reader's SQL uses (DuckDB dialect; SqlReader transpiles it to the warehouse's own)."""
    return r._table_duck() if isinstance(r, oc.SqlReader) else oc._q(r.view)


# ================================================================== the context a step function gets

class Ctx:
    """What every step function receives: the work item, its folder, earlier results, and the helpers a step needs.
    A step returns a dict: summary (str), data (the view's payload), records (editable rows), counts ({label: n}),
    items (lines for the Validation queue), ok (False stops the journey for a person), next (a later step id to jump
    to). Evidence and outputs are written through ctx.evidence / ctx.output while the step runs."""

    def __init__(self, pid: str, step_id: str | None = None, *, who: str | None = None, comment: str | None = None, action: str | None = None):
        self.id, self.step_id, self.who, self.comment, self.action = pid, step_id, who, comment, action
        self.st = _load(pid)
        self.pack = PACKS[self.st["module"]]
        self.data = dict(self.st.get("data") or {})
        self.new_evidence: list[dict] = []
        self.new_outputs: list[dict] = []

    # ---- the item
    module = property(lambda self: self.st["module"])
    work = property(lambda self: self.st["work"])
    title = property(lambda self: self.st["title"])
    brief = property(lambda self: self.st.get("brief") or "")
    scope = property(lambda self: self.st.get("scope") or {})
    owner = property(lambda self: (db.project(self.id) or {}).get("owner_id"))
    dir = property(lambda self: folder(self.id))
    module_name = property(lambda self: registry.BY_ID[self.st["module"]]["name"])

    @property
    def spec(self) -> Step:
        return self.pack.step(self.work, self.step_id) if self.step_id else None

    def get(self, key: str, default=None):
        """Pack data kept on the item between steps (project.json `data`)."""
        return self.data.get(key, default)

    def put(self, key: str, value) -> None:
        self.data[key] = value

    def result(self, sid: str) -> dict | None:
        """The stored result of an earlier step: {"summary", "data", "records", "counts", "ok", "status"}."""
        s = next((x for x in self.st["steps"] if x["id"] == sid), None)
        return {k: s.get(k) for k in ("summary", "data", "records", "counts", "ok", "status")} if s else None

    def records(self, sid: str) -> list[dict]:
        r = self.result(sid)
        return list((r or {}).get("records") or [])

    # ---- sources
    def connections(self) -> list[dict]:
        """The item's connections, as its owner may use them (a person's own or one shared with them)."""
        out = []
        for cid in self.st.get("connections") or []:
            try:
                out.append(connectors.connection(cid, self.owner or ""))
            except connectors.ConnectorError:
                continue
        return out

    def connection(self, cid: str) -> dict:
        try:
            return connectors.connection(cid, self.owner or "")
        except connectors.ConnectorError as e:
            raise StepFailed("The connection this work item reads through is not one its owner may use any more.") from e

    def files(self, exts: tuple | None = None) -> list[dict]:
        return [f for f in self.st.get("files") or [] if not exts or Path(f["name"]).suffix.lower() in exts]

    def platform(self) -> Platform:
        return self.pack.platforms.get(self.st.get("platform") or "") or next(iter(self.pack.platforms.values()))

    def reader(self, ref: dict):
        """A read-only reader for a data reference (observe_checks readers: columns, count, stats, dupes, run(sql))."""
        src = ref.get("source")
        if src == "file":
            item = ref.get("item") or self.id
            if item != self.id:
                p = db.project(item)
                u = db.user(self.owner or "") or {}
                if not (p and u and auth.can_project(u, "view", p)):
                    raise StepFailed(f"The file {ref.get('file')} belongs to a work item its owner can no longer see.")
            return FileReader(folder(item), ref["file"])
        if src == "connection":
            c = self.connection(ref["connection"])
            if connectors.KINDS.get(c["kind"], {}).get("dialect"):
                return oc.SqlReader(c, ref["object"], self.who or self.owner or "workbench")
            return oc.SdkReader(c, ref["object"], self.who or self.owner or "workbench")
        raise StepFailed(f"Unknown data reference: {ref}")

    # ---- what a step leaves behind
    def evidence(self, label: str, payload, *, kind: str = "json", ok: bool | None = None, step: str | None = None) -> str:
        """Write one piece of evidence for the current step (evidence/<step>/<id>.json); returns its id."""
        sid = step or self.step_id or "item"
        eid = "ev-" + _secrets.token_hex(4)
        d = self.dir / "evidence" / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{eid}.json").write_text(_dumps({"id": eid, "label": label, "kind": kind, "step": sid, "when": _now(), "ok": ok, "payload": payload}), encoding="utf-8")
        rows = len(payload) if isinstance(payload, list) else len(payload["rows"]) if isinstance(payload, dict) and isinstance(payload.get("rows"), list) else None
        self.new_evidence.append({"id": eid, "label": label[:200], "kind": kind, "step": sid, "file": f"evidence/{sid}/{eid}.json", "ok": ok, "when": _now(), "rows": rows})
        return eid

    def output(self, name: str, content, *, label: str = "") -> str:
        """Write a file to outputs/ (data, configs, code, documents); listed on the item and in the evidence pack."""
        name = re.sub(r"[^\w.\- ]+", "_", name).strip()[:120] or "output"
        d = self.dir / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else str(content).encode("utf-8")
        (d / name).write_bytes(data)
        self.new_outputs = [o for o in self.new_outputs if o["name"] != name]
        self.new_outputs.append({"name": name, "label": label or name, "step": self.step_id, "bytes": len(data), "when": _now()})
        return name

    def note(self, text: str, level: str = "info", items: list | None = None) -> None:
        worker.app_note(self.id, f"{self.module}.{self.step_id or 'item'}", text, level, items)

    def proof(self, name: str, *, label: str | None = None, **kw) -> dict:
        """Run a registered proof check; its full result is stored as evidence; returns the gate row."""
        p = PROOFS.get(name)
        if not p:
            raise StepFailed(f"Unknown proof check {name!r}")
        try:
            r = p["fn"](self, **kw) or {}
        except oc.ReadError as e:
            r = {"status": "fail", "detail": f"could not read: {e}"}
        except StepFailed as e:
            r = {"status": "fail", "detail": str(e)}
        row = {"name": name, "label": label or p["label"], "status": r.get("status") or "skip", "measured": r.get("measured"), "expected": r.get("expected"),
               "detail": r.get("detail") or ""}
        row["evidence"] = self.evidence(row["label"], {**row, "rows": r.get("rows") or []}, kind="proof", ok=row["status"] in ("pass", "warn", "skip"))
        return row

    def lineage_node(self, kind: str, system: str, name: str, *, label: str | None = None, properties: dict | None = None, own: bool = True) -> str:
        """A node in the lineage graph. `own=False` for a node other modules share (a warehouse table): it is not linked
        to this item and keeps its source; the pack's own nodes (a rule set, a job) open the work item."""
        props = dict(properties or {})
        if own:
            props.update(work_item=self.id, module=self.module, link=route_of(self.st))
        nid = lineage.upsert_node(kind, system, name, label=label, properties=props, source=f"wb:{self.id}" if own else None)
        have = self.data.setdefault("_lineage", [])
        if nid not in have:
            have.append(nid)
        return nid

    def lineage_edge(self, a: str, b: str, kind: str, evidence: dict | None = None) -> None:
        lineage.upsert_edge(a, b, kind, {**(evidence or {}), "work_item": self.id}, source=f"wb:{self.id}")

    def request_write(self, connection_id: str, obj: str, payload: dict, what: str) -> dict:
        """The only way a step writes to a connected system: a checkpoint for a named person (connection.write); the
        adapter writes when - and only when - it is accepted."""
        c = self.connection(connection_id)
        try:
            cp = connectors.request_write(c, obj, payload, self.who or self.owner, module=self.module_name, what=what)
        except Exception as e:  # noqa: BLE001 - ScopeError / ConnectorError: shown to the person
            raise StepFailed(str(e)) from e
        self._handoff({"kind": "write", "label": what, "connection": c["name"], "checkpoint": cp["id"], "status": "awaiting approval", "link": "#/validate"})
        return cp

    def _handoff(self, h: dict) -> dict:
        h = {"id": "h-" + _secrets.token_hex(3), "when": _now(), "step": self.step_id, **h}
        self.data.setdefault("_handoffs", []).append(h)
        db.audit("wb.handoff", self.id, {k: h.get(k) for k in ("kind", "label", "case", "checkpoint", "status")}, self.who or "agent")
        return h

    def heal(self, title: str, what: str, *, place: str = "", signature: str | None = None, subject: dict | None = None) -> dict:
        """Hand a failure to Self-healing (call it only after a person approved the hand-off)."""
        return handoff_heal(self, title, what, place=place, signature=signature, subject=subject)

    def ticket(self, title: str, body: str, *, priority: str = "P3", about: str = "") -> dict:
        """Raise a ticket (call it only after a person approved it): through a write-capable service-desk connection of
        the item (its own per-change approval), else joined to a matching Service desk group, else a ticket draft."""
        return handoff_ticket(self, title, body, priority=priority, about=about)


# ================================================================== proof checks (pluggable; reconciliation built in)

def _norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    try:
        import decimal
        if isinstance(v, decimal.Decimal):
            return round(float(v), 6)
    except ImportError:
        pass
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:19]
    s = str(v).strip()
    try:
        return round(float(s), 6) if re.fullmatch(r"-?\d+(\.\d+)?", s) else s
    except ValueError:
        return s


def _agg(r, exprs: list[tuple[str, str]]) -> dict:
    """One SELECT of aggregates over a reader's table: [(alias, duckdb expression)] -> {alias: value}."""
    if isinstance(r, oc.SdkReader):
        raise oc.ReadError("this platform is read as records; its aggregates are computed in Python")
    sql = "SELECT " + ", ".join(f"{e} AS {a}" for a, e in exprs) + f" FROM {table_sql(r)}"
    row = r.run(sql)[0]
    return {k.lower(): v for k, v in row.items()}


def _cols(r) -> dict[str, dict]:
    return {c["name"].lower(): c for c in r.columns()}


def _qc(name: str) -> str:
    return oc._q(name)


def checksum_exprs(cols: list[dict]) -> list[tuple[str, str]]:
    """Engine-independent column fingerprints (count, sum, min, max, distinct, total length) - the same on every engine,
    unlike hash functions, so a source in one database reconciles with a target in another."""
    out = [("n_rows", "COUNT(*)")]
    for i, c in enumerate(cols):
        q = _qc(c["name"])
        out.append((f"c{i}_n", f"COUNT({q})"))
        if c["kind"] in ("int", "decimal"):
            out += [(f"c{i}_s", f"SUM(CAST({q} AS DOUBLE))"), (f"c{i}_lo", f"MIN({q})"), (f"c{i}_hi", f"MAX({q})")]       # rounded in Python (not every engine rounds a double)
        elif c["kind"] == "date":
            out += [(f"c{i}_lo", f"MIN({q})"), (f"c{i}_hi", f"MAX({q})")]
        elif c["kind"] == "bool":
            out += [(f"c{i}_t", f"SUM(CASE WHEN {q} THEN 1 ELSE 0 END)")]
        else:
            out += [(f"c{i}_d", f"COUNT(DISTINCT {q})"), (f"c{i}_l", f"SUM(LENGTH(CAST({q} AS VARCHAR)))")]
    return out


def _py_checksums(rows: list[dict], cols: list[dict]) -> dict:
    out = {"n_rows": len(rows)}
    for i, c in enumerate(cols):
        vals = [r.get(c["name"]) for r in rows if r.get(c["name"]) not in (None, "")]
        out[f"c{i}_n"] = len(vals)
        if c["kind"] in ("int", "decimal"):
            nums = [float(v) for v in vals if _norm(v) is not None and isinstance(_norm(v), float)]
            out.update({f"c{i}_s": round(sum(nums), 2) if nums else None, f"c{i}_lo": min(nums) if nums else None, f"c{i}_hi": max(nums) if nums else None})
        elif c["kind"] == "date":
            ss = sorted(str(v)[:19] for v in vals)
            out.update({f"c{i}_lo": ss[0] if ss else None, f"c{i}_hi": ss[-1] if ss else None})
        else:
            out.update({f"c{i}_d": len({str(v) for v in vals}), f"c{i}_l": sum(len(str(v)) for v in vals)})
    return out


def _same(a, b, tol: float = 0.0) -> bool:
    a, b = _norm(a), _norm(b)
    if isinstance(a, str) and isinstance(b, str) and re.match(r"\d{4}-\d{2}-\d{2}", a) and re.match(r"\d{4}-\d{2}-\d{2}", b):
        return a[:10] == b[:10] if (len(a) <= 10 or len(b) <= 10) else a[:19] == b[:19]
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.01, abs(a) * tol, abs(b) * 1e-9)
    return a == b


def _readers(ctx: Ctx, source: dict, target: dict):
    return ctx.reader(source), ctx.reader(target)


@proof("row_count", "Row counts: source vs target")
def _p_rows(ctx: Ctx, source: dict, target: dict, tolerance_pct: float = 0.0, **_):
    a, b = _readers(ctx, source, target)
    try:
        na, nb = a.count(), b.count()
    finally:
        _close(a); _close(b)
    diff = abs(na - nb)
    ok = diff <= (max(na, nb) * tolerance_pct / 100.0)
    return {"status": "pass" if ok else "fail", "measured": nb, "expected": na,
            "detail": f"{na:,} rows in the source, {nb:,} in the target" + ("" if ok else f" - {diff:,} {'missing' if nb < na else 'extra'}")}


@proof("checksum", "Checksums per column: count, sum, min, max, distinct, length")
def _p_checksums(ctx: Ctx, source: dict, target: dict, columns: list[str] | None = None, tolerance_pct: float = 0.0, **_):
    a, b = _readers(ctx, source, target)
    try:
        ca, cb = _cols(a), _cols(b)
        names = [n for n in ca if n in cb and (not columns or n in [c.lower() for c in columns])]
        if not names:
            return {"status": "fail", "detail": "the source and the target share no column names to compare"}
        cols = [ca[n] for n in names]
        tcols = [{**cb[n], "kind": ca[n]["kind"]} for n in names]
        sa = _py_checksums(a._read().get("rows") or [], cols) if isinstance(a, oc.SdkReader) else _agg(a, checksum_exprs(cols))
        sb = _py_checksums(b._read().get("rows") or [], tcols) if isinstance(b, oc.SdkReader) else _agg(b, checksum_exprs(tcols))
    finally:
        _close(a); _close(b)
    rows, bad = [], 0
    for i, c in enumerate(cols):
        for key, what in (("n", "values"), ("s", "sum"), ("lo", "min"), ("hi", "max"), ("d", "distinct"), ("l", "total length"), ("t", "true count")):
            k = f"c{i}_{key}"
            if k not in sa:
                continue
            same = _same(sa.get(k), sb.get(k), tolerance_pct / 100.0)
            bad += 0 if same else 1
            rows.append({"column": c["name"], "fingerprint": what, "source": _norm(sa.get(k)), "target": _norm(sb.get(k)), "same": same})
    n = len(rows)
    return {"status": "pass" if not bad else "fail", "measured": n - bad, "expected": n, "rows": rows,
            "detail": f"{n - bad} of {n} fingerprints agree on {len(cols)} column(s)" + (f"; {bad} differ" if bad else "")}


@proof("totals", "Business totals: source vs target")
def _p_totals(ctx: Ctx, source: dict, target: dict, measures: list[str], by: str | None = None, tolerance_pct: float = 0.5, **_):
    a, b = _readers(ctx, source, target)
    try:
        def tot(r):
            cs = _cols(r)
            ms = [cs[m.lower()]["name"] for m in measures if m.lower() in cs]
            if len(ms) != len(measures):
                raise oc.ReadError(f"{', '.join(m for m in measures if m.lower() not in cs)} not found")
            g = cs[by.lower()]["name"] if by and by.lower() in cs else None
            if by and not g:
                raise oc.ReadError(f"{by} not found")
            if isinstance(r, oc.SdkReader):
                out: dict = {}
                for row in r._read().get("rows") or []:
                    key = str(row.get(g)) if g else "all"
                    for m in ms:
                        v = _norm(row.get(m))
                        out.setdefault((key, m.lower()), 0.0)
                        out[(key, m.lower())] += v if isinstance(v, float) else 0.0
                return out
            sel = ", ".join(f"SUM(CAST({_qc(m)} AS DOUBLE)) AS m{i}" for i, m in enumerate(ms))
            sql = f"SELECT {'CAST(' + _qc(g) + ' AS VARCHAR) AS g, ' if g else ''}{sel} FROM {table_sql(r)}" + (f" GROUP BY CAST({_qc(g)} AS VARCHAR)" if g else "")
            res = {}
            for row in r.run(sql):
                row = {k.lower(): v for k, v in row.items()}
                for i, m in enumerate(ms):
                    res[(str(row.get("g")) if g else "all", m.lower())] = float(row.get(f"m{i}") or 0)
            return res
        ta, tb = tot(a), tot(b)
    finally:
        _close(a); _close(b)
    rows, bad = [], 0
    for key in sorted(set(ta) | set(tb)):
        va, vb = ta.get(key), tb.get(key)
        ok = va is not None and vb is not None and abs(va - vb) <= max(0.01, abs(va) * tolerance_pct / 100.0)
        bad += 0 if ok else 1
        rows.append({"group": key[0], "measure": key[1], "source": None if va is None else round(va, 2), "target": None if vb is None else round(vb, 2),
                     "difference": None if va is None or vb is None else round(vb - va, 2), "same": ok})
    return {"status": "pass" if not bad else "fail", "measured": len(rows) - bad, "expected": len(rows), "rows": rows,
            "detail": f"{len(rows) - bad} of {len(rows)} totals agree within {tolerance_pct:g} %" + (f"; {bad} differ" if bad else "")}


@proof("sample_diff", "Sample rows compared field by field")
def _p_sample(ctx: Ctx, source: dict, target: dict, keys: list[str], n: int = 20, columns: list[str] | None = None, **_):
    a, b = _readers(ctx, source, target)
    try:
        ca, cb = _cols(a), _cols(b)
        ks = [k.lower() for k in keys]
        miss = [k for k in ks if k not in ca or k not in cb]
        if miss:
            return {"status": "fail", "detail": f"key column(s) {', '.join(miss)} not on both sides"}
        common = [c for c in ca if c in cb and (not columns or c in [x.lower() for x in columns])]

        def rows_of(r, where: str | None = None, order: bool = False):
            if isinstance(r, oc.SdkReader):
                return [{k.lower(): v for k, v in row.items()} for row in r._read().get("rows") or []]
            names = [ca[k]["name"] if r is a else cb[k]["name"] for k in ks]
            if isinstance(a, FileReader) and isinstance(b, FileReader):   # snapshot files: DuckDB may read "0000099001" as text in one file and 99001 in the other -
                kexpr = " || '|' || ".join(                # compare digit-only keys without their leading zeros on both sides
                    f"(CASE WHEN regexp_full_match(CAST({_qc(x)} AS VARCHAR), '[0-9]+') THEN ltrim(CAST({_qc(x)} AS VARCHAR), '0') ELSE CAST({_qc(x)} AS VARCHAR) END)" for x in names)
            else:
                kexpr = " || '|' || ".join(f"CAST({_qc(x)} AS VARCHAR)" for x in names)
            sql = f"SELECT * FROM {table_sql(r)}" + (f" WHERE {kexpr} IN ({where})" if where else "") + (f" ORDER BY {', '.join(_qc(x) for x in names)}" if order else "") + f" LIMIT {int(n) if order else 10000}"
            return [{k.lower(): v for k, v in row.items()} for row in r.run(sql)]
        src = rows_of(a, order=True)[:n]
        def keyof(row):
            out = []
            for k in ks:
                v = _norm(row.get(k))
                s = (str(int(v)) if float(v).is_integer() else str(v)) if isinstance(v, float) else str(v)
                out.append(s.lstrip("0") if files_only and s.isdigit() else s)          # leading zeros do not make two keys different (see kexpr)
            return "|".join(out)
        files_only = isinstance(a, FileReader) and isinstance(b, FileReader)
        wanted = [keyof(r) for r in src]
        lits = ", ".join("'" + w.replace("'", "''") + "'" for w in wanted) or "''"
        tgt = {keyof(r): r for r in rows_of(b, where=lits)}
    finally:
        _close(a); _close(b)
    diffs, missing = [], []
    for r in src:
        k = keyof(r)
        t = tgt.get(k)
        if t is None:
            missing.append(k)
            diffs.append({"key": k, "column": "(row)", "source": "present", "target": "missing"})
            continue
        for c in common:
            if not _same(r.get(c), t.get(c), 1e-9):
                diffs.append({"key": k, "column": c, "source": _norm(r.get(c)), "target": _norm(t.get(c))})
    bad_rows = len({d["key"] for d in diffs})
    return {"status": "pass" if not diffs else "fail", "measured": len(src) - bad_rows, "expected": len(src), "rows": diffs[:200],
            "detail": f"{len(src) - bad_rows} of {len(src)} sampled rows identical on {len(common)} column(s)" + (f"; {len(missing)} missing in the target" if missing else "")
            + (f"; {len(diffs) - len(missing)} field(s) differ" if len(diffs) > len(missing) else "")}


@proof("tests_run", "Tests run and passed")
def _p_tests(ctx: Ctx, results: list[dict], **_):  # noqa: ARG001
    bad = [r for r in results if (r.get("status") or "").lower() not in ("pass", "passed", "ok", "success")]
    return {"status": "pass" if results and not bad else "fail" if bad else "skip", "measured": len(results) - len(bad), "expected": len(results), "rows": results[:200],
            "detail": f"{len(results) - len(bad)} of {len(results)} tests passed" if results else "no tests were run"}


@proof("references_real", "Every reference exists")
def _p_refs(ctx: Ctx, refs: list[str], known: list[str], **_):  # noqa: ARG001
    k = {str(x).lower() for x in known}
    missing = sorted({r for r in refs if str(r).lower() not in k})
    return {"status": "pass" if not missing else "fail", "measured": len(set(refs)) - len(missing), "expected": len(set(refs)), "rows": [{"reference": m, "found": False} for m in missing],
            "detail": "every reference resolves" if not missing else f"{len(missing)} reference(s) not found: {', '.join(missing[:8])}"}


# ================================================================== Run & support: Self-healing, tickets, schedules

def handoff_heal(ctx: Ctx, title: str, what: str, *, place: str = "", signature: str | None = None, subject: dict | None = None) -> dict:
    from . import heal
    sig = signature or f"{ctx.module}:{_sid(title)[:40]}"
    cand = {"signature": sig, "kind": "generic", "source": "workbench", "source_id": f"{ctx.id}:{sig}", "title": f"{title}"[:200], "what": what[:1000],
            "place": place or f"{ctx.module_name} - {ctx.title}", "since": _now(), "route": "config", "owner_id": ctx.owner,
            "subject": {"work_item": ctx.id, "module": ctx.module, **(subject or {})}, "work": {"module": "workbench", "table": "wb_items", "id": ctx.id}}
    case = heal.open_case(cand, ctx.who)
    if case is None:
        have = db.one("SELECT id FROM heal_cases WHERE source = ? AND source_id = ? AND signature = ? AND closed IS NULL", (cand["source"], cand["source_id"], sig))
        cid = have["id"] if have else None
        return ctx._handoff({"kind": "heal", "label": title, "case": cid, "status": "already with Self-healing", "link": f"#/heal/{cid}" if cid else "#/heal"})
    return ctx._handoff({"kind": "heal", "label": title, "case": case["id"], "status": "case opened", "link": f"#/heal/{case['id']}"})


def handoff_ticket(ctx: Ctx, title: str, body: str, *, priority: str = "P3", about: str = "") -> dict:
    # 1. a write-capable service-desk connection on the item: the platform's own per-change approval
    for c in ctx.connections():
        a = connectors.sdk.get(c["kind"]) if hasattr(connectors, "sdk") else None
        if (c.get("category") or connectors.KINDS.get(c["kind"], {}).get("category")) == "crm" and connectors.may_write(c) and getattr(a, "can_write", False):
            cp = connectors.request_write(c, "ticket", {"title": title[:200], "description": body[:4000], "priority": priority, "labels": ["relay", ctx.module]},
                                          ctx.who or ctx.owner, module=ctx.module_name, what=f"Raise a ticket: {title[:120]}")
            return ctx._handoff({"kind": "ticket", "label": title, "checkpoint": cp["id"], "status": "awaiting the write approval", "link": "#/validate", "via": c["name"]})
    # 2. an open Service desk group about the same thing: its own write-back gate
    try:
        from . import itsm
        words = [w for w in re.findall(r"[a-z0-9_]{4,}", (about or title).lower())][:6]
        for g in itsm.groups():
            if g["status"] in ("closed", "written"):
                continue
            hay = " ".join(str(g.get(k) or "") for k in ("title", "about", "summary")).lower()
            if words and any(w in hay for w in words):
                cp = itsm.open_checkpoint(g["id"], agent=ctx.module_name, who=ctx.who)
                return ctx._handoff({"kind": "ticket", "label": title, "group": g["id"], "checkpoint": cp["id"], "status": "joined a Service desk group", "link": "#/servicedesk"})
    except Exception:  # noqa: BLE001 - the draft below is kept when the Service desk cannot take it
        traceback.print_exc()
    # 3. a ticket draft in the item's outputs, ready to copy
    name = ctx.output(f"ticket-{_sid(title)[:40]}.md", f"# {title}\n\nPriority: {priority}\n\n{body}\n", label=f"Ticket draft: {title[:60]}")
    return ctx._handoff({"kind": "ticket", "label": title, "status": "draft (no service desk connected)", "output": name})


def _hm(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (s or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise HTTPException(400, "The time must look like 06:00.")
    return int(m.group(1)), int(m.group(2))


def check_schedule(s: dict) -> dict:
    if not isinstance(s, dict) or s.get("every") not in CADENCES:
        raise HTTPException(400, "How often: every hour, day, week or month.")
    out = {"every": s["every"], "tz": s.get("tz") or "UTC"}
    try:
        ZoneInfo(out["tz"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Unknown time zone {out['tz']!r}.") from e
    if out["every"] != "hour":
        _hm(s.get("at") or "06:00")
        out["at"] = s.get("at") or "06:00"
    if out["every"] == "week":
        wd = int(s.get("weekday") if s.get("weekday") is not None else 0)
        if not 0 <= wd <= 6:
            raise HTTPException(400, "The weekday is 0 (Monday) to 6 (Sunday).")
        out["weekday"] = wd
    if out["every"] == "month":
        day = str(s.get("day") if s.get("day") is not None else 1).strip().lower()
        if day != "last" and not (day.isdigit() and 1 <= int(day) <= 28):
            raise HTTPException(400, "The day of the month is 1 to 28, or \"last\" (the last day of each month).")
        out["day"] = day if day == "last" else int(day)
    return out


def _month_day(year: int, month: int, day) -> int:
    import calendar
    return calendar.monthrange(year, month)[1] if day == "last" else int(day)


def next_run(s: dict, now: float | None = None) -> float:
    now = now or _now()
    tz = ZoneInfo(s.get("tz") or "UTC")
    local = dt.datetime.fromtimestamp(now, tz)
    if s["every"] == "hour":
        return (local.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)).timestamp()
    hh, mm = _hm(s.get("at") or "06:00")
    cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if s["every"] == "week":
        cand += dt.timedelta(days=(int(s.get("weekday", 0)) - cand.weekday()) % 7)
        if cand <= local:
            cand += dt.timedelta(days=7)
    elif s["every"] == "month":
        day = s.get("day", 1)
        cand = cand.replace(day=_month_day(cand.year, cand.month, day))
        if cand <= local:
            y, m = (cand.year + 1, 1) if cand.month == 12 else (cand.year, cand.month + 1)
            cand = cand.replace(year=y, month=m, day=_month_day(y, m, day))
    elif cand <= local:
        cand += dt.timedelta(days=1)
    return cand.timestamp()


def schedule_text(s: dict | None) -> str:
    if not s:
        return ""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if s["every"] == "hour":
        return "Every hour"
    if s["every"] == "week":
        return f"Every {days[int(s.get('weekday', 0))]} at {s.get('at')} ({s.get('tz')})"
    if s["every"] == "month":
        d = s.get("day", 1)
        return f"Every month on the {'last day' if d == 'last' else str(d) + ('st' if d in (1, 21) else 'nd' if d in (2, 22) else 'rd' if d in (3, 23) else 'th')} at {s.get('at')} ({s.get('tz')})"
    return f"Every day at {s.get('at')} ({s.get('tz')})"


# ================================================================== the item lifecycle

def _new_id(module: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:24].strip("-") or "work"
    return f"wb-{module}-{slug}-{_secrets.token_hex(2)}"


def _step_record(s: Step) -> dict:
    return {"id": s.id, "name": s.name, "kind": s.kind, "view": s.view, "agent": s.agent, "text": s.text, "confirm_label": s.confirm_label, "confirm": s.confirm_text,
            "approver": s.approver, "status": "pending", "summary": "", "data": None, "records": None, "counts": {}, "items": [], "ok": None, "evidence": [], "outputs": [],
            "started": None, "ended": None, "seconds": None, "runs": 0, "checkpoint": None, "decided_by": None, "decided": None, "comment": None, "error": None,
            "next": None, "edited": 0}


def status_of(st: dict) -> str:
    return "closed" if st.get("closed") else st["status"]


def _settle(st: dict) -> None:
    """The item's status from its steps (after a helper action, which never moves the journey)."""
    if st.get("closed"):
        st["status"] = "closed"
    elif any(s["status"] in ("running", "queued") for s in st["steps"]):
        return
    elif any(s["status"] == "waiting" for s in st["steps"]):
        st["status"] = "waiting"
    elif any(s["status"] == "error" for s in st["steps"]):
        st["status"] = "error"
    elif all(s["status"] in ("done", "skipped") for s in st["steps"]):
        st["status"] = "scheduled" if st.get("schedule") else "done"
    else:
        st["status"] = "new"


def index(st: dict) -> None:
    """Mirror the item's state into wb_items (the list screens, Home and the scheduler read it)."""
    cur = current_step(st)
    i = st["steps"].index(cur) if cur else len(st["steps"])
    p = db.project(st["id"]) or {}
    sched = st.get("schedule")
    vals = (st["module"], st["work"], st["title"][:200], st.get("platform"), status_of(st), cur["id"] if cur else None, i, len(st["steps"]), p.get("owner_id"),
            st.get("approver"), st.get("parent"), json.dumps(sched) if sched else None, st.get("next_run"), st.get("last_run"), len(st.get("rounds") or []),
            st.get("created") or _now(), _now(), st.get("closed"))
    with db.transaction():
        if db.one("SELECT 1 FROM wb_items WHERE id = ?", (st["id"],)):
            db.run("UPDATE wb_items SET module = ?, work = ?, title = ?, platform = ?, status = ?, step = ?, step_index = ?, steps = ?, owner_id = ?, approver_id = ?, parent = ?, "
                   "schedule = ?, next_run = ?, last_run = ?, rounds = ?, created = ?, updated = ?, closed = ? WHERE id = ?", vals + (st["id"],))
        else:
            db.run("INSERT INTO wb_items (module, work, title, platform, status, step, step_index, steps, owner_id, approver_id, parent, schedule, next_run, last_run, rounds, created, updated, closed, id) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", vals + (st["id"],))


def _mutate(pid: str, fn: Callable[[dict], Any]):
    with _lock(pid):
        st = _load(pid)
        out = fn(st)
        store.save(st)
    index(st)
    return out if out is not None else st


def _save_ctx(ctx: Ctx, st: dict) -> None:
    """Fold what a step left behind (pack data, evidence, outputs, hand-offs) into the item's state."""
    st["data"] = {**(st.get("data") or {}), **ctx.data}
    st.setdefault("evidence", []).extend(ctx.new_evidence)
    outs = {o["name"]: o for o in st.get("outputs") or []}
    for o in ctx.new_outputs:
        outs[o["name"]] = o
    st["outputs"] = list(outs.values())
    ctx.new_evidence, ctx.new_outputs = [], []


def save_files(pid: str, files: list[tuple[str, bytes]], who: str | None) -> list[dict]:
    """Uploads into data/ (a copy in the item's folder). An Excel workbook's first sheet is also kept as a CSV table."""
    d = folder(pid) / "data"
    d.mkdir(parents=True, exist_ok=True)
    added = []
    for name, data in files:
        safe = re.sub(r"[^\w.\- ]+", "_", Path(name).name).strip()[:120]
        if not safe or Path(safe).suffix.lower() not in DATA_EXT:
            raise HTTPException(400, f"{name}: this kind of file is not accepted here.")
        if len(data) > UPLOAD_MAX:
            raise HTTPException(400, f"{name} is bigger than {UPLOAD_MAX // 1048576} MB.")
        (d / safe).write_bytes(data)
        rec = {"name": safe, "bytes": len(data), "when": _now(), "by": who}
        if safe.lower().endswith((".csv", ".parquet")):
            rec["table"] = safe
        if safe.lower().endswith(".xlsx"):
            try:
                rec["table"], rec["sheet"] = xlsx_to_csv(d / safe)
            except Exception as e:  # noqa: BLE001 - kept as an attachment
                rec["note"] = f"the workbook could not be read as a table: {str(e)[:120]}"
        added.append(rec)

    def put(st):
        have = {f["name"]: f for f in st.get("files") or []}
        for r in added:
            have[r["name"]] = r
        st["files"] = list(have.values())
    _mutate(pid, put)
    for r in added:
        store.log(pid, {"kind": "user", "text": f"Uploaded {r['name']} ({_size(r['bytes'])})"})
    return added


def xlsx_to_csv(path: Path) -> tuple[str, str]:
    import csv

    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    out = path.with_name(path.stem + ".xlsx.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            if row is None or all(v is None for v in row):
                continue
            w.writerow(["" if v is None else (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for v in row])
    title = ws.title
    wb.close()
    return out.name, title


def create(module: str, work: str, title: str, *, who: str, brief: str = "", platform: str | None = None, connections: list[str] | None = None,
           scope: dict | None = None, approver: str | None = None, visibility: str = "private", team_id: str | None = None,
           files: list[tuple[str, bytes]] | None = None, parent: str | None = None, schedule: dict | None = None, start_now: bool = True) -> dict:
    pack = PACKS.get(module)
    if not pack:
        raise HTTPException(404, "This module has no workbench pack yet.")
    if work not in pack.work:
        raise HTTPException(400, f"{registry.BY_ID[module]['name']} does not do {WORK_NAME.get(work, work)} work yet.")
    w = pack.work[work]
    title = (title or "").strip()[:160]
    if not title:
        raise HTTPException(400, "Give the work item a name.")
    if visibility not in ("private", "team", "org"):
        raise HTTPException(400, "Who can see it: only me, my team or the organisation.")
    u = db.user(who) or {}
    teams = [t["id"] for t in u.get("teams") or []]
    team = team_id or (teams[0] if teams else db.DEFAULT_TEAM)
    if visibility == "team" and team not in teams and not auth.is_admin(u):
        raise HTTPException(400, "Share it with one of your own teams.")
    allowed = w.platforms or tuple(pack.platforms)
    picked = bool(platform)
    platform = platform or allowed[0]
    if platform not in allowed:
        raise HTTPException(400, "Pick one of the platforms this work offers.")
    cons = []
    for cid in dict.fromkeys(connections or []):
        try:
            c = connectors.connection(cid, who)
        except connectors.ConnectorError as e:
            raise HTTPException(400, "One of the connections is not yours to use.") from e
        if not any(c["kind"] in pack.platforms[p].kinds for p in allowed):
            raise HTTPException(400, f"{c['name']} ({connectors.KINDS[c['kind']]['label']}) is not a platform this work reads.")
        if not picked and not cons:                      # no platform named: the first connection's, not the pack's first
            platform = next((p for p in allowed if c["kind"] in pack.platforms[p].kinds), platform)
        cons.append(cid)
    scope = dict(scope or {})
    for f in w.fields:
        v = scope.get(f.key, f.default)
        if f.required and v in (None, "", []):
            raise HTTPException(400, f"{f.label} is needed.")
        if f.type == "cadence" and v:
            scope[f.key] = check_schedule(v)
        elif v is not None:
            scope[f.key] = v
    if approver and not db.user(approver):
        raise HTTPException(400, "The approver is not a person in this workspace.")
    if w.needs_source and not cons and not files and not scope.get("_source_ok"):
        raise HTTPException(400, "Pick a connection or upload the files this work reads.")
    if schedule is None and isinstance(scope.get("schedule"), dict):
        schedule = scope["schedule"]                     # a wizard field named "schedule" (type cadence) schedules the item
    if schedule:
        schedule = check_schedule(schedule)
    pid = _new_id(module, title)
    d = folder(pid)
    for sub in ("data", "evidence", "outputs"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    now = _now()
    st = {"id": pid, "kind": KIND, "module": module, "work": work, "name": title, "title": title, "prompt": brief[:240], "brief": brief.strip()[:8000],
          "platform": platform, "connections": cons, "files": [], "scope": scope, "approver": approver, "parent": parent, "status": "new", "error": None, "job": None,
          "model": worker.DEFAULT_MODEL, "created": now, "versions": [], "runs": [], "steps": [_step_record(s) for s in pack.steps(work)], "evidence": [], "outputs": [],
          "data": {}, "rounds": [], "schedule": schedule, "next_run": None, "last_run": None}
    store.save(st)
    db.add_project(pid, who, team, visibility)
    if approver and approver != who:                 # the named approver can open what they approve
        db.run("INSERT OR IGNORE INTO shares (project_id, principal_type, principal_id, permission, expires, created, created_by) VALUES (?, 'user', ?, 'view', NULL, ?, ?)",
               (pid, approver, now, who))
    index(st)
    (d / "request.md").write_text(f"# {title}\n\n{registry.BY_ID[module]['name']} - {WORK_NAME.get(work, work)}\n\n## The brief ({time.strftime('%Y-%m-%d %H:%M')})\n\n"
                                  f"{brief.strip() or '(no brief: the scope below is the whole request)'}\n\n## Scope\n\n"
                                  + "\n".join(f"- {k}: {v}" for k, v in scope.items() if not k.startswith("_")) + "\n", encoding="utf-8")
    if pack.guide:
        (d / "WORK.md").write_text(pack.guide, encoding="utf-8")
    if files:
        save_files(pid, files, who)
    store.log(pid, {"kind": "user", "text": f"Work item created: {title} ({WORK_NAME.get(work, work)})"})
    db.audit("wb.item.create", pid, {"module": module, "work": work, "title": title, "platform": platform, "connections": cons, "visibility": visibility}, who)
    if schedule:
        _mutate(pid, lambda s: s.update(next_run=next_run(schedule)))
    if start_now:
        start(pid, who=who)
    return _load(pid)


def _reset_from(st: dict, i: int) -> None:
    """Step i and every later one start again (their last results stay until they run; open checks are withdrawn)."""
    for s in st["steps"][i:]:
        if s["status"] == "waiting" and s.get("checkpoint"):
            c = checkpoints.get(s["checkpoint"])
            if c and c["status"] == "open":
                checkpoints.withdraw(f"wb.{st['module']}", st["id"], name=c["name"])
        s.update(status="pending", checkpoint=None, next=None, error=None)


def start(pid: str, sid: str | None = None, *, who: str | None = None, comment: str | None = None, action: str | None = None, _internal: bool = False) -> dict:
    """Run a step (the current one by default): a worker job for rules, platform, proof and agent steps; person steps
    are shaped at once (they only show what earlier steps found) and wait for their checkpoint."""
    st = _load(pid)
    if st.get("closed"):
        raise HTTPException(409, "This work item is closed.")
    if not module_on(st["module"]):                     # P17: switched off here - the work waits until it is back on
        raise _off(st["module"])
    if not _internal and st["status"] in RUNNING and (worker.is_running(pid) or st["status"] == "queued"):
        raise HTTPException(409, "Relay is already working on this item - wait for it, or stop it first.")
    step = _step(st, sid) if sid else current_step(st)
    if step is None:
        raise HTTPException(409, "Every step of this work item is done.")
    pack = PACKS[st["module"]]
    spec = pack.step(st["work"], step["id"])
    if spec is None:
        raise HTTPException(409, "This step is no longer part of the module's journey.")
    act = spec.actions.get(action) if action else None
    if action and not act:
        raise HTTPException(404, "No such action on this step.")

    def prep(s):
        i = next(k for k, x in enumerate(s["steps"]) if x["id"] == step["id"])
        if not act:
            _reset_from(s, i)
            s["steps"][i]["status"] = "queued"
            if comment:
                s["steps"][i]["comment"] = comment
        s["error"] = None
    _mutate(pid, prep)
    kind = (act.kind if act else spec.kind)
    if kind == "person":
        ctx = Ctx(pid, step["id"], who=who, comment=comment)
        try:
            out = spec.run(ctx) if spec.run else {"summary": spec.confirm_text or step["name"]}
        except StepFailed as e:
            _failed(ctx, spec, str(e))
            return _load(pid)
        except Exception as e:  # noqa: BLE001 - shown to the person; the item waits for them
            traceback.print_exc()
            _failed(ctx, spec, f"{e.__class__.__name__}: {str(e)[:400]}")
            return _load(pid)
        _complete(ctx, spec, out)
        return _load(pid)
    if comment:
        store.note(pid, f"Sent back: {step['name']}", comment)
    job = JOB_AGENT if kind == "agent" else JOB_STEP
    token = auth.current.set(None)                      # the item's owner runs it (their AI provider and quota); people are told by checkpoints
    try:
        worker.enqueue(pid, job, step=step["id"], who=who, comment=comment, action=action)
    finally:
        auth.current.reset(token)
    index(_load(pid))
    return _load(pid)


def _begin(ctx: Ctx, spec, action: bool) -> None:
    def f(st):
        s = _step(st, ctx.step_id)
        if not action:
            s.update(status="running", started=_now(), error=None)
        s["runs"] = (s.get("runs") or 0) + 1
        st["status"] = "agent_working" if spec.kind == "agent" else "working"
    _mutate(ctx.id, f)
    ctx.st = _load(ctx.id)


def _run_record(ctx: Ctx, stage: str, seconds: float, ok: bool) -> None:
    """Rules, platform and proof steps are recorded as runs too (model 'rules', no AI cost), so Team & agents shows the
    module's agents at work."""
    def f(st):
        st.setdefault("runs", []).append({"stage": stage, "for": ctx.step_id, "model": "rules", "ok": ok, "turns": 0, "cost_usd": 0.0,
                                          "duration_ms": round(seconds * 1000), "provider": "Relay rules", "provider_kind": "rules", "owner": ctx.owner, "ended": _now()})
    _mutate(ctx.id, f)


def _normalise(out) -> dict:
    out = dict(out or {})
    data = out.get("data")
    if isinstance(data, dict) and isinstance(data.get("rows"), list) and len(data["rows"]) > ROWS_KEPT:
        data = {**data, "rows": data["rows"][:ROWS_KEPT], "truncated": len(data["rows"])}
    return {"summary": str(out.get("summary") or "")[:2000], "data": data, "records": out.get("records"), "counts": out.get("counts") or {},
            "items": [str(x)[:300] for x in (out.get("items") or [])][:12], "ok": out.get("ok") is not False, "next": out.get("next")}


def _queue_evidence(ctx: Ctx, step: dict, out: dict) -> dict:
    data = out.get("data") or {}
    ev = {"summary": out["summary"], "items": out["items"] or ([step["confirm"]] if step.get("confirm") else []), "counts": out["counts"],
          "step": step["id"], "item": {"id": ctx.id, "title": ctx.title, "work": ctx.work, "module": ctx.module}, "confirm": step.get("confirm")}
    if isinstance(data, dict) and data.get("columns") and data.get("rows"):
        ev["columns"] = data["columns"]
        ev["rows"] = data["rows"][:20]
    elif isinstance(data, dict) and data.get("checks"):
        ev["columns"] = ["Check", "Status", "Detail"]
        ev["rows"] = [[c.get("label"), c.get("status"), c.get("detail")] for c in data["checks"][:20]]
    return ev


def _complete(ctx: Ctx, spec, out, action: str | None = None) -> None:
    out = _normalise(out)
    sid = ctx.step_id
    new_ids = [e["id"] for e in ctx.new_evidence]

    def f(st):
        s = _step(st, sid)
        _save_ctx(ctx, st)
        s["evidence"] = ((s.get("evidence") or []) + new_ids)[-80:] if action else new_ids
        s["outputs"] = sorted({o["name"] for o in st["outputs"] if o.get("step") == sid})
        s.update(summary=out["summary"] or s.get("summary") or "", counts=out["counts"] or s.get("counts") or {}, items=out["items"] or s.get("items") or [])
        if out["data"] is not None:
            s["data"] = out["data"]
        if out["records"] is not None:
            s["records"] = _ids(out["records"])
        if action:
            _settle(st)
        else:
            s.update(status="done", ok=out["ok"], next=out["next"], ended=_now(), error=None,
                     seconds=round(_now() - (s.get("started") or _now()), 1))
    _mutate(ctx.id, f)
    if action:
        return
    st = _load(ctx.id)
    step = _step(st, sid)
    needs = bool(step.get("confirm")) and (spec.confirm_if(ctx, out) if spec.confirm_if else True)
    if needs:
        _open_confirm(ctx, spec, step, out)
    elif not out["ok"]:
        _mutate(ctx.id, lambda s: (s.update(status="attention"), _step(s, sid).update(status="error", error=out["summary"] or "This step did not pass.")))
        _tell(st, f"Needs attention: {st['title']}", f"{step['name']}: {out['summary'][:200]}")
    else:
        try:
            advance(ctx.id, sid, jump=out["next"], who=ctx.who)
        except HTTPException as e:
            _mutate(ctx.id, lambda s: s.update(status="attention"))
            worker.app_note(ctx.id, f"{ctx.module}.{sid}", f"The next step could not start: {e.detail}", "error")


def _ids(records: list) -> list[dict]:
    out, seen = [], set()
    for i, r in enumerate(records or []):
        r = dict(r)
        rid = str(r.get("id") or f"r-{i + 1}")
        while rid in seen:
            rid += "x"
        seen.add(rid)
        r["id"] = rid
        out.append(r)
    return out


def _assignee(st: dict, spec) -> str | None:
    owner = (db.project(st["id"]) or {}).get("owner_id")
    if getattr(spec, "approver", False) and st.get("approver") and db.user(st["approver"]):
        return st["approver"]
    return owner


def _open_confirm(ctx: Ctx, spec, step: dict, out: dict) -> None:
    st = _load(ctx.id)
    cp = checkpoints.open(f"wb.{ctx.module}", ctx.id, ctx.module_name, f"{step['name']}: {st['title']}", spec.view, _queue_evidence(ctx, step, out),
                          link=route_of(st) + f"?step={step['id']}", assignee=_assignee(st, spec), agent=spec.agent or "Relay", opened_by="agent")

    def f(s):
        x = _step(s, step["id"])
        x.update(status="waiting", checkpoint=cp["id"])
        s["status"] = "waiting"
    _mutate(ctx.id, f)
    worker.app_note(ctx.id, f"{ctx.module}.{step['id']}", f"{step['name']}: {out['summary'][:240]} Waiting for a person to confirm ({step.get('confirm_label') or step['name']}).", "ok")


def _failed(ctx: Ctx, spec, msg: str) -> None:
    def f(st):
        _save_ctx(ctx, st)
        s = _step(st, ctx.step_id)
        if ctx.action:                                    # a helper failed: the step keeps its state
            _settle(st)
            st["error"] = msg[:1000]
            return
        s.update(status="error", error=msg[:1000], ended=_now())
        st.update(status="error", error=msg[:1000])      # the worker records the job as failed
    _mutate(ctx.id, f)
    worker.app_note(ctx.id, f"{ctx.module}.{ctx.step_id}", msg[:600], "error")
    st = _load(ctx.id)
    _tell(st, f"Needs attention: {st['title']}", msg[:240])


def _tell(st: dict, title: str, body: str) -> None:
    owner = (db.project(st["id"]) or {}).get("owner_id")
    if owner:
        notify.add(owner, "build", title, body, route_of(st))


def advance(pid: str, after: str, *, jump: str | None = None, who: str | None = None) -> None:
    st = _load(pid)
    ids = [s["id"] for s in st["steps"]]
    i = ids.index(after)
    j = ids.index(jump) if jump in ids and ids.index(jump) > i else i + 1

    def skip(s):
        for k in range(i + 1, j):
            s["steps"][k].update(status="skipped", ended=_now())
    if j > i + 1:
        _mutate(pid, skip)
    if j >= len(ids):
        finish(pid, who)
        return
    start(pid, ids[j], who=who, _internal=True)


def finish(pid: str, who: str | None = None) -> None:
    st = _load(pid)
    pack = PACKS[st["module"]]
    if pack.on_done:
        try:
            pack.on_done(Ctx(pid, None, who=who))
        except Exception:  # noqa: BLE001 - a pack's hook never undoes the work
            traceback.print_exc()

    def f(s):
        s["rounds"] = (s.get("rounds") or [])[-59:] + [{"n": len(s.get("rounds") or []) + 1, "ended": _now(), "steps": [
            {k: x.get(k) for k in ("id", "name", "status", "summary", "ok", "counts")} for x in s["steps"]]}]
        s["last_run"] = _now()
        s["status"] = "scheduled" if s.get("schedule") else "done"
        s["finished"] = _now()
        if s.get("schedule") and not s.get("next_run"):
            s["next_run"] = next_run(s["schedule"])
    _mutate(pid, f)
    st = _load(pid)
    db.audit("wb.item.done", pid, {"module": st["module"], "work": st["work"], "rounds": len(st["rounds"])}, who or "agent")
    worker.app_note(pid, f"{st['module']}.done", "Every step is done" + (f"; the next scheduled run is {_when(st.get('next_run'))}." if st.get("schedule") else ". The evidence pack is ready to download."), "ok")
    if not st.get("schedule"):
        _tell(st, f"Done: {st['title']}", "Every step is confirmed; the evidence pack is ready.")


def record_problems(pid: str, sid: str) -> list[str]:
    """What stops a step's records from being confirmed: required columns, then the pack's validator."""
    st = _load(pid)
    step = _step(st, sid)
    spec = PACKS[st["module"]].step(st["work"], sid)
    if not spec or not spec.edit:
        return []
    recs = step.get("records") or []
    probs = [f"Row {i + 1}: {c.label} is needed." for i, r in enumerate(recs) for c in spec.edit.columns if c.required and r.get(c.key) in (None, "")]
    if not probs and spec.edit.validate:
        probs += spec.edit.validate([dict(r) for r in recs], Ctx(pid, sid)) or []
    return probs


def decide(pid: str, sid: str, decision: str, who: str, comment: str | None = None) -> dict:
    """Confirm in place: the same checkpoint the Validation queue shows (signed, timed, audited)."""
    st = _load(pid)
    step = _step(st, sid)
    if step["status"] != "waiting" or not step.get("checkpoint"):
        raise HTTPException(409, "This step is not waiting for a decision.")
    u = db.user(who) or {}
    c = checkpoints.get(step["checkpoint"])
    if not c or not checkpoints.visible(u, c):
        raise HTTPException(403, "This check is for someone else; ask them or an admin to reassign it.")
    if decision == "accept":
        probs = record_problems(pid, sid)
        if probs:
            raise HTTPException(409, "Correct these first: " + "; ".join(probs[:5]))
    checkpoints.decide(step["checkpoint"], "accept" if decision == "accept" else "send_back", who, comment)
    return _load(pid)


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    ev = c.get("evidence") or {}
    pid = c["subject"]
    try:
        st = _load(pid)
    except (KeyError, FileNotFoundError):
        return
    if ev.get("action") == "route":
        _route_decided(pid, c, decision, comment, who)
        return
    sid = ev.get("step")
    step = next((s for s in st["steps"] if s["id"] == sid), None)
    if not step or step.get("checkpoint") != c["id"]:
        return
    pack = PACKS[st["module"]]
    spec = pack.step(st["work"], sid)
    if decision == "accept" and record_problems(pid, sid):
        probs = record_problems(pid, sid)               # accepted in the queue, but the rows cannot run: ask again
        db.audit("wb.step.reopened", pid, {"step": sid, "checkpoint": c["id"], "problems": probs[:5]}, who)
        ctx = Ctx(pid, sid, who=who)
        _open_confirm(ctx, spec, _step(_load(pid), sid), _normalise({"summary": "Accepted in the queue, but the rows have problems - correct them and confirm again.", "items": probs[:6]}))
        return
    if decision == "accept":
        def f(s):
            _step(s, sid).update(status="done", decided_by=who, decided=_now(), comment=(comment or None))
        _mutate(pid, f)
        store.log(pid, {"kind": "user", "text": f"Confirmed: {step['name']}" + (f" - {comment}" if comment else "")})
        db.audit("wb.step.accepted", pid, {"step": sid, "checkpoint": c["id"], "comment": (comment or "")[:200]}, who)
        try:
            advance(pid, sid, jump=step.get("next"), who=who)
        except HTTPException as e:
            _mutate(pid, lambda s: s.update(status="attention"))
            worker.app_note(pid, f"{st['module']}.{sid}", f"Confirmed, but the next step could not start: {e.detail}", "error")
        return
    back = (spec.back_to if spec and spec.back_to else sid)

    def g(s):
        _step(s, sid).update(status="sent_back", decided_by=who, decided=_now(), comment=comment)
    _mutate(pid, g)
    store.log(pid, {"kind": "user", "text": f"Sent back: {step['name']} - {comment}"})
    db.audit("wb.step.sent_back", pid, {"step": sid, "back_to": back, "checkpoint": c["id"], "comment": (comment or "")[:300]}, who)
    try:
        start(pid, back, who=who, comment=comment)
    except HTTPException as e:
        _mutate(pid, lambda s: s.update(status="attention"))
        worker.app_note(pid, f"{st['module']}.{sid}", f"Sent back, but the step could not start again: {e.detail}", "error")


def edit_records(pid: str, sid: str, records: list[dict], who: str) -> dict:
    st = _load(pid)
    step = _step(st, sid)
    spec = PACKS[st["module"]].step(st["work"], sid)
    if not spec or not spec.edit:
        raise HTTPException(409, "This step has nothing to edit.")
    if step["status"] != "waiting":
        raise HTTPException(409, "Only a step waiting for your confirmation can be edited.")
    before = {r["id"]: r for r in step.get("records") or []}
    out, problems = [], []
    allowed = {}
    for col in spec.edit.columns:                     # select options once per column (they may be per item)
        if col.type == "select":
            opts = col.options(Ctx(pid, sid)) if callable(col.options) else col.options
            allowed[col.key] = [o[0] if isinstance(o, (list, tuple)) else o for o in opts]
    for i, r in enumerate(records or []):
        rid = str(r.get("id") or "")
        base = dict(before.get(rid) or {})
        if not rid and not spec.edit.add:
            problems.append("Rows cannot be added here.")
            continue
        for col in spec.edit.columns:
            if col.readonly and rid:
                continue
            v = r.get(col.key)
            if col.type == "number":
                if v in (None, ""):
                    v = None
                else:
                    try:
                        v = float(v)
                        v = int(v) if v.is_integer() else v
                    except (TypeError, ValueError):
                        problems.append(f"Row {i + 1}: {col.label} must be a number.")
                        continue
            elif col.type == "bool":
                v = bool(v) and v not in ("false", "0", "no")
            elif col.type == "select":
                vals = allowed[col.key]
                if v not in vals and v not in (None, ""):
                    problems.append(f"Row {i + 1}: {col.label} must be one of {', '.join(map(str, vals))[:200]}.")
                    continue
            else:
                v = ("" if v is None else str(v)).strip()[:8000 if col.type == "longtext" else 2000]
            if col.required and v in (None, ""):
                problems.append(f"Row {i + 1}: {col.label} is needed.")
            base[col.key] = v
        base["id"] = rid or f"p-{_secrets.token_hex(3)}"
        if not rid:
            base["origin"] = base.get("origin") or "person"
        out.append(base)
    removed = [k for k in before if k not in {r["id"] for r in out}]
    if removed and not spec.edit.remove:
        problems.append("Rows cannot be removed here.")
    if not problems and spec.edit.validate:
        problems += spec.edit.validate(out, Ctx(pid, sid, who=who)) or []
    if problems:
        return {"ok": False, "problems": problems[:40]}
    changed = sum(1 for r in out if before.get(r["id"]) != r) + len(removed)

    def f(s):
        x = _step(s, sid)
        x["records"] = out
        x["edited"] = (x.get("edited") or 0) + changed
    _mutate(pid, f)
    store.log(pid, {"kind": "user", "text": f"Edited {step['name']}: {changed} change(s)"})
    db.audit("wb.step.edited", pid, {"step": sid, "changes": changed, "rows": len(out)}, who)
    return {"ok": True, "problems": [], "changes": changed}


def route(pid: str, kind: str, title: str, detail: str, who: str, step: str | None = None, priority: str = "P3") -> dict:
    """A person proposes a hand-off (a ticket or Self-healing) from the item; a named person approves it first."""
    st = _load(pid)
    if kind not in ("ticket", "heal"):
        raise HTTPException(400, "Hand it to the service desk (ticket) or to Self-healing.")
    label = {"ticket": "Raise a ticket", "heal": "Hand to Self-healing"}[kind]
    cp = checkpoints.open(f"wb.{st['module']}", pid, registry.BY_ID[st["module"]]["name"], f"{label}: {title[:120]}", "text",
                          {"action": "route", "route": kind, "title": title[:200], "detail": detail[:2000], "priority": priority, "step": step, "summary": detail[:300],
                           "items": [f"{label}: {title}", f"Priority {priority}"], "item": {"id": pid, "title": st["title"]}},
                          link=route_of(st), assignee=_assignee(st, Step(approver=True)), agent="Relay", opened_by=who)
    db.audit("wb.route.proposed", pid, {"route": kind, "title": title[:120], "checkpoint": cp["id"]}, who)
    return cp


def _route_decided(pid: str, c: dict, decision: str, comment: str | None, who: str) -> None:
    ev = c.get("evidence") or {}
    if decision != "accept":
        db.audit("wb.route.refused", pid, {"route": ev.get("route"), "comment": (comment or "")[:200]}, who)
        return
    ctx = Ctx(pid, ev.get("step"), who=who)
    if ev["route"] == "heal":
        ctx.heal(ev["title"], ev["detail"])
    else:
        ctx.ticket(ev["title"], ev["detail"], priority=ev.get("priority") or "P3")
    _mutate(pid, lambda st: _save_ctx(ctx, st))


def close(pid: str, who: str, comment: str) -> dict:
    if not (comment or "").strip():
        raise HTTPException(400, "Say why the work item closes.")
    st = _load(pid)
    if worker.is_running(pid) or st["status"] == "queued":
        worker.stop(pid)
    checkpoints.withdraw(f"wb.{st['module']}", pid, who=who)

    def f(s):
        s.update(status="closed", closed=_now(), closed_by=who, close_note=comment.strip()[:500], next_run=None)
    _mutate(pid, f)
    store.note(pid, "Closed", comment)
    db.audit("wb.item.close", pid, {"comment": comment[:200]}, who)
    return _load(pid)


# ================================================================== the worker jobs

async def _job_step(pid: str, args: dict) -> None:
    ctx = Ctx(pid, args.get("step"), who=args.get("who"), comment=args.get("comment"), action=args.get("action"))
    spec = ctx.spec
    act = spec.actions.get(ctx.action) if ctx.action else None
    fn = (act.run if act else spec.run)
    _begin(ctx, act or spec, bool(act))
    t0 = time.time()
    try:
        if fn is None:
            raise StepFailed("This step has nothing to run.")
        out = await asyncio.to_thread(fn, ctx)
    except StepFailed as e:
        _failed(ctx, act or spec, str(e))
        _run_record(ctx, f"{ctx.module}.{ctx.step_id}", time.time() - t0, False)
        return
    except Exception as e:
        traceback.print_exc()
        _failed(ctx, act or spec, f"{e.__class__.__name__}: {str(e)[:400]}")
        _run_record(ctx, f"{ctx.module}.{ctx.step_id}", time.time() - t0, False)
        return
    _run_record(ctx, f"{ctx.module}.{ctx.step_id}", time.time() - t0, True)
    _complete(ctx, spec, out, action=ctx.action)


async def _job_agent(pid: str, args: dict) -> None:
    ctx = Ctx(pid, args.get("step"), who=args.get("who"), comment=args.get("comment"), action=args.get("action"))
    spec = ctx.spec
    act = spec.actions.get(ctx.action) if ctx.action else None
    a = act or spec
    stage = f"{ctx.module}.{ctx.step_id}" + (f".{ctx.action}" if act else "")
    _begin(ctx, a, bool(act))
    try:
        if ctx.pack.guide:
            (ctx.dir / "WORK.md").write_text(ctx.pack.guide, encoding="utf-8")
        body = a.prompt(ctx) if a.prompt else "Do this step as WORK.md describes."
        prompt = wp.frame(stage.upper(), ctx.title, WORK_NAME.get(ctx.work, ctx.work), ctx.module_name, body, ctx.comment)
        worker.app_note(pid, stage, f"Relay is working on {ctx.spec.name}" + (" with your note." if ctx.comment else "."))
        res = await worker.agent(pid, stage, prompt, a.turns, ctx.step_id, system=wp.system(ctx.module_name))
        for attempt in range(worker.FIX_ROUNDS + 1):
            problems = await asyncio.to_thread(a.check, ctx) if a.check else []
            if not problems:
                break
            if attempt == worker.FIX_ROUNDS:
                raise StepFailed(f"What Relay wrote still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
            worker.app_note(pid, stage, f"The check found {len(problems)} problem(s) - Relay is fixing them.", "warn", problems)
            res = await worker.agent(pid, stage, wp.fix(problems), worker.TURNS["fix"], ctx.step_id, resume=res.get("session_id"), system=wp.system(ctx.module_name))
        ctx.st = _load(pid)
        out = await asyncio.to_thread(a.after, ctx, res) if a.after else {"summary": res.get("text") or ""}
    except StepFailed as e:
        _failed(ctx, a, str(e))
        return
    except Exception as e:  # noqa: BLE001 - the agent service, quotas, a provider: shown to the person
        traceback.print_exc()
        _failed(ctx, a, str(e) or e.__class__.__name__)
        return
    _complete(ctx, spec, out, action=ctx.action)


worker.register_job(JOB_STEP, _job_step, status="working", done="Step finished")
worker.register_job(JOB_AGENT, _job_agent, status="agent_working", done="Relay finished a step", llm=True, turns=40, timeout_s=1800)


# ================================================================== scheduled rounds (Run & support)

def _round(pid: str, now: float) -> str:
    """One scheduled round, decided under the item's lock (two passes never start the same round)."""
    with _lock(pid):
        row = db.one("SELECT next_run FROM wb_items WHERE id = ?", (pid,))
        if not row or row["next_run"] is None or row["next_run"] > now:
            return "not due"
        st = _load(pid)
        sched = st.get("schedule")
        if not sched or st.get("closed"):
            _mutate(pid, lambda s: s.update(next_run=None))
            return "off"
        nxt = next_run(sched, now)
        busy = st["status"] in RUNNING or st["status"] == "waiting"
        w = PACKS[st["module"]].work[st["work"]]
        first = _sid(w.schedule_from) if w.schedule_from else st["steps"][0]["id"]

        def f(s):
            s["next_run"] = nxt
            if not busy:
                _reset_from(s, next(k for k, x in enumerate(s["steps"]) if x["id"] == first))
                s["status"] = "new"
        _mutate(pid, f)
    if busy:
        worker.app_note(pid, f"{st['module']}.schedule", "A scheduled run was skipped: the last run is " + ("still running." if st["status"] in RUNNING else "waiting for a person's decision."), "warn")
        return "skipped"
    worker.app_note(pid, f"{st['module']}.schedule", f"Scheduled run ({schedule_text(sched)}).")
    start(pid, first, who=None, _internal=True)
    return "started"


def tick(now: float | None = None) -> list[dict]:
    """One pass: for each module with a pack, every tenant that has it switched on (db.each_tenant(module), P17) starts
    its rounds that are due. Where a module is switched off its rounds wait; the first pass after it is back on runs
    the one that is due, then the schedule carries on from there."""
    now = now or _now()
    out = []
    for mid in sorted(PACKS):
        for t in db.each_tenant(mid):
            for r in db.q("SELECT id FROM wb_items WHERE module = ? AND next_run IS NOT NULL AND next_run <= ? AND closed IS NULL", (mid, now)):
                try:
                    out.append({"tenant": t, "module": mid, "item": r["id"], "result": _round(r["id"], now)})
                except Exception:  # noqa: BLE001 - one item never stops the others
                    traceback.print_exc()
    return out


async def _loop() -> None:
    await asyncio.sleep(15)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(SCHED_EVERY_S)


def ensure_scheduler() -> bool:
    """Start the scheduled rounds once - from any request: on the running loop, or (a sync endpoint, in the thread
    pool) on the worker's event loop. The task gets a clean context: each pass sets its tenant itself."""
    global _sched_task
    import contextvars
    with _LOCKS_GUARD:
        if _sched_task is not None and not _sched_task.done():
            return False
        try:
            loop = asyncio.get_running_loop()
            _sched_task = loop.create_task(_loop(), context=contextvars.Context())
            return True
        except RuntimeError:
            pass
        loop = worker._loop
        if loop is None or loop.is_closed():
            return False
        import concurrent.futures
        fut: concurrent.futures.Future = concurrent.futures.Future()

        def _start():
            try:
                t = loop.create_task(_loop())
                t.add_done_callback(lambda _t: fut.done() or fut.set_result(None))
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)
        loop.call_soon_threadsafe(_start, context=contextvars.Context())
        _sched_task = fut
        return True


# ================================================================== views for the screens, Home, Team & agents

def _names() -> dict:
    return {r["id"]: r["name"] for r in db.q("SELECT id, name FROM users")}


def public_item(st: dict, u: dict | None = None, detail: bool = False) -> dict:
    p = db.project(st["id"]) or {}
    cur = current_step(st)
    names = _names()
    pack = PACKS.get(st["module"])
    m = registry.BY_ID.get(st["module"], {})
    out = {"id": st["id"], "module": st["module"], "module_name": m.get("name"), "work": st["work"], "work_name": WORK_NAME.get(st["work"], st["work"]),
           "title": st["title"], "brief": st.get("brief") or "", "platform": st.get("platform"),
           "platform_label": pack.platforms[st["platform"]].label if pack and st.get("platform") in pack.platforms else st.get("platform"),
           "status": status_of(st), "status_label": STATUS_LABEL.get(status_of(st), status_of(st)), "error": st.get("error"),
           "step": cur["id"] if cur else None, "step_name": cur["name"] if cur else None, "step_index": st["steps"].index(cur) if cur else len(st["steps"]),
           "steps_total": len(st["steps"]), "owner_id": p.get("owner_id"), "owner": names.get(p.get("owner_id")), "approver_id": st.get("approver"),
           "approver": names.get(st.get("approver")), "visibility": p.get("visibility") or "private", "team_id": p.get("team_id"),
           "created": st.get("created"), "updated": st.get("updated"), "route": route_of(st), "schedule": st.get("schedule"), "schedule_text": schedule_text(st.get("schedule")),
           "next_run": st.get("next_run"), "last_run": st.get("last_run"), "rounds": len(st.get("rounds") or []), "parent": st.get("parent"), "closed": st.get("closed")}
    if u is not None:
        level, via = auth.access(u, p if p else None)
        out["access"] = {"level": level, "via": via, "can_edit": bool(auth.can_project(u, "edit", p) and auth.is_dev(u)) if p else False, "can_share": level == "owner"}
    if not detail:
        return out
    cps = {c["id"]: c for c in (checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE subject = ? AND kind = ? ORDER BY created", (st["id"], f"wb.{st['module']}")))}
    conns = []
    for cid in st.get("connections") or []:
        try:
            c = connectors._row(cid)
            conns.append({"id": c["id"], "name": c["name"], "label": connectors.KINDS.get(c["kind"], {}).get("label", c["kind"]), "scope": c.get("scope") or "read", "status": c.get("status")})
        except connectors.ConnectorError:
            conns.append({"id": cid, "name": "(removed)", "label": "", "scope": "", "status": "removed"})
    steps = []
    for s in st["steps"]:
        spec = pack.step(st["work"], s["id"]) if pack else None
        cp = cps.get(s.get("checkpoint")) if s.get("checkpoint") else None
        x = {**s, "kind_label": KIND_LABEL.get(s["kind"], s["kind"]), "status_label": STEP_LABEL.get(s["status"], s["status"]),
             "decided_by_name": names.get(s.get("decided_by")),
             "edit": {"columns": [_col_public(c, st) for c in spec.edit.columns], "add": spec.edit.add, "remove": spec.edit.remove, "label": spec.edit.label} if spec and spec.edit else None,
             "actions": [{"id": k, "label": a.label, "kind": a.kind, "help": a.help} for k, a in (spec.actions.items() if spec else [])],
             "checkpoint": {**{k: cp.get(k) for k in ("id", "status", "assignee_id", "created", "decided", "decided_by", "comment")}, "assignee": names.get(cp.get("assignee_id")),
                            "can_decide": bool(u and checkpoints.visible(u, cp) and cp["status"] == "open")} if cp else None}
        steps.append(x)
    act = []
    try:
        act = [{k: e.get(k) for k in ("ts", "kind", "stage", "level", "text", "tool", "who")} for e in store.activity(st["id"], 0, 3000)[-40:]]
    except (KeyError, FileNotFoundError):
        pass
    decisions = [{"id": c["id"], "name": c["name"], "status": c["status"], "decided_by": names.get(c.get("decided_by")), "decided": c.get("decided"), "comment": c.get("comment"),
                  "seconds": c.get("seconds"), "created": c["created"], "route": (c.get("evidence") or {}).get("route")} for c in cps.values()]
    out.update(steps=steps, connections=conns, files=st.get("files") or [], scope={k: v for k, v in (st.get("scope") or {}).items() if not k.startswith("_")},
               evidence=st.get("evidence") or [], outputs=st.get("outputs") or [], handoffs=(st.get("data") or {}).get("_handoffs") or [], activity=act, decisions=decisions,
               history=[{k: r.get(k) for k in ("n", "ended", "steps")} for r in (st.get("rounds") or [])[-12:]],
               running=st["status"] in RUNNING, position=worker.position(st["id"]) if st["status"] == "queued" else 0,
               lineage=_lineage_of(st), observe=_observe_overlap(st), pack_ready=st["status"] in ("done", "scheduled") and bool(st.get("rounds")),
               close_note=st.get("close_note"))
    return out


def _col_public(c: Column, st: dict) -> dict:
    opts = c.options
    if callable(opts):
        try:
            opts = opts(Ctx(st["id"]))
        except Exception:  # noqa: BLE001
            opts = ()
    return {"key": c.key, "label": c.label, "type": c.type, "options": [list(o) if isinstance(o, (list, tuple)) else [o, o] for o in opts], "help": c.help,
            "required": c.required, "readonly": c.readonly}


def _lineage_of(st: dict) -> list[dict]:
    ids = (st.get("data") or {}).get("_lineage") or []
    if not ids:
        return []
    rows = db.q(f"SELECT id, kind, label, name, system FROM lineage_nodes WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
    return [{"id": r["id"], "kind": r["kind"], "label": r["label"] or r["name"], "system": r["system"]} for r in rows]


def _observe_overlap(st: dict) -> list[dict]:
    """Assets Data observability also watches (the same lineage table), with any open incident - one link each."""
    ids = (st.get("data") or {}).get("_lineage") or []
    if not ids or "observe_assets" not in db.tables():
        return []
    out = []
    for a in db.q(f"SELECT id, label, name, node_id FROM observe_assets WHERE node_id IN ({','.join('?' * len(ids))})", tuple(ids)):
        inc = db.one("SELECT id, title FROM observe_incidents WHERE asset_id = ? AND status IN ('open', 'proposed', 'actioned') ORDER BY last_seen DESC LIMIT 1", (a["id"],))
        out.append({"asset": a["id"], "label": a["label"] or a["name"], "incident": inc["id"] if inc else None, "incident_title": inc["title"] if inc else None,
                    "link": f"#/observability?open={inc['id']}" if inc else "#/observability"})
    return out


def items_for(u: dict, module: str | None = None, work: str | None = None, status: str | None = None, limit: int = 500) -> list[dict]:
    sql, args = "SELECT id FROM wb_items WHERE 1 = 1", []
    if module:
        sql += " AND module = ?"; args.append(module)
    if work:
        sql += " AND work = ?"; args.append(work)
    sql += " ORDER BY updated DESC LIMIT ?"; args.append(limit)
    ids = [r["id"] for r in db.q(sql, tuple(args))]
    access = auth.access_map(u, ids)
    out = []
    for pid in ids:
        if pid not in access:
            continue
        try:
            st = _load(pid)
        except (KeyError, FileNotFoundError, ValueError):
            continue
        it = public_item(st, u)
        if status == "open" and it["status"] not in OPEN:
            continue
        if status == "waiting" and it["status"] != "waiting":
            continue
        if status == "done" and it["status"] not in ("done", "scheduled"):
            continue
        out.append(it)
    return out


def _team_subject(pid: str) -> dict:
    st = _load(pid)
    cur = current_step(st) or {}
    m = registry.BY_ID.get(st["module"], {})
    return {"module": m.get("name") or st["module"], "link": route_of(st), "agent": cur.get("agent") or "Relay agent",
            "doing": f"{cur.get('name') or 'A step'} ({WORK_NAME.get(st['work'], st['work'])})"}


def _home_inflight(u: dict | None) -> list[dict]:
    ensure_scheduler()                                  # Home is the first page after a restart: scheduled rounds resume
    rows = []
    for mid in PACKS:
        if not module_on(mid):
            continue
        r = db.q("SELECT id, status FROM wb_items WHERE module = ? AND closed IS NULL", (mid,))
        if u is not None:
            vis = auth.access_map(u, [x["id"] for x in r])
            r = [x for x in r if x["id"] in vis]
        m = registry.BY_ID[mid]
        rows.append({"id": f"wb-{mid}", "name": m.get("short") or m["name"], "n": sum(1 for x in r if x["status"] in OPEN), "running": sum(1 for x in r if x["status"] in RUNNING),
                     "waiting": sum(1 for x in r if x["status"] == "waiting"), "route": f"#/m/{mid}"})
    return rows


try:                                            # Team & agents and Home name and count workbench items (their hooks)
    from . import home as _home, team as _team
    if hasattr(_team, "SUBJECTS"):
        _team.SUBJECTS[KIND] = _team_subject
    if hasattr(_home, "INFLIGHT") and _home_inflight not in _home.INFLIGHT:
        _home.INFLIGHT.append(_home_inflight)
except ImportError:  # pragma: no cover
    pass


# ================================================================== the evidence pack (hand-over)

def evidence_pack(pid: str) -> bytes:
    st = _load(pid)
    d = folder(pid)
    names = _names()
    cps = [checkpoints._public(r) for r in db.q("SELECT * FROM checkpoints WHERE subject = ? ORDER BY created", (pid,))]
    lines = [f"# {st['title']}", "", f"{registry.BY_ID[st['module']]['name']} - {WORK_NAME.get(st['work'], st['work'])} - work item {pid}", "",
             f"Owner: {names.get((db.project(pid) or {}).get('owner_id'), '-')}", f"Created: {_when(st.get('created'))}", f"Status: {STATUS_LABEL.get(st['status'], st['status'])}", "",
             "## The brief", "", st.get("brief") or "(none)", "", "## Steps", ""]
    for i, s in enumerate(st["steps"], 1):
        lines += [f"### {i}. {s['name']} - {STEP_LABEL.get(s['status'], s['status'])} ({KIND_LABEL.get(s['kind'], s['kind'])}{', ' + s['agent'] if s.get('agent') else ''})", "",
                  s.get("summary") or "", ""]
        if s.get("decided_by"):
            lines += [f"Confirmed by {names.get(s['decided_by'], s['decided_by'])} on {_when(s.get('decided'))}" + (f": \"{s['comment']}\"" if s.get("comment") else ""), ""]
        for eid in s.get("evidence") or []:
            e = next((x for x in st.get("evidence") or [] if x["id"] == eid), None)
            if e:
                lines.append(f"- evidence: {e['label']} {e['file']}")
        lines.append("")
    lines += ["## Decisions", ""] + [f"- {c['name']}: {c['status'].replace('_', ' ')} by {names.get(c.get('decided_by'), c.get('decided_by') or '-')} {_when(c.get('decided'))}"
                                     + (f" - \"{c['comment']}\"" if c.get("comment") else "") for c in cps] + [""]
    hs = (st.get("data") or {}).get("_handoffs") or []
    if hs:
        lines += ["## Hand-offs", ""] + [f"- {h['kind']}: {h['label']} - {h.get('status')}" for h in hs] + [""]
    summary = "\n".join(lines)
    doc = None
    try:
        doc = handover_document(st, cps, names)
    except Exception:  # noqa: BLE001 - the pack goes out without the document; the reason is in the summary
        traceback.print_exc()
        summary += "\n\n(The hand-over document could not be built; everything it would hold is in this summary and the evidence files.)\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("summary.md", summary)
        z.writestr("decisions.json", _dumps(cps))
        z.writestr("steps.json", _dumps([{k: s.get(k) for k in ("id", "name", "kind", "status", "summary", "counts", "ok", "evidence", "outputs", "decided_by", "decided", "comment")} for s in st["steps"]]))
        for sub in ("evidence", "outputs", "handover"):
            for f in sorted((d / sub).rglob("*")) if (d / sub).exists() else []:
                if f.is_file():
                    z.write(f, f.relative_to(d).as_posix())
        if (d / "activity.jsonl").exists():
            z.write(d / "activity.jsonl", "activity.jsonl")
        if (d / "request.md").exists():
            z.write(d / "request.md", "request.md")
    db.audit("wb.pack.download", pid, {"steps": len(st["steps"]), "document": bool(doc)}, auth.who())
    return buf.getvalue()


def handover_document(st: dict, cps: list[dict], names: dict) -> str | None:
    """A hand-over document (Word) through the P11 docs engine: every table sourced from a record in the folder."""
    from genbi_kit.docs import build as docs_build

    from . import studio
    d = folder(st["id"])
    hd = d / "handover"
    (d / "sources").mkdir(exist_ok=True)
    hd.mkdir(exist_ok=True)
    studio.write_brand(d, "relay")
    steps = [[s["name"], KIND_LABEL.get(s["kind"], s["kind"]), STEP_LABEL.get(s["status"], s["status"]), names.get(s.get("decided_by"), "") or "-", (s.get("summary") or "")[:160]] for s in st["steps"]]
    decided = [[c["name"][:80], c["status"].replace("_", " "), names.get(c.get("decided_by"), c.get("decided_by") or "-"), _when(c.get("decided")), (c.get("comment") or "")[:120]] for c in cps]
    ev = [[e["label"][:90], e["step"], e["file"]] for e in st.get("evidence") or []][:120]
    (d / "sources" / "handover.json").write_text(_dumps({"steps": steps, "decisions": decided, "evidence": ev}), encoding="utf-8")
    spec = {"kind": "doc", "title": f"Hand-over: {st['title']}", "subtitle": f"{registry.BY_ID[st['module']]['name']} - {WORK_NAME.get(st['work'], st['work'])}",
            "audience": "the owner and the people who run it next", "sections": [
                {"title": "What was done", "blocks": [{"kind": "paragraph", "text": "Every step below ran in Relay and was confirmed by the person named next to it. The evidence files are in the evidence pack, one per check."},
                                                      {"kind": "table", "table": {"columns": ["Step", "Done by", "Status", "Confirmed by", "Result"], "rows": steps, "source": "record:handover#steps", "caption": "The journey, step by step"}}]},
                {"title": "Decisions", "blocks": [{"kind": "table", "table": {"columns": ["Decision", "Outcome", "By", "When", "Comment"], "rows": decided or [["-", "-", "-", "-", "-"]], "source": "record:handover#decisions", "caption": "Every checkpoint, signed and timed"}}]},
                {"title": "Evidence", "blocks": [{"kind": "table", "table": {"columns": ["Evidence", "Step", "File"], "rows": ev or [["-", "-", "-"]], "source": "record:handover#evidence", "caption": "Where each piece of evidence is"}}]}]}
    import yaml
    (hd / "doc.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
    info = docs_build.build(hd / "doc.yaml", hd, workspace=store.root(), name="handover")
    return (info.get("files") or {}).get("docx")


# ================================================================== API

class Decide(BaseModel):
    decision: str
    comment: str | None = None


class Records(BaseModel):
    records: list[dict]


class RunStep(BaseModel):
    comment: str | None = None
    action: str | None = None


class ScheduleIn(BaseModel):
    every: str
    at: str | None = None
    weekday: int | None = None
    day: int | str | None = None              # monthly: 1-28 or "last"
    tz: str | None = None


class RouteIn(BaseModel):
    route: str
    title: str
    detail: str = ""
    step: str | None = None
    priority: str = "P3"


class Visibility(BaseModel):
    visibility: str
    team_id: str | None = None


class Comment(BaseModel):
    comment: str | None = None


class Hook(BaseModel):
    files: dict[str, str] = {}
    text: str = ""


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    ensure_scheduler()
    return u


def _pack(mid: str) -> Pack:
    p = PACKS.get(mid)
    if not p:
        raise HTTPException(404, "This module has no workbench pack yet.")
    if not module_on(mid):
        raise _off(mid)
    return p


def _item(mid: str, iid: str, u: dict, action: str = "view") -> dict:
    _pack(mid)
    try:
        st = _load(iid)
    except (KeyError, FileNotFoundError, ValueError):
        raise HTTPException(404, "No such work item.") from None
    if st["module"] != mid:
        raise HTTPException(404, "No such work item.")
    p = db.project(iid)
    if not auth.can_project(u, "view", p):
        raise HTTPException(404, "No such work item.")
    if action != "view" and not (auth.can_project(u, "edit", p) and auth.is_dev(u)):
        raise HTTPException(403, "You can look at this work item; only its owner, or a builder it is shared with, can change it.")
    return st


def pack_public(pack: Pack, u: dict) -> dict:
    m = registry.BY_ID[pack.module]
    work = {}
    for w, spec in pack.work.items():
        fields = []
        for f in spec.fields:
            opts = f.options
            if callable(opts):
                try:
                    opts = opts(u)
                except Exception:  # noqa: BLE001
                    opts = ()
            fields.append({"key": f.key, "label": f.label, "type": f.type, "options": [list(o) if isinstance(o, (list, tuple)) else [o, o] for o in opts], "help": f.help,
                           "required": f.required, "default": f.default})
        work[w] = {"name": WORK_NAME.get(w, w), "title": spec.title, "fields": fields, "platforms": list(spec.platforms or pack.platforms), "needs_source": spec.needs_source, "sources": spec.sources,
                   "steps": [{"id": s.id, "name": s.name, "kind": s.kind, "kind_label": KIND_LABEL[s.kind], "text": s.text, "confirm": s.confirm_text, "confirm_label": s.confirm_label,
                              "agent": s.agent, "approver": s.approver} for s in pack.steps(w)]}
    return {"module": pack.module, "name": m["name"], "short": m.get("short") or m["name"], "work": work, "order": [w for w in m["work"] if w in work] or list(work),
            "platforms": {k: p.describe() for k, p in pack.platforms.items()}, "lineage": pack.lineage, "api": f"/api/m/{pack.module}"}


@router.get("/api/workbench/packs")
def api_packs():
    u = _u()
    role = registry.role_of(u)
    out = []
    for k, p in PACKS.items():
        if role in registry.BY_ID[k]["roles"] or auth.is_admin(u):
            state = module_state(k)                     # P17: 'off' (switched off here) and 'locked' (not in the edition)
            out.append({"module": k, "name": registry.BY_ID[k]["name"], "work": list(p.work), "route": f"#/m/{k}", "api": f"/api/m/{k}",
                        "state": state, "on": state not in (None, "locked", "off")})
    return {"packs": out}


@router.get("/api/workbench/summary")
def api_summary():
    u = _u()
    rows = _home_inflight(u)
    return {"modules": rows, "open": sum(r["n"] for r in rows), "waiting": sum(r["waiting"] for r in rows), "running": sum(r["running"] for r in rows)}


@router.get("/api/m/{mid}/overview")
def api_overview(mid: str, work: str | None = None):
    u = _u()
    pack = _pack(mid)
    m = registry.BY_ID[mid]
    w = work if work in pack.work else next((x for x in m["work"] if x in pack.work), next(iter(pack.work)))
    items = items_for(u, mid)
    counts = {k: {"total": sum(1 for i in items if i["work"] == k), "open": sum(1 for i in items if i["work"] == k and i["status"] in OPEN),
                  "waiting": sum(1 for i in items if i["work"] == k and i["status"] == "waiting")} for k in pack.work}
    cards = []
    if pack.cards:
        try:
            cards = pack.cards(u) or []
        except Exception:  # noqa: BLE001 - a pack's card never breaks the page
            traceback.print_exc()
    return {"module": registry.public(m, registry.brand()["edition"], registry.switched_on()), "pack": pack_public(pack, u), "work_type": w, "plan": registry.plan_for(m, w),
            "confirm": registry.confirm_for(m, w), "items": [i for i in items if i["work"] == w], "counts": counts, "can_create": auth.is_dev(u), "cards": cards,
            "rules": ["One AI job at a time, every step logged", "Nothing reaches a live system without a named approval",
                      "Credentials by name only, kept in the secrets store", "Proven before it ships"]}


@router.get("/api/m/{mid}/items")
def api_items(mid: str, work: str | None = None, status: str | None = None):
    u = _u()
    _pack(mid)
    return {"items": items_for(u, mid, work, status)}


@router.post("/api/m/{mid}/items")
async def api_create(mid: str, work: str = Form(...), title: str = Form(...), brief: str = Form(""), platform: str = Form(""), connections: str = Form("[]"),
                     scope: str = Form("{}"), approver: str = Form(""), visibility: str = Form("private"), team_id: str = Form(""),
                     files: list[UploadFile] = File(default=[])):
    u = _u()
    _pack(mid)
    if not auth.is_dev(u):
        raise HTTPException(403, "Only a builder or an admin can start work here.")
    try:
        cons = json.loads(connections or "[]")
        sc = json.loads(scope or "{}")
    except ValueError as e:
        raise HTTPException(400, "The form did not arrive whole; try again.") from e
    data = [(f.filename, await f.read()) for f in files if f and f.filename]
    st = await asyncio.to_thread(create, mid, work, title, who=u["id"], brief=brief, platform=platform or None, connections=cons, scope=sc, approver=approver or None,
                                 visibility=visibility, team_id=team_id or None, files=data)
    return public_item(st, u)


@router.get("/api/m/{mid}/items/{iid}")
def api_item(mid: str, iid: str):
    u = _u()
    return public_item(_item(mid, iid, u), u, detail=True)


@router.post("/api/m/{mid}/items/{iid}/files")
async def api_files(mid: str, iid: str, files: list[UploadFile] = File(...)):
    u = _u()
    _item(mid, iid, u, "edit")
    data = [(f.filename, await f.read()) for f in files if f and f.filename]
    added = await asyncio.to_thread(save_files, iid, data, u["id"])
    return {"added": added}


@router.post("/api/m/{mid}/items/{iid}/steps/{sid}/run")
def api_run(mid: str, iid: str, sid: str, body: RunStep | None = None):
    u = _u()
    _item(mid, iid, u, "edit")
    db.audit("wb.step.run", iid, {"step": sid, "action": body.action if body else None}, u["id"])
    st = start(iid, sid, who=u["id"], comment=(body.comment if body else None), action=(body.action if body else None))
    return public_item(st, u, detail=True)


@router.put("/api/m/{mid}/items/{iid}/steps/{sid}/records")
def api_records(mid: str, iid: str, sid: str, body: Records):
    u = _u()
    _item(mid, iid, u, "edit")
    r = edit_records(iid, sid, body.records, u["id"])
    return {**r, "item": public_item(_load(iid), u, detail=True)}


@router.post("/api/m/{mid}/items/{iid}/steps/{sid}/decide")
def api_decide(mid: str, iid: str, sid: str, body: Decide):
    """Confirm in place: anyone who can open the item and whom the checkpoint is for (the queue's own rule) - the
    named approver included, even with view access only."""
    u = _u()
    _item(mid, iid, u)
    if body.decision not in ("accept", "send_back"):
        raise HTTPException(400, "Decide accept or send_back.")
    if body.decision == "send_back" and not (body.comment or "").strip():
        raise HTTPException(400, "Say what to change when you send it back.")
    return public_item(decide(iid, sid, body.decision, u["id"], body.comment), u, detail=True)


@router.get("/api/m/{mid}/items/{iid}/evidence/{eid}")
def api_evidence(mid: str, iid: str, eid: str):
    u = _u()
    st = _item(mid, iid, u)
    e = next((x for x in st.get("evidence") or [] if x["id"] == eid), None)
    if not e:
        raise HTTPException(404, "No such evidence.")
    p = folder(iid) / e["file"]
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise HTTPException(404, "The evidence file is missing.") from err


@router.get("/api/m/{mid}/items/{iid}/outputs/{name}")
def api_output(mid: str, iid: str, name: str):
    u = _u()
    st = _item(mid, iid, u)
    if not any(o["name"] == name for o in st.get("outputs") or []):
        raise HTTPException(404, "No such output.")
    p = folder(iid) / "outputs" / name
    if not p.is_file():
        raise HTTPException(404, "The output file is missing.")
    return Response(p.read_bytes(), media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/m/{mid}/items/{iid}/evidence-pack.zip")
def api_pack(mid: str, iid: str):
    u = _u()
    st = _item(mid, iid, u)
    if st["status"] not in ("done", "scheduled") or not st.get("rounds"):
        raise HTTPException(409, "The evidence pack is ready at hand-over: when every step is done and confirmed.")
    data = evidence_pack(iid)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{iid}-evidence.zip"'})


@router.post("/api/m/{mid}/items/{iid}/schedule")
def api_schedule(mid: str, iid: str, body: ScheduleIn):
    u = _u()
    _item(mid, iid, u, "edit")
    s = check_schedule(body.model_dump())

    def f(st):
        st.update(schedule=s, next_run=next_run(s))
        if st["status"] == "done":
            st["status"] = "scheduled"
    _mutate(iid, f)
    db.audit("wb.schedule.set", iid, s, u["id"])
    store.log(iid, {"kind": "user", "text": f"Schedule: {schedule_text(s)}"})
    return public_item(_load(iid), u, detail=True)


@router.delete("/api/m/{mid}/items/{iid}/schedule")
def api_unschedule(mid: str, iid: str):
    u = _u()
    _item(mid, iid, u, "edit")

    def f(st):
        st.update(schedule=None, next_run=None)
        if st["status"] == "scheduled":
            st["status"] = "done"
    _mutate(iid, f)
    db.audit("wb.schedule.off", iid, {}, u["id"])
    store.log(iid, {"kind": "user", "text": "Schedule switched off"})
    return public_item(_load(iid), u, detail=True)


@router.post("/api/m/{mid}/items/{iid}/route")
def api_route(mid: str, iid: str, body: RouteIn):
    u = _u()
    _item(mid, iid, u, "edit")
    if not body.title.strip():
        raise HTTPException(400, "Say what the hand-off is about.")
    return {"checkpoint": route(iid, body.route, body.title.strip(), body.detail, u["id"], body.step, body.priority)}


@router.post("/api/m/{mid}/items/{iid}/visibility")
def api_visibility(mid: str, iid: str, body: Visibility):
    u = _u()
    _item(mid, iid, u)
    p = db.project(iid)
    if not (p["owner_id"] == u["id"] or auth.is_admin(u)):
        raise HTTPException(403, "Only the owner or an admin can change who sees this work item.")
    if body.visibility not in ("private", "team", "org"):
        raise HTTPException(400, "Only me, my team or the organisation.")
    team = body.team_id or p.get("team_id")
    if body.visibility == "team" and not (team and db.one("SELECT 1 FROM teams WHERE id = ?", (team,))):
        raise HTTPException(400, "Pick the team.")
    db.run("UPDATE projects SET visibility = ?, team_id = ? WHERE id = ?", (body.visibility, team, iid))
    db.audit("wb.item.visibility", iid, {"visibility": body.visibility, "team": team}, u["id"])
    store.log(iid, {"kind": "user", "text": f"Visibility: {body.visibility}"})
    return public_item(_load(iid), u, detail=True)


@router.post("/api/m/{mid}/items/{iid}/stop")
def api_stop(mid: str, iid: str):
    u = _u()
    _item(mid, iid, u, "edit")
    stopped = worker.stop(iid)
    db.audit("wb.item.stop", iid, {"stopped": stopped}, u["id"])
    return public_item(_load(iid), u, detail=True)


@router.post("/api/m/{mid}/items/{iid}/close")
def api_close(mid: str, iid: str, body: Comment):
    u = _u()
    _item(mid, iid, u, "edit")
    return public_item(close(iid, u["id"], body.comment or ""), u, detail=True)


@router.post("/api/m/{mid}/items/{iid}/steps/{sid}/hook")
def api_hook(mid: str, iid: str, sid: str, body: Hook):
    """Tests only (D2D_TEST_HOOKS=1): stands in for an agent run - writes the files the agent would have written, then
    the step's own check and after run as they would after a real run."""
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u = _u()
    st = _item(mid, iid, u, "edit")
    d = folder(iid)
    for name, text in body.files.items():
        p = (d / name).resolve()
        if d.resolve() not in p.parents:
            raise HTTPException(400, "Inside the item's folder only.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    ctx = Ctx(iid, sid, who=u["id"])
    spec = ctx.spec
    problems = spec.check(ctx) if spec.check else []
    if problems:
        return {"ok": False, "problems": problems}
    out = spec.after(ctx, {"text": body.text}) if spec.after else {"summary": body.text}
    _mutate(iid, lambda s: (_step(s, sid).update(status="running", started=_now()), s.update(status="working")))
    _complete(ctx, spec, out)
    return {"ok": True, "item": public_item(_load(iid), u, detail=True), "status": st["status"]}
