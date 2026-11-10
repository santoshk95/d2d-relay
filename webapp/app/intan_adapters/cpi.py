"""SAP Integration Suite (Cloud Integration, CPI) and PI/PO — the OData API (…/api/v1): deployed integration
runtime artifacts (iFlows), message processing logs (runs with Sender / Receiver), user credentials by name."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import base

KIND, LABEL, GROUP = "cpi", "SAP CPI · PI/PO", "Integration platform"
AUTH = "service account (basic) or OAuth client credentials"
DOCS = "CPI OData API v1: IntegrationRuntimeArtifacts, MessageProcessingLogs, UserCredentials"
CONFIG = [{"name": "url", "label": "OData base URL", "hint": "https://<tenant>.it-cpi.cfapps.eu10.hana.ondemand.com/api/v1", "required": True}]
SECRETS = [{"name": "username", "label": "User"}, {"name": "password", "label": "Password or token"}]
STATUS = {"COMPLETED": "success", "FAILED": "failed", "RETRY": "failed", "ESCALATED": "failed", "PROCESSING": "running", "DISCARDED": "skipped"}


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.basic(secrets.get("username") or "", secrets.get("password") or ""))
    out = base.empty()
    arts = ((c.get("/IntegrationRuntimeArtifacts").get("d") or {}).get("results")) or []
    since = datetime.fromtimestamp(now - 42 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    logs = ((c.get("/MessageProcessingLogs", {"$filter": f"LogStart gt datetime'{since}'", "$orderby": "LogStart desc", "$top": 5000}).get("d") or {}).get("results")) or []
    by_flow: dict[str, list] = {}
    for l in logs:
        by_flow.setdefault(l.get("IntegrationFlowName") or "", []).append(l)
    systems = {}
    for a in arts:
        mine = by_flow.get(a["Id"], [])
        frm = next((l.get("Sender") for l in mine if l.get("Sender")), None) or base.arrow(a.get("Name") or "")[0]
        to = next((l.get("Receiver") for l in mine if l.get("Receiver")), None) or base.arrow(a.get("Name") or "")[1]
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        out["integrations"].append({"ext_id": a["Id"], "name": a.get("Name") or a["Id"], "kind": "Integration", "via": "SAP CPI", "from_system": frm, "to_system": to,
                                    "schedule": a.get("Schedule") or ("On event" if not a.get("Schedule") else a["Schedule"]), "owner": base.owner_from([a.get("Description")]) or a.get("DeployedBy"),
                                    "writes": base.writes_from([a.get("Description")]), "properties": {"type": a.get("Type"), "status": a.get("Status"), "deployed_on": base.ts(a.get("DeployedOn"))}})
        fails = 0
        mine.sort(key=lambda l: base.ts(l.get("LogStart")) or 0, reverse=True)       # the newest failures carry the error text
        for l in mine:
            st, en = base.ts(l.get("LogStart")), base.ts(l.get("LogEnd"))
            status = STATUS.get((l.get("Status") or "").upper(), "failed")
            err = None
            if status == "failed" and fails < 5:
                fails += 1
                try:
                    err = ((c.get(f"/MessageProcessingLogs('{l['MessageGuid']}')/ErrorInformation").get("d") or {}).get("ErrorText")) or l.get("CustomStatus")
                except base.SourceError:
                    err = l.get("CustomStatus")
            out["runs"].append({"integration": a["Id"], "ext_id": l.get("MessageGuid"), "started": st, "ended": en, "status": status, "duration_s": round(en - st, 1) if st and en else None, "volume": 1, "error": err})
    try:
        for u in ((c.get("/UserCredentials").get("d") or {}).get("results")) or []:
            out["credentials"].append({"name": u.get("Name"), "kind": (u.get("Kind") or "credential").lower(), "integration": None, "expires": base.expires_from([u.get("Description")]), "status": None})
    except base.SourceError:
        pass
    out["systems"] = list(systems.values())
    return out
