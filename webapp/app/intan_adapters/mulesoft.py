"""MuleSoft Anypoint Platform — Runtime Manager (CloudHub applications) and Anypoint Analytics events (requests per
API with status code and response time, the "runs" of an always-on application). Signs in with a connected app
(client credentials → token) or a ready token."""
from __future__ import annotations

import time

from . import base

KIND, LABEL, GROUP = "mulesoft", "MuleSoft Anypoint", "Integration platform"
AUTH = "connected app (client credentials) or bearer token"
DOCS = "Anypoint: POST /accounts/api/v2/oauth2/token, GET /cloudhub/api/v2/applications, GET /analytics/1.0/{org}/environments/{env}/events"
CONFIG = [{"name": "url", "label": "Anypoint base URL", "hint": "https://anypoint.mulesoft.com", "required": True},
          {"name": "org", "label": "Organisation id", "required": True}, {"name": "env", "label": "Environment id", "required": True}]
SECRETS = [{"name": "client_id", "label": "Connected app client id"}, {"name": "client_secret", "label": "Client secret (or a token)"}]


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    now = now or time.time()
    c = base.Client(cfg["url"])
    if secrets.get("client_id"):
        tok = c.post("/accounts/api/v2/oauth2/token", {"grant_type": "client_credentials", "client_id": secrets["client_id"], "client_secret": secrets.get("client_secret") or ""})
        c.headers.update(base.Client.bearer(tok.get("access_token") or ""))
    else:
        c.headers.update(base.Client.bearer(secrets.get("client_secret") or ""))
    c.headers["X-ANYPNT-ENV-ID"] = cfg["env"]; c.headers["X-ANYPNT-ORG-ID"] = cfg["org"]
    out = base.empty()
    systems = {}
    apps = c.get("/cloudhub/api/v2/applications")
    for a in (apps if isinstance(apps, list) else apps.get("data") or []):
        props = a.get("properties") or {}
        frm, to = props.get("source.system") or base.arrow(a.get("description") or "")[0], props.get("target.system") or base.arrow(a.get("description") or "")[1]
        for s in (frm, to):
            if s:
                systems[s] = {"name": s, "kind": "system"}
        out["integrations"].append({"ext_id": a["domain"], "name": a.get("description") and base.arrow(a["description"])[0] and a["description"].split(";")[0].strip() or a["domain"], "kind": "API" if "api" in a["domain"] else "Integration", "via": "MuleSoft",
                                    "from_system": frm, "to_system": to, "schedule": props.get("schedule") or "On event", "owner": props.get("owner") or base.owner_from([a.get("description")]),
                                    "properties": {"status": a.get("status"), "runtime": (a.get("muleVersion") or {}).get("version") if isinstance(a.get("muleVersion"), dict) else a.get("muleVersion"), "workers": (a.get("workers") or {}).get("amount")}})
    ev = c.get(f"/analytics/1.0/{cfg['org']}/environments/{cfg['env']}/events", {"format": "json", "duration": "42d", "fields": "Timestamp,API Name,Status Code,Response Time,Message ID"})
    for e in (ev if isinstance(ev, list) else ev.get("events") or []):
        code = int(e.get("Status Code") or 0)
        st = base.ts(e.get("Timestamp"))
        out["runs"].append({"integration": e.get("API Name"), "ext_id": e.get("Message ID"), "started": st, "ended": (st + (e.get("Response Time") or 0) / 1000) if st else None,
                            "status": "success" if 200 <= code < 400 else "failed", "duration_s": (e.get("Response Time") or 0) / 1000, "volume": 1, "error": f"HTTP {code}" + (f" from {e.get('Backend') or 'upstream'}" if code >= 500 else "") if code >= 400 else None})
    try:
        lic = c.get(f"/accounts/api/organizations/{cfg['org']}/entitlements") or {}
        vc = (lic.get("vCoresProduction") or {})
        if vc.get("assigned") and vc.get("usage") is not None:
            out["signals"].append({"kind": "licence", "integration": None, "text": f"vCore usage at {round(100 * vc['usage'] / vc['assigned'])} % of the subscription", "value": vc["usage"], "limit": vc["assigned"], "due": None})
    except (base.SourceError, base.AuthError):
        pass
    out["systems"] = list(systems.values())
    return out
