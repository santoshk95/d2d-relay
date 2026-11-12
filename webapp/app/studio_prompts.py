"""What the web app asks the agent to do in the studio (build-plan v2, P11): propose an outline for a deliverable
(STUDIO OUTLINE), then draft deck.yaml / doc.yaml from the confirmed outline with every figure sourced (STUDIO
DRAFT), and fix what the checks found. Same patterns as start_prompts.py / prompts.py."""
from __future__ import annotations

from pathlib import Path

SYSTEM = """You are the Relay agent: Claude Code running headless in a Docker container, drafting a consulting
deliverable (a deck or a document) for a person who reviews every step in a web app. Your working directory is the
deliverable's folder. CLAUDE.md there is the guide for a studio folder; the stage prompt says exactly what to write
now. Bash runs only `genbi` commands. Nobody can answer questions during the run: decide sensibly and say what you assumed.
Nothing invented: every number, reference and case study must come from the files under sources/ - a figure
without a source is a failed check, not a draft. Plain British English, short sentences, no filler. Keep your
messages short: they are shown to the person as progress notes."""

OUTLINE = """Stage: STUDIO OUTLINE. A person briefed a {kind_label}: brief.md says what it is, for whom, by when and
in which template. The facts you may use are under sources/ ({sources}). Read brief.md, then every file under
sources/ - run `genbi read sources/` for the attachments (documents, sheets, slides, PDFs) and Read the JSON records
(dashboard-*.json: measures with the values Power BI returned; registry.json: the modules and what each does;
practice.json, start-*.json, rfp-*.json, assess*.json: platform records; library.json: past answers and case studies).

Write outline.yaml exactly in this shape - the story line section by section, nothing drafted yet:

story: 2-3 sentences: the argument the deliverable makes for this audience, start to finish.
sections:
  - title: Where we are
    {unit}s:
      - title: The estate today
        layout: bullets                 # {layouts}
        intent: what this {unit} says and which source it draws on (one sentence)
        sources: [record:assess#estate, dashboard:atlas-1a2b/Stores]   # the references it will use (see below)

Source references (only these forms; every one must exist under sources/):
  dashboard:<id>/<measure>  a measure of sources/dashboard-<id>.json   record:<name>#<key.path>  a value in sources/<name>.json or .yaml
  attachment:<file>         a file under sources/                      library:<id>  an item of sources/library.json
  module:<id>               a module in sources/registry.json
Rules: {min_units}-{max_units} {unit}s in {min_sections}-{max_sections} sections; the first {unit} is the title ({unit} layout `title`) and the last the closing
(`closing`) for a deck; a {unit} that will show a number names its source here already; do not write deck.yaml or
doc.yaml in this stage. End with 2-3 sentences for the person: the story and what the sources support (and what
they do not)."""

DRAFT = """Stage: STUDIO DRAFT. The person confirmed outline.yaml{changed}. Write {spec} following it section by
section, in this shape (YAML; every key as shown; plain British English):

kind: {kind}
title: ...                        # the deliverable's title (from the brief)
subtitle: ...                     # optional
audience: ...                     # from the brief
date: {date}
template: {template}
sections:
  - title: Where we are
    {unit}s:
{shape}
Rules that the checks enforce (run `genbi {cli} check {spec}` until it reports OK; `genbi {cli} build {spec}` draws it):
- every number a reader sees (in titles, bullets, paragraphs) is listed under that {unit}'s `figures` with its `source`;
  the source must resolve (forms: dashboard:<id>/<measure>, record:<name>#<key.path>, attachment:<file>, library:<id>, module:<id>)
  and, where it holds a value, the figure must match it - never round a source value into something else, never estimate;
- tables, charts and quotes carry a `source`; charts and diagrams and images carry `alt` (one sentence of what they show);
- no placeholder text (lorem, TODO, xxx, tbd); at most {max_bullets} bullets a slide, titles under {max_title} characters;
- British spelling (organisation, colour, analyse ...); nothing from outside this folder;
- diagrams are Mermaid flowcharts (graph LR / TD with A[box] --> B(rounded) --> C{{decision}}); other kinds are not drawn.
Speaker notes (`notes`) say what the presenter says and where each number comes from. Do not write any other file.
End with 2-4 sentences for the person: what the draft says and which sources carried it."""

DECK_SHAPE = """      - layout: title
        title: ...
        subtitle: ...
      - layout: bullets
        title: ...
        bullets: ["1,842 reports across Cognos and Tableau", "..."]
        figures: [{text: "1,842", source: "record:assess#estate.reports"}]
        notes: ...
      - layout: two-column
        title: ...
        left: {heading: ..., bullets: [...]}
        right: {heading: ..., bullets: [...]}
      - layout: table
        title: ...
        table: {columns: [Decision, Reports], rows: [[Keep, "512"], [Retire, "377"]], source: "record:assess#estate", caption: ...}
      - layout: chart
        title: ...
        chart: {type: column, categories: [Wave 1, Wave 2], series: [{name: Days, values: [40, 65]}], unit: days, source: "record:assess#waves", alt: ...}
      - layout: diagram
        title: ...
        diagram: {mermaid: "graph LR\\n  A[Sources] --> B(Warehouse) --> C[Power BI]", alt: ...}
      - layout: quote
        quote: {text: ..., who: ..., source: "attachment:interview-notes.docx"}
      - layout: closing
        title: Thank you
        bullets: [Decide ... by ...]"""

DOC_SHAPE = """      - kind: heading
        title: ...
      - kind: paragraph
        title: ...                       # optional sub-heading
        text: "..."
        figures: [{text: "1,842", source: "record:assess#estate.reports"}]
      - kind: bullets
        bullets: [... , ...]
      - kind: table
        table: {columns: [...], rows: [[...]], source: "record:...", caption: ...}
      - kind: chart
        chart: {type: column, categories: [...], series: [{name: ..., values: [...]}], unit: ..., source: "record:...", alt: ...}
      - kind: diagram
        diagram: {mermaid: "graph LR\\n  A[Sources] --> B(Warehouse)", alt: ...}
      - kind: quote
        quote: {text: ..., who: ..., source: "attachment:..."}"""

CHANGED = """ and then, after reviewing a draft, asked for changes (also at the bottom of brief.md):

{comment}

Revise {spec} to do exactly that and keep the rest"""

FIX = """The web app ran the checks on {spec} and found {n} problem(s) (each starts with its check):

{problems}

Fix them in {spec} (keep the rest as it is), run `genbi {cli} check {spec}` until it reports OK, and end with one
sentence on what you fixed."""


def sources_line(folder: Path) -> str:
    names = sorted(p.name for p in (folder / "sources").glob("*") if p.is_file() and p.name != "brand.json")
    return ", ".join(names[:30]) + (f" ... and {len(names) - 30} more" if len(names) > 30 else "") if names else "nothing yet"


def outline(st: dict, folder: Path) -> str:
    deck = st.get("deliverable_kind", "deck") == "deck"
    return OUTLINE.format(kind_label=st.get("type_label") or "deliverable", sources=sources_line(folder), unit="slide" if deck else "block",
                          layouts="title, bullets, two-column, table, chart, diagram, quote, closing, image" if deck else "heading, paragraph, bullets, table, chart, diagram, quote, image",
                          min_units=8 if deck else 6, max_units=24 if deck else 40, min_sections=3, max_sections=7)


def draft(st: dict, comment: str | None = None, max_bullets: int = 7, max_title: int = 70) -> str:
    deck = st.get("deliverable_kind", "deck") == "deck"
    spec = "deck.yaml" if deck else "doc.yaml"
    return DRAFT.format(spec=spec, cli="deck" if deck else "doc", kind="deck" if deck else "doc", unit="slide" if deck else "block",
                        shape=DECK_SHAPE if deck else DOC_SHAPE, date=st.get("due") or "", template=st.get("template") or "relay",
                        changed=CHANGED.format(comment=comment.strip(), spec=spec) if comment else "", max_bullets=max_bullets, max_title=max_title)


def fix(st: dict, problems: list[str]) -> str:
    deck = st.get("deliverable_kind", "deck") == "deck"
    shown = problems[:25] + ([f"... and {len(problems) - 25} more"] if len(problems) > 25 else [])
    return FIX.format(spec="deck.yaml" if deck else "doc.yaml", cli="deck" if deck else "doc", n=len(problems), problems="\n".join(f"- {p}" for p in shown))
