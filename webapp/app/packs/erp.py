"""ERP (registry id `erp`) on the workbench - SAP S/4HANA, SAP ECC, Oracle Fusion ERP / SCM, Oracle Retail MFCS, Oracle
E-Business Suite, Dynamics 365 F&O, Oracle NetSuite and Odoo.

Assess   Connect -> Inventory -> Health -> Findings -> Estimate: every object in the system's own terms (business partners,
         CustomersV3, res.partner, MFCS items and supplier sites ...) with counts and usage, its scheduled jobs with their run history, and - from ECC
         exports - the custom objects with their usage and the S/4HANA simplification items their code hits. Rules: jobs
         that keep failing (with the vendor's error), duplicate customers and suppliers, GSTINs missing or malformed,
         blocked masters, custom code that breaks in S/4HANA, custom objects nobody ran in 90 days.
Develop  Describe -> Shape -> Build -> Prove -> Ship -> Run: an inbound interface - records from an upload mapped onto the
         system's fields (rules first), a dry run against its own rules and what it already holds, a named approval, one
         approved write (X-Relay-Approval), then Relay reads the system back and reconciles record by record.
Change   Request -> Diagnose -> Fix -> Prove -> Approve -> Learn: a failing job diagnosed from its own log (the exchange rate
         SAP and Dynamics 365 miss, Fusion's invalid supplier site, NetSuite's usage limit, Odoo's duplicate IRN), or a
         duplicate customer blocked; the change proposed, dry-run, released with approval, checked on the system and
         kept as a rule. The agent drafts a reading of a log only where no rule recognises the error.
Migrate  Discover -> Decide -> Convert -> Prove -> Hand over -> Run: master data between ERPs - ECC (table downloads) to
         S/4HANA, on-premises to cloud - keep / merge / retire with reasons, a crosswalk for every source record, counts,
         fingerprints, control totals and every record compared before the load and after it.
Run      Watch -> Alert -> Fix -> Approve -> Report: the jobs on a schedule; a break goes to a Change item, Self-healing or a
         ticket only after a person approves.
"""
from __future__ import annotations

import re
from collections import Counter

from .. import db
from .. import workbench as wb
from . import _systems as w3
from . import erp_adapters  # noqa: F401 - registers the ERP adapters with the Connector SDK and the Connections hub

MODULE = "erp"

# S/4HANA simplification items (https://me.sap.com/sic) that custom code reading these tables or calling these modules runs into
SIMPLIFICATION = {
    "VBUK": ("SD simplified data model", "document status moved from VBUK / VBUP into VBAK / VBAP / LIKP: read the status from the document tables"),
    "VBUP": ("SD simplified data model", "item status moved into VBAP / LIPS: read it there"),
    "BSID": ("Financials data model (ACDOCA)", "the index tables BSID / BSAD / BSIK / BSAK are compatibility views on the universal journal: read ACDOCA or the released views"),
    "BSAD": ("Financials data model (ACDOCA)", "BSAD is a compatibility view on ACDOCA: read the universal journal"),
    "BSIK": ("Financials data model (ACDOCA)", "BSIK is a compatibility view on ACDOCA: read the universal journal"),
    "BSAK": ("Financials data model (ACDOCA)", "BSAK is a compatibility view on ACDOCA: read the universal journal"),
    "KONV": ("Pricing data model", "pricing conditions moved from KONV to PRCD_ELEMENTS"),
    "BAPI_CUSTOMER_CREATEFROMDATA1": ("Business partner approach (CVI)", "customers are business partners in S/4HANA: create them through API_BUSINESS_PARTNER or the BP BAPIs"),
    "XD01": ("Business partner approach (CVI)", "customer master transactions are replaced by transaction BP"),
    "XK01": ("Business partner approach (CVI)", "vendor master transactions are replaced by transaction BP"),
}


def custom_objects(ctx, seen) -> list[dict]:
    """ECC custom objects (TADIR_Z), what their code uses (CUSTOM_CODE_SCAN) and how often they ran (SCMON_USAGE)."""
    files = {f["name"].lower(): f for f in ctx.files(w3.UPLOADS)}
    tadir = next((f for n, f in files.items() if "tadir" in n), None)
    if not tadir:
        return []
    _, objs = w3.upload_rows(ctx, tadir)
    uses: dict[str, list] = {}
    scan = next((f for n, f in files.items() if "custom_code" in n), None)
    if scan:
        for r in w3.upload_rows(ctx, scan)[1]:
            uses.setdefault(r.get("OBJ_NAME"), []).append(r.get("USES"))
    runs: dict[str, int] = {}
    usage = next((f for n, f in files.items() if "scmon" in n), None)
    if usage:
        for r in w3.upload_rows(ctx, usage)[1]:
            runs[r.get("OBJ_NAME")] = int(w3.num(r.get("EXECUTIONS_90D")) or 0)
    rows = [{"key": o.get("OBJ_NAME"), "name": o.get("TEXT"), "type": o.get("OBJECT"), "package": o.get("DEVCLASS"), "uses": ", ".join(uses.get(o.get("OBJ_NAME"), [])),
             "executions_90d": runs.get(o.get("OBJ_NAME"))} for o in objs]
    f = w3.snap(ctx, "inv-ecc-custom", rows)
    return [{"id": "ecc:custom", "include": True, "system": "SAP ECC (exports)", "platform": "Export (upload)", "object": "TADIR (customer namespace)", "what": "Custom objects and their code",
             "records": len(rows), "usage": f"{sum(1 for r in rows if (r['executions_90d'] or 0) > 0)} ran in the last 90 days" if usage else "no usage file", "file": f, "entity": "custom"}]


def _custom(inv) -> list[tuple[str, list[dict]]]:
    return [(it["system"], w3.read_csv(inv.ctx.dir / "data" / it["file"])) for it in inv.items if it.get("entity") == "custom" and it.get("file")]


def rule_s4_readiness(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in _custom(inv):
        for r in rows:
            hits = [(u, SIMPLIFICATION[u]) for u in (x.strip() for x in str(r.get("uses") or "").split(",")) if u in SIMPLIFICATION]
            if hits:
                ran = int(w3.num(r.get("executions_90d")) or 0)
                out.append(w3.finding("s4_simplification", system, "custom", r["key"], f"{r['key']} ({r.get('name')}) uses {', '.join(u for u, _ in hits)}: "
                                      + "; ".join(f"{item} - {how}" for _, (item, how) in hits), "high" if ran else "low", measured=f"{ran} executions in 90 days",
                                      fix="Adapt the code before the conversion (or retire it if nobody runs it).", work="migrate"))
    return out


rule_s4_readiness.label = "Custom code that changes in S/4HANA (simplification items)"


def rule_unused_custom(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in _custom(inv):
        idle = [r for r in rows if str(r.get("executions_90d") or "") != "" and int(w3.num(r.get("executions_90d")) or 0) == 0]
        if idle:
            out.append(w3.finding("unused_custom", system, "custom", f"{len(idle)} custom objects", f"{len(idle)} custom object(s) did not run in 90 days: {', '.join(r['key'] for r in idle)}",
                                  "low", measured=", ".join(r["key"] for r in idle), fix="Retire them before the conversion: less code to adapt and test.", work="migrate",
                                  keys=[r["key"] for r in idle]))
    return out


rule_unused_custom.label = "Custom objects nobody ran in 90 days"


def propose_site(ctx, c, a, api, run) -> list[dict]:
    """Fusion's Import Payables Invoices rejects lines whose supplier site is not defined: the site each affected
    supplier's other invoices carry is the proposal (from the data, never a guess)."""
    m = re.search(r"site (\S+) is not defined", run.get("error") or "", re.I)
    bad = m.group(1) if m else None
    invs = a.records(api, "invoice")
    good: dict[str, Counter] = {}
    for i in invs:
        if i.get("site") and i["site"] != bad:
            good.setdefault(i["party"], Counter())[i["site"]] += 1
    out = []
    for i in invs:
        if bad and i.get("site") == bad:
            best = good.get(i["party"], Counter()).most_common(1)
            out.append({"action": "update", "entity": "invoice", "key": i["key"], "label": f"Invoice {i['number']} ({i['party']})", "field": "site", "value": best[0][0] if best else "",
                        "before": bad, "why": f"{i['party']}'s other invoices use site {best[0][0]}" if best else "no other invoice of this supplier shows its site: type it in"})
    return out


SIGNATURES = [
    w3.Signature(r"No exchange rate found for (\w+)/(\w+)|Exchange rate for currency (\w+) to (\w+) on \S+ was not found",
                 "the INR/GBP exchange rate for the valuation date is not maintained, so the valuation stops",
                 "Maintain the rate for that date (SAP: Currency Exchange Rates, rate type M; Dynamics 365: Currencies > Exchange rates), then run the job again.", route="change"),
    w3.Signature(r"INVALID SUPPLIER SITE", "invoices from the capture robot carry a supplier site the supplier does not have (LEEDS-HQ)",
                 "Correct the site on those invoices to the supplier's own site, then submit Import Payables Invoices again.", propose=propose_site, route="change"),
    w3.Signature(r"SSS_USAGE_LIMIT_EXCEEDED", "the map/reduce script runs out of governance units in its map stage",
                 "Lower the batch size or yield in the map stage and redeploy the script (SuiteCloud), then let it run again.", route="ticket"),
    w3.Signature(r"Duplicate IRN|error 2150", "the e-invoice portal already holds an IRN for that invoice, so Odoo's retry is refused",
                 "Fetch the existing IRN for the invoice from the portal (or cancel it there), record it on the invoice, then trigger the sync.", route="change"),
    w3.Signature(r"Customer group' must be filled in|Field 'Customer group'", "import rows arrive without a customer group",
                 "Fill CustomerGroupId in the source file or map a default group in the import project.", route="ticket"),
]

SPEC = w3.Spec(
    module=MODULE, noun="ERP", system="Relay ERP", entities=("customer", "supplier", "product", "order", "invoice"),
    rules=[w3.rule_failing_jobs, w3.rule_duplicates("customer"), w3.rule_duplicates("supplier"), w3.rule_tax_ids("customer"), w3.rule_blocked("customer"),
           rule_s4_readiness, rule_unused_custom],
    signatures=SIGNATURES, minutes={"s4_simplification": 240, "unused_custom": 15},
    upload_entities={"kna1": "customer", "lfa1": "supplier", "mara": "product", "vbak": "order", "tadir": "custom", "custom_code": "custom", "scmon": "custom",
                     "customer": "customer", "supplier": "supplier", "vendor": "supplier", "item": "product", "product": "product"},
    inventory_extra=custom_objects, creates=("customer", "supplier"), measures={"customer": ("credit_limit", "currency")})

PLATFORMS = {
    "sap": w3.SysPlatform("SAP S/4HANA, and SAP ECC exports", ("sap_s4hana",), "tests/mocklab/sims: sap_s4hana (OData v2, CSRF, Application Jobs) and sap_ecc (SE16N table downloads)",
                          "business partners, products, sales orders and application jobs through the person's communication user; ECC as KNA1 / LFA1 / MARA / VBAK downloads and its custom-code scan",
                          uploads=(".txt", ".csv", ".xlsx")),
    "oracle": w3.SysPlatform("Oracle Fusion Cloud ERP, and E-Business Suite exports", ("oracle_fusion",), "tests/mocklab/sims: oracle_fusion (Financials REST + ESS)",
                             "suppliers, Payables invoices and scheduled processes (ESS); E-Business Suite as CSV exports", uploads=(".csv", ".xlsx")),
    "mfcs": w3.SysPlatform("Oracle Retail MFCS", ("oracle_mfcs",), "tests/mocklab/sims: oracle_mfcs (MerchIntegrations ReST publish services, OAuth 2.0 client credentials)",
                           "items, supplier sites, stores, warehouses, purchase orders, transfers and stock through the MerchIntegrations publish services (read-only); "
                           "or CSV exports", uploads=(".csv", ".xlsx")),
    "dynamics": w3.SysPlatform("Dynamics 365 Finance & Operations", ("dynamics_fo",), "tests/mocklab/sims: dynamics_fo (OData data entities, BatchJobs, DMF)",
                               "customers, vendors, released products, sales orders (all legal entities) and batch jobs"),
    "netsuite": w3.SysPlatform("Oracle NetSuite", ("netsuite",), "tests/mocklab/sims: netsuite (REST record service, SuiteQL, OAuth 2.0 M2M)",
                               "customer records, invoices and script runs (SuiteQL)"),
    "odoo": w3.SysPlatform("Odoo", ("odoo",), "tests/mocklab/sims: odoo (external JSON-RPC)", "contacts, products, sales orders, invoices and scheduled actions"),
}


def _kinds() -> set:
    return {k for p in PLATFORMS.values() for k in p.kinds}


def _cards(u: dict) -> list[dict]:
    rows = [[r["signature"][:60], r["cause"][:120], r["fix"][:120], r["uses"], wb._when(r["updated"])] for r in w3.learned(MODULE)]
    return [{"title": "Fixes Relay learned", "columns": ["Error it recognises", "Cause", "Fix", "Used", "When"], "rows": rows,
             "empty": "None yet: a Change item that fixes a job keeps its fix here, and the next diagnosis uses it."}]


GUIDE = """# ERP - the work item

This folder is one work item of Relay's ERP module (SAP S/4HANA, SAP ECC, Oracle Fusion, Oracle Retail MFCS, Dynamics
365 F&O, NetSuite, Odoo and Oracle EBS exports). Rules do the reading, mapping, checks and reconciliation; the agent is asked
only to read a job log that no rule recognises.

- `diagnose.json` (written by the app before your run): the failing jobs with no known cause - each with its run
  history and the vendor's own log lines.
- `diagnosis.yaml`: what you write when asked - `jobs:` mapping each job id to `cause` and `fix` (one sentence each).
- `data/`: the person's uploads and Relay's read-only snapshots (CSV); `evidence/`: what earlier steps measured.

Never invent a table, a field, a number or a setting the log does not name; say "the log does not say" instead."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS, cards=_cards,
    lineage="each ERP and object read (system -> entity), an interface as a flow that writes into the ERP, a migration as feeds edges from the source objects to the target's",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "Inventory the ERP - configuration, customisation and usage - and find what fails"),
        "develop": w3.develop_work(SPEC, "Bring records into the ERP through its API: mapping agreed, a dry run, one approved write, read back"),
        "change": w3.change_work(SPEC, "Fix a failing job or a bad record, diagnosed from the vendor's own log, released with approval"),
        "migrate": w3.migrate_work(SPEC, "Move master data between ERPs - ECC to S/4HANA, on-premises to cloud - reconciled record by record", _kinds),
        "run": w3.run_work(SPEC, "Watch the ERP's jobs and integrations; breaks go to a person first"),
    }))
