"""Document AI engines of Document processing as Connector SDK adapters — one adapter + one mock-lab simulator each
(tests/mocklab/sims/docai.py: `azure_di`, `textract`, `google_docai`) — each answering one question: what does this
engine read in this document? The answer is in one neutral shape whatever the engine:

  {"fields": {"InvoiceTotal": {"value": 1234.5, "confidence": 0.97}, …}, "items": [{"Description", "Quantity", …}],
   "pages": 2, "orientation": 0}

with the field names of an invoice (VendorName, VendorTaxId, InvoiceId, InvoiceDate, DueDate, PurchaseOrder, SubTotal,
TotalTax, InvoiceTotal, CurrencyCode, CustomerName) or a receipt (MerchantName, TransactionDate, Total, TotalTax,
CurrencyCode). Money comes back as a number, dates as ISO text.

  Azure AI Document Intelligence  2024-11-30: POST documentModels/prebuilt-invoice:analyze (base64Source), then the
                                  Operation-Location polled until it succeeds; Ocp-Apim-Subscription-Key.
  AWS Textract                    AnalyzeExpense (SummaryFields, LineItemGroups) signed with SigV4 (service textract).
  Google Document AI              processors/{id}:process with rawDocument; a service-account JWT grant.
Reading a document sends it to the engine; nothing is written anywhere.
"""
from __future__ import annotations

import base64
import json
import time

from .. import connectors
from . import _w2
from ._w1 import sign_v4
from .n8n_platforms import _cached, _keep

INVOICE = ("VendorName", "VendorTaxId", "InvoiceId", "InvoiceDate", "DueDate", "PurchaseOrder", "SubTotal", "TotalTax", "InvoiceTotal", "CurrencyCode", "CustomerName")
RECEIPT = ("MerchantName", "TransactionDate", "Total", "TotalTax", "CurrencyCode")
MONEY = {"SubTotal", "TotalTax", "InvoiceTotal", "Total"}
ITEM_KEYS = ("Description", "Quantity", "UnitPrice", "Amount")


def fields_of(kind: str) -> tuple:
    return RECEIPT if kind == "receipt" else INVOICE


def _num(v):
    try:
        return round(float(str(v).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def _f(name: str, value, conf) -> dict:
    return {"value": _num(value) if name in MONEY else (str(value).strip() if value is not None else None), "confidence": round(float(conf or 0), 3)}


class Engine(_w2.Adapter):
    category = "ai"
    can_write = False

    def extract(self, c: dict, data: bytes, kind: str = "invoice") -> dict:  # noqa: ARG002
        raise connectors.ConnectorError(f"{self.label} does not read documents through Relay")

    def estate(self, c):
        return []

    def test(self, c):
        return {"ok": True, "sees": self.sees(c)}

    def sees(self, c) -> str:
        return "ready"


# ================================================================== Azure AI Document Intelligence

DI_API = "2024-11-30"


class AzureDocumentIntelligence(Engine):
    kind, label, vendor, platform = "azure_di", "Azure AI Document Intelligence", "Azure AI Document Intelligence", "Azure AI Document Intelligence"
    simulator = "tests/mocklab/sims/docai.py: azure_di (2024-11-30)"
    fields = [("base_url", "Endpoint (https://<resource>.cognitiveservices.azure.com)", True), ("invoice_model", "Invoice model (default prebuilt-invoice)", False)]
    secrets = {"api_key": ["key"]}

    def signin_headers(self, c):
        return {"Ocp-Apim-Subscription-Key": _w2.secret(c, "key")}

    def sees(self, c):
        ms = self.req(c, "GET", "/documentintelligence/documentModels", params={"api-version": DI_API}).json().get("value") or []
        return f"{len(ms)} model(s): " + ", ".join(m["modelId"] for m in ms[:5])

    def extract(self, c, data, kind="invoice"):
        model = (_w2.cfg(c, "invoice_model") or "prebuilt-invoice") if kind != "receipt" else "prebuilt-receipt"
        r = self.req(c, "POST", f"/documentintelligence/documentModels/{model}:analyze", params={"api-version": DI_API}, json_body={"base64Source": base64.b64encode(data).decode()}, ok=(202,))
        loc = r.headers.get("Operation-Location")
        res = {}
        for i in range(60):
            res = self.req(c, "GET", loc).json()
            if res.get("status") in ("succeeded", "failed"):
                break
            time.sleep(min(1.0, 0.05 * (i + 1)))
        if res.get("status") != "succeeded":
            raise connectors.ConnectorError(f"Document Intelligence did not finish the analysis: {res.get('status')} {json.dumps(res.get('error') or {})[:200]}")
        ar = res["analyzeResult"]
        doc = (ar.get("documents") or [{}])[0]
        out, cur = {}, None
        for k, v in (doc.get("fields") or {}).items():
            if k == "Items":
                continue
            val = v.get("valueString") or v.get("valueDate") or (v.get("valueCurrency") or {}).get("amount") or v.get("valueNumber") or v.get("content")
            cur = cur or (v.get("valueCurrency") or {}).get("currencyCode")
            out[k] = _f(k, val, v.get("confidence"))
        if cur:                                  # the currency is part of every amount: the document's own confidence, not one amount's
            out["CurrencyCode"] = _f("CurrencyCode", cur, doc.get("confidence") or 0.9)
        items = [{k: (x.get("valueString") or x.get("valueNumber") or (x.get("valueCurrency") or {}).get("amount") or x.get("content")) for k, x in (it.get("valueObject") or {}).items()}
                 for it in ((doc.get("fields") or {}).get("Items") or {}).get("valueArray") or []]
        return {"fields": out, "items": items, "pages": len(ar.get("pages") or []), "orientation": ((ar.get("pages") or [{}])[0]).get("angle") or 0, "confidence": doc.get("confidence")}


# ================================================================== AWS Textract (AnalyzeExpense)

TX = {"VENDOR_NAME": "VendorName", "TAX_PAYER_ID": "VendorTaxId", "INVOICE_RECEIPT_ID": "InvoiceId", "INVOICE_RECEIPT_DATE": "InvoiceDate", "DUE_DATE": "DueDate", "PO_NUMBER": "PurchaseOrder",
      "SUBTOTAL": "SubTotal", "TAX": "TotalTax", "TOTAL": "InvoiceTotal", "RECEIVER_NAME": "CustomerName"}
TX_RECEIPT = {"VENDOR_NAME": "MerchantName", "INVOICE_RECEIPT_DATE": "TransactionDate", "TOTAL": "Total", "TAX": "TotalTax"}


class AwsTextract(Engine):
    kind, label, vendor, platform = "textract_api", "AWS Textract", "AWS Textract", "AWS Textract"
    simulator = "tests/mocklab/sims/docai.py: textract (AnalyzeExpense, SigV4)"
    signin = ["aws_keys"]
    fields = [("base_url", "Endpoint (https://textract.<region>.amazonaws.com)", True), ("region", "Region", True), ("access_key_id", "Access key id", True)]
    secrets = {"aws_keys": ["secret_access_key", "session_token"]}

    def _call(self, c, op: str, body: dict) -> dict:
        raw = json.dumps(body).encode()
        url = self.base(c) + "/"
        try:
            tok = _w2.secret(c, "session_token")
        except connectors.ConnectorError:
            tok = None
        h = sign_v4("POST", url, _w2.cfg(c, "region") or "us-east-1", "textract", _w2.cfg(c, "access_key_id"), _w2.secret(c, "secret_access_key"), raw,
                    {"content-type": "application/x-amz-json-1.1", "x-amz-target": f"Textract.{op}"}, tok)
        return _w2.call("AWS Textract", "POST", url, headers=h, content=raw).json()

    def sees(self, c):
        self._call(c, "AnalyzeExpense", {"Document": {"Bytes": base64.b64encode(b"%PDF-1.4\n%%EOF\n").decode()}})
        return "AnalyzeExpense answers"

    def extract(self, c, data, kind="invoice"):
        r = self._call(c, "AnalyzeExpense", {"Document": {"Bytes": base64.b64encode(data).decode()}})
        names = TX_RECEIPT if kind == "receipt" else TX
        out, cur = {}, None
        docs = r.get("ExpenseDocuments") or [{}]
        for f in docs[0].get("SummaryFields") or []:
            k = names.get((f.get("Type") or {}).get("Text"))
            if not k or k in out:
                continue
            vd = f.get("ValueDetection") or {}
            out[k] = _f(k, vd.get("Text"), (vd.get("Confidence") or 0) / 100)
            cur = cur or (f.get("Currency") or {}).get("Code")
        if cur:                                  # read with every amount: the surest of them
            out["CurrencyCode"] = _f("CurrencyCode", cur, max((x["confidence"] for k, x in out.items() if k in MONEY), default=0.9))
        tmap = {"ITEM": "Description", "QUANTITY": "Quantity", "UNIT_PRICE": "UnitPrice", "PRICE": "Amount"}
        items = [{tmap[x["Type"]["Text"]]: (x.get("ValueDetection") or {}).get("Text") for x in li.get("LineItemExpenseFields") or [] if x["Type"]["Text"] in tmap}
                 for g in docs[0].get("LineItemGroups") or [] for li in g.get("LineItems") or []]
        return {"fields": out, "items": items, "pages": (r.get("DocumentMetadata") or {}).get("Pages") or 1, "orientation": 0}


# ================================================================== Google Document AI

G = {"supplier_name": "VendorName", "supplier_tax_id": "VendorTaxId", "invoice_id": "InvoiceId", "invoice_date": "InvoiceDate", "due_date": "DueDate", "purchase_order": "PurchaseOrder",
     "net_amount": "SubTotal", "total_tax_amount": "TotalTax", "total_amount": "InvoiceTotal", "currency": "CurrencyCode", "receiver_name": "CustomerName"}
G_RECEIPT = {"supplier_name": "MerchantName", "receipt_date": "TransactionDate", "total_amount": "Total", "total_tax_amount": "TotalTax", "currency": "CurrencyCode"}


class GoogleDocumentAI(Engine):
    kind, label, vendor, platform = "google_docai", "Google Document AI", "Google Document AI", "Google Document AI"
    simulator = "tests/mocklab/sims/docai.py: google_docai (v1, service account)"
    signin = ["service_account"]
    fields = [("base_url", "Endpoint (https://<location>-documentai.googleapis.com)", True), ("project", "Project id", True), ("location", "Location (eu or us)", True),
              ("invoice_processor", "Invoice processor id", True), ("receipt_processor", "Expense (receipt) processor id", False)]
    secrets = {"service_account": ["service_account_json"]}

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            from .ship_adapters import google_sign_in

            class _Api:                      # google_sign_in needs .secret and .raw, as the W3 Api has them
                def secret(self, n):
                    return _w2.secret(c, n)

                def raw(self, method, url, **kw):
                    import httpx
                    return httpx.request(method, url, timeout=30, **kw)
            h = google_sign_in(self, _Api(), "https://www.googleapis.com/auth/cloud-platform")
            tok = _keep(c, h["Authorization"].split(" ", 1)[1], 3500)
        return {"Authorization": f"Bearer {tok}"}

    def error_text(self, r):
        return r.text[:200]

    def _loc(self, c) -> str:
        return f"/v1/projects/{_w2.cfg(c, 'project')}/locations/{_w2.cfg(c, 'location')}"

    def sees(self, c):
        ps = self.req(c, "GET", f"{self._loc(c)}/processors").json().get("processors") or []
        return f"{len(ps)} processor(s): " + ", ".join(p.get("displayName") or p["name"] for p in ps[:4])

    def extract(self, c, data, kind="invoice"):
        pid = _w2.cfg(c, "receipt_processor") if kind == "receipt" and _w2.cfg(c, "receipt_processor") else _w2.cfg(c, "invoice_processor")
        d = self.req(c, "POST", f"{self._loc(c)}/processors/{pid}:process", json_body={"rawDocument": {"content": base64.b64encode(data).decode(), "mimeType": "application/pdf"}}).json()["document"]
        names = G_RECEIPT if kind == "receipt" else G
        out, items = {}, []
        for e in d.get("entities") or []:
            if e["type"] == "line_item":
                items.append({{"description": "Description", "quantity": "Quantity", "unit_price": "UnitPrice", "amount": "Amount"}[p["type"].split("/", 1)[1]]: p.get("mentionText")
                              for p in e.get("properties") or [] if p["type"].split("/", 1)[-1] in ("description", "quantity", "unit_price", "amount")})
                continue
            k = names.get(e["type"])
            if not k or k in out:
                continue
            nv = e.get("normalizedValue") or {}
            mv = nv.get("moneyValue")
            val = (int(mv.get("units") or 0) + int(mv.get("nanos") or 0) / 1e9) if mv else (nv.get("text") if nv.get("dateValue") else e.get("mentionText"))
            out[k] = _f(k, val, e.get("confidence"))
            if mv and mv.get("currencyCode") and "CurrencyCode" not in out:
                out["CurrencyCode"] = _f("CurrencyCode", mv["currencyCode"], e.get("confidence"))
        pg = d.get("pages") or [{}]
        return {"fields": out, "items": items, "pages": len(pg), "orientation": 90 if (pg[0].get("layout") or {}).get("orientation") == "PAGE_RIGHT" else 0}


# ================================================================== UiPath Document Understanding

DU_FIELD = {"invoices.vendor-name": "VendorName", "invoices.vendor-tax-id": "VendorTaxId", "invoices.invoice-no": "InvoiceId", "invoices.invoice-date": "InvoiceDate",
            "invoices.due-date": "DueDate", "invoices.po-no": "PurchaseOrder", "invoices.net-amount": "SubTotal", "invoices.tax-amount": "TotalTax", "invoices.total": "InvoiceTotal",
            "invoices.currency": "CurrencyCode", "invoices.customer-name": "CustomerName"}
DU_COL = {"description": "Description", "quantity": "Quantity", "unit-price": "UnitPrice", "line-amount": "Amount"}


def _multipart(name: str, filename: str, data: bytes) -> tuple[bytes, str]:
    import hashlib
    b = "relay" + hashlib.sha1(data).hexdigest()[:12]
    head = f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'
    return head.encode() + data + f"\r\n--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def _wait(fn, tries: int = 60) -> dict:
    out = {}
    for i in range(tries):
        out = fn()
        if str(out.get("status")).lower() in ("succeeded", "failed", "processed", "error"):
            return out
        time.sleep(min(1.0, 0.05 * (i + 1)))
    return out


class UiPathDocumentUnderstanding(Engine):
    kind, label, vendor, platform = "uipath_du", "UiPath Document Understanding", "UiPath Document Understanding", "UiPath Document Understanding"
    simulator = "tests/mocklab/sims/docai.py: uipath_du (framework API v1)"
    fields = [("base_url", "Document Understanding API (https://cloud.uipath.com/<org>/<tenant>/du_/api/framework)", True),
              ("token_url", "Identity token URL (https://cloud.uipath.com/identity_/connect/token)", True), ("client_id", "External application id", True),
              ("project", "Project id (blank: the predefined project)", False)]
    secrets = {"api_key": ["client_secret"]}
    SCOPE = "Du.Digitization.Api Du.Classification.Api Du.Extraction.Api"

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            d = _w2.call("UiPath identity", "POST", _w2.cfg(c, "token_url"), data={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"),
                                                                                 "client_secret": _w2.secret(c, "client_secret"), "scope": self.SCOPE}).json()
            tok = _keep(c, d["access_token"], d.get("expires_in"))
        return {"Authorization": f"Bearer {tok}"}

    def _pid(self, c) -> str:
        return _w2.cfg(c, "project") or "00000000-0000-0000-0000-000000000000"

    def sees(self, c):
        ex = self.req(c, "GET", f"/projects/{self._pid(c)}/extractors", params={"api-version": 1}).json().get("extractors") or []
        return f"{len(ex)} extractor(s): " + ", ".join(e["name"] for e in ex[:5])

    def extract(self, c, data, kind="invoice"):
        body, ct = _multipart("File", "document.pdf", data)
        d = self.req(c, "POST", f"/projects/{self._pid(c)}/digitization/start", params={"api-version": 1}, content=body, headers={"Content-Type": ct}).json()
        dig = _wait(lambda: self.req(c, "GET", d["resultUrl"]).json())
        if str(dig.get("status")) != "Succeeded":
            raise connectors.ConnectorError(f"Document Understanding did not digitise the document: {dig.get('status')}")
        ex = "receipts" if kind == "receipt" else "invoices"
        r = self.req(c, "POST", f"/projects/{self._pid(c)}/extractors/{ex}/extraction", params={"api-version": 1}, json_body={"documentId": d["documentId"]}).json()
        rd = (r.get("extractionResult") or {}).get("ResultsDocument") or {}
        out = {}
        for f in rd.get("Fields") or []:
            k = DU_FIELD.get(f.get("FieldId")) or f.get("FieldName")
            v = (f.get("Values") or [{}])[0]
            if k and not f.get("IsMissing"):
                out[k] = _f(k, v.get("Value"), v.get("Confidence"))
        items = []
        for t in rd.get("Tables") or []:
            tv = (t.get("Values") or [{}])[0]
            cols = {i: ci["FieldName"] for i, ci in enumerate(tv.get("ColumnInfo") or [])}
            rows: dict = {}
            for cell in tv.get("Cells") or []:
                if cell.get("IsHeader"):
                    continue
                col = cols.get(cell["ColumnIndex"])
                rows.setdefault(cell["RowIndex"], {})[DU_COL.get(col, col)] = ((cell.get("Values") or [{}])[0]).get("Value")
            items += [rows[k] for k in sorted(rows)]
        pages = ((dig.get("result") or {}).get("documentObjectModel") or {}).get("Pages") or [{}]
        return {"fields": out, "items": items, "pages": len(pages), "orientation": pages[0].get("Rotation") or 0}


# ================================================================== ABBYY Vantage

ABBYY_FIELD = {"InvoiceNumber": "InvoiceId", "TotalAmount": "InvoiceTotal", "NetAmount": "SubTotal", "TaxAmount": "TotalTax", "Currency": "CurrencyCode", "VendorTaxID": "VendorTaxId",
               "Vendor": "VendorName", "PONumber": "PurchaseOrder", "Customer": "CustomerName"}


class AbbyyVantage(Engine):
    kind, label, vendor, platform = "abbyy_vantage", "ABBYY Vantage", "ABBYY Vantage", "ABBYY Vantage"
    simulator = "tests/mocklab/sims/docai.py: abbyy (Vantage public API v1)"
    fields = [("base_url", "Vantage URL (https://vantage-eu.abbyy.com)", True), ("client_id", "Client id", True), ("invoice_skill", "Invoice skill (default: Invoice)", False),
              ("receipt_skill", "Receipt skill (default: Receipt)", False)]
    secrets = {"api_key": ["client_secret"]}

    def signin_headers(self, c):
        tok = _cached(c)
        if not tok:
            d = _w2.call("ABBYY Vantage", "POST", self.base(c) + "/auth2/connect/token", data={"grant_type": "client_credentials", "client_id": _w2.cfg(c, "client_id"),
                                                                                             "client_secret": _w2.secret(c, "client_secret")}).json()
            tok = _keep(c, d["access_token"], d.get("expires_in"))
        return {"Authorization": f"Bearer {tok}"}

    def _skills(self, c) -> list[dict]:
        return self.req(c, "GET", "/api/publicapi/v1/skills").json()

    def sees(self, c):
        return "skills: " + ", ".join(s["name"] for s in self._skills(c)[:6])

    def extract(self, c, data, kind="invoice"):
        want = (_w2.cfg(c, "receipt_skill") or "Receipt") if kind == "receipt" else (_w2.cfg(c, "invoice_skill") or "Invoice")
        sk = next((s["id"] for s in self._skills(c) if s["name"].lower() == want.lower()), None)
        if not sk:
            raise connectors.ConnectorError(f"ABBYY Vantage has no skill named {want!r}")
        body, ct = _multipart("Files", "document.pdf", data)
        tid = self.req(c, "POST", "/api/publicapi/v1/transactions/launch", params={"skillId": sk}, content=body, headers={"Content-Type": ct}).json()["transactionId"]
        st = _wait(lambda: self.req(c, "GET", f"/api/publicapi/v1/transactions/{tid}").json())
        if str(st.get("status")) != "Processed":
            raise connectors.ConnectorError(f"ABBYY Vantage did not process the document: {st.get('status')}")
        doc0 = (st.get("documents") or [{}])[0]
        fid = next((f["fileId"] for f in doc0.get("resultFiles") or [] if f.get("type") == "Json"), None)
        res = self.req(c, "GET", f"/api/publicapi/v1/transactions/{tid}/files/{fid}/download").json()
        fields = (((res.get("Documents") or [{}])[0].get("ExtractedData") or {}).get("RootObject") or {}).get("Fields") or []
        out, items = {}, []
        for f in fields:
            if f.get("Instances"):
                items += [{x["Name"]: (x.get("Value") or {}).get("Value") for x in inst.get("Fields") or []} for inst in f["Instances"]]
                continue
            k = ABBYY_FIELD.get(f["Name"], f["Name"])
            v = f.get("Value") or {}
            out[k] = _f(k, v.get("Value"), v.get("Confidence"))
        return {"fields": out, "items": items, "pages": 1, "orientation": 0, "review_link": st.get("manualReviewLink")}


ENGINES = ("azure_di", "textract_api", "google_docai", "uipath_du", "abbyy_vantage")
_w2.register(AzureDocumentIntelligence(), AwsTextract(), GoogleDocumentAI(), UiPathDocumentUnderstanding(), AbbyyVantage())
