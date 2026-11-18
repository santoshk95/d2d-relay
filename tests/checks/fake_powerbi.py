"""A stand-in for Microsoft's sign-in, the Fabric REST API and the Power BI REST API, for the D2D Relay test stack only
(never live). Standard library only. Item 55 (Semantic Review) reads semantic models through these.

Runs inside the test web container (docker exec -d), on 0.0.0.0:9912; the stack points the app at it with
D2D_ENTRA_LOGIN=http://d2d-relay-test-web:9912/login, D2D_FABRIC_API=.../fabric, D2D_POWERBI_API=.../powerbi:
  POST /login/<tenant>/oauth2/v2.0/token          client credentials: CLIENT_ID + SECRET, else 401 invalid_client
  GET  /fabric/v1/workspaces                      two workspaces (Bearer token needed)
  GET  /fabric/v1/workspaces/<ws>/semanticModels  the Sales BI workspace holds two models
  POST /fabric/v1/workspaces/<ws>/semanticModels/<id>/getDefinition?format=TMSL
       Sales model: 202, then the operation (Location on this host) Succeeded, then its result: model.bim
       Finance model: 403 (no write permission), so the app falls back to INFO.VIEW through executeQueries
  POST /powerbi/v1.0/myorg/groups/<ws>/datasets/<id>/executeQueries
       EVALUATE INFO.VIEW.MEASURES() / TABLES() / COLUMNS() / RELATIONSHIPS() for the Finance model, and
       EVALUATE ROW ( "v0", [Measure], ... ): fixed values; [Broken] makes the whole query fail (the app then asks one
       measure at a time)
and, for the tests: GET /_test/state (calls by kind), POST /_test/reset.
"""
import base64
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CLIENT_ID = "33333333-aaaa-4bbb-8ccc-000000000001"
SECRET = "stand-in-client-secret-not-real"
WS_SALES = "11111111-aaaa-4bbb-8ccc-000000000001"
WS_OPS = "11111111-aaaa-4bbb-8ccc-000000000002"
M_SALES = "22222222-aaaa-4bbb-8ccc-000000000001"
M_FIN = "22222222-aaaa-4bbb-8ccc-000000000002"
BASE = "http://d2d-relay-test-web:9912"
TOKENS: dict = {}
OPS: dict = {}
STATE: dict = {}
LOCK = threading.Lock()


def col(name, typ="decimal", sb="sum", hidden=False):
    return {"name": name, "dataType": typ, "summarizeBy": sb, "isHidden": hidden, "sourceColumn": name}


SALES_TMSL = {"name": "Sales model", "compatibilityLevel": 1567, "model": {"tables": [
    {"name": "Sales", "columns": [col("Amount"), col("NetAmount"), col("Status", "string", "none"), col("CustomerKey", "int64")],
     "measures": [
         {"name": "Revenue", "expression": "CALCULATE ( SUM ( Sales[NetAmount] ), Sales[Status] = \"Completed\" )", "formatString": "\\$#,0"},
         {"name": "Total Revenue", "expression": ["SUM (", "    Sales[Amount]", ")"], "formatString": "\\$#,0"},
         {"name": "Broken", "expression": "SUM ( Sales[Nope] )"}]},
    {"name": "Date", "columns": [col("Date", "dateTime", "none"), col("Year", "int64")]}],
    "relationships": []}}

FIN_MEASURES = [
    {"ID": 1, "Name": "Revenue", "Table": "Fact Sales", "Description": "", "DataType": "Variant", "Expression": "SUM ( 'Fact Sales'[Amount] )",
     "FormatString": "\\$#,0", "IsHidden": False, "State": "Ready", "DisplayFolder": ""},
    {"ID": 2, "Name": "COGS", "Table": "Fact Sales", "Description": "", "DataType": "Variant", "Expression": "SUM ( 'Fact Sales'[Cost] )",
     "FormatString": "\\$#,0", "IsHidden": False, "State": "Ready", "DisplayFolder": ""}]
FIN_TABLES = [{"ID": 1, "Name": "Fact Sales", "IsHidden": False, "Description": None, "Expression": None}]
FIN_COLUMNS = [{"Table": "Fact Sales", "Name": "Amount", "DataType": "Decimal", "SummarizeBy": "Sum", "IsHidden": False},
               {"Table": "Fact Sales", "Name": "Cost", "DataType": "Decimal", "SummarizeBy": "Sum", "IsHidden": False}]
VALUES = {"Revenue": 1234567.5, "Total Revenue": 1300000, "COGS": 400000}


def bump(kind: str) -> None:
    with LOCK:
        STATE[kind] = STATE.get(kind, 0) + 1


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code: int, body=None, headers=None):
        raw = json.dumps(body if body is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def authed(self) -> bool:
        tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if tok not in TOKENS:
            self.send(401, {"errorCode": "TokenExpired", "message": "Access token is missing or invalid."})
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/_test/state":
            with LOCK:
                return self.send(200, dict(STATE))
        if not self.authed():
            return None
        if p == "/fabric/v1/workspaces":
            bump("workspaces")
            return self.send(200, {"value": [{"id": WS_SALES, "displayName": "Sales BI", "type": "Workspace"},
                                             {"id": WS_OPS, "displayName": "Operations", "type": "Workspace"}]})
        m = re.fullmatch(r"/fabric/v1/workspaces/([0-9a-f-]{36})/semanticModels", p)
        if m:
            bump("models")
            if m.group(1) == WS_SALES:
                return self.send(200, {"value": [{"id": M_SALES, "displayName": "Sales model", "description": "Sales reporting"},
                                                 {"id": M_FIN, "displayName": "Finance model"}]})
            if m.group(1) == WS_OPS:
                return self.send(200, {"value": []})
            return self.send(404, {"errorCode": "WorkspaceNotFound", "message": "Workspace not found"})
        m = re.fullmatch(r"/fabric/v1/operations/([0-9a-f]{32})(/result)?", p)
        if m:
            op = OPS.get(m.group(1))
            if not op:
                return self.send(404, {"errorCode": "OperationNotFound"})
            if m.group(2):
                bump("definition_result")
                return self.send(200, op["result"])
            op["polls"] += 1
            bump("operation_poll")
            return self.send(200, {"status": "Running" if op["polls"] < 2 else "Succeeded", "percentComplete": 50 if op["polls"] < 2 else 100},
                             {"Retry-After": "1"})
        return self.send(404, {"errorCode": "NotFound"})

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        if p == "/_test/reset":
            with LOCK:
                STATE.clear()
            return self.send(200, {"ok": True})
        m = re.fullmatch(r"/login/([^/]+)/oauth2/v2.0/token", p)
        if m:
            form = {k: v[0] for k, v in parse_qs(self.body().decode()).items()}
            bump("token")
            if form.get("grant_type") != "client_credentials" or form.get("client_id") != CLIENT_ID:
                return self.send(400, {"error": "unauthorized_client", "error_description": "AADSTS700016: Application not found."})
            if form.get("client_secret") != SECRET:
                return self.send(401, {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."})
            tok = "standin-" + secrets.token_hex(12)
            TOKENS[tok] = form.get("scope")
            return self.send(200, {"token_type": "Bearer", "expires_in": 3599, "access_token": tok})
        if not self.authed():
            return None
        m = re.fullmatch(r"/fabric/v1/workspaces/([0-9a-f-]{36})/semanticModels/([0-9a-f-]{36})/getDefinition", p)
        if m:
            bump("get_definition")
            if m.group(2) == M_FIN:
                return self.send(403, {"errorCode": "InsufficientPrivileges", "message": "The caller does not have write permission."})
            if m.group(2) != M_SALES:
                return self.send(404, {"errorCode": "ItemNotFound"})
            op = secrets.token_hex(16)
            payload = base64.b64encode(json.dumps(SALES_TMSL).encode()).decode()
            OPS[op] = {"polls": 0, "result": {"definition": {"format": "TMSL", "parts": [
                {"path": "model.bim", "payload": payload, "payloadType": "InlineBase64"},
                {"path": "definition.pbism", "payload": base64.b64encode(b"{}").decode(), "payloadType": "InlineBase64"}]}}}
            return self.send(202, {}, {"Location": f"{BASE}/fabric/v1/operations/{op}", "x-ms-operation-id": op, "Retry-After": "1"})
        m = re.fullmatch(r"/powerbi/v1.0/myorg/groups/([0-9a-f-]{36})/datasets/([0-9a-f-]{36})/executeQueries", p)
        if m:
            q = json.loads(self.body() or b"{}").get("queries", [{}])[0].get("query", "")
            bump("execute_queries")
            rows = None
            if "INFO.VIEW.MEASURES" in q:
                rows = FIN_MEASURES if m.group(2) == M_FIN else []
            elif "INFO.VIEW.TABLES" in q:
                rows = FIN_TABLES if m.group(2) == M_FIN else []
            elif "INFO.VIEW.COLUMNS" in q:
                rows = FIN_COLUMNS if m.group(2) == M_FIN else []
            elif "INFO.VIEW.RELATIONSHIPS" in q:
                rows = []
            elif q.startswith("EVALUATE ROW"):
                pairs = re.findall(r'"(v\d*)", \[((?:[^\]]|\]\])*)\]', q)
                if any(n == "Broken" for _, n in pairs):
                    return self.send(200, {"results": [{"error": {"code": "DatasetExecuteQueriesError",
                                                                  "message": "Column 'Nope' in table 'Sales' cannot be found."}}]})
                rows = [{f"[{k}]": VALUES.get(n.replace("]]", "]")) for k, n in pairs}]
            if rows is None:
                return self.send(400, {"error": {"code": "BadRequest", "message": "The stand-in does not know that query."}})
            return self.send(200, {"results": [{"tables": [{"rows": [{f"[{k.strip('[]')}]": v for k, v in r.items()} for r in rows]}]}]})
        return self.send(404, {"errorCode": "NotFound"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9912), H).serve_forever()
