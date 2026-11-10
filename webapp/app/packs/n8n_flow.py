"""n8n workflow JSON for Workflows & iPaaS (and the other W2 packs that move work onto n8n): the node vocabulary, a
process map or a neutral flow -> the design a person confirms (rules first), the design -> a workflow skeleton, and the
rules every workflow must pass before it is tested or deployed (the format n8n's public API accepts: nodes with type /
typeVersion / position / parameters / credentials by name, `connections` keyed by node name).

A design: [{"id", "name", "type", "role" (trigger | action | decision | person), "system", "api", "credential",
"detail", "next" ("Name A; Name B" — a decision's first is its true branch), "origin"}].
"""
from __future__ import annotations

import copy
import json
import re
import uuid as _uuid

from . import _w2

# node type -> (typeVersion, role, what it is in plain words)
NODES = {
    "n8n-nodes-base.webhook": (2, "trigger", "Webhook (a call starts it)"),
    "n8n-nodes-base.scheduleTrigger": (1.2, "trigger", "Schedule"),
    "n8n-nodes-base.emailReadImap": (2, "trigger", "New e-mail (IMAP)"),
    "n8n-nodes-base.manualTrigger": (1, "trigger", "Started by hand"),
    "n8n-nodes-base.formTrigger": (2.2, "trigger", "Form submitted"),
    "n8n-nodes-base.httpRequest": (4.2, "action", "HTTP request (an API call)"),
    "n8n-nodes-base.if": (2, "decision", "If (a decision)"),
    "n8n-nodes-base.switch": (3, "decision", "Switch"),
    "n8n-nodes-base.splitInBatches": (3, "action", "Loop over items"),
    "n8n-nodes-base.code": (2, "action", "Code (JavaScript)"),
    "n8n-nodes-base.set": (3.4, "action", "Set fields"),
    "n8n-nodes-base.microsoftTeams": (2, "person", "Microsoft Teams message"),
    "n8n-nodes-base.emailSend": (2.1, "action", "Send e-mail"),
    "n8n-nodes-base.jira": (1, "person", "Jira issue (hand to a person)"),
    "n8n-nodes-base.ftp": (1, "action", "FTP / SFTP"),
    "n8n-nodes-base.microsoftExcel": (2, "action", "Microsoft Excel 365"),
    "n8n-nodes-base.readWriteFile": (1, "action", "Read or write a file"),
    "n8n-nodes-base.wait": (1.1, "action", "Wait"),
    "n8n-nodes-base.noOp": (1, "action", "No operation"),
}
TRIGGERS = {k for k, v in NODES.items() if v[1] == "trigger"}
TYPE_OPTIONS = tuple((k, f"{v[2]} ({k.split('.')[-1]})") for k, v in NODES.items())
# neutral step kind -> node type
FOR_KIND = {"read_mail": "n8n-nodes-base.emailReadImap", "extract": "n8n-nodes-base.httpRequest", "lookup": "n8n-nodes-base.httpRequest", "decide": "n8n-nodes-base.if",
            "post": "n8n-nodes-base.httpRequest", "human": "n8n-nodes-base.jira", "notify": "n8n-nodes-base.microsoftTeams", "validate": "n8n-nodes-base.httpRequest",
            "download": "n8n-nodes-base.ftp", "loop": "n8n-nodes-base.splitInBatches", "write": "n8n-nodes-base.microsoftExcel", "export": "n8n-nodes-base.httpRequest",
            "read_file": "n8n-nodes-base.readWriteFile", "type": "n8n-nodes-base.httpRequest", "fetch": "n8n-nodes-base.httpRequest", "build": "n8n-nodes-base.code",
            "upload": "n8n-nodes-base.httpRequest", "code": "n8n-nodes-base.code", "http": "n8n-nodes-base.httpRequest", "wait": "n8n-nodes-base.wait", "screen": "n8n-nodes-base.httpRequest"}
SYSTEM_URL = {"Oracle Fusion": "https://fa-larkspur.fa.ocs.oraclecloud.com", "SAP S/4HANA": "https://s4.larkspur.example", "Entra ID": "https://graph.microsoft.com",
              "Jira": "https://larkspur.atlassian.net", "Power BI": "https://api.powerbi.com", "Zoho Books": "https://www.zohoapis.in", "GST portal": "https://api.gst.example",
              "Tally": "http://tally.larkspur.example:9000", "Azure AI Document Intelligence": "https://larkspur-di.cognitiveservices.azure.com"}
CRED_TYPE = {"Entra ID": "microsoftOAuth2Api", "Jira": "jiraSoftwareCloudApi"}
HOSTS = [(re.compile(r"oraclecloud\.com"), "Oracle Fusion"), (re.compile(r"s4\.|/sap/opu/"), "SAP S/4HANA"), (re.compile(r"graph\.microsoft\.com"), "Entra ID"),
         (re.compile(r"atlassian\.net|/rest/api/\d"), "Jira"), (re.compile(r"powerbi\.com"), "Power BI"), (re.compile(r"zohoapis|/books/v3"), "Zoho Books"),
         (re.compile(r"gst\.example|gstr1|/returns/"), "GST portal"), (re.compile(r"cognitiveservices|documentintelligence|formrecognizer"), "Azure AI Document Intelligence"),
         (re.compile(r"tally"), "Tally")]


def system_of(url: str) -> str:
    return next((name for rx, name in HOSTS if rx.search(url or "")), "")


def names(nxt: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;\n]", str(nxt or "")) if x.strip()]


# ------------------------------------------------------------------ design from a process map (W4 Business process documents)

def design_from_map(proc: dict) -> tuple[list[dict], list[str]]:
    """A confirmed BPMN map -> the nodes of a workflow, rules first: the start event becomes the trigger (an e-mail, a
    schedule or a call), a task in a system with an API becomes an API call, a decision an If with its labelled ways, a
    person's task a hand-over to that person; the end event closes the flow. Returns (design, notes)."""
    steps = {s["id"]: s for s in proc.get("steps") or []}
    lanes = {l["id"]: l for l in proc.get("lanes") or []}
    notes: list[str] = []
    start = next((s for s in steps.values() if s.get("type") == "start"), None)
    if not start:
        return [], ["the map has no start event"]
    sname = (start.get("name") or "").lower()
    if any(w in sname for w in ("e-mail", "email", "mail", "inbox")):
        ttype, tdetail = "n8n-nodes-base.emailReadImap", "the mailbox named in the map"
    elif any(w in sname for w in ("daily", "every", "schedule", "each morning", "weekly", "monthly", "night")):
        ttype, tdetail = "n8n-nodes-base.scheduleTrigger", start.get("name")
    else:
        ttype, tdetail = "n8n-nodes-base.webhook", "a call from the system that starts it"
    out: list[dict] = []
    name_of: dict[str, str] = {}
    used: set[str] = set()

    def uniq(n):
        n = (n or "Step")[:60]
        base, k = n, 2
        while n in used:
            n, k = f"{base} {k}", k + 1
        used.add(n)
        return n
    name_of[start["id"]] = uniq(start.get("name") or "Start")
    out.append({"id": start["id"], "name": name_of[start["id"]], "type": ttype, "role": "trigger", "system": "", "api": "", "credential": "", "detail": tdetail, "next": "", "origin": start["id"]})
    for sid, s in steps.items():
        t = s.get("type")
        if t in ("start", "end"):
            continue
        lane = (lanes.get(s.get("lane")) or {}).get("kind") or "person"
        sysname = s.get("system") or ""
        if t == "gateway":
            typ, role, detail = "n8n-nodes-base.if", "decision", s.get("name") or "a decision"
        elif lane == "person" and t in ("manual",) or (lane == "person" and not sysname):
            typ, role, detail = "n8n-nodes-base.microsoftTeams", "person", f"{(lanes.get(s.get('lane')) or {}).get('name') or 'a person'} does it: {s.get('name')}"
        elif sysname in SYSTEM_URL or sysname in _w2.API_SYSTEMS:
            typ, role, detail = "n8n-nodes-base.httpRequest", "action", f"{sysname} API" + (f": {', '.join(s.get('fields') or [])}" if s.get("fields") else "")
        elif sysname:
            typ, role, detail = "n8n-nodes-base.httpRequest", "action", f"{sysname}: no API Relay knows — the person names the endpoint, or this step stays a bot (RPA)"
            notes.append(f"{s.get('name')}: {sysname} has no API Relay knows; the endpoint is to be named")
        else:
            typ, role, detail = "n8n-nodes-base.code", "action", s.get("rule") or s.get("name") or "a step"
        name_of[sid] = uniq(s.get("name"))
        out.append({"id": sid, "name": name_of[sid], "type": typ, "role": role, "system": sysname, "api": "", "credential": f"{sysname} service account" if typ == "n8n-nodes-base.httpRequest" and sysname else
                    ("Teams bot" if typ == "n8n-nodes-base.microsoftTeams" else ""), "detail": detail, "next": "", "origin": sid, "when": ""})
    ends = {sid for sid, s in steps.items() if s.get("type") == "end"}
    for d in out:
        src = steps[d["origin"]]
        ways = [n for n in src.get("next") or [] if n.get("to") in name_of and n.get("to") not in ends]
        if d["type"] == "n8n-nodes-base.if":
            ways = sorted(ways, key=lambda n: 0 if re.search(r"\b(yes|match|true|ok|within|approved)\b", (n.get("when") or "").lower()) else 1)
            d["when"] = "; ".join(f"{name_of[n['to']]}: {n.get('when') or ''}" for n in ways)
        d["next"] = "; ".join(name_of[n["to"]] for n in ways)
    return out, notes


def design_from_auto(a: dict) -> list[dict]:
    """A neutral flow (any platform, read by Relay) -> the n8n design: one node per step, in order; a decision's true
    way is the next step and its false way the hand-over to a person when there is one (as the source flow does)."""
    t = (a.get("trigger") or {}).get("kind") or "manual"
    ttype = {"email": "n8n-nodes-base.emailReadImap", "schedule": "n8n-nodes-base.scheduleTrigger", "webhook": "n8n-nodes-base.webhook", "form": "n8n-nodes-base.webhook",
             "manual": "n8n-nodes-base.manualTrigger", "queue": "n8n-nodes-base.webhook"}.get(t, "n8n-nodes-base.webhook")
    out = [{"id": "t", "name": "Trigger" if t == "manual" else {"email": "New invoice e-mail", "schedule": "Schedule", "webhook": "Webhook", "form": "Form submitted", "queue": "Webhook"}[t],
            "type": ttype, "role": "trigger", "system": "", "api": "", "credential": "", "detail": (a.get("trigger") or {}).get("detail") or "", "next": "", "origin": "trigger"}]
    used = {out[0]["name"]}
    steps = [s for s in a.get("steps") or [] if s["kind"] != "trigger"]
    for s in steps:
        n = s["label"][:60] or s["kind"]
        while n in used:
            n += " 2"
        used.add(n)
        typ = FOR_KIND.get(s["kind"], "n8n-nodes-base.httpRequest")
        if s["kind"] == "notify" and "mail" in (s.get("detail") or s["label"]).lower():
            typ = "n8n-nodes-base.emailSend"
        cred = (f"{s['system']} service account" if typ == "n8n-nodes-base.httpRequest" and s.get("system") else "Teams bot" if typ == "n8n-nodes-base.microsoftTeams" else
                "Jira service desk" if typ == "n8n-nodes-base.jira" else "Relay SMTP" if typ == "n8n-nodes-base.emailSend" else "")
        out.append({"id": s.get("id") or n, "name": n, "type": typ, "role": NODES[typ][1], "system": s.get("system") or "", "api": s.get("api") or "", "credential": cred,
                    "detail": s.get("detail") or NEUTRAL_TEXT.get(s["kind"], ""), "next": "", "origin": s.get("id") or s["label"], "kind": s["kind"]})
    person = next((d["name"] for d in out if d.get("kind") == "human"), None)
    for i, d in enumerate(out):
        nxt = out[i + 1]["name"] if i + 1 < len(out) else ""
        if d.get("kind") == "human":
            d["next"] = ""
            continue
        if nxt and out[i + 1].get("kind") == "human" and d["type"] != "n8n-nodes-base.if":
            nxt = out[i + 2]["name"] if i + 2 < len(out) else ""
        if d["type"] == "n8n-nodes-base.if":
            yes = next((x["name"] for x in out[i + 1:] if x.get("kind") != "human"), "")
            d["next"] = "; ".join(x for x in (yes, person) if x)
            d["when"] = f"{yes}: yes; {person}: no" if person else f"{yes}: yes"
        else:
            d["next"] = nxt
    return out


NEUTRAL_TEXT = dict(_w2.NEUTRAL)


def design_problems(design: list[dict]) -> list[str]:
    """Rules first: a design that cannot become a workflow is refused before anything is written."""
    out = []
    nm = [d.get("name") or "" for d in design]
    dup = sorted({n for n in nm if nm.count(n) > 1})
    if dup:
        out.append(f"node names must be unique: {', '.join(dup)}")
    trig = [d for d in design if d.get("type") in TRIGGERS]
    if len(trig) != 1:
        out.append(f"a workflow starts with exactly one trigger (an e-mail, a schedule, a webhook or a form) — this design has {len(trig)}")
    for d in design:
        if d.get("type") not in NODES:
            out.append(f"{d.get('name')}: {d.get('type')!r} is not a node type Relay writes")
        for n in names(d.get("next")):
            if n not in nm:
                out.append(f"{d.get('name')}: its next node “{n}” is not in the design")
        if d.get("type") == "n8n-nodes-base.if" and len(names(d.get("next"))) not in (1, 2):
            out.append(f"{d.get('name')}: a decision leads to one or two nodes (true, then false)")
        if d.get("credential") and _w2.SECRET_INLINE.search(f"password={d['credential']}") and re.search(r"[:=]|\s", str(d["credential"])) is None and len(str(d["credential"])) > 40:
            out.append(f"{d.get('name')}: a credential is named, never pasted")
        if re.search(r"(?i)pass(word)?\s*[:=]|secret\s*[:=]|bearer\s+\S{12,}", str(d.get("credential") or "") + " " + str(d.get("detail") or "")):
            out.append(f"{d.get('name')}: credentials are referred to by name only — remove the secret from the design")
    reach, seen = [t["name"] for t in trig[:1]], set()
    while reach:
        n = reach.pop()
        if n in seen:
            continue
        seen.add(n)
        d = next((x for x in design if x.get("name") == n), None)
        reach += names((d or {}).get("next"))
    lost = [d["name"] for d in design if d.get("name") not in seen]
    if trig and lost:
        out.append(f"not reachable from the trigger: {', '.join(lost[:6])}")
    return out


# ------------------------------------------------------------------ design -> workflow skeleton

def skeleton(name: str, design: list[dict], *, seed: str = "") -> dict:
    """The workflow the rules can write: every node with its type, version, position and the parameters its kind needs;
    what needs judgement (an If's condition, a Code node's JavaScript, an endpoint's path) is marked TODO for the agent."""
    nodes, conns = [], {}
    for i, d in enumerate(design):
        t = d["type"]
        p: dict = {}
        if t == "n8n-nodes-base.httpRequest":
            method, path = ((d.get("api") or "").split(" ", 1) + [""])[:2] if d.get("api") else ("POST", "")
            url = (path if path.startswith("http") else SYSTEM_URL.get(d.get("system") or "", "") + path) if path else (SYSTEM_URL.get(d.get("system") or "", "") + "/TODO" if d.get("system") else "TODO")
            p = {"method": method or "POST", "url": url, "authentication": "predefinedCredentialType" if d.get("system") else "genericCredentialType",
                 "sendBody": (method or "POST") in ("POST", "PATCH", "PUT"), "options": {"timeout": 120000}}
        elif t == "n8n-nodes-base.if":
            p = {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [{"id": "c1", "leftValue": "TODO", "rightValue": "", "operator": {"type": "string", "operation": "equals"}}]}}
        elif t == "n8n-nodes-base.webhook":
            p = {"httpMethod": "POST", "path": _w2.slug(name, 40), "responseMode": "onReceived", "options": {}}
        elif t == "n8n-nodes-base.scheduleTrigger":
            p = {"rule": {"interval": [{"field": "cronExpression", "expression": "0 7 * * *"}]}}
        elif t == "n8n-nodes-base.emailReadImap":
            p = {"mailbox": "INBOX", "format": "resolved", "options": {}}
        elif t == "n8n-nodes-base.code":
            p = {"jsCode": "// TODO: " + (d.get("detail") or d["name"]) + "\nreturn items;"}
        elif t == "n8n-nodes-base.microsoftTeams":
            p = {"resource": "channelMessage", "teamId": "TODO", "channelId": "TODO", "message": f"={d['name']}: {{{{ $json.summary }}}}"}
        elif t == "n8n-nodes-base.jira":
            p = {"project": {"__rl": True, "value": "TODO", "mode": "list"}, "issueType": {"__rl": True, "value": "10002", "mode": "list"}, "summary": f"={d['name']}"}
        elif t == "n8n-nodes-base.emailSend":
            p = {"fromEmail": "automation@larkspur.example", "toEmail": "={{ $json.to }}", "subject": d["name"], "emailFormat": "text"}
        elif t == "n8n-nodes-base.splitInBatches":
            p = {"batchSize": 50, "options": {}}
        elif t == "n8n-nodes-base.ftp":
            p = {"protocol": "sftp", "operation": "download", "path": "TODO"}
        elif t == "n8n-nodes-base.microsoftExcel":
            p = {"resource": "worksheet", "operation": "append", "workbook": {"__rl": True, "value": "TODO", "mode": "list"}}
        elif t == "n8n-nodes-base.readWriteFile":
            p = {"fileSelector": "TODO"}
        node = {"id": str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"relay:{seed}:{name}:{d['name']}")), "name": d["name"], "type": t, "typeVersion": NODES[t][0], "position": [240 * i, 300], "parameters": p}
        if d.get("credential"):
            ctype = CRED_TYPE.get(d.get("system") or "", "oAuth2Api") if t == "n8n-nodes-base.httpRequest" else {"n8n-nodes-base.microsoftTeams": "microsoftTeamsOAuth2Api", "n8n-nodes-base.jira": "jiraSoftwareCloudApi",
                                                                                                                   "n8n-nodes-base.emailSend": "smtp", "n8n-nodes-base.emailReadImap": "imap", "n8n-nodes-base.ftp": "sftp"}.get(t, "httpHeaderAuth")
            node["credentials"] = {ctype: {"name": d["credential"]}}
        nodes.append(node)
    for d in design:
        nxt = names(d.get("next"))
        if not nxt:
            continue
        if d["type"] == "n8n-nodes-base.if":
            conns[d["name"]] = {"main": [[{"node": n, "type": "main", "index": 0}] for n in nxt[:2]]}
        else:
            conns[d["name"]] = {"main": [[{"node": n, "type": "main", "index": 0} for n in nxt]]}
    return {"name": name, "nodes": nodes, "connections": conns, "settings": {"executionOrder": "v1", "saveManualExecutions": True, "callerPolicy": "workflowsFromSameOwner"},
            "staticData": None, "meta": {"relay": True}, "pinData": {}, "tags": []}


def from_auto(a: dict, *, fixes: dict | None = None) -> tuple[dict, list[dict]]:
    """A neutral flow -> (n8n workflow, the design it came from), rules only: every parameter Relay can carry over is
    carried (the API path, the payload), a known fix is applied where a decision says so (GSTR1_V2)."""
    design = design_from_auto(a)
    wf = skeleton(a["name"], design, seed=a["id"])
    by_label = {s["label"][:60]: s for s in a.get("steps") or []}
    for n in wf["nodes"]:
        s = by_label.get(n["name"])
        if not s:
            continue
        if n["type"] == "n8n-nodes-base.httpRequest" and s.get("api"):
            method, path = (s["api"].split(" ", 1) + [""])[:2]
            n["parameters"]["method"], n["parameters"]["url"] = method, (path if path.startswith("http") else SYSTEM_URL.get(s.get("system") or "", "https://" + _w2.slug(s.get("system") or "api") + ".example") + path)
            n["parameters"]["sendBody"] = method in ("POST", "PATCH", "PUT")
        if s.get("body"):
            n["parameters"]["sendBody"] = True
            n["parameters"]["specifyBody"] = "json"
            n["parameters"]["jsonBody"] = "=" + json.dumps(s["body"]) if not str(s["body"]).startswith("=") else s["body"]
        if n["type"] == "n8n-nodes-base.if":
            n["parameters"]["conditions"]["conditions"] = [{"id": "c1", "leftValue": "={{ $json.confidence }}", "rightValue": 0.85, "operator": {"type": "number", "operation": "gte"}}] \
                if "confidence" in (s.get("detail") or s["label"]).lower() or "85" in s["label"] else [{"id": "c1", "leftValue": "={{ $json.ok }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}}]
        if n["type"] == "n8n-nodes-base.code":
            n["parameters"]["jsCode"] = "// " + (s.get("detail") or s["label"]) + "\nreturn items.map(i => ({ json: { ...i.json } }));"
        if n["type"] in ("n8n-nodes-base.microsoftTeams",):
            n["parameters"].update(teamId="larkspur-ops", channelId="automation")
        if n["type"] == "n8n-nodes-base.jira":
            n["parameters"]["project"]["value"] = "AP"
        if n["type"] == "n8n-nodes-base.ftp":
            n["parameters"]["path"] = s.get("detail") or "/outbound"
        if n["type"] == "n8n-nodes-base.microsoftExcel":
            n["parameters"]["workbook"]["value"] = s.get("detail") or "workbook.xlsx"
        if n["type"] == "n8n-nodes-base.readWriteFile":
            n["parameters"]["fileSelector"] = s.get("detail") or "/data/input"
    t = next(n for n in wf["nodes"] if n["type"] in TRIGGERS)
    if t["type"] == "n8n-nodes-base.scheduleTrigger" and (a.get("trigger") or {}).get("cron"):
        t["parameters"]["rule"]["interval"][0]["expression"] = a["trigger"]["cron"]
    if t["type"] == "n8n-nodes-base.webhook":
        t["parameters"]["path"] = _w2.slug(a["name"], 40)
    for k, v in (fixes or {}).items():
        wf = json.loads(json.dumps(wf).replace(k, v))
    return wf, design


# ------------------------------------------------------------------ the rules every workflow passes

def check(wf, design: list[dict] | None = None) -> list[dict]:
    """Each rule as a gate row (status pass | fail | warn): what n8n's API refuses, and what Relay refuses on top —
    secrets in clear, nodes the design does not have, TODOs left, unbalanced expressions."""
    rows = []

    def r(name, label, ok, detail, warn=False):
        rows.append(_w2.gate(name, label, "pass" if ok else ("warn" if warn else "fail"), detail=detail))
    if not isinstance(wf, dict):
        return [_w2.gate("json", "The file is a workflow object", "fail", detail="workflow.json is not a JSON object")]
    miss = [k for k in ("name", "nodes", "connections", "settings") if k not in wf]
    r("shape", "Name, nodes, connections and settings are there (what n8n's API requires)", not miss, "missing: " + ", ".join(miss) if miss else "all four present")
    nodes = wf.get("nodes") if isinstance(wf.get("nodes"), list) else []
    nm = [n.get("name") for n in nodes if isinstance(n, dict)]
    bad = [str(n.get("name") or "?") for n in nodes if not isinstance(n, dict) or not n.get("name") or not n.get("type") or not isinstance(n.get("typeVersion"), (int, float))
           or not (isinstance(n.get("position"), list) and len(n["position"]) == 2) or not isinstance(n.get("parameters"), dict)]
    r("nodes", "Every node has a name, type, version, position and parameters", nodes and not bad, f"{len(nodes)} node(s)" + (f"; incomplete: {', '.join(bad[:5])}" if bad else ""))
    dup = sorted({x for x in nm if nm.count(x) > 1})
    r("unique", "Node names are unique", not dup, "duplicates: " + ", ".join(dup) if dup else "unique")
    unknown = sorted({n.get("type") for n in nodes if isinstance(n, dict) and n.get("type") not in NODES})
    r("types", "Every node type is one Relay knows how to test", not unknown, "unknown: " + ", ".join(map(str, unknown)) if unknown else "known types")
    trig = [n for n in nodes if isinstance(n, dict) and n.get("type") in TRIGGERS]
    r("trigger", "Exactly one trigger starts it (n8n refuses to activate a workflow without one)", len(trig) == 1, f"{len(trig)} trigger(s)")
    conns = wf.get("connections") if isinstance(wf.get("connections"), dict) else {}
    broken = []
    for src, outs in conns.items():
        if src not in nm:
            broken.append(f"from {src}")
        for branch in (outs or {}).get("main") or []:
            for cn in branch or []:
                if not isinstance(cn, dict) or cn.get("node") not in nm:
                    broken.append(f"{src} → {(cn or {}).get('node')}")
    r("connections", "Every connection joins two nodes that exist", not broken, "broken: " + "; ".join(broken[:5]) if broken else f"{sum(len(b or []) for o in conns.values() for b in (o or {}).get('main') or [])} link(s)")
    reach, seen = [t["name"] for t in trig[:1]], set()
    while reach:
        n = reach.pop()
        if n in seen:
            continue
        seen.add(n)
        for branch in (conns.get(n) or {}).get("main") or []:
            reach += [cn.get("node") for cn in branch or [] if isinstance(cn, dict)]
    lost = [x for x in nm if x not in seen]
    r("reachable", "Every node is reached from the trigger", not lost, "not reached: " + ", ".join(map(str, lost[:5])) if lost else "all reached")
    ifs = [n for n in nodes if isinstance(n, dict) and n.get("type") == "n8n-nodes-base.if"]
    bad_if = [n["name"] for n in ifs if not (((n.get("parameters") or {}).get("conditions") or {}).get("conditions")) or len((conns.get(n["name"]) or {}).get("main") or []) > 2]
    r("decisions", "Every decision has a condition and at most two ways on", not bad_if, "to fix: " + ", ".join(bad_if) if bad_if else f"{len(ifs)} decision(s)")
    http = [n for n in nodes if isinstance(n, dict) and n.get("type") == "n8n-nodes-base.httpRequest"]
    bad_http = [n["name"] for n in http if not (n.get("parameters") or {}).get("url") or not (n.get("parameters") or {}).get("method")]
    r("http", "Every API call names its method and URL", not bad_http, "to fix: " + ", ".join(bad_http) if bad_http else f"{len(http)} API call(s)")
    sec = _w2.secrets_in(wf)
    r("secrets", "No credential is kept in clear — credentials by name only", not sec, "; ".join(s["where"] for s in sec[:4]) if sec else "credentials by name")
    cred_bad = [n["name"] for n in nodes if isinstance(n, dict) and isinstance(n.get("credentials"), dict) and any(not isinstance(v, dict) or not v.get("name") for v in n["credentials"].values())]
    r("credentials", "Every credential is referred to by its name", not cred_bad, "unnamed: " + ", ".join(cred_bad) if cred_bad else "named")
    text = json.dumps(wf)
    todo = [n["name"] for n in nodes if isinstance(n, dict) and "TODO" in json.dumps(n.get("parameters") or {})]
    r("todo", "Nothing is left to fill in (no TODO)", not todo, "still TODO: " + ", ".join(todo[:6]) if todo else "complete")
    exprs = re.findall(r'"=([^"\\]*(?:\\.[^"\\]*)*)"', text)
    unbal = [e[:40] for e in exprs if e.count("{{") != e.count("}}")]
    r("expressions", "Every expression is balanced ({{ … }})", not unbal, "unbalanced: " + "; ".join(unbal[:3]) if unbal else f"{len(exprs)} expression(s)")
    if design:
        want = {d["name"] for d in design}
        extra, missing = sorted(set(nm) - want), sorted(want - set(nm))
        r("design", "The nodes are the ones the person confirmed — nothing invented, nothing left out", not extra and not missing,
          ("not in the design: " + ", ".join(map(str, extra)) if extra else "") + ("; " if extra and missing else "") + ("left out: " + ", ".join(missing) if missing else "") or "as designed")
        links = {(d["name"], n) for d in design for n in names(d.get("next"))}
        have = {(src, cn.get("node")) for src, outs in conns.items() for b in (outs or {}).get("main") or [] for cn in b or [] if isinstance(cn, dict)}
        r("flow", "The links are the ones the person confirmed", links == have, f"{len(links & have)} of {len(links)} link(s) as designed" + (f"; extra: {sorted(have - links)[:3]}" if have - links else ""))
    return rows


def problems(wf, design: list[dict] | None = None) -> list[str]:
    return [f"{g['label']}: {g['detail']}" for g in check(wf, design) if g["status"] == "fail"]


def test_copy(wf: dict, path: str) -> dict:
    """The copy a test run executes: the same nodes, the trigger replaced by a webhook at a path of its own (so sample
    payloads can be sent), inactive until the approved test activates it, removed afterwards."""
    cp = copy.deepcopy(wf)
    trig = next((n for n in cp["nodes"] if n.get("type") in TRIGGERS), None)
    if trig:
        old = trig["name"]
        trig.update(type="n8n-nodes-base.webhook", typeVersion=NODES["n8n-nodes-base.webhook"][0], parameters={"httpMethod": "POST", "path": path, "responseMode": "onReceived", "options": {}})
        trig.pop("credentials", None)
        trig.pop("webhookId", None)
        _ = old
    cp["name"] = f"[Relay test] {wf.get('name')}"[:120]
    return {k: cp[k] for k in ("name", "nodes", "connections", "settings")}


def change_param(wf: dict, node: str, old: str, new: str) -> tuple[dict, int]:
    """A rules-first fix: replace text inside one node's parameters only (returns the workflow and how many places changed)."""
    out = copy.deepcopy(wf)
    n = next((x for x in out.get("nodes") or [] if x.get("name") == node), None)
    if not n:
        return out, 0
    before = json.dumps(n.get("parameters") or {})
    after = before.replace(old, new)
    n["parameters"] = json.loads(after)
    return out, before.count(old)


def change_credential(wf: dict, node: str, new_name: str, new_id: str | None = None) -> tuple[dict, int]:
    out = copy.deepcopy(wf)
    k = 0
    for n in out.get("nodes") or []:
        if node and n.get("name") != node:
            continue
        for ctype, ref in (n.get("credentials") or {}).items():
            n["credentials"][ctype] = {"name": new_name, **({"id": new_id} if new_id else {})}
            k += 1
    return out, k


def diff(a: dict, b: dict) -> list[dict]:
    """Node-level difference between two workflows: which nodes' parameters, credentials or links changed."""
    an = {n["name"]: n for n in a.get("nodes") or []}
    bn = {n["name"]: n for n in b.get("nodes") or []}
    out = []
    for name in sorted(set(an) | set(bn)):
        x, y = an.get(name), bn.get(name)
        if not x or not y:
            out.append({"node": name, "what": "added" if y else "removed"})
            continue
        for part in ("type", "parameters", "credentials"):
            if json.dumps(x.get(part), sort_keys=True) != json.dumps(y.get(part), sort_keys=True):
                out.append({"node": name, "what": part})
    if json.dumps(a.get("connections"), sort_keys=True) != json.dumps(b.get("connections"), sort_keys=True):
        out.append({"node": "(links)", "what": "connections"})
    return out


def to_neutral(wf: dict, *, wid: str = "", active: bool = True) -> dict:
    """An n8n workflow (the API's or an export) -> the neutral flow."""
    nodes = wf.get("nodes") or []
    kind_of = {"n8n-nodes-base.emailReadImap": "read_mail", "n8n-nodes-base.if": "decide", "n8n-nodes-base.splitInBatches": "loop", "n8n-nodes-base.code": "build",
               "n8n-nodes-base.microsoftTeams": "notify", "n8n-nodes-base.emailSend": "notify", "n8n-nodes-base.jira": "human", "n8n-nodes-base.ftp": "download",
               "n8n-nodes-base.microsoftExcel": "write", "n8n-nodes-base.readWriteFile": "read_file", "n8n-nodes-base.set": "build", "n8n-nodes-base.wait": "wait"}
    trig = next((n for n in nodes if n.get("type") in TRIGGERS), None)
    tk = {"n8n-nodes-base.emailReadImap": "email", "n8n-nodes-base.scheduleTrigger": "schedule", "n8n-nodes-base.webhook": "webhook", "n8n-nodes-base.formTrigger": "form"}.get((trig or {}).get("type"), "manual")
    detail = ""
    cron = ""
    if trig and tk == "schedule":
        try:
            cron = trig["parameters"]["rule"]["interval"][0].get("expression") or ""
        except (KeyError, IndexError, TypeError):
            cron = ""
        detail = cron
    elif trig and tk == "webhook":
        detail = (trig.get("parameters") or {}).get("path") or ""
    steps, creds = [], []
    for n in nodes:
        if n is trig:
            continue
        p = n.get("parameters") or {}
        url = str(p.get("url") or "")
        sysname = _w2_system(url) if n.get("type") == "n8n-nodes-base.httpRequest" else ("Jira" if n.get("type") == "n8n-nodes-base.jira" else "")
        api = f"{p.get('method') or 'GET'} {re.sub(r'^https?://[^/]+', '', url)}" if url else ""
        kind = kind_of.get(n.get("type"), "http")
        if kind == "http":
            low = n.get("name", "").lower()
            kind = ("upload" if "upload" in low else "extract" if "extract" in low else "lookup" if any(w in low for w in ("find", "look")) else "validate" if "validat" in low else
                    "fetch" if "fetch" in low else "export" if "export" in low else "type" if "type" in low else "post")
        body = p.get("jsonBody") if isinstance(p.get("jsonBody"), str) else None
        s = _w2.step(n.get("name") or kind, kind, system=sysname, api=api if kind not in ("notify", "human") else "", detail=str(p.get("path") or p.get("fileSelector") or "")[:120])
        if body:
            s["body"] = body
        steps.append(s)
        for ctype, ref in (n.get("credentials") or {}).items():
            creds.append((ref or {}).get("name") or ctype)
    return _w2.auto(wid or wf.get("id") or _w2.slug(wf.get("name")), wf.get("name") or "workflow", "n8n_api", active=active, trigger={"kind": tk, "detail": detail, "cron": cron},
                    steps=steps, credentials=creds, definition=wf, updated=wf.get("updatedAt"))


def _w2_system(url: str) -> str:
    return system_of(url)
