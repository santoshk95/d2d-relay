"""Cloud & CI/CD adapters (W3, registry id `ship`).

CI / CD — pipelines (the canonical `pipeline`) and their runs:
  Azure DevOps     Build REST 7.1: a personal access token as basic auth; definitions, builds paged with the
                   x-ms-continuationtoken header, a failed build's timeline issues; a build queued after approval.
  GitHub Actions   REST 2022-11-28: a fine-grained token; workflows, runs paged by Link rel="next", a failed run's job
                   log (a 302 to a short-lived URL, followed without the token); a failed run re-run after approval.
  GitLab CI        REST v4: PRIVATE-TOKEN; pipelines paged by X-Next-Page, a failed pipeline's failed jobs and their
                   traces; a pipeline created on the branch after approval.
Cloud — what is deployed (the canonical `deployment`), each in the cloud's own terms:
  Azure            Resource Manager deployments (Entra client credentials for management.azure.com, nextLink paging),
                   the latest per app with its error details.
  AWS              CloudFormation stacks (the Query API signed with SigV4), the failed resource from the stack events.
  Google Cloud     Cloud Run services (a service-account JWT grant), the last ready revision and its image; after
                   approval a service is rolled back to that image (PATCH, a long-running operation).

Mock lab stand-ins (tests/mocklab/sims/devops.py, cloud.py): azure_devops, github_actions, gitlab, azure_arm,
aws_cloudformation, gcp_cloud_run.
"""
from __future__ import annotations

import base64
import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

from .. import connectors
from ._systems import SysAdapter, register, when
from ._w1 import sign_v4

IMAGE = re.compile(r"^[a-z0-9.-]+(:\d+)?(/[a-z0-9._-]+)+(:[\w.-]+|@sha256:[0-9a-f]{64})$")


def _st(v: str) -> str:
    v = str(v or "").lower()
    return ("succeeded" if v in ("succeeded", "success", "completed", "complete") else "failed" if v in ("failed", "failure", "error", "canceled", "cancelled")
            else "running" if v in ("inprogress", "in_progress", "running", "pending", "queued", "notstarted", "waiting_for_resource", "created") else v or "unknown")


# ================================================================== CI / CD

class AzureDevOps(SysAdapter):
    kind, label, category = "azure_devops", "Azure DevOps", "cicd"
    simulator = "azure_devops"
    docs = "https://learn.microsoft.com/en-us/rest/api/azure/devops/build/builds?view=azure-devops-rest-7.1"
    signin = ["api_key"]
    fields = [("base_url", "Organisation URL (https://dev.azure.com/<org>)", True), ("project", "Project", True)]
    secrets = {"api_key": ["pat"]}
    ENTITIES = {"pipeline": ("definitions", "Build pipelines (definitions)")}
    JOBS = "Builds"
    V = {"api-version": "7.1"}

    def sign_in(self, api):
        return {"Authorization": "Basic " + base64.b64encode((":" + api.secret("pat")).encode()).decode(), "Accept": "application/json"}

    def expired(self, r):
        return r.status_code in (203, 401)            # an expired PAT answers with the sign-in page

    def _p(self, api, path: str) -> str:
        return f"/{quote(api.cfg.get('project') or '')}/_apis/{path}"

    def _builds(self, api) -> list[dict]:
        if "builds" in api.state:
            return api.state["builds"]
        out, tok = [], None
        for _ in range(200):
            r = api.request("GET", self._p(api, "build/builds"), params={**self.V, "$top": 200, **({"continuationToken": tok} if tok else {})})
            out += self.check(r, "builds").get("value") or []
            tok = r.headers.get("x-ms-continuationtoken")
            if not tok:
                break
        api.state["builds"] = out
        return out

    def _issues(self, api, bid) -> str:
        tl = api.get(self._p(api, f"build/builds/{bid}/timeline"), self.V)
        msgs = [i.get("message") for rec in tl.get("records") or [] if rec.get("result") == "failed" for i in rec.get("issues") or [] if i.get("type") == "error"]
        return "; ".join(m for m in msgs if m) or "the build failed (no error issue on its timeline)"

    def fetch(self, api, entity):
        if entity == "pipeline":
            defs = api.get(self._p(api, "build/definitions"), self.V).get("value") or []
            last = {}
            for b in self._builds(api):
                d = (b.get("definition") or {}).get("id")
                if d not in last or (b.get("queueTime") or "") > (last[d].get("queueTime") or ""):
                    last[d] = b
            return [{**d, "_last": last.get(d["id"])} for d in defs]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "pipeline":
            b = r.get("_last") or {}
            return {"key": str(r["id"]), "name": r.get("name"), "repository": r.get("path"), "last_status": _st(b.get("result") or b.get("status")) if b else None,
                    "last_run": b.get("finishTime") or b.get("startTime"), "platform": "Azure DevOps"}
        return r

    def runs(self, api):
        bs = sorted(self._builds(api), key=lambda b: b.get("queueTime") or "", reverse=True)
        out, read = [], {}
        for b in bs:
            name = (b.get("definition") or {}).get("name")
            st = _st(b.get("result") or b.get("status"))
            err = None
            if st == "failed":
                read[name] = read.get(name, 0) + 1
                err = self._issues(api, b["id"]) if read[name] <= 2 else "the build failed"
            out.append({"job": name, "label": name, "id": str(b["id"]), "started": when(b.get("startTime") or b.get("queueTime")), "ended": when(b.get("finishTime")), "status": st, "error": err})
        return out

    def op_rerun(self, api, job, run_id, approval):
        d = next((x for x in api.get(self._p(api, "build/definitions"), self.V).get("value") or [] if x.get("name") == job), None)
        if not d:
            raise connectors.ConnectorError(f"Azure DevOps: no pipeline called {job}")
        b = self.check(api.request("POST", self._p(api, "build/builds"), params=self.V, json={"definition": {"id": d["id"]}, "sourceBranch": "refs/heads/main"},
                                   headers={"Content-Type": "application/json"}, approval=approval), "queue a build")
        return {"id": str(b.get("id")), "job": job}

    def op_status(self, api, ref):
        b = api.get(self._p(api, f"build/builds/{ref.get('id')}"), self.V)
        st = _st(b.get("result") or b.get("status"))
        return {"status": st, "error": self._issues(api, ref.get("id")) if st == "failed" else None}


class GitHubActions(SysAdapter):
    kind, label, category = "github_actions", "GitHub Actions", "cicd"
    simulator = "github_actions"
    docs = "https://docs.github.com/en/rest/actions/workflow-runs"
    signin = ["api_key"]
    fields = [("base_url", "API (https://api.github.com)", True), ("owner", "Owner (organisation or user)", True), ("repo", "Repository", True)]
    secrets = {"api_key": ["token"]}
    ENTITIES = {"pipeline": ("workflows", "Workflows")}
    JOBS = "Workflow runs"

    def sign_in(self, api):
        return {"Authorization": "Bearer " + api.secret("token"), "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def throttled(self, r):
        return r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0"

    def retry_after(self, r):
        v = r.headers.get("retry-after")
        return float(v) if v and v.isdigit() else None

    def _r(self, api) -> str:
        return f"/repos/{api.cfg.get('owner')}/{api.cfg.get('repo')}/actions"

    def _runs(self, api) -> list[dict]:
        if "runs" in api.state:
            return api.state["runs"]
        out, url, p = [], f"{self._r(api)}/runs", {"per_page": 100}
        for _ in range(100):
            r = api.request("GET", url, params=p)
            out += self.check(r, "workflow runs").get("workflow_runs") or []
            m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
            if not m:
                break
            url, p = m.group(1), None
        api.state["runs"] = out
        return out

    def _log(self, api, rid) -> str:
        jobs = api.get(f"{self._r(api)}/runs/{rid}/jobs").get("jobs") or []
        bad = next((j for j in jobs if j.get("conclusion") == "failure"), None)
        if not bad:
            return "the run failed"
        r = api.request("GET", f"{self._r(api)}/jobs/{bad['id']}/logs")
        if r.status_code in (301, 302, 303, 307) and r.headers.get("Location"):
            r = api.raw("GET", r.headers["Location"])          # a short-lived URL: no token goes with it
        lines = [re.sub(r"^\S+Z\s+", "", x) for x in (r.text or "").splitlines()]
        hits = [x for x in lines if re.search(r"error", x, re.I) and "exit code" not in x]
        return "; ".join(hits[:3]) or f"{bad.get('name')} failed"

    def fetch(self, api, entity):
        if entity == "pipeline":
            wfs = api.get(f"{self._r(api)}/workflows", {"per_page": 100}).get("workflows") or []
            runs = self._runs(api)
            return [{**w, "_last": next((r for r in runs if r.get("workflow_id") == w["id"]), None)} for w in wfs]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "pipeline":
            b = r.get("_last") or {}
            return {"key": str(r["id"]), "name": r.get("name"), "repository": r.get("path"), "last_status": _st(b.get("conclusion") or b.get("status")) if b else None,
                    "last_run": b.get("updated_at"), "platform": "GitHub Actions"}
        return r

    def runs(self, api):
        out, read = [], {}
        for r in sorted(self._runs(api), key=lambda x: x.get("run_started_at") or x.get("created_at") or "", reverse=True):
            st = _st(r.get("conclusion") or r.get("status"))
            err = None
            if st == "failed":
                read[r["name"]] = read.get(r["name"], 0) + 1
                err = self._log(api, r["id"]) if read[r["name"]] <= 2 else "the run failed"
            out.append({"job": r.get("name"), "label": r.get("name"), "id": str(r["id"]), "started": when(r.get("run_started_at") or r.get("created_at")), "ended": when(r.get("updated_at")),
                        "status": st, "error": err})
        return out

    def op_rerun(self, api, job, run_id, approval):
        rid = run_id or next((str(r["id"]) for r in self._runs(api) if r.get("name") == job), "")
        if not rid:
            raise connectors.ConnectorError(f"GitHub Actions: no run of {job} to run again")
        self.check(api.request("POST", f"{self._r(api)}/runs/{rid}/rerun", approval=approval), "re-run", ok=(201, 204))
        return {"id": rid, "job": job, "after": time.time() - 5}

    def op_status(self, api, ref):
        rs = api.get(f"{self._r(api)}/runs", {"per_page": 20}).get("workflow_runs") or []
        r = next((x for x in rs if x.get("name") == ref.get("job") and str(x["id"]) != str(ref.get("id")) and x.get("event") in ("rerun", "workflow_dispatch")), None)
        if not r:
            return {"status": "queued", "error": None}
        st = _st(r.get("conclusion") or r.get("status"))
        return {"status": st, "error": self._log(api, r["id"]) if st == "failed" else None}


class GitLabCI(SysAdapter):
    kind, label, category = "gitlab_ci", "GitLab CI", "cicd"
    simulator = "gitlab"
    docs = "https://docs.gitlab.com/ee/api/pipelines.html"
    signin = ["api_key"]
    fields = [("base_url", "GitLab (https://gitlab.com)", True), ("project", "Project (id or group/name)", True)]
    secrets = {"api_key": ["token"]}
    ENTITIES = {"pipeline": ("pipelines", "Pipelines (by branch: the default branch, merge requests)")}
    JOBS = "Pipelines"

    def sign_in(self, api):
        return {"PRIVATE-TOKEN": api.secret("token"), "Accept": "application/json"}

    def _p(self, api) -> str:
        return f"/api/v4/projects/{quote(str(api.cfg.get('project') or ''), safe='')}"

    def _name(self, api) -> str:
        return str(api.cfg.get("project") or "").rsplit("/", 1)[-1]

    def _pipes(self, api) -> list[dict]:
        if "pipes" in api.state:
            return api.state["pipes"]
        out, page = [], "1"
        for _ in range(200):
            r = api.request("GET", f"{self._p(api)}/pipelines", params={"per_page": 100, "page": page})
            out += self.check(r, "pipelines") or []
            page = r.headers.get("X-Next-Page") or ""
            if not page:
                break
        api.state["pipes"] = out
        return out

    def _job(self, api, p) -> str:
        return f"{self._name(api)} · {p.get('ref')}" if p.get("source") != "merge_request_event" else f"{self._name(api)} · merge requests"

    def _trace(self, api, pid) -> str:
        jobs = api.get(f"{self._p(api)}/pipelines/{pid}/jobs", {"scope[]": "failed"}) or []
        out = []
        for j in jobs[:2]:
            r = api.request("GET", f"{self._p(api)}/jobs/{j['id']}/trace")
            hits = [x for x in (r.text or "").splitlines() if re.search(r"error", x, re.I) and "Job failed" not in x]
            out.append(f"{j.get('name')}: " + ("; ".join(hits[:2]) or str(j.get("failure_reason") or "failed")))
        return "; ".join(out) or "the pipeline failed"

    def fetch(self, api, entity):
        if entity == "pipeline":
            last = {}
            for p in self._pipes(api):
                last.setdefault(self._job(api, p), p)
            return [{"_name": k, **p} for k, p in last.items()]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "pipeline":
            return {"key": r["_name"], "name": r["_name"], "repository": str(r.get("web_url") or "").split("/-/")[0], "last_status": _st(r.get("status")), "last_run": r.get("updated_at"),
                    "platform": "GitLab CI"}
        return r

    def runs(self, api):
        out, read = [], {}
        for p in sorted(self._pipes(api), key=lambda x: x.get("created_at") or "", reverse=True):
            job = self._job(api, p)
            st = _st(p.get("status"))
            err = None
            if st == "failed":
                read[job] = read.get(job, 0) + 1
                err = self._trace(api, p["id"]) if read[job] <= 2 else "the pipeline failed"
            out.append({"job": job, "label": job, "id": str(p["id"]), "started": when(p.get("created_at")), "ended": when(p.get("updated_at")), "status": st, "error": err, "ref": p.get("ref")})
        return out

    def op_rerun(self, api, job, run_id, approval):
        ref = job.split(" · ", 1)[-1]
        if ref == "merge requests":
            raise connectors.ConnectorError("GitLab: a merge request's pipeline is run again from the merge request")
        p = self.check(api.request("POST", f"{self._p(api)}/pipeline", params={"ref": ref}, approval=approval), "create a pipeline", ok=(201,))
        return {"id": str(p.get("id")), "job": job}

    def op_status(self, api, ref):
        api.state.pop("pipes", None)
        p = next((x for x in self._pipes(api) if str(x["id"]) == str(ref.get("id"))), None)
        if not p:
            return {"status": "unknown", "error": None}
        st = _st(p.get("status"))
        return {"status": st, "error": self._trace(api, p["id"]) if st == "failed" else None}


# ================================================================== Cloud

class AzureResourceManager(SysAdapter):
    kind, label, category = "azure_arm", "Microsoft Azure (Resource Manager)", "cloud"
    simulator = "azure_arm"
    docs = "https://learn.microsoft.com/en-us/rest/api/resources/deployments"
    signin = ["service_account"]
    fields = [("base_url", "Resource Manager (https://management.azure.com)", True), ("tenant", "Entra tenant id", True), ("client_id", "App (client) id", True),
              ("subscription", "Subscription id", True), ("resource_group", "Resource group", True), ("authority", "Sign-in endpoint (optional: a national cloud)", False)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"deployment": ("deployments", "Template deployments (the latest per app)")}
    API = {"api-version": "2021-04-01"}

    def sign_in(self, api):
        auth = (api.cfg.get("authority") or "https://login.microsoftonline.com").rstrip("/")
        r = api.raw("POST", f"{auth}/{api.cfg.get('tenant')}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": api.cfg.get("client_id"),
                                                                                       "client_secret": api.secret("client_secret"), "scope": "https://management.azure.com/.default"})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Entra ID refused the app's sign-in: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def error_text(self, r):
        try:
            e = r.json().get("error")
            if isinstance(e, dict):
                return f"{e.get('code')}: {e.get('message')}"
        except (ValueError, AttributeError):
            pass
        return super().error_text(r)

    def _deps(self, api) -> list[dict]:
        url, p, out = f"/subscriptions/{api.cfg.get('subscription')}/resourcegroups/{api.cfg.get('resource_group')}/providers/Microsoft.Resources/deployments", {**self.API, "$top": 100}, []
        for _ in range(500):
            b = api.get(url, p)
            out += b.get("value") or []
            if not b.get("nextLink"):
                return out
            url, p = b["nextLink"], None
        return out

    @staticmethod
    def app_of(name: str) -> str:
        return re.sub(r"-\d{8}(-\d+)?$", "", str(name))

    def fetch(self, api, entity):
        if entity == "deployment":
            latest = {}
            for d in self._deps(api):
                app = self.app_of(d["name"])
                if app not in latest or (d["properties"].get("timestamp") or "") > (latest[app]["properties"].get("timestamp") or ""):
                    latest[app] = d
            return list(latest.values())
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "deployment":
            p = r.get("properties") or {}
            err = p.get("error") or {}
            det = "; ".join(f"{x.get('code')}: {x.get('message')}" for x in err.get("details") or []) or (f"{err.get('code')}: {err.get('message')}" if err else "")
            return {"key": r["name"], "name": self.app_of(r["name"]), "environment": f"resource group {r['id'].split('/resourcegroups/')[-1].split('/')[0]}" if "/resourcegroups/" in r.get("id", "") else "",
                    "status": _st(p.get("provisioningState")), "when": p.get("timestamp"), "error": det or None, "platform": "Azure", "kind": "ARM deployment", "image": None, "rollback_image": None}
        return r


CFN_NS = {"c": "http://cloudformation.amazonaws.com/doc/2010-05-15/"}


class AwsCloudFormation(SysAdapter):
    kind, label, category = "aws_cloudformation", "AWS (CloudFormation)", "cloud"
    simulator = "aws_cloudformation"
    docs = "https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/"
    signin = ["api_key"]
    fields = [("base_url", "Endpoint (https://cloudformation.<region>.amazonaws.com)", True), ("region", "Region", True), ("access_key_id", "Access key id", True)]
    secrets = {"api_key": ["secret_access_key", "session_token"]}
    ENTITIES = {"deployment": ("stacks", "CloudFormation stacks")}

    def expired(self, r):
        return r.status_code == 403 and b"ExpiredToken" in (r.content or b"")

    def throttled(self, r):
        return r.status_code == 400 and b"<Code>Throttling</Code>" in (r.content or b"")

    def error_text(self, r):
        m = re.search(r"<Code>([^<]+)</Code>.*?<Message>([^<]*)</Message>", r.text or "", re.S)
        return f"{m.group(1)}: {m.group(2)}" if m else super().error_text(r)

    def check(self, r, what, ok=(200,)):
        if r.status_code == 403:
            raise connectors.Reconsent(f"AWS refused the signed request: {self.error_text(r)}")
        if r.status_code not in ok:
            raise connectors.ConnectorError(f"{self.label} · {what}: {r.status_code} {self.error_text(r)}")
        return r.text

    def _call(self, api, action: str, **params) -> ET.Element:
        body = urlencode({"Action": action, "Version": "2010-05-15", **params}).encode()
        tok = connectors._secret(api.c, "session_token") or None
        url = api.url("/")
        for attempt in range(5):
            h = sign_v4("POST", url, api.cfg.get("region") or "us-east-1", "cloudformation", api.cfg.get("access_key_id") or "", api.secret("secret_access_key"), body,
                        {"content-type": "application/x-www-form-urlencoded; charset=utf-8"}, tok)
            r = api.request("POST", "/", content=body, headers=h, signed=False)
            if not self.throttled(r):
                break
            time.sleep(min(4, 0.5 * 2 ** attempt))
        return ET.fromstring(self.check(r, action))

    def _stacks(self, api) -> list[dict]:
        out, tok = [], None
        for _ in range(100):
            x = self._call(api, "DescribeStacks", **({"NextToken": tok} if tok else {}))
            for m in x.iterfind(".//c:Stacks/c:member", CFN_NS):
                out.append({"name": m.findtext("c:StackName", "", CFN_NS), "id": m.findtext("c:StackId", "", CFN_NS), "status": m.findtext("c:StackStatus", "", CFN_NS),
                            "updated": m.findtext("c:LastUpdatedTime", "", CFN_NS) or m.findtext("c:CreationTime", "", CFN_NS),
                            "env": next((p.findtext("c:ParameterValue", "", CFN_NS) for p in m.iterfind("c:Parameters/c:member", CFN_NS) if p.findtext("c:ParameterKey", "", CFN_NS) == "Environment"), "")})
            tok = x.findtext(".//c:NextToken", None, CFN_NS)
            if not tok:
                return out
        return out

    def _failure(self, api, stack: str) -> str:
        """The first resource that failed in the stack's last operation (DescribeStackEvents, newest first, paged)."""
        tok, evs = None, []
        for _ in range(20):
            x = self._call(api, "DescribeStackEvents", StackName=stack, **({"NextToken": tok} if tok else {}))
            for m in x.iterfind(".//c:StackEvents/c:member", CFN_NS):
                evs.append((m.findtext("c:ResourceStatus", "", CFN_NS), m.findtext("c:LogicalResourceId", "", CFN_NS), m.findtext("c:ResourceStatusReason", "", CFN_NS)))
            if any(s.endswith("_IN_PROGRESS") and lid == stack and reason == "User Initiated" for s, lid, reason in evs):
                break
            tok = x.findtext(".//c:NextToken", None, CFN_NS)
            if not tok:
                break
        bad = [f"{lid}: {reason}" for s, lid, reason in evs if s.endswith("_FAILED") and lid != stack]
        return bad[-1] if bad else "the stack's last update was rolled back"

    def fetch(self, api, entity):
        if entity == "deployment":
            out = []
            for s in self._stacks(api):
                if re.search(r"ROLLBACK|FAILED", s["status"]):
                    s["error"] = self._failure(api, s["name"])
                out.append(s)
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "deployment":
            s = r["status"]
            st = "running" if s.endswith("_IN_PROGRESS") else "failed" if "FAILED" in s or ("ROLLBACK" in s and s.startswith(("ROLLBACK", "CREATE"))) else "rolled back" if "ROLLBACK" in s else "succeeded"
            return {"key": r["name"], "name": r["name"], "environment": r.get("env") or "", "status": st, "when": r.get("updated"), "error": r.get("error"), "platform": "AWS",
                    "kind": "CloudFormation stack", "state": s, "image": None, "rollback_image": None}
        return r


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def google_sign_in(adapter, api, scope: str) -> dict:
    """A Google service account's JWT bearer grant (RS256, the key from the JSON key file) for one or more scopes."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        sa = json.loads(api.secret("service_account_json"))
        key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    except (ValueError, KeyError, TypeError) as e:
        raise connectors.Reconsent("The service account key could not be read: paste the JSON key file Google gave you.") from e
    now = int(time.time())
    head = _b64u(json.dumps({"alg": "RS256", "typ": "JWT", "kid": sa.get("private_key_id")}, separators=(",", ":")).encode())
    body = _b64u(json.dumps({"iss": sa["client_email"], "scope": scope, "aud": sa["token_uri"], "iat": now, "exp": now + 3600, "kid": sa.get("private_key_id")},
                            separators=(",", ":")).encode())
    sig = _b64u(key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()))
    r = api.raw("POST", sa["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": f"{head}.{body}.{sig}"})
    if r.status_code != 200:
        raise connectors.Reconsent(f"Google refused the service account: {adapter.error_text(r)}")
    return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}


class GcpCloudRun(SysAdapter):
    kind, label, category = "gcp_cloud_run", "Google Cloud (Cloud Run)", "cloud"
    simulator = "gcp_cloud_run"
    docs = "https://cloud.google.com/run/docs/reference/rest"
    signin = ["service_account"]
    fields = [("base_url", "Cloud Run Admin API (https://run.googleapis.com)", True), ("project", "Project id", True), ("location", "Region (e.g. europe-west2)", True)]
    secrets = {"service_account": ["service_account_json"]}
    ENTITIES = {"deployment": ("services", "Cloud Run services")}
    WRITABLE = {"deployment": {"image": "template.containers[0].image"}}

    def sign_in(self, api):
        return google_sign_in(self, api, "https://www.googleapis.com/auth/cloud-platform")

    def _loc(self, api) -> str:
        return f"/v2/projects/{api.cfg.get('project')}/locations/{api.cfg.get('location')}"

    def _all(self, api, path, key) -> list[dict]:
        out, tok = [], None
        for _ in range(200):
            b = api.get(path, {"pageSize": 100, **({"pageToken": tok} if tok else {})})
            out += b.get(key) or []
            tok = b.get("nextPageToken")
            if not tok:
                return out
        return out

    def fetch(self, api, entity):
        if entity == "deployment":
            out = []
            for s in self._all(api, f"{self._loc(api)}/services", "services"):
                tc = s.get("terminalCondition") or {}
                if tc.get("state") == "CONDITION_FAILED":
                    short = s["name"].rsplit("/", 1)[-1]
                    revs = {r["name"]: r for r in self._all(api, f"{self._loc(api)}/services/{short}/revisions", "revisions")}
                    ready = revs.get(s.get("latestReadyRevision") or "") or {}
                    s["_rollback"] = ((ready.get("containers") or [{}])[0]).get("image")
                    s["_ready"] = (s.get("latestReadyRevision") or "").rsplit("/", 1)[-1]
                out.append(s)
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "deployment":
            tc = r.get("terminalCondition") or {}
            img = ((r.get("template") or {}).get("containers") or [{}])[0].get("image")
            st = "running" if r.get("reconciling") else "failed" if tc.get("state") == "CONDITION_FAILED" else "succeeded"
            return {"key": r["name"].rsplit("/", 1)[-1], "name": r["name"].rsplit("/", 1)[-1], "environment": f"{r['name'].split('/')[1]} · {r['name'].split('/')[3]}",
                    "status": st, "when": r.get("updateTime"), "error": tc.get("message") if st == "failed" else None, "platform": "Google Cloud", "kind": "Cloud Run service",
                    "image": img, "rollback_image": r.get("_rollback"), "serving": r.get("_ready")}
        return r

    def field_problems(self, entity, field, value):
        if field == "image" and not IMAGE.match(str(value or "")):
            return [f"{value!r} is not a container image reference (registry/path:tag)"]
        return []

    def op_update(self, api, entity, key, changes, approval):
        if set(changes) - {"image"}:
            raise connectors.ConnectorError("Relay changes only the container image of a Cloud Run service")
        if self.field_problems(entity, "image", changes["image"]):
            raise connectors.ConnectorError(self.field_problems(entity, "image", changes["image"])[0])
        op = api.json("PATCH", f"{self._loc(api)}/services/{key}", json={"template": {"containers": [{"image": changes["image"]}]}}, headers={"Content-Type": "application/json"},
                      approval=approval, what=f"service {key}")
        name = op.get("name") or ""
        for _ in range(10):                                   # the long-running operation, polled until done
            if op.get("done"):
                break
            time.sleep(0.2)
            op = api.get(f"/v2/{name}")
        if op.get("error"):
            raise connectors.ConnectorError(f"Cloud Run: {op['error'].get('message')}")
        return {"id": key, "operation": name.rsplit("/", 1)[-1], "done": bool(op.get("done"))}


ADAPTERS = [register(a) for a in (AzureDevOps(), GitHubActions(), GitLabCI(), AzureResourceManager(), AwsCloudFormation(), GcpCloudRun())]
CI_KINDS = ("azure_devops", "github_actions", "gitlab_ci")
CLOUD_KINDS = ("azure_arm", "aws_cloudformation", "gcp_cloud_run")
