"""Test plans & UAT scripts — the test managers a plan's cases are written to: Jira Xray (Cloud), Zephyr Scale (Cloud)
and TestRail. One Connector SDK adapter each, read-only by default like every connection: `test` signs in and counts
the project's cases, `read` lists them. A write happens only through connectors.request_write, after a named person
accepted exactly those cases, and carries the approval's id (X-Relay-Approval); the keys come back to the work item
(_w4.push_written) and the cases are read back from the tool and compared — title and steps, case by case.

  cases   payload {"from", "plan", "cases": [{"ref", "title", "req", "type", "priority", "preconditions", "steps": [...], "data", "expected"}]}
          Xray        POST /api/v2/import/test/bulk (the test importer), then the job's status for the keys
          Zephyr      POST /v2/testcases, then POST /v2/testcases/{key}/teststeps (OVERWRITE)
          TestRail    POST add_section/{project} (one section per push), then add_case/{section} with separated steps
"""
from __future__ import annotations

import base64
import re
import time

from .. import connectors
from .. import connectors_sdk as sdk
from . import _w4
from .brd_trackers import _call, _secret

KINDS = ("xray_cloud", "zephyr_scale", "testrail")
LABEL_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _label(s: str) -> str:
    return LABEL_RE.sub("-", str(s or "")).strip("-")[:60]


class _Manager(sdk.Adapter):
    category = "code"
    can_write = True

    def _base(self, c: dict) -> str:
        return (c["config"].get("base_url") or self.DEFAULT).rstrip("/")

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        if obj != "cases":
            raise sdk.ScopeError(f"{self.label}: Relay writes test cases, not {obj!r}")
        try:
            out = self.create(c, payload, approval)
        except Exception as e:
            _w4.push_written(approval, {"error": str(e)[:400]}, ok=False)
            raise
        _w4.push_written(approval, out, ok=True)
        return out


# ------------------------------------------------------------------ Jira Xray (Cloud)

class XrayCloud(_Manager):
    kind, label = "xray_cloud", "Jira Xray (Cloud)"
    DEFAULT = "https://xray.cloud.getxray.app"
    signin = ["api_key"]
    fields = [("base_url", "Xray API (https://xray.cloud.getxray.app, or eu.xray.cloud.getxray.app)", False), ("project_key", "Jira project key (LK)", True),
              ("client_id", "API key client id (Xray › API keys)", True)]
    secrets = {"api_key": ["client_secret"]}

    def _h(self, c: dict) -> dict:
        tok = _call("Xray", "POST", self._base(c) + "/api/v2/authenticate", json={"client_id": c["config"].get("client_id"), "client_secret": _secret(c, "client_secret")}).json()
        return {"Authorization": f"Bearer {tok}"}

    def _gql(self, c: dict, h: dict, q: str) -> dict:
        d = _call("Xray", "POST", self._base(c) + "/api/v2/graphql", headers=h, json={"query": q}).json()
        if d.get("errors"):
            raise connectors.ConnectorError("Xray: " + "; ".join(e.get("message", "") for e in d["errors"])[:300])
        return d["data"]

    def cases(self, c: dict) -> list[dict]:
        h, out, start = self._h(c), [], 0
        key = c["config"].get("project_key")
        for _ in range(100):
            r = self._gql(c, h, f'{{ getTests(jql: "project = {key}", limit: 100, start: {start}) {{ total start limit results {{ issueId jira(fields: ["key", "summary", "labels"]) '
                                f'steps {{ action data result }} }} }} }}')["getTests"]
            out += [{"key": x["jira"]["key"], "title": x["jira"].get("summary"), "steps": [s.get("action") for s in x.get("steps") or []], "labels": x["jira"].get("labels") or []}
                    for x in r["results"]]
            start += 100
            if start >= r["total"]:
                break
        return out

    def test(self, c: dict) -> dict:
        r = self._gql(c, self._h(c), f'{{ getTests(jql: "project = {c["config"].get("project_key")}", limit: 1) {{ total }} }}')
        return {"ok": True, "sees": f"{r['getTests']['total']} test(s) in {c['config'].get('project_key')}", "scope": c.get("scope")}

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        rows = [{"key": x["key"], "title": x["title"], "steps": len(x["steps"])} for x in self.cases(c)[:limit]]
        return {"columns": ["key", "title", "steps"], "rows": rows, "row_count": len(rows)}

    def create(self, c: dict, payload: dict, approval: str) -> dict:
        h = {**self._h(c), "X-Relay-Approval": approval}
        key = c["config"].get("project_key")
        cases = payload.get("cases") or []
        body = []
        for x in cases:
            st = x.get("steps") or [""]
            body.append({"testtype": "Manual", "fields": {"summary": x["title"][:255], "project": {"key": key},
                                                          "description": "\n".join(p for p in (x.get("preconditions") and f"Preconditions: {x['preconditions']}", f"Requirement: {x.get('req')}") if p),
                                                          "labels": [lb for lb in ("relay", _label(x["ref"]), _label(x.get("req"))) if lb]},
                         "steps": [{"action": s or x["title"], "data": x.get("data") or "" if i == 0 else "", "result": x.get("expected") or "" if i == len(st) - 1 else ""} for i, s in enumerate(st)]})
        job = _call("Xray", "POST", self._base(c) + "/api/v2/import/test/bulk", headers=h, json=body).json()["jobId"]
        st = {}
        for i in range(60):
            st = _call("Xray", "GET", self._base(c) + f"/api/v2/import/test/bulk/{job}/status", headers=h).json()
            if st.get("status") not in ("pending", "working"):
                break
            time.sleep(min(1.0, 0.1 * (i + 1)))
        res = st.get("result") or {}
        created = [{"ref": cases[x["elementNumber"]]["ref"], "key": x["key"], "id": x.get("id")} for x in res.get("issues") or []]
        errors = [{"ref": cases[e["elementNumber"]]["ref"], "error": "; ".join(f"{k}: {v}" for k, v in (e.get("errors") or {}).items())} for e in res.get("errors") or []]
        return {"ok": not errors, "created": created, "errors": errors, "where": f"Jira project {key}", "job": job}


# ------------------------------------------------------------------ Zephyr Scale (Cloud)

class ZephyrScale(_Manager):
    kind, label = "zephyr_scale", "Zephyr Scale (Cloud)"
    DEFAULT = "https://api.zephyrscale.smartbear.com"
    signin = ["api_key"]
    fields = [("base_url", "API (https://api.zephyrscale.smartbear.com, or the EU address)", False), ("project_key", "Jira project key (LK)", True)]
    secrets = {"api_key": ["token"]}
    PRIORITY = {"must": "High", "should": "Normal", "could": "Low", "wont": "Low"}

    def _h(self, c: dict) -> dict:
        return {"Authorization": f"Bearer {_secret(c, 'token')}"}

    def _pages(self, c: dict, h: dict, url: str) -> list[dict]:
        out = []
        for _ in range(200):
            d = _call("Zephyr Scale", "GET", url, headers=h).json()
            out += d.get("values") or []
            if d.get("isLast", True) or not d.get("next"):
                break
            url = d["next"]
        return out

    def cases(self, c: dict, keys: set | None = None) -> list[dict]:
        h = self._h(c)
        rows = self._pages(c, h, self._base(c) + f"/v2/testcases?projectKey={c['config'].get('project_key')}&maxResults=100")
        out = []
        for x in rows:
            if keys is not None and x["key"] not in keys:
                continue
            st = self._pages(c, h, self._base(c) + f"/v2/testcases/{x['key']}/teststeps?maxResults=100") if keys is not None else []
            out.append({"key": x["key"], "title": x.get("name"), "steps": [((s.get("inline") or {}).get("description")) for s in st], "labels": x.get("labels") or []})
        return out

    def test(self, c: dict) -> dict:
        d = _call("Zephyr Scale", "GET", self._base(c) + f"/v2/testcases?projectKey={c['config'].get('project_key')}&maxResults=1", headers=self._h(c)).json()
        return {"ok": True, "sees": f"{d.get('total')} test case(s) in {c['config'].get('project_key')}", "scope": c.get("scope")}

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        rows = [{"key": x["key"], "title": x["title"]} for x in self.cases(c)[:limit]]
        return {"columns": ["key", "title"], "rows": rows, "row_count": len(rows)}

    def create(self, c: dict, payload: dict, approval: str) -> dict:
        h = {**self._h(c), "X-Relay-Approval": approval}
        key = c["config"].get("project_key")
        created, errors = [], []
        for x in payload.get("cases") or []:
            try:
                r = _call("Zephyr Scale", "POST", self._base(c) + "/v2/testcases", headers=h, ok=(201,),
                          json={"projectKey": key, "name": x["title"][:255], "precondition": x.get("preconditions") or "", "priorityName": self.PRIORITY.get(x.get("priority"), "Normal"),
                                "labels": [lb for lb in ("relay", _label(x["ref"]), _label(x.get("req"))) if lb], "objective": f"Requirement: {x.get('req')}"}).json()
                st = x.get("steps") or [""]
                _call("Zephyr Scale", "POST", self._base(c) + f"/v2/testcases/{r['key']}/teststeps", headers=h, ok=(201,),
                      json={"mode": "OVERWRITE", "items": [{"inline": {"description": s or x["title"], "testData": x.get("data") or "" if i == 0 else "",
                                                                       "expectedResult": x.get("expected") or "" if i == len(st) - 1 else ""}} for i, s in enumerate(st)]})
                created.append({"ref": x["ref"], "key": r["key"], "id": str(r.get("id"))})
            except connectors.Reconsent:
                raise
            except connectors.ConnectorError as e:
                errors.append({"ref": x["ref"], "error": str(e)[:300]})
        return {"ok": not errors, "created": created, "errors": errors, "where": f"Zephyr Scale project {key}"}


# ------------------------------------------------------------------ TestRail

class TestRail(_Manager):
    kind, label = "testrail", "TestRail"
    DEFAULT = ""
    signin = ["api_key"]
    fields = [("base_url", "TestRail address (https://<you>.testrail.io)", True), ("user", "User (the e-mail you sign in with)", True), ("project_id", "Project id", True),
              ("suite_id", "Suite id (single-suite projects: leave empty)", False)]
    secrets = {"api_key": ["api_key"]}
    TYPE = {"boundary": 6, "negative": 6, "regression": 9, "positive": 1}            # Functional, Regression, Acceptance
    PRIORITY = {"must": 4, "should": 3, "could": 2, "wont": 1}                      # Critical, High, Medium, Low

    def _h(self, c: dict) -> dict:
        return {"Authorization": "Basic " + base64.b64encode(f"{c['config'].get('user')}:{_secret(c, 'api_key')}".encode()).decode(), "Content-Type": "application/json"}

    def _api(self, c: dict, path: str) -> str:
        return f"{self._base(c)}/index.php?/api/v2/{path}"

    def cases(self, c: dict, sections: set | None = None) -> list[dict]:
        h, out = self._h(c), []
        url = self._api(c, f"get_cases/{c['config'].get('project_id')}&limit=250")
        for _ in range(200):
            d = _call("TestRail", "GET", url, headers=h).json()
            out += [{"key": f"C{x['id']}", "title": x.get("title"), "steps": [s.get("content") for s in x.get("custom_steps_separated") or []], "section": x.get("section_id")}
                    for x in d.get("cases") or [] if sections is None or x.get("section_id") in sections]
            nxt = (d.get("_links") or {}).get("next")
            if not nxt:
                break
            url = f"{self._base(c)}/index.php?{nxt}"
        return out

    def test(self, c: dict) -> dict:
        d = _call("TestRail", "GET", self._api(c, f"get_cases/{c['config'].get('project_id')}&limit=1"), headers=self._h(c)).json()
        return {"ok": True, "sees": f"project {c['config'].get('project_id')}: cases readable ({d.get('size', 0)} on the first page)", "scope": c.get("scope")}

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        rows = [{"key": x["key"], "title": x["title"], "steps": len(x["steps"])} for x in self.cases(c)[:limit]]
        return {"columns": ["key", "title", "steps"], "rows": rows, "row_count": len(rows)}

    def create(self, c: dict, payload: dict, approval: str) -> dict:
        h = {**self._h(c), "X-Relay-Approval": approval}
        body = {"name": f"Relay — {payload.get('plan') or 'test plan'}"[:250], "description": "Written by Relay after an approval"}
        if c["config"].get("suite_id"):
            body["suite_id"] = int(c["config"]["suite_id"])
        sec = _call("TestRail", "POST", self._api(c, f"add_section/{c['config'].get('project_id')}"), headers=h, json=body).json()
        created, errors = [], []
        for x in payload.get("cases") or []:
            st = x.get("steps") or [""]
            try:
                r = _call("TestRail", "POST", self._api(c, f"add_case/{sec['id']}"), headers=h,
                          json={"title": x["title"][:250], "type_id": self.TYPE.get(x.get("type"), 1), "priority_id": self.PRIORITY.get(x.get("priority"), 2), "refs": x.get("req") or "",
                                "custom_preconds": x.get("preconditions") or "",
                                "custom_steps_separated": [{"content": s or x["title"], "expected": x.get("expected") or "" if i == len(st) - 1 else "",
                                                            "additional_info": x.get("data") or "" if i == 0 else ""} for i, s in enumerate(st)]}).json()
                created.append({"ref": x["ref"], "key": f"C{r['id']}", "id": str(r["id"])})
            except connectors.Reconsent:
                raise
            except connectors.ConnectorError as e:
                errors.append({"ref": x["ref"], "error": str(e)[:300]})
        return {"ok": not errors, "created": created, "errors": errors, "where": f"TestRail section “{sec.get('name')}”", "section": sec.get("id")}


ADAPTERS = {a.kind: a for a in (XrayCloud(), ZephyrScale(), TestRail())}
for _a in ADAPTERS.values():
    sdk.register(_a)
    _d = _a.describe()
    connectors.KINDS[_a.kind] = {"label": _d["label"], "dialect": None, "auth": list(_d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in _d["fields"]],
                                 "secrets": _d["secrets"], "category": _d["category"], "sdk": True}


def read_back(c: dict, created: list[dict], result: dict) -> dict:
    """The written cases as the tool holds them now: {key: {"title", "steps"}}."""
    a = ADAPTERS[c["kind"]]
    keys = {x["key"] for x in created}
    if c["kind"] == "zephyr_scale":
        rows = a.cases(c, keys)
    elif c["kind"] == "testrail":
        rows = a.cases(c, {result.get("section")} if result.get("section") else None)
    else:
        rows = a.cases(c)
    return {x["key"]: x for x in rows if x["key"] in keys}
