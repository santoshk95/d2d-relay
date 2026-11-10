"""Azure Logic Apps (Consumption) — the ARM REST API (api-version 2016-06-01): workflows with their trigger and
action connections (the systems), workflow runs, and API connections with their status (an "Error" status is an
expired or broken sign-in). Tags may carry owner."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "logicapps", "Azure Logic Apps", "Workflows & iPaaS"
AUTH = "Entra ID app (bearer token) with Reader on the resource group"
DOCS = "ARM: Microsoft.Logic/workflows, workflows/{name}/runs, Microsoft.Web/connections (2016-06-01)"
CONFIG = [{"name": "url", "label": "Management endpoint", "hint": "https://management.azure.com", "required": True},
          {"name": "subscription", "label": "Subscription id", "required": True}, {"name": "resource_group", "label": "Resource group", "required": True}]
SECRETS = [{"name": "token", "label": "Bearer token"}]
API = "2016-06-01"
STATUS = {"Succeeded": "success", "Failed": "failed", "Cancelled": "failed", "TimedOut": "failed", "Running": "running", "Waiting": "running"}
CONN_SYSTEM = {"sharepointonline": "SharePoint", "teams": "Teams", "dynamics365": "Dynamics 365", "commondataservice": "Dataverse", "office365": "Email (Microsoft)",
               "sql": "Azure SQL", "sftp": "SFTP", "salesforce": "Salesforce", "azureblob": "Azure Blob Storage", "formrecognizer": "Azure AI Document Intelligence", "snowflake": "Snowflake"}


def _conn(node: dict) -> str | None:
    name = (((node.get("inputs") or {}).get("host") or {}).get("connection") or {}).get("name") or ""
    key = name.split("/")[-1].split("-")[0].lower()
    return CONN_SYSTEM.get(key, name.split("/")[-1] or None)


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.bearer(secrets.get("token") or ""))
    rg = f"/subscriptions/{cfg['subscription']}/resourceGroups/{cfg['resource_group']}"
    out = base.empty()
    conns = {}
    for x in (c.get(rg + "/providers/Microsoft.Web/connections", {"api-version": API}).get("value") or []):
        p = x.get("properties") or {}
        sts = [s.get("status") for s in p.get("statuses") or []]
        conns[x["name"]] = p.get("displayName") or x["name"]
        out["credentials"].append({"name": p.get("displayName") or x["name"], "kind": ((p.get("api") or {}).get("name") or "connection").split("/")[-1], "integration": None,
                                   "expires": base.ts(p.get("expirationTime")) if p.get("expirationTime") else (now - 1 if "Error" in sts else None), "status": "error" if "Error" in sts else "connected"})
    systems = {}
    for w in (c.get(rg + "/providers/Microsoft.Logic/workflows", {"api-version": API}).get("value") or []):
        p = w.get("properties") or {}
        d = p.get("definition") or {}
        trigs = list((d.get("triggers") or {}).values()); acts = list((d.get("actions") or {}).values())
        frm = (_conn(trigs[0]) if trigs else None) or (w.get("tags") or {}).get("source")
        to = next((_conn(a) for a in reversed(acts) if _conn(a)), None) or (w.get("tags") or {}).get("target")
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        rec = (trigs[0].get("recurrence") if trigs else None) or {}
        sched = {"Minute": f"Every {rec.get('interval', 1)} min", "Hour": "Hourly" if rec.get("interval", 1) == 1 else f"Every {rec.get('interval')} h", "Day": "Daily", "Week": "Weekly"}.get(rec.get("frequency"), "On event")
        out["integrations"].append({"ext_id": w["name"], "name": (w.get("tags") or {}).get("displayName") or w["name"], "kind": "Flow", "via": "Logic Apps", "from_system": frm, "to_system": to,
                                    "schedule": sched + ("" if p.get("state") == "Enabled" else " (disabled)"), "owner": (w.get("tags") or {}).get("owner"),
                                    "properties": {"state": p.get("state"), "actions": len(acts), "connections": sorted({x for n in trigs + acts for x in [(((n.get('inputs') or {}).get('host') or {}).get('connection') or {}).get('name')] if x})}})
        for r in (c.get(rg + f"/providers/Microsoft.Logic/workflows/{w['name']}/runs", {"api-version": API, "$top": 500}).get("value") or []):
            rp = r.get("properties") or {}
            st, en = base.ts(rp.get("startTime")), base.ts(rp.get("endTime"))
            out["runs"].append({"integration": w["name"], "ext_id": r.get("name"), "started": st, "ended": en, "status": STATUS.get(rp.get("status"), "failed"),
                                "duration_s": round(en - st, 1) if st and en else None, "volume": (rp.get("outputs") or {}).get("count"), "error": (rp.get("error") or {}).get("message")})
    out["systems"] = list(systems.values())
    return out
