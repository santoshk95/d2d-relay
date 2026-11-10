"""Jira Cloud REST API v3 (Jira Service Management and Jira Software): search by JQL with page tokens, issue, comments
(Atlassian Document Format), transitions and field edits; and (consolidation) creating an issue — through the
platform API, or as a customer request of a request type through the Jira Service Management API — and an internal
comment. Sign-in: the service account's e-mail + API token (Basic), or a bearer token for a Jira Data Center personal
access token. Every write is reached only through itsm.py, after a person's approval."""
from __future__ import annotations

import re

from . import AdapterError, Client, normalise, parse_time

OPEN_JQL = "statusCategory != Done"
PRIORITY = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}      # Relay priority -> Jira default scheme
FIELDS = ["summary", "description", "status", "priority", "reporter", "assignee", "created", "updated", "duedate", "labels",
          "project", "issuetype", "customfield_10010", "customfield_10030", "customfield_10050"]
SLA_FIELD = "customfield_10030"        # Jira Service Management "Time to resolution" (ongoingCycle.breachTime); duedate otherwise
FIELD_ID = re.compile(r"^customfield_\d{3,6}$")
# a comment Relay writes is internal on Jira Service Management (not shown to the customer on the portal); Jira
# Software keeps it as a plain comment with the property stored
INTERNAL = [{"key": "sd.public.comment", "value": {"internal": True}}]


def sla_due(f: dict, field: str = SLA_FIELD):
    sla = f.get(field)
    if isinstance(sla, dict):
        cycle = sla.get("ongoingCycle") or {}
        bt = cycle.get("breachTime") or {}
        if bt.get("epochMillis"):
            return float(bt["epochMillis"]) / 1000
        if bt.get("iso8601"):
            return parse_time(bt["iso8601"])
    return parse_time(f.get("duedate"))


def adf(text: str) -> dict:
    paras = [p for p in text.split("\n\n") if p.strip()] or [text]
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": p.strip()}]} for p in paras]}


def adf_text(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        if node.get("type") == "hardBreak":
            return "\n"
        sep = "\n" if node.get("type") in ("doc", "bulletList", "orderedList") else " "
        return sep.join(adf_text(c) for c in node.get("content", []) if c).strip()
    if isinstance(node, list):
        return "\n".join(adf_text(c) for c in node)
    return ""


class Jira(Client):
    label = "Jira"

    def __init__(self, base_url: str, email: str, token: str, projects: list[str] | None = None, sla_field: str | None = None, **kw):
        super().__init__(base_url, auth=(email, token) if email else None, bearer=None if email else token, **kw)
        self.projects = [p.strip().upper() for p in (projects or []) if p.strip()]
        self.sla_field = sla_field if sla_field and FIELD_ID.match(sla_field) else SLA_FIELD    # a source setting (the pilot's own field id)

    def fields(self) -> list[str]:
        return FIELDS + ([self.sla_field] if self.sla_field not in FIELDS else [])

    # -- reads
    def test(self) -> dict:
        me = self.get("/rest/api/3/myself").json()
        projects = self.get("/rest/api/3/project/search", params={"maxResults": 50}).json().get("values") or []
        keys = {p.get("key") for p in projects}
        missing = [p for p in self.projects if p not in keys]
        return {"account": me.get("displayName") or me.get("emailAddress") or "service account", "projects": sorted(keys),
                "missing": missing, "ok": not missing}

    def jql(self, since: float | None = None) -> str:
        parts = [OPEN_JQL]
        if self.projects:
            parts.insert(0, "project in (" + ", ".join(self.projects) + ")")
        if since:
            from datetime import datetime, timezone
            parts.append('updated >= "' + datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d %H:%M") + '"')
        return " AND ".join(parts) + " ORDER BY created ASC"

    def tickets(self, since: float | None = None, page_size: int = 100):
        """Every open issue of the configured projects (all pages, `nextPageToken` as Jira Cloud pages today)."""
        token = None
        while True:
            params = {"jql": self.jql(since), "maxResults": page_size, "fields": ",".join(self.fields())}
            if token:
                params["nextPageToken"] = token
            data = self.get("/rest/api/3/search/jql", params=params).json()
            for issue in data.get("issues") or []:
                yield self.normalise(issue)
            token = data.get("nextPageToken")
            if data.get("isLast", True) or not token:
                break

    def issue(self, key: str) -> dict:
        return self.normalise(self.get(f"/rest/api/3/issue/{key}").json())

    def comments(self, key: str) -> list[dict]:
        return [{"id": c.get("id"), "text": adf_text(c.get("body")), "author": (c.get("author") or {}).get("displayName"), "created": parse_time(c.get("created"))}
                for c in self.get(f"/rest/api/3/issue/{key}/comment").json().get("comments") or []]

    def transitions(self, key: str) -> list[dict]:
        return [{"id": t.get("id"), "name": t.get("name"), "to": (t.get("to") or {}).get("name")} for t in self.get(f"/rest/api/3/issue/{key}/transitions").json().get("transitions") or []]

    def service_desks(self) -> list[dict]:
        """Jira Service Management: the service desks and, for each, its request types (to check a source's settings)."""
        out = []
        for d in self.get("/rest/servicedeskapi/servicedesk").json().get("values") or []:
            types = self.get(f"/rest/servicedeskapi/servicedesk/{d.get('id')}/requesttype").json().get("values") or []
            out.append({"id": str(d.get("id")), "project": d.get("projectKey"), "name": d.get("projectName"), "request_types": [{"id": str(t.get("id")), "name": t.get("name")} for t in types]})
        return out

    # -- writes (only through itsm.py: write_back after the group's approval, perform_write after a per-change approval)
    def comment(self, key: str, text: str) -> dict:
        """An internal comment (Jira Service Management keeps it off the customer portal)."""
        return self.post(f"/rest/api/3/issue/{key}/comment", json={"body": adf(text), "properties": INTERNAL}).json()

    def add_comment(self, key: str, text: str) -> dict:
        c = self.comment(key, text)
        return {"key": key, "id": str(c.get("id") or ""), "url": f"{self.base}/browse/{key}" + (f"?focusedCommentId={c.get('id')}" if c.get("id") else "")}

    def create_issue(self, project: str, title: str, description: str, *, issue_type: str = "Task", priority: str | None = None,
                     labels: list[str] | None = None, service_desk: str | None = None, request_type: str | None = None, **_) -> dict:
        """A new issue in a project (platform API), or — when the source names a Jira Service Management service desk and
        request type — a customer request of that type (it shows in the portal and its SLAs start). Returns key + URL."""
        if not (title or "").strip():
            raise AdapterError("A ticket needs a title.")
        if service_desk and request_type:
            r = self.post("/rest/servicedeskapi/request", json={"serviceDeskId": str(service_desk), "requestTypeId": str(request_type),
                                                                 "requestFieldValues": {"summary": title.strip()[:255], "description": description or ""}}).json()
            key = r.get("issueKey") or ""
            if not key:
                raise AdapterError("Jira Service Management did not return the new request's key.")
            extra = {}
            if priority:
                extra["priority"] = {"name": PRIORITY.get(priority, "Medium")}
            if labels:
                extra["labels"] = sorted({str(x).replace(" ", "-") for x in labels})
            if extra:
                self.edit(key, extra)
            return {"key": key, "id": str(r.get("issueId") or ""), "url": f"{self.base}/browse/{key}", "via": "Jira Service Management request"}
        if not (project or "").strip():
            raise AdapterError("Name the Jira project new tickets go to (the source's settings).")
        fields = {"project": {"key": project.strip().upper()}, "summary": title.strip()[:255], "description": adf(description or title), "issuetype": {"name": issue_type or "Task"}}
        if priority:
            fields["priority"] = {"name": PRIORITY.get(priority, "Medium")}
        if labels:
            fields["labels"] = sorted({str(x).replace(" ", "-") for x in labels})
        r = self.post("/rest/api/3/issue", json={"fields": fields}).json()
        if not r.get("key"):
            raise AdapterError("Jira did not return the new issue's key.")
        return {"key": r["key"], "id": str(r.get("id") or ""), "url": f"{self.base}/browse/{r['key']}", "via": "Jira issue"}

    def edit(self, key: str, fields: dict) -> None:
        self.put(f"/rest/api/3/issue/{key}", json={"fields": fields})

    def set_priority(self, key: str, relay_priority: str) -> None:
        self.edit(key, {"priority": {"name": PRIORITY.get(relay_priority, "Medium")}})

    def add_labels(self, key: str, labels: list[str], current: list[str] | None = None) -> None:
        have = list(current if current is not None else self.issue(key)["labels"])
        self.edit(key, {"labels": sorted(set(have) | {l.replace(" ", "-") for l in labels})})

    def transition(self, key: str, transition_id: str) -> None:
        self.post(f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": str(transition_id)}})

    # -- shape
    def normalise(self, issue: dict) -> dict:
        f = issue.get("fields") or {}
        status = f.get("status") or {}
        cat = ((status.get("statusCategory") or {}).get("key") or "").lower()
        desc = f.get("description")
        team = f.get("customfield_10050") or ((f.get("project") or {}).get("name")) or ""
        return normalise("jira", issue.get("key") or "", issue.get("id") or "", f.get("summary") or "", adf_text(desc) if desc else "",
                         status.get("name") or "", cat != "done", (f.get("priority") or {}).get("name") or "",
                         (f.get("reporter") or {}).get("displayName") or "", (f.get("reporter") or {}).get("emailAddress") or "",
                         team if isinstance(team, str) else str(team), parse_time(f.get("created")) or 0.0, parse_time(f.get("updated")) or 0.0,
                         sla_due(f, self.sla_field), f.get("labels") or [], f"{self.base}/browse/{issue.get('key')}", {"issuetype": (f.get("issuetype") or {}).get("name")})
