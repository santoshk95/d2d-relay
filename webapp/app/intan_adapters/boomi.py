"""Boomi AtomSphere - the platform API (.../api/rest/v1/{account}): Process/query, ExecutionRecord/query (status,
execution time, duration and inbound document count in Boomi's typed-array JSON), ProcessSchedules/query."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import base

KIND, LABEL, GROUP = "boomi", "Boomi AtomSphere", "Integration platform"
AUTH = "API token user (basic: user, BOOMI_TOKEN.<token>)"
DOCS = "AtomSphere API: POST Process/query, ExecutionRecord/query, ProcessSchedules/query"
CONFIG = [{"name": "url", "label": "API base URL", "hint": "https://api.boomi.com/api/rest/v1/<accountId>", "required": True}]
SECRETS = [{"name": "username", "label": "User (BOOMI_TOKEN.user@example.com)"}, {"name": "token", "label": "API token"}]
STATUS = {"COMPLETE": "success", "COMPLETE_WARN": "success", "ERROR": "failed", "ABORTED": "failed", "INPROCESS": "running", "DISCARDED": "skipped"}


def _v(x):
    """Boomi's typed values: ["Long", 123] -> 123."""
    return x[1] if isinstance(x, list) and len(x) == 2 else x


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.basic(secrets.get("username") or "", secrets.get("token") or ""))
    out = base.empty()
    procs = c.post("/Process/query", {"QueryFilter": {"expression": {"operator": "and", "nestedExpression": []}}}).get("result") or []
    sched = {}
    try:
        for s in c.post("/ProcessSchedules/query", {}).get("result") or []:
            ss = s.get("Schedule") or []
            if ss:
                m, hh = ss[0].get("minutes", "*"), ss[0].get("hours", "*")
                sched[s.get("processId")] = "Hourly" if hh == "*" and m in ("0", 0) else (f"Daily {int(hh):02d}:{int(m):02d}" if str(hh).isdigit() else f"Every {m.split('/')[-1]} min" if "/" in str(m) else "Scheduled")
    except base.SourceError:
        pass
    since = datetime.fromtimestamp(now - 42 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recs = c.post("/ExecutionRecord/query", {"QueryFilter": {"expression": {"argument": [since], "operator": "GREATER_THAN", "property": "executionTime"}}}).get("result") or []
    systems = {}
    for p in procs:
        desc = p.get("description") or ""
        frm, to = base.arrow(desc)
        if not (frm and to):
            frm, to = base.arrow(p.get("name") or "")
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        out["integrations"].append({"ext_id": p["id"], "name": p.get("name") or p["id"], "kind": "Integration", "via": "Boomi", "from_system": frm, "to_system": to, "schedule": sched.get(p["id"], "Unknown"),
                                    "owner": base.owner_from([desc]), "writes": base.writes_from([desc]), "properties": {}})
    for r in recs:
        st = base.ts(r.get("executionTime")); dur = (_v(r.get("executionDuration")) or 0) / 1000
        out["runs"].append({"integration": r.get("processId"), "ext_id": r.get("executionId"), "started": st, "ended": (st + dur) if st else None, "status": STATUS.get((r.get("status") or "").upper(), "failed"),
                            "duration_s": round(dur, 1), "volume": _v(r.get("inboundDocumentCount")), "error": r.get("message") if (r.get("status") or "").upper() in ("ERROR", "ABORTED") else None})
    out["systems"] = list(systems.values())
    return out
