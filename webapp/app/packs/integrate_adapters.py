"""Finance & accounting adapters (W3, registry id `integrate`): TallyPrime (XML over HTTP), Zoho Books (API v3),
QuickBooks Online (Accounting API v3) and Xero (Accounting API 2.0) behind the Connector SDK. Oracle Fusion Cloud
Financials is the ERP module's adapter (one connection serves both modules); Busy, ClearTax and the GST / TRACES / MCA
portals come in as exports.

Canonical records: ledger accounts (with their debits, credits and balance - a trial balance), voucher lines, customers
and invoices (with place of supply and GSTIN for GSTR-1). Writes carry X-Relay-Approval: Tally masters and vouchers
(Import Data), Zoho Books accounts, journals and invoice corrections.

Mock lab stand-ins (tests/mocklab/sims/finance.py): tally, zoho_books, quickbooks, xero.
"""
from __future__ import annotations

import base64
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from .. import connectors
from ._systems import SysAdapter, day, num, register

TALLY_TYPE = {"Sundry Debtors": "asset", "Bank Accounts": "asset", "Cash-in-Hand": "asset", "Current Assets": "asset", "Fixed Assets": "asset",
              "Sundry Creditors": "liability", "Duties & Taxes": "liability", "Current Liabilities": "liability", "Capital Account": "equity",
              "Sales Accounts": "income", "Direct Incomes": "income", "Indirect Incomes": "income", "Purchase Accounts": "expense", "Direct Expenses": "expense", "Indirect Expenses": "expense"}


def _tb(lines: list[dict]) -> dict:
    """Debits and credits per account from voucher lines."""
    out: dict[str, dict] = {}
    for ln in lines:
        a = out.setdefault(ln["account"], {"debit": 0.0, "credit": 0.0})
        a["debit"] += float(ln.get("debit") or 0)
        a["credit"] += float(ln.get("credit") or 0)
    return out


# ------------------------------------------------------------------ TallyPrime: Export Data / Import Data envelopes on the XML port

class Tally(SysAdapter):
    kind, label, category = "tally", "TallyPrime", "finance"
    simulator = "tally"
    docs = "https://help.tallysolutions.com/developer-reference/integration-using-xml-interface/"
    signin = ["api_key"]                      # the XML port takes no sign-in at all (a finding the health check reports)
    fields = [("base_url", "XML port (http://<tally host>:9000)", True), ("company", "Company (as loaded in Tally)", True)]
    secrets = {"api_key": []}
    ENTITIES = {"account": ("List of Accounts (ledgers)", "Ledgers with their group and movements"), "voucher": ("Day Book", "Voucher lines"),
                "customer": ("Sundry Debtors", "Party ledgers of customers")}
    CREATES = ("account",)
    JOBS = "Voucher imports"

    def sign_in(self, api):
        return {"Content-Type": "text/xml"}

    def expired(self, r):
        return False

    def throttled(self, r):
        return r.status_code == 503                          # "Tally is busy": nothing was processed, so a retry is safe

    def error_text(self, r):
        try:
            x = ET.fromstring(r.content)
            return x.findtext(".//LINEERROR") or r.text[:200]
        except ET.ParseError:
            return r.text[:200]

    def _post(self, api, xml: str, approval: str | None = None) -> ET.Element:
        r = api.request("POST", "/", content=xml.encode("utf-8"), headers={"Content-Type": "text/xml"}, approval=approval)
        if r.status_code != 200:
            raise connectors.ConnectorError(f"TallyPrime: {r.status_code} {self.error_text(r)}")
        try:
            x = ET.fromstring(r.content)
        except ET.ParseError as e:
            raise connectors.ConnectorError(f"TallyPrime answered something that is not XML: {e}") from e
        if x.tag == "RESPONSE" and x.findtext("LINEERROR") and not x.findtext("CREATED"):
            raise connectors.ConnectorError(f"TallyPrime: {x.findtext('LINEERROR')}")
        return x

    def _export(self, api, report: str, extra: str = "") -> ET.Element:
        company = escape(api.cfg.get("company") or "")
        return self._post(api, f"<ENVELOPE><HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER><BODY><EXPORTDATA><REQUESTDESC><REPORTNAME>{report}</REPORTNAME>"
                               f"<STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT><SVCURRENTCOMPANY>{company}</SVCURRENTCOMPANY>{extra}</STATICVARIABLES>"
                               f"</REQUESTDESC></EXPORTDATA></BODY></ENVELOPE>")

    def _lines(self, api) -> list[dict]:
        if "lines" not in api.state:
            out = []
            for v in self._export(api, "Day Book").iter("VOUCHER"):
                for n, e in enumerate(v.iter("ALLLEDGERENTRIES.LIST")):
                    amt = float(e.findtext("AMOUNT") or 0)
                    out.append({"key": f"{v.findtext('GUID') or v.get('REMOTEID')}:{n}", "number": v.findtext("VOUCHERNUMBER"), "date": day(v.findtext("DATE")),
                                "type": v.findtext("VOUCHERTYPENAME") or v.get("VCHTYPE"), "account": e.findtext("LEDGERNAME"), "debit": round(-amt, 2) if amt < 0 else 0.0,
                                "credit": round(amt, 2) if amt > 0 else 0.0, "party": v.findtext("PARTYLEDGERNAME")})
            api.state["lines"] = out
        return api.state["lines"]

    def fetch(self, api, entity):
        if entity in ("account", "customer"):
            led = [{"name": l.get("NAME"), "parent": l.findtext("PARENT"), "gstin": l.findtext("PARTYGSTIN"), "state": l.findtext("LEDSTATENAME"),
                    "opening": float(l.findtext("OPENINGBALANCE") or 0)} for l in self._export(api, "List of Accounts", "<ACCOUNTTYPE>Ledgers</ACCOUNTTYPE>").iter("LEDGER")]
            if entity == "customer":
                return [l for l in led if l["parent"] == "Sundry Debtors"]
            tb = _tb(self._lines(api))
            for l in led:
                l.update(tb.get(l["name"]) or {"debit": 0.0, "credit": 0.0})
            return led
        if entity == "voucher":
            return self._lines(api)
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "account":
            dr, cr = round(r.get("debit") or 0, 2), round(r.get("credit") or 0, 2)
            return {"key": r["name"], "name": r["name"], "group": r.get("parent"), "type": TALLY_TYPE.get(r.get("parent") or "", "other"), "debit": dr, "credit": cr,
                    "balance": round(dr - cr + (r.get("opening") or 0), 2), "gstin": r.get("gstin")}
        if entity == "customer":
            return {"key": r["name"], "name": r["name"], "country": "IN", "tax_id": r.get("gstin") or None, "status": "active", "state": r.get("state")}
        return r

    def payload(self, entity, rec):
        if entity == "account":
            return {"name": rec.get("name") or rec.get("key"), "group": rec.get("group") or ""}
        return super().payload(entity, rec)

    def op_create(self, api, entity, rec, approval):
        if entity != "account":
            raise connectors.ConnectorError(f"TallyPrime takes ledgers here, not {entity}")
        xml = (f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>All Masters</REPORTNAME>"
               f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(api.cfg.get('company') or '')}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>"
               f"<TALLYMESSAGE><LEDGER NAME={quoteattr(rec['name'])} ACTION=\"Create\"><PARENT>{escape(rec.get('group') or '')}</PARENT></LEDGER></TALLYMESSAGE>"
               f"</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
        x = self._post(api, xml, approval)
        if (x.findtext("CREATED") or "0") == "0":
            raise connectors.ConnectorError(f"TallyPrime: {x.findtext('LINEERROR') or 'the ledger was not created'}")
        return {"id": rec["name"]}


# ------------------------------------------------------------------ Zoho Books: API v3, refresh-token grant, organization_id on every call

class ZohoBooks(SysAdapter):
    kind, label, category = "zoho_books", "Zoho Books", "finance"
    simulator = "zoho_books"
    docs = "https://www.zoho.com/books/api/v3/introduction/"
    signin = ["api_key"]
    fields = [("base_url", "API domain (https://www.zohoapis.in)", True), ("accounts_url", "Accounts server (https://accounts.zoho.in)", True),
              ("client_id", "Client id (Zoho API console)", True), ("organization_id", "Organisation id", True)]
    secrets = {"api_key": ["client_secret", "refresh_token"]}
    ENTITIES = {"account": ("chartofaccounts", "Chart of accounts"), "customer": ("contacts", "Customers"), "invoice": ("invoices", "Invoices"), "voucher": ("journals", "Journal lines")}
    CREATES = ("account", "journal")
    WRITABLE = {"invoice": {"place_of_supply": "place_of_supply"}}

    def sign_in(self, api):
        r = api.raw("POST", f"{(api.cfg.get('accounts_url') or '').rstrip('/')}/oauth/v2/token",
                    params={"refresh_token": api.secret("refresh_token"), "client_id": api.cfg.get("client_id"), "client_secret": api.secret("client_secret"), "grant_type": "refresh_token"})
        b = r.json() if r.content else {}
        if r.status_code != 200 or not b.get("access_token"):
            raise connectors.Reconsent(f"Zoho refused the refresh token: {b.get('error') or r.status_code}")
        return {"Authorization": "Zoho-oauthtoken " + b["access_token"], "Accept": "application/json"}

    def _p(self, api, extra=None):
        return {"organization_id": api.cfg.get("organization_id"), **(extra or {})}

    def check(self, r, what, ok=(200, 201, 202, 204)):
        b = super().check(r, what, ok)
        if isinstance(b, dict) and b.get("code") not in (None, 0):
            raise connectors.ConnectorError(f"Zoho Books - {what}: {b.get('code')} {b.get('message')}")
        return b

    def _all(self, api, path, key):
        out, page, per = [], 1, 200
        for _ in range(1000):
            b = api.get(path, self._p(api, {"page": page, "per_page": per}))
            rows = b.get(key) or []
            out += rows
            if not (b.get("page_context") or {}).get("has_more_page") or not rows:
                return out
            if len(rows) < per:                               # the organisation caps the page: carry on at the size it serves
                per = len(rows)
            page = len(out) // per + 1
        return out

    def fetch(self, api, entity):
        if entity == "account":
            return self._all(api, "/books/v3/chartofaccounts", "chartofaccounts")
        if entity == "customer":
            return [c for c in self._all(api, "/books/v3/contacts", "contacts") if c.get("contact_type") == "customer"]
        if entity == "invoice":
            gst = {c["contact_id"]: c for c in self._all(api, "/books/v3/contacts", "contacts")}
            rows = self._all(api, "/books/v3/invoices", "invoices")
            for r in rows:
                c = gst.get(r.get("customer_id")) or {}
                r["_gstin"], r["_pos"] = c.get("gst_no") or None, c.get("place_of_contact")
            return rows
        if entity == "voucher":
            return [{**ln, "_j": j} for j in self._all(api, "/books/v3/journals", "journals") for ln in j.get("line_items") or []]
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "account":
            return {"key": r["account_id"], "name": r.get("account_name"), "group": r.get("account_type"), "type": r.get("account_type"), "code": r.get("account_code"),
                    "status": "active" if r.get("is_active", True) else "blocked"}
        if entity == "customer":
            return {"key": r["contact_id"], "name": r.get("contact_name"), "email": r.get("email") or None, "country": "IN", "tax_id": r.get("gst_no") or None,
                    "status": "active" if r.get("status") == "active" else "blocked", "created": day(r.get("created_time")), "place": r.get("place_of_contact")}
        if entity == "invoice":
            return {"key": r["invoice_id"], "number": r.get("invoice_number"), "party": r.get("customer_name"), "date": day(r.get("date")), "currency": r.get("currency_code"),
                    "amount": num(r.get("total")), "tax": num(r.get("tax_total")), "status": r.get("status"), "place_of_supply": r.get("place_of_supply") or None, "gstin": r.get("_gstin"),
                    "customer_place": r.get("_pos"), "gst_treatment": r.get("gst_treatment"), "customer_id": r.get("customer_id")}
        if entity == "voucher":
            j = r.get("_j") or {}
            amt = num(r.get("amount")) or 0
            return {"key": f"{j.get('journal_id')}:{r.get('line_id')}", "number": j.get("entry_number"), "date": day(j.get("journal_date")), "type": "journal",
                    "account": r.get("account_name"), "debit": amt if r.get("debit_or_credit") == "debit" else 0.0, "credit": amt if r.get("debit_or_credit") == "credit" else 0.0,
                    "reference": j.get("reference_number")}
        return r

    def payload(self, entity, rec):
        if entity == "account":
            return {"account_name": rec.get("name"), "account_type": rec.get("type") or rec.get("group"), "account_code": rec.get("code") or ""}
        return super().payload(entity, rec)

    def op_create(self, api, entity, rec, approval):
        if entity == "account":
            r = api.request("POST", "/books/v3/chartofaccounts", params=self._p(api), json={k: v for k, v in rec.items() if v not in (None, "")}, approval=approval)
            return {"id": (self.check(r, "chartofaccounts", (201,)).get("chart_of_account") or {}).get("account_id")}
        if entity == "journal":
            ids = {a["account_name"]: a["account_id"] for a in self.fetch(api, "account")}
            lines = []
            for ln in rec.get("lines") or []:
                if ln["account"] not in ids:
                    raise connectors.ConnectorError(f"Zoho Books has no account {ln['account']!r} for the journal")
                for side in ("debit", "credit"):
                    if float(ln.get(side) or 0):
                        lines.append({"account_id": ids[ln["account"]], "debit_or_credit": side, "amount": round(float(ln[side]), 2), "description": ln.get("description") or ""})
            r = api.request("POST", "/books/v3/journals", params=self._p(api), json={"journal_date": rec.get("date"), "reference_number": rec.get("reference") or "",
                                                                                    "notes": rec.get("notes") or "", "line_items": lines}, approval=approval)
            j = self.check(r, "journals", (201,)).get("journal") or {}
            return {"id": j.get("journal_id"), "number": j.get("entry_number")}
        return super().op_create(api, entity, rec, approval)

    def field_problems(self, entity, field, value):
        if entity == "invoice" and field == "place_of_supply" and str(value) not in GST_STATE:
            return [f"{value!r} is not a state code GST knows (KA, MH, TN ...)"]
        return []

    def op_update(self, api, entity, key, changes, approval):
        body = {}
        for f, v in changes.items():
            col = self.WRITABLE.get(entity, {}).get(f)
            if not col:
                raise connectors.ConnectorError(f"{f} cannot be changed on a Zoho Books {entity} through Relay")
            body[col] = v
        self.check(api.request("PUT", f"/books/v3/invoices/{key}", params=self._p(api), json=body, approval=approval), f"invoice {key}", (200,))
        return {"id": key}


# ------------------------------------------------------------------ QuickBooks Online: query language, refresh-token grant, realm in the path

class QuickBooks(SysAdapter):
    kind, label, category = "quickbooks", "QuickBooks Online", "finance"
    simulator = "quickbooks"
    docs = "https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/invoice"
    signin = ["api_key"]
    fields = [("base_url", "API base (https://quickbooks.api.intuit.com)", True), ("realm_id", "Company (realm) id", True), ("client_id", "App client id", True),
              ("token_url", "Token endpoint (optional: Intuit's)", False)]
    secrets = {"api_key": ["client_secret", "refresh_token"]}
    ENTITIES = {"customer": ("Customer", "Customers"), "invoice": ("Invoice", "Invoices")}
    can_write = False

    def sign_in(self, api):
        url = api.cfg.get("token_url") or "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        basic = base64.b64encode(f"{api.cfg.get('client_id')}:{api.secret('client_secret')}".encode()).decode()
        r = api.raw("POST", url, data={"grant_type": "refresh_token", "refresh_token": api.secret("refresh_token")}, headers={"Authorization": "Basic " + basic, "Accept": "application/json"})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Intuit refused the refresh token ({r.status_code}).")
        return {"Authorization": "Bearer " + r.json()["access_token"], "Accept": "application/json"}

    def error_text(self, r):
        try:
            e = (r.json().get("Fault") or r.json().get("fault") or {})
            err = (e.get("Error") or e.get("error") or [{}])[0]
            return f"{err.get('code')} {err.get('Message') or err.get('message')}: {err.get('Detail') or err.get('detail') or ''}"
        except ValueError:
            return super().error_text(r)

    def fetch(self, api, entity):
        if entity not in self.ENTITIES:
            return super().fetch(api, entity)
        out, st = [], 1
        for _ in range(1000):
            b = api.get(f"/v3/company/{api.cfg.get('realm_id')}/query", {"query": f"select * from {self.ENTITIES[entity][0]} startposition {st} maxresults 1000", "minorversion": 73})
            rows = (b.get("QueryResponse") or {}).get(self.ENTITIES[entity][0]) or []
            out += rows
            if len(rows) < 1000:
                return out
            st += 1000
        return out

    def canon(self, entity, r):
        if entity == "customer":
            return {"key": r["Id"], "name": r.get("DisplayName"), "email": (r.get("PrimaryEmailAddr") or {}).get("Address"), "currency": (r.get("CurrencyRef") or {}).get("value"),
                    "status": "active" if r.get("Active", True) else "blocked", "created": day((r.get("MetaData") or {}).get("CreateTime"))}
        if entity == "invoice":
            return {"key": r["Id"], "number": r.get("DocNumber"), "party": (r.get("CustomerRef") or {}).get("value"), "date": day(r.get("TxnDate")), "currency": (r.get("CurrencyRef") or {}).get("value"),
                    "amount": num(r.get("TotalAmt")), "status": "paid" if not num(r.get("Balance")) else "open"}
        return r


# ------------------------------------------------------------------ Xero: client credentials (custom connection), xero-tenant-id on every call

class Xero(SysAdapter):
    kind, label, category = "xero", "Xero", "finance"
    simulator = "xero"
    docs = "https://developer.xero.com/documentation/api/accounting/invoices"
    signin = ["service_account"]
    fields = [("base_url", "API base (https://api.xero.com)", True), ("tenant_id", "Organisation (tenant) id", True), ("client_id", "Custom connection's client id", True),
              ("token_url", "Token endpoint (optional: Xero's)", False)]
    secrets = {"service_account": ["client_secret"]}
    ENTITIES = {"customer": ("Contacts", "Contacts"), "invoice": ("Invoices", "Invoices")}
    can_write = False

    def sign_in(self, api):
        url = api.cfg.get("token_url") or "https://identity.xero.com/connect/token"
        basic = base64.b64encode(f"{api.cfg.get('client_id')}:{api.secret('client_secret')}".encode()).decode()
        r = api.raw("POST", url, data={"grant_type": "client_credentials", "scope": "accounting.transactions accounting.contacts"}, headers={"Authorization": "Basic " + basic})
        if r.status_code != 200:
            raise connectors.Reconsent(f"Xero refused the custom connection's sign-in ({r.status_code}).")
        return {"Authorization": "Bearer " + r.json()["access_token"], "xero-tenant-id": api.cfg.get("tenant_id") or "", "Accept": "application/json"}

    def fetch(self, api, entity):
        if entity == "customer":
            return api.get("/api.xro/2.0/Contacts").get("Contacts") or []
        if entity == "invoice":
            out, page = [], 1
            for _ in range(1000):
                b = api.get("/api.xro/2.0/Invoices", {"page": page, "pageSize": 1000})
                out += b.get("Invoices") or []
                if page >= int((b.get("pagination") or {}).get("pageCount") or 1):
                    return out
                page += 1
            return out
        return super().fetch(api, entity)

    def canon(self, entity, r):
        if entity == "customer":
            return {"key": r["ContactID"], "name": r.get("Name"), "email": r.get("EmailAddress") or None, "status": "active" if r.get("ContactStatus") == "ACTIVE" else "blocked"}
        if entity == "invoice":
            return {"key": r["InvoiceID"], "number": r.get("InvoiceNumber"), "party": (r.get("Contact") or {}).get("Name"), "date": day(r.get("DateString")), "currency": r.get("CurrencyCode"),
                    "amount": num(r.get("Total")), "tax": num(r.get("TotalTax")), "status": (r.get("Status") or "").lower()}
        return r


ADAPTERS = [register(a) for a in (Tally(), ZohoBooks(), QuickBooks(), Xero())]
GST_STATE = {"JK": "01", "HP": "02", "PB": "03", "CH": "04", "UT": "05", "HR": "06", "DL": "07", "RJ": "08", "UP": "09", "BR": "10", "SK": "11", "AR": "12", "NL": "13", "MN": "14",
             "MZ": "15", "TR": "16", "ML": "17", "AS": "18", "WB": "19", "JH": "20", "OR": "21", "CT": "22", "MP": "23", "GJ": "24", "MH": "27", "KA": "29", "GA": "30", "LD": "31",
             "KL": "32", "TN": "33", "PY": "34", "AN": "35", "TG": "36", "AP": "37", "LA": "38"}


def state_of_gstin(g: str | None) -> str | None:
    """The state a GSTIN is registered in (its first two digits), as the 2-letter code Zoho and the GST portal use."""
    m = re.match(r"(\d{2})", str(g or ""))
    return next((k for k, v in GST_STATE.items() if m and v == m.group(1)), None)
