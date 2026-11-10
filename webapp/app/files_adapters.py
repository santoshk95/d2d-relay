"""Filing adapters (consolidation of P11: "SharePoint / OneDrive / Drive filing adapters, one adapter + one mock each",
and "Google formats"): where the studio files an accepted final. Microsoft Graph for a SharePoint document library and
for a person's OneDrive; Google Drive v3 for a folder in Drive, optionally converted to Google Slides / Docs / Sheets.
They sign in as an app — Entra ID client credentials (tenant, client id, client secret) or a Google service account
(its JSON key) — with the secret by name in the secrets store, never returned.

Read-only by default like every connection (Connector SDK): an upload happens only through connectors.request_write,
after a named person accepted exactly that file — the payload carries its SHA-256, and the adapter reads the file from
the deliverable's folder again and refuses when it changed. Endpoints are overridable per connection (a national
cloud, a private endpoint), which is also how the mock lab's simulator stands in for the clouds (tests/mocklab/files_sim.py).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from urllib.parse import quote

import httpx

from .connectors_sdk import Adapter, ScopeError, register

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
GOOGLE_API = "https://www.googleapis.com"
SIMPLE_MAX = 250 * 1024 * 1024                        # Graph's simple upload takes files up to 250 MB; decks and documents are far below
GOOGLE_TYPES = {".pptx": "application/vnd.google-apps.presentation", ".docx": "application/vnd.google-apps.document",
                ".xlsx": "application/vnd.google-apps.spreadsheet"}
TIMEOUT = 60


def _reconsent(text: str):
    from . import connectors
    return connectors.Reconsent(text)


def _error(text: str):
    from . import connectors
    return connectors.ConnectorError(text)


def _secret(c: dict, name: str) -> str | None:
    from . import secrets_store
    return secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}")


def approved_file(payload: dict, approval: str) -> bytes:
    """The file the approval covers, read again from the deliverable's folder: refused when the person who asked
    may not see that deliverable, or when the file changed since the approval."""
    from . import auth, checkpoints, db, store
    origin = str(payload.get("from") or "")
    parts = origin.split(":")
    if len(parts) < 2 or parts[0] != "studio":
        raise ScopeError("Only a studio deliverable is filed through this connection.")
    asker, p = db.user((checkpoints.get(approval) or {}).get("opened_by") or ""), db.project(parts[1])
    if not asker or p is None or not auth.can_project(asker, "view", p):          # an unknown deliverable is refused, for Admins too
        raise ScopeError("The person who asked for this filing may not see that deliverable; nothing was filed.")
    base = (store.root() / parts[1]).resolve()
    path = (base / str(payload.get("path") or "")).resolve()
    if base not in path.parents or not path.is_file():
        raise ScopeError("The approved file is not in the deliverable's folder any more.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != payload.get("sha256"):
        raise ScopeError("The file changed after the approval; nothing was filed. Ask for the write approval again.")
    return data


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code in (401, 403):
        raise _reconsent(f"{what}: the sign-in was refused ({r.status_code}). Renew the connection's secret or its permissions.")
    if r.status_code >= 400:
        raise _error(f"{what}: {r.status_code} {r.text[:200]}")
    return r.json() if r.content else {}


# ------------------------------------------------------------------ Microsoft Graph: SharePoint and OneDrive

class GraphFiles(Adapter):
    category = "files"
    signin = ["service_account"]
    secrets = {"service_account": ["client_secret"]}
    can_write = True
    COMMON = [("tenant", "Entra tenant id", True), ("client_id", "App (client) id with Files.ReadWrite / Sites.Selected", True)]
    LAB = [("graph", "Graph endpoint (optional: a national cloud)", False), ("authority", "Sign-in endpoint (optional: a national cloud)", False)]

    def _token(self, c: dict) -> str:
        cfg = c["config"]
        secret = _secret(c, "client_secret")
        if not secret:
            raise _reconsent("No client secret is stored for this connection.")
        r = httpx.post(f"{(cfg.get('authority') or LOGIN).rstrip('/')}/{cfg.get('tenant')}/oauth2/v2.0/token", timeout=TIMEOUT,
                       data={"grant_type": "client_credentials", "client_id": cfg.get("client_id"), "client_secret": secret, "scope": "https://graph.microsoft.com/.default"})
        if r.status_code in (400, 401):
            raise _reconsent("Entra ID refused the app's sign-in: check the tenant, the client id and the secret.")
        return _check(r, "Entra ID")["access_token"]

    def _api(self, c: dict) -> str:
        return (c["config"].get("graph") or GRAPH).rstrip("/")

    def _drive(self, c: dict, h: dict) -> str:                 # the drive's path on Graph (each kind says which)
        raise NotImplementedError

    def _session(self, c: dict) -> tuple[str, dict]:
        h = {"Authorization": f"Bearer {self._token(c)}"}
        return self._api(c) + self._drive(c, h), h

    def test(self, c: dict) -> dict:
        drive, h = self._session(c)
        items = _check(httpx.get(f"{drive}/root/children", headers=h, timeout=TIMEOUT), self.label).get("value") or []
        return {"ok": True, "sees": f"{len(items)} item(s) at the top of the library"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        drive, h = self._session(c)
        items = _check(httpx.get(f"{drive}/root/children", headers=h, timeout=TIMEOUT), self.label).get("value") or []
        return [{"object": i["name"], "type": "folder"} for i in items if "folder" in i and search.lower() in i["name"].lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        drive, h = self._session(c)
        items = _check(httpx.get(f"{drive}/root:/{quote(obj.strip('/'))}:/children", headers=h, timeout=TIMEOUT), self.label).get("value") or []
        rows = [{"name": i.get("name"), "size": i.get("size"), "modified": i.get("lastModifiedDateTime"), "kind": "folder" if "folder" in i else "file"} for i in items[:limit]]
        return {"columns": ["name", "kind", "size", "modified"], "rows": rows, "row_count": len(items)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        data = approved_file(payload, approval)
        if len(data) > SIMPLE_MAX:
            raise ScopeError("The file is larger than Graph's simple upload takes (250 MB).")
        drive, h = self._session(c)
        r = httpx.put(f"{drive}/root:/{quote(obj.strip('/'))}:/content", content=data, timeout=TIMEOUT,
                      headers={**h, "Content-Type": payload.get("content_type") or "application/octet-stream"})
        item = _check(r, self.label)
        return {"ok": True, "id": item.get("id"), "url": item.get("webUrl"), "name": item.get("name"), "bytes": item.get("size"), "approval": approval}


class SharePoint(GraphFiles):
    kind, label = "sharepoint", "SharePoint (document library)"
    fields = GraphFiles.COMMON + [("site", "Site (contoso.sharepoint.com:/sites/Bids)", True)] + GraphFiles.LAB

    def _drive(self, c: dict, h: dict) -> str:
        site = _check(httpx.get(f"{self._api(c)}/sites/{c['config'].get('site')}", headers=h, timeout=TIMEOUT), "SharePoint")
        return f"/sites/{site['id']}/drive"


class OneDrive(GraphFiles):
    kind, label = "onedrive", "OneDrive"
    fields = GraphFiles.COMMON + [("user", "Whose OneDrive (user@contoso.com)", True)] + GraphFiles.LAB

    def _drive(self, c: dict, h: dict) -> str:
        return f"/users/{quote(c['config'].get('user') or '')}/drive"


# ------------------------------------------------------------------ Google Drive v3 (a service account; Google formats on request)

class GoogleDrive(Adapter):
    kind, label, category = "gdrive", "Google Drive", "files"
    signin = ["service_account"]
    secrets = {"service_account": ["service_account_json"]}
    fields = [("folder_id", "Folder id to file into (shared with the service account)", True), ("convert", "Convert to Google formats: yes or no", False),
              ("api", "Drive API endpoint (optional: a private endpoint)", False)]
    can_write = True
    SCOPE = "https://www.googleapis.com/auth/drive"     # drive.file cannot reach a folder someone shared with the account; the account sees only what is shared with it

    def _token(self, c: dict) -> str:
        raw = _secret(c, "service_account_json")
        if not raw:
            raise _reconsent("No service account key is stored for this connection.")
        try:
            key = json.loads(raw)
        except ValueError as e:
            raise _reconsent("The stored service account key is not JSON.") from e
        import jwt                                          # PyJWT (with cryptography for RS256), already in the image
        now = int(time.time())
        aud = key.get("token_uri") or "https://oauth2.googleapis.com/token"
        assertion = jwt.encode({"iss": key.get("client_email"), "scope": self.SCOPE, "aud": aud, "iat": now, "exp": now + 3600}, key.get("private_key"), algorithm="RS256",
                               headers={"kid": key.get("private_key_id")} if key.get("private_key_id") else None)
        r = httpx.post(aud, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}, timeout=TIMEOUT)
        if r.status_code in (400, 401):
            raise _reconsent("Google refused the service account's sign-in: check the key and that the Drive API is on.")
        return _check(r, "Google sign-in")["access_token"]

    def _base(self, c: dict) -> str:
        return (c["config"].get("api") or GOOGLE_API).rstrip("/")

    def _children(self, c: dict, h: dict, parent: str, folders_only: bool = False) -> list[dict]:
        q = f"'{parent}' in parents and trashed = false" + (" and mimeType = 'application/vnd.google-apps.folder'" if folders_only else "")
        r = httpx.get(f"{self._base(c)}/drive/v3/files", params={"q": q, "fields": "files(id,name,mimeType,size,modifiedTime)", "supportsAllDrives": "true",
                                                                 "includeItemsFromAllDrives": "true"}, headers=h, timeout=TIMEOUT)
        return _check(r, "Google Drive").get("files") or []

    def test(self, c: dict) -> dict:
        h = {"Authorization": f"Bearer {self._token(c)}"}
        f = _check(httpx.get(f"{self._base(c)}/drive/v3/files/{c['config'].get('folder_id')}", params={"fields": "id,name", "supportsAllDrives": "true"}, headers=h, timeout=TIMEOUT), "Google Drive")
        return {"ok": True, "sees": f"the folder “{f.get('name')}”"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        h = {"Authorization": f"Bearer {self._token(c)}"}
        return [{"object": f["name"], "type": "folder"} for f in self._children(c, h, c["config"].get("folder_id"), True) if search.lower() in f["name"].lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        h = {"Authorization": f"Bearer {self._token(c)}"}
        parent = self._folder(c, h, [p for p in obj.strip("/").split("/") if p], create=False)
        files = self._children(c, h, parent) if parent else []
        rows = [{"name": f.get("name"), "kind": "folder" if f.get("mimeType", "").endswith(".folder") else "file", "size": f.get("size"), "modified": f.get("modifiedTime")} for f in files[:limit]]
        return {"columns": ["name", "kind", "size", "modified"], "rows": rows, "row_count": len(files)}

    def _folder(self, c: dict, h: dict, parts: list[str], create: bool) -> str | None:
        """The id of the sub-folder path under the configured folder (made on the way when `create`)."""
        parent = c["config"].get("folder_id")
        for name in parts:
            hit = next((f for f in self._children(c, h, parent, True) if f.get("name") == name), None)
            if hit:
                parent = hit["id"]
                continue
            if not create:
                return None
            r = httpx.post(f"{self._base(c)}/drive/v3/files", params={"supportsAllDrives": "true", "fields": "id"}, headers=h, timeout=TIMEOUT,
                           json={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]})
            parent = _check(r, "Google Drive")["id"]
        return parent

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        data = approved_file(payload, approval)
        h = {"Authorization": f"Bearer {self._token(c)}"}
        parts = [p for p in obj.strip("/").split("/") if p]
        name, parent = parts[-1], self._folder(c, h, parts[:-1], create=True)
        suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        convert = str(c["config"].get("convert") or "").strip().lower() in ("yes", "true", "1")
        meta = {"name": name.rsplit(".", 1)[0] if convert and suffix in GOOGLE_TYPES else name, "parents": [parent]}
        if convert and suffix in GOOGLE_TYPES:
            meta["mimeType"] = GOOGLE_TYPES[suffix]                  # Drive converts the upload to Google Slides / Docs / Sheets
        boundary = "relay-" + uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n--{boundary}\r\n"
                f"Content-Type: {payload.get('content_type') or 'application/octet-stream'}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        r = httpx.post(f"{self._base(c)}/upload/drive/v3/files", params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,name,mimeType,webViewLink"},
                       content=body, headers={**h, "Content-Type": f"multipart/related; boundary={boundary}"}, timeout=TIMEOUT)
        f = _check(r, "Google Drive")
        return {"ok": True, "id": f.get("id"), "url": f.get("webViewLink"), "name": f.get("name"), "mime": f.get("mimeType"), "converted": "mimeType" in meta, "approval": approval}


for _a in (SharePoint(), OneDrive(), GoogleDrive()):
    register(_a)
