"""PLM adapters (W3, registry id `plm`): Siemens Teamcenter (JSON REST over the SOA services: a session login that sets
JSESSIONID, saved queries for items and workflow processes, createItems) and PTC Windchill (Windchill REST Services,
OData v4 with @odata.nextLink; basic auth; every modifying request carries the CSRF nonce from PTC/GetCSRFToken())
behind the Connector SDK. Parts are the canonical `part` (key, number, name, revision, state, type, modified) and
engineering changes the canonical `change` (key, name, state, due, owner, overdue days); Teamcenter's workflow runs are
its runs. Writes carry X-Relay-Approval: a part / item created. 3DEXPERIENCE, Agile, SAP PLM, Aras and Arena come in as
exports for now.

Mock lab stand-ins (tests/mocklab/sims/plm.py): teamcenter, windchill.
"""
from __future__ import annotations

import time

from .. import connectors
from .. import workbench as wb
from ._systems import SysAdapter, day, register, when

TCJ = "/tc/JsonRestServices"
WC = "/Windchill/servlet/odata"
DONE = ("released", "resolved", "completed", "cancelled", "obsolete", "implemented")


def _overdue(due: str | None, state: str | None) -> int | None:
    if not due or str(state or "").lower() in DONE:
        return None
    d = (wb.lab_now() - time.mktime(time.strptime(due, "%Y-%m-%d"))) // 86400
    return int(d) if d > 0 else 0


class Teamcenter(SysAdapter):
    kind, label, category = "teamcenter", "Siemens Teamcenter", "plm"
    simulator = "teamcenter"
    docs = "https://docs.sw.siemens.com/en-US/doc/282219420/"
    signin = ["password"]
    fields = [("base_url", "Teamcenter web tier (https://<host>)", True), ("user", "User", True), ("group", "Group", False), ("role", "Role", False)]
    secrets = {"password": ["password"]}
    ENTITIES = {"part": ("Item", "Items (the Item... saved query) - keyed by item id"), "change": ("EPMJob", "Workflow processes")}
    CREATES = ("part",)
    JOBS = "Workflow processes"

    def _body(self, body: dict) -> dict:
        return {"header": {"state": {}, "policy": {}}, "body": body}

    def sign_in(self, api):
        cr = {"user": api.cfg.get("user"), "password": api.secret("password"), "group": api.cfg.get("group") or "", "role": api.cfg.get("role") or "", "locale": "en_US",
              "descrimator": "relay"}
        r = api.raw("POST", f"{TCJ}/Core-2011-06-Session/login", json=self._body({"credentials": cr}), headers={"Content-Type": "application/json"})
        b = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or "Exception" in str(b.get(".QName", "")) or "JSESSIONID" not in api.cookies:
            raise connectors.Reconsent(f"Teamcenter refused the login: {b.get('message') or self.error_text(r)}")
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def expired(self, r):
        return r.status_code == 401 or "InvalidUserException" in (r.text or "")[:300]

    def on_expired(self, api):
        api.cookies.clear()

    def _call(self, api, op: str, body: dict) -> dict:
        b = api.json("POST", f"{TCJ}/{op}", json=self._body(body), what=op)
        if "Exception" in str(b.get(".QName", "")):
            raise connectors.ConnectorError(f"Teamcenter: {b.get('code')} {b.get('message')}")
        return b

    def _query(self, api, name: str) -> list[dict]:
        found = self._call(api, "Query-2010-04-SavedQuery/findSavedQueries", {"inputCriteria": [{"queryNames": [name], "queryDescs": [], "queryType": 0}]})
        q = (found.get("savedQueries") or [None])[0]
        if not q:
            raise connectors.ConnectorError(f"Teamcenter has no saved query \"{name}\".")
        entry = "Item ID" if name == "Item..." else "Status"
        res = self._call(api, "Query-2008-06-SavedQuery/executeSavedQueries", {"input": [{"query": q, "entries": [entry], "values": ["*"], "maxNumToReturn": 0, "limitList": [],
                                                                                          "resultsType": 0}]})
        mo = (res.get("ServiceData") or {}).get("modelObjects") or {}
        out = []
        for o in mo.values():
            props = {k: ((v.get("dbValues") or [None])[0]) for k, v in (o.get("props") or {}).items()}
            out.append({"uid": o["uid"], "className": o.get("className"), **props})
        return out

    def fetch(self, api, entity):
        if entity == "part":
            return self._query(api, "Item...")
        if entity == "change":
            return [j for j in self._query(api, "Workflow Processes") if str(j.get("object_name", "")).upper().startswith(("ECN", "ECR", "ECO"))]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "part":
            return {"key": r.get("item_id") or r["uid"], "number": r.get("item_id"), "name": r.get("object_name"), "revision": r.get("item_revision_id"), "uid": r["uid"], "state": (r.get("release_status_list") or "In work").lower(),
                    "type": r.get("className"), "modified": day(r.get("last_mod_date")) or None}
        if entity == "change":
            st = str(r.get("fnd0Status") or "").lower()
            due = day(r.get("due_date")) or None
            return {"key": r["uid"], "name": r.get("object_name"), "state": "completed" if st == "completed" else "aborted" if st == "aborted" else "under review" if st == "started" else st,
                    "due": due, "owner": r.get("fnd0WorkflowInitiator"), "overdue_days": _overdue(due, "completed" if st == "completed" else st)}
        return r

    def runs(self, api):
        out = []
        for j in self._query(api, "Workflow Processes"):
            name = str(j.get("object_name") or "")
            if name.upper().startswith(("ECN", "ECR", "ECO")):
                continue                                       # changes are records, not runs
            job = " ".join(w for w in name.split() if not w.isdigit()) or name
            st = str(j.get("fnd0Status") or "")
            out.append({"job": job, "label": job, "id": j["uid"], "started": when(j.get("creation_date")), "ended": when(j.get("last_mod_date")),
                        "status": {"Completed": "succeeded", "Aborted": "failed", "Started": "running"}.get(st, "unknown"),
                        "error": f"The workflow process {name} was aborted" if st == "Aborted" else None})
        return sorted(out, key=lambda r: r["started"] or 0, reverse=True)

    def payload(self, entity, rec):
        if entity != "part":
            return super().payload(entity, rec)
        return {"clientId": rec.get("number") or rec.get("name"), "itemId": rec.get("number") or "", "name": rec.get("name"), "type": "Item", "description": rec.get("type") or "",
                "itemRevisionId": rec.get("revision") or "A"}

    def problems(self, c, entity, rec):
        return ["a Teamcenter item needs a name"] if entity == "part" and not rec.get("name") else []

    def op_create(self, api, entity, rec, approval):
        r = api.request("POST", f"{TCJ}/Core-2006-03-DataManagement/createItems", json=self._body({"properties": [{k: v for k, v in rec.items() if not k.startswith("_")}]}),
                        headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "createItems")
        errs = (b.get("ServiceData") or {}).get("partialErrors") or []
        if errs:
            ev = (errs[0].get("errorValues") or [{}])[0]
            raise connectors.ConnectorError(f"Teamcenter refused the item: {ev.get('code')} {ev.get('message')}")
        uid = ((b.get("output") or [{}])[0].get("item") or {}).get("uid")
        mo = ((b.get("ServiceData") or {}).get("modelObjects") or {}).get(uid) or {}
        return {"id": (((mo.get("props") or {}).get("item_id") or {}).get("dbValues") or [rec.get("itemId") or uid])[0]}   # items are keyed by their item id


class Windchill(SysAdapter):
    kind, label, category = "windchill", "PTC Windchill", "plm"
    simulator = "windchill"
    docs = "https://support.ptc.com/help/wnc/r13.0.0.0/en/#page/Windchill_Help_Center/WCRESTOverview.html"
    signin = ["password"]
    fields = [("base_url", "Windchill server (https://<host>)", True), ("username", "User", True), ("container", "Product context (Containers('OR:...'))", True)]
    secrets = {"password": ["password"]}
    ENTITIES = {"part": ("Parts", "Parts (ProdMgmt) - keyed by part number"), "change": ("ChangeNotices", "Change notices (ChangeMgmt)")}
    CREATES = ("part",)
    JOBS = "Workflow work items"

    def sign_in(self, api):
        import base64
        tok = base64.b64encode(f"{api.cfg.get('username')}:{api.secret('password')}".encode()).decode()
        return {"Authorization": "Basic " + tok, "Accept": "application/json"}

    def error_text(self, r):
        try:
            b = r.json()
            return (b.get("error") or {}).get("message") or super().error_text(r)
        except (ValueError, AttributeError):
            return super().error_text(r)

    def _all(self, api, path, params=None):
        out, url, p = [], path, params
        for _ in range(1000):
            b = api.get(url, p)
            out += b.get("value") or []
            if not b.get("@odata.nextLink"):
                return out
            url, p = b["@odata.nextLink"], None
        return out

    def fetch(self, api, entity):
        if entity == "part":
            return self._all(api, f"{WC}/ProdMgmt/Parts")
        if entity == "change":
            return self._all(api, f"{WC}/ChangeMgmt/ChangeNotices")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "part":
            return {"key": r.get("Number") or r["ID"], "number": r.get("Number"), "name": r.get("Name"), "revision": str(r.get("Version") or "").split(".")[0] or None,  # A.1 = revision A, iteration 1
                    "iteration": (str(r.get("Version") or "").split(".") + [""])[1] or None, "oid": r["ID"], "state": str((r.get("State") or {}).get("Value") or "").lower(),
                    "type": (r.get("Source") or {}).get("Display"), "modified": day(r.get("LastModified")) or None}
        if entity == "change":
            st = str((r.get("State") or {}).get("Value") or "").lower()
            due = day(r.get("NeedDate")) or None
            return {"key": r["ID"], "name": f"{r.get('Number')} {r.get('Name')}", "state": "under review" if st == "underreview" else st, "due": due, "owner": None,
                    "overdue_days": _overdue(due, st)}
        return r

    def payload(self, entity, rec):
        if entity != "part":
            return super().payload(entity, rec)
        return {"Name": rec.get("name"), **({"Number": rec["number"]} if rec.get("number") else {}), "Source": {"Value": "make"}, "DefaultUnit": {"Value": "ea"}}

    def problems(self, c, entity, rec):
        out = []
        if entity == "part":
            if not rec.get("name"):
                out.append("a Windchill part needs a name")
            if not ((c.get("config") or {}).get("container")):
                out.append("set the product context (container) on the connection")
        return out

    def op_create(self, api, entity, rec, approval):
        nonce = api.get(f"{WC}/PTC/GetCSRFToken()").get("NonceValue")              # every modifying request carries a fresh nonce
        body = {k: v for k, v in rec.items() if not k.startswith("_")} | {"Context@odata.bind": api.cfg.get("container")}
        r = api.request("POST", f"{WC}/ProdMgmt/Parts", json=body, headers={"Content-Type": "application/json", "CSRF_NONCE": nonce or ""}, approval=approval)
        b = self.check(r, "Parts", (201,))
        return {"id": b.get("Number") or b.get("ID")}                          # parts are keyed by their number


ADAPTERS = [register(a) for a in (Teamcenter(), Windchill())]
