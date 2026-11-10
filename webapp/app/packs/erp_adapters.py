"""ERP adapters (W3, registry id `erp`): SAP S/4HANA, Oracle Fusion Cloud ERP, Oracle Retail MFCS, Dynamics 365
Finance & Operations, Oracle NetSuite and Odoo behind the Connector SDK, each speaking its vendor's own API — sign-in,
paging, errors and writes — and reading the same canonical records (customers, suppliers, products, sales orders,
invoices) plus each platform's scheduled-job history. Oracle Retail MFCS is read-only (its MerchIntegrations publish
services) and its objects can also be pulled into dashboards. SAP ECC and Oracle E-Business Suite come in as exports
(table downloads, CSV), read by the pack. Every write carries X-Relay-Approval (the accepted checkpoint's id).

Mock lab stand-ins (tests/mocklab/sims): sap_s4hana, sap_ecc (files), oracle_fusion, oracle_mfcs, dynamics_fo, netsuite, odoo.
"""
from __future__ import annotations

import base64
import re
import time
import uuid
from urllib.parse import urlsplit

from .. import connectors
from ._systems import ISO3, SysAdapter, day, iso2, num, register, when

ISO3_OF = {v: k for k, v in ISO3.items()}


def _pairs(text: str) -> dict:
    """'GB=lkuk, IN=lkin' -> {"GB": "lkuk", "IN": "lkin"} (a connection setting)."""
    return {k.strip().upper(): v.strip() for k, _, v in (p.partition("=") for p in re.split(r"[,;\s]+", text or "") if "=" in p)}


# ------------------------------------------------------------------ SAP S/4HANA: OData v2 through SAP Gateway, CSRF on writes

SAP = "/sap/opu/odata/sap"
BP, SO, PR, APJ = f"{SAP}/API_BUSINESS_PARTNER", f"{SAP}/API_SALES_ORDER_SRV", f"{SAP}/API_PRODUCT_SRV", f"{SAP}/BC_EXT_APPJOB_MANAGEMENT;v=0002"
SAP_STATUS = {"F": "succeeded", "A": "failed", "R": "running", "S": "queued", "C": "cancelled"}


class SapS4(SysAdapter):
    kind, label, category = "sap_s4hana", "SAP S/4HANA", "erp"
    simulator = "sap_s4hana"
    docs = "https://api.sap.com/api/API_BUSINESS_PARTNER/overview"
    signin = ["password"]
    fields = [("base_url", "Host (https://my-s4.example.com)", True), ("user", "Communication user", True), ("client", "SAP client (e.g. 100)", False),
              ("grouping_customer", "Business partner grouping for new customers (e.g. BP02)", False), ("grouping_supplier", "… and for new suppliers (e.g. BP03)", False)]
    secrets = {"password": ["password"]}
    ENTITIES = {"customer": ("A_BusinessPartner", "Business partners in the customer role"), "supplier": ("A_Supplier", "Business partners in the supplier role"),
                "product": ("A_Product", "Products"), "order": ("A_SalesOrder", "Sales orders")}
    CREATES = ("customer", "supplier")
    WRITABLE = {"customer": {"status": "BusinessPartnerIsBlocked", "email": "EmailAddress", "name": "BusinessPartnerFullName", "city": "CityName"},
                "supplier": {"status": "BusinessPartnerIsBlocked", "email": "EmailAddress", "name": "BusinessPartnerFullName"}}
    DEACTIVATE = {"customer": {"status": "blocked"}, "supplier": {"status": "blocked"}}
    JOBS = "Application jobs"

    def sign_in(self, api):
        tok = base64.b64encode(f"{api.cfg.get('user')}:{api.secret('password')}".encode()).decode()
        return {"Authorization": "Basic " + tok, "Accept": "application/json"}

    def _p(self, api, extra=None) -> dict:
        p = dict(extra or {})
        if api.cfg.get("client"):
            p["sap-client"] = api.cfg["client"]
        return p

    def _all(self, api, path: str, params: dict | None = None) -> list[dict]:
        out, url, p = [], path, self._p(api, params)
        for _ in range(1000):
            d = (api.get(url, p) or {}).get("d") or {}
            out += d.get("results") or []
            if not d.get("__next"):
                return out
            url, p = d["__next"], None                          # SAP's $skiptoken next link carries every parameter
        return out

    def _partners(self, api) -> list[dict]:
        if "bp" not in api.state:
            bps = self._all(api, f"{BP}/A_BusinessPartner")
            tax = {t["BusinessPartner"]: t["BPTaxNumber"] for t in self._all(api, f"{BP}/A_BusinessPartnerTaxNumber") if t.get("BPTaxType") == "IN3"}
            for b in bps:
                b["_tax"] = tax.get(b["BusinessPartner"])
            api.state["bp"] = bps
        return api.state["bp"]

    def fetch(self, api, entity):
        if entity == "customer":
            return [b for b in self._partners(api) if b.get("Customer")]
        if entity == "supplier":
            return [b for b in self._partners(api) if b.get("Supplier")]
        if entity == "product":
            return self._all(api, f"{PR}/A_Product")
        if entity == "order":
            return self._all(api, f"{SO}/A_SalesOrder")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity in ("customer", "supplier"):
            return {"key": r["BusinessPartner"], "number": r.get("Customer") or r.get("Supplier"), "name": r.get("BusinessPartnerFullName"), "email": r.get("EmailAddress") or None,
                    "country": r.get("Country") or None, "city": r.get("CityName") or None, "currency": r.get("Currency") or None, "tax_id": r.get("_tax"),
                    "group": r.get("BusinessPartnerGrouping"), "status": "blocked" if r.get("BusinessPartnerIsBlocked") else "active", "created": day(r.get("CreationDate"))}
        if entity == "product":
            return {"key": r["Product"], "sku": r["Product"], "name": r.get("ProductDescription"), "category": r.get("ProductGroup"), "uom": r.get("BaseUnit"),
                    "status": "blocked" if r.get("IsMarkedForDeletion") else "active"}
        if entity == "order":
            return {"key": r["SalesOrder"], "number": r.get("PurchaseOrderByCustomer"), "customer": r.get("SoldToParty"), "date": day(r.get("SalesOrderDate")),
                    "currency": r.get("TransactionCurrency"), "amount": num(r.get("TotalNetAmount")), "status": r.get("OverallSDProcessStatus")}
        return r

    def runs(self, api):
        out = []
        for j in self._all(api, f"{APJ}/JobHeaderSet"):
            out.append({"job": j["JobTemplateName"], "label": j.get("JobText") or j["JobTemplateName"], "id": f"{j['JobName']}|{j['JobRunCount']}",
                        "started": when(j.get("JobStartDateTime")) or when(j.get("JobPlannedStartDateTime")), "ended": when(j.get("JobEndDateTime")),
                        "status": SAP_STATUS.get(j.get("JobStatus"), "unknown"), "error": None})
        out.sort(key=lambda r: r["started"] or 0, reverse=True)
        seen = set()
        for r in out:                                         # the error text of each job's latest failure, from its job log
            if r["status"] == "failed" and r["job"] not in seen:
                seen.add(r["job"])
                r["error"] = " ".join(self.job_log(api, r))[:500] or None
        return out

    def job_log(self, api, run):
        name, _, count = str(run.get("id") or "").partition("|")
        if not count:
            return []
        msgs = (api.get(f"{APJ}/JobinfoGet", self._p(api, {"JobName": f"'{name}'", "JobRunCount": f"'{count}'"})).get("d") or {}).get("results") or []
        return [m["MessageText"] for m in msgs if m.get("MessageType") in ("E", "A")] or [m["MessageText"] for m in msgs[-2:]]

    def _csrf(self, api, again: bool = False) -> str:
        if again or "csrf" not in api.state:
            r = api.request("GET", f"{BP}/A_BusinessPartner", params=self._p(api, {"$top": 1}), headers={"X-CSRF-Token": "Fetch"})
            self.check(r, "CSRF token")
            api.state["csrf"] = r.headers.get("x-csrf-token") or ""
        return api.state["csrf"]

    def _send(self, api, method, path, body, approval, params=None, ok=(200, 201, 204)):
        for attempt in (0, 1):
            r = api.request(method, path, json=body, params=self._p(api, params), headers={"X-CSRF-Token": self._csrf(api, again=attempt == 1), "Content-Type": "application/json"},
                            approval=approval)
            if r.status_code == 403 and "csrf" in (r.text or "").lower() and attempt == 0:
                continue                                      # the token expired with the session: fetch a new one, once
            return self.check(r, path, ok)
        return {}

    def payload(self, entity, rec):
        if entity not in ("customer", "supplier"):
            return super().payload(entity, rec)
        body = {"BusinessPartnerCategory": "2", "BusinessPartnerGrouping": rec.get("group") or "", "OrganizationBPName1": rec.get("name"), "BusinessPartnerFullName": rec.get("name"),
                "Country": rec.get("country") or "", "CityName": rec.get("city") or "", "EmailAddress": rec.get("email") or "", "Currency": rec.get("currency") or "",
                "to_BusinessPartnerRole": {"results": [{"BusinessPartnerRole": "FLCU01" if entity == "customer" else "FLVN01"}]}}
        if rec.get("tax_id"):
            body["to_BusinessPartnerTax"] = {"results": [{"BPTaxType": "IN3", "BPTaxNumber": rec["tax_id"]}]}
        return body

    def problems(self, c, entity, rec):
        g = (c.get("config") or {}).get(f"grouping_{entity}")
        return [] if g or entity not in ("customer", "supplier") else [f"set the business partner grouping for new {entity}s on the connection (e.g. BP02)"]

    def prepare(self, c, entity, rec):
        g = (c.get("config") or {}).get(f"grouping_{entity}")
        if entity in ("customer", "supplier") and g:
            rec = {**rec, "group": g}                         # a new business partner takes the grouping this S/4HANA uses
        return rec

    def op_create(self, api, entity, rec, approval):
        body = dict(rec)
        if not body.get("BusinessPartnerGrouping"):
            body["BusinessPartnerGrouping"] = api.cfg.get(f"grouping_{entity}") or ""
        d = (self._send(api, "POST", f"{BP}/A_BusinessPartner", body, approval) or {}).get("d") or {}
        return {"id": d.get("BusinessPartner")}

    def op_update(self, api, entity, key, changes, approval):
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on an S/4HANA business partner through Relay")
            body[col] = (str(v).lower() in ("blocked", "true", "x", "1")) if f == "status" else v
        self._send(api, "PATCH", f"{BP}/A_BusinessPartner('{key}')", body, approval)
        return {"id": key}

    def op_rerun(self, api, job, run_id, approval):
        name, _, count = run_id.partition("|")
        d = (self._send(api, "POST", f"{APJ}/JobRestart", None, approval, params={"JobName": f"'{name}'", "JobRunCount": f"'{count}'"}, ok=(200,)) or {}).get("d") or {}
        return {"id": f"{d.get('JobName')}|{d.get('JobRunCount')}", "job": job}

    def op_status(self, api, ref):
        name, _, count = str(ref.get("id") or "").partition("|")
        d = (api.get(f"{APJ}/JobStatusGet", self._p(api, {"JobName": f"'{name}'", "JobRunCount": f"'{count}'"})).get("d") or {})
        st = SAP_STATUS.get(d.get("JobStatus"), "unknown")
        return {"status": st, "error": d.get("StatusText") if st == "failed" else None}


# ------------------------------------------------------------------ Oracle Fusion Cloud ERP: Financials REST + ESS

FIN, ESS = "/fscmRestApi/resources/11.13.18.05", "/ess/rest/scheduler/v1"
ESS_STATUS = {"SUCCEEDED": "succeeded", "WARNING": "warning", "ERROR": "failed", "RUNNING": "running", "WAIT": "queued", "CANCELLED": "cancelled", "BLOCKED": "queued"}


class OracleFusion(SysAdapter):
    kind, label, category = "oracle_fusion", "Oracle Fusion Cloud ERP", "erp"
    simulator = "oracle_fusion"
    docs = "https://docs.oracle.com/en/cloud/saas/financials/24d/farfa/"
    signin = ["password"]
    fields = [("base_url", "Pod URL (https://<pod>.fa.<dc>.oraclecloud.com)", True), ("user", "Integration user", True)]
    secrets = {"password": ["password"]}
    ENTITIES = {"supplier": ("suppliers", "Suppliers"), "invoice": ("invoices", "Payables invoices")}
    WRITABLE = {"invoice": {"site": "SupplierSite", "description": "Description"}}
    JOBS = "Scheduled processes (ESS)"

    def sign_in(self, api):
        return {"Authorization": "Basic " + base64.b64encode(f"{api.cfg.get('user')}:{api.secret('password')}".encode()).decode(), "Accept": "application/json"}

    def _all(self, api, path: str, params: dict | None = None) -> list[dict]:
        out, off = [], 0
        for _ in range(1000):
            b = api.get(path, {"limit": 500, "offset": off, "onlyData": "true", **(params or {})})
            items = b.get("items") or []
            out += items
            if not b.get("hasMore") or not items:
                return out
            off = int(b.get("offset") or off) + len(items)
        return out

    def fetch(self, api, entity):
        if entity == "supplier":
            return self._all(api, f"{FIN}/suppliers")
        if entity == "invoice":
            return self._all(api, f"{FIN}/invoices")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "supplier":
            return {"key": r.get("SupplierNumber"), "number": r.get("SupplierNumber"), "name": r.get("Supplier"), "country": r.get("TaxpayerCountry"),
                    "status": "active" if r.get("Status") == "ACTIVE" else "blocked"}
        if entity == "invoice":
            return {"key": str(r["InvoiceId"]), "number": r.get("InvoiceNumber"), "party": r.get("Supplier"), "date": day(r.get("InvoiceDate")), "currency": r.get("InvoiceCurrency"),
                    "amount": num(r.get("InvoiceAmount")), "status": r.get("ValidationStatus"), "site": r.get("SupplierSite"), "source": r.get("Source"),
                    "business_unit": r.get("BusinessUnit"), "po": r.get("PurchaseOrderNumber")}
        return r

    def runs(self, api):
        out, off = [], 0
        for _ in range(200):
            b = api.get(f"{ESS}/requests", {"limit": 500, "offset": off})
            items = b.get("items") or []
            for x in items:
                jd = str(x.get("jobDefinition") or "")
                pkg, _, name = jd.replace("JobDefinition://", "").rpartition("/")
                out.append({"job": name or jd, "label": x.get("jobDefinitionName") or name, "id": str(x["requestId"]), "started": when(x.get("processStart")),
                            "ended": when(x.get("processEnd")), "status": ESS_STATUS.get(x.get("state"), "unknown"), "error": x.get("errorWarningMessage"), "package": pkg})
            if not b.get("hasMore") or not items:
                break
            off += len(items)
        api.state["pkg"] = {r["job"]: r["package"] for r in out}
        return sorted(out, key=lambda r: r["started"] or 0, reverse=True)

    def op_update(self, api, entity, key, changes, approval):
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a Fusion {entity} through Relay")
            body[col] = v
        r = api.request("PATCH", f"{FIN}/invoices/{key}", json=body, headers={"Content-Type": "application/vnd.oracle.adf.resourceitem+json"}, approval=approval)
        self.check(r, f"invoice {key}", (200,))
        return {"id": key}

    def op_rerun(self, api, job, run_id, approval):
        pkg = (api.state.get("pkg") or {}).get(job)
        if not pkg:
            self.runs(api)
            pkg = (api.state.get("pkg") or {}).get(job)
        r = api.request("POST", f"{FIN}/erpintegrations", json={"OperationName": "submitESSJobRequest", "JobPackageName": pkg, "JobDefName": job, "ESSParameters": "#NULL"},
                        headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, f"submit {job}", (200, 201))
        return {"id": str(b.get("ReqstId")), "job": job}

    def op_status(self, api, ref):
        b = api.get(f"{FIN}/erpintegrations", {"finder": f"ESSJobStatusRF;requestId={ref.get('id')}"})
        st = ((b.get("items") or [{}])[0]).get("RequestStatus")
        out = {"status": ESS_STATUS.get(st, "unknown")}
        if out["status"] in ("failed", "warning"):
            out["error"] = (api.get(f"{ESS}/requests/{ref.get('id')}") or {}).get("errorWarningMessage")
        return out


# ------------------------------------------------------------------ Oracle Retail MFCS: MerchIntegrations ReST publish services, OAuth client credentials

MERCH = "/MerchIntegrations/services"
MFCS_SERVICE = {"product": "foundation/item", "supplier": "foundation/supplier", "store": "foundation/store", "warehouse": "foundation/warehouse",
                "purchase_order": "procurement/order", "transfer": "inventory/transfer", "inventory": "inventory/available"}
MFCS_KEY = {"foundation/item": ("item",), "foundation/supplier": ("supplier",), "foundation/store": ("store",), "foundation/warehouse": ("warehouse",),
            "procurement/order": ("orderNo",), "inventory/transfer": ("transferNo",), "inventory/available": ("locationType", "location", "item")}
MFCS_LINES = {"purchase_order_line": ("purchase_order", ("orderNo", "supplier", "status", "currencyCode", "notBeforeDate", "notAfterDate", "location")),
              "transfer_line": ("transfer", ("transferNo", "fromLocation", "toLocation", "status", "deliveryDate"))}


class OracleRetailMFCS(SysAdapter):
    """Oracle Retail Merchandising Foundation Cloud Service through its MerchIntegrations ReST publish services, signed in
    with an OAuth client of the retailer's identity domain (client credentials, scope rgbu:merch:MFCS-<ENV>; basic
    authentication is no longer accepted since 22.1). Read-only: the publish services download; nothing is written to
    MFCS through Relay. Items and supplier sites are the ERP module's canonical products and suppliers; every object —
    purchase-order and transfer lines included — can be pulled whole into a dashboard."""
    kind, label, category = "oracle_mfcs", "Oracle Retail MFCS", "erp"
    simulator = "oracle_mfcs"
    docs = "https://docs.oracle.com/en/industries/retail/retail-merchandising-foundation-cloud/23.1.201.0/rmsob/restful-web-services.htm"
    signin = ["service_account"]
    fields = [("base_url", "Merchandising URL up to …-mfcs (https://<host>/<customer environment>-mfcs)", True),
              ("token_url", "Identity domain token URL (https://idcs-….identity.oraclecloud.com/oauth2/v1/token)", True),
              ("client_id", "OAuth client id (made in Retail Home)", True),
              ("scope", "Scope (rgbu:merch:MFCS-PRD; …-STG, …-UAT for other environments)", True)]
    secrets = {"service_account": ["client_secret"]}
    can_write = False
    extract = True
    PAGE = 1000
    ENTITIES = {"product": ("items", "Items (Item publish)"), "supplier": ("suppliers", "Supplier sites"), "store": ("stores", "Stores"),
                "warehouse": ("warehouses", "Warehouses, physical and virtual"), "purchase_order": ("purchase_orders", "Purchase orders"),
                "purchase_order_line": ("purchase_order_lines", "Purchase order lines (item × location)"), "transfer": ("transfers", "Transfers"),
                "transfer_line": ("transfer_lines", "Transfer lines"), "inventory": ("available_inventory", "Stock on hand and available, by item and location")}

    def base(self, c):
        u = str((c.get("config") or {}).get("base_url") or "").strip().rstrip("/")
        return re.sub(r"(?i)/MerchIntegrations(/services)?$", "", u)          # the services' own path is added per call

    def sign_in(self, api):
        token_url = str(api.cfg.get("token_url") or "").strip()
        if not token_url.startswith(("http://", "https://")):
            raise connectors.ConnectorError("The identity domain token URL must start with https:// (…/oauth2/v1/token).")
        basic = base64.b64encode(f"{api.cfg.get('client_id') or ''}:{api.secret('client_secret')}".encode()).decode()
        r = api.raw("POST", token_url, data={"grant_type": "client_credentials", "scope": str(api.cfg.get("scope") or "").strip()},
                    headers={"Authorization": "Basic " + basic, "Accept": "application/json"})
        if r.status_code != 200:
            raise connectors.Reconsent(f"The identity domain refused the OAuth client ({r.status_code}): {self.error_text(r)}")
        tok = (r.json() if r.content else {}).get("access_token")
        if not tok:
            raise connectors.Reconsent("The identity domain answered without an access token.")
        return {"Authorization": "Bearer " + tok, "Accept": "application/json"}

    def _all(self, api, service: str, params: dict | None = None) -> list[dict]:
        """Every page of one publish service. Keyset paging: the server's next link carries offsetkey and the same since /
        before window; its query is replayed on the configured host as sent (links can name an internal host)."""
        path, p, out = f"{MERCH}/{service}", {"limit": self.PAGE, **(params or {})}, []
        for _ in range(100_000):
            b = api.get(path, p) or {}
            items = b.get("items") or []
            out += items
            if not b.get("hasMore") or not items:
                return out
            nxt = next((ln.get("href") for ln in b.get("links") or [] if ln.get("rel") == "next" and ln.get("href")), None)
            q = urlsplit(nxt).query if nxt else ""
            if q:
                path, p = f"{MERCH}/{service}?{q}", None
            else:                                                     # no next link: carry on after the last record's key
                path, p = f"{MERCH}/{service}", {**{"limit": self.PAGE, **(params or {})}, "offsetkey": ",".join(str(items[-1].get(k)) for k in MFCS_KEY[service])}
        return out

    def fetch(self, api, entity):
        if entity in MFCS_SERVICE:
            if ("mfcs", entity) not in api.state:                     # read once per session (lines come from their orders and transfers)
                api.state[("mfcs", entity)] = self._all(api, MFCS_SERVICE[entity])
            return api.state[("mfcs", entity)]
        if entity in MFCS_LINES:
            parent, keep = MFCS_LINES[entity]
            return [{**{k: h.get(k) for k in keep}, **ln} for h in self.fetch(api, parent) for ln in h.get("details") or []]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "product":
            return {"key": r.get("item"), "sku": r.get("item"), "name": r.get("itemDescription"), "category": r.get("departmentName") or str(r.get("department") or ""),
                    "uom": r.get("standardUom"), "price": num(r.get("unitRetail")), "status": "active" if r.get("status") == "A" else "inactive",
                    "supplier": r.get("primarySupplier"), "cost": num(r.get("unitCost"))}
        if entity == "supplier":
            return {"key": str(r.get("supplier")), "number": str(r.get("supplier")), "name": r.get("supplierName"), "email": r.get("contactEmail") or None,
                    "country": iso2(r.get("country")) if r.get("country") else None, "currency": r.get("currencyCode"), "terms": r.get("terms"),
                    "status": "active" if r.get("supplierStatus") == "A" else "blocked"}
        return r

    def test(self, c):
        api = self.session(c)
        try:
            stores, whs = self.fetch(api, "store"), self.fetch(api, "warehouse")
            api.get(f"{MERCH}/foundation/item", {"limit": 1})
            return {"ok": True, "sees": f"{len(stores)} store(s) and {len(whs)} warehouse(s); items, supplier sites, purchase orders, transfers and stock "
                                        "readable through the MerchIntegrations publish services"}
        finally:
            api.close()


# ------------------------------------------------------------------ Dynamics 365 Finance & Operations: OData v4 at /data, Entra sign-in

D365_STATUS = {"Finished": "succeeded", "Error": "failed", "Executing": "running", "Waiting": "queued", "Canceled": "cancelled", "Withhold": "queued", "Ended": "succeeded"}


class Dynamics365FO(SysAdapter):
    kind, label, category = "dynamics_fo", "Dynamics 365 Finance & Operations", "erp"
    simulator = "dynamics_fo"
    docs = "https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/odata"
    signin = ["service_account"]
    fields = [("base_url", "Environment URL (https://<env>.operations.dynamics.com)", True), ("tenant", "Entra tenant id", True), ("client_id", "App (client) id", True),
              ("companies", "Legal entity per country (e.g. GB=lkuk, IN=lkin)", False), ("resource", "Resource (optional: the environment URL)", False),
              ("authority", "Sign-in endpoint (optional: a national cloud)", False)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"customer": ("CustomersV3", "Customers (all legal entities)"), "supplier": ("VendorsV2", "Vendors"), "product": ("ReleasedProductsV2", "Released products"),
                "order": ("SalesOrderHeadersV2", "Sales order headers")}
    CREATES = ("customer",)
    WRITABLE = {"customer": {"status": "OnHoldStatus", "email": "PrimaryContactEmail", "credit_limit": "CreditLimit", "tax_id": "TaxExemptNumber", "group": "CustomerGroupId", "city": "AddressCity"}}
    DEACTIVATE = {"customer": {"status": "blocked"}}
    JOBS = "Batch jobs"

    def sign_in(self, api):
        auth = (api.cfg.get("authority") or "https://login.microsoftonline.com").rstrip("/")
        res = (api.cfg.get("resource") or api.cfg.get("base_url") or "").rstrip("/")
        r = api.raw("POST", f"{auth}/{api.cfg.get('tenant')}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": api.cfg.get("client_id"),
                                                                                       "client_secret": api.secret("client_secret"), "scope": f"{res}/.default"})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Entra ID refused the app's sign-in: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json", "OData-Version": "4.0"}

    def _all(self, api, path, params=None):
        out, url, p = [], path, {"cross-company": "true", **(params or {})}
        for _ in range(1000):
            b = api.get(url, p)
            out += b.get("value") or []
            if not b.get("@odata.nextLink"):
                return out
            url, p = b["@odata.nextLink"], None
        return out

    def fetch(self, api, entity):
        if entity in self.ENTITIES:
            return self._all(api, f"/data/{self.ENTITIES[entity][0]}")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "customer":
            return {"key": f"{r['dataAreaId']}/{r['CustomerAccount']}", "number": r["CustomerAccount"], "name": r.get("OrganizationName"), "email": r.get("PrimaryContactEmail") or None,
                    "country": iso2(r.get("AddressCountryRegionId")), "city": r.get("AddressCity") or None, "currency": r.get("SalesCurrencyCode"), "tax_id": r.get("TaxExemptNumber") or None,
                    "credit_limit": num(r.get("CreditLimit")), "group": r.get("CustomerGroupId"), "status": "active" if r.get("OnHoldStatus") in ("No", None, "") else "blocked",
                    "company": r["dataAreaId"]}
        if entity == "supplier":
            return {"key": f"{r['dataAreaId']}/{r['VendorAccountNumber']}", "number": r["VendorAccountNumber"], "name": r.get("VendorOrganizationName"), "country": iso2(r.get("AddressCountryRegionId")),
                    "currency": r.get("CurrencyCode"), "terms": r.get("PaymentTermsName"), "status": "active" if r.get("OnHoldStatus") in ("No", None, "") else "blocked"}
        if entity == "product":
            return {"key": f"{r['dataAreaId']}/{r['ItemNumber']}", "sku": r["ItemNumber"], "name": r.get("ProductName"), "category": r.get("ProductGroupId"), "uom": r.get("InventoryUnitSymbol"),
                    "price": num(r.get("SalesPrice")), "status": "active"}
        if entity == "order":
            return {"key": f"{r['dataAreaId']}/{r['SalesOrderNumber']}", "number": r["SalesOrderNumber"], "customer": r.get("OrderingCustomerAccountNumber"), "date": day(r.get("RequestedShippingDate")),
                    "currency": r.get("CurrencyCode"), "amount": num(r.get("OrderTotalAmount")), "status": r.get("SalesOrderStatus")}
        return r

    def runs(self, api):
        out = [{"job": j["JobDescription"], "label": j["JobDescription"], "id": str(j["BatchJobRecId"]), "started": when(j.get("StartDateTime")) or when(j.get("ScheduledDateTime")),
                "ended": when(j.get("EndDateTime")), "status": D365_STATUS.get(j.get("Status"), "unknown"), "error": j.get("Message") or None}
               for j in self._all(api, "/data/BatchJobs", {})]
        return sorted(out, key=lambda r: r["started"] or 0, reverse=True)

    def payload(self, entity, rec):
        if entity != "customer":
            return super().payload(entity, rec)
        body = {"OrganizationName": rec.get("name"), "CustomerGroupId": rec.get("group") or "", "SalesCurrencyCode": rec.get("currency") or "",
                "AddressCountryRegionId": ISO3_OF.get(str(rec.get("country") or ""), rec.get("country") or ""), "AddressCity": rec.get("city") or "",
                "PrimaryContactEmail": rec.get("email") or "", "TaxExemptNumber": rec.get("tax_id") or "", "_country": rec.get("country")}
        if rec.get("credit_limit") not in (None, ""):
            body["CreditLimit"] = num(rec["credit_limit"])
        return body

    def problems(self, c, entity, rec):
        out = []
        if entity == "customer":
            if not rec.get("group"):
                out.append("Dynamics 365 needs a customer group (CustomerGroupId): map one, or give a constant in the mapping")
            if str(rec.get("country") or "").upper() not in _pairs((c.get("config") or {}).get("companies")):
                out.append(f"no legal entity is set for country {rec.get('country')} on the connection (Companies, e.g. GB=lkuk)")
        return out

    def op_create(self, api, entity, rec, approval):
        body = {k: v for k, v in rec.items() if not k.startswith("_")}
        body["dataAreaId"] = _pairs(api.cfg.get("companies")).get(str(rec.get("_country") or "").upper()) or ""
        r = api.request("POST", "/data/CustomersV3", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        b = self.check(r, "CustomersV3", (201,))
        return {"id": f"{b.get('dataAreaId')}/{b.get('CustomerAccount')}"}

    def op_update(self, api, entity, key, changes, approval):
        company, _, acct = str(key).partition("/")
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a Dynamics 365 customer through Relay")
            body[col] = ("All" if str(v).lower() == "blocked" else "No") if f == "status" else num(v) if f == "credit_limit" else v
        r = api.request("PATCH", f"/data/CustomersV3(dataAreaId='{company}',CustomerAccount='{acct}')", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        self.check(r, f"customer {key}", (204, 200))
        return {"id": key}

    def op_rerun(self, api, job, run_id, approval):
        r = api.request("POST", "/data/BatchJobs/Microsoft.Dynamics.DataEntities.SetBatchJobToWaiting", json={"batchJobRecId": int(run_id)}, headers={"Content-Type": "application/json"}, approval=approval)
        self.check(r, f"batch job {run_id}", (200,))
        return {"id": run_id, "job": job}

    def op_status(self, api, ref):
        rows = api.get("/data/BatchJobs", {"$filter": f"BatchJobRecId eq {ref.get('id')}"}).get("value") or [{}]
        st = D365_STATUS.get(rows[0].get("Status"), "unknown")
        return {"status": st, "error": rows[0].get("Message") or None}


# ------------------------------------------------------------------ Oracle NetSuite: REST record service + SuiteQL, OAuth 2.0 M2M

NS_STATUS = {"COMPLETE": "succeeded", "FAILED": "failed", "PROCESSING": "running", "PENDING": "queued", "RETRY": "queued", "CANCELED": "cancelled"}


class NetSuite(SysAdapter):
    kind, label, category = "netsuite", "Oracle NetSuite", "erp"
    simulator = "netsuite"
    docs = "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1540391670.html"
    signin = ["service_account"]
    fields = [("base_url", "REST base (https://<account>.suitetalk.api.netsuite.com/services/rest)", True), ("account_id", "Account id", True),
              ("client_id", "Integration record's client id", True), ("certificate_id", "Certificate id (kid)", True), ("token_url", "Token endpoint (optional: <REST base>/auth/oauth2/v1/token)", False),
              ("subsidiaries", "Subsidiary per country (e.g. GB=1, IN=2)", False)]
    secrets = {"service_account": ["private_key"]}
    ENTITIES = {"customer": ("customer", "Customer records"), "invoice": ("invoice", "Customer invoices (transactions)")}
    CREATES = ("customer",)
    WRITABLE = {"customer": {"status": "isInactive", "email": "email", "name": "companyName", "credit_limit": "creditLimit", "tax_id": "defaultTaxReg"}}
    DEACTIVATE = {"customer": {"status": "blocked"}}
    JOBS = "Scheduled and map/reduce scripts"

    def sign_in(self, api):
        import jwt
        tok_url = api.cfg.get("token_url") or f"{api.base}/auth/oauth2/v1/token"
        now = int(time.time())
        kid = api.cfg.get("certificate_id")
        try:
            assertion = jwt.encode({"iss": api.cfg.get("client_id"), "scope": ["rest_webservices"], "aud": tok_url, "iat": now, "exp": now + 3000, "kid": kid},
                                   api.secret("private_key"), algorithm="PS256", headers={"kid": kid})
        except (ValueError, TypeError) as e:
            raise connectors.Reconsent(f"The stored private key cannot sign the NetSuite assertion: {e}") from e
        r = api.raw("POST", tok_url, data={"grant_type": "client_credentials", "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": assertion})
        if r.status_code != 200:
            raise connectors.Reconsent(f"NetSuite refused the M2M sign-in: {self.error_text(r)}")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def throttled(self, r):
        return r.status_code == 429

    def retry_after(self, r):
        return None                                          # NetSuite sends no Retry-After: exponential backoff

    def _ids(self, api, kind):
        ids, url, p = [], f"/record/v1/{kind}", {"limit": 1000}
        for _ in range(1000):
            b = api.get(url, p)
            ids += [i["id"] for i in b.get("items") or []]
            nxt = next((x["href"] for x in b.get("links") or [] if x.get("rel") == "next"), None)
            if not nxt:
                return ids
            url, p = nxt, None
        return ids

    def suiteql(self, api, q):
        out, url, p = [], "/query/v1/suiteql", {"limit": 1000}
        for _ in range(1000):
            r = api.request("POST", url, params=p, json={"q": q}, headers={"Prefer": "transient", "Content-Type": "application/json"})
            b = self.check(r, "SuiteQL", (200,))
            out += [{k: v for k, v in i.items() if k != "links"} for i in b.get("items") or []]
            nxt = next((x["href"] for x in b.get("links") or [] if x.get("rel") == "next"), None)
            if not nxt:
                return out
            url, p = nxt, None
        return out

    def fetch(self, api, entity):
        if entity == "customer":
            subs = {v: k for k, v in _pairs(api.cfg.get("subsidiaries")).items()}
            rows = [api.get(f"/record/v1/customer/{i}") for i in self._ids(api, "customer")]
            for r in rows:
                r["_country"] = subs.get(str((r.get("subsidiary") or {}).get("id")))
            return rows
        if entity == "invoice":
            return self.suiteql(api, "SELECT id, tranid, entity, trandate, foreigntotal, currency, status FROM transaction WHERE type = 'CustInvc'")
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "customer":
            return {"key": r["id"], "number": r.get("entityId"), "name": r.get("companyName"), "email": r.get("email") or None, "country": r.get("_country"),
                    "currency": (r.get("currency") or {}).get("refName"), "tax_id": r.get("defaultTaxReg") or None, "credit_limit": num(r.get("creditLimit")),
                    "status": "blocked" if r.get("isInactive") else "active", "created": day(r.get("dateCreated")), "subsidiary": (r.get("subsidiary") or {}).get("refName")}
        if entity == "invoice":
            return {"key": r["id"], "number": r.get("tranid"), "party": r.get("entity"), "date": day(r.get("trandate")), "amount": num(r.get("foreigntotal")), "status": r.get("status"),
                    "currency_id": r.get("currency")}
        return r

    def runs(self, api):
        inst = self.suiteql(api, "SELECT taskid, script, scriptdeployment, status, startdate, enddate FROM scheduledscriptinstance ORDER BY startdate DESC")
        notes = self.suiteql(api, "SELECT scripttype, title, detail, date FROM scriptnote WHERE type = 'ERROR'")
        err = {(n["scripttype"], n["date"]): n["detail"] for n in notes}
        return [{"job": i["script"], "label": i["script"], "id": i["taskid"], "started": when(i.get("startdate")), "ended": when(i.get("enddate")), "status": NS_STATUS.get(i.get("status"), "unknown"),
                 "error": err.get((i["script"], i.get("enddate"))), "deployment": i.get("scriptdeployment")} for i in inst]

    def payload(self, entity, rec):
        if entity != "customer":
            return super().payload(entity, rec)
        body = {"companyName": rec.get("name"), "email": rec.get("email") or "", "defaultTaxReg": rec.get("tax_id") or "", "_country": rec.get("country")}
        if rec.get("credit_limit") not in (None, ""):
            body["creditLimit"] = num(rec["credit_limit"])
        return body

    def problems(self, c, entity, rec):
        if entity == "customer" and str(rec.get("country") or "").upper() not in _pairs((c.get("config") or {}).get("subsidiaries")):
            return [f"no NetSuite subsidiary is set for country {rec.get('country')} on the connection (Subsidiaries, e.g. GB=1)"]
        return []

    def op_create(self, api, entity, rec, approval):
        body = {k: v for k, v in rec.items() if not k.startswith("_")}
        body["subsidiary"] = {"id": _pairs(api.cfg.get("subsidiaries")).get(str(rec.get("_country") or "").upper()) or ""}
        r = api.request("POST", "/record/v1/customer", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        self.check(r, "customer", (204,))
        return {"id": (r.headers.get("Location") or "").rstrip("/").rsplit("/", 1)[-1]}

    def op_update(self, api, entity, key, changes, approval):
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a NetSuite customer through Relay")
            body[col] = (str(v).lower() == "blocked") if f == "status" else num(v) if f == "credit_limit" else v
        r = api.request("PATCH", f"/record/v1/customer/{key}", json=body, headers={"Content-Type": "application/json"}, approval=approval)
        self.check(r, f"customer {key}", (204,))
        return {"id": key}


# ------------------------------------------------------------------ Odoo: external JSON-RPC (database, login and API key on every call)



class Odoo(SysAdapter):
    kind, label, category = "odoo", "Odoo", "erp"
    simulator = "odoo"
    docs = "https://www.odoo.com/documentation/17.0/developer/reference/external_api.html"
    signin = ["api_key"]
    fields = [("base_url", "Odoo URL (https://<company>.odoo.com)", True), ("db", "Database", True), ("login", "Login (the integration user)", True)]
    secrets = {"api_key": ["api_key"]}
    ENTITIES = {"customer": ("res.partner (customers)", "Contacts with a customer rank"), "supplier": ("res.partner (vendors)", "Contacts with a vendor rank"),
                "product": ("product.product", "Product variants"), "order": ("sale.order", "Sales orders"), "invoice": ("account.move", "Customer invoices")}
    CREATES = ("customer", "supplier")
    WRITABLE = {"customer": {"status": "active", "email": "email", "name": "name", "city": "city", "tax_id": "vat"}, "supplier": {"status": "active", "email": "email", "name": "name"}}
    DEACTIVATE = {"customer": {"status": "blocked"}, "supplier": {"status": "blocked"}}
    JOBS = "Scheduled actions (ir.cron)"

    def expired(self, r):
        try:
            return r.status_code == 200 and (r.json().get("error") or {}).get("code") == 100
        except ValueError:
            return False

    def sign_in(self, api):
        uid = self._rpc(api, "common", "authenticate", [api.cfg.get("db"), api.cfg.get("login"), api.secret("api_key"), {}], signed=False)
        if not uid:
            raise connectors.Reconsent("Odoo refused the login or the API key.")
        api.state["uid"] = uid
        return {"Content-Type": "application/json"}

    def _rpc(self, api, service, method, args, approval=None, signed=True):
        body = {"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}, "id": uuid.uuid4().int % 10 ** 6}
        r = api.request("POST", "/jsonrpc", json=body, approval=approval, signed=signed, headers={"Content-Type": "application/json"})
        b = self.check(r, f"{service}.{method}", (200,))
        if b.get("error"):
            e = b["error"].get("data") or {}
            if e.get("name") == "odoo.exceptions.AccessDenied":
                raise connectors.Reconsent("Odoo refused the API key (AccessDenied). Renew the connection.")
            raise connectors.ConnectorError(f"Odoo: {e.get('message') or b['error'].get('message')}")
        return b.get("result")

    def ex(self, api, model, method, args, kw=None, approval=None):
        if api.headers is None:
            api.headers = self.sign_in(api)
        return self._rpc(api, "object", "execute_kw", [api.cfg.get("db"), api.state["uid"], api.secret("api_key"), model, method, args, kw or {}], approval=approval)

    def _all(self, api, model, domain, fields):
        out, off = [], 0
        for _ in range(1000):
            page = self.ex(api, model, "search_read", [domain], {"fields": fields, "offset": off, "limit": 200, "order": "id"})
            out += page or []
            if not page or len(page) < 200:
                return out
            off += 200
        return out

    ALL = ["|", ["active", "=", True], ["active", "=", False]]

    def fetch(self, api, entity):
        if entity in ("customer", "supplier"):
            rank = "customer_rank" if entity == "customer" else "supplier_rank"
            return self._all(api, "res.partner", [[rank, ">", 0], *self.ALL], ["name", "email", "city", "country_id", "vat", "active", "ref", "create_date", "company_id"])
        if entity == "product":
            return self._all(api, "product.product", self.ALL, ["name", "default_code", "list_price", "categ_id", "uom_id", "active"])
        if entity == "order":
            return self._all(api, "sale.order", [], ["name", "partner_id", "date_order", "amount_total", "currency_id", "state"])
        if entity == "invoice":
            return self._all(api, "account.move", [["move_type", "=", "out_invoice"]], ["name", "partner_id", "invoice_date", "amount_total", "currency_id", "payment_state"])
        return super().fetch(api, entity)

    def canon(self, entity, r):
        m2o = lambda v: v[1] if isinstance(v, list) and len(v) > 1 else None  # noqa: E731
        if entity in ("customer", "supplier"):
            return {"key": str(r["id"]), "number": r.get("ref") or None, "name": r.get("name"), "email": r.get("email") or None, "country": iso2(m2o(r.get("country_id"))),
                    "city": r.get("city") or None, "tax_id": r.get("vat") or None, "status": "active" if r.get("active") else "blocked", "created": day(r.get("create_date")),
                    "company": m2o(r.get("company_id"))}
        if entity == "product":
            return {"key": str(r["id"]), "sku": r.get("default_code"), "name": r.get("name"), "category": m2o(r.get("categ_id")), "uom": m2o(r.get("uom_id")), "price": num(r.get("list_price")),
                    "status": "active" if r.get("active") else "blocked"}
        if entity == "order":
            return {"key": str(r["id"]), "number": r.get("name"), "customer": str((r.get("partner_id") or [None])[0]), "date": day(r.get("date_order")), "currency": m2o(r.get("currency_id")),
                    "amount": num(r.get("amount_total")), "status": r.get("state")}
        if entity == "invoice":
            return {"key": str(r["id"]), "number": r.get("name"), "party": m2o(r.get("partner_id")), "date": day(r.get("invoice_date")), "currency": m2o(r.get("currency_id")),
                    "amount": num(r.get("amount_total")), "status": r.get("payment_state")}
        return r

    def runs(self, api):
        crons = {str(c["id"]): c.get("cron_name") or c.get("display_name") for c in self._all(api, "ir.cron", self.ALL, ["cron_name", "display_name"])}
        logs = self.ex(api, "ir.logging", "search_read", [[["path", "ilike", "ir_cron"]]], {"fields": ["create_date", "level", "message"], "order": "id desc", "limit": 2000}) or []
        out = []
        for x in logs:
            m = re.search(r"\((\d+)\) done|in Job #(\d+)", str(x.get("message") or ""))     # Odoo's own log lines name the job
            job = (m.group(1) or m.group(2)) if m else ""
            if not job:
                continue
            msg = str(x.get("message") or "")
            out.append({"job": job, "label": crons.get(job) or job, "id": str(x["id"]), "started": when(x.get("create_date")), "ended": when(x.get("create_date")),
                        "status": "failed" if x.get("level") == "ERROR" else "succeeded", "error": msg.strip().splitlines()[-1][:500] if x.get("level") == "ERROR" else None})
        return out

    def payload(self, entity, rec):
        if entity not in ("customer", "supplier"):
            return super().payload(entity, rec)
        return {"name": rec.get("name"), "is_company": True, "email": rec.get("email") or False, "city": rec.get("city") or False, "vat": rec.get("tax_id") or False,
                "ref": rec.get("number") or False, ("customer_rank" if entity == "customer" else "supplier_rank"): 1, "_country": rec.get("country")}

    def _country_id(self, api, cc: str):
        """Odoo's own id for a country: res.country by its code, else what the existing contacts carry (never a guess)."""
        if not cc:
            return None
        try:
            hit = self.ex(api, "res.country", "search_read", [[["code", "=", cc]]], {"fields": ["code"], "limit": 1})
            if hit:
                return hit[0]["id"]
        except connectors.ConnectorError:
            pass
        if "countries" not in api.state:
            api.state["countries"] = {}
            for r in self._all(api, "res.partner", self.ALL, ["country_id"]):
                if isinstance(r.get("country_id"), list):
                    api.state["countries"][iso2(r["country_id"][1])] = r["country_id"][0]
        return api.state["countries"].get(cc)

    def problems(self, c, entity, rec):
        return [] if rec.get("country") else ["Odoo needs the country to file the contact under"]

    def op_create(self, api, entity, rec, approval):
        body = {k: v for k, v in rec.items() if not k.startswith("_")}
        cid = self._country_id(api, str(rec.get("_country") or ""))
        if cid:
            body["country_id"] = cid
        return {"id": str(self.ex(api, "res.partner", "create", [body], approval=approval))}

    def op_update(self, api, entity, key, changes, approval):
        vals = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on an Odoo contact through Relay")
            vals[col] = (str(v).lower() != "blocked") if f == "status" else v
        self.ex(api, "res.partner", "write", [[int(key)], vals], approval=approval)
        return {"id": key}

    def op_rerun(self, api, job, run_id, approval):
        try:
            self.ex(api, "ir.cron", "method_direct_trigger", [[int(job)]], approval=approval)
            return {"id": job, "job": job, "status": "succeeded"}
        except connectors.Reconsent:
            raise
        except connectors.ConnectorError as e:                # the run happened and failed: a result, not a refused write
            return {"id": job, "job": job, "status": "failed", "error": str(e)[:300]}

    def op_status(self, api, ref):
        return {"status": ref.get("status") or "unknown", "error": ref.get("error")}


ADAPTERS = [register(a) for a in (SapS4(), OracleFusion(), OracleRetailMFCS(), Dynamics365FO(), NetSuite(), Odoo())]
