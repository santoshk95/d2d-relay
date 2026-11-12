"""Identity & access (registry id `iam`) on the workbench - Microsoft Entra ID and Okta through their APIs, the HR systems
(Workday, SuccessFactors or an export) as the source of truth for who works here; Google Workspace, AWS IAM and SAP roles
through their exports.

Assess   accounts, groups and app registrations in each identity system's own terms, checked against HR: a leaver
         whose account is still switched on (and any sign-in after the leaving date), active accounts without MFA,
         app secrets expired or expiring within 30 days (with the sign-ins they break), accounts unused for 90 days.
Develop  joiners' accounts from an upload or an HR export: mapping suggested, a dry run (a login per person, no one
         twice), a named approver, one approved write (Entra ID accounts created switched off, Okta users staged), read
         back.
Change   a leaver's accounts switched off (or another account corrected) after approval, checked on the system.
Migrate  accounts between identity systems, keep / merge / retire, crosswalk, proven record by record.
Run      the identity estate watched on a schedule against HR; every break goes to a person first.
"""
from __future__ import annotations

import time

from .. import workbench as wb
from . import _systems as w3
from . import hr_adapters  # noqa: F401 - Workday and SuccessFactors: who works here
from . import iam_adapters  # noqa: F401 - registers Entra ID and Okta with the Connector SDK and the Connections hub

MODULE = "iam"
STALE_DAYS = 90
SECRET_DAYS = 30
OFF = ("disabled", "terminated", "deprovisioned", "suspended")


def _today(days: int = 0) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + days * 86400))


def _leavers(inv) -> dict:
    """Who has left, from every HR source in the item: employee id and e-mail -> (name, end date, the HR system)."""
    out = {}
    for system, rows in inv.rows("worker"):
        for r in rows:
            if r.get("status") == "terminated":
                v = (r.get("name"), r.get("end_date") or "", system)
                for k in (str(r.get("number") or r.get("key") or "").lower(), str(r.get("email") or "").lower()):
                    if k:
                        out[k] = v
    return out


def rule_leavers_active(ctx, inv, spec=None) -> list[dict]:
    left = _leavers(inv)
    out = []
    if not left:
        return out
    for system, rows in inv.rows("user"):
        hits = []
        for u in rows:
            if u.get("status") in OFF:
                continue
            lv = left.get(str(u.get("employee_id") or "").lower()) or left.get(str(u.get("email") or "").lower())
            if lv:
                hits.append((u, lv))
        if hits:
            after = [(u, lv) for u, lv in hits if u.get("last_signin") and lv[1] and u["last_signin"] > lv[1]]
            what = "; ".join(f"{lv[0]} left on {lv[1]} ({lv[2]}) - the account is still on" + (f", signed in on {u['last_signin']}" if (u, lv) in after else "") for u, lv in hits[:4])
            out.append(w3.finding("leaver_active", system, "user", ", ".join(str(lv[0]) for _, lv in hits[:6]), what, "high", measured=f"{len(hits)} account(s), {len(after)} used after leaving",
                                  fix="Switch the accounts off (a Change item does it after approval) and review what they did after the leaving date.", work="change",
                                  keys=[u["key"] for u, _ in hits],
                                  proposals=[{"action": "deactivate", "entity": "user", "key": str(u["key"]), "label": f"{lv[0]} ({u.get('login') or u.get('email')})", "field": "status",
                                              "value": "disabled", "before": str(u.get("status")), "why": f"left on {lv[1]} ({lv[2]})"} for u, lv in hits]))
    return out


rule_leavers_active.label = "Leavers whose accounts are still switched on"


def rule_no_mfa(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("user"):
        bad = [u for u in rows if u.get("status") == "active" and str(u.get("mfa")).strip().lower() in ("false", "0", "no")]     # rows come back from the inventory's CSV as text
        if bad:
            who = [str(u.get("login") or u.get("email")) for u in bad]           # the sign-in name (a service account's mailbox is often shared)
            out.append(w3.finding("no_mfa", system, "user", ", ".join(who[:6]), f"{len(bad)} active account(s) without an MFA factor: {', '.join(who[:4])}", "high",
                                  measured=", ".join(who[:6]), fix="Enrol a factor, or for a service account move it to a workload identity with no password.",
                                  work="change", keys=[u["key"] for u in bad],
                                  proposals=[{"action": "manual", "entity": "user", "key": str(u["key"]), "label": w_, "field": "", "value": "", "before": "",
                                              "why": "the person (or the service owner) enrols a factor - Relay never sets up MFA on someone's behalf"} for u, w_ in zip(bad, who)]))
    return out


rule_no_mfa.label = "Active accounts without MFA"


def rule_secrets(ctx, inv, spec=None) -> list[dict]:
    out = []
    soon = _today(SECRET_DAYS)
    for system, rows in inv.rows("app"):
        for a in rows:
            exp = a.get("secret_expires")
            if exp and exp <= soon:
                gone = exp < _today()
                out.append(w3.finding("secret_expiry", system, "app", str(a.get("name")), f"{a.get('name')}: its client secret {'expired on' if gone else 'expires on'} {exp}"
                                      + (" - its sign-ins fail" if gone else ""), "high" if gone else "medium", measured=exp,
                                      fix="Add a new secret (Relay can do it after approval), store it where the app reads it, then remove the old one.", work="change", keys=[a["key"]]))
    return out


rule_secrets.label = f"App secrets expired or expiring within {SECRET_DAYS} days"


def rule_stale(ctx, inv, spec=None) -> list[dict]:
    out = []
    cut = _today(-STALE_DAYS)
    for system, rows in inv.rows("user"):
        bad = [u for u in rows if u.get("status") == "active" and u.get("last_signin") and u["last_signin"] < cut]
        if bad:
            out.append(w3.finding("stale_account", system, "user", f"{len(bad)} accounts", f"{len(bad)} active account(s) unused for {STALE_DAYS} days", "low",
                                  measured=", ".join(str(u.get("email")) for u in bad[:6]), fix="Ask the owners whether they still need them; switch off the rest.", work="change",
                                  keys=[u["key"] for u in bad]))
    return out


rule_stale.label = f"Accounts unused for {STALE_DAYS} days"

SIGNATURES = [
    w3.Signature(r"AADSTS7000222|client secret keys .* are expired", "the app's client secret has expired, so every sign-in it makes fails",
                 "Add a new client secret to the app registration (after approval), store it in the app's settings, then remove the expired one.", route="change"),
    w3.Signature(r"AADSTS7000215", "the app sends a wrong client secret (the value, not the secret id, is needed)", "Store the secret's value, not its id.", route="ticket"),
    w3.Signature(r"E0000047", "Okta's rate limit for the API token was reached", "Spread the calls, or ask Okta for a higher limit for the token.", route="ticket"),
]

SPEC = w3.Spec(
    module=MODULE, noun="identity system", system="Relay identity", entities=("user", "group", "app", "worker"),
    rules=[rule_leavers_active, rule_no_mfa, rule_secrets, w3.rule_failing_jobs, rule_stale, w3.rule_duplicates("user")],
    signatures=SIGNATURES, minutes={"leaver_active": 15, "no_mfa": 10, "secret_expiry": 30, "stale_account": 3},
    upload_entities={"user": "user", "account": "user", "member": "user", "group": "group", "role": "group", "worker": "worker", "employee": "worker", "leaver": "worker"},
    creates=("user",), measures={})

PLATFORMS = {
    "entra": w3.SysPlatform("Microsoft Entra ID", ("entra_id",), "tests/mocklab/sims/msgraph.py: msgraph (Graph v1.0, client credentials)",
                            "users with their last sign-in, groups, app registrations and their secrets, and the sign-in log through an app registration"),
    "okta": w3.SysPlatform("Okta", ("okta",), "tests/mocklab/sims/okta.py: okta (Management API, SSWS token)", "users with their MFA factors and lifecycle, and groups through an API token"),
    "hr": w3.SysPlatform("HR systems (who works here)", ("workday", "successfactors"), "tests/mocklab/sims/hr.py: workday, successfactors",
                         "workers with their leaving dates - read-only, as the source of truth for joiners and leavers"),
    "exports": w3.SysPlatform("Google Workspace, AWS IAM, SAP roles, HR exports", (), "export fixtures the tests write", "accounts, groups and workers you upload (CSV, Excel)",
                              uploads=(".csv", ".xlsx", ".json")),
}


def _kinds() -> set:
    return {"entra_id", "okta"}


GUIDE = """# Identity & access - the work item

Relay's identity module reads accounts, groups and app registrations, checks them against HR (who works here, who left
and when) and switches accounts on or off only after a named person approves that very change. Rules do the reading,
mapping and checks; the agent is asked only to read a log no rule recognises (diagnose.json -> diagnosis.yaml). Never
invent an account, a person or a date; never show or store a password or a secret."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each identity system and object read (system -> entity), the HR system it is checked against, an account change as a write into the identity system",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See who can still get in - leavers with access, missing MFA, expiring secrets - checked against HR"),
        "develop": w3.develop_work(SPEC, "Create joiners' accounts: mapping agreed, a dry run, one approved write, read back"),
        "change": w3.change_work(SPEC, "Switch a leaver's accounts off (or correct an account), with approval, checked on the system"),
        "migrate": w3.migrate_work(SPEC, "Move accounts between identity systems, reconciled record by record", _kinds),
        "run": w3.run_work(SPEC, "Watch the identity estate against HR; breaks go to a person first"),
    }))
