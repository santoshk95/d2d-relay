"""Self-healing (build-plan v2, P16): watch what the platform already observes, diagnose with the logs and the
lineage, propose a fix, prove it on a copy, apply it when a person approves - through the owning module's own
guarded path - and keep the rule for next time.

Watch: dashboard refresh and gate failures (project runs, extracts and review gates), expired warehouse sign-ins
(connections), the DAX checker's heartbeat, schedules that paused, integration runs that failed with a retry-able
error (P13), and the work rows other modules leave for Self-healing (P12 `itsm_work`, P13 `intan_work`, P14
`observe_work` with kind heal). Each becomes a **case**: a folder `output/projects/<id>/` with kind `heal`,
evidence/ (the activity log, run history, lineage neighbours, the configuration it may read - secrets never),
diagnosis.yaml, fix/ (the copy with before / after) and tests/.

Diagnose: a learned (or built-in) rule for the failure's signature proposes its fix at once - "seen N times" - and
the agent run is skipped unless the person asks; otherwise the registered job `heal_diagnose` (an LLM run in the
case folder) writes diagnosis.yaml (cause, confidence, evidence rows, the fix, the test). Checkpoint `heal.diagnosis`
(view text) - nothing runs until a person accepts the proposed fix.
Fix on a copy: job `heal_fix` applies the change on a copy (a copied dashboard definition is edited by the agent and
re-checked by the definition validator; a copied configuration is validated by the owning module's validator), runs
the proposed test and records before / after. Checkpoint `heal.apply` (view table).
Approve & apply: on accept the change goes through the owning module's own path - the dashboard's extract or revise
job, `connectors.renew` / `connectors.request_write` (a guarded write with its own per-change approval),
`schedules.save`, `observe.set_asset_checks` - never by editing files behind a module's back. An accepted fix becomes
(or strengthens) a rule in `heal_rules`, keyed by the signature; rules can be disabled, every change is audited.
"""
from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import json
import os
import re
import secrets as _secrets
import shutil
import statistics
import time
import traceback
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from genbi_kit import daxcheck, definition
from genbi_kit import validate as checks

from . import auth, checkpoints, connectors, db, heal_prompts, lineage, notify, schedules, store, worker

router = APIRouter()
MODULE = "Self-healing"
ROUTE = "#/heal"
KIND_DIAG = "heal.diagnosis"
KIND_APPLY = "heal.apply"
TEST_HOOKS = os.environ.get("D2D_TEST_HOOKS") == "1"
WATCH_EVERY_S = int(os.environ.get("HEAL_WATCH_S", "300"))
AUTO_DIAGNOSE = os.environ.get("HEAL_AUTO_DIAGNOSE", "1") == "1"
COPY_MAX_BYTES = 200 * 1024 * 1024

db.register_schema("""
CREATE TABLE IF NOT EXISTS heal_cases (
  id TEXT PRIMARY KEY, signature TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
  what TEXT, place TEXT, since REAL, route TEXT NOT NULL DEFAULT 'config', status TEXT NOT NULL DEFAULT 'waiting', step TEXT NOT NULL DEFAULT 'watch',
  rule_id TEXT, checkpoint_id TEXT, owner_id TEXT, subject TEXT NOT NULL DEFAULT '{}', diagnosis TEXT, fix TEXT, applied TEXT, note TEXT, work TEXT,
  created REAL NOT NULL, updated REAL NOT NULL, closed REAL, closed_by TEXT);
CREATE INDEX IF NOT EXISTS heal_cases_status ON heal_cases (status, updated);
CREATE INDEX IF NOT EXISTS heal_cases_source ON heal_cases (source, source_id);
CREATE TABLE IF NOT EXISTS heal_rules (
  id TEXT PRIMARY KEY, signature TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, title TEXT NOT NULL, cause TEXT, fix TEXT NOT NULL, test TEXT,
  origin TEXT NOT NULL DEFAULT 'learned', enabled INTEGER NOT NULL DEFAULT 1, seen INTEGER NOT NULL DEFAULT 0, applied INTEGER NOT NULL DEFAULT 0,
  learned_from TEXT, learned_by TEXT, created REAL NOT NULL, updated REAL NOT NULL, last_used REAL);
""")

# What a fix may be: the kinds the app knows how to prove on a copy and apply through the owning module.
FIX_KINDS = {
    "rerun_extract": {"what": "pull the stale warehouse tables again through the dashboard's own extract job", "keys": [], "module": "D2D"},
    "renew_connection": {"what": "ask the connection's owner to sign in again; what paused on it resumes when it works", "keys": [], "module": "Connections"},
    "notify_hold": {"what": "tell the people responsible and hold what depends on it - no configuration changes", "keys": [], "module": "DAX checker"},
    "dashboard_revise": {"what": "a change to the dashboard definition, applied through the dashboard's own revise path", "keys": ["file", "edit"], "module": "D2D"},
    "rerun_integration": {"what": "run the integration again on its platform (a guarded write on its connection, with its own approval)", "keys": ["integration", "action"], "module": "Integration analytics"},
    "schedule_update": {"what": "change a schedule setting (email account, cadence, recipients) and resume it", "keys": ["email_account_id", "cadence", "recipients"], "module": "Schedules"},
    "threshold": {"what": "tune a data check's threshold on one asset", "keys": ["check", "asset", "config"], "module": "Data observability"},
    "retry_policy": {"what": "a retry policy on an integration: attempts and the wait between them", "keys": ["integration", "attempts", "wait_s"], "module": "Integration analytics"},
    "needs_code": {"what": "a code change - AI SDLC opens a change request from this case", "keys": [], "module": "AI SDLC"},
}
ROUTE_TEXT = {"config": "a configuration change through the owning module", "code": "a code change through AI SDLC"}
STEPS = ["watch", "diagnose", "fix", "prove", "approve", "learn"]
STEP_LABEL = {"watch": "Watch", "diagnose": "Diagnose", "fix": "Fix", "prove": "Prove", "approve": "Approve", "learn": "Learn"}
STEP_OF = {"waiting": "watch", "diagnosing": "diagnose", "diagnosed": "diagnose", "sent_back": "diagnose", "fixing": "fix", "held": "prove", "proven": "approve",
           "applying": "approve", "applied": "learn", "needs_code": "fix", "recovered": "learn", "closed": "learn", "error": "fix"}
STATUS_LABEL = {"waiting": "Waiting to start", "diagnosing": "Diagnosing", "diagnosed": "Fix proposed - confirm it", "sent_back": "Sent back", "fixing": "Fixing on a copy",
                "held": "Needs a person", "proven": "Proven - approve to apply", "applying": "Applying (write awaiting approval)", "applied": "Applied", "needs_code": "Needs code -> AI SDLC",
                "recovered": "Recovered on its own", "closed": "Closed", "error": "Run failed"}
OPEN = ("waiting", "diagnosing", "diagnosed", "sent_back", "fixing", "held", "proven", "applying", "error")
RETRYABLE = re.compile(r"timeout|timed out|\b50[234]\b|\b429\b|rate limit|connection reset|temporarily|unavailable|ECONNRESET|try again|throttl", re.I)
EXTRACT_ERR = re.compile(r"extract|warehouse|pull", re.I)
SIGNIN_ERR = re.compile(r"sign in|sign-in|reconsent|expired|token|unauthori[sz]ed|\b401\b", re.I)

# Known failure signatures to start with: each is a built-in rule (origin "builtin") with the fix it proposes and
# the test the copy run makes. Learned rules join them with origin "learned".
BUILTIN = {
    "stale_extract": {"kind": "stale_extract", "title": "Stale extract: re-run the extract", "route": "config",
                      "cause": "The warehouse extract behind the dashboard did not run on its schedule (or failed), so the dashboard shows old numbers.",
                      "fix": {"kind": "rerun_extract", "module": "D2D", "text": "Pull the stale warehouse tables again through the dashboard's own extract job.", "change": {}, "risk": "low"},
                      "test": {"what": "The same tables pull into a copy of the project from the same connection.", "how": "Each stale table is extracted into the case's fix/copy folder with the connection owner's stored sign-in (read-only).", "expect": "Every table arrives with rows and a newer extract time than the stale file."}},
    "warehouse_signin": {"kind": "warehouse_signin", "title": "Expired warehouse sign-in: renew the connection, tell the owner", "route": "config",
                         "cause": "The stored sign-in for the warehouse connection no longer works (expired or revoked); everything that reads through it - extracts, schedules, Ask D - waits on it.",
                         "fix": {"kind": "renew_connection", "module": "Connections", "text": "Mark the connection for renewal and tell its owner to sign in again; the schedules paused on it resume once it works.", "change": {}, "risk": "low"},
                         "test": {"what": "Confirms the stored sign-in really is refused (not a one-off outage).", "how": "A read-only connection test runs with the stored credentials.", "expect": "The warehouse refuses the sign-in; if it accepts it, the case closes as recovered."}},
    "daxcheck_offline": {"kind": "daxcheck_offline", "title": "DAX checker off: tell the admins, hold publishing", "route": "config",
                         "cause": "The DAX checker on the Windows PC stopped writing its heartbeat; every version waits for its DAX check and publishing is blocked.",
                         "fix": {"kind": "notify_hold", "module": "DAX checker", "text": "Tell the admins to start daxcheck\\start-daxcheck.cmd and hold publishing until the heartbeat is back.", "change": {}, "risk": "low"},
                         "test": {"what": "Confirms the checker is still silent.", "how": "The heartbeat file is read again.", "expect": "No heartbeat in the last 30 seconds; if it is back, the case closes as recovered."}},
    "integration_retry": {"kind": "integration_retry", "title": "Integration run failed with a retry-able error: run it again", "route": "config",
                          "cause": "The integration's last run failed on a transient error (timeout, throttling, a short outage) rather than on its logic or data.",
                          "fix": {"kind": "rerun_integration", "module": "Integration analytics", "text": "Run the integration again on its platform - a guarded write on its connection that needs its own approval.", "change": {"action": "rerun"}, "risk": "low"},
                          "test": {"what": "The platform is reachable again.", "how": "A read-only test of the platform's connection, and the run history is read for repeated failures.", "expect": "The connection answers; the failure did not repeat on every run."}},
    "schedule_mail": {"kind": "schedule_mail", "title": "Schedule paused: its email account is missing or expired", "route": "config",
                      "cause": "The schedule's email account was removed or its sign-in expired, so the schedule paused instead of sending.",
                      "fix": {"kind": "schedule_update", "module": "Schedules", "text": "Point the schedule at the owner's working email account (or deliver in the app when it has one recipient) and resume it.", "change": {"email_account_id": "<owner's working account or none>"}, "risk": "low"},
                      "test": {"what": "The changed schedule is valid and has a next run.", "how": "The Schedules validator checks the copy (target, recipients, account) and computes the next run.", "expect": "The validator accepts it and the next run is in the future."}},
    "schedule_connection": {"kind": "warehouse_signin", "title": "Schedule paused: a warehouse sign-in expired", "route": "config",
                            "cause": "The schedule reads live data through a connection whose stored sign-in expired, so it paused.",
                            "fix": {"kind": "renew_connection", "module": "Connections", "text": "Mark the connection for renewal and tell its owner; the schedule resumes once the sign-in works.", "change": {}, "risk": "low"},
                            "test": {"what": "Confirms the stored sign-in is refused.", "how": "A read-only connection test.", "expect": "The warehouse refuses it; if it accepts, the schedule is resumed and the case closes."}},
}
GATE_FIX = {"kind": "dashboard_revise", "module": "D2D", "text": "Apply the smallest change to the definition that makes the failing gate pass, through the dashboard's own revise path.", "change": {"file": "definition.yaml"}, "risk": "medium"}
GATE_TEST = {"what": "The copied definition passes the definition check after the edit.", "how": "The agent edits fix/copy/definition.yaml and the definition validator runs on the copy.", "expect": "No validation errors on the copy and the failing gate's problem is gone."}
_sched_task = None


def _j(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _when(t: float | None) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if t else "-"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:32] or "case"


# ------------------------------------------------------------------ rules

def ensure_builtin() -> None:
    now = time.time()
    for sig, r in BUILTIN.items():
        if not db.one("SELECT 1 FROM heal_rules WHERE signature = ?", (sig,)):
            db.run("INSERT INTO heal_rules (id, signature, kind, title, cause, fix, test, origin, enabled, seen, applied, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, 'builtin', 1, 0, 0, ?, ?)",
                   ("rule-" + sig.replace("_", "-"), sig, r["kind"], r["title"], r["cause"], json.dumps(r["fix"]), json.dumps(r["test"]), now, now))
    for gid in ("report_rules", "model_rules", "coherence", "pbir_schema", "definition", "prototype", "custom_visuals", "power_query", "data", "values", "display"):
        sig = f"gate:{gid}"
        if not db.one("SELECT 1 FROM heal_rules WHERE signature = ?", (sig,)):
            db.run("INSERT INTO heal_rules (id, signature, kind, title, cause, fix, test, origin, enabled, seen, applied, created, updated) VALUES (?, ?, 'gate_failure', ?, ?, ?, ?, 'builtin', 1, 0, 0, ?, ?)",
                   ("rule-gate-" + gid.replace("_", "-"), sig, f"Review gate failed: {gid.replace('_', ' ')} - fix the definition", f"The latest version fails the '{gid.replace('_', ' ')}' review gate; the problems the gate lists point at the definition keys to change.",
                    json.dumps(GATE_FIX), json.dumps(GATE_TEST), now, now))


def _rule_public(r: dict) -> dict:
    return {**r, "fix": _j(r["fix"], {}), "test": _j(r["test"], {}), "enabled": bool(r["enabled"])}


def rule_for(signature: str) -> dict | None:
    r = db.one("SELECT * FROM heal_rules WHERE signature = ? AND enabled = 1", (signature,))
    return _rule_public(r) if r else None


def rules() -> list[dict]:
    return [_rule_public(r) for r in db.q("SELECT * FROM heal_rules ORDER BY origin DESC, seen DESC, title")]


def set_rule(rid: str, enabled: bool, who: str) -> dict:
    r = db.one("SELECT * FROM heal_rules WHERE id = ?", (rid,))
    if not r:
        raise HTTPException(404, "No such rule.")
    db.run("UPDATE heal_rules SET enabled = ?, updated = ? WHERE id = ?", (1 if enabled else 0, time.time(), rid))
    db.audit("heal.rule.enable" if enabled else "heal.rule.disable", rid, {"signature": r["signature"], "title": r["title"]}, who)
    return _rule_public(db.one("SELECT * FROM heal_rules WHERE id = ?", (rid,)))


def learn(case: dict, who: str) -> dict:
    """An accepted, applied fix becomes a rule for its signature - or strengthens the one that proposed it."""
    diag = case.get("diagnosis") or {}
    now = time.time()
    have = db.one("SELECT * FROM heal_rules WHERE signature = ?", (case["signature"],))
    if have:
        db.run("UPDATE heal_rules SET applied = applied + 1, last_used = ?, updated = ? WHERE id = ?", (now, now, have["id"]))
        if have["origin"] == "learned" and diag.get("fix"):
            db.run("UPDATE heal_rules SET fix = ?, test = ?, cause = COALESCE(?, cause) WHERE id = ?", (json.dumps(diag["fix"]), json.dumps(diag.get("test") or {}), diag.get("cause"), have["id"]))
        db.audit("heal.rule.used", have["id"], {"signature": case["signature"], "case": case["id"], "applied": have["applied"] + 1}, who)
        return _rule_public(db.one("SELECT * FROM heal_rules WHERE id = ?", (have["id"],)))
    rid = "rule-" + _secrets.token_hex(4)
    db.run("INSERT INTO heal_rules (id, signature, kind, title, cause, fix, test, origin, enabled, seen, applied, learned_from, learned_by, created, updated, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, 'learned', 1, 1, 1, ?, ?, ?, ?, ?)",
           (rid, case["signature"], case["kind"], (case.get("title") or case["signature"])[:160], (diag.get("cause") or "")[:600], json.dumps(diag.get("fix") or {}), json.dumps(diag.get("test") or {}), case["id"], who, now, now, now))
    db.audit("heal.rule.learned", rid, {"signature": case["signature"], "case": case["id"], "fix": (diag.get("fix") or {}).get("kind")}, who)
    return _rule_public(db.one("SELECT * FROM heal_rules WHERE id = ?", (rid,)))


# ------------------------------------------------------------------ cases

def _row(cid: str) -> dict:
    r = db.one("SELECT * FROM heal_cases WHERE id = ?", (cid,))
    if not r:
        raise HTTPException(404, "No such case.")
    for k in ("subject", "diagnosis", "fix", "applied", "work"):
        r[k] = _j(r[k], {} if k != "work" else None)
    return r


def _set(cid: str, **kw) -> None:
    kw["updated"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in kw)
    vals = tuple(json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in kw.values())
    db.run(f"UPDATE heal_cases SET {cols} WHERE id = ?", vals + (cid,))


def public(r: dict, with_detail: bool = False) -> dict:
    out = {k: r.get(k) for k in ("id", "signature", "kind", "source", "source_id", "title", "what", "place", "since", "route", "status", "step", "rule_id", "checkpoint_id", "owner_id",
                                  "subject", "diagnosis", "fix", "applied", "note", "work", "created", "updated", "closed", "closed_by")}
    out["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
    out["step"] = STEP_OF.get(r["status"], r.get("step") or "watch")
    out["step_index"] = STEPS.index(out["step"])
    out["kind_label"] = (BUILTIN.get(r["signature"]) or {}).get("title") or ("Review gate failed" if r["signature"].startswith("gate:") else r["kind"].replace("_", " ").capitalize())
    out["route_label"] = "Configuration" if r["route"] == "config" else "Code -> AI SDLC"
    out["age_s"] = round(time.time() - (r.get("since") or r["created"]))
    out["open"] = r["status"] in OPEN
    if r.get("rule_id"):
        rr = db.one("SELECT * FROM heal_rules WHERE id = ?", (r["rule_id"],))
        out["rule"] = _rule_public(rr) if rr else None
    if with_detail:
        out["checkpoint"] = checkpoints.get(r["checkpoint_id"]) if r.get("checkpoint_id") else None
        out["checkpoints"] = [checkpoints._public(c) for c in db.q("SELECT * FROM checkpoints WHERE subject = ? AND kind IN (?, ?) ORDER BY created", (r["id"], KIND_DIAG, KIND_APPLY))]
        d = store.ROOT / r["id"]
        out["evidence_files"] = sorted(p.name for p in (d / "evidence").glob("*")) if (d / "evidence").exists() else []
        out["evidence_rows"] = _j((d / "evidence" / "rows.json").read_text(encoding="utf-8"), []) if (d / "evidence" / "rows.json").exists() else []
        try:
            st = store.load(r["id"])
            out["runs"] = st.get("runs") or []
            out["folder_status"] = st.get("status")
            out["folder_error"] = st.get("error")
        except (KeyError, FileNotFoundError, ValueError):
            out["runs"], out["folder_status"], out["folder_error"] = [], None, None
        try:
            out["activity"] = [{k: e.get(k) for k in ("ts", "kind", "stage", "level", "text", "tool", "detail", "who")} for e in store.activity(r["id"], 0, 400)[-40:]]
        except (KeyError, FileNotFoundError):
            out["activity"] = []
        out["sdlc"] = (r.get("applied") or {}).get("sdlc") if r.get("applied") else None
    return out


def _owner_user(uid: str | None) -> str:
    return uid if uid and db.user(uid) else db.ADMIN_ID


def _folder(cid: str, cand: dict, who: str | None) -> Path:
    d = store.ROOT / cid
    (d / "evidence").mkdir(parents=True, exist_ok=True)
    (d / "fix").mkdir(exist_ok=True)
    (d / "tests").mkdir(exist_ok=True)
    store.save({"id": cid, "kind": "heal", "name": cand["title"], "prompt": cand.get("what") or cand["title"], "model": worker.DEFAULT_MODEL, "status": "waiting",
                "created": time.time(), "versions": [], "runs": [], "job": None, "error": None,
                "case": {k: cand.get(k) for k in ("signature", "kind", "source", "source_id", "place", "route")}})
    db.add_project(cid, _owner_user(who))
    (d / "request.md").write_text(f"# Self-healing case: {cand['title']}\n\n## What the watcher saw ({_when(time.time())})\n\n{cand.get('what') or ''}\n\n"
                                  f"- Where: {cand.get('place') or '-'}\n- Signature: {cand['signature']}\n- Source: {cand['source']} {cand['source_id']}\n"
                                  f"- Suggested route: {cand.get('route') or 'config'} - {ROUTE_TEXT.get(cand.get('route') or 'config')}\n\n"
                                  "Nothing changes on a live system until a named person approves the fix in the validation queue.\n", encoding="utf-8")
    return d


def open_case(cand: dict, who: str | None = None) -> dict | None:
    """One open case per (source, source id, signature). A matching enabled rule proposes its fix at once."""
    have = db.one("SELECT id FROM heal_cases WHERE source = ? AND source_id = ? AND signature = ? AND closed IS NULL", (cand["source"], cand["source_id"], cand["signature"]))
    if have:
        return None
    cid = "heal-" + _slug(cand["title"]) + "-" + _secrets.token_hex(2)
    now = time.time()
    _folder(cid, cand, who or cand.get("owner_id"))
    db.run("INSERT INTO heal_cases (id, signature, kind, source, source_id, title, what, place, since, route, status, step, owner_id, subject, work, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 'watch', ?, ?, ?, ?, ?)",
           (cid, cand["signature"], cand["kind"], cand["source"], cand["source_id"], cand["title"][:200], (cand.get("what") or "")[:1000], (cand.get("place") or "")[:200], cand.get("since") or now,
            cand.get("route") or "config", cand.get("owner_id"), json.dumps(cand.get("subject") or {}, default=str), json.dumps(cand["work"]) if cand.get("work") else None, now, now))
    db.audit("heal.case.opened", cid, {"signature": cand["signature"], "source": cand["source"], "source_id": cand["source_id"], "title": cand["title"][:120]}, who or "watcher")
    try:
        _write_evidence(_row(cid))
    except Exception:  # noqa: BLE001 - evidence is best effort
        traceback.print_exc()
    rule = rule_for(cand["signature"])
    if rule:
        db.run("UPDATE heal_rules SET seen = seen + 1, last_used = ?, updated = ? WHERE id = ?", (now, now, rule["id"]))
        diag = {"cause": rule["cause"], "confidence": 0.9 if rule["origin"] == "learned" else 0.8, "evidence": _rows(cid)[:6], "fix": rule["fix"], "test": rule["test"],
                "notes": f"Proposed by the rule '{rule['title']}' (seen {rule['seen'] + 1} time{'' if rule['seen'] + 1 == 1 else 's'}, applied {rule['applied']} time{'' if rule['applied'] == 1 else 's'}). "
                         "Send it back with a note to have the agent diagnose it afresh.", "from_rule": rule["id"], "seen": rule["seen"] + 1}
        _set(cid, rule_id=rule["id"])
        (store.ROOT / cid / "diagnosis.yaml").write_text(yaml.safe_dump(diag, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
        diagnosed(cid, diag, rule=rule)
    elif AUTO_DIAGNOSE:
        try:
            worker.enqueue(cid, "heal_diagnose")
            _set(cid, status="diagnosing", step="diagnose")
        except Exception as e:  # noqa: BLE001 - a quota or a missing agent: the case waits for the person
            _set(cid, note=f"Diagnosis not started: {str(e)[:200]}")
    return _row(cid)


def _rows(cid: str) -> list[dict]:
    p = store.ROOT / cid / "evidence" / "rows.json"
    return _j(p.read_text(encoding="utf-8"), []) if p.exists() else []


def _conn_evidence(c: dict) -> dict:
    """A connection as evidence: its public fields, with only whether its sign-in is stored (no secret names or values)."""
    pub = connectors.public(c)
    stored = pub.pop("has_secret", {}) or {}
    pub["sign_in_stored"] = all(stored.values()) if stored else None
    return pub


def _dump(d: Path, name: str, obj) -> str:
    (d / "evidence" / name).write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    return name


def _write_evidence(case: dict) -> list[str]:
    """What the platform knows about the thing that failed, as files the agent reads (no secrets, ever)."""
    d = store.ROOT / case["id"]
    (d / "evidence").mkdir(exist_ok=True)
    sub, files, rows = case["subject"] or {}, [], []
    pid = sub.get("project")
    if pid:
        try:
            st = store.load(pid)
            files.append(_dump(d, "project.json", {k: st.get(k) for k in ("id", "name", "status", "error", "approved", "extract_schedule", "updated", "model")}))
            files.append(_dump(d, "runs.json", (st.get("runs") or [])[-20:]))
            vs = st.get("versions") or []
            if vs:
                files.append(_dump(d, "gates.json", {"version": vs[-1].get("v"), "gates": vs[-1].get("gates") or []}))
                for g in vs[-1].get("gates") or []:
                    if g.get("status") == "fail":
                        rows.append({"when": _when(st.get("updated")), "what": f"gate failed: {g.get('name')}", "detail": (g.get("summary") or "")[:300]})
            acts = store.activity(pid, 0, 2000)[-80:]
            (d / "evidence" / "activity.jsonl").write_text("".join(json.dumps(e, default=str) + "\n" for e in acts), encoding="utf-8")
            files.append("activity.jsonl")
            for e in acts:
                if e.get("level") == "error" or e.get("kind") == "error":
                    rows.append({"when": _when(e.get("ts")), "what": f"{e.get('stage') or 'run'} error", "detail": (e.get("text") or "")[:300]})
            if st.get("error"):
                rows.append({"when": _when(st.get("updated")), "what": "project error", "detail": st["error"][:300]})
            m = connectors.manifest(store.ROOT / pid)
            if m:
                files.append(_dump(d, "extracts.json", {f: {k: v for k, v in x.items() if k != "connection"} | {"connection": {k: v for k, v in (x.get("connection") or {}).items() if k not in ("password", "token", "secret")}} for f, x in m.items()}))
                for f, x in m.items():
                    rows.append({"when": _when(x.get("extracted")), "what": f"extract {f}", "detail": f"{x.get('rows')} rows from {x.get('kind')}:{x.get('object')}"})
                conns = []
                for x in m.values():
                    try:
                        c = connectors._row(x["connection_id"])
                        conns.append(_conn_evidence(c))
                    except connectors.ConnectorError:
                        pass
                files.append(_dump(d, "config.json", {"connections": conns}))
            try:
                lineage.ensure_synced()
                nid = lineage.node_id("report", "Power BI", st.get("name") or pid)
                if lineage.get(nid):
                    files.append(_dump(d, "lineage.json", {"node": nid, "neighbours": lineage.neighbours(nid), "impact": lineage.impact(nid)}))
            except Exception:  # noqa: BLE001
                pass
        except (KeyError, FileNotFoundError, ValueError):
            pass
    if sub.get("schedule"):
        s = db.one("SELECT * FROM schedules WHERE id = ?", (sub["schedule"],))
        if s:
            files.append(_dump(d, "schedule.json", {k: (_j(s[k], {}) if k in ("target", "cadence", "state") else s[k]) for k in s if k != "recipients"} | {"recipients": len(_j(s["recipients"], []))}))
            rows.append({"when": _when(s.get("last_run") or s.get("updated")), "what": f"schedule {s['status']}", "detail": (s.get("paused_reason") or s.get("last_error") or "")[:300]})
            accounts = db.q("SELECT id, kind, address, status, error FROM email_accounts WHERE owner_id = ?", (s["owner_id"],))
            files.append(_dump(d, "email_accounts.json", [{**a, "address": a["address"][:3] + "...@" + a["address"].split("@")[-1] if "@" in a["address"] else "..."} for a in accounts]))
    if sub.get("connection"):
        try:
            c = connectors._row(sub["connection"])
            files.append(_dump(d, "config.json", {"connection": _conn_evidence(c), "used_by": connectors.used_by(c["id"])}))
            rows.append({"when": _when(c.get("last_used")), "what": f"connection {c['status']}", "detail": (c.get("error") or "")[:300]})
            paused = db.q("SELECT id, name, paused_reason FROM schedules WHERE owner_id = ? AND status = 'paused' AND paused_reason LIKE 'Connection:%'", (c["owner_id"],))
            if paused:
                files.append(_dump(d, "schedules_paused.json", paused))
        except connectors.ConnectorError:
            pass
    if sub.get("integration"):
        i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (sub["integration"],))
        if i:
            runs = db.q("SELECT * FROM intan_runs WHERE integration_id = ? ORDER BY started DESC LIMIT 20", (i["id"],))
            files.append(_dump(d, "integration.json", {**i, "properties": _j(i["properties"], {}), "runs": runs}))
            for r in runs[:6]:
                rows.append({"when": _when(r["started"]), "what": f"run {r['status']}", "detail": (r.get("error") or f"{r.get('duration_s')} s")[:300]})
            if i.get("node_id"):
                try:
                    files.append(_dump(d, "lineage.json", {"node": i["node_id"], "neighbours": lineage.neighbours(i["node_id"]), "impact": lineage.impact(i["node_id"], stop_at={"system"})}))
                except Exception:  # noqa: BLE001
                    pass
    if sub.get("incident"):
        try:
            from . import observe
            inc = observe.detail(sub["incident"])
            imp = dict(inc.get("impact") or {})
            imp.pop("path", None)
            files.append(_dump(d, "incident.json", {k: inc.get(k) for k in ("id", "check_kind", "check_label", "title", "what", "severity", "status", "cause", "measured", "expected", "rows", "asset", "first_seen", "last_seen", "tool")} | {"impact": imp}))
            for r in (inc.get("rows") or [])[:6]:
                rows.append({"when": _when(inc.get("last_seen")), "what": str(r.get("what") or r.get("What") or inc.get("check_label")), "detail": f"measured {r.get('measured') or r.get('Measured')} - expected {r.get('expected') or r.get('Expected')}"[:300]})
        except Exception:  # noqa: BLE001
            pass
    if sub.get("group"):
        try:
            from . import itsm
            g = itsm.public_group(itsm._grp(sub["group"]), True)
            files.append(_dump(d, "ticket.json", {k: g.get(k) for k in ("id", "title", "about", "category", "summary", "priority", "reason", "route", "route_reason", "tickets", "status", "ticket_list")}))
            for t in (g.get("ticket_list") or [])[:6]:
                rows.append({"when": _when(t.get("created")), "what": f"ticket {t.get('key')}", "detail": (t.get("summary") or t.get("title") or "")[:300]})
        except Exception:  # noqa: BLE001
            pass
    if sub.get("daxcheck"):
        beat = daxcheck.available()
        try:
            hb = json.loads((daxcheck.QUEUE / "heartbeat.json").read_text(encoding="utf-8-sig")) if (daxcheck.QUEUE / "heartbeat.json").exists() else None
        except (OSError, ValueError):
            hb = None
        files.append(_dump(d, "daxcheck.json", {"online": bool(beat), "heartbeat": hb, "pending": len(list((daxcheck.QUEUE / "requests").glob("*.json"))) if (daxcheck.QUEUE / "requests").exists() else 0}))
        rows.append({"when": _when(time.time()), "what": "DAX checker heartbeat", "detail": "online" if beat else "no heartbeat in the last 30 seconds"})
    if case.get("what") and not rows:
        rows.append({"when": _when(case.get("since")), "what": case["kind"].replace("_", " "), "detail": case["what"][:300]})
    _dump(d, "rows.json", rows[:40])
    return sorted(set(files + ["rows.json"]))


# ------------------------------------------------------------------ watchers

def _watch_dashboards() -> list[dict]:
    out = []
    for p in store.all_projects():
        if (p.get("kind") or "dashboard") != "dashboard":
            continue
        try:
            st = store.load(p["id"])
        except (KeyError, FileNotFoundError, ValueError):
            continue
        pid, name = p["id"], p.get("name") or p["id"]
        owner = (db.project(pid) or {}).get("owner_id")
        err = st.get("error") or ""
        if st.get("status") == "error" and err and not err.startswith("Stopped") and EXTRACT_ERR.search(err):
            sig = "warehouse_signin" if SIGNIN_ERR.search(err) and (st.get("warehouse") or {}).get("connection_id") else "stale_extract"
            out.append({"signature": sig, "kind": sig, "source": "project", "source_id": pid, "title": f"Extract failed: {name}", "what": err, "place": f"Dashboard {name}", "since": st.get("updated"), "route": "config", "owner_id": owner,
                        "subject": {"project": pid, **({"connection": st["warehouse"]["connection_id"]} if sig == "warehouse_signin" else {})}})
        m = connectors.manifest(store.ROOT / pid)
        sched = st.get("extract_schedule") or {}
        if m and sched.get("daily"):
            oldest = min((x.get("extracted") or 0) for x in m.values())
            if oldest and time.time() - oldest > 2 * 86400:
                out.append({"signature": "stale_extract", "kind": "stale_extract", "source": "project", "source_id": pid, "title": f"Stale extract: {name}",
                            "what": f"The daily extract is {round((time.time() - oldest) / 86400, 1)} days old ({', '.join(m)[:120]}).", "place": f"Dashboard {name}", "since": oldest + 86400, "route": "config", "owner_id": owner, "subject": {"project": pid}})
        vs = st.get("versions") or []
        if vs:
            bad = [g for g in vs[-1].get("gates") or [] if g.get("status") == "fail"]
            for g in bad[:3]:
                if g.get("id") in ("approval", "kpis", "dax"):
                    continue
                out.append({"signature": f"gate:{g.get('id')}", "kind": "gate_failure", "source": "project", "source_id": f"{pid}:v{vs[-1].get('v')}:{g.get('id')}", "title": f"Gate failed: {g.get('name')} - {name}",
                            "what": (g.get("summary") or "")[:600], "place": f"Dashboard {name} v{vs[-1].get('v')}", "since": st.get("updated"), "route": "config", "owner_id": owner,
                            "subject": {"project": pid, "version": vs[-1].get("v"), "gate": g.get("id"), "gates": [x.get("id") for x in bad]}})
    return out


def _watch_connections() -> list[dict]:
    out = []
    for c in db.q("SELECT * FROM connections WHERE status = 'reconsent'"):
        out.append({"signature": "warehouse_signin", "kind": "warehouse_signin", "source": "connection", "source_id": c["id"], "title": f"Sign-in expired: {c['name']}",
                    "what": c.get("error") or "The stored sign-in no longer works.", "place": f"Connection {c['name']} ({c['kind']})", "since": c.get("last_used"), "route": "config", "owner_id": c["owner_id"], "subject": {"connection": c["id"]}})
    return out


def _watch_daxcheck() -> list[dict]:
    if daxcheck.available() or os.environ.get("HEAL_WATCH_DAXCHECK", "1") != "1":
        return []
    req = daxcheck.QUEUE / "requests"
    pending = len(list(req.glob("*.json"))) if req.exists() else 0
    if not pending and not (daxcheck.QUEUE / "heartbeat.json").exists():
        return []                                   # never ran here (a test box): nothing to heal
    return [{"signature": "daxcheck_offline", "kind": "daxcheck_offline", "source": "daxcheck", "source_id": "daxcheck", "title": "DAX checker is offline",
             "what": f"No heartbeat in the last 30 seconds; {pending} check(s) waiting. Publishing is blocked until it is back.", "place": "DAX checker (Windows PC)", "since": time.time(), "route": "config", "subject": {"daxcheck": True}}]


def _watch_schedules() -> list[dict]:
    out = []
    for s in db.q("SELECT * FROM schedules WHERE status = 'paused' AND paused_reason IS NOT NULL AND paused_reason != 'Paused by you.'"):
        reason = s["paused_reason"] or ""
        if reason.startswith("Email:"):
            sig, kind = "schedule_mail", "schedule_mail"
        elif reason.startswith("Connection:"):
            sig, kind = "schedule_connection", "warehouse_signin"
        else:
            sig, kind = "schedule_failed", "generic"
        out.append({"signature": sig, "kind": kind, "source": "schedule", "source_id": s["id"], "title": f"Schedule paused: {s['name']}", "what": reason, "place": f"Schedule {s['name']}",
                    "since": s.get("updated"), "route": "config", "owner_id": s["owner_id"], "subject": {"schedule": s["id"], "project": (_j(s["target"], {}).get("project") or (_j(s["target"], {}).get("scope") or {}).get("project"))}})
    return out


def _watch_integrations() -> list[dict]:
    out = []
    if "intan_integrations" not in db.tables():
        return out
    for i in db.q("SELECT * FROM intan_integrations WHERE active = 1 AND last_status IN ('failed', 'error', 'Failed', 'Error')"):
        last = db.one("SELECT * FROM intan_runs WHERE integration_id = ? ORDER BY started DESC LIMIT 1", (i["id"],))
        if not last or not RETRYABLE.search(last.get("error") or ""):
            continue
        out.append({"signature": "integration_retry", "kind": "integration_retry", "source": "integration", "source_id": i["id"], "title": f"Run failed (retry-able): {i['name']}",
                    "what": last.get("error") or "", "place": f"{i['kind']} on {i.get('via') or i.get('from_system') or 'its platform'}", "since": last["started"], "route": "config",
                    "subject": {"integration": i["id"], "run": last["ext_id"], "connection": _integration_connection(i)}})
    return out


def _integration_connection(i: dict) -> str | None:
    """A write-capable connection for the integration's platform (its source kind or its 'via' name), if any."""
    src = db.one("SELECT kind, config FROM intan_sources WHERE id = ?", (i["source_id"],)) or {}
    cfg = _j(src.get("config"), {})
    if cfg.get("connection"):
        return cfg["connection"]
    for c in db.q("SELECT * FROM connections WHERE enabled = 1"):
        if (c.get("scope") or "read") != "write":
            continue
        if c["kind"] == src.get("kind") or (i.get("via") and i["via"].lower() in c["name"].lower()):
            return c["id"]
    return None


def _watch_work() -> list[dict]:
    """The rows P12 / P13 / P14 left for Self-healing become cases waiting to start."""
    out = []
    tables = set(db.tables())
    if "intan_work" in tables:
        for w in db.q("SELECT w.*, i.name AS iname, i.kind AS ikind, i.via AS via, i.owner AS iowner, r.kind AS rkind, r.cause AS rcause FROM intan_work w JOIN intan_integrations i ON i.id = w.integration_id LEFT JOIN intan_risks r ON r.id = w.risk_id WHERE w.kind = 'heal' AND w.status = 'drafted'"):
            body = _j(w["body"], {})
            rk = w.get("rkind") or "risk"
            sig = {"credential_expired": "warehouse_signin", "failing": "integration_retry", "unstable": "integration_retry", "dependency": "integration_retry"}.get(rk, f"intan:{rk}")
            kind = {"warehouse_signin": "warehouse_signin", "integration_retry": "integration_retry"}.get(sig, "generic")
            out.append({"signature": sig, "kind": kind, "source": "intan_work", "source_id": w["id"], "title": w["title"], "what": (body.get("summary") or "") + ("\n\n" + body["cause"] if body.get("cause") else ""),
                        "place": f"{w['ikind']} {w['iname']} on {w.get('via') or 'its platform'}", "since": w["created"], "route": "config", "owner_id": w.get("approved_by"),
                        "subject": {"integration": w["integration_id"], "connection": _integration_connection({"source_id": db.one("SELECT source_id FROM intan_integrations WHERE id = ?", (w["integration_id"],))["source_id"], "via": w.get("via")})}, "work": {"module": "intan", "table": "intan_work", "id": w["id"]}})
    if "observe_work" in tables:
        for w in db.q("SELECT w.*, i.check_kind, i.asset_id, i.title AS ititle, i.cause AS icause FROM observe_work w JOIN observe_incidents i ON i.id = w.incident_id WHERE w.kind = 'heal' AND w.status = 'approved'"):
            body = _j(w["body"], {})
            a = db.one("SELECT * FROM observe_assets WHERE id = ?", (w["asset_id"],)) or {}
            props = _j(a.get("config"), {})
            pid = (props.get("project") or _j((db.one("SELECT properties FROM lineage_nodes WHERE id = ?", (a.get("node_id"),)) or {}).get("properties"), {}).get("project")) if a else None
            sig = "stale_extract" if w["check_kind"] in ("freshness", "lineage") and pid and connectors.manifest(store.ROOT / pid) else f"observe:{w['check_kind']}"
            out.append({"signature": sig, "kind": "stale_extract" if sig == "stale_extract" else "generic", "source": "observe_work", "source_id": w["id"], "title": w["title"], "what": (body.get("summary") or w["ititle"]) + ("\n\n" + (body.get("cause") or w.get("icause") or "") if (body.get("cause") or w.get("icause")) else ""),
                        "place": a.get("label") or a.get("name") or "data asset", "since": w["created"], "route": "config", "owner_id": w.get("approved_by"),
                        "subject": {"incident": w["incident_id"], "project": pid, "asset": w["asset_id"], "check": w["check_kind"]}, "work": {"module": "observe", "table": "observe_work", "id": w["id"]}})
    if "itsm_work" in tables:
        for w in db.q("SELECT w.*, g.title AS gtitle, g.summary AS gsummary, g.category AS gcat, g.priority AS gprio FROM itsm_work w JOIN itsm_groups g ON g.id = w.group_id WHERE w.target = 'heal' AND w.status = 'recorded'"):
            out.append({"signature": f"itsm:{(w.get('gcat') or 'ticket').lower().replace(' ', '_')}", "kind": "generic", "source": "itsm_work", "source_id": w["id"], "title": w["gtitle"] or "Service desk ticket", "what": (w.get("gsummary") or "") + (f"\n\n{w['note']}" if w.get("note") else ""),
                        "place": f"Service desk - {w.get('gcat') or 'ticket'} - {w.get('gprio') or ''}".strip(" -"), "since": w["created"], "route": "config", "owner_id": w.get("who"),
                        "subject": {"group": w["group_id"]}, "work": {"module": "itsm", "table": "itsm_work", "id": w["id"]}})
    return out


def watch(who: str | None = None) -> dict:
    """Everything the platform observes, turned into cases (once each); recovered cases close themselves."""
    ensure_builtin()
    found, opened = [], []
    for fn in (_watch_dashboards, _watch_connections, _watch_daxcheck, _watch_schedules, _watch_integrations, _watch_work):
        try:
            found += fn()
        except Exception:  # noqa: BLE001 - one watcher must not stop the others
            traceback.print_exc()
    for cand in found:
        try:
            c = open_case(cand, who)
            if c:
                opened.append(c["id"])
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    recovered = _close_recovered()
    settled = _settle_writes()
    return {"seen": len(found), "opened": opened, "recovered": recovered, "settled": settled}


def _close_recovered() -> int:
    """A case whose failure is gone before a fix was applied closes as recovered (audited)."""
    n = 0
    for r in db.q("SELECT * FROM heal_cases WHERE closed IS NULL AND status IN ('waiting', 'diagnosing', 'diagnosed', 'sent_back', 'held', 'proven', 'applied')"):
        sub = _j(r["subject"], {})
        gone = False
        if r["source"] == "connection":
            c = db.one("SELECT status FROM connections WHERE id = ?", (r["source_id"],))
            gone = not c or c["status"] == "connected"
        elif r["source"] == "schedule":
            s = db.one("SELECT status FROM schedules WHERE id = ?", (r["source_id"],))
            gone = not s or s["status"] == "active"
        elif r["source"] == "daxcheck":
            gone = bool(daxcheck.available())
        elif r["source"] == "project" and r["kind"] == "gate_failure" and sub.get("project"):
            try:
                st = store.load(sub["project"])
                vs = st.get("versions") or []
                gone = bool(vs) and (vs[-1].get("v") != sub.get("version") or not any(g.get("id") == sub.get("gate") and g.get("status") == "fail" for g in vs[-1].get("gates") or []))
            except (KeyError, FileNotFoundError, ValueError):
                gone = True
        if gone and r["status"] == "applied":
            _close(r["id"], "closed", "The failure is gone after the fix.", "watcher")
            n += 1
        elif gone:
            _close(r["id"], "recovered", "The failure is no longer seen; nothing was applied.", "watcher")
            n += 1
    return n


def _settle_writes() -> int:
    """A re-run requested through connectors.request_write finishes when that write's own checkpoint is decided."""
    n = 0
    for r in db.q("SELECT * FROM heal_cases WHERE status = 'applying'"):
        applied = _j(r["applied"], {})
        cp = checkpoints.get(applied.get("write_checkpoint") or "")
        if not cp or cp["status"] == "open":
            continue
        if cp["status"] == "accepted":
            applied["result"] = f"The write was approved by {cp.get('decided_by')} and sent to the platform."
            _set(r["id"], status="applied", step="learn", applied=applied)
        else:
            applied["result"] = f"The write was {cp['status'].replace('_', ' ')}: {cp.get('comment') or ''}"
            _set(r["id"], status="held", step="prove", applied=applied, note="The guarded write was not approved.")
        n += 1
    return n


def _close(cid: str, status: str, note: str, who: str) -> None:
    checkpoints.withdraw(KIND_DIAG, cid, who=who)
    checkpoints.withdraw(KIND_APPLY, cid, who=who)
    _set(cid, status=status, step="learn", note=note, closed=time.time(), closed_by=who)
    db.audit("heal.case." + status, cid, {"note": note[:200]}, who)


# ------------------------------------------------------------------ diagnosis (the LLM job, or a rule)

def load_diagnosis(d: Path) -> dict:
    return yaml.safe_load((d / "diagnosis.yaml").read_text(encoding="utf-8")) or {}


def check_diagnosis(d: Path) -> list[str]:
    p = d / "diagnosis.yaml"
    if not p.exists():
        return ["diagnosis.yaml was not written"]
    try:
        y = load_diagnosis(d)
    except Exception as e:  # noqa: BLE001
        return [f"diagnosis.yaml does not parse: {str(e).splitlines()[0]}"]
    out = []
    if not isinstance(y, dict):
        return ["diagnosis.yaml must be a mapping with cause, confidence, evidence, fix and test"]
    if not str(y.get("cause") or "").strip():
        out.append("cause is missing")
    try:
        c = float(y.get("confidence"))
        if not 0 <= c <= 1:
            out.append(f"confidence {c} is not between 0 and 1")
    except (TypeError, ValueError):
        out.append("confidence must be a number between 0 and 1")
    ev = y.get("evidence")
    if not isinstance(ev, list) or not ev or not all(isinstance(e, dict) and (e.get("what") or e.get("detail")) for e in ev):
        out.append("evidence must be a list of rows with when / what / detail (at least one)")
    f = y.get("fix")
    if not isinstance(f, dict) or f.get("kind") not in FIX_KINDS:
        out.append("fix.kind must be one of " + ", ".join(FIX_KINDS))
    else:
        if not str(f.get("text") or "").strip():
            out.append("fix.text is missing")
        change = f.get("change") or {}
        if not isinstance(change, dict):
            out.append("fix.change must be a mapping")
        else:
            extra = [k for k in change if k not in FIX_KINDS[f["kind"]]["keys"]]
            if extra:
                out.append(f"fix.change has keys the kind {f['kind']} does not take: {', '.join(extra)}")
    t = y.get("test")
    if not isinstance(t, dict) or not str(t.get("what") or "").strip():
        out.append("test.what is missing")
    return out


def diagnosed(cid: str, diag: dict, rule: dict | None = None, summary: str = "") -> dict:
    """The diagnosis stands: store it, open the checkpoint for the proposed fix (nothing runs until it is accepted)."""
    f = diag.get("fix") or {}
    _set(cid, status="diagnosed", step="diagnose", diagnosis=diag, note=None)
    checkpoints.withdraw(KIND_DIAG, cid, who="system")
    r = _row(cid)
    conf = round(float(diag.get("confidence") or 0) * 100)
    items = [f"Fix ({FIX_KINDS.get(f.get('kind'), {}).get('module') or f.get('module') or '-'}): {f.get('text') or '-'}",
             f"Test on a copy: {(diag.get('test') or {}).get('what') or '-'}", f"Confidence {conf} % - risk {f.get('risk') or 'low'}"]
    if rule:
        items.insert(0, f"Rule '{rule['title']}' - seen {diag.get('seen') or rule['seen']} time{'' if (diag.get('seen') or rule['seen']) == 1 else 's'}, applied {rule['applied']} time{'' if rule['applied'] == 1 else 's'}; the agent run was skipped")
    ev = {"summary": diag.get("cause") or "", "items": items, "counts": {"confidence %": conf, "evidence rows": len(diag.get("evidence") or [])},
          "columns": ["when", "what", "detail"], "rows": diag.get("evidence") or [], "diagnosis": diag, "case": {"id": cid, "signature": r["signature"], "title": r["title"], "place": r["place"]}}
    cp = checkpoints.open(KIND_DIAG, cid, MODULE, f"Fix: {r['title']}", "text", ev, link=f"{ROUTE}/{cid}", assignee=r.get("owner_id") if r.get("owner_id") and db.user(r["owner_id"]) else None, agent="Relay", opened_by="agent")
    _set(cid, checkpoint_id=cp["id"])
    worker.app_note(cid, "heal_diagnose", (f"Rule-based diagnosis ({rule['title']}): " if rule else "Diagnosis: ") + (diag.get("cause") or "")[:300] + " Waiting for you to confirm the proposed fix.", "ok")
    db.audit("heal.diagnosed", cid, {"fix": f.get("kind"), "confidence": diag.get("confidence"), "rule": rule["id"] if rule else None, "summary": summary[:200]}, "agent")
    return _row(cid)


async def _diagnose_job(pid: str, args: dict) -> None:
    case = _row(pid)
    d = store.ROOT / pid
    _set(pid, status="diagnosing", step="diagnose")
    correction = args.get("correction")
    worker.app_note(pid, "heal_diagnose", "Relay is reading the evidence again with your note." if correction else "Relay is diagnosing: the logs, the run history, the lineage neighbours and the configuration it may read.")
    try:
        files = await asyncio.to_thread(_write_evidence, case)
        prompt = heal_prompts.diagnose(public(case), files, FIX_KINDS, ROUTE_TEXT.get(case["route"], ""), correction)
        res = await worker.agent(pid, "heal_diagnose", prompt, worker.TURNS["heal_diagnose"], "diagnosis", system=heal_prompts.SYSTEM)
        for attempt in range(worker.FIX_ROUNDS + 1):
            problems = await asyncio.to_thread(check_diagnosis, d)
            if not problems:
                break
            if attempt == worker.FIX_ROUNDS:
                raise RuntimeError(f"diagnosis.yaml still has {len(problems)} problem(s): " + "; ".join(problems[:4]))
            worker.app_note(pid, "heal_diagnose", f"The check found {len(problems)} problem(s) in diagnosis.yaml - Relay is fixing them.", "warn", problems)
            res = await worker.agent(pid, "heal_diagnose", heal_prompts.fix(problems), worker.TURNS["fix"], "diagnosis", resume=res.get("session_id"), system=heal_prompts.SYSTEM)
        diag = load_diagnosis(d)
        diag["from_rule"] = None
        diagnosed(pid, diag, summary=res.get("text") or "")
        store.update(pid, status="diagnosed", job=None, error=None)
    except Exception as e:
        _set(pid, status="error", step="diagnose", note=str(e)[:300])
        raise


worker.register_job("heal_diagnose", _diagnose_job, status="diagnosing", done="Diagnosis ready - confirm the proposed fix", llm=True, turns=60, timeout_s=1800)


# ------------------------------------------------------------------ fix on a copy (proof)

def _schedule_body(s: dict, change: dict) -> dict:
    body = {k: s[k] for k in ("kind", "name", "target", "cadence", "tz", "email_account_id", "recipients")}
    for k in ("email_account_id", "cadence", "recipients"):
        if k in change:
            body[k] = change[k]
    return body


def _prove(case: dict, diag: dict) -> dict:
    """Apply the proposed change on a copy, run the test, record before / after. Returns {before, after, test, summary}."""
    f, sub = diag.get("fix") or {}, case["subject"] or {}
    kind, change = f.get("kind"), f.get("change") or {}
    d = store.ROOT / case["id"]
    copy_dir = d / "fix" / "copy"
    before, after, test = [], [], {"ok": False, "text": ""}
    if kind == "rerun_extract":
        pid = sub.get("project")
        m = connectors.manifest(store.ROOT / pid) if pid else {}
        if not m:
            return {"before": [], "after": [], "test": {"ok": False, "text": "This dashboard has no warehouse extract to re-run: its data was uploaded, not pulled."}, "summary": "nothing to re-run"}
        shutil.rmtree(copy_dir, ignore_errors=True)
        (copy_dir / "data").mkdir(parents=True)
        pulled, errors = [], []
        for file, x in m.items():
            before.append([file, f"{x.get('rows')} rows - {_when(x.get('extracted'))}"])
            try:
                c = connectors._row(x["connection_id"])
                r = connectors.extract(c, x["object"], file[:-len(".parquet")], copy_dir, "heal")
                after.append([file, f"{r.get('rows')} rows - {_when(r.get('extracted'))}"])
                pulled.append(file)
            except connectors.Reconsent as e:
                errors.append(f"{file}: the sign-in expired ({e}) - renew the connection first")
                after.append([file, "sign-in expired"])
            except Exception as e:  # noqa: BLE001
                errors.append(f"{file}: {str(e)[:200]}")
                after.append([file, "failed"])
        test = {"ok": bool(pulled) and not errors, "text": f"{len(pulled)} of {len(m)} table(s) pulled into the copy" + (": " + "; ".join(errors) if errors else " - every table arrived with rows and a newer extract time."), "errors": errors}
    elif kind == "renew_connection":
        cid = sub.get("connection")
        if not cid:
            s = db.one("SELECT owner_id FROM schedules WHERE id = ?", (sub.get("schedule"),)) if sub.get("schedule") else None
            c = db.one("SELECT * FROM connections WHERE owner_id = ? AND status = 'reconsent'", (s["owner_id"],)) if s else None
            cid = c["id"] if c else None
        if not cid:
            return {"before": [], "after": [], "test": {"ok": False, "text": "No connection in 'sign in again' state was found for this case."}, "summary": "no connection"}
        c = connectors._row(cid)
        before = [["status", c["status"]], ["error", (c.get("error") or "")[:160]], ["last used", _when(c.get("last_used"))]]
        try:
            connectors.test({**c, "_who": "heal"})
            test = {"ok": False, "recovered": True, "text": f"{c['name']} accepted the stored sign-in: nothing to renew."}
        except connectors.Reconsent as e:
            test = {"ok": True, "text": f"Confirmed: {c['name']} refuses the stored sign-in ({str(e)[:160]})."}
        except Exception as e:  # noqa: BLE001
            test = {"ok": True, "text": f"{c['name']} could not be reached with the stored sign-in ({str(e)[:160]}); renewal is the safe fix."}
        if test["ok"] and c["status"] == "reconsent":              # the read-only test is proof, not a state change
            db.run("UPDATE connections SET status = 'reconsent', error = ? WHERE id = ?", (c.get("error"), c["id"]))
        paused = db.q("SELECT name FROM schedules WHERE owner_id = ? AND status = 'paused' AND paused_reason LIKE 'Connection:%'", (c["owner_id"],))
        after = [["status", "reconsent -> the owner signs in again"], ["owner told", (db.user(c["owner_id"]) or {}).get("name") or c["owner_id"]], ["schedules that resume", ", ".join(p["name"] for p in paused) or "none"]]
        case["subject"] = {**sub, "connection": cid}
        _set(case["id"], subject=case["subject"])
    elif kind == "notify_hold":
        beat = daxcheck.available()
        before = [["DAX checker", "online" if beat else "no heartbeat"]]
        after = [["admins told", "start daxcheck\\start-daxcheck.cmd on the Windows PC"], ["publishing", "held until the heartbeat is back"]]
        test = {"ok": not beat, "recovered": bool(beat), "text": "The checker is back online: nothing to do." if beat else "Confirmed: still no heartbeat."}
    elif kind == "dashboard_revise":
        return _prove_dashboard(case, diag)
    elif kind == "rerun_integration":
        i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (sub.get("integration"),))
        if not i:
            return {"before": [], "after": [], "test": {"ok": False, "text": "The integration is no longer listed."}, "summary": "gone"}
        runs = db.q("SELECT * FROM intan_runs WHERE integration_id = ? ORDER BY started DESC LIMIT 10", (i["id"],))
        last = runs[0] if runs else {}
        before = [["last run", f"{last.get('status')} - {_when(last.get('started'))}"], ["error", (last.get("error") or "")[:160]], ["failures in last 10", str(sum(1 for r in runs if r["status"].lower() in ("failed", "error")))]]
        cid = sub.get("connection")
        if cid:
            c = connectors._row(cid)
            try:
                connectors.test({**c, "_who": "heal"})
                reach = f"{c['name']} answers (read-only test)"
                ok = True
            except Exception as e:  # noqa: BLE001
                reach, ok = f"{c['name']} does not answer: {str(e)[:160]}", False
            after = [["re-run", f"requested on {c['name']} - a guarded write with its own approval"], ["platform", reach]]
            test = {"ok": ok, "text": reach + ("; the failure was transient, a re-run is safe." if ok else "")}
        else:
            after = [["re-run", f"the owner ({i.get('owner') or 'not named'}) is told to re-run it - no write-capable connection for {i.get('via') or 'this platform'} exists"]]
            test = {"ok": True, "text": f"No write-capable connection for {i.get('via') or 'this platform'}: Relay cannot re-run it itself; the owner is told with the error and the evidence."}
    elif kind == "schedule_update":
        sid = sub.get("schedule")
        s = schedules._row(sid) if sid else None
        if not s:
            return {"before": [], "after": [], "test": {"ok": False, "text": "The schedule is no longer there."}, "summary": "gone"}
        u = db.user(s["owner_id"]) or {"id": s["owner_id"]}
        ch = dict(change)
        if "email_account_id" in ch and (ch["email_account_id"] in (None, "", "<owner's working account or none>")):
            acc = db.one("SELECT id FROM email_accounts WHERE owner_id = ? AND status = 'connected' AND id != ? ORDER BY last_used DESC", (s["owner_id"], s.get("email_account_id") or ""))
            ch["email_account_id"] = acc["id"] if acc else None
        body = _schedule_body(s, ch)

        def cad(c, tz):
            try:
                return schedules.describe(c, tz)
            except (KeyError, TypeError):
                return json.dumps(c)
        before = [["status", f"{s['status']} - {(s.get('paused_reason') or '')[:120]}"], ["email account", s.get("email_account_id") or "in the app"], ["recipients", str(len(s["recipients"]))], ["cadence", cad(s["cadence"], s["tz"])]]
        try:
            clean = schedules.validate(u, body)
            nxt = schedules.next_run(clean["cadence"], clean["tz"], time.time())
            after = [["status", "active"], ["email account", clean["email_account_id"] or "in the app"], ["recipients", str(len(clean["recipients"]))], ["cadence", schedules.describe(clean["cadence"], clean["tz"])], ["next run", _when(nxt)]]
            test = {"ok": nxt > time.time(), "text": f"The Schedules validator accepts the copy; next run {_when(nxt)}."}
            (d / "fix" / "after.json").write_text(json.dumps(clean, default=str, indent=1), encoding="utf-8")
        except schedules.ScheduleError as e:
            after = [["status", "paused"]]
            test = {"ok": False, "text": f"The Schedules validator refused the copy: {e}"}
        diag["fix"]["change"] = ch
    elif kind == "threshold":
        from . import observe
        aid, check = change.get("asset") or sub.get("asset"), change.get("check") or sub.get("check")
        if not aid or not check:
            return {"before": [], "after": [], "test": {"ok": False, "text": "The threshold change names no asset or check."}, "summary": "incomplete"}
        cur = observe.check_cfg(aid, check)
        new = {k: v for k, v in (change.get("config") or {}).items() if k in cur}
        before = [[k, str(v)] for k, v in cur.items()]
        after = [[k, str(new.get(k, v))] for k, v in cur.items()]
        test = {"ok": bool(new), "text": f"{len(new)} known setting(s) of the {check} check change; unknown keys were dropped." if new else "No known setting of this check is in the change."}
    elif kind == "retry_policy":
        i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (change.get("integration") or sub.get("integration"),))
        if not i:
            return {"before": [], "after": [], "test": {"ok": False, "text": "The integration is no longer listed."}, "summary": "gone"}
        props = _j(i["properties"], {})
        try:
            attempts, wait = int(change.get("attempts") or 3), int(change.get("wait_s") or 300)
            ok = 1 <= attempts <= 10 and 10 <= wait <= 86400
        except (TypeError, ValueError):
            attempts, wait, ok = 0, 0, False
        before = [["retry policy", json.dumps(props.get("retry") or "none")]]
        after = [["retry policy", json.dumps({"attempts": attempts, "wait_s": wait})]]
        test = {"ok": ok, "text": "A policy of 1-10 attempts with 10 s to 24 h between them." if ok else "attempts must be 1-10 and wait_s 10-86400."}
    else:
        return {"before": [], "after": [], "test": {"ok": False, "text": f"The fix kind {kind!r} cannot be proven on a copy."}, "summary": "unknown kind"}
    (d / "fix" / "before.json").write_text(json.dumps(before, indent=1), encoding="utf-8")
    (d / "tests" / "result.json").write_text(json.dumps(test, indent=1), encoding="utf-8")
    return {"before": before, "after": after, "test": test, "summary": test.get("text") or ""}


def _prove_dashboard(case: dict, diag: dict) -> dict:
    """Copy the dashboard's definition (and its data) into fix/copy, let the agent make the edit there, re-check it."""
    sub = case["subject"] or {}
    pid, v = sub.get("project"), sub.get("version")
    src = store.ROOT / pid
    d = store.ROOT / case["id"]
    copy_dir = d / "fix" / "copy"
    shutil.rmtree(copy_dir, ignore_errors=True)
    (copy_dir / "data").mkdir(parents=True)
    defn = src / "versions" / f"v{v}" / "definition.yaml" if v else src / "definition.yaml"
    if not defn.exists():
        return {"before": [], "after": [], "test": {"ok": False, "text": "The version's definition.yaml is not there any more."}, "summary": "gone"}
    shutil.copy2(defn, copy_dir / "definition.yaml")
    total = 0
    for f in sorted((src / "data").glob("*")):
        if f.is_file() and not f.name.startswith("."):
            total += f.stat().st_size
            if total <= COPY_MAX_BYTES:
                shutil.copy2(f, copy_dir / "data" / f.name)
    st = store.load(pid)
    gates_before = [g for g in ((st.get("versions") or [{}])[-1].get("gates") or []) if g.get("status") == "fail"]
    before = [[g.get("name") or g.get("id"), (g.get("summary") or "fail")[:160]] for g in gates_before] or [["definition", "fails a review gate"]]
    (d / "fix" / "before.json").write_text(json.dumps(before, indent=1), encoding="utf-8")
    original = (copy_dir / "definition.yaml").read_text(encoding="utf-8")
    return {"before": before, "after": [], "test": {"ok": False, "text": "pending the agent's edit"}, "summary": "copy ready", "copy": str(copy_dir), "original": original, "gates": [g.get("name") or g.get("id") for g in gates_before]}


def _check_copy(case: dict, original: str) -> dict:
    d = store.ROOT / case["id"]
    copy_dir = d / "fix" / "copy"
    text = (copy_dir / "definition.yaml").read_text(encoding="utf-8")
    changed = text != original
    try:
        raw = definition.load(copy_dir / "definition.yaml")
        errors, dd = checks.definition_errors(raw, copy_dir, check_sql=False)
    except Exception as e:  # noqa: BLE001
        errors, dd = [f"definition.yaml does not parse: {str(e).splitlines()[0]}"], None
    diff = _yaml_diff(original, text)
    after = [["definition check", "OK" if not errors else f"{len(errors)} problem(s): " + "; ".join(errors[:3])[:200]], ["changed", "; ".join(diff[:6]) if diff else ("yes" if changed else "nothing changed")]]
    if dd:
        after.append(["model", f"{len(dd.get('tables') or [])} tables, {len(dd.get('measures') or [])} measures, {sum(len(p.get('visuals') or []) for p in dd.get('pages') or [])} visuals"])
    test = {"ok": changed and not errors, "text": ("The copy passes the definition check after the edit." if changed and not errors else "The agent did not change the copy." if not changed else "The copy still fails the definition check: " + "; ".join(errors[:3])), "diff": diff[:40]}
    (d / "tests" / "result.json").write_text(json.dumps(test, indent=1), encoding="utf-8")
    return {"after": after, "test": test, "summary": test["text"]}


def _yaml_diff(a: str, b: str) -> list[str]:
    try:
        ya, yb = yaml.safe_load(a) or {}, yaml.safe_load(b) or {}
    except Exception:  # noqa: BLE001
        return ["(the copy no longer parses as YAML)"]
    out = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y), key=str):
                if k not in x:
                    out.append(f"added {path}.{k}" if path else f"added {k}")
                elif k not in y:
                    out.append(f"removed {path}.{k}" if path else f"removed {k}")
                else:
                    walk(x[k], y[k], f"{path}.{k}" if path else str(k))
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                out.append(f"{path}: {len(x)} {len(y)} items")
            for i, (p, q) in enumerate(zip(x, y)):
                walk(p, q, f"{path}[{(p.get('name') or p.get('id') or i) if isinstance(p, dict) else i}]")
        elif x != y:
            out.append(f"{path}: {str(x)[:40]!r} {str(y)[:40]!r}")
    walk(ya, yb, "")
    return out


def proven(cid: str, proof: dict) -> dict:
    diag = _row(cid)["diagnosis"] or {}
    f = diag.get("fix") or {}
    fix = {"kind": f.get("kind"), "module": FIX_KINDS.get(f.get("kind"), {}).get("module") or f.get("module"), "text": f.get("text"), "change": f.get("change") or {}, "before": proof.get("before") or [], "after": proof.get("after") or [],
           "test": proof.get("test") or {}, "proven": time.time()}
    r = _row(cid)
    if (proof.get("test") or {}).get("recovered"):
        _set(cid, fix=fix)
        _close(cid, "recovered", (proof.get("test") or {}).get("text") or "Recovered.", "agent")
        worker.app_note(cid, "heal_fix", (proof.get("test") or {}).get("text") or "Recovered.", "ok")
        return _row(cid)
    if not (proof.get("test") or {}).get("ok"):
        _set(cid, status="held", step="prove", fix=fix, note=(proof.get("test") or {}).get("text") or "The test on the copy did not pass.")
        worker.app_note(cid, "heal_fix", "The test on the copy did not pass: " + ((proof.get("test") or {}).get("text") or ""), "warn")
        if r.get("owner_id") and db.user(r["owner_id"]):
            notify.add(r["owner_id"], "alert", f"Self-healing needs you: {r['title']}", (proof.get("test") or {}).get("text") or "", f"{ROUTE}/{cid}")
        db.audit("heal.held", cid, {"test": (proof.get("test") or {}).get("text", "")[:200]}, "agent")
        return _row(cid)
    _set(cid, status="proven", step="approve", fix=fix, note=None)
    rows = []
    keys = {}
    for k, v in fix["before"]:
        keys.setdefault(k, ["", ""])[0] = v
    for k, v in fix["after"]:
        keys.setdefault(k, ["", ""])[1] = v
    rows = [{"setting": k, "before": b, "after": a} for k, (b, a) in keys.items()]
    ev = {"summary": f"{fix['text']} - proven on a copy: {fix['test'].get('text', '')}", "items": [f"Applied through {fix['module']} only after you accept", f"Test: {fix['test'].get('text', '')}"] + [f"{x['setting']}: {x['before'] or '-'} {x['after'] or '-'}" for x in rows[:5]],
          "counts": {"settings": len(rows), "test": "pass"}, "columns": ["setting", "before", "after"], "rows": rows, "fix": fix, "case": {"id": cid, "title": r["title"], "place": r["place"]}}
    cp = checkpoints.open(KIND_APPLY, cid, MODULE, f"Approve & apply: {r['title']}", "table", ev, link=f"{ROUTE}/{cid}", assignee=r.get("owner_id") if r.get("owner_id") and db.user(r["owner_id"]) else None, agent="Relay", opened_by="agent")
    _set(cid, checkpoint_id=cp["id"])
    worker.app_note(cid, "heal_fix", f"Proven on a copy: {fix['test'].get('text', '')} Waiting for your approval to apply it through {fix['module']}.", "ok")
    db.audit("heal.proven", cid, {"fix": fix["kind"], "test": fix["test"].get("text", "")[:200]}, "agent")
    return _row(cid)


async def _fix_job(pid: str, args: dict) -> None:
    case = _row(pid)
    diag = case["diagnosis"] or {}
    _set(pid, status="fixing", step="fix")
    f = diag.get("fix") or {}
    worker.app_note(pid, "heal_fix", f"Relay is applying the fix on a copy: {f.get('text') or f.get('kind')}")
    try:
        proof = await asyncio.to_thread(_prove, case, diag)
        if f.get("kind") == "dashboard_revise" and proof.get("copy"):
            res = await worker.agent(pid, "heal_fix", heal_prompts.copy_fix(diag, proof.get("gates") or []), worker.TURNS["heal_fix"], "fix", system=heal_prompts.SYSTEM)
            proof = {**proof, **(await asyncio.to_thread(_check_copy, case, proof["original"])), "agent": (res.get("text") or "")[:300]}
            for _ in range(worker.FIX_ROUNDS):
                if proof["test"].get("ok"):
                    break
                worker.app_note(pid, "heal_fix", "The copy does not pass yet - Relay is fixing it: " + proof["test"].get("text", ""), "warn")
                res = await worker.agent(pid, "heal_fix", heal_prompts.fix([proof["test"]["text"]]), worker.TURNS["fix"], "fix", resume=res.get("session_id"), system=heal_prompts.SYSTEM)
                proof = {**proof, **(await asyncio.to_thread(_check_copy, case, proof["original"]))}
        _set(pid, diagnosis=diag)                   # the proof may have resolved placeholders in the change (e.g. which email account)
        proven(pid, proof)
        store.update(pid, status=_row(pid)["status"], job=None, error=None)
    except Exception as e:
        _set(pid, status="error", step="fix", note=str(e)[:300])
        raise


worker.register_job("heal_fix", _fix_job, status="fixing", done="Fix proven on a copy - approve it to apply", llm=True, turns=60, timeout_s=1800)


# ------------------------------------------------------------------ approve & apply (through the owning module), learn

def _mark_work(case: dict, status: str, who: str, link: str | None = None) -> None:
    w = case.get("work") or {}
    if not w:
        return
    try:
        if w["table"] == "intan_work":
            db.run("UPDATE intan_work SET status = ? WHERE id = ?", (status, w["id"]))
        elif w["table"] == "observe_work":
            db.run("UPDATE observe_work SET status = ?, note = COALESCE(?, note) WHERE id = ?", (status, f"Self-healing case {case['id']}: {status}", w["id"]))
        elif w["table"] == "itsm_work":
            db.run("UPDATE itsm_work SET status = ?, link = COALESCE(?, link), note = COALESCE(note, '') || ? WHERE id = ?", (status, link, f" Self-healing case {case['id']}: {status}.", w["id"]))
        db.audit("heal.work", w["id"], {"table": w["table"], "status": status, "case": case["id"]}, who)
    except Exception:  # noqa: BLE001 - the source row is a courtesy; the case is the record
        traceback.print_exc()


def _apply(case: dict, who: str) -> dict:
    fix, sub = case["fix"] or {}, case["subject"] or {}
    kind, change = fix.get("kind"), fix.get("change") or {}
    res: dict = {"kind": kind, "module": fix.get("module"), "who": who, "when": time.time()}
    if kind == "rerun_extract":
        pid = sub["project"]
        d = store.project_dir(pid)
        try:
            done = connectors.refresh_project(d, who, only_owner=False)      # the same path as the dashboard's own "refresh" button and its daily refresh
        except connectors.Reconsent as e:
            raise HTTPException(409, f"The sign-in expired while re-running: {e}") from e
        except connectors.ConnectorError as e:
            raise HTTPException(409, str(e)) from e
        worker.refresh_files(pid)
        worker.app_note(pid, "extract", f"Self-healing case {case['id']}: {len(done)} warehouse table(s) pulled again.", "ok")
        res["result"] = f"{len(done)} table(s) pulled again through the dashboard's extract refresh: " + ", ".join(f"{e['object']} {e['rows']:,} rows" for e in done)
    elif kind == "renew_connection":
        c = connectors._row(sub["connection"])
        r = connectors.renew(c["id"], c["owner_id"])
        notify.add(c["owner_id"], "alert", f"Sign in again: {c['name']}", f"Self-healing confirmed the stored sign-in no longer works. Renew it under Connections; what paused on it resumes afterwards. (Case {case['id']})", "#/connections")
        res["result"] = f"{c['name']} is marked for renewal ({r.get('status')}); its owner was told."
    elif kind == "notify_hold":
        admins = [u["id"] for u in db.q("SELECT id FROM users WHERE org_role = 'admin' AND active = 1")]
        notify.add_many(admins, "alert", "DAX checker is offline", f"Start daxcheck\\start-daxcheck.cmd on the Windows PC. Publishing is held until the heartbeat is back. (Self-healing case {case['id']})", "#/admin/monitoring")
        res["result"] = f"{len(admins)} admin(s) told; publishing stays blocked by the checker itself until it is back."
    elif kind == "dashboard_revise":
        pid = sub["project"]
        st = store.load(pid)
        if st["status"] not in ("awaiting_review", "done", "error") or not st.get("versions"):
            raise HTTPException(409, f"The dashboard cannot take a change request right now (status {st['status']}).")
        diff = (fix.get("test") or {}).get("diff") or []
        text = (f"Self-healing case {case['id']} - {case['title']}. Apply the change proven on a copy: {fix.get('text')}. "
                f"Edited keys on the copy: {'; '.join(diff[:12]) or 'see fix/copy/definition.yaml in the case folder'}. Make the same edit here so the '{sub.get('gate')}' gate passes; change nothing else.")
        store.note(pid, "Change request from Self-healing", text)
        store.log(pid, {"kind": "user", "stage": "revise", "text": text})
        st2 = worker.enqueue(pid, "revise", feedback=text, attachments=[])
        res["result"] = f"A change request was queued on the dashboard through its revise path (job {(st2.get('job') or {}).get('id')})."
    elif kind == "rerun_integration":
        i = db.one("SELECT * FROM intan_integrations WHERE id = ?", (sub["integration"],))
        if sub.get("connection"):
            c = connectors._row(sub["connection"])
            cp = connectors.request_write(c, i["ext_id"], {"action": change.get("action") or "rerun", "integration": i["name"], "reason": f"Self-healing case {case['id']}: {case['what'][:120]}"}, who, module=MODULE, what=f"Re-run {i['name']} on {c['name']}")
            res["write_checkpoint"] = cp["id"]
            res["result"] = f"A guarded write was requested on {c['name']} (checkpoint {cp['id']}); the platform is written only when that is accepted."
        else:
            devs = [u["id"] for u in db.q("SELECT DISTINCT u.id FROM users u JOIN memberships m ON m.user_id = u.id WHERE m.role = 'dev' AND u.active = 1")]
            notify.add_many(devs or [db.ADMIN_ID], "alert", f"Re-run needed: {i['name']}", f"The last run failed on a transient error ({(case.get('what') or '')[:160]}). Owner: {i.get('owner') or 'not named'}. (Self-healing case {case['id']})", f"#/integrations?open={i['id']}")
            res["result"] = f"{len(devs) or 1} person(s) told to re-run {i['name']}: no write-capable connection exists for its platform."
    elif kind == "schedule_update":
        s = schedules._row(sub["schedule"])
        u = db.user(s["owner_id"]) or {"id": s["owner_id"]}
        body = _schedule_body(s, change)
        try:
            out = schedules.save(u, body, s["id"])
        except schedules.ScheduleError as e:
            raise HTTPException(409, f"Schedules refused the change: {e}") from e
        res["result"] = f"Schedule '{out['name']}' saved through Schedules and resumed (next run {_when(out.get('next_run'))})."
    elif kind == "threshold":
        from . import observe
        aid, check = change.get("asset") or sub.get("asset"), change.get("check") or sub.get("check")
        observe.set_asset_checks(aid, {"checks": {check: {"config": change.get("config") or {}}}}, db.user(who) or {"id": who})
        res["result"] = f"The {check} threshold on {aid} was saved through Data observability."
    elif kind == "retry_policy":
        iid = change.get("integration") or sub.get("integration")
        i = db.one("SELECT properties FROM intan_integrations WHERE id = ?", (iid,))
        props = _j(i["properties"], {}) if i else {}
        props["retry"] = {"attempts": int(change.get("attempts") or 3), "wait_s": int(change.get("wait_s") or 300), "set_by": who, "case": case["id"]}
        db.run("UPDATE intan_integrations SET properties = ? WHERE id = ?", (json.dumps(props), iid))
        res["result"] = f"Retry policy recorded on the integration row ({props['retry']['attempts']} attempts, {props['retry']['wait_s']} s)."
    else:
        raise HTTPException(409, f"The fix kind {kind!r} cannot be applied.")
    return res


def needs_code(cid: str, who: str) -> dict:
    r = _row(cid)
    diag = r["diagnosis"] or {}
    applied = {"kind": "needs_code", "who": who, "when": time.time()}
    try:
        from . import sdlc
        req = sdlc.request_from_heal(r, who)
        applied["sdlc"] = {"id": req["id"], "link": f"#/sdlc/{req['id']}"}
        applied["result"] = f"AI SDLC change request {req['id']} opened from this case."
    except ImportError:
        applied["result"] = "AI SDLC is not available here; the diagnosis is kept for a developer."
    except Exception as e:  # noqa: BLE001
        applied["result"] = f"AI SDLC could not open a request: {str(e)[:200]}"
    _set(cid, status="needs_code", step="fix", applied=applied, note=(diag.get("fix") or {}).get("text"))
    _mark_work(r, "handed", who, applied.get("sdlc", {}).get("link"))
    db.audit("heal.needs_code", cid, applied, who)
    worker.app_note(cid, "heal", applied["result"], "ok")
    return _row(cid)


def _on_diag_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    cid = c["subject"]
    try:
        r = _row(cid)
    except HTTPException:
        return
    if decision != "accept":
        _set(cid, status="sent_back", step="diagnose", note=(comment or "")[:500], checkpoint_id=None)
        store.note(cid, "Sent back", comment or "")
        db.audit("heal.diagnosis.sent_back", cid, {"comment": (comment or "")[:300]}, who)
        try:
            worker.enqueue(cid, "heal_diagnose", correction=comment)
            _set(cid, status="diagnosing")
        except Exception as e:  # noqa: BLE001
            _set(cid, note=f"Sent back; a new diagnosis could not start: {str(e)[:200]}")
        return
    db.audit("heal.diagnosis.accepted", cid, {"fix": ((r["diagnosis"] or {}).get("fix") or {}).get("kind"), "comment": (comment or "")[:200]}, who)
    if ((r["diagnosis"] or {}).get("fix") or {}).get("kind") == "needs_code":
        needs_code(cid, who)
        return
    try:
        worker.enqueue(cid, "heal_fix")
        _set(cid, status="fixing", step="fix", checkpoint_id=None)
    except Exception as e:  # noqa: BLE001
        _set(cid, status="held", note=f"The fix on a copy could not start: {str(e)[:200]}")


def _on_apply_decision(c: dict, decision: str, comment: str | None, who: str) -> None:
    cid = c["subject"]
    try:
        r = _row(cid)
    except HTTPException:
        return
    if decision != "accept":
        _set(cid, status="sent_back", step="diagnose", note=(comment or "")[:500], checkpoint_id=None)
        db.audit("heal.apply.sent_back", cid, {"comment": (comment or "")[:300]}, who)
        store.note(cid, "Apply refused", comment or "")
        return
    db.audit("heal.apply.accepted", cid, {"fix": (r["fix"] or {}).get("kind"), "comment": (comment or "")[:200]}, who)
    try:                                   # the apply runs in the lane (an extract can take minutes); the decision is already signed
        worker.enqueue(cid, "heal_apply", who=who)
        _set(cid, status="applying", step="approve", checkpoint_id=None, note=None)
    except Exception as e:  # noqa: BLE001
        _set(cid, status="held", step="prove", note=f"Not applied: {str(e)[:300]}", checkpoint_id=None)


def _after_apply(cid: str, who: str, res: dict) -> None:
    r = _row(cid)
    status = "applying" if res.get("write_checkpoint") else "applied"
    _set(cid, status=status, step="approve" if status == "applying" else "learn", applied=res, note=None)
    rule = learn(r, who)
    _mark_work(r, "done" if status == "applied" else "applying", who, f"{ROUTE}/{cid}")
    store.note(cid, "Applied", f"{res.get('result')}\n\nRule: {rule['title']} ({rule['origin']}, applied {rule['applied']} time(s)).")
    worker.app_note(cid, "heal_apply", f"Applied through {res.get('module')}: {res.get('result')} Rule kept: {rule['title']}.", "ok")
    db.audit("heal.applied", cid, {"kind": res.get("kind"), "module": res.get("module"), "result": (res.get("result") or "")[:300], "rule": rule["id"]}, who)
    if r.get("owner_id") and db.user(r["owner_id"]) and r["owner_id"] != who:
        notify.add(r["owner_id"], "build", f"Fixed: {r['title']}", (res.get("result") or "")[:300], f"{ROUTE}/{cid}")


async def _apply_job(pid: str, args: dict) -> None:
    r = _row(pid)
    who = args.get("who") or r.get("owner_id") or db.ADMIN_ID
    worker.app_note(pid, "heal_apply", f"Applying the approved fix through {(r['fix'] or {}).get('module') or 'its module'}...")
    try:
        res = await asyncio.to_thread(_apply, r, who)
    except HTTPException as e:
        _set(pid, status="held", step="prove", note=f"Not applied: {e.detail}")
        db.audit("heal.apply.failed", pid, {"error": str(e.detail)[:300]}, who)
        notify.add(who, "alert", f"The approved fix did not go through: {r['title']}", str(e.detail)[:300], f"{ROUTE}/{pid}")
        store.update(pid, status="held", job=None, error=None)
        worker.app_note(pid, "heal_apply", f"Not applied: {e.detail}", "error")
        return
    except Exception as e:  # noqa: BLE001
        _set(pid, status="held", step="prove", note=f"Not applied: {str(e)[:300]}")
        db.audit("heal.apply.failed", pid, {"error": str(e)[:300]}, who)
        notify.add(who, "alert", f"The approved fix did not go through: {r['title']}", str(e)[:300], f"{ROUTE}/{pid}")
        raise
    _after_apply(pid, who, res)
    store.update(pid, status=_row(pid)["status"], job=None, error=None)


worker.register_job("heal_apply", _apply_job, status="applying", done="Fix applied")
checkpoints.register_kind(KIND_DIAG, "Self-healing fix", _on_diag_decision)
checkpoints.register_kind(KIND_APPLY, "Self-healing apply", _on_apply_decision)


# ------------------------------------------------------------------ summaries, scheduler, API

def summary() -> dict:
    rows = db.q("SELECT * FROM heal_cases")
    now = time.time()
    open_rows = [r for r in rows if r["status"] in OPEN]
    done = [r for r in rows if r["status"] in ("applied", "closed") and r.get("applied")]
    fixed_30 = [r for r in done if (_j(r["applied"], {}).get("when") or 0) >= now - 30 * 86400]
    secs = [(_j(r["applied"], {}).get("when") or r["updated"]) - (r["since"] or r["created"]) for r in done]
    secs = [s for s in secs if s is not None and s >= 0]
    rl = db.q("SELECT origin, COUNT(*) AS n, SUM(seen) AS seen, SUM(applied) AS applied FROM heal_rules WHERE enabled = 1 GROUP BY origin")
    return {"open": len(open_rows), "waiting_for_you": sum(1 for r in open_rows if r["status"] in ("diagnosed", "proven", "held")), "fixed_30d": len(fixed_30),
            "recovered": sum(1 for r in rows if r["status"] == "recovered"), "needs_code": sum(1 for r in rows if r["status"] == "needs_code"),
            "median_fix_h": round(statistics.median(secs) / 3600, 1) if secs else None,
            "rules": {r["origin"]: {"n": r["n"], "seen": r["seen"] or 0, "applied": r["applied"] or 0} for r in rl},
            "rules_total": sum(r["n"] for r in rl), "by_step": {s: sum(1 for r in open_rows if STEP_OF.get(r["status"]) == s) for s in STEPS},
            "hint": "Nothing to heal right now" if not open_rows else None}


async def _loop() -> None:
    while True:
        await asyncio.sleep(WATCH_EVERY_S)              # started at boot (main.py): the first pass one interval later
        try:
            for _t in db.each_tenant("heal"):           # P17: every tenant that has Self-healing switched on
                await asyncio.to_thread(watch, None)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()


_sched_tasks: dict[int, asyncio.Task] = {}             # one watcher per event loop (the app's; a test's)


def ensure_scheduler() -> bool:
    """Start the watcher once on the app's loop. The app starts it at boot (consolidation: before, it started only from
    a request on the event loop, so after a restart it did not run by itself); a request still makes sure it runs,
    from the loop or from the thread pool. It starts in a fresh context, never a request's tenant or person."""
    global _sched_task
    try:
        loop, here = asyncio.get_running_loop(), True
    except RuntimeError:
        loop, here = worker._loop, False
    if loop is None or loop.is_closed():
        return False
    t = _sched_tasks.get(id(loop))
    if t is not None and not t.done():
        return False

    def start() -> None:
        global _sched_task
        have = _sched_tasks.get(id(loop))
        if have is None or have.done():
            _sched_task = _sched_tasks[id(loop)] = loop.create_task(_loop(), context=contextvars.Context())
    if here:
        start()
    else:
        loop.call_soon_threadsafe(start)
    return True


def stop_scheduler() -> None:
    global _sched_task
    for t in _sched_tasks.values():
        t.cancel()
    _sched_tasks.clear()
    _sched_task = None


class CaseIn(BaseModel):
    title: str
    what: str | None = None
    place: str | None = None
    route: str | None = None
    project: str | None = None


class Comment(BaseModel):
    comment: str | None = None


class Enable(BaseModel):
    enabled: bool


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


def cases(status: str = "open", limit: int = 300) -> list[dict]:
    if status == "open":
        rows = db.q(f"SELECT * FROM heal_cases WHERE status IN ({','.join('?' * len(OPEN))}) ORDER BY updated DESC LIMIT ?", (*OPEN, limit))
    elif status == "all":
        rows = db.q("SELECT * FROM heal_cases ORDER BY updated DESC LIMIT ?", (limit,))
    else:
        rows = db.q("SELECT * FROM heal_cases WHERE status = ? ORDER BY updated DESC LIMIT ?", (status, limit))
    out = []
    for r in rows:
        for k in ("subject", "diagnosis", "fix", "applied", "work"):
            r[k] = _j(r[k], {} if k != "work" else None)
        out.append(public(r))
    return out


@router.get("/api/heal/overview")
def api_overview(status: str = "open"):
    u = _u()
    ensure_builtin()
    return {"summary": summary(), "cases": cases(status), "rules": rules(), "can_edit": auth.is_dev(u), "test_hooks": TEST_HOOKS, "steps": [[s, STEP_LABEL[s]] for s in STEPS],
            "fix_kinds": {k: v["what"] for k, v in FIX_KINDS.items()}, "worker": {"running": worker.current.get("pid"), "kind": worker.current.get("kind"), "waiting": worker.waiting()}}


@router.get("/api/heal/summary")
def api_summary():
    _u()
    return summary()


@router.get("/api/heal/cases/{cid}")
def api_case(cid: str):
    _u()
    return public(_row(cid), with_detail=True)


@router.get("/api/heal/cases/{cid}/file/{name}")
def api_case_file(cid: str, name: str):
    _u()
    _row(cid)
    d = store.ROOT / cid
    p = (d / "evidence" / name) if name != "diagnosis.yaml" else d / name
    if not re.match(r"^[\w.-]+$", name) or not p.exists() or not p.is_file():
        raise HTTPException(404, "No such file.")
    return {"name": name, "text": p.read_text(encoding="utf-8", errors="replace")[:200000]}


@router.post("/api/heal/watch")
def api_watch():
    u = _builder()
    r = watch(u["id"])
    db.audit("heal.watch", None, r, u["id"])
    return r


@router.post("/api/heal/cases")
def api_new_case(body: CaseIn):
    u = _builder()
    ensure_builtin()
    title = " ".join((body.title or "").split())[:200]
    if len(title) < 4:
        raise HTTPException(400, "Say what failed, in a few words.")
    sub = {"project": body.project} if body.project else {}
    if body.project and not db.project(body.project):
        raise HTTPException(404, "No such dashboard.")
    c = open_case({"signature": f"manual:{_slug(title)}", "kind": "generic", "source": "person", "source_id": "p-" + _secrets.token_hex(3), "title": title, "what": body.what or title, "place": body.place or "", "since": time.time(),
                   "route": body.route if body.route in ("config", "code") else "config", "owner_id": u["id"], "subject": sub}, u["id"])
    return public(c, with_detail=True)


@router.post("/api/heal/cases/{cid}/diagnose")
def api_diagnose(cid: str, body: Comment | None = None):
    u = _builder()
    r = _row(cid)
    if r["status"] in ("diagnosing", "fixing"):
        raise HTTPException(409, "A run is already going on this case.")
    if r["closed"]:
        raise HTTPException(409, "This case is closed.")
    checkpoints.withdraw(KIND_DIAG, cid, who=u["id"])
    checkpoints.withdraw(KIND_APPLY, cid, who=u["id"])
    note = (body.comment if body else None) or None
    if note:
        store.note(cid, "Note for the diagnosis", note)
    st = worker.enqueue(cid, "heal_diagnose", correction=note)
    _set(cid, status="diagnosing", step="diagnose", checkpoint_id=None)
    db.audit("heal.diagnose.requested", cid, {"note": (note or "")[:200]}, u["id"])
    return {"queued": True, "job": st.get("job"), "case": public(_row(cid), with_detail=True)}


@router.post("/api/heal/cases/{cid}/close")
def api_close(cid: str, body: Comment):
    u = _builder()
    r = _row(cid)
    if r["closed"]:
        raise HTTPException(409, "Already closed.")
    if not (body.comment or "").strip():
        raise HTTPException(400, "Say why the case closes.")
    _close(cid, "closed", body.comment.strip()[:500], u["id"])
    _mark_work(r, "closed", u["id"])
    return public(_row(cid), with_detail=True)


@router.get("/api/heal/rules")
def api_rules():
    _u()
    ensure_builtin()
    return {"items": rules()}


@router.post("/api/heal/rules/{rid}/enable")
def api_rule_enable(rid: str, body: Enable):
    u = _builder()
    return set_rule(rid, body.enabled, u["id"])


@router.post("/api/heal/test/seed")
def api_test_seed():
    """Tests only (D2D_TEST_HOOKS=1): a paused schedule (missing mail account) on a sample dashboard, a connection whose
    sign-in expired, and a failed integration run - then one watch pass."""
    if not TEST_HOOKS:
        raise HTTPException(404, "Not found")
    u = _builder()
    return seed_sample(u["id"])


def seed_sample(who: str, pid: str = "heal-sample-board") -> dict:
    now = time.time()
    d = store.ROOT / pid
    if not (d / "project.json").exists():
        (d / "data").mkdir(parents=True, exist_ok=True); (d / "versions" / "v1").mkdir(parents=True, exist_ok=True)
        (d / "data" / "sales.csv").write_text("id,sale_date,amount\n1,2026-10-01,120\n2,2026-10-02,80\n", encoding="utf-8")
        (d / "versions" / "v1" / "definition.yaml").write_text("name: Sales board sample\ntables:\n- name: Sales\n  csv: sales.csv\n  columns:\n  - {name: Id, source: id, type: int}\n  - {name: Date, source: sale_date, type: date}\n  - {name: Amount, source: amount, type: number}\nmeasures:\n- name: Net Sales\n  expression: SUM ( Sales[Amount] )\npages:\n- name: Overview\n  rows:\n  - visuals:\n    - {id: k1, type: kpiCard, fields: {value: '[Net Sales]'}}\n", encoding="utf-8")
        store.save({"id": pid, "name": "Sales board sample", "prompt": "sample dashboard for self-healing", "status": "done", "created": now - 5 * 86400, "versions": [{"v": 1, "pages": ["Overview"], "visuals": 1,
                    "gates": [{"id": "definition", "name": "Report definition", "status": "pass", "summary": "ok"}, {"id": "report_rules", "name": "Report & accessibility", "status": "fail", "summary": "Overview: KPI k1 has no alt text - screen readers announce only its type"}]}],
                    "runs": [], "job": None, "error": None, "approved": 1, "output": {"pbip": "Sales board sample.pbip"}, "files": [{"name": "sales.csv", "bytes": 60}], "images": []})
        db.add_project(pid, who)
    sid = "sc-heal-sample"
    if not db.one("SELECT 1 FROM schedules WHERE id = ?", (sid,)):
        db.run("INSERT INTO schedules (id, owner_id, kind, name, target, cadence, tz, email_account_id, recipients, status, paused_reason, next_run, state, created, updated) VALUES (?, ?, 'report', 'Sales board - Monday 08:00', ?, ?, 'UTC', 'ea-gone', ?, 'paused', ?, ?, '{}', ?, ?)",
               (sid, who, json.dumps({"type": "dashboard", "project": pid}), json.dumps({"freq": "weekly", "time": "08:00", "weekday": 0}), json.dumps([who]), "Email: its email account was removed.", now + 86400, now - 3600, now - 3600))
    cid = "conn-heal-sample"
    if not db.one("SELECT 1 FROM connections WHERE id = ?", (cid,)):
        db.run("INSERT INTO connections (id, owner_id, kind, name, config, auth_mode, status, error, created, last_used) VALUES (?, ?, 'mock', 'Finance warehouse (sample)', '{}', 'api_key', 'reconsent', 'Sign in again: the stored token was refused (401).', ?, ?)", (cid, who, now - 86400, now - 7200))
    r = watch(who)
    db.audit("heal.sample", pid, r, who)
    return {"project": pid, "schedule": sid, "connection": cid, **r, "cases": {c["signature"]: c["id"] for c in cases("open")}}
