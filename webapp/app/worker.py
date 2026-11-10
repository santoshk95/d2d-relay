"""The one sequential worker: every job (an agent stage or the Power BI build) runs alone, in order.

plan -> (user confirms KPIs) -> build -> (user reviews) -> revise ... -> (user approves) -> pbi

After every agent run the app runs the review gates (genbi_kit/gates.py). If a gate fails, the same Claude session
is resumed with the problems (up to FIX_ROUNDS times) — still one agent, in turn. A version whose gates fail cannot
be approved; publishing writes the project to a staging folder, runs the gates on those exact files and only then
moves it into powerbi/. Custom visuals Claude built for a version (built, tested, in use) go to the visual library.
"""
import asyncio
import csv
import json
import os
import shutil
import time
import traceback
import zipfile
from pathlib import Path

import httpx

from genbi_kit import KIT, catalog, library_dir, use_project, visuals_dir
from genbi_kit import data as data_mod
from genbi_kit import datagen, daxcheck, definition, gates, prototype, report_builder, vfactory
from genbi_kit import validate as checks
from genbi_kit.profile import profile

from . import connectors, db, doctor, errors, instances, notify, prompts, providers, store, usage

AGENT_URL = os.environ.get("AGENT_URL", "http://agent:8090")
CATALOG = Path(os.environ.get("MODELS_FILE", "/opt/genbi/config/models.json"))
FALLBACK = {"default": "sonnet", "models": [{"id": "sonnet", "label": "Sonnet (latest)", "family": "sonnet", "latest": True},
                                            {"id": "opus", "label": "Opus (latest)", "family": "opus", "latest": True}]}


def house_models() -> list[dict]:
    """Relay's own models (config/house-models.json) as the app shows them: id, label, group and note. The model that
    serves one (its target) is the agent's business and is never passed on."""
    try:
        ms = json.loads(CATALOG.with_name("house-models.json").read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return [{k: v for k, v in m.items() if k != "target"} for m in ms if m.get("id") and m.get("target")]


def model_catalog() -> dict:
    """The models this install offers: Relay's own first, then the Claude models this login can use
    (config/models.json, written by agent/probe_models.py)."""
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        data = data if data.get("models") else FALLBACK
    except (OSError, ValueError):
        data = FALLBACK
    house = house_models()
    return {**data, "models": house + [m for m in data["models"] if m["id"] not in {h["id"] for h in house}]} if house else data


def model_labels() -> dict:
    return {m["id"]: m["label"] for m in model_catalog()["models"]}


DEFAULT_MODEL = os.environ.get("AGENT_MODEL") or model_catalog().get("default") or "sonnet"
HOST_DIR = os.environ.get("HOST_PROJECTS_DIR", "").rstrip("\\/")
FIX_ROUNDS = 2
TURNS = {"data": 80, "plan": 50, "build": 200, "revise": 100, "fix": 50}
TIMEOUT_S = {"data": 2400, "plan": 1800, "build": 5400, "revise": 3600, "fix": 1800}
VISUAL_TURNS, VISUAL_S = 60, 1800      # more room for each custom visual a run has to build
STATUS = {"extract": "extracting", "data": "generating_data", "plan": "planning", "build": "building", "revise": "revising", "pbi": "building_pbi"}
RUNNING = {"queued", *STATUS.values()}
# Build-plan v2 (P10+): phase modules register their own job kinds; the worker runs them in the same lane, one at a
# time, with the same queue, retries, notifications and activity log.
HANDLERS: dict = {}


def register_job(kind: str, handler, *, status: str, done: str, llm: bool = False, turns: int = 80, timeout_s: int = 2400) -> None:
    """`handler(pid, args)` is awaited by the worker for jobs of this kind; `status` is the project status while it
    runs, `done` the notification text when it finishes; `llm` kinds count against quotas and get turns / timeouts."""
    HANDLERS[kind] = handler
    STATUS[kind] = status
    RUNNING.add(status)
    DONE_TEXT[kind] = done
    if llm:
        LLM_KINDS.add(kind)
        TURNS[kind] = turns
        TIMEOUT_S[kind] = timeout_s
ZIP_DATA_LIMIT = 100 * 1024 * 1024     # CSVs go into the download only up to this size

LANE = "build"                          # this worker's lane; Ask D (phase 5) gets its own 'chat' lane
class _Current(dict):
    """The job running now (pid, kind, task, started, job, owner, tenant) as the rest of the app sees it: only a
    request or pass in the job's own tenant sees which job it is — everyone else sees an idle mapping (P17: the
    agent is shared by every tenant; what it works on is not)."""

    def _mine(self) -> bool:
        return dict.__len__(self) > 0 and (dict.get(self, "tenant") or db.PLATFORM) == db.tenant()

    def get(self, key, default=None):
        return dict.get(self, key, default) if self._mine() else default

    def __getitem__(self, key):
        if not self._mine():
            raise KeyError(key)
        return dict.__getitem__(self, key)

    def __contains__(self, key) -> bool:
        return self._mine() and dict.__contains__(self, key)

    def __bool__(self) -> bool:
        return self._mine()

    def __len__(self) -> int:
        return dict.__len__(self) if self._mine() else 0

    def __iter__(self):
        return dict.__iter__(self) if self._mine() else iter(())

    def items(self):
        return dict.items(self) if self._mine() else {}.items()

    def keys(self):
        return dict.keys(self) if self._mine() else {}.keys()

    def values(self):
        return dict.values(self) if self._mine() else {}.values()


current = _Current()                    # the job running now, seen per tenant (see _Current)
wake: asyncio.Event | None = None       # set when a job is queued, so the worker starts it at once (made per loop)
_loop: asyncio.AbstractEventLoop | None = None
POLL_S = 5                              # safety net: the worker also looks at the queue this often


class AgentError(Exception):
    def __init__(self, text: str, session_id: str | None = None):
        super().__init__(text)
        self.session_id = session_id          # the run's Claude session, so a backup provider can continue it


def app_note(pid: str, stage: str, text: str, level: str = "info", items: list | None = None) -> None:
    store.log(pid, {"kind": "app", "stage": stage, "level": level, "text": text, **({"items": items} if items else {})})


def _wake() -> None:
    """Wake the worker; safe from request threads (sync endpoints run in a thread pool)."""
    loop, event = _loop, wake
    if loop is not None and event is not None and not loop.is_closed():
        loop.call_soon_threadsafe(event.set)


def enqueue(pid: str, kind: str, **args) -> dict:
    """Queue a job in the database (it survives a restart). It runs with the project's Claude model as chosen
    when the request was made; a newer request replaces whatever the project still had waiting."""
    from . import auth
    if kind in LLM_KINDS:
        usage.check(auth.who(), (db.project(pid) or {}).get("team_id"))     # QuotaError -> 429 (main.py)
    model = store.load(pid).get("model") or DEFAULT_MODEL
    jid = db.add_job(pid, kind, args, model, auth.who(), LANE)
    db.skip_queued(pid, keep=jid)
    st = store.update(pid, status="queued", job={**args, "kind": kind, "id": jid, "model": model}, error=None)
    _wake()
    return st


LLM_KINDS = {"plan", "build", "revise", "data"}
# phase 8: the other CLIs run in their own agent images (docker compose --profile runners)
RUNNER_URLS = {"codex": "http://agent-codex:8090", "gemini": "http://agent-gemini:8090", "antigravity": "http://agent-antigravity:8090",
               **json.loads(os.environ.get("D2D_RUNNER_URLS") or "{}")}
DONE_TEXT = {"plan": "Plan ready", "build": "Prototype built", "revise": "Changes applied", "pbi": "Power BI report published",
             "data": "Demo data ready", "extract": "Warehouse data pulled"}


FRESH_S = 30                            # enqueue adds the row before the folder points at it: a row this young is looked at again


def _valid(row: dict) -> bool:
    """A queued row still stands for its project's queued job; one that was stopped or replaced is skipped. A row
    younger than FRESH_S whose folder does not point at it yet (or is being saved) is left for the next look, never
    skipped: otherwise a poll between enqueue's add_job and its folder save lost the job for good (consolidation)."""
    fresh = time.time() - float(row.get("created") or 0) < FRESH_S
    try:
        st = store.load(row["pid"])
    except (KeyError, FileNotFoundError, ValueError):
        if not fresh:
            db.set_job(row["id"], "skipped", "project is gone")
        return False
    if st["status"] == "queued" and (st.get("job") or {}).get("id") == row["id"]:
        return True
    if not fresh:
        db.set_job(row["id"], "skipped")
    return False


def _waiting_rows() -> list[dict]:
    """Every tenant's waiting jobs in this lane, oldest first (one agent serves them all, one job at a time), each
    with its tenant."""
    rows = []
    for t in db.each_tenant():
        rows += [{**r, "tenant": t} for r in db.queued(LANE) if _valid(r)]
    return sorted(rows, key=lambda r: (r["created"], r["id"]))


def waiting() -> int:
    return len(_waiting_rows())


def busy_owner() -> str | None:
    """Whose job the agent runs now, whatever the tenant (the workspace reaper must not stop it)."""
    return dict.get(current, "owner")


def position(pid: str) -> int:
    """How many jobs run before this project's queued job (0 = it is next or running)."""
    t = db.tenant()
    ahead = 1 if dict.__len__(current) and (dict.get(current, "pid"), dict.get(current, "tenant")) != (pid, t) else 0
    for row in _waiting_rows():
        if row["pid"] == pid and row["tenant"] == t:
            return ahead
        ahead += 1
    return 0


def stop(pid: str) -> bool:
    """Stop the running job of this project, or take its queued job out of the queue."""
    if current.get("pid") == pid:                # only a job of the current tenant (see _Current)
        current["task"].cancel()
        return True
    st = store.load(pid)
    if st["status"] == "queued":
        jid = (st.get("job") or {}).get("id")
        if jid:
            db.set_job(jid, "stopped", "stopped before it started")
        store.update(pid, status="error", error="Stopped before it started. Press Retry to run this step.")
        return True
    return False


def recover() -> None:
    """After a restart: a job that was mid-run cannot be resumed, so it is marked for Retry; queued jobs stay queued
    and run in order (the durable queue). Projects queued by an older version of the app (no job row) or left in a
    running state are marked for Retry, as before."""
    for _t in db.each_tenant():                  # P17: every tenant's queue and folders
        for row in db.interrupted():
            db.set_job(row["id"], "error", "interrupted by a restart")
        for p in store.all_projects():
            if p["status"] not in RUNNING:
                continue
            jid = (store.load(p["id"]).get("job") or {}).get("id")
            row = db.job(jid) if jid else None
            if p["status"] == "queued" and row and row["state"] == "queued":
                continue
            store.update(p["id"], status="error", error="Interrupted by a restart. Press Retry to run this step again.")


def _finish(jid: str, pid: str) -> None:
    try:
        st = store.load(pid)
    except (KeyError, FileNotFoundError, ValueError):
        db.set_job(jid, "error", "project is gone")
        return
    err = st.get("error") if st.get("status") == "error" else None
    state = ("stopped" if err and err.startswith("Stopped") else "error") if err else "done"
    db.set_job(jid, state, err)
    row = db.job(jid) or {}
    if state != "stopped" and row.get("owner_id"):
        from . import agents                   # every kind of folder opens its own screen (a start, a change request …), not #/p/
        here = agents.place(pid, st)
        name = st.get("name") or here["module"]
        if state == "done":
            notify.add(row["owner_id"], "build", f"{DONE_TEXT.get(row['kind'], 'Finished')}: {name}",
                       "Your turn: review it." if st.get("status") in ("awaiting_review", "awaiting_kpis") else "", here["link"])
        else:
            notify.add(row["owner_id"], "build", f"Needs attention: {name}", (err or "")[:300], here["link"])


async def worker_loop() -> None:
    global _loop, wake
    wake = asyncio.Event()                # bound to this loop (a restart in the same process makes a new one)
    _loop = asyncio.get_running_loop()
    while True:
        try:
            wake.clear()
            rows = _waiting_rows()
            if not rows:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=POLL_S)
                except TimeoutError:
                    pass
                continue
            if doctor.holding():                 # Relay Doctor is restarting the app or running its fix: the queue waits, nothing is lost
                await asyncio.sleep(POLL_S)
                continue
            row = rows[0]
            pid, kind, args = row["pid"], row["kind"], json.loads(row["args"] or "{}")
            with db.use(row["tenant"]):          # the job runs in its own tenant: schema, folders, secrets, library
                db.set_job(row["id"], "running")
                task = asyncio.create_task(_run(pid, kind, args))     # the task keeps this context
                dict.update(current, pid=pid, kind=kind, model=row["model"], task=task, started=time.time(), job=row["id"],
                            owner=row["owner_id"], tenant=row["tenant"])
                from . import monitor
                monitor.log("job.start", job=row["id"], pid=pid, kind=kind, model=row["model"], owner=row["owner_id"], tenant=row["tenant"])
                await asyncio.wait({task})
                _finish(row["id"], pid)
                done = db.job(row["id"]) or {}
                monitor.log("job.end", "info" if done.get("state") == "done" else "warn", job=row["id"], pid=pid, kind=kind,
                            state=done.get("state"), seconds=round(time.time() - dict.get(current, "started", time.time())),
                            error=(done.get("error") or "")[:200] or None, tenant=row["tenant"])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the worker alive
            traceback.print_exc()
            await asyncio.sleep(1)
        finally:
            dict.clear(current)


def policy(st: dict) -> str:
    """What the user allows for new custom visuals: ask (propose in the plan), auto, never. A report of Power BI's
    built-in visuals only never gets a new custom visual."""
    if st.get("visuals_mode") == "builtin":
        return "never"
    return st.get("custom_visuals") or "ask"


def chosen_visuals(d: Path) -> list[dict]:
    """plan.yaml `custom_visuals` (proposals with the user's decision)."""
    try:
        items = definition.load(d / "plan.yaml").get("custom_visuals") or []
    except Exception:  # noqa: BLE001 - no plan, no proposals
        return []
    return [v for v in items if isinstance(v, dict) and v.get("name")]


async def _run(pid: str, kind: str, args: dict) -> None:
    errors.CONTEXT.set({"where": f"job {kind}", "kind": kind, "pid": pid, "tenant": db.tenant()})   # a crash in this task names the job
    use_project(store.project_dir(pid))          # this project's own custom visuals join the catalog
    store.update(pid, status=STATUS[kind])
    try:
        if kind == "extract":
            await _extract(pid)
        elif kind == "data":
            await _data(pid, args.get("feedback"))
        elif kind == "plan":
            await _plan(pid, args.get("feedback"), args.get("attachments"))
        elif kind == "build":
            chosen = chosen_visuals(store.project_dir(pid))
            mode = store.load(pid).get("visuals_mode")
            await _version(pid, "build", prompts.build(chosen, mode), None,
                           visuals=0 if mode == "builtin" else sum(v.get("decision") == "generate" for v in chosen))
        elif kind == "revise":
            st = store.load(pid)
            v = len(st["versions"])
            prompt = prompts.revise(v, args["feedback"], policy(st), st.get("visuals_mode")) + prompts.attached(args.get("attachments"))
            await _version(pid, "revise", prompt, args["feedback"], args.get("attachments"),
                           visuals=1 if args.get("visual") or policy(st) == "auto" else 0)
        elif kind == "pbi":
            await _pbi(pid, args["version"])
        elif kind in HANDLERS:
            await HANDLERS[kind](pid, args)
        else:
            raise AgentError(f"Unknown job kind: {kind}")
    except asyncio.CancelledError:
        app_note(pid, kind, "Stopped by the user.", "error")
        store.update(pid, status="error", error="Stopped. Press Retry to run this step again.")
    except Exception as e:  # noqa: BLE001 - shown to the user
        traceback.print_exc()
        msg = str(e) or e.__class__.__name__
        if isinstance(e, httpx.TransportError):
            msg = f"Could not reach the agent service at {AGENT_URL} ({e.__class__.__name__}). Is the agent container running?"
        app_note(pid, kind, msg, "error")
        store.update(pid, status="error", error=msg)


def refresh_guide(d: Path) -> None:
    """The guide (CLAUDE.md, loaded by Claude Code automatically; AGENTS.md / GEMINI.md for the other CLIs) belongs to
    the app, not the project: every run gets the current one — the guide for this kind of folder (app/guides.py: a
    dashboard gets GENBI.md, its worked example and the team's metrics; a start, a studio item, an RFP, a case, a
    change request, a converted report each get their own)."""
    from . import guides
    guides.write(d)


async def agent(pid: str, stage: str, prompt: str, turns: int, target: str, resume: str | None = None,
                extra_s: int = 0, system: str | None = None, env: dict | None = None) -> dict:
    """One Claude Code run in the project folder; every event goes to the activity log as it happens.
    `target` is what the run works towards ("plan", "v1", "v2" …), so its tokens and cost add up per version.
    `system` replaces the dashboard system prompt for phase modules whose subject is not a dashboard (P10+);
    `env` adds per-run variables for the toolkit (P16: the repository credential `genbi repo` uses) — never logged."""
    refresh_guide(store.project_dir(pid))
    model = (store.load(pid).get("job") or {}).get("model") or DEFAULT_MODEL
    owner = _owner(pid)
    timeout = TIMEOUT_S["fix" if resume else stage] + extra_s
    try:
        usage.check(owner, (db.project(pid) or {}).get("team_id"))
    except usage.QuotaError as e:
        raise AgentError(str(e)) from e
    try:
        cfg = providers.run_config(owner, model, timeout)
    except providers.ProviderError as e:
        raise AgentError(str(e)) from e
    failed, result = None, {}
    try:
        result = await _stream(pid, stage, prompt, cfg, turns, timeout, resume, owner, system, env)
        if result.get("ok") is False:
            failed = result.get("text") or ""
    except AgentError as e:
        failed, result = str(e), {"session_id": e.session_id} if e.session_id else {}
    if failed is not None and providers.is_failover_error(failed):
        backup = providers.backup_kind(owner)
        try:
            bcfg = providers.run_config(owner, model, timeout, kind=backup) if backup else None
        except providers.ProviderError:
            bcfg = None
        if bcfg:
            app_note(pid, stage, f"{cfg['provider']} failed ({failed[:160]}). Trying once more on the backup: "
                                 f"{bcfg['provider']}.", "warn")
            db.audit("ai.fallback", pid, {"from": cfg["kind"], "to": bcfg["kind"], "error": failed[:300]}, owner)
            result = await _stream(pid, stage, prompt, bcfg, turns, timeout, result.get("session_id") or resume, owner, system, env)
            cfg, failed = {**bcfg, "fallback": True}, None
    if failed is not None and "kind" not in result:
        raise AgentError(failed)
    st = store.load(pid)
    st.setdefault("runs", []).append({"stage": stage, "for": target, "model": result.get("model") or cfg["model"], "fix": bool(resume),   # a resumed run is a fix round
                                      "ok": result.get("ok"), "subtype": result.get("subtype"),
                                      "turns": result.get("turns"), "cost_usd": result.get("cost_usd"),
                                      "duration_ms": result.get("duration_ms"), "usage": result.get("usage"),
                                      "models": result.get("models"), "session_id": result.get("session_id"),
                                      "provider": cfg["provider"], "provider_kind": cfg["kind"], "owner": owner,
                                      "fallback": bool(cfg.get("fallback")), "ended": time.time()})
    store.save(st)
    usage.record_run(pid, st["runs"][-1], len(st["runs"]) - 1)
    return result


def _owner(pid: str) -> str | None:
    """Whose run this is: the person who queued the job, else the dashboard's owner (their AI provider is used)."""
    jid = (store.load(pid).get("job") or {}).get("id")
    row = db.job(jid) if jid else None
    if row and row.get("owner_id"):
        return row["owner_id"]
    p = db.project(pid)
    return p["owner_id"] if p else None


async def _stream(pid: str, stage: str, prompt: str, cfg: dict, turns: int, timeout: int, resume: str | None,
                  owner: str | None, system: str | None = None, env: dict | None = None) -> dict:
    """One run on the agent service: every event goes to the activity log as it happens."""
    runner = cfg.get("runner") or "claude-code"
    tenant_env = {}
    if db.tenant() != db.PLATFORM:              # P17: the run sees its own tenant's visual library (same path in the agent)
        lib = library_dir()
        lib.mkdir(parents=True, exist_ok=True)
        tenant_env["GENBI_LIBRARY"] = str(lib)
    payload = {"workdir": store.rel(pid), "prompt": prompt, "system": system or prompts.SYSTEM, "model": cfg["model"], "max_turns": turns,
               "timeout_s": timeout, "resume": resume, "lane": LANE, "runner": runner,
               "env": {**cfg["env"], **tenant_env, **{k: v for k, v in (env or {}).items() if v}}}
    url = RUNNER_URLS[runner] if runner in RUNNER_URLS else await instances.agent_url(owner)
    result: dict = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, read=None)) as client:
        async with client.stream("POST", f"{url}/runs", json=payload) as r:
            if r.status_code != 200:
                raise AgentError(f"Agent service refused the run: {(await r.aread()).decode(errors='replace')[:300]}")
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                store.log(pid, {"stage": stage, **ev})
                if ev.get("session_id"):
                    result["session_id"] = ev["session_id"]
                if ev["kind"] == "start" and ev.get("model"):
                    result["model"] = ev["model"]          # the exact model behind the alias
                if ev["kind"] == "done":
                    result.update(ev)
                elif ev["kind"] == "error":
                    raise AgentError(ev["text"], result.get("session_id"))
    if "kind" not in result:
        raise AgentError("The agent stopped without finishing its run.", result.get("session_id"))
    return result


# ---------------------------------------------------------------- plan

def _check_plan(d: Path) -> list[str]:
    path = d / "plan.yaml"
    if not path.exists():
        return ["plan.yaml was not written"]
    try:
        raw = definition.load(path)
    except Exception as e:  # noqa: BLE001
        return [f"plan.yaml does not parse: {str(e).splitlines()[0]}"]
    return checks.plan(raw) if isinstance(raw, dict) else ["plan.yaml must be a mapping"]


def _sync_data(d: Path) -> list[str]:
    """Generated demo data must match its recipe: when a later stage changed datagen.yaml after the last
    generation, generate (and profile) it again. Returns the recipe's problems, if any."""
    recipe, manifest = d / "datagen.yaml", d / "data" / datagen.MANIFEST
    if not recipe.exists() or (manifest.exists() and manifest.stat().st_mtime >= recipe.stat().st_mtime):
        return []
    return _check_data(d)[0]


def refresh_files(pid: str) -> list[dict]:
    """project.json `files`: every CSV in data/, marked when the demo data generator made it; for generated demo
    data also its tables (rows, columns) and story, which a later stage may have changed."""
    d = store.project_dir(pid)
    made = datagen.generated_files(d)
    csvs = sorted((d / "data").glob("*.csv"))
    files = [{"name": f.name, "bytes": f.stat().st_size, **({"generated": True} if f.name in made else {})} for f in csvs]
    extracts = connectors.manifest(d)
    files += [{"name": f.name, "bytes": f.stat().st_size, "warehouse": extracts.get(f.name, {}).get("object"),
               "rows": extracts.get(f.name, {}).get("rows"), "extracted": extracts.get(f.name, {}).get("extracted")}
              for f in sorted((d / "data").glob("*.parquet"))]
    update: dict = {"files": files}
    st = store.load(pid)
    if st.get("data") and (d / "datagen.yaml").exists():
        try:
            when = json.loads((d / "data" / datagen.MANIFEST).read_text(encoding="utf-8")).get("when")
        except (OSError, ValueError):
            when = None
        if when and st.get("data_generated") and when > st["data_generated"] + 1:
            update.update(data_summary="", data_regenerated=when)   # Claude's data notes were about the earlier data
        update["data_generated"] = when
        tables = []
        for f in csvs:
            with open(f, encoding="utf-8-sig", newline="") as fh:
                header = next(csv.reader(fh), [])
                rows = sum(1 for _ in fh)
            tables.append({"table": f.stem, "file": f.name, "rows": rows, "columns": header, "generated": f.name in made})
        update.update(data_tables=tables, data_rows=sum(t["rows"] for t in tables))
        try:
            update["data_story"] = [datagen.story_text(s) for s in datagen.load(d / "datagen.yaml").get("story") or []]
        except (datagen.RecipeError, ValueError, OSError):
            pass
    store.update(pid, **update)
    return files


def _check_data(d: Path) -> tuple[list[str], dict | None]:
    """Generate the recipe again (the same seed gives the same files, so this is what the report will use) and
    profile it. Returns (problems, summary)."""
    if not (d / "datagen.yaml").exists():
        return ["datagen.yaml was not written — write the recipe (CLAUDE.md, Demo data) and run `genbi datagen`"], None
    try:
        summary = datagen.run(d)
    except (datagen.RecipeError, ValueError, OSError) as e:
        return [f"datagen.yaml: {str(e)[:1500]}"], None
    problems = [f"{t['table']}: no rows were generated" for t in summary["tables"] if not t["rows"]]
    if not summary["story"]:
        problems.append("datagen.yaml has no `story` — list the 3-5 things the data was made to show")
    profile(d)
    return problems, summary


async def _extract(pid: str) -> None:
    """EXTRACT: pull the warehouse tables the person picked into data/*.parquet with their own login, profile them,
    then plan — the same path as uploaded CSVs from there on."""
    d = store.project_dir(pid)
    st = store.load(pid)
    spec = st.get("warehouse") or {}
    owner = _owner(pid)
    try:
        c = connectors.connection(spec["connection_id"], owner)
    except (connectors.ConnectorError, KeyError) as e:
        raise RuntimeError("The warehouse connection of this dashboard is not one of its owner's connections.") from e
    app_note(pid, "extract", f"Pulling {len(spec['tables'])} table(s) from {c['name']} with your own login.")
    done = []
    for t in spec["tables"]:
        try:
            info = await asyncio.to_thread(connectors.extract, c, t["object"], t["alias"], d, owner)
        except connectors.Reconsent as e:
            raise RuntimeError(f"{e} Open Connections, sign in to {c['name']} again, then press Retry.") from e
        except connectors.ConnectorError as e:
            raise RuntimeError(str(e)) from e
        done.append(info)
        app_note(pid, "extract", f"{t['object']}: {info['rows']:,} rows → data/{info['file']} ({info['seconds']}s)", "ok")
    await asyncio.to_thread(profile, d)
    refresh_files(pid)
    label = (connectors.KINDS.get(c["kind"]) or {}).get("label") or c["kind"]
    store.note(pid, "Warehouse tables", f"Pulled from {label} ({c['name']}) with the user's own "
               "login. In definition.yaml use `extract: <file>` for these tables (CLAUDE.md, Warehouse tables); the app "
               + ("writes the native Power BI connector.\n" if c["kind"] in report_builder.NATIVE_KINDS else
                  f"refreshes these files ({label} has no Power BI connector, so the Power BI project reads them).\n")
               + "\n".join(f"- data/{i['file']} ← {i['object']} ({i['rows']:,} rows)" for i in done))
    app_note(pid, "extract", f"Data ready: {len(done)} table(s), {sum(i['rows'] for i in done):,} rows.", "ok")
    if not store.load(pid).get("plan_rounds"):
        enqueue(pid, "plan")
    else:
        store.update(pid, status="awaiting_review" if store.load(pid).get("versions") else "awaiting_kpis", job=None)


KIND_LABEL = {k: v["label"] for k, v in connectors.KINDS.items()}


async def _data(pid: str, feedback: str | None = None) -> None:
    """DATA: Claude designs a demo dataset for the business the user described (datagen.yaml); the generator
    writes it to data/. Then the plan stage follows, as for uploaded data."""
    d = store.project_dir(pid)
    st = store.load(pid)
    spec = st.get("data") or {}
    app_note(pid, "data", "Changing the demo data." if feedback else
             "Designing demo data for your business: tables, keys, trends and a few stories to find.")
    uploaded = [f["name"] for f in st.get("files") or [] if not f.get("generated")]
    res = await agent(pid, "data", prompts.data(spec, uploaded, feedback), TURNS["data"], "data")
    for attempt in range(FIX_ROUNDS + 1):
        problems, summary = await asyncio.to_thread(_check_data, d)
        if not problems:
            break
        if attempt == FIX_ROUNDS:
            raise RuntimeError(f"The demo data recipe still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        app_note(pid, "data", f"The check found {len(problems)} problem(s) in datagen.yaml — D2D is fixing them.",
                 "warn", problems)
        res = await agent(pid, "data", prompts.fix(problems, "data"), TURNS["fix"], "data", resume=res.get("session_id"))
    refresh_files(pid)
    st = store.load(pid)
    st.update(data_summary=res.get("text") or "", data_rounds=st.get("data_rounds", 0) + 1)
    store.save(st)
    store.note(pid, "Demo data generated", "From datagen.yaml (`genbi datagen` makes the same files again):\n"
               + "\n".join(f"- {t['file']} ({t['rows']:,} rows)" for t in st.get("data_tables") or [])
               + ("\n\nWhat the data was made to show:\n" + "\n".join(f"- {s}" for s in summary["story"])
                  if summary["story"] else ""))
    app_note(pid, "data", f"Demo data ready: {len(summary['tables'])} tables, {summary['rows']:,} rows ("
             + ", ".join(f"{t['table']} {t['rows']:,}" for t in summary["tables"]) + ").", "ok",
             [f"Story: {s}" for s in summary["story"]])
    if not st.get("plan_rounds"):
        enqueue(pid, "plan")            # first time: plan the report on the new data (its own job, in turn)
    else:
        store.update(pid, status="awaiting_kpis", job=None)


async def _plan(pid: str, feedback: str | None, attachments: list[dict] | None = None) -> None:
    d = store.project_dir(pid)
    st = store.load(pid)
    app_note(pid, "plan", "Revising the plan with your feedback." if feedback
             else "Reading your data and request to plan the report.")
    prompt = (prompts.PLAN_REVISE.format(feedback=feedback) + prompts.attached(attachments) if feedback
              else prompts.plan(st.get("images") or [], policy(st), generated=(d / "datagen.yaml").exists(),
                                visuals=st.get("visuals_mode")))
    res = await agent(pid, "plan", prompt, TURNS["plan"], "plan")
    for attempt in range(FIX_ROUNDS + 1):
        problems = await asyncio.to_thread(lambda: _sync_data(d) + _check_plan(d))
        if not problems:
            break
        if attempt == FIX_ROUNDS:
            raise RuntimeError(f"plan.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
        app_note(pid, "plan", f"The check found {len(problems)} problem(s) in plan.yaml — D2D is fixing them.", "warn", problems)
        res = await agent(pid, "plan", prompts.fix(problems, "plan"), TURNS["fix"], "plan", resume=res.get("session_id"))
    plan = definition.load(d / "plan.yaml")
    refresh_files(pid)                  # the plan stage may have changed generated demo data
    st = store.load(pid)
    st.update(status="awaiting_kpis", job=None, plan_summary=res.get("text") or "", plan_rounds=st.get("plan_rounds", 0) + 1)
    store.save(st)
    app_note(pid, "plan", f"Plan ready: {len(plan.get('kpis') or [])} KPIs on {len(plan.get('pages') or [])} pages. "
             "Waiting for you to confirm the KPIs.", "ok")


# ---------------------------------------------------------------- build / revise

def _check_definition(d: Path, pid: str, rel: str = "definition.yaml",
                      proto: str = "prototype/index.html", dax: dict | None = None) -> tuple[list[str], dict | None, list[dict]]:
    """Validate a definition, render its prototype and run every review gate. Returns (problems, info, gates):
    problems go to Claude in a fix round; info is None when the definition is not usable at all."""
    path = d / rel
    if not path.exists():
        msg = f"{rel} was not written"
        return [msg], None, [gates.gate("definition", [msg])]
    try:
        raw = definition.load(path)
    except Exception as e:  # noqa: BLE001
        msg = f"{rel} does not parse: {str(e).splitlines()[0]}"
        return [msg], None, [gates.gate("definition", [msg])]
    errors, dd = checks.definition_errors(raw, d, check_sql=False)
    if not errors and not dd["pages"]:
        errors = [f"{rel} has no pages yet — add the pages of the plan"]
    if errors:
        return errors, None, [gates.gate("definition", errors)]
    con = data_mod.connect(d, dd)
    n = sum(len(p["visuals"]) for p in dd["pages"])
    found = [gates.gate("definition", ok=f"{len(dd['tables'])} tables, {len(dd['measures'])} measures, {n} visuals"),
             gates.gate("prototype", prototype.render(dd, con, d / proto), ok=f"{n} visuals drawn from your data"),
             gates.custom_visuals(d, dd)]
    if dax is None:
        dax = _dax_check(d, dd)
    found += gates.dax_gates(dax)
    found += gates.file_gates(d, dd, catalog(), visuals_dir(), con, dax=dax)
    found.append(_display(pid, proto))
    found = gates.ordered(found)
    problems = gates.problems(found) + [f"Power BI's DAX disagrees with the prototype SQL (make them agree — fix "
                                        f"whichever is wrong): {x}" for x in dax.get("differences") or []]
    return problems, {"report": dd["name"], "pages": [p["name"] for p in dd["pages"]], "visuals": n,
                      "measures": len(dd["measures"]), "tables": len(dd["tables"]),
                      "custom_visuals": _custom_used(dd), "dax": dax}, found


def _display(pid: str, rel: str) -> dict:
    """The display gate runs in the agent container, which has the headless browser."""
    try:
        r = httpx.post(f"{AGENT_URL}/display-check", json={"workdir": store.rel(pid), "file": rel}, timeout=240)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001 - a check that cannot run never breaks the version
        return gates.gate("display", skip=f"the browser check could not run ({e.__class__.__name__})")


def _dax_check(d: Path, dd: dict) -> dict:
    """Every measure and visual query evaluated by Power BI's engine (the DAX checker on this PC). Problems go back to
    Claude like any other; without the checker the version is marked as not checked."""
    if not daxcheck.available():
        return {"checked": False, "reason": "the DAX checker is not running on this PC"}
    try:
        return daxcheck.summary(daxcheck.run(d, dd, catalog()))
    except Exception as e:  # noqa: BLE001 - a check that cannot run never breaks the version
        return {"checked": False, "reason": (str(e).splitlines() or [e.__class__.__name__])[0][:300]}


def _custom_used(dd: dict) -> list[dict]:
    """The custom visuals (library or this project's) a definition uses."""
    cat, used = catalog(), {v["type"] for p in dd["pages"] for v in p["visuals"]}
    return [{"name": t, "title": cat[t]["displayName"], "origin": cat[t]["origin"], "version": cat[t]["version"]}
            for t in sorted(used) if t in cat and cat[t].get("origin") in ("project", "library")]


def _promote(pid: str, d: Path, info: dict, problems: list[str]) -> list[str]:
    """Add the custom visuals this version uses — built, tested, without open problems — to the visual library."""
    st, notes = store.load(pid), []
    state = {v["name"]: v for v in vfactory.status(d)}
    for cv in info.get("custom_visuals") or []:
        v = state.get(cv["name"])
        if cv["origin"] != "project" or not v or v["stale"] or not v["tested"] or any(cv["name"] in p for p in problems):
            continue
        try:
            how, rec = vfactory.promote(d, cv["name"], {"project": pid, "project_name": st.get("name"), "report": info["report"]})
        except (vfactory.VisualError, OSError) as e:
            notes.append(f"{cv['title']} was not added: {e}")
            continue
        owner = db.project(pid) or {}             # the library entry belongs to the dashboard's owner and team
        db.add_library(cv["name"], owner.get("owner_id") or db.ADMIN_ID, owner.get("team_id"))
        if how == "added":
            db.audit("library.add", cv["name"], {"project": pid}, owner.get("owner_id"))
        if how != "unchanged":
            notes.append(f"{how} {rec['title']} v{rec['version']}")
    return notes


async def _version(pid: str, stage: str, prompt: str, feedback: str | None, attachments: list[dict] | None = None,
                   visuals: int = 0) -> None:
    d = store.project_dir(pid)
    target = f"v{len(store.load(pid)['versions']) + 1}"
    app_note(pid, stage, "Building the model, the measures and the report pages." if stage == "build"
             else "Applying your changes.")
    if visuals:
        app_note(pid, stage, f"This run may build {visuals} new custom visual{'s' if visuals > 1 else ''} "
                 "(code, compile, browser test) — it takes longer.")
    res = await agent(pid, stage, prompt, TURNS[stage] + VISUAL_TURNS * visuals, target, extra_s=VISUAL_S * visuals)
    for attempt in range(FIX_ROUNDS + 1):
        app_note(pid, stage, "Running the review gates: definition, prototype, Power Query, data, DAX in Power BI's "
                             "engine, report files, consistency, best practices, accessibility, display…")
        drift = await asyncio.to_thread(_sync_data, d)
        problems, info, found = await asyncio.to_thread(_check_definition, d, pid)
        problems = drift + problems
        if not problems or attempt == FIX_ROUNDS:
            break
        names = ", ".join(g["name"] for g in gates.failed(found)) or "Values match the prototype"
        app_note(pid, stage, f"Review gates not passed ({names}): {len(problems)} problem(s) — D2D is fixing them.",
                 "warn", problems)
        res = await agent(pid, stage, prompts.fix(problems, "definition"), TURNS["fix"], target, resume=res.get("session_id"))
    if info is None:
        raise RuntimeError(f"D2D could not produce a valid report definition ({len(problems)} problem(s)): "
                           + "; ".join(problems[:4]))
    refresh_files(pid)                  # a change request may have regenerated the demo data
    st = store.load(pid)
    v = len(st["versions"]) + 1
    vdir = d / "versions" / f"v{v}"
    vdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(d / "definition.yaml", vdir / "definition.yaml")
    shutil.copy2(d / "prototype" / "index.html", vdir / "prototype.html")
    dax = info.pop("dax", None) or {}
    (vdir / "dax.json").write_text(json.dumps(dax), encoding="utf-8")
    (vdir / "gates.json").write_text(json.dumps(found), encoding="utf-8")
    info["dax"] = _dax_brief(dax)
    info["gates"] = gates.compact(found)
    st["versions"].append({"v": v, "created": time.time(), "summary": res.get("text") or "", "feedback": feedback,
                           "attachments": [a["path"] for a in attachments or []], "problems": problems, **info})
    st.update(status="awaiting_review", job=None, approved=None)
    store.save(st)
    added = await asyncio.to_thread(_promote, pid, d, info, problems)
    if added:
        app_note(pid, stage, "Visual library: " + "; ".join(added) + " — later reports can use it.", "ok")
    bad, passed = gates.failed(found), sum(g["status"] in ("pass", "warn") for g in found)
    if bad:
        app_note(pid, stage, f"Prototype v{v} is ready, but {len(bad)} review gate(s) still fail "
                 f"({', '.join(g['name'] for g in bad)}) — it can be approved once they pass: ask Relay to fix them.",
                 "warn", gates.problems(found))
    elif problems:
        app_note(pid, stage, f"Prototype v{v} is ready and passed its review gates; {len(problems)} value(s) in Power BI "
                 "differ from the prototype — look at them before approving.", "warn", problems)
    else:
        app_note(pid, stage, f"Prototype v{v} is ready: {len(info['pages'])} pages, {info['visuals']} visuals, "
                 f"{info['measures']} measures — {passed} review gates passed. Review it, then approve or ask for "
                 "changes.", "ok")


def _dax_brief(dax: dict) -> dict:
    """What project.json keeps of a DAX check (the values stay in versions/vN/dax.json)."""
    return {k: dax.get(k) for k in ("checked", "reason", "engine", "measures", "visuals", "sampled", "compared")} | \
           {"problems": len(dax.get("problems") or []), "differences": len(dax.get("differences") or [])}


def check_version(pid: str, v: int) -> list[dict]:
    """Run the review gates again for a saved version (one made before the gates existed, or to re-check it).
    The DAX check this version already has is reused; the prototype is drawn into a scratch file."""
    d = store.project_dir(pid)
    use_project(d)
    vdir = d / "versions" / f"v{v}"
    dax = None
    if (vdir / "dax.json").exists():
        saved = json.loads((vdir / "dax.json").read_text(encoding="utf-8"))
        dax = saved if saved.get("checked") else None
    scratch = f".genbi/gates-v{v}.html"
    (d / ".genbi").mkdir(exist_ok=True)
    try:
        _, info, found = _check_definition(d, pid, f"versions/v{v}/definition.yaml", scratch, dax)
    finally:
        (d / scratch).unlink(missing_ok=True)
    if info and info.get("dax", {}).get("checked") and not (vdir / "dax.json").exists():
        (vdir / "dax.json").write_text(json.dumps(info["dax"]), encoding="utf-8")
    _save_gates(pid, d, v, found, (info or {}).get("dax"))
    bad = gates.failed(found)
    app_note(pid, "check", f"Review gates for v{v}: " + (f"{len(bad)} failed ({', '.join(g['name'] for g in bad)})" if bad
             else f"all {sum(g['status'] != 'skip' for g in found)} passed"), "warn" if bad else "ok",
             gates.problems(found) or None)
    return found


# ---------------------------------------------------------------- Power BI

README = """{name} — Power BI project (PBIP) built by D2D

Open "{name}.pbip" in Power BI Desktop, then press Refresh.

The model reads the CSVs from the folder in the DataFolder parameter:
    {folder}
If you move the project to another computer, put the CSVs in a folder there and change the parameter
(Home > Transform data > Edit parameters > DataFolder), then Refresh.{zip_note}

The report uses D2D custom visuals; they are embedded in the project (no import needed).{custom_note}
Prototype.html is the approved browser prototype (v{v}).
DAX check.txt: every measure and visual query was evaluated in Power BI's own engine before publishing, with
the value each measure shows.
Review gates.txt: every check this project passed before it was published — Power Query, data, DAX, Microsoft's
report schemas, file consistency, best-practice and accessibility rules, the display check, and your approval.
"""


def _save_gates(pid: str, d: Path, v: int, found: list[dict], dax: dict | None = None) -> None:
    (d / "versions" / f"v{v}" / "gates.json").write_text(json.dumps(found), encoding="utf-8")
    st = store.load(pid)
    for x in st["versions"]:
        if x["v"] == v:
            x["gates"] = gates.compact(found)
            if dax:
                x["dax"] = _dax_brief(dax)
    store.save(st)


def _move(src: Path, dst: Path) -> None:
    """Put the checked folder where the published one was (copied over it if Power BI Desktop holds files open)."""
    shutil.rmtree(dst, ignore_errors=True)
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        shutil.rmtree(src, ignore_errors=True)


def _build_pbip(d: Path, pid: str, v: int) -> dict:
    raw = definition.load(d / "versions" / f"v{v}" / "definition.yaml")
    errors, dd = checks.definition_errors(raw, d, check_sql=False)
    if errors:
        raise RuntimeError("The approved definition does not validate: " + "; ".join(errors[:4]))
    folder = f"{HOST_DIR}\\{pid}\\data\\" if HOST_DIR else str(d / "data") + "/"
    dd["data"]["folder"] = folder
    dd["data"]["extracts"] = connectors.extracts_for_pbip(d)    # native connectors for warehouse tables
    out, stage = d / "powerbi", d / ".publish"
    # publish only what Power BI's own engine accepts: every measure and visual query, before anything is written
    if not daxcheck.available():
        raise RuntimeError("The DAX checker is not running on this PC, so the DAX cannot be checked in Power BI's engine "
                           "before publishing. Start daxcheck\\start-daxcheck.cmd (in the Gen BI folder), then press Retry.")
    try:
        dax = daxcheck.summary(daxcheck.run(d, dd, catalog()))
    except Exception as err:  # noqa: BLE001 - shown to the user
        raise RuntimeError(f"The DAX check in Power BI's engine did not finish: {err}. Press Retry.") from err
    (d / "versions" / f"v{v}" / "dax.json").write_text(json.dumps(dax), encoding="utf-8")
    # write the project to a staging folder, run every review gate on those exact files, and only then move it in
    shutil.rmtree(stage, ignore_errors=True)
    pbip = report_builder.build(dd, catalog(), stage, visuals_dir=visuals_dir())
    n = sum(len(p["visuals"]) for p in dd["pages"])
    found = gates.ordered([
        gates.gate("kpis", ok="KPIs and formulas confirmed before the build"),
        gates.gate("definition", ok=f"{len(dd['tables'])} tables, {len(dd['measures'])} measures, {n} visuals"),
        gates.gate("prototype", ok=f"prototype v{v}, drawn from your data"),
        gates.custom_visuals(d, dd), *gates.dax_gates(dax),
        *gates.file_gates(d, dd, catalog(), visuals_dir(), data_mod.connect(d, dd), out=stage, dax=dax),
        _display(pid, f"versions/v{v}/prototype.html"),
        gates.gate("approval", ok=f"v{v} approved for Power BI")])
    _save_gates(pid, d, v, found, dax)
    bad = gates.failed(found)
    if bad:
        shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError(f"Publishing stopped at {len(bad)} review gate(s) ({', '.join(g['name'] for g in bad)}), so "
                           f"nothing was published. Ask Relay to fix them with a change request: "
                           + " | ".join(gates.problems(found)[:6]))
    shutil.copy2(d / "versions" / f"v{v}" / "prototype.html", stage / "Prototype.html")
    (stage / "DAX check.txt").write_text(daxcheck.text_report(dax, pbip.stem), encoding="utf-8")
    (stage / "Review gates.txt").write_text(gates.text_report(found, pbip.stem), encoding="utf-8")
    customs = _custom_used(dd)
    for cv in customs:        # also as .pbiviz files, to import into other reports
        src = (d / "visuals" / "dist" if cv["origin"] == "project" else library_dir() / cv["name"]) / f"{cv['name']}.pbiviz"
        if src.exists():
            (stage / "custom-visuals").mkdir(exist_ok=True)
            shutil.copyfile(src, stage / "custom-visuals" / f"{cv['name']}.pbiviz")
    custom_note = ("\nCustom visuals made for this report: " + ", ".join(c["title"] for c in customs)
                   + " — their .pbiviz files are in custom-visuals/ to import into other reports." if customs else "")
    csvs = sorted((d / "data").glob("*.csv"))
    with_data = sum(f.stat().st_size for f in csvs) <= ZIP_DATA_LIMIT
    zip_note = ("\nThe download also contains the CSVs in data/ — point DataFolder there if you open it elsewhere."
                if with_data else "")
    (stage / "README.txt").write_text(README.format(name=pbip.stem, folder=folder, zip_note=zip_note, v=v,
                                                    custom_note=custom_note), encoding="utf-8")
    _move(stage, out)           # every gate passed: the checked files become the published project
    pbip = out / pbip.name
    zpath = d / f"{pbip.stem}.zip"
    tmp = zpath.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, f"{pbip.stem}/{f.relative_to(out).as_posix()}")
        if with_data:
            for f in csvs:
                z.write(f, f"{pbip.stem}/data/{f.name}")
    os.replace(tmp, zpath)
    host = f"{HOST_DIR}\\{pid}\\powerbi" if HOST_DIR else None
    return {"pbip": pbip.name, "zip": zpath.name, "folder": host, "pbip_path": f"{host}\\{pbip.name}" if host else None,
            "data_folder": folder, "data_in_zip": with_data, "pages": len(dd["pages"]),
            "visuals": sum(len(p["visuals"]) for p in dd["pages"]), "measures": len(dd["measures"]),
            "custom_visuals": [c["title"] for c in customs],
            "dax": {"checked": True, "engine": dax["engine"], "measures": dax["measures"], "visuals": dax["visuals"],
                    "sampled": dax["sampled"], "when": dax["when"], "compared": dax.get("compared"),
                    "differences": dax.get("differences") or []},
            "gates": gates.compact(found)}


async def _pbi(pid: str, v: int) -> None:
    d = store.project_dir(pid)
    app_note(pid, "pbi", f"Building the Power BI project from prototype v{v}…")
    out = await asyncio.to_thread(_build_pbip, d, pid, v)
    st = store.load(pid)
    st.update(status="done", job=None, approved=v, output=out, finished=time.time())
    from . import publishing
    review = publishing.approved_by(st, v)
    st.setdefault("publishes", []).append({"v": v, "when": time.time(), "pbip": out["pbip"], "zip": out["zip"],
                                          "dax": out.get("dax"), "custom_visuals": out.get("custom_visuals"),
                                          "gates": out.get("gates"), "published_by": _owner(pid),
                                          "review": {"reviewer": review["decided_by"], "approved": review.get("decided")} if review else None})
    store.save(st)
    if out["dax"]["differences"]:
        app_note(pid, "pbi", f"{len(out['dax']['differences'])} value(s) in Power BI differ from the approved prototype — "
                 "see DAX check.txt, or ask Relay to make them agree:", "warn", out["dax"]["differences"])
    passed = [g for g in out["gates"] if g["status"] in ("pass", "warn")]
    warned = [g["name"] for g in out["gates"] if g["status"] == "warn"]
    app_note(pid, "pbi", f"Power BI project ready: {out['pbip']} ({out['pages']} pages, {out['visuals']} visuals, "
             f"{out['measures']} measures) — passed all {len(passed)} review gates"
             + (f", with warnings in {', '.join(warned)}" if warned else "") + ". See Review gates.txt.", "ok")
