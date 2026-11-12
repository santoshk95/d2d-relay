"""Warehouse connections, configured tables, live queries and extracts (platform plan, phase 3).

Connections are personal: every endpoint here works on the asking person's own connections only. Project extract
endpoints sit under /api/projects/{id}/... so auth.middleware applies the dashboard's view / edit rules first.

D2D Relay: a connection is used (added, tested, browsed, queried, pulled from, signed in again) only while PASDACS has
its connector switched on for the organisation (orgs.require_connector, use=True below). Listing, sharing, disabling and
removing a connection always work, so an organisation can tidy up after a connector was switched off.
"""
import asyncio
import json
import time
import traceback
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import auth, connectors, db, orgs, store

router = APIRouter()


def _me() -> str:
    return auth.who() or db.ADMIN_ID


def _mine(cid: str, use: bool = False) -> dict:
    """A connection this person may use: their own or one shared with them (P10). use=True: it is about to be used,
    so its connector must be switched on for the organisation (D2D Relay)."""
    try:
        c = connectors.connection(cid, _me())
    except connectors.ConnectorError:
        raise HTTPException(404, "Unknown connection")
    if use:
        orgs.require_connector(c["kind"])
    c["_who"] = _me()
    return c


def _owned(cid: str, admin_ok: bool = False, use: bool = False) -> dict:
    _mine(cid, use)
    try:
        return connectors.owned(cid, _me(), admin_ok)
    except connectors.ConnectorError as e:
        raise HTTPException(403, str(e))


def _fail(e: Exception) -> HTTPException:
    if isinstance(e, connectors.Reconsent):
        return HTTPException(409, f"{e} (Connections > Renew sign-in)")
    if isinstance(e, connectors.sdk.ScopeError):
        return HTTPException(403, str(e))
    return HTTPException(400, str(e))


def _vocab() -> dict:
    return {"categories": [{"id": i, "name": n} for i, n in connectors.CATEGORIES], "signin": connectors.SIGNIN, "scopes": connectors.SCOPES,
            "sharing": connectors.SHARING}


@router.get("/api/connectors")
def connector_kinds():
    """The connectors this organisation may add connections for (D2D Relay: the ones PASDACS switched on)."""
    kinds = {k: v for k, v in connectors.kinds_public().items() if orgs.connector_on(k)}
    return {"kinds": kinds, "guardrails": connectors.guardrails(), **_vocab()}


@router.get("/api/connections")
def my_connections():
    return {"connections": [{**c, "allowed": orgs.connector_on(c["kind"])} for c in connectors.mine(_me())], **_vocab()}


class ConnectionBody(BaseModel):
    kind: str | None = None
    name: str | None = None
    auth_mode: str | None = None
    config: dict = {}
    secrets: dict = {}
    # P10: what it may do, who may use it
    scope: str | None = None
    limits: str | None = None
    sharing: str | None = None
    category: str | None = None


@router.post("/api/connections")
def add_connection(body: ConnectionBody):
    orgs.require_connector(body.kind)
    try:
        return connectors.save(_me(), body.model_dump())
    except connectors.ConnectorError as e:
        raise _fail(e)


@router.patch("/api/connections/{cid}")
def change_connection(cid: str, body: ConnectionBody):
    _owned(cid, use=True)
    try:
        return connectors.save(_me(), body.model_dump(), cid)
    except connectors.ConnectorError as e:
        raise _fail(e)


@router.delete("/api/connections/{cid}")
def remove_connection(cid: str):
    _owned(cid, admin_ok=True)
    connectors.remove(cid, _me())
    return my_connections()


@router.post("/api/connections/{cid}/test")
async def test_connection(cid: str):
    c = _mine(cid, use=True)
    try:
        return await asyncio.to_thread(connectors.test, c)
    except connectors.ConnectorError as e:
        raise _fail(e)


# ---------------------------------------------------------------- P10: scope, sharing, enable / disable, renew, used by, objects, guarded writes

class ScopeBody(BaseModel):
    scope: str
    limits: str | None = None


@router.put("/api/connections/{cid}/scope")
def set_scope(cid: str, body: ScopeBody):
    _owned(cid)
    try:
        return connectors.set_scope(cid, _me(), body.scope, body.limits)
    except connectors.ConnectorError as e:
        raise _fail(e)


class SharingBody(BaseModel):
    sharing: str


@router.put("/api/connections/{cid}/sharing")
def set_sharing(cid: str, body: SharingBody):
    _owned(cid, admin_ok=True)
    try:
        return connectors.set_sharing(cid, _me(), body.sharing)
    except connectors.ConnectorError as e:
        raise _fail(e)


@router.post("/api/connections/{cid}/disable")
def disable_connection(cid: str):
    _owned(cid, admin_ok=True)
    return connectors.set_enabled(cid, _me(), False)


@router.post("/api/connections/{cid}/enable")
def enable_connection(cid: str):
    _owned(cid, admin_ok=True, use=True)
    return connectors.set_enabled(cid, _me(), True)


class RenewBody(BaseModel):
    secrets: dict = {}


@router.post("/api/connections/{cid}/renew")
def renew_connection(cid: str, body: RenewBody | None = None):
    _owned(cid, use=True)
    try:
        return connectors.renew(cid, _me(), body.secrets if body else None)
    except connectors.ConnectorError as e:
        raise _fail(e)


@router.get("/api/connections/{cid}/used-by")
def connection_used_by(cid: str):
    _mine(cid)
    return {"used_by": connectors.used_by(cid)}


class ReadBody(BaseModel):
    object: str
    limit: int = 100


@router.post("/api/connections/{cid}/read")
async def read_object(cid: str, body: ReadBody):
    """One object of a connected platform, read-only (an SDK adapter's read; a warehouse table as a guarded query)."""
    c = _mine(cid, use=True)
    try:
        return await asyncio.to_thread(connectors.read_object, c, body.object, _me(), max(1, min(body.limit, 1000)))
    except connectors.ConnectorError as e:
        raise _fail(e)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"The platform said: {str(e).splitlines()[0][:300]}")


class WriteBody(BaseModel):
    object: str
    payload: dict
    what: str | None = None


@router.post("/api/connections/{cid}/write", status_code=202)
def request_write(cid: str, body: WriteBody):
    """Never a direct write: the scope must allow it and a checkpoint opens for a named person (Validation queue);
    the adapter writes when it is accepted."""
    c = _mine(cid, use=True)
    try:
        cp = connectors.request_write(c, body.object, body.payload, _me(), what=body.what)
    except (connectors.ConnectorError, connectors.sdk.ScopeError) as e:
        raise _fail(e)
    return {"checkpoint": cp, "written": False, "message": "Waiting for a person's approval in the Validation queue."}


@router.get("/api/connections/{cid}/oauth/start")
def connection_signin(cid: str, request: Request):
    try:
        _owned(cid, use=True)
    except HTTPException as e:                  # a browser navigation: back to Connections with the reason
        return RedirectResponse("/#/connections?error=" + quote(str(e.detail)), 303)
    try:
        return RedirectResponse(connectors.oauth_start(cid, _me(), str(request.base_url)), 303)
    except connectors.ConnectorError as e:
        return RedirectResponse("/#/connections?error=" + quote(str(e)), 303)


@router.get("/auth/connector/callback")
def connection_signin_done(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return RedirectResponse("/#/connections?error=" + quote(error_description or error), 303)
    try:
        cid, uid = connectors.oauth_callback(state, code, str(request.base_url))
    except (connectors.ConnectorError, httpx.HTTPError) as e:
        return RedirectResponse("/#/connections?error=" + quote(str(e)), 303)
    me = auth.current.get()
    if me and me["id"] != uid:           # signed in to D2D as someone else meanwhile: nothing leaks either way
        return RedirectResponse("/#/connections?error=" + quote("Signed in as another person."), 303)
    return RedirectResponse(f"/#/connections?connected={cid}", 303)


@router.get("/api/connections/{cid}/browse")
async def browse_connection(cid: str, q: str = ""):
    c = _mine(cid, use=True)
    try:
        return {"tables": await asyncio.to_thread(connectors.browse, c, q)}
    except (connectors.ConnectorError, connectors.sdk.ScopeError) as e:
        raise _fail(e)
    except Exception as e:  # noqa: BLE001 - the warehouse's message helps the person
        raise HTTPException(400, f"The warehouse said: {str(e).splitlines()[0][:300]}")


class Tables(BaseModel):
    objects: list[str]


@router.put("/api/connections/{cid}/tables")
def configure_tables(cid: str, body: Tables):
    c = _owned(cid, use=True)
    try:
        return connectors.set_tables(c, body.objects)
    except connectors.ConnectorError as e:
        raise _fail(e)


class Query(BaseModel):
    sql: str


@router.post("/api/connections/{cid}/query")
async def live_query(cid: str, body: Query):
    """A guarded live query (Ask D's engine): read-only, row limit, timeout, BigQuery scan limit."""
    c = _mine(cid, use=True)
    try:
        return await asyncio.to_thread(connectors.query, c, body.sql, _me())
    except connectors.ConnectorError as e:
        raise _fail(e)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"The warehouse said: {str(e).splitlines()[0][:300]}")


# ---------------------------------------------------------------- a dashboard's extracts

@router.get("/api/projects/{pid}/extracts")
def project_extracts(pid: str):
    st = store.load(pid)
    m = connectors.manifest(store.project_dir(pid))
    return {"extracts": [{"file": f, **{k: v for k, v in e.items() if k != "connection"}, "native": connectors.native_pbip(e.get("kind"))} for f, e in m.items()],
            "schedule": st.get("extract_schedule") or {"daily": False, "hour_utc": 5},
            "can_refresh": all(db.one("SELECT 1 FROM connections WHERE id = ? AND owner_id = ?", (e["connection_id"], _me()))
                               for e in m.values()) if m else False}


@router.post("/api/projects/{pid}/extracts/refresh")
async def refresh_extracts(pid: str):
    d = store.project_dir(pid)
    for e in connectors.manifest(d).values():          # D2D Relay: every source's connector must still be switched on
        orgs.require_connector(e.get("kind"))
    try:
        done = await asyncio.to_thread(connectors.refresh_project, d, _me())
    except connectors.ConnectorError as e:
        raise _fail(e)
    from . import worker
    worker.refresh_files(pid)
    store.log(pid, {"kind": "user", "stage": "extract", "text": f"Refreshed {len(done)} warehouse table(s)"})
    worker.app_note(pid, "extract", "Warehouse data refreshed: " + ", ".join(f"{e['object']} {e['rows']:,} rows" for e in done)
                    + ". Run the review gates again to check the new data.", "ok")
    return project_extracts(pid)


class Schedule(BaseModel):
    daily: bool
    hour_utc: int = 5


@router.put("/api/projects/{pid}/extracts/schedule")
def schedule_extracts(pid: str, body: Schedule):
    if not 0 <= body.hour_utc <= 23:
        raise HTTPException(400, "Hour must be 0-23 (UTC).")
    store.update(pid, extract_schedule={"daily": body.daily, "hour_utc": body.hour_utc})
    db.audit("extract.schedule", pid, body.model_dump(), _me())
    return project_extracts(pid)


async def scheduler() -> None:
    """Daily extract refreshes, run with each connection's owner's stored login (offline access). A connection
    whose sign-in no longer works pauses the refresh and says so on the dashboard instead of failing silently."""
    from . import worker
    while True:
        await asyncio.sleep(300)
        try:
            hour, today = time.gmtime().tm_hour, time.strftime("%Y-%m-%d", time.gmtime())
            for _t in db.each_tenant():                 # P17: every tenant's dashboards
                for p in store.all_projects():
                    st = store.load(p["id"])
                    sch = st.get("extract_schedule") or {}
                    if not sch.get("daily") or sch.get("hour_utc") != hour or st.get("extract_last_day") == today:
                        continue
                    store.update(p["id"], extract_last_day=today)
                    off = sorted({orgs.connector_label(e.get("kind")) for e in connectors.manifest(store.project_dir(p["id"])).values()
                                  if not orgs.connector_on(e.get("kind"))})
                    if off:                             # D2D Relay: PASDACS switched the connector off for this organisation
                        worker.app_note(p["id"], "extract", f"Scheduled refresh paused: {', '.join(off)} is switched off for "
                                        "this organisation. Ask PASDACS on the Connections page.", "warn")
                        continue
                    try:
                        done = await asyncio.to_thread(connectors.refresh_project, store.project_dir(p["id"]), None, False)
                        worker.refresh_files(p["id"])
                        worker.app_note(p["id"], "extract", f"Scheduled refresh: {len(done)} warehouse table(s) pulled again.", "ok")
                    except connectors.ConnectorError as e:
                        worker.app_note(p["id"], "extract", f"Scheduled refresh paused: {e}", "warn")
                        db.audit("extract.paused", p["id"], {"error": str(e)[:300]}, "system")
        except Exception:  # noqa: BLE001
            traceback.print_exc()


# ---------------------------------------------------------------- administration (Admins only: /api/admin)

class DataAdmin(BaseModel):
    oauth: dict = {}
    secrets: dict = {}
    guardrails: dict | None = None


@router.get("/api/admin/data")
def admin_data(request: Request):
    apps = connectors.oauth_apps()
    from . import secrets_store
    return {"oauth": {k: {**apps.get(k, {}), "has_secret": secrets_store.get("org", f"connector_oauth:{k}:client_secret") is not None,
                          "label": connectors.KINDS[k]["label"]} for k in connectors.OAUTH},
            "redirect_uri": connectors.redirect_uri(str(request.base_url)), "guardrails": connectors.guardrails(),
            "connections": db.q("SELECT c.id, c.kind, c.name, c.status, c.last_used, c.scope, c.sharing, c.enabled, u.name AS owner FROM connections c "
                                "JOIN users u ON u.id = c.owner_id ORDER BY c.created")}


@router.put("/api/admin/data")
def admin_set_data(body: DataAdmin, request: Request):
    try:
        connectors.save_oauth_apps(body.oauth, body.secrets, _me())
        if body.guardrails:
            connectors.save_guardrails(body.guardrails, _me())
    except (connectors.ConnectorError, ValueError) as e:
        raise HTTPException(400, str(e))
    return admin_data(request)
