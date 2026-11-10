"""Power Automate (cloud flows) — the Flow management API (providers/Microsoft.ProcessSimple, api-version 2016-11-01):
flows with their trigger / action connectors (the systems), flow runs, and connections with their status (an
"Error" status is a sign-in that no longer works)."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "powerautomate", "Power Automate", "Workflows & iPaaS"
AUTH = "Entra ID app (bearer token) with environment admin or maker read"
DOCS = "Flow management API: environments/{env}/flows, flows/{id}/runs, environments/{env}/connections (2016-11-01)"
CONFIG = [{"name": "url", "label": "API base URL", "hint": "https://api.flow.microsoft.com", "required": True}, {"name": "environment", "label": "Environment id", "required": True}]
SECRETS = [{"name": "token", "label": "Bearer token"}]
API = "2016-11-01"
STATUS = {"Succeeded": "success", "Failed": "failed", "Cancelled": "failed", "TimedOut": "failed", "Running": "running"}
API_SYSTEM = {"shared_office365": "Email (Microsoft)", "shared_sharepointonline": "SharePoint", "shared_teams": "Teams", "shared_commondataserviceforapps": "Dataverse", "shared_dynamics365": "Dynamics 365",
              "shared_sql": "Azure SQL", "shared_salesforce": "Salesforce", "shared_excelonlinebusiness": "Excel", "shared_onedriveforbusiness": "OneDrive", "shared_sftp": "SFTP", "shared_approvals": "Approvals"}


def _sys(node: dict) -> str | None:
    name = ((node.get("api") or {}).get("name") or "").split("/")[-1]
    return API_SYSTEM.get(name, name or None)


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.bearer(secrets.get("token") or ""))
    env = f"/providers/Microsoft.ProcessSimple/environments/{cfg['environment']}"
    out = base.empty()
    for cn in (c.get(env + "/connections", {"api-version": API}).get("value") or []):
        p = cn.get("properties") or {}
        sts = [s.get("status") for s in p.get("statuses") or []]
        out["credentials"].append({"name": p.get("displayName") or cn["name"], "kind": (p.get("apiId") or "").split("/")[-1] or "connection", "integration": None,
                                   "expires": base.ts(p.get("expirationTime")) if p.get("expirationTime") else (now - 1 if "Error" in sts else None), "status": "error" if "Error" in sts else "connected"})
    systems = {}
    for f in (c.get(env + "/flows", {"api-version": API}).get("value") or []):
        p = f.get("properties") or {}
        ds = p.get("definitionSummary") or {}
        trigs, acts = ds.get("triggers") or [], ds.get("actions") or []
        frm = _sys(trigs[0]) if trigs else None
        to = next((_sys(a) for a in reversed(acts) if _sys(a)), None)
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        t0 = trigs[0] if trigs else {}
        sched = "On event" if t0.get("type") in ("OpenApiConnection", "ApiConnection", "Request") else ("Scheduled" if t0.get("type") == "Recurrence" else "Manual")
        if t0.get("type") == "Recurrence":
            rec = t0.get("recurrence") or {}
            sched = {"Minute": f"Every {rec.get('interval', 1)} min", "Hour": "Hourly", "Day": "Daily", "Week": "Weekly"}.get(rec.get("frequency"), "Scheduled")
        out["integrations"].append({"ext_id": f["name"], "name": p.get("displayName") or f["name"], "kind": "Flow", "via": "Power Automate", "from_system": frm, "to_system": to,
                                    "schedule": sched + ("" if p.get("state") == "Started" else " (stopped)"), "owner": None,
                                    "properties": {"state": p.get("state"), "actions": len(acts), "connections": sorted({(v or {}).get("displayName") for v in (p.get("connectionReferences") or {}).values() if (v or {}).get("displayName")})}})
        for cr in out["credentials"]:
            if not cr["integration"] and cr["name"] in (out["integrations"][-1]["properties"]["connections"] or []):
                cr["integration"] = f["name"]
        for r in (c.get(env + f"/flows/{f['name']}/runs", {"api-version": API}).get("value") or []):
            rp = r.get("properties") or {}
            st, en = base.ts(rp.get("startTime")), base.ts(rp.get("endTime"))
            out["runs"].append({"integration": f["name"], "ext_id": r.get("name"), "started": st, "ended": en, "status": STATUS.get(rp.get("status"), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": 1, "error": (rp.get("error") or {}).get("message")})
    out["systems"] = list(systems.values())
    return out
