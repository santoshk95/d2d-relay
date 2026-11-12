"""The iPaaS platforms of Workflows & iPaaS as Connector SDK adapters - one adapter + one mock-lab simulator each
(tests/mocklab/sims/n8n.py: `n8n`; powerautomate.py: `power_automate`; ipaas.py: `zapier`, `make`, `workato`, `boomi`,
`mulesoft`) - and the readers of their exports (n8n workflow JSON, Power Automate definitions, Make blueprints, Workato
recipes, Boomi component XML, Mule 4 XML, the Zap History CSV).

Read-only by default: each adapter signs in the vendor's way (an API key header, Entra ID client credentials, a bearer
or `Token` header, basic auth with BOOMI_TOKEN, a connected app), follows the vendor's paging (cursors, nextLink,
pg[offset], queryMore, links.next) and reads flows and run history into the neutral shape (_w2.auto / _w2.run).
Writes happen only through connectors.request_write - after a named person accepted that very change - and carry the
approval's id in X-Relay-Approval: n8n deploys a workflow, runs a test copy with sample payloads (then removes it),
updates a workflow and re-runs its failed executions; Power Automate, Make and Boomi run the old flow on the same
payloads for a side-by-side proof.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from xml.etree import ElementTree as ET

from .. import connectors, db
from .. import connectors_sdk as sdk
from . import _w2
from . import n8n_flow as nf

_TOKENS: dict = {}                 # (tenant, connection id) -> (bearer, expiry): a sign-in kept for its lifetime only


def _cached(c: dict):
    t = _TOKENS.get((db.tenant(), c["id"]))
    return t[0] if t and t[1] > time.time() + 30 else None


def _keep(c: dict, tok: str, ttl: float) -> str:
    _TOKENS[(db.tenant(), c["id"])] = (tok, time.time() + max(60.0, float(ttl or 3600)))
    return tok


def _drop(c: dict) -> None:
    _TOKENS.pop((db.tenant(), c["id"]), None)


def _poll(fn, done, tries: int = 40):
    """Poll until done(result); a platform that moves on its own clock gets a short pause between asks."""
    out = None
    for i in range(tries):
        out = fn()
        if done(out):
            return out
        time.sleep(min(1.5, 0.05 * (i + 1)))
    return out


# ================================================================== n8n (public API v1)

class N8nApi(_w2.Adapter):
    kind, label, vendor, platform = "n8n_api", "n8n", "n8n", "n8n"
    simulator = "tests/mocklab/sims/n8n.py: n8n (public API v1 + webhooks)"
    fields = [("base_url", "n8n API URL (https://your-n8n/api/v1)", True), ("webhook_url", "Webhook URL (https://your-n8n/webhook) - used for test runs", False)]
    secrets = {"api_key": ["api_key"]}
    can_write = True

    def signin_headers(self, c):
        return {"X-N8N-API-KEY": _w2.secret(c, "api_key")}

    def hook(self, c) -> str:
        return (_w2.cfg(c, "webhook_url") or re.sub(r"/api/v1/?$", "", self.base(c)) + "/webhook").rstrip("/")

    def _pages(self, c, path, params=None):
        out, cur = [], None
        for _ in range(500):
            p = {"limit": 100, **(params or {}), **({"cursor": cur} if cur else {})}
            d = self.req(c, "GET", path, params=p).json()
            out += d.get("data") or []
            cur = d.get("nextCursor")
            if not cur:
                break
        return out

    def workflows(self, c) -> list[dict]:
        return self._pages(c, "/workflows")

    def workflow(self, c, wid: str) -> dict:
        return self.req(c, "GET", f"/workflows/{wid}").json()

    def estate(self, c):
        return [nf.to_neutral(w, wid=w["id"], active=w.get("active", False)) | {"platform": self.kind, "tags": [t.get("name") for t in w.get("tags") or []]} for w in self.workflows(c)]

    def _run(self, e: dict) -> dict:
        rd = ((e.get("data") or {}).get("resultData") or {})
        node = next((n for n, rs in (rd.get("runData") or {}).items() for x in rs or [] if x.get("executionStatus") == "error"), None) or (rd.get("lastNodeExecuted") if e.get("status") == "error" else None)
        err = ((rd.get("error") or {}).get("message")) or next((x.get("error", {}).get("message") for rs in (rd.get("runData") or {}).values() for x in rs or [] if x.get("error")), None)
        return _w2.run(e["id"], e.get("workflowId"), e.get("status"), e.get("startedAt"), e.get("stoppedAt"), err, node, mode=e.get("mode"), retry_of=e.get("retryOf"))

    def runs(self, c, autos, since=None):
        out = [self._run(e) for e in self._pages(c, "/executions", {"includeData": "true"})]
        return [r for r in out if not since or (r["start"] or 0) >= since]

    def execution(self, c, eid: str, data: bool = True) -> dict:
        return self.req(c, "GET", f"/executions/{eid}", params={"includeData": "true"} if data else None).json()

    def _wait(self, c, eid: str) -> dict:
        return _poll(lambda: self.execution(c, eid), lambda e: e.get("status") in ("success", "error", "canceled", "crashed"))

    def write_now(self, c, obj, payload, approval):
        h = approval
        if obj == "deploy":
            wf = {k: payload["workflow"][k] for k in ("name", "nodes", "connections", "settings")}
            if payload.get("workflow_id"):
                w = self.req(c, "PUT", f"/workflows/{payload['workflow_id']}", json_body=wf, approval=h).json()
            else:
                w = self.req(c, "POST", "/workflows", json_body=wf, approval=h).json()
            if payload.get("activate"):
                w = self.req(c, "POST", f"/workflows/{w['id']}/activate", approval=h).json()
            return {"ok": True, "workflow_id": w["id"], "active": w.get("active"), "name": w.get("name"), "version": w.get("versionId"),
                    "created": [{"ref": "workflow", "key": w["id"], "url": f"{re.sub(r'/api/v1/?$', '', self.base(c))}/workflow/{w['id']}"}]}
        if obj == "test_run":
            return self._test_run(c, payload, h)
        if obj == "test_runs":
            out = []
            for f in payload.get("flows") or []:
                r = self._test_run(c, {"workflow": f["workflow"], "payloads": payload.get("payloads")}, h)
                out.append({"auto": f["auto"], "runs": r["runs"], "removed": r["removed"]})
            return {"ok": True, "flows": out}
        if obj == "deploy_many":
            out = []
            for f in payload.get("flows") or []:
                r = self.write_now(c, "deploy", {"workflow": f["workflow"], "activate": payload.get("activate")}, h)
                out.append({"auto": f["auto"], "workflow_id": r["workflow_id"], "active": r.get("active")})
            return {"ok": True, "flows": out}
        if obj in ("update_retry", "retry"):
            done = {}
            if obj == "update_retry":
                wf = {k: payload["workflow"][k] for k in ("name", "nodes", "connections", "settings")}
                w = self.req(c, "PUT", f"/workflows/{payload['workflow_id']}", json_body=wf, approval=h).json()
                done["updated"] = {"workflow_id": w["id"], "version": w.get("versionId")}
            reruns = []
            for eid in payload.get("executions") or []:
                n = self.req(c, "POST", f"/executions/{eid}/retry", approval=h, ok=(200, 201, 409)).json()
                if not n.get("id"):
                    reruns.append({"of": eid, "status": "not retried", "error": n.get("message")})
                    continue
                e = self._wait(c, n["id"])
                r = self._run(e)
                reruns.append({"of": eid, "id": n["id"], "status": r["status"], "error": r["error"], "node": r["node"]})
            return {"ok": all(r["status"] == "success" for r in reruns) if reruns else True, **done, "reruns": reruns}
        raise sdk.ScopeError(f"n8n: Relay does not write {obj!r}")

    def _test_run(self, c, payload, approval) -> dict:
        """A copy of the workflow (its trigger a webhook of its own), activated, sent each sample payload, read back node
        by node, then deactivated and removed - every call carrying the approval."""
        path = "relay-test-" + _w2.sha(payload["workflow"])[:10]
        cp = nf.test_copy(payload["workflow"], path)
        w = self.req(c, "POST", "/workflows", json_body=cp, approval=approval).json()
        out = []
        try:
            self.req(c, "POST", f"/workflows/{w['id']}/activate", approval=approval)
            for i, body in enumerate(payload.get("payloads") or [{}]):
                case = (body or {}).get("_case") or f"payload {i + 1}"
                r = _w2.call("n8n webhook", "POST", f"{self.hook(c)}/{path}", json_body={k: v for k, v in (body or {}).items() if k != "_case"}, headers={_w2.wb_approval_header(): approval},
                             ok=(200, 201, 202, 404))
                d = r.json() if r.content else {}
                if r.status_code == 404 or not d.get("executionId"):
                    out.append({"case": case, "status": "failed", "error": d.get("message") or f"webhook answered {r.status_code}", "nodes": []})
                    continue
                e = self._wait(c, str(d["executionId"]))
                run = self._run(e)
                nodes = [{"node": n, "status": (xs or [{}])[-1].get("executionStatus")} for n, xs in (((e.get("data") or {}).get("resultData") or {}).get("runData") or {}).items()]
                out.append({"case": case, "execution": d["executionId"], "status": run["status"], "error": run["error"], "node": run["node"], "nodes": nodes})
        finally:
            try:
                self.req(c, "POST", f"/workflows/{w['id']}/deactivate", approval=approval)
                self.req(c, "DELETE", f"/workflows/{w['id']}", approval=approval)
                removed = True
            except connectors.ConnectorError:
                removed = False
        return {"ok": all(x["status"] == "success" for x in out), "copy": w["id"], "removed": removed, "runs": out, "sha": payload.get("sha")}


def old_runs(adapter, c, payload, approval) -> dict:
    """test_runs on a source platform: each old flow run as it is on the same payloads (Power Automate, Make, Boomi)."""
    out = []
    for f in payload.get("flows") or []:
        r = adapter.write_now(c, "test_run", {f["id_key"]: f["id"], "payloads": payload.get("payloads")}, approval)
        out.append({"auto": f["auto"], "runs": r["runs"]})
    return {"ok": True, "flows": out}


# ================================================================== Power Automate (Flow management API, Entra ID client credentials)

PA_API = "2016-11-01"
PA_SYSTEM = {"shared_oracleerp": "Oracle Fusion", "shared_saperp": "SAP S/4HANA", "shared_azuread": "Entra ID", "shared_jira": "Jira", "shared_powerbi": "Power BI", "shared_zohobooks": "Zoho Books",
             "shared_webcontents": "", "shared_sftpwithssh": "Bank SFTP", "shared_office365": "", "shared_teams": "", "shared_approvals": "", "shared_formrecognizer": "Azure AI Document Intelligence",
             "shared_excelonlinebusiness": ""}
PA_OP = {"SendEmailV2": "notify", "PostMessageToConversation": "notify", "StartAndWaitForAnApproval": "human", "AnalyzeDocumentForPrebuiltModel": "extract", "GetEmailsV3": "read_mail",
         "GetFileContentByPath": "download", "GetItems": "read_file", "AddRowV2": "write"}


class PowerAutomateFlows(_w2.Adapter):
    kind, label, vendor, platform = "power_automate_flows", "Power Automate", "Power Automate", "Power Automate"
    simulator = "tests/mocklab/sims/powerautomate.py: power_automate (Flow management API)"
    fields = [("base_url", "Flow API URL (https://api.flow.microsoft.com)", True), ("environment", "Environment id", True), ("tenant_id", "Entra tenant id", True),
              ("client_id", "App (client) id", True), ("token_url", "Token URL (default: Entra ID for the tenant)", False)]
    secrets = {"api_key": ["client_secret"]}
    can_write = True

    def _flows(self, c) -> str:
        return f"/providers/Microsoft.ProcessSimple/environments/{_w2.cfg(c, 'environment')}/flows"

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            url = _w2.cfg(c, "token_url") or f"https://login.microsoftonline.com/{_w2.cfg(c, 'tenant_id')}/oauth2/v2.0/token"
            r = _w2.call("Entra ID", "POST", url, data={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"), "client_secret": _w2.secret(c, "client_secret"),
                                                        "scope": "https://service.flow.microsoft.com/.default"})
            tok = _keep(c, r.json()["access_token"], r.json().get("expires_in") or 3599)
        return {"Authorization": f"Bearer {tok}"}

    def forget(self, c):
        _drop(c)

    def _list(self, c, path) -> list[dict]:
        out, url, params = [], path, {"api-version": PA_API, "$top": 50}
        for _ in range(500):
            d = self.req(c, "GET", url, params=params).json()
            out += d.get("value") or []
            url, params = d.get("nextLink"), None
            if not url:
                break
        return out

    def estate(self, c):
        out = []
        for f in self._list(c, self._flows(c)):
            full = self.req(c, "GET", f"{self._flows(c)}/{f['name']}", params={"api-version": PA_API}).json()
            p = full.get("properties") or {}
            a = pa_neutral(f["name"], p.get("displayName") or f["name"], p.get("definition") or {}, refs=p.get("connectionReferences") or {}, active=p.get("state") == "Started")
            a["platform"] = self.kind
            out.append(a)
        return out

    def runs(self, c, autos, since=None):
        out = []
        for a in autos:
            for r in self._list(c, f"{self._flows(c)}/{a['id']}/runs"):
                p = r.get("properties") or {}
                err = (p.get("error") or {}).get("message")
                node = (re.search(r"\.\s*([A-Za-z0-9_]+):", err or "") or [None, None])[1] if err else None
                out.append(_w2.run(r["name"], a["id"], p.get("status"), p.get("startTime"), p.get("endTime"), err, node.replace("_", " ") if node else None))
        return [r for r in out if not since or (r["start"] or 0) >= since]

    def write_now(self, c, obj, payload, approval):
        fid = payload.get("flow_id")
        if obj == "deploy":
            self.req(c, "PATCH", f"{self._flows(c)}/{fid}", params={"api-version": PA_API}, json_body={"properties": {"definition": payload["definition"]}}, approval=approval)
            return {"ok": True, "updated": [{"ref": "flow", "key": fid}]}
        if obj == "test_run":
            full = self.req(c, "GET", f"{self._flows(c)}/{fid}", params={"api-version": PA_API}).json()
            trig = next(iter(((full.get("properties") or {}).get("definition") or {}).get("triggers") or {"manual": {}}))
            cb = self.req(c, "POST", f"{self._flows(c)}/{fid}/triggers/{trig}/listCallbackUrl", params={"api-version": PA_API}, approval=approval).json()["response"]["value"]
            out = []
            for i, body in enumerate(payload.get("payloads") or [{}]):
                case = (body or {}).get("_case") or f"payload {i + 1}"
                r = _w2.call("Power Automate", "POST", cb, json_body={k: v for k, v in (body or {}).items() if k != "_case"}, headers={_w2.wb_approval_header(): approval}, ok=(200, 202, 409))
                rid = r.headers.get("x-ms-workflow-run-id")
                if not rid:
                    out.append({"case": case, "status": "failed", "error": _w2._msg(r)})
                    continue
                st = _poll(lambda: self.req(c, "GET", f"{self._flows(c)}/{fid}/runs/{rid}", params={"api-version": PA_API}).json(),
                           lambda x: (x.get("properties") or {}).get("status") in ("Succeeded", "Failed", "Cancelled"))
                p = st.get("properties") or {}
                out.append({"case": case, "run": rid, "status": _w2.run(rid, fid, p.get("status"), None)["status"], "error": (p.get("error") or {}).get("message")})
            return {"ok": True, "runs": out}
        if obj == "test_runs":
            return old_runs(self, c, payload, approval)
        raise sdk.ScopeError(f"Power Automate: Relay does not write {obj!r}")


def _pa_label(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip()


def pa_neutral(fid: str, name: str, d: dict, *, refs: dict | None = None, active: bool = True) -> dict:
    """A Logic Apps workflow definition (Power Automate) -> the neutral flow: actions in runAfter order, an If's yes
    branch then its else (the hand-over), a Foreach's inner actions."""
    trig_name, trig = next(iter((d.get("triggers") or {"manual": {}}).items()))
    t = trig.get("type") or ""
    op = ((trig.get("inputs") or {}).get("host") or {}).get("operationId") or ""
    tk = "email" if "Email" in op or t == "OpenApiConnectionNotification" else "schedule" if t == "Recurrence" else "webhook" if t == "Request" else "manual"
    cron = ""
    if t == "Recurrence":
        rec = trig.get("recurrence") or {}
        sch = rec.get("schedule") or {}
        hh, mm = (sch.get("hours") or ["0"])[0], (sch.get("minutes") or [0])[0]
        cron = f"{mm} {hh} " + ({"Month": f"{(sch.get('monthDays') or [1])[0]} * *", "Week": "* * 1", "Day": "* * *"}.get(rec.get("frequency"), "* * *"))
    steps, creds = [], []

    def ordered(acts: dict) -> list[tuple[str, dict]]:
        left, done, out = dict(acts), set(), []
        for _ in range(len(acts) + 1):
            for k, v in list(left.items()):
                if all(p in done for p in (v.get("runAfter") or {})):
                    out.append((k, v))
                    done.add(k)
                    left.pop(k)
        return out + list(left.items())

    def walk(acts: dict):
        for k, v in ordered(acts):
            typ = v.get("type")
            inp = v.get("inputs") if isinstance(v.get("inputs"), dict) else {}
            host = inp.get("host") or {}
            cn = host.get("connectionName") or ""
            sysname = PA_SYSTEM.get(cn, "")
            prm = inp.get("parameters") or {}
            if typ == "If":
                steps.append(_w2.step(_pa_label(k), "decide", detail=json.dumps(v.get("expression"))[:200]))
                walk(v.get("actions") or {})
                walk(((v.get("else") or {}).get("actions")) or {})
                continue
            if typ == "Foreach":
                steps.append(_w2.step(_pa_label(k), "loop", detail=str(v.get("foreach") or "")))
                walk(v.get("actions") or {})
                continue
            if typ == "InitializeVariable":
                steps.append(_w2.step(_pa_label(k), "build", detail="initialise variables"))
                continue
            if typ == "Compose":
                steps.append(_w2.step(_pa_label(k), "build", detail="compose a payload"))
                continue
            if typ == "Http":
                api = f"{inp.get('method') or 'POST'} {inp.get('uri') or ''}"
                s = _w2.step(_pa_label(k), "upload" if "upload" in k.lower() else "post", system=nf.system_of(inp.get("uri") or ""), api=api)
                if inp.get("body") is not None:
                    s["body"] = json.dumps(inp["body"])
                steps.append(s)
                continue
            kind = PA_OP.get(host.get("operationId") or "")
            if not kind:
                low = k.lower()
                kind = "lookup" if low.startswith(("find", "look")) else "upload" if "upload" in low else "fetch" if "fetch" in low else "export" if "export" in low else "type" if "type" in low else "post"
            api = f"{prm.get('request/method')} {prm.get('request/url')}" if prm.get("request/url") else ""
            steps.append(_w2.step(_pa_label(k), kind, system=sysname, api=api if kind not in ("notify", "human") else "", detail=str(prm.get("path") or "")[:120]))
            if cn:
                creds.append(cn)
    walk(d.get("actions") or {})
    bad = [k for k, v in (refs or {}).items() if (v or {}).get("status") == "Error"]
    a = _w2.auto(fid, name, "power_automate_flows", active=active, trigger={"kind": tk, "detail": trig_name, "cron": cron}, steps=steps, credentials=creds, definition=d)
    a["connection_problems"] = [f"{k} is in Error" for k in bad]
    return a


# ================================================================== Zapier (Workflow API v2; run history only as the Zap History export)

ZAP_APP = {"MicrosoftTeamsCLIAPI": "notify", "JiraSoftwareCloudCLIAPI": "human", "AzureFormRecognizerCLIAPI": "extract", "CodeCLIAPI": "build", "FilterCLIAPI": "decide"}


class Zapier(_w2.Adapter):
    kind, label, vendor, platform = "zapier", "Zapier", "Zapier", "Zapier"
    simulator = "tests/mocklab/sims/ipaas.py: zapier (Workflow API v2 + Zap History export)"
    fields = [("base_url", "API URL (https://api.zapier.com)", True)]
    secrets = {"api_key": ["access_token"]}
    can_write = False

    def signin_headers(self, c):
        return {"Authorization": f"Bearer {_w2.secret(c, 'access_token')}"}

    def estate(self, c):
        out, url, params = [], "/v2/zaps", {"limit": 100, "offset": 0}
        for _ in range(200):
            d = self.req(c, "GET", url, params=params).json()
            out += [zap_neutral(z) for z in d.get("data") or []]
            url, params = (d.get("links") or {}).get("next"), None
            if not url:
                break
        return out


def zap_neutral(z: dict) -> dict:
    steps, creds = [], []
    trig = (z.get("steps") or [{}])[0]
    tk = {"new_email": "email", "every_day": "schedule", "catch_hook": "webhook", "new_submission": "form"}.get(((trig.get("action") or {}).get("key")), "manual")
    for s in (z.get("steps") or [])[1:]:
        act = s.get("action") or {}
        app = (act.get("app") or {}).get("id") or ""
        inp = s.get("inputs") or {}
        kind = ZAP_APP.get(app) or (act.get("key") if act.get("key") in _w2.NEUTRAL else "post")
        url = str(inp.get("url") or "")
        st = _w2.step(s.get("title") or kind, kind, system=nf.system_of(url) or ("Jira" if app.startswith("Jira") else ""), api=f"{inp.get('method') or 'POST'} {url}" if url else "")
        if inp.get("data"):
            st["body"] = inp["data"]
        steps.append(st)
        if s.get("authentication"):
            creds.append((act.get("app") or {}).get("title") or app)
    return _w2.auto(z["id"], z.get("title") or z["id"], "zapier", active=z.get("is_enabled", True), trigger={"kind": tk, "detail": ((trig.get("action") or {}).get("app") or {}).get("title") or ""},
                    steps=steps, credentials=creds, definition=z, updated=z.get("updated_at"))


def zap_history(text: str) -> list[dict]:
    """The Zap History export (Date, Zap, Zap ID, Status, Tasks, Error) -> runs."""
    out = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text))):
        if not r.get("Zap ID"):
            continue
        out.append(_w2.run(f"{r['Zap ID']}-{i}", r["Zap ID"], "success" if (r.get("Status") or "").lower().startswith("succ") else "failed", r.get("Date"), None, r.get("Error") or None,
                           items=int(r.get("Tasks") or 0) if str(r.get("Tasks") or "").isdigit() else None))
    return out


# ================================================================== Make (API v2)

MAKE_MOD = {"builtin:BasicRouter": "decide", "jira:CreateAnIssue": "human", "microsoft-teams:createMessage": "notify", "sftp:GetFile": "download", "builtin:BasicFeeder": "loop",
            "microsoft-excel:addAWorksheetRow": "write", "microsoft-excel:filterRows": "read_file", "json:CreateJSON": "build", "email:TriggerNewEmail": "read_mail"}


class Make(_w2.Adapter):
    kind, label, vendor, platform = "make", "Make", "Make", "Make"
    simulator = "tests/mocklab/sims/ipaas.py: make (API v2)"
    fields = [("base_url", "Zone URL (https://eu1.make.com)", True), ("team_id", "Team id", True)]
    secrets = {"api_key": ["api_token"]}
    can_write = True

    def signin_headers(self, c):
        return {"Authorization": f"Token {_w2.secret(c, 'api_token')}"}

    def scenarios(self, c) -> list[dict]:
        out, off = [], 0
        for _ in range(500):
            d = self.req(c, "GET", "/api/v2/scenarios", params={"teamId": _w2.cfg(c, "team_id"), "pg[limit]": 100, "pg[offset]": off}).json()
            page = d.get("scenarios") or []
            if not page:
                break
            out += page
            off += len(page)
        return out

    def estate(self, c):
        out = []
        for s in self.scenarios(c):
            bp = self.req(c, "GET", f"/api/v2/scenarios/{s['id']}/blueprint").json().get("response", {}).get("blueprint") or {}
            a = make_neutral(str(s["id"]), s.get("name") or str(s["id"]), bp, active=s.get("isActive", True))
            a["schedule"] = json.dumps(s.get("scheduling") or {})
            out.append(a)
        return out

    def runs(self, c, autos, since=None):
        out = []
        for a in autos:
            d = self.req(c, "GET", f"/api/v2/scenarios/{a['id']}/logs", params={"pg[limit]": 100, "pg[offset]": 0}).json()
            for x in d.get("scenarioLogs") or []:
                st = {1: "success", 2: "success", 3: "failed"}.get(x.get("status"), "failed")
                s0 = _w2.epoch(x.get("timestamp"))
                out.append(_w2.run(x.get("id") or x.get("imtId"), a["id"], st, s0, (s0 or 0) + (x.get("duration") or 0) / 1000, (x.get("error") or {}).get("message")))
        return [r for r in out if not since or (r["start"] or 0) >= since]

    def write_now(self, c, obj, payload, approval):
        sid = payload.get("scenario_id")
        if obj == "deploy":
            self.req(c, "PATCH", f"/api/v2/scenarios/{sid}", json_body={"blueprint": json.dumps(payload["blueprint"])}, approval=approval)
            return {"ok": True, "updated": [{"ref": "scenario", "key": sid}]}
        if obj == "test_run":
            out = []
            for i, body in enumerate(payload.get("payloads") or [{}]):
                case = (body or {}).get("_case") or f"payload {i + 1}"
                r = self.req(c, "POST", f"/api/v2/scenarios/{sid}/run", json_body={"data": {k: v for k, v in (body or {}).items() if k != "_case"}, "responsive": True}, approval=approval, ok=(200, 400))
                d = r.json()
                if r.status_code == 400:
                    out.append({"case": case, "status": "failed", "error": d.get("message")})
                    continue
                st = _poll(lambda: self.req(c, "GET", d["statusUrl"]).json(), lambda x: x.get("status") in ("SUCCESS", "ERROR", "WARNING"))
                out.append({"case": case, "run": d.get("executionId"), "status": "success" if st.get("status") in ("SUCCESS", "WARNING") else "failed", "error": (st.get("error") or {}).get("message")})
            return {"ok": True, "runs": out}
        if obj == "test_runs":
            return old_runs(self, c, payload, approval)
        raise sdk.ScopeError(f"Make: Relay does not write {obj!r}")


def make_neutral(sid: str, name: str, bp: dict, *, active: bool = True) -> dict:
    flow = bp.get("flow") or []
    first = (flow[0] if flow else {}).get("module") or ""
    tk = "email" if first.startswith("email:") else "schedule" if first == "builtin:BasicScheduler" else "webhook" if first.startswith("gateway:") else "manual"
    steps, creds = [], []
    for m in flow[1:]:
        mod = m.get("module") or ""
        label = ((m.get("metadata") or {}).get("designer") or {}).get("name") or mod
        mp = m.get("mapper") or {}
        kind = MAKE_MOD.get(mod)
        if not kind:
            low = label.lower()
            kind = "upload" if "upload" in low else "extract" if "extract" in low else "lookup" if low.startswith(("find", "look")) else "validate" if "validat" in low else \
                   "fetch" if "fetch" in low else "export" if "export" in low else "type" if "type" in low else "post"
        url = str(mp.get("url") or "")
        st = _w2.step(label, kind, system=nf.system_of(url), api=f"{str(mp.get('method') or 'post').upper()} {url}" if url else "")
        if mp.get("data"):
            st["body"] = mp["data"]
        steps.append(st)
        if (m.get("parameters") or {}).get("account"):
            creds.append(f"{mod.split(':')[0]} connection {m['parameters']['account']}")
    return _w2.auto(sid, name, "make", active=active, trigger={"kind": tk, "detail": first}, steps=steps, credentials=creds, definition=bp)


# ================================================================== Workato (developer API)

WK_PROV = {"jira": "human", "teams": "notify", "azure_document_intelligence": "extract", "oracle_fusion": "lookup", "sftp": "download", "excel_online": "write", "power_bi": "export",
           "sap": "type", "zoho_books": "fetch", "ruby": "build", "email": "read_mail", "workato_list": "loop"}
WK_SYSTEM = {"oracle_fusion": "Oracle Fusion", "sap": "SAP S/4HANA", "azure_ad": "Entra ID", "jira": "Jira", "power_bi": "Power BI", "zoho_books": "Zoho Books"}


class Workato(_w2.Adapter):
    kind, label, vendor, platform = "workato", "Workato", "Workato", "Workato"
    simulator = "tests/mocklab/sims/ipaas.py: workato (developer API)"
    fields = [("base_url", "API URL (https://www.workato.com)", True)]
    secrets = {"api_key": ["api_token"]}
    can_write = False

    def signin_headers(self, c):
        return {"Authorization": f"Bearer {_w2.secret(c, 'api_token')}"}

    def estate(self, c):
        cons = {x.get("application"): x for x in self.req(c, "GET", "/api/connections").json() or []}
        out, page = [], 1
        for _ in range(200):
            items = self.req(c, "GET", "/api/recipes", params={"page": page, "per_page": 100}).json().get("items") or []
            for r in items:
                a = workato_neutral(str(r["id"]), r.get("name") or str(r["id"]), _w2.j(r.get("code"), {}) if isinstance(r.get("code"), str) else r.get("code") or {}, active=r.get("running", True))
                a["connection_problems"] = [f"{app}: {cons[app].get('authorization_error') or 'not authorised'}" for app in r.get("applications") or [] if app in cons and cons[app].get("authorization_status") != "success"]
                out.append(a)
            if len(items) < 100:
                break
            page += 1
        return out

    def runs(self, c, autos, since=None):
        out = []
        for a in autos:
            for x in self.req(c, "GET", f"/api/recipes/{a['id']}/jobs", params={"per_page": 100}).json().get("items") or []:
                out.append(_w2.run(x["id"], a["id"], x.get("status"), x.get("started_at"), x.get("completed_at"), x.get("error")))
        return [r for r in out if not since or (r["start"] or 0) >= since]


def workato_neutral(rid: str, name: str, code: dict, *, active: bool = True) -> dict:
    tk = {"email": "email", "clock": "schedule", "workato_webhooks": "webhook"}.get(code.get("provider"), "manual")
    steps = []
    for b in code.get("block") or []:
        if b.get("keyword") == "if":
            steps.append(_w2.step("Decision", "decide", detail="confidence at least 0.85"))
            continue
        prov = b.get("provider") or ""
        inp = b.get("input") or {}
        label = inp.get("label") or b.get("name") or prov
        kind = b.get("name") if b.get("name") in _w2.NEUTRAL else WK_PROV.get(prov, "post")
        st = _w2.step(label, kind, system=WK_SYSTEM.get(prov, ""))
        if inp.get("request_body"):
            st["body"] = inp["request_body"]
        steps.append(st)
    return _w2.auto(rid, name, "workato", active=active, trigger={"kind": tk, "detail": code.get("provider") or ""}, steps=steps,
                    credentials=sorted({b.get("provider") for b in code.get("block") or [] if b.get("provider")}), definition=code)


# ================================================================== Boomi (AtomSphere platform API)

class BoomiAtomSphere(_w2.Adapter):
    kind, label, vendor, platform = "boomi_atomsphere", "Boomi", "Boomi", "Boomi"
    simulator = "tests/mocklab/sims/ipaas.py: boomi (AtomSphere API; throttles with 503)"
    fields = [("base_url", "API URL (https://api.boomi.com)", True), ("account_id", "Account id", True), ("username", "API user (BOOMI_TOKEN.<user>)", True)]
    secrets = {"api_key": ["password"]}
    can_write = True

    def signin_headers(self, c):
        import base64
        return {"Authorization": "Basic " + base64.b64encode(f"{_w2.cfg(c, 'username')}:{_w2.secret(c, 'password')}".encode()).decode()}

    def _p(self, c) -> str:
        return f"/api/rest/v1/{_w2.cfg(c, 'account_id')}"

    def _query(self, c, what: str, body: dict) -> list[dict]:
        d = self.req(c, "POST", f"{self._p(c)}/{what}/query", json_body=body).json()
        out = list(d.get("result") or [])
        for _ in range(500):
            tok = d.get("queryToken")
            if not tok:
                break
            d = self.req(c, "POST", f"{self._p(c)}/{what}/queryMore", content=tok.encode(), headers={"Content-Type": "text/plain"}).json()
            out += d.get("result") or []
        return out

    def estate(self, c):
        out = []
        for p in self._query(c, "Process", {"QueryFilter": {"expression": {"operator": "and", "nestedExpression": []}}}):
            xml = self.req(c, "GET", f"{self._p(c)}/Component/{p['id']}", headers={"Accept": "application/xml"}).text
            out.append(boomi_neutral(xml, p["id"], p.get("name")))
        return out

    def runs(self, c, autos, since=None):
        since = since or _w2.wb.lab_now() - 60 * 86400
        recs = self._query(c, "ExecutionRecord", {"QueryFilter": {"expression": {"argument": [_w2.iso(since), _w2.iso(time.time() + 86400)], "operator": "BETWEEN", "property": "executionTime"}}})
        return [_w2.run(r["executionId"], r.get("processId"), r.get("status"), r.get("executionTime"), r.get("recordedDate"), r.get("message") or None, atom=r.get("atomId")) for r in recs]

    def write_now(self, c, obj, payload, approval):
        if obj == "test_runs":
            return old_runs(self, c, payload, approval)
        if obj != "test_run":
            raise sdk.ScopeError(f"Boomi: Relay does not write {obj!r}")
        atom = _w2.cfg(c, "atom_id") or payload.get("atom_id")
        out = []
        for i, body in enumerate(payload.get("payloads") or [{}]):
            case = (body or {}).get("_case") or f"payload {i + 1}"
            rq = self.req(c, "POST", f"{self._p(c)}/ExecutionRequest", json_body={"@type": "ExecutionRequest", "atomId": atom, "processId": payload["process_id"],
                                                                                   "ProcessProperties": {"@type": "ProcessProperties", "ProcessProperty": []}}, approval=approval).json()
            d = _poll(lambda: self.req(c, "GET", rq["recordUrl"], ok=(200, 202)).json(), lambda x: x.get("responseStatusCode") == 200)
            res = (d.get("result") or [{}])[0]
            out.append({"case": case, "run": rq.get("requestId"), "status": "success" if res.get("status") == "COMPLETE" else "failed", "error": res.get("message") or None})
        return {"ok": True, "runs": out}


def boomi_neutral(xml: str, cid: str = "", name: str | None = None) -> dict:
    root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    nm = name or root.get("name") or cid
    shapes = [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "shape"]
    steps, tk = [], "manual"
    for sh in shapes:
        st = sh.get("shapetype")
        label = sh.get("userlabel") or ""
        ca = next((e for e in sh.iter() if e.tag.endswith("connectoraction")), None)
        ctype = ca.get("connectorType") if ca is not None else ""
        if st == "start":
            tk = {"mail": "email", "wss": "webhook", "none": "schedule"}.get(ctype or "none", "schedule")
            continue
        if st == "stop":
            continue
        kind = {"decision": "decide", "flowcontrol": "loop", "map": "build"}.get(st)
        if not kind:
            low = label.lower()
            kind = "human" if ctype == "jira" else "notify" if ctype == "mail" else "upload" if "upload" in low else "extract" if "extract" in low else \
                   "lookup" if low.startswith(("find", "look")) else "validate" if "validat" in low else "fetch" if "fetch" in low else "export" if "export" in low else "type" if "type" in low else "post"
        s = _w2.step(label or st, kind)
        prop = next((e for e in sh.iter() if e.tag.endswith("documentproperty") and e.get("name") == "schemaVersion"), None)
        if prop is not None:
            s["body"] = json.dumps({"schema": prop.get("value")})
        steps.append(s)
    return _w2.auto(cid or root.get("componentId") or _w2.slug(nm), nm, "boomi_atomsphere", trigger={"kind": tk, "detail": ""}, steps=steps, definition=xml if isinstance(xml, str) else xml.decode(),
                    updated=root.get("modifiedDate"), folder=root.get("folderFullPath"))


# ================================================================== MuleSoft (Anypoint: connected app, CloudHub 2.0 deployments and logs)

class MuleSoftAnypoint(_w2.Adapter):
    kind, label, vendor, platform = "mulesoft_anypoint", "MuleSoft", "MuleSoft Anypoint", "MuleSoft"
    simulator = "tests/mocklab/sims/ipaas.py: mulesoft (Anypoint Platform)"
    fields = [("base_url", "Anypoint URL (https://anypoint.mulesoft.com)", True), ("org_id", "Organisation id", True), ("env_id", "Environment id", True), ("client_id", "Connected app client id", True)]
    secrets = {"api_key": ["client_secret"]}
    can_write = False

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            r = _w2.call("MuleSoft", "POST", self.base(c) + "/accounts/api/v2/oauth2/token", json_body={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"),
                                                                                                       "client_secret": _w2.secret(c, "client_secret")})
            tok = _keep(c, r.json()["access_token"], r.json().get("expires_in") or 3600)
        return {"Authorization": f"Bearer {tok}"}

    def forget(self, c):
        _drop(c)

    def _dep(self, c) -> str:
        return f"/amc/application-manager/api/v2/organizations/{_w2.cfg(c, 'org_id')}/environments/{_w2.cfg(c, 'env_id')}/deployments"

    def estate(self, c):
        out = []
        for d in self.req(c, "GET", self._dep(c)).json().get("items") or []:
            app = d.get("application") or {}
            out.append(_w2.auto(d["id"], d.get("name") or d["id"], self.kind, active=app.get("status") == "RUNNING", trigger={"kind": "manual", "detail": "Mule app"},
                                steps=[], definition={"deployment": d.get("name"), "version": (app.get("ref") or {}).get("version")}, app=d.get("name")))
        return out

    def runs(self, c, autos, since=None):
        out = []
        for a in autos:
            for i, x in enumerate(self.req(c, "GET", f"{self._dep(c)}/{a['id']}/specs/current/logs", params={"limit": 500}).json() or []):
                failed = x.get("logLevel") == "ERROR"
                out.append(_w2.run(f"{a['id']}-{x.get('timestamp')}-{i}", a["id"], "failed" if failed else "success", x.get("timestamp"), x.get("timestamp"), x.get("message") if failed else None))
        return [r for r in out if not since or (r["start"] or 0) >= since]


def mule_neutral(xml: str, name: str = "") -> dict:
    """A Mule 4 configuration file -> the neutral flow (HTTP requests, choices, foreach, e-mail, loggers)."""
    root = ET.fromstring(xml.encode())
    loc = lambda e: e.tag.rsplit("}", 1)[-1]  # noqa: E731
    flow = next((e for e in root if loc(e) == "flow"), None)
    steps, tk = [], "manual"
    for e in list(flow) if flow is not None else []:
        t = loc(e)
        label = e.get("{http://www.mulesoft.org/schema/mule/documentation}name") or t
        if t in ("listener-imap",):
            tk = "email"
        elif t == "scheduler":
            tk = "schedule"
        elif t == "listener":
            tk = "webhook"
        elif t == "request":
            low = label.lower()
            body = next((x.text for x in e.iter() if loc(x) == "body"), None)
            kind = "upload" if "upload" in low else "lookup" if low.startswith(("find", "look")) else "validate" if "validat" in low else "fetch" if "fetch" in low else \
                   "export" if "export" in low else "type" if "type" in low else "post"
            s = _w2.step(label, kind, api=f"{e.get('method') or 'POST'} {e.get('path') or ''}", system=(e.get("config-ref") or "").replace("_Config", "").replace("_", " "))
            if body:
                s["body"] = body
            steps.append(s)
        elif t == "choice":
            steps.append(_w2.step(label, "decide"))
        elif t == "foreach":
            steps.append(_w2.step(label, "loop"))
        elif t == "send":
            steps.append(_w2.step(label, "notify", detail="e-mail"))
        elif t == "logger":
            steps.append(_w2.step(label, "human" if "review" in label.lower() else "post"))
    return _w2.auto(name or (flow.get("name") if flow is not None else "mule-app"), name or (flow.get("name") if flow is not None else "mule-app"), "mulesoft_anypoint",
                    trigger={"kind": tk, "detail": ""}, steps=steps, definition=xml)


# ================================================================== exports instead of a connection

def parse_file(name: str, data: bytes) -> dict:
    """One upload -> {"autos": [...], "runs": [...], "kind": what it was}; anything else -> {"kind": None}."""
    low = name.lower()
    try:
        if low.endswith(".json"):
            d = json.loads(data.decode("utf-8-sig"))
            if isinstance(d, dict) and isinstance(d.get("nodes"), list) and isinstance(d.get("connections"), dict):
                a = nf.to_neutral(d, wid=d.get("id") or _w2.slug(name), active=d.get("active", True))
                return {"autos": [a], "runs": [], "kind": "n8n workflow"}
            p = d.get("properties") if isinstance(d, dict) and isinstance(d.get("properties"), dict) else d
            if isinstance(p, dict) and isinstance((p.get("definition") or {}).get("actions"), dict):
                return {"autos": [pa_neutral(_w2.slug(name), p.get("displayName") or name.rsplit(".", 1)[0], p["definition"], refs=p.get("connectionReferences"))], "runs": [], "kind": "Power Automate flow"}
            if isinstance(d, dict) and isinstance(d.get("flow"), list):
                return {"autos": [make_neutral(_w2.slug(name), d.get("name") or name, d)], "runs": [], "kind": "Make blueprint"}
            if isinstance(d, dict) and d.get("code"):
                code = _w2.j(d["code"], {}) if isinstance(d["code"], str) else d["code"]
                return {"autos": [workato_neutral(_w2.slug(name), d.get("name") or name, code)], "runs": [], "kind": "Workato recipe"}
        if low.endswith(".xml"):
            text = data.decode("utf-8-sig")
            if "<mule" in text[:600]:
                return {"autos": [mule_neutral(text, re.sub(r"\.xml$", "", name.rsplit("/", 1)[-1]))], "runs": [], "kind": "Mule 4 app"}
            if "Component" in text[:400] and "shapes" in text:
                return {"autos": [boomi_neutral(text)], "runs": [], "kind": "Boomi process"}
        if low.endswith(".csv"):
            text = data.decode("utf-8-sig")
            if text.startswith("Date,Zap,Zap ID"):
                return {"autos": [], "runs": zap_history(text), "kind": "Zap History"}
    except (ValueError, ET.ParseError, KeyError) as e:
        return {"autos": [], "runs": [], "kind": None, "error": f"could not be read: {str(e)[:160]}"}
    return {"autos": [], "runs": [], "kind": None}


_w2.register(N8nApi(), PowerAutomateFlows(), Zapier(), Make(), Workato(), BoomiAtomSphere(), MuleSoftAnypoint())
IPAAS = ("n8n_api", "power_automate_flows", "zapier", "make", "workato", "boomi_atomsphere", "mulesoft_anypoint", "boomi", "mulesoft")     # boomi / mulesoft: Integration & APIs' connections
RUNNABLE = {"power_automate_flows": "flow_id", "make": "scenario_id", "boomi_atomsphere": "process_id", "boomi": "process_id"}     # old flows Relay can run on demand (side by side)
