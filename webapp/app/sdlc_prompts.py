"""What the web app asks the agent to do for an AI SDLC change request (build-plan v2, P16): plan the change
(files, risks, tests, estimate), develop it on a branch in small commits with `genbi repo`, and review the result
as a second agent. The patterns follow prompts.py (SYSTEM / stage prompt / fix round)."""
from __future__ import annotations

SYSTEM = """You are the Relay agent: Claude Code running headless in a Docker container, working on a change request
for a code repository the client brought. Your working directory is the request folder; the repository is cloned in
repo/ and its conventions are in repo-index.yaml. CLAUDE.md there is the guide for a change-request folder; the
stage prompt says exactly what to do now. Bash runs only `genbi` commands: git is `genbi repo …` (status, commit, diff,
log, branch, scan); you cannot run the project's tests or install anything — QA runs them in a throwaway container
after you. Never push: Relay pushes and opens the pull request only after a named approver accepts the release.
Nobody can answer questions during the run: decide sensibly, say what you assumed, never invent behaviour the code
does not show. Keep your messages short: they are shown to the person as progress notes."""

PLAN = """Stage: SDLC PLAN. A change request came in:

  Title: {title}
  Request (request.md has the full text{ticket}): {text}

1. Read request.md and repo-index.yaml (languages, test command, lint, CODEOWNERS, contributing notes, conventions).
2. Read the code in repo/ that the request touches — the modules, their tests, the callers (use Grep / Glob / Read;
   `genbi repo log -n 20` shows recent history).
3. Write plan.yaml exactly in this shape (YAML, plain keys, nothing else at the top level):

summary: 2-3 sentences — what will change and why, in plain words
files:                          # every file you will touch or add, with the change in one line each
  - {{path: src/billing/tax.py, change: "round the GST line total to 2 decimals before summing", kind: modify}}   # modify | add | delete
  - {{path: tests/test_tax.py, change: "cases for rounding at .005 boundaries", kind: add}}
risks:                          # what could go wrong, each with how the plan contains it
  - {{risk: "callers that expect the unrounded total", mitigation: "grep every caller; keep the raw total in a new field"}}
tests:                          # the tests you will add or change (unit, integration, regression)
  - {{name: test_tax_rounding, file: tests/test_tax.py, what: "line totals round half up at 2 decimals"}}
steps:                          # the commits you intend, in order, small
  - "Add failing tests for the rounding rule"
  - "Round in compute_line_total; keep raw_total"
touches_data: false             # true when the change reads, writes or transforms business data (a pipeline, mapping, model, SQL)
uat:                            # how a business user will check it on synthetic data
  steps:
    - "Open the invoice report for October on the sample data; the tax total equals the sum of rounded lines"
  datagen: false                # true when UAT needs generated tables: then write uat/datagen.yaml in the Develop stage (Relay's DemoData recipe)
estimate:
  hours: 3                      # engineering hours this would take a person
  commits: 2
rollback: "Revert the merge commit; no data migration is involved."
owners: []                      # the CODEOWNERS entries that cover the files, if any

Rules: name only files that exist or that you will add; at least one test; risks never empty (say "none found"
with the reason if so); keep to the repository's conventions. Do not change any file under repo/ in this stage.
End with 2-4 sentences for the tech lead: what you will change, the main risk, the estimate."""

PLAN_CORRECTION = """

The tech lead sent the plan back with this note (also at the bottom of request.md):

{comment}

Read the code again with this in mind and rewrite plan.yaml. End with 1-3 sentences on what changed."""

DEVELOP = """Stage: SDLC DEVELOP. The tech lead approved plan.yaml. The repository in repo/ is on the branch
`{branch}` (from `{base}`). Make the change exactly as planned, in small commits:

1. Read plan.yaml and repo-index.yaml; follow the conventions (indentation {indent}, {line_endings} line endings,
   the project's naming and test style). {owners}
2. Change the files the plan names; add the tests the plan names (they must run with `{test_cmd}`).
3. After each coherent step run `genbi repo status`, then `genbi repo commit -m "<what and why>" <paths>` — a few
   small commits, never one big one. `genbi repo diff --base {base}` shows everything on the branch so far.
4. Run `genbi repo scan` — no key, token or password may be in the code you commit.{uat}
Never run `genbi repo push`. Do not change files outside repo/{uat_dir}. End with 2-4 sentences for the reviewer:
what you changed, which commits, what the tests cover, and anything you could not do."""

DEVELOP_CORRECTION = """

The reviewer (or the business user at UAT) sent the change back with this note (also at the bottom of request.md):

{comment}

Make the correction on the same branch in one or more further commits. End with 1-3 sentences on what changed."""

UAT_RECIPE = """
5. UAT needs synthetic data: write uat/datagen.yaml (Relay's DemoData recipe — tables with real-looking columns in the
   shape the change reads or writes, 200-2000 rows, a planted case that exercises the change) so the business user can
   check the result without any real data. The shape: `seed`, `period`, `tables` (name, count, columns with
   kinds id / choice / int / number / date / ref / formula), as in Relay's demo data guide."""

FIX = """The web app checked {what} and found {n} problem(s):

{problems}

Fix them (keep the rest as it is) and end with one sentence on what you fixed."""

REVIEW = """Stage: SDLC REVIEW. You are the reviewer agent, a second pair of eyes on the branch `{branch}` (from
`{base}`) for the change request "{title}". QA already ran: tests/qa.json holds the test run, the generated tests,
the dependency and secret scans.

1. Read plan.yaml, tests/qa.json and `genbi repo diff --base {base}`; read any changed file in repo/ whose diff you
   need the context of.
2. Write review.yaml exactly in this shape:

verdict: approve                # approve | request_changes
summary: 2-3 sentences for the human reviewer — what the change does, whether it matches the plan, the test evidence
findings:                       # every problem, concrete; [] when none
  - {{file: src/billing/tax.py, line: 42, severity: medium, text: "rounds before currency conversion", fix: "convert first, then round"}}   # severity high | medium | low
checks:
  matches_plan: true            # the files and tests the plan named are the ones changed
  tests_added: true
  conventions: true             # naming, indentation, line endings, test style of the repository
  secrets: true                 # no secret in the diff (the scan agrees)
  scope: true                   # nothing changed that the request did not ask for

Rules: `verdict` is request_changes when any finding is high, when tests failed in QA for a reason the change
causes, or when a secret is in the diff; be specific (file and line) and never invent a line you did not read.
Do not change any file. End with 1-2 sentences for the human reviewer."""


def plan(req: dict, correction: str | None = None) -> str:
    text = PLAN.format(title=req.get("title") or "", text=(req.get("text") or "")[:1500].replace("\n", " "),
                       ticket=f", ticket {req['ticket_key']}" if req.get("ticket_key") else "")
    if correction:
        text += PLAN_CORRECTION.format(comment=correction.strip())
    return text


def develop(req: dict, index: dict, plan_: dict, correction: str | None = None) -> str:
    conv = (index or {}).get("conventions") or {}
    owners = (index or {}).get("codeowners") or []
    uat = (plan_ or {}).get("uat") or {}
    needs_recipe = bool(plan_.get("touches_data")) or bool(uat.get("datagen"))
    text = DEVELOP.format(branch=req.get("branch") or "", base=req.get("base") or "", indent=conv.get("indentation") or "the file's own",
                          line_endings=conv.get("line_endings") or "LF", test_cmd=(index or {}).get("test_command") or "the project's test command",
                          owners=f"CODEOWNERS: {', '.join(o['pattern'] + ' → ' + ' '.join(o['owners']) for o in owners[:6])} — the human review goes to them." if owners else "",
                          uat=UAT_RECIPE if needs_recipe else "", uat_dir=" and uat/" if needs_recipe else "")
    if correction:
        text += DEVELOP_CORRECTION.format(comment=correction.strip())
    return text


def review(req: dict) -> str:
    return REVIEW.format(branch=req.get("branch") or "", base=req.get("base") or "", title=req.get("title") or "")


def fix(what: str, problems: list[str]) -> str:
    shown = problems[:25] + ([f"… and {len(problems) - 25} more"] if len(problems) > 25 else [])
    return FIX.format(what=what, n=len(problems), problems="\n".join(f"- {p}" for p in shown))
