"""Backlog trackers for BRD & requirements (and the other W4 packs that push work items).

Jira goes through the Service desk's sources (P12, consolidation): a story is raised and a comment added with
itsm.request_write, each after its own itsm.write approval showing exactly what is written (_w4.desk_write; the keys
come back through itsm.register_write_hook). Azure Boards (Azure DevOps Services REST 7.1) is a Connector SDK adapter
here — one adapter + one mock (tests/mocklab/sims/process.py: `azure-boards`) — read-only by default: `test` signs in
and reads the project and its work item types, `list_objects` lists the types, `read` the work items Relay created
(tag `relay`). Its writes happen only through connectors.request_write — after a named person accepted exactly that
backlog (the same shape as AI SDLC's Azure Boards write-back: a checkpoint for exactly the write, then the call) — and
carry the approval's id in an X-Relay-Approval header; the ids and links go back to the work item (_w4.push_written).

  stories   payload {"from", "stories": [{"ref", "summary", "description", "acceptance": [...], "priority", "labels"}]}
            -> POST …/_apis/wit/workitems/$<type> (JSON Patch: title, description, acceptance criteria, tags, priority)
  updates   payload {"from", "updates": [{"key", "comment", "summary"?}]} -> PATCH …/workitems/{id} (System.History)
"""
from __future__ import annotations

import base64
import json as _json
import time

import httpx

from .. import connectors
from .. import connectors_sdk as sdk
from . import _w4

TIMEOUT = 25
PRIORITY_JIRA = {"must": "High", "should": "Medium", "could": "Low", "wont": "Lowest", "High": "High", "Medium": "Medium", "Low": "Low"}
PRIORITY_ADO = {"must": 1, "should": 2, "could": 3, "wont": 4, "High": 1, "Medium": 2, "Low": 3}


def _secret(c: dict, name: str) -> str:
    from .. import secrets_store
    v = secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}")
    if not v:
        raise connectors.Reconsent(f"No {name.replace('_', ' ')} is stored for {c['name']}: sign in again.")
    return v


def _call(label: str, method: str, url: str, *, auth=None, headers: dict | None = None, json=None, content: bytes | None = None, ok=(200, 201, 204), attempts: int = 3) -> httpx.Response:
    """One vendor call with the rules every adapter keeps: 429 and 5xx back off and retry, 401 is "sign in again",
    403 / 404 / other refusals are explained."""
    last = ""
    for i in range(attempts):
        try:
            with httpx.Client(timeout=TIMEOUT, auth=auth, headers={"Accept": "application/json", **(headers or {})}) as cl:
                r = cl.request(method, url, json=json, content=content)
        except httpx.TransportError as e:
            last = f"{label} could not be reached ({e.__class__.__name__})"
            time.sleep(min(4, 0.5 * 2 ** i))
            continue
        if r.status_code == 401:
            raise connectors.Reconsent(f"{label} refused the stored sign-in: sign in again with a new token.")
        if r.status_code == 429 or r.status_code >= 500:
            last = f"{label} answered {r.status_code}"
            try:
                time.sleep(min(4.0, float(r.headers.get("Retry-After") or 0.5 * 2 ** i)))
            except ValueError:
                time.sleep(1)
            continue
        if r.status_code == 403:
            raise connectors.ConnectorError(f"{label}: the account has no access to {'/'.join(url.split('?')[0].rsplit('/', 2)[-2:])} (403).")
        if r.status_code not in ok:
            try:
                body = r.json()
                msg = body.get("errorMessages") or body.get("message") or body.get("errors") or body
            except ValueError:
                msg = r.text[:200]
            raise connectors.ConnectorError(f"{label} refused {method} {url.split('?')[0]} ({r.status_code}): {str(msg)[:300]}")
        return r
    raise connectors.ConnectorError(last or f"{label} did not answer")


class AzureBoards(sdk.Adapter):
    kind = "azure_boards"
    label = "Azure Boards"
    category = "code"
    signin = ["api_key"]
    fields = [("org_url", "Organisation URL (https://dev.azure.com/your-org)", True), ("project", "Project", True),
              ("work_item_type", "Work item type (default User Story)", False), ("area_path", "Area path (optional)", False)]
    secrets = {"api_key": ["pat"]}
    can_write = True
    V = "api-version=7.1"

    def _base(self, c: dict) -> tuple[str, str]:
        return (c["config"].get("org_url") or "").rstrip("/"), (c["config"].get("project") or "").strip()

    def _h(self, c: dict) -> dict:
        return {"Authorization": "Basic " + base64.b64encode(f":{_secret(c, 'pat')}".encode()).decode()}

    def test(self, c: dict) -> dict:
        org, proj = self._base(c)
        p = _call("Azure Boards", "GET", f"{org}/_apis/projects/{proj}?{self.V}", headers=self._h(c)).json()
        types = [t.get("name") for t in _call("Azure Boards", "GET", f"{org}/{proj}/_apis/wit/workitemtypes?{self.V}", headers=self._h(c)).json().get("value") or []]
        return {"ok": True, "sees": f"project {p.get('name')} ({p.get('state') or 'wellFormed'}); work item types: {', '.join(types[:6])}", "scope": c.get("scope")}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        org, proj = self._base(c)
        return [{"object": t.get("name"), "type": "work item type"} for t in _call("Azure Boards", "GET", f"{org}/{proj}/_apis/wit/workitemtypes?{self.V}", headers=self._h(c)).json().get("value") or []
                if search.lower() in (t.get("name") or "").lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        org, proj = self._base(c)
        q = _call("Azure Boards", "POST", f"{org}/{proj}/_apis/wit/wiql?{self.V}", headers=self._h(c),
                  json={"query": "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND [System.Tags] CONTAINS 'relay' ORDER BY [System.Id]"}).json()
        ids = [str(w["id"]) for w in (q.get("workItems") or [])[:limit]]
        rows = []
        if ids:
            got = _call("Azure Boards", "GET", f"{org}/{proj}/_apis/wit/workitems?ids={','.join(ids)}&fields=System.Id,System.Title,System.State,System.WorkItemType,System.Tags&{self.V}", headers=self._h(c)).json()
            rows = [{"id": w.get("id"), "title": (w.get("fields") or {}).get("System.Title"), "state": (w.get("fields") or {}).get("System.State"),
                     "type": (w.get("fields") or {}).get("System.WorkItemType"), "tags": (w.get("fields") or {}).get("System.Tags")} for w in got.get("value") or []]
        return {"columns": ["id", "title", "state", "type", "tags"], "rows": rows, "row_count": len(rows)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        try:
            out = self._do_write(c, obj, payload, approval)
        except Exception as e:
            _w4.push_written(approval, {"error": str(e)}, ok=False)
            raise
        _w4.push_written(approval, out, ok=True)
        return out

    def _do_write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        org, proj = self._base(c)
        h = {**self._h(c), "X-Relay-Approval": approval}
        wtype = (c["config"].get("work_item_type") or "").strip() or "User Story"
        area = (c["config"].get("area_path") or "").strip()
        created, errors, updated = [], [], []
        if obj not in ("stories", "updates"):
            raise sdk.ScopeError(f"Azure Boards: Relay writes stories and updates, not {obj!r}")
        for s in payload.get("stories") or []:
            ops = [{"op": "add", "path": "/fields/System.Title", "value": s["summary"][:255]},
                   {"op": "add", "path": "/fields/System.Description", "value": "<p>" + _w4.esc(s.get("description") or "") + "</p>"},
                   {"op": "add", "path": "/fields/Microsoft.VSTS.Common.AcceptanceCriteria", "value": "<ul>" + "".join(f"<li>{_w4.esc(a)}</li>" for a in s.get("acceptance") or []) + "</ul>"},
                   {"op": "add", "path": "/fields/System.Tags", "value": "; ".join(["relay", *[str(x) for x in s.get("labels") or []]])}]
            if s.get("priority"):
                ops.append({"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": PRIORITY_ADO.get(s["priority"], 2)})
            if area:
                ops.append({"op": "add", "path": "/fields/System.AreaPath", "value": area})
            try:
                r = _call("Azure Boards", "POST", f"{org}/{proj}/_apis/wit/workitems/${wtype.replace(' ', '%20')}?{self.V}", headers={**h, "Content-Type": "application/json-patch+json"},
                          content=_json.dumps(ops).encode(), ok=(200, 201)).json()
                created.append({"ref": s["ref"], "key": str(r.get("id")), "id": str(r.get("id")), "url": ((r.get("_links") or {}).get("html") or {}).get("href") or r.get("url")})
            except connectors.Reconsent:
                raise
            except connectors.ConnectorError as e:
                errors.append({"ref": s["ref"], "error": str(e)[:300]})
        for u in payload.get("updates") or []:
            ops = []
            if u.get("summary"):
                ops.append({"op": "add", "path": "/fields/System.Title", "value": u["summary"][:255]})
            if u.get("comment"):
                ops.append({"op": "add", "path": "/fields/System.History", "value": _w4.esc(u["comment"])})
            if ops:
                _call("Azure Boards", "PATCH", f"{org}/{proj}/_apis/wit/workitems/{u['key']}?{self.V}", headers={**h, "Content-Type": "application/json-patch+json"}, content=_json.dumps(ops).encode())
            updated.append({"ref": u.get("ref"), "key": u["key"], "url": f"{org}/{proj}/_workitems/edit/{u['key']}"})
        return {"ok": not errors, "created": created, "updated": updated, "errors": errors, "where": f"{org}/{proj}/_boards"}


for _a in (AzureBoards(),):
    if _a.kind not in connectors.KINDS:
        sdk.register(_a)
        _d = _a.describe()
        connectors.KINDS[_a.kind] = {"label": _d["label"], "dialect": None, "auth": list(_d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in _d["fields"]],
                                     "secrets": _d["secrets"], "category": _d["category"], "sdk": True}
TRACKERS = ("azure_boards",)
