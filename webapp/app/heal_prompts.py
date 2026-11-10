"""What the web app asks the agent to do for a Self-healing case (build-plan v2, P16): read the evidence the
app collected (logs, run history, the lineage neighbours, the configuration it may read) and write diagnosis.yaml —
the cause, how sure it is, the evidence rows, the fix it proposes (a configuration change the app can apply through
the owning module, or "needs code" for AI SDLC) and the test it will run on a copy. The patterns follow prompts.py
(SYSTEM / stage prompt / fix round)."""
from __future__ import annotations

SYSTEM = """You are the Relay agent: Claude Code running headless in a Docker container, diagnosing a failure the
platform noticed, so a person can approve a fix before anything changes. Your working directory is the case folder.
CLAUDE.md there is the guide for a case folder (reference/GENBI.md is the dashboard definition guide, for a fix on a
copy of a definition); the stage prompt says exactly what to write now. Bash runs only `genbi` commands. Nothing you write here changes a live system: the app applies a fix only after a named person
approves it. Nobody can answer questions during the run: decide sensibly, say what you assumed, and never invent an
observation that is not in the evidence. Keep your messages short: they are shown to the person as progress notes."""

DIAGNOSE = """Stage: HEAL DIAGNOSE. Something failed and Relay opened a case for it:

  What: {title}
  Where: {place}
  Signature: {signature} ({kind_label})
  Route the watcher suggests: {route} ({route_text})

1. Read request.md (the case, what the watcher saw, and every later note from the person, newest last).
2. Read every file under evidence/ — {evidence_list}. They are what the platform knows: the activity log and run
   history of the thing that failed, the lineage neighbours (what feeds it and what it feeds), the configuration
   it may read through connections (read-only, secrets never included), the schedule or integration record, the
   incident or ticket that raised the case.
3. Write diagnosis.yaml exactly in this shape (YAML, plain keys, nothing else at the top level):

cause: one or two sentences — what went wrong and why, in plain words (what the evidence shows, not a guess).
confidence: 0.85                 # 0 to 1 — how sure the evidence makes you
evidence:                        # the rows that support the cause (quote the evidence files; never invent one)
  - {{when: "2026-11-05 03:10", what: "extract failed", detail: "Snowflake: token expired (evidence/runs.json)"}}
fix:
  kind: {fix_kinds}      # one of these, nothing else
  module: D2D                    # the module that owns the change: D2D, Connections, Schedules, Integration analytics, Data observability, DAX checker, AI SDLC
  text: what the fix does, in one sentence a person can approve
  change: {{}}                     # the configuration change as key / value pairs (see the kinds below); {{}} when none
  risk: low                      # low / medium / high — what could go wrong when it is applied
test:
  what: what the test on a copy proves (one sentence)
  how: how the app runs it on the copy (one sentence)
  expect: what "pass" looks like
notes: anything the person should know (what you assumed, what you could not see)

Fix kinds and the change they carry:
{fix_kind_lines}

Rules: `fix.kind` must be one of the kinds above; `needs_code` when the cause is in code (a pipeline, bot, mapping,
model or application file) and no configuration change fixes it — AI SDLC then takes it as a change request; the
evidence list has at least one row; confidence is between 0 and 1; the change carries only keys the kind allows.
Do not write any other file. End with 2-4 sentences for the person: the cause, the fix and what the test will show."""

CORRECTION = """

The person looked at the diagnosis and sent it back with this note (also at the bottom of request.md):

{comment}

Read the evidence again with this in mind, then rewrite diagnosis.yaml. End with 1-3 sentences on what changed."""

FIX = """The web app checked diagnosis.yaml and found {n} problem(s):

{problems}

Fix them in diagnosis.yaml (keep the rest as it is) and end with one sentence on what you fixed."""

COPY_FIX = """Stage: HEAL FIX ON A COPY. The person approved this diagnosis and fix for a dashboard definition:

  Cause: {cause}
  Fix: {text}
  Change: {change}
  The failing review gate(s): {gates}

The dashboard's definition was copied to fix/copy/definition.yaml (its data is in fix/copy/data/). Change ONLY that
file so the fix above is applied — the smallest edit that makes the failing gate pass; keep every other table,
measure, page and visual as it is. Then run `genbi validate fix/copy/definition.yaml` until it reports OK.
Do not touch anything outside fix/copy/. End with 1-3 sentences on what you changed, naming the edited keys."""


def diagnose(case: dict, evidence_files: list[str], fix_kinds: dict, route_text: str, correction: str | None = None) -> str:
    text = DIAGNOSE.format(title=case.get("title") or "", place=case.get("place") or "", signature=case.get("signature") or "",
                           kind_label=case.get("kind_label") or case.get("kind") or "", route=case.get("route") or "config", route_text=route_text,
                           evidence_list=", ".join(evidence_files) or "none yet", fix_kinds=" | ".join(fix_kinds),
                           fix_kind_lines="\n".join(f"- {k}: {v['what']} — change keys: {', '.join(v['keys']) or 'none'}" for k, v in fix_kinds.items()))
    if correction:
        text += CORRECTION.format(comment=correction.strip())
    return text


def fix(problems: list[str]) -> str:
    shown = problems[:25] + ([f"… and {len(problems) - 25} more"] if len(problems) > 25 else [])
    return FIX.format(n=len(problems), problems="\n".join(f"- {p}" for p in shown))


def copy_fix(diag: dict, gates: list[str]) -> str:
    f = diag.get("fix") or {}
    return COPY_FIX.format(cause=diag.get("cause") or "", text=f.get("text") or "", change=f.get("change") or {}, gates=", ".join(gates) or "none named")
