"""Process mining platforms for Process mining & discovery: Celonis (the Data Integration API's data pool and data model:
its load history and its activity table as the event log; the Data Push API for loading one after its own approval) and SAP Signavio Process Intelligence (its
processes and their event logs, read-only) as Connector SDK adapters - one adapter + one mock each
(tests/mocklab/sims/process.py: `celonis`, `signavio-pi`). UiPath Process Mining and Power Automate Process Mining
come in as their CSV exports (uploads), as do SAP and Oracle extracts.

Read-only by default: `test` signs in and lists what the account sees, `list_objects` the event logs on offer,
`read` a page of events, `events` every event of one (paged through). Celonis writes only through
connectors.request_write - after a named person accepted that very event log - with the approval's id in an
X-Relay-Approval header.
"""
from __future__ import annotations

import csv
import io

from .. import connectors
from .. import connectors_sdk as sdk
from . import _w4
from .brd_trackers import _call, _secret

MAX_EVENTS = 200_000


class Celonis(sdk.Adapter):
    """Celonis Data Integration API: the data pool and its data model (with the load history), the model's activity
    table as the event log, and the Data Push API (a job, the CSV as an upserted chunk, the job executed) to load an
    event log after its own approval."""
    kind = "celonis"
    label = "Celonis"
    category = "integration"
    signin = ["api_key"]
    fields = [("team_url", "Team URL (https://your-team.eu-1.celonis.cloud)", True), ("data_pool_id", "Data pool id", True), ("data_model_id", "Data model id", True)]
    secrets = {"api_key": ["api_key"]}
    can_write = True

    def _h(self, c):
        return {"Authorization": f"Bearer {_secret(c, 'api_key')}"}

    def _base(self, c):
        return (c["config"].get("team_url") or "").rstrip("/")

    def _ids(self, c):
        return (c["config"].get("data_pool_id") or "").strip(), (c["config"].get("data_model_id") or "").strip()

    def _model(self, c) -> dict:
        pool, dm = self._ids(c)
        pools = _call("Celonis", "GET", f"{self._base(c)}/integration/api/pools", headers=self._h(c)).json() or []
        if pool not in {p.get("id") for p in pools}:
            raise connectors.ConnectorError(f"Celonis has no data pool {pool!r} this key can read.")
        dms = _call("Celonis", "GET", f"{self._base(c)}/integration/api/pools/{pool}/data-models", headers=self._h(c)).json() or []
        m = next((d for d in dms if d.get("id") == dm), None)
        if not m:
            raise connectors.ConnectorError(f"The data pool has no data model {dm!r}.")
        return {**m, "pool_name": next(p.get("name") for p in pools if p.get("id") == pool)}

    def test(self, c: dict) -> dict:
        m = self._model(c)
        return {"ok": True, "sees": f"data pool {m['pool_name']}, data model {m.get('name')} (last load {str(m.get('lastLoadStatus') or '-').lower()})", "scope": c.get("scope")}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        m = self._model(c)
        return [{"object": m["id"], "type": f"data model {m.get('name')}"}] if search.lower() in (m.get("name") or "").lower() else []

    def loads(self, c: dict, limit: int = 10) -> list[dict]:
        """The data model's load history, newest first: a failed load is the first thing to know about a log."""
        pool, dm = self._ids(c)
        return _call("Celonis", "GET", f"{self._base(c)}/integration/api/pools/{pool}/data-models/{dm}/load-history?limit={int(limit)}", headers=self._h(c)).json().get("loads") or []

    def _page(self, c, off, size):
        pool, dm = self._ids(c)
        return _call("Celonis", "GET", f"{self._base(c)}/integration/api/pools/{pool}/data-models/{dm}/activities?offset={off}&limit={size}", headers=self._h(c)).json()

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        d = self._page(c, 0, min(limit, 1000))
        rows = d.get("rows") or []
        return {"columns": list(rows[0].keys()) if rows else [], "rows": rows, "row_count": d.get("total") or len(rows)}

    def events(self, c: dict, obj: str | None = None) -> tuple[list[str], list[dict]]:
        rows, off = [], 0
        while len(rows) < MAX_EVENTS:
            d = self._page(c, off, 1000)
            page = d.get("rows") or []
            rows += page
            off += len(page)
            if not page or not d.get("hasMore"):
                break
        cols = list(dict.fromkeys(k for r in rows[:50] for k in r))
        return cols, rows

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        try:
            out = self._push(c, obj, payload, approval)
        except Exception as e:
            _w4.push_written(approval, {"error": str(e)}, ok=False)
            raise
        _w4.push_written(approval, out, ok=True)
        return out

    def _push(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        """Data Push API: a job for the table, the CSV as an upserted chunk, then the job executed - the file is the one
        approved (its sha256 is checked first)."""
        if obj != "eventlog":
            raise sdk.ScopeError(f"Celonis: Relay loads event logs, not {obj!r}")
        pool, _ = self._ids(c)
        _, item, _ = _w4.payload_from(payload)
        from .. import store
        f = store.root() / item / "outputs" / str(payload.get("file") or "")
        if not f.is_file():
            raise connectors.ConnectorError("The approved event log file is not in the work item's outputs any more.")
        data = f.read_bytes()
        import hashlib
        if payload.get("sha256") and hashlib.sha256(data).hexdigest() != payload["sha256"]:
            raise sdk.ScopeError("The event log changed after it was approved; nothing was loaded.")
        h = {**self._h(c), "X-Relay-Approval": approval}
        base = f"{self._base(c)}/integration/api/v1/data-push/{pool}/jobs/"
        job = _call("Celonis", "POST", base, headers=h, json={"targetName": payload.get("table") or "RELAY_EVENT_LOG", "type": "REPLACE", "fileType": "CSV", "dataPoolId": pool}, ok=(200, 201)).json()
        import httpx
        with httpx.Client(timeout=60, headers=h) as cl:
            r = cl.post(f"{base}{job['id']}/chunks/upserted", files={"file": (f.name, data, "text/csv")})
        if r.status_code >= 400:
            raise connectors.ConnectorError(f"Celonis refused the event log chunk ({r.status_code}).")
        done = _call("Celonis", "POST", f"{base}{job['id']}", headers=h, json={}, ok=(200, 201)).json()
        rows = max(0, data.count(b"\n") - 1)
        return {"ok": True, "created": [{"ref": "eventlog", "key": job["id"], "url": f"{self._base(c)}/integration/ui/pools/{pool}"}], "rows": rows, "status": done.get("status"), "errors": []}


class SignavioPI(sdk.Adapter):
    kind = "signavio_pi"
    label = "SAP Signavio Process Intelligence"
    category = "integration"
    signin = ["api_key"]
    fields = [("base_url", "Signavio URL (https://editor.signavio.com)", True), ("workspace", "Workspace id", True), ("process", "Process id (default: the first one)", False)]
    secrets = {"api_key": ["api_key"]}
    can_write = False

    def _h(self, c):
        return {"Authorization": f"Bearer {_secret(c, 'api_key')}", "x-signavio-workspace": (c["config"].get("workspace") or "").strip()}

    def _base(self, c):
        return (c["config"].get("base_url") or "").rstrip("/")

    def test(self, c: dict) -> dict:
        ps = _call("Signavio PI", "GET", f"{self._base(c)}/pi/api/v1/processes", headers=self._h(c)).json().get("processes") or []
        return {"ok": True, "sees": f"{len(ps)} process(es) in workspace {c['config'].get('workspace')}", "scope": c.get("scope")}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        ps = _call("Signavio PI", "GET", f"{self._base(c)}/pi/api/v1/processes", headers=self._h(c)).json().get("processes") or []
        return [{"object": p.get("id"), "type": p.get("name") or "process"} for p in ps if search.lower() in (p.get("name") or "").lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        d = _call("Signavio PI", "GET", f"{self._base(c)}/pi/api/v1/processes/{obj}/events?offset=0&limit={min(limit, 1000)}", headers=self._h(c)).json()
        rows = d.get("events") or []
        return {"columns": sorted({k for r in rows for k in r}), "rows": rows, "row_count": d.get("total") or len(rows)}

    def events(self, c: dict, obj: str | None = None) -> tuple[list[str], list[dict]]:
        rows, off = [], 0
        while len(rows) < MAX_EVENTS:
            d = _call("Signavio PI", "GET", f"{self._base(c)}/pi/api/v1/processes/{obj}/events?offset={off}&limit=1000", headers=self._h(c)).json()
            page = d.get("events") or []
            rows += page
            off += len(page)
            if not page or off >= int(d.get("total") or 0):
                break
        return sorted({k for r in rows for k in r}), rows


for _a in (Celonis(), SignavioPI()):
    if _a.kind not in connectors.KINDS:
        sdk.register(_a)
        _d = _a.describe()
        connectors.KINDS[_a.kind] = {"label": _d["label"], "dialect": None, "auth": list(_d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in _d["fields"]],
                                     "secrets": _d["secrets"], "category": _d["category"], "sdk": True}
SOURCES = ("celonis", "signavio_pi")


def as_csv(cols: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) for k in cols})
    return buf.getvalue().encode("utf-8")
