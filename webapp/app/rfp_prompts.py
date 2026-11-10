"""What the web app asks the agent to do for an RFP response (build-plan v2, P11): read the pack and list every
requirement with its page reference plus the go / no-go recommendation (RFP READ), draft the compliance matrix
citing only library items and registry facts (RFP ANSWER), and read the response as the buyer's evaluator would
(RFP RED TEAM). Same patterns as start_prompts.py."""
from __future__ import annotations

SYSTEM = """You are the Relay agent: Claude Code running headless in a Docker container, working on a response to an
RFP, RFI or tender for a bid team that confirms every step in a web app. Your working directory is the response
folder. CLAUDE.md there is the guide for a response folder; the stage prompt says exactly what to write now. Bash
runs only `genbi` commands. Nobody can answer questions during the run: decide sensibly and say what you assumed. Never
invent a requirement, a reference, a case study or a number: requirements come from the pack, answers cite only the
library items under sources/library.json and the modules in sources/registry.json. Plain British English. Keep your
messages short: they are shown to the bid team as progress notes."""

READ = """Stage: RFP READ. The pack is under attachments/ ({files}). request.md says who the buyer is and what the bid
team already knows. Run `genbi read attachments/` (Word, Excel, PDF, slides as text with page and sheet markers),
then Read each PDF for its layout and tables.{correction}

1. Write requirements.yaml exactly in this shape — every requirement, with where it is in the pack:

buyer:
  name: Contoso Retail Ltd
  type: private            # public, private, ngo, government
  country: India
  currency: INR            # the currency the buyer prices in
deadline: "2026-12-01 17:00 IST"   # as the pack states it; omit the key if the pack gives none
format:
  submission: portal       # portal, email, both, paper
  portal: SAP Ariba        # omit if none named
  rules: ["PDF, at most 40 pages", "Pricing in a separate sealed file"]   # every format rule the pack states
evaluation:
  - {{criterion: Technical fit, weight: 60}}
  - {{criterion: Price, weight: 40}}
facts: ["Current estate: 1,842 Cognos reports (pack p. 4)"]    # buyer facts worth citing, each with its page
requirements:
  - id: R-001              # the pack's own numbering where it has one, else R-001, R-002 …
    text: The supplier shall migrate all Cognos reports to Power BI.   # the requirement as written, trimmed
    page: 4                # page (PDF / Word) or sheet name (Excel) where it is
    source: rfp-pack.docx  # the file in attachments/ it came from
    section: "3.2"         # the pack's section number or heading, if any
    kind: mandatory        # mandatory, scored, information
    confidence: 0.95       # 0-1: how sure you are this is a requirement as stated

2. Write gonogo.yaml — your recommendation for the named person who decides:

recommendation: go         # go | no-go
reasons: ["Fit: 28 of 32 requirements map to live or partly live modules", "Deadline leaves 18 working days"]
fit:                       # how the requirements map to the modules in sources/registry.json (ids only)
  - {{module: bi, requirements: 14}}
  - {{module: pipelines, requirements: 6}}
risks: ["R-017 asks for on-premises hosting only"]
effort: "roughly 3 waves"  # only what the pack and the registry support; no invented day counts
deadline_ok: true

Rules: list every requirement you find (a pack of this size has dozens — do not stop early); ids unique; page and
source on every one; kinds only mandatory, scored or information; modules only from sources/registry.json. Do not
write any other file. End with 2-4 sentences for the bid team: how many requirements, the deadline and format rules,
and your recommendation in one line."""

CORRECTION = """

The bid team looked at the requirements list and corrected it (also at the bottom of request.md):

{comment}

Read the pack again with this in mind and rewrite requirements.yaml and gonogo.yaml, keeping what was right."""

ANSWER = """Stage: RFP ANSWER. The bid team confirmed requirements.yaml and decided to go.{correction} Draft the compliance
matrix: for every requirement, a status and an answer with its evidence. The only evidence you may cite:
  module:<id>   a module in sources/registry.json (its name, platforms, journey, checkpoints — Relay's own facts)
  library:<id>  an item in sources/library.json (past answers and case studies the tenant chose to reuse)
Nothing else: no client names, numbers, certifications or references that are not in those two files.

Write matrix.yaml exactly in this shape:

rows:
  - id: R-001
    status: Comply         # Comply | Partial | Not | Alternative
    answer: >-
      Two or three sentences in the bid team's voice, specific to the requirement, drawing on the evidence.
    evidence: [module:bi, library:lib-3f2a]   # at least one for Comply / Partial / Alternative; none for Not
    note: what would make this a full Comply (optional)
summary:
  comply: 24
  partial: 5
  not: 1
  alternative: 2
  themes: ["Migration and proof", "Run & support"]

Rules: one row per requirement id, every id exactly once; statuses only those four; a `Not` is honest and says why
in the answer; wording in plain British English, no superlatives, no promises the evidence does not support. Do not
write any other file. End with 2-4 sentences for the bid team: the counts, the weak spots, and which library items
carried the answers."""

ANSWER_CORRECTION = """ They then sent the matrix back with this comment (also at the bottom of request.md):

{comment}

Rewrite matrix.yaml with it, keeping what was right."""

REDTEAM = """Stage: RFP RED TEAM. Read requirements.yaml, matrix.yaml and pricing.yaml as the buyer's evaluator would —
critically, against the evaluation criteria and format rules in requirements.yaml. Write redteam.yaml:

findings:
  - requirement: R-017      # the requirement id, or "general"
    severity: high          # high | medium | low
    finding: The answer promises cloud hosting; the requirement asks for on-premises only.
    suggestion: Mark it Alternative and say what the on-premises option would be.
  - requirement: general
    severity: medium
    finding: Nothing addresses the 40-page limit from the format rules.
    suggestion: Add a page budget to the submission plan.
summary: 2-3 sentences on the response's strongest and weakest points.

Rules: findings refer only to what is in the three files (never invent a buyer position); 3-12 findings, the
important ones first; nothing else is written. End with one sentence for the bid team."""

FIX = """The web app checked {file} and found {n} problem(s):

{problems}

Fix them in {file} (keep the rest as it is) and end with one sentence on what you fixed."""


def read(st: dict, correction: str | None = None) -> str:
    files = ", ".join(a["name"] for a in st.get("attachments") or []) or "nothing attached"
    return READ.format(files=files, correction=CORRECTION.format(comment=correction.strip()) if correction else "")


def answer(correction: str | None = None) -> str:
    return ANSWER.format(correction=ANSWER_CORRECTION.format(comment=correction.strip()) if correction else "")


def redteam() -> str:
    return REDTEAM


def fix(file: str, problems: list[str]) -> str:
    shown = problems[:25] + ([f"… and {len(problems) - 25} more"] if len(problems) > 25 else [])
    return FIX.format(file=file, n=len(problems), problems="\n".join(f"- {p}" for p in shown))
