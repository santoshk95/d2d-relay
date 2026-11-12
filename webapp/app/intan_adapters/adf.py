"""Azure Data Factory - the ARM REST API (api-version 2018-06-01): pipelines with their activities' input / output
datasets, datasets -> linked services (the systems), triggers (schedules), queryPipelineRuns (runs). Linked-service
annotations may carry "system:<name>" and "expires:<date>" (ADF does not expose a credential's expiry itself);
pipeline annotations may carry "owner:<team>"."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import base

KIND, LABEL, GROUP = "adf", "Azure Data Factory", "Pipelines & ETL"
AUTH = "Entra ID app (bearer token) with Reader on the factory"
DOCS = "ARM: factories/{f}/pipelines, /datasets, /linkedservices, /triggers, POST /queryPipelineRuns (2018-06-01)"
CONFIG = [{"name": "url", "label": "Management endpoint", "hint": "https://management.azure.com", "required": True},
          {"name": "subscription", "label": "Subscription id", "required": True}, {"name": "resource_group", "label": "Resource group", "required": True},
          {"name": "factory", "label": "Factory name", "required": True}]
SECRETS = [{"name": "token", "label": "Bearer token (or client secret exchanged by the app)"}]
API = "2018-06-01"
STATUS = {"Succeeded": "success", "Failed": "failed", "Cancelled": "failed", "Canceling": "running", "InProgress": "running", "Queued": "running"}
TYPE_SYSTEM = {"Snowflake": "Snowflake", "SnowflakeV2": "Snowflake", "AzureSqlDatabase": "Azure SQL", "SqlServer": "SQL Server", "SapTable": "SAP S/4HANA", "SapEcc": "SAP ECC",
               "Sftp": "SFTP", "SftpServer": "SFTP", "AzureBlobStorage": "Azure Blob Storage", "AzureBlobFS": "Azure Data Lake", "Oracle": "Oracle", "Salesforce": "Salesforce", "RestService": "REST API"}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"], base.Client.bearer(secrets.get("token") or ""))
    f = f"/subscriptions/{cfg['subscription']}/resourceGroups/{cfg['resource_group']}/providers/Microsoft.DataFactory/factories/{cfg['factory']}"
    out = base.empty()
    ls = {}
    for x in (c.get(f + "/linkedservices", {"api-version": API}).get("value") or []):
        p = x.get("properties") or {}
        ann = p.get("annotations") or []
        system = next((a.split(":", 1)[1].strip() for a in ann if str(a).lower().startswith("system:")), None) or TYPE_SYSTEM.get(p.get("type"), p.get("type") or x["name"])
        ls[x["name"]] = system
        exp = base.expires_from(ann + [p.get("description")])
        if exp or p.get("type") in ("RestService", "Salesforce", "SapTable", "Snowflake", "SnowflakeV2"):
            out["credentials"].append({"name": x["name"], "kind": (p.get("typeProperties") or {}).get("authenticationType") or p.get("type") or "linked service", "integration": None, "expires": exp, "status": None})
    ds = {}
    for x in (c.get(f + "/datasets", {"api-version": API}).get("value") or []):
        p = x.get("properties") or {}
        ds[x["name"]] = {"system": ls.get(((p.get("linkedServiceName") or {}).get("referenceName")), None), "object": (p.get("typeProperties") or {}).get("tableName") or (p.get("typeProperties") or {}).get("table"), "ls": (p.get("linkedServiceName") or {}).get("referenceName")}
    trig = {}
    for x in (c.get(f + "/triggers", {"api-version": API}).get("value") or []):
        p = x.get("properties") or {}
        rec = (p.get("typeProperties") or {}).get("recurrence") or {}
        text = {"Minute": f"Every {rec.get('interval', 1)} min", "Hour": "Hourly" if rec.get("interval", 1) == 1 else f"Every {rec.get('interval')} h", "Day": "Daily" + (f" {rec['schedule']['hours'][0]:02d}:{(rec['schedule'].get('minutes') or [0])[0]:02d}" if rec.get("schedule") and rec["schedule"].get("hours") else ""), "Week": "Weekly", "Month": "Monthly"}.get(rec.get("frequency"), p.get("type") or "Unknown")
        for pl in p.get("pipelines") or []:
            trig[(pl.get("pipelineReference") or {}).get("referenceName")] = text + ("" if p.get("runtimeState") == "Started" else " (trigger stopped)")
    systems = {}
    for x in (c.get(f + "/pipelines", {"api-version": API}).get("value") or []):
        p = x.get("properties") or {}
        acts = p.get("activities") or []
        ins = [ds.get((i.get("referenceName")), {}) for a in acts for i in a.get("inputs") or []]
        outs = [ds.get((o.get("referenceName")), {}) for a in acts for o in a.get("outputs") or []]
        frm = next((d["system"] for d in ins if d.get("system")), None)
        to = next((d["system"] for d in reversed(outs) if d.get("system")), None) or "Azure Data Factory"
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        kind = "API pull" if any(a.get("type") in ("WebActivity", "Copy") and (ds.get((i.get("referenceName")), {}).get("ls") or "").lower().find("rest") >= 0 for a in acts for i in a.get("inputs") or []) else "Pipeline"
        writes = [f"{d['system'].lower()}:{d['object']}" for d in outs if d.get("system") and d.get("object") and d["system"].lower() in ("snowflake", "fabric", "bigquery", "redshift", "synapse")]
        ann = p.get("annotations") or []
        out["integrations"].append({"ext_id": x["name"], "name": x["name"], "kind": kind, "via": "ADF", "from_system": frm, "to_system": to, "schedule": trig.get(x["name"], "Manual"),
                                    "owner": base.owner_from(ann + [p.get("description")]), "writes": writes, "properties": {"folder": (p.get("folder") or {}).get("name"), "activities": len(acts), "linked_services": sorted({d["ls"] for d in ins + outs if d.get("ls")})}})
        for d in ins:
            if d.get("ls") and any(cr["name"] == d["ls"] for cr in out["credentials"]):
                for cr in out["credentials"]:
                    if cr["name"] == d["ls"] and not cr["integration"]:
                        cr["integration"] = x["name"]
    runs = c.post(f + "/queryPipelineRuns", {"lastUpdatedAfter": _iso(now - 42 * 86400), "lastUpdatedBefore": _iso(now + 3600)}, {"api-version": API})
    for r in runs.get("value") or []:
        st, en = base.ts(r.get("runStart")), base.ts(r.get("runEnd"))
        out["runs"].append({"integration": r.get("pipelineName"), "ext_id": r.get("runId"), "started": st, "ended": en, "status": STATUS.get(r.get("status"), "failed"),
                            "duration_s": round((r.get("durationInMs") or 0) / 1000, 1) if r.get("durationInMs") else (round(en - st, 1) if st and en else None), "volume": r.get("rowsCopied"), "error": r.get("message") or None})
    out["systems"] = list(systems.values())
    return out
