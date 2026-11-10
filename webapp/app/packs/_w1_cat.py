"""W1 — the data catalogues Data governance & catalogue reads (and, only after a person approves the change, writes):
Microsoft Purview (Data Map), Collibra (REST Core 2.0), Alation (Integration API), Atlan (metadata API); Unity Catalog
through the Databricks kind of _w1_sql. The mock lab's catalogue simulators stand in for each (tests/mocklab/sims/catalogs.py
and the Databricks workspace in cloudwh.py).

Every reader returns one neutral catalogue, so two catalogues — or a catalogue and Relay's own lineage — compare:
  assets  [{key, id, kind (database|schema|table|view|column|process|report), name, platform, parent, owner, description,
            classification (neutral: personal.email …), certified (Certified|Deprecated|None), rows, qualified, type}]
  edges   [{from, to, via}]            keys of assets (via: the process that moves the data, if any)
  terms   [{id, name, definition, status (Approved|Draft|Obsolete), steward}]
  scans   [{source, status (Succeeded|Failed|Running), start, end, error}]
Keys are platform:SCHEMA.TABLE[.COLUMN] (upper case), reports powerbi:<name>, processes <tool>:<name>.
"""
from __future__ import annotations

import re
import time

from .. import connectors
from . import _w1, _w1_sql
from ._w1 import Kind, cfg, secret

# ---------------------------------------------------------------- neutral vocabulary

CLASSES = {  # neutral classification -> how each catalogue names it
    "personal.email": {"purview": "MICROSOFT.PERSONAL.EMAIL", "collibra": "Email", "atlan": "PII", "alation": "MICROSOFT.PERSONAL.EMAIL"},
    "personal.name": {"purview": "MICROSOFT.PERSONAL.NAME", "collibra": "Name", "atlan": "PII", "alation": "MICROSOFT.PERSONAL.NAME"},
    "personal.phone": {"purview": "MICROSOFT.PERSONAL.PHONENUMBER", "collibra": "Phone", "atlan": "PII", "alation": "MICROSOFT.PERSONAL.PHONENUMBER"},
    "personal.address": {"purview": "MICROSOFT.PERSONAL.PHYSICALADDRESS", "collibra": "Address", "atlan": "PII", "alation": "MICROSOFT.PERSONAL.PHYSICALADDRESS"},
    "personal.birthdate": {"purview": "MICROSOFT.PERSONAL.DATEOFBIRTH", "collibra": "Date Of Birth", "atlan": "PII", "alation": "MICROSOFT.PERSONAL.DATEOFBIRTH"},
    "government.taxid": {"purview": "MICROSOFT.GOVERNMENT.INDIA.GSTIN", "collibra": "Gstin", "atlan": "PII", "alation": "MICROSOFT.GOVERNMENT.INDIA.GSTIN"},
    "financial.account": {"purview": "MICROSOFT.FINANCIAL.INTERNATIONAL_BANKING_ACCOUNT_NUMBER", "collibra": "Bank Account", "atlan": "PII", "alation": "MICROSOFT.FINANCIAL.IBAN"},
    "personal": {"purview": "MICROSOFT.PERSONAL.NAME", "collibra": "Personal", "atlan": "PII", "alation": "PII"},
}
CLASS_LABEL = {"personal.email": "Personal data: email", "personal.name": "Personal data: name", "personal.phone": "Personal data: phone number",
               "personal.address": "Personal data: address", "personal.birthdate": "Personal data: date of birth", "government.taxid": "Government id: tax number",
               "financial.account": "Financial: bank account", "personal": "Personal data"}


def neutral_class(v) -> str | None:
    """A catalogue's classification name -> the neutral one (None when it is not one Relay knows)."""
    if not v:
        return None
    s = str(v).upper()
    for k, by in CLASSES.items():                      # a label only one class uses (Atlan's PII is everyone's: it stays generic)
        if k != "personal" and s in {x.upper() for x in by.values()} and not any(s in {y.upper() for y in o.values()} for k2, o in CLASSES.items() if k2 != k):
            return k
    if "EMAIL" in s:
        return "personal.email"
    if "PHONE" in s:
        return "personal.phone"
    if "GSTIN" in s or "TAX" in s or "GOVERNMENT" in s:
        return "government.taxid"
    if "NAME" in s:
        return "personal.name"
    if "ADDRESS" in s:
        return "personal.address"
    if "BIRTH" in s:
        return "personal.birthdate"
    if "IBAN" in s or "BANK" in s or "ACCOUNT" in s:
        return "financial.account"
    if s in ("PII", "PERSONAL", "SENSITIVE"):
        return "personal"
    return None


def platform_of(text: str) -> str:
    t = (text or "").lower()
    for k, words in (("snowflake", ("snowflake",)), ("powerbi", ("powerbi", "power bi")), ("databricks", ("databricks", "unity")), ("ssis", ("ssis", "etl process")),
                     ("oracle", ("oracle", "ora01", "dwhprd")), ("sqlserver", ("mssql", "sqlserver", "sql server")), ("postgres", ("postgres",)),
                     ("bigquery", ("bigquery",)), ("glossary", ("glossary",))):
        if any(w in t for w in words):
            return k
    return "other"


def key(platform: str, *parts) -> str:
    return f"{platform}:" + ".".join(str(p).upper() for p in parts if p not in (None, ""))


def _path(q: str) -> list[str]:
    """oracle://host/DB/SCHEMA/TABLE[/COL] or snowflake://host/databases/DB/SCHEMA/TABLE -> [DB, SCHEMA, TABLE, COL?]."""
    rest = (q or "").split("://", 1)[-1]
    if rest.startswith("default/"):
        rest = rest[len("default/"):]
    parts = rest.split("/")[1:]
    if parts and parts[0] == "databases":
        parts = parts[1:]
    return [p for p in parts if p]


def asset(**kw) -> dict:
    base = {"key": "", "id": "", "kind": "", "name": "", "platform": "", "parent": None, "owner": None, "description": None, "classification": None,
            "certified": None, "rows": None, "qualified": "", "type": ""}
    base.update(kw)
    return base


def _from_qualified(kind: str, name: str, q: str, platform: str) -> tuple[str, str | None]:
    """(key, parent key) from a qualified name."""
    if kind in ("report", "process"):
        return key(platform, name), None
    p = _path(q)
    if kind == "column" and len(p) >= 4:
        return key(platform, p[-3], p[-2], p[-1]), key(platform, p[-3], p[-2])
    if kind in ("table", "view") and len(p) >= 3:
        return key(platform, p[-2], p[-1]), key(platform, p[-2])
    if kind == "schema" and len(p) >= 2:
        return key(platform, p[-1]), None
    if kind == "database":
        return key(platform, "DB:" + (p[-1] if p else name)), None
    return key(platform, name), None


def catalog(assets=None, edges=None, terms=None, scans=None, tool="") -> dict:
    return {"tool": tool, "assets": assets or [], "edges": edges or [], "terms": terms or [], "scans": scans or []}


# ================================================================== Microsoft Purview

PV = "2023-09-01"
PV_KIND = {"oracle_table": "table", "oracle_view": "view", "oracle_table_column": "column", "oracle_schema": "schema", "oracle_server": "database",
           "snowflake_table": "table", "snowflake_view": "view", "snowflake_column": "column", "snowflake_schema": "schema", "snowflake_database": "database",
           "ssis_package": "process", "powerbi_report": "report"}
PV_TYPE = {("oracle", "table"): "oracle_table", ("oracle", "view"): "oracle_view", ("oracle", "column"): "oracle_table_column",
           ("snowflake", "table"): "snowflake_table", ("snowflake", "view"): "snowflake_view", ("snowflake", "column"): "snowflake_column",
           ("ssis", "process"): "ssis_package", ("powerbi", "report"): "powerbi_report"}


class Purview(Kind):
    """Microsoft Purview Data Map: the discovery query, Atlas v2 entities, lineage, the glossary and the scanning API —
    signed in with an Entra ID app registration (client credentials, scope https://purview.azure.net/.default)."""
    kind, label, category = "purview", "Microsoft Purview", "governance"
    signin = ["service_account"]
    fields = [("base_url", "Purview account endpoint (https://<account>.purview.azure.com)", True), ("token_url", "Entra ID token endpoint (…/oauth2/v2.0/token)", True),
              ("client_id", "App registration (client) id", True)]
    secrets = {"service_account": ["client_secret"]}
    can_write = True
    simulator = "purview"

    def auth(self, c):
        def fetch():
            r = self.call(c, "POST", cfg(c, "token_url"), form={"grant_type": "client_credentials", "client_id": cfg(c, "client_id"), "client_secret": secret(c, "client_secret"),
                                                                "scope": "https://purview.azure.net/.default"}, auth=False)
            return r["access_token"], r.get("expires_in") or 3599
        return {"Authorization": "Bearer " + self.token(c, fetch)}

    def search(self, c, flt: dict | None = None) -> list[dict]:
        out, body = [], {"keywords": "*", "limit": 1000, **({"filter": flt} if flt else {})}
        while True:
            r = self.call(c, "POST", "/datamap/api/search/query", params={"api-version": PV}, json_body=body)
            out += r.get("value") or []
            if not r.get("continuationToken") or len(out) > 50000:
                return out
            body["continuationToken"] = r["continuationToken"]

    def entity(self, c, guid: str) -> dict:
        return (self.call(c, "GET", f"/datamap/api/atlas/v2/entity/guid/{guid}") or {}).get("entity") or {}

    def test(self, c):
        r = self.call(c, "POST", "/datamap/api/search/query", params={"api-version": PV}, json_body={"keywords": "*", "limit": 1})
        return {"ok": True, "sees": f"{r.get('@search.count', 0)} asset(s) in the Data Map"}

    def list_objects(self, c, search=""):
        return [{"object": h["qualifiedName"], "type": h.get("entityType")} for h in self.search(c) if search.lower() in (h.get("name") or "").lower()][:500]

    def read(self, c, obj, limit=100):
        rows = [{"name": h["name"], "type": h.get("entityType"), "qualifiedName": h["qualifiedName"]} for h in self.search(c) if obj.lower() in h["qualifiedName"].lower()][:limit]
        return {"columns": ["name", "type", "qualifiedName"], "rows": rows, "row_count": len(rows)}

    def catalog(self, c) -> dict:
        hits = self.search(c)
        assets, by_guid = [], {}
        for h in hits:
            kind = PV_KIND.get(h.get("entityType") or "") or (h.get("objectType") or "").lower().rstrip("s")
            if kind not in ("database", "schema", "table", "view", "column", "process", "report"):
                continue
            plat = "powerbi" if kind == "report" else "ssis" if kind == "process" else platform_of(h.get("entityType") or h.get("qualifiedName"))
            k, parent = _from_qualified(kind, h["name"], h["qualifiedName"], plat)
            a = asset(key=k, id=h["id"], kind=kind, name=h["name"], platform=plat, parent=parent, description=h.get("description"),
                      classification=neutral_class((h.get("classification") or [None])[0]), qualified=h["qualifiedName"], type=h.get("entityType") or "",
                      owner="(owner)" if h.get("contact") else None)
            assets.append(a)
            by_guid[h["id"]] = a
        edges = []
        for a in assets:                                       # owners' names, certificates and lineage: only the governed kinds
            if a["kind"] not in ("table", "view", "report", "process"):
                continue
            e = self.entity(c, a["id"])
            own = ((e.get("contacts") or {}).get("Owner") or [{}])[0]
            a["owner"] = own.get("info") or (own.get("id") if own else None) or None
            a["rows"] = (e.get("attributes") or {}).get("rowCount")
            if a["kind"] in ("table", "view"):
                lin = self.call(c, "GET", f"/datamap/api/atlas/v2/lineage/{a['id']}", params={"direction": "OUTPUT", "depth": 1}) or {}
                for r in lin.get("relations") or []:
                    x, y = by_guid.get(r["fromEntityId"]), by_guid.get(r["toEntityId"])
                    if x and y:
                        edges.append({"from": x["key"], "to": y["key"], "via": None})
        # a process in between (table -> process -> table) becomes one edge with its via
        procs = {a["key"] for a in assets if a["kind"] == "process"}
        flat = [e for e in edges if e["from"] not in procs and e["to"] not in procs]
        for e in edges:
            if e["to"] in procs:
                flat += [{"from": e["from"], "to": o["to"], "via": e["to"]} for o in edges if o["from"] == e["to"]] or [e]
        terms = []
        for g in self.call(c, "GET", "/datamap/api/atlas/v2/glossary") or []:
            off = 0
            while True:
                page = self.call(c, "GET", f"/datamap/api/atlas/v2/glossary/{g['guid']}/terms", params={"limit": 100, "offset": off}) or []
                for t in page:
                    stw = ((t.get("contacts") or {}).get("Steward") or [{}])[0]
                    terms.append({"id": t["guid"], "name": t["name"], "definition": t.get("longDescription") or "", "status": t.get("status") or "Draft",
                                  "steward": stw.get("info") or None, "glossary": g["guid"]})
                if len(page) < 100:
                    break
                off += 100
        scans = []
        for d in (self.call(c, "GET", "/scan/datasources") or {}).get("value") or []:
            try:
                names = [s["name"] for s in (self.call(c, "GET", f"/scan/datasources/{d['name']}/scans") or {}).get("value") or []]
            except connectors.ConnectorError:
                names = []
            for sc in names or [cfg(c, "scan") or "default"]:
                runs = (self.call(c, "GET", f"/scan/datasources/{d['name']}/scans/{sc}/runs") or {}).get("value") or []
                for r in runs[:30]:
                    scans.append({"source": d["name"], "scan": sc, "status": r.get("status"), "start": r.get("startTime"), "end": r.get("endTime"),
                                  "error": (r.get("error") or {}).get("message")})
        return catalog(assets, _dedupe(flat), terms, scans, "purview")

    def ops(self, changes: list[dict], cat: dict) -> list[dict]:
        """Neutral changes -> Purview calls."""
        by = {a["key"]: a for a in cat["assets"]}
        out = []
        for ch in changes:
            a = by.get(ch["object"])
            if not a:
                continue
            if ch["change"] == "classify":
                out.append({"method": "POST", "path": f"/datamap/api/atlas/v2/entity/guid/{a['id']}/classifications", "body": [{"typeName": CLASSES[ch["value"]]["purview"]}],
                            "what": f"classify {a['name']} as {CLASS_LABEL.get(ch['value'], ch['value'])}"})
            elif ch["change"] in ("owner", "describe"):
                ent = {"typeName": a["type"] or PV_TYPE.get((a["platform"], a["kind"]), "DataSet"), "attributes": {"qualifiedName": a["qualified"], "name": a["name"]}}
                if ch["change"] == "describe":
                    ent["attributes"]["description"] = ch["value"]
                else:
                    ent["contacts"] = {"Owner": [{"id": ch["value"], "info": ch["value"]}]}
                out.append({"method": "POST", "path": "/datamap/api/atlas/v2/entity", "body": {"entity": ent},
                            "what": f"{'describe' if ch['change'] == 'describe' else 'set the owner of'} {a['name']}" + (f" to {ch['value']}" if ch["change"] == "owner" else "")})
            elif ch["change"] == "rescan":
                out.append({"method": "PUT", "path": f"/scan/datasources/{a['name']}/scans/{ch.get('scan') or 'default'}/run", "params": {"runId": ch.get("run_id") or _w1.slug(str(time.time()))},
                            "what": f"run the scan of {a['name']} again"})
        return out

    def _write(self, c, obj, payload, approval):
        if payload.get("ops"):
            done = []
            for op in payload["ops"]:
                self.call(c, op["method"], op["path"], json_body=op.get("body"), params={**({"api-version": PV} if "/search/" in op["path"] else {}), **(op.get("params") or {})},
                          approval=approval)
                done.append(op.get("what") or op["path"])
            return {"ok": True, "done": done}
        return super()._write(c, obj, payload, approval)


def _dedupe(edges: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in edges:
        k = (e["from"], e["to"], e.get("via"))
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


# ================================================================== Collibra

CB_TYPE = {"table": "00000000-0000-0000-0000-000000031007", "column": "00000000-0000-0000-0000-000000031008", "view": "00000000-0000-0000-0000-000000031009",
           "process": "00000000-0000-0000-0000-000000031301", "report": "00000000-0000-0000-0000-000000031101", "term": "00000000-0000-0000-0000-000000011001"}
CB_ATTR = {"Description": "00000000-0000-0000-0000-000000003114", "Personal Data Classification": "00000000-0000-0000-0000-000000003117"}
CB_STATUS = {"Accepted": "00000000-0000-0000-0000-000000005009", "Obsolete": "00000000-0000-0000-0000-000000005010", "Candidate": "00000000-0000-0000-0000-000000005008"}
PERSONAL_RX = re.compile(r"(?i)^(E?MAIL|EMAIL_ADDRESS|PHONE|PHONE_NO|MOBILE|FULL_NAME|FIRST_NAME|LAST_NAME|SURNAME|NAME|CONTACT_NAME|DOB|DATE_OF_BIRTH|BIRTH_DATE|"
                         r"ADDRESS|ADDRESS_LINE\d?|STREET|POSTCODE|POST_CODE|ZIP|GSTIN|PAN|SSN|NI_NUMBER|NATIONAL_ID|PASSPORT|IBAN|ACCOUNT_NUMBER|IP_ADDRESS)$")


class Collibra(Kind):
    """Collibra Data Intelligence Platform — REST Core API 2.0 (a service user, basic auth)."""
    kind, label, category = "collibra", "Collibra", "governance"
    signin = ["password"]
    fields = [("base_url", "REST API (https://<instance>.collibra.com/rest/2.0)", True), ("user", "Service user", True)]
    secrets = {"password": ["password"]}
    can_write = True
    simulator = "collibra"

    def auth(self, c):
        return self.basic(cfg(c, "user"), secret(c, "password"))

    def paged(self, c, path: str, params: dict | None = None) -> list[dict]:
        out, off = [], 0
        while True:
            r = self.call(c, "GET", path, params={**(params or {}), "offset": off, "limit": 1000}) or {}
            res = r.get("results") or []
            out += res
            off += len(res)
            if not res or off >= int(r.get("total") or 0) or len(out) > 50000:
                return out

    def test(self, c):
        r = self.call(c, "GET", "/assets", params={"limit": 1})
        return {"ok": True, "sees": f"{r.get('total', 0)} asset(s)"}

    def list_objects(self, c, search=""):
        return [{"object": a["name"], "type": a["type"]["name"]} for a in self.paged(c, "/assets", {"typeId": CB_TYPE["table"]}) if search.lower() in a["name"].lower()]

    def read(self, c, obj, limit=100):
        rows = [{"name": a["name"], "type": a["type"]["name"], "domain": a["domain"]["name"], "status": a["status"]["name"]} for a in self.paged(c, "/assets", {"name": obj})][:limit]
        return {"columns": ["name", "type", "domain", "status"], "rows": rows, "row_count": len(rows)}

    def attributes(self, c, aid: str) -> dict:
        return {x["type"]["name"]: x.get("value") for x in (self.call(c, "GET", "/attributes", params={"assetId": aid}) or {}).get("results") or []}

    def catalog(self, c) -> dict:
        owners = {r["baseResource"]["id"]: (r.get("owner") or {}).get("id") for r in self.paged(c, "/responsibilities")}
        assets, terms, by_id = [], [], {}
        for kind in ("table", "view", "column", "process", "report", "term"):
            for x in self.paged(c, "/assets", {"typeId": CB_TYPE[kind]}):
                dom = x["domain"]["name"]
                st = x["status"]["name"]
                if kind == "term":
                    at = self.attributes(c, x["id"])
                    terms.append({"id": x["id"], "name": x["name"], "definition": at.get("Description") or "", "status": {"Accepted": "Approved", "Obsolete": "Obsolete"}.get(st, "Draft"),
                                  "steward": owners.get(x["id"])})
                    continue
                plat = "powerbi" if kind == "report" else "ssis" if kind == "process" else platform_of(dom)
                a = asset(key=key(plat, x["name"]), id=x["id"], kind=kind, name=x["name"], platform=plat, owner=owners.get(x["id"]),
                          certified={"Accepted": "Certified", "Obsolete": "Deprecated"}.get(st), qualified=f"{dom}/{x['name']}", type=x["type"]["name"], domain=x["domain"]["id"])
                if kind != "column" or PERSONAL_RX.match(x["name"]):
                    at = self.attributes(c, x["id"])
                    a["description"] = at.get("Description")
                    a["rows"] = at.get("Row Count")
                    a["classification"] = neutral_class(at.get("Personal Data Classification"))
                if kind == "column":                           # Collibra keeps columns by name in the domain: one asset per column name
                    a["key"] = key(plat, "?", x["name"]) + f"#{x['id'][:8]}"
                assets.append(a)
                by_id[x["id"]] = a
        edges = []
        for r in self.paged(c, "/relations"):
            x, y = by_id.get(r["source"]["id"]), by_id.get(r["target"]["id"])
            if x and y:
                edges.append({"from": x["key"], "to": y["key"], "via": None})
        procs = {a["key"] for a in assets if a["kind"] == "process"}
        flat = [e for e in edges if e["from"] not in procs and e["to"] not in procs]
        for e in edges:
            if e["to"] in procs:
                flat += [{"from": e["from"], "to": o["to"], "via": e["to"]} for o in edges if o["from"] == e["to"]] or [e]
        scans = [{"source": "Collibra Edge", "scan": j.get("name"), "status": "Succeeded" if j.get("result") == "SUCCESS" else "Failed" if j.get("state") == "COMPLETED" else "Running",
                  "start": j.get("startDate"), "end": j.get("endDate"), "error": j.get("message")} for j in (self.call(c, "GET", "/jobs") or {}).get("results") or []]
        return catalog(assets, _dedupe(flat), terms, scans, "collibra")

    def ops(self, changes: list[dict], cat: dict) -> list[dict]:
        by = {a["key"]: a for a in cat["assets"]}
        terms = {t["name"].lower(): t for t in cat["terms"]}
        out = []
        for ch in changes:
            a = by.get(ch["object"])
            if ch["change"] == "describe" and a:
                out.append({"method": "POST", "path": "/attributes", "body": {"assetId": a["id"], "typeId": CB_ATTR["Description"], "value": ch["value"]}, "what": f"describe {a['name']}"})
            elif ch["change"] == "classify" and a:
                out.append({"method": "POST", "path": "/attributes", "body": {"assetId": a["id"], "typeId": CB_ATTR["Personal Data Classification"], "value": CLASSES[ch["value"]]["collibra"]},
                            "what": f"classify {a['name']} as {CLASS_LABEL.get(ch['value'], ch['value'])}"})
            elif ch["change"] == "deprecate" and a:
                out.append({"method": "PATCH", "path": f"/assets/{a['id']}", "body": {"statusId": CB_STATUS["Obsolete"]}, "what": f"mark {a['name']} Obsolete"})
            elif ch["change"] in ("define", "term"):
                t = terms.get(str(ch.get("name") or ch["object"]).lower())
                if t:
                    out.append({"method": "POST", "path": "/attributes", "body": {"assetId": t["id"], "typeId": CB_ATTR["Description"], "value": ch["value"]}, "what": f"define the term {t['name']}"})
                else:
                    out.append({"op": "create_term", "name": ch.get("name") or ch["object"], "definition": ch["value"], "what": f"add the term {ch.get('name') or ch['object']}"})
            elif ch["change"] == "retire_term":
                t = terms.get(str(ch.get("name") or ch["object"]).lower())
                if t:
                    out.append({"method": "PATCH", "path": f"/assets/{t['id']}", "body": {"statusId": CB_STATUS["Obsolete"]}, "what": f"mark the term {t['name']} Obsolete (a duplicate)"})
        return out

    def _write(self, c, obj, payload, approval):
        if payload.get("ops"):
            done = []
            glossary = None
            for op in payload["ops"]:
                if op.get("op") == "create_term":
                    if glossary is None:
                        glossary = next((d["id"] for d in (self.call(c, "GET", "/domains") or {}).get("results") or [] if (d.get("type") or {}).get("name") == "Glossary"), None)
                    if not glossary:
                        raise connectors.ConnectorError("Collibra has no glossary domain to add the term to")
                    t = self.call(c, "POST", "/assets", json_body={"name": op["name"], "domainId": glossary, "typeId": CB_TYPE["term"]}, approval=approval)
                    self.call(c, "POST", "/attributes", json_body={"assetId": t["id"], "typeId": CB_ATTR["Description"], "value": op["definition"]}, approval=approval)
                else:
                    self.call(c, op["method"], op["path"], json_body=op.get("body"), approval=approval)
                done.append(op.get("what") or op.get("path"))
            return {"ok": True, "done": done}
        return super()._write(c, obj, payload, approval)


# ================================================================== Alation

class Alation(Kind):
    """Alation Data Catalog — Integration API v1 / v2 (a refresh token exchanged for an API access token, TOKEN header)."""
    kind, label, category = "alation", "Alation", "governance"
    signin = ["api_key"]
    fields = [("base_url", "Alation address (https://<instance>.alationcloud.com)", True), ("user_id", "User id the refresh token belongs to", True)]
    secrets = {"api_key": ["refresh_token"]}
    can_write = True
    simulator = "alation"

    def auth(self, c):
        def fetch():
            r = self.call(c, "POST", "/integration/v1/createAPIAccessToken/", json_body={"refresh_token": secret(c, "refresh_token"), "user_id": int(cfg(c, "user_id") or 0)}, auth=False)
            return r["api_access_token"], 3600
        return {"TOKEN": self.token(c, fetch)}

    def paged(self, c, path: str, params: dict | None = None) -> list[dict]:
        out, url, p = [], path, {**(params or {}), "limit": 500, "skip": 0}
        while url and len(out) < 50000:
            r = self.call(c, "GET", url, params=p, raw=True)
            out += r.json() or []
            nxt = r.headers.get("X-Next-Page")
            url, p = (nxt, None) if nxt else (None, None)
        return out

    def datasources(self, c) -> list[dict]:
        return self.call(c, "GET", "/integration/v1/datasource/") or []

    def test(self, c):
        return {"ok": True, "sees": f"{len(self.datasources(c))} data source(s)"}

    def list_objects(self, c, search=""):
        return [{"object": t["key"], "type": t.get("table_type", "TABLE").lower()} for t in self.paged(c, "/integration/v2/table/") if search.lower() in t["name"].lower()]

    def read(self, c, obj, limit=100):
        rows = [{"key": t["key"], "name": t["name"], "description": t.get("description")} for t in self.paged(c, "/integration/v2/table/") if obj.lower() in t["key"]][:limit]
        return {"columns": ["key", "name", "description"], "rows": rows, "row_count": len(rows)}

    def catalog(self, c) -> dict:
        ds = {d["id"]: platform_of(d.get("dbtype") or d.get("title")) for d in self.datasources(c)}
        assets, by_id, by_akey = [], {}, {}
        for t in self.paged(c, "/integration/v2/table/"):
            plat = ds.get(t.get("ds_id"), "other")
            cf = {f["field_name"]: f.get("value") for f in t.get("custom_fields") or []}
            stew = cf.get("Steward") or []
            kind = "view" if t.get("table_type") == "VIEW" else "table"
            a = asset(key=key(plat, t["schema_name"], t["name"]), id=str(t["id"]), kind=kind, name=t["name"].upper(), platform=plat, parent=key(plat, t["schema_name"]),
                      owner=(stew[0].get("name") if stew and isinstance(stew[0], dict) else None), description=t.get("description") or None,
                      certified=cf.get("Status") or None, qualified=t["key"], type=t.get("table_type") or "TABLE")
            assets.append(a)
            by_id[t["id"]] = a
            by_akey[t["key"]] = a
        for col in self.paged(c, "/integration/v2/column/"):
            tab = by_id.get(col.get("table_id"))
            if not tab:
                continue
            cf = {f["field_name"]: f.get("value") for f in col.get("custom_fields") or []}
            assets.append(asset(key=tab["key"] + "." + col["name"].upper(), id=str(col["id"]), kind="column", name=col["name"].upper(), platform=tab["platform"], parent=tab["key"],
                                classification=neutral_class(cf.get("PII")), qualified=tab["qualified"] + "." + col["name"].lower(), type=col.get("column_type") or ""))
        edges = []
        for a in [x for x in assets if x["kind"] in ("table", "view")]:
            try:
                lin = self.call(c, "GET", "/integration/v2/lineage/", params={"otype": "table", "key": a["qualified"]}) or {}
            except connectors.ConnectorError:
                continue
            for t in lin.get("target") or []:
                b = by_akey.get(t.get("key"))
                edges.append({"from": a["key"], "to": b["key"] if b else key("powerbi" if t.get("otype") == "bi_report" else "other", t.get("key")), "via": None})
        terms = []
        for t in self.paged(c, "/integration/v2/term/"):
            cf = {f["field_name"]: f.get("value") for f in t.get("custom_fields") or []}
            terms.append({"id": str(t["id"]), "name": t["title"], "definition": t.get("description") or "", "status": cf.get("Status") or "Draft", "steward": cf.get("Steward") or None})
        return catalog(assets, _dedupe(edges), terms, [], "alation")

    def ops(self, changes: list[dict], cat: dict) -> list[dict]:
        by = {a["key"]: a for a in cat["assets"]}
        desc = [{"key": by[ch["object"]]["qualified"], "description": ch["value"]} for ch in changes if ch["change"] == "describe" and ch["object"] in by and by[ch["object"]]["kind"] in ("table", "view")]
        out = [{"op": "describe", "items": desc, "what": f"describe {len(desc)} table(s)"}] if desc else []
        for ch in changes:
            if ch["change"] == "lineage":
                out.append({"method": "POST", "path": "/integration/v2/lineage/", "body": {"source": [{"otype": "table", "key": ch["source"]}], "target": [{"otype": "table", "key": ch["target"]}],
                                                                                           "dataflow_objects": [{"otype": "dataflow", "key": ch.get("via") or "relay." + _w1.slug(ch["target"])}]},
                            "what": f"lineage {ch['source']} → {ch['target']}"})
        return out

    def _write(self, c, obj, payload, approval):
        if payload.get("ops"):
            done = []
            for op in payload["ops"]:
                if op.get("op") == "describe":
                    j = self.call(c, "PUT", "/integration/v2/table/", json_body=op["items"], approval=approval)
                    for _ in range(20):                         # the bulk update runs as a job
                        st = self.call(c, "GET", "/api/v1/bulk_metadata/job/", params={"id": j.get("job_id")})
                        if st.get("status") in ("successful", "failed"):
                            break
                        time.sleep(0.2)
                else:
                    self.call(c, op["method"], op["path"], json_body=op.get("body"), approval=approval)
                done.append(op.get("what"))
            return {"ok": True, "done": done}
        return super()._write(c, obj, payload, approval)


# ================================================================== Atlan

AT_KIND = {"Table": "table", "View": "view", "Column": "column", "Process": "process", "PowerBIReport": "report", "Schema": "schema", "Database": "database"}


class Atlan(Kind):
    """Atlan — the metadata API (Elasticsearch-DSL index search, entity bulk upsert, lineage list) and workflow runs, with
    a bearer API token."""
    kind, label, category = "atlan", "Atlan", "governance"
    signin = ["api_key"]
    fields = [("base_url", "Atlan tenant (https://<tenant>.atlan.com)", True)]
    secrets = {"api_key": ["api_token"]}
    can_write = True
    simulator = "atlan"

    def auth(self, c):
        return {"Authorization": "Bearer " + secret(c, "api_token")}

    def search(self, c, type_name: str) -> list[dict]:
        out, frm = [], 0
        while True:
            r = self.call(c, "POST", "/api/meta/search/indexsearch", json_body={"dsl": {"from": frm, "size": 300, "query": {"bool": {"must": [{"term": {"__typeName.keyword": type_name}},
                                                                                                                                                 {"term": {"__state": "ACTIVE"}}]}}},
                                                                                "attributes": ["name", "qualifiedName", "ownerGroups", "ownerUsers", "certificateStatus", "description"]}) or {}
            ents = r.get("entities") or []
            out += ents
            frm += len(ents)
            if not ents or frm >= int(r.get("approximateCount") or 0) or len(out) > 50000:
                return out

    def test(self, c):
        r = self.call(c, "POST", "/api/meta/search/indexsearch", json_body={"dsl": {"from": 0, "size": 1, "query": {"bool": {"must": [{"term": {"__state": "ACTIVE"}}]}}}})
        return {"ok": True, "sees": f"{r.get('approximateCount', 0)} asset(s)"}

    def list_objects(self, c, search=""):
        return [{"object": e["attributes"]["qualifiedName"], "type": "table"} for e in self.search(c, "Table") if search.lower() in e["attributes"]["name"].lower()]

    def read(self, c, obj, limit=100):
        rows = [{"name": e["attributes"]["name"], "qualifiedName": e["attributes"]["qualifiedName"]} for e in self.search(c, "Table") if obj.lower() in e["attributes"]["qualifiedName"].lower()][:limit]
        return {"columns": ["name", "qualifiedName"], "rows": rows, "row_count": len(rows)}

    def catalog(self, c) -> dict:
        assets, terms = [], []
        for tn, kind in AT_KIND.items():
            for e in self.search(c, tn):
                at = e.get("attributes") or {}
                q = at.get("qualifiedName") or ""
                plat = "powerbi" if kind == "report" else "ssis" if kind == "process" else platform_of(q)
                k, parent = _from_qualified(kind, at.get("name") or "", q, plat)
                owner = (at.get("ownerUsers") or []) + (at.get("ownerGroups") or [])
                assets.append(asset(key=k, id=e["guid"], kind=kind, name=at.get("name") or "", platform=plat, parent=parent, owner=owner[0] if owner else None,
                                    description=at.get("description"), classification=neutral_class((e.get("classificationNames") or [None])[0]),
                                    certified={"VERIFIED": "Certified", "DEPRECATED": "Deprecated"}.get(at.get("certificateStatus") or ""), qualified=q, type=tn))
        for e in self.search(c, "AtlasGlossaryTerm"):
            at = e.get("attributes") or {}
            terms.append({"id": e["guid"], "name": at.get("name"), "definition": at.get("description") or "", "status": {"VERIFIED": "Approved", "DEPRECATED": "Obsolete"}.get(at.get("certificateStatus") or "", "Draft"),
                          "steward": ((at.get("ownerUsers") or []) + (at.get("ownerGroups") or []) or [None])[0]})
        by = {a["id"]: a for a in assets}
        edges = []
        for a in [x for x in assets if x["kind"] in ("table", "view")]:
            r = self.call(c, "POST", "/api/meta/lineage/list", json_body={"guid": a["id"], "direction": "DOWNSTREAM", "depth": 1, "size": 50}) or {}
            for e in r.get("entities") or []:
                b = by.get(e["guid"])
                if b and b["kind"] != "process":
                    edges.append({"from": a["key"], "to": b["key"], "via": None})
        runs = ((self.call(c, "POST", "/api/service/runs/indexsearch", json_body={"from": 0, "size": 100}) or {}).get("hits") or {}).get("hits") or []
        scans = [{"source": ((h["_source"].get("metadata") or {}).get("labels") or {}).get("workflows.argoproj.io/workflow-template") or h["_id"], "scan": h["_id"],
                  "status": (h["_source"].get("status") or {}).get("phase"), "start": (h["_source"].get("status") or {}).get("startedAt"),
                  "end": (h["_source"].get("status") or {}).get("finishedAt"), "error": (h["_source"].get("status") or {}).get("message")} for h in runs]
        return catalog(assets, _dedupe(edges), terms, scans, "atlan")

    def ops(self, changes: list[dict], cat: dict) -> list[dict]:
        by = {a["key"]: a for a in cat["assets"]}
        ents, what = [], []
        for ch in changes:
            a = by.get(ch["object"])
            if not a:
                if ch["change"] in ("define", "term"):
                    ents.append({"typeName": "AtlasGlossaryTerm", "attributes": {"qualifiedName": "relay/" + _w1.slug(ch.get("name") or ch["object"]), "name": ch.get("name") or ch["object"],
                                                                                "description": ch["value"]}})
                    what.append(f"add the term {ch.get('name') or ch['object']}")
                continue
            attrs = {"qualifiedName": a["qualified"], "name": a["name"]}
            if ch["change"] == "describe":
                attrs["description"] = ch["value"]
            elif ch["change"] == "owner":
                attrs["ownerGroups"] = [ch["value"].lower().replace(" ", "_")]
            elif ch["change"] == "certify":
                attrs["certificateStatus"] = {"Certified": "VERIFIED", "Deprecated": "DEPRECATED"}.get(ch["value"], ch["value"])
            elif ch["change"] == "classify":
                attrs["description"] = a.get("description")
            ent = {"typeName": a["type"] or "Table", "attributes": attrs}
            if ch["change"] == "classify":
                ent["classificationNames"] = [CLASSES[ch["value"]]["atlan"]]
            ents.append(ent)
            what.append(f"{ch['change']} {a['name']}")
        return [{"method": "POST", "path": "/api/meta/entity/bulk", "body": {"entities": ents[i:i + 50]}, "what": "; ".join(what[i:i + 50])} for i in range(0, len(ents), 50)]

    def _write(self, c, obj, payload, approval):
        if payload.get("ops"):
            for op in payload["ops"]:
                self.call(c, op["method"], op["path"], json_body=op.get("body"), approval=approval)
            return {"ok": True, "done": [op.get("what") for op in payload["ops"]]}
        return super()._write(c, obj, payload, approval)


# ================================================================== Unity Catalog (the Databricks kind)

def unity(c) -> dict:
    a = _w1_sql.DATABRICKS
    assets = []
    for t in a.uc_tables(c):
        k = key("databricks", t["schema_name"], t["name"])
        props = t.get("properties") or {}
        assets.append(asset(key=k, id=t.get("table_id") or t["full_name"], kind="view" if t.get("table_type") == "VIEW" else "table", name=t["name"].upper(), platform="databricks",
                            parent=key("databricks", t["schema_name"]), owner=t.get("owner") or None, description=t.get("comment") or None,
                            certified=props.get("certified") or ("Deprecated" if "deprecated" in str(props).lower() else None), qualified=t["full_name"], type=t.get("table_type") or ""))
        for col in t.get("columns") or []:
            assets.append(asset(key=k + "." + col["name"].upper(), id=f"{t['full_name']}.{col['name']}", kind="column", name=col["name"].upper(), platform="databricks", parent=k,
                                description=col.get("comment"), classification=neutral_class((col.get("tags") or {}).get("class") if isinstance(col.get("tags"), dict) else None),
                                qualified=f"{t['full_name']}.{col['name']}", type=col.get("type_name") or ""))
    return catalog(assets, [], [], [], "unity")


def unity_ops(changes: list[dict], cat: dict) -> list[dict]:
    by = {a["key"]: a for a in cat["assets"]}
    out = []
    for ch in changes:
        a = by.get(ch["object"])
        if a and a["kind"] in ("table", "view") and ch["change"] in ("owner", "describe"):
            out.append({"method": "PATCH", "path": f"/api/2.1/unity-catalog/tables/{a['qualified']}", "body": {"owner" if ch["change"] == "owner" else "comment": ch["value"]},
                        "what": f"{'set the owner of' if ch['change'] == 'owner' else 'describe'} {a['qualified']}"})
    return out


PURVIEW = _w1.register(Purview())
COLLIBRA = _w1.register(Collibra())
ALATION = _w1.register(Alation())
ATLAN = _w1.register(Atlan())
CATALOG_KINDS = ("purview", "collibra", "alation", "atlan", "databricks_sql")


def read(c: dict) -> dict:
    """The neutral catalogue of one connection."""
    if c["kind"] == "databricks_sql":
        return unity(c)
    a = connectors.sdk.get(c["kind"])
    if not hasattr(a, "catalog"):
        raise connectors.ConnectorError(f"{c['name']} is not a catalogue Relay reads")
    return a.catalog(c)


def ops(c: dict, changes: list[dict], cat: dict) -> list[dict]:
    if c["kind"] == "databricks_sql":
        return unity_ops(changes, cat)
    return connectors.sdk.get(c["kind"]).ops(changes, cat)
