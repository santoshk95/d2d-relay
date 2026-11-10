"""HR adapters (W3, registry id `hr`): Workday (REST API v1 with an OAuth 2.0 refresh-token API client, and Reports-as-a-
Service with the integration system user's basic auth) and SAP SuccessFactors (OData v2 Employee Central with the OAuth
2.0 SAML bearer flow; Integration Center runs from Execution Manager) behind the Connector SDK. Workers are the canonical
`worker` (key, name, e-mail, department, country, status, end date); each platform's integration history is its runs.
Writes carry X-Relay-Approval: SuccessFactors' upsert creates a joiner's User. Oracle Fusion HCM, Zoho People,
Darwinbox and Keka come in as exports for now.

Mock lab stand-ins (tests/mocklab/sims/hr.py): workday, successfactors.
"""
from __future__ import annotations

import base64

from .. import connectors
from ._systems import SysAdapter, day, register, when

WD_RAAS_WORKERS = "INT_Workers_All"
WD_RAAS_EVENTS = "INT_Integration_Events"
SF_STATE = {"COMPLETED": "succeeded", "FAILED": "failed", "RUNNING": "running", "IN_PROGRESS": "running", "PENDING": "queued", "CANCELLED": "cancelled"}


class Workday(SysAdapter):
    kind, label, category = "workday", "Workday", "hr"
    simulator = "workday"
    can_write = False
    docs = "https://community.workday.com/sites/default/files/file-hosting/restapi/index.html"
    signin = ["service_account"]
    fields = [("base_url", "Workday REST host (https://wd2-impl-services1.workday.com)", True), ("tenant", "Tenant name", True), ("client_id", "API client id", True),
              ("isu_username", "Integration system user for reports (ISU_…@tenant)", True), ("raas_owner", "Report owner (the ISU's account name)", True)]
    secrets = {"service_account": ["client_secret", "refresh_token", "isu_password"]}
    ENTITIES = {"worker": (WD_RAAS_WORKERS, "Workers (Reports-as-a-Service, with leavers)")}
    JOBS = "Integration events"

    def sign_in(self, api):
        t = api.cfg.get("tenant")
        r = api.raw("POST", f"/ccx/oauth2/{t}/token", data={"grant_type": "refresh_token", "refresh_token": api.secret("refresh_token"),
                                                             "client_id": api.cfg.get("client_id"), "client_secret": api.secret("client_secret")})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Workday refused the API client's refresh token: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def error_text(self, r):
        try:
            b = r.json()
            return b.get("error_description") or b.get("error") or super().error_text(r)
        except ValueError:
            return super().error_text(r)

    def _raas(self, api, report: str, params: dict | None = None) -> list[dict]:
        """A Workday custom report as JSON — RaaS takes the integration system user's basic auth, not the API token."""
        isu = f"{api.cfg.get('isu_username')}:{api.secret('isu_password')}"
        b = api.get(f"/ccx/service/customreport2/{api.cfg.get('tenant')}/{api.cfg.get('raas_owner')}/{report}", {"format": "json", **(params or {})},
                    headers={"Authorization": "Basic " + base64.b64encode(isu.encode()).decode()})
        return b.get("Report_Entry") or []

    def active_workers(self, api) -> list[dict]:
        """The REST API's workers (active only), paged with limit (at most 100) / offset — what the API client sees."""
        out, off = [], 0
        for _ in range(1000):
            b = api.get(f"/ccx/api/v1/{api.cfg.get('tenant')}/workers", {"limit": 100, "offset": off})
            out += b.get("data") or []
            off += 100
            if off >= int(b.get("total") or 0):
                return out
        return out

    def fetch(self, api, entity):
        if entity == "worker":
            return self._raas(api, WD_RAAS_WORKERS)
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "worker":
            return {"key": r.get("Employee_ID"), "number": r.get("Employee_ID"), "name": r.get("Worker"), "email": r.get("Email_Work") or None, "department": r.get("Supervisory_Organization"),
                    "status": "terminated" if str(r.get("Worker_Status") or "").lower() == "terminated" else "active", "end_date": day(r.get("Termination_Date")) or None,
                    "hired": day(r.get("Hire_Date")) or None, "cost_centre": r.get("Cost_Center")}
        return r

    def runs(self, api):
        rows = self._raas(api, WD_RAAS_EVENTS)
        out = [{"job": e.get("Integration_System"), "label": e.get("Integration_System"), "id": e.get("Event_ID"), "started": when(e.get("Initiated")), "ended": when(e.get("Completed")),
                "status": {"Completed": "succeeded", "Failed": "failed", "In Progress": "running"}.get(e.get("Status"), "unknown"),
                "error": e.get("Messages") or None if e.get("Status") == "Failed" else None} for e in rows]
        return sorted(out, key=lambda r: r["started"] or 0, reverse=True)

    def test(self, c):
        out = super().test(c)
        if out.get("status") == "connected":
            api = self.session(c)
            try:
                n = len(self.active_workers(api))
                out["sees"] = (out.get("sees") or "") + f"; the REST API sees {n} active worker(s)"
            finally:
                api.close()
        return out


class SuccessFactors(SysAdapter):
    kind, label, category = "successfactors", "SAP SuccessFactors", "hr"
    simulator = "successfactors"
    docs = "https://help.sap.com/docs/SAP_SUCCESSFACTORS_PLATFORM/d599f15995d348a1b45ba5603e2aba9b/"
    signin = ["service_account"]
    fields = [("base_url", "API server (https://api<n>.successfactors.com)", True), ("company_id", "Company id", True), ("client_id", "OAuth client (API key)", True),
              ("user_id", "API user", True)]
    secrets = {"service_account": ["private_key"]}
    ENTITIES = {"worker": ("User", "Users (Employee Central)")}
    CREATES = ("worker",)
    WRITABLE = {"worker": {"department": "department", "email": "email", "status": "status"}}
    DEACTIVATE = {"worker": {"status": "terminated"}}
    JOBS = "Integration Center processes"

    def sign_in(self, api):
        cid, uid = api.cfg.get("client_id"), api.cfg.get("user_id")
        r = api.raw("POST", "/oauth/idp", data={"client_id": cid, "user_id": uid, "token_url": api.url("/oauth/token"), "private_key": api.secret("private_key")})
        if r.status_code != 200:
            raise connectors.Reconsent(f"SuccessFactors did not issue a SAML assertion: {self.error_text(r)}")
        t = api.raw("POST", "/oauth/token", data={"company_id": api.cfg.get("company_id"), "client_id": cid, "grant_type": "urn:ietf:params:oauth:grant-type:saml2-bearer",
                                                   "assertion": r.text.strip()})
        if t.status_code != 200:
            raise connectors.Reconsent(f"SuccessFactors refused the SAML assertion: {self.error_text(t)}")
        return {"Authorization": "Bearer " + t.json()["access_token"], "Accept": "application/json"}

    def error_text(self, r):
        try:
            b = r.json()
            if isinstance(b.get("error"), dict):
                return f"{b['error'].get('code')}: {(b['error'].get('message') or {}).get('value')}"
            return b.get("errorMessage") or super().error_text(r)
        except (ValueError, AttributeError):
            return super().error_text(r)

    def _all(self, api, entity: str, params: dict | None = None) -> list[dict]:
        """OData v2 with server paging: d.results, then d.__next until there is none."""
        out, url, p = [], f"/odata/v2/{entity}", {"$format": "json", **(params or {})}
        for _ in range(1000):
            b = api.get(url, p)
            d = b.get("d") or {}
            out += d.get("results") if isinstance(d, dict) else d or []
            nxt = d.get("__next") if isinstance(d, dict) else None
            if not nxt:
                return out
            url, p = nxt, None
        return out

    def fetch(self, api, entity):
        if entity == "worker":
            ends = {e["userId"]: e.get("endDate") for e in self._all(api, "EmpEmployment")}
            return [{**u, "_endDate": ends.get(u.get("userId"))} for u in self._all(api, "User")]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "worker":
            return {"key": r.get("userId"), "number": r.get("userId"), "name": f"{r.get('firstName') or ''} {r.get('lastName') or ''}".strip(), "email": r.get("email") or None, "department": r.get("department"),
                    "status": "active" if str(r.get("status")).lower() in ("t", "true", "active") else "terminated", "end_date": day(r.get("_endDate")) or None,
                    "hired": day(r.get("hireDate")) or None}
        return r

    def runs(self, api):
        errs = {e["processId"]: e.get("eventDescription") for e in self._all(api, "EMEvent") if e.get("eventType") == "ERROR"}
        out = [{"job": p.get("processDefinitionId"), "label": p.get("processDefinitionName") or p.get("processDefinitionId"), "id": p.get("processInstanceId"),
                "started": None, "ended": when(p.get("lastEventTimestamp")), "status": SF_STATE.get(p.get("processState"), "unknown"),
                "error": errs.get(p.get("processInstanceId")) if p.get("processState") == "FAILED" else None} for p in self._all(api, "EMMonitoredProcess")]
        for r in out:
            r["started"] = r["ended"]
        return sorted(out, key=lambda r: r["ended"] or 0, reverse=True)

    def payload(self, entity, rec):
        if entity != "worker":
            return super().payload(entity, rec)
        first, _, last = str(rec.get("name") or "").partition(" ")
        return {"userId": rec.get("number") or rec.get("key") or "", "username": str(rec.get("email") or "").split("@")[0], "firstName": first, "lastName": last or first,
                "email": rec.get("email") or "", "department": rec.get("department") or "", "status": "t"}

    def problems(self, c, entity, rec):
        out = []
        if entity == "worker":
            if not (rec.get("number") or rec.get("key")):
                out.append("SuccessFactors needs the joiner's user id (userId): map the employee number")
            if not rec.get("email"):
                out.append("a joiner needs a work e-mail")
        return out

    def _upsert(self, api, body: dict, approval: str) -> dict:
        r = api.request("POST", "/odata/v2/upsert", params={"$format": "json"}, json=body, headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "upsert", (200, 201))
        rows = b.get("d") if isinstance(b, dict) else b
        row = (rows if isinstance(rows, list) else [rows] if rows else [{}])[0] or {}
        if row.get("status") != "OK":
            raise connectors.ConnectorError(f"SuccessFactors refused the record: {row.get('message') or row}")
        return row

    def op_create(self, api, entity, rec, approval):
        body = {"__metadata": {"uri": f"User('{rec['userId']}')"}, **{k: v for k, v in rec.items() if not k.startswith("_")}}
        self._upsert(api, body, approval)
        return {"id": rec["userId"]}

    def op_update(self, api, entity, key, changes, approval):
        body = {"__metadata": {"uri": f"User('{key}')"}, "userId": key}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a SuccessFactors user through Relay")
            body[col] = ("f" if str(v).lower() in ("terminated", "inactive", "blocked") else "t") if f == "status" else v
        self._upsert(api, body, approval)
        return {"id": key}


ADAPTERS = [register(a) for a in (Workday(), SuccessFactors())]
