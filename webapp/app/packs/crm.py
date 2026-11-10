"""CRM & sales (registry id `crm`) on the workbench — Salesforce and HubSpot through their APIs; Dynamics 365 CE, Zoho CRM
and Freshsales through their exports.

Assess   accounts / companies, contacts and opportunities in each CRM's own terms, the batch jobs and imports with
         their history; rules: jobs that keep failing (Salesforce's ERP sync batch with UNABLE_TO_LOCK_ROW, HubSpot's
         nightly import refusing rows with INVALID_EMAIL), duplicate accounts (Hilltop Grocers twice), contacts without
         an e-mail, opportunities past their close date still open.
Develop  new accounts from an upload into the CRM: mapping suggested and corrected, a dry run against the CRM's own
         rules and duplicates (Salesforce's duplicate rule would refuse them anyway), a named approver, one approved
         write, read back and reconciled.
Change   a failing job diagnosed from its own log, a duplicate merged (a step for a person in the CRM's duplicate
         management — Relay has no merge API to call) or an account corrected, released with approval.
Migrate  accounts between CRMs (HubSpot → Salesforce …): keep / merge / retire, crosswalk, counts, fingerprints and every
         record compared before and after the approved load.
Run      the batch jobs and imports on a schedule; breaks go to a Change item, Self-healing or a ticket after approval.
"""
from __future__ import annotations

import time

from .. import workbench as wb
from . import _systems as w3
from . import crm_adapters  # noqa: F401 - registers Salesforce and HubSpot with the Connector SDK and the Connections hub

MODULE = "crm"


def rule_contacts(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("contact"):
        bad = [r for r in rows if not r.get("email") or not w3.EMAIL.match(str(r.get("email")))]
        if bad:
            out.append(w3.finding("missing_email", system, "contact", f"{len(bad)} contacts", f"{len(bad)} contact(s) without a usable e-mail: campaigns and invoices cannot reach them",
                                  "low", measured=", ".join(str(r.get("name")) for r in bad[:6]), fix="Ask the account owners for the e-mail, or retire the contact.", work="change",
                                  keys=[r["key"] for r in bad]))
    return out


rule_contacts.label = "Contacts without a usable e-mail"


def rule_stale_deals(ctx, inv, spec=None) -> list[dict]:
    out = []
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for system, rows in inv.rows("deal"):
        late = [r for r in rows if r.get("close_date") and r["close_date"] < today and not str(r.get("stage") or "").lower().startswith("closed")]
        if late:
            out.append(w3.finding("stale_deal", system, "deal", f"{len(late)} opportunities", f"{len(late)} open opportunit(ies) past their close date: the pipeline overstates the quarter",
                                  "medium", measured=", ".join(str(r.get("name")) for r in late[:5]), fix="Ask the owners to move the close date or close them.", work="change"))
    return out


rule_stale_deals.label = "Open opportunities past their close date"

SIGNATURES = [
    w3.Signature(r"UNABLE_TO_LOCK_ROW", "the ERP sync batch updates the same accounts as another job at the same time, so Salesforce cannot lock the rows",
                 "Move the sync to a slot nothing else locks the accounts in, or lower its batch scope and order the records by parent account; then let it run again.", route="change"),
    w3.Signature(r"INVALID_EMAIL", "the ERP sends customer e-mails HubSpot refuses (a double dot in the domain)",
                 "Correct the e-mails in the ERP's customer master — the import takes them the next night.", route="ticket"),
    w3.Signature(r"DUPLICATES_DETECTED", "the account already exists: Salesforce's duplicate rule refuses a second one", "Use the existing account, or merge the two first.", route="change"),
    w3.Signature(r"REQUEST_LIMIT_EXCEEDED", "the org has used its daily API calls", "Spread the integration's calls over the day or raise the limit with Salesforce.", route="ticket"),
]

SPEC = w3.Spec(
    module=MODULE, noun="CRM", system="Relay CRM", entities=("customer", "contact", "deal"),
    rules=[w3.rule_failing_jobs, w3.rule_duplicates("customer"), rule_contacts, rule_stale_deals, w3.rule_blocked("customer")],
    signatures=SIGNATURES, minutes={"missing_email": 5, "stale_deal": 15},
    upload_entities={"account": "customer", "compan": "customer", "contact": "contact", "opportunit": "deal", "deal": "deal", "lead": "contact"},
    creates=("customer",), measures={})

PLATFORMS = {
    "salesforce": w3.SysPlatform("Salesforce", ("salesforce",), "tests/mocklab/sims: salesforce (REST, SOQL, AsyncApexJob)", "accounts, contacts, opportunities and asynchronous Apex jobs through the connected app"),
    "hubspot": w3.SysPlatform("HubSpot", ("hubspot",), "tests/mocklab/sims: hubspot (CRM API v3)", "companies, contacts and imports with their row errors through the private app"),
    "exports": w3.SysPlatform("Dynamics 365 CE, Zoho CRM, Freshsales (exports)", (), "export fixtures the tests write", "accounts, contacts and opportunities you upload (CSV, Excel)", uploads=(".csv", ".xlsx", ".json")),
}


def _kinds() -> set:
    return {k for p in PLATFORMS.values() for k in p.kinds}


GUIDE = """# CRM & sales — the work item

Relay's CRM module reads accounts, contacts, opportunities and the CRM's job history, and moves records between CRMs
with a record-by-record reconciliation. Rules do the reading, mapping and checks; the agent is asked only to read a job
log no rule recognises (diagnose.json → diagnosis.yaml, as WORK.md of the ERP module describes). Never invent a record,
a field or a number."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each CRM and object read (system → entity), an interface as a flow that writes into the CRM, a migration as feeds edges from the source CRM's objects to the target's",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See what the CRM holds — duplicates, stale pipeline, failing syncs"),
        "develop": w3.develop_work(SPEC, "Bring accounts into the CRM: mapping agreed, a dry run, one approved write, read back"),
        "change": w3.change_work(SPEC, "Fix a failing sync or a duplicate account, diagnosed from the CRM's own log, released with approval"),
        "migrate": w3.migrate_work(SPEC, "Move accounts between CRMs, reconciled record by record", _kinds),
        "run": w3.run_work(SPEC, "Watch the CRM's batch jobs and imports; breaks go to a person first"),
    }))
