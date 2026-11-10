"""What the web app asks the Claude Code agent to do at each stage. CLAUDE.md in the project folder
(the toolkit guide) holds the how; these prompts hold the what and when."""

SYSTEM = """You are the Relay agent: Claude Code running headless in a Docker container, building a
Power BI report for a business user who watches your progress live in a web app. Your working directory
is the project folder and CLAUDE.md there is your manual — follow it exactly. Bash runs only `genbi`
commands. Nobody can answer questions during the run, so decide sensibly and say what you assumed.
Keep your messages short: they are shown to the user as progress notes.
Write the way a thoughtful colleague would: plain words, short sentences, no internal codes, file paths or tool names
unless the person needs them; never say which AI model or company is behind Relay.
The product is D2D Relay. Every custom visual is a Relay visual: never write the word "Atlas" in anything the person
sees (plans, notes, visual titles, descriptions), even though the tools and type names use it."""

PLAN = """Stage: PLAN.
1. Read request.md. Run `genbi profile`, then read profile.md.{images}
2. Use `genbi sql` to understand the grain, keys, date range and the numbers behind each candidate KPI.
3. Write plan.yaml as described in CLAUDE.md: summary, model, 6-16 KPIs and the pages with their purpose and
   visuals (pick the best chart for each question from `genbi catalog`: Relay visuals and the Visual Atlas
   families). Each KPI has a label, a plain-language description that includes the formula, a format, and complete,
   working DAX against the planned model (VAR/RETURN for multi-step logic) — the user reviews it and the build
   uses it as written, so never put prose or placeholders in `dax`.
   {custom}
4. Run `genbi validate plan.yaml` until it reports OK.
Do not write definition.yaml in this stage. End with 2-4 sentences for the user: what you found in the data and
what you propose."""

DATA = """Stage: DATA. The user has no data for this dashboard yet (request.md, "Data — generate demo data"): design a
realistic demo dataset for the business they describe and generate it.
1. Read request.md{files}. Read CLAUDE.md, Demo data — whatever the industry, its shapes (events, daily
   measurements, snapshots, budgets, lifecycles, funnels, hierarchies, scores …) are what you build it from.
2. Write datagen.yaml: {size}, period {start} to {end}. Lookup tables first (real-sounding names for the domain:
   products, sites, regions, customers …), then the facts that refer to them, with keys that join. Give it a
   believable shape — trend, seasonality, skew (a few big products/customers), a little missing data — and plant 3-5
   stories a dashboard should reveal (one item growing or declining, a region or month that dips, a segment that
   behaves differently …). List them under `story`. Shape the tables so the user's questions can be answered.
   Totals must look real for this kind of business: the row budget is a sample size, not the size of the
   business — when rows are few, use a coarser grain (e.g. daily sales per store and product instead of single
   receipts) or scale the amounts, so monthly and yearly totals match a real company of this kind.
3. Run `genbi datagen` until it reports no problems, then prove each story with `genbi sql` (fix the recipe if a
   story does not show clearly).
Do not write plan.yaml or definition.yaml in this stage. End with 2-4 sentences for the user: the tables (rows)
and the stories in the data."""

DATA_REVISE = """Stage: DATA (revision). The user wants the demo data changed (also recorded at the bottom of request.md):

{feedback}

Change datagen.yaml to do exactly that, run `genbi datagen` until it reports no problems, check the stories with
`genbi sql`, and end with 1-3 sentences on what changed."""

GENERATED = """
   The data was generated for this demo from datagen.yaml; its `story` lists what the data was made to show —
   make sure the KPIs and pages bring those stories out."""

PLAN_IMAGES = """
   Look at every image in images/ with Read: {names}. They show the design the user wants (layout, chart
   types, style) — imitate it. All numbers come from data/ only; never copy figures from an image."""

PLAN_REVISE = """Stage: PLAN (revision). The user reviewed plan.yaml and asked for changes (also recorded at the
bottom of request.md):

{feedback}

Their direct edits to the KPIs are already saved in plan.yaml — keep them unless the request says otherwise.
If datagen.yaml exists (generated demo data) and they ask for different data, change the recipe and run
`genbi datagen` first.
Update plan.yaml, run `genbi validate plan.yaml` until it reports OK, and end with 2-3 sentences on what changed."""

BUILD = """Stage: BUILD. The user confirmed the KPIs in plan.yaml (see the bottom of request.md) — keep their names,
labels, formats and DAX logic.
Read reference/atlas_retail.yaml for patterns, then build definition.yaml following CLAUDE.md: the model first,
then the pages of the plan one at a time.{custom} Before using a Visual Atlas family, read `genbi catalog <type>`. Apply the
visual style in request.md (look, brand color, palette, dark) through `theme`. Loop until `genbi validate` and `genbi prototype` both report no problems and `genbi daxcheck` (Power BI's own engine)
accepts every measure and visual, then check the headline KPI values with `genbi sql` and the values `genbi daxcheck` printed.
Finish with `genbi gates` — every review gate the app runs before the user sees the version — and fix every fail item
(and the warnings that matter to the user).
End with a short summary for the user: what each page shows and the headline numbers."""

REVISE = """Stage: REVISE (prototype v{v} -> v{next}). The user reviewed the prototype and asked for (also recorded at
the bottom of request.md):

{feedback}

Change definition.yaml (and plan.yaml if KPIs change) to do exactly that and keep everything else. {custom}
If it needs different or more data and datagen.yaml exists (generated demo data), change the recipe and run
`genbi datagen` first.
Loop until `genbi validate` and `genbi prototype` report no problems and `genbi daxcheck` accepts every measure and visual,
then finish with `genbi gates` and fix every fail item.
End with 1-3 sentences on what changed."""

# What the user allows for new custom visuals (request.md, "Custom visuals"), at each stage.
CUSTOM_PLAN = {
    "ask": "Where nothing in `genbi catalog` (the visual library included) answers a need well, propose a custom visual "
           "under `custom_visuals` in plan.yaml with the closest existing visual as `fallback` and your `recommend` "
           "(CLAUDE.md, Custom visuals); the user chooses between them.",
    "auto": "Where nothing in `genbi catalog` (the visual library included) answers a need well, add a custom visual under "
            "`custom_visuals` in plan.yaml with `recommend: generate` and the closest existing visual as `fallback` "
            "(CLAUDE.md, Custom visuals); it is built unless the user picks the fallback.",
    "never": "Use only visuals from `genbi catalog`: the user does not want new custom visuals (no `custom_visuals`).",
}
CUSTOM_REVISE = {
    "ask": "If the change needs a chart nothing in `genbi catalog` draws, use the closest visual and add a proposal without "
           "`decision` to `custom_visuals` in plan.yaml, so the user can ask for it to be built; if the user asks for a custom "
           "visual in so many words, build it (CLAUDE.md, Custom visuals).",
    "auto": "If the change needs a chart nothing in `genbi catalog` draws, build a custom visual (CLAUDE.md, Custom visuals) "
            "and add it to `custom_visuals` in plan.yaml with `decision: generate`.",
    "never": "Use only visuals from `genbi catalog` unless the user asks for a custom visual in so many words.",
}

GENERATE = """Build the custom visual you proposed: {title} (`{name}`) — {need}. Use it in place of {fallback}{pages}.
Its `decision` in plan.yaml is now `generate`."""

FIX = """The web app ran the review gates on your work and found {n} problem(s) (each starts with its gate):

{problems}

Fix them, re-run {commands} until clean, and end with one or two sentences for the user on what you fixed."""


ATTACHED = """

The user attached files with this request (already saved in the project folder):
{items}
{steps}"""


def attached(items: list[dict] | None) -> str:
    """Prompt section for files that came with a change request."""
    if not items:
        return ""
    lines = [f"- {a['path']}" + (" — replaces the earlier file of the same name (the data changed)" if a.get("replaced")
                                 else " — new") for a in items]
    steps = []
    if any(a["kind"] == "data" for a in items):
        steps.append("For data: run `genbi profile`, read profile.md and check the new data with `genbi sql`, then add or "
                     "update tables, relationships, measures and visuals as the request needs. Keep existing names working.")
    if any(a["kind"] == "image" for a in items):
        steps.append("For images: look at each with Read — they show what the user wants.")
    return ATTACHED.format(items="\n".join(lines), steps="\n".join(steps))


# Which visuals the report uses (request.md, "Visuals"; project.json `visuals_mode`).
VISUALS = {
    "builtin": " Visuals: builtin (request.md) — use only Power BI's own visuals (`type: pbi.<visual>`, `genbi catalog pbi`; "
               "CLAUDE.md, Power BI's own visuals) with the Format-pane options the design needs; no custom visual, "
               "`genbi validate` refuses them.",
    "mixed": " Visuals: mixed (request.md) — use Power BI's own visuals (`genbi catalog pbi`) first, and a Relay, Visual Atlas or "
             "custom visual only where no built-in visual does the job; say which and why in the plan.",
    "relay": "",
}


def visuals_note(mode: str | None) -> str:
    return VISUALS.get(mode or "relay", "")


def plan(images: list[str], policy: str = "ask", generated: bool = False, visuals: str | None = None) -> str:
    extra = (PLAN_IMAGES.format(names=", ".join(images)) if images else "") + (GENERATED if generated else "")
    return PLAN.format(images=extra, custom=CUSTOM_PLAN.get(policy, CUSTOM_PLAN["ask"]) + visuals_note(visuals))


SIZES = {"small": "the biggest table about 5,000 rows (fast)", "medium": "the biggest table about 50,000 rows",
         "large": "the biggest table about 500,000 rows (all tables under 1,500,000)"}


def data(spec: dict, files: list[str], feedback: str | None = None) -> str:
    """DATA: generate a demo dataset (or change it)."""
    if feedback:
        return DATA_REVISE.format(feedback=feedback)
    keep = (f" and look at the files the user uploaded ({', '.join(files)}): use them as they are (`file:` tables) "
            "and generate the rest around them") if files else ""
    return DATA.format(files=keep, size=SIZES.get(spec.get("size"), SIZES["medium"]),
                       start=spec.get("start"), end=spec.get("end"))


def build(chosen: list[dict], visuals: str | None = None) -> str:
    """BUILD, with the custom visuals the user chose to have built (plan.yaml `custom_visuals`)."""
    make = [v for v in chosen if v.get("decision") == "generate"] if visuals != "builtin" else []
    keep = [v for v in chosen if v.get("decision") == "available"]
    text = visuals_note(visuals)
    if make:
        text += ("\nFirst build the custom visuals the user chose (CLAUDE.md, Custom visuals) — "
                 + "; ".join(f"{v['title']} (`{v['name']}`): {v.get('need', '')}" for v in make)
                 + " — then use them on their pages.")
    if keep:
        text += ("\nWhere the user chose an available visual instead of a custom one, use the fallback: "
                 + "; ".join(f"{v.get('fallback')} instead of {v['title']}" for v in keep) + ".")
    return BUILD.format(custom=text)


def revise(v: int, feedback: str, policy: str = "ask", visuals: str | None = None) -> str:
    return REVISE.format(v=v, next=v + 1, feedback=feedback,
                         custom=CUSTOM_REVISE.get(policy, CUSTOM_REVISE["ask"]) + visuals_note(visuals))


def generate(item: dict) -> str:
    pages = item.get("pages")
    pages = f" on {', '.join(map(str, pages))}" if isinstance(pages, list) and pages else ""
    return GENERATE.format(title=item.get("title", item["name"]), name=item["name"], need=item.get("need", ""),
                           fallback=item.get("fallback", "the visual used now"), pages=pages)


def fix(problems: list[str], stage: str) -> str:
    commands = {"plan": "`genbi validate plan.yaml`", "data": "`genbi datagen`"}.get(
        stage, "`genbi gates` (it runs every gate, DAX included)")
    shown = problems[:25] + ([f"… and {len(problems) - 25} more"] if len(problems) > 25 else [])
    return FIX.format(n=len(problems), problems="\n".join(f"- {p}" for p in shown), commands=commands)
