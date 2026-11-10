"""The document & deck engine (build-plan v2, P11 — Consulting studio).

A deck or a document is described in YAML (deck.yaml / doc.yaml, see spec.py): title, audience, template, sections
of slides (or blocks) with a layout — title, bullets, two-column, table, chart, diagram, quote, closing — speaker
notes, and every figure with a `source` reference (a dashboard measure, a table in the brief's attachments, an
Assess / Programme / RFP record, a library item). Nothing invented: a figure without a source is a check failure.

  build.build(spec_path, out_dir, ...)   -> deck.pptx / doc.docx (python-pptx / python-docx), the HTML twin
                                            (same content, CSS from the brand tokens; the web app previews it and
                                            renders it to PDF through the agent's Chromium), check.json
  checks.run(...)                        -> every check: sources resolve, numbers vs source, no placeholder text,
                                            limits, contrast, alt text, house style (fonts, title lengths, British
                                            spelling), nothing from outside the tenant's folder
  template.default_template(brand)       -> the RELAY template from the PASDACS brand tokens (partner white-label:
                                            the partner's name and colour, "Powered by PASDACS Relay" on the closing
                                            slide); template.load_template(path) opens a tenant .pptx / .potx
  diagrams.render(mermaid)               -> SVG (and native shapes in the deck) from Mermaid flowchart text; PNG
                                            through headless Chromium where Playwright is installed (the agent image)
  charts.svg(chart)                      -> inline SVG for the twin; the deck gets native PowerPoint charts

`genbi deck build|check` and `genbi doc build|check` (cli.py) wrap it for the agent."""
from .spec import DocError, LAYOUTS, load, normalise, shape_errors  # noqa: F401
from .template import Template, default_template, load_template  # noqa: F401
