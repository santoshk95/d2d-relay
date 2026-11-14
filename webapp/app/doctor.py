"""Relay Doctor's side in the app. The Doctor itself (doctor/doctor.py) runs on the Windows PC next to Docker: a broken
app cannot fix itself, and the app's container has, on purpose, no Docker access and no source code. The two talk
through files in a shared folder, `<projects>/.doctor/`, so the channel still works when the database or the app is
the thing that is broken:

- app.json      written by the app every EVERY_S seconds: the job running now, the queue, the agent's lanes, whether
                new jobs are held, the bugs this process has seen (errors.recent) and the commit it was built from.
- state.json    written by the Doctor on every pass: its heartbeat, mode, incidents with their steps, recent actions.
- hold.json     written by the Doctor: while it exists (and the Doctor's heartbeat is fresh) the worker starts no new
                job - queued work waits, nothing is lost. The Doctor holds while it restarts the app, and while its own
                AI fix runs (one AI run at a time).
- control.json  written by the app when an Admin acts on Admin > Operations > Relay Doctor: pause / resume, the mode
                (auto: fix and deploy by itself; approve: deploy after one click; watch: report only), approve a fix
                that is ready, retry, mute or close an incident.

New incidents, fixes put live, roll-backs and incidents that need a person notify every Admin (and the ops webhook).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets as _secrets
import time
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import db, errors, notify, store

router = APIRouter()
DIR = Path(os.environ.get("RELAY_DOCTOR_DIR") or store.BASE / ".doctor")
EVERY_S = int(os.environ.get("RELAY_DOCTOR_EVERY_S", "10"))
FRESH_S = 180                     # a Doctor heartbeat older than this: offline, and its hold no longer counts
HOLD_MAX_S = 3 * 3600             # whatever hold.json says, the app never waits longer than this
OFFLINE_MIN = 10                  # monitor rule doctor_offline
COMMIT = os.environ.get("RELAY_COMMIT") or None
STARTED = time.time()
MODES = ("auto", "approve", "watch")
ACTIONS = ("pause", "resume", "mode", "approve", "retry", "mute", "unmute", "close")
INCIDENT_ID = re.compile(r"^inc-[0-9a-z-]{6,64}$")
FILES = {"evidence": "evidence.txt", "ai": "ai.log", "diff": "fix.diff", "tests": "tests.log", "deploy": "deploy.log"}
OPEN = ("new", "fixing", "proving", "ready", "deploying", "verifying")
TELL = {"needs_person": "Relay Doctor needs a person", "rolled_back": "Relay Doctor rolled a fix back", "ready": "A fix is ready to deploy"}


# ---------------------------------------------------------------- the shared folder

def _read(name: str) -> dict | None:
    try:
        return json.loads((DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(name: str, obj: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DIR / f".{name}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, default=str)
    os.replace(tmp, DIR / name)


def state() -> dict:
    s = _read("state.json") or {}
    s["online"] = time.time() - float(s.get("time") or 0) < FRESH_S
    return s


def holding() -> dict | None:
    """The Doctor's hold on new jobs, while it counts: the Doctor is alive and the hold is not too old."""
    h = _read("hold.json")
    if not h:
        return None
    now = time.time()
    if now - float((_read("state.json") or {}).get("time") or 0) > FRESH_S or now - float(h.get("since") or 0) > HOLD_MAX_S:
        return None
    return h


async def _app_state() -> dict:
    from . import monitor, worker                          # late: worker imports this module
    now = time.time()
    jobs = worker.all_running()                            # every tenant's (item 46: up to worker.PARALLEL at once)
    oldest = jobs[0] if jobs else None
    running = {"kind": oldest["kind"], "pid": oldest["pid"], "tenant": oldest["tenant"],
               "age_s": round(now - oldest["started"])} if oldest else None
    agent = await monitor._agent()                         # noqa: SLF001
    return {"time": now, "instance": db.INSTANCE, "commit": COMMIT, "started": STARTED, "process": os.getpid(),
            "running": running, "jobs_running": len(jobs), "queue": worker.waiting(),
            "agent": {"ok": bool(agent.get("ok")), "lanes": agent.get("lanes") or {}},
            "holding": bool(holding()), "errors": errors.recent(30)}


# ---------------------------------------------------------------- telling Admins

def _notify_changes(s: dict) -> int:
    """One notification per incident step worth knowing (new, fixed, rolled back, needs a person, ready to approve)."""
    from . import monitor
    seen = json.loads(db.meta("doctor_seen") or "{}")
    sent = 0
    for inc in s.get("incidents") or []:
        iid, st = inc.get("id"), inc.get("status")
        if not iid or seen.get(iid) == st:
            continue
        first = iid not in seen
        title = None
        if first and st in OPEN:
            title = "Relay Doctor found a problem"
        elif st == "closed" and inc.get("outcome") == "fixed":
            title = "Fixed by Relay Doctor"
        elif st in TELL and (st != "ready" or s.get("mode") == "approve"):
            title = TELL[st]
        seen[iid] = st
        if not title:
            continue
        body = f"{inc.get('title') or 'A crash in Relay'} - {inc.get('step') or st}"
        notify.add_many(monitor._admins(), "ops", f"{title}: {(inc.get('title') or '')[:90]}", body, "#/admin/doctor")   # noqa: SLF001
        monitor._webhook(f"Relay ({db.INSTANCE}) {title}: {body}")                                                     # noqa: SLF001
        sent += 1
    if len(seen) > 400:
        seen = dict(list(seen.items())[-300:])
    db.set_meta("doctor_seen", json.dumps(seen))
    return sent


async def loop() -> None:
    """Every EVERY_S seconds: app.json for the Doctor; every 30 s: notifications for what the Doctor did."""
    last = 0.0
    while True:
        try:
            _write("app.json", await _app_state())
            if time.time() - last >= 30:
                last = time.time()
                s = _read("state.json")
                if s:
                    _notify_changes(s)
        except Exception:  # noqa: BLE001 - this loop must keep going
            traceback.print_exc()
        await asyncio.sleep(EVERY_S)


def rules(now: float) -> dict[str, dict]:
    """Monitor rules (monitor.rules): the Doctor stopped, or incidents it could not fix by itself."""
    s = _read("state.json")
    if not s:
        return {}                                          # never installed on this PC: nothing to say
    found = {}
    age = now - float(s.get("time") or 0)
    if age > OFFLINE_MIN * 60 and not s.get("stopped_on_purpose"):
        found["doctor_offline"] = {"severity": "warning", "text": f"Relay Doctor on the Windows PC has not checked in for {round(age / 60)} min: "
                                   "crashes are not being fixed (start doctor\\start-doctor.cmd)."}
    waiting = [i for i in s.get("incidents") or [] if i.get("status") in ("needs_person", "rolled_back")]
    if waiting:
        found["doctor_needs_person"] = {"severity": "warning", "text": f"{len(waiting)} problem(s) Relay Doctor could not fix by itself need a person "
                                        "(Admin > Operations > Relay Doctor)."}
    return found


def brief() -> dict:
    """For Admin > Monitoring's tile."""
    s = state()
    inc = s.get("incidents") or []
    return {"installed": bool(s.get("time")), "online": s["online"], "mode": s.get("mode"), "paused": bool(s.get("paused")),
            "open": sum(i.get("status") in OPEN for i in inc), "needs_person": sum(i.get("status") in ("needs_person", "rolled_back") for i in inc)}


# ---------------------------------------------------------------- Admin > Operations > Relay Doctor

class Control(BaseModel):
    action: str
    incident: str | None = None
    mode: str | None = None
    note: str | None = None


@router.get("/api/admin/doctor")
def api_doctor():
    s = state()
    return {"installed": bool(s.get("time")), "online": s["online"] and not s.get("stopped_on_purpose"), "stopped": bool(s.get("stopped_on_purpose")),
            "time": s.get("time"), "mode": s.get("mode"),
            "paused": bool(s.get("paused")), "version": s.get("version"), "busy": s.get("busy"), "limits": s.get("limits") or {},
            "incidents": s.get("incidents") or [], "actions": s.get("actions") or [], "live": s.get("live") or {},
            "holding": holding(), "control": {k: v for k, v in (_read("control.json") or {}).items() if k != "requests"},
            "app": {"commit": COMMIT, "started": STARTED, "errors": errors.recent(20)}}


@router.post("/api/admin/doctor/control")
def api_control(body: Control):
    from . import auth
    if body.action not in ACTIONS:
        raise HTTPException(400, f"Choose one of: {', '.join(ACTIONS)}.")
    if body.action == "mode" and body.mode not in MODES:
        raise HTTPException(400, f"Mode is one of: {', '.join(MODES)}.")
    if body.action not in ("pause", "resume", "mode"):
        if not body.incident or not INCIDENT_ID.match(body.incident):
            raise HTTPException(400, "Say which incident.")
        if body.incident not in {i.get("id") for i in state().get("incidents") or []}:
            raise HTTPException(404, "Relay Doctor does not know this incident.")
    c = _read("control.json") or {}
    req = {"id": _secrets.token_hex(6), "action": body.action, "incident": body.incident, "mode": body.mode,
           "note": (body.note or "")[:500] or None, "by": auth.who(), "time": time.time()}
    c["requests"] = (c.get("requests") or [])[-49:] + [req]
    if body.action in ("pause", "resume"):
        c["paused"] = body.action == "pause"
    if body.action == "mode":
        c["mode"] = body.mode
    c["updated"] = req["time"]
    _write("control.json", c)
    db.audit("doctor.control", body.incident or body.action, {k: v for k, v in req.items() if k not in ("id", "by", "time")}, auth.who())
    return api_doctor()


@router.get("/api/admin/doctor/incidents/{iid}/{name}", response_class=PlainTextResponse)
def api_incident_file(iid: str, name: str):
    if not INCIDENT_ID.match(iid) or name not in FILES:
        raise HTTPException(404, "Not found")
    f = DIR / "incidents" / iid / FILES[name]
    try:
        data = f.read_bytes()
    except OSError:
        raise HTTPException(404, "Relay Doctor has not written this yet.") from None
    return data[-300_000:].decode("utf-8", errors="replace")
