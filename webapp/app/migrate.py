"""Migrate BI (build-plan v2, P15): Discover -> Decide -> Convert -> Prove -> Hand over -> Run for a BI estate.

A migration programme is a folder under output/projects/<id>/ (project.json with kind "migbi"): source/ holds the
exports, the downloaded content store or the sample estate; estate.json is the neutral model; predictions.json the
"Ready to convert" calls; similarity.json the merge candidates; decisions.json the signed decisions; waves.json the
waves. Every converted report is its own dashboard-style sub-project (<id>-<slug>/, kind "migbi_report") built
through the existing path - definition.yaml -> review gates (worker._check_definition) -> DAX checker -> PBIP
builder - never a second builder.

Jobs in the one sequential lane: migbi_scan (reads the estate page by page, pause / resume / stop, resumes from a
cursor after a restart), migbi_convert (rules first, the agent only for the gaps, gates with fix rounds, the
proof, the package; llm=True), migbi_drift (the nightly re-proof, a stub schedule in P15).
Checkpoints: migbi.decide (the rules and their result, signed), migbi.prove (numbers vs source per report),
migbi.handover (owner sign-off per wave; the pack cannot be downloaded before it).
Lineage goes to migbi_lineage; when app.lineage exists (P13), push_lineage hands the same edges to it.
"""
from __future__ import annotations

import asyncio
import contextvars
import csv
import io
import json
import os
import re
import secrets as pysecrets
import shutil
import time
import traceback
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from genbi_kit import catalog, definition, report_builder, use_project, visuals_dir
from genbi_kit import gates as gates_mod
from genbi_kit.migrate import convert as conv
from genbi_kit.migrate import decide as dec
from genbi_kit.migrate import model, proof as proof_mod, rules, sample_estate
from genbi_kit.migrate.readers import READERS, catalogue as reader_catalogue, cognos

from . import auth, checkpoints, db, migrate_prompts, notify, prompts, secrets_store, store, worker

router = APIRouter()
MODULE = "Migrate BI"
ROUTE = "#/migrate-bi"
KIND_DECIDE, KIND_PROVE, KIND_HANDOVER = "migbi.decide", "migbi.prove", "migbi.handover"
SCAN_PACE_S = float(os.environ.get("MIGBI_SCAN_PACE_S", "0.12"))        # a short breath per page so the feed reads naturally
PAGE_SIZE = int(os.environ.get("MIGBI_PAGE_SIZE", "100"))
COST_PER_CALL = 0.03                                                   # the estimate before anything runs; real cost comes from the runs
MINUTES = {"simple": 2, "medium": 5, "complex": 11, "very complex": 19}
TARGETS = {"powerbi": {"label": "Power BI", "versions": ["Power BI Service (PBIP)", "Power BI Report Server - January 2025 (PBIX)"]},
           "fabric": {"label": "Microsoft Fabric", "versions": ["Fabric workspace"], "next": True},
           "databricks": {"label": "Databricks AI/BI", "versions": ["Dashboards"], "next": True}}
MODES = {"rules_first": "Rules first (recommended)", "ai_led": "AI-led", "rules_only": "Rules only"}
MODE_HELP = {"rules_first": "tested rules do the work; the agent is asked only where no rule fits, and its answer is checked by the review gates and the proof before it is used.",
             "ai_led": "the agent reworks every calculation after the rules draft the report, then everything is proven. For unusual estates; costs more.",
             "rules_only": "no AI at all. Anything without a rule stays blank and waits for a person."}
STEPS = ["discover", "decide", "convert", "prove", "handover", "run"]
STAGES = [("understand", "Understand", "read, describe, plan"), ("build", "Build", "rules first, AI where none fits"), ("prove", "Prove", "review gates, numbers vs source"),
          ("package", "Package", "package and proof pack")]

db.register_schema("""
CREATE TABLE IF NOT EXISTS migbi_projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, source_version TEXT, target TEXT, target_version TEXT, read_from TEXT NOT NULL,
  mode TEXT NOT NULL, calls TEXT, status TEXT NOT NULL, created REAL NOT NULL, created_by TEXT, updated REAL, objects INTEGER NOT NULL DEFAULT 0,
  tenant TEXT NOT NULL DEFAULT 'default', budget_usd REAL NOT NULL DEFAULT 250);
CREATE TABLE IF NOT EXISTS migbi_reports (
  project TEXT NOT NULL, report TEXT NOT NULL, name TEXT, sub TEXT, wave INTEGER, status TEXT, stage TEXT, gates TEXT, proof TEXT,
  ai_calls INTEGER NOT NULL DEFAULT 0, ai_cost REAL NOT NULL DEFAULT 0, seconds REAL, checkpoint TEXT, proven INTEGER NOT NULL DEFAULT 0,
  accepted_by TEXT, accepted REAL, note TEXT, updated REAL, PRIMARY KEY (project, report));
CREATE TABLE IF NOT EXISTS migbi_lineage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, report TEXT NOT NULL, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
  detail TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS migbi_lineage_report ON migbi_lineage (project, report);
CREATE TABLE IF NOT EXISTS migbi_schedules (
  id TEXT PRIMARY KEY, project TEXT NOT NULL, report TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'drift', cadence TEXT NOT NULL DEFAULT 'nightly',
  active INTEGER NOT NULL DEFAULT 1, next_run REAL, last_run REAL, last_result TEXT, runs INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, created_by TEXT);
""")


class MigError(Exception):
    pass


# ------------------------------------------------------------------ files and rows

def _dir(mid: str) -> Path:
    try:
        return store.project_dir(mid)
    except KeyError:
        raise HTTPException(404, "No such migration.")


def _row(mid: str) -> dict:
    r = db.one("SELECT * FROM migbi_projects WHERE id = ?", (mid,))
    if not r:
        raise HTTPException(404, "No such migration.")
    return r


def _json(d: Path, name: str, default=None):
    f = d / name
    if not f.exists():
        return default
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return default


def _save_json(d: Path, name: str, data) -> None:
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o)), encoding="utf-8")
    tmp.replace(d / name)


def _estate(d: Path) -> dict | None:
    return _json(d, "estate.json")


def _note(mid: str, stage: str, text: str, level: str = "info", items=None) -> None:
    worker.app_note(mid, stage, text, level, items)


def _tenant() -> str:
    from . import registry
    b = registry.brand()
    return re.sub(r"[^a-z0-9]+", "-", (b.get("name") if b.get("partner") else "default").lower()).strip("-") or "default"


def rule_pack(tenant: str | None = None) -> rules.RulePack:
    t = tenant or _tenant()
    return rules.RulePack(store.ROOT / ".migbi" / f"rules-{t}.json", t)


def _user_name(uid: str | None) -> str:
    if not uid:
        return "agent"
    u = db.user(uid)
    return (u or {}).get("name") or uid


# ------------------------------------------------------------------ programmes

def create(body: dict, who: str | None) -> dict:
    source = (body.get("source") or "cognos").strip()
    if source not in READERS:
        raise HTTPException(400, "Choose a source tool from the list.")
    if READERS[source]["status"] != "available":
        raise HTTPException(400, f"{READERS[source]['label']} is next: its reader is not built yet.")
    target = (body.get("target") or "powerbi").strip()
    if target not in TARGETS:
        raise HTTPException(400, "Choose a target.")
    if TARGETS[target].get("next"):
        raise HTTPException(400, f"{TARGETS[target]['label']} is next: Power BI is the target in this release.")
    read_from = (body.get("read_from") or "sample").strip()
    if read_from not in ("server", "exports", "sample"):
        raise HTTPException(400, "Where the estate lives: a live server, exports or the sample estate.")
    if read_from == "server" and READERS[source]["server"] is None:
        raise HTTPException(400, f"{READERS[source]['label']} has no live-server reader yet: upload exports instead.")
    if read_from == "sample" and source != "cognos":
        raise HTTPException(400, "The sample estate is an IBM Cognos Analytics estate.")
    mode = (body.get("mode") or "rules_first").strip()
    if mode not in MODES:
        raise HTTPException(400, "Conversion mode: rules first, AI-led or rules only.")
    calls = "batch" if body.get("calls") == "batch" else "live"
    visuals = (body.get("visuals") or "relay").strip()
    if visuals not in ("relay", "builtin"):
        raise HTTPException(400, "Target visuals: relay (Visual Atlas) or builtin (Power BI's own visuals).")
    name = (body.get("name") or "").strip()[:80] or f"{READERS[source]['label']} to {TARGETS[target]['label']}"
    mid = "mig-" + pysecrets.token_hex(4)
    d = store.ROOT / mid
    (d / "source").mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.save({"id": mid, "kind": "migbi", "name": name, "prompt": f"Migrate BI: {name}", "status": "new", "created": now, "versions": [], "runs": [], "job": None, "error": None,
                "files": [], "images": [], "migbi": {"source": source, "source_version": body.get("source_version") or "", "target": target, "target_version": body.get("target_version") or "",
                                                     "read_from": read_from, "mode": mode, "calls": calls, "visuals": visuals,
                                                     "scope": {"usage": True, "team": True, "views": True, "personal": read_from != "server"}},
                "scan": {"state": "idle", "pct": 0}, "connection": {}})
    db.add_project(mid, who or db.ADMIN_ID, visibility="org")        # a programme is the team's work: everyone may read it, BI Devs act
    db.run("INSERT INTO migbi_projects (id, name, source, source_version, target, target_version, read_from, mode, calls, status, created, created_by, updated, tenant) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)", (mid, name, source, body.get("source_version") or "", target, body.get("target_version") or "", read_from, mode, calls, now, who, now, _tenant()))
    (d / "request.md").write_text(f"# {name}\n\nMigrate BI programme: {READERS[source]['label']} {TARGETS[target]['label']}, read from {read_from}, mode {MODES[mode]}.\n", encoding="utf-8")
    db.audit("migbi.create", mid, {"name": name, "source": source, "target": target, "read_from": read_from, "mode": mode}, who)
    _note(mid, "discover", f"Programme created: {READERS[source]['label']} {TARGETS[target]['label']}, {MODES[mode].lower()}, read from "
          f"{'the sample estate' if read_from == 'sample' else 'exports' if read_from == 'exports' else 'a live server'}.")
    return get(mid)


def _status(mid: str, status: str) -> None:
    db.run("UPDATE migbi_projects SET status = ?, updated = ? WHERE id = ?", (status, time.time(), mid))


def projects(u: dict | None) -> list[dict]:
    rows = db.q("SELECT * FROM migbi_projects ORDER BY created DESC")
    out = []
    for r in rows:
        if u and not auth.can_project(u, "view", db.project(r["id"])):
            continue
        out.append({**r, "source_label": READERS.get(r["source"], {}).get("label", r["source"]), "target_label": TARGETS.get(r["target"], {}).get("label", r["target"]),
                    "mode_label": MODES.get(r["mode"], r["mode"]), "status_label": STATUS_LABEL.get(r["status"], r["status"])})
    return out


STATUS_LABEL = {"new": "New", "connected": "Connected", "scanning": "Discovering", "scan_paused": "Paused", "scan_stopped": "Stopped", "discovered": "Discovered", "decided": "Decided",
                "converting": "Converting", "proven": "Proven", "handed": "Handed over", "running": "Running", "error": "Needs attention"}


def _step_state(mid: str, st: dict, row: dict, est: dict | None, reports: list[dict], waves: list[dict], decisions: dict | None) -> dict:
    counts = model.counts(est) if est else None
    conv_done = [r for r in reports if r["status"] in ("converted", "proven", "accepted")]
    proven = [r for r in reports if r["proven"]]
    handed = [w for w in waves if (w.get("handover") or {}).get("accepted")]
    scan = st.get("scan") or {}
    sub = {"discover": (f"{counts['objects']:,} objects found" if counts else f"scanning - {scan.get('pct', 0)} %" if scan.get("state") == "running" else "paused" if scan.get("state") == "paused"
                        else "connected" if st.get("connection", {}).get("ok") or st["migbi"]["read_from"] == "sample" else "where the estate lives"),
           "decide": (f"{decisions['counts']['keep']:,} to keep - {decisions['counts']['retire']:,} to retire" if decisions and decisions.get("applied") else "set your rules" if est else ""),
           "convert": (f"wave {waves[-1]['n']} - {len(waves[-1]['reports'])} selected" if waves else "pick a wave" if decisions and decisions.get("applied") else ""),
           "prove": f"{len(proven)} of {len(reports)} proven" if reports else "", "handover": "pack sent" if handed else "pack and sign-off" if conv_done else "",
           "run": f"{len(db.q('SELECT id FROM migbi_schedules WHERE project = ? AND active = 1', (mid,)))} nightly checks" if handed else "after go-live"}
    done = {"discover": bool(est), "decide": bool(decisions and decisions.get("applied")), "convert": bool(waves) and all(r["status"] not in ("queued", "converting") for r in reports) and bool(reports),
            "prove": bool(reports) and all(r["proven"] for r in reports), "handover": bool(handed), "run": False}
    return {"sub": sub, "done": done}


def get(mid: str) -> dict:
    d = _dir(mid)
    st = store.load(mid)
    row = _row(mid)
    est = _estate(d)
    reports = report_rows(mid)
    waves = _json(d, "waves.json", [])
    decisions = _json(d, "decisions.json")
    counts = model.counts(est) if est else None
    preds = _json(d, "predictions.json") or {}
    ready = {"auto": 0, "review": 0, "no": 0}
    for p in preds.values():
        ready[p["convert"]] = ready.get(p["convert"], 0) + 1
    u = auth.current.get()
    out = {"id": mid, "name": row["name"], "status": row["status"], "status_label": STATUS_LABEL.get(row["status"], row["status"]), "created": row["created"], "created_by": row["created_by"],
           "source": row["source"], "source_label": READERS[row["source"]]["label"], "source_version": row["source_version"], "target": row["target"], "target_label": TARGETS[row["target"]]["label"],
           "target_version": row["target_version"], "read_from": row["read_from"], "mode": row["mode"], "mode_label": MODES[row["mode"]], "mode_help": MODE_HELP[row["mode"]], "calls": row["calls"],
           "budget_usd": row["budget_usd"], "tenant": row["tenant"], "terms": model.TOOLS.get(row["source"], {}).get("terms", ""), "sample": row["read_from"] == "sample",
           "scan": st.get("scan") or {"state": "idle", "pct": 0}, "connection": {k: v for k, v in (st.get("connection") or {}).items() if k not in ("secret",)}, "scope": st["migbi"].get("scope"), "visuals": st["migbi"].get("visuals") or "relay",
           "job": st.get("job"), "project_status": st.get("status"), "error": st.get("error"), "counts": counts, "ready": ready if preds else None,
           "estate": {"read_at": est.get("read_at"), "read_seconds": est.get("read_seconds"), "problems": (est.get("problems") or [])[:20], "n_problems": len(est.get("problems") or []),
                      "usage": est.get("usage"), "version": est["source"].get("version")} if est else None,
           "decisions": {"applied": decisions.get("applied"), "counts": decisions.get("counts"), "before": decisions.get("before"), "after": decisions.get("after"), "kept_groups": decisions.get("kept_groups"),
                         "rules": decisions.get("rules"), "overrides": len(decisions.get("overrides") or {}), "checkpoint": decisions.get("checkpoint")} if decisions else None,
           "waves": waves, "reports": reports, "steps": _step_state(mid, st, row, est, reports, waves, decisions), "can_edit": bool(u and auth.is_dev(u)),
           "ai": {"calls": sum(r["ai_calls"] for r in reports), "cost_usd": round(sum(r["ai_cost"] for r in reports), 2), "budget_usd": row["budget_usd"]},
           "rule_pack": rule_pack(row["tenant"]).stats(), "worker": {"running": worker.current.get("pid") if worker.current else None, "waiting": worker.waiting()},
           "schedules": [dict(s) for s in db.q("SELECT * FROM migbi_schedules WHERE project = ? ORDER BY created", (mid,))]}
    out["current_step"] = _current_step(out)
    return out


def _current_step(p: dict) -> str:
    done = p["steps"]["done"]
    for s in STEPS:
        if not done.get(s):
            return s
    return "run"


def report_rows(mid: str) -> list[dict]:
    rows = db.q("SELECT * FROM migbi_reports WHERE project = ? ORDER BY wave, updated", (mid,))
    out = []
    for r in rows:
        r = dict(r)
        for k in ("gates", "proof"):
            try:
                r[k] = json.loads(r[k]) if r.get(k) else None
            except ValueError:
                r[k] = None
        r["proven"] = bool(r["proven"])
        r["status_label"] = REPORT_STATUS.get(r["status"], r["status"])
        r["accepted_by_name"] = _user_name(r["accepted_by"]) if r.get("accepted_by") else None     # signed by name on the screens
        out.append(r)
    return out


REPORT_STATUS = {"queued": "Queued", "converting": "Converting", "converted": "Converted", "proven": "Proven", "accepted": "Proven - accepted", "sent_back": "Sent back", "error": "Needs attention",
                 "gates_failed": "Gates failed", "open_items": "Open items"}


# ------------------------------------------------------------------ Discover: connect, upload, test, scan

def _secret_name(mid: str) -> str:
    return f"migbi:{mid}:secret"


def connect(mid: str, body: dict, who: str | None) -> dict:
    """Save where the estate lives (server URL, namespace, user, what to scan); the password / API key is kept in the
    secrets store by name and never returned."""
    st = store.load(mid)
    conn = st.get("connection") or {}
    for k in ("url", "namespace", "user", "sign_in", "folders"):
        if k in body and body[k] is not None:
            conn[k] = str(body[k]).strip()[:300]
    if body.get("secret"):
        secrets_store.put("org", _secret_name(mid), str(body["secret"]), who)
        conn["has_secret"] = True
    for k in ("page_size", "max_rps", "usage_days"):
        if body.get(k) is not None:
            try:
                conn[k] = max(1, int(body[k]))
            except (TypeError, ValueError):
                pass
    scope = st["migbi"].get("scope") or {}
    for k in ("usage", "team", "views", "personal"):
        if k in (body.get("scope") or {}):
            scope[k] = bool(body["scope"][k])
    st["migbi"]["scope"] = scope
    conn["ok"] = False
    store.save({**st, "connection": conn})
    db.audit("migbi.connect", mid, {"url": conn.get("url"), "user": conn.get("user"), "secret": "stored" if body.get("secret") else "kept", "scope": scope}, who)
    return get(mid)


def _reader_for(mid: str, st: dict, row: dict):
    """The reader for this programme's source and read-from; for a live server the thin client."""
    d = store.project_dir(mid)
    src = d / "source"
    if row["read_from"] == "server":
        conn = st.get("connection") or {}
        secret = secrets_store.get("org", _secret_name(mid)) or ""
        if not conn.get("url"):
            raise MigError("Give the server's URL first.")
        return cognos.CognosRest(conn["url"], conn.get("user") or "", secret, conn.get("namespace") or "", page_size=int(conn.get("page_size") or PAGE_SIZE),
                                 max_rps=float(conn.get("max_rps") or 4), timeout=30)
    cls = READERS[row["source"]]["exports"]
    if row["read_from"] == "sample":
        if not (src / "content.csv").exists():
            raise MigError("The sample estate is written when the scan starts.")
        return cls(src, page_size=PAGE_SIZE)
    archive = next(iter(sorted(src.glob("*.zip"))), None)
    folder = src / "extracted" if (src / "extracted").is_dir() else src
    if not archive and not any(folder.rglob("*")):
        raise MigError("Upload the exports (a deployment archive or the export folder) first.")
    return cls(folder if any(folder.rglob("*")) and (folder / "content.csv").exists() or not archive else archive, page_size=PAGE_SIZE, version=row["source_version"])


def test(mid: str, who: str | None) -> dict:
    st, row = store.load(mid), _row(mid)
    try:
        if row["read_from"] == "sample":
            src = store.project_dir(mid) / "source"
            if not (src / "content.csv").exists():
                sample_estate.generate(src, seed=42, objects=1842)
            out = cognos.CognosExports(src).test()
            out["sample"] = True
        else:
            rd = _reader_for(mid, st, row)
            out = rd.test()
            if hasattr(rd, "close"):
                rd.close()
    except (MigError, cognos.ReadError) as e:
        st["connection"] = {**(st.get("connection") or {}), "ok": False, "error": str(e)[:300]}
        store.save(st)
        _note(mid, "discover", f"Connection test failed: {e}", "error")
        return {"ok": False, "error": str(e), "sign_in": isinstance(e, cognos.SignInAgain)}
    except Exception as e:  # noqa: BLE001 - shown plainly
        traceback.print_exc()
        return {"ok": False, "error": f"The test did not finish: {e.__class__.__name__}: {str(e)[:200]}"}
    st["connection"] = {**(st.get("connection") or {}), "ok": True, "error": None, "info": out, "tested": time.time()}
    store.save(st)
    if row["status"] == "new":
        _status(mid, "connected")
    db.audit("migbi.test", mid, {"ok": True, "objects": out.get("objects")}, who)
    _note(mid, "discover", f"Connection test passed: {out.get('product', '')} {out.get('version', '')}, {out.get('objects') or '?'} objects, "
          f"{'usage ' + str(out.get('usage_days')) + ' days' if out.get('usage_days') else 'no usage source'} - {out.get('permissions', '')}".strip(), "ok")
    return {"ok": True, **out}


async def upload(mid: str, files: list[UploadFile], who: str | None) -> dict:
    d = store.project_dir(mid)
    src = d / "source"
    saved = []
    for f in files:
        name = re.sub(r"[^\w.\- ]+", "_", Path(f.filename or "export").name).strip(" ._") or "export"
        path = src / name
        data = await f.read()
        if len(data) > 400 * 1024 * 1024:
            raise HTTPException(413, f"{name} is bigger than 400 MB.")
        path.write_bytes(data)
        saved.append({"name": name, "bytes": len(data)})
        if name.lower().endswith(".zip"):
            out = src / "extracted"
            shutil.rmtree(out, ignore_errors=True)
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    n = info.filename.replace("\\", "/")
                    if n.startswith("/") or ".." in n.split("/"):
                        continue
                    z.extract(info, out)
            inner = [p for p in out.iterdir() if p.is_dir()]
            if not (out / "content.csv").exists() and len(inner) == 1 and (inner[0] / "content.csv").exists():
                for p in inner[0].iterdir():
                    shutil.move(str(p), str(out / p.name))
    st = store.load(mid)
    st["files"] = (st.get("files") or []) + saved
    store.save(st)
    db.audit("migbi.upload", mid, {"files": [s["name"] for s in saved]}, who)
    _note(mid, "discover", "Exports received: " + ", ".join(f"{s['name']} ({s['bytes'] // 1024} KB)" for s in saved), "ok")
    return {"files": saved}


async def _job_scan(mid: str, args: dict) -> None:
    """Read the estate page by page with live activity; pause / resume / stop; resume from the cursor on Retry."""
    d = store.project_dir(mid)
    st, row = store.load(mid), _row(mid)
    src = d / "source"
    scope = st["migbi"].get("scope") or {}
    resume = bool(args.get("resume")) and (d / "estate.partial.json").exists()
    scan = {"state": "running", "pct": 0, "phase": "starting", "found": {}, "started": time.time(), "paused": False, "stop": False, "cursor": (st.get("scan") or {}).get("cursor") if resume else None,
            "waits": 0}
    store.update(mid, scan=scan)
    _status(mid, "scanning")
    partial = (_json(d, "estate.partial.json") if resume else None) or model.new_estate(row["source"], row["source_version"], row["read_from"])

    def flush(**kw):
        cur = store.load(mid)
        s = {**(cur.get("scan") or {}), **kw}
        store.update(mid, scan=s)
        return s

    def progress(ev: dict):
        text = ev.get("text") or ""
        level = ev.get("level") or "info"
        if ev.get("phase") == "wait":
            flush(waits=(store.load(mid).get("scan") or {}).get("waits", 0) + 1)
            _note(mid, "discover", text, "warn")
            return
        if text:
            _note(mid, "discover", text, "warn" if level == "warn" else "ok" if ev.get("phase") == "done" else "info")
        flush(pct=ev.get("pct", 0), phase=ev.get("phase"), page=ev.get("page"), pages=ev.get("pages"), found={**((store.load(mid).get("scan") or {}).get("found") or {}), **(ev.get("found") or {})},
              cursor=ev.get("cursor"))
        if SCAN_PACE_S:
            time.sleep(SCAN_PACE_S)

    def pause() -> bool:
        while True:
            s = store.load(mid).get("scan") or {}
            if s.get("stop"):
                return False
            if not s.get("paused"):
                return True
            if s.get("state") != "paused":
                flush(state="paused")
                _status(mid, "scan_paused")
                _note(mid, "discover", "Paused - the scan resumes from the same page, even after a restart.", "warn")
            time.sleep(0.5)

    try:
        if row["read_from"] == "sample":
            if not (src / "content.csv").exists():
                _note(mid, "discover", "Writing the sample estate (a made-up IBM Cognos Analytics estate: 1,842 objects, 2.5 years of usage, the data behind five packages)...")
                summary = await asyncio.to_thread(sample_estate.generate, src, 42, 1842)
                _note(mid, "discover", f"Sample estate ready: {summary['objects']:,} objects, {summary['datasets']} packages and data modules, {summary['runs']:,} audit runs.", "ok")
            reader = cognos.CognosExports(src, page_size=PAGE_SIZE)
        elif row["read_from"] == "server":
            client = _reader_for(mid, st, row)
            _note(mid, "discover", f"Session opened on {st.get('connection', {}).get('url')} (read-only). Nothing is ever changed on the server.")
            dl = src / "downloaded"
            if not resume or not (dl / "content.csv").exists():
                shutil.rmtree(dl, ignore_errors=True)
                await asyncio.to_thread(client.download, dl, progress, pause, {"personal": scope.get("personal", False), "usage": scope.get("usage", True)})
                for p in client.problems[:10]:
                    _note(mid, "discover", p, "warn")
            reader = cognos.CognosExports(dl, page_size=PAGE_SIZE)
        else:
            reader = _reader_for(mid, st, row)
        cursor = scan.get("cursor") if resume else None
        est = await asyncio.to_thread(reader.read, progress, pause, cursor, partial)
        if hasattr(reader, "close"):
            reader.close()
    except cognos.Stopped as e:
        _save_json(d, "estate.partial.json", partial)           # the reader filled this very dict up to the cursor
        flush(state="stopped", cursor=e.cursor)
        _status(mid, "scan_stopped")
        store.update(mid, status="error", error=f"Stopped: {e}. Press Resume to carry on from the same page, or start the scan again.", job=None)
        _note(mid, "discover", f"Stopped - {e}. Objects read so far are kept.", "warn")
        return
    except (MigError, cognos.ReadError) as e:
        flush(state="error")
        _status(mid, "error")
        raise RuntimeError(str(e))
    model.save(d / "estate.json", est)
    (d / "estate.partial.json").unlink(missing_ok=True)
    preds = {r["id"]: rules.predict(r, model.dataset_of(est, r), rule_pack(row["tenant"])) for r in est["reports"]}
    _save_json(d, "predictions.json", preds)
    pairs = await asyncio.to_thread(dec.similarity_pairs, est)
    _save_json(d, "similarity.json", pairs)
    c = model.counts(est)
    auto = sum(1 for p in preds.values() if p["convert"] == "auto")
    flush(state="done", pct=100, finished=time.time(), seconds=round(time.time() - scan["started"], 1))
    db.run("UPDATE migbi_projects SET objects = ?, status = 'discovered', updated = ? WHERE id = ?", (c["objects"], time.time(), mid))
    store.update(mid, status="discovered", job=None, error=None)
    _note(mid, "discover", f"What we found: {c['objects']:,} objects - {c['used_90']:,} used in 90 days - {auto:,} ready to convert ({round(100 * auto / max(1, c['objects']))} %) - "
          f"{c['shared_objects']} shared objects - {c['missing_dataset']} point to missing packages.", "ok")
    db.audit("migbi.scan", mid, {"objects": c["objects"], "seconds": round(time.time() - scan["started"], 1), "auto": auto}, None)


worker.register_job("migbi_scan", _job_scan, status="scanning", done="Estate discovered")


def start_scan(mid: str, who: str | None, resume: bool = False) -> dict:
    st, row = store.load(mid), _row(mid)
    if (st.get("scan") or {}).get("state") == "running":
        raise HTTPException(409, "The scan is already running.")
    if row["read_from"] != "sample" and not (st.get("connection") or {}).get("ok"):
        raise HTTPException(409, "Test the connection (or upload the exports) first.")
    store.update(mid, scan={**(st.get("scan") or {}), "paused": False, "stop": False, "state": "queued"})
    worker.enqueue(mid, "migbi_scan", resume=resume)
    db.audit("migbi.scan.start", mid, {"resume": resume}, who)
    return get(mid)


def scan_control(mid: str, action: str, who: str | None) -> dict:
    st = store.load(mid)
    s = st.get("scan") or {}
    if action == "pause":
        if s.get("state") not in ("running", "queued"):
            raise HTTPException(409, "Nothing is scanning.")
        s["paused"] = True
    elif action == "resume":
        if s.get("state") in ("paused", "running"):
            s["paused"] = False; s["state"] = "running"
            _status(mid, "scanning")
            _note(mid, "discover", "Resumed.", "ok")
        else:
            store.update(mid, scan=s)
            return start_scan(mid, who, resume=True)
    elif action == "stop":
        if s.get("state") not in ("running", "paused", "queued"):
            raise HTTPException(409, "Nothing is scanning.")
        s["stop"] = True; s["paused"] = False
        if s.get("state") == "queued":
            worker.stop(mid)
    else:
        raise HTTPException(400, "pause, resume or stop")
    store.update(mid, scan=s)
    db.audit(f"migbi.scan.{action}", mid, None, who)
    return get(mid)


def inventory(mid: str, decision: str | None = None, type_: str | None = None, used: str | None = None, q: str | None = None, page: int = 0, per: int = 25,
              convert: str | None = None, folder: str | None = None) -> dict:
    d = _dir(mid)
    est = _estate(d)
    if not est:
        return {"rows": [], "total": 0, "page": 0, "pages": 0}
    preds = _json(d, "predictions.json") or {}
    decisions = (_json(d, "decisions.json") or {}).get("result") or {}
    rows = model.inventory_rows(est, preds)
    qq = (q or "").lower()
    out = []
    for r in rows:
        dcs = decisions.get(r["id"]) or {}
        r["decision"] = dcs.get("decision"); r["decision_reason"] = dcs.get("reason"); r["merged_into"] = dcs.get("merged_into")
        if decision and decision != "all" and r["decision"] != decision:
            continue
        if type_ and type_ != "all" and r["type"] != type_:
            continue
        if convert and convert != "all" and r.get("convert") != convert:
            continue
        if folder and folder != "all" and not r["folder"].startswith(folder):
            continue
        if used == "90" and not (r["last_run_days"] is not None and r["last_run_days"] <= 90):
            continue
        if used == "never" and r["last_run_days"] is not None:
            continue
        if qq and qq not in r["name"].lower() and qq not in r["folder"].lower():
            continue
        out.append(r)
    out.sort(key=lambda r: -(r["runs_365"] or 0))
    pages = max(1, -(-len(out) // per))
    page = max(0, min(page, pages - 1))
    return {"rows": out[page * per:(page + 1) * per], "total": len(out), "page": page, "pages": pages, "types": sorted({r["type"] for r in rows}),
            "folders": sorted({r["folder"].split("/")[0] + ("/" + r["folder"].split("/")[1] if r["folder"].startswith("Team content/") else "") for r in rows})}


def object_detail(mid: str, rid: str) -> dict:
    d = _dir(mid)
    est = _estate(d)
    if not est:
        raise HTTPException(404, "No estate yet.")
    r = model.by_id(est).get(rid)
    if not r:
        raise HTTPException(404, "No such object.")
    preds = _json(d, "predictions.json") or {}
    decisions = (_json(d, "decisions.json") or {}).get("result") or {}
    ds = model.dataset_of(est, r)
    conv_row = db.one("SELECT * FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    return {"report": {k: r[k] for k in r if k not in ("queries", "pages")}, "queries": r["queries"], "pages": r["pages"], "prompts": r.get("prompts"),
            "dataset": {"id": ds["id"], "name": ds["name"], "kind": ds["kind"], "tables": [t["name"] for t in ds["tables"]], "has_data": ds.get("has_data")} if ds else None,
            "prediction": preds.get(rid), "decision": decisions.get(rid), "last_used": model.last_used_bucket(r), "conversion": dict(conv_row) if conv_row else None,
            "lineage": [dict(x) for x in db.q("SELECT * FROM migbi_lineage WHERE project = ? AND report = ? ORDER BY id", (mid, rid))]}


# ------------------------------------------------------------------ Decide

def decide_state(mid: str) -> dict:
    d = _dir(mid)
    est = _estate(d)
    if not est:
        return {"estate": False}
    saved = _json(d, "decisions.json") or {}
    rules_ = saved.get("rules") or dec.DEFAULTS
    pv = _preview(d, est, rules_, saved.get("overrides"))
    return {"estate": True, **pv, "applied": saved.get("applied"), "overrides": saved.get("overrides") or {}, "checkpoint": saved.get("checkpoint"), "labels": dec.LABELS}


def _preview(d: Path, est: dict, rules_: dict | None, overrides: dict | None) -> dict:
    preds = _json(d, "predictions.json") or {}
    pairs = _json(d, "similarity.json") or []
    pv = dec.preview(est, rules_, pairs, preds, overrides)
    top = {k: dec.top_rows(est, pv, k, 8) for k in dec.LABELS}
    return {"rules": pv["rules"], "defaults": pv["defaults"], "changed": pv["changed"], "counts": pv["counts"], "kept_groups": pv["kept_groups"], "before": pv["before"], "after": pv["after"],
            "reduction_pct": pv["reduction_pct"], "top": top, "_decisions": pv["decisions"]}


def preview(mid: str, rules_: dict | None) -> dict:
    d = _dir(mid)
    est = _estate(d)
    if not est:
        raise HTTPException(409, "Discover the estate first.")
    saved = _json(d, "decisions.json") or {}
    pv = _preview(d, est, rules_, saved.get("overrides"))
    pv.pop("_decisions", None)
    return pv


def override(mid: str, rid: str, decision: str, note: str | None, who: str) -> dict:
    d = _dir(mid)
    est = _estate(d)
    if not est or rid not in model.by_id(est):
        raise HTTPException(404, "No such object.")
    if decision not in ("keep", "retire", "review"):
        raise HTTPException(400, "Keep, retire or needs a decision.")
    saved = _json(d, "decisions.json") or {}
    ov = saved.setdefault("overrides", {})
    ov[rid] = {"decision": decision, "by": _user_name(who), "by_id": who, "at": time.time(), "note": (note or "").strip()[:300]}
    if saved.get("applied"):                                   # the decisions moved on: recompute the applied result with the new call
        pv = _preview(d, est, saved.get("rules"), ov)
        saved["result"] = pv.pop("_decisions"); saved["counts"] = pv["counts"]; saved["before"] = pv["before"]; saved["after"] = pv["after"]; saved["kept_groups"] = pv["kept_groups"]
    _save_json(d, "decisions.json", saved)
    db.audit("migbi.decide.override", mid, {"report": rid, "decision": decision, "note": (note or "")[:200]}, who)
    return {"ok": True, "override": ov[rid], "name": model.by_id(est)[rid]["name"]}


def _decide_evidence(pv: dict, rules_: dict, est: dict, who: str) -> dict:
    c = pv["counts"]
    return {"summary": f"Rules applied by {who}: keep {c['keep']:,} - merge {c['merge']:,} into {pv['kept_groups']} - retire {c['retire']:,} - needs a decision {c['review']:,}; "
                       f"{pv['before']:,} objects today {pv['after']:,} to look after (-{pv['reduction_pct']} %)",
            "columns": ["Rule", "Value", "Default"], "rows": [[k, str(rules_[k]), str(dec.DEFAULTS[k])] for k in dec.DEFAULTS],
            "items": [f"Retire: not run for {rules_['retire_days']} days; never run and older than {rules_['never_age']} days; personal folders: {rules_['personal']}" + (f"; never when owned by {rules_['protect']}" if rules_['protect'] else ""),
                      f"Merge: at least {rules_['sim_pct']} % the same (dataset {rules_['w_dataset']} - attributes {rules_['w_attr']} - metrics {rules_['w_metric']} - filters {rules_['w_filter']}), keep the {rules_['keep']}",
                      f"Needs a decision: failed in the last {rules_['review_days']} days, or used but not convertible, or its package is missing"],
            "counts": {"keep": c["keep"], "merge": c["merge"], "retire": c["retire"], "needs a decision": c["review"]}, "before": pv["before"], "after": pv["after"]}


def apply_rules(mid: str, rules_: dict | None, who: str, ask_queue: bool = False) -> dict:
    """Save the decisions and sign them: a checkpoint of kind migbi.decide is opened and - unless the person asks the
    queue to look - accepted in the same signed step."""
    d = _dir(mid)
    est = _estate(d)
    if not est:
        raise HTTPException(409, "Discover the estate first.")
    saved = _json(d, "decisions.json") or {}
    pv = _preview(d, est, rules_, saved.get("overrides"))
    result = pv.pop("_decisions")
    saved.update(rules=pv["rules"], counts=pv["counts"], before=pv["before"], after=pv["after"], kept_groups=pv["kept_groups"], reduction_pct=pv["reduction_pct"], result=result,
                 proposed={"by": _user_name(who), "by_id": who, "at": time.time()})
    name = f"Decide what to keep: {pv['counts']['keep']:,} keep - {pv['counts']['merge']:,} merge - {pv['counts']['retire']:,} retire - {pv['counts']['review']:,} need a decision"
    checkpoints.withdraw(KIND_DECIDE, mid, who=who)
    c = checkpoints.open(KIND_DECIDE, mid, MODULE, name, "table", _decide_evidence(pv, pv["rules"], est, _user_name(who)), link=f"{ROUTE}/{mid}/decide", agent="Decide", opened_by=who)
    saved["checkpoint"] = c["id"]
    saved.pop("applied", None)
    _save_json(d, "decisions.json", saved)
    if not ask_queue:
        c = checkpoints.decide(c["id"], "accept", who)
    db.audit("migbi.decide.apply", mid, {"counts": pv["counts"], "checkpoint": c["id"], "signed": not ask_queue}, who)
    return decide_state(mid)


def _on_decide(c: dict, decision: str, comment: str | None, who: str) -> None:
    mid = c["subject"]
    try:
        d = store.project_dir(mid)
    except KeyError:
        return
    saved = _json(d, "decisions.json") or {}
    if decision == "accept":
        saved["applied"] = {"by": _user_name(who), "by_id": who, "at": time.time(), "checkpoint": c["id"]}
        _save_json(d, "decisions.json", saved)
        _status(mid, "decided")
        store.update(mid, status="decided")
        _note(mid, "decide", f"Decisions signed by {_user_name(who)}: {saved['counts']['keep']:,} to keep, {saved['counts']['merge']:,} to merge, "
              f"{saved['counts']['retire']:,} to retire, {saved['counts']['review']:,} need a decision.", "ok")
    else:
        saved["sent_back"] = {"by": _user_name(who), "at": time.time(), "comment": (comment or "")[:500]}
        saved.pop("applied", None)
        _save_json(d, "decisions.json", saved)
        _note(mid, "decide", f"Decisions sent back by {_user_name(who)}: {comment}", "warn")


checkpoints.register_kind(KIND_DECIDE, "Migrate BI: decisions", _on_decide)


# ------------------------------------------------------------------ Convert: waves and the conversion job

def _minutes_by_complexity(mid: str) -> dict:
    """Estimates from this install's own completed conversions when it has them, else the defaults."""
    out = dict(MINUTES)
    rows = db.q("SELECT r.seconds, r.report, r.project FROM migbi_reports r WHERE r.seconds IS NOT NULL AND r.status IN ('converted', 'proven', 'accepted')")
    by: dict[str, list[float]] = {}
    for r in rows:
        try:
            est = _estate(store.project_dir(r["project"]))
            rep = model.by_id(est).get(r["report"]) if est else None
        except KeyError:
            rep = None
        if rep:
            by.setdefault(rep["complexity"], []).append(r["seconds"] / 60)
    for k, v in by.items():
        if len(v) >= 2:
            out[k] = round(sum(v) / len(v), 1)
    return out


def estimate(mid: str, report_ids: list[str]) -> dict:
    d = _dir(mid)
    est = _estate(d)
    if not est:
        raise HTTPException(409, "Discover the estate first.")
    preds = _json(d, "predictions.json") or {}
    row = _row(mid)
    by = model.by_id(est)
    mins = _minutes_by_complexity(mid)
    picked = [by[i] for i in report_ids if i in by]
    calls = sum(preds.get(r["id"], {}).get("no_rule", 0) for r in picked) if row["mode"] != "rules_only" else 0
    if row["mode"] == "ai_led":
        calls += len(picked)
    ds = {model.dataset_of(est, r)["name"]: model.dataset_of(est, r)["kind"] for r in picked if model.dataset_of(est, r)}
    spent = round(sum(r["ai_cost"] for r in report_rows(mid)), 2)
    cost = round(calls * COST_PER_CALL, 2)
    return {"reports": len(picked), "minutes": round(sum(mins.get(r["complexity"], 5) for r in picked)), "ai_calls": calls, "ai_cost_usd": cost, "budget_usd": row["budget_usd"],
            "spent_usd": spent, "over_budget": spent + cost > row["budget_usd"], "datasets": [{"name": k, "kind": v} for k, v in ds.items()],
            "not_convertible": [{"id": r["id"], "name": r["name"], "reason": preds.get(r["id"], {}).get("reason")} for r in picked if preds.get(r["id"], {}).get("convert") == "no"],
            "retired": [r["id"] for r in picked if ((_json(d, "decisions.json") or {}).get("result") or {}).get(r["id"], {}).get("decision") in ("retire", "merge")],
            "minutes_by_complexity": mins, "cost_per_call": COST_PER_CALL}


def _sub_id(mid: str, report: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", report["name"].lower()).strip("-")[:30] or "report"
    sid = f"{mid}-{slug}"
    k = 2
    while (store.ROOT / sid / "project.json").exists() and (store.load(sid).get("migbi") or {}).get("report") != report["id"]:
        sid = f"{mid}-{slug}-{k}"; k += 1
    return sid


def create_wave(mid: str, name: str | None, report_ids: list[str], who: str | None) -> dict:
    d = _dir(mid)
    est = _estate(d)
    row = _row(mid)
    if not est:
        raise HTTPException(409, "Discover the estate first.")
    decisions = _json(d, "decisions.json") or {}
    if not decisions.get("applied"):
        raise HTTPException(409, "Decide what to keep first (the decisions must be signed).")
    by = model.by_id(est)
    result = decisions.get("result") or {}
    picked = [by[i] for i in dict.fromkeys(report_ids) if i in by]
    if not picked:
        raise HTTPException(400, "Pick at least one object to convert.")
    blocked = [r["name"] for r in picked if result.get(r["id"], {}).get("decision") in ("retire", "merge")]
    if blocked:
        raise HTTPException(409, "Retired and merged objects stay on record and are never converted: " + ", ".join(blocked[:5]))
    nodata = [r["name"] for r in picked if not (model.dataset_of(est, r) or {}).get("has_data")]
    if nodata:
        raise HTTPException(409, "No source data to build and prove these reports (their package has no data files): " + ", ".join(nodata[:5]))
    e = estimate(mid, [r["id"] for r in picked])
    if e["over_budget"]:
        raise HTTPException(409, f"This wave would take the AI cost past the budget ({e['spent_usd'] + e['ai_cost_usd']:.2f} of {e['budget_usd']:.2f} USD). Raise the budget or pick fewer reports.")
    waves = _json(d, "waves.json", [])
    n = len(waves) + 1
    wave = {"n": n, "name": (name or f"Wave {n}").strip()[:60], "reports": [r["id"] for r in picked], "created": time.time(), "created_by": who, "estimate": e, "status": "converting", "handover": None}
    waves.append(wave)
    _save_json(d, "waves.json", waves)
    _status(mid, "converting")
    store.update(mid, status="converting")
    for r in picked:
        _queue_convert(mid, r, n, who, None)
    db.audit("migbi.wave", mid, {"wave": n, "reports": len(picked), "estimate": {k: e[k] for k in ("minutes", "ai_calls", "ai_cost_usd")}}, who)
    _note(mid, "convert", f"{wave['name']}: {len(picked)} report(s) queued - about {e['minutes']} min, {e['ai_calls']} AI call(s) (≈ {e['ai_cost_usd']:.2f} USD) before anything runs.", "ok")
    return get(mid)


def _queue_convert(mid: str, report: dict, wave: int, who: str | None, comment: str | None) -> str:
    sid = _sub_id(mid, report)
    sd = store.ROOT / sid
    if not (sd / "project.json").exists():
        (sd / "data").mkdir(parents=True, exist_ok=True)
        store.save({"id": sid, "kind": "migbi_report", "name": report["name"], "prompt": f"Migrate BI: {report['name']}", "status": "queued", "created": time.time(), "versions": [], "runs": [],
                    "job": None, "error": None, "files": [], "images": [], "custom_visuals": "never", "migbi": {"project": mid, "report": report["id"], "wave": wave, "stage": None}})
        db.add_project(sid, who or db.ADMIN_ID, visibility="org")
    else:
        st = store.load(sid)
        st["migbi"] = {**(st.get("migbi") or {}), "wave": wave, "stage": None}
        store.save(st)
    now = time.time()
    db.run("INSERT OR REPLACE INTO migbi_reports (project, report, name, sub, wave, status, stage, gates, proof, ai_calls, ai_cost, seconds, checkpoint, proven, accepted_by, accepted, note, updated) "
           "VALUES (?, ?, ?, ?, ?, 'queued', NULL, NULL, NULL, COALESCE((SELECT ai_calls FROM migbi_reports WHERE project = ? AND report = ?), 0), "
           "COALESCE((SELECT ai_cost FROM migbi_reports WHERE project = ? AND report = ?), 0), NULL, NULL, 0, NULL, NULL, ?, ?)",
           (mid, report["id"], report["name"], sid, wave, mid, report["id"], mid, report["id"], (comment or "")[:500] or None, now))
    checkpoints.withdraw(KIND_PROVE, f"{mid}:{report['id']}", who=who)
    worker.enqueue(sid, "migbi_convert", migration=mid, report=report["id"], wave=wave, comment=comment)
    return sid


def _set_report(mid: str, rid: str, **kw) -> None:
    kw["updated"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in kw)
    db.run(f"UPDATE migbi_reports SET {cols} WHERE project = ? AND report = ?", tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in kw.values()) + (mid, rid))


def _stage(sid: str, mid: str, rid: str, stage: str, text: str) -> None:
    st = store.load(sid)
    st["migbi"] = {**(st.get("migbi") or {}), "stage": stage, "stage_since": time.time()}
    store.save(st)
    _set_report(mid, rid, stage=stage, status="converting")
    worker.app_note(sid, "convert", text)


async def _job_convert(sid: str, args: dict) -> None:
    """One report: Understand (rules) - Build (definition + the agent for the gaps) - Prove (gates with fix rounds,
    numbers vs source) - Package (PBIP). Runs in the sub-project folder so the agent, the gates and the DAX checker
    work exactly as they do for a dashboard."""
    mid, rid, wave = args["migration"], args["report"], args.get("wave")
    comment = args.get("comment")
    md = store.project_dir(mid)
    row = _row(mid)
    est = _estate(md)
    if not est:
        raise RuntimeError("The estate is gone: discover it again.")
    report = model.by_id(est).get(rid)
    if not report:
        raise RuntimeError(f"Report {rid} is not in the estate any more.")
    sd = store.project_dir(sid)
    t0 = time.time()
    pack = rule_pack(row["tenant"])
    # ---- Understand
    _stage(sid, mid, rid, "understand", f"Understand: reading \"{report['name']}\" - {len(report.get('queries') or [])} quer{'y' if len(report.get('queries') or []) == 1 else 'ies'}, "
           f"{sum(len(p.get('visuals') or []) for p in report.get('pages') or [])} visuals on {len(report.get('pages') or [])} page(s), {report['calculations']} calculations.")
    try:
        defn, plan = conv.build(est, report, pack, md / "source" / "data", mode=row["mode"], comment=comment,
                                visuals=(store.load(mid).get("migbi") or {}).get("visuals") or "relay")
    except rules.RuleError as e:
        raise RuntimeError(str(e))
    conv.write_project(sd, est, report, defn, plan, md / "source", mode=row["mode"], comment=comment)
    worker.refresh_files(sid)
    s = plan["summary"]
    worker.app_note(sid, "convert", f"Rules: {s['measures'] - plan['ai']} of {s['measures']} calculations, {s['columns'] + s['calculated_columns']} attributes, {s['filters']} slicer(s), "
                    f"{s['visuals']} of {s['visuals'] + s['unsupported']} visuals converted by {s['rules']} rule applications"
                    + (f"; {plan['ai']} calculation(s) for the agent" if plan["ai"] else "; the agent is not needed") + (f"; {s['unsupported']} not converted (a person decides)" if s["unsupported"] else "") + ".",
                    "ok", [f"{d}" for d in plan["decisions"][:40]])
    _record_lineage(mid, rid, plan)
    # ---- Build
    _stage(sid, mid, rid, "build", "Build: " + ("asking the agent for the calculations without a rule..." if plan["ai"] and row["mode"] != "rules_only" else "the rules wrote definition.yaml; no AI needed."))
    res, session = {}, None
    ai_gaps = [g for g in plan["gaps"] if g.get("kind") == "measure"] + [g for g in plan["gaps"] if g.get("kind") == "filter"]
    if row["mode"] != "rules_only" and (plan["ai"] or row["mode"] == "ai_led"):
        _budget_check(mid, row, len(ai_gaps) or 1)
        prompt = migrate_prompts.convert(report["name"], est["source"]["label"], ai_gaps, comment, ai_led=row["mode"] == "ai_led")
        res = await worker.agent(sid, "convert", prompt, worker.TURNS.get("migbi_convert", 80), "v1")
        session = res.get("session_id")
        _add_ai(mid, rid, res)
    # ---- Prove: the review gates (fix rounds), then numbers vs source
    _stage(sid, mid, rid, "prove", "Prove: running the review gates (definition, prototype, Power Query, data, DAX in Power BI's engine, report files, consistency, best practices, accessibility, display)...")
    found, info, problems = [], None, []
    for attempt in range(worker.FIX_ROUNDS + 1):
        problems, info, found = await asyncio.to_thread(worker._check_definition, sd, sid)
        if not problems or attempt == worker.FIX_ROUNDS or row["mode"] == "rules_only":
            break
        names = ", ".join(g["name"] for g in gates_mod.failed(found)) or "Values match the prototype"
        worker.app_note(sid, "convert", f"Review gates not passed ({names}): {len(problems)} problem(s) - the agent is fixing them.", "warn", problems)
        _budget_check(mid, row, 1)
        res = await worker.agent(sid, "convert", prompts.fix(problems, "definition"), worker.TURNS["fix"], "v1", resume=session)
        session = res.get("session_id") or session
        _add_ai(mid, rid, res)
    if info is None:
        _set_report(mid, rid, status="error", gates=gates_mod.compact(found), seconds=round(time.time() - t0, 1))
        raise RuntimeError(f"The converted definition does not validate ({len(problems)} problem(s)): " + "; ".join(problems[:4]))
    v = 1
    vdir = sd / "versions" / "v1"
    vdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sd / "definition.yaml", vdir / "definition.yaml")
    if (sd / "prototype" / "index.html").exists():
        shutil.copy2(sd / "prototype" / "index.html", vdir / "prototype.html")
    dax = info.pop("dax", None) or {}
    (vdir / "dax.json").write_text(json.dumps(dax), encoding="utf-8")
    (vdir / "gates.json").write_text(json.dumps(found), encoding="utf-8")
    info["dax"] = worker._dax_brief(dax)
    info["gates"] = gates_mod.compact(found)
    st = store.load(sid)
    st["versions"] = [{"v": v, "created": time.time(), "summary": res.get("text") or "Converted by Relay's rules.", "feedback": comment, "attachments": [], "problems": problems, **info}]
    store.save(st)
    bad = gates_mod.failed(found)
    pr = await asyncio.to_thread(proof_mod.prove, sd, est, report, plan, md / "source")
    _save_json(sd, "proof.json", pr)
    _save_json(sd, "plan.json", plan)
    dax_note = "DAX checked in Power BI's engine" if dax.get("checked") else f"DAX not checked ({dax.get('reason') or 'checker off'}) - the DAX gate is skipped, never passed"
    worker.app_note(sid, "convert", f"Numbers vs source: {pr['matched']:,} of {pr['compared']:,} numbers match across {len(pr['visuals'])} visuals"
                    + (f"; {pr['differences']} differ" if pr["differences"] else "") + (f"; {len(pr['open'])} measure(s) still open: {', '.join(pr['open'][:4])}" if pr["open"] else "") + f". {dax_note}.",
                    "warn" if pr["differences"] or pr["open"] or bad else "ok")
    # ---- Package
    _stage(sid, mid, rid, "package", "Package: writing the Power BI project (PBIP) and the proof pack...")
    packaged = None
    if not bad:
        try:
            packaged = await asyncio.to_thread(_package, sd, sid, found, dax, pr)
        except Exception as e:  # noqa: BLE001 - the package is a convenience; the report stays converted
            worker.app_note(sid, "convert", f"The package could not be written: {e}", "warn")
    status = "gates_failed" if bad else "open_items" if pr["open"] else "proven" if pr["proven"] else "converted"
    st = store.load(sid)
    st.update(status="converted", job=None, error=None, approved=None, output=packaged, migbi={**(st.get("migbi") or {}), "stage": "done", "proof": {k: pr[k] for k in ("compared", "matched", "differences", "proven", "open")}})
    store.save(st)
    _set_report(mid, rid, status=status, stage="done", gates=gates_mod.compact(found), proof={k: pr[k] for k in ("compared", "matched", "differences", "proven", "open", "skipped")},
                proven=1 if pr["proven"] else 0, seconds=round(time.time() - t0, 1))
    worker.app_note(sid, "convert", {"gates_failed": f"Converted, but {len(bad)} review gate(s) fail ({', '.join(g['name'] for g in bad)}): a person decides what next.",
                                     "open_items": f"Converted with {len(pr['open'])} open calculation(s) (no rule and no agent answer yet).",
                                     "proven": f"Proven: {pr['matched']:,} numbers match the source. Waiting for a person to accept the proof.",
                                     "converted": f"Converted; {pr['differences']} number(s) differ from the source - look at them before accepting."}[status], "ok" if status == "proven" else "warn",
                    gates_mod.problems(found) or None)
    _open_prove_checkpoint(mid, rid, report, pr, found, sid, plan)
    _update_wave_status(mid)
    db.audit("migbi.convert", f"{mid}:{rid}", {"status": status, "seconds": round(time.time() - t0, 1), "matched": pr["matched"], "compared": pr["compared"], "ai": plan["ai"]}, None)


worker.register_job("migbi_convert", _job_convert, status="converting", done="Report converted", llm=True, turns=80, timeout_s=2400)
worker.TURNS.setdefault("convert", 80)            # the agent stage name inside a conversion (worker.agent reads TURNS / TIMEOUT_S by stage)
worker.TIMEOUT_S.setdefault("convert", 2400)


def _budget_check(mid: str, row: dict, calls: int) -> None:
    spent = sum(r["ai_cost"] for r in report_rows(mid))
    if spent + calls * COST_PER_CALL > row["budget_usd"]:
        raise RuntimeError(f"The AI budget of this programme ({row['budget_usd']:.2f} USD) would be passed ({spent:.2f} spent). Raise it under Agents & AI, then Retry.")


def _add_ai(mid: str, rid: str, res: dict) -> None:
    cost = float(res.get("cost_usd") or 0)
    db.run("UPDATE migbi_reports SET ai_calls = ai_calls + 1, ai_cost = ai_cost + ?, updated = ? WHERE project = ? AND report = ?", (cost, time.time(), mid, rid))


def _package(sd: Path, sid: str, found: list[dict], dax: dict, pr: dict) -> dict:
    """The PBIP for a converted report: written into powerbi/ with the proof pack files and zipped. Never published
    anywhere; the hand-over pack carries it after the owner's sign-off."""
    use_project(sd)
    raw = definition.load(sd / "versions" / "v1" / "definition.yaml")
    from genbi_kit import validate as checks
    errors, dd = checks.definition_errors(raw, sd, check_sql=False)
    if errors:
        raise RuntimeError("; ".join(errors[:3]))
    dd["data"]["folder"] = (f"{worker.HOST_DIR}\\{sid}\\data\\" if worker.HOST_DIR else str(sd / "data") + "/")
    out, stage = sd / "powerbi", sd / ".publish"
    shutil.rmtree(stage, ignore_errors=True)
    pbip = report_builder.build(dd, catalog(), stage, visuals_dir=visuals_dir())
    (stage / "Review gates.txt").write_text(gates_mod.text_report(found, pbip.stem), encoding="utf-8")
    (stage / "Numbers vs source.txt").write_text(proof_text(pr, pbip.stem), encoding="utf-8")
    if (sd / "versions" / "v1" / "prototype.html").exists():
        shutil.copy2(sd / "versions" / "v1" / "prototype.html", stage / "Prototype.html")
    (stage / "README.txt").write_text(f"{pbip.stem} - converted by Relay (Migrate BI)\n\nOpen \"{pbip.name}\" in Power BI Desktop, then press Refresh. The model reads the CSVs "
                                      f"from the DataFolder parameter ({dd['data']['folder']}).\nReview gates.txt lists every check; Numbers vs source.txt the comparison with the source report"
                                      f"{'; the DAX was checked in Power BI own engine' if dax.get('checked') else '; the DAX check in Power BI engine was skipped (checker not running)'}.\n", encoding="utf-8")
    worker._move(stage, out)
    pbip = out / pbip.name
    zpath = sd / f"{pbip.stem}.zip"
    with zipfile.ZipFile(zpath.with_suffix(".zip.tmp"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, f"{pbip.stem}/{f.relative_to(out).as_posix()}")
        for f in sorted((sd / "data").glob("*.csv")):
            z.write(f, f"{pbip.stem}/data/{f.name}")
    os.replace(zpath.with_suffix(".zip.tmp"), zpath)
    return {"pbip": pbip.name, "zip": zpath.name, "pages": len(dd["pages"]), "visuals": sum(len(p["visuals"]) for p in dd["pages"]), "measures": len(dd["measures"]),
            "dax": {"checked": bool(dax.get("checked")), "reason": dax.get("reason")}, "gates": gates_mod.compact(found)}


def proof_text(pr: dict, name: str) -> str:
    lines = [f"{name} - numbers vs source", f"{pr.get('matched', 0):,} of {pr.get('compared', 0):,} numbers match; {pr.get('differences', 0)} differ; "
             f"{len(pr.get('open') or [])} measure(s) open" + (": " + ", ".join(pr["open"]) if pr.get("open") else ""), ""]
    for v in pr.get("visuals") or []:
        lines.append(f"[{'MATCH' if v.get('compared') and not v.get('differences') else 'SKIP' if v.get('skipped') else 'DIFF'}] {v['title']} ({v.get('kind')} {v.get('type')}): "
                     f"{v.get('matched', 0)} of {v.get('compared', 0)} numbers" + (f" - {v['skipped']}" if v.get("skipped") else ""))
        for dfx in v.get("differences") or []:
            lines.append(f"         {dfx['key']} - {dfx['measure']}: source {dfx['source']} vs Power BI {dfx['target']}")
    return "\n".join(lines) + "\n"


def _record_lineage(mid: str, rid: str, plan: dict) -> None:
    db.run("DELETE FROM migbi_lineage WHERE project = ? AND report = ?", (mid, rid))
    now = time.time()
    for e in plan.get("lineage") or []:
        db.run("INSERT INTO migbi_lineage (project, report, kind, src, dst, detail, created) VALUES (?, ?, ?, ?, ?, ?, ?)", (mid, rid, e["kind"], e["from"], e["to"], (e.get("detail") or "")[:500], now))
    push_lineage(mid, rid, plan)


def push_lineage(mid: str, rid: str, plan: dict) -> bool:
    """Hand the same edges to the shared lineage store (P13, app.lineage) so the knowledge map shows the migration: source
    tables and query items (system = the source BI) feed the converted tables, columns and measures (system = the target),
    and the converted report reads its tables and contains its measures. migbi_lineage stays the migration's own record."""
    try:
        from . import lineage
    except ImportError:
        return False
    try:
        row = db.one("SELECT name, source, target FROM migbi_projects WHERE id = ?", (mid,))
        src_sys = (row["source"] if row else None) or "source BI"
        tgt_sys = (row["target"] if row else None) or "Power BI"
        src, now = "migbi", time.time()
        report = lineage.upsert_node("report", tgt_sys, plan.get("name") or rid, properties={"migration": mid, "report": rid}, source=src, now=now)
        for e in plan.get("lineage") or []:
            if e["kind"] == "source_table":
                a = lineage.upsert_node("table", src_sys, e["from"], source=src, now=now)
                b = lineage.upsert_node("table", tgt_sys, e["to"], properties={"migration": mid}, source=src, now=now)
                lineage.upsert_edge(a, b, "feeds", evidence={"migration": mid, "report": rid, "detail": e.get("detail")}, source=src, now=now)
                lineage.upsert_edge(report, b, "reads", evidence={"migration": mid}, source=src, now=now)
            else:                                   # transform: a query item feeds a converted column or measure
                a = lineage.upsert_node("column", src_sys, e["from"], source=src, now=now)
                kind = "measure" if str(e["to"]).startswith("[") else "column"
                b = lineage.upsert_node(kind, tgt_sys, e["to"], properties={"migration": mid, "report": rid}, source=src, now=now)
                lineage.upsert_edge(a, b, "feeds", evidence={"migration": mid, "report": rid, "expression": (e.get("detail") or "")[:500]}, source=src, now=now)
                lineage.upsert_edge(report, b, "contains", evidence={"migration": mid}, source=src, now=now)
        return True
    except Exception:  # noqa: BLE001 - our own table is the record; the shared map is best effort
        traceback.print_exc()
    return False


def lineage_graph(mid: str, rid: str | None = None) -> dict:
    rows = db.q("SELECT * FROM migbi_lineage WHERE project = ?" + (" AND report = ?" if rid else "") + " ORDER BY id", (mid, rid) if rid else (mid,))
    nodes: dict[str, dict] = {}
    edges = []
    for r in rows:
        col_from = "source" if r["kind"] == "source_table" else "transform"
        col_to = "target" if r["kind"] == "source_table" else "target"
        if r["kind"] == "transform":
            col_from, col_to = "transform", "target"
            # source table -> transform: derive from the detail's references
        nodes.setdefault(r["src"], {"id": r["src"], "kind": col_from, "label": r["src"]})
        nodes.setdefault(r["dst"], {"id": r["dst"], "kind": col_to, "label": r["dst"]})
        edges.append({"from": r["src"], "to": r["dst"], "kind": r["kind"], "detail": r["detail"], "report": r["report"]})
    for r in rows:
        if r["kind"] == "transform":
            for m in re.findall(r"\[([^\]]+)\]\.\[([^\]]+)\]\.\[([^\]]+)\]", r["detail"] or ""):
                src = f"{m[0]}.{m[1]}"
                if src in nodes:
                    edges.append({"from": src, "to": r["src"], "kind": "reads", "detail": m[2], "report": r["report"]})
    return {"nodes": list(nodes.values()), "edges": edges}


def _open_prove_checkpoint(mid: str, rid: str, report: dict, pr: dict, found: list[dict], sid: str, plan: dict) -> dict:
    ev = proof_mod.evidence(pr, report["name"])
    bad = gates_mod.failed(found)
    ev["gates"] = gates_mod.compact(found)
    ev["items"] = ev["items"] + ([f"{len(bad)} review gate(s) fail: " + ", ".join(g["name"] for g in bad)] if bad else ["every review gate passed" + (" (DAX gate skipped: checker not running)" if any(g["id"] == "dax" and g["status"] == "skip" for g in found) else "")])
    ev["items"].append(f"{plan['ai']} calculation(s) by the agent, {plan['summary']['measures'] - plan['ai']} by rules")
    name = f"Prove: {report['name']} - {pr['matched']:,} of {pr['compared']:,} numbers match" + (f", {pr['differences']} differ" if pr["differences"] else "") + (f", {len(pr['open'])} open" if pr["open"] else "")
    c = checkpoints.open(KIND_PROVE, f"{mid}:{rid}", MODULE, name, "table", ev, link=f"{ROUTE}/{mid}/prove?report={rid}", agent="Checker")
    _set_report(mid, rid, checkpoint=c["id"])
    return c


def _on_prove(c: dict, decision: str, comment: str | None, who: str) -> None:
    mid, _, rid = c["subject"].partition(":")
    row = db.one("SELECT * FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    if not row:
        return
    if decision == "accept":
        _set_report(mid, rid, status="accepted", accepted_by=who, accepted=time.time(), note=(comment or "")[:500] or None)
        learned = _learn(mid, rid, row, who)
        try:
            worker.app_note(row["sub"], "prove", f"Proof accepted by {_user_name(who)}" + (f" - {learned} rule(s) learned for the next reports." if learned else "."), "ok")
        except Exception:  # noqa: BLE001
            pass
    else:
        _set_report(mid, rid, status="sent_back", note=(comment or "")[:500] or None)
        try:
            worker.app_note(row["sub"], "prove", f"Sent back by {_user_name(who)}: {comment}", "warn")
        except Exception:  # noqa: BLE001
            pass
    _update_wave_status(mid)


checkpoints.register_kind(KIND_PROVE, "Migrate BI: numbers vs source", _on_prove)


def _learn(mid: str, rid: str, row: dict, who: str) -> int:
    """An accepted, proven conversion teaches the rule pack: every measure the agent wrote for a gap becomes a rule."""
    try:
        sd = store.project_dir(row["sub"])
        md = store.project_dir(mid)
    except KeyError:
        return 0
    plan = _json(sd, "plan.json") or {}
    pr = _json(sd, "proof.json") or {}
    if not plan.get("gaps") or pr.get("differences"):
        return 0
    est = _estate(md)
    report = model.by_id(est).get(rid) if est else None
    if not report:
        return 0
    try:
        raw = definition.load(sd / "definition.yaml")
    except Exception:  # noqa: BLE001
        return 0
    measures = {m["name"]: m for m in raw.get("measures") or []}
    ds = model.dataset_of(est, report)
    pack = rule_pack(_row(mid)["tenant"])
    n = 0
    for g in plan["gaps"]:
        if g.get("kind") != "measure":
            continue
        m = measures.get(g["measure"])
        if not m or str(m.get("expression", "")).strip().upper() in ("BLANK ()", "BLANK()"):
            continue
        q = next((qq for qq in report.get("queries") or [] if qq["name"] == g.get("query")), None)
        ctx = rules.Context(ds, (q or {}).get("items") or [])
        if pack.learn(g["expression"], str(m["expression"]), ctx, _user_name(who), rid):
            n += 1
    if n:
        pack.save()
        db.audit("migbi.learn", mid, {"report": rid, "rules": n, "tenant": pack.tenant}, who)
    return n


def _update_wave_status(mid: str) -> None:
    d = store.project_dir(mid)
    waves = _json(d, "waves.json", [])
    rows = {r["report"]: r for r in report_rows(mid)}
    changed = False
    for w in waves:
        rs = [rows.get(i) for i in w["reports"]]
        if all(r and r["status"] not in ("queued", "converting") for r in rs) and not (w.get("handover") or {}).get("checkpoint"):
            new = "proven" if all(r["proven"] for r in rs) else "converted"
            if w.get("status") != new:
                w["status"] = new; changed = True
    if changed:
        _save_json(d, "waves.json", waves)
    all_rows = list(rows.values())
    if all_rows and all(r["status"] not in ("queued", "converting") for r in all_rows):
        st = "proven" if all(r["proven"] for r in all_rows) else "converting" if any(r["status"] in ("queued", "converting") for r in all_rows) else "decided"
        if st == "decided":
            st = "converting"
        cur = _row(mid)["status"]
        if cur not in ("handed", "running"):
            _status(mid, "proven" if st == "proven" else "converting")
            store.update(mid, status="proven" if st == "proven" else "converting")


def convert_again(mid: str, rid: str, comment: str | None, who: str | None) -> dict:
    d = _dir(mid)
    est = _estate(d)
    report = model.by_id(est).get(rid) if est else None
    if not report:
        raise HTTPException(404, "No such report.")
    row = db.one("SELECT * FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    if row and row["status"] in ("queued", "converting"):
        raise HTTPException(409, "This report is converting now.")
    wave = row["wave"] if row else (len(_json(d, "waves.json", [])) or 1)
    _queue_convert(mid, report, wave, who, comment)
    _note(mid, "convert", f"\"{report['name']}\" queued to convert again" + (f" with the comment: {comment}" if comment else "") + ".", "ok")
    db.audit("migbi.convert.again", f"{mid}:{rid}", {"comment": (comment or "")[:200]}, who)
    return report_detail(mid, rid)


def report_detail(mid: str, rid: str) -> dict:
    d = _dir(mid)
    row = db.one("SELECT * FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    if not row:
        raise HTTPException(404, "This report has not been converted.")
    row = dict(row)
    for k in ("gates", "proof"):
        try:
            row[k] = json.loads(row[k]) if row.get(k) else None
        except ValueError:
            row[k] = None
    sid = row["sub"]
    out = {**row, "status_label": REPORT_STATUS.get(row["status"], row["status"]), "stages": [{"id": i, "label": l, "line": t} for i, l, t in STAGES]}
    try:
        sd = store.project_dir(sid)
        st = store.load(sid)
    except KeyError:
        out["missing"] = True
        return out
    plan = _json(sd, "plan.json") or {}
    pr = _json(sd, "proof.json") or {}
    out.update(stage=(st.get("migbi") or {}).get("stage"), project_status=st.get("status"), error=st.get("error"), job=st.get("job"), runs=st.get("runs") or [], output=st.get("output"),
               versions=[{k: v.get(k) for k in ("v", "created", "summary", "pages", "visuals", "measures", "tables", "gates", "dax", "problems")} for v in st.get("versions") or []],
               plan={"summary": plan.get("summary"), "decisions": plan.get("decisions"), "gaps": plan.get("gaps"), "unsupported": plan.get("unsupported"), "visuals": plan.get("visuals"),
                     "measures": plan.get("measures"), "filters": plan.get("filters"), "rules_used": plan.get("rules_used"), "ai": plan.get("ai"), "mode": plan.get("mode")},
               proof_detail=pr, brief=_json(sd, "migrate_brief.json"), checkpoint_detail=checkpoints.get(row["checkpoint"]) if row.get("checkpoint") else None,
               files={"definition": (sd / "definition.yaml").exists(), "prototype": (sd / "prototype" / "index.html").exists(), "pbip": bool(st.get("output"))},
               lineage=lineage_graph(mid, rid), activity_after=0)
    return out


def report_activity(mid: str, rid: str, after: int = 0) -> list[dict]:
    row = db.one("SELECT sub FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    if not row:
        return []
    try:
        return store.activity(row["sub"], after)
    except KeyError:
        return []


def accept_proof(mid: str, rid: str, who: str, comment: str | None = None) -> dict:
    row = db.one("SELECT * FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    if not row:
        raise HTTPException(404, "This report has not been converted.")
    if row["status"] in ("queued", "converting"):
        raise HTTPException(409, "Still converting.")
    c = checkpoints.get(row["checkpoint"]) if row.get("checkpoint") else None
    if not c or c["status"] != "open":
        d = _dir(mid); est = _estate(d)
        report = model.by_id(est)[rid]
        sd = store.project_dir(row["sub"])
        pr = _json(sd, "proof.json") or {}
        found = json.loads((sd / "versions" / "v1" / "gates.json").read_text(encoding="utf-8")) if (sd / "versions" / "v1" / "gates.json").exists() else []
        c = _open_prove_checkpoint(mid, rid, report, pr, found, row["sub"], _json(sd, "plan.json") or {"ai": 0, "summary": {"measures": 0}})
    c = checkpoints.decide(c["id"], "accept", who, comment)
    return {"checkpoint": c, "report": report_detail(mid, rid)}


# ------------------------------------------------------------------ Hand over

def handover_pack(mid: str, n: int, who: str | None) -> dict:
    """Build the hand-over pack for a wave: inventory, decisions, waves, proof per report, the PBIP zips; then open
    the owner sign-off checkpoint. The pack can only be downloaded after that checkpoint is accepted."""
    d = _dir(mid)
    est = _estate(d)
    waves = _json(d, "waves.json", [])
    wave = next((w for w in waves if w["n"] == n), None)
    if not wave or not est:
        raise HTTPException(404, "No such wave.")
    rows = {r["report"]: r for r in report_rows(mid)}
    rs = [rows.get(i) for i in wave["reports"]]
    if any(r is None or r["status"] in ("queued", "converting") for r in rs):
        raise HTTPException(409, "Every report of the wave must finish converting first.")
    not_proven = [r["name"] for r in rs if not r["proven"]]
    out = d / "handover" / f"wave{n}"
    shutil.rmtree(out, ignore_errors=True)
    (out / "reports").mkdir(parents=True)
    preds = _json(d, "predictions.json") or {}
    (out / "inventory.csv").write_text(model.inventory_csv(est, preds), encoding="utf-8")
    decisions = _json(d, "decisions.json") or {}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "name", "type", "folder", "owner", "decision", "reason", "merged_into", "signed_by", "signed_at"])
    by = model.by_id(est)
    applied = decisions.get("applied") or {}
    for rid, dcs in (decisions.get("result") or {}).items():
        r = by.get(rid, {})
        ov = (decisions.get("overrides") or {}).get(rid)
        w.writerow([rid, r.get("name"), r.get("type"), r.get("folder"), r.get("owner"), dec.LABELS.get(dcs["decision"], dcs["decision"]), dcs["reason"], dcs.get("merged_into") or "",
                    (ov or {}).get("by") or applied.get("by"), time.strftime("%Y-%m-%d %H:%M", time.localtime((ov or {}).get("at") or applied.get("at") or 0))])
    (out / "decisions.csv").write_text(buf.getvalue(), encoding="utf-8")
    (out / "rules.json").write_text(json.dumps({"rules": decisions.get("rules"), "defaults": dec.DEFAULTS, "applied": applied}, indent=1), encoding="utf-8")
    (out / "waves.json").write_text(json.dumps(waves, indent=1), encoding="utf-8")
    manifest = []
    for r in rs:
        try:
            sd = store.project_dir(r["sub"])
        except KeyError:
            continue
        rd = out / "reports" / re.sub(r"[^\w.\- ]+", "_", r["name"])[:60]
        rd.mkdir(parents=True, exist_ok=True)
        for f in ("proof.json", "plan.json", "definition.yaml", "migrate_brief.json"):
            if (sd / f).exists():
                shutil.copy2(sd / f, rd / f)
        pr = _json(sd, "proof.json") or {}
        (rd / "Numbers vs source.txt").write_text(proof_text(pr, r["name"]), encoding="utf-8")
        gj = sd / "versions" / "v1" / "gates.json"
        if gj.exists():
            (rd / "Review gates.txt").write_text(gates_mod.text_report(json.loads(gj.read_text(encoding="utf-8")), r["name"]), encoding="utf-8")
        st = store.load(r["sub"])
        z = (st.get("output") or {}).get("zip")
        if z and (sd / z).exists():
            shutil.copy2(sd / z, rd / z)
        manifest.append({"report": r["report"], "name": r["name"], "status": r["status"], "proven": r["proven"], "matched": pr.get("matched"), "compared": pr.get("compared"),
                         "differences": pr.get("differences"), "open": pr.get("open"), "accepted_by": _user_name(r.get("accepted_by")) if r.get("accepted_by") else None, "pbip": z,
                         "dax_checked": bool(((st.get("output") or {}).get("dax") or {}).get("checked")), "ai_calls": r["ai_calls"], "ai_cost_usd": round(r["ai_cost"], 2)})
    pack_json = {"programme": _row(mid)["name"], "wave": wave["name"], "built": time.time(), "built_by": _user_name(who), "reports": manifest, "not_proven": not_proven,
                 "rules_learned": rule_pack(_row(mid)["tenant"]).stats(), "before_go_live": ["Point the dataset at the client's gateway (the DataFolder parameter / the warehouse connection)",
                                                                                            "Map the source tool's groups to Power BI roles (row-level security)", "Publish to the target workspace or report server folder",
                                                                                            "Ask the report owner to sign off with the numbers pack"]}
    (out / "pack.json").write_text(json.dumps(pack_json, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "README.txt").write_text(f"Hand-over pack - {pack_json['programme']} - {wave['name']}\n\ninventory.csv: what we found, in the source tool's own terms, with usage and the "
                                    f"conversion prediction.\ndecisions.csv + rules.json: every decision with its reason, who signed it and the rules used.\nwaves.json: the waves.\n"
                                    f"reports/<name>/: the Power BI project (zip), Review gates.txt, Numbers vs source.txt, the conversion plan and the definition.\n"
                                    f"{len(manifest)} report(s); {len(manifest) - len(not_proven)} proven" + (f"; not proven: {', '.join(not_proven)}" if not_proven else "") + "\n", encoding="utf-8")
    zpath = d / "handover" / f"wave{n}.zip"
    with zipfile.ZipFile(zpath.with_suffix(".zip.tmp"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, f"handover-wave{n}/{f.relative_to(out).as_posix()}")
    os.replace(zpath.with_suffix(".zip.tmp"), zpath)
    ev = {"summary": f"{wave['name']}: {len(manifest)} report(s), {len(manifest) - len(not_proven)} proven; pack built by {_user_name(who)}",
          "columns": ["Report", "Status", "Numbers matched", "Accepted by", "Package"], "rows": [[m["name"], m["status"], f"{m['matched']} of {m['compared']}", m["accepted_by"] or "-", m["pbip"] or "-"] for m in manifest],
          "items": ["Inventory, decisions with reasons and signatures, waves, proof per report, PBIP packages"] + ([f"Not proven: {', '.join(not_proven[:5])}"] if not_proven else []),
          "counts": {"reports": len(manifest), "proven": len(manifest) - len(not_proven), "open": len(not_proven)}, "wave": n}
    checkpoints.withdraw(KIND_HANDOVER, f"{mid}:wave{n}", who=who)
    assignee = (wave.get("handover") or {}).get("assignee")
    c = checkpoints.open(KIND_HANDOVER, f"{mid}:wave{n}", MODULE, f"Hand over {wave['name']}: owner sign-off ({len(manifest)} reports)", "link", ev, link=f"{ROUTE}/{mid}/handover",
                         agent="Packager", assignee=assignee, opened_by=who)
    wave["handover"] = {"built": time.time(), "built_by": who, "checkpoint": c["id"], "accepted": None, "accepted_by": None, "zip": zpath.name, "reports": len(manifest), "proven": len(manifest) - len(not_proven),
                        "assignee": assignee}
    wave["status"] = "handover"
    _save_json(d, "waves.json", waves)
    _note(mid, "handover", f"Hand-over pack for {wave['name']} built ({len(manifest)} reports, {len(manifest) - len(not_proven)} proven). Waiting for the owner's sign-off.", "ok")
    db.audit("migbi.handover.pack", f"{mid}:wave{n}", {"reports": len(manifest), "proven": len(manifest) - len(not_proven), "checkpoint": c["id"]}, who)
    return get(mid)


def assign_handover(mid: str, n: int, to: str, who: str) -> dict:
    d = _dir(mid)
    waves = _json(d, "waves.json", [])
    wave = next((w for w in waves if w["n"] == n), None)
    if not wave:
        raise HTTPException(404, "No such wave.")
    if not db.user(to):
        raise HTTPException(400, "No such person.")
    wave["handover"] = {**(wave.get("handover") or {}), "assignee": to}
    _save_json(d, "waves.json", waves)
    cid = (wave.get("handover") or {}).get("checkpoint")
    if cid and (checkpoints.get(cid) or {}).get("status") == "open":
        checkpoints.reassign(cid, to, who)
    return get(mid)


def _on_handover(c: dict, decision: str, comment: str | None, who: str) -> None:
    mid, _, w = c["subject"].partition(":wave")
    try:
        d = store.project_dir(mid)
    except KeyError:
        return
    waves = _json(d, "waves.json", [])
    wave = next((x for x in waves if str(x["n"]) == w), None)
    if not wave:
        return
    if decision == "accept":
        wave["handover"] = {**(wave.get("handover") or {}), "accepted": time.time(), "accepted_by": who, "accepted_by_name": _user_name(who), "comment": (comment or "")[:500]}
        wave["status"] = "handed"
        _save_json(d, "waves.json", waves)
        _status(mid, "handed")
        store.update(mid, status="handed")
        _note(mid, "handover", f"{wave['name']} signed off by {_user_name(who)}. The pack can be downloaded; nightly drift checks can be registered under Run.", "ok")
        for rid in wave["reports"]:
            register_drift(mid, rid, who)
    else:
        wave["handover"] = {**(wave.get("handover") or {}), "sent_back": {"by": who, "at": time.time(), "comment": (comment or "")[:500]}}
        wave["status"] = "sent_back"
        _save_json(d, "waves.json", waves)
        _note(mid, "handover", f"{wave['name']} sent back by {_user_name(who)}: {comment}", "warn")


checkpoints.register_kind(KIND_HANDOVER, "Migrate BI: hand-over sign-off", _on_handover)


def handover_download(mid: str, n: int) -> Path:
    d = _dir(mid)
    waves = _json(d, "waves.json", [])
    wave = next((w for w in waves if w["n"] == n), None)
    if not wave or not (wave.get("handover") or {}).get("zip"):
        raise HTTPException(404, "No pack for this wave yet.")
    if not wave["handover"].get("accepted"):
        raise HTTPException(409, "Nothing is handed over before the owner's sign-off: the pack opens once the hand-over checkpoint is accepted.")
    return d / "handover" / wave["handover"]["zip"]


# ------------------------------------------------------------------ Run: nightly drift checks (stub schedules)

def register_drift(mid: str, rid: str, who: str | None) -> dict:
    have = db.one("SELECT * FROM migbi_schedules WHERE project = ? AND report = ? AND kind = 'drift'", (mid, rid))
    if have:
        return dict(have)
    sid = "ds-" + pysecrets.token_hex(4)
    nxt = time.time() + 86400
    db.run("INSERT INTO migbi_schedules (id, project, report, kind, cadence, active, next_run, created, created_by) VALUES (?, ?, ?, 'drift', 'nightly', 1, ?, ?, ?)", (sid, mid, rid, nxt, time.time(), who))
    return dict(db.one("SELECT * FROM migbi_schedules WHERE id = ?", (sid,)))


async def _job_drift(sid_sub: str, args: dict) -> None:
    """Re-run the proof of a converted report against the source data (the nightly drift check; a stub in P15:
    the same comparison, on a schedule)."""
    mid, rid, sched = args["migration"], args["report"], args["schedule"]
    md = store.project_dir(mid)
    est = _estate(md)
    report = model.by_id(est).get(rid) if est else None
    sd = store.project_dir(sid_sub)
    plan = _json(sd, "plan.json") or {}
    if not report or not plan:
        raise RuntimeError("Nothing to check: the report was not converted.")
    pr = await asyncio.to_thread(proof_mod.prove, sd, est, report, plan, md / "source")
    _save_json(sd, "drift.json", pr)
    result = f"{pr['matched']:,} of {pr['compared']:,} match" + (f"; {pr['differences']} drifted" if pr["differences"] else "")
    db.run("UPDATE migbi_schedules SET last_run = ?, last_result = ?, runs = runs + 1, next_run = ? WHERE id = ?", (time.time(), result, time.time() + 86400, sched))
    worker.app_note(sid_sub, "run", f"Nightly check: {result}.", "warn" if pr["differences"] else "ok")
    store.update(sid_sub, status="converted", job=None)


worker.register_job("migbi_drift", _job_drift, status="checking_drift", done="Drift check done")


def run_drift_now(mid: str, sched_id: str, who: str | None) -> dict:
    s = db.one("SELECT * FROM migbi_schedules WHERE id = ? AND project = ?", (sched_id, mid))
    if not s:
        raise HTTPException(404, "No such check.")
    row = db.one("SELECT sub FROM migbi_reports WHERE project = ? AND report = ?", (mid, s["report"]))
    if not row:
        raise HTTPException(409, "The report is not converted.")
    worker.enqueue(row["sub"], "migbi_drift", migration=mid, report=s["report"], schedule=sched_id)
    db.audit("migbi.drift.run", sched_id, None, who)
    return {"ok": True, "schedule": dict(s)}


async def run_due_drift(now: float | None = None) -> int:
    """One pass in the current tenant (drift_loop runs it for each): queues every due nightly check. A check whose
    report is gone is moved on a day with the reason, so it never blocks the others."""
    now = now or time.time()
    n = 0
    for s in db.q("SELECT * FROM migbi_schedules WHERE active = 1 AND (next_run IS NULL OR next_run <= ?)", (now,)):
        row = db.one("SELECT sub FROM migbi_reports WHERE project = ? AND report = ?", (s["project"], s["report"]))
        try:
            if not row:
                raise KeyError(s["report"])
            worker.enqueue(row["sub"], "migbi_drift", migration=s["project"], report=s["report"], schedule=s["id"])
            n += 1
        except KeyError:                       # the converted report (or its folder) is gone: say so, never block the others
            db.run("UPDATE migbi_schedules SET last_result = ? WHERE id = ?", ("Not run: the converted report is missing - convert it again", s["id"]))
        except Exception as e:  # noqa: BLE001 - one bad check never stops the other checks
            db.run("UPDATE migbi_schedules SET last_result = ? WHERE id = ?", (f"Not run: {str(e)[:160]}", s["id"]))
        db.run("UPDATE migbi_schedules SET next_run = ? WHERE id = ?", (now + 86400, s["id"]))
    return n


DRIFT_TICK_S = float(os.environ.get("MIGBI_DRIFT_TICK_S", "300"))      # how often the loop looks for a due nightly check
_drift_tasks: dict[int, asyncio.Task] = {}                              # one loop per event loop (the app's; a test's)


async def drift_pass(now: float | None = None) -> int:
    """Every tenant with Migrate BI on, in turn (P17): its due checks are queued in its own lane."""
    n = 0
    for _t in db.each_tenant("migbi"):
        try:
            n += await run_due_drift(now)
        except Exception:  # noqa: BLE001 - one tenant's problem never stops the others
            traceback.print_exc()
    return n


async def drift_loop() -> None:
    while True:
        await asyncio.sleep(DRIFT_TICK_S)
        try:
            await drift_pass()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep looking
            traceback.print_exc()


def ensure_drift_loop() -> bool:
    """Start the nightly drift loop on the app's loop once (the app starts it at boot; every Migrate BI call makes
    sure it is still running, also from the thread pool). True when it was started (or asked to start) now."""
    try:
        loop, here = asyncio.get_running_loop(), True
    except RuntimeError:
        loop, here = worker._loop, False
    if loop is None or loop.is_closed():
        return False
    t = _drift_tasks.get(id(loop))
    if t is not None and not t.done():
        return False

    def start() -> None:
        have = _drift_tasks.get(id(loop))
        if have is None or have.done():          # a fresh context: never the tenant or the person of the request that noticed the loop was gone
            _drift_tasks[id(loop)] = loop.create_task(drift_loop(), context=contextvars.Context())
    if here:
        start()
    else:
        loop.call_soon_threadsafe(start)
    return True


def stop_drift_loop() -> None:
    for t in _drift_tasks.values():
        t.cancel()
    _drift_tasks.clear()


# ------------------------------------------------------------------ the agent log across the programme

def agent_log(mid: str, limit: int = 300) -> list[dict]:
    out = []
    try:
        for e in store.activity(mid, 0, 2000):
            out.append({**e, "report": None, "report_name": None})
    except KeyError:
        pass
    for r in report_rows(mid):
        try:
            for e in store.activity(r["sub"], 0, 2000):
                out.append({**e, "report": r["report"], "report_name": r["name"]})
        except KeyError:
            continue
    out.sort(key=lambda e: e.get("ts") or 0)
    return out[-limit:]


# ------------------------------------------------------------------ API

class NewMigration(BaseModel):
    name: str | None = None
    source: str | None = None
    source_version: str | None = None
    target: str | None = None
    target_version: str | None = None
    read_from: str | None = None
    mode: str | None = None
    calls: str | None = None
    visuals: str | None = None          # relay (Visual Atlas) or builtin (Power BI's own visuals)


class ConnectIn(BaseModel):
    url: str | None = None
    namespace: str | None = None
    user: str | None = None
    sign_in: str | None = None
    secret: str | None = None
    folders: str | None = None
    page_size: int | None = None
    max_rps: int | None = None
    usage_days: int | None = None
    scope: dict | None = None


class RulesIn(BaseModel):
    rules: dict | None = None
    ask_queue: bool = False


class OverrideIn(BaseModel):
    report: str
    decision: str
    note: str | None = None


class WaveIn(BaseModel):
    name: str | None = None
    reports: list[str]


class AgainIn(BaseModel):
    comment: str | None = None


class Budget(BaseModel):
    budget_usd: float


class Assign(BaseModel):
    to: str


def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    ensure_drift_loop()                      # the nightly drift checks keep running (started at boot; restarted if it ever stopped)
    return u


def _dev() -> dict:
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only BI Devs / Analysts and admins run a migration.")
    return u


def _can_see(mid: str, u: dict) -> None:
    p = db.project(mid)
    if p is None or not auth.can_project(u, "view", p):           # an unknown id is not found, for Admins too
        raise HTTPException(404, "No such migration.")


@router.get("/api/migrate-bi")
def api_list():
    u = _u()
    return {"projects": projects(u), "sources": reader_catalogue(), "targets": [{"id": k, **v} for k, v in TARGETS.items()], "modes": [{"id": k, "label": v, "help": MODE_HELP[k]} for k, v in MODES.items()],
            "can_edit": auth.is_dev(u), "rules": {"builtin": len(rules.RULES), "learned": rule_pack().stats()}, "stages": [{"id": i, "label": l, "line": t} for i, l, t in STAGES]}


@router.post("/api/migrate-bi")
def api_create(body: NewMigration):
    u = _dev()
    return create(body.model_dump(), u["id"])


@router.get("/api/migrate-bi/{mid}")
def api_get(mid: str):
    u = _u(); _can_see(mid, u)
    return get(mid)


@router.put("/api/migrate-bi/{mid}/budget")
def api_budget(mid: str, body: Budget):
    u = _dev(); _can_see(mid, u)
    if body.budget_usd < 0:
        raise HTTPException(400, "The budget cannot be negative.")
    db.run("UPDATE migbi_projects SET budget_usd = ? WHERE id = ?", (body.budget_usd, mid))
    db.audit("migbi.budget", mid, {"budget_usd": body.budget_usd}, u["id"])
    return get(mid)


@router.post("/api/migrate-bi/{mid}/connect")
def api_connect(mid: str, body: ConnectIn):
    u = _dev(); _can_see(mid, u)
    return connect(mid, body.model_dump(), u["id"])


@router.post("/api/migrate-bi/{mid}/upload")
async def api_upload(mid: str, files: list[UploadFile] = File(default=[])):
    u = _dev(); _can_see(mid, u)
    if not files:
        raise HTTPException(400, "Choose the export files.")
    return await upload(mid, files, u["id"])


@router.post("/api/migrate-bi/{mid}/test")
def api_test(mid: str):
    u = _dev(); _can_see(mid, u)
    return test(mid, u["id"])


@router.post("/api/migrate-bi/{mid}/scan")
def api_scan(mid: str):
    u = _dev(); _can_see(mid, u)
    return start_scan(mid, u["id"])


@router.post("/api/migrate-bi/{mid}/scan/{action}")
def api_scan_control(mid: str, action: str):
    u = _dev(); _can_see(mid, u)
    return scan_control(mid, action, u["id"])


@router.get("/api/migrate-bi/{mid}/activity")
def api_activity(mid: str, after: int = 0):
    u = _u(); _can_see(mid, u)
    return {"events": store.activity(mid, after)}


@router.get("/api/migrate-bi/{mid}/inventory")
def api_inventory(mid: str, decision: str | None = None, type: str | None = None, used: str | None = None, q: str | None = None, page: int = 0, convert: str | None = None,  # noqa: A002
                  folder: str | None = None, per: int = 25):
    u = _u(); _can_see(mid, u)
    return inventory(mid, decision, type, used, q, page, per=max(1, min(per, 5000)), convert=convert, folder=folder)


@router.get("/api/migrate-bi/{mid}/inventory.csv", response_class=PlainTextResponse)
def api_inventory_csv(mid: str):
    u = _u(); _can_see(mid, u)
    est = _estate(_dir(mid))
    if not est:
        raise HTTPException(404, "No estate yet.")
    return PlainTextResponse(model.inventory_csv(est, _json(_dir(mid), "predictions.json")), headers={"Content-Disposition": f'attachment; filename="inventory-{mid}.csv"'})


@router.get("/api/migrate-bi/{mid}/objects/{rid}")
def api_object(mid: str, rid: str):
    u = _u(); _can_see(mid, u)
    return object_detail(mid, rid)


@router.get("/api/migrate-bi/{mid}/decide")
def api_decide(mid: str):
    u = _u(); _can_see(mid, u)
    out = decide_state(mid)
    out.pop("_decisions", None)
    return out


@router.post("/api/migrate-bi/{mid}/decide/preview")
def api_preview(mid: str, body: RulesIn):
    u = _u(); _can_see(mid, u)
    return preview(mid, body.rules)


@router.post("/api/migrate-bi/{mid}/decide/override")
def api_override(mid: str, body: OverrideIn):
    u = _dev(); _can_see(mid, u)
    return override(mid, body.report, body.decision, body.note, u["id"])


@router.post("/api/migrate-bi/{mid}/decide/apply")
def api_apply(mid: str, body: RulesIn):
    u = _dev(); _can_see(mid, u)
    out = apply_rules(mid, body.rules, u["id"], body.ask_queue)
    out.pop("_decisions", None)
    return out


@router.post("/api/migrate-bi/{mid}/waves/estimate")
def api_estimate(mid: str, body: WaveIn):
    u = _u(); _can_see(mid, u)
    return estimate(mid, body.reports)


@router.post("/api/migrate-bi/{mid}/waves")
def api_wave(mid: str, body: WaveIn):
    u = _dev(); _can_see(mid, u)
    return create_wave(mid, body.name, body.reports, u["id"])


@router.get("/api/migrate-bi/{mid}/reports/{rid}")
def api_report(mid: str, rid: str):
    u = _u(); _can_see(mid, u)
    return report_detail(mid, rid)


@router.get("/api/migrate-bi/{mid}/reports/{rid}/activity")
def api_report_activity(mid: str, rid: str, after: int = 0):
    u = _u(); _can_see(mid, u)
    return {"events": report_activity(mid, rid, after)}


@router.post("/api/migrate-bi/{mid}/reports/{rid}/convert")
def api_convert_again(mid: str, rid: str, body: AgainIn | None = None):
    u = _dev(); _can_see(mid, u)
    return convert_again(mid, rid, body.comment if body else None, u["id"])


@router.post("/api/migrate-bi/{mid}/reports/{rid}/accept")
def api_accept_proof(mid: str, rid: str, body: AgainIn | None = None):
    u = _dev(); _can_see(mid, u)
    return accept_proof(mid, rid, u["id"], body.comment if body else None)


@router.get("/api/migrate-bi/{mid}/reports/{rid}/download")
def api_report_download(mid: str, rid: str):
    u = _u(); _can_see(mid, u)
    row = db.one("SELECT sub FROM migbi_reports WHERE project = ? AND report = ?", (mid, rid))
    if not row:
        raise HTTPException(404, "Not converted.")
    st = store.load(row["sub"])
    z = (st.get("output") or {}).get("zip")
    if not z or not (store.project_dir(row["sub"]) / z).exists():
        raise HTTPException(404, "No package yet (the review gates must pass first).")
    return FileResponse(store.project_dir(row["sub"]) / z, filename=z, media_type="application/zip")


@router.post("/api/migrate-bi/{mid}/handover/{n}")
def api_handover(mid: str, n: int):
    u = _dev(); _can_see(mid, u)
    return handover_pack(mid, n, u["id"])


@router.post("/api/migrate-bi/{mid}/handover/{n}/assign")
def api_handover_assign(mid: str, n: int, body: Assign):
    u = _dev(); _can_see(mid, u)
    return assign_handover(mid, n, body.to, u["id"])


@router.get("/api/migrate-bi/{mid}/handover/{n}/pack.zip")
def api_handover_download(mid: str, n: int):
    u = _u(); _can_see(mid, u)
    path = handover_download(mid, n)
    return FileResponse(path, filename=f"handover-wave{n}.zip", media_type="application/zip")


@router.post("/api/migrate-bi/{mid}/run/{sched_id}/now")
def api_drift_now(mid: str, sched_id: str):
    u = _dev(); _can_see(mid, u)
    return run_drift_now(mid, sched_id, u["id"])


@router.get("/api/migrate-bi/{mid}/lineage")
def api_lineage(mid: str, report: str | None = None):
    u = _u(); _can_see(mid, u)
    return lineage_graph(mid, report)


@router.get("/api/migrate-bi/{mid}/log")
def api_log(mid: str, limit: int = 300):
    u = _u(); _can_see(mid, u)
    return {"events": agent_log(mid, min(limit, 1000))}


@router.get("/api/migrate-bi/{mid}/rules")
def api_rules(mid: str):
    u = _u(); _can_see(mid, u)
    pack = rule_pack(_row(mid)["tenant"])
    return {"builtin": rules.catalogue(), "learned": [{k: r.get(k) for k in ("id", "pattern", "function", "accepted_by", "report", "when", "uses")} for r in pack.rules], "tenant": pack.tenant}
