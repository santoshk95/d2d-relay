"""What the Service desk asks the agent when the optional LLM pass is on (ITSM_LLM=1): rewrite each group's summary
in plain English and, where the rules missed something, adjust the priority - with the reason. The groups
themselves never change here; the rules decide those. Output is one JSON file the app reads back and checks."""

REFINE = """Stage: SERVICE DESK TRIAGE REFINEMENT.
The file triage_input.json lists groups of service-desk tickets a rules engine has already formed (duplicates and
same-cause tickets of a data & analytics team), each with its tickets (title, description, reporter, team, SLA), the
rules' summary, priority (P1 critical … P4 low) and the reason.

For every group write a better two-line plain-English summary a team lead can act on (what is broken or asked, for
whom, since when, with what error) and, only where the tickets clearly show the rules got the impact wrong, a new
priority with a one-sentence reason. Never invent facts: everything you write must come from the tickets.

Write triage_output.json: {{"groups": [{{"id": "<group id>", "summary": "<text>", "priority": "P1|P2|P3|P4" (optional),
"reason": "<text>" (with priority)}}]}} and nothing else. {count} groups; keep every id. End with one sentence for the user."""


def refine(count: int) -> str:
    return REFINE.format(count=count)
