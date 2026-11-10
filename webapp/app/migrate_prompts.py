"""What Migrate BI asks the agent: only the calculations, filters and visuals the rules could not convert. The
definition.yaml is already written by the rules; the agent fills the gaps, keeps everything else, and proves its
work with the same toolkit (genbi validate, prototype, gates). Fix rounds reuse prompts.fix."""

CONVERT = """Stage: CONVERT (Migrate BI — fill the gaps the rules left). The report “{name}” from {source} was converted
by Relay's rules into definition.yaml (read it and request.md first). The data behind it is in data/. Everything
the rules converted is right and stays as it is: tables, relationships, the measures with DAX, the slicers, the
pages and visuals, every prototype SQL.

migrate_brief.json lists what still needs you ({n} item(s)):
{items}

For each measure listed, write the DAX in definition.yaml in place of `BLANK ()` (keep the measure's name, format
and folder; drop the "NO RULE YET" words from its description and say in one line what the DAX does). The source
expression is given in the brief and in the measure's description; `sql` in the brief is the prototype SQL the
visuals already use for that calculation — the DAX must give the same numbers as that SQL, because the review gates
compare them (and the Prove step compares both with the source). Running totals follow the visual's row order
(dates or the category's sort); rank is 1 for the largest value; moving averages take the last N rows including the
current one. Where a filter is listed with no rule, apply it inside the measures of that query with CALCULATE, or
say in the description why it cannot be applied. Where a visual is listed as not converted, leave it out (a person
decides) — do not invent a replacement.{comment}

Then run `genbi validate`, `genbi prototype` and `genbi gates --no-dax` and fix every problem they report. Change
nothing else. Finish with 2-4 sentences for the migration lead: which calculations you wrote and what they do."""

REWORK = """Stage: CONVERT (Migrate BI, AI-led). The report “{name}” from {source} was drafted into definition.yaml by
Relay's rules (read it and request.md first; data in data/). In AI-led mode you review and rework every measure:
keep each measure's name, format and folder, and make sure its DAX gives exactly the numbers the visual's
prototype SQL gives (the gates compare them). The items that have no rule at all are listed in
migrate_brief.json ({n}); write their DAX as described in each gap's `reason` and `sql`.{comment}

Then run `genbi validate`, `genbi prototype` and `genbi gates --no-dax` and fix every problem. Finish with 2-4
sentences for the migration lead."""


def convert(name: str, source: str, gaps: list[dict], comment: str | None = None, ai_led: bool = False) -> str:
    lines = []
    for g in gaps:
        if g.get("kind") == "measure":
            lines.append(f"- measure [{g['measure']}] ← {g['expression']} — {g['reason']}" + (f"\n    prototype SQL: {g['sql']}" if g.get("sql") else "\n    (no SQL rule either: write the prototype SQL of the visuals that use it too)")
                         + (f"\n    the query's own filter to apply: {g['filter']}" if g.get("filter") else ""))
        elif g.get("kind") == "filter":
            lines.append(f"- filter {g['expression']} ({g.get('query')}) — {g['reason']}")
        else:
            lines.append(f"- {g.get('kind', 'item')} {g.get('item') or g.get('expression')} — {g['reason']}")
    tail = f"\n\nThe person who reviewed the last conversion asked: {comment.strip()}" if comment and comment.strip() else ""
    tpl = REWORK if ai_led else CONVERT
    return tpl.format(name=name, source=source, n=len(gaps), items="\n".join(lines) or "- (nothing: rework only)", comment=tail)
