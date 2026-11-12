"""Data observability (build-plan v2, P14): is the data healthy - everywhere?

Watched assets are the lineage graph's tables, columns, measures, reports, flows and jobs (P13) plus what the
watched connections expose. Checks - freshness, volume, schema change, distribution, nulls, duplicates,
reconciliation to source, lineage breaks - run as the registered job kind `observe_check` (not an LLM run), on
request and from a lazy scheduler the router starts; readers are read-only (DuckDB over the dashboards' extracts,
the Connector SDK for warehouses and platforms, P13's runs for integrations). Baselines are learned from each
asset's own history (rolling window, by weekday), thresholds are tunable per check and per asset, and what a
person marks "expected" widens the band.

An incident = the check, the asset, measured vs expected, severity, first / last seen and its impact path from the
graph: every report, schedule, Ask D answer, agent run and person downstream. One upstream break is one incident
(downstream findings of the same cause fold into it). Every action - warn report users (a banner on the affected
dashboards + a notification to their owners), raise a ticket (through the Service desk's own write-back gate),
Self-healing and AI SDLC fix drafts - opens a checkpoint (kind `observe.action`, view `table`); nothing is written
until a person accepts it. Other tools' results (OpenLineage, dbt, Great Expectations, Soda, a generic webhook that
Monte Carlo / Bigeye / Acceldata / Metaplane / Elementary / Datadog can post to) land in the same incident table
with the tool named.
"""
from __future__ import annotations

import asyncio
import collections
import datetime as dt
import json
import os
import secrets as _secrets
import statistics
import time
import traceback

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import auth, checkpoints, db, lineage, notify, secrets_store, store, worker
from . import observe_checks as oc

router = APIRouter()
MODULE = "Data observability"
SUBJECT = "data-observability"
KIND = "observe.action"
ROUTE = "#/observability"
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
LAYERS = [("sources", "Sources", "ERP, PLM, finance, CRM, files"), ("integrations", "Integrations", "OIC, SSIS, ADF, n8n, bots"),
          ("warehouse", "Warehouse", "Snowflake, Fabric, Databricks"), ("semantic", "Semantic models", "metrics, ontology, models"),
          ("bi", "BI & reports", "Power BI, Tableau, migrated"), ("consumers", "Consumers", "Ask D, schedules, alerts, agents")]
LAYER_LABEL = {k: l for k, l, _ in LAYERS}
WATCH_KINDS = ("table", "column", "report", "page", "measure", "flow", "job", "bot")
ROUTES = {"warn": "Warn report users", "ticket": "Raise a ticket", "heal": "Fix with Self-healing", "sdlc": "Fix with AI SDLC"}
ROUTE_TARGET = {"warn": "Affected dashboards", "ticket": "Service desk (Jira / Freshservice)", "heal": "Self-healing", "sdlc": "AI SDLC"}
SUGGEST = {"freshness": "heal", "lineage": "heal", "volume": "ticket", "schema": "sdlc", "distribution": "ticket", "nulls": "sdlc", "duplicates": "sdlc", "reconcile": "ticket", "quality": "ticket"}
STATUS_LABEL = {"open": "Open", "proposed": "Waiting for you", "actioned": "Fix proposed", "expected": "Expected", "resolved": "Resolved", "dismissed": "Dismissed"}
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
_sched_task = None

db.register_schema("""
CREATE TABLE IF NOT EXISTS observe_sources (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}', owner_id TEXT,
  status TEXT NOT NULL DEFAULT 'new', error TEXT, every_min INTEGER NOT NULL DEFAULT 60, last_check REAL, next_check REAL,
  assets INTEGER NOT NULL DEFAULT 0, seconds REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS observe_assets (
  id TEXT PRIMARY KEY, node_id TEXT, kind TEXT NOT NULL, layer TEXT NOT NULL, name TEXT NOT NULL, label TEXT, system TEXT,
  source_id TEXT, reader TEXT NOT NULL DEFAULT 'none', config TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'Unknown', signal TEXT, last_check REAL, seen REAL NOT NULL, created REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS observe_assets_node ON observe_assets (node_id);
CREATE INDEX IF NOT EXISTS observe_assets_layer ON observe_assets (layer, enabled);
CREATE TABLE IF NOT EXISTS observe_checks (
  asset_id TEXT NOT NULL, check_kind TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, config TEXT NOT NULL DEFAULT '{}',
  last_run REAL, last_status TEXT, last_text TEXT, updated REAL, updated_by TEXT, PRIMARY KEY (asset_id, check_kind));
CREATE TABLE IF NOT EXISTS observe_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, check_kind TEXT NOT NULL, ts REAL NOT NULL, value TEXT NOT NULL,
  expected INTEGER NOT NULL DEFAULT 0, anomaly INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS observe_obs_key ON observe_observations (asset_id, check_kind, ts);
CREATE TABLE IF NOT EXISTS observe_incidents (
  id TEXT PRIMARY KEY, check_kind TEXT NOT NULL, asset_id TEXT NOT NULL, column_name TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL, title TEXT NOT NULL,
  what TEXT, measured TEXT NOT NULL DEFAULT '{}', expected TEXT NOT NULL DEFAULT '{}', rows TEXT NOT NULL DEFAULT '[]', cause TEXT, route TEXT,
  status TEXT NOT NULL DEFAULT 'open', tool TEXT NOT NULL DEFAULT 'relay', external_id TEXT, impact TEXT NOT NULL DEFAULT '{}', also TEXT NOT NULL DEFAULT '[]',
  checkpoint_id TEXT, note TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL, resolved REAL, resolved_by TEXT, resolved_how TEXT, observation_id INTEGER);
CREATE INDEX IF NOT EXISTS observe_incidents_status ON observe_incidents (status, last_seen);
CREATE INDEX IF NOT EXISTS observe_incidents_asset ON observe_incidents (asset_id, check_kind);
CREATE TABLE IF NOT EXISTS observe_work (
  id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, priority TEXT, target TEXT,
  status TEXT NOT NULL DEFAULT 'proposed', checkpoint_id TEXT, approved_by TEXT, note TEXT, created REAL NOT NULL, decided REAL);
CREATE TABLE IF NOT EXISTS observe_warnings (
  id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, project TEXT NOT NULL, text TEXT NOT NULL, since REAL NOT NULL, cleared REAL, cleared_by TEXT,
  created_by TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS observe_warnings_project ON observe_warnings (project, cleared);
CREATE TABLE IF NOT EXISTS observe_settings (check_kind TEXT PRIMARY KEY, config TEXT NOT NULL DEFAULT '{}', updated REAL, updated_by TEXT);
""")

oc.register_lab_engines()


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _aid(node_id: str) -> str:
    return "a-" + node_id[2:16] if node_id.startswith("n-") else "a-" + node_id[:14]


def _when(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d %b %H:%M") if t else "-"


# ------------------------------------------------------------------ settings (defaults per check, tunable)

def settings() -> dict:
    saved = {r["check_kind"]: _j(r["config"], {}) for r in db.q("SELECT * FROM observe_settings")}
    return {k: oc.cfg_for(k, saved.get(k)) for k in oc.CHECKS}


def save_settings(body: dict, who: str) -> dict:
    now = time.time()
    for check, cfg in (body or {}).items():
        if check not in oc.CHECKS or not isinstance(cfg, dict):
            continue
        clean = {k: v for k, v in cfg.items() if k in (oc.DEFAULTS.get(check) or {})}
        db.run("INSERT OR REPLACE INTO observe_settings (check_kind, config, updated, updated_by) VALUES (?, ?, ?, ?)", (check, json.dumps(clean), now, who))
    db.audit("observe.settings", None, {k: v for k, v in (body or {}).items() if k in oc.CHECKS}, who)
    return settings()


def check_cfg(asset_id: str, check: str, global_cfg: dict | None = None) -> dict:
    row = db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = ?", (asset_id, check))
    g = (global_cfg or settings()).get(check) or {}
    return oc.cfg_for(check, g, _j(row["config"], {}) if row else None)


# ------------------------------------------------------------------ the worker's subject, the job and the scheduler

def _subject() -> str:
    d = store.ROOT / SUBJECT
    if not (d / "project.json").exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / "data").mkdir(exist_ok=True)
        store.save({"id": SUBJECT, "name": MODULE, "kind": "observe", "prompt": "Data checks across the watched assets - not a dashboard.", "status": "idle",
                    "created": time.time(), "versions": [], "runs": [], "job": None, "error": None})
    return SUBJECT


def check_state() -> dict:
    if not (store.ROOT / SUBJECT / "project.json").exists():
        return {"status": "idle"}
    try:
        st = store.load(SUBJECT)
    except (KeyError, FileNotFoundError, ValueError):
        return {"status": "idle"}
    return {"status": st.get("status"), "error": st.get("error"), "updated": st.get("updated"), "job": (st.get("job") or {}).get("kind")}


def due(now: float | None = None) -> list[dict]:
    now = now or time.time()
    return db.q("SELECT * FROM observe_sources WHERE status != 'paused' AND kind != 'import' AND (next_check IS NULL OR next_check <= ?) ORDER BY next_check", (now,))


def request_check(assets: list[str] | None = None, source: str | None = None, who: str | None = None) -> dict:
    pid = _subject()
    st = store.load(pid)
    if st.get("status") in ("queued", "checking") and (st.get("job") or {}).get("kind") == "observe_check" and not assets and not source:
        return {"queued": True, "already": True}
    worker.enqueue(pid, "observe_check", assets=list(assets or []), source=source, who=who)
    db.audit("observe.check.requested", source or (",".join(assets or []) or "all"), None, who or "system")
    return {"queued": True}


async def _check_job(pid: str, args: dict) -> None:
    worker.app_note(pid, "observe_check", "Running the data checks...")
    r = await asyncio.to_thread(run_checks, args.get("assets") or None, args.get("source"), None, args.get("who") or "worker")
    worker.app_note(pid, "observe_check", f"{r['assets']} assets checked: {r['incidents_new']} new incident{'s' if r['incidents_new'] != 1 else ''}, {r['resolved']} resolved" + (f", {r['errors']} could not be read" if r["errors"] else ""),
                    "warn" if r["errors"] else "info")
    store.update(pid, status="idle", error=None)


worker.register_job("observe_check", _check_job, status="checking", done="Data checks done")


async def _scheduler() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            for _t in db.each_tenant("observe"):        # P17: every tenant with Data observability on
                if due() and check_state().get("status") not in ("queued", "checking"):
                    request_check()
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def ensure_scheduler() -> None:
    """Started lazily from the router (main.py is not touched): one task on the app's loop."""
    global _sched_task
    loop = worker._loop
    if loop is None or loop.is_closed():
        return
    if _sched_task is None or _sched_task.done():
        def start():
            global _sched_task
            if _sched_task is None or _sched_task.done():
                _sched_task = loop.create_task(_scheduler())
        loop.call_soon_threadsafe(start)


# ------------------------------------------------------------------ sources: dashboards (auto), integrations (auto), connections, imports

SOURCE_KINDS = {"dashboards": "Dashboards & extracts", "integrations": "Integrations (discovered)", "connection": "A connection", "import": "Another tool's results"}


def ensure_sources(who: str | None = None) -> None:
    now = time.time()
    for kind, name in (("dashboards", "Dashboards & extracts"), ("integrations", "Integrations")):
        if not db.one("SELECT 1 FROM observe_sources WHERE kind = ?", (kind,)):
            db.run("INSERT INTO observe_sources (id, kind, name, config, owner_id, status, every_min, next_check, created, updated) VALUES (?, ?, ?, '{}', ?, 'new', 60, ?, ?, ?)",
                   ("src-" + _secrets.token_hex(4), kind, name, who, now, now, now))


def _source(sid: str) -> dict:
    s = db.one("SELECT * FROM observe_sources WHERE id = ?", (sid,))
    if not s:
        raise HTTPException(404, "No such source.")
    return s


def public_source(s: dict) -> dict:
    out = {k: s[k] for k in ("id", "kind", "name", "owner_id", "status", "error", "every_min", "last_check", "next_check", "assets", "seconds", "created", "updated")}
    cfg = _j(s["config"], {})
    out["config"] = cfg
    out["label"] = SOURCE_KINDS.get(s["kind"], s["kind"])
    out["assets"] = db.one("SELECT COUNT(*) AS n FROM observe_assets WHERE source_id = ? AND enabled = 1", (s["id"],))["n"]
    if s["kind"] == "connection":
        c = db.one("SELECT id, kind, name, scope, enabled, sharing FROM connections WHERE id = ?", (cfg.get("connection_id"),))
        out["connection"] = {"id": c["id"], "kind": c["kind"], "name": c["name"], "scope": c.get("scope") or "read", "enabled": bool(c.get("enabled", 1))} if c else None
    if s["kind"] == "import":
        out["tool"] = cfg.get("tool") or "webhook"
        out["tool_label"] = oc.TOOLS.get(out["tool"], out["tool"])
        out["has_token"] = secrets_store.get("org", f"observe:{s['id']}:token") is not None
        out["hook"] = f"/auth/observe/hook/{s['id']}"
        out["incidents"] = db.one("SELECT COUNT(*) AS n FROM observe_incidents WHERE tool = ? AND status IN ('open', 'proposed', 'actioned')", (out["tool"],))["n"]
    return out


def save_source(body: dict, u: dict, sid: str | None = None) -> dict:
    have = db.one("SELECT * FROM observe_sources WHERE id = ?", (sid,)) if sid else None
    if sid and not have:
        raise HTTPException(404, "No such source.")
    kind = (have or {}).get("kind") or (body.get("kind") or "").strip()
    if kind not in ("connection", "import"):
        raise HTTPException(400, "Add a connection to watch, or another tool's results to import.")
    cfg = _j(have["config"], {}) if have else {}
    if kind == "connection":
        from . import connectors
        cid = (body.get("config") or {}).get("connection_id") or cfg.get("connection_id")
        try:
            c = connectors.connection(cid, u["id"])
        except connectors.ConnectorError:
            raise HTTPException(400, "Choose a connection you may use.")
        objs = (body.get("config") or {}).get("objects")
        if objs is not None:
            cfg["objects"] = [str(o).strip() for o in (objs if isinstance(objs, list) else str(objs).replace(";", ",").split(",")) if str(o).strip()][:200]
        cfg["connection_id"] = c["id"]
        name = str(body.get("name") or (have or {}).get("name") or f"{c['name']} ({connectors.KINDS[c['kind']]['label']})").strip()[:120]
    else:
        tool = str((body.get("config") or {}).get("tool") or cfg.get("tool") or "webhook").lower()
        if tool not in oc.TOOLS:
            raise HTTPException(400, "Tool must be one of: " + ", ".join(oc.TOOLS))
        cfg["tool"] = tool
        name = str(body.get("name") or (have or {}).get("name") or f"{oc.TOOLS[tool]} results").strip()[:120]
    every = max(5, min(int(body.get("every_min") or (have or {}).get("every_min") or 60), 24 * 60))
    now = time.time()
    sid = sid or "src-" + _secrets.token_hex(4)
    if have:
        db.run("UPDATE observe_sources SET name = ?, config = ?, every_min = ?, updated = ? WHERE id = ?", (name, json.dumps(cfg), every, now, sid))
    else:
        db.run("INSERT INTO observe_sources (id, kind, name, config, owner_id, status, every_min, next_check, created, updated) VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)",
               (sid, kind, name, json.dumps(cfg), u["id"], every, now, now, now))
    token = (body.get("token") or "").strip()
    if kind == "import" and token:
        secrets_store.put("org", f"observe:{sid}:token", token, u["id"])
    db.audit("observe.source.save", sid, {"kind": kind, "name": name, "token": "stored" if token else "kept"}, u["id"])
    if kind == "connection":
        sync_assets(who=u["id"])
    return public_source(_source(sid))


def remove_source(sid: str, u: dict) -> None:
    s = _source(sid)
    if s["kind"] in ("dashboards", "integrations"):
        raise HTTPException(400, "The dashboards and integrations are always watched; pause the source instead.")
    secrets_store.delete("org", f"observe:{sid}:token", u["id"])
    for a in db.q("SELECT id FROM observe_assets WHERE source_id = ?", (sid,)):
        db.run("UPDATE observe_assets SET enabled = 0, source_id = NULL, reader = 'none', status = 'Not readable' WHERE id = ?", (a["id"],))
    db.run("DELETE FROM observe_sources WHERE id = ?", (sid,))
    db.audit("observe.source.remove", sid, {"kind": s["kind"], "name": s["name"]}, u["id"])


# ------------------------------------------------------------------ watched assets from the graph and the connections

def _warehouse_kinds() -> set[str]:
    from . import connectors
    return {k for k, v in connectors.KINDS.items() if v.get("dialect")} | {"duckdb"}


def layer_of(n: dict, wh: set[str]) -> str:
    k, system, p = n["kind"], n.get("system") or "", n.get("properties") or {}
    if k in ("job", "flow", "bot", "api", "file_drop", "queue"):
        return "integrations"
    if k in ("report", "page"):
        return "bi"
    if k in ("measure", "entity"):
        return "semantic"
    if system.startswith("model:"):
        return "semantic"
    if p.get("upload") or ("/" in system and (":" not in system or system.index("/") < system.index(":"))):
        return "sources"
    kind_part = (p.get("warehouse") or system.split(":", 1)[0] or "").lower()
    if kind_part in wh:
        return "warehouse"
    return "sources"


def _connection_for(kind: str, obj: str) -> dict | None:
    """A connection that may read this object: a watched connection listing it, else the connection a dashboard
    extracted it from (connection_tables), with the owner's stored login."""
    for s in db.q("SELECT config FROM observe_sources WHERE kind = 'connection' AND status != 'paused'"):
        cfg = _j(s["config"], {})
        c = db.one("SELECT * FROM connections WHERE id = ? AND kind = ? AND enabled = 1", (cfg.get("connection_id"), kind))
        if c and (not cfg.get("objects") or obj in cfg["objects"] or obj.lower() in [o.lower() for o in cfg["objects"]]):
            return c
    row = db.one("SELECT c.* FROM connection_tables t JOIN connections c ON c.id = t.connection_id WHERE c.kind = ? AND t.object = ? AND c.enabled = 1 ORDER BY t.added LIMIT 1", (kind, obj))
    return row


def _reader_for(n: dict, wh: set[str]) -> tuple[str, dict, str | None]:
    """(reader, config, source id) for a node."""
    from . import connectors
    k, system, p = n["kind"], n.get("system") or "", n.get("properties") or {}
    dash = db.one("SELECT id FROM observe_sources WHERE kind = 'dashboards'")
    intan_src = db.one("SELECT id FROM observe_sources WHERE kind = 'integrations'")
    if k == "table":
        if system.startswith("model:") and p.get("from"):
            return "duckdb", {"project": system[6:], "file": p["from"]}, dash["id"] if dash else None
        if p.get("upload") and p.get("project"):
            return "duckdb", {"project": p["project"], "file": n["name"]}, dash["id"] if dash else None
        kind = (p.get("warehouse") or system.split(":", 1)[0] or "").lower()
        if kind in connectors.KINDS:
            c = _connection_for(kind, n["name"])
            if c:
                src = db.one("SELECT id FROM observe_sources WHERE kind = 'connection' AND config LIKE ?", (f'%"{c["id"]}"%',))
                sdk_kind = bool(connectors.KINDS[kind].get("sdk")) and not connectors.KINDS[kind].get("dialect")
                return ("sdk" if sdk_kind else "connection"), {"connection_id": c["id"], "object": n["name"]}, (src or {}).get("id")
        return "none", {}, None
    if k in ("flow", "job", "bot") and p.get("integration"):
        return "intan", {"integration": p["integration"]}, intan_src["id"] if intan_src else None
    if k in ("report", "page") and p.get("project"):
        return "project", {"project": p["project"]}, dash["id"] if dash else None
    return "none", {}, None


def _checks_for(kind: str, reader: str) -> list[str]:
    if kind == "table" and reader in ("duckdb", "connection", "sdk"):
        return ["freshness", "volume", "schema", "distribution", "nulls", "duplicates", "reconcile", "lineage"]
    if kind == "table":
        return ["lineage"]
    if kind in ("flow", "job", "bot"):
        return ["freshness", "lineage"]
    if kind == "report":
        return ["freshness", "lineage"]
    if kind in ("measure", "page", "column"):
        return ["lineage"]
    return []


def sync_assets(now: float | None = None, who: str | None = None) -> dict:
    """Every lineage node of a watched kind becomes an asset (idempotent, keyed by the node id); the watched
    connections' objects join the graph as table nodes first. Nodes that vanished keep their asset, disabled."""
    from . import connectors
    now = now or time.time()
    ensure_sources(who)
    lineage.ensure_synced()
    wh = _warehouse_kinds()
    for s in db.q("SELECT * FROM observe_sources WHERE kind = 'connection' AND status != 'paused'"):
        cfg = _j(s["config"], {})
        c = db.one("SELECT * FROM connections WHERE id = ?", (cfg.get("connection_id"),))
        if not c:
            continue
        objs = cfg.get("objects") or [r["object"] for r in db.q("SELECT object FROM connection_tables WHERE connection_id = ?", (c["id"],))]
        if not objs and connectors.KINDS.get(c["kind"], {}).get("sdk"):
            try:
                row = {**c, "config": _j(c["config"], {})}
                objs = [o["object"] for o in connectors.browse(row, "")][:50]
            except Exception:  # noqa: BLE001 - a platform that does not answer now is watched once it does
                objs = []
        for o in objs:
            lineage.upsert_node("table", c["kind"], o, label=f"{o} ({connectors.KINDS[c['kind']]['label']})", properties={"source_key": f"{c['kind']}:{o}", "warehouse": c["kind"], "connection": c["id"]}, source=f"observe:{s['id']}", now=now)
    seen, added = set(), 0
    for n in db.q(f"SELECT * FROM lineage_nodes WHERE kind IN ({','.join('?' * len(WATCH_KINDS))})", WATCH_KINDS):
        n = lineage._public(n)
        reader, cfg, sid = _reader_for(n, wh)
        aid = _aid(n["id"])
        seen.add(aid)
        layer = layer_of(n, wh)
        have = db.one("SELECT id, reader, config FROM observe_assets WHERE id = ?", (aid,))
        if have:
            db.run("UPDATE observe_assets SET kind = ?, layer = ?, name = ?, label = ?, system = ?, source_id = ?, reader = ?, config = ?, seen = ?, enabled = 1 WHERE id = ?",
                   (n["kind"], layer, n["name"], n["label"], n.get("system"), sid, reader, json.dumps(cfg), now, aid))
        else:
            db.run("INSERT INTO observe_assets (id, node_id, kind, layer, name, label, system, source_id, reader, config, enabled, status, seen, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                   (aid, n["id"], n["kind"], layer, n["name"], n["label"], n.get("system"), sid, reader, json.dumps(cfg), "Unknown" if reader != "none" else ("Watched" if n["kind"] != "table" else "Not readable"), now, now))
            added += 1
        for ck in _checks_for(n["kind"], reader):
            db.run("INSERT OR IGNORE INTO observe_checks (asset_id, check_kind, enabled, config) VALUES (?, ?, 1, '{}')", (aid, ck))
    gone = 0
    for a in db.q("SELECT id, node_id FROM observe_assets WHERE enabled = 1"):
        if a["id"] not in seen and a["node_id"] and not lineage.get(a["node_id"]):
            db.run("UPDATE observe_assets SET enabled = 0, status = 'Gone', seen = ? WHERE id = ?", (now, a["id"]))
            gone += 1
    for s in db.q("SELECT id, kind FROM observe_sources WHERE kind != 'import'"):
        db.run("UPDATE observe_sources SET assets = (SELECT COUNT(*) FROM observe_assets WHERE source_id = ? AND enabled = 1), updated = ? WHERE id = ?", (s["id"], now, s["id"]))
    db.set_meta("observe_synced", str(now))
    db.audit("observe.sync", None, {"assets": len(seen), "added": added, "gone": gone}, who or "system")
    return {"assets": len(seen), "added": added, "gone": gone}


def ensure_synced(max_age: float = 300) -> None:
    if time.time() - float(db.meta("observe_synced", "0") or 0) > max_age:
        sync_assets()


def _asset(aid: str) -> dict:
    a = db.one("SELECT * FROM observe_assets WHERE id = ?", (aid,))
    if not a:
        raise HTTPException(404, "No such asset.")
    a["config"] = _j(a["config"], {})
    return a


def asset_by_node(node_id: str) -> dict | None:
    a = db.one("SELECT * FROM observe_assets WHERE node_id = ?", (node_id,))
    if a:
        a["config"] = _j(a["config"], {})
    return a


# ------------------------------------------------------------------ observations and baselines

def record(asset_id: str, check: str, ts: float, value: dict, anomaly: bool = False, expected: bool = False) -> int:
    db.run("INSERT INTO observe_observations (asset_id, check_kind, ts, value, expected, anomaly) VALUES (?, ?, ?, ?, ?, ?)", (asset_id, check, ts, json.dumps(value, default=str), 1 if expected else 0, 1 if anomaly else 0))
    row = db.one("SELECT MAX(id) AS id FROM observe_observations WHERE asset_id = ? AND check_kind = ?", (asset_id, check))
    db.run("DELETE FROM observe_observations WHERE asset_id = ? AND check_kind = ? AND ts < ?", (asset_id, check, ts - 120 * 86400))
    return int(row["id"])


def history(asset_id: str, check: str, before: float, window_days: int = 42) -> list[tuple[float, dict]]:
    """Earlier observations for the baseline: normal ones and the ones a person marked expected (anomalies left out)."""
    rows = db.q("SELECT ts, value, expected, anomaly FROM observe_observations WHERE asset_id = ? AND check_kind = ? AND ts < ? AND ts >= ? AND (anomaly = 0 OR expected = 1) ORDER BY ts",
                (asset_id, check, before, before - window_days * 86400))
    return [(r["ts"], _j(r["value"], {})) for r in rows]


def _accepted(asset_id: str, check: str) -> list[dict]:
    row = db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = ?", (asset_id, check))
    return list((_j(row["config"], {}) if row else {}).get("accepted") or [])


def _reader(a: dict, who: str = "observe"):
    from . import connectors
    cfg = a["config"]
    if a["reader"] == "duckdb":
        try:
            d = store.project_dir(cfg["project"])
        except KeyError:
            raise oc.ReadError("The dashboard this table belongs to is gone.")
        return oc.DuckReader(d, cfg["file"])
    if a["reader"] in ("connection", "sdk"):
        try:
            c = connectors._row(cfg["connection_id"])
        except connectors.ConnectorError:
            raise oc.ReadError("The connection that read this table is gone.")
        if not c.get("enabled", 1):
            raise oc.ReadError(f"{c['name']} is disabled under Connections.")
        return oc.SqlReader(c, cfg["object"], who) if a["reader"] == "connection" else oc.SdkReader(c, cfg["object"], who)
    raise oc.ReadError("Not readable: no connection reads this table yet.")


def _learned_cadence(asset_id: str, now: float, cfg: dict) -> float | None:
    loads = [v.get("loaded_at") for _, v in history(asset_id, "freshness", now, 60)]
    return oc.learned_cadence_h([x for x in loads if x], int(cfg.get("min_history") or 3))


def _schedule_cadence(a: dict) -> float | None:
    """The cadence the platform knows: a dashboard's daily extract refresh, an integration's own schedule."""
    cfg = a["config"]
    if a["reader"] in ("duckdb", "project") and cfg.get("project"):
        try:
            st = store.load(cfg["project"])
        except (KeyError, FileNotFoundError, ValueError):
            return None
        if (st.get("extract_schedule") or {}).get("daily"):
            return 24.0
    if a["reader"] == "intan":
        i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (cfg.get("integration"),))
        if i:
            props = _j(i["properties"], {})
            if props.get("every_min"):
                return float(props["every_min"]) / 60
            runs = db.q("SELECT started FROM intan_runs WHERE integration_id = ? ORDER BY started DESC LIMIT 12", (i["id"],))
            return oc.learned_cadence_h([r["started"] for r in runs], 3)
    return None


def _upstream_source(a: dict) -> dict | None:
    """The table that feeds this one (the lineage `feeds` edge), when it is a readable asset of its own."""
    if not a.get("node_id"):
        return None
    for e in db.q("SELECT from_id FROM lineage_edges WHERE to_id = ? AND kind = 'feeds'", (a["node_id"],)):
        up = asset_by_node(e["from_id"])
        if up and up["reader"] in ("duckdb", "connection", "sdk") and up["enabled"] and not (up["reader"] == a["reader"] == "duckdb" and up["config"] == a["config"]):
            return up
    return None


# ------------------------------------------------------------------ running the checks

def _measure_table(a: dict, now: float, gcfg: dict, who: str, cache: dict) -> tuple[list[dict], dict]:
    """Read one table once, store the observations, evaluate every enabled check. Returns (findings, measurements)."""
    if a["id"] in cache:
        return [], cache[a["id"]]
    enabled = {r["check_kind"]: r for r in db.q("SELECT * FROM observe_checks WHERE asset_id = ? AND enabled = 1", (a["id"],))}
    reader = _reader(a, who)
    label = a["label"] or a["name"]
    try:
        cols = reader.columns()
        dist_cfg = oc.cfg_for("distribution", gcfg.get("distribution"), _j(enabled["distribution"]["config"], {}) if "distribution" in enabled else None)
        stats = reader.stats(cols, int(dist_cfg.get("topk") or 8), int(dist_cfg.get("max_columns") or 24))
        n = stats["rows"]
        loaded_at = reader.loaded_at()
    finally:
        reader.close()
    fr_cfg = oc.cfg_for("freshness", gcfg.get("freshness"), _j(enabled["freshness"]["config"], {}) if "freshness" in enabled else None)
    max_date = None
    date_col = fr_cfg.get("date_column") or next((c["name"] for c in cols if c["kind"] == "date" and not loaded_at), None)
    if date_col and (stats["columns"].get(date_col) or {}).get("max"):
        max_date = oc._ts(stats["columns"][date_col]["max"])
    hist_profile = history(a["id"], "profile", now, int(dist_cfg.get("window_days") or 42))
    hist_volume = history(a["id"], "volume", now, int(oc.cfg_for("volume", gcfg.get("volume")).get("window_days") or 42))
    last_schema = next((v.get("columns") for _, v in reversed(history(a["id"], "schema", now, 120)) if v.get("columns") is not None), None)
    cadence = fr_cfg.get("cadence_h") or _learned_cadence(a["id"], now, fr_cfg) or _schedule_cadence(a)
    findings: list[dict] = []
    if "freshness" in enabled:
        f = oc.check_freshness(now, loaded_at, max_date, fr_cfg, cadence, label, [x.get("age_h", 0) * 3600 for x in _accepted(a["id"], "freshness")])
        if f:
            findings.append(f)
    if "volume" in enabled:
        vcfg = oc.cfg_for("volume", gcfg.get("volume"), _j(enabled["volume"]["config"], {}))
        base = oc.baseline([(t, v.get("rows")) for t, v in hist_volume], now, int(vcfg.get("window_days") or 42), int(vcfg.get("weekday_min") or 3))
        f = oc.check_volume(n, base, vcfg, label, [x.get("rows") for x in _accepted(a["id"], "volume") if x.get("rows") is not None])
        if f:
            findings.append(f)
    if "schema" in enabled:
        f = oc.check_schema(cols, last_schema, oc.cfg_for("schema", gcfg.get("schema"), _j(enabled["schema"]["config"], {})), label)
        if f:
            findings.append(f)
    if "distribution" in enabled:
        findings += oc.check_distribution(stats, hist_profile, dist_cfg, now, label, {x.get("column"): x.get("shift_pct", x.get("shift")) for x in _accepted(a["id"], "distribution") if x.get("column")})
    keys = [k.strip() for k in str(oc.cfg_for("duplicates", gcfg.get("duplicates"), _j(enabled["duplicates"]["config"], {}) if "duplicates" in enabled else None).get("keys") or "").split(",") if k.strip()]
    if not keys:
        keys = oc.learned_keys([v for _, v in hist_profile], cols)
    keys = [k for k in keys if k in stats["columns"]]
    if "nulls" in enabled:
        findings += oc.check_nulls(stats, hist_profile, oc.cfg_for("nulls", gcfg.get("nulls"), _j(enabled["nulls"]["config"], {})), now, label, keys, {x.get("column"): x.get("jump_pp") for x in _accepted(a["id"], "nulls") if x.get("column")})
    if "duplicates" in enabled and keys:
        dcfg = oc.cfg_for("duplicates", gcfg.get("duplicates"), _j(enabled["duplicates"]["config"], {}))
        try:
            rd = _reader(a, who)
            try:
                d = rd.dupes(keys)
            finally:
                rd.close()
        except oc.ReadError:
            d = 0
        f = oc.check_duplicates(d, keys, dcfg, label, n)
        if f and not any(x.get("duplicates", -1) >= d for x in _accepted(a["id"], "duplicates")):
            findings.append(f)
    anomalies = {f["check"] for f in findings}
    record(a["id"], "profile", now, {"columns": stats["columns"]}, anomaly=bool(anomalies & {"distribution", "nulls", "duplicates"}))   # an anomaly never teaches the baseline
    record(a["id"], "volume", now, {"rows": n}, anomaly="volume" in anomalies)
    record(a["id"], "schema", now, {"columns": cols}, anomaly="schema" in anomalies)
    record(a["id"], "freshness", now, {"loaded_at": loaded_at, "max_date": max_date, "late": "freshness" in anomalies}, anomaly="freshness" in anomalies)
    m = {"rows": n, "columns": cols, "stats": stats, "loaded_at": loaded_at, "max_date": max_date, "keys": keys, "cadence_h": cadence}
    cache[a["id"]] = m
    return findings, m


def _measure_integration(a: dict, now: float, gcfg: dict) -> list[dict]:
    i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (a["config"].get("integration"),))
    label = a["label"] or a["name"]
    enabled = {r["check_kind"] for r in db.q("SELECT check_kind FROM observe_checks WHERE asset_id = ? AND enabled = 1", (a["id"],))}
    out = []
    if not i:
        if "lineage" in enabled:
            out.append(oc.finding("lineage", "high", f"{label} is no longer found by its tool", "the integration disappeared from the last discovery scan", {"found": False}, {"found": True},
                                  [["Found by the tool", "no", "yes"]], cause="The integration was removed or renamed; what it fed is no longer loaded."))
        return out
    runs = db.q("SELECT * FROM intan_runs WHERE integration_id = ? ORDER BY started DESC LIMIT 12", (i["id"],))
    last = runs[0] if runs else None
    cadence = oc.cfg_for("freshness", gcfg.get("freshness"), _j((db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = 'freshness'", (a["id"],)) or {}).get("config"), {})).get("cadence_h") or _schedule_cadence(a)
    lcfg = oc.cfg_for("lineage", gcfg.get("lineage"), _j((db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = 'lineage'", (a["id"],)) or {}).get("config"), {}))
    record(a["id"], "freshness", now, {"loaded_at": last["started"] if last else None, "status": last["status"] if last else None})
    if "lineage" in enabled:
        if not i["active"]:
            out.append(oc.finding("lineage", "high", f"{label} stopped: no longer in the tool", "its last discovery scan did not list it", {"active": False}, {"active": True}, [["Listed by the tool", "no", "yes"]], cause="Removed or renamed in the tool; downstream tables stop loading."))
        elif last and last["status"] == "failed":
            out.append(oc.finding("lineage", "high", f"{label} failed its last run", (last["error"] or "no error text")[:160], {"status": "failed", "error": (last["error"] or "")[:300], "when": last["started"]}, {"status": "success"},
                                  [["Last run", f"failed {_when(last['started'])}", "success"], ["Error", (last["error"] or "-")[:120], "-"]], cause=(last["error"] or "The run failed.")[:200]))
        elif cadence and last and now - last["started"] > float(cadence) * 3600 * max(1, int(lcfg.get("missed_runs") or 2)):
            out.append(oc.finding("lineage", "high", f"{label} stopped running", f"last run {_when(last['started'])}; expected every {oc._fmt(float(cadence))} h", {"last_run": last["started"], "age_h": round((now - last["started"]) / 3600, 1)}, {"cadence_h": float(cadence), "missed_runs": lcfg.get("missed_runs")},
                                  [["Last run", _when(last["started"]), f"every {oc._fmt(float(cadence))} h"]], cause="The schedule stopped or the tool is down; nothing downstream is loaded."))
    if "freshness" in enabled and cadence and last and not out:
        f = oc.check_freshness(now, last["started"], None, {"cadence_h": cadence, "grace": 1.5}, None, label)
        if f:
            out.append(f)
    return out


def _measure_report(a: dict, now: float, gcfg: dict) -> list[dict]:
    """A report's freshness is its extracts': the newest load of its data files against the extract schedule."""
    try:
        st = store.load(a["config"]["project"])
        d = store.project_dir(a["config"]["project"])
    except (KeyError, FileNotFoundError, ValueError):
        return [oc.finding("lineage", "high", f"{a['label'] or a['name']} is gone", "its dashboard folder no longer exists", {"exists": False}, {"exists": True}, [["Dashboard folder", "missing", "present"]], cause="The dashboard was removed.")]
    from . import connectors
    loads = [m.get("extracted") for m in connectors.manifest(d).values() if m.get("extracted")]
    loaded = min(loads) if loads else None
    record(a["id"], "freshness", now, {"loaded_at": loaded, "status": st.get("status")})
    out = []
    enabled = {r["check_kind"] for r in db.q("SELECT check_kind FROM observe_checks WHERE asset_id = ? AND enabled = 1", (a["id"],))}
    if "freshness" in enabled and st.get("status") == "error" and str(st.get("error") or "").lower().startswith(("extract", "scheduled refresh")):
        out.append(oc.finding("freshness", "high", f"Refresh failing for {a['label'] or a['name']}", str(st.get("error"))[:160], {"status": "error", "error": str(st.get("error"))[:300]}, {"status": "refreshed"},
                              [["Last refresh", "failed", "ok"], ["Error", str(st.get("error"))[:120], "-"]], cause=str(st.get("error"))[:200]))
    return out


def _lineage_breaks(assets: list[dict], now: float) -> list[tuple[dict, dict]]:
    """Edges whose node no longer exists, measures and pages whose columns vanished: a finding per affected asset."""
    out = []
    ids = {r["id"] for r in db.q("SELECT id FROM lineage_nodes")}
    for a in assets:
        if not a.get("node_id"):
            continue
        if a["enabled"] and a["node_id"] not in ids:
            out.append((a, oc.finding("lineage", "high", f"{a['label'] or a['name']} is no longer on the map", "the node disappeared while things still depended on it", {"exists": False}, {"exists": True}, [["On the map", "no", "yes"]],
                                      cause="Removed from its source or from the model; what read it is broken.")))
            continue
        dangling = [e for e in db.q("SELECT from_id, to_id, kind FROM lineage_edges WHERE to_id = ? OR from_id = ?", (a["node_id"], a["node_id"])) if e["from_id"] not in ids or e["to_id"] not in ids]
        if dangling and a["kind"] in ("measure", "page", "table", "report"):
            out.append((a, oc.finding("lineage", "high", f"{a['label'] or a['name']} reads something that no longer exists", f"{len(dangling)} broken link{'s' if len(dangling) != 1 else ''}", {"broken_links": len(dangling)}, {"broken_links": 0},
                                      [["Links to missing items", str(len(dangling)), "0"]], cause="A column or table it uses was removed upstream.")))
    return out


def _upstream_ids(node_id: str, up_adj: dict) -> set[str]:
    return set(lineage._walk(node_id, up_adj, None))


def run_checks(asset_ids: list[str] | None = None, source: str | None = None, now: float | None = None, who: str = "observe") -> dict:
    """Run every enabled check on the chosen assets (default: all), store observations, open / update / resolve
    incidents with their impact, and update each asset's status. Not an LLM run."""
    now = now or time.time()
    ensure_synced()
    gcfg = settings()
    sql, args = "SELECT * FROM observe_assets WHERE enabled = 1", []
    if asset_ids:
        sql += f" AND id IN ({','.join('?' * len(asset_ids))})"; args += list(asset_ids)
    if source:
        sql += " AND source_id = ?"; args.append(source)
    assets = db.q(sql, tuple(args))
    for a in assets:
        a["config"] = _j(a["config"], {})
    cache: dict = {}
    findings: list[tuple[dict, dict]] = []
    errors = 0
    checked = set()
    oc.DuckReader.reset()
    for a in assets:
        try:
            if a["kind"] == "table" and a["reader"] in ("duckdb", "connection", "sdk"):
                fs, _ = _measure_table(a, now, gcfg, who, cache)
                findings += [(a, f) for f in fs]
                checked.add(a["id"])
            elif a["reader"] == "intan":
                findings += [(a, f) for f in _measure_integration(a, now, gcfg)]
                checked.add(a["id"])
            elif a["reader"] == "project":
                findings += [(a, f) for f in _measure_report(a, now, gcfg)]
                checked.add(a["id"])
        except oc.ReadError as e:
            errors += 1
            db.run("UPDATE observe_assets SET status = 'Not readable', signal = ?, last_check = ? WHERE id = ?", (str(e)[:300], now, a["id"]))
            db.run("UPDATE observe_checks SET last_run = ?, last_status = 'error', last_text = ? WHERE asset_id = ?", (now, str(e)[:300], a["id"]))
        except Exception as e:  # noqa: BLE001 - one unreadable asset never stops the run
            traceback.print_exc()
            errors += 1
            db.run("UPDATE observe_assets SET status = 'Not readable', signal = ?, last_check = ? WHERE id = ?", (str(e)[:300], now, a["id"]))
    # reconciliation: a readable table against the readable table that feeds it
    for a in assets:
        if a["id"] in cache and db.one("SELECT 1 FROM observe_checks WHERE asset_id = ? AND check_kind = 'reconcile' AND enabled = 1", (a["id"],)):
            up = _upstream_source(a)
            if not up:
                continue
            try:
                if up["id"] not in cache:
                    _measure_table(up, now, gcfg, who, cache)
                f = oc.check_reconcile(cache[a["id"]]["stats"], cache[up["id"]]["stats"], oc.cfg_for("reconcile", gcfg.get("reconcile"), _j((db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = 'reconcile'", (a["id"],)) or {}).get("config"), {})),
                                      a["label"] or a["name"], up["label"] or up["name"])
                if f:
                    findings.append((a, f))
            except oc.ReadError:
                pass
    findings += _lineage_breaks(assets, now)
    for a in assets:
        checked.add(a["id"])
    new_ids, folded = _store_findings(findings, now, cache)
    resolved = _resolve_missing(checked, {(a["id"], f["check"], f.get("column") or "") for a, f in findings}, now)
    _update_status(checked, now)
    for a in assets:
        db.run("UPDATE observe_checks SET last_run = ?, last_status = CASE WHEN last_status = 'error' AND last_run = ? THEN 'error' ELSE 'ok' END WHERE asset_id = ?", (now, now, a["id"]))
    for a, f in findings:
        db.run("UPDATE observe_checks SET last_status = 'incident', last_text = ? WHERE asset_id = ? AND check_kind = ?", (f["title"][:200], a["id"], f["check"]))
    db.run("UPDATE observe_sources SET last_check = ?, next_check = ?, status = 'ok', updated = ? WHERE kind != 'import' AND status != 'paused'" + (" AND id = ?" if source else ""), (now, now + 3600, now, source) if source else (now, now + 3600, now))
    db.run("UPDATE observe_sources SET next_check = last_check + every_min * 60 WHERE kind != 'import' AND last_check IS NOT NULL")
    out = {"assets": len(assets), "checked": len(checked), "findings": len(findings), "incidents_new": len(new_ids), "folded": folded, "resolved": resolved, "errors": errors, "at": now}
    db.audit("observe.check", source or "all", out, who)
    return out


def _store_findings(findings: list[tuple[dict, dict]], now: float, cache: dict) -> tuple[list[str], int]:
    """New incidents, or the same ones seen again; a finding whose cause sits upstream folds into that incident."""
    edges = lineage._edges()
    up_adj, _ = lineage._adjacency(edges)
    open_rows = db.q("SELECT * FROM observe_incidents WHERE status IN ('open', 'proposed', 'actioned', 'expected')")
    open_by_asset: dict[str, list[dict]] = collections.defaultdict(list)
    for r in open_rows:
        open_by_asset[r["asset_id"]].append(r)
    node_of = {a["id"]: a["node_id"] for a in db.q("SELECT id, node_id FROM observe_assets")}
    asset_of_node = {v: k for k, v in node_of.items() if v}
    # roots first: a finding on an asset with fewer upstream assets in this run is handled before its dependants
    order = []
    for a, f in findings:
        ups = _upstream_ids(a["node_id"], up_adj) if a.get("node_id") else set()
        order.append((len(ups), a, f, ups))
    order.sort(key=lambda x: (x[0], x[1]["label"] or x[1]["name"]))
    created_now: dict[str, dict] = {}
    new_ids, folded = [], 0
    for _, a, f, ups in order:
        col = f.get("column") or ""
        have = next((r for r in open_by_asset.get(a["id"], []) if r["check_kind"] == f["check"] and (r["column_name"] or "") == col and r["tool"] == "relay"), None)
        if have:                                                      # seen before: the same incident, brought up to date
            reopen = have["status"] == "expected"                     # beyond what a person accepted: it is an incident again
            db.run("UPDATE observe_incidents SET title = ?, what = ?, measured = ?, expected = ?, rows = ?, severity = ?, last_seen = ?, status = ?, first_seen = ?, resolved = ?, resolved_by = ?, resolved_how = ? WHERE id = ?",
                   (f["title"], f["what"], json.dumps(f["measured"], default=str), json.dumps(f["expected"], default=str), json.dumps(f["rows"], default=str), f["severity"], now,
                    "open" if reopen else have["status"], now if reopen else have["first_seen"], None if reopen else have["resolved"], None if reopen else have["resolved_by"], None if reopen else have["resolved_how"], have["id"]))
            continue
        root = None
        for up_node in ups:
            up_asset = asset_of_node.get(up_node)
            if not up_asset:
                continue
            for r in open_by_asset.get(up_asset, []) + [x for x in created_now.values() if x["asset_id"] == up_asset]:
                if r["status"] in ("resolved", "dismissed"):
                    continue
                same = r["check_kind"] == f["check"]
                cause_of_staleness = r["check_kind"] == "lineage" and f["check"] in ("freshness", "volume")
                if same or cause_of_staleness:
                    root = r
                    break
            if root:
                break
        if root:
            also = _j(root.get("also"), []) if isinstance(root.get("also"), str) else list(root.get("also") or [])
            if a["id"] not in [x.get("asset_id") for x in also]:
                also.append({"asset_id": a["id"], "label": a["label"] or a["name"], "check": f["check"], "title": f["title"]})
            db.run("UPDATE observe_incidents SET also = ?, last_seen = ? WHERE id = ?", (json.dumps(also), now, root["id"]))
            root["also"] = also
            folded += 1
            continue
        asset_col = _column_asset(a, col) if col and a["kind"] == "table" else None
        imp = impact_of(a, now)
        sev = _severity(f, imp, a)
        iid = "ob-" + _secrets.token_hex(4)
        db.run("INSERT INTO observe_incidents (id, check_kind, asset_id, column_name, severity, title, what, measured, expected, rows, cause, route, status, tool, impact, also, first_seen, last_seen) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 'relay', ?, '[]', ?, ?)",
               (iid, f["check"], a["id"], col, sev, f["title"], f["what"], json.dumps(f["measured"], default=str), json.dumps(f["expected"], default=str), json.dumps(f["rows"], default=str), f.get("cause"),
                _route_for(f, a), json.dumps(_compact_impact(imp), default=str), now, now))
        if asset_col:
            db.run("UPDATE observe_incidents SET also = ? WHERE id = ?", (json.dumps([{"asset_id": asset_col["id"], "label": asset_col["label"] or asset_col["name"], "check": f["check"], "title": f["title"], "column": True}]), iid))
        row = db.one("SELECT * FROM observe_incidents WHERE id = ?", (iid,))
        created_now[iid] = row
        open_by_asset[a["id"]].append(row)
        new_ids.append(iid)
        db.audit("observe.incident", iid, {"check": f["check"], "asset": a["label"] or a["name"], "severity": sev, "reports": imp["reports"][:5], "people": imp["people"]}, "system")
        _notify_incident(row, a, imp)
    return new_ids, folded


def _column_asset(a: dict, col: str) -> dict | None:
    """The column node the table contains whose name (or model label) is this column, when it is watched."""
    if not a.get("node_id"):
        return None
    want = col.lower()
    for e in db.q("SELECT to_id FROM lineage_edges WHERE from_id = ? AND kind = 'contains'", (a["node_id"],)):
        n = lineage.get(e["to_id"])
        if n and n["kind"] == "column" and (n["name"].lower() == want or n["name"].lower().endswith("." + want) or n["label"].lower().endswith(f"[{want}]") or n["label"].lower().endswith("." + want)):
            return asset_by_node(n["id"])
    return None


def _notify_incident(row: dict, a: dict, imp: dict) -> None:
    """Owners of the affected dashboards hear about a high incident at once (no banner yet: that is a decision)."""
    if row["severity"] != "high":
        return
    for uid in imp.get("owner_ids") or []:
        notify.add(uid, "alert", f"Data incident: {row['title'][:120]}", f"{oc.CHECK_LABEL.get(row['check_kind'], row['check_kind'])} on {a['label'] or a['name']} - {imp['text']}", f"{ROUTE}?open={row['id']}")


def _severity(f: dict, imp: dict, a: dict) -> str:
    sev = f["severity"]
    if imp["reports"] and f["check"] in ("freshness", "volume", "reconcile", "lineage", "duplicates"):
        return "high"
    if not imp["downstream"] and not imp["reports"] and sev == "high" and a["kind"] != "report":
        return "medium"
    return sev


def _route_for(f: dict, a: dict) -> str:
    if a["layer"] == "integrations":
        return "sdlc" if f["check"] == "schema" else "heal"
    return SUGGEST.get(f["check"], "ticket")


def _resolve_missing(checked: set[str], seen: set[tuple], now: float) -> int:
    n = 0
    for r in db.q("SELECT * FROM observe_incidents WHERE tool = 'relay' AND status IN ('open', 'proposed', 'actioned')"):   # an 'expected' one is closed already
        if r["asset_id"] in checked and (r["asset_id"], r["check_kind"], r["column_name"] or "") not in seen:
            db.run("UPDATE observe_incidents SET status = 'resolved', resolved = ?, resolved_by = 'relay', resolved_how = COALESCE(resolved_how, ?) WHERE id = ?",
                   (now, "owner fixed at source" if r["status"] in ("open", "proposed") else "fix approved", r["id"]))
            checkpoints.withdraw(KIND, r["id"])
            db.run("UPDATE observe_work SET status = 'withdrawn', decided = ? WHERE incident_id = ? AND status = 'proposed'", (now, r["id"]))
            n += 1
    return n


def _update_status(asset_ids: set[str], now: float) -> None:
    open_rows = db.q("SELECT asset_id, severity, title, also FROM observe_incidents WHERE status IN ('open', 'proposed', 'actioned')")
    worst: dict[str, tuple[int, str]] = {}
    for r in open_rows:
        for aid in [r["asset_id"]] + [x.get("asset_id") for x in _j(r["also"], [])]:
            cur = worst.get(aid)
            rank = SEV_ORDER.get(r["severity"], 2)
            if cur is None or rank < cur[0]:
                worst[aid] = (rank, r["title"])
    for aid in asset_ids:
        a = db.one("SELECT reader, kind, status FROM observe_assets WHERE id = ?", (aid,))
        if not a or (a["status"] == "Not readable" and aid not in worst and a["reader"] != "none"):
            continue
        if aid in worst:
            st = "Failing" if worst[aid][0] == 0 else "Warning"
            db.run("UPDATE observe_assets SET status = ?, signal = ?, last_check = ? WHERE id = ?", (st, worst[aid][1][:300], now, aid))
        elif a["reader"] == "none":
            db.run("UPDATE observe_assets SET status = ?, signal = NULL, last_check = ? WHERE id = ?", ("Watched" if a["kind"] != "table" else "Not readable", now, aid))
        else:
            db.run("UPDATE observe_assets SET status = 'Healthy', signal = NULL, last_check = ? WHERE id = ?", (now, aid))


# ------------------------------------------------------------------ impact: everything downstream, people included

def impact_of(a: dict, now: float | None = None) -> dict:
    """Downstream of the asset on the graph (reports, pages, measures, tables, jobs), then the consumers the platform
    knows: the dashboards' owners and the people they are shared with, schedules and their recipients, Ask D
    answers that used the data (30 days), agent runs on those dashboards (30 days). With the path for the map."""
    now = now or time.time()
    nid = a.get("node_id")
    nodes: dict[str, dict] = {}
    path_nodes: list[dict] = []
    path_edges: list[dict] = []
    if nid and lineage.get(nid):
        edges = lineage._edges()
        _, down = lineage._adjacency(edges)
        hops = lineage._walk(nid, down, None)
        nodes = lineage._nodes(list(hops))
        focus = lineage.get(nid)
        keep = {nid} | set(nodes)
        # a BFS tree from the asset: the path the drawer draws (bounded)
        allowed = sorted(hops, key=lambda i: hops[i])[:60]
        tree = {nid} | set(allowed)
        path_nodes = [{**focus, "role": "focus", "hop": 0}] + [{**nodes[i], "role": "down", "hop": hops[i]} for i in allowed if i in nodes]
        seen_e = set()
        for e in edges:
            u, d = lineage._flow(e)
            if u in tree and d in tree and (u, d) not in seen_e:
                seen_e.add((u, d))
                path_edges.append({"from": e["from_id"], "to": e["to_id"], "kind": e["kind"]})
        _ = keep
    by_kind = collections.Counter(n["kind"] for n in nodes.values())
    reports = [n for n in nodes.values() if n["kind"] == "report"]
    if a["kind"] == "report" and a["config"].get("project"):
        reports = reports + [{"label": a["label"] or a["name"], "properties": {"project": a["config"]["project"]}, "id": nid}]
    pids = []
    for r in reports:
        pid = (r.get("properties") or {}).get("project")
        if pid and pid not in pids:
            pids.append(pid)
    people: set[str] = set()
    owner_ids: set[str] = set()
    for pid in pids:
        p = db.project(pid)
        if p:
            owner_ids.add(p["owner_id"])
            people.add(p["owner_id"])
            try:
                people |= auth.visible_to(p)
            except Exception:  # noqa: BLE001
                pass
    schedules = []
    for s in db.q("SELECT id, name, kind, target, recipients, owner_id FROM schedules WHERE status = 'active'"):
        t = _j(s["target"], {})
        proj = t.get("project") or (t.get("scope") or {}).get("project")
        if proj in pids:
            schedules.append({"id": s["id"], "name": s["name"], "kind": s["kind"], "recipients": _j(s["recipients"], [])})
            people |= set(_j(s["recipients"], []))
            people.add(s["owner_id"])
    table_names = {n["name"].split(".")[-1].lower() for n in nodes.values() if n["kind"] == "table"} | ({a["name"].split(".")[-1].lower()} if a["kind"] == "table" else set())
    model_tables = {n["name"].lower() for n in nodes.values() if n["kind"] == "table" and (n.get("system") or "").startswith("model:")}
    answers = 0
    for row in db.q("SELECT detail, who FROM audit WHERE action = 'askd.question' AND ts >= ?", (now - 30 * 86400,)):
        d = _j(row["detail"], {})
        used = {str(t).split(".")[-1].lower() for t in (d.get("tables") or [])}
        where = str(d.get("where") or "")
        if used & (table_names | model_tables) or any(pid in where for pid in pids):
            answers += 1
            if row["who"]:
                people.add(row["who"])
    runs = db.one(f"SELECT COUNT(*) AS n FROM jobs WHERE created >= ? AND pid IN ({','.join('?' * len(pids))})", (now - 30 * 86400, *pids))["n"] if pids else 0
    names = {u["id"]: u["name"] for u in db.q("SELECT id, name FROM users WHERE active = 1")}
    people = {p for p in people if p in names}
    # the consumers as nodes on the path
    rep_ids = {r.get("id") for r in reports if r.get("id")}
    for s in schedules:
        sid = "v-sch-" + s["id"]
        path_nodes.append({"id": sid, "kind": "flow", "label": f"Schedule: {s['name']}", "name": s["name"], "role": "down", "hop": 99, "status": None, "virtual": True})
        for rid in rep_ids:
            path_edges.append({"from": rid, "to": sid, "kind": "feeds"})
    if answers:
        path_nodes.append({"id": "v-askd", "kind": "entity", "label": f"Ask D: {answers} answer{'s' if answers != 1 else ''}", "name": "Ask D", "role": "down", "hop": 99, "virtual": True})
        for rid in rep_ids:
            path_edges.append({"from": rid, "to": "v-askd", "kind": "feeds"})
    for uid in sorted(people, key=lambda x: names.get(x, x))[:12]:
        pn = "v-p-" + uid
        path_nodes.append({"id": pn, "kind": "owner", "label": names.get(uid, uid), "name": names.get(uid, uid), "role": "down", "hop": 100, "virtual": True})
        for rid in rep_ids:
            path_edges.append({"from": rid, "to": pn, "kind": "owns"})
    parts = []
    if reports:
        parts.append(f"{len(reports)} report{'s' if len(reports) != 1 else ''}")
    if schedules:
        parts.append(f"{len(schedules)} schedule{'s' if len(schedules) != 1 else ''}")
    if answers:
        parts.append(f"{answers} Ask D answer{'s' if answers != 1 else ''}")
    if runs:
        parts.append(f"{runs} agent run{'s' if runs != 1 else ''}")
    if people:
        parts.append(f"{len(people)} {'person' if len(people) == 1 else 'people'}")
    return {"downstream": len(nodes), "by_kind": dict(by_kind), "reports": [r["label"] for r in reports][:20], "projects": pids, "schedules": len(schedules), "schedule_names": [s["name"] for s in schedules][:10],
            "answers": answers, "runs": runs, "people": len(people), "people_ids": sorted(people), "people_names": [names[p] for p in sorted(people, key=lambda x: names.get(x, x))][:12], "owner_ids": sorted(owner_ids),
            "text": ("Touches " + ", ".join(parts) + ".") if parts else ("Nothing downstream yet." if not nodes else f"{len(nodes)} downstream item{'s' if len(nodes) != 1 else ''}, no report yet."),
            "path": {"nodes": path_nodes, "edges": path_edges}}


def _compact_impact(imp: dict) -> dict:
    return {k: v for k, v in imp.items() if k != "path"}


# ------------------------------------------------------------------ incidents: reading, marking, acting (with approval)

def _incident(iid: str) -> dict:
    r = db.one("SELECT * FROM observe_incidents WHERE id = ?", (iid,))
    if not r:
        raise HTTPException(404, "No such incident.")
    return _public_incident(r)


def _public_incident(r: dict) -> dict:
    out = dict(r)
    for k, dflt in (("measured", {}), ("expected", {}), ("rows", []), ("impact", {}), ("also", [])):
        out[k] = _j(r[k], dflt)
    a = db.one("SELECT * FROM observe_assets WHERE id = ?", (r["asset_id"],))
    out["asset"] = {"id": a["id"], "label": a["label"] or a["name"], "name": a["name"], "kind": a["kind"], "layer": a["layer"], "layer_label": LAYER_LABEL.get(a["layer"], a["layer"]), "system": a["system"], "node_id": a["node_id"], "status": a["status"]} if a else {"id": r["asset_id"], "label": "?", "layer": "warehouse", "layer_label": "Warehouse"}
    out["check_label"] = oc.CHECK_LABEL.get(r["check_kind"], r["check_kind"])
    out["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
    out["tool_label"] = "Relay checks" if r["tool"] == "relay" else oc.TOOLS.get(r["tool"], r["tool"])
    out["route_label"] = ROUTES.get(r["route"] or "", "needs a person")
    imp = out["impact"]
    out["affects"] = " - ".join(x for x in [f"{len(imp.get('reports') or [])} report{'s' if len(imp.get('reports') or []) != 1 else ''}" if imp.get("reports") else "", f"{imp.get('schedules')} schedule{'s' if imp.get('schedules') != 1 else ''}" if imp.get("schedules") else "",
                                              f"{imp.get('people')} people" if imp.get("people") else ""] if x) or (f"{imp.get('downstream')} downstream" if imp.get("downstream") else "nothing downstream yet")
    out["age_s"] = round(time.time() - (r["first_seen"] or time.time()))
    out["work"] = [{**w, "body": _j(w["body"], {})} for w in db.q("SELECT * FROM observe_work WHERE incident_id = ? ORDER BY created DESC", (r["id"],))]
    return out


def incidents(status: str = "open", layer: str | None = None, check: str | None = None, limit: int = 200) -> list[dict]:
    sts = {"open": ("open", "proposed", "actioned"), "all": ("open", "proposed", "actioned", "expected", "resolved", "dismissed"), "resolved": ("resolved",), "expected": ("expected",)}.get(status, (status,))
    rows = db.q(f"SELECT i.*, a.layer AS asset_layer FROM observe_incidents i LEFT JOIN observe_assets a ON a.id = i.asset_id WHERE i.status IN ({','.join('?' * len(sts))}) ORDER BY i.last_seen DESC LIMIT ?", (*sts, min(limit, 1000)))
    out = []
    for r in rows:
        if layer and layer != "consumers" and r["asset_layer"] != layer:
            continue
        if check and r["check_kind"] != check:
            continue
        p = _public_incident(r)
        if layer == "consumers" and not (p["impact"].get("schedules") or p["impact"].get("answers") or p["impact"].get("people")):
            continue
        out.append(p)
    out.sort(key=lambda i: (0 if i["status"] in ("open", "proposed", "actioned") else 1, SEV_ORDER.get(i["severity"], 2), -i["last_seen"]))
    return out


def detail(iid: str) -> dict:
    inc = _incident(iid)
    a = _asset(inc["asset_id"])
    inc["impact"] = impact_of(a)                                        # fresh: who relies on it right now
    inc["proposals"] = {r: proposal(inc, r) for r in ROUTES}
    inc["checkpoint"] = checkpoints.get(inc["checkpoint_id"]) if inc.get("checkpoint_id") else None
    inc["checks"] = [{**c, "config": _j(c["config"], {})} for c in db.q("SELECT * FROM observe_checks WHERE asset_id = ?", (a["id"],))]
    inc["history"] = [{"ts": t, **v} for t, v in history(a["id"], "volume", time.time() + 1, 42)][-14:] if inc["check_kind"] == "volume" else []
    inc["warnings"] = db.q("SELECT * FROM observe_warnings WHERE incident_id = ? AND cleared IS NULL", (iid,))
    return inc


def _priority(inc: dict) -> str:
    return {"high": "P1", "medium": "P2"}.get(inc["severity"], "P3")


def _ticket_target() -> dict | None:
    """The Service desk source new tickets go to (P12: the first that may raise tickets), or None."""
    try:
        from . import itsm
        s = itsm.ticket_target()
    except Exception:  # noqa: BLE001
        return None
    return {"source": s["id"], "name": s["name"]} if s else None


def _ticket_payload(inc: dict, p: dict) -> dict:
    """The ticket an approved "Raise a ticket" becomes: the summary, the cause, what it affects and the measurements."""
    rows = _j(inc.get("rows"), []) if isinstance(inc.get("rows"), str) else (inc.get("rows") or [])
    lines = [p.get("cause") or inc.get("cause") or "", ("Affects: " + ", ".join(p.get("reports")[:8])) if p.get("reports") else "",
             "\n".join(" - ".join(str(x) for x in r) for r in rows[:6]), f"Found by Relay's Data observability ({oc.CHECK_LABEL.get(inc.get('check_kind'), inc.get('check_kind') or 'check')})."]
    return {"title": p.get("summary") or inc.get("title") or "Data incident", "description": "\n\n".join(x for x in lines if x), "priority": p.get("priority") or "P3",
            "labels": ["data-observability", str(inc.get("check_kind") or "incident")]}


def _ticket_written(wr: dict, event: str) -> None:
    """P12's hook: the ticket this incident asked for was written (or not) - record it on the work row."""
    wid = str(wr.get("origin") or "").split(":", 1)[-1]
    w = db.one("SELECT * FROM observe_work WHERE id = ?", (wid,))
    if not w:
        return
    body = _j(w["body"], {})
    res = wr.get("result") or {}
    if event == "written":
        body["ticket"] = {"key": res.get("key"), "url": res.get("url"), "source": wr.get("source"), "approved_by": wr.get("decided_by_name")}
        db.run("UPDATE observe_work SET status = 'raised', body = ?, note = ? WHERE id = ?", (json.dumps(body, default=str), f"Ticket {res.get('key')} raised on {wr.get('source')}", wid))
        db.audit("observe.ticket.raised", w["incident_id"], {"work": wid, "key": res.get("key"), "source": wr.get("source_id")}, None)
    else:                                                     # not written: the draft is back in the Service desk's list
        body["ticket_request"] = {**(body.get("ticket_request") or {}), "status": event, "error": wr.get("error")}
        db.run("UPDATE observe_work SET body = ?, note = ? WHERE id = ?", (json.dumps(body, default=str), f"Ticket not raised: {wr.get('status_label', event).lower()}", wid))


def _matching_groups(inc: dict) -> list[dict]:
    """Open service-desk groups (P12) whose tickets talk about this asset - the ticket action joins one of them."""
    try:
        from . import itsm
    except Exception:  # noqa: BLE001
        return []
    short = (inc["asset"]["name"] or "").split(".")[-1].lower()
    words = [w for w in (short, (inc["asset"]["label"] or "").lower().split(" (")[0]) if len(w) >= 4]
    if not words:
        return []
    out = []
    for g in itsm.groups():
        if g["status"] in ("closed", "written"):
            continue
        hay = " ".join(str(g.get(k) or "") for k in ("title", "about", "summary")).lower()
        if any(w in hay for w in words):
            out.append({"id": g["id"], "title": g["title"], "tickets": g["tickets"], "priority": g["priority"], "status": g["status"]})
    return out[:5]


def proposal(inc: dict, route: str) -> dict:
    if route not in ROUTES:
        raise HTTPException(400, "The action is warn, ticket, heal or sdlc.")
    imp, pr = inc["impact"], _priority(inc)
    since = _when(inc["first_seen"])
    names = ", ".join(imp.get("people_names") or [])
    p = {"route": route, "label": ROUTES[route], "target": ROUTE_TARGET[route], "priority": pr, "summary": f"{inc['asset']['label']}: {inc['title']}", "cause": inc.get("cause"), "incident": inc["id"],
         "projects": imp.get("projects") or [], "reports": imp.get("reports") or []}
    if route == "warn":
        p["banner"] = f"Numbers under review since {since}: {inc['title']}"
        p["next"] = (f"A banner goes on {len(p['reports'])} affected dashboard{'s' if len(p['reports']) != 1 else ''} ({', '.join(p['reports'][:4])}) - \"{p['banner']}\" - and {imp.get('people') or 0} {'person is' if imp.get('people') == 1 else 'people are'} told"
                     + (f" ({names})" if names else "") + ". Nothing changes in the data.") if p["reports"] else "No dashboard reads this yet: the owners are told, no banner."
    elif route == "ticket":
        groups = _matching_groups(inc)
        p["groups"] = groups
        target = None if groups else _ticket_target()          # consolidation: P12 can raise the ticket itself now
        if target:
            p["ticket"] = target
        p["next"] = f"A ticket draft goes to {ROUTE_TARGET['ticket']} with the summary, cause, evidence and priority {pr}." + (
            f" It joins the open group \"{groups[0]['title']}\" ({groups[0]['tickets']} ticket{'s' if groups[0]['tickets'] != 1 else ''}); the summary and priority reach Jira / Freshservice only through the Service desk's own approval." if groups
            else f" No open ticket mentions this yet, so a new one is raised on {target['name']} - exactly what is written waits for a named person's approval first." if target
            else " No open ticket mentions this yet and no service-desk source may raise tickets: the draft waits in the Service desk's ticket drafts until one may.")
    elif route == "heal":
        p["next"] = "Self-healing diagnoses the load with the logs and the lineage, prepares a configuration fix (re-run, restore the schedule, renew the credential), tests it on a copy and waits for your approval before anything changes."
    else:
        p["next"] = "A change request is opened: agents plan the fix (mapping, pipeline or model code), develop and test it on a branch and run UAT on synthetic data - your tech lead approves the plan and the release."
    return p


def act(iid: str, u: dict, route: str) -> dict:
    """Propose the action: opens the checkpoint (evidence = the incident, measurements, impact path); nothing is
    written until it is accepted in the Validation queue."""
    inc = detail(iid)
    if inc["status"] in ("resolved", "dismissed"):
        raise HTTPException(409, f"This incident is {inc['status']}.")
    p = proposal(inc, route)
    have = db.one("SELECT * FROM observe_work WHERE incident_id = ? AND kind = ? AND status = 'proposed'", (iid, route))
    if have:
        return {"checkpoint": checkpoints.get(have["checkpoint_id"]), "incident": _incident(iid), "proposal": p, "already": True}
    imp = inc["impact"]
    ev = {"summary": p["summary"], "items": [f"{inc['check_label']} - {inc['what'] or ''}", imp["text"], f"Likely cause: {inc.get('cause') or '-'}", f"Then: {p['next']}"],
          "counts": {"priority": p["priority"], "reports": len(imp.get("reports") or []), "schedules": imp.get("schedules") or 0, "people": imp.get("people") or 0},
          "columns": ["What", "Measured", "Expected"], "rows": inc["rows"], "proposal": p,
          "incident": {"id": iid, "check": inc["check_kind"], "label": inc["check_label"], "asset": inc["asset"]["label"], "severity": inc["severity"], "title": inc["title"], "tool": inc["tool"]},
          "impact": {**_compact_impact(imp), "path": {"nodes": [{k: n.get(k) for k in ("id", "kind", "label", "role", "hop")} for n in imp["path"]["nodes"][:40]], "edges": imp["path"]["edges"][:80]}}}
    c = checkpoints.open(KIND, iid, MODULE, f"{p['label']}: {inc['asset']['label']}", "table", ev, link=f"{ROUTE}?open={iid}", opened_by=u["id"], agent="Relay")
    wid = "w-" + _secrets.token_hex(5)
    db.run("INSERT INTO observe_work (id, incident_id, kind, title, body, priority, target, status, checkpoint_id, created) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)",
           (wid, iid, route, c["name"][:200], json.dumps({k: p.get(k) for k in ("summary", "cause", "priority", "next", "target", "projects", "reports", "banner", "groups")}, default=str), p["priority"], p["target"], c["id"], time.time()))
    db.run("UPDATE observe_incidents SET status = CASE WHEN status = 'open' THEN 'proposed' ELSE status END, checkpoint_id = ?, route = ? WHERE id = ?", (c["id"], route, iid))
    db.audit("observe.action.proposed", iid, {"route": route, "asset": inc["asset"]["label"], "priority": p["priority"], "checkpoint": c["id"]}, u["id"])
    return {"checkpoint": c, "incident": _incident(iid), "proposal": p}


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    w = db.one("SELECT * FROM observe_work WHERE checkpoint_id = ?", (c["id"],))
    inc = db.one("SELECT * FROM observe_incidents WHERE id = ?", (c["subject"],))
    if not w or not inc:
        return
    now = time.time()
    p = (c.get("evidence") or {}).get("proposal") or {}
    if decision != "accept":
        db.run("UPDATE observe_work SET status = 'sent_back', note = ?, decided = ? WHERE id = ?", ((comment or "")[:500], now, w["id"]))
        still = db.one("SELECT 1 FROM observe_work WHERE incident_id = ? AND status = 'proposed'", (inc["id"],))
        db.run("UPDATE observe_incidents SET status = CASE WHEN status = 'proposed' AND ? IS NULL THEN 'open' ELSE status END, note = ?, checkpoint_id = NULL WHERE id = ?", (1 if still else None, (comment or "")[:500], inc["id"]))
        db.audit("observe.action.sent_back", inc["id"], {"route": w["kind"], "comment": (comment or "")[:200]}, who)
        return
    db.run("UPDATE observe_work SET status = 'approved', approved_by = ?, decided = ?, note = ? WHERE id = ?", (who, now, (comment or "")[:500] or None, w["id"]))
    db.run("UPDATE observe_incidents SET status = CASE WHEN status IN ('open', 'proposed') THEN 'actioned' ELSE status END, checkpoint_id = NULL WHERE id = ?", (inc["id"],))
    detail_log = {"route": w["kind"], "work": w["id"], "comment": (comment or "")[:200]}
    if w["kind"] == "warn":
        n = 0
        for pid in p.get("projects") or []:
            if db.one("SELECT 1 FROM observe_warnings WHERE incident_id = ? AND project = ? AND cleared IS NULL", (inc["id"], pid)):
                continue
            db.run("INSERT INTO observe_warnings (id, incident_id, project, text, since, created_by, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   ("wn-" + _secrets.token_hex(4), inc["id"], pid, p.get("banner") or inc["title"], inc["first_seen"], who, now))
            n += 1
        people = set()
        for pid in p.get("projects") or []:
            pr = db.project(pid)
            if pr:
                people.add(pr["owner_id"])
                try:
                    people |= auth.visible_to(pr)
                except Exception:  # noqa: BLE001
                    pass
            for s in db.q("SELECT recipients, owner_id, target FROM schedules WHERE status = 'active'"):
                t = _j(s["target"], {})
                if (t.get("project") or (t.get("scope") or {}).get("project")) == pid:
                    people |= set(_j(s["recipients"], [])); people.add(s["owner_id"])
        link = f"#/p/{p['projects'][0]}" if p.get("projects") else f"{ROUTE}?open={inc['id']}"
        notify.add_many(sorted(people), "alert", f"Numbers under review: {', '.join((p.get('reports') or ['your dashboard'])[:3])}", p.get("banner") or inc["title"], link)
        detail_log.update(warnings=n, told=len(people))
    elif w["kind"] == "ticket":
        groups = p.get("groups") or []
        handed, raising = None, None
        if groups:
            try:
                from . import itsm
                g = itsm._grp(groups[0]["id"])
                if not itsm.group_writable(g["id"], g["members"]):     # its sources are read-only: noted, and the draft stays for a source that may write
                    handed = {"group": g["id"], "checkpoint": None, "note": "the group's sources are read-only"}
                elif g["status"] in ("open", "sent_back") or not g.get("checkpoint_id"):
                    cp = itsm.open_checkpoint(g["id"], agent="Data observability", who=who)
                    handed = {"group": g["id"], "checkpoint": cp["id"]}
                else:
                    handed = {"group": g["id"], "checkpoint": g.get("checkpoint_id")}
            except Exception as e:  # noqa: BLE001 - the draft is kept even when the service desk is not reachable
                traceback.print_exc()
                handed = {"error": str(e)[:200]}
        else:                                                    # no group talks about it: raise a new ticket (its own approval of exactly what is written)
            target = _ticket_target() or p.get("ticket")
            if target:
                try:
                    from . import itsm
                    wr = itsm.request_write(target["source"], "create", _ticket_payload(inc, p), who=who, module=MODULE, origin=f"observe_work:{w['id']}",
                                            link=f"{ROUTE}?open={inc['id']}", name=f"Raise a ticket on {target['name']}: {p.get('summary') or inc['title']}"[:200])
                    raising = {"write": wr["id"], "checkpoint": wr["checkpoint_id"], "source": wr["source"], "status": wr["status"]}
                except Exception as e:  # noqa: BLE001 - refused (scope, settings) or unreachable: the draft waits in the Service desk's list
                    raising = {"error": str(e)[:200]}
        body = _j(w["body"], {})
        body["handed"] = handed
        if raising:
            body["ticket_request"] = raising
        db.run("UPDATE observe_work SET body = ?, status = ? WHERE id = ?", (json.dumps(body, default=str), "handed" if handed and handed.get("checkpoint") else "approved", w["id"]))
        detail_log.update(handed=handed, ticket_request=raising)
    db.audit("observe.action.accepted", inc["id"], detail_log, who)


checkpoints.register_kind(KIND, "Data incident action", _on_decision)
try:                                                           # consolidation: P12 tells us when the ticket is written
    from . import itsm as _itsm
    _itsm.register_write_hook("observe_work", _ticket_written)
except Exception:  # noqa: BLE001 - without the Service desk the ticket drafts simply wait
    traceback.print_exc()


def mark_expected(iid: str, u: dict, comment: str) -> dict:
    """A person says this is normal: the observation joins the baseline and the asset's band widens to it (audited)."""
    inc = _incident(iid)
    if not (comment or "").strip():
        raise HTTPException(400, "Say why this is expected - it tunes the baseline.")
    now = time.time()
    a = _asset(inc["asset_id"])
    ck = {"freshness": "freshness", "volume": "volume", "schema": "schema", "distribution": "profile", "nulls": "profile", "duplicates": "profile", "reconcile": "profile", "lineage": "freshness", "quality": "profile"}[inc["check_kind"]]
    last = db.one("SELECT id FROM observe_observations WHERE asset_id = ? AND check_kind = ? ORDER BY ts DESC LIMIT 1", (a["id"], ck))
    if last:
        db.run("UPDATE observe_observations SET expected = 1 WHERE id = ?", (last["id"],))
    row = db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = ?", (a["id"], inc["check_kind"]))
    cfg = _j(row["config"], {}) if row else {}
    acc = list(cfg.get("accepted") or [])
    acc.append({**{k: v for k, v in inc["measured"].items() if isinstance(v, (int, float, str))}, "column": inc["column_name"] or None, "jump_pp": (inc["measured"].get("null_pct") or 0) - (inc["expected"].get("null_pct_median") or 0) if inc["check_kind"] == "nulls" else None, "when": now, "by": u["id"]})
    cfg["accepted"] = acc[-10:]
    if inc["check_kind"] == "schema":
        cfg = {k: v for k, v in cfg.items()}
    db.run("INSERT OR REPLACE INTO observe_checks (asset_id, check_kind, enabled, config, last_run, last_status, last_text, updated, updated_by) VALUES (?, ?, 1, ?, ?, 'ok', ?, ?, ?)",
           (a["id"], inc["check_kind"], json.dumps(cfg, default=str), now, "expected: " + comment.strip()[:160], now, u["id"]))
    checkpoints.withdraw(KIND, iid, who=u["id"])
    db.run("UPDATE observe_work SET status = 'withdrawn', decided = ? WHERE incident_id = ? AND status = 'proposed'", (now, iid))
    db.run("UPDATE observe_incidents SET status = 'expected', note = ?, resolved = ?, resolved_by = ?, resolved_how = 'rule or threshold tuned', checkpoint_id = NULL WHERE id = ?", (comment.strip()[:500], now, u["id"], iid))
    db.audit("observe.incident.expected", iid, {"check": inc["check_kind"], "asset": inc["asset"]["label"], "comment": comment[:200], "accepted": acc[-1]}, u["id"])
    _update_status({a["id"]}, now)
    return _incident(iid)


def resolve(iid: str, u: dict, comment: str | None, how: str = "owner fixed at source") -> dict:
    inc = _incident(iid)
    now = time.time()
    checkpoints.withdraw(KIND, iid, who=u["id"])
    db.run("UPDATE observe_work SET status = 'withdrawn', decided = ? WHERE incident_id = ? AND status = 'proposed'", (now, iid))
    db.run("UPDATE observe_incidents SET status = 'resolved', note = ?, resolved = ?, resolved_by = ?, resolved_how = ?, checkpoint_id = NULL WHERE id = ?", ((comment or "")[:500] or None, now, u["id"], how, iid))
    db.run("UPDATE observe_warnings SET cleared = ?, cleared_by = ? WHERE incident_id = ? AND cleared IS NULL", (now, u["id"], iid))
    db.audit("observe.incident.resolved", iid, {"check": inc["check_kind"], "asset": inc["asset"]["label"], "how": how, "comment": (comment or "")[:200]}, u["id"])
    _update_status({inc["asset_id"]}, now)
    return _incident(iid)


# ------------------------------------------------------------------ warnings on dashboards (after an accepted "warn")

def warnings_for(pid: str) -> list[dict]:
    out = []
    for w in db.q("SELECT w.*, i.title, i.check_kind, i.severity, i.status AS incident_status FROM observe_warnings w JOIN observe_incidents i ON i.id = w.incident_id WHERE w.project = ? AND w.cleared IS NULL ORDER BY w.created DESC", (pid,)):
        out.append({"id": w["id"], "incident_id": w["incident_id"], "text": w["text"], "since": w["since"], "title": w["title"], "check": w["check_kind"], "check_label": oc.CHECK_LABEL.get(w["check_kind"], w["check_kind"]),
                    "severity": w["severity"], "link": f"{ROUTE}?open={w['incident_id']}"})
    return out


# ------------------------------------------------------------------ imports from other tools

def _asset_for_import(it: dict, tool: str, now: float) -> dict:
    name, system = it["asset"], it.get("system") or ""
    short = name.split(".")[-1].lower()
    rows = db.q("SELECT * FROM observe_assets WHERE enabled = 1 AND (lower(name) = ? OR lower(name) LIKE ? OR lower(label) LIKE ?) ORDER BY CASE WHEN lower(name) = ? THEN 0 ELSE 1 END, length(name) LIMIT 5",
                (name.lower(), f"%.{short}", f"{short} (%", name.lower()))
    if not rows and it.get("kind") != "job":
        rows = [r for r in db.q("SELECT * FROM observe_assets WHERE enabled = 1 AND lower(name) = ?", (short,))]
    if rows:
        a = dict(rows[0]); a["config"] = _j(a["config"], {})
        return a
    kind = "job" if it.get("kind") == "job" else "table"
    nid = lineage.upsert_node(kind, system or oc.TOOLS.get(tool, tool), name, label=f"{name} ({oc.TOOLS.get(tool, tool)})", properties={"imported_from": tool}, source=f"observe:{tool}", now=now)
    sync_assets(now)
    a = asset_by_node(nid)
    return a


def import_results(tool: str, payload, who: str | None, source_id: str | None = None) -> dict:
    tool = (tool or "webhook").lower()
    if tool not in oc.TOOLS:
        raise HTTPException(400, "Tool must be one of: " + ", ".join(oc.TOOLS))
    now = time.time()
    known = [r["name"].split(".")[-1] for r in db.q("SELECT name FROM observe_assets WHERE enabled = 1 AND kind = 'table'")]
    items = oc.parse_results(tool, payload, known)
    new, seen_again = 0, 0
    for it in items:
        a = _asset_for_import(it, it["tool"] if it["tool"] in oc.TOOLS else tool, now)
        if not a:
            continue
        col = it.get("column") or ""
        have = db.one("SELECT * FROM observe_incidents WHERE asset_id = ? AND check_kind = ? AND column_name = ? AND tool = ? AND status IN ('open', 'proposed', 'actioned')", (a["id"], it["check"], col, it["tool"]))
        when = it.get("when") or now
        if have:
            db.run("UPDATE observe_incidents SET title = ?, measured = ?, expected = ?, last_seen = ?, external_id = COALESCE(?, external_id) WHERE id = ?", (it["title"], json.dumps(it["measured"], default=str), json.dumps(it["expected"], default=str), max(when, have["last_seen"]), it.get("external_id"), have["id"]))
            seen_again += 1
            continue
        imp = impact_of(a, now)
        sev = it["severity"] if it["severity"] in SEV_ORDER else "medium"
        if imp["reports"] and sev == "medium" and it["check"] in ("freshness", "volume", "duplicates", "lineage"):
            sev = "high"
        iid = "ob-" + _secrets.token_hex(4)
        rows = [[f"{it['check']} ({oc.TOOLS.get(it['tool'], it['tool'])})", "; ".join(f"{k} {v}" for k, v in it["measured"].items())[:120] or "failed", "; ".join(f"{k} {v}" for k, v in it["expected"].items())[:120] or "pass"]]
        db.run("INSERT INTO observe_incidents (id, check_kind, asset_id, column_name, severity, title, what, measured, expected, rows, cause, route, status, tool, external_id, impact, also, first_seen, last_seen) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, '[]', ?, ?)",
               (iid, it["check"], a["id"], col, sev, it["title"], f"reported by {oc.TOOLS.get(it['tool'], it['tool'])}", json.dumps(it["measured"], default=str), json.dumps(it["expected"], default=str), json.dumps(rows), None,
                SUGGEST.get(it["check"], "ticket"), it["tool"], it.get("external_id"), json.dumps(_compact_impact(imp), default=str), when, max(when, now)))
        new += 1
    _update_status({r["asset_id"] for r in db.q("SELECT asset_id FROM observe_incidents WHERE tool != 'relay'")}, now)
    if source_id:
        db.run("UPDATE observe_sources SET last_check = ?, status = 'ok', error = NULL, updated = ? WHERE id = ?", (now, now, source_id))
    db.audit("observe.import", tool, {"items": len(items), "new": new, "seen_again": seen_again, "source": source_id}, who or "webhook")
    return {"tool": tool, "items": len(items), "new": new, "seen_again": seen_again}


# ------------------------------------------------------------------ summary and the screen's data

def _layer_counts() -> list[dict]:
    assets = {r["layer"]: r["n"] for r in db.q("SELECT layer, COUNT(*) AS n FROM observe_assets WHERE enabled = 1 GROUP BY layer")}
    opens = db.q("SELECT i.severity, a.layer, i.impact FROM observe_incidents i LEFT JOIN observe_assets a ON a.id = i.asset_id WHERE i.status IN ('open', 'proposed', 'actioned')")
    per: dict[str, list] = collections.defaultdict(list)
    for r in opens:
        per[r["layer"] or "warehouse"].append(r["severity"])
        imp = _j(r["impact"], {})
        if imp.get("schedules") or imp.get("answers") or imp.get("people"):
            per["consumers"].append(r["severity"])
    now = time.time()
    consumers = db.one("SELECT COUNT(*) AS n FROM schedules WHERE status = 'active'")["n"] + db.one("SELECT COUNT(*) AS n FROM askd_threads WHERE updated >= ?", (now - 30 * 86400,))["n"] + db.one("SELECT COUNT(DISTINCT pid) AS n FROM jobs WHERE created >= ?", (now - 30 * 86400,))["n"]
    out = []
    for i, (k, label, sub) in enumerate(LAYERS):
        n = consumers if k == "consumers" else assets.get(k, 0)
        inc = per.get(k, [])
        out.append({"id": k, "n": i + 1, "label": label, "sub": sub, "assets": n, "open": len(inc), "high": sum(1 for s in inc if s == "high"),
                    "status": "bad" if "high" in inc else "warn" if inc else ("ok" if n else "mute")})
    return out


def summary() -> dict:
    now = time.time()
    ensure_sources()
    watched = db.one("SELECT COUNT(*) AS n FROM observe_assets WHERE enabled = 1")["n"]
    checked = db.q("SELECT status FROM observe_assets WHERE enabled = 1 AND status IN ('Healthy', 'Warning', 'Failing')")
    health = round(100.0 * sum(1 for r in checked if r["status"] == "Healthy") / len(checked), 1) if checked else None
    opens = db.q("SELECT severity, first_seen, tool FROM observe_incidents WHERE status IN ('open', 'proposed', 'actioned')")
    fixed = [r["resolved"] - r["first_seen"] for r in db.q("SELECT resolved, first_seen FROM observe_incidents WHERE status = 'resolved' AND resolved IS NOT NULL AND resolved >= ?", (now - 90 * 86400,))]
    recent = db.q("SELECT id, tool, first_seen, asset_id FROM observe_incidents WHERE first_seen >= ?", (now - 30 * 86400,))
    caught = None
    if recent:
        tickets = db.q("SELECT title, description, created FROM itsm_tickets WHERE created >= ?", (now - 60 * 86400,)) if "itsm_tickets" in db.tables() else []
        names = {r["id"]: (r["name"] or "").split(".")[-1].lower() for r in db.q("SELECT id, name FROM observe_assets")}
        before = 0
        for r in recent:
            short = names.get(r["asset_id"], "")
            earlier = any(short and len(short) >= 4 and short in f"{t['title']} {t['description']}".lower() and (t["created"] or 0) < r["first_seen"] for t in tickets)
            before += 1 if (r["tool"] == "relay" and not earlier) else 0
        caught = round(100.0 * before / len(recent), 1)
    by_check = {r["check_kind"]: r["n"] for r in db.q("SELECT check_kind, COUNT(*) AS n FROM observe_incidents WHERE first_seen >= ? GROUP BY check_kind", (now - 90 * 86400,))}
    fixed_by = {r["resolved_how"] or "owner fixed at source": r["n"] for r in db.q("SELECT resolved_how, COUNT(*) AS n FROM observe_incidents WHERE status IN ('resolved', 'expected') AND resolved >= ? GROUP BY resolved_how", (now - 90 * 86400,))}
    for w in db.q("SELECT kind, COUNT(*) AS n FROM observe_work WHERE status IN ('approved', 'handed') AND decided >= ? GROUP BY kind", (now - 90 * 86400,)):
        fixed_by[{"heal": "Self-healing (approved)", "sdlc": "AI SDLC change", "ticket": "Ticket raised", "warn": "Users warned"}.get(w["kind"], w["kind"])] = w["n"]
    days = []
    for d in range(6, -1, -1):
        t0 = (int(now // 86400) - d) * 86400
        rows = db.q("SELECT value FROM observe_observations WHERE check_kind = 'freshness' AND ts >= ? AND ts < ?", (t0, t0 + 86400))
        with_cadence = [_j(r["value"], {}) for r in rows]
        late = sum(1 for v in with_cadence if v.get("late"))
        days.append({"day": dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%a"), "pct": round(100.0 * (len(with_cadence) - late) / len(with_cadence), 1) if with_cadence else None, "n": len(with_cadence)})
    srcs = db.q("SELECT kind, status FROM observe_sources")
    return {"watched": watched, "readable": db.one("SELECT COUNT(*) AS n FROM observe_assets WHERE enabled = 1 AND reader != 'none'")["n"], "health_pct": health, "open": len(opens), "high": sum(1 for r in opens if r["severity"] == "high"),
            "oldest_h": round((now - min(r["first_seen"] for r in opens)) / 3600, 1) if opens else None, "caught_before_users_pct": caught, "time_to_fix_h": round(statistics.median(fixed) / 3600, 1) if fixed else None,
            "fixed": len(fixed), "layers": _layer_counts(), "by_check": [{"check": k, "label": oc.CHECK_LABEL.get(k, k), "n": v} for k, v in sorted(by_check.items(), key=lambda kv: -kv[1])],
            "fixed_by": [{"how": k, "n": v} for k, v in sorted(fixed_by.items(), key=lambda kv: -kv[1])], "on_time": days, "sources": len(srcs), "imports": sum(1 for s in srcs if s["kind"] == "import"),
            "last_check": max((float(x) for x in [db.meta("observe_synced", "0")] if x), default=None), "state": check_state(), "route": ROUTE,
            "hint": None if watched else "Nothing watched yet: publish a dashboard, add a connection or import another tool's results."}


def assets(layer: str | None = None, q: str = "", limit: int = 500) -> list[dict]:
    rows = db.q("SELECT * FROM observe_assets WHERE enabled = 1" + (" AND layer = ?" if layer else "") + " ORDER BY CASE status WHEN 'Failing' THEN 0 WHEN 'Warning' THEN 1 WHEN 'Not readable' THEN 3 ELSE 2 END, layer, name LIMIT ?", ((layer, limit) if layer else (limit,)))
    counts = {r["asset_id"]: r for r in db.q("SELECT asset_id, COUNT(*) AS checks, SUM(CASE WHEN last_status = 'incident' THEN 1 ELSE 0 END) AS failing FROM observe_checks WHERE enabled = 1 GROUP BY asset_id")}
    out = []
    for r in rows:
        if q and q.lower() not in f"{r['name']} {r['label']} {r['system']} {r['kind']}".lower():
            continue
        c = counts.get(r["id"]) or {"checks": 0, "failing": 0}
        out.append({**{k: r[k] for k in ("id", "node_id", "kind", "layer", "name", "label", "system", "reader", "status", "signal", "last_check")}, "layer_label": LAYER_LABEL.get(r["layer"], r["layer"]), "checks": c["checks"], "failing": c["failing"] or 0})
    return out


def asset_detail(aid: str) -> dict:
    a = _asset(aid)
    g = settings()
    checks = []
    for c in db.q("SELECT * FROM observe_checks WHERE asset_id = ? ORDER BY check_kind", (aid,)):
        over = _j(c["config"], {})
        checks.append({"check": c["check_kind"], "label": oc.CHECK_LABEL.get(c["check_kind"], c["check_kind"]), "enabled": bool(c["enabled"]), "override": {k: v for k, v in over.items() if k != "accepted"}, "accepted": over.get("accepted") or [],
                       "effective": oc.cfg_for(c["check_kind"], g.get(c["check_kind"]), over), "defaults": {**(oc.DEFAULTS.get(c["check_kind"]) or {}), **(g.get(c["check_kind"]) or {})}, "help": oc.THRESHOLD_HELP.get(c["check_kind"], {}),
                       "last_run": c["last_run"], "last_status": c["last_status"], "last_text": c["last_text"]})
    out = {**a, "layer_label": LAYER_LABEL.get(a["layer"], a["layer"]), "checks": checks, "incidents": [i for i in incidents("all", limit=400) if i["asset_id"] == aid][:20],
           "history": {"volume": [{"ts": t, **v} for t, v in history(aid, "volume", time.time() + 1, 42)][-21:], "freshness": [{"ts": t, **v} for t, v in history(aid, "freshness", time.time() + 1, 42)][-10:]}}
    if a.get("node_id") and lineage.get(a["node_id"]):
        out["impact"] = _compact_impact(impact_of(a))
    return out


def set_asset_checks(aid: str, body: dict, u: dict) -> dict:
    a = _asset(aid)
    now = time.time()
    for check, spec in (body.get("checks") or {}).items():
        if check not in oc.CHECKS or not isinstance(spec, dict):
            continue
        row = db.one("SELECT config FROM observe_checks WHERE asset_id = ? AND check_kind = ?", (aid, check))
        cfg = _j(row["config"], {}) if row else {}
        over = {k: v for k, v in (spec.get("config") or {}).items() if k in (oc.DEFAULTS.get(check) or {})}
        cfg = {**{k: v for k, v in cfg.items() if k == "accepted"}, **over}
        if spec.get("forget_accepted"):
            cfg.pop("accepted", None)
        db.run("INSERT OR REPLACE INTO observe_checks (asset_id, check_kind, enabled, config, last_run, last_status, last_text, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (aid, check, 1 if spec.get("enabled", True) else 0, json.dumps(cfg, default=str), (row or {}).get("last_run") if row else None, None, None, now, u["id"]))
    db.audit("observe.thresholds", aid, {"asset": a["label"] or a["name"], "checks": {k: {kk: vv for kk, vv in (v.get("config") or {}).items()} for k, v in (body.get("checks") or {}).items() if k in oc.CHECKS}}, u["id"])
    return asset_detail(aid)


# ------------------------------------------------------------------ the sample estate (tests and the e2e flow; D2D_TEST_HOOKS=1)

def seed_sample(who: str | None = None, pid: str = "data-health-sample") -> dict:
    """A small synthetic estate: a dashboard with one upload table (6 weeks of daily history with a weekday
    pattern), a schedule and shares on it, then a planted stale load and a volume drop - detected by the checks."""
    import csv
    import random
    now = time.time()
    d = store.ROOT / pid
    (d / "data").mkdir(parents=True, exist_ok=True); (d / "versions" / "v1").mkdir(parents=True, exist_ok=True)
    rng = random.Random(14)
    rows = [["id", "sale_date", "amount", "channel"]]
    for i in range(600):
        rows.append([i + 1, (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=rng.randint(0, 60))).strftime("%Y-%m-%d"), round(rng.uniform(10, 400), 2), rng.choice(["web", "store", "store"])])
    with (d / "data" / "sales.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    (d / "versions" / "v1" / "definition.yaml").write_text("name: Sales health sample\ntables:\n- name: Sales\n  csv: sales.csv\n  columns:\n  - {name: Id, source: id, type: int}\n  - {name: Date, source: sale_date, type: date}\n  - {name: Amount, source: amount, type: number}\n  - {name: Channel, source: channel, type: string}\nmeasures:\n- name: Net Sales\n  expression: SUM ( Sales[Amount] )\npages:\n- name: Overview\n  rows:\n  - visuals:\n    - {id: k1, type: kpiCard, fields: {value: '[Net Sales]'}}\n", encoding="utf-8")
    (d / "project.json").write_text(json.dumps({"id": pid, "name": "Sales health sample", "prompt": "sample estate for data health", "status": "done", "created": now - 7 * 86400, "updated": now - 3600,
                                                "files": [{"name": "sales.csv", "bytes": (d / "data" / "sales.csv").stat().st_size}], "images": [], "plan_rounds": 0,
                                                "versions": [{"v": 1, "pages": ["Overview"], "visuals": 1}], "runs": [], "job": None, "error": None, "approved": 1, "output": {"pbip": "Sales health sample.pbip", "pages": 1, "visuals": 1, "measures": 1},
                                                "extract_schedule": {"daily": True, "hour_utc": 5}}), encoding="utf-8")
    db.add_project(pid, who or db.ADMIN_ID)
    if not db.one("SELECT 1 FROM schedules WHERE target LIKE ?", (f'%"{pid}"%',)):
        db.run("INSERT INTO schedules (id, owner_id, kind, name, target, cadence, tz, recipients, status, next_run, state, created, updated) VALUES (?, ?, 'report', 'Sales health sample - Monday 08:00', ?, ?, 'UTC', ?, 'active', ?, '{}', ?, ?)",
               ("s-" + _secrets.token_hex(3), who or db.ADMIN_ID, json.dumps({"type": "dashboard", "project": pid}), json.dumps({"kind": "weekly", "weekday": 0, "hour": 8}), json.dumps([who or db.ADMIN_ID]), now + 86400, now, now))
    for u in db.q("SELECT id FROM users WHERE active = 1 AND id != ?", (who or db.ADMIN_ID,))[:3]:
        db.run("INSERT OR IGNORE INTO shares (project_id, principal_type, principal_id, permission, created, created_by) VALUES (?, 'user', ?, 'view', ?, ?)", (pid, u["id"], now, who))
    lineage.sync_all(who)
    sync_assets(now, who)
    a = asset_by_node(lineage.node_id("table", pid, "sales.csv"))
    model = asset_by_node(lineage.node_id("table", f"model:{pid}", "Sales"))
    for aa in (a, model):
        if not aa:
            continue
        db.run("DELETE FROM observe_observations WHERE asset_id = ?", (aa["id"],))
        for day in range(42, 0, -1):
            t = now - day * 86400
            wd = oc.weekday(t)
            n = (120 if wd < 5 else 40) + rng.randint(-6, 6)
            record(aa["id"], "volume", t, {"rows": n})
            record(aa["id"], "freshness", t, {"loaded_at": t - 600})
            record(aa["id"], "schema", t, {"columns": [{"name": "id", "kind": "int"}, {"name": "sale_date", "kind": "date"}, {"name": "amount", "kind": "decimal"}, {"name": "channel", "kind": "string"}]})
            record(aa["id"], "profile", t, {"columns": {"amount": {"kind": "decimal", "mean": 205 + rng.uniform(-4, 4), "sd": 110, "min": 10, "max": 400, "sum": 24600, "nulls": 0, "null_pct": 0.0}, "channel": {"kind": "string", "top": [["store", 80], ["web", 40]], "distinct": 2, "nulls": 0, "null_pct": 0.0}}})
    # planted: the load is three days old (cadence daily), and today's file holds a fraction of the usual rows - few enough
    # to be a drop against the weekend baseline too (about 40 rows), not only the weekday one (about 120)
    with (d / "data" / "sales.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows[:7])
    old = now - 3 * 86400
    os.utime(d / "data" / "sales.csv", (old, old))
    r = run_checks(None, None, now, who or "sample")
    db.audit("observe.sample", pid, r, who or "system")
    return {"project": pid, **r, "incidents": [i["id"] for i in incidents("open")]}


# ------------------------------------------------------------------ API

def _u() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in.")
    ensure_scheduler()
    return u


def _builder() -> dict:
    u = _u()
    if not auth.is_dev(u):
        raise HTTPException(403, "Only a BI Dev / Analyst or an Admin can do that.")
    return u


class SourceIn(BaseModel):
    kind: str | None = None
    name: str | None = None
    config: dict | None = None
    token: str | None = None
    every_min: int | None = None


class ActIn(BaseModel):
    route: str


class Comment(BaseModel):
    comment: str | None = None


class ChecksIn(BaseModel):
    checks: dict


class SettingsIn(BaseModel):
    settings: dict


class ImportIn(BaseModel):
    tool: str
    payload: dict | list
    source: str | None = None


@router.get("/api/observe/summary")
def api_summary():
    _u()
    return summary()


@router.get("/api/observe/overview")
def api_overview(status: str = "open", layer: str | None = None, check: str | None = None):
    u = _u()
    ensure_sources(u["id"])
    if db.meta("observe_synced") is None:
        sync_assets(who=u["id"])
    return {"summary": summary(), "incidents": incidents(status, layer, check), "recent": incidents("resolved", limit=20)[:8], "assets": assets(), "sources": [public_source(s) for s in db.q("SELECT * FROM observe_sources ORDER BY created")],
            "settings": settings(), "help": oc.THRESHOLD_HELP, "labels": oc.CHECK_LABEL, "layers": LAYERS, "routes": ROUTES, "tools": oc.TOOLS, "status_labels": STATUS_LABEL, "state": check_state(),
            "can_edit": auth.is_dev(u), "test_hooks": TEST_HOOKS}


@router.post("/api/observe/sync")
def api_sync():
    u = _builder()
    return sync_assets(who=u["id"])


@router.post("/api/observe/check")
def api_check_all():
    u = _builder()
    sync_assets(who=u["id"])
    return request_check(None, None, u["id"])


@router.get("/api/observe/incidents")
def api_incidents(status: str = "open", layer: str | None = None, check: str | None = None):
    _u()
    return {"items": incidents(status, layer, check)}


@router.get("/api/observe/incidents/{iid}")
def api_incident(iid: str):
    _u()
    return detail(iid)


@router.post("/api/observe/incidents/{iid}/act")
def api_act(iid: str, body: ActIn):
    return act(iid, _builder(), body.route)


@router.post("/api/observe/incidents/{iid}/expected")
def api_expected(iid: str, body: Comment):
    return mark_expected(iid, _builder(), body.comment or "")


@router.post("/api/observe/incidents/{iid}/resolve")
def api_resolve(iid: str, body: Comment | None = None):
    return resolve(iid, _builder(), body.comment if body else None)


@router.get("/api/observe/assets")
def api_assets(layer: str | None = None, q: str = ""):
    _u()
    return {"items": assets(layer, q)}


@router.get("/api/observe/assets/{aid}")
def api_asset(aid: str):
    _u()
    return asset_detail(aid)


@router.put("/api/observe/assets/{aid}/checks")
def api_asset_checks(aid: str, body: ChecksIn):
    return set_asset_checks(aid, body.model_dump(), _builder())


@router.post("/api/observe/assets/{aid}/check")
def api_asset_check(aid: str):
    u = _builder()
    _asset(aid)
    return request_check([aid], None, u["id"])


@router.get("/api/observe/settings")
def api_settings():
    _u()
    return {"settings": settings(), "defaults": oc.DEFAULTS, "help": oc.THRESHOLD_HELP, "labels": oc.CHECK_LABEL}


@router.put("/api/observe/settings")
def api_set_settings(body: SettingsIn):
    u = _builder()
    return {"settings": save_settings(body.settings, u["id"]), "defaults": oc.DEFAULTS, "help": oc.THRESHOLD_HELP, "labels": oc.CHECK_LABEL}


@router.get("/api/observe/sources")
def api_sources():
    _u(); ensure_sources()
    return {"items": [public_source(s) for s in db.q("SELECT * FROM observe_sources ORDER BY created")], "state": check_state(), "tools": oc.TOOLS}


@router.post("/api/observe/sources")
def api_add_source(body: SourceIn):
    return save_source(body.model_dump(), _builder())


@router.put("/api/observe/sources/{sid}")
def api_edit_source(sid: str, body: SourceIn):
    return save_source(body.model_dump(), _builder(), sid)


@router.delete("/api/observe/sources/{sid}")
def api_remove_source(sid: str):
    remove_source(sid, _builder())
    return {"ok": True}


@router.post("/api/observe/sources/{sid}/check")
def api_source_check(sid: str):
    u = _builder()
    s = _source(sid)
    if s["status"] == "paused":
        raise HTTPException(409, "This source is paused. Resume it first.")
    if s["kind"] == "import":
        raise HTTPException(400, "An import source receives results; it has nothing to check itself.")
    return request_check(None, sid, u["id"])


@router.post("/api/observe/sources/{sid}/pause")
def api_source_pause(sid: str):
    u = _builder(); _source(sid)
    db.run("UPDATE observe_sources SET status = 'paused', updated = ? WHERE id = ?", (time.time(), sid))
    db.audit("observe.source.pause", sid, None, u["id"])
    return public_source(_source(sid))


@router.post("/api/observe/sources/{sid}/resume")
def api_source_resume(sid: str):
    u = _builder(); _source(sid)
    db.run("UPDATE observe_sources SET status = 'new', next_check = ?, updated = ? WHERE id = ?", (time.time(), time.time(), sid))
    db.audit("observe.source.resume", sid, None, u["id"])
    return public_source(_source(sid))


@router.post("/api/observe/import")
def api_import(body: ImportIn):
    u = _builder()
    return import_results(body.tool, body.payload, u["id"], body.source)


@router.post("/auth/observe/hook/{sid}")
async def api_hook(sid: str, request: Request):
    """The webhook other tools post to: the source's token by name (never shown back), the payload parsed by the
    source's tool. Reachable without a session (like the connector callbacks), guarded by the token."""
    s = db.one("SELECT * FROM observe_sources WHERE id = ? AND kind = 'import'", (sid,))
    if not s:
        raise HTTPException(404, "No such import source.")
    want = secrets_store.get("org", f"observe:{sid}:token")
    got = request.headers.get("x-relay-token") or (request.headers.get("authorization") or "").replace("Bearer ", "").strip() or request.query_params.get("token", "")
    if not want or not got or not _secrets.compare_digest(want, got):
        db.audit("observe.hook.refused", sid, None, "webhook")
        raise HTTPException(401, "The token does not match this import source.")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "The body must be JSON.")
    tool = (_j(s["config"], {}).get("tool") or "webhook")
    if isinstance(payload, dict) and str(payload.get("tool") or "").lower() in oc.TOOLS and tool == "webhook":
        tool = str(payload["tool"]).lower()
    return import_results(tool, payload, "webhook", sid)


@router.get("/api/observe/warnings")
def api_warnings(pid: str):
    u = _u()
    if not auth.can_project(u, "view", db.project(pid)):
        raise HTTPException(404, "Project not found")
    return {"items": warnings_for(pid)}


@router.post("/api/observe/warnings/{wid}/clear")
def api_clear_warning(wid: str):
    u = _builder()
    w = db.one("SELECT * FROM observe_warnings WHERE id = ?", (wid,))
    if not w:
        raise HTTPException(404, "No such warning.")
    db.run("UPDATE observe_warnings SET cleared = ?, cleared_by = ? WHERE id = ?", (time.time(), u["id"], wid))
    db.audit("observe.warning.cleared", wid, {"incident": w["incident_id"], "project": w["project"]}, u["id"])
    return {"ok": True}


@router.get("/api/observe/work")
def api_work(status: str | None = None):
    _u()
    rows = db.q("SELECT w.*, i.title AS incident_title, i.check_kind FROM observe_work w JOIN observe_incidents i ON i.id = w.incident_id" + (" WHERE w.status = ?" if status else "") + " ORDER BY w.created DESC", (status,) if status else ())
    return {"items": [{**w, "body": _j(w["body"], {})} for w in rows]}


@router.post("/api/observe/test/seed")
def api_test_seed():
    """Tests only (D2D_TEST_HOOKS=1): the sample estate with its planted incidents."""
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u = _builder()
    return seed_sample(u["id"])
