"""CRM adapters (W3, registry id `crm`): Salesforce (REST API + SOQL, OAuth 2.0 client credentials) and HubSpot (CRM API
v3, a private app token) behind the Connector SDK — accounts / companies as canonical customers, contacts,
opportunities as deals, and each platform's run history (AsyncApexJob; HubSpot's imports with their row errors). Every
write carries X-Relay-Approval. Dynamics 365 CE, Zoho CRM and Freshsales come in as exports for now.

Mock lab stand-ins (tests/mocklab/sims/crm.py): salesforce, hubspot.
"""
from __future__ import annotations

from .. import connectors
from ._systems import SysAdapter, day, iso2, num, register, when

SF_V = "v61.0"
SF_STATUS = {"Completed": "succeeded", "Failed": "failed", "Processing": "running", "Preparing": "running", "Queued": "queued", "Holding": "queued", "Aborted": "cancelled"}
COUNTRY_NAME = {"GB": "United Kingdom", "IN": "India", "US": "United States", "IE": "Ireland", "DE": "Germany", "FR": "France"}


class Salesforce(SysAdapter):
    kind, label, category = "salesforce", "Salesforce", "crm"
    simulator = "salesforce"
    docs = "https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/"
    signin = ["service_account"]
    fields = [("base_url", "My Domain (https://<domain>.my.salesforce.com)", True), ("client_id", "Connected app's consumer key", True)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"customer": ("Account", "Accounts"), "contact": ("Contact", "Contacts"), "deal": ("Opportunity", "Opportunities")}
    CREATES = ("customer",)
    WRITABLE = {"customer": {"name": "Name", "city": "BillingCity", "number": "AccountNumber", "type": "Type"}}
    JOBS = "Asynchronous Apex jobs"
    FIELDS = {"Account": "Id, Name, AccountNumber, Type, BillingCity, BillingCountry, CreatedDate", "Contact": "Id, FirstName, LastName, Email, AccountId, CreatedDate",
              "Opportunity": "Id, Name, StageName, Amount, CloseDate, AccountId"}

    def sign_in(self, api):
        r = api.raw("POST", "/services/oauth2/token", data={"grant_type": "client_credentials", "client_id": api.cfg.get("client_id"), "client_secret": api.secret("client_secret")})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Salesforce refused the connected app's sign-in: {self.error_text(r)}")
        b = r.json()
        api.base = (b.get("instance_url") or api.base).rstrip("/")         # the org's own instance from here on
        return {"Authorization": "Bearer " + b["access_token"], "Accept": "application/json"}

    def throttled(self, r):
        return r.status_code == 403 and "REQUEST_LIMIT_EXCEEDED" in (r.text or "")

    def error_text(self, r):
        try:
            b = r.json()
            if isinstance(b, list) and b:
                return f"{b[0].get('errorCode')}: {b[0].get('message')}"
            return b.get("error_description") or super().error_text(r)
        except ValueError:
            return super().error_text(r)

    def soql(self, api, q: str) -> list[dict]:
        out, b = [], api.get(f"/services/data/{SF_V}/query", {"q": q}, headers={"Sforce-Query-Options": "batchSize=2000"})
        for _ in range(1000):
            out += [{k: v for k, v in r.items() if k != "attributes"} for r in b.get("records") or []]
            if b.get("done", True) or not b.get("nextRecordsUrl"):
                return out
            b = api.get(b["nextRecordsUrl"], headers={"Sforce-Query-Options": "batchSize=2000"})
        return out

    def fetch(self, api, entity):
        if entity in self.ENTITIES:
            obj = self.ENTITIES[entity][0]
            return self.soql(api, f"SELECT {self.FIELDS[obj]} FROM {obj}")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "customer":
            return {"key": r["Id"], "number": r.get("AccountNumber"), "name": r.get("Name"), "country": iso2(r.get("BillingCountry")) or None, "city": r.get("BillingCity"),
                    "status": "active", "created": day(r.get("CreatedDate")), "type": r.get("Type")}
        if entity == "contact":
            return {"key": r["Id"], "name": f"{r.get('FirstName') or ''} {r.get('LastName') or ''}".strip(), "email": r.get("Email"), "account": r.get("AccountId"), "status": "active"}
        if entity == "deal":
            return {"key": r["Id"], "name": r.get("Name"), "account": r.get("AccountId"), "amount": num(r.get("Amount")), "stage": r.get("StageName"), "close_date": day(r.get("CloseDate"))}
        return r

    def runs(self, api):
        rows = self.soql(api, "SELECT Id, ApexClassName, JobType, Status, NumberOfErrors, ExtendedStatus, CreatedDate, CompletedDate FROM AsyncApexJob ORDER BY CreatedDate DESC")
        return [{"job": r["ApexClassName"], "label": r["ApexClassName"], "id": r["Id"], "started": when(r.get("CreatedDate")), "ended": when(r.get("CompletedDate")),
                 "status": SF_STATUS.get(r.get("Status"), "unknown"), "error": r.get("ExtendedStatus") if r.get("Status") == "Failed" else None} for r in rows]

    def payload(self, entity, rec):
        if entity != "customer":
            return super().payload(entity, rec)
        body = {"Name": rec.get("name"), "AccountNumber": rec.get("number") or None, "BillingCity": rec.get("city") or None,
                "BillingCountry": COUNTRY_NAME.get(str(rec.get("country") or ""), rec.get("country")) or None, "Type": rec.get("type") or "Customer"}
        return {k: v for k, v in body.items() if v not in (None, "")}

    def op_create(self, api, entity, rec, approval):
        r = api.request("POST", f"/services/data/{SF_V}/sobjects/Account", json=rec, headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "Account", (201,))
        return {"id": b.get("id")}

    def op_update(self, api, entity, key, changes, approval):
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a Salesforce account through Relay")
            body[col] = v
        self.check(api.request("PATCH", f"/services/data/{SF_V}/sobjects/Account/{key}", json=body, headers={"Content-Type": "application/json"}, approval=approval), f"Account {key}", (204,))
        return {"id": key}


class HubSpot(SysAdapter):
    kind, label, category = "hubspot", "HubSpot", "crm"
    simulator = "hubspot"
    docs = "https://developers.hubspot.com/docs/api/crm/understanding-the-crm"
    signin = ["api_key"]
    fields = [("base_url", "API base (https://api.hubapi.com)", True)]
    secrets = {"api_key": ["access_token"]}
    ENTITIES = {"customer": ("companies", "Companies"), "contact": ("contacts", "Contacts")}
    CREATES = ("customer",)
    WRITABLE = {"customer": {"name": "name", "city": "city", "number": "erp_customer_code", "domain": "domain"}}
    JOBS = "Imports"

    def sign_in(self, api):
        return {"Authorization": "Bearer " + api.secret("access_token"), "Accept": "application/json"}

    def _all(self, api, path, props):
        out, after = [], None
        for _ in range(1000):
            b = api.get(path, {"limit": 100, "properties": props, **({"after": after} if after else {})})
            out += b.get("results") or []
            after = ((b.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                return out
        return out

    def fetch(self, api, entity):
        if entity == "customer":
            return self._all(api, "/crm/v3/objects/companies", "name,domain,city,country,lifecyclestage,erp_customer_code")
        if entity == "contact":
            return self._all(api, "/crm/v3/objects/contacts", "email,firstname,lastname,company")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        p = r.get("properties") or {}
        if entity == "customer":
            return {"key": r["id"], "number": p.get("erp_customer_code"), "name": p.get("name"), "city": p.get("city"), "country": iso2(p.get("country")) or None,
                    "status": "blocked" if r.get("archived") else "active", "created": day(r.get("createdAt")), "domain": p.get("domain")}
        if entity == "contact":
            return {"key": r["id"], "name": f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip(), "email": p.get("email"), "account": p.get("company"), "status": "active"}
        return r

    def runs(self, api):
        out, after = [], None
        for _ in range(100):
            b = api.get("/crm/v3/imports", {"limit": 100, **({"after": after} if after else {})})
            for i in b.get("results") or []:
                c = (i.get("metadata") or {}).get("counters") or {}
                name = str(i.get("importName") or "import")
                job = name.rsplit(" ", 1)[0] if name[-10:-8] == "20" or name[-10:].count("-") == 2 else name
                out.append({"job": job, "label": job, "id": i["id"], "started": when(i.get("createdAt")), "ended": when(i.get("updatedAt")),
                            "status": ("failed" if c.get("ERRORS") else "succeeded") if i.get("state") == "DONE" else "running" if i.get("state") in ("STARTED", "PROCESSING") else "failed",
                            "error": None, "errors": c.get("ERRORS") or 0})
            after = ((b.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break
        out.sort(key=lambda r: r["started"] or 0, reverse=True)
        seen = set()
        for r in out:                                       # the row errors of each import's latest failure
            if r["status"] == "failed" and r["job"] not in seen:
                seen.add(r["job"])
                r["error"] = " ".join(self.job_log(api, r))[:500] or None
        return out

    def job_log(self, api, run):
        errs = api.get(f"/crm/v3/imports/{run['id']}/errors").get("results") or []
        kinds: dict[str, list] = {}
        for e in errs:
            kinds.setdefault(e.get("errorType") or "ERROR", []).append(f"line {((e.get('sourceData') or {}).get('lineNumber'))}: {e.get('invalidValue')}")
        return [f"{len(v)} row(s) refused with {k} ({'; '.join(v[:3])})" for k, v in kinds.items()]

    def payload(self, entity, rec):
        if entity != "customer":
            return super().payload(entity, rec)
        props = {"name": rec.get("name"), "city": rec.get("city"), "country": COUNTRY_NAME.get(str(rec.get("country") or ""), rec.get("country")), "erp_customer_code": rec.get("number"),
                 "domain": rec.get("domain") or (str(rec.get("email") or "").split("@")[-1] if rec.get("email") else None), "lifecyclestage": "customer"}
        return {"properties": {k: v for k, v in props.items() if v not in (None, "")}}

    def op_create(self, api, entity, rec, approval):
        b = self.check(api.request("POST", "/crm/v3/objects/companies", json=rec, headers={"Content-Type": "application/json"}, approval=approval), "companies", (201,))
        return {"id": b.get("id")}

    def op_update(self, api, entity, key, changes, approval):
        props = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a HubSpot company through Relay")
            props[col] = v
        self.check(api.request("PATCH", f"/crm/v3/objects/companies/{key}", json={"properties": props}, headers={"Content-Type": "application/json"}, approval=approval), f"company {key}", (200,))
        return {"id": key}


ADAPTERS = [register(a) for a in (Salesforce(), HubSpot())]
