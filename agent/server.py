"""Relay agent: runs the Claude Code CLI as an agent inside one project folder and streams what it does.

POST /runs  {"workdir": "<project id>", "prompt": "...", "system": "...", "model": "sonnet", "max_turns": 60,
             "resume": null}
            -> application/x-ndjson events: start, say, tool, result, done (or error)
            `model` is an id from config/models.json (an alias such as "sonnet" or a pinned version such as
            "claude-opus-4-5"); the start event names the exact model.
            `resume` continues an earlier session (its id comes in the start/done events).
POST /display-check  {"workdir": "<project id>", "file": "prototype/index.html"}
            -> the display review gate: the prototype drawn in headless Chromium, its labels read back
GET  /health
GET  /metrics   Prometheus text: lane busy / busy-since, runs and run seconds per runner, lane and outcome

Claude gets file tools for the project folder and Bash limited to the `genbi` toolkit; no web
access and no sub-agents.

Runners and lanes (platform plan, phase 0): every run goes through a `Runner` (start a run, stream normalised
events: start, say, tool, result, done with usage - or error). `ClaudeCodeRunner` is the only one today; Codex CLI
and Gemini CLI adapters plug in behind the same interface later. Runs are strictly sequential *per lane*: the
`build` lane (dashboards; the only lane the app uses today) and the `chat` lane (Ask Relay, phase 5), so a question
never waits behind a build. One run at a time in each lane.
"""
import asyncio
import json
import os
import re
import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from runners import RUNNER_ENV, installed

ROOT = Path(os.environ.get("WORKSPACES", "/data/projects")).resolve()
MODEL = os.environ.get("AGENT_MODEL", "sonnet")
CATALOG = Path(os.environ.get("MODELS_FILE", "/opt/genbi/config/models.json"))


HOUSE = CATALOG.with_name("house-models.json")
HOUSE_SYSTEM = ("You are {label}, the AI model built into Relay by PASDACS. If anyone asks which model, version or company is "
                "behind you, say you are {label}; do not name any other model or AI company.")


def _house() -> dict:
    """Relay's own models (config/house-models.json): an id and a label the app shows, and the model that serves it.
    The serving model stays here: every event the agent sends names the house id instead."""
    try:
        return {m["id"]: m for m in json.loads(HOUSE.read_text(encoding="utf-8"))["models"] if m.get("id") and m.get("target")}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _models() -> list[str]:
    """Model names the app may ask for: the catalog probe_models.py wrote (re-read, so updates need no restart)."""
    try:
        ids = [m["id"] for m in json.loads(CATALOG.read_text(encoding="utf-8"))["models"]]
    except (OSError, ValueError, KeyError, TypeError):
        ids = [MODEL]
    return list(_house()) + ids


def _mask(ev: dict, alias: str, real: str) -> dict:
    """A house model's run: the serving model's name becomes the house id in the start event, the per-model usage and
    any error text."""
    if ev.get("kind") == "start" and ev.get("model"):
        ev["model"] = alias
    if isinstance(ev.get("models"), dict):
        merged: dict = {}
        for name, u in ev["models"].items():
            key = alias if name.startswith(real) else name
            merged[key] = {k: (merged[key].get(k, 0) + v if isinstance(v, (int, float)) else v) for k, v in u.items()} if key in merged else dict(u)
        ev["models"] = merged
    if ev.get("kind") == "error" and isinstance(ev.get("text"), str):
        ev["text"] = ev["text"].replace(real, alias)
    return ev
# (TodoWrite: older Claude Code; its task list is TaskCreate/TaskUpdate/TaskList/TaskGet since 2.1)
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
         "Bash(genbi:*)"]
DENY = ["WebFetch", "WebSearch", "Task", "Agent", "NotebookEdit"]   # no web, no sub-agents
# Whatever a data file or an attachment tells the AI, it works inside its own dashboard's folder. The limits are Claude
# Code's managed settings (/etc/claude-code/managed-settings.json, above every other settings file): reads and writes
# outside the folder refused, only managed hooks run (bash_guard.py: the shell runs one `genbi` command), no web, no
# sub-agents, CLAUDE.md and the folder's .claude/ not editable. Here: no MCP servers, no skills or slash commands.
# (Not --restricted: it confines the same way but leaves out the folder's CLAUDE.md, the agent's manual.)
LOCKDOWN = ["--strict-mcp-config", "--disable-slash-commands"]

app = FastAPI(title="Relay agent")
LANES = ("build", "chat")
locks = {lane: asyncio.Lock() for lane in LANES}
since: dict[str, float] = {}                       # lane -> when its current run started (observability, phase 8)
RUN_STATS: dict[tuple, list] = {}                  # (runner, lane, outcome) -> [count, seconds]
STARTED = time.time()


def _record(runner: str, lane: str, outcome: str, seconds: float) -> None:
    c = RUN_STATS.setdefault((runner, lane, outcome), [0, 0.0])
    c[0] += 1
    c[1] += seconds


class Run(BaseModel):
    workdir: str
    prompt: str
    system: str = ""
    model: str | None = None
    max_turns: int = 60
    timeout_s: int = 3600
    resume: str | None = None
    lane: str = "build"
    runner: str = "claude-code"
    # the run owner's AI provider (phase 2): only the variables in PROVIDER_ENV are passed to the CLI process;
    # they are never logged or echoed back
    env: dict[str, str] = {}
    # a subset of TOOLS for this run; [] = no tools at all (Ask Relay: the web app runs every query itself)
    tools: list[str] | None = None


PROVIDER_ENV = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
                "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_CUSTOM_HEADERS"}
# P16 (AI SDLC): the repository credential `genbi repo` uses, injected by the web app per run, never written to disk;
# P17: GENBI_LIBRARY = the run's tenant's visual library (a folder inside this container's library mount)
TOOLKIT_ENV = {"GENBI_REPO_TOKEN", "GENBI_REPO_USER", "GENBI_LIBRARY"}


def _library_ok(value: str) -> bool:
    base = Path(os.environ.get("GENBI_LIBRARY", "/opt/genbi/library")).resolve()
    path = Path(value).resolve()
    return path == base or base in path.parents


def _env(run: "Run") -> dict[str, str]:
    allowed = PROVIDER_ENV if run.runner == "claude-code" else RUNNER_ENV      # each runner gets only its own kind of key
    extra = {k: str(v) for k, v in run.env.items() if (k in allowed or k in TOOLKIT_ENV) and v}
    if "GENBI_LIBRARY" in extra and not _library_ok(extra["GENBI_LIBRARY"]):
        extra.pop("GENBI_LIBRARY")                                              # only a folder of this container's library
    env = dict(os.environ)
    if extra.keys() & {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"}:
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):   # one credential only
            env.pop(k, None)
    return env | extra


def _short(text: str, n: int = 400) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 3] + "..."


def _detail(name: str, inp: dict) -> str:
    if name == "Bash":
        return inp.get("command", "")
    if name in ("Read", "Write", "Edit"):
        path = Path(inp.get("file_path", "")).name
        if name == "Write":
            return f"{path} ({len(inp.get('content', '')):,} chars)"
        return path
    if name in ("Glob", "Grep"):
        return inp.get("pattern", "")
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        now = next((t.get("content") for t in todos if t.get("status") == "in_progress"), None)
        return f"{sum(t.get('status') == 'completed' for t in todos)}/{len(todos)} done" + (f" - {now}" if now else "")
    if name in ("TaskCreate", "TaskUpdate"):
        return _short(" - ".join(str(inp[k]) for k in ("subject", "status") if inp.get(k)), 200)
    return _short(json.dumps(inp), 200)


USAGE_KEYS = {"input": "inputTokens", "cache_write": "cacheCreationInputTokens",
              "cache_read": "cacheReadInputTokens", "output": "outputTokens"}


def _by_model(obj: dict) -> dict:
    """Tokens and Claude Code's cost estimate (list prices of that model) per model the run used."""
    return {model: {**{k: int(u.get(v) or 0) for k, v in USAGE_KEYS.items()}, "cost_usd": u.get("costUSD") or 0}
            for model, u in (obj.get("modelUsage") or {}).items()}


def _usage(obj: dict) -> dict:
    """Exact token totals of a finished run, summed over every model Claude Code used: new input,
    cache writes, cache reads and output. (Per-message usage in the stream undercounts output.)"""
    models = _by_model(obj)
    if models:
        return {k: sum(m[k] for m in models.values()) for k in USAGE_KEYS}
    u = obj.get("usage") or {}
    return {"input": u.get("input_tokens") or 0, "cache_write": u.get("cache_creation_input_tokens") or 0,
            "cache_read": u.get("cache_read_input_tokens") or 0, "output": u.get("output_tokens") or 0}


def _events(obj: dict):
    kind = obj.get("type")
    if kind == "system" and obj.get("subtype") == "init":
        yield {"kind": "start", "model": obj.get("model"), "session_id": obj.get("session_id")}
    elif kind == "assistant":
        for block in obj.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                yield {"kind": "say", "text": block["text"].strip()}
            elif block.get("type") == "tool_use":
                yield {"kind": "tool", "id": block.get("id"), "tool": block.get("name"),
                       "detail": _detail(block.get("name"), block.get("input") or {})}
    elif kind == "user":
        for block in obj.get("message", {}).get("content", []) if isinstance(obj.get("message", {}).get("content"), list) else []:
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                yield {"kind": "result", "id": block.get("tool_use_id"), "ok": not block.get("is_error"),
                       "text": _short(content or "", 600)}
    elif kind == "result":
        yield {"kind": "done", "ok": not obj.get("is_error"), "subtype": obj.get("subtype"), "text": obj.get("result", ""),
               "turns": obj.get("num_turns"), "cost_usd": obj.get("total_cost_usd"), "duration_ms": obj.get("duration_ms"),
               "session_id": obj.get("session_id"), "usage": _usage(obj), "models": _by_model(obj)}


class Runner(ABC):
    """One agentic CLI. `run` yields normalised events (dicts with `kind`) and must stop its process when the
    consumer goes away (the generator is closed) or the timeout passes."""
    name: str

    @abstractmethod
    def run(self, run: Run, workdir: Path, model: str) -> AsyncIterator[dict]:
        ...


class ClaudeCodeRunner(Runner):
    """Claude Code headless (`claude -p`, stream-json), file tools and the genbi toolkit only."""
    name = "claude-code"

    async def run(self, run: Run, workdir: Path, model: str) -> AsyncIterator[dict]:
        house = _house().get(model)
        real = house["target"] if house else model
        args = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", real,
                "--max-turns", str(run.max_turns), "--permission-mode", "acceptEdits",
                *LOCKDOWN, *_tool_args(run)]
        system = "\n\n".join(x for x in (run.system, HOUSE_SYSTEM.format(label=house.get("label") or model) if house else None) if x)
        if system:
            args += ["--append-system-prompt", system]
        if run.resume:
            args += ["--resume", run.resume]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=workdir, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024, env=_env(run))
        proc.stdin.write(run.prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        done = False
        try:
            async with asyncio.timeout(run.timeout_s):
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for ev in _events(obj):
                        done = done or ev["kind"] == "done"
                        yield _mask(ev, model, real) if house else ev
                await proc.wait()
        except TimeoutError:
            yield {"kind": "error", "text": f"Agent run timed out after {run.timeout_s // 60} minutes"}
            return
        finally:
            # Timeout, or the web app went away (user pressed Stop): never leave Claude running.
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        if not done:
            err = (await proc.stderr.read()).decode(errors="replace").strip()
            ev = {"kind": "error", "text": _short(err or f"claude exited with code {proc.returncode}", 1500)}
            yield _mask(ev, model, real) if house else ev


def _tool_args(run: "Run") -> list[str]:
    """--tools: the only built-in tools the run has (a subset never has the shell; [] = none at all: Ask Relay, where
    the web app runs every query itself); --allowedTools: what runs without asking (anything else is refused: -p)."""
    if run.tools is None:
        allowed = list(TOOLS)
    else:
        allowed = [t for t in run.tools if t in TOOLS and not t.startswith("Bash")]
    builtin = list(dict.fromkeys(t.split("(")[0] for t in allowed))      # Bash(genbi:*) -> Bash
    args = ["--tools", ",".join(builtin)]
    if allowed:
        args += ["--allowedTools", *allowed]
    return args + ["--disallowedTools", *DENY, *([] if "Bash" in builtin else ["Bash"])]


class CliAdapter(Runner):
    """Codex CLI, Gemini CLI or Antigravity CLI (runners.py) behind the same interface; the model is the CLI's own
    (None = the CLI's default), and each gets only its owner's credentials."""

    def __init__(self, cli):
        self.cli, self.name = cli, cli.name

    def run(self, run: Run, workdir: Path, model: str) -> AsyncIterator[dict]:
        return self.cli.run(run, workdir, run.model or None, _env(run))


RUNNERS: dict[str, Runner] = {r.name: r for r in (ClaudeCodeRunner(), *(CliAdapter(c) for c in installed()))}
if os.environ.get("D2D_RUNNERS") and "claude-code" not in os.environ["D2D_RUNNERS"]:
    RUNNERS.pop("claude-code")                       # a runner image serves its own CLI only


@app.get("/health")
def health():
    lanes = {lane: lock.locked() for lane, lock in locks.items()}
    # `busy` = the build lane, as before (the web app gates redeploys and its status pill on it)
    return {"ok": True, "busy": lanes["build"], "lanes": lanes, "runners": list(RUNNERS), "model": MODEL,
            "models": _models(), "since": {lane: since.get(lane) for lane in LANES}}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    now = time.time()
    out = ["# TYPE d2d_agent_up gauge", "d2d_agent_up 1", f"d2d_agent_uptime_seconds {now - STARTED:.0f}",
           "# TYPE d2d_agent_lane_busy gauge"]
    out += [f'd2d_agent_lane_busy{{lane="{lane}"}} {int(lock.locked())}' for lane, lock in locks.items()]
    out.append("# TYPE d2d_agent_lane_busy_seconds gauge")
    out += [f'd2d_agent_lane_busy_seconds{{lane="{lane}"}} {now - since[lane] if lane in since else 0:.0f}' for lane in LANES]
    out += ["# TYPE d2d_agent_runs_total counter", "# TYPE d2d_agent_run_seconds_total counter"]
    for (runner, lane, outcome), (n, secs) in sorted(RUN_STATS.items()):
        lab = f'runner="{runner}",lane="{lane}",outcome="{outcome}"'
        out += [f"d2d_agent_runs_total{{{lab}}} {n}", f"d2d_agent_run_seconds_total{{{lab}}} {secs:.1f}"]
    return "\n".join(out) + "\n"


class Display(BaseModel):
    workdir: str
    file: str = "prototype/index.html"


@app.post("/display-check")
def display_check(req: Display):
    """Runs in a worker thread (Playwright's sync API); no Claude involved, so it does not take the run lock."""
    path = (ROOT / req.workdir / req.file).resolve()
    if ROOT not in path.parents or not path.is_file():
        raise HTTPException(400, "file must be an existing prototype inside a project folder")
    from genbi_kit import display
    return display.check(path)


@app.post("/runs")
async def runs(run: Run):
    workdir = (ROOT / run.workdir).resolve()
    if ROOT not in workdir.parents or not workdir.is_dir():
        raise HTTPException(400, "workdir must be an existing project folder")
    model, allowed = run.model or MODEL, _models()
    if run.runner == "claude-code" and model not in allowed and not run.env.get("ANTHROPIC_BASE_URL"):   # a gateway names its own models
        raise HTTPException(400, f"model must be one of {', '.join(allowed)}")
    if run.lane not in locks:
        raise HTTPException(400, f"lane must be one of {', '.join(LANES)}")
    runner = RUNNERS.get(run.runner)
    if runner is None:
        raise HTTPException(400, f"runner must be one of {', '.join(RUNNERS)}")
    lock = locks[run.lane]
    if lock.locked():
        raise HTTPException(409, f"Another agent run is in progress in the {run.lane} lane")

    async def stream():
        async with lock:
            since[run.lane] = started = time.time()
            outcome = "stopped"
            events = runner.run(run, workdir, model)
            try:
                async for ev in events:
                    if ev["kind"] == "done":
                        outcome = "ok" if ev.get("ok", True) else "failed"
                    elif ev["kind"] == "error":
                        outcome = "error"
                    yield json.dumps(ev) + "\n"
            finally:
                await events.aclose()        # the client went away: the runner's cleanup kills its process
                since.pop(run.lane, None)
                _record(runner.name, run.lane, outcome, time.time() - started)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class Snapshot(BaseModel):
    html: str
    width: int = 900


class Render(BaseModel):
    html: str
    format: str = "png"
    width: int = 1320


@app.post("/render")
def render(req: Render):
    """PNG or PDF of a self-contained page (a dashboard prototype, an insight page). Its own inline scripts run (the
    prototype draws its charts); every request to the network is blocked. Does not take a lane lock."""
    import base64

    from playwright.sync_api import sync_playwright
    if req.format not in ("png", "pdf"):
        raise HTTPException(400, "png or pdf")
    if len(req.html) > 30_000_000:
        raise HTTPException(413, "too large")
    from genbi_kit.display import OFFLINE_ARGS, offline
    with sync_playwright() as p:
        browser = p.chromium.launch(args=OFFLINE_ARGS)
        try:
            page = browser.new_page(viewport={"width": max(320, min(req.width, 2000)), "height": 900}, device_scale_factor=1 if req.format == "pdf" else 2)
            offline(page)
            page.set_content(req.html, wait_until="load", timeout=60000)
            page.wait_for_timeout(1500)                   # let the page's own scripts finish drawing
            if req.format == "pdf":
                data = page.pdf(print_background=True, landscape=True, format="A4", margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
            else:
                data = page.screenshot(full_page=True, type="png")
        finally:
            browser.close()
    return {"data": base64.b64encode(data).decode(), "format": req.format}


@app.post("/snapshot")
def snapshot(req: Snapshot):
    """A PNG of a self-contained HTML card (an Ask Relay answer), drawn in headless Chromium. No network, no scripts
    from outside: the page is set as content and external requests are blocked. Does not take a lane lock."""
    import base64

    from playwright.sync_api import sync_playwright
    if len(req.html) > 2_000_000:
        raise HTTPException(413, "too large")
    from genbi_kit.display import OFFLINE_ARGS, offline
    with sync_playwright() as p:
        browser = p.chromium.launch(args=OFFLINE_ARGS)
        try:
            page = browser.new_page(viewport={"width": max(320, min(req.width, 1600)), "height": 600}, device_scale_factor=2)
            offline(page)
            page.set_content(req.html, wait_until="load", timeout=15000)
            png = page.screenshot(full_page=True, type="png")
        finally:
            browser.close()
    return {"png": base64.b64encode(png).decode()}


# ---------------------------------------------------------------- forgetting runs (data governance, item 22)
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
SESSION_ID = re.compile(r"^[0-9a-fA-F][0-9a-fA-F-]{7,63}$")
PER_SESSION = ("tasks", "session-env", "file-history", "debug", "todos")     # Claude Code's other records, by session id


class Forget(BaseModel):
    workdir: str | None = None          # a folder the runs used, as POST /runs takes it
    sessions: list[str] | None = None   # only these sessions of it (an Ask Relay answer); none: every run it had
    missing: bool = False               # instead: every folder under the projects root that no longer exists
    older_than_days: float | None = None   # with missing: also every transcript not touched for this long


def _slug(path: Path) -> str:
    """Where Claude Code keeps a working folder's sessions: ~/.claude/projects/<the path, every other character a dash>."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _drop_session(sid: str) -> int:
    n = 0
    for sub in PER_SESSION:
        base = CLAUDE_HOME / sub
        for p in list(base.glob(sid + "*")) if base.is_dir() else []:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            n += 1
    return n


def _drop(folder: Path, sessions: list[str] | None = None) -> int:
    if not folder.is_dir():
        return 0
    n = 0
    for sid in ([p.stem for p in folder.glob("*.jsonl")] if sessions is None else sessions):
        if not SESSION_ID.match(sid):
            continue
        n += _drop_session(sid)
        if sessions is not None:
            for p in (folder / f"{sid}.jsonl", folder / sid):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    n += 1
                elif p.exists():
                    p.unlink(missing_ok=True)
                    n += 1
    if sessions is None:
        shutil.rmtree(folder, ignore_errors=True)
        n += 1
    return n


def _live_folders() -> set[str]:
    """The slugs of every folder a run can use today: the projects root, its folders, and each tenant's folders."""
    out = {ROOT}
    for p in ROOT.iterdir():
        if p.is_dir():
            out.add(p)
    tenants = ROOT / ".tenants"
    for t in tenants.iterdir() if tenants.is_dir() else []:
        if t.is_dir():
            out.add(t)
            out.update(p for p in t.iterdir() if p.is_dir())
    return {_slug(p) for p in out}


@app.post("/forget")
def forget(req: Forget):
    """Delete Claude Code's own record of runs (the transcripts with the tool output saved beside them, task lists,
    shell state) once what they read is deleted: a dashboard, an Ask Relay answer, an organisation (missing: every folder
    that is gone). The transcripts hold what the AI read, so they must not outlive it. Claude Code also drops any
    transcript older than cleanupPeriodDays by itself (managed settings)."""
    projects = CLAUDE_HOME / "projects"
    if req.missing:
        root, live = _slug(ROOT), _live_folders()
        mine = [d for d in (projects.glob(root + "*") if projects.is_dir() else [])
                if d.is_dir() and (d.name == root or d.name.startswith(root + "-"))]
        gone = [d for d in mine if d.name not in live]
        removed = sum(_drop(d) for d in gone)
        if req.older_than_days:                 # Claude Code's own clean-up runs only when a run starts: this one nightly
            cutoff = time.time() - req.older_than_days * 86400
            for d in mine:
                old = [f.stem for f in d.glob("*.jsonl") if d.name in live and f.stat().st_mtime < cutoff]
                removed += _drop(d, old) if old else 0
        return {"removed": removed, "folders": len(gone)}
    if not req.workdir:
        raise HTTPException(400, "workdir or missing")
    target = (ROOT / req.workdir).resolve()
    if ROOT not in target.parents:
        raise HTTPException(400, "workdir must be inside the projects root")
    if req.sessions is not None and not all(SESSION_ID.match(s) for s in req.sessions):
        raise HTTPException(400, "unknown session id")
    return {"removed": _drop(projects / _slug(target), req.sessions)}
