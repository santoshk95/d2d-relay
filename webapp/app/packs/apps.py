"""Apps & products (registry id `apps`) on the workbench - the apps and services an organisation runs: Power Apps
(the Power Platform admin API), Android apps on Google Play, iOS apps in App Store Connect, and web apps and services
(React, Angular, Python, Java, Node.js) through Sentry; the HR systems (Workday, SuccessFactors or an export) say who
still works here. AppSheet, Zoho Creator and others through their exports.

Assess   the apps and their releases in each platform's own terms; rules: a Power App owned by someone who has left
         (HR says so), a Power App that reads business data and is shared with the whole organisation, a release
         rolling out while it crashes (Google Play's own crash rate above its 1.09 % bad-behaviour line, or Sentry's
         release health for the same build below 99 % crash-free sessions), a version App Review rejected, a web or
         service release that brought a new error many users hit.
Change   from the assessment or a request: a staged rollout halted on Google Play, a phased release paused on the App
         Store, a Power App's owner changed to its co-owner or its share with everyone removed - each after approval,
         read back on the platform; a fix in the code is a step for a person (AI SDLC), a rollback goes through Cloud &
         CI/CD.
Run      releases and apps watched on a schedule; breaks go to a Change item or a ticket after approval.
(Develop and Migrate are not offered yet: building an app means a repository and a pipeline of its own, which AI SDLC
and Cloud & CI/CD hold; this module looks after what is already running.)
"""
from __future__ import annotations

from .. import workbench as wb
from . import _systems as w3
from . import apps_adapters as aa
from . import hr_adapters  # noqa: F401 - Workday and SuccessFactors: who works here

MODULE = "apps"
CRASH_FREE = 99.0           # % crash-free sessions a release should keep (Sentry release health)
MANY_USERS = 100            # a new error that many users hit is a regression worth a person's time


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _leavers(inv) -> dict:
    out = {}
    for system, rows in inv.rows("worker"):
        for r in rows:
            if r.get("status") == "terminated" and r.get("email"):
                out[str(r["email"]).lower()] = (r.get("name"), r.get("end_date") or "", system)
    return out


def rule_owner_left(ctx, inv, spec=None) -> list[dict]:
    left = _leavers(inv)
    out = []
    for system, rows in inv.rows("application"):
        for a in rows:
            lv = left.get(str(a.get("owner") or "").lower())
            if not lv:
                continue
            co = a.get("co_owner") or ""
            prop = ({"action": "update", "entity": "application", "key": str(a["key"]), "label": str(a["name"]), "field": "owner", "value": co, "before": a.get("owner") or "",
                     "why": f"{co} already edits the app; {lv[0]} keeps view access until the app is checked"} if co else
                    {"action": "manual", "entity": "application", "key": str(a["key"]), "label": str(a["name"]), "field": "", "value": "", "before": "",
                     "why": "share the app with its new owner, then change the owner"})
            out.append(w3.finding("owner_left", system, "application", str(a["name"]), f"{a['name']} is owned by {lv[0]} ({a.get('owner')}), who left on {lv[1] or 'a date HR holds'} ({lv[2]}) -"
                                  f" when the account goes, the app and its connections stop working", "high", measured=f"owner {a.get('owner')}", work="change",
                                  fix=f"Make {co} (co-owner) the owner." if co else "Give the app a new owner who works here.", cause="the owner left and nobody took the app over",
                                  keys=[str(a["key"])], proposals=[prop]))
    return out


rule_owner_left.label = "Apps owned by someone who has left"


def rule_shared_everyone(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("application"):
        for a in rows:
            if a.get("sharing") != "organisation":
                continue
            data = str(a.get("premium")).lower() == "true"
            out.append(w3.finding("shared_everyone", system, "application", str(a["name"]), f"{a['name']} is shared with everyone in the organisation and reads {a.get('data') or 'business data'}",
                                  "high" if data else "medium", measured="shared with: Everyone", work="change",
                                  fix="Remove the share with everyone; the people it is shared with by name keep their access.", cause="an app shared with the whole tenant exposes the data its connections read",
                                  keys=[str(a["key"])], proposals=[{"action": "update", "entity": "application", "key": str(a["key"]), "label": str(a["name"]), "field": "sharing", "value": "people",
                                                                    "before": "organisation", "why": "keep the named people; remove Everyone"}]))
    return out


rule_shared_everyone.label = "Apps shared with the whole organisation"


def _health(rows_by_system) -> dict:
    """Sentry's crash-free rate per (bundle, version, os), from every Sentry connection in the item."""
    out = {}
    for system, rows in rows_by_system:
        for r in rows:
            if r.get("track") == "Sentry release" and _f(r.get("crash_free")) is not None:
                out[(str(r.get("bundle")), str(r.get("version")), str(r.get("os")))] = (_f(r["crash_free"]), r.get("error") or "", system)
    return out


def crashing(r: dict, health: dict) -> str | None:
    """Why a release that is rolling out should stop (None when it is healthy)."""
    rate = _f(r.get("crash_rate"))
    if rate is not None and rate > aa.PLAY_BAD:
        return f"{rate:.2f} % of users see it crash (Google Play's bad-behaviour line is {aa.PLAY_BAD} %)"
    h = health.get((str(r.get("bundle")), str(r.get("version")), str(r.get("os"))))
    if h and h[0] < CRASH_FREE:
        return f"Sentry ({h[2]}) shows {h[0]:.1f} % crash-free sessions for this build (below {CRASH_FREE:.0f} %)" + (f"; the new crash: {h[1][:160]}" if h[1] else "")
    return None


def rule_rollouts(ctx, inv, spec=None) -> list[dict]:
    allrows = inv.rows("release")
    health = _health(allrows)
    out = []
    for system, rows in allrows:
        for r in rows:
            if r.get("status") != "rolling out":
                continue
            why = crashing(r, health)
            if not why:
                continue
            stop = r.get("stop_as") or "halted"
            out.append(w3.finding("crashing_rollout", system, "release", str(r["name"]), f"{r['name']} is rolling out ({r.get('rollout')}) on {r.get('platform') or r.get('track')} while {why}",
                                  "high", measured=why, work="change", fix=f"{'Halt the staged rollout' if stop == 'halted' else 'Pause the phased release'} until a fixed build is ready.",
                                  cause="a build that crashes is still reaching more users every day", keys=[str(r["key"])],
                                  proposals=[{"action": "update", "entity": "release", "key": str(r["key"]), "label": str(r["name"]), "field": "rollout", "value": stop,
                                              "before": r.get("rollout") or "", "why": f"stop it reaching more users: {why[:160]}"}]))
    return out


rule_rollouts.label = "Releases rolling out while they crash"


def rule_rejected(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("release"):
        for r in rows:
            if r.get("status") == "rejected":
                out.append(w3.finding("rejected_release", system, "release", str(r["name"]), f"{r['name']} was rejected in App Review - {r.get('error') or ''}", "medium",
                                      measured="rejected", work="change", fix="Read App Review's message, fix the build or the metadata, then submit it again.",
                                      cause="the store refused the version", keys=[str(r["key"])],
                                      proposals=[{"action": "manual", "entity": "release", "key": str(r["key"]), "label": str(r["name"]), "field": "", "value": "", "before": "",
                                                  "why": "read App Review's message in App Store Connect, fix the build or its metadata, then submit it again"}]))
    return out


rule_rejected.label = "Versions the store rejected"


def rule_regressions(ctx, inv, spec=None) -> list[dict]:
    out = []
    for system, rows in inv.rows("release"):
        for r in rows:
            n = int(_f(r.get("new_issue_users")) or 0)
            if r.get("track") != "Sentry release" or r.get("status") != "newest" or r.get("os") in ("iOS", "Android") or n < MANY_USERS:
                continue
            out.append(w3.finding("regression", system, "release", str(r["name"]), f"{r['name']} brought a new error: {r.get('error')}", "high", measured=f"{n} users",
                                  work="change", fix="Roll the release back (Cloud & CI/CD > Change) or fix the code (AI SDLC), then mark the issue resolved in the next release.",
                                  cause="the release introduced an error", keys=[str(r["key"])],
                                  proposals=[{"action": "manual", "entity": "release", "key": str(r["key"]), "label": str(r["name"]), "field": "", "value": "", "before": "",
                                              "why": f"roll {r['name']} back to the release before it, or fix {r.get('new_issue') or 'the error'} in the code"}]))
    return out


rule_regressions.label = "Releases that brought a new error"


def watch_releases(ctx, seen) -> list[dict]:
    """Run > Watch: every release that is rolling out, rejected or newest on Sentry; a crashing rollout, a rejection or a
    regression is a break."""
    got = []
    for c, a in w3.systems(ctx, aa.RELEASE_KINDS):
        got.append((c, seen.records(c, a, "release")))
    health = _health([(c["name"], rows) for c, rows in got])
    out = []
    for c, rows in got:
        for r in rows:
            why, route = None, "ticket"
            if r.get("status") == "rolling out":
                why, route = crashing(r, health), "change"
            elif r.get("status") == "rejected":
                why = r.get("error")
            elif r.get("track") == "Sentry release" and r.get("status") == "newest" and r.get("os") not in ("iOS", "Android") and (r.get("new_issue_users") or 0) >= MANY_USERS:
                why = r.get("error")
            elif r.get("status") not in ("rolling out", "newest"):
                continue
            row = {"name": f"{c['id']}:release:{r['key']}", "label": f"{r['name']} - {c['name']}", "status": "fail" if why else "pass", "measured": r.get("rollout") or r.get("status"),
                   "expected": "healthy", "detail": (why or "")[:220] if why else "no crash or new error above the line"}
            if why:
                row["break"] = {"conn": c["id"], "system": c["name"], "job": str(r["name"]), "label": str(r["name"]), "status": "failed", "streak": 1, "error": why,
                                "since": w3.when(r.get("when")), "run": "", "route": route}
            out.append(row)
    return out


SPEC = w3.Spec(
    module=MODULE, noun="apps", system="Relay apps & products", entities=("application", "release", "worker"),
    rules=[rule_rollouts, rule_regressions, rule_owner_left, rule_shared_everyone, rule_rejected],
    minutes={"crashing_rollout": 30, "regression": 240, "owner_left": 20, "shared_everyone": 15, "rejected_release": 120},
    monitors=[watch_releases],
    upload_entities={"app": "application", "application": "application", "service": "application", "release": "release", "version": "release", "build": "release",
                     "worker": "worker", "employee": "worker", "leaver": "worker"},
    creates=(), measures={})

PLATFORMS = {
    "power_apps": w3.SysPlatform("Power Apps", ("power_apps",), "tests/mocklab/sims/apps.py: power_apps (admin API, Entra client credentials)",
                                 "canvas apps with their owners, sharing and data connections through an app registration (Power Platform admin)"),
    "android": w3.SysPlatform("Android (Google Play)", ("google_play",), "tests/mocklab/sims/apps.py: google_play (Reporting API, Publishing API edits, service account)",
                              "apps, the production track's releases and their crash rate through a service account; a staged rollout halted after approval"),
    "ios": w3.SysPlatform("iOS (App Store Connect)", ("app_store_connect",), "tests/mocklab/sims/apps.py: app_store_connect (API v1, ES256 key)",
                          "apps, their newest version and its phased release through an API key; a phased release paused after approval"),
    "web": w3.SysPlatform("Web apps and services (Sentry)", ("sentry",), "tests/mocklab/sims/apps.py: sentry (web API, auth token)",
                          "projects, releases with crash-free sessions and the errors each release brought - read-only"),
    "hr": w3.SysPlatform("HR systems (who works here)", ("workday", "successfactors"), "tests/mocklab/sims/hr.py: workday, successfactors",
                         "workers with their leaving dates - read-only, to find apps whose owner has left"),
    "exports": w3.SysPlatform("AppSheet, Zoho Creator, other app platforms (exports)", (), "export fixtures the tests write",
                              "apps and releases you upload as a list (CSV, Excel)", uploads=(".csv", ".xlsx", ".json")),
}

GUIDE = """# Apps & products - the work item

Relay's apps module reads the apps and releases on each platform - and who still works here - and changes something
(halts a rollout, pauses a phased release, changes an app's owner or removes a share with everyone) only after a named
person approves that very change. A fix in the code is a step for a person (or AI SDLC); a rollback goes through Cloud &
CI/CD. Never invent an app, a release or a crash rate."""

w3.hook(MODULE)

wb.register(wb.Pack(
    module=MODULE, guide=GUIDE, platforms=PLATFORMS,
    lineage="each app platform and what runs on it (system -> entity), a halted rollout, a paused release or an owner change as a write into the platform",
    schemas={"inventory": ["include", "system", "object", "records"], "finding": ["decision", "severity", "system", "what"]},
    work={
        "assess": w3.assess_work(SPEC, "See which apps and releases need a person: crashing rollouts, new errors, owners who left, apps shared with everyone"),
        "change": w3.change_work(SPEC, "Halt a crashing rollout, pause a release or fix an app's owner or sharing, released with approval"),
        "run": w3.run_work(SPEC, "Watch the releases and apps; breaks go to a person first"),
    }))
