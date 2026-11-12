"""Automation Anywhere (Automation 360 Control Room) - the Control Room API: POST /v2/authentication for a token,
/v2/repository/workspaces/public/files/list (bots), /v3/activity/list (runs with status and message - "UI element
not found" is a screen change), /v1/schedule/automations/list, /v2/credentialvault/credentials/list (names only)."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "aa", "Automation Anywhere", "RPA"
AUTH = "Control Room user with an API key"
DOCS = "Control Room API: /v2/authentication, /v2/repository/workspaces/public/files/list, /v3/activity/list, /v1/schedule/automations/list, /v2/credentialvault/credentials/list"
CONFIG = [{"name": "url", "label": "Control Room URL", "hint": "https://<tenant>.my.automationanywhere.digital", "required": True}]
SECRETS = [{"name": "username", "label": "User"}, {"name": "api_key", "label": "API key"}]
STATUS = {"COMPLETED": "success", "RUN_FAILED": "failed", "RUN_ABORTED": "failed", "DEPLOY_FAILED": "failed", "RUNNING": "running", "QUEUED": "running", "RUN_PAUSED": "running", "STOPPED": "skipped"}


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"])
    tok = c.post("/v2/authentication", {"username": secrets.get("username") or "", "apiKey": secrets.get("api_key") or ""}).get("token") or ""
    c.headers["X-Authorization"] = tok
    out = base.empty()
    bots = [b for b in (c.post("/v2/repository/workspaces/public/files/list", {"filter": {"operator": "eq", "field": "type", "value": "TASKBOT"}}).get("list") or [])]
    sched = {}
    try:
        for s in (c.post("/v1/schedule/automations/list", {}).get("list") or []):
            sched[s.get("fileName") or s.get("name")] = base.schedule_text(cron=" ".join((s.get("cronExpression") or "").split()[1:6]).replace(" ? ", " ") or None, text=None if s.get("cronExpression") else "Scheduled")
    except base.SourceError:
        pass
    acts = c.post("/v3/activity/list", {"sort": [{"field": "startDateTime", "direction": "desc"}], "page": {"offset": 0, "length": 1000}}).get("list") or []
    by_name: dict[str, list] = {}
    for a in acts:
        by_name.setdefault(a.get("automationName") or "", []).append(a)
    systems = {}
    for b in bots:
        desc = b.get("description") or ""
        frm, to = base.arrow(desc)
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        out["integrations"].append({"ext_id": str(b.get("id")), "name": b["name"], "kind": "Bot", "via": "Automation Anywhere", "from_system": frm, "to_system": to, "schedule": sched.get(b["name"], "Manual"),
                                    "owner": base.owner_from([desc]), "properties": {"path": b.get("path"), "type": b.get("type")}})
        for a in by_name.get(b["name"], []):
            st, en = base.ts(a.get("startDateTime")), base.ts(a.get("endDateTime"))
            out["runs"].append({"integration": str(b.get("id")), "ext_id": str(a.get("id")), "started": st, "ended": en, "status": STATUS.get(a.get("status"), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": None, "error": a.get("message") if STATUS.get(a.get("status")) == "failed" else None})
    try:
        for cr in (c.post("/v2/credentialvault/credentials/list", {}).get("list") or []):
            out["credentials"].append({"name": cr["name"], "kind": "credential vault", "integration": None, "expires": base.expires_from([cr.get("description")]), "status": None})
    except base.SourceError:
        pass
    out["systems"] = list(systems.values())
    return out
