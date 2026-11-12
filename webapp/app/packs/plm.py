"""PLM (registry id `plm`) on the workbench - Siemens Teamcenter and PTC Windchill through their REST services;
3DEXPERIENCE / ENOVIA, Oracle Agile PLM, SAP PLM, Aras Innovator and Arena PLM through their exports.

Assess   parts / items and engineering changes in each system's own terms, and the workflow processes; rules: changes
         past their due date (ECN-000412, under review for 9 days with its review overdue), workflow processes that were
         aborted, the same part twice, parts still in work long after they were created.
Develop  new parts from an upload into Teamcenter or Windchill: mapping suggested and corrected, a dry run (a name, no
         number used twice), a named approver, one approved write, read back and reconciled.
Change   an overdue change or an aborted workflow, diagnosed from the system, released with approval.
Migrate  parts between PLM systems (Windchill -> Teamcenter ...), keep / merge / retire, crosswalk, proven record by record.
Run      changes and workflows watched on a schedule; breaks go to a person first.
"""
from __future__ import annotations

import time

from .. import workbench as wb
from . import _systems as w3
from . import plm_adapters  # noqa: F401 - registers Teamcenter and Windchill with the Connector SDK and the Connections hub

MODULE = "plm"
IN_WORK_DAYS = 180


def rule_overdue_changes(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("change"):
        late = []
        for r in rows:
            try:
                d = int(float(r.get("overdue_days") or 0))
            except ValueError:
                d = 0
            if d > 0:
                late.append((r, d))
        if late:
            out.append(w3.finding("overdue_change", system, "change", ", ".join(str(r.get("name")) for r, _ in late[:4]),
                                  "; ".join(f"{r.get('name')} is {r.get('state')} and {d} day(s) past its due date {r.get('due')}" for r, d in late[:4]),
                                  "high" if any(d >= 2 for _, d in late) else "medium", measured=", ".join(str(r.get("name")) for r, _ in late[:6]),
                                  fix="Ask the reviewer to decide, or move the due date with a reason; production waits on the change.", work="change", keys=[r["key"] for r, _ in late]))
    return out


rule_overdue_changes.label = "Engineering changes past their due date"


def rule_long_in_work(ctx, inv, spec=None) -> list[dict]:
    out = []
    cut = time.strftime("%Y-%m-%d", time.gmtime(wb.lab_now() - IN_WORK_DAYS * 86400))
    for system, rows in inv.rows("part"):
        bad = [r for r in rows if str(r.get("state") or "").lower() in ("inwork", "in work") and (r.get("modified") or "9999") < cut]
        if bad:
            out.append(w3.finding("long_in_work", system, "part", f"{len(bad)} parts", f"{len(bad)} part(s) still in work, untouched for {IN_WORK_DAYS} days", "low",
                                  measured=", ".join(str(r.get("number") or r.get("name")) for r in bad[:6]), fix="Release them or cancel them with their owners.", work="change",
                                  keys=[r["key"] for r in bad]))
    return out


rule_long_in_work.label = f"Parts still in work after {IN_WORK_DAYS} days"


def rule_aborted_workflows(ctx, inv, spec=None) -> list[dict]:
    """A change workflow aborted in the last week leaves its change in limbo - one abort is enough (a failing *job*
    needs a streak; a workflow carries one change)."""
    out = []
    since = wb.lab_now() - 7 * 86400
    for system, runs in inv.runs():
        hit = [r for r in runs if r.get("status") == "failed" and "abort" in str(r.get("error") or "").lower() and float(r.get("started") or 0) >= since]
        for r in hit:
            sig = next((s for s in (spec.signatures if spec else []) if s.match(r.get("error") or "")), None)
            out.append(w3.finding("aborted_workflow", system, "jobs", str(r.get("job")), f"{r.get('label') or r.get('job')}: a workflow process was aborted on {w3.stamp(float(r.get('started') or 0))}",
                                  "medium", measured=str(r.get("error") or ""), fix=sig.fix if sig else "Restart the workflow or close its change with a reason.", work="change",
                                  cause=sig.cause if sig else ""))
    return out


rule_aborted_workflows.label = "Change workflows aborted in the last 7 days"

def monitor_overdue(ctx, seen) -> list[dict]:
    """Run > Watch: an engineering change past its due date is a break (production waits on it), like a failed job."""
    out = []
    for c, a in w3.systems(ctx):
        if "change" not in a.ENTITIES:
            continue
        for r in seen.records(c, a, "change"):
            d = r.get("overdue_days") or 0
            if d > 0:
                err = f"{r.get('name')} is {r.get('state')} and {d} day(s) past its due date {r.get('due')}"
                out.append({"name": f"{c['id']}:change:{r['key']}", "label": f"{r.get('name')} - {c['name']}", "status": "fail", "measured": f"{d} day(s) late", "expected": "decided by its due date",
                            "detail": err, "break": {"conn": c["id"], "system": c["name"], "job": str(r.get("name")), "label": str(r.get("name")), "status": "overdue", "streak": 0,
                                                     "error": err, "since": None, "run": str(r["key"])}})
    return out


SIGNATURES = [
    w3.Signature(r"past its due date", "the change is waiting on a decision past its due date, so production waits on it",
                 "Ask the reviewer to decide (a Change item tracks it), or move the due date with a reason.", route="change"),
    w3.Signature(r"workflow process .* was aborted", "a change workflow was stopped before its decision, so the change it carried is in limbo",
                 "Restart the workflow on the same change (after approval) or close the change with a reason.", route="change"),
    w3.Signature(r"48037|already exists", "the part number is already used in the PLM system", "Use the existing part, or give the new one its own number.", route="change"),
    w3.Signature(r"CSRF_NONCE", "a Windchill write was sent without a fresh CSRF nonce", "Fetch a nonce from PTC/GetCSRFToken() before each write.", route="ticket"),
]

SPEC = w3.Spec(
    module=MODULE, noun="PLM system", system="Relay PLM", entities=("part", "change"),
    rules=[rule_overdue_changes, rule_aborted_workflows, w3.rule_failing_jobs, w3.rule_duplicates("part"), rule_long_in_work],
    signatures=SIGNATURES, minutes={"overdue_change": 30, "aborted_workflow": 30, "long_in_work": 5},
    upload_entities={"part": "part", "item": "part", "bom": "part", "material": "part", "change": "change", "ecn": "change", "eco": "change", "ecr": "change"},
    creates=("part",), measures={}, monitors=[monitor_overdue])

PLATFORMS = {
    "teamcenter": w3.SysPlatform("Siemens Teamcenter", ("teamcenter",), "tests/mocklab/sims/plm.py: teamcenter (JSON REST, SOA services)",
                                 "items, workflow processes and engineering changes through saved queries - a session login"),
    "windchill": w3.SysPlatform("PTC Windchill", ("windchill",), "tests/mocklab/sims/plm.py: windchill (REST Services, OData v4, CSRF nonce)",
                                "parts and change notices through Windchill REST Services - basic auth"),
    "exports": w3.SysPlatform("3DEXPERIENCE, Agile PLM, SAP PLM, Aras, Arena (exports)", (), "export fixtures the tests write", "parts, BOMs and changes you upload (CSV, Excel)",
                              uploads=(".csv", ".xlsx", ".json")),
}


def _kinds() -> set:
    return {k for p in PLATFORMS.values() for k in p.kinds}


GUIDE = """# PLM - the work item

Relay's PLM module reads parts, engineering changes and workflow processes, and brings parts in or moves them between
PLM systems with a record-by-record reconciliation. Rules do the reading, mapping and checks; the agent is asked only to
read a log no rule recognises (diagnose.json -> diagnosis.yaml). Never invent a part, a revision or a date."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each PLM system and object read (system -> entity), parts created as a write into the PLM system, a migration as feeds edges between systems",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See what the PLM holds - overdue changes, aborted workflows, duplicate parts"),
        "develop": w3.develop_work(SPEC, "Bring new parts into the PLM: mapping agreed, a dry run, one approved write, read back"),
        "change": w3.change_work(SPEC, "Move an overdue change or an aborted workflow on, diagnosed from the system, released with approval"),
        "migrate": w3.migrate_work(SPEC, "Move parts between PLM systems, reconciled record by record", _kinds),
        "run": w3.run_work(SPEC, "Watch changes and workflows; breaks go to a person first"),
    }))
