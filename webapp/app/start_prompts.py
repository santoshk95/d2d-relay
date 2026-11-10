"""What the web app asks the agent to do for a Start (build-plan v2, P10): read every attachment and write
analysis.yaml — three views a person confirms (process map, fields & rules, plan & modules). The patterns follow
prompts.py (SYSTEM / stage prompt / fix round); the format is spelled out in the stage prompt, and the folder's guide
(CLAUDE.md, written by app/guides.py for a Start) says what the folder holds and the rules."""
from __future__ import annotations

from pathlib import Path

from . import registry

SYSTEM = """You are the Relay agent: Claude Code running headless in a Docker container, reading what a person wrote
and attached to start a piece of work, so they can confirm what you understood before anything is built. Your
working directory is the Start folder. CLAUDE.md there is the guide for a Start folder; the stage prompt says
exactly what to write now. Bash runs only `genbi` commands. Nobody can answer questions during the run: decide
sensibly, say what you assumed, and never invent a fact that is not in the brief or the attachments. Keep your
messages short: they are shown to the person as progress notes."""

READ = """Stage: START READ. A person wants to start something (request.md: the brief at the top; every later
correction is appended at the bottom, newest last). Read everything they attached and show what you understood.

1. Read request.md.
2. Run `genbi read attachments/` — it prints what every attachment says and lists the key frames it extracted from
   each video. Then look with Read at every image in attachments/ and every frame it listed (the screens, fields,
   clicks and values are in the pictures), and at each PDF for its layout and tables.{links}{connections}
3. Write analysis.yaml exactly in this shape (YAML, plain keys, nothing else at the top level):

summary: 2-3 sentences on what the person wants and what the attachments show.
process:                       # the work as it runs today, step by step, as the attachments show it
  steps:
    - id: s1                   # short unique ids in order
      actor: AP clerk          # who or what does it: a person's role, "agent" for a Relay agent, or a system name
      screen: Outlook          # where it happens (app, screen, document); omit if none
      action: Opens the invoice email and saves the PDF
      fields: [invoice number, supplier]   # the fields used or typed; omit if none
      decision: Does the total match the PO?   # only on a decision step
      rule: Totals within 10 rupees count as a match   # a rule the attachments state; omit if none
  handoffs:                    # where the work changes hands or branches
    - {{from: s3, to: s4, when: match}}
    - {{from: s3, to: s5, when: no match}}
fields:                        # every field, value and rule found, with how sure you are (0 to 1)
  - field: Supplier GSTIN
    source: sample-invoice.png # the attachment it came from
    type: text                 # text, number, date, amount, code, boolean, list
    rule: 15 characters, must match the PO supplier   # omit if none
    example: 27AABCN1234F1Z5   # a value as it appears; never a made-up one
    confidence: 0.98
    where: top right of the invoice   # page, cell range, slide, timestamp or position
plan:                          # which Relay modules build what, in order, and where the person confirms
  modules:
    - id: processdocs          # one of the module ids below, nothing else
      builds: Process map and SOP for invoice matching
      checkpoints: [Map, Correct]    # the names of the checks a person will confirm (see the module list)
  estimate: 9 working days      # optional, only when the attachments support it
  hours_saved_month: 120        # optional, only when the attachments support it

Module ids you may use (id — name — the checks it opens):
{modules}

Rules: every view must have at least one row; confidence is between 0 and 1; a step needs id, actor and action; a
plan module needs id, builds and at least one checkpoint; use the attachments' own words for fields and values.
Where the attachments say nothing about a part (no process, no fields), still write the view with what the brief
implies and say so in `summary`. Do not write any other file.
End with 2-4 sentences for the person: what you read, what you understood and what you were unsure about."""

CORRECTION = """

The person looked at the {view} view and corrected it (also recorded at the bottom of request.md):

{comment}

Read the attachments again with this in mind, then rewrite analysis.yaml — all three views, keeping what was right
and changing what the correction says. End with 1-3 sentences on what changed."""

LINKS = """
   The brief also names links ({links}); you cannot open them here — note them in `summary` as sources the person
   will give access to, and do not invent their content."""

CONNECTIONS = """
   The person also picked these connections for the modules to use read-only later: {names}. You do not query them
   in this stage; mention in `plan` where a module will read from them."""

FIX = """The web app checked analysis.yaml and found {n} problem(s):

{problems}

Fix them in analysis.yaml (keep the rest as it is) and end with one sentence on what you fixed."""


def module_lines() -> str:
    out = []
    for m in registry.MODULES:
        if m["pl"] in ("hidden", "platform"):
            continue
        checks = registry.confirm_for(m, "develop" if "develop" in m["work"] else (m["work"][0] if m["work"] else "engage"))
        out.append(f"- {m['id']} — {m['name']} — {', '.join(c[0] for c in checks)}")
    return "\n".join(out)


def read(st: dict, folder: Path, correction: str | None = None, view: str | None = None, connection_names: list[str] | None = None) -> str:
    links = st.get("links") or []
    text = READ.format(links=LINKS.format(links=", ".join(links)) if links else "",
                       connections=CONNECTIONS.format(names=", ".join(connection_names)) if connection_names else "",
                       modules=module_lines())
    if correction:
        text += CORRECTION.format(view={"process": "process map", "fields": "fields & rules", "plan": "plan & modules"}.get(view or "", view or "analysis"),
                                  comment=correction.strip())
    return text


def fix(problems: list[str]) -> str:
    shown = problems[:25] + ([f"… and {len(problems) - 25} more"] if len(problems) > 25 else [])
    return FIX.format(n=len(problems), problems="\n".join(f"- {p}" for p in shown))
