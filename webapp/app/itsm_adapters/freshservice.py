"""Freshservice API v2: tickets (paged, filtered to the groups the source reads), one ticket, conversations, private
notes and updates; and (consolidation) creating a ticket in a group. Sign-in: the service account's API key (Basic,
the key as the user name). Every write is reached only through itsm.py, after a person's approval."""
from __future__ import annotations

import html
import re

from . import AdapterError, Client, normalise, parse_time

STATUS = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
PRIORITY_NAME = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
PRIORITY = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}                      # Relay priority -> Freshservice priority id
OPEN = (2, 3)


class Freshservice(Client):
    label = "Freshservice"

    def __init__(self, base_url: str, api_key: str, groups: list[str] | None = None, **kw):
        super().__init__(base_url, auth=(api_key, "X"), **kw)
        self.group_names = [g.strip() for g in (groups or []) if g.strip()]
        self._groups: dict[int, str] | None = None

    # -- reads
    def groups(self) -> dict[int, str]:
        if self._groups is None:
            self._groups = {int(g["id"]): g.get("name") or "" for g in self.get("/api/v2/groups", params={"per_page": 100}).json().get("groups") or []}
        return self._groups

    def group_ids(self) -> list[int]:
        wanted = {g.lower() for g in self.group_names}
        return [gid for gid, name in self.groups().items() if name.lower() in wanted]

    def test(self) -> dict:
        me = self.get("/api/v2/agents/me").json().get("agent") or {}
        names = {n.lower() for n in self.groups().values()}
        missing = [g for g in self.group_names if g.lower() not in names]
        return {"account": " ".join(x for x in (me.get("first_name"), me.get("last_name")) if x) or me.get("email") or "service account",
                "groups": sorted(self.groups().values()), "missing": missing, "ok": not missing}

    def tickets(self, since: float | None = None, page_size: int = 100):
        """Open and pending tickets, every page (Freshservice pages by number and announces the next in `Link`)."""
        gids = self.group_ids() if self.group_names else []
        page = 1
        while True:
            params = {"per_page": page_size, "page": page, "include": "requester", "order_by": "updated_at", "order_type": "asc"}
            if since:
                from datetime import datetime, timezone
                params["updated_since"] = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            r = self.get("/api/v2/tickets", params=params)
            rows = r.json().get("tickets") or []
            for t in rows:
                if int(t.get("status") or 0) not in OPEN:
                    continue
                if gids and int(t.get("group_id") or 0) not in gids:
                    continue
                yield self.normalise(t)
            link = r.headers.get("Link") or ""
            if 'rel="next"' not in link and len(rows) < page_size:
                break
            if not rows:
                break
            page += 1

    def ticket(self, tid: str) -> dict:
        return self.normalise(self.get(f"/api/v2/tickets/{tid}").json().get("ticket") or {})

    def conversations(self, tid: str) -> list[dict]:
        return [{"id": c.get("id"), "text": c.get("body_text") or re.sub(r"<[^>]+>", "", str(c.get("body") or "")), "private": c.get("private"), "created": parse_time(c.get("created_at"))}
                for c in self.get(f"/api/v2/tickets/{tid}/conversations").json().get("conversations") or []]

    # -- writes (only through itsm.py: write_back after the group's approval, perform_write after a per-change approval)
    def note(self, tid: str, text: str, private: bool = True) -> dict:
        body = "".join(f"<p>{html.escape(p.strip())}</p>" for p in text.split("\n\n") if p.strip()) or f"<p>{html.escape(text)}</p>"
        return self.post(f"/api/v2/tickets/{tid}/notes", json={"body": body, "private": bool(private)}).json()

    def add_comment(self, key: str, text: str) -> dict:
        """A private note (agents see it, the requester does not)."""
        tid = key[3:] if str(key).upper().startswith("FS-") else str(key)
        if not tid.isdigit():
            raise AdapterError(f"{key} is not a Freshservice ticket.")
        c = (self.note(tid, text, private=True).get("conversation") or {})
        return {"key": f"FS-{tid}", "id": str(c.get("id") or ""), "url": f"{self.base}/a/tickets/{tid}"}

    def create_issue(self, project: str, title: str, description: str, *, priority: str | None = None, labels: list[str] | None = None,
                     requester: str | None = None, **_) -> dict:
        """A new ticket in a group (`project` is the group's name; none = the account's default routing), raised by the
        requester e-mail the source names, else by the service account itself. Returns key + URL."""
        if not (title or "").strip():
            raise AdapterError("A ticket needs a title.")
        body = {"subject": title.strip()[:255], "description": "".join(f"<p>{html.escape(p.strip())}</p>" for p in (description or title).split("\n\n") if p.strip()),
                "priority": PRIORITY.get(priority or "P3", 2), "status": 2, "tags": sorted({str(x) for x in labels or []})}
        if project:
            gid = next((i for i, n in self.groups().items() if n.lower() == project.strip().lower()), None)
            if gid is None:
                raise AdapterError(f"Freshservice has no group called {project}.")
            body["group_id"] = gid
        email = (requester or "").strip() or (self.get("/api/v2/agents/me").json().get("agent") or {}).get("email")
        if not email:
            raise AdapterError("Freshservice needs a requester for a new ticket: give one in the source's settings.")
        body["email"] = email
        t = self.post("/api/v2/tickets", json=body).json().get("ticket") or {}
        if not t.get("id"):
            raise AdapterError("Freshservice did not return the new ticket's id.")
        return {"key": f"FS-{t['id']}", "id": str(t["id"]), "url": f"{self.base}/a/tickets/{t['id']}", "via": "Freshservice ticket"}

    def update(self, tid: str, fields: dict) -> dict:
        return self.put(f"/api/v2/tickets/{tid}", json=fields).json()

    def set_priority(self, tid: str, relay_priority: str) -> None:
        self.update(tid, {"priority": PRIORITY.get(relay_priority, 2)})

    def add_tags(self, tid: str, tags: list[str], current: list[str] | None = None) -> None:
        have = list(current if current is not None else self.ticket(tid)["labels"])
        self.update(tid, {"tags": sorted(set(have) | set(tags))})

    # -- shape
    def normalise(self, t: dict) -> dict:
        req = t.get("requester") or {}
        desc = t.get("description_text") or re.sub(r"<[^>]+>", "", str(t.get("description") or ""))
        gid = int(t.get("group_id") or 0)
        team = (self._groups or {}).get(gid) or (self.groups().get(gid) if gid else "") or ""
        tid = t.get("id")
        return normalise("freshservice", f"FS-{tid}", tid, t.get("subject") or "", desc, STATUS.get(int(t.get("status") or 0), str(t.get("status"))),
                         int(t.get("status") or 0) in OPEN, PRIORITY_NAME.get(int(t.get("priority") or 0), ""), req.get("name") or "", req.get("email") or "",
                         team, parse_time(t.get("created_at")) or 0.0, parse_time(t.get("updated_at")) or 0.0, parse_time(t.get("due_by")),
                         t.get("tags") or [], f"{self.base}/a/tickets/{tid}", {"type": t.get("type"), "category": t.get("category")})
