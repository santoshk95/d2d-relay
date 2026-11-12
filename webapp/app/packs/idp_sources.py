"""Document processing - where the documents come from besides an upload: an Outlook mailbox's attachments and a
SharePoint or OneDrive folder, both through Microsoft Graph, read-only.

The mailbox is a connection of its own (kind m365_mail: an Entra ID app with Mail.Read on that mailbox, the secret in
the secrets store). A folder is read through the SharePoint or OneDrive connection the studio already files to, at the
path the Run item names. Each round takes what it has not taken before - a message's attachment by its id, a file by
its id and its last change - and copies it into the Run item, so the documents read, the evidence and the results all
stay with the item. Nothing is moved, flagged or deleted in the mailbox or the folder: Relay only reads.
"""
from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

import httpx

from .. import connectors_sdk as sdk
from .. import files_adapters as fa

DOC_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")
FOLDER_KINDS = ("sharepoint", "onedrive")
SOURCE_KINDS = ("m365_mail",) + FOLDER_KINDS
PAGE_MAX = 20                                  # pages of 50 messages read in one round at most


class OutlookMailbox(fa.GraphFiles):
    kind, label = "m365_mail", "Outlook mailbox (Microsoft Graph)"
    can_write = False
    fields = fa.GraphFiles.COMMON[:1] + [("client_id", "App (client) id with Mail.Read on this mailbox (an application access policy limits it to it)", True),
                                         ("mailbox", "Mailbox (invoices@contoso.com)", True), ("folder", "Mail folder (default: Inbox)", False)] + fa.GraphFiles.LAB

    def _box(self, c: dict) -> str:
        return f"{self._api(c)}/users/{quote(c['config'].get('mailbox') or '')}"

    def _h(self, c: dict) -> dict:
        return {"Authorization": f"Bearer {self._token(c)}"}

    def messages(self, c: dict, h: dict | None = None) -> list[dict]:
        h = h or self._h(c)
        folder = c["config"].get("folder") or "Inbox"
        url = f"{self._box(c)}/mailFolders/{quote(folder)}/messages"
        params: dict | None = {"$filter": "hasAttachments eq true", "$select": "id,subject,from,receivedDateTime", "$top": "50", "$orderby": "receivedDateTime desc"}
        out = []
        for _ in range(PAGE_MAX):
            d = fa._check(httpx.get(url, headers=h, params=params, timeout=fa.TIMEOUT), self.label)
            out += d.get("value") or []
            url, params = d.get("@odata.nextLink"), None
            if not url:
                break
        return out

    def attachments(self, c: dict, mid: str, h: dict | None = None) -> list[dict]:
        d = fa._check(httpx.get(f"{self._box(c)}/messages/{quote(mid)}/attachments", headers=h or self._h(c), timeout=fa.TIMEOUT), self.label)
        return [a for a in d.get("value") or [] if a.get("@odata.type") == "#microsoft.graph.fileAttachment"]

    def test(self, c: dict) -> dict:
        n = len(self.messages(c))
        return {"ok": True, "sees": f"{n} message(s) with attachments in {c['config'].get('folder') or 'Inbox'}"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        h = self._h(c)
        d = fa._check(httpx.get(f"{self._box(c)}/mailFolders", headers=h, timeout=fa.TIMEOUT), self.label)
        return [{"object": f["displayName"], "type": "mail folder"} for f in d.get("value") or [] if search.lower() in f["displayName"].lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        rows = [{"subject": m.get("subject"), "from": ((m.get("from") or {}).get("emailAddress") or {}).get("address"), "received": m.get("receivedDateTime")} for m in self.messages(c)[:limit]]
        return {"columns": ["subject", "from", "received"], "rows": rows, "row_count": len(rows)}

    def _write(self, c, obj, payload, approval):
        raise sdk.ScopeError("Relay only reads the mailbox: it moves, flags and deletes nothing.")


def _register(a: sdk.Adapter) -> None:
    from .. import connectors
    sdk.register(a)
    d = a.describe()
    connectors.KINDS[a.kind] = {"label": d["label"], "dialect": None, "auth": list(d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in d["fields"]],
                                "secrets": d["secrets"], "category": d["category"], "sdk": True}


_register(OutlookMailbox())


def _safe(s: str, n: int = 60) -> str:
    import re
    return re.sub(r"[^\w.\- ]+", "_", s or "").strip()[:n] or "document"


def pull_mail(c: dict, seen: set) -> tuple[list[tuple[str, str, bytes]], int]:
    """New attachments that are documents: [(key, file name, bytes)] and how many messages were looked at."""
    a = OutlookMailbox()
    h = a._h(c)
    msgs = a.messages(c, h)
    out = []
    for m in msgs:
        for att in a.attachments(c, m["id"], h):
            key = f"mail:{m['id']}:{att.get('id')}"
            name = att.get("name") or ""
            if key in seen or Path(name).suffix.lower() not in DOC_EXT:
                continue
            out.append((key, f"mail-{_safe(m['id'][-8:], 8)}-{_safe(name)}", base64.b64decode(att.get("contentBytes") or "")))
    return out, len(msgs)


def pull_folder(c: dict, path: str, seen: set) -> tuple[list[tuple[str, str, bytes]], int]:
    """New or changed documents in a SharePoint or OneDrive folder: [(key, file name, bytes)] and how many files are there."""
    a = sdk.get(c["kind"])
    drive, h = a._session(c)
    p = (path or "").strip("/")
    url = f"{drive}/root:/{quote(p)}:/children" if p else f"{drive}/root/children"
    items = fa._check(httpx.get(url, headers=h, timeout=fa.TIMEOUT), a.label).get("value") or []
    files = [i for i in items if "file" in i and Path(i.get("name") or "").suffix.lower() in DOC_EXT]
    out = []
    for i in files:
        key = f"file:{i['id']}:{i.get('lastModifiedDateTime') or ''}"
        if key in seen:
            continue
        r = httpx.get(f"{drive}/root:/{quote((p + '/' if p else '') + i['name'])}:/content", headers=h, timeout=fa.TIMEOUT, follow_redirects=True)
        if r.status_code >= 400:
            fa._check(r, a.label)
        out.append((key, f"{c['kind']}-{_safe(i['id'][-8:], 8)}-{_safe(i['name'])}", r.content))
    return out, len(files)
