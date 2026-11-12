"""HR & payroll (registry id `hr`) on the workbench - Workday and SAP SuccessFactors through their APIs; Oracle Fusion HCM,
Zoho People, Darwinbox and Keka through their exports. Personal data is read only as far as the work needs (name, work
e-mail, department, status, dates) and never leaves the work item's folder.

Assess   workers in each system's own terms with leavers, and each system's integration runs; rules: a payroll or
         benefits integration that keeps failing (the India payroll export: a worker without a bank account on the
         payment election), leavers in the last 90 days whose access must go (Identity & access checks the accounts),
         workers without a work e-mail or a department, the same person twice.
Develop  joiners from an upload into SuccessFactors: mapping suggested and corrected, a dry run against the rules (user
         id, work e-mail, no one hired twice), a named approver, one approved write, read back and reconciled.
Change   a failing integration diagnosed from its own run history, the worker's record corrected or the run started
         again after approval.
Migrate  workers between HR systems (Workday -> SuccessFactors ...): keep / merge / retire, crosswalk, proven record by record.
Run      the integrations on a schedule; breaks go to a Change item, Self-healing or a ticket after approval.
"""
from __future__ import annotations

import time

from .. import workbench as wb
from . import _systems as w3
from . import hr_adapters  # noqa: F401 - registers Workday and SuccessFactors with the Connector SDK and the Connections hub

MODULE = "hr"
LEAVER_DAYS = 90


def rule_leavers(ctx, inv, spec=None) -> list[dict]:
    """Leavers in the last 90 days: their accounts must be switched off - a finding per system for Identity & access."""
    out = []
    cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - LEAVER_DAYS * 86400))
    for system, rows in inv.rows("worker"):
        gone = [r for r in rows if r.get("status") == "terminated" and (r.get("end_date") or "") >= cut]
        if gone:
            who = ", ".join(f"{r.get('name')} on {r.get('end_date')}" for r in gone[:3])
            out.append(w3.finding("leaver", system, "worker", ", ".join(str(r.get("key")) for r in gone[:6]),
                                  f"{len(gone)} leaver(s) in the last {LEAVER_DAYS} days ({who}): their accounts must be switched off",
                                  "high", measured=", ".join(str(r.get("name")) for r in gone[:6]), fix="Check their accounts in Entra ID and Okta (Identity & access) and switch them off.",
                                  work="change", keys=[r["key"] for r in gone]))
    return out


rule_leavers.label = f"Leavers in the last {LEAVER_DAYS} days whose access must go"


def rule_incomplete(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("worker"):
        live = [r for r in rows if r.get("status") != "terminated"]
        bad = [r for r in live if not r.get("email") or not w3.EMAIL.match(str(r.get("email"))) or not r.get("department")]
        if bad:
            out.append(w3.finding("incomplete_worker", system, "worker", f"{len(bad)} workers", f"{len(bad)} active worker(s) without a work e-mail or a department: "
                                  "joiner flows and access requests cannot route them", "medium", measured=", ".join(str(r.get("name")) for r in bad[:6]),
                                  fix="Complete the records in the HR system - the source of truth for people data.", work="change", keys=[r["key"] for r in bad]))
    return out


rule_incomplete.label = "Active workers without a work e-mail or a department"

SIGNATURES = [
    w3.Signature(r"no bank account on the payment election", "a worker in the payroll run has no bank account on their payment election, so the payroll export stops",
                 "Ask payroll to add the worker's bank account (or exclude the worker from this run with a reason), then run the export again.", route="change"),
    w3.Signature(r"(?i)cost cent(re|er) .* (not found|invalid)", "a cost centre the integration sends does not exist in the target", "Create the cost centre in the target first, or map it.", route="ticket"),
    w3.Signature(r"(?i)duplicate (user|worker|employee)", "the person already exists in the target system", "Use the existing record, or merge the two first.", route="change"),
]

SPEC = w3.Spec(
    module=MODULE, noun="HR system", system="Relay HR", entities=("worker",),
    rules=[w3.rule_failing_jobs, rule_leavers, rule_incomplete, w3.rule_duplicates("worker")],
    signatures=SIGNATURES, minutes={"leaver": 10, "incomplete_worker": 5},
    upload_entities={"worker": "worker", "employee": "worker", "people": "worker", "joiner": "worker", "staff": "worker", "hcm": "worker"},
    creates=("worker",), measures={})

PLATFORMS = {
    "workday": w3.SysPlatform("Workday", ("workday",), "tests/mocklab/sims/hr.py: workday (REST v1, RaaS, OAuth refresh token)",
                              "workers (with leavers, from a custom report) and integration events through the API client and the integration system user"),
    "successfactors": w3.SysPlatform("SAP SuccessFactors", ("successfactors",), "tests/mocklab/sims/hr.py: successfactors (OData v2, SAML bearer)",
                                     "users, employment and Integration Center runs through the OAuth client"),
    "exports": w3.SysPlatform("Oracle Fusion HCM, Zoho People, Darwinbox, Keka (exports)", (), "export fixtures the tests write", "workers you upload (CSV, Excel)", uploads=(".csv", ".xlsx", ".json")),
}


def _kinds() -> set:
    return {k for p in PLATFORMS.values() for k in p.kinds}


GUIDE = """# HR & payroll - the work item

Relay's HR module reads workers (name, work e-mail, department, status and dates - no more personal data than the work
needs) and each HR system's integration runs, and brings joiners in or moves workers between HR systems with a
record-by-record reconciliation. Rules do the reading, mapping and checks; the agent is asked only to read a run log no
rule recognises (diagnose.json -> diagnosis.yaml). Never invent a person, a field or a number."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each HR system and object read (system -> entity), an inbound interface as a flow that writes into the HR system, a migration as feeds edges between systems",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See what the HR systems hold - failing payroll runs, leavers, incomplete records"),
        "develop": w3.develop_work(SPEC, "Bring joiners into the HR system: mapping agreed, a dry run, one approved write, read back"),
        "change": w3.change_work(SPEC, "Fix a failing payroll or HR integration, diagnosed from its own runs, released with approval"),
        "migrate": w3.migrate_work(SPEC, "Move workers between HR systems, reconciled record by record", _kinds),
        "run": w3.run_work(SPEC, "Watch the HR integrations; breaks go to a person first"),
    }))
