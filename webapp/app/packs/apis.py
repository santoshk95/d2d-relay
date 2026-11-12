"""Integration & APIs (registry id `apis`) on the workbench - Boomi and MuleSoft through their platform APIs; OIC, SAP
CPI, Azure Logic Apps / API Management, Kafka and Service Bus through their exports.

Assess   the integrations (processes, deployments) and published APIs in each platform's own terms, and their runs;
         rules: integrations that keep failing (the GST return upload: the portal no longer takes GSTR-1 v1), a secret
         kept in clear text in an integration's configuration, integrations that are stopped.
Change   a failing integration diagnosed from its own runs: the fix proposed from the platform's configuration (the
         schema version the portal now takes), released with approval - the configuration changed, the integration run
         again, checked on the platform. A secret in clear text is a step for a person (moved to the platform's secure
         properties) - Relay never handles the secret itself.
Run      the integrations watched on a schedule; breaks go to a Change item, Self-healing or a ticket after approval.
(Develop and Migrate of integrations are not offered yet: building a new flow or moving one between platforms needs
the platforms' deployment pipelines, which this module does not drive.)
"""
from __future__ import annotations

import re

from .. import workbench as wb
from . import _systems as w3
from . import apis_adapters  # noqa: F401 - registers Boomi and MuleSoft with the Connector SDK and the Connections hub

MODULE = "apis"


def propose_schema(ctx, c, a, api, run) -> list[dict]:
    """The GST portal takes GSTR-1 v2 only: the integration whose runs fail is switched to it, then run again - the
    integration found by its name on the platform (never a guess)."""
    job = str(run.get("job") or "")
    recs = a.records(api, "integration")
    hit = next((r for r in recs if r["name"] == job), None) or next((r for r in recs if w3.norm_name(r["name"]) == w3.norm_name(job.replace("-", " "))), None)
    if not hit:
        return []
    return [{"action": "update", "entity": "integration", "key": str(hit["key"]), "label": str(hit["name"]), "field": "schema_version", "value": "GSTR1_V2",
             "before": hit.get("schema_version") or "GSTR1_V1", "why": "the GST portal no longer accepts GSTR-1 v1"}]


def rule_clear_secret(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("integration"):
        bad = [r for r in rows if str(r.get("clear_secret") or "").strip()]
        if bad:
            out.append(w3.finding("clear_secret", system, "integration", ", ".join(str(r.get("name")) for r in bad[:6]),
                                  "; ".join(f"{r.get('name')} keeps \"{r.get('clear_secret')}\" in clear text in its configuration" for r in bad[:4]), "high",
                                  measured=", ".join(str(r.get("name")) for r in bad[:6]), fix="Move the value to the platform's encrypted / secure properties and rotate it; Relay never handles the secret itself.",
                                  work="change", keys=[r["key"] for r in bad],
                                  proposals=[{"action": "manual", "entity": "integration", "key": str(r["key"]), "label": str(r.get("name")), "field": "", "value": "", "before": "",
                                              "why": f"move {r.get('clear_secret')} to secure properties and rotate it - a person does it"} for r in bad]))
    return out


rule_clear_secret.label = "Secrets kept in clear text in an integration"


def rule_stopped(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("integration"):
        bad = [r for r in rows if str(r.get("status")) == "stopped"]
        if bad:
            out.append(w3.finding("stopped_integration", system, "integration", ", ".join(str(r.get("name")) for r in bad[:6]), f"{len(bad)} integration(s) stopped: "
                                  + ", ".join(str(r.get("name")) for r in bad[:4]), "medium", measured=", ".join(str(r.get("name")) for r in bad[:6]),
                                  fix="Start them if they are still needed, or retire them with their owners.", work="change", keys=[r["key"] for r in bad]))
    return out


rule_stopped.label = "Integrations that are stopped"

SIGNATURES = [
    w3.Signature(r"GSTR-1 v1 schema is no longer accepted|GST portal changed its upload", "the GST portal changed its GSTR-1 upload (it takes the v2 schema only) and the integration still sends v1",
                 "Switch the upload's schema version to GSTR1_V2 (Relay changes the configuration after approval), then run it again.", propose=propose_schema, route="change"),
    w3.Signature(r"(?i)token .*expired|401 Unauthorized|invalid_grant", "a connection the integration uses has an expired credential", "Renew the connection's credential on the platform.", route="ticket"),
    w3.Signature(r"(?i)rate limit exceeded", "the platform's API rate limit was reached", "Spread the calls, or ask the vendor for a higher limit.", route="ticket"),
]

SPEC = w3.Spec(
    module=MODULE, noun="integration platform", system="Relay integrations", entities=("integration", "api"),
    rules=[w3.rule_failing_jobs, rule_clear_secret, rule_stopped],
    signatures=SIGNATURES, minutes={"clear_secret": 30, "stopped_integration": 10},
    upload_entities={"integration": "integration", "process": "integration", "flow": "integration", "deployment": "integration", "iflow": "integration", "api": "api", "openapi": "api"},
    creates=(), measures={})

PLATFORMS = {
    "boomi": w3.SysPlatform("Boomi AtomSphere", ("boomi", "boomi_atomsphere"), "tests/mocklab/sims/ipaas.py: boomi (AtomSphere API, BOOMI_TOKEN)",
                            "processes with their component configuration and their execution records through an API token"),
    "mulesoft": w3.SysPlatform("MuleSoft Anypoint", ("mulesoft", "mulesoft_anypoint"), "tests/mocklab/sims/ipaas.py: mulesoft (connected app, CloudHub 2.0, Exchange)",
                               "deployments with their logs and the Exchange assets through a connected app"),
    "exports": w3.SysPlatform("OIC, SAP CPI, Logic Apps, API Management, Kafka, Service Bus (exports)", (), "export fixtures the tests write",
                              "integrations and APIs you upload as a list (CSV, Excel)", uploads=(".csv", ".xlsx", ".json")),
}

GUIDE = """# Integration & APIs - the work item

Relay's integration module reads the integrations and APIs on each platform with their runs and configuration, and
changes a configuration or runs an integration again only after a named person approves that very change. It reads the
names of secret properties, never their values. Never invent an integration, a run or a setting."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each integration platform and what it runs (system -> entity), a configuration change as a write into the platform",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See which integrations fail, keep secrets in clear text or are stopped"),
        "change": w3.change_work(SPEC, "Fix a failing integration from its own runs and configuration, released with approval"),
        "run": w3.run_work(SPEC, "Watch the integrations; breaks go to a person first"),
    }))
