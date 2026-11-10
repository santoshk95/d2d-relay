PASDACS looks like a well-made tool: near-black ink, white space, one bright mint, and type that is bold where it matters and quiet everywhere else. The mint means "it works": the cursor in the logo, a check that passed, a pillar that is ready. Use it sparingly so it keeps that meaning.

This pack is taken from the live pasdacs.com code. The light theme is the site exactly. The dark theme is a proposal for RELAY by PASDACS, built from the same scale; the site itself has no dark mode.

## Content fundamentals

**Voice.** Plain, practical and specific. Short sentences. Outcomes over jargon. Write as "we" (PASDACS) to "you" (the client's team).

- Say what happens: "Routine bank and ledger matches happen automatically; only the items that don't match reach a person."
- Name real things: Power BI, Tally, Dynamics 365, a month-end close, a GST tie-out.
- Keep a person in the sentence: "with a person approving everything that matters."
- Proof before claims: "every figure checked against its source", "results proven before they ship."

**Never:**
- Invent a client, number, partner, product, person or certification. A figure needs a source; until a pilot produces one, leave the number out.
- Use superlatives ("world-class", "leading", "#1") or compare with other firms.
- Use emoji in product or marketing copy.

**Casing and spelling.** Sentence case for headings and buttons ("Contact us", "Book a demo"). Uppercase only in the `eyebrow` style. British/Indian English spelling: organisation, programme, standardise, catalogue. The pillar names are proper nouns: Process, Automation, Systems, Data Analytics, Artificial Intelligence (AI in running text), Consulting Services, Support.

**Real copy to model on**

| Where | Copy |
| --- | --- |
| Hero | Your partner, from business plan to proven results. |
| Section | What we do is in our name |
| Band | Fast-forward your agentic journey |
| Steps | Talk · Build & prove · Grow |
| Closing | Have something in mind? |
| Form note | Every enquiry is read by a person on the team that can help. |

## Visual foundations

**Colour.** The brand is mono plus one hue.
- Ground is `surface`; alternate bands use `surface-alt`. Set text in `ink`, secondary text in `ink-muted`, captions and resting icons in `ink-subtle`.
- Mint text is always `accent-text` (`accent-600` in light). `accent-500` is the logo mint: use it for fills, dots, glows and the mark's cursor, never for text on white.
- The main action is `primary-fill` with `on-primary`. A second, mint action uses `accent-fill` with `on-accent`.
- Dark bands (the agentic section, the footer) use a 135° gradient `brand-900` → `brand-800` → `brand-700`, white headings, `brand-100` body and `accent-400` eyebrows.
- Status: `success` and `danger` always carry a word or icon, never colour alone.
- Hairlines (`line`) separate cards; there are no coloured left-border accents and no blue or purple anywhere.

**Type.** Two Google faces plus the system mono.
- `display` (Manrope, 800) for every heading: `hero`, `page-title`, `band-title`, `section-title`, `pillar-letter`; `card-title` at 700. Headings use tight negative tracking and balanced wrapping.
- `sans` (Inter) for everything else: `lede`, `body`, `small`, `button`. Turn on Inter's `cv11` and `ss01` features.
- `eyebrow`: 14px bold uppercase, 0.1em tracking, in `accent-text`, above a `section-title`.
- `mono` (`terminal`) for agent output, logs, IDs and the terminal motif.

**Layout and spacing.** Content sits in a `container-max` column with `gutter-sm` / `gutter-md` / `gutter-lg` sides. Sections breathe: `section-y-sm` → `section-y-lg`. A heading block is followed by `heading-gap`. Card grids are joined by 1px `line` gaps inside one `radius-card` frame, rather than floating separate cards.

**Shape.** `radius-btn` (8px) for buttons, `radius-card` (16px) for cards and panels, `radius-full` for pills and dots. The logo tile is `radius-mark` at 48px.

**Depth.** Flat by default. Only buttons cast shadows: `shadow-btn` at rest, `shadow-btn-hover` with a 1px lift on hover, `shadow-glow` for the white button on dark.

**Texture.** Two quiet backgrounds, both fading out:
- an engineering grid at `grid-pitch` in 5% ink, masked to a soft ellipse;
- a mint dot lattice at `dot-pitch` (14% `accent-600`) with a faint mint glow in the top-right, on `brand-50`.

**Motion.** Slow and purposeful; ease `cubic-bezier(0.22, 1, 0.36, 1)`.
- Headlines reveal word by word; sections fade up 14px.
- Cards get a pointer-following mint spotlight (10% `accent-500`) on hover.
- Links draw an underline in from the left.
- The hero types a terminal command, then ticks each pillar "✓ ready".
- Page changes cross-fade with a slight rise; the header stays still.
- Under `prefers-reduced-motion`, everything shows in its final state at once.

**States.** Hover lifts primary buttons 1px; press scales to 0.98; focus is a 2px solid `focus-ring` outline with 2px offset on every element. Disabled is 50% opacity with no pointer events.

## Iconography

Line icons from Lucide (`lucide-react`), 20px, 2px stroke, in `ink-subtle`, turning `accent-text` on hover. The pillars use Workflow (Process), Zap (Automation), MonitorSmartphone (Systems), BarChart3 (Data Analytics), Sparkles (AI), Compass (Consulting Services) and LifeBuoy (Support). Add icons from the same set only. No emoji, no filled or duotone icons.

## Logo

The "fast forward" mark: a rounded `brand-900` tile, two white chevrons (>>) running into a mint cursor. It stands for speed, and for "we run the fix". Files are in the Logos group:
- `logo.svg` on light grounds and `logo-dark.svg` on dark grounds (white tile, ink chevrons).
- `logo-mark.svg` alone where space is square.
- `favicon-mark.svg` below 48px (heavier strokes).
- PNGs for email signatures, structured data and social cards.

Rules:
- The wordmark is PASDACS in Manrope 800, tracked +3, one tile-width to the right of the mark.
- Keep clear space of at least half the tile around it.
- Never recolour the chevrons or the cursor, stretch it, add effects, or set it on a busy image.
- The cursor is always `accent-500`.

## RELAY by PASDACS

See the "Applying to Relay" section for how Relay takes on this identity.
