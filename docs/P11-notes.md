# P11 — Consulting studio: status note

Built 2026-11-05 on branch `worktree-agent-adb0ae5f2ab753a27` (build-plan v2, P11: Proposals, decks & documents;
RFP & bid response; the Architecture "Present" and Strategy "Deck" steps; Assess & estimate's proposal pack).
Everything below runs on mocks in throwaway containers with the worktree mounted over the images (`docs/parallel-work.md`
rule 2); the live install was not touched and no image was rebuilt.

## What is built and where

| Piece | Where |
|---|---|
| **Document & deck engine**: deck.yaml / doc.yaml → .pptx (python-pptx: native charts, native tables, diagrams as grouped native shapes, alt text, speaker notes, partner closing slide) or .docx (python-docx: charts and diagrams as PNG rendered in headless Chromium, else the data as a table) + the HTML twin (CSS from the brand tokens, every figure linked to its evidence, inline SVG charts / diagrams, print CSS for the PDF) + check.json; Mermaid flowcharts parsed and laid out here; the RELAY template generated from the Night & Signal tokens, tenant .pptx / .potx / .docx / .dotx kept with their layouts and theme; partner white-label ("Powered by PASDACS Relay") | `genbi_kit/docs/` (`spec.py`, `sources.py`, `template.py`, `charts.py`, `diagrams.py`, `pptx_build.py`, `docx_build.py`, `twin.py`, `checks.py`, `build.py`) |
| The checks: every figure has a resolvable source and agrees with its value (numbers vs source), no placeholder text, template limits (slides, bullets, titles, table rows), colour contrast (4.5:1 body, 3:1 large titles; from the tenant file's theme or the partner colour), alt text / captions, house style (title lengths, British spelling list, the tenant's notes), nothing read from outside the project folder | `genbi_kit/docs/checks.py` |
| Toolkit commands `genbi deck build\|check` and `genbi doc build\|check` (the agent's loop) | `genbi_kit/cli.py` (sub-parsers appended at the end) |
| **Studio** (Brief → Outline → Draft → Check → Review → Final): folder `kind: deliverable` with brief.md, sources/, outline.yaml, deck.yaml / doc.yaml, builds/vN/; jobs `studio_outline` (llm), `studio_draft` (llm, build + checks with fix rounds on the resumed session), `studio_build` (rebuild after an edit by hand); checkpoints `studio.outline` (view plan; reorder / cut / add in the UI) and `studio.final` (view link to the twin and PDF; comments in place; send back = another draft round); downloads; "File to …" through a write-scoped connection (`connectors.request_write` → `connection.write` checkpoint); "Send by mail" through `mailer` only after the final is accepted; ten deliverable types; the Home "Studio" card with its empty state | `webapp/app/studio.py`, `studio_prompts.py`, `webapp/static/js/28-studio.js` (routes `#/studio`, `#/studio/<id>`), `19-home.js` (one fetch + one card) |
| Sources the agent may quote (snapshots into `sources/`): dashboards (plan.yaml KPIs with the values Power BI's engine returned from `versions/vN/dax.json`), starts (confirmed views), RFP responses, the practice pulse (`home.build` KPIs), the registry's module facts, library items, attachments read with the P10 reader, brand.json + the tenant template files | `studio.snapshot_sources`, `studio.write_brand` |
| Templates per tenant: Admin › Branding gains the PowerPoint and Word templates (data URLs ≤ 2 MB in the secrets-free `branding` meta, never returned with the brand) and house-style notes | `webapp/app/registry.py` (`TEMPLATE_KEYS`, `templates()`, `BrandIn` fields, `_check_template`), `js/20-modules.js` (`adminBranding`) |
| **RFP & bid response** (Qualify → Understand → Answer → Price → Review → Submit → Learn): folder `kind: rfp`; jobs `rfp_read` (requirements.yaml with page references + gonogo.yaml), `rfp_answer` (matrix.yaml), `rfp_redteam` (redteam.yaml), `rfp_pack` (the submission pack through the studio engine); checkpoints `rfp.requirements` (table), `rfp.gonogo` (text, the named decider), `rfp.matrix` (table), `rfp.price` (table), `rfp.review` ×3 (technical / commercial / legal, the red-team findings as evidence), `rfp.submit` (link, the named decider); the past-responses library `rfp_library` (+ `rfp_library_fts`, SQLite FTS5; LIKE over tokens on Postgres) with tags, kinds and promotion from wins; rate cards `rfp_rate_cards`; pricing computed in Python (`compute_price`); "submitted" recorded with who / when / how; outcome + feedback | `webapp/app/rfp.py`, `rfp_prompts.py`, `webapp/static/js/29-rfp.js` (routes `#/rfp`, `#/rfp/<id>`) |
| The submission pack: `response.docx` (+ `.pdf` when the agent can draw), `matrix.xlsx`, `portal-fields.json`, `proposal-deck.pptx` + both HTML twins + both check reports — every figure a `record:` source over the confirmed records | `rfp.build_pack`, `rfp.deck_yaml`, `rfp.response_yaml` |
| Catalogue: `proposals` and `rfp` available (`#/studio`, `#/rfp`); `architecture`, `strategy`, `assess` partly with `stat="Decks through the studio"` and `links={"engage": "studio"}`; `LIVE["studio"]`, `LIVE["rfp"]`; the module pages' last step ("Present", "Deck", "Propose") gets **Prepare the deck in the studio** (pre-fills the brief with the module's facts: `#/studio?type=…&module=…`) | `webapp/app/registry.py`, `js/20-modules.js` |
| Plug-in lines: one import + ROUTERS line in `phases.py`; two route lines in `02-shell.js`; two script lines in `index.html`; one appended block in `css/relay.css`; three `add` lines in `tests/run_all.sh`; routes, axe pages and two flows (gated by `P11_E2E`) in `tests/p9_e2e_test.py` | — |
| Tests | `tests/p11_decks_test.py`, `p11_unit_test.py`, `p11_fixtures.py`, `p11_bin/claude` (fake agent), `p11_studio_test.py`, `p11_rfp_test.py`, `p11_flows.sh` (runner: agent with the fake claude + web app, worktree mounted), `p11_e2e.sh` |

## Done-when evidence

- **A synthetic RFP pack becomes a confirmed requirements list, a go / no-go, a compliance matrix with evidence, a
  priced response and a submission pack + deck, every checkpoint confirmed** — `tests/p11_flows.sh rfp`: the pack
  (Word with 32 numbered requirements across five sections, an Excel pricing sheet, a PDF cover with the deadline —
  `tests/p11_fixtures.py`) is read by the real agent service with the fake `claude` running `genbi read`; 32
  requirements with page references and kinds (17 mandatory / 10 scored / 5 information), the deadline, the portal
  (SAP Ariba), three format rules and the evaluation criteria; the requirements checkpoint confirmed; the go / no-go
  decided by the named person (someone else gets 403); the first matrix cites `library:does-not-exist` → the check
  catches it ("an answer may cite only library items and registry modules") → fix round on the resumed session;
  the matrix confirmed after an edit; the price computed from three rate cards (INR per day, USD per hour × 8 ×
  fx) with licences, run & support and a discount, sent back once, then confirmed; the red-team findings open the
  three reviews; the pack (Word, PDF drawn by the agent's Chromium, Excel matrix with 32 rows, portal fields with
  32 entries, proposal deck with a chart and a price table) passes its checks and is accepted by the named person;
  mail and "submitted" are refused (409) at every earlier step; the win promotes 31 answers into the library
  (tagged won, by module and buyer type, found by full-text search; no duplicates on a second win); every decision
  is in the Validation queue's history; no secret in any payload.
- **An architecture deck and a steering pack from real platform records in both the RELAY and a partner template** —
  `tests/p11_flows.sh studio`: the architecture deck is briefed with an estate spreadsheet, the architecture and
  warehouse module facts and the practice pulse; the outline is reordered and a slide cut before confirming; the
  first draft's unsourced "48 stores" fails the check → fix round → build v1 (pptx, twin, PDF, check.json, nine
  checks passed); review sent back with a comment in place → v2 → accepted as final; filed to a write-scoped mock
  connection only through a `connection.write` checkpoint (nothing written before a person accepts); mail refused
  before the final and reaching the mailer after it; an edit by hand that sneaks in "TODO" rebuilds v3, fails the
  placeholder check and reopens the review. Then the install is switched to a partner brand and a **steering pack**
  is briefed from the practice pulse (Home KPIs of the last 30 days): the build uses the partner template, the deck
  opens with python-pptx with Northwind's name in every footer and "Powered by PASDACS Relay" on the closing slide,
  the house-style notes appear as a warning on the check report.
- **The generated files open and pass the checks** — `tests/p11_decks_test.py` (agent image): the RELAY template
  (every colour pair meets its WCAG AA minimum), a deck read back with python-pptx (8 slides, a native chart with
  the YAML's data, a native table, a grouped diagram, notes, alt text, the closing slide), a document read back
  with python-docx (headings, bullets, a table, two PNG pictures rendered by Playwright's Chromium with alt text,
  the brand footer), the partner swap, a tenant .pptx keeping its layouts, a low-contrast .potx failing the
  contrast check, and the checks catching an unsourced figure, a number that disagrees with its source, placeholder
  text, missing alt text, American spellings, too many bullets and a path outside the project; the twin matches the
  YAML; the CLI builds and checks.

## Tests (all in throwaway containers; images `gen-bi-agent` / `gen-bi-webapp` with the worktree mounted)

| Suite | Command | Result |
|---|---|---|
| `tests/p11_decks_test.py` | `docker run --rm -v "$PWD/tests:/tests:ro" -v "$PWD/genbi_kit:/opt/genbi/genbi_kit:ro" --entrypoint python3 gen-bi-agent /tests/p11_decks_test.py` (run_all line without the mount, after the images are rebuilt) | 51 checks pass |
| `tests/p11_unit_test.py` (mail gate with a fake SMTP, pricing maths, library FTS, matrix evidence rule, requirements check, figure detection, spelling, placeholders) | `docker run … gen-bi-webapp python /tests/p11_unit_test.py` (run_all line) | 32 checks pass |
| `tests/p11_flows.sh studio` → `p11_studio_test.py` | `bash tests/p11_flows.sh studio` | 59 checks pass |
| `tests/p11_flows.sh rfp` → `p11_rfp_test.py` | `bash tests/p11_flows.sh rfp` | 69 checks pass |
| `tests/p11_e2e.sh` (the P9 Playwright sweep with `#/studio`, `#/rfp` for all three roles, axe on both, flows "Studio: brief → outline → draft → check → final" and "RFP: pack → requirements → matrix → price → submit" through the test hooks) | `bash tests/p11_e2e.sh` | 91 pages × roles / themes / phone, 657 checks, 0 failures; 12 of 12 flows pass (the service-desk flow is skipped without its simulator, as designed); axe clean on 12 screens incl. `#/studio` and `#/rfp`; 145 s |
| `tests/brand_gate_test.py` | `docker run --rm -v "$PWD:/repo:ro" --entrypoint python3 gen-bi-agent /repo/tests/brand_gate_test.py` | 0 problems in 46 files |
| `tests/p10_checkpoints_test.py` (regression, worktree mounted) | run_all line | 29 checks pass |

`run_all.sh` gained `p11_decks`, `p11_unit` and `p11_flows` (before `p12_itsm`). `p11_flows.sh` and `p11_e2e.sh`
mount `webapp/app`, `webapp/static` and `genbi_kit` from the checkout, so they are right both on this branch and on
`main` after the merge.

## Design notes (for the merge and the pilot)

- **No new packages.** python-pptx, python-docx, openpyxl, pypdf and Playwright were already in the images (P10);
  no Dockerfile or requirements line was added. SQLite FTS5 is available in the webapp image's sqlite (3.46).
- **Mermaid** is parsed and laid out by `diagrams.py` (flowchart / graph LR TD TB RL, node shapes, labelled, dotted
  and thick edges, chains, `&` groups; subgraphs read and flattened). Other kinds (sequence, gantt …) are reported
  as unsupported: the check warns and the slide shows the text. The deck gets native shapes (editable, alt text on
  the group); the document and the twin's PNG go through headless Chromium (Playwright where installed — the agent
  image — else the web app's callback to the agent's `/render`; without either the document shows the data / the
  description and the build records `pictures_missing`).
- **PDF of the deck** is the HTML twin printed by the agent's `/render` (D12): landscape A4, one slide per page. In
  the throwaway e2e app (no agent) the build records "PDF not drawn" and the page says so; `p11_flows.sh` has the
  agent, so the PDF is produced and checked.
- **Figures** = numbers a reader takes as fact: currency, percentages, thousands with separators, decimals, 4+
  digit numbers (years excluded) and counts with a unit noun ("48 stores"). Each must be declared under `figures`
  with a `source`; where the source holds a value (`record:x#path`, `dashboard:<id>/<measure>` from dax.json,
  `attachment:x.csv#col=key:value` / `#col:sum`) the figure must agree with it. Tables, charts and quotes carry
  their own `source`. Plain small integers in prose are not figures.
- **Tenant boundary**: the resolver refuses any path outside the project folder; the web app only snapshots records
  the person may view (`auth.can_project`) into `sources/`, and library items are tenant-wide by design (single
  tenant until P17 — the P17 isolation suite must cover `rfp_library` and the branding templates).
- **Filing**: `studio.file_to` goes through `connectors.request_write` on any write-scoped connection whose adapter
  can write (today the mock; SharePoint / OneDrive / Google Drive are one adapter + one mock each in the pilot —
  the payload carries the file name, folder, size, sha256 and the build path for the adapter to upload).
- **Mail** goes through `mailer.send` with the person's own account (Gmail app password / Microsoft Graph); the
  studio only after `studio.final` is accepted, the RFP only after `rfp.submit` is accepted; both record the send.
- **Portals** (SAP Ariba, Coupa, Jaggaer, GeM, Loopio, Responsive) are listed on the RFP page with "exports and
  portal fields, upload by hand"; `portal-fields.json` is the export. API submission is pilot work (mock-lab
  simulators exist in `tests/mocklab` for the sign-in kinds).
- **Team & agents**: the new stages (`studio_outline`, `studio_draft`, `rfp_read`, `rfp_answer`, `rfp_redteam`)
  show under their stage names until `team.AGENTS` names them (one line each at consolidation: Writer, Bid writer,
  Red team).
- **Known pre-existing failure on this base**: `tests/p9_shell_test.py` "a viewer sees only viewer modules" fails on
  the P10-merge base because the P12 registry gives viewers `servicedesk`; `main` already carries the updated
  expectation (`servicedesk` in the set). Not touched here.
- Untouched: `main.py`, `connectors.py`, `start.py`, `build-plan.md`, `platform-plan.md`, `test-report.md`,
  `README.md`, the live install, `agent/Dockerfile`, `webapp/requirements.txt`.

## Open points

- A real-model smoke run of the three llm stages (outline, draft, RFP read / answer / red team) has not been done on
  this branch (no live install use); the prompts and YAML shapes are exercised by the fake agent and the app's
  checks only.
- The studio's "comments in place" are recorded per slide number and travel with the send-back; anchoring them on
  the twin itself (click a slide to comment) is a small follow-up.
- Google Slides / Docs output is not produced (listed on the module card); the pptx / docx open in Google's tools.
- Assess & estimate and Programme view are not built yet (W6 / later): their "proposal pack" and "steering pack"
  go through the studio with the records that exist today (dashboards, starts, RFP responses, the practice pulse,
  module facts); when those modules land, their records join `snapshot_sources` as one more `record:` kind each.
