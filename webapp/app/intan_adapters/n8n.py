"""n8n - the public API (.../api/v1, X-N8N-API-KEY): workflows with their nodes (the trigger gives the schedule, the
first data node the source system, the last node the target), executions (runs), credentials by name from the
nodes that use them. Tags may carry "owner:<team>"."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "n8n", "n8n", "Workflows & iPaaS"
AUTH = "API key (n8n public API)"
DOCS = "n8n public API v1: GET /workflows, /executions"
CONFIG = [{"name": "url", "label": "API base URL", "hint": "https://n8n.example.com/api/v1", "required": True}]
SECRETS = [{"name": "api_key", "label": "API key"}]
STATUS = {"success": "success", "error": "failed", "crashed": "failed", "canceled": "skipped", "running": "running", "waiting": "running"}
TRIGGERS = ("trigger", "webhook", "cron", "interval")
SYSTEM_TYPES = {"snowflake": "Snowflake", "postgres": "PostgreSQL", "mysql": "MySQL", "microsoftsql": "SQL Server", "salesforce": "Salesforce", "jira": "Jira / Freshservice",
                "microsoftteams": "Teams", "slack": "Slack", "gmail": "Gmail", "sftp": "SFTP", "googlesheets": "Google Sheets", "hubspot": "HubSpot", "zohocrm": "Zoho CRM"}


def _system(node: dict) -> str | None:
    t = (node.get("type") or "").split(".")[-1].lower()
    for k, v in SYSTEM_TYPES.items():
        if t.startswith(k):
            return v
    return node.get("name")


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], {"X-N8N-API-KEY": secrets.get("api_key") or ""})
    out = base.empty()
    systems, creds = {}, {}
    for w in (c.get("/workflows", {"limit": 250}).get("data") or []):
        nodes = w.get("nodes") or []
        trig = next((n for n in nodes if any(k in (n.get("type") or "").lower() for k in TRIGGERS)), None)
        data_nodes = [n for n in nodes if n is not trig and "noOp" not in (n.get("type") or "") and "set" != (n.get("type") or "").split(".")[-1].lower()]
        frm = _system(data_nodes[0]) if data_nodes else (_system(trig) if trig else None)
        to = _system(data_nodes[-1]) if len(data_nodes) > 1 else "n8n"
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        kind, sched = "Flow", "Manual"
        if trig:
            tt = (trig.get("type") or "").lower()
            if "webhook" in tt:
                kind, sched = "Webhook", "On event"
            elif "schedule" in tt or "cron" in tt or "interval" in tt:
                rule = ((trig.get("parameters") or {}).get("rule") or {}).get("interval") or [{}]
                r0 = rule[0] if rule else {}
                sched = base.schedule_text(every_min=r0.get("minutesInterval") or (r0.get("hoursInterval") or 0) * 60 or None, cron=(trig.get("parameters") or {}).get("cronExpression"), text=f"Daily {r0.get('triggerAtHour', 0):02d}:00" if r0.get("field") == "days" else None)
            else:
                sched = "On event"
        tags = [t.get("name") if isinstance(t, dict) else t for t in w.get("tags") or []]
        for n in nodes:
            for ctype, cref in (n.get("credentials") or {}).items():
                nm = (cref or {}).get("name") or ctype
                creds.setdefault(nm, {"name": nm, "kind": ctype, "integration": str(w["id"]), "expires": None, "status": None})
        out["integrations"].append({"ext_id": str(w["id"]), "name": w.get("name") or str(w["id"]), "kind": kind, "via": "n8n", "from_system": frm, "to_system": to, "schedule": sched + ("" if w.get("active") else " (inactive)"),
                                    "owner": base.owner_from(tags), "writes": [str(t).split(":", 1)[1].strip() for t in tags if str(t).lower().startswith("writes:")], "properties": {"active": w.get("active"), "nodes": len(nodes), "tags": tags}})
        for e in (c.get("/executions", {"workflowId": w["id"], "limit": 250}).get("data") or []):
            st, en = base.ts(e.get("startedAt")), base.ts(e.get("stoppedAt"))
            out["runs"].append({"integration": str(w["id"]), "ext_id": str(e.get("id")), "started": st, "ended": en, "status": STATUS.get(e.get("status"), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": (e.get("data") or {}).get("items") if isinstance(e.get("data"), dict) else None, "error": (e.get("data") or {}).get("error") if isinstance(e.get("data"), dict) else None})
    out["credentials"] = list(creds.values())
    out["systems"] = list(systems.values())
    return out
