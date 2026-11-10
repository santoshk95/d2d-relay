"""Relay web app: uploads, review steps and the activity feed. All AI work is done by the Claude Code
agent service, one job at a time (see worker.py)."""
import asyncio
import json
import os
import re
import secrets
import shutil
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
import httpx
import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from genbi_kit import datagen, daxcheck, definition, library_dir, vfactory, visuals_dir
from genbi_kit import validate as checks
from genbi_kit.data import _lit

from . import (askd_routes, auth, connectors, publishing, publishing_routes, data_routes, db, identity, instances, ops, platform, prompts, providers, secrets_store, semantic,
               semantic_routes, store, worker)
from . import changes as changes_mod
from . import home, mailer, monitor, notify, phases, registry, schedules, usage
from . import doctor, errors
from . import branding, edition, otp                 # D2D Relay: the dashboard-only catalogue and the email-code sign-in

errors.install()                                # every traceback.print_exc() and thread crash reports Relay's own bugs (Relay Doctor)
STATIC = Path(__file__).resolve().parent.parent / "static"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIEWABLE = {"request.md", "plan.yaml", "definition.yaml", "profile.md", "CLAUDE.md", "datagen.yaml"}
CHUNK = 1024 * 1024


def _import_existing() -> None:
    """Every project folder and library visual gets an owner in the index (the bootstrap admin when it has none).
    Idempotent: runs at every start, so folders made outside the app are picked up too."""
    projects = store.all_projects()
    added = db.import_existing([p["id"] for p in projects], {p["id"]: p["created"] for p in projects},
                               [v["name"] for v in vfactory.library() if v.get("name")])
    if any(added.values()):
        db.audit("import", None, added, "system")


async def _otp_mail_keepalive():
    """D2D Relay: use the code mailbox's sign-in once a day, so Microsoft never ends it for being unused."""
    from . import otp_mail
    while True:
        try:
            await asyncio.to_thread(otp_mail.keep_alive)
        except Exception:  # noqa: BLE001 - logged; the next sign-in code shows the problem to the person too
            traceback.print_exc()
        await asyncio.sleep(24 * 3600)


@asynccontextmanager
async def lifespan(_):
    db.init()
    identity.bootstrap_password()
    try:
        otp.sync_admin()
    except Exception:  # noqa: BLE001 - sign-in still works with the address the admin row has
        traceback.print_exc()
    _import_existing()
    try:
        usage.backfill()                        # once: cost rows for the runs recorded before phase 7
    except Exception:  # noqa: BLE001 - the cost report is not worth failing start-up for
        traceback.print_exc()
    worker.recover()
    db.audit("app.start", db.INSTANCE, {"auth": auth.MODE}, "system")
    try:
        providers.write_gateway_config()
    except OSError:
        pass                                    # no gateway volume (tests): the gateway keeps its last config
    from . import tenancy                       # P17: grants end on time even when nobody is using the app
    errors.install_loop(asyncio.get_running_loop())
    tasks = [asyncio.create_task(worker.worker_loop()), asyncio.create_task(ops.nightly()),
             asyncio.create_task(instances.reaper(worker.busy_owner)),
             asyncio.create_task(data_routes.scheduler()), asyncio.create_task(schedules.scheduler()),
             asyncio.create_task(monitor.watchdog()), asyncio.create_task(tenancy.sweeper()),
             asyncio.create_task(doctor.loop()), asyncio.create_task(_otp_mail_keepalive())]  # Relay Doctor's shared folder: what runs now, the hold, Admin requests
    await asyncio.sleep(0)                      # let the worker loop record its event loop (Integration analytics and observability use it)
    worker._loop = worker._loop or asyncio.get_running_loop()
    for starter in ():                          # D2D Relay: the other modules' pollers (service desk, integrations, observability, workbench) stay off
        try:                                    # the Service desk, Integration analytics and Data observability pollers and the workbench's
            starter()                           # schedule start with the app, not with the first visit to their page
        except Exception:  # noqa: BLE001 - one poller must not stop the app from starting
            traceback.print_exc()
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="D2D Relay", lifespan=lifespan)
app.middleware("http")(auth.middleware)        # every request: who is asking, and may they (see auth.py)
app.middleware("http")(monitor.middleware)     # outermost: request counts, timings, JSON log lines (phase 8)
app.include_router(platform.router)            # sign-in, sharing, administration (phase 1)
app.include_router(data_routes.router)         # warehouse connections and extracts (phase 3)
app.include_router(semantic_routes.router)     # semantic layer: metrics, terms, context, ontology (phase 4)
app.include_router(askd_routes.router)         # Ask D (phase 5)
app.include_router(publishing_routes.router)   # reviews, GitHub, exports, channels, insight pages (phase 6)
app.include_router(notify.router)              # in-app notifications (phase 7)
app.include_router(usage.router)               # cost report and quotas (phase 7)
app.include_router(mailer.router)              # email sending accounts (phase 7)
app.include_router(schedules.router)           # scheduled reports and alerts (phase 7)
app.include_router(monitor.router)             # metrics, monitoring, alerts on stuck work (phase 8)
app.include_router(doctor.router)              # Relay Doctor: crashes found, fixed, proven and deployed by the service on the host
app.include_router(registry.router)            # module registry, brand settings (P9)
app.include_router(home.router)                # Home insight dashboard (P9)
for _r in phases.ROUTERS:                      # P10 onwards: one router per phase module (app/phases.py)
    app.include_router(_r)
app.include_router(branding.router)            # D2D Relay: Branding (logo + description -> palettes)
app.include_router(otp.router)                 # D2D Relay: sign-in with a one-time email code
edition.apply()                                # D2D Relay: keep dashboards, the visual library and BigQuery; switch the rest off


@app.exception_handler(usage.QuotaError)
async def _quota_stop(_request, exc: usage.QuotaError):
    return JSONResponse({"detail": str(exc)}, status_code=429)


@app.exception_handler(Exception)
async def _crash(request, exc: Exception):
    """An unexpected error: a bug in Relay's own code is reported for Relay Doctor (errors.py); the person gets a plain
    message with the reference instead of a bare "Internal Server Error". (Uvicorn still logs the traceback.)"""
    bug = errors.report(exc, "request", route=monitor._route(request.url.path), method=request.method)   # noqa: SLF001
    ref = f" (reference {bug['fp']})" if bug else ""
    return JSONResponse({"detail": f"Relay hit an unexpected error{ref}. Please try again in a moment."}, status_code=500)


def _str_presenter(dumper, value):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


yaml.SafeDumper.add_representer(str, _str_presenter)


def _get(pid: str) -> dict:
    try:
        return store.load(pid)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "Project not found")


def _safe_name(name: str, default: str) -> str:
    base = re.sub(r"[^\w.\- ]+", "_", Path(name or default).name).strip(" ._") or default
    return base


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


async def _save_upload(upload: UploadFile, path: Path) -> int:
    size = 0
    with path.open("wb") as out:
        while chunk := await upload.read(CHUNK):
            out.write(chunk)
            size += len(chunk)
    return size


def _check_uploads(files: list[UploadFile], images: list[UploadFile]) -> tuple[list[UploadFile], list[UploadFile]]:
    files = [f for f in files if f.filename]
    images = [i for i in images if i.filename]
    for f in files:
        if Path(f.filename).suffix.lower() != ".csv":
            raise HTTPException(400, f'"{f.filename}" is not a .csv file.')
    for i in images:
        if Path(i.filename).suffix.lower() not in IMAGE_EXT:
            raise HTTPException(400, f'"{i.filename}" is not a PNG, JPEG, WebP or GIF image.')
    return files, images


def _csv_problem(path: Path) -> str | None:
    """Why DuckDB cannot read this CSV, or None — checked before a file joins a project."""
    try:
        duckdb.connect().execute(f"SELECT * FROM read_csv_auto({_lit(path)}, header = true) LIMIT 100").fetchall()
        return None
    except duckdb.Error as e:
        return str(e).splitlines()[0][:200]


async def _stage(folder: Path, upload: UploadFile, default: str, replace: bool, taken: set) -> dict:
    """Save an upload beside its destination and check it (a CSV must be readable). With replace=True a CSV
    whose name already exists is an updated dataset and will replace it; otherwise a clash gets a "_" prefix."""
    folder.mkdir(exist_ok=True)
    name = _safe_name(upload.filename, default)
    replaced = replace and (folder / name).exists()
    while not replace and ((folder / name).exists() or name in taken):
        name = "_" + name
    taken.add(name)
    tmp = folder / f".upload-{secrets.token_hex(4)}.tmp"
    try:
        size = await _save_upload(upload, tmp)
        problem = await asyncio.to_thread(_csv_problem, tmp) if name.lower().endswith(".csv") else None
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if problem:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f'"{upload.filename}" could not be read as a CSV: {problem}')
    return {"tmp": tmp, "target": folder / name, "name": name, "bytes": size, "replaced": replaced}


async def _store_uploads(d: Path, files: list[UploadFile], images: list[UploadFile], replace_data: bool) -> list[dict]:
    """CSVs into data/, images into images/ — all checked first, so a bad file adds nothing."""
    staged, taken = [], set()
    try:
        for f in files:
            staged.append({**await _stage(d / "data", f, "data.csv", replace_data, taken), "kind": "data"})
        for i in images:
            staged.append({**await _stage(d / "images", i, "image.png", False, taken), "kind": "image"})
    except BaseException:
        for s in staged:
            s["tmp"].unlink(missing_ok=True)
        raise
    for s in staged:
        os.replace(s["tmp"], s["target"])
    return staged


async def _attach(st: dict, files: list[UploadFile], images: list[UploadFile]) -> list[dict]:
    """Files sent with a change request. A CSV with an existing name replaces that dataset (new data)."""
    if not files and not images:
        return []
    staged = await _store_uploads(store.project_dir(st["id"]), files, images, replace_data=True)
    for s in staged:
        if s["kind"] == "data":
            st["files"] = [f for f in st["files"] if f["name"] != s["name"]] + [{"name": s["name"], "bytes": s["bytes"]}]
        else:
            st["images"] = (st.get("images") or []) + [s["name"]]
    store.save(st)
    return [{"kind": s["kind"], "path": f"{'data' if s['kind'] == 'data' else 'images'}/{s['name']}",
             "bytes": s["bytes"], "replaced": s["replaced"]} for s in staged]


def _attachment_note(added: list[dict]) -> str:
    if not added:
        return ""
    return "\n\nFiles attached with this request:\n" + "\n".join(
        f"- {a['path']} ({_size(a['bytes'])}{', replaces the earlier file of that name' if a['replaced'] else ''})"
        for a in added)


@app.get("/healthz")
def healthz():
    """Liveness / readiness for Kubernetes and load balancers (no sign-in): the process and its database answer."""
    db.one("SELECT 1 AS ok")
    return {"ok": True, "database": db.BACKEND, "instance": db.INSTANCE}


@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            agent = (await client.get(f"{worker.AGENT_URL}/health")).json()
    except Exception as e:  # noqa: BLE001
        agent = {"ok": False, "error": e.__class__.__name__}
    return {"ok": True, "agent": agent, "queue": worker.waiting(), "running": worker.current.get("pid"),
            "running_model": _shown_model(worker.current.get("model")), "daxcheck": daxcheck.available()}


def _catalog() -> dict:
    """The model picker for the person asking: their LiteLLM gateway routes, their own CLI provider, or the Claude
    catalog. Only admins see the models behind Relay's own: when the install has house models
    (config/house-models.json), everyone else picks from those alone (the user's decision, 2026-11-10)."""
    u = auth.current.get()
    cat = providers.catalog_for(u["id"] if u else None, {**worker.model_catalog(), "default": worker.DEFAULT_MODEL})
    ids = {h["id"] for h in worker.house_models()}
    house = [m for m in cat["models"] if m["id"] in ids]
    if house:                                   # D2D Relay: the Relay Model only, admins included
        cat = {**cat, "models": house, "default": cat["default"] if cat["default"] in ids else house[0]["id"]}
    return cat


def _shown_model(model: str | None) -> str | None:
    """The running model for /api/health: named only to admins, or when it is one the person can pick themselves."""
    if not model:
        return None
    u = auth.current.get()
    return model if (u and auth.is_admin(u)) or model in {m["id"] for m in _catalog()["models"]} else None


def _model(model: str) -> str:
    cat = _catalog()
    model = (model or "").strip().lower() or cat["default"]
    ids = [m["id"] for m in cat["models"]]
    if model not in ids:
        raise HTTPException(400, f"Choose a model: {', '.join(ids)}.")
    return model


@app.get("/api/models")
def models():
    """The models this person can pick, with labels and relative price, for the pickers (house models only for
    everyone but admins)."""
    return _catalog()


LOOKS = {"flat": "Flat", "soft": "Soft", "3d": "3D"}
POLICIES = {"ask": "where no available visual fits, Relay proposes a new custom visual in the plan and you decide",
            "auto": "Relay builds a new custom visual wherever it fits the request better than the available ones",
            "never": "Relay uses only the available visuals"}
from genbi_kit.validate import VISUALS_MODES  # noqa: E402 - relay | builtin | mixed, with what each means


def _visuals_line(mode: str) -> str:
    return f"- Visuals: {mode} — {VISUALS_MODES[mode]} (CLAUDE.md, Power BI's own visuals)"
PALETTES = ("spectrum", "analogous", "mono")


def _style(look: str, brand: str, palette: str, dark: str) -> dict:
    """The visual style a user picked on the form (all optional): look, brand color + palette, dark."""
    style = {}
    if look:
        if look not in LOOKS:
            raise HTTPException(400, "Look must be flat, soft or 3d.")
        style["look"] = look
    if brand:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", brand):
            raise HTTPException(400, "Brand color must look like #0F766E.")
        style["accent"] = brand.upper()
        style["palette"] = palette if palette in PALETTES else "spectrum"
    if dark in ("1", "true", "on"):
        style["dark"] = True
    return style


@app.get("/gallery", response_class=HTMLResponse)
def gallery():
    """The Visual Atlas gallery: every visual idea with its variants and a theme studio."""
    path = visuals_dir() / "atlas" / "gallery.html"
    if not path.exists():
        raise HTTPException(404, "The Visual Atlas gallery is not installed.")
    return FileResponse(path, media_type="text/html")


DATA_SIZES = {"small": "about 5,000 rows in the biggest table", "medium": "about 50,000 rows in the biggest table",
              "large": "about 500,000 rows in the biggest table"}


@app.post("/api/projects")
async def create_project(prompt: str = Form(...), name: str = Form(""), model: str = Form(""),
                         look: str = Form(""), brand: str = Form(""), palette: str = Form(""), dark: str = Form(""),
                         custom_visuals: str = Form("ask"), data_mode: str = Form("upload"), data_brief: str = Form(""),
                         data_size: str = Form("medium"), data_months: int = Form(12),
                         connection_id: str = Form(""), tables: str = Form(""), visuals_mode: str = Form("relay"),
                         use_brand: str = Form("1"),
                         files: list[UploadFile] = File(default=[]), images: list[UploadFile] = File(default=[])):
    prompt = prompt.strip()
    model = _model(model)
    custom_visuals = custom_visuals.strip().lower() or "ask"
    if custom_visuals not in POLICIES:
        raise HTTPException(400, "Custom visuals must be ask, auto or never.")
    # called directly by other modules (Start), a parameter they leave out is FastAPI's Form() default, not a string
    visuals_mode = (visuals_mode.strip().lower() if isinstance(visuals_mode, str) else "") or "relay"
    if visuals_mode not in VISUALS_MODES:
        raise HTTPException(400, "Visuals must be relay, builtin or mixed.")
    if visuals_mode == "builtin":
        custom_visuals = "never"          # a report of Power BI's built-in visuals only gets no new custom visual
    style = _style(look.strip().lower(), brand.strip(), palette.strip().lower(), dark.strip().lower())
    house = branding.chosen_style() if isinstance(use_brand, str) and use_brand.strip() in ("1", "true", "on") and not brand.strip() else None
    if house:                                   # D2D Relay: the palette chosen under Branding (the form's own look wins)
        style = {**house, **{k: v for k, v in style.items() if k in ("look", "dark")}}
    files, images = _check_uploads(files, images)
    generate, warehouse = data_mode == "generate", data_mode == "warehouse"
    picked = []
    if warehouse:                      # tables the person configured on one of their own connections
        try:
            conn = connectors.connection(connection_id, auth.who() or db.ADMIN_ID)
        except connectors.ConnectorError:
            raise HTTPException(400, "Choose one of your warehouse connections.")
        configured = {r["object"]: r["alias"] for r in conn_tables(conn["id"])}
        try:
            wanted = json.loads(tables or "[]")
        except ValueError:
            wanted = []
        picked = [{"object": o, "alias": configured[o]} for o in dict.fromkeys(wanted) if o in configured]
        if not picked:
            raise HTTPException(400, "Pick at least one of the tables you configured on that connection.")
    if not prompt:
        raise HTTPException(400, "Describe what you need.")
    if generate and not data_brief.strip():
        raise HTTPException(400, "Describe the business the demo data should be about.")
    if generate and (data_size not in DATA_SIZES or not 3 <= data_months <= 60):
        raise HTTPException(400, "Data size must be small, medium or large, and the period 3 to 60 months.")
    if not files and not generate and not warehouse:
        raise HTTPException(400, "Upload at least one CSV file — or connect a warehouse, or generate demo data.")

    title = name.strip() or (" ".join(data_brief.split()[:5]).rstrip(".,;:").title() if generate
                             else picked[0]["object"].split(".")[-1].replace("_", " ").title() if warehouse
                             else Path(files[0].filename).stem.replace("_", " ").title())
    pid = store.new_id(title)
    d = store.ROOT / pid
    (d / "data").mkdir(parents=True)
    try:
        staged = await _store_uploads(d, files, images, replace_data=False)
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    saved = [{"name": s["name"], "bytes": s["bytes"]} for s in staged if s["kind"] == "data"]
    pics = [s["name"] for s in staged if s["kind"] == "image"]

    worker.refresh_guide(d)
    data = None
    lines = [f"# {title}", "", "## What the user asked for", "", prompt, ""]
    if generate:
        start, end = datagen.default_period(data_months)
        data = {"mode": "generate", "brief": data_brief.strip(), "size": data_size, "months": data_months,
                "start": start.isoformat(), "end": end.isoformat()}
        lines += ["## Data — generate demo data", "", "The user has no data yet: design a realistic demo dataset "
                  "(datagen.yaml) and generate it with `genbi datagen`.", "",
                  f"- Business and data: {data['brief']}", f"- Size: {data_size} — {DATA_SIZES[data_size]}",
                  f"- Period: {data['start']} to {data['end']} ({data_months} months)"]
        lines += ([f"- Use these uploaded files as they are and generate the rest around them: "
                   + ", ".join(f["name"] for f in saved)] if saved else []) + [""]
    if warehouse:
        lines += [f"## Data — warehouse tables ({connectors.KINDS[conn['kind']]['label']}: {conn['name']})", "",
                  "The app pulls these into data/ as Parquet before planning (see the Warehouse tables section that "
                  "follows, and CLAUDE.md):", ""] + [f"- {t['object']} → data/{t['alias']}.parquet" for t in picked] + [""]
    lines += ["## Data (in data/)", ""] + ([f"- {f['name']} ({_size(f['bytes'])})" for f in saved]
                                         or ["- (extracted from the warehouse first)" if warehouse else "- (generated in the data stage)"])
    if pics:
        lines += ["", "## Reference images (in images/)", ""] + [f"- {p}" for p in pics]
    if style:
        lines += ["", "## Visual style (put these in definition.yaml `theme`)", ""]
        lines += [f"- look: {style['look']} ({LOOKS[style['look']]})"] if style.get("look") else []
        lines += [f"- accent: \"{style['accent']}\" (the brand color), palette: {style['palette']}"] if style.get("accent") else []
        lines += [f"- colors: [{', '.join(chr(34) + c + chr(34) for c in style['colors'])}] (the brand palette \"{style.get('brand_name', '')}\", in this order)"] if style.get("colors") else []
        lines += ["- dark: true (dark report background)"] if style.get("dark") else []
    lines += ["", "## Custom visuals", "", f"- Custom visuals: {custom_visuals} — {POLICIES[custom_visuals]}"]
    lines += ["", "## Visuals", "", _visuals_line(visuals_mode)]
    (d / "request.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    store.save({"id": pid, "name": title, "prompt": prompt, "model": model, "style": style, "created": time.time(),
                "custom_visuals": custom_visuals, "visuals_mode": visuals_mode, **({"data": data} if data else {}),
                **({"warehouse": {"connection_id": conn["id"], "kind": conn["kind"], "name": conn["name"], "tables": picked}}
                   if warehouse else {}),
                "status": "queued", "files": saved, "images": pics, "versions": [], "runs": [], "job": None, "error": None})
    db.add_project(pid, auth.who() or db.ADMIN_ID)
    db.audit("project.create", pid, {"name": title, "data": "generate" if generate else "warehouse" if warehouse else "upload",
                                     "model": model}, auth.who())
    worker.enqueue(pid, "data" if generate else "extract" if warehouse else "plan")
    return store.load(pid)


def conn_tables(cid: str) -> list[dict]:
    return db.q("SELECT object, alias FROM connection_tables WHERE connection_id = ?", (cid,))


@app.get("/api/projects")
def list_projects():
    """The dashboards the person asking can see (all of them in single-user mode)."""
    projects = [p for p in store.all_projects() if p.get("kind", "dashboard") == "dashboard"]     # starts (P10) have their own list
    access = auth.access_map(auth.current.get(), [p["id"] for p in projects])
    names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users")}
    return [{**p, **access[p["id"]], "owner": names.get(access[p["id"]]["owner_id"])} for p in projects if p["id"] in access]


@app.get("/api/me")
def me():
    """The person using the app, their teams and roles, and the sign-in mode."""
    from . import tenancy
    u = auth.current.get()
    return {**{k: u[k] for k in ("id", "email", "name", "org_role")}, "teams": u["teams"],
            "admin": auth.is_admin(u), "builder": auth.is_dev(u), "auth": auth.MODE, "instance": db.INSTANCE,
            "tz": u.get("tz"), "guest": bool(u.get("home_tenant")), "tenant": tenancy.me_info(u)}


TOKENS = ("input", "cache_write", "cache_read", "output")


def _usage(runs: list[dict]) -> dict:
    """Claude runs, time, tokens and estimated cost per step ("plan", "v1", "v2" …), for the dashboard and per
    model. Costs are Claude Code's estimates at the list prices of the model each run used."""
    def blank():
        return {"runs": 0, "turns": 0, "duration_ms": 0, "cost_usd": 0.0, "tokens": 0, **dict.fromkeys(TOKENS, 0),
                "complete": True, "from_logs": False, "models": []}
    by, total, by_model = {}, blank(), {}
    for r in runs:
        u = r.get("usage")
        model = r.get("model") or "unknown"
        for g in (by.setdefault(r.get("for") or r.get("stage") or "?", blank()), total):
            g["runs"] += 1
            g["turns"] += r.get("turns") or 0
            g["duration_ms"] += r.get("duration_ms") or 0
            g["cost_usd"] += r.get("cost_usd") or 0
            if u:
                for k in TOKENS:
                    g[k] += u.get(k) or 0
                    g["tokens"] += u.get(k) or 0
            else:
                g["complete"] = False       # a run from before tracking, or one that was stopped
            g["from_logs"] |= r.get("usage_source") == "logs"
            if model not in g["models"]:
                g["models"].append(model)
        # exact split when Claude Code reported one; otherwise the whole run counts for its model
        parts = r.get("models") or {model: {**(u or {}), "cost_usd": r.get("cost_usd") or 0}}
        for m, part in parts.items():
            pm = by_model.setdefault(m, {"runs": 0, "tokens": 0, **dict.fromkeys(TOKENS, 0), "cost_usd": 0.0})
            pm["runs"] += 1
            pm["cost_usd"] += part.get("cost_usd") or 0
            for k in TOKENS:
                pm[k] += part.get(k) or 0
                pm["tokens"] += part.get(k) or 0
    return {"by": by, "total": total, "by_model": by_model}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    st = _get(pid)
    d = store.project_dir(pid)
    plan = d / "plan.yaml"
    if plan.exists() and st.get("plan_rounds"):
        try:
            st["plan"] = definition.load(plan)
        except Exception as e:  # noqa: BLE001
            st["plan_error"] = str(e).splitlines()[0]
    live = d / "prototype" / "index.html"
    st["live_prototype"] = live.stat().st_mtime if live.exists() else None
    st["position"] = worker.position(pid) if st["status"] == "queued" else 0
    st["running_since"] = worker.current.get("started") if worker.current.get("pid") == pid else None
    st["files_available"] = sorted(n for n in VIEWABLE if (d / n).exists())
    me = auth.current.get()
    level, via = auth.access(me, db.project(pid))
    try:
        st["certification"] = semantic.certification(pid)
    except Exception:  # noqa: BLE001 - never break the project page for the badge
        st["certification"] = {}
    st["access"] = {"level": level, "via": via, "can_edit": auth.can_project(me, "edit", db.project(pid)),
                    "can_publish": auth.can_project(me, "publish", db.project(pid)), "can_share": level == "owner"}
    st["usage"] = _usage(st.get("runs") or [])
    st.setdefault("model", worker.DEFAULT_MODEL)
    st.setdefault("custom_visuals", "ask")
    st.setdefault("visuals_mode", "relay")
    if not st.get("publishes") and st.get("output") and st.get("approved"):     # published before the history was kept
        st["publishes"] = [{"v": st["approved"], "when": st.get("finished"), "pbip": st["output"].get("pbip"),
                            "zip": st["output"].get("zip"), "dax": st["output"].get("dax")}]
    st["visuals"] = {"proposals": worker.chosen_visuals(d) if st.get("plan_rounds") else [],
                     "built": vfactory.status(d) if (d / "visuals").is_dir() else []}
    st["host_dir"] = f"{worker.HOST_DIR}\\{pid}" if worker.HOST_DIR else None
    return st


@app.get("/api/projects/{pid}/activity")
def activity(pid: str, after: int = 0):
    _get(pid)
    return store.activity(pid, after)


@app.get("/api/projects/{pid}/images/{name}")
def image(pid: str, name: str):
    st = _get(pid)
    if name not in (st.get("images") or []):
        raise HTTPException(404, "No such image")
    return FileResponse(store.project_dir(pid) / "images" / name)


@app.get("/api/projects/{pid}/files/{name}", response_class=PlainTextResponse)
def project_file(pid: str, name: str):
    _get(pid)
    path = store.project_dir(pid) / name
    if name not in VIEWABLE or not path.exists():
        raise HTTPException(404, "No such file")
    return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))


@app.get("/api/projects/{pid}/prototype/{v}", response_class=HTMLResponse)
def prototype_page(pid: str, v: str):
    _get(pid)
    d = store.project_dir(pid)
    path = d / "prototype" / "index.html" if v == "live" else d / "versions" / f"v{v}" / "prototype.html"
    if not re.fullmatch(r"live|\d+", v) or not path.exists():
        raise HTTPException(404, "No such prototype")
    return HTMLResponse(path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


class KpiReview(BaseModel):
    action: str                     # confirm | revise
    kpis: list[dict]
    feedback: str = ""
    visuals: dict[str, str] = {}    # custom visual name -> generate | available


def _decide(plan: dict, decisions: dict[str, str]) -> list[str]:
    """Write the user's choice on each proposed custom visual into plan.yaml; returns lines for request.md."""
    lines = []
    for v in plan.get("custom_visuals") or []:
        choice = decisions.get(v.get("name"))
        if choice is None:
            continue
        if choice not in checks.CHOICES:
            raise HTTPException(400, "A custom visual choice must be generate or available.")
        v["decision"] = choice
        lines.append(f"- build the custom visual {v.get('title')} ({v['name']})" if choice == "generate"
                     else f"- use the available {v.get('fallback')} instead of a custom {v.get('title')} ({v['name']})")
    return lines


def _kpi_changes(before: list[dict], after: list[dict]) -> list[str]:
    old = {k.get("name"): k for k in before}
    new = {k.get("name"): k for k in after}
    out = [f"- removed **{n}**" for n in old if n not in new]
    out += [f"- added **{n}**: {k.get('label', '')} = `{k.get('dax', '')}`" for n, k in new.items() if n not in old]
    for n, k in new.items():
        if n in old:
            for field in ("label", "description", "dax", "format"):
                if str(k.get(field, "")).strip() != str(old[n].get(field, "")).strip():
                    out.append(f"- **{n}** {field}: `{old[n].get(field, '')}` → `{k.get(field, '')}`")
    return out


@app.post("/api/projects/{pid}/kpis")
async def review_kpis(pid: str, payload: str = Form(...), files: list[UploadFile] = File(default=[]),
                      images: list[UploadFile] = File(default=[])):
    """payload: JSON {action: confirm|revise, kpis, feedback}; files/images may come with a revise request."""
    try:
        body = KpiReview(**json.loads(payload))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Bad request: {e}")
    st = _get(pid)
    if st["status"] != "awaiting_kpis":
        raise HTTPException(409, f"The plan is not waiting for review (status: {st['status']}).")
    if body.action not in ("confirm", "revise"):
        raise HTTPException(400, "Unknown action")
    files, images = _check_uploads(files, images)
    if body.action == "confirm" and (files or images):
        raise HTTPException(400, "New files change the plan: use “Ask Relay to revise the plan” so you can review the KPIs again.")
    feedback = body.feedback.strip()
    if body.action == "revise" and not feedback and not files and not images:
        raise HTTPException(400, "Tell Relay what to change in the plan, or attach files.")
    d = store.project_dir(pid)
    plan = definition.load(d / "plan.yaml")
    kpis = []
    for k in body.kpis:
        if k.get("include", True) is False:
            continue
        clean = {f: str(k.get(f, "")).strip() for f in ("name", "label", "description", "dax", "format")}
        if not clean["name"] or not clean["dax"]:
            raise HTTPException(400, "Every KPI needs a name and a DAX formula.")
        kpis.append({**{x: y for x, y in k.items() if x not in ("include",)}, **clean})
    changes = _kpi_changes(plan.get("kpis") or [], kpis)
    plan["kpis"] = kpis
    chosen = _decide(plan, body.visuals)
    problems = checks.plan(plan)
    if problems:
        raise HTTPException(400, "; ".join(problems[:4]))
    added = await _attach(st, files, images)
    (d / "plan.yaml").write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    if body.action == "revise":
        request = feedback or "Use the attached files in the plan."
        store.note(pid, "Plan change request", request + _attachment_note(added)
                   + ("\n\nThe user also edited the KPIs directly:\n" + "\n".join(changes) if changes else ""))
        store.log(pid, {"kind": "user", "stage": "plan", "text": feedback or "(attached files)",
                        "attachments": [a["path"] for a in added]})
        worker.enqueue(pid, "plan", attachments=added, feedback=request + (
            "\n\n(Direct KPI edits, already saved in plan.yaml:\n" + "\n".join(changes) + ")" if changes else ""))
    else:
        summary = "\n".join(f"- **{k['name']}** ({k['label']}): `{k['dax']}` format `{k['format']}`" for k in kpis)
        store.note(pid, "KPIs confirmed by the user", summary + ("\n\nChanges the user made:\n" + "\n".join(changes) if changes else "")
                   + ("\n\nCustom visuals, as the user chose:\n" + "\n".join(chosen) if chosen else "")
                   + (f"\n\nComment: {feedback}" if feedback else ""))
        store.log(pid, {"kind": "user", "stage": "plan", "text": f"Confirmed {len(kpis)} KPIs"
                        + (f" ({len(changes)} edit(s))" if changes else "") + (f" — {feedback}" if feedback else "")})
        worker.enqueue(pid, "build")
    return get_project(pid)


@app.post("/api/projects/{pid}/feedback")
async def feedback(pid: str, text: str = Form(""), version: int | None = Form(None),
                   files: list[UploadFile] = File(default=[]), images: list[UploadFile] = File(default=[])):
    """A change request on a prototype version, optionally with new CSVs (more or updated data) and images."""
    st = _get(pid)
    if st["status"] not in ("awaiting_review", "done", "error") or not st["versions"]:
        raise HTTPException(409, f"There is no prototype to change right now (status: {st['status']}).")
    files, images = _check_uploads(files, images)
    text = text.strip()
    if not text and not files and not images:
        raise HTTPException(400, "Describe the changes you want, or attach files.")
    d = store.project_dir(pid)
    latest = st["versions"][-1]["v"]
    base = version or latest
    src = d / "versions" / f"v{base}" / "definition.yaml"
    if base != latest and not src.exists():
        raise HTTPException(400, "Unknown version")
    added = await _attach(st, files, images)
    request = text or "Use the attached files where they improve the report."
    if base != latest:
        shutil.copy2(src, d / "definition.yaml")
        request = f"(Start from prototype v{base} — the user went back to it; definition.yaml has been restored to v{base}.)\n\n{request}"
    store.note(pid, f"Change request on prototype v{base}", request + _attachment_note(added))
    store.log(pid, {"kind": "user", "stage": "revise", "text": text or "(attached files)",
                    "attachments": [a["path"] for a in added]})
    worker.enqueue(pid, "revise", feedback=request, attachments=added)
    return get_project(pid)


class VisualChoice(BaseModel):
    name: str
    decision: str                   # generate | available


@app.post("/api/projects/{pid}/custom-visuals")
def choose_visual(pid: str, body: VisualChoice):
    """The user's answer to a custom visual Claude proposed during a revision: build it now, or keep the fallback."""
    st = _get(pid)
    if st["status"] not in ("awaiting_review", "done", "error") or not st["versions"]:
        raise HTTPException(409, f"Not now (status: {st['status']}).")
    d = store.project_dir(pid)
    plan = definition.load(d / "plan.yaml")
    item = next((v for v in plan.get("custom_visuals") or [] if v.get("name") == body.name), None)
    if item is None:
        raise HTTPException(404, "No such proposal")
    line = _decide(plan, {body.name: body.decision})
    (d / "plan.yaml").write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    if body.decision == "available":
        store.note(pid, "Custom visual declined", line[0][2:])
        store.log(pid, {"kind": "user", "stage": "revise", "text": f"Keep {item.get('fallback')} (no custom {item.get('title')})"})
        return get_project(pid)
    request = prompts.generate(item)
    store.note(pid, "Custom visual requested", request)
    store.log(pid, {"kind": "user", "stage": "revise", "text": f"Build the custom visual {item.get('title')}"})
    worker.enqueue(pid, "revise", feedback=request, visual=body.name)
    return get_project(pid)


# ---------------------------------------------------------------- versions: what changed, labels, files

def _version(st: dict, v: int) -> dict:
    entry = next((x for x in st["versions"] if x["v"] == v), None)
    if entry is None:
        raise HTTPException(404, f"There is no version {v}")
    return entry


@app.get("/api/projects/{pid}/versions/{v}/changes")
def version_changes(pid: str, v: int, against: int | None = None):
    """What changed in version v since the one before it (or since `against`), in business terms."""
    st = _get(pid)
    entry = _version(st, v)
    d = store.project_dir(pid)
    base = against if against is not None else max((x["v"] for x in st["versions"] if x["v"] < v), default=None)
    if base is not None:
        _version(st, base)
    try:
        new = definition.load(d / "versions" / f"v{v}" / "definition.yaml")
        old = definition.load(d / "versions" / f"v{base}" / "definition.yaml") if base else None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not read the version: {str(e).splitlines()[0]}")
    out = changes_mod.diff(old, new)
    out.update(v=v, against=base, attachments=entry.get("attachments") or [], feedback=entry.get("feedback"))
    return out


class VersionLabel(BaseModel):
    label: str = ""


@app.post("/api/projects/{pid}/versions/{v}/label")
def version_label(pid: str, v: int, body: VersionLabel):
    """A short name for a version ("Sent to CFO"), shown in the version history."""
    st = _get(pid)
    entry = _version(st, v)
    label = " ".join(body.label.split())[:60]
    entry["label"] = label or None
    store.save(st)
    store.log(pid, {"kind": "user", "text": f"Named v{v} “{label}”" if label else f"Removed the name of v{v}"})
    return get_project(pid)


@app.get("/api/projects/{pid}/versions/{v}/definition")
def version_definition(pid: str, v: int):
    """The report definition of a version (YAML), to keep or compare outside the app."""
    st = _get(pid)
    _version(st, v)
    path = store.project_dir(pid) / "versions" / f"v{v}" / "definition.yaml"
    if not path.exists():
        raise HTTPException(404, "No definition for this version")
    return FileResponse(path, filename=f"{pid}-v{v}-definition.yaml", media_type="text/yaml")


# ---------------------------------------------------------------- activity log export

WHO = {"user": "You", "app": "Relay", "error": "Relay", "say": "Relay", "start": "Relay", "done": "Relay",
       "tool": "Relay", "result": "Relay"}
STAGE_NAMES = {"plan": "Plan", "build": "Build", "revise": "Change request", "pbi": "Power BI"}


def _event_text(e: dict) -> str:
    kind = e.get("kind")
    if kind == "start":
        return "Started working" + (f" ({worker.model_labels().get(e['model'], e['model'])})" if e.get("model") else "")
    if kind == "done":
        return (f"Finished: {e.get('turns') or 0} steps, {round((e.get('duration_ms') or 0) / 1000)} s, "
                f"${(e.get('cost_usd') or 0):.2f}" + ("" if e.get("ok", True) else f" ({e.get('subtype')})"))
    if kind == "tool":
        return f"{e.get('tool')}: {e.get('detail') or ''}"
    if kind == "result":
        return ("" if e.get("ok") else "FAILED: ") + str(e.get("text") or "")
    text = str(e.get("text") or "")
    if e.get("items"):
        text += "".join(f"\n  - {i}" for i in e["items"])
    if e.get("attachments"):
        text += "\n  attached: " + ", ".join(e["attachments"])
    return text


@app.get("/api/projects/{pid}/activity/export")
def activity_export(pid: str, fmt: str = "md", detail: str = "summary", tz: int = 0):
    """The activity log as Markdown or CSV. detail=summary leaves out Claude's individual tool steps; tz is the
    browser's offset (minutes, as JavaScript's getTimezoneOffset) for local times."""
    st = _get(pid)
    events = store.activity(pid, 0, limit=10 ** 9)
    if detail != "all":
        events = [e for e in events if e.get("kind") not in ("tool", "result")]
    when = lambda e: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime((e.get("ts") or 0) - tz * 60))
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", st["name"]).strip() or pid
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["time", "stage", "who", "event", "text"])
        for e in events:
            w.writerow([when(e), STAGE_NAMES.get(e.get("stage"), e.get("stage") or ""), WHO.get(e.get("kind"), ""),
                        e.get("kind"), _event_text(e)])
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem} activity.csv"'})
    lines = [f"# Activity log — {st['name']}", "",
             f"Exported {time.strftime('%Y-%m-%d %H:%M', time.gmtime(time.time() - tz * 60))} · {len(events)} events · "
             + ("every step the agent took" if detail == "all" else "summary (the agent's individual tool steps left out)"), ""]
    stage = None
    for e in events:
        if e.get("stage") and e.get("stage") != stage:
            stage = e["stage"]
            lines += ["", f"## {STAGE_NAMES.get(stage, stage)}", ""]
        text = _event_text(e).replace("\n", "\n  ")
        lines.append(f"- **{when(e)[11:]} · {WHO.get(e.get('kind'), '')}** — {text}")
    return Response("\n".join(lines) + "\n", media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{stem} activity.md"'})


@app.get("/api/projects/{pid}/data/{name}")
def data_preview(pid: str, name: str, limit: int = 25):
    """The first rows of a data file (uploaded or generated), with its row count."""
    _get(pid)
    path = store.project_dir(pid) / "data" / name
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name or not path.is_file():
        raise HTTPException(404, "No such data file")
    con = duckdb.connect()
    try:
        src = f"read_csv_auto({_lit(path)}, header = true, all_varchar = true)"
        cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
        rows = con.execute(f"SELECT * FROM {src} LIMIT {max(1, min(limit, 200))}").fetchall()
        total = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    except duckdb.Error as e:
        raise HTTPException(400, f"Could not read {name}: {str(e).splitlines()[0][:200]}") from e
    return {"name": name, "columns": cols, "rows": rows, "total": total}


@app.get("/api/projects/{pid}/versions/{v}/gates")
def version_gates(pid: str, v: int):
    """Every review gate of a version, with what each one found."""
    _get(pid)
    path = store.project_dir(pid) / "versions" / f"v{v}" / "gates.json"
    if not path.exists():
        raise HTTPException(404, "No review gates recorded for this version yet")
    return json.loads(path.read_text(encoding="utf-8"))


GATING: set[str] = set()


@app.post("/api/projects/{pid}/versions/{v}/gates")
async def run_version_gates(pid: str, v: int):
    """Run the review gates for a saved version now (no Claude involved; the DAX check it already has is reused)."""
    st = _get(pid)
    if not any(x["v"] == v for x in st["versions"]):
        raise HTTPException(404, "Unknown version")
    if st["status"] in worker.RUNNING or pid in GATING:
        raise HTTPException(409, "This dashboard is busy — run the gates when the current step has finished.")
    GATING.add(pid)
    try:
        await asyncio.to_thread(worker.check_version, pid, v)
    except Exception as e:  # noqa: BLE001 - shown to the user
        raise HTTPException(500, f"The review gates could not run: {e}") from e
    finally:
        GATING.discard(pid)
    return get_project(pid)


@app.get("/api/projects/{pid}/dax/{v}")
def dax_values(pid: str, v: int):
    """What Power BI's engine computed for a version: every measure's value and every visual query."""
    _get(pid)
    path = store.project_dir(pid) / "versions" / f"v{v}" / "dax.json"
    if not path.exists():
        raise HTTPException(404, "No DAX check for this version")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/projects/{pid}/visuals/{name}/preview")
def visual_preview(pid: str, name: str):
    """The browser test screenshot of one of this project's custom visuals."""
    _get(pid)
    path = store.project_dir(pid) / "visuals" / name / "test.png"
    if not vfactory.NAME.match(name) or not path.exists():
        raise HTTPException(404, "No preview")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- visual library

def _library_item(name: str, file: str) -> Path:
    path = library_dir() / name / file
    if not vfactory.NAME.match(name) or not path.exists():
        raise HTTPException(404, "Not in the visual library")
    return path


@app.get("/api/library")
def library():
    """Custom visuals built for earlier reports; every new report can use them."""
    return {"visuals": vfactory.library(), "folder": os.environ.get("HOST_LIBRARY_DIR") or str(library_dir())}


@app.get("/api/library/{name}/preview")
def library_preview(name: str):
    return FileResponse(_library_item(name, "preview.png"), media_type="image/png")


@app.get("/api/library/{name}/download")
def library_download(name: str):
    return FileResponse(_library_item(name, f"{name}.pbiviz"), filename=f"{name}.pbiviz",
                        media_type="application/octet-stream")


@app.delete("/api/library/{name}")
def library_remove(name: str):
    """Remove a visual from the library (reports that embed it keep their copy)."""
    _library_item(name, "visual.json")
    vfactory.remove(name)
    db.remove_library(name)
    db.audit("library.remove", name, None, auth.who())
    return library()


class Approve(BaseModel):
    version: int


@app.post("/api/projects/{pid}/approve")
def approve(pid: str, body: Approve):
    st = _get(pid)
    if st["status"] not in ("awaiting_review", "done", "error") or not st["versions"]:
        raise HTTPException(409, f"Nothing to approve right now (status: {st['status']}).")
    ver = next((v for v in st["versions"] if v["v"] == body.version), None)
    if ver is None:
        raise HTTPException(400, "Unknown version")
    bad = [g["name"] for g in ver.get("gates") or [] if g.get("status") == "fail"]
    if bad:
        raise HTTPException(409, f"v{body.version} has not passed its review gates ({', '.join(bad)}). Ask Relay to fix "
                                 f"them with a change request — or run the gates again — before approving.")
    try:
        publishing.check_publish(pid, body.version, auth.current.get())     # review policy (phase 6)
    except publishing.PublishError as e:
        raise HTTPException(409, str(e))
    store.note(pid, "Approved", f"The user approved prototype v{body.version} for the Power BI build.")
    store.log(pid, {"kind": "user", "stage": "pbi", "text": f"Approved prototype v{body.version}"})
    db.audit("project.approve", pid, {"version": body.version}, auth.who())
    worker.enqueue(pid, "pbi", version=body.version)
    return get_project(pid)


@app.post("/api/projects/{pid}/retry")
def retry(pid: str):
    st = _get(pid)
    job = st.get("job")
    if st["status"] != "error" or not job:
        raise HTTPException(409, "Nothing to retry.")
    store.log(pid, {"kind": "user", "stage": job["kind"], "text": "Retry"})
    worker.enqueue(pid, job["kind"], **{k: v for k, v in job.items() if k not in ("kind", "id", "model")})
    return get_project(pid)


class ModelChoice(BaseModel):
    model: str


@app.post("/api/projects/{pid}/model")
def set_model(pid: str, body: ModelChoice):
    """The Claude model for this project's next runs (a run already going keeps its model)."""
    st = _get(pid)
    model = _model(body.model)
    if model != st.get("model", worker.DEFAULT_MODEL):
        store.update(pid, model=model)
        db.audit("project.model", pid, {"model": model}, auth.who())
        store.log(pid, {"kind": "user", "text": f"Model: {({m['id']: m['label'] for m in _catalog()['models']}).get(model, model)} for the next runs"})
    return get_project(pid)


class VisualsChoice(BaseModel):
    mode: str


@app.post("/api/projects/{pid}/visuals")
def set_visuals_mode(pid: str, body: VisualsChoice):
    """Which visuals the next versions use: relay (custom visuals), builtin (Power BI's own only) or mixed."""
    st = _get(pid)
    mode = (body.mode or "").strip().lower()
    if mode not in VISUALS_MODES:
        raise HTTPException(400, "Visuals must be relay, builtin or mixed.")
    if mode != st.get("visuals_mode", "relay"):
        changes = {"visuals_mode": mode, **({"custom_visuals": "never"} if mode == "builtin" else {})}
        store.update(pid, **changes)
        req = store.ROOT / pid / "request.md"
        if req.exists():                    # the agent reads its brief from request.md: keep its Visuals line current
            text = req.read_text(encoding="utf-8")
            line = _visuals_line(mode)
            text = re.sub(r"(?m)^- Visuals: .*$", line, text) if re.search(r"(?m)^- Visuals: ", text) else text.rstrip("\n") + f"\n\n## Visuals\n\n{line}\n"
            if mode == "builtin":
                text = re.sub(r"(?m)^- Custom visuals: .*$", f"- Custom visuals: never — {POLICIES['never']}", text)
            req.write_text(text, encoding="utf-8")
        db.audit("project.visuals", pid, {"mode": mode}, auth.who())
        store.log(pid, {"kind": "user", "text": f"Visuals for the next versions: {VISUALS_MODES[mode]}"})
    return get_project(pid)


@app.post("/api/projects/{pid}/stop")
def stop(pid: str):
    _get(pid)
    if not worker.stop(pid):
        raise HTTPException(409, "Nothing is running for this project.")
    return {"ok": True}


@app.get("/api/projects/{pid}/download")
def download(pid: str):
    st = _get(pid)
    out = st.get("output") or {}
    path = store.project_dir(pid) / out.get("zip", "-")
    if st["status"] != "done" or not path.exists():
        raise HTTPException(404, "The Power BI project is not ready yet.")
    return FileResponse(path, filename=out["zip"], media_type="application/zip")


# ---------------------------------------------------------------- administration (admins only: see auth.check)

@app.get("/api/admin/audit")
def admin_audit(limit: int = 200, action: str | None = None):
    """Platform events: sign-ins (phase 1), project created / approved, model changes, library changes, backups."""
    return db.audit_log(min(max(limit, 1), 2000), action)


@app.get("/api/admin/jobs")
def admin_jobs(limit: int = 100):
    """The durable queue: what is waiting, running and recently finished, in every lane."""
    return {"running": {k: v for k, v in worker.current.items() if k != "task"},
            "jobs": db.q("SELECT id, pid, kind, model, lane, owner_id, state, created, started, ended, error FROM jobs "
                         "ORDER BY created DESC LIMIT ?", (min(max(limit, 1), 1000),))}


@app.get("/api/admin/backups")
def admin_backups():
    return {"backups": ops.backups(), "keep": ops.KEEP, "hour_utc": ops.HOUR_UTC, "folder": str(ops.BACKUPS),
            "max_file_mb": ops.BIG_MB, "cache_days": ops.CACHE_DAYS}


@app.post("/api/admin/backups")
async def admin_backup_now():
    try:
        return await asyncio.to_thread(ops.backup_now, auth.who())
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/admin/secrets")
def admin_secrets():
    """Names of stored secrets (never their values) and where the encryption key comes from."""
    return {"secrets": secrets_store.names(), "key": secrets_store.key_source()}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
