"""Integration platform adapters (W3, registry id `apis`): Boomi AtomSphere (basic auth with a BOOMI_TOKEN API token;
Process and ExecutionRecord queries with queryMore paging; Component XML read and, after approval, written back;
ExecutionRequest to run a process, polled through its async record) and MuleSoft Anypoint (connected-app client
credentials; CloudHub 2.0 deployments with their logs; Exchange assets; a redeploy via PATCH, polled until applied)
behind the Connector SDK. Integrations are the canonical `integration` (key, name, platform, area, status, version,
schema version, a secret kept in clear text); published APIs the canonical `api`. Oracle Integration Cloud, SAP CPI,
Azure Logic Apps / API Management, Kafka and Service Bus come in as exports for now.

Mock lab stand-ins (tests/mocklab/sims/ipaas.py): boomi, mulesoft.
"""
from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET

from .. import connectors
from ._systems import SysAdapter, register, when

SECRET_NAME = re.compile(r"pass(word)?|secret|token|api[_-]?key", re.I)


class Boomi(SysAdapter):
    kind, label, category = "boomi", "Boomi AtomSphere", "ipaas"
    simulator = "boomi"
    docs = "https://help.boomi.com/docs/Atomsphere/Integration/AtomSphere%20API/"
    signin = ["api_key"]
    fields = [("base_url", "AtomSphere API (https://api.boomi.com)", True), ("account_id", "Account id", True), ("username", "API token user (BOOMI_TOKEN.<user>)", True)]
    secrets = {"api_key": ["password"]}
    ENTITIES = {"integration": ("Process", "Processes (with their component configuration)")}
    WRITABLE = {"integration": {"schema_version": "schemaVersion"}}
    JOBS = "Process executions"

    def sign_in(self, api):
        tok = base64.b64encode(f"{api.cfg.get('username')}:{api.secret('password')}".encode()).decode()
        return {"Authorization": "Basic " + tok, "Accept": "application/json"}

    def throttled(self, r):
        """Boomi throttles with 503, not 429; and its queries are reads sent as POST, so a 503 on one is retried too."""
        if r.status_code != 503:
            return False
        path = str(getattr(r.request, "url", "") or "")
        return "rate limit" in (r.text or "").lower() or path.endswith(("/query", "/queryMore"))

    def error_text(self, r):
        try:
            return r.json().get("message") or super().error_text(r)
        except (ValueError, AttributeError):
            return super().error_text(r)

    def _acc(self, api) -> str:
        return f"/api/rest/v1/{api.cfg.get('account_id')}"

    def _query(self, api, obj: str, expr: dict | None = None) -> list[dict]:
        b = api.json("POST", f"{self._acc(api)}/{obj}/query", json={"QueryFilter": {"expression": expr or {"operator": "and", "nestedExpression": []}}},
                      headers={"Content-Type": "application/json"}, what=f"{obj} query")
        out = list(b.get("result") or [])
        for _ in range(1000):
            tok = b.get("queryToken")
            if not tok:
                return out
            b = api.json("POST", f"{self._acc(api)}/{obj}/queryMore", content=tok.encode(), headers={"Content-Type": "text/plain"}, what=f"{obj} queryMore")
            out += b.get("result") or []
        return out

    def _component(self, api, cid: str) -> str:
        r = api.request("GET", f"{self._acc(api)}/Component/{cid}", headers={"Accept": "application/xml"})
        if r.status_code != 200:
            raise connectors.ConnectorError(f"Boomi: component {cid}: {self.error_text(r)}")
        return r.text

    @staticmethod
    def config_of(xml: str) -> dict:
        """What a process's component holds that matters: its folder, the schema version it sends, a secret in clear text."""
        out = {"area": None, "schema_version": None, "clear_secret": None}
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return out
        out["area"] = root.get("folderName")
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "documentproperty" and el.get("name") == "schemaVersion":
                out["schema_version"] = el.get("value")
            if tag == "processproperty" and SECRET_NAME.search(el.get("name") or "") and (el.get("value") or "").strip():
                out["clear_secret"] = el.get("name")                       # the property's name only — never its value
        return out

    def fetch(self, api, entity):
        if entity == "integration":
            out = []
            for p in self._query(api, "Process"):
                out.append({**p, **self.config_of(self._component(api, p["id"]))})
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "integration":
            return {"key": r["id"], "name": r.get("name"), "platform": "Boomi", "area": r.get("area"), "status": "deployed", "version": None,
                    "schema_version": r.get("schema_version"), "clear_secret": r.get("clear_secret")}
        return r

    def runs(self, api):
        recs = self._query(api, "ExecutionRecord")
        api.state["procs"] = {r.get("processName"): (r.get("processId"), r.get("atomId")) for r in recs}
        return sorted([{"job": r.get("processName"), "label": r.get("processName"), "id": r.get("executionId"), "started": when(r.get("executionTime")), "ended": when(r.get("recordedDate")),
                        "status": "succeeded" if r.get("status") == "COMPLETE" else "failed" if r.get("status") == "ERROR" else "running", "error": r.get("message") or None}
                       for r in recs], key=lambda x: x["started"] or 0, reverse=True)

    def op_update(self, api, entity, key, changes, approval):
        xml = self._component(api, key)
        for f, v in changes.items():
            prop = self.WRITABLE.get(entity, {}).get(f)
            if not prop:
                raise connectors.ConnectorError(f"{f} cannot be changed on a Boomi process through Relay")
            xml, n = re.subn(rf'(name="{prop}"\s+value=")[^"]*(")', rf"\g<1>{v}\g<2>", xml)
            if not n:
                raise connectors.ConnectorError(f"the process has no {prop} to change")
        r = api.request("POST", f"{self._acc(api)}/Component/{key}", content=xml.encode(), headers={"Content-Type": "application/xml", "Accept": "application/xml"}, approval=approval)
        if r.status_code != 200:
            raise connectors.ConnectorError(f"Boomi refused the component: {self.error_text(r)}")
        return {"id": key}

    def op_rerun(self, api, job, run_id, approval):
        if "procs" not in api.state:
            self.runs(api)
        pid, atom = (api.state.get("procs") or {}).get(job, (None, None))
        if not pid:
            raise connectors.ConnectorError(f"Boomi: no process called {job} has run here")
        b = api.json("POST", f"{self._acc(api)}/ExecutionRequest", json={"@type": "ExecutionRequest", "processId": pid, "atomId": atom}, headers={"Content-Type": "application/json"},
                     approval=approval, what="ExecutionRequest")
        return {"id": b.get("requestId"), "job": job}

    def op_status(self, api, ref):
        r = api.request("GET", f"{self._acc(api)}/ExecutionRecord/async/{ref.get('id')}")
        if r.status_code == 202:
            return {"status": "running", "error": None}
        res = (self.check(r, "execution record").get("result") or [{}])[0]
        return {"status": "succeeded" if res.get("status") == "COMPLETE" else "failed", "error": res.get("message") or None}


class MuleSoft(SysAdapter):
    kind, label, category = "mulesoft", "MuleSoft Anypoint", "ipaas"
    simulator = "mulesoft"
    docs = "https://anypoint.mulesoft.com/exchange/portals/anypoint-platform/"
    signin = ["service_account"]
    fields = [("base_url", "Anypoint (https://anypoint.mulesoft.com)", True), ("org_id", "Organisation id", True), ("env_id", "Environment id", True), ("client_id", "Connected app id", True)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"integration": ("deployments", "CloudHub 2.0 deployments"), "api": ("assets", "Exchange assets")}
    WRITABLE = {"integration": {"schema_version": "gst.schema"}}
    JOBS = "Application logs"

    def sign_in(self, api):
        r = api.raw("POST", "/accounts/api/v2/oauth2/token", json={"grant_type": "client_credentials", "client_id": api.cfg.get("client_id"), "client_secret": api.secret("client_secret")})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Anypoint refused the connected app: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def _dep(self, api) -> str:
        return f"/amc/application-manager/api/v2/organizations/{api.cfg.get('org_id')}/environments/{api.cfg.get('env_id')}/deployments"

    def fetch(self, api, entity):
        if entity == "integration":
            return api.get(self._dep(api)).get("items") or []
        if entity == "api":
            return api.get("/exchange/api/v2/assets") or []
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "integration":
            app = r.get("application") or {}
            return {"key": r["id"], "name": r.get("name"), "platform": "MuleSoft", "area": None, "status": "running" if app.get("status") == "RUNNING" else "stopped",
                    "version": (app.get("ref") or {}).get("version"), "schema_version": None, "clear_secret": None}
        if entity == "api":
            return {"key": f"{r.get('groupId')}/{r.get('assetId')}", "name": r.get("name"), "version": r.get("version"), "type": r.get("type"), "status": r.get("status")}
        return r

    def runs(self, api):
        out = []
        for d in api.get(self._dep(api)).get("items") or []:
            for x in api.get(f"{self._dep(api)}/{d['id']}/specs/current/logs", {"limit": 100}) or []:
                ok = x.get("logLevel") != "ERROR"
                out.append({"job": d["name"], "label": d["name"], "id": f"{d['id']}:{x.get('timestamp')}", "started": (x.get("timestamp") or 0) / 1000, "ended": (x.get("timestamp") or 0) / 1000,
                            "status": "succeeded" if ok else "failed", "error": None if ok else x.get("message")})
        return sorted(out, key=lambda r: r["started"] or 0, reverse=True)

    def _redeploy(self, api, key, props: dict | None, approval) -> dict:
        cur = api.get(f"{self._dep(api)}/{key}")
        ver = ((cur.get("application") or {}).get("ref") or {}).get("version")
        body = {"application": {"ref": {"version": ver}, **({"configuration": {"mule.agent.application.properties.service": {"properties": props}}} if props else {})}}
        r = api.request("PATCH", f"{self._dep(api)}/{key}", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        return self.check(r, f"deployment {key}")

    def op_update(self, api, entity, key, changes, approval):
        props = {}
        for f, v in changes.items():
            p = self.WRITABLE.get(entity, {}).get(f)
            if not p:
                raise connectors.ConnectorError(f"{f} cannot be changed on a MuleSoft deployment through Relay")
            props[p] = v
        self._redeploy(api, key, props, approval)
        return {"id": key}

    def op_rerun(self, api, job, run_id, approval):
        did = next((d["id"] for d in api.get(self._dep(api)).get("items") or [] if d["name"] == job), None)
        if not did:
            raise connectors.ConnectorError(f"MuleSoft: no deployment called {job}")
        self._redeploy(api, did, None, approval)
        return {"id": did, "job": job}

    def op_status(self, api, ref):
        st = api.get(f"{self._dep(api)}/{ref.get('id')}").get("status")
        return {"status": "running" if st == "APPLYING" else "succeeded" if st == "APPLIED" else "failed", "error": None}


ADAPTERS = [register(a) for a in (Boomi(), MuleSoft())]
