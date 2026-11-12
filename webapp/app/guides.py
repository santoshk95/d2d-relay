"""The guide in every agent folder (consolidation of P10-P16): CLAUDE.md, which Claude Code loads by itself, and the
same text as AGENTS.md / GEMINI.md for the other CLIs (phase 8). worker.refresh_guide writes it before every run,
and it is the guide for the folder's kind (project.json `kind`) - a dashboard gets the dashboard builder's guide
(genbi_kit/GENBI.md) with its worked example and the team's certified metrics, as before; a Start, a studio item, an
RFP response, a Self-healing case, an AI SDLC change request, a converted Migrate BI report and the Service desk's
triage folder each get their own: what the folder holds, the steps and the file each one writes, and the rules,
reusing the module's own prompts (its SYSTEM text) and, where the agent edits a dashboard definition, GENBI.md.
A module that adds a new kind of agent folder adds one entry to KINDS (tests/cons_test.py checks every kind with an
agent run has one). Constant text only: nothing here holds a tenant's data.
"""
from __future__ import annotations

import importlib
import json
import shutil
import traceback
from pathlib import Path

from genbi_kit import KIT

OTHER_CLIS = ("<!-- For Codex CLI, Gemini CLI and Antigravity CLI (phase 8): the same guide as CLAUDE.md. Where it names "
              "Claude Code's tools, use yours: read / write / edit files, and your shell tool for `genbi ...` only (no other "
              "commands, no web, no sub-agents). -->\n\n")


def dashboard_guide() -> str:
    return (KIT / "GENBI.md").read_text(encoding="utf-8")


def _system(module: str) -> str:
    """The module's standing instructions (its SYSTEM prompt), reused as the guide's 'How Relay runs you'."""
    try:
        return getattr(importlib.import_module(f".{module}", __package__), "SYSTEM", "")
    except Exception:  # noqa: BLE001 - the guide is still written without it
        traceback.print_exc()
        return ""


def _page(title: str, what: str, files: list[tuple[str, str]], steps: list[tuple[str, str]], rules: list[str], system: str = "",
          tail: str = "") -> str:
    out = [f"# Relay - {title}", "", what.strip(), "", "## What is in this folder", ""]
    out += [f"- `{f}` - {d}" for f, d in files]
    out += ["", "## The steps (each run's prompt names its stage and gives the exact file format)", ""]
    out += [f"{i}. **{s}** - {d}" for i, (s, d) in enumerate(steps, 1)]
    out += ["", "## Rules", ""] + [f"- {r}" for r in rules]
    if system:
        out += ["", "## How Relay runs you", "", system.strip()]
    if tail:
        out += ["", tail.strip()]
    return "\n".join(out) + "\n"


COMMON = ["Bash runs only `genbi` commands; nothing else, no web, no sub-agents.",
          "Nobody can answer questions during a run: decide sensibly and say what you assumed.",
          "Never invent a fact, a number, a reference or a behaviour the files do not show.",
          "A person confirms every step that matters in Relay's Validation queue; nothing you write reaches a live system, a buyer or a client by itself.",
          "Write only the files the stage prompt names. Keep your messages short: they are shown to people as progress notes."]


def _start(d: Path, st: dict) -> str:
    return _page("reading a start in this folder",
                 "A person described a piece of work and attached what they have. You read all of it and show what you understood in "
                 "three views the person confirms or corrects - the process map, the fields & rules, and the plan & modules - before "
                 "Relay builds anything.",
                 [("request.md", "the brief at the top; every correction the person made is appended at the bottom, newest last"),
                  ("attachments/", "what they attached: videos, images, PDF, Word, Excel, PowerPoint, audio, text - `genbi read attachments/` prints what each says (pages, sheets, slides, video frames and transcript)"),
                  ("analysis.yaml", "what you write: summary, process (steps and hand-offs), fields (with source, confidence and where), plan (modules and their checkpoints)"),
                  ("connections.json", "the connections the person picked for the modules to read later (read-only; you do not query them)")],
                 [("Read", "read request.md and every attachment, look at the images and the frames, and write analysis.yaml"),
                  ("Correct", "when the person sends a view back, read again with their correction and rewrite all three views")],
                 COMMON + ["Use the attachments' own words for fields and values; confidence is between 0 and 1; module ids come only from the list the prompt gives."],
                 _system("start_prompts"))


def _studio(d: Path, st: dict) -> str:
    kind = "deck" if st.get("deliverable_kind") == "deck" else "document"
    spec = "deck.yaml" if kind == "deck" else "doc.yaml"
    cli = "deck" if kind == "deck" else "doc"
    return _page(f"drafting a {kind} in this folder",
                 f"A consulting deliverable ({st.get('type_label') or kind}) for a person who reviews every step: an outline first, then the "
                 f"draft, every figure sourced. The app builds the {'PowerPoint' if kind == 'deck' else 'Word'} file and its HTML twin from {spec}.",
                 [("brief.md", "what the deliverable is, for whom, by when and in which template; every later comment appended"),
                  ("sources/", "the only facts you may use: attachments (`genbi read sources/`), dashboard-*.json measures with Power BI's values, registry.json, practice.json, library.json, other platform records"),
                  ("outline.yaml", "the story line, section by section (the Outline step)"),
                  (spec, f"the {kind} itself, section by section, with figures, sources and alt text (the Draft step)")],
                 [("Outline", "read the brief and every source, write outline.yaml; a person confirms it"),
                  ("Draft", f"write {spec} following the confirmed outline; run `genbi {cli} check {spec}` until it reports OK (`genbi {cli} build {spec}` draws it)"),
                  ("Fix", "when the checks or the reviewer find problems, fix them in place")],
                 COMMON + ["Every number a reader sees is listed with its source, and the source must resolve; a figure without a source is a failed check, not a draft.",
                           "Charts, diagrams and images carry alt text; no placeholder text; plain British English."],
                 _system("studio_prompts"))


def _rfp(d: Path, st: dict) -> str:
    return _page("responding to an RFP in this folder",
                 "A bid team answers an RFP, RFI or tender. You read the pack into requirements with page references, recommend go / no-go, "
                 "draft the compliance matrix from the past-responses library and Relay's modules, and read the response as the buyer's "
                 "evaluator would. A named person confirms each step; pricing comes from the rate cards, not from you.",
                 [("request.md", "who the buyer is and what the bid team knows; corrections appended"),
                  ("attachments/", "the pack (Word, Excel, PDF, slides) - `genbi read attachments/`"),
                  ("sources/library.json, sources/registry.json", "the only answers you may cite: past responses and case studies, and Relay's modules"),
                  ("requirements.yaml, gonogo.yaml", "every requirement with page, source, kind and confidence; your go / no-go recommendation (Read)"),
                  ("matrix.yaml", "Comply / Partial / Not / Alternative per requirement, with evidence (Answer)"),
                  ("redteam.yaml", "the evaluator's read: weak answers and what would strengthen them (Red team)")],
                 [("Read", "list every requirement in the pack and recommend go or no-go"),
                  ("Answer", "draft the compliance matrix citing only library items and modules"),
                  ("Red team", "read the response as the buyer's evaluator would")],
                 COMMON + ["Requirements come from the pack, answers cite only sources/library.json and sources/registry.json; an invented reference is a failed check."],
                 _system("rfp_prompts"))


def _heal(d: Path, st: dict) -> str:
    return _page("diagnosing a failure in this case folder",
                 "Relay noticed a failure (a refresh, a review gate, a sign-in, a schedule, an integration run, a data incident) and opened "
                 "this case. You diagnose it from the evidence and propose one fix a person approves; Relay tests the fix on a copy and "
                 "applies it only after a named approval, through the module that owns it.",
                 [("request.md", "the case, what the watcher saw, and every note from the person, newest last"),
                  ("evidence/", "what the platform knows: activity and run history, lineage neighbours, the configuration it may read (secrets never included), the schedule, integration or incident record"),
                  ("diagnosis.yaml", "the cause, how sure you are, the evidence rows, the fix and the test (Diagnose)"),
                  ("fix/copy/", "a copy of a dashboard definition and its data, when the fix edits a definition (Fix on a copy)"),
                  ("reference/GENBI.md", "the dashboard definition guide, for a fix on a copy of a definition")],
                 [("Diagnose", "read the evidence and write diagnosis.yaml"),
                  ("Fix on a copy", "for a definition fix, change only fix/copy/definition.yaml and run `genbi validate fix/copy/definition.yaml` until it is OK")],
                 COMMON + ["The fix kind is one of the kinds the prompt lists; `needs_code` hands the case to AI SDLC.", "Nothing you write here changes a live system."],
                 _system("heal_prompts"))


def _sdlc(d: Path, st: dict) -> str:
    return _page("working on a change request in this folder",
                 "A change request for a code repository the client brought: plan it, develop it on a branch in small commits, and review "
                 "it as a second agent. A tech lead approves the plan, a named reviewer the pull request, business users UAT on synthetic "
                 "data and a named approver the release; Relay pushes and opens the pull request only then, and never merges.",
                 [("request.md", "what is asked (and the ticket it came from); every later note appended"),
                  ("repo/", "the clone; git is `genbi repo ...` (status, commit, diff, log, branch, scan) - never `genbi repo push`"),
                  ("repo-index.yaml", "languages, test and lint commands, CODEOWNERS, contributing notes and conventions"),
                  ("plan.yaml", "files, risks, tests, steps, UAT, estimate and roll-back (Plan)"),
                  ("tests/qa.json", "QA's results: the repository's tests, generated tests, the secret and dependency scans (written by Relay)"),
                  ("review.yaml", "the reviewer agent's verdict and findings (Review)"),
                  ("uat/datagen.yaml", "the synthetic data recipe for UAT, when the change touches data")],
                 [("Plan", "read the request, the index and the code; write plan.yaml - change no file under repo/"),
                  ("Develop", "make the planned change on the branch in small commits with `genbi repo commit`; run `genbi repo scan`"),
                  ("Review", "read plan.yaml, tests/qa.json and the diff; write review.yaml - change no file")],
                 COMMON + ["Keep to the repository's conventions; no key, token or password in anything you commit.",
                           "You cannot run the tests or install anything: QA runs them in a throwaway container after you."],
                 _system("sdlc_prompts"))


def _servicedesk(d: Path, st: dict) -> str:
    from . import itsm_prompts
    return _page("refining service-desk triage in this folder",
                 "The Service desk's rules engine already grouped the data & analytics team's tickets (duplicates and same-cause tickets) "
                 "with a summary, a priority and the reason. In this optional pass you write better summaries and, only where the tickets "
                 "clearly show the rules got the impact wrong, a new priority with the reason. The groups never change here.",
                 [("triage_input.json", "the groups with their tickets, the rules' summary, priority and reason"),
                  ("triage_output.json", "what you write: one entry per group id with the summary (and a priority with its reason)")],
                 [("Refine", itsm_prompts.REFINE.split("\n\n")[1].replace("\n", " ").strip())],
                 COMMON + ["Everything you write comes from the tickets; keep every group id."])


def _migbi_report(d: Path, st: dict) -> str:
    lead = _page("converting a report to Power BI in this folder",
                 "Migrate BI converted one report of a BI estate (Cognos, Qlik, MicroStrategy, Tableau, SSRS, BusinessObjects) into this "
                 "folder with its rules: definition.yaml is already written in Relay's dashboard definition schema (the guide below). "
                 "You fill only the gaps the rules left - the calculations, filters and visuals listed in migrate_brief.json - and keep "
                 "everything else. The review gates and the Prove step compare your numbers with the source before a person accepts them.",
                 [("request.md", "the report, its source and every comment from the migration lead"),
                  ("definition.yaml", "the converted report; the measures still to write carry `BLANK ()` and a \"NO RULE YET\" description"),
                  ("migrate_brief.json", "what still needs you: each measure with its source expression and the prototype SQL its visuals use"),
                  ("data/", "the data behind the report (from the source estate)")],
                 [("Convert", "write the DAX for every listed measure (same numbers as its SQL), apply the listed filters, leave unconverted visuals out"),
                  ("Prove", "run `genbi validate`, `genbi prototype` and `genbi gates --no-dax` and fix every problem they report")],
                 COMMON + ["Change nothing the rules converted: tables, relationships, the measures with DAX, slicers, pages, visuals and every prototype SQL stay."],
                 tail="The dashboard definition guide follows: the schema definition.yaml is written in, the toolkit and the review gates.")
    return lead + "\n---\n\n" + dashboard_guide()


def _generic(d: Path, st: dict) -> str:
    return _page("work in this folder",
                 f"A {st.get('kind') or 'module'} folder of Relay. The stage prompt of each run says what to read and what to write.",
                 [("request.md", "what is asked and every later note, newest last")], [("Run", "follow the stage prompt")], COMMON)


# folder kind -> (guide builder, also give the dashboard definition guide as reference/GENBI.md)
KINDS = {"start": (_start, False), "deliverable": (_studio, False), "rfp": (_rfp, False), "heal": (_heal, True), "sdlc": (_sdlc, False),
         "servicedesk": (_servicedesk, False), "migbi_report": (_migbi_report, False)}


def text_for(d: Path, st: dict | None) -> str:
    """The guide text for a folder (its project.json as st); a dashboard (no kind) gets GENBI.md as before."""
    st = st or {}
    kind = st.get("kind") or "dashboard"
    if kind == "dashboard":
        return dashboard_guide()
    fn = KINDS.get(kind, (_generic, False))[0]
    return fn(d, st)


def write(d: Path, st: dict | None = None) -> str:
    """CLAUDE.md, AGENTS.md and GEMINI.md for this folder's kind (+ what a dashboard-like folder needs next to it).
    Returns the kind it wrote the guide for."""
    if st is None:
        try:
            st = json.loads((d / "project.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
    kind = st.get("kind") or "dashboard"
    guide = text_for(d, st)
    (d / "CLAUDE.md").write_text(guide, encoding="utf-8")
    for name in ("AGENTS.md", "GEMINI.md"):
        (d / name).write_text(OTHER_CLIS + guide, encoding="utf-8")
    if kind in ("dashboard", "migbi_report"):          # the agent writes a dashboard definition here: the team's metrics and the worked example
        try:
            from . import semantic
            semantic.team_metrics_file(d.name)         # the team's certified metrics, for the agent to reuse
        except Exception:  # noqa: BLE001 - the guide must not fail on the semantic layer
            traceback.print_exc()
        example = KIT / "examples" / "atlas_retail.yaml"
        if example.exists():
            (d / "reference").mkdir(exist_ok=True)
            shutil.copy2(example, d / "reference" / example.name)
    elif KINDS.get(kind, (None, False))[1]:              # a case may fix a copy of a dashboard definition
        (d / "reference").mkdir(exist_ok=True)
        shutil.copy2(KIT / "GENBI.md", d / "reference" / "GENBI.md")
    return kind
