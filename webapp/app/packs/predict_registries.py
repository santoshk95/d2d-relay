"""Model registries and endpoints as deployment targets (the AI wave: Predictive analytics registers its forecast
models; AI governance inventories them): Azure Machine Learning, Amazon SageMaker and Google Vertex AI - one Connector
SDK adapter each (connectors_sdk), registered here at import with its connectors.KINDS entry, so no shared file changes.

Read-only by default like every connection: models, their versions and the online endpoints are listed and read. A
registration (a new model version carrying the method, its parameters and its back-tested accuracy) is written only
through connectors.request_write, after a named person accepted exactly that payload; the approval's id travels with
the call (header X-Relay-Approval). Endpoints are overridable per connection (sovereign clouds, private endpoints),
which is also how the mock lab's simulators stand in for the clouds (tests/mocklab/sims/ai.py: azure_ml, sagemaker, vertex_ai).

Sign-in: Azure ML - an Entra ID app (client credentials) for Azure Resource Manager; SageMaker - AWS access keys
(boto3 signs every call with Signature Version 4); Vertex AI - a Google service account (a JWT-bearer grant signed with
its private key)."""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import quote

import httpx

from .. import connectors, secrets_store
from .. import connectors_sdk as sdk
from .. import workbench as wb

APPROVAL_HEADER = "X-Relay-Approval"
TIMEOUT = 30
ARM = "https://management.azure.com"
LOGIN = "https://login.microsoftonline.com"
AML_API = "2024-04-01"


def _secret(c: dict, name: str) -> str | None:
    return secrets_store.get(f"user:{c['owner_id']}", f"conn:{c['id']}:{name}")


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code in (401, 403):
        raise connectors.Reconsent(f"{what}: the sign-in was refused ({r.status_code}). Renew the connection's secret or its permissions.")
    if r.status_code == 429:
        raise connectors.ConnectorError(f"{what}: the registry asked Relay to slow down (429); try again shortly.")
    if r.status_code >= 400:
        raise connectors.ConnectorError(f"{what}: {r.status_code} {r.text[:200]}")
    return r.json() if r.content else {}


def payload_lines(p: dict) -> list[str]:
    return [f"Model: {p.get('name')} - version {p.get('version')}", f"Method: {p.get('method')}", f"Back-tested accuracy: {p.get('accuracy')}",
            f"Description: {p.get('description')}"]


# ------------------------------------------------------------------ Azure Machine Learning (Azure Resource Manager)

class AzureML(sdk.Adapter):
    kind, label, category = "azureml", "Azure Machine Learning", "code"
    signin = ["service_account"]
    fields = [("tenant_id", "Entra tenant id", True), ("client_id", "App (client) id", True), ("subscription_id", "Subscription id", True),
              ("resource_group", "Resource group", True), ("workspace", "Workspace name", True),
              ("arm_url", "Resource Manager URL (optional; a sovereign cloud or private endpoint)", False), ("login_url", "Sign-in URL (optional)", False)]
    secrets = {"service_account": ["client_secret"]}
    can_write = True

    def _token(self, c: dict) -> str:
        cfg = c["config"]
        secret = _secret(c, "client_secret")
        if not secret:
            raise connectors.Reconsent("No client secret is stored for this connection.")
        url = f"{(cfg.get('login_url') or LOGIN).rstrip('/')}/{cfg['tenant_id']}/oauth2/v2.0/token"
        try:
            r = httpx.post(url, data={"grant_type": "client_credentials", "client_id": cfg["client_id"], "client_secret": secret, "scope": f"{ARM}/.default"}, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"Entra ID could not be reached: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise connectors.Reconsent(f"Entra ID refused the app's sign-in ({r.status_code}): {r.text[:160]}")
        return r.json()["access_token"]

    def _ws(self, c: dict) -> str:
        cfg = c["config"]
        return (f"{(cfg.get('arm_url') or ARM).rstrip('/')}/subscriptions/{cfg['subscription_id']}/resourceGroups/{cfg['resource_group']}"
                f"/providers/Microsoft.MachineLearningServices/workspaces/{cfg['workspace']}")

    def _get_all(self, c: dict, path: str, what: str) -> list[dict]:
        h = {"Authorization": f"Bearer {self._token(c)}"}
        url, out = f"{self._ws(c)}{path}?api-version={AML_API}", []
        for _ in range(50):
            try:
                r = httpx.get(url, headers=h, timeout=TIMEOUT)
            except httpx.HTTPError as e:
                raise connectors.ConnectorError(f"{what}: {e.__class__.__name__}") from e
            body = _check(r, what)
            out += body.get("value") or []
            url = body.get("nextLink")
            if not url:
                break
        return out

    def test(self, c: dict) -> dict:
        ms = self._get_all(c, "/models", "Azure ML models")
        eps = self._get_all(c, "/onlineEndpoints", "Azure ML online endpoints")
        return {"ok": True, "sees": f"{len(ms)} model(s), {len(eps)} online endpoint(s) in {c['config']['workspace']}"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        out = []
        for m in self._get_all(c, "/models", "Azure ML models"):
            p = m.get("properties") or {}
            out.append({"object": f"models/{m['name']}", "type": "model", "name": m["name"], "version": p.get("latestVersion"), "stage": (p.get("tags") or {}).get("stage") or ""})
        for e in self._get_all(c, "/onlineEndpoints", "Azure ML online endpoints"):
            out.append({"object": f"endpoints/{e['name']}", "type": "endpoint", "name": e["name"], "version": "", "stage": (e.get("properties") or {}).get("provisioningState") or ""})
        return [o for o in out if search.lower() in o["object"].lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        if obj.startswith("models/"):
            rows = [{"version": v["name"], "stage": (v.get("properties") or {}).get("stage"), "model_type": (v.get("properties") or {}).get("modelType"),
                     "uri": (v.get("properties") or {}).get("modelUri"), "tags": json.dumps((v.get("properties") or {}).get("tags") or {})}
                    for v in self._get_all(c, f"/models/{quote(obj.split('/', 1)[1])}/versions", "Azure ML model versions")]
        elif obj in ("models", "endpoints"):
            rows = [o for o in self.list_objects(c) if o["type"] == obj[:-1]]
        else:
            raise connectors.ConnectorError(f"No object {obj} on {c['name']}")
        return {"columns": sorted({k for r in rows for k in r}), "rows": rows[:limit], "row_count": len(rows)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        h = {"Authorization": f"Bearer {self._token(c)}", "Content-Type": "application/json", APPROVAL_HEADER: approval}
        name, ver = payload["name"], str(payload["version"])
        base = f"{self._ws(c)}/models/{quote(name)}"
        version = {"properties": {"description": payload.get("description") or "", "modelType": "custom_model", "modelUri": payload.get("uri") or "",
                                  "properties": {k: str(v) for k, v in (payload.get("properties") or {}).items()}, "tags": {"method": str(payload.get("method")), "source": "relay"}}}
        try:
            r = httpx.put(f"{base}/versions/{ver}?api-version={AML_API}", headers=h, timeout=TIMEOUT, json=version)
            if r.status_code == 404:                          # no model container yet: create it, then the version
                _check(httpx.put(f"{base}?api-version={AML_API}", headers=h, json={"properties": {"description": payload.get("description") or "", "tags": {"source": "relay"}}}, timeout=TIMEOUT), "Azure ML model")
                r = httpx.put(f"{base}/versions/{ver}?api-version={AML_API}", headers=h, timeout=TIMEOUT, json=version)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"Azure ML: {e.__class__.__name__}") from e
        if r.status_code == 409:
            raise connectors.ConnectorError(f"Azure ML: version {ver} of {name} already exists (model versions cannot be changed)")
        body = _check(r, "Azure ML model version")
        return {"ok": True, "registry": "azureml", "id": body.get("id"), "version": body.get("name") or ver}


# ------------------------------------------------------------------ Amazon SageMaker (Model Registry: model package groups)

class SageMaker(sdk.Adapter):
    kind, label, category = "sagemaker", "Amazon SageMaker", "code"
    signin = ["api_key"]
    fields = [("region", "Region (e.g. eu-west-2)", True), ("model_package_group", "Model package group for new versions", False),
              ("endpoint_url", "Endpoint URL (optional; a VPC endpoint)", False)]
    secrets = {"api_key": ["aws_access_key_id", "aws_secret_access_key", "aws_session_token"]}
    can_write = True

    def _client(self, c: dict, approval: str | None = None):
        import boto3
        from botocore.config import Config
        ak, sk = _secret(c, "aws_access_key_id"), _secret(c, "aws_secret_access_key")
        if not ak or not sk:
            raise connectors.Reconsent("No AWS access key is stored for this connection.")
        cl = boto3.client("sagemaker", region_name=c["config"]["region"], endpoint_url=(c["config"].get("endpoint_url") or None), aws_access_key_id=ak,
                          aws_secret_access_key=sk, aws_session_token=_secret(c, "aws_session_token") or None,
                          config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=TIMEOUT))
        if approval:
            cl.meta.events.register("before-sign.sagemaker.*", lambda request, **_: request.headers.__setitem__(APPROVAL_HEADER, approval))
        return cl

    def _call(self, c: dict, op: str, approval: str | None = None, **kw) -> dict:
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            return getattr(self._client(c, approval), op)(**kw)
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code") or ""
            if code in ("ExpiredTokenException", "UnrecognizedClientException", "InvalidSignatureException", "AccessDeniedException", "MissingAuthenticationTokenException"):
                raise connectors.Reconsent(f"SageMaker refused the sign-in ({code}). Renew the connection's keys.") from e
            raise connectors.ConnectorError(f"SageMaker {op}: {code} {str(e)[:200]}") from e
        except BotoCoreError as e:
            raise connectors.ConnectorError(f"SageMaker could not be reached: {str(e)[:200]}") from e

    def _all(self, c: dict, op: str, key: str, **kw) -> list[dict]:
        out, token = [], None
        for _ in range(50):
            r = self._call(c, op, **kw, **({"NextToken": token} if token else {}))
            out += r.get(key) or []
            token = r.get("NextToken")
            if not token:
                break
        return out

    def test(self, c: dict) -> dict:
        groups = self._all(c, "list_model_package_groups", "ModelPackageGroupSummaryList")
        eps = self._all(c, "list_endpoints", "Endpoints")
        return {"ok": True, "sees": f"{len(groups)} model package group(s), {len(eps)} endpoint(s) in {c['config']['region']}"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        out = []
        for g in self._all(c, "list_model_package_groups", "ModelPackageGroupSummaryList"):
            vs = self._all(c, "list_model_packages", "ModelPackageSummaryList", ModelPackageGroupName=g["ModelPackageGroupName"])
            last = max(vs, key=lambda v: v.get("ModelPackageVersion") or 0) if vs else {}
            out.append({"object": f"models/{g['ModelPackageGroupName']}", "type": "model", "name": g["ModelPackageGroupName"], "version": last.get("ModelPackageVersion"),
                        "stage": last.get("ModelApprovalStatus") or ""})
        for e in self._all(c, "list_endpoints", "Endpoints"):
            out.append({"object": f"endpoints/{e['EndpointName']}", "type": "endpoint", "name": e["EndpointName"], "version": "", "stage": e.get("EndpointStatus") or ""})
        return [o for o in out if search.lower() in o["object"].lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        if obj.startswith("models/"):
            rows = [{"version": v.get("ModelPackageVersion"), "status": v.get("ModelPackageStatus"), "approval": v.get("ModelApprovalStatus"), "arn": v.get("ModelPackageArn"),
                     "description": v.get("ModelPackageDescription")} for v in self._all(c, "list_model_packages", "ModelPackageSummaryList", ModelPackageGroupName=obj.split("/", 1)[1])]
        elif obj in ("models", "endpoints"):
            rows = [o for o in self.list_objects(c) if o["type"] == obj[:-1]]
        else:
            raise connectors.ConnectorError(f"No object {obj} on {c['name']}")
        return {"columns": sorted({k for r in rows for k in r}), "rows": rows[:limit], "row_count": len(rows)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        if payload.get("action") == "approve":                # approve a pending model package version for deployment
            r = self._call(c, "update_model_package", approval, ModelPackageArn=payload["arn"], ModelApprovalStatus="Approved",
                           ApprovalDescription=(payload.get("description") or "Approved in Relay")[:1000])
            return {"ok": True, "registry": "sagemaker", "id": r.get("ModelPackageArn"), "approved": True}
        group = c["config"].get("model_package_group") or re.sub(r"[^A-Za-z0-9-]+", "-", payload["name"])[:63].strip("-")
        names = {g["ModelPackageGroupName"] for g in self._all(c, "list_model_package_groups", "ModelPackageGroupSummaryList")}
        if group not in names:
            self._call(c, "create_model_package_group", approval, ModelPackageGroupName=group, ModelPackageGroupDescription="Forecast models registered by Relay")
        r = self._call(c, "create_model_package", approval, ModelPackageGroupName=group, ModelPackageDescription=(payload.get("description") or "")[:1000],
                       ModelApprovalStatus="PendingManualApproval", CustomerMetadataProperties={k: str(v)[:256] for k, v in {**(payload.get("properties") or {}), "method": payload.get("method"), "source": "relay"}.items()})
        return {"ok": True, "registry": "sagemaker", "id": r.get("ModelPackageArn"), "group": group}


# ------------------------------------------------------------------ Google Vertex AI (Model Registry)

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class VertexAI(sdk.Adapter):
    kind, label, category = "vertexai", "Google Vertex AI", "code"
    signin = ["service_account"]
    fields = [("project", "Project id", True), ("location", "Region (e.g. europe-west2)", True), ("api_url", "API URL (optional; a private endpoint)", False)]
    secrets = {"service_account": ["service_account_json"]}
    can_write = True

    def _token(self, c: dict) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        raw = _secret(c, "service_account_json")
        if not raw:
            raise connectors.Reconsent("No service account key is stored for this connection.")
        try:
            sa = json.loads(raw)
            key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
        except (ValueError, KeyError, TypeError) as e:
            raise connectors.Reconsent("The service account key could not be read: paste the JSON key file Google gave you.") from e
        now = int(time.time())
        head = _b64u(json.dumps({"alg": "RS256", "typ": "JWT", "kid": sa.get("private_key_id")}, separators=(",", ":")).encode())
        body = _b64u(json.dumps({"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/cloud-platform", "aud": sa["token_uri"], "iat": now, "exp": now + 3600,
                                 "kid": sa.get("private_key_id")},
                                separators=(",", ":")).encode())
        sig = _b64u(key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()))
        try:
            r = httpx.post(sa["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": f"{head}.{body}.{sig}"}, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"Google sign-in could not be reached: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise connectors.Reconsent(f"Google refused the service account ({r.status_code}): {r.text[:160]}")
        return r.json()["access_token"]

    def _base(self, c: dict) -> str:
        cfg = c["config"]
        api = (cfg.get("api_url") or f"https://{cfg['location']}-aiplatform.googleapis.com").rstrip("/")
        return f"{api}/v1/projects/{cfg['project']}/locations/{cfg['location']}"

    def _all(self, c: dict, path: str, key: str, what: str) -> list[dict]:
        h = {"Authorization": f"Bearer {self._token(c)}"}
        out, token = [], None
        for _ in range(50):
            try:
                r = httpx.get(f"{self._base(c)}/{path}", params={"pageToken": token} if token else None, headers=h, timeout=TIMEOUT)
            except httpx.HTTPError as e:
                raise connectors.ConnectorError(f"{what}: {e.__class__.__name__}") from e
            body = _check(r, what)
            out += body.get(key) or []
            token = body.get("nextPageToken")
            if not token:
                break
        return out

    def test(self, c: dict) -> dict:
        ms = self._all(c, "models", "models", "Vertex AI models")
        eps = self._all(c, "endpoints", "endpoints", "Vertex AI endpoints")
        return {"ok": True, "sees": f"{len(ms)} model(s), {len(eps)} endpoint(s) in {c['config']['location']}"}

    def list_objects(self, c: dict, search: str = "") -> list[dict]:
        out = [{"object": f"models/{m['name'].rsplit('/', 1)[-1]}", "type": "model", "name": m.get("displayName") or m["name"], "version": m.get("versionId"),
                "stage": ",".join(m.get("versionAliases") or [])} for m in self._all(c, "models", "models", "Vertex AI models")]
        out += [{"object": f"endpoints/{e['name'].rsplit('/', 1)[-1]}", "type": "endpoint", "name": e.get("displayName") or e["name"], "version": "",
                 "stage": f"{len(e.get('deployedModels') or [])} deployed"} for e in self._all(c, "endpoints", "endpoints", "Vertex AI endpoints")]
        return [o for o in out if search.lower() in o["object"].lower() or search.lower() in str(o["name"]).lower()]

    def read(self, c: dict, obj: str, limit: int = 100) -> dict:
        if obj in ("models", "endpoints"):
            rows = [o for o in self.list_objects(c) if o["type"] == obj[:-1]]
        elif obj.startswith("models/"):
            rows = [o for o in self.list_objects(c) if o["object"] == obj]
        else:
            raise connectors.ConnectorError(f"No object {obj} on {c['name']}")
        return {"columns": sorted({k for r in rows for k in r}), "rows": rows[:limit], "row_count": len(rows)}

    def _write(self, c: dict, obj: str, payload: dict, approval: str) -> dict:
        h = {"Authorization": f"Bearer {self._token(c)}", APPROVAL_HEADER: approval}
        model = {"displayName": payload["name"], "description": payload.get("description") or "", "labels": {"source": "relay", "method": re.sub(r"[^a-z0-9_-]", "_", str(payload.get("method")).lower())[:63]},
                 "artifactUri": payload.get("uri") or "", "metadata": payload.get("properties") or {}}
        try:
            r = httpx.post(f"{self._base(c)}/models:upload", headers=h, json={"model": model}, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise connectors.ConnectorError(f"Vertex AI: {e.__class__.__name__}") from e
        body = _check(r, "Vertex AI model upload")
        api = (c["config"].get("api_url") or f"https://{c['config']['location']}-aiplatform.googleapis.com").rstrip("/")
        for _ in range(20):                                    # a long-running operation: poll it until it is done
            if body.get("done") or not body.get("name"):
                break
            time.sleep(0.2)
            try:
                body = _check(httpx.get(f"{api}/v1/{body['name']}", headers={"Authorization": h["Authorization"]}, timeout=TIMEOUT), "Vertex AI upload operation")
            except httpx.HTTPError as e:
                raise connectors.ConnectorError(f"Vertex AI: {e.__class__.__name__}") from e
        if body.get("error"):
            raise connectors.ConnectorError(f"Vertex AI: the upload failed: {(body['error'] or {}).get('message')}")
        resp = body.get("response") or {}
        return {"ok": True, "registry": "vertexai", "id": resp.get("model") or body.get("name"), "version": resp.get("modelVersionId"), "done": bool(body.get("done"))}


ADAPTERS = (AzureML(), SageMaker(), VertexAI())
for _a in ADAPTERS:
    sdk.register(_a)
    if _a.kind not in connectors.KINDS:                  # the same catalogue entry the SDK loop in connectors.py makes
        _d = _a.describe()
        connectors.KINDS[_a.kind] = {"label": _d["label"], "dialect": None, "auth": list(_d["auth"]), "fields": [(f["key"], f["label"], f["required"]) for f in _d["fields"]],
                                     "secrets": _d["secrets"], "category": _d["category"], "sdk": True}
KINDS = tuple(a.kind for a in ADAPTERS)
LABEL = {a.kind: a.label for a in ADAPTERS}


class RegistryPlatform(wb.Platform):
    id, label = "registry", "A model registry (deployment target)"
    kinds = KINDS
    simulator = "tests/mocklab/sims/ai.py - azure_ml (ARM + Entra ID), sagemaker (JSON 1.1 + SigV4), vertex_ai (REST + JWT-bearer)"
    reads = "models, their versions and online endpoints - read-only; a model is registered only after that write is approved"


PLATFORM = RegistryPlatform()


def inventory(ctx: wb.Ctx) -> list[dict]:
    """Every model and endpoint in the item's registry connections (read-only)."""
    out = []
    for c in ctx.connections():
        if c["kind"] not in KINDS:
            continue
        try:
            for o in connectors.browse(c):
                out.append({"registry": f"{c['name']} ({LABEL[c['kind']]})", "kind": c["kind"], "connection": c["id"], **{k: o.get(k) for k in ("object", "type", "name", "version", "stage")}})
        except connectors.ConnectorError as e:
            out.append({"registry": f"{c['name']} ({LABEL[c['kind']]})", "kind": c["kind"], "connection": c["id"], "object": "", "type": "error", "name": str(e)[:200], "version": "", "stage": ""})
    return out


def request_deploy(ctx: wb.Ctx, c: dict, fc: dict) -> dict:
    """Ask for a registration of the forecast's model in a registry - a write request a named person approves."""
    name = re.sub(r"[^A-Za-z0-9-]+", "-", f"relay-{fc['name']}").strip("-")[:60].lower()
    acc = {sid: m.get("wape") for sid, m in (fc.get("metrics") or {}).items() if isinstance(m, dict)}
    payload = {"from": f"predict:{ctx.id}", "name": name, "version": fc["version"], "method": ", ".join(sorted({m.get("method") for m in (fc.get("metrics") or {}).values() if isinstance(m, dict)})),
               "accuracy": ", ".join(f"{k}: WAPE {v} %" for k, v in acc.items())[:500], "description": f"Relay forecast \"{fc['name']}\" version {fc['version']} ({len(fc.get('spec') or [])} series)",
               "uri": f"relay://forecasts/{fc['id']}/v{fc['version']}", "properties": {"forecast_id": fc["id"], "relay_version": fc["version"], "series": len(fc.get("spec") or [])}}
    try:
        cp = ctx.request_write(c["id"], "model", payload, f"Register {name} v{fc['version']} in {c['name']} ({LABEL[c['kind']]})")
        return {"status": f"registration waits for its approval ({cp['id']})", "checkpoint": cp["id"]}
    except wb.StepFailed as e:
        return {"status": f"not requested: {e}"}
