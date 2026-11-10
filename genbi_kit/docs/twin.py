"""The HTML twin: the same content as the deck or document, one self-contained page with CSS from the brand tokens.
The web app shows it as the preview, lets reviewers comment on it, and renders it to PDF through the agent's
Chromium (/render, landscape A4 — one slide per page). Every figure, table, chart and quote carries its source and a
link to the evidence; charts and diagrams are inline SVG with titles for screen readers."""
from __future__ import annotations

from html import escape

from . import charts, diagrams, spec
from .template import Template


def _fig(text: str, figures: list[dict], resolver, base: str) -> str:
    """Numbers in prose wrapped as figures with their source (title + link)."""
    out, pos = [], 0
    for start, end, tok in spec.figure_spans(text):
        if start < pos:
            continue
        norm = spec.norm_number(tok)
        f = next((f for f in figures if spec.norm_number(f["text"] or "") == norm or (f["value"] is not None and spec.norm_number(str(f["value"])) == norm)), None)
        out.append(escape(text[pos:start]))
        if f and f.get("source"):
            r = resolver.resolve(f["source"])
            name = r.get("name") or r.get("path") or f["source"]
            out.append(f'<a class="fig{"" if r["ok"] else " bad"}" href="{escape(base + f["source"])}" title="Source: {escape(name)}" data-source="{escape(f["source"])}">{escape(tok)}</a>')
        else:
            out.append(f'<span class="fig bad" title="No source">{escape(tok)}</span>')
        pos = end
    out.append(escape(text[pos:]))
    return "".join(out)


def _source_line(ref: str, resolver, base: str) -> str:
    if not ref:
        return '<div class="src bad">No source</div>'
    r = resolver.resolve(ref)
    name = r.get("name") or r.get("path") or ref
    return f'<div class="src{"" if r["ok"] else " bad"}">Source: <a href="{escape(base + ref)}" data-source="{escape(ref)}">{escape(name)}</a>' + ("" if r["ok"] else f" — {escape(r['why'])}") + "</div>"


def _bullets(items: list[str], figures, resolver, base) -> str:
    return "<ul>" + "".join(f"<li>{_fig(b, figures, resolver, base)}</li>" for b in items) + "</ul>"


def _table(tbl: dict, resolver, base) -> str:
    head = "".join(f"<th>{escape(c)}</th>" for c in tbl["columns"])
    rows = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in tbl["rows"])
    cap = f"<caption>{escape(tbl['caption'] or tbl['alt'])}</caption>" if (tbl["caption"] or tbl["alt"]) else ""
    return f'<table class="data">{cap}<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>' + _source_line(tbl["source"], resolver, base)


def unit_html(u: dict, t: Template, resolver, base: str, kind: str) -> str:
    c = t.colours
    lay, figs = u["layout"], u["figures"]
    body = []
    if lay in ("title", "closing"):
        body.append(f'<div class="hero"><div class="bar"></div><h1>{escape(u["title"] or "")}</h1>' + (f'<p class="sub">{escape(u["subtitle"])}</p>' if u["subtitle"] else "")
                    + (_bullets(u["bullets"], figs, resolver, base) if u["bullets"] else "") + (f'<p class="powered">{escape(t.powered)}</p>' if t.partner and lay == "closing" else "") + "</div>")
    else:
        if u["title"]:
            body.append(f'<header class="band"><h2>{_fig(u["title"], figs, resolver, base)}</h2>' + (f'<p class="sub">{_fig(u["subtitle"], figs, resolver, base)}</p>' if u["subtitle"] else "") + "</header>")
        if lay in ("bullets", "paragraph", "heading"):
            if u["text"]:
                body.append(f"<p>{_fig(u['text'], figs, resolver, base)}</p>")
            if u["bullets"]:
                body.append(_bullets(u["bullets"], figs, resolver, base))
        elif lay == "two-column":
            cols = []
            for side in ("left", "right"):
                col = u[side]
                cols.append('<div class="col">' + (f"<h3>{_fig(col['heading'], figs, resolver, base)}</h3>" if col["heading"] else "") + _bullets(col["bullets"], figs, resolver, base) + "</div>")
            body.append('<div class="cols">' + "".join(cols) + "</div>")
        elif lay == "table" and u["table"]:
            body.append(_table(u["table"], resolver, base))
        elif lay == "chart" and u["chart"]:
            body.append('<figure>' + charts.svg(u["chart"], c) + (f"<figcaption>{escape(u['chart']['alt'])}</figcaption>" if u["chart"]["alt"] else "") + "</figure>" + _source_line(u["chart"]["source"], resolver, base))
        elif lay == "diagram" and u["diagram"]:
            r = diagrams.render(u["diagram"]["mermaid"], c, u["diagram"]["alt"])
            body.append('<figure class="dg">' + r["svg"] + (f"<figcaption>{escape(u['diagram']['alt'])}</figcaption>" if u["diagram"]["alt"] else "") + (f'<pre class="mermaid">{escape(u["diagram"]["mermaid"])}</pre>' if r["kind"] != "flowchart" else "") + "</figure>")
        elif lay == "quote" and u["quote"]:
            q = u["quote"]
            body.append(f'<blockquote><p>{escape(q["text"])}</p>' + (f"<footer>— {escape(q['who'])}</footer>" if q["who"] else "") + "</blockquote>" + _source_line(q["source"], resolver, base))
        elif lay == "image" and u["image"]:
            im = u["image"]
            body.append(f'<figure><div class="imgbox" role="img" aria-label="{escape(im["alt"])}">{escape(im["file"])}</div><figcaption>{escape(im["alt"])}</figcaption></figure>')
    if u["notes"]:
        body.append(f'<aside class="notes"><b>Speaker notes</b> {escape(u["notes"])}</aside>')
    tag = "section" if kind == "deck" else "div"
    return f'<{tag} class="slide l-{lay}" id="u{u["n"]}" data-n="{u["n"]}">' + "".join(body) + (f'<footer class="foot"><span>{escape(t.footer())}</span><span>{u["n"]}</span></footer>' if kind == "deck" else "") + f"</{tag}>"


def css(t: Template) -> str:
    c, f = t.colours, t.fonts
    return f"""
:root{{--bg:{c['bg']};--paper:{c.get('paper', '#F7F9FB')};--text:{c['text']};--muted:{c['muted']};--accent:{c['accent']};--accent-text:{c['accent_text']};--band:{c['band']};--band-text:{c['band_text']};--line:{c['line']};--night:{c.get('night', '#111111')};
--font-head:"{f['head']}","Manrope","Segoe UI",system-ui,sans-serif;--font:"{f['body']}","Inter","Segoe UI",system-ui,sans-serif}}
*{{box-sizing:border-box}}html,body{{margin:0;background:var(--paper);color:var(--text);font:15px/1.5 var(--font)}}
.twin{{display:flex;flex-direction:column;gap:24px;padding:24px;align-items:center}}
.slide{{position:relative;width:1280px;min-height:720px;background:var(--bg);border:1px solid var(--line);box-shadow:0 2px 12px rgba(0,0,0,.08);display:flex;flex-direction:column;overflow:hidden;font-size:20px}}
.doc .slide{{width:900px;min-height:0;border:0;box-shadow:none;background:transparent;font-size:16px;padding:0 0 12px}}
.band{{background:var(--band);color:var(--band-text);padding:28px 48px}}.band h2{{margin:0;font:700 34px/1.2 var(--font-head);letter-spacing:-.02em}}.band .sub{{margin:6px 0 0;opacity:.85;font-size:18px}}
.doc .band{{background:transparent;color:var(--band);padding:18px 0 4px}}.doc .band h2{{font-size:24px}}
.slide>p,.slide>ul,.slide>figure,.slide>table,.slide>.cols,.slide>blockquote,.slide>aside{{margin:18px 48px}}.doc .slide>*{{margin-left:0;margin-right:0}}
ul{{padding-left:28px}}li{{margin:8px 0}}.cols{{display:flex;gap:40px}}.col{{flex:1}}.col h3{{margin:0 0 8px;font:700 22px var(--font-head);color:var(--accent-text)}}
.hero{{flex:1;background:linear-gradient(135deg,var(--night),#1C1C1C 55%,#262626);color:#fff;padding:120px 72px 60px;display:flex;flex-direction:column;justify-content:center}}.hero .bar{{width:84px;height:7px;background:var(--accent);margin-bottom:22px}}
.hero h1{{margin:0;font:800 54px/1.1 var(--font-head);letter-spacing:-.03em}}.hero .sub{{font-size:24px;color:#33D6A6;margin:16px 0 0}}.hero ul{{margin-top:20px;color:#E5E5E5}}.hero .powered{{color:#33D6A6;font-weight:700;margin-top:28px}}
.doc .hero{{background:transparent;color:var(--text);padding:0 0 12px}}.doc .hero h1{{color:var(--band)}}.doc .hero .sub{{color:var(--muted)}}
table.data{{border-collapse:collapse;width:calc(100% - 96px);font-size:16px}}.doc table.data{{width:100%}}table.data th,table.data td{{border:1px solid var(--line);padding:7px 10px;text-align:left}}table.data th{{background:var(--paper);font-weight:700}}table.data caption{{text-align:left;color:var(--muted);font-size:14px;padding:4px 0}}
figure{{margin:18px 48px}}figure svg{{width:100%;height:auto;max-height:520px}}figcaption{{color:var(--muted);font-size:14px;margin-top:4px}}.imgbox{{border:1px dashed var(--line);padding:30px;color:var(--muted);text-align:center}}
blockquote{{border-left:5px solid var(--accent);padding:6px 24px;font:italic 28px/1.4 var(--font-head);color:var(--accent-text)}}blockquote footer{{font:16px var(--font);color:var(--muted);margin-top:8px}}
.src{{margin:0 48px;font-size:13px;color:var(--muted)}}.doc .src{{margin:0}}.src a{{color:var(--accent-text)}}.src.bad,.fig.bad{{color:#B4332B}}
a.fig{{color:inherit;text-decoration:underline dotted var(--accent);text-underline-offset:3px;font-variant-numeric:tabular-nums}}
.notes{{margin-top:auto;background:var(--paper);border-top:1px solid var(--line);padding:10px 48px;font-size:14px;color:var(--muted)}}
.foot{{display:flex;justify-content:space-between;padding:8px 48px 12px;font-size:12px;color:var(--muted)}}
pre.mermaid{{font:13px/1.4 ui-monospace,Consolas,monospace;color:var(--muted);background:var(--paper);padding:12px;white-space:pre-wrap}}
@media print{{html,body{{background:#fff}}.twin{{padding:0;gap:0;display:block}}.slide{{width:277mm;height:156mm;min-height:0;border:0;box-shadow:none;page-break-after:always;break-after:page;font-size:14px;zoom:.8}}.doc .slide{{height:auto;page-break-after:auto;break-after:auto}}.notes{{display:none}}}}
"""


def html(model: dict, template: Template, resolver, evidence_base: str = "", report: dict | None = None) -> str:
    units = [u for s in model["sections"] for u in s["units"]]
    kind = model["kind"]
    parts = [unit_html(u, template, resolver, evidence_base, kind) for u in units]
    if kind == "deck":
        if not units or units[0]["layout"] != "title":
            parts.insert(0, unit_html({"n": 0, "layout": "title", "title": model["title"], "subtitle": model["subtitle"] or (f"For {model['audience']}" if model["audience"] else ""),
                                       "bullets": [], "notes": "", "figures": [], "text": "", "left": {"heading": "", "bullets": []}, "right": {"heading": "", "bullets": []},
                                       "table": None, "chart": None, "diagram": None, "quote": None, "image": None, "section": ""}, template, resolver, evidence_base, kind))
        if not units or units[-1]["layout"] != "closing":
            parts.append(unit_html({"n": len(units) + 1, "layout": "closing", "title": "Thank you", "subtitle": "", "bullets": [], "notes": "", "figures": [], "text": "",
                                    "left": {"heading": "", "bullets": []}, "right": {"heading": "", "bullets": []}, "table": None, "chart": None, "diagram": None, "quote": None, "image": None, "section": ""},
                                   template, resolver, evidence_base, kind))
    else:
        head = (f'<div class="slide l-title"><div class="hero"><div class="bar"></div><h1>{escape(model["title"])}</h1>'
                + (f'<p class="sub">{escape(model["subtitle"])}</p>' if model["subtitle"] else "")
                + (f'<p class="sub">For {escape(model["audience"])}</p>' if model["audience"] else "") + "</div></div>")
        parts.insert(0, head)
        out = []
        for s in model["sections"]:
            out.append(f'<h2 class="sec">{escape(s["title"])}</h2>')
            out += [unit_html(u, template, resolver, evidence_base, kind) for u in s["units"]]
        parts = [head] + out + [f'<div class="slide"><footer class="foot"><span>{escape(template.footer())}</span></footer></div>']
    badge = ""
    if report:
        badge = f'<div class="check {"ok" if report["ok"] else "bad"}" style="position:fixed;right:12px;top:12px;font:600 12px var(--font);padding:4px 10px;border-radius:999px;background:{"#E6F4EC" if report["ok"] else "#FBEAE8"};color:{"#1B7A45" if report["ok"] else "#B4332B"}">Checks: {"passed" if report["ok"] else str(report["counts"]["fails"]) + " problem(s)"}</div>'
    return (f'<!doctype html><html lang="{escape(model.get("language") or "en-GB")}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(model['title'])} — {escape(template.owner)}</title><style>{css(template)}</style></head>"
            f'<body class="{kind}"><main class="twin {kind}" data-units="{len(units)}" data-kind="{kind}">{badge}' + "".join(parts) + "</main></body></html>")
