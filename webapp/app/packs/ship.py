"""Cloud & CI/CD (registry id `ship`) on the workbench — CI/CD pipelines on Azure DevOps, GitHub Actions and GitLab CI,
and what is deployed on Azure (Resource Manager), AWS (CloudFormation) and Google Cloud (Cloud Run), through their APIs.

Assess   the pipelines and deployments in each platform's own terms, and the pipeline runs; rules: pipelines that keep
         failing (with the cause Relay recognises from the vendor's own log: a dbt model's missing column, a held
         Terraform state lock, an Airflow 1 import), deployments that failed or were rolled back (a VM size with no
         capacity in the region, a bucket name already taken, a container that does not listen on its port).
Change   a failing pipeline diagnosed from its own runs and logs: the step for a person (release the lock, fix the
         model) and the pipeline run again with approval; a Cloud Run service whose new revision cannot start rolled
         back to the image of its last ready revision with approval — read back on the platform.
Run      pipelines and deployments watched on a schedule; breaks go to a Change item, Self-healing or a ticket after
         approval.
(Develop and Migrate are not offered yet: writing a pipeline or moving one between platforms means committing to the
repository, which this module does not do; infrastructure templates stay in their own repositories.)
"""
from __future__ import annotations

from .. import workbench as wb
from . import _systems as w3
from . import ship_adapters as sa

MODULE = "ship"


def propose_rollback(ctx, c, a, api, run) -> list[dict]:
    """A Cloud Run service whose new revision cannot start: roll it back to the image of its last ready revision — the
    service found by its name in the error (never a guess)."""
    if c.get("kind") != "gcp_cloud_run":
        return []
    text = f"{run.get('error') or ''} {run.get('job') or ''} {ctx.brief or ''}"
    out = []
    for d in a.records(api, "deployment"):
        if d["status"] == "failed" and d.get("rollback_image") and d["name"] in text:
            out.append(rollback(d))
    return out


def rollback(d: dict) -> dict:
    return {"action": "update", "entity": "deployment", "key": str(d["key"]), "label": str(d["name"]), "field": "image", "value": d["rollback_image"], "before": d.get("image") or "",
            "why": f"roll back to the image of the last ready revision ({d.get('serving') or 'still serving'}); the new image has to listen on $PORT before it goes out again"}


SIGNATURES = [
    w3.Signature(r"Compilation Error in model|invalid identifier", "a dbt model refers to a column the warehouse does not have — the model needs changing, not the pipeline",
                 "Fix the model in the dbt project (Data pipelines › Change), then run the build again.", route="ticket"),
    w3.Signature(r"Error acquiring the state lock", "a Terraform state lock is still held by an earlier run that did not finish",
                 "Check that no plan or apply is still running, release the lock (terraform force-unlock with the lock id), then run the plan again.", route="change"),
    w3.Signature(r"airflow\.contrib", "a DAG still imports from airflow.contrib, which Airflow 2 removed",
                 "Change the import to airflow.providers (Data pipelines › Migrate does it for the DAG), then run the pipeline again.", route="ticket"),
    w3.Signature(r"SkuNotAvailable", "the VM size the template asks for has no capacity in that region",
                 "Pick a size the region offers (az vm list-skus) or another region in the template, then deploy again through the pipeline.", route="ticket", kinds=("azure_arm",)),
    w3.Signature(r"already exists", "the stack creates a resource (an S3 bucket) whose name is already taken, so the update rolled back",
                 "Import the existing bucket into the stack (resource import) or give the template a new name, then update the stack.", route="ticket", kinds=("aws_cloudformation",)),
    w3.Signature(r"failed to start and listen on the port|HealthCheckContainerError", "the new container image does not listen on the port Cloud Run gives it (PORT), so its revision never became ready",
                 "Roll the service back to the image of its last ready revision (Relay does it after approval); the app team fixes the image to listen on $PORT.",
                 propose=propose_rollback, route="change", kinds=("gcp_cloud_run",)),
    w3.Signature(r"(?i)bad credentials|personal access token used has expired|401 unauthorized", "the pipeline's credential to a service has expired", "Renew the service connection's credential.", route="ticket"),
]


def _sig(text: str):
    return next((s for s in SIGNATURES if s.match(text or "")), None)


def rule_failed_deployments(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("deployment"):
        for r in rows:
            if r.get("status") not in ("failed", "rolled back"):
                continue
            sig = _sig(r.get("error") or "")
            props = [rollback(r)] if r.get("rollback_image") else [{"action": "manual", "entity": "deployment", "key": str(r["key"]), "label": str(r["name"]), "field": "", "value": "", "before": "",
                                                                 "why": sig.fix if sig else "read the deployment's error and fix the template"}]
            out.append(w3.finding("failed_deployment", system, "deployment", str(r["name"]), f"{r.get('kind') or 'Deployment'} {r['name']} {'was rolled back' if r['status'] == 'rolled back' else 'failed'}"
                                  f" ({r.get('environment') or 'no environment'}): {(r.get('error') or '')[:220]}", "high", measured=f"{r.get('state') or r['status']} since {r.get('when') or '—'}",
                                  fix=sig.fix if sig else "Read the deployment's error, fix the template or the image, then deploy again.", work="change", cause=sig.cause if sig else "",
                                  keys=[str(r["key"])], proposals=props))
    return out


rule_failed_deployments.label = "Deployments that failed or were rolled back"


def watch_deployments(ctx, seen) -> list[dict]:
    """Run › Watch: every deployment's state, read-only; a failed or rolled-back one is a break."""
    out = []
    for c, a in w3.systems(ctx, sa.CLOUD_KINDS):
        for d in seen.records(c, a, "deployment"):
            bad = d["status"] in ("failed", "rolled back")
            sig = _sig(d.get("error") or "")
            row = {"name": f"{c['id']}:deploy:{d['key']}", "label": f"{d['name']} ({d.get('kind')}) · {c['name']}", "status": "fail" if bad else "pass", "measured": d["status"], "expected": "succeeded",
                   "detail": (d.get("error") or "")[:220] if bad else f"deployed {d.get('when') or ''}".strip()}
            if bad:
                row["break"] = {"conn": c["id"], "system": c["name"], "job": str(d["name"]), "label": f"{d['name']} ({d.get('kind')})", "status": "failed", "streak": 1, "error": d.get("error") or "",
                                "since": w3.when(d.get("when")), "run": "", "route": sig.route if sig else "ticket"}
            out.append(row)
    return out


SPEC = w3.Spec(
    module=MODULE, noun="cloud and CI/CD", system="Relay cloud & CI/CD", entities=("pipeline", "deployment"),
    rules=[w3.rule_failing_jobs, rule_failed_deployments], signatures=SIGNATURES, minutes={"failed_deployment": 90},
    monitors=[watch_deployments],
    upload_entities={"pipeline": "pipeline", "workflow": "pipeline", "build": "pipeline", "deployment": "deployment", "stack": "deployment", "service": "deployment", "release": "deployment"},
    creates=(), measures={})

PLATFORMS = {
    "azure_devops": w3.SysPlatform("Azure DevOps", ("azure_devops",), "tests/mocklab/sims/devops.py: azure_devops (Build REST 7.1, PAT)",
                                   "build pipelines, their builds and the failed tasks' errors through a personal access token"),
    "github": w3.SysPlatform("GitHub Actions", ("github_actions",), "tests/mocklab/sims/devops.py: github_actions (REST, fine-grained token)",
                             "workflows, their runs and the failed jobs' logs through a fine-grained token"),
    "gitlab": w3.SysPlatform("GitLab CI", ("gitlab_ci",), "tests/mocklab/sims/devops.py: gitlab (REST v4, PRIVATE-TOKEN)", "pipelines, failed jobs and their traces through an access token"),
    "azure": w3.SysPlatform("Microsoft Azure", ("azure_arm",), "tests/mocklab/sims/cloud.py: azure_arm (Resource Manager, Entra client credentials)",
                            "template deployments and their errors through an app registration (Reader on the resource group)"),
    "aws": w3.SysPlatform("AWS", ("aws_cloudformation",), "tests/mocklab/sims/cloud.py: aws_cloudformation (Query API, SigV4)", "CloudFormation stacks and their events through an access key"),
    "gcp": w3.SysPlatform("Google Cloud", ("gcp_cloud_run",), "tests/mocklab/sims/cloud.py: gcp_cloud_run (Admin API v2, service account)",
                          "Cloud Run services and revisions through a service account; a rollback after approval"),
    "exports": w3.SysPlatform("Jenkins, Bitbucket, Terraform Cloud, Kubernetes (exports)", (), "export fixtures the tests write",
                              "pipelines and deployments you upload as a list (CSV, Excel)", uploads=(".csv", ".xlsx", ".json")),
}

GUIDE = """# Cloud & CI/CD — the work item

Relay's cloud and CI/CD module reads the pipelines with their runs and logs, and what is deployed in each cloud, and
runs a pipeline again or rolls a service back only after a named person approves that very change. A fix in code or
in a template is a step for a person (or another module's work item). Never invent a pipeline, a run or a deployment."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each pipeline platform and cloud and what it runs (system → entity), a rerun or a rollback as a write into the platform",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See which pipelines keep failing and which deployments failed, with their causes"),
        "change": w3.change_work(SPEC, "Fix a failing pipeline or deployment from its own runs and logs, released with approval"),
        "run": w3.run_work(SPEC, "Watch the pipelines and deployments; breaks go to a person first"),
    }))
