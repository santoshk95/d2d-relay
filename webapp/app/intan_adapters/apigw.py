"""API gateways — Azure API Management (ARM, api-version 2022-08-01: apis with contact and backend, reports/byRequest
as runs, subscriptions with their expiry, api releases whose notes announce schema changes) or a Kong-style gateway
(admin API /services and /routes; requests from the file-log plugin's JSON records)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import base

KIND, LABEL, GROUP = "apigw", "API gateway (APIM / Kong)", "APIs"
AUTH = "APIM: Entra ID app (bearer); Kong: admin API key"
DOCS = "APIM: service/{s}/apis, /reports/byRequest, /subscriptions, /apis/{id}/releases (2022-08-01); Kong admin API /services, /routes + file-log records"
CONFIG = [{"name": "style", "label": "Gateway", "hint": "apim or kong", "required": True}, {"name": "url", "label": "Base URL", "hint": "https://management.azure.com or http://kong:8001", "required": True},
          {"name": "subscription", "label": "APIM: subscription id", "required": False}, {"name": "resource_group", "label": "APIM: resource group", "required": False},
          {"name": "service", "label": "APIM: service name", "required": False}, {"name": "log_url", "label": "Kong: file-log records URL", "required": False}]
SECRETS = [{"name": "token", "label": "Bearer token or admin API key"}]
API = "2022-08-01"


def _apim(cfg: dict, secrets: dict, now: float) -> dict:
    c = base.Client(cfg["url"], base.Client.bearer(secrets.get("token") or ""))
    s = f"/subscriptions/{cfg['subscription']}/resourceGroups/{cfg['resource_group']}/providers/Microsoft.ApiManagement/service/{cfg['service']}"
    out = base.empty()
    systems = {}
    apis = c.get(s + "/apis", {"api-version": API}).get("value") or []
    for a in apis:
        p = a.get("properties") or {}
        desc = p.get("description") or ""
        frm, to = base.arrow(desc)
        via = next((x.split("via", 1)[1].strip().rstrip(".;") for x in desc.split(";") if " via " in x), None)
        for x in (frm, to):
            if x:
                systems[x] = {"name": x, "kind": "system"}
        sched = next((x.strip().capitalize() for x in desc.split(";") if x.strip().lower() in ("monthly", "daily", "hourly", "weekly")), "On event")
        out["integrations"].append({"ext_id": a["name"], "name": p.get("displayName") or a["name"], "kind": "API push" if "push" in a["name"] else "API pull" if "pull" in a["name"] else "API", "via": via or "APIM",
                                    "from_system": frm, "to_system": to, "schedule": sched, "owner": (p.get("contact") or {}).get("name"), "properties": {"path": p.get("path"), "backend": p.get("serviceUrl")}})
        try:
            for r in (c.get(s + f"/apis/{a['name']}/releases", {"api-version": API}).get("value") or []):
                notes = (r.get("properties") or {}).get("notes") or ""
                if "schema" in notes.lower():
                    out["signals"].append({"kind": "schema_change", "integration": a["name"], "text": notes.split("\n")[0][:200], "value": None, "limit": None, "due": base.ts((r.get("properties") or {}).get("effectiveDate")) or base.expires_from([notes])})
        except (base.SourceError, base.AuthError):
            pass
    since = datetime.fromtimestamp(now - 42 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in (c.get(s + "/reports/byRequest", {"api-version": API, "$filter": f"timestamp ge datetime'{since}'", "$top": 5000}).get("value") or []):
        code = int(r.get("responseCode") or 0)
        st = base.ts(r.get("timestamp"))
        out["runs"].append({"integration": (r.get("apiId") or "").split("/")[-1], "ext_id": r.get("requestId"), "started": st, "ended": (st + (r.get("apiTime") or 0) / 1000) if st else None,
                            "status": "success" if 200 <= code < 400 else "failed", "duration_s": (r.get("apiTime") or 0) / 1000, "volume": r.get("requestSize"), "error": f"HTTP {code} from backend" if code >= 500 else f"HTTP {code}" if code >= 400 else None})
    for sub in (c.get(s + "/subscriptions", {"api-version": API}).get("value") or []):
        p = sub.get("properties") or {}
        out["credentials"].append({"name": p.get("displayName") or sub["name"], "kind": "subscription key", "integration": (p.get("scope") or "").split("/apis/")[-1] if "/apis/" in (p.get("scope") or "") else None,
                                   "expires": base.ts(p.get("expirationDate")), "status": p.get("state")})
    out["systems"] = list(systems.values())
    return out


def _kong(cfg: dict, secrets: dict, now: float) -> dict:
    c = base.Client(cfg["url"], {"Kong-Admin-Token": secrets.get("token") or ""})
    out = base.empty()
    systems = {}
    svcs = c.get("/services").get("data") or []
    for sv in svcs:
        tags = sv.get("tags") or []
        tag = lambda k: next((t.split(":", 1)[1].strip() for t in tags if t.lower().startswith(k + ":")), None)  # noqa: E731
        frm, to = tag("from"), tag("to")
        for x in (frm, to):
            if x:
                systems[x] = {"name": x, "kind": "system"}
        out["integrations"].append({"ext_id": sv["name"], "name": sv["name"], "kind": "API", "via": "Kong", "from_system": frm, "to_system": to or sv.get("host"), "schedule": "On event", "owner": tag("owner"),
                                    "properties": {"host": sv.get("host"), "path": sv.get("path"), "tags": tags}})
    if cfg.get("log_url"):
        lc = base.Client(cfg["log_url"], {"Kong-Admin-Token": secrets.get("token") or ""})
        for e in (lc.get("").get("entries") or []):
            code = int(((e.get("response") or {}).get("status")) or 0)
            st = base.ts(e.get("started_at"))
            ms = ((e.get("latencies") or {}).get("request")) or 0
            out["runs"].append({"integration": (e.get("service") or {}).get("name") if isinstance(e.get("service"), dict) else e.get("service"), "ext_id": e.get("request_id") or f"{e.get('service')}-{e.get('started_at')}", "started": st, "ended": (st + ms / 1000) if st else None,
                                "status": "success" if 200 <= code < 400 else "failed", "duration_s": ms / 1000, "volume": (e.get("request") or {}).get("size"), "error": f"HTTP {code} from upstream" if code >= 500 else f"HTTP {code}" if code >= 400 else None})
    out["systems"] = list(systems.values())
    return out


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    return _kong(cfg, secrets, now) if (cfg.get("style") or "apim").lower() == "kong" else _apim(cfg, secrets, now)
