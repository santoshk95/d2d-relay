"""Integration analytics (build-plan v2, P13): understand every integration running across all systems and act
before it breaks.

Discover (read-only): one source per platform (Oracle Integration Cloud, SSIS catalog, Azure Data Factory, Airflow,
SAP CPI / PI-PO, MuleSoft, Boomi, Logic Apps, AWS Glue, n8n, Power Automate, UiPath / Blue Prism / Automation
Anywhere, API gateways, SFTP and mail drops, system logs — and the Sample estate), each read by its adapter in
app/intan_adapters/ as the registered job kind `intan_scan` (not an LLM run), on request and on a schedule. What
it finds goes into the lineage & asset graph (nodes + edges) and a runs history here.

Watch: health rules with learned baselines — failing, slow (duration ×3 vs the baseline), slowing (×2), unstable
(retries), volume drop (−15 % or more), credentials expiring or expired, message-pack / licence usage, announced
schema changes, screen changes for bots, dependencies, and integrations nobody owns (owners from the RACI table
when the tool does not expose one). Every risk carries its reason and evidence rows.

Act, with approval: each risk proposes one action (a ticket with summary, cause, evidence and priority; a
configuration fix through Self-healing; a code fix through AI SDLC; an owner to assign). Proposing opens a checkpoint
(kind intan.action, view table) in the Validation queue; nothing is written until a person accepts it, and then a
work item is recorded here for Service desk (P12) and Self-healing / AI SDLC (P16) to carry out.
"""
from __future__ import annotations

import asyncio
import collections
import datetime as dt
import hashlib
import json
import math
import re
import secrets as _secrets
import statistics
import time
import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import auth, checkpoints, db, lineage, secrets_store, store, worker
from . import intan_adapters as adapters
from .intan_adapters import base as abase

router = APIRouter()
SUBJECT = "integration-analytics"                 # the worker's subject folder (project.json, kind "intan")
MODULE = "Integration analytics"

db.register_schema("""
CREATE TABLE IF NOT EXISTS intan_sources (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}', owner_id TEXT,
  status TEXT NOT NULL DEFAULT 'new', error TEXT, every_min INTEGER NOT NULL DEFAULT 60, last_scan REAL, next_scan REAL,
  found INTEGER NOT NULL DEFAULT 0, seconds REAL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS intan_integrations (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, ext_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, via TEXT,
  from_system TEXT, to_system TEXT, schedule TEXT, owner TEXT, owner_from TEXT, node_id TEXT, properties TEXT NOT NULL DEFAULT '{}',
  health TEXT NOT NULL DEFAULT 'Unknown', signal TEXT, last_run REAL, last_status TEXT, success_30 REAL, usual_s REAL,
  first_seen REAL NOT NULL, last_seen REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS intan_integrations_key ON intan_integrations (source_id, ext_id);
CREATE TABLE IF NOT EXISTS intan_runs (
  integration_id TEXT NOT NULL, ext_id TEXT NOT NULL, started REAL NOT NULL, ended REAL, status TEXT NOT NULL,
  duration_s REAL, volume REAL, error TEXT, PRIMARY KEY (integration_id, ext_id));
CREATE INDEX IF NOT EXISTS intan_runs_time ON intan_runs (integration_id, started);
CREATE TABLE IF NOT EXISTS intan_credentials (
  source_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT, integration_id TEXT, expires REAL, status TEXT, seen REAL NOT NULL,
  PRIMARY KEY (source_id, name));
CREATE TABLE IF NOT EXISTS intan_signals (
  source_id TEXT NOT NULL, kind TEXT NOT NULL, integration_id TEXT, text TEXT NOT NULL, value REAL, limit_value REAL, due REAL,
  seen REAL NOT NULL, PRIMARY KEY (source_id, kind, text));
CREATE TABLE IF NOT EXISTS intan_owners (
  id TEXT PRIMARY KEY, pattern TEXT NOT NULL, owner TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'A', updated REAL NOT NULL, updated_by TEXT);
CREATE TABLE IF NOT EXISTS intan_risks (
  id TEXT PRIMARY KEY, integration_id TEXT NOT NULL, kind TEXT NOT NULL, health TEXT NOT NULL, reason TEXT NOT NULL, cause TEXT,
  evidence TEXT NOT NULL DEFAULT '[]', route TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', checkpoint_id TEXT, note TEXT,
  created REAL NOT NULL, updated REAL NOT NULL, resolved REAL);
CREATE UNIQUE INDEX IF NOT EXISTS intan_risks_key ON intan_risks (integration_id, kind);
CREATE TABLE IF NOT EXISTS intan_work (
  id TEXT PRIMARY KEY, risk_id TEXT NOT NULL, integration_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
  priority TEXT, target TEXT, status TEXT NOT NULL DEFAULT 'drafted', checkpoint_id TEXT, approved_by TEXT, created REAL NOT NULL);
""")

# Health rules (tunable): learned baselines come from each integration's own runs.
RULES = {"slow_factor": 3.0, "slowing_factor": 2.0, "volume_drop": 0.15, "credential_days": 14, "failures_week": 3, "usage_pct": 85, "baseline_min": 3, "window_days": 42}
HEALTH_ORDER = ["Failing", "Degraded", "At risk", "No owner", "Healthy", "Unknown"]
RISK_HEALTH = {"failing": "Failing", "screen_change": "Failing", "credential_expired": "Failing", "dependency": "Failing", "slow": "Degraded", "unstable": "Degraded",
               "slowing": "At risk", "volume_drop": "At risk", "credential_expiring": "At risk", "usage": "At risk", "schema_change": "At risk", "no_owner": "No owner"}
RISK_LABEL = {"failing": "Failing", "screen_change": "Screen changed", "credential_expired": "Credential expired", "dependency": "Waits on a failing step", "slow": "Much slower than usual",
              "unstable": "Retries this week", "slowing": "Slower than usual", "volume_drop": "Volume dropped", "credential_expiring": "Credential expiring", "usage": "Usage near the limit",
              "schema_change": "Schema change announced", "no_owner": "No owner"}
CODE_KINDS = {"Bot", "Pipeline", "Flow", "Package", "Integration", "Job", "Webhook", "Connector"}
KIND_NODE = {"Bot": "bot", "Flow": "flow", "Webhook": "flow", "Integration": "flow", "Pipeline": "job", "Package": "job", "Connector": "job", "Refresh": "job", "Job": "job",
             "API": "api", "API pull": "api", "API push": "api", "File": "file_drop"}
ROUTE_LABEL = {"ticket": "Raise a ticket", "heal": "Fix with Self-healing", "sdlc": "Fix with AI SDLC", "owner": "Assign an owner"}
ROUTE_TARGET = {"ticket": "Service desk (Jira / Freshservice)", "heal": "Self-healing", "sdlc": "AI SDLC", "owner": "Owner assignment"}
SCREEN_RE = re.compile(r"selector|screen|element not found|ui element|not found: '|application screen|clicks the wrong", re.I)
CRED_RE = re.compile(r"\b401\b|unauthori[sz]ed|token expired|credential|sign-in|oauth|expired", re.I)
_sched_task = None


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _iid(source_id: str, ext_id: str) -> str:
    return "i-" + hashlib.sha1(f"{source_id}|{ext_id}".encode()).hexdigest()[:12]


# ------------------------------------------------------------------ the worker's subject and the scheduler

def _subject() -> str:
    d = store.ROOT / SUBJECT
    if not (d / "project.json").exists():
        d.mkdir(parents=True, exist_ok=True)
        (d / "data").mkdir(exist_ok=True)
        store.save({"id": SUBJECT, "name": MODULE, "kind": "intan", "prompt": "Discovery scans of the integration sources — not a dashboard.", "status": "idle",
                    "created": time.time(), "versions": [], "runs": [], "job": None, "error": None})
    return SUBJECT


def scan_state() -> dict:
    if not (store.ROOT / SUBJECT / "project.json").exists():        # the subject folder appears with the first scan
        return {"status": "idle"}
    try:
        st = store.load(SUBJECT)
    except (KeyError, FileNotFoundError, ValueError):
        return {"status": "idle"}
    return {"status": st.get("status"), "error": st.get("error"), "updated": st.get("updated"), "job": (st.get("job") or {}).get("kind")}


def due(now: float | None = None) -> list[dict]:
    now = now or time.time()
    return db.q("SELECT * FROM intan_sources WHERE status != 'paused' AND (next_scan IS NULL OR next_scan <= ?) ORDER BY next_scan", (now,))


def request_scan(ids: list[str] | None = None, who: str | None = None) -> dict:
    now = time.time()
    if ids:
        for sid in ids:
            db.run("UPDATE intan_sources SET next_scan = ? WHERE id = ?", (now, sid))
    pid = _subject()
    st = store.load(pid)
    if st.get("status") in ("queued", "scanning") and (st.get("job") or {}).get("kind") == "intan_scan":
        return {"queued": True, "already": True}
    worker.enqueue(pid, "intan_scan", sources=list(ids or []))
    db.audit("intan.scan.requested", ",".join(ids or []) or "all", None, who or "system")
    return {"queued": True}


async def _scan_job(pid: str, args: dict) -> None:
    wanted = list(args.get("sources") or [])
    for _ in range(3):                                                 # what became due while scanning is picked up too
        ids = list(dict.fromkeys(wanted + [s["id"] for s in due()]))
        if not ids:
            break
        wanted = []
        for sid in ids:
            src = db.one("SELECT * FROM intan_sources WHERE id = ?", (sid,))
            if not src or src["status"] == "paused":
                continue
            worker.app_note(pid, "intan_scan", f"Scanning {src['name']} ({src['kind']})…")
            r = await asyncio.to_thread(scan_source, sid)
            worker.app_note(pid, "intan_scan", f"{src['name']}: {r.get('found', 0)} integrations, {r.get('runs', 0)} runs, {r.get('risks', 0)} risks" if r.get("ok") else f"{src['name']}: {r.get('error')}",
                            "info" if r.get("ok") else "warn")
    store.update(pid, status="idle", error=None)


worker.register_job("intan_scan", _scan_job, status="scanning", done="Integration scan done")


async def _scheduler() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            for _t in db.each_tenant("intan"):          # P17: every tenant with Integration analytics on
                if due() and scan_state().get("status") not in ("queued", "scanning"):
                    request_scan()
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


# ------------------------------------------------------------------ sources

def _source(sid: str) -> dict:
    s = db.one("SELECT * FROM intan_sources WHERE id = ?", (sid,))
    if not s:
        raise HTTPException(404, "No such source.")
    return s


def _secret_names(kind: str) -> list[str]:
    return [s["name"] for s in adapters.get(kind).SECRETS]


def public_source(s: dict) -> dict:
    out = {k: s[k] for k in ("id", "kind", "name", "owner_id", "status", "error", "every_min", "last_scan", "next_scan", "found", "seconds", "created", "updated")}
    out["config"] = _j(s["config"], {})
    out["label"] = adapters.get(s["kind"]).LABEL if s["kind"] in adapters.ADAPTERS else s["kind"]
    out["secrets"] = {n: secrets_store.get("org", f"intan:{s['id']}:{n}") is not None for n in _secret_names(s["kind"])} if s["kind"] in adapters.ADAPTERS else {}
    out["integrations"] = db.one("SELECT COUNT(*) AS n FROM intan_integrations WHERE source_id = ? AND active = 1", (s["id"],))["n"]
    # for the Connections hub (read-only there): who added it, and the screen that manages it — never a credential
    out["owner"] = (db.one("SELECT name FROM users WHERE id = ?", (s["owner_id"],)) or {}).get("name") if s.get("owner_id") else None
    out.update(module=MODULE, link="#/integrations", category="integration", scope="read")
    return out


def save_source(body: dict, u: dict, sid: str | None = None) -> dict:
    kind = body.get("kind") or (db.one("SELECT kind FROM intan_sources WHERE id = ?", (sid,)) or {}).get("kind")
    if kind not in adapters.ADAPTERS:
        raise HTTPException(400, f"Unknown source kind {kind!r}.")
    ad = adapters.get(kind)
    have = db.one("SELECT * FROM intan_sources WHERE id = ?", (sid,)) if sid else None
    if sid and not have:
        raise HTTPException(404, "No such source.")
    cfg = {**(_j(have["config"], {}) if have else {}), **{k: v for k, v in (body.get("config") or {}).items() if k in {c["name"] for c in ad.CONFIG}}}
    for c in ad.CONFIG:
        if c.get("required") and not str(cfg.get(c["name"]) or "").strip():
            raise HTTPException(400, f"{c['label']} is needed.")
    name = str(body.get("name") or (have or {}).get("name") or ad.LABEL).strip()[:120]
    every = int(body.get("every_min") or (have or {}).get("every_min") or 60)
    every = max(5, min(every, 24 * 60))
    now = time.time()
    sid = sid or "src-" + _secrets.token_hex(4)
    if have:
        db.run("UPDATE intan_sources SET kind = ?, name = ?, config = ?, every_min = ?, updated = ? WHERE id = ?", (kind, name, json.dumps(cfg), every, now, sid))
    else:
        db.run("INSERT INTO intan_sources (id, kind, name, config, owner_id, status, every_min, next_scan, created, updated) VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)",
               (sid, kind, name, json.dumps(cfg), u["id"], every, now, now, now))
    for n, v in (body.get("secrets") or {}).items():
        if n in _secret_names(kind) and v not in (None, ""):
            secrets_store.put("org", f"intan:{sid}:{n}", str(v), u["id"])
    if kind == "sample" and not have and not owners():                   # the sample estate brings its RACI rows
        from .intan_adapters import estate
        set_owners([{"pattern": p, "owner": o} for p, o in estate.RACI], u)
    db.audit("intan.source.save", sid, {"kind": kind, "name": name, "secrets": sorted(n for n, v in (body.get("secrets") or {}).items() if v)}, u["id"])
    return public_source(_source(sid))


def remove_source(sid: str, u: dict) -> None:
    s = _source(sid)
    for n in _secret_names(s["kind"]):
        secrets_store.delete("org", f"intan:{sid}:{n}", u["id"])
    ids = [r["id"] for r in db.q("SELECT id FROM intan_integrations WHERE source_id = ?", (sid,))]
    for iid in ids:
        for rk in db.q("SELECT id, checkpoint_id FROM intan_risks WHERE integration_id = ?", (iid,)):
            checkpoints.withdraw("intan.action", rk["id"], who=u["id"])
        db.run("DELETE FROM intan_risks WHERE integration_id = ?", (iid,))
        db.run("DELETE FROM intan_runs WHERE integration_id = ?", (iid,))
    for t in ("intan_integrations", "intan_credentials", "intan_signals"):
        db.run(f"DELETE FROM {t} WHERE source_id = ?", (sid,))
    db.run("DELETE FROM intan_sources WHERE id = ?", (sid,))
    lineage.prune(f"intan:{sid}", time.time() + 1)
    db.audit("intan.source.remove", sid, {"name": s["name"]}, u["id"])


# ------------------------------------------------------------------ owners (RACI)

def owners() -> list[dict]:
    return db.q("SELECT * FROM intan_owners ORDER BY pattern")


def set_owners(rows: list[dict], u: dict) -> list[dict]:
    db.run("DELETE FROM intan_owners")
    now = time.time()
    for r in rows:
        if str(r.get("pattern") or "").strip() and str(r.get("owner") or "").strip():
            db.run("INSERT INTO intan_owners (id, pattern, owner, role, updated, updated_by) VALUES (?, ?, ?, ?, ?, ?)",
                   ("o-" + _secrets.token_hex(3), str(r["pattern"]).strip()[:120], str(r["owner"]).strip()[:120], (r.get("role") or "A")[:1], now, u["id"]))
    db.audit("intan.owners.save", None, {"rows": len(rows)}, u["id"])
    return owners()


def _raci_owner(i: dict, table: list[dict]) -> str | None:
    hay = " | ".join(str(i.get(k) or "") for k in ("name", "from_system", "to_system", "via")).lower()
    for r in table:
        if r["pattern"].lower() in hay:
            return r["owner"]
    return None


# ------------------------------------------------------------------ scanning

def _ingest(src: dict, disc: dict, now: float) -> dict:
    sid = src["id"]
    seen, n_runs = set(), 0
    raci = owners()
    for i in disc.get("integrations") or []:
        if not i.get("ext_id") or not i.get("name"):
            continue
        iid = _iid(sid, str(i["ext_id"]))
        seen.add(iid)
        own, own_from = (i.get("owner") or None), "adapter" if i.get("owner") else None
        if not own:
            own = _raci_owner(i, raci)
            own_from = "raci" if own else None
        props = {**(i.get("properties") or {}), "depends_on": i.get("depends_on") or [], "writes": i.get("writes") or [], "reads": i.get("reads") or [], "feeds": i.get("feeds") or []}
        have = db.one("SELECT id, properties FROM intan_integrations WHERE id = ?", (iid,))
        if have:
            db.run("UPDATE intan_integrations SET name = ?, kind = ?, via = ?, from_system = ?, to_system = ?, schedule = ?, owner = ?, owner_from = ?, properties = ?, last_seen = ?, active = 1 WHERE id = ?",
                   (i["name"][:200], i.get("kind") or "Integration", i.get("via"), i.get("from_system"), i.get("to_system"), i.get("schedule"), own, own_from, json.dumps(props), now, iid))
        else:
            db.run("INSERT INTO intan_integrations (id, source_id, ext_id, name, kind, via, from_system, to_system, schedule, owner, owner_from, properties, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (iid, sid, str(i["ext_id"]), i["name"][:200], i.get("kind") or "Integration", i.get("via"), i.get("from_system"), i.get("to_system"), i.get("schedule"), own, own_from, json.dumps(props), now, now))
    for r in db.q("SELECT id FROM intan_integrations WHERE source_id = ? AND active = 1", (sid,)):
        if r["id"] not in seen:
            db.run("UPDATE intan_integrations SET active = 0 WHERE id = ?", (r["id"],))
    with db.transaction():
        for r in disc.get("runs") or []:
            if not r.get("integration") or r.get("started") is None:
                continue
            iid = _iid(sid, str(r["integration"]))
            if iid not in seen:
                continue
            n_runs += db.run("INSERT OR IGNORE INTO intan_runs (integration_id, ext_id, started, ended, status, duration_s, volume, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (iid, str(r.get("ext_id") or r["started"]), float(r["started"]), r.get("ended"), r.get("status") or "failed", r.get("duration_s"), r.get("volume"), (r.get("error") or None) and str(r["error"])[:500]))
        db.run("DELETE FROM intan_credentials WHERE source_id = ?", (sid,))
        for c in disc.get("credentials") or []:
            if c.get("name"):
                db.run("INSERT OR REPLACE INTO intan_credentials (source_id, name, kind, integration_id, expires, status, seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (sid, str(c["name"])[:200], c.get("kind"), _iid(sid, str(c["integration"])) if c.get("integration") else None, c.get("expires"), c.get("status"), now))
        db.run("DELETE FROM intan_signals WHERE source_id = ?", (sid,))
        for s in disc.get("signals") or []:
            if s.get("text"):
                db.run("INSERT OR REPLACE INTO intan_signals (source_id, kind, integration_id, text, value, limit_value, due, seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (sid, s.get("kind") or "signal", _iid(sid, str(s["integration"])) if s.get("integration") else None, str(s["text"])[:300], s.get("value"), s.get("limit"), s.get("due"), now))
    cutoff = now - 120 * 86400
    db.run("DELETE FROM intan_runs WHERE started < ? AND integration_id IN (SELECT id FROM intan_integrations WHERE source_id = ?)", (cutoff, sid))
    return {"found": len(seen), "runs": n_runs}


def _to_lineage(src: dict, now: float) -> None:
    tag = f"intan:{src['id']}"
    ad = adapters.get(src["kind"])
    rows = db.q("SELECT * FROM intan_integrations WHERE source_id = ? AND active = 1", (src["id"],))
    by_ext = {r["ext_id"]: r for r in rows}
    for r in rows:
        props = _j(r["properties"], {})
        via = r["via"] or ad.LABEL
        nid = lineage.upsert_node(KIND_NODE.get(r["kind"], "job"), via, r["name"], label=r["name"], source=tag, status=r["health"], owner=r["owner"], now=now,
                                  properties={"integration": r["id"], "kind": r["kind"], "schedule": r["schedule"], "signal": r["signal"], "from": r["from_system"], "to": r["to_system"], "link": f"#/integrations?open={r['id']}"})
        db.run("UPDATE intan_integrations SET node_id = ? WHERE id = ?", (nid, r["id"]))
        if r["from_system"]:
            lineage.upsert_edge(lineage.upsert_node("system", "", r["from_system"], source=tag, now=now), nid, "reads", {"integration": r["name"]}, tag, now)
        if r["to_system"]:
            lineage.upsert_edge(nid, lineage.upsert_node("system", "", r["to_system"], source=tag, now=now), "writes", {"integration": r["name"]}, tag, now)
        if r["via"] and r["via"] not in (r["from_system"], r["to_system"]):
            lineage.upsert_edge(lineage.upsert_node("system", "", r["via"], source=tag, now=now), nid, "schedules", {"schedule": r["schedule"]}, tag, now)
        if r["owner"]:
            lineage.upsert_edge(lineage.upsert_node("owner", "", r["owner"], source=tag, now=now), nid, "owns", {"from": r["owner_from"]}, tag, now)
        for w in props.get("writes") or []:
            lineage.upsert_edge(nid, lineage.source_table(w, now, tag), "writes", {}, tag, now)
        for w in props.get("reads") or []:
            lineage.upsert_edge(lineage.source_table(w, now, tag), nid, "reads", {}, tag, now)
        for rep in props.get("feeds") or []:
            rid = lineage.node_id("report", "Power BI", rep)
            if lineage.get(rid):
                lineage.upsert_edge(nid, rid, "feeds", {"refresh": True}, tag, now)
        for dep in props.get("depends_on") or []:
            d = by_ext.get(str(dep))
            if d:
                lineage.upsert_edge(lineage.node_id(KIND_NODE.get(d["kind"], "job"), d["via"] or ad.LABEL, d["name"]), nid, "feeds", {"waits_on": True}, tag, now)
    lineage.prune(tag, now)


def scan_source(sid: str, now: float | None = None) -> dict:
    """Read one source with its adapter, store what it found, assess every integration, update the graph."""
    now = now or time.time()
    src = _source(sid)
    ad = adapters.get(src["kind"])
    cfg = _j(src["config"], {})
    secrets = {n: v for n in _secret_names(src["kind"]) for v in [secrets_store.get("org", f"intan:{sid}:{n}")] if v is not None}
    t0 = time.time()
    try:
        disc = ad.discover(cfg, secrets, now)
    except abase.AuthError as e:
        msg = f"Sign in again: {e}"
        db.run("UPDATE intan_sources SET status = 'error', error = ?, last_scan = ?, next_scan = ?, seconds = ?, updated = ? WHERE id = ?", (msg, now, now + src["every_min"] * 60, round(time.time() - t0, 1), now, sid))
        db.audit("intan.scan.error", sid, {"kind": src["kind"], "error": msg[:200]}, "system")
        return {"ok": False, "error": msg}
    except (abase.SourceError, Exception) as e:  # noqa: BLE001 - the source's own problem, shown to the person
        msg = str(e)[:300] or e.__class__.__name__
        traceback.print_exc()
        db.run("UPDATE intan_sources SET status = 'error', error = ?, last_scan = ?, next_scan = ?, seconds = ?, updated = ? WHERE id = ?", (msg, now, now + src["every_min"] * 60, round(time.time() - t0, 1), now, sid))
        db.audit("intan.scan.error", sid, {"kind": src["kind"], "error": msg[:200]}, "system")
        return {"ok": False, "error": msg}
    counts = _ingest(src, disc, now)
    risks = sum(len(assess(r["id"], now)) for r in db.q("SELECT id FROM intan_integrations WHERE source_id = ? AND active = 1", (sid,)))
    _to_lineage(src, now)
    db.run("UPDATE intan_sources SET status = 'ok', error = NULL, last_scan = ?, next_scan = ?, found = ?, seconds = ?, updated = ? WHERE id = ?",
           (now, now + src["every_min"] * 60, counts["found"], round(time.time() - t0, 1), now, sid))
    db.audit("intan.scan", sid, {"kind": src["kind"], **counts, "risks": risks}, "system")
    return {"ok": True, **counts, "risks": risks}


# ------------------------------------------------------------------ health rules with learned baselines

def _fmt_dur(s: float | None) -> str:
    if s is None:
        return "—"
    return f"{s:.1f} s" if s < 10 else f"{round(s)} s" if s < 90 else f"{round(s / 60)} min" if s < 5400 else f"{s / 3600:.1f} h"


def _fmt_vol(v: float | None, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "File":
        return f"{v / 1048576:.1f} MB" if v >= 1048576 else f"{v / 1024:.0f} KB" if v >= 1024 else f"{v:.0f} B"
    return f"{v:,.0f}"


def _when(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d %b %H:%M") if t else "—"


def _run_rows(runs: list[dict]) -> list[dict]:
    return [{"when": _when(r["started"]), "status": r["status"], "duration": _fmt_dur(r["duration_s"]), "volume": r["volume"], "error": (r["error"] or "")[:160]} for r in runs]


def assess(iid: str, now: float | None = None) -> list[dict]:
    """Apply every rule to one integration; store its risks (reopen / update / resolve) and its health."""
    now = now or time.time()
    i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (iid,))
    if not i:
        return []
    runs = db.q("SELECT * FROM intan_runs WHERE integration_id = ? AND started >= ? ORDER BY started", (iid, now - RULES["window_days"] * 86400))
    found: list[dict] = []
    week = [r for r in runs if r["started"] >= now - 7 * 86400]
    fails_week = [r for r in week if r["status"] == "failed"]
    last = runs[-1] if runs else None
    code = i["kind"] in CODE_KINDS
    # failing / screen change / credential expired / dependency — from the newest runs
    if last and last["status"] == "failed" and sum(1 for r in runs[-3:] if r["status"] == "failed") >= 2:
        err = last["error"] or ""
        if i["kind"] == "Bot" and SCREEN_RE.search(err):
            found.append({"kind": "screen_change", "reason": f"{len(fails_week)} failures this week: the screen changed ({err[:90]})", "route": "sdlc",
                          "cause": f"The bot fails at a screen step — {err[:160]}. A code fix replaces the screen steps with the system's API where one exists.", "evidence": _run_rows(runs[-6:])})
        elif CRED_RE.search(err):
            found.append({"kind": "credential_expired", "reason": f"{len(fails_week)} failures this week: the sign-in no longer works ({err[:80]})", "route": "heal",
                          "cause": f"The credential this integration uses is refused: {err[:160]}. Renewing it is a configuration fix.", "evidence": _run_rows(runs[-6:])})
        else:
            found.append({"kind": "failing", "reason": f"{len(fails_week)} failures this week: {err[:100] or 'no error text'}", "route": "sdlc" if code else "heal",
                          "cause": f"The last {sum(1 for r in runs[-3:] if r['status'] == 'failed')} of 3 runs failed with: {err[:160] or 'no error text recorded'}.", "evidence": _run_rows(runs[-6:])})
    elif last and last["status"] == "skipped" and "waits on" in (last["error"] or "").lower():
        found.append({"kind": "dependency", "reason": last["error"][:120], "route": "sdlc" if code else "heal",
                      "cause": "This step is skipped while the step it waits on keeps failing; fixing the upstream step restores it.", "evidence": _run_rows(runs[-6:])})
    # unstable: retries this week, but the last run succeeded
    if last and last["status"] == "success" and len(fails_week) >= RULES["failures_week"] and len(fails_week) >= 0.1 * len(week):
        found.append({"kind": "unstable", "reason": f"{len(fails_week)} retries this week ({(fails_week[-1]['error'] or 'failed')[:60]})", "route": "sdlc" if code else "heal",
                      "cause": f"{len(fails_week)} runs failed and were re-run this week; the last error was: {(fails_week[-1]['error'] or '')[:160]}.", "evidence": _run_rows(fails_week[-6:])})
    # slow / slowing: learned duration baseline vs the newest successful runs
    ok = [r for r in runs if r["status"] == "success" and r["duration_s"]]
    old = [r for r in ok if r["started"] < now - 7 * 86400] or ok[:-3]
    if len(old) >= RULES["baseline_min"] and len(ok) >= RULES["baseline_min"] + 1:
        base = statistics.median(r["duration_s"] for r in old)
        recent = ok[-3:]
        cur = statistics.median(r["duration_s"] for r in recent)
        ratio = cur / base if base else 1
        if ratio >= RULES["slowing_factor"]:
            since = next((r for r in ok if r["duration_s"] >= RULES["slowing_factor"] * base and r["started"] >= now - 14 * 86400), recent[0])
            kind = "slow" if ratio >= RULES["slow_factor"] else "slowing"
            found.append({"kind": kind, "reason": f"Duration up {ratio:.1f}× since {_when(since['started'])[:6]} ({_fmt_dur(cur)} vs {_fmt_dur(base)} usual)" if kind == "slow" else f"Runs {ratio:.1f}× longer than usual ({_fmt_dur(cur)} vs {_fmt_dur(base)})",
                          "route": "sdlc" if code else "heal", "cause": f"Runs take {_fmt_dur(cur)} against a learned baseline of {_fmt_dur(base)} (median of {len(old)} earlier runs); nothing has failed yet." if kind == "slowing" else f"Runs take {_fmt_dur(cur)} against a learned baseline of {_fmt_dur(base)} — {ratio:.1f}× — since {_when(since['started'])}.",
                          "evidence": _run_rows(recent) + [{"when": "baseline", "status": f"median of {len(old)} runs", "duration": _fmt_dur(base), "volume": None, "error": ""}]})
        db.run("UPDATE intan_integrations SET usual_s = ? WHERE id = ?", (round(base, 1), iid))
    # volume drop: the newest run against the learned volume baseline
    vol = [r for r in runs if r["status"] == "success" and r["volume"]]
    if len(vol) >= RULES["baseline_min"] + 2:
        base_v = statistics.median(r["volume"] for r in vol[:-1])
        lastv = vol[-1]["volume"]
        if base_v and lastv <= base_v * (1 - RULES["volume_drop"]):
            pct = round(100 * (1 - lastv / base_v))
            what = "File" if i["kind"] == "File" else "Volume"
            found.append({"kind": "volume_drop", "reason": f"{what} {pct} % smaller than usual ({_fmt_vol(lastv, i['kind'])} vs {_fmt_vol(base_v, i['kind'])})", "route": "heal",
                          "cause": f"The newest run moved {_fmt_vol(lastv, i['kind'])} against a learned baseline of {_fmt_vol(base_v, i['kind'])} (median of {len(vol) - 1} runs). Nothing has failed yet — check the source before the next run.", "evidence": _run_rows(vol[-5:])})
    # credentials by name and expiry
    for c in db.q("SELECT * FROM intan_credentials WHERE integration_id = ?", (iid,)):
        if c["expires"] is None:
            continue
        days = (c["expires"] - now) / 86400
        if days < 0 or (c["status"] or "") == "expired":
            if not any(f["kind"] == "credential_expired" for f in found):
                found.append({"kind": "credential_expired", "reason": f"{c['name']} expired {_when(c['expires'])}", "route": "heal", "cause": f"The credential '{c['name']}' ({c['kind'] or 'credential'}) has expired; renewing it is a configuration fix.",
                              "evidence": [{"when": _when(c["expires"]), "status": "expired", "duration": "", "volume": None, "error": c["name"]}]})
        elif days <= RULES["credential_days"]:
            left = math.ceil(days)
            found.append({"kind": "credential_expiring", "reason": f"API token expires in {left} day{'' if left == 1 else 's'} ({c['name']})", "route": "heal",
                          "cause": f"The credential '{c['name']}' ({c['kind'] or 'credential'}) expires on {_when(c['expires'])}; nothing has failed yet. Renewing it is a configuration fix.",
                          "evidence": [{"when": _when(c["expires"]), "status": c["status"] or "valid", "duration": "", "volume": None, "error": c["name"]}]})
    # usage, announced changes
    for s in db.q("SELECT * FROM intan_signals WHERE integration_id = ?", (iid,)):
        if s["kind"] in ("usage", "licence") and s["limit_value"] and s["value"] is not None and 100 * s["value"] / s["limit_value"] >= RULES["usage_pct"]:
            found.append({"kind": "usage", "reason": s["text"], "route": "heal", "cause": f"{s['text']} — at this rate the pack runs out before the period ends; raising the pack or throttling is a configuration change.",
                          "evidence": [{"when": _when(s["seen"]), "status": f"{round(100 * s['value'] / s['limit_value'])} %", "duration": "", "volume": s["value"], "error": s["text"]}]})
        elif s["kind"] == "schema_change":
            found.append({"kind": "schema_change", "reason": s["text"], "route": "sdlc" if code or i["kind"].startswith("API") else "heal",
                          "cause": f"{s['text']}" + (f" (due {_when(s['due'])})" if s["due"] else "") + " — the mapping must change before the portal does; nothing has failed yet.",
                          "evidence": [{"when": _when(s["due"]) if s["due"] else _when(s["seen"]), "status": "announced", "duration": "", "volume": None, "error": s["text"]}]})
    # owners
    if not i["owner"]:
        props = _j(i["properties"], {})
        found.append({"kind": "no_owner", "reason": (f"Found in {props['found_in']}; not in any inventory" if props.get("found_in") else "Running, but nobody has claimed it"), "route": "owner",
                      "cause": "No team owns this integration: the tool does not name one and the RACI table has no match. Assign an owner so failures reach someone.",
                      "evidence": [{"when": _when(last["started"]) if last else "—", "status": f"{len(runs)} runs in {RULES['window_days']} days", "duration": _fmt_dur(last["duration_s"]) if last else "", "volume": None, "error": props.get("found_in") or ""}]})
    # store: reopen / update / resolve
    kinds = {f["kind"] for f in found}
    for f in found:
        have = db.one("SELECT * FROM intan_risks WHERE integration_id = ? AND kind = ?", (iid, f["kind"]))
        health = RISK_HEALTH[f["kind"]]
        if have:
            status = have["status"] if have["status"] in ("open", "proposed", "actioned", "dismissed") else "open"
            db.run("UPDATE intan_risks SET health = ?, reason = ?, cause = ?, evidence = ?, route = ?, status = ?, updated = ?, resolved = NULL WHERE id = ?",
                   (health, f["reason"][:300], f["cause"][:600], json.dumps(f["evidence"][:8]), f["route"], status, now, have["id"]))
        else:
            db.run("INSERT INTO intan_risks (id, integration_id, kind, health, reason, cause, evidence, route, status, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                   ("r-" + _secrets.token_hex(5), iid, f["kind"], health, f["reason"][:300], f["cause"][:600], json.dumps(f["evidence"][:8]), f["route"], now, now))
    for r in db.q("SELECT * FROM intan_risks WHERE integration_id = ? AND status != 'resolved'", (iid,)):
        if r["kind"] not in kinds:
            db.run("UPDATE intan_risks SET status = 'resolved', resolved = ?, updated = ? WHERE id = ?", (now, now, r["id"]))
            checkpoints.withdraw("intan.action", r["id"])
    live = [r for r in db.q("SELECT * FROM intan_risks WHERE integration_id = ? AND status IN ('open', 'proposed', 'actioned')", (iid,))]
    health = min((r["health"] for r in live), key=HEALTH_ORDER.index, default="Healthy" if runs else "Unknown")
    top = sorted(live, key=lambda r: (HEALTH_ORDER.index(r["health"]), len(r["reason"])))
    m30 = [r for r in runs if r["started"] >= now - 30 * 86400 and r["status"] in ("success", "failed")]
    db.run("UPDATE intan_integrations SET health = ?, signal = ?, last_run = ?, last_status = ?, success_30 = ? WHERE id = ?",
           (health, top[0]["reason"] if top else None, last["started"] if last else None, last["status"] if last else None,
            round(100 * sum(1 for r in m30 if r["status"] == "success") / len(m30), 1) if m30 else None, iid))
    return found


# ------------------------------------------------------------------ act before it breaks (with approval)

def _risk(rid: str) -> dict:
    r = db.one("SELECT * FROM intan_risks WHERE id = ?", (rid,))
    if not r:
        raise HTTPException(404, "No such risk.")
    r["evidence"] = _j(r["evidence"], [])
    return r


def proposal(risk: dict, i: dict, route: str | None = None) -> dict:
    route = route or risk["route"]
    if route not in ROUTE_LABEL:
        raise HTTPException(400, "The action is ticket, heal, sdlc or owner.")
    pr = "P1" if risk["health"] == "Failing" else "P2" if risk["health"] in ("Degraded", "At risk") else "P3"
    steps = {"ticket": f"A ticket goes to {ROUTE_TARGET['ticket']} with the summary, cause, evidence and priority {pr}. Owner: {i['owner'] or 'to be assigned'}.",
             "heal": "Self-healing prepares a configuration fix (renew the credential, restore the setting, re-run), tests it on a copy and waits for your approval.",
             "sdlc": "A change request is opened from the ticket; agents plan the change" + (" (replace screen steps with the system's API)" if risk["kind"] == "screen_change" else "") + ", develop and test it on a branch and run UAT on synthetic data — your tech lead approves the plan and the release.",
             "owner": "The owner you name is recorded for this integration and the RACI table; failures and tickets then reach them."}
    return {"route": route, "label": ROUTE_LABEL[route], "target": ROUTE_TARGET[route], "priority": pr, "summary": f"{i['name']}: {risk['reason']}", "cause": risk["cause"],
            "evidence": risk["evidence"], "owner": i["owner"], "integration": {"id": i["id"], "name": i["name"], "kind": i["kind"], "via": i["via"], "from": i["from_system"], "to": i["to_system"]},
            "next": steps[route], "then": "ticket → AI SDLC" if risk["route"] == "sdlc" else "assign an owner" if risk["route"] == "owner" else "ticket → Self-healing"}


def act(rid: str, u: dict, route: str | None = None, owner: str | None = None) -> dict:
    """Propose the action: opens the checkpoint; nothing else is written until it is accepted."""
    risk = _risk(rid)
    if risk["status"] in ("resolved", "dismissed"):
        raise HTTPException(409, f"This risk is {risk['status']}.")
    if risk["status"] == "actioned":
        raise HTTPException(409, "An action was already approved for this risk.")
    i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (risk["integration_id"],))
    p = proposal(risk, i, route)
    if p["route"] == "owner" and not (owner or "").strip():
        raise HTTPException(400, "Name the owner to assign.")
    if owner:
        p["owner"] = owner.strip()[:120]
    ev = {"summary": p["summary"], "items": [f"{e.get('when')} · {e.get('status')}" + (f" · {e['duration']}" if e.get("duration") else "") + (f" · {e['error']}" if e.get("error") else "") for e in p["evidence"][:6]],
          "counts": {"priority": p["priority"], "route": p["label"]}, "columns": ["when", "status", "duration", "volume", "error"], "rows": p["evidence"], "proposal": p, "risk": {"id": rid, "kind": risk["kind"], "label": RISK_LABEL.get(risk["kind"], risk["kind"]), "health": risk["health"]}}
    c = checkpoints.open("intan.action", rid, MODULE, f"{p['label']}: {i['name']}", "table", ev, link=f"#/integrations?open={i['id']}", opened_by=u["id"], agent="Relay")
    db.run("UPDATE intan_risks SET status = 'proposed', checkpoint_id = ?, route = ?, updated = ? WHERE id = ?", (c["id"], p["route"], time.time(), rid))
    db.audit("intan.action.proposed", rid, {"route": p["route"], "integration": i["name"], "priority": p["priority"], "checkpoint": c["id"]}, u["id"])
    return {"checkpoint": c, "risk": _risk(rid), "proposal": p}


def _on_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    risk = db.one("SELECT * FROM intan_risks WHERE id = ?", (c["subject"],))
    if not risk:
        return
    p = (c.get("evidence") or {}).get("proposal") or {}
    now = time.time()
    if decision == "accept":
        wid = "w-" + _secrets.token_hex(5)
        body = {k: p.get(k) for k in ("summary", "cause", "evidence", "priority", "owner", "integration", "next", "target")}
        db.run("INSERT INTO intan_work (id, risk_id, integration_id, kind, title, body, priority, target, status, checkpoint_id, approved_by, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'drafted', ?, ?, ?)",
               (wid, risk["id"], risk["integration_id"], p.get("route") or risk["route"], c["name"][:200], json.dumps(body), p.get("priority"), p.get("target"), c["id"], who, now))
        db.run("UPDATE intan_risks SET status = 'actioned', updated = ? WHERE id = ?", (now, risk["id"]))
        if p.get("route") == "ticket":                        # consolidation: the Service desk raises it now (its own approval of exactly what is written)
            _raise_ticket(wid, p, who)
        if (p.get("route") == "owner") and p.get("owner"):
            db.run("UPDATE intan_integrations SET owner = ?, owner_from = 'person' WHERE id = ?", (p["owner"], risk["integration_id"]))
            i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (risk["integration_id"],))
            db.run("INSERT INTO intan_owners (id, pattern, owner, role, updated, updated_by) VALUES (?, ?, ?, 'A', ?, ?)", ("o-" + _secrets.token_hex(3), i["name"], p["owner"], now, who))
            assess(risk["integration_id"], now)
        db.audit("intan.action.accepted", risk["id"], {"work": wid, "route": p.get("route"), "comment": (comment or "")[:200]}, who)
    else:
        db.run("UPDATE intan_risks SET status = 'open', checkpoint_id = NULL, note = ?, updated = ? WHERE id = ?", ((comment or "")[:500], now, risk["id"]))
        db.audit("intan.action.sent_back", risk["id"], {"comment": (comment or "")[:200]}, who)


checkpoints.register_kind("intan.action", "Integration action", _on_decision)


def _raise_ticket(wid: str, p: dict, who: str) -> None:
    """An approved "Raise a ticket": the Service desk (P12) asks a named person to approve exactly the ticket, on the
    first source that may raise tickets; with none, the draft waits in the Service desk's ticket drafts."""
    try:
        from . import itsm
        s = itsm.ticket_target()
        if not s:
            return
        i = p.get("integration") or {}
        lines = [p.get("cause") or "", f"Integration: {i.get('kind') or ''} {i.get('name') or ''} on {i.get('via') or 'its platform'} ({i.get('from') or '—'} → {i.get('to') or '—'})",
                 f"Owner: {p['owner']}" if p.get("owner") else "", "\n".join(" · ".join(str(e.get(k)) for k in ("when", "status", "duration", "error") if e.get(k)) for e in (p.get("evidence") or [])[:6]),
                 "Found by Relay's Integration analytics."]
        itsm.request_write(s["id"], "create", {"title": p.get("summary") or "Integration at risk", "description": "\n\n".join(x for x in lines if x.strip()), "priority": p.get("priority") or "P3",
                                               "labels": ["integration-analytics"]}, who=who, module=MODULE, origin=f"intan_work:{wid}", link=f"#/integrations?open={i.get('id') or ''}",
                           name=f"Raise a ticket on {s['name']}: {p.get('summary') or 'integration at risk'}"[:200])
    except Exception:  # noqa: BLE001 - refused (scope, settings) or unreachable: the draft waits in the Service desk's list
        traceback.print_exc()


def _ticket_written(wr: dict, event: str) -> None:
    """P12's hook: the ticket an approved action asked for was written (or not)."""
    wid = str(wr.get("origin") or "").split(":", 1)[-1]
    w = db.one("SELECT * FROM intan_work WHERE id = ?", (wid,))
    if not w:
        return
    body = _j(w["body"], {})
    if event == "written":
        res = wr.get("result") or {}
        body["ticket"] = {"key": res.get("key"), "url": res.get("url"), "source": wr.get("source"), "approved_by": wr.get("decided_by_name")}
        db.run("UPDATE intan_work SET status = 'raised', body = ? WHERE id = ?", (json.dumps(body), wid))
        db.audit("intan.ticket.raised", w["risk_id"], {"work": wid, "key": res.get("key")}, None)
    else:
        body["ticket_request"] = {"status": event, "error": wr.get("error")}
        db.run("UPDATE intan_work SET body = ? WHERE id = ?", (json.dumps(body), wid))


try:                                                           # consolidation: P12 tells us when the ticket is written
    from . import itsm as _itsm
    _itsm.register_write_hook("intan_work", _ticket_written)
except Exception:  # noqa: BLE001
    traceback.print_exc()


def dismiss(rid: str, u: dict, comment: str) -> dict:
    risk = _risk(rid)
    if not (comment or "").strip():
        raise HTTPException(400, "Say why this risk can be dismissed.")
    checkpoints.withdraw("intan.action", rid, who=u["id"])
    db.run("UPDATE intan_risks SET status = 'dismissed', note = ?, checkpoint_id = NULL, updated = ? WHERE id = ?", (comment.strip()[:500], time.time(), rid))
    db.audit("intan.action.dismissed", rid, {"comment": comment[:200]}, u["id"])
    assess(risk["integration_id"])
    return _risk(rid)


# ------------------------------------------------------------------ reading

def _display(i: dict) -> dict:
    props = _j(i["properties"], {})
    out = {k: i[k] for k in ("id", "source_id", "ext_id", "name", "kind", "via", "from_system", "to_system", "schedule", "owner", "owner_from", "node_id", "health", "signal", "last_run", "last_status", "success_30", "usual_s", "first_seen", "last_seen", "active")}
    out["display_name"] = ("Unknown: " + i["name"]) if (not i["owner"] and props.get("found_in")) else i["name"]
    out["properties"] = props
    out["code"] = i["kind"] in CODE_KINDS
    return out


def integrations(filter_: str = "all", q: str = "", source: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM intan_integrations WHERE active = 1 ORDER BY name")
    out = []
    for r in rows:
        if source and r["source_id"] != source:
            continue
        if filter_ == "issues" and r["health"] == "Healthy":
            continue
        if filter_ not in ("all", "issues") and r["health"] != filter_:
            continue
        if q and q.lower() not in f"{r['name']} {r['from_system']} {r['to_system']} {r['via']} {r['owner']} {r['kind']}".lower():
            continue
        out.append(_display(r))
    return out


def risks(status: str = "open") -> list[dict]:
    sts = ("open", "proposed") if status == "open" else (status,)
    rows = db.q(f"SELECT r.*, i.name AS integration_name, i.kind AS integration_kind, i.health AS integration_health, i.owner AS owner, i.via AS via, i.from_system, i.to_system "
                f"FROM intan_risks r JOIN intan_integrations i ON i.id = r.integration_id WHERE r.status IN ({','.join('?' * len(sts))}) AND i.active = 1 ORDER BY r.updated DESC", sts)
    out = []
    for r in rows:
        r["evidence"] = _j(r["evidence"], [])
        r["label"] = RISK_LABEL.get(r["kind"], r["kind"])
        r["then"] = "ticket → AI SDLC" if r["route"] == "sdlc" else "assign an owner" if r["route"] == "owner" else "ticket → Self-healing"
        out.append(r)
    out.sort(key=lambda r: (HEALTH_ORDER.index(r["health"]), -r["updated"]))
    return out


def kpis() -> dict:
    rows = db.q("SELECT health, owner FROM intan_integrations WHERE active = 1")
    return {"found": len(rows), "healthy": sum(1 for r in rows if r["health"] == "Healthy"), "at_risk": sum(1 for r in rows if r["health"] == "At risk"),
            "failing": sum(1 for r in rows if r["health"] in ("Failing", "Degraded")), "no_owner": sum(1 for r in rows if not r["owner"]),
            "sources": db.one("SELECT COUNT(*) AS n FROM intan_sources")["n"], "scanned": db.one("SELECT COUNT(*) AS n FROM intan_sources WHERE last_scan IS NOT NULL")["n"]}


def stats(now: float | None = None) -> dict:
    now = now or time.time()
    day0 = int(now // 86400)
    per_day = collections.Counter(); weeks: dict[str, list] = collections.defaultdict(lambda: [0, 0])
    for r in db.q("SELECT started, status FROM intan_runs WHERE started >= ?", (now - 49 * 86400,)):
        d = int(r["started"] // 86400)
        if d > day0 - 7:
            per_day[d] += 1
        if r["status"] in ("success", "failed"):
            iso = dt.datetime.fromtimestamp(r["started"], dt.timezone.utc).isocalendar()
            w = weeks[f"W{iso[1]:02d}"]
            w[0] += 1; w[1] += r["status"] == "success"
    days = [{"day": dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime("%a"), "date": dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).strftime("%Y-%m-%d"), "runs": per_day.get(d, 0)} for d in range(day0 - 6, day0 + 1)]
    wk = sorted(weeks.items())[-6:]
    by_type = collections.Counter(r["kind"] for r in db.q("SELECT kind FROM intan_integrations WHERE active = 1"))
    by_via = collections.Counter(f"{r['kind']} ({r['via']})" if r["via"] else r["kind"] for r in db.q("SELECT kind, via FROM intan_integrations WHERE active = 1"))
    return {"runs_per_day": days, "success_rate": [{"week": k, "pct": round(100 * v[1] / v[0], 1) if v[0] else None, "runs": v[0]} for k, v in wk],
            "by_type": [{"type": k, "n": v} for k, v in by_type.most_common()], "by_via": [{"type": k, "n": v} for k, v in by_via.most_common(10)]}


TOOL_NAMES = {"n8n", "Azure Data Factory", "Oracle Integration Cloud", "UiPath", "SSIS", "SAP CPI", "MuleSoft", "Boomi", "Logic Apps", "Azure Logic Apps", "AWS Glue", "Power Automate",
              "Blue Prism", "Automation Anywhere", "Airflow", "Apache Airflow", "Kong", "APIM", "Informatica", "Fivetran", "Sample estate"}


def map_data() -> dict:
    """Systems as nodes in columns (sources → tools → targets → consumers) and integrations as edges coloured by health."""
    rows = [r for r in db.q("SELECT * FROM intan_integrations WHERE active = 1") if r["from_system"] and r["to_system"]]
    tools = TOOL_NAMES | {adapters.get(s["kind"]).LABEL for s in db.q("SELECT kind FROM intan_sources") if s["kind"] in adapters.ADAPTERS}
    systems: dict[str, dict] = {}
    incoming: dict[str, set] = collections.defaultdict(set)
    for r in rows:
        for s in (r["from_system"], r["to_system"]):
            systems.setdefault(s, {"id": "sys:" + s, "label": s, "kind": "system", "issues": 0, "col": None})
        incoming[r["to_system"]].add(r["from_system"])
        if r["health"] != "Healthy":
            systems[r["from_system"]]["issues"] += 1; systems[r["to_system"]]["issues"] += 1
    for s in systems.values():
        if s["label"] in tools:
            s["col"] = 1
        elif not incoming.get(s["label"]):
            s["col"] = 0
    for _ in range(4):
        for s in systems.values():
            if s["col"] is not None:
                continue
            ins = [systems[x]["col"] for x in incoming[s["label"]] if systems[x]["col"] is not None]
            if ins and all(c >= 2 for c in ins) and len(ins) == len(incoming[s["label"]]):
                s["col"] = 3
            elif ins:
                s["col"] = 2
    for s in systems.values():
        if s["col"] is None:
            s["col"] = 2
    edges = [{"id": r["id"], "from": "sys:" + r["from_system"], "to": "sys:" + r["to_system"], "kind": "feeds", "label": r["name"], "status": r["health"],
              "signal": r["signal"], "type": r["kind"], "schedule": r["schedule"], "owner": r["owner"]} for r in rows]
    return {"nodes": sorted(systems.values(), key=lambda s: (s["col"], s["label"])), "edges": edges}


def details(iid: str) -> dict:
    i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (iid,))
    if not i:
        raise HTTPException(404, "No such integration.")
    out = _display(i)
    runs = db.q("SELECT * FROM intan_runs WHERE integration_id = ? ORDER BY started DESC LIMIT 30", (iid,))
    out["runs"] = [{**r, "when": _when(r["started"]), "duration": _fmt_dur(r["duration_s"])} for r in runs]
    out["risks"] = [{**r, "evidence": _j(r["evidence"], []), "label": RISK_LABEL.get(r["kind"], r["kind"]), "proposal": proposal({**r, "evidence": _j(r["evidence"], [])}, i),
                     "checkpoint": checkpoints.get(r["checkpoint_id"]) if r.get("checkpoint_id") else None}
                    for r in db.q("SELECT * FROM intan_risks WHERE integration_id = ? AND status IN ('open', 'proposed', 'actioned') ORDER BY updated DESC", (iid,))]
    out["work"] = [{**w, "body": _j(w["body"], {})} for w in db.q("SELECT * FROM intan_work WHERE integration_id = ? ORDER BY created DESC", (iid,))]
    out["credentials"] = db.q("SELECT name, kind, expires, status FROM intan_credentials WHERE integration_id = ?", (iid,))
    out["source"] = public_source(_source(i["source_id"]))
    feeds = {"reports": [], "downstream": 0}
    if i["node_id"] and lineage.get(i["node_id"]):
        im = lineage.impact(i["node_id"], stop_at={"system"})
        feeds = {"reports": im["reports"], "downstream": im["downstream"], "text": im["text"]}
    out["feeds"] = feeds
    return out


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
    secrets: dict | None = None
    every_min: int | None = None


class OwnersIn(BaseModel):
    rows: list[dict]


class ActIn(BaseModel):
    route: str | None = None
    owner: str | None = None


class Comment(BaseModel):
    comment: str


@router.get("/api/intan/overview")
def api_overview():
    _u()
    return {"kpis": kpis(), "risks": risks("open"), "map": map_data(), "stats": stats(), "sources": [public_source(s) for s in db.q("SELECT * FROM intan_sources ORDER BY created")],
            "scan": scan_state(), "owners": owners(), "adapters": adapters.describe(), "rules": RULES, "labels": RISK_LABEL}


@router.get("/api/intan/integrations")
def api_integrations(filter: str = "all", q: str = "", source: str | None = None):  # noqa: A002
    _u()
    return {"items": integrations(filter, q, source)}


@router.get("/api/intan/integrations/{iid}")
def api_integration(iid: str):
    _u()
    return details(iid)


@router.get("/api/intan/stats")
def api_stats():
    _u()
    return stats()


@router.get("/api/intan/map")
def api_map():
    _u()
    return map_data()


@router.get("/api/intan/adapters")
def api_adapters():
    _u()
    return {"items": adapters.describe()}


@router.get("/api/intan/sources")
def api_sources():
    _u()
    return {"items": [public_source(s) for s in db.q("SELECT * FROM intan_sources ORDER BY created")], "scan": scan_state()}


@router.post("/api/intan/sources")
def api_add_source(body: SourceIn):
    return save_source(body.model_dump(), _builder())


@router.put("/api/intan/sources/{sid}")
def api_edit_source(sid: str, body: SourceIn):
    return save_source(body.model_dump(), _builder(), sid)


@router.delete("/api/intan/sources/{sid}")
def api_remove_source(sid: str):
    remove_source(sid, _builder())
    return {"ok": True}


@router.post("/api/intan/sources/{sid}/scan")
def api_scan_source(sid: str):
    u = _builder()
    s = _source(sid)
    if s["status"] == "paused":
        raise HTTPException(409, "This source is paused. Resume it first.")
    return request_scan([sid], u["id"])


@router.post("/api/intan/sources/{sid}/pause")
def api_pause(sid: str):
    u = _builder(); _source(sid)
    db.run("UPDATE intan_sources SET status = 'paused', updated = ? WHERE id = ?", (time.time(), sid))
    db.audit("intan.source.pause", sid, None, u["id"])
    return public_source(_source(sid))


@router.post("/api/intan/sources/{sid}/resume")
def api_resume(sid: str):
    u = _builder(); _source(sid)
    db.run("UPDATE intan_sources SET status = 'new', next_scan = ?, updated = ? WHERE id = ?", (time.time(), time.time(), sid))
    db.audit("intan.source.resume", sid, None, u["id"])
    return public_source(_source(sid))


@router.post("/api/intan/scan")
def api_scan_all():
    u = _builder()
    ids = [s["id"] for s in db.q("SELECT id FROM intan_sources WHERE status != 'paused'")]
    if not ids:
        raise HTTPException(400, "Add a source first.")
    return request_scan(ids, u["id"])


@router.get("/api/intan/owners")
def api_owners():
    _u()
    return {"items": owners()}


@router.put("/api/intan/owners")
def api_set_owners(body: OwnersIn):
    u = _builder()
    rows = set_owners(body.rows, u)
    for r in db.q("SELECT id FROM intan_integrations WHERE active = 1 AND (owner IS NULL OR owner_from = 'raci')"):
        i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (r["id"],))
        own = _raci_owner(i, rows)
        db.run("UPDATE intan_integrations SET owner = ?, owner_from = ? WHERE id = ?", (own, "raci" if own else None, r["id"]))
        assess(r["id"])
    return {"items": rows}


@router.get("/api/intan/risks")
def api_risks(status: str = "open"):
    _u()
    return {"items": risks(status)}


@router.post("/api/intan/risks/{rid}/act")
def api_act(rid: str, body: ActIn | None = None):
    u = _builder()
    return act(rid, u, body.route if body else None, body.owner if body else None)


@router.post("/api/intan/risks/{rid}/dismiss")
def api_dismiss(rid: str, body: Comment):
    return dismiss(rid, _builder(), body.comment)


@router.get("/api/intan/work")
def api_work(status: str | None = None):
    _u()
    rows = db.q("SELECT w.*, i.name AS integration_name FROM intan_work w JOIN intan_integrations i ON i.id = w.integration_id" + (" WHERE w.status = ?" if status else "") + " ORDER BY w.created DESC", (status,) if status else ())
    return {"items": [{**w, "body": _j(w["body"], {})} for w in rows]}
