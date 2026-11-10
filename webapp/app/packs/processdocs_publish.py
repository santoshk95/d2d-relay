"""Confluence Cloud as a Connector SDK adapter for Business process documents: where a published process is filed —
a page in a space with the step-by-step procedure (storage format) and the BPMN 2.0 map and the Word SOP attached.
One adapter + one mock (tests/mocklab/sims/process.py: `confluence`).

Read-only by default: `test` signs in and reads the space, `list_objects` lists its pages, `read` the pages Relay filed
(label relay). A page is written only through connectors.request_write — after a named person accepted exactly that
version — with the approval's id in an X-Relay-Approval header; the files are read again from the work item's outputs.

  page   payload {"from": "processdocs:<item>:<step>", "title", "body" (storage XHTML), "files": [output names], "version"}
         -> POST /wiki/api/v2/pages, then POST /wiki/rest/api/content/{id}/child/attachment for each file
"""
from __future__ import annotations

import httpx

from .. import connectors, db, store
from .. import connectors_sdk as sdk
from . import _w4
from .brd_trackers import _call, _secret


class Confluence(sdk.Adapter):
    kind = "confluence"
    label = "Confluence (process pages)"
    category = "files"
    signin = ["api_key"]
    fields = [("base_url", "Site URL (https://your-site.atlassian.net)", True), ("space", "Space key (e.g. OPS)", True), ("email", "Service account e-mail", True),
              ("parent", "Parent page id (optional)", False)]
    secrets = {"api_key": ["api_token"]}
    can_write = True

    def _a(self, c):
        return httpx.BasicAuth((c["config"].get("email") or "").strip(), _secret(c, "api_token"))

    def _base(self, c):
        return (c["config"].get("base_url") or "").rstrip("/")

    def _space(self, c) -> dict:
        key = (c["config"].get("space") or "").strip()
        r = _call("Confluence", "GET", f"{self._base(c)}/wiki/api/v2/spaces?keys={key}", auth=self._a(c)).json()
        sp = (r.get("results") or [None])[0]
        if not sp:
            raise connectors.ConnectorError(f"Confluence has no space {key!r} the account can see.")
        return sp

    def test(self, c: dict) -> dict:
        sp = self._space(c)
        return {"ok": True, "sees": f"space {sp.get('key')} ({sp.get('name')})", "scope": c.get("scope")}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        sp = self._space(c)
        r = _call("Confluence", "GET", f"{self._base(c)}/wiki/api/v2/spaces/{sp['id']}/pages?limit=100", auth=self._a(c)).json()
        return [{"object": p.get("title"), "type": "page"} for p in r.get("results") or [] if search.lower() in (p.get("title") or "").lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        sp = self._space(c)
        r = _call("Confluence", "GET", f"{self._base(c)}/wiki/api/v2/spaces/{sp['id']}/pages?limit={min(limit, 250)}", auth=self._a(c)).json()
        rows = [{"id": p.get("id"), "title": p.get("title"), "status": p.get("status"), "version": (p.get("version") or {}).get("number")} for p in r.get("results") or []]
        return {"columns": ["id", "title", "status", "version"], "rows": rows, "row_count": len(rows)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        try:
            out = self._do(c, obj, payload, approval)
        except Exception as e:
            _w4.push_written(approval, {"error": str(e)}, ok=False)
            raise
        _w4.push_written(approval, out, ok=True)
        return out

    def _do(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        if obj != "page":
            raise sdk.ScopeError(f"Confluence: Relay files process pages, not {obj!r}")
        _, item, _ = _w4.payload_from(payload)
        from .. import auth, checkpoints
        asker = db.user((checkpoints.get(approval) or {}).get("opened_by") or "") or db.user(c["owner_id"]) or {}
        p = db.project(item)
        if not p or not auth.can_project(asker, "view", p):
            raise sdk.ScopeError("The work item this page comes from is not one the person who asked may see; nothing was filed.")
        sp = self._space(c)
        h = {"X-Relay-Approval": approval}
        body = {"spaceId": sp["id"], "status": "current", "title": payload["title"][:255], "body": {"representation": "storage", "value": payload.get("body") or ""}}
        if (c["config"].get("parent") or "").strip():
            body["parentId"] = c["config"]["parent"].strip()
        pg = _call("Confluence", "POST", f"{self._base(c)}/wiki/api/v2/pages", auth=self._a(c), headers=h, json=body, ok=(200, 201)).json()
        files = []
        for name in payload.get("files") or []:
            f = store.root() / item / "outputs" / name
            if not f.is_file():
                continue
            with httpx.Client(timeout=60, auth=self._a(c), headers={"X-Atlassian-Token": "no-check", **h}) as cl:
                r = cl.post(f"{self._base(c)}/wiki/rest/api/content/{pg['id']}/child/attachment", files={"file": (name, f.read_bytes(), "application/octet-stream")})
            if r.status_code == 401:
                raise connectors.Reconsent("Confluence refused the stored sign-in: sign in again.")
            if r.status_code >= 400:
                raise connectors.ConnectorError(f"Confluence refused the attachment {name} ({r.status_code}).")
            files.append(name)
        url = f"{self._base(c)}/wiki{(pg.get('_links') or {}).get('webui') or ''}"
        return {"ok": True, "created": [{"ref": "page", "key": str(pg.get("id")), "url": url}], "attachments": files, "errors": []}


_a = Confluence()
if _a.kind not in connectors.KINDS:
    sdk.register(_a)
    _d = _a.describe()
    connectors.KINDS[_a.kind] = {"label": _d["label"], "dialect": None, "auth": list(_d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in _d["fields"]],
                                 "secrets": _d["secrets"], "category": _d["category"], "sdk": True}
FILING = ("confluence",)
