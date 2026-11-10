"""Collaboration & content (registry id `collab`) on the workbench — SharePoint, OneDrive and Teams content through
Microsoft Graph; Google Workspace and Confluence through their exports.

Assess   sites and the files and folders in their document libraries, each with its sharing; rules: content shared by
         an anonymous link (anyone with the link can open it — Finance's "Month end" folder), content shared with the
         whole organisation, folders nobody has touched in two years.
Develop  a folder structure from an upload (a new team's library): names checked against SharePoint's rules and what
         is already there, a named approver, one approved write, read back.
Change   an anonymous link removed after approval (Relay only ever narrows access through this connection), checked on
         the system.
Migrate  folders between libraries or tenants: keep / merge / retire, crosswalk, proven record by record.
Run      sharing watched on a schedule: a new anonymous link is a break that goes to a person first.
"""
from __future__ import annotations

import time

from .. import workbench as wb
from . import _systems as w3
from . import collab_adapters  # noqa: F401 - registers Microsoft 365 content with the Connector SDK and the Connections hub

MODULE = "collab"
STALE_YEARS = 2


def rule_anonymous(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("item"):
        bad = [r for r in rows if str(r.get("sharing") or "") == "anonymous link"]
        if bad:
            out.append(w3.finding("anonymous_link", system, "item", ", ".join(f"{r.get('site')}/{r.get('name')}" for r in bad[:6]),
                                  f"{len(bad)} item(s) shared by an anonymous link — anyone with the link can open them: " + ", ".join(f"{r.get('site')} › {r.get('name')}" for r in bad[:4]),
                                  "high", measured=", ".join(str(r.get("name")) for r in bad[:6]), fix="Remove the anonymous link (a Change item does it after approval); share with named people instead.",
                                  work="change", keys=[r["key"] for r in bad],
                                  proposals=[{"action": "update", "entity": "item", "key": str(r["key"]), "label": f"{r.get('site')} › {r.get('name')}", "field": "sharing", "value": "members",
                                              "before": "anonymous link", "why": "anyone with the link can open it"} for r in bad]))
    return out


rule_anonymous.label = "Content shared by an anonymous link"


def rule_org_wide(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("item"):
        bad = [r for r in rows if str(r.get("sharing") or "") == "organisation link"]
        if bad:
            out.append(w3.finding("org_link", system, "item", f"{len(bad)} items", f"{len(bad)} item(s) shared with the whole organisation", "medium",
                                  measured=", ".join(str(r.get("name")) for r in bad[:6]), fix="Check each one is meant for everyone; narrow the rest to the team.", work="change",
                                  keys=[r["key"] for r in bad]))
    return out


rule_org_wide.label = "Content shared with the whole organisation"


def rule_stale(ctx, inv, spec=None) -> list[dict]:
    out = []
    cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - STALE_YEARS * 365 * 86400))
    for system, rows in inv.rows("item"):
        bad = [r for r in rows if str(r.get("kind")) == "folder" and r.get("modified") and r["modified"] < cut]
        if bad:
            out.append(w3.finding("stale_content", system, "item", f"{len(bad)} folders", f"{len(bad)} folder(s) untouched for {STALE_YEARS} years", "low",
                                  measured=", ".join(str(r.get("name")) for r in bad[:6]), fix="Archive or retire them with their owners (a Migrate item can move them).", work="migrate",
                                  keys=[r["key"] for r in bad]))
    return out


rule_stale.label = f"Folders untouched for {STALE_YEARS} years"


def monitor_anonymous(ctx, seen) -> list[dict]:
    """Run › Watch: an anonymous link is a break — whoever has the link can open the content."""
    out = []
    for c, a in w3.systems(ctx):
        if "item" not in a.ENTITIES:
            continue
        for r in seen.records(c, a, "item"):
            if r.get("sharing") == "anonymous link":
                err = f"{r.get('site')} › {r.get('name')} is shared by an anonymous link"
                out.append({"name": f"{c['id']}:anon:{r['key']}", "label": f"{r.get('site')} › {r.get('name')} · {c['name']}", "status": "fail", "measured": "anonymous link",
                            "expected": "members only", "detail": err, "break": {"conn": c["id"], "system": c["name"], "job": f"Sharing: {r.get('name')}", "label": f"Sharing: {r.get('name')}",
                                                                                   "status": "exposed", "streak": 0, "error": err, "since": None, "run": str(r["key"])}})
    return out


SIGNATURES = [
    w3.Signature(r"anonymous link", "content is open to anyone who has the link", "Remove the anonymous link (after approval) and share with named people instead.", route="change"),
    w3.Signature(r"nameAlreadyExists", "a folder of that name is already in the library", "Use the existing folder, or give the new one its own name.", route="change"),
]

SPEC = w3.Spec(
    module=MODULE, noun="content platform", system="Relay content", entities=("site", "item"),
    rules=[rule_anonymous, rule_org_wide, rule_stale],
    signatures=SIGNATURES, minutes={"anonymous_link": 10, "org_link": 5, "stale_content": 3},
    upload_entities={"site": "site", "file": "item", "item": "item", "folder": "item", "document": "item", "drive": "item", "page": "item"},
    creates=("item",), measures={}, monitors=[monitor_anonymous])

PLATFORMS = {
    "m365": w3.SysPlatform("Microsoft 365 (SharePoint, OneDrive, Teams)", ("m365_content",), "tests/mocklab/sims/msgraph.py: msgraph (sites, drives, items, permissions)",
                           "sites, their document libraries' files and folders, and each item's sharing through an app registration"),
    "exports": w3.SysPlatform("Google Workspace, Confluence (exports)", (), "export fixtures the tests write", "files, folders and pages you upload as a list (CSV, Excel)",
                              uploads=(".csv", ".xlsx", ".json")),
}


def _kinds() -> set:
    return {"m365_content"}


GUIDE = """# Collaboration & content — the work item

Relay's content module reads sites, files and folders with their sharing, narrows access (an anonymous link removed)
and creates or moves folders only after a named person approves that very change. It reads names, sizes, dates and
sharing — never the documents' contents. Never invent a file, a link or a date."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each content platform and the libraries read (system → entity), folders created as a write into the library",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See what is shared too widely — anonymous links, organisation-wide sharing, stale folders"),
        "develop": w3.develop_work(SPEC, "Set up a library's folders: names checked, a dry run, one approved write, read back"),
        "change": w3.change_work(SPEC, "Remove an anonymous link (or narrow other sharing) with approval, checked on the system"),
        "migrate": w3.migrate_work(SPEC, "Move folders between libraries, reconciled record by record", _kinds),
        "run": w3.run_work(SPEC, "Watch sharing; a new anonymous link goes to a person first"),
    }))
