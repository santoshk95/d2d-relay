"""Blue Prism — the Blue Prism API (v7): processes, sessions (runs with status and exception message — an
"Element not found" exception is a screen change), schedules. The process description may carry "<from> → <to>"
and "owner:"."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "blueprism", "Blue Prism", "RPA"
AUTH = "Authentication Server client (bearer token)"
DOCS = "Blue Prism API v7: /processes, /sessions, /schedules"
CONFIG = [{"name": "url", "label": "API base URL", "hint": "https://blueprism.example.com/api/v7", "required": True}]
SECRETS = [{"name": "token", "label": "Bearer token"}]
STATUS = {"Completed": "success", "Terminated": "failed", "Stopped": "skipped", "Failed": "failed", "Running": "running", "Pending": "running", "Warning": "success"}


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.bearer(secrets.get("token") or ""))
    out = base.empty()
    sched = {}
    try:
        for s in (c.get("/schedules").get("items") or []):
            for t in s.get("tasks") or [{"processName": s.get("processName")}]:
                sched[t.get("processName")] = s.get("description") or ("Daily " + s["startTime"][11:16] if s.get("startTime") else "Scheduled")
    except base.SourceError:
        pass
    sessions = c.get("/sessions", {"itemsPerPage": 1000, "sortBy": "startTimeDesc"}).get("items") or []
    by_proc: dict[str, list] = {}
    for s in sessions:
        by_proc.setdefault(s.get("processName") or "", []).append(s)
    systems = {}
    for p in (c.get("/processes").get("items") or []):
        desc = p.get("description") or ""
        frm, to = base.arrow(desc)
        if not (frm and to):
            frm, to = base.arrow(p.get("name") or "")
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        out["integrations"].append({"ext_id": p.get("id") or p["name"], "name": p["name"], "kind": "Bot", "via": "Blue Prism", "from_system": frm, "to_system": to, "schedule": sched.get(p["name"], "Manual"),
                                    "owner": base.owner_from([desc]), "properties": {"group": p.get("groupName")}})
        for s in by_proc.get(p["name"], []):
            st, en = base.ts(s.get("startTime")), base.ts(s.get("endTime"))
            out["runs"].append({"integration": p.get("id") or p["name"], "ext_id": s.get("sessionId"), "started": st, "ended": en, "status": STATUS.get(s.get("status"), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": None, "error": s.get("exceptionMessage")})
    out["systems"] = list(systems.values())
    return out
