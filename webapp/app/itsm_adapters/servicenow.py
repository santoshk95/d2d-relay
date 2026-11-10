"""ServiceNow Table API (the incident table): open incidents of the assignment groups the source reads (paged with
sysparm_offset, every field as {value, display_value}), one incident, work notes (internal) and field edits
(impact / urgency, which ServiceNow turns into the priority), and (consolidation) creating an incident. Sign-in: a
service account's user name + password (Basic), or an OAuth bearer token. Every write is reached only through
itsm.py, after a person's approval."""
from __future__ import annotations

from datetime import datetime, timezone

from . import AdapterError, Client, NotFound, normalise, parse_time

OPEN = ("1", "2", "3")                                  # New, In Progress, On Hold (6 Resolved, 7 Closed, 8 Canceled)
IMPACT_URGENCY = {"P1": ("1", "1"), "P2": ("1", "2"), "P3": ("2", "2"), "P4": ("3", "3")}    # the default priority lookup gives 1, 2, 3, 4
PRIORITY = {k: v for k, v in IMPACT_URGENCY.items()}
FIELDS = ("sys_id,number,short_description,description,state,priority,impact,urgency,caller_id,assignment_group,opened_at,sys_updated_on,"
          "due_date,sla_due,category,u_relay_labels")


def _v(f: dict, key: str) -> str:
    x = f.get(key)
    return str((x.get("value") if isinstance(x, dict) else x) or "")


def _d(f: dict, key: str) -> str:
    x = f.get(key)
    return str((x.get("display_value") if isinstance(x, dict) else x) or "")


def _time(s: str) -> float | None:
    """ServiceNow's values are UTC 'YYYY-MM-DD HH:MM:SS'."""
    return parse_time(s.replace(" ", "T") + "Z") if s and len(s) >= 19 else parse_time(s) if s else None


class ServiceNow(Client):
    label = "ServiceNow"

    def __init__(self, base_url: str, user: str, secret: str, groups: list[str] | None = None, **kw):
        super().__init__(base_url, auth=(user, secret) if user else None, bearer=None if user else secret, **kw)
        self.group_names = [g.strip() for g in (groups or []) if g.strip()]
        self.user = user

    # -- reads
    def groups(self) -> list[str]:
        rows = self.get("/api/now/table/sys_user_group", params={"sysparm_fields": "name", "sysparm_limit": 500}).json().get("result") or []
        return sorted(r.get("name") or "" for r in rows if r.get("name"))

    def test(self) -> dict:
        names = self.groups()
        low = {n.lower() for n in names}
        missing = [g for g in self.group_names if g.lower() not in low]
        return {"account": self.user or "OAuth token", "groups": names, "missing": missing, "ok": not missing}

    def query(self, since: float | None = None) -> str:
        q = ["active=true", "stateIN" + ",".join(OPEN)]
        if self.group_names:
            q.append("assignment_group.nameIN" + ",".join(self.group_names))
        if since:
            q.append("sys_updated_on>=" + datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        return "^".join(q) + "^ORDERBYopened_at"

    def tickets(self, since: float | None = None, page_size: int = 100):
        """Every open incident of the groups the source reads, every page (sysparm_offset until a short page)."""
        offset = 0
        while True:
            rows = self.get("/api/now/table/incident", params={"sysparm_query": self.query(since), "sysparm_limit": page_size, "sysparm_offset": offset,
                                                              "sysparm_display_value": "all", "sysparm_exclude_reference_link": "true", "sysparm_fields": FIELDS}).json().get("result") or []
            for r in rows:
                yield self.normalise(r)
            if len(rows) < page_size:
                break
            offset += page_size

    def _sys_id(self, key: str) -> str:
        if len(key) == 32 and all(c in "0123456789abcdef" for c in key):
            return key
        rows = self.get("/api/now/table/incident", params={"sysparm_query": f"number={key}", "sysparm_fields": "sys_id", "sysparm_limit": 1}).json().get("result") or []
        if not rows:
            raise NotFound(f"ServiceNow: {key} was not found.")
        return _v(rows[0], "sys_id")

    def issue(self, key: str) -> dict:
        r = self.get(f"/api/now/table/incident/{self._sys_id(key)}", params={"sysparm_display_value": "all", "sysparm_exclude_reference_link": "true", "sysparm_fields": FIELDS})
        return self.normalise(r.json().get("result") or {})

    # -- writes (only through itsm.py: write_back after the group's approval, perform_write after a per-change approval)
    def comment(self, key: str, text: str) -> dict:
        """A work note: internal, the caller does not see it."""
        return self.request("PATCH", f"/api/now/table/incident/{self._sys_id(key)}", json={"work_notes": text}).json().get("result") or {}

    def edit(self, key: str, fields: dict) -> dict:
        return self.request("PATCH", f"/api/now/table/incident/{self._sys_id(key)}", json=fields).json().get("result") or {}

    def set_priority(self, key: str, relay_priority: str) -> None:
        impact, urgency = IMPACT_URGENCY.get(relay_priority, ("2", "2"))
        self.edit(key, {"impact": impact, "urgency": urgency})

    def add_comment(self, key: str, text: str) -> dict:
        r = self.comment(key, text)
        sid = _v(r, "sys_id") or self._sys_id(key)
        return {"key": key, "id": sid, "url": f"{self.base}/nav_to.do?uri=incident.do?sys_id={sid}"}

    def create_issue(self, project: str, title: str, description: str, *, priority: str | None = None, requester: str | None = None, **_) -> dict:
        """A new incident in an assignment group (`project` is the group's name), with impact and urgency from the
        priority; the caller is the requester the source names (else the service account)."""
        if not (title or "").strip():
            raise AdapterError("An incident needs a short description.")
        impact, urgency = IMPACT_URGENCY.get(priority or "P3", ("2", "2"))
        body = {"short_description": title.strip()[:160], "description": description or title, "impact": impact, "urgency": urgency}
        if project:
            body["assignment_group"] = project.strip()
        if requester or self.user:
            body["caller_id"] = (requester or self.user).strip()
        r = self.post("/api/now/table/incident", params={"sysparm_input_display_value": "true"}, json=body).json().get("result") or {}
        key, sid = _v(r, "number"), _v(r, "sys_id")
        if not key:
            raise AdapterError("ServiceNow did not return the new incident's number.")
        return {"key": key, "id": sid, "url": f"{self.base}/nav_to.do?uri=incident.do?sys_id={sid}", "via": "ServiceNow incident"}

    # -- shape
    def normalise(self, r: dict) -> dict:
        state = _v(r, "state")
        labels = [x.strip() for x in _v(r, "u_relay_labels").split(",") if x.strip()]
        return normalise("servicenow", _v(r, "number"), _v(r, "sys_id"), _v(r, "short_description"), _v(r, "description"), _d(r, "state") or state, state in OPEN,
                         _d(r, "priority").split(" - ", 1)[-1] if _d(r, "priority") else "", _d(r, "caller_id"), "", _d(r, "assignment_group"),
                         _time(_v(r, "opened_at")) or 0.0, _time(_v(r, "sys_updated_on")) or 0.0, _time(_v(r, "sla_due")) or _time(_v(r, "due_date")), labels,
                         f"{self.base}/nav_to.do?uri=incident.do?sys_id={_v(r, 'sys_id')}", {"category": _v(r, "category")})
