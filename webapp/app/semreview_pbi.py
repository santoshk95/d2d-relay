"""Semantic Review (item 55): reading semantic models from the Power BI service (Microsoft Fabric) with an
organisation's own Microsoft Entra app.

The organisation registers an app in its own Entra ID (Azure AD), gives it a client secret, adds it to the workspaces
to review, and lets service principals use the Fabric APIs (Fabric admin portal, Developer settings). An owner enters
the tenant, the app's client id and the secret under Semantic Review; the secret is kept encrypted with the
workspace's other secrets (secrets_store, scope "org") and never shown again.

What D2D Relay asks Microsoft for, all read-only:
  - a token: POST login.microsoftonline.com/<tenant>/oauth2/v2.0/token (client credentials)
  - the workspaces and semantic models the app can see (Fabric REST API)
  - a model's definition: POST .../semanticModels/<id>/getDefinition?format=TMSL (a long-running operation, polled at
    the operation address Fabric gives, which must be on the Fabric API's own host). Power BI shows a model's DAX
    only to identities with write permission on it (Contributor or higher on the workspace), so the review needs that.
    When getDefinition is refused, the INFO.VIEW functions are tried through executeQueries (Power BI REST API).
  - the values of the measures that disagree (executeQueries, EVALUATE ROW (...)), to show the numbers side by side.

The addresses are fixed (D2D_ENTRA_LOGIN, D2D_FABRIC_API and D2D_POWERBI_API exist for the test stack's stand-in);
workspace and model ids must be GUIDs, so nothing a person types decides where D2D Relay connects.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

import httpx

from . import db, secrets_store

LOGIN = os.environ.get("D2D_ENTRA_LOGIN", "https://login.microsoftonline.com").rstrip("/")
FABRIC = os.environ.get("D2D_FABRIC_API", "https://api.fabric.microsoft.com").rstrip("/")
POWERBI = os.environ.get("D2D_POWERBI_API", "https://api.powerbi.com").rstrip("/")
FABRIC_SCOPE = os.environ.get("D2D_FABRIC_SCOPE", "https://api.fabric.microsoft.com/.default")
POWERBI_SCOPE = os.environ.get("D2D_POWERBI_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TENANT = re.compile(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Za-z0-9][A-Za-z0-9-]{0,62}(\.[A-Za-z0-9][A-Za-z0-9-]{0,62})+)$")
META = "semreview_pbi"
SECRET = "semreview:pbi:client_secret"
MAX_BODY = 64 * 1024 * 1024
LRO_WAIT_S = 180
_tokens: dict[tuple, tuple[str, float]] = {}
_lock = threading.Lock()


class PbiError(Exception):
    """Shown to the person as it is."""


# ---------------------------------------------------------------- settings

def settings() -> dict | None:
    try:
        s = json.loads(db.meta(META) or "null")
    except ValueError:
        return None
    return s if isinstance(s, dict) and s.get("client_id") else None


def public() -> dict:
    """What the screens may see: never the secret."""
    s = settings()
    if not s:
        return {"configured": False}
    cid = s["client_id"]
    return {"configured": True, "tenant": s["tenant"], "client_id": cid[:8] + "..." + cid[-4:], "saved": s.get("saved"),
            "has_secret": secrets_store.get("org", SECRET) is not None}


def save(tenant: str, client_id: str, secret: str | None, who: str) -> dict:
    tenant, client_id, secret = (tenant or "").strip(), (client_id or "").strip(), (secret or "").strip()
    if not TENANT.match(tenant):
        raise PbiError("The tenant is your Microsoft Entra tenant id (a GUID) or its domain, for example contoso.onmicrosoft.com.")
    if not GUID.match(client_id):
        raise PbiError("The client id is the app's Application (client) id, a GUID.")
    old = settings()
    if not secret and not (old and secrets_store.get("org", SECRET)):
        raise PbiError("Enter the app's client secret.")
    if secret and (len(secret) > 512 or any(ord(ch) < 32 for ch in secret)):
        raise PbiError("That does not look like a client secret.")
    if secret:
        secrets_store.put("org", SECRET, secret, who)
    db.set_meta(META, json.dumps({"tenant": tenant, "client_id": client_id, "saved": time.time(), "by": who}))
    with _lock:
        for k in [k for k in _tokens if k[0] == db.tenant()]:
            _tokens.pop(k, None)
    db.audit("semreview.pbi_save", None, {"tenant": tenant, "client_id": client_id[:8]}, who)
    return public()


def remove(who: str) -> None:
    secrets_store.delete("org", SECRET, who)
    db.run("DELETE FROM meta WHERE key = ?", (META,))
    with _lock:
        for k in [k for k in _tokens if k[0] == db.tenant()]:
            _tokens.pop(k, None)
    db.audit("semreview.pbi_remove", None, None, who)


# ---------------------------------------------------------------- HTTP

def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(30, read=90), follow_redirects=False,
                        headers={"User-Agent": "D2D-Relay-Semantic-Review/1.0"})


def _read(r: httpx.Response) -> dict:
    if len(r.content) > MAX_BODY:
        raise PbiError("The Power BI service sent more than the review reads.")
    try:
        out = r.json()
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {"value": out}


def _error(r: httpx.Response, what: str) -> PbiError:
    body = _read(r) if r.content else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(body.get("errorCode") or err.get("code") or "")
    if r.status_code in (401,):
        return PbiError(f"Microsoft did not accept the app for {what} (401). Check the tenant, the client id and the secret.")
    if r.status_code == 403 or code in ("Unauthorized", "InsufficientPrivileges", "PowerBINotAuthorizedException"):
        return PbiError(f"The app may not {what} (403). Add the app to the workspace as Contributor (or higher), and switch on "
                        "\"Service principals can use Fabric APIs\" in the Fabric admin portal.")
    if r.status_code == 404:
        return PbiError(f"Not found when trying to {what} (404): the workspace or model is gone, or the app cannot see it.")
    if r.status_code == 429:
        return PbiError("The Power BI service is busy for this app (429). Try again in a few minutes.")
    detail = str(body.get("message") or err.get("message") or "")
    return PbiError(f"The Power BI service could not {what} ({r.status_code}{', ' + code if code else ''}){': ' + detail[:200] if detail else ''}.")


def token(scope: str = FABRIC_SCOPE) -> str:
    s = settings()
    if not s:
        raise PbiError("Connect Power BI first: an owner enters your Entra app under Semantic Review.")
    key = (db.tenant(), s["tenant"], s["client_id"], scope)
    with _lock:
        hit = _tokens.get(key)
        if hit and hit[1] > time.time() + 60:
            return hit[0]
    secret = secrets_store.get("org", SECRET)
    if not secret:
        raise PbiError("The app's client secret is missing: an owner enters it again under Semantic Review.")
    try:
        with _client() as c:
            r = c.post(f"{LOGIN}/{s['tenant']}/oauth2/v2.0/token",
                       data={"grant_type": "client_credentials", "client_id": s["client_id"], "client_secret": secret, "scope": scope})
    except httpx.HTTPError as e:
        raise PbiError(f"Could not reach Microsoft's sign-in ({e.__class__.__name__}).") from e
    if r.status_code != 200:
        body = _read(r)
        err = str(body.get("error") or "")
        hint = {"invalid_client": "the client secret is wrong or has expired", "unauthorized_client": "the client id is not an app of that tenant",
                "invalid_request": "the tenant or the client id is not right"}.get(err, err or str(r.status_code))
        raise PbiError(f"Microsoft did not sign the app in: {hint}.")
    t = r.json()
    with _lock:
        _tokens[key] = (t["access_token"], time.time() + float(t.get("expires_in") or 3600))
    return t["access_token"]


def _get(url: str, what: str, scope: str = FABRIC_SCOPE) -> dict:
    try:
        with _client() as c:
            r = c.get(url, headers={"Authorization": f"Bearer {token(scope)}"})
    except httpx.HTTPError as e:
        raise PbiError(f"Could not reach the Power BI service ({e.__class__.__name__}).") from e
    if r.status_code != 200:
        raise _error(r, what)
    return _read(r)


def _check_id(v: str, what: str) -> str:
    if not GUID.match(v or ""):
        raise PbiError(f"That is not a {what} id.")
    return v


# ---------------------------------------------------------------- lists

def workspaces() -> list[dict]:
    out, url, pages = [], f"{FABRIC}/v1/workspaces", 0
    while url and pages < 20:
        body = _get(url, "list the workspaces")
        for w in body.get("value") or []:
            if GUID.match(str(w.get("id") or "")):
                out.append({"id": w["id"], "name": str(w.get("displayName") or w.get("name") or w["id"])[:200],
                            "type": w.get("type")})
        url = _same_host(body.get("continuationUri"))
        pages += 1
    return sorted(out, key=lambda w: w["name"].lower())


def models(wid: str) -> list[dict]:
    _check_id(wid, "workspace")
    out, url, pages = [], f"{FABRIC}/v1/workspaces/{wid}/semanticModels", 0
    while url and pages < 20:
        body = _get(url, "list the workspace's semantic models")
        for m in body.get("value") or []:
            if GUID.match(str(m.get("id") or "")):
                out.append({"id": m["id"], "name": str(m.get("displayName") or m["id"])[:200], "description": (m.get("description") or "")[:300]})
        url = _same_host(body.get("continuationUri"))
        pages += 1
    return sorted(out, key=lambda m: m["name"].lower())


def _same_host(url) -> str | None:
    """A next-page or operation address, only on the Fabric API's own host (never anywhere a reply points to)."""
    if not url or not isinstance(url, str):
        return None
    a, b = urlparse(url), urlparse(FABRIC)
    return url if a.scheme == b.scheme and a.netloc == b.netloc else None


# ---------------------------------------------------------------- one model

def definition(wid: str, mid: str) -> dict:
    """{path: bytes} of a model's definition (TMSL: model.bim), through Fabric's getDefinition."""
    _check_id(wid, "workspace")
    _check_id(mid, "semantic model")
    url = f"{FABRIC}/v1/workspaces/{wid}/semanticModels/{mid}/getDefinition?format=TMSL"
    try:
        with _client() as c:
            r = c.post(url, headers={"Authorization": f"Bearer {token()}"})
            if r.status_code == 202:
                where = _same_host(r.headers.get("Location")) or (
                    f"{FABRIC}/v1/operations/{r.headers.get('x-ms-operation-id')}" if GUID.match(r.headers.get("x-ms-operation-id") or "") else None)
                if not where:
                    raise PbiError("The Power BI service answered with an operation the review cannot follow.")
                deadline = time.time() + LRO_WAIT_S
                while True:
                    time.sleep(min(max(int(r.headers.get("Retry-After") or 2), 1), 10))
                    r = c.get(where, headers={"Authorization": f"Bearer {token()}"})
                    if r.status_code != 200:
                        raise _error(r, "read the model's definition")
                    state = str(_read(r).get("status") or "")
                    if state == "Succeeded":
                        r = c.get(where.rstrip("/") + "/result", headers={"Authorization": f"Bearer {token()}"})
                        break
                    if state in ("Failed", "Undefined"):
                        err = (_read(r).get("error") or {}).get("message") or "the operation failed"
                        raise PbiError(f"The Power BI service could not export the model: {str(err)[:200]}.")
                    if time.time() > deadline:
                        raise PbiError("The Power BI service took too long to export the model.")
    except httpx.HTTPError as e:
        raise PbiError(f"Could not reach the Power BI service ({e.__class__.__name__}).") from e
    if r.status_code != 200:
        raise _error(r, "read the model's definition")
    parts = {}
    for p in ((_read(r).get("definition") or {}).get("parts") or [])[:5000]:
        path = str(p.get("path") or "")
        if p.get("payloadType", "InlineBase64") != "InlineBase64" or not path:
            continue
        try:
            parts[path] = base64.b64decode(p.get("payload") or "", validate=False)
        except ValueError:
            continue
    if not parts:
        raise PbiError("The Power BI service sent an empty definition (DirectLake models and some others cannot be exported).")
    return parts


def dax_query(wid: str, mid: str, query: str) -> list[dict]:
    """One DAX query through the Power BI REST API (executeQueries): its rows."""
    _check_id(wid, "workspace")
    _check_id(mid, "semantic model")
    try:
        with _client() as c:
            r = c.post(f"{POWERBI}/v1.0/myorg/groups/{wid}/datasets/{mid}/executeQueries",
                       headers={"Authorization": f"Bearer {token(POWERBI_SCOPE)}"},
                       json={"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}})
    except httpx.HTTPError as e:
        raise PbiError(f"Could not reach the Power BI service ({e.__class__.__name__}).") from e
    if r.status_code != 200:
        raise _error(r, "run a query on the model")
    body = _read(r)
    res = (body.get("results") or [{}])[0]
    if res.get("error"):
        raise PbiError(f"Power BI refused the query: {str((res['error'] or {}).get('message') or res['error'])[:200]}")
    tables = res.get("tables") or [{}]
    return [{str(k).split("[", 1)[-1].rstrip("]"): v for k, v in row.items()} for row in (tables[0].get("rows") or [])[:20000]]


# INFO.VIEW.COLUMNS gives data types by their Power BI Desktop names; the review uses the model's (TMSL) names
VIEW_TYPES = {"text": "string", "whole number": "int64", "decimal number": "double", "fixed decimal number": "decimal",
              "date": "dateTime", "date/time": "dateTime", "datetime": "dateTime", "time": "dateTime", "true/false": "boolean",
              "binary": "binary", "int64": "int64", "double": "double", "decimal": "decimal", "string": "string", "boolean": "boolean"}


def info_view(wid: str, mid: str) -> dict:
    """The model through the INFO.VIEW functions (when getDefinition is refused). Power BI leaves the DAX out for
    identities without write permission: then this says so."""
    measures = dax_query(wid, mid, "EVALUATE INFO.VIEW.MEASURES()")
    if measures and not any((m.get("Expression") or "").strip() for m in measures):
        raise PbiError("Power BI did not show the measures' DAX: it does so only to identities with write permission. Add the app to "
                       "the workspace as Contributor (or higher).")
    tables = dax_query(wid, mid, "EVALUATE INFO.VIEW.TABLES()")
    columns = dax_query(wid, mid, "EVALUATE INFO.VIEW.COLUMNS()")
    rels = dax_query(wid, mid, "EVALUATE INFO.VIEW.RELATIONSHIPS()")
    by_table: dict[str, dict] = {}
    for t in tables:
        n = str(t.get("Name") or "")
        if n:
            by_table[n] = {"name": n, "hidden": bool(t.get("IsHidden")), "description": t.get("Description"), "columns": [],
                           "expression": t.get("Expression") if str(t.get("Expression") or "").strip() else None}
    for c in columns:
        if "rownumber" in (str(c.get("Type") or "") + str(c.get("DataCategory") or "")).replace(" ", "").lower():
            continue                                          # every table's row-number column
        t = by_table.setdefault(str(c.get("Table") or ""), {"name": str(c.get("Table") or ""), "hidden": False, "description": None,
                                                            "columns": [], "expression": None})
        dt = str(c.get("DataType") or "").strip().lower()
        t["columns"].append({"name": str(c.get("Name") or ""), "type": VIEW_TYPES.get(dt, dt) or None,
                             "summarize": str(c.get("SummarizeBy") or "").lower() or None, "format": c.get("FormatString"),
                             "hidden": bool(c.get("IsHidden")), "expression": c.get("Expression") or None,
                             "category": c.get("DataCategory"), "description": c.get("Description")})
    out_rel = []
    for r in rels:
        fc, tc = str(r.get("FromColumn") or ""), str(r.get("ToColumn") or "")
        out_rel.append({"from": [r.get("FromTable"), fc.split("[")[-1].rstrip("]") if "[" in fc else fc],
                        "to": [r.get("ToTable"), tc.split("[")[-1].rstrip("]") if "[" in tc else tc],
                        "active": r.get("IsActive") is not False,
                        "cross": "both" if "both" in str(r.get("CrossFilteringBehavior") or "").lower() else "single",
                        "card": f"{'1' if str(r.get('FromCardinality')).lower() == 'one' else 'M'}:{'M' if str(r.get('ToCardinality')).lower() == 'many' else '1'}"})
    return {"tables": [t for t in by_table.values() if t["name"]],
            "measures": [{"table": m.get("Table"), "name": m.get("Name"), "expression": m.get("Expression") or "",
                          "format": m.get("FormatString"), "description": m.get("Description"), "folder": m.get("DisplayFolder"),
                          "hidden": bool(m.get("IsHidden"))} for m in measures if m.get("Name")],
            "relationships": out_rel, "calc_groups": []}


def read_model(wid: str, mid: str, name: str) -> dict:
    """A semantic model of the service as the review's neutral model."""
    from genbi_kit.semreview import model as M
    try:
        parts = definition(wid, mid)
        m = M.tmdl_parts({p.split("/")[-1] if p.endswith("model.bim") else p: b for p, b in parts.items()}, name)
        how = "definition"
    except PbiError as first:
        try:
            m = info_view(wid, mid)
            how = "info.view"
        except PbiError:
            raise first from None
    m["name"] = name
    m["source"] = {"kind": "powerbi", "workspace": wid, "model": mid, "via": how}
    return m


def _dax_name(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def values(wid: str, mid: str, measures: list[str]) -> dict[str, object]:
    """Each measure's value over the whole model (no filters): EVALUATE ROW (...), 20 measures a query; a query that
    fails is asked again one measure at a time, so one broken measure does not hide the others."""
    out: dict[str, object] = {}
    names = list(dict.fromkeys(measures))[:60]
    for i in range(0, len(names), 20):
        chunk = names[i:i + 20]
        q = "EVALUATE ROW ( " + ", ".join(f'"v{j}", {_dax_name(n)}' for j, n in enumerate(chunk)) + " )"
        try:
            rows = dax_query(wid, mid, q)
            row = rows[0] if rows else {}
            for j, n in enumerate(chunk):
                out[n] = row.get(f"v{j}")
        except PbiError:
            for n in chunk:
                try:
                    rows = dax_query(wid, mid, f'EVALUATE ROW ( "v", {_dax_name(n)} )')
                    out[n] = (rows[0] if rows else {}).get("v")
                except PbiError as e:
                    out[n] = {"error": str(e)[:200]}
    return out
