"""AWS Glue — the Glue API (JSON 1.1 targets AWSGlue.GetJobs, GetJobRuns, GetTriggers). With boto3 installed and no
endpoint override the call is signed properly; the mock lab's endpoint checks the access key id in a SigV4-shaped
header, which is all a simulator can do. Job descriptions may carry "owner:" and "<from> → <to>"."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "glue", "AWS Glue", "Pipelines & ETL"
AUTH = "IAM access key (read-only Glue policy)"
DOCS = "Glue API: GetJobs, GetJobRuns, GetTriggers"
CONFIG = [{"name": "region", "label": "Region", "hint": "eu-west-1", "required": True}, {"name": "url", "label": "Endpoint override", "hint": "only for the mock lab", "required": False}]
SECRETS = [{"name": "access_key", "label": "Access key id"}, {"name": "secret_key", "label": "Secret access key"}]
STATUS = {"SUCCEEDED": "success", "FAILED": "failed", "ERROR": "failed", "TIMEOUT": "failed", "STOPPED": "failed", "RUNNING": "running", "STARTING": "running", "WAITING": "running"}


def _call(cfg: dict, secrets: dict):
    if cfg.get("url"):
        c = base.Client(cfg["url"], {"Authorization": f"AWS4-HMAC-SHA256 Credential={secrets.get('access_key', '')}/{time.strftime('%Y%m%d')}/{cfg.get('region', '')}/glue/aws4_request, SignedHeaders=host;x-amz-target, Signature=mock-lab",
                                     "Content-Type": "application/x-amz-json-1.1"})
        return lambda target, body: c.post("/", body, headers={"X-Amz-Target": f"AWSGlue.{target}"})
    try:
        import boto3
    except ImportError as e:
        raise base.SourceError("boto3 is not installed in this image; AWS Glue needs it (or an endpoint override for the mock lab).") from e
    g = boto3.client("glue", region_name=cfg.get("region"), aws_access_key_id=secrets.get("access_key"), aws_secret_access_key=secrets.get("secret_key"))
    ops = {"GetJobs": lambda b: g.get_jobs(**b), "GetJobRuns": lambda b: g.get_job_runs(**b), "GetTriggers": lambda b: g.get_triggers(**b)}
    return lambda target, body: ops[target](body)


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    call = _call(cfg, secrets)
    out = base.empty()
    sched = {}
    for t in call("GetTriggers", {}).get("Triggers") or []:
        text = base.schedule_text(cron=(t.get("Schedule") or "").replace("cron(", "").rstrip(")").replace(" ? ", " ") if t.get("Schedule") else None, text=None if t.get("Schedule") else t.get("Type"))
        for a in t.get("Actions") or []:
            sched[a.get("JobName")] = text
    systems = {}
    for j in call("GetJobs", {}).get("Jobs") or []:
        desc = j.get("Description") or ""
        frm, to = base.arrow(desc)
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        out["integrations"].append({"ext_id": j["Name"], "name": j["Name"], "kind": "Pipeline", "via": "AWS Glue", "from_system": frm, "to_system": to, "schedule": sched.get(j["Name"], "On demand"),
                                    "owner": base.owner_from([desc]), "writes": base.writes_from([desc]), "properties": {"command": (j.get("Command") or {}).get("Name"), "role": j.get("Role")}})
        for r in call("GetJobRuns", {"JobName": j["Name"], "MaxResults": 200}).get("JobRuns") or []:
            st, en = base.ts(r.get("StartedOn")), base.ts(r.get("CompletedOn"))
            out["runs"].append({"integration": j["Name"], "ext_id": r.get("Id"), "started": st, "ended": en, "status": STATUS.get(r.get("JobRunState"), "failed"),
                                "duration_s": r.get("ExecutionTime") or (round(en - st, 1) if st and en else None), "volume": None, "error": r.get("ErrorMessage")})
    out["systems"] = list(systems.values())
    return out
