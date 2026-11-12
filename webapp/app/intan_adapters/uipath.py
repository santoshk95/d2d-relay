"""UiPath Orchestrator - the OData API: Releases (processes), Jobs (runs with State and Info - a faulted job whose
Info names a selector or a screen is a screen change), Assets of type Credential (credentials by name),
ProcessSchedules (cron), QueueDefinitions. The release description may carry "<from> -> <to>" and "owner:"."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "uipath", "UiPath Orchestrator", "RPA"
AUTH = "external application (bearer token) with Orchestrator read scopes"
DOCS = "Orchestrator OData: /odata/Releases, /odata/Jobs, /odata/Assets, /odata/ProcessSchedules, /odata/QueueDefinitions"
CONFIG = [{"name": "url", "label": "Orchestrator URL", "hint": "https://cloud.uipath.com/<org>/<tenant>/orchestrator_", "required": True}, {"name": "folder", "label": "Folder id (X-UIPATH-OrganizationUnitId)", "required": False}]
SECRETS = [{"name": "token", "label": "Bearer token"}]
STATUS = {"Successful": "success", "Faulted": "failed", "Stopped": "skipped", "Terminating": "failed", "Running": "running", "Pending": "running", "Suspended": "running", "Resumed": "running"}


def _cron_text(cron: str | None) -> str:
    if not cron:
        return "Manual"
    parts = cron.split()
    if len(parts) >= 6 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        return f"Daily {int(parts[2]):02d}:{int(parts[1]):02d}"
    return base.schedule_text(cron=" ".join(parts[1:6]).replace(" ? ", " ") if len(parts) >= 6 else cron)


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    hdr = base.Client.bearer(secrets.get("token") or "")
    if cfg.get("folder"):
        hdr["X-UIPATH-OrganizationUnitId"] = str(cfg["folder"])
    c = base.Client(cfg["url"], hdr)
    out = base.empty()
    sched = {}
    try:
        for s in (c.get("/odata/ProcessSchedules").get("value") or []):
            sched[s.get("ReleaseName")] = _cron_text(s.get("StartProcessCron")) + ("" if s.get("Enabled", True) else " (disabled)")
    except base.SourceError:
        pass
    jobs = c.get("/odata/Jobs", {"$top": 1000, "$orderby": "StartTime desc"}).get("value") or []
    by_rel: dict[str, list] = {}
    for j in jobs:
        by_rel.setdefault(j.get("ReleaseName") or "", []).append(j)
    systems = {}
    for r in (c.get("/odata/Releases").get("value") or []):
        desc = r.get("Description") or ""
        frm, to = base.arrow(desc)
        if not (frm and to):
            frm, to = base.arrow(r.get("Name") or "")
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        dep = [x.split("waits on", 1)[1].strip().rstrip(".") for x in desc.split(";") if "waits on" in x.lower()]
        out["integrations"].append({"ext_id": r.get("ProcessKey") or r["Name"], "name": r["Name"], "kind": "Bot", "via": "UiPath", "from_system": frm, "to_system": to, "schedule": sched.get(r["Name"], "Manual"),
                                    "owner": base.owner_from([desc]) or ((r.get("OrganizationUnitFullyQualifiedName") or "").split("/")[0] or None), "depends_on": dep,
                                    "properties": {"version": r.get("ProcessVersion"), "folder": r.get("OrganizationUnitFullyQualifiedName")}})
        for j in by_rel.get(r["Name"], []):
            st, en = base.ts(j.get("StartTime")), base.ts(j.get("EndTime"))
            status = STATUS.get(j.get("State"), "failed")
            out["runs"].append({"integration": r.get("ProcessKey") or r["Name"], "ext_id": str(j.get("Id")), "started": st, "ended": en, "status": status,
                                "duration_s": round(en - st, 1) if st and en else None, "volume": (j.get("OutputArguments") or {}).get("items") if isinstance(j.get("OutputArguments"), dict) else None,
                                "error": j.get("Info") if status in ("failed", "skipped") else None})
    try:
        for a in (c.get("/odata/Assets").get("value") or []):
            if a.get("ValueType") == "Credential":
                out["credentials"].append({"name": a["Name"], "kind": "credential asset", "integration": None, "expires": base.expires_from([a.get("Description")]), "status": None})
        for q in (c.get("/odata/QueueDefinitions").get("value") or []):
            out["systems"].append({"name": q["Name"], "kind": "queue"})
    except base.SourceError:
        pass
    out["systems"] += list(systems.values())
    return out
