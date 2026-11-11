"""Relay's agents by name (consolidation of P10-P16): every job kind the worker runs and every stage an agent run
records gets a proper name and one line on what it does, so Team & agents, Home's "Agents right now" and the
notifications never show a raw job kind; and every kind of project folder knows which module it belongs to and
where its screen is, so a running job links to the right page.

A module that registers a new job kind (worker.register_job) or a new run stage (worker.agent(pid, stage, …)) adds
its line to AGENTS; tests/cons_test.py fails when a registered kind has no name. Constant tables only — nothing here
holds a tenant's data (docs/parallel-work.md, Tenancy).
"""
from __future__ import annotations

# job kind or run stage -> (agent name, what it does, what it is doing while it runs)
AGENTS: dict[str, tuple[str, str, str]] = {
    # D2D · Dashboards: the core lane (P0-P8)
    "extract": ("Extractor", "Pulls the warehouse tables a person picked, with that person's own sign-in.", "pulling warehouse tables"),
    "data": ("Data designer", "Designs demo data for the business a person described and generates it.", "designing demo data"),
    "plan": ("Planner", "Plans a dashboard from the data and the request: KPIs, pages and visuals.", "planning a dashboard"),
    "build": ("Builder", "Builds the dashboard's definition and prototype and runs the review gates.", "building the prototype"),
    "revise": ("Builder", "Applies a change request to a dashboard and runs the review gates again.", "applying a change request"),
    "fix": ("Fixer", "Fixes what a review gate or Power BI's own engine rejected.", "fixing review-gate problems"),
    "pbi": ("Publisher", "Makes the Power BI file (.pbix) once every review gate has passed.", "making the Power BI file"),
    # P10 Start
    "start_read": ("Reader", "Reads a start's brief and attachments into the three views a person confirms.", "reading a start"),
    # P11 Consulting studio
    "studio_outline": ("Outliner", "Proposes the outline of a deck or document from its brief and sources.", "outlining a deliverable"),
    "studio_draft": ("Drafter", "Drafts the deck or document from the confirmed outline, every figure sourced.", "drafting a deliverable"),
    "studio_build": ("Document builder", "Draws a deck or document again from its definition and runs the checks.", "rebuilding a deliverable"),
    "rfp_read": ("Bid reader", "Reads an RFP pack into requirements with page references and a go / no-go.", "reading an RFP pack"),
    "rfp_answer": ("Bid writer", "Drafts the compliance matrix from the past-responses library and the modules.", "drafting the compliance matrix"),
    "rfp_redteam": ("Red team", "Reads the response as the buyer's evaluator would and lists the weak answers.", "reading the response as the buyer"),
    "rfp_pack": ("Bid packer", "Builds the submission pack in the buyer's format.", "building the submission pack"),
    # P12 Service desk
    "itsm_sync": ("Ticket reader", "Reads the service-desk queues and groups duplicate and same-cause tickets.", "reading tickets"),
    "triage": ("Triage", "Rewrites the ticket groups' summaries and checks their priority (optional AI pass).", "refining the ticket groups"),
    # P13 Integration analytics
    "intan_scan": ("Integration scanner", "Discovers the integrations on each source and checks their health.", "scanning the integration sources"),
    # P14 Data observability
    "observe_check": ("Data checker", "Checks freshness, volume, schema and distribution on every watched asset.", "checking the watched data"),
    # P15 Migrate BI
    "migbi_scan": ("Estate scanner", "Discovers the BI estate to migrate: reports, queries, calculations and use.", "scanning a BI estate"),
    "migbi_convert": ("Converter", "Converts one report to Power BI: rules first, the agent only for the gaps.", "converting a report"),
    "convert": ("Converter", "Writes the calculations the conversion rules could not, then proves them.", "converting a report"),
    "migbi_drift": ("Drift checker", "Proves a migrated report's numbers against the source again, every night.", "checking a migrated report for drift"),
    # P16 Self-healing
    "heal_diagnose": ("Diagnoser", "Diagnoses a failure from the logs and the lineage and proposes a fix.", "diagnosing a failure"),
    "heal_fix": ("Healer", "Makes the approved fix on a copy and proves it with the right test.", "proving a fix on a copy"),
    "heal_apply": ("Applier", "Applies a proven fix through the module that owns it.", "applying an approved fix"),
    # P16 AI SDLC
    "sdlc_plan": ("Change planner", "Plans a code change: the files, the risks, the tests and an estimate.", "planning a code change"),
    "sdlc_dev": ("Developer", "Develops the approved plan on a branch, in small commits.", "developing on a branch"),
    "sdlc_qa": ("Tester", "Runs the repository's own tests and the secret and dependency scans.", "running the tests and scans"),
    "sdlc_review": ("Reviewer", "Reviews the change as a second pair of eyes before the named reviewer.", "reviewing a change"),
    "sdlc_release": ("Releaser", "Pushes the branch and opens the pull request once the approver accepts.", "opening the pull request"),
    # Module workbench: the two lane jobs of every wave module (its packs name their own steps' agents, below)
    "wb_step": ("Module runner", "Runs a module's rule, platform and proof steps, one after another.", "running a module step"),
    "wb_agent": ("Module agent", "Works the module steps that need judgement, with the pack's guide and checks.", "working a module step"),
}
# every name by kind, the ones above and the ones a module adds at import (the workbench's packs name their steps'
# agents here through team.AGENTS, which is this dict)
NAMES: dict[str, str] = {k: v[0] for k, v in AGENTS.items()}
# folder kinds a module names and links itself: kind -> fn(pid) -> {"module", "link", "agent"?, "doing"?} (the
# workbench's work items register here through team.SUBJECTS, which is this dict)
SUBJECTS: dict = {}

# folder kind (project.json `kind`) -> (module, link to its screen; {id} = the folder, {migration} = its programme)
FOLDERS: dict[str, tuple[str, str]] = {
    "dashboard": ("D2D · Dashboards", "#/p/{id}"),
    "start": ("Start", "#/start/{id}"),
    "deliverable": ("Studio", "#/studio/{id}"),
    "rfp": ("RFP & bid response", "#/rfp/{id}"),
    "servicedesk": ("Service desk", "#/servicedesk"),
    "intan": ("Integration analytics", "#/integrations"),
    "observe": ("Data observability", "#/observability"),
    "migbi": ("Migrate BI", "#/migrate-bi/{id}"),
    "migbi_report": ("Migrate BI", "#/migrate-bi/{migration}/convert"),
    "heal": ("Self-healing", "#/heal/{id}"),
    "sdlc": ("AI SDLC", "#/sdlc/{id}"),
}
# module subjects every signed-in person may see (their screens are open to every role): the job's name is no secret
SHARED_SUBJECTS = {"servicedesk", "intan", "observe"}


def name(kind: str | None) -> str:
    """The agent's name for a job kind or a run stage ('Agent' for one nobody named — never the raw kind)."""
    return NAMES.get(kind or "") or "Agent"


def does(kind: str | None) -> str:
    return AGENTS[kind][1] if kind in AGENTS else "Works on a step of a module."


def doing(kind: str | None) -> str:
    return AGENTS[kind][2] if kind in AGENTS else "working"


def catalogue() -> list[dict]:
    """Every agent once (kinds that share a name are one agent), for the screens: name, what it does, its kinds."""
    out: dict[str, dict] = {}
    for k, (n, d, _) in AGENTS.items():
        a = out.setdefault(n, {"agent": n, "does": d, "kinds": []})
        a["kinds"].append(k)
    for k, n in NAMES.items():                  # the agents a module's steps name (the workbench's packs)
        if k not in AGENTS:
            out.setdefault(n, {"agent": n, "does": does(k), "kinds": []})["kinds"].append(k)
    return list(out.values())


def place(pid: str | None, st: dict | None) -> dict:
    """Where a folder lives on screen: its module, the link to it and its name (st is its project.json)."""
    st = st or {}
    kind = st.get("kind") or "dashboard"
    if kind in SUBJECTS and pid:                # a module that names and links its own folders (the workbench's work items)
        try:
            info = SUBJECTS[kind](pid) or {}
            return {"kind": kind, "module": info.get("module") or "Relay", "link": info.get("link") or "#/", "name": st.get("name") or info.get("module") or "Relay",
                    "shared": False, **{k: info[k] for k in ("agent", "doing") if info.get(k)}}
        except Exception:  # noqa: BLE001 - a module's naming never breaks a page or a notification
            pass
    module, link = FOLDERS.get(kind, ("Relay", "#/"))
    mig = (st.get("migbi") or {}).get("project")
    if "{migration}" in link and not mig:
        link = "#/migrate-bi"
    return {"kind": kind, "module": module, "link": link.format(id=pid or "", migration=mig or ""), "name": st.get("name") or module,
            "shared": kind in SHARED_SUBJECTS}
