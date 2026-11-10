"""The RPA platforms as Connector SDK adapters — one adapter + one mock-lab simulator each (tests/mocklab/sims/uipath.py:
`uipath`; blueprism.py: `blue_prism`; automationanywhere.py: `automation_anywhere`; powerautomate.py:
`power_automate_desktop`) — and the readers of their files (UiPath Main.xaml / .nupkg, Blue Prism .bprelease, Automation
Anywhere task-bot JSON, Power Automate Desktop Robin scripts), all into the W2 neutral shape (_w2.auto / _w2.run).

  UiPath           Orchestrator OData: client credentials at the identity server (OR.* scopes), the folder header,
                   $top / $skip paging; releases with their package's Main.xaml, jobs with their error. After approval:
                   a fixed package (the selector changed in Main.xaml, the version raised) uploaded, the release moved to
                   it and a job started to check it; failed jobs started again.
  Blue Prism       API v7 behind the Authentication Server; processes and sessions (pagingToken); the process design
                   comes from its .bprelease (the API does not serve it).
  Automation Any.  Control Room: POST /v2/authentication (20-minute token in X-Authorization), the repository's task
                   bots and their content, the activity list.
  PA Desktop       Dataverse Web API with Entra client credentials: desktop flows (category 6) with their Robin script,
                   flow sessions.
Screens are named by their window title; SCREENS says which application a title belongs to (a screen on a system that
has an API is an API candidate; the GST portal has none).
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
from xml.etree import ElementTree as ET

from .. import connectors
from .. import connectors_sdk as sdk
from . import _w2
from .n8n_platforms import _cached, _drop, _keep, _poll

SCREENS = {"Create Invoice": "Oracle Fusion", "Create Receipt": "Oracle Fusion", "XK01": "SAP S/4HANA", "VA01": "SAP S/4HANA", "VK12": "SAP S/4HANA", "saplogon.exe": "SAP S/4HANA",
           "Search Taxpayer": "GST portal", "GST Portal": "GST portal", "Returns > GSTR-1 > Upload": "GST portal", "Larkspur": ""}


def system_of(title: str) -> str:
    t = str(title or "").strip().rstrip("*").strip()
    return next((v for k, v in SCREENS.items() if k.lower() in t.lower()), "") if t else ""


# ================================================================== UiPath (Main.xaml)

UI = "{http://schemas.uipath.com/workflow/activities}"
XAML_KIND = {"GetIMAPMailMessages": "read_mail", "InvokeWorkflowFile": "extract", "TypeInto": "type", "Click": "screen", "AddQueueItem": "human", "SendOutlookMail": "notify",
             "ExcelReadRange": "read_file", "ForEachRow": "loop", "LogMessage": "code", "If": "decide"}


def xaml_steps(xaml: str) -> list[dict]:
    """Activities in order: kind, label, the window (system) a selector targets and the element it finds."""
    out = []
    try:
        root = ET.fromstring(xaml)
    except ET.ParseError:
        return out
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in XAML_KIND or tag in ("ExcelApplicationScope",):
            continue
        label = el.get("DisplayName")
        if not label:                                  # an unnamed activity (the error handler's log) is not a step
            continue
        sel = next((t.get("Selector") for t in el.iter() if t.tag.split("}")[-1] == "Target"), "") or ""
        win = (re.search(r"title='([^']+)'", sel) or re.search(r"app='([^']+)'", sel) or [None, ""])[1]
        elem = (re.search(r"(?:id|aaname|name)='([^']+)'", sel.split("/>", 1)[-1]) or [None, ""])[1]
        kind = XAML_KIND[tag]
        if kind == "screen" and out and out[-1]["label"] == label:            # TypeInto then Click on the same field: one step
            continue
        sys_ = system_of(win) if win else ""
        if not sys_ and "saplogon" in sel:
            sys_ = "SAP S/4HANA"
        out.append(_w2.step(label, kind, system=sys_, screen=win.rstrip("*") if win else "", field=elem, detail=sel[:200]))
    return out


def xaml_secrets(xaml: str) -> list[dict]:
    """A variable whose name says it is a password and that has a default value."""
    out = []
    try:
        root = ET.fromstring(xaml or "")
    except ET.ParseError:
        return out
    for el in root.iter():
        if el.tag.split("}")[-1] == "Variable" and _w2.SECRET_KEY.search(el.get("Name") or "") and len((el.get("Default") or "").strip()) >= 6:
            out.append({"where": f"variable {el.get('Name')}", "kind": "a default value"})
    return out


def mail_trigger(steps: list[dict], trigger: dict) -> tuple[dict, list[dict]]:
    """A bot that starts by reading a mailbox is started by the mail: the first step becomes its trigger."""
    if steps and steps[0]["kind"] == "read_mail":
        return {"kind": "email", "detail": steps[0]["label"]}, steps[1:]
    return trigger, steps


class UiPathOrchestrator(_w2.Adapter):
    kind, label, vendor, platform = "uipath_orchestrator", "UiPath Orchestrator", "UiPath", "UiPath"
    simulator = "tests/mocklab/sims/uipath.py: uipath (Orchestrator OData)"
    fields = [("base_url", "Orchestrator URL (https://cloud.uipath.com/<org>/<tenant>/orchestrator_)", True), ("token_url", "Identity token URL (https://cloud.uipath.com/identity_/connect/token)", True),
              ("folder_id", "Folder id (X-UIPATH-OrganizationUnitId)", True), ("client_id", "External application id", True)]
    secrets = {"api_key": ["client_secret"]}
    can_write = True
    SCOPE = "OR.Jobs OR.Execution OR.Robots OR.Queues OR.Assets OR.Monitoring OR.Folders"

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            r = _w2.call("UiPath identity", "POST", _w2.cfg(c, "token_url"), data={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"),
                                                                                 "client_secret": _w2.secret(c, "client_secret"), "scope": self.SCOPE})
            d = r.json()
            tok = _keep(c, d["access_token"], d.get("expires_in"))
        return {"Authorization": f"Bearer {tok}", "X-UIPATH-OrganizationUnitId": _w2.cfg(c, "folder_id"), "Accept": "application/json"}

    def forget(self, c):
        _drop(c)

    def _all(self, c, ent, params=None) -> list[dict]:
        out, skip = [], 0
        for _ in range(200):
            d = self.req(c, "GET", f"/odata/{ent}", params={"$top": 500, "$skip": skip, **(params or {})}).json()
            v = d.get("value") or []
            out += v
            if len(v) < 500:
                break
            skip += 500
        return out

    def package(self, c, key: str) -> bytes:
        return self.req(c, "GET", f"/odata/Processes/UiPath.Server.Configuration.OData.DownloadPackage(key='{key}')").content

    def xaml(self, c, key: str) -> str:
        return zipfile.ZipFile(io.BytesIO(self.package(c, key))).read("lib/net45/Main.xaml").decode("utf-8")

    def releases(self, c) -> list[dict]:
        return self._all(c, "Releases")

    def estate(self, c):
        out = []
        sched = {s["ReleaseId"]: s for s in self._all(c, "ProcessSchedules")}
        for r in self.releases(c):
            key = f"{r['ProcessKey']}:{r['ProcessVersion']}"
            try:
                x = self.xaml(c, key)
            except (connectors.ConnectorError, KeyError, zipfile.BadZipFile):
                x = ""
            s = sched.get(r["Id"]) or {}
            trig, steps = mail_trigger(xaml_steps(x), {"kind": "schedule" if s else "manual", "detail": s.get("StartProcessCronSummary") or ""})
            out.append(_w2.auto(str(r["Id"]), r.get("Description") or r["Name"], self.kind, kind="bot", active=bool(s.get("Enabled", True)),
                                trigger=trig, steps=steps, definition=x,
                                owner=r.get("OrganizationUnitFullyQualifiedName"), schedule=s.get("StartProcessCron") or "", release_key=r["Key"], package=key, process_key=r["ProcessKey"],
                                version=r["ProcessVersion"]))
            out[-1]["secrets"] = out[-1]["secrets"] or xaml_secrets(x)
        return out

    def runs(self, c, autos, since=None):
        out = [_w2.run(j["Id"], j["ReleaseId"], j["State"], j.get("StartTime"), j.get("EndTime"), j.get("Info") if j.get("State") == "Faulted" else None, None, source=j.get("Source"))
               for j in self._all(c, "Jobs", {"$orderby": "Id desc"})]
        return [r for r in out if not since or (r["start"] or 0) >= since]

    def _job(self, c, jid) -> dict:
        return _poll(lambda: self.req(c, "GET", f"/odata/Jobs({jid})").json(), lambda j: j.get("State") in ("Successful", "Faulted", "Stopped"))

    def _start(self, c, release_key: str, approval: str) -> dict:
        v = self.req(c, "POST", "/odata/Jobs/UiPath.Server.Configuration.OData.StartJobs", approval=approval,
                     json_body={"startInfo": {"ReleaseKey": release_key, "Strategy": "ModernJobsCount", "JobsCount": 1, "Source": "Manual"}}).json()["value"][0]
        j = self._job(c, v["Id"])
        return {"id": str(j["Id"]), "status": _w2.run(j["Id"], j["ReleaseId"], j["State"], None).get("status"), "error": j.get("Info") if j.get("State") == "Faulted" else None}

    def write_now(self, c, obj, payload, approval):
        if obj == "release_fix":
            pkg = self.package(c, payload["package"])
            new_ver = payload["version"]
            src = zipfile.ZipFile(io.BytesIO(pkg))
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n in src.namelist():
                    data = src.read(n)
                    if n.endswith("Main.xaml"):
                        data = data.decode("utf-8").replace(payload["find"], payload["replace"]).encode("utf-8")
                    elif n.endswith(".nuspec"):
                        data = re.sub(rb"<version>[^<]+</version>", f"<version>{new_ver}</version>".encode(), data)
                    elif n.endswith("project.json"):
                        d = json.loads(data)
                        d["projectVersion"] = new_ver
                        data = json.dumps(d, indent=2).encode()
                    z.writestr(n, data)
            self.req(c, "POST", "/odata/Processes/UiPath.Server.Configuration.OData.UploadPackage", approval=approval, content=buf.getvalue(), headers={"Content-Type": "application/octet-stream"})
            rel = self.req(c, "POST", f"/odata/Releases({payload['release_id']})/UiPath.Server.Configuration.OData.UpdateToLatestPackageVersion", approval=approval).json()
            check = self._start(c, payload["release_key"], approval)
            return {"ok": check["status"] == "success", "version": rel.get("ProcessVersion"), "reruns": [{"of": "a check job", **check}]}
        if obj == "retry":
            out = [{"of": k, **self._start(c, k, approval)} for k in payload.get("releases") or []]
            return {"ok": all(r["status"] == "success" for r in out), "reruns": out}
        raise sdk.ScopeError(f"UiPath: Relay does not write {obj!r}")


# ================================================================== Blue Prism (API v7; the design from a .bprelease)

PRC = "{http://www.blueprism.co.uk/product/process}"


def bprelease(text: str) -> list[dict]:
    """Processes of a Blue Prism release in the neutral shape: action stages with their business object (application -
    screen), decisions, and Text data items that hold a credential."""
    root = ET.fromstring(text)
    out = []
    for proc in root.iter(f"{PRC}process"):
        if proc.get("type") == "object" or not proc.get("name") or proc.find(f"{PRC}subsheet") is None:
            continue
        steps, secrets = [], []
        for st in proc.iter("stage"):
            typ, name = st.get("type"), st.get("name")
            if typ == "Action":
                res = st.find("resource")
                obj = res.get("object") if res is not None else ""
                app, _, screen = obj.partition(" - ")
                steps.append(_w2.step(name, "screen" if screen and screen != "API" else "post", system=system_of(screen) or (app if app != "Larkspur" else ""), screen="" if screen == "API" else screen))
            elif typ == "Decision":
                steps.append(_w2.step(name, "decide"))
            elif typ == "Data" and _w2.SECRET_KEY.search(name.replace(" ", "")) and (st.findtext("initialvalue") or "").strip():
                secrets.append({"where": f"data item {name}", "kind": "a Text data item"})
        a = _w2.auto(proc.get("name"), proc.get("narrative") or proc.get("name"), "blueprism_api", kind="bot", steps=steps, definition=None)
        a["secrets"] = secrets
        out.append(a)
    return out


class BluePrismApi(_w2.Adapter):
    kind, label, vendor, platform = "blueprism_api", "Blue Prism", "Blue Prism", "Blue Prism"
    simulator = "tests/mocklab/sims/blueprism.py: blue_prism (API v7)"
    fields = [("base_url", "API URL (https://<server>/api/v7)", True), ("token_url", "Authentication Server token URL (…/connect/token)", True), ("client_id", "Client id", True)]
    secrets = {"api_key": ["client_secret"]}

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            d = _w2.call("Blue Prism", "POST", _w2.cfg(c, "token_url"), data={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"),
                                                                            "client_secret": _w2.secret(c, "client_secret"), "scope": "bp-api"}).json()
            tok = _keep(c, d["access_token"], d.get("expires_in"))
        return {"Authorization": f"Bearer {tok}"}

    def forget(self, c):
        _drop(c)

    def _pages(self, c, path, params=None) -> list[dict]:
        out, tok = [], None
        for _ in range(200):
            d = self.req(c, "GET", path, params={"itemsPerPage": 200, **(params or {}), **({"pagingToken": tok} if tok else {})}).json()
            out += d.get("items") or []
            tok = d.get("pagingToken")
            if not tok:
                break
        return out

    def estate(self, c):
        return [_w2.auto(p["id"], p.get("description") or p["name"], self.kind, kind="bot", steps=[], updated=p.get("lastModifiedDate"), bp_name=p["name"]) for p in self._pages(c, "/processes")]

    def runs(self, c, autos, since=None):
        ids = {a.get("bp_name"): a["id"] for a in autos or self.estate(c)}
        out = []
        for s in self._pages(c, "/sessions"):
            out.append(_w2.run(s["sessionId"], ids.get(s["processName"], s["processName"]), {"Completed": "success", "Terminated": "failed", "Running": "running", "Pending": "queued"}.get(s["status"], s["status"]),
                               s.get("startTime"), s.get("endTime"), s.get("terminationReason"), s.get("latestStage")))
        return [r for r in out if not since or (r["start"] or 0) >= since]


# ================================================================== Automation Anywhere (Control Room)

AA_KIND = {"emailRetrieve": "read_mail", "extractData": "extract", "if": "decide", "insertWorkItem": "human", "emailSend": "notify", "loop.commands.start": "loop", "ftpDownload": "download",
           "setCell": "write", "openSpreadsheet": "read_file", "assign": "build", "capture": "screen", "restPost": "post"}


def aa_bot(content: dict) -> tuple[list[dict], list[dict]]:
    steps, secrets = [], []
    for n in content.get("nodes") or []:
        at = {a["name"]: a.get("value") or {} for a in n.get("attributes") or []}
        label = (at.get("label") or {}).get("string") or n.get("commandName")
        if n.get("packageName") == "Recorder":
            win = (at.get("windowTitle") or {}).get("string") or ""
            props = ((at.get("uiObject") or {}).get("uiObject") or {}).get("properties") or []
            steps.append(_w2.step(label, "screen", system=system_of(win), screen=win.rstrip("*"), field=next((p["value"] for p in props if p.get("isSelected")), "")))
        else:
            steps.append(_w2.step(label, AA_KIND.get(n.get("commandName"), "http"), api=(at.get("uri") or {}).get("string") or ""))
    for v in content.get("variables") or []:
        if _w2.SECRET_KEY.search(v.get("name") or "") and ((v.get("defaultValue") or {}).get("string") or "").strip():
            secrets.append({"where": f"variable {v['name']}", "kind": "a default value"})
    return steps, secrets


class AutomationAnywhereCR(_w2.Adapter):
    kind, label, vendor, platform = "aa_control_room", "Automation Anywhere", "Automation Anywhere", "Automation Anywhere"
    simulator = "tests/mocklab/sims/automationanywhere.py: automation_anywhere (Control Room API)"
    fields = [("base_url", "Control Room URL (https://<tenant>.my.automationanywhere.digital)", True), ("username", "API user", True)]
    secrets = {"api_key": ["api_key"]}

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            d = _w2.call("Automation Anywhere", "POST", self.base(c) + "/v2/authentication", json_body={"username": _w2.cfg(c, "username"), "apiKey": _w2.secret(c, "api_key")}).json()
            tok = _keep(c, d["token"], 1100)
        return {"X-Authorization": tok}

    def forget(self, c):
        _drop(c)

    def _list(self, c, path, body=None) -> list[dict]:
        out, off = [], 0
        for _ in range(200):
            d = self.req(c, "POST", path, json_body={**(body or {}), "page": {"offset": off, "length": 200}}).json()
            out += d.get("list") or []
            off += len(d.get("list") or [])
            if not d.get("list") or off >= int((d.get("page") or {}).get("total") or 0):
                break
        return out

    def estate(self, c):
        out = []
        for f in self._list(c, "/v2/repository/workspaces/public/files/list"):
            if f.get("type") != "application/vnd.aa.taskbot":
                continue
            content = self.req(c, "GET", f"/v2/repository/files/{f['id']}/content").json()
            steps, secrets = aa_bot(content)
            a = _w2.auto(str(f["id"]), f["name"], self.kind, kind="bot", steps=steps, definition=None, updated=f.get("lastModified"), path=f.get("path"))
            a["secrets"] = secrets
            out.append(a)
        return out

    def runs(self, c, autos, since=None):
        ids = {a["name"]: a["id"] for a in autos or self.estate(c)}
        out = [_w2.run(x["id"], ids.get(x["fileName"], x["fileName"]), {"COMPLETED": "success", "RUN_FAILED": "failed", "RUNNING": "running", "DEPLOYED": "queued"}.get(x["status"], x["status"]),
                       x.get("startDateTime"), x.get("endDateTime"), x.get("message") or None) for x in self._list(c, "/v3/activity/list")]
        return [r for r in out if not since or (r["start"] or 0) >= since]


# ================================================================== Power Automate Desktop (Dataverse)

def robin_steps(script: str) -> tuple[list[dict], list[dict]]:
    steps, secrets = [], []
    for line in (script or "").splitlines():
        s = line.strip()
        m = re.match(r"SET (\w+) TO \$'''(.*)'''", s)
        if m and _w2.SECRET_KEY.search(m.group(1)) and len(m.group(2)) >= 6:
            secrets.append({"where": f"variable {m.group(1)}", "kind": "a literal value"})
            continue
        win = (re.search(r"Window \\'([^\\]+)\\'", s) or re.search(r"Web Page \\'([^\\]+)\\'", s) or [None, ""])[1]
        if s.startswith(("UIAutomation.", "WebAutomation.Click", "WebAutomation.Populate")):
            steps.append(_w2.step(s.split(" ", 1)[0].split(".")[-1], "type" if "Populate" in s else "screen", system=system_of(win), screen=win))
        elif s.startswith("Outlook.SendEmail") or "SendEmail" in s.split(" ", 1)[0]:
            steps.append(_w2.step("Send e-mail", "notify"))
        elif s.startswith("Excel."):
            steps.append(_w2.step(s.split(" ", 1)[0], "read_file"))
        elif s.startswith("LOOP") or s.startswith("FOREACH"):
            steps.append(_w2.step("For each row", "loop"))
    return steps, secrets


class PowerAutomateDesktopDv(_w2.Adapter):
    kind, label, vendor, platform = "pa_desktop", "Power Automate Desktop", "Power Automate Desktop", "Power Automate Desktop"
    can_write = True
    simulator = "tests/mocklab/sims/powerautomate.py: power_automate_desktop (Dataverse Web API)"
    fields = [("base_url", "Dataverse URL (https://<org>.crm.dynamics.com)", True), ("tenant_id", "Entra tenant id", True), ("client_id", "App (client) id", True),
              ("token_url", "Token URL (default: Entra ID for the tenant)", False), ("resource", "Dataverse resource for the token (default: the URL)", False)]
    secrets = {"api_key": ["client_secret"]}

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            url = _w2.cfg(c, "token_url") or f"https://login.microsoftonline.com/{_w2.cfg(c, 'tenant_id')}/oauth2/v2.0/token"
            res = (_w2.cfg(c, "resource") or self.base(c)).rstrip("/")
            d = _w2.call("Entra ID", "POST", url, data={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"), "client_secret": _w2.secret(c, "client_secret"),
                                                        "scope": f"{res}/.default"}).json()
            tok = _keep(c, d["access_token"], d.get("expires_in"))
        return {"Authorization": f"Bearer {tok}", "OData-MaxVersion": "4.0", "OData-Version": "4.0", "Accept": "application/json"}

    def forget(self, c):
        _drop(c)

    def _all(self, c, path, params=None) -> list[dict]:
        out, url, p = [], path, params
        for _ in range(200):
            d = self.req(c, "GET", url, params=p).json()
            out += d.get("value") or []
            url, p = d.get("@odata.nextLink"), None
            if not url:
                break
        return out

    def estate(self, c):
        out = []
        for w in self._all(c, "/api/data/v9.2/workflows", {"$filter": "category eq 6"}):
            script = (json.loads(w.get("clientdata") or "{}").get("properties") or {}).get("definition") or ""
            steps, secrets = robin_steps(script)
            a = _w2.auto(w["workflowid"], w["name"], self.kind, kind="bot", active=w.get("statecode") == 1, steps=steps, definition=None, updated=w.get("modifiedon"))
            a["secrets"] = secrets
            out.append(a)
        return out

    def script(self, c, wid: str) -> tuple[dict, str]:
        w = next((x for x in self._all(c, "/api/data/v9.2/workflows", {"$filter": "category eq 6"}) if x["workflowid"] == wid), None)
        if not w:
            raise connectors.ConnectorError(f"Power Automate has no desktop flow {wid}")
        cd = json.loads(w.get("clientdata") or "{}")
        return cd, (cd.get("properties") or {}).get("definition") or ""

    def write_now(self, c, obj, payload, approval):
        if obj == "update_script":
            cd = json.loads(json.dumps(payload.get("clientdata") or {}))
            cd.setdefault("properties", {})["definition"] = payload["script"]
            self.req(c, "PATCH", f"/api/data/v9.2/workflows({payload['workflow_id']})", json_body={"clientdata": json.dumps(cd)}, approval=approval, headers={"Content-Type": "application/json"})
            _, back = self.script(c, payload["workflow_id"])
            found = [x for x in payload.get("expect") or [] if x in back]
            return {"ok": len(found) == len(payload.get("expect") or []), "updated": True, "found": found}
        raise sdk.ScopeError(f"Power Automate Desktop: Relay does not write {obj!r}")

    def runs(self, c, autos, since=None):
        out = [_w2.run(s["flowsessionid"], s["_regardingobjectid_value"], {4: "success", 5: "failed"}.get(s.get("statuscode"), "running"), s.get("startedon"), s.get("completedon"),
                       s.get("errormessage")) for s in self._all(c, "/api/data/v9.2/flowsessions")]
        return [r for r in out if not since or (r["start"] or 0) >= since]


RPA = ("uipath_orchestrator", "blueprism_api", "aa_control_room", "pa_desktop")
_w2.register(UiPathOrchestrator(), BluePrismApi(), AutomationAnywhereCR(), PowerAutomateDesktopDv())


def parse_file(name: str, data: bytes) -> dict:
    """An uploaded RPA file in the neutral shape: Main.xaml, a .nupkg, a .bprelease, a task-bot .json, a Robin .txt."""
    low = name.lower()
    try:
        if low.endswith(".nupkg"):
            z = zipfile.ZipFile(io.BytesIO(data))
            x = z.read(next(n for n in z.namelist() if n.endswith("Main.xaml"))).decode("utf-8")
            a = _w2.auto(name, name.rsplit(".", 4)[0], "uipath_orchestrator", kind="bot", steps=xaml_steps(x), definition=x)
            a["secrets"] = a["secrets"] or xaml_secrets(x)
            return {"kind": "UiPath package", "autos": [a], "runs": []}
        if low.endswith(".xaml"):
            x = data.decode("utf-8")
            a = _w2.auto(name, name.rsplit(".", 1)[0], "uipath_orchestrator", kind="bot", steps=xaml_steps(x), definition=x)
            a["secrets"] = a["secrets"] or xaml_secrets(x)
            return {"kind": "UiPath workflow", "autos": [a], "runs": []}
        if low.endswith(".bprelease"):
            return {"kind": "Blue Prism release", "autos": bprelease(data.decode("utf-8")), "runs": []}
        if low.endswith(".json"):
            d = json.loads(data)
            if isinstance(d, dict) and "nodes" in d and "variables" in d:
                steps, secrets = aa_bot(d)
                a = _w2.auto(name, name.rsplit(".", 1)[0], "aa_control_room", kind="bot", steps=steps)
                a["secrets"] = secrets
                return {"kind": "Automation Anywhere bot", "autos": [a], "runs": []}
        if low.endswith(".txt") and (b"UIAutomation" in data or b"WebAutomation" in data):
            steps, secrets = robin_steps(data.decode("utf-8"))
            a = _w2.auto(name, name.split(".", 1)[0], "pa_desktop", kind="bot", steps=steps)
            a["secrets"] = secrets
            return {"kind": "Power Automate Desktop flow", "autos": [a], "runs": []}
    except (ValueError, KeyError, StopIteration, ET.ParseError, zipfile.BadZipFile, UnicodeDecodeError) as e:
        return {"kind": "unreadable", "autos": [], "runs": [], "error": str(e)[:200]}
    return {"kind": None, "autos": [], "runs": []}
