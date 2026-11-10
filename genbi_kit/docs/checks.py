"""The checks a deliverable passes before a person reviews it (build-plan v2 rule 7, §8): every figure has a
resolvable source and agrees with it, no placeholder text, counts within the template's limits, the template's
colours contrast, alt text on every image / chart / diagram, house style (fonts, title lengths, British spelling,
the tenant's own notes), nothing read from outside the project folder. Each check is pass / warn / fail with the
items a fix round needs; `problems()` lists the fail items as the agent's to-do."""
from __future__ import annotations

import re
from pathlib import Path

from . import spec
from .sources import Resolver, split
from .template import BRITISH, PLACEHOLDER_RE, PRODUCT_RE, Template, contrast

ORDER = ("shape", "sources", "numbers", "placeholders", "limits", "contrast", "alt_text", "house_style", "tenant")
LABELS = {"shape": "Shape of the YAML", "sources": "Every figure has a source", "numbers": "Numbers agree with their source",
          "placeholders": "No placeholder text", "limits": "Within the template's limits", "contrast": "Colour contrast",
          "alt_text": "Alt text on every image, chart and diagram", "house_style": "House style", "tenant": "Nothing from outside the tenant's folder"}
WORD_RE = re.compile(r"[A-Za-z]+")


def _item(level: str, text: str) -> dict:
    return {"level": level, "text": text}


def _check(name: str, fails: list[str], warns: list[str] | None = None, ok: str = "") -> dict:
    warns = warns or []
    status = "fail" if fails else "warn" if warns else "pass"
    return {"check": name, "label": LABELS[name], "status": status, "summary": (f"{len(fails)} problem(s)" if fails else f"{len(warns)} warning(s)" if warns else ok or "ok"),
            "items": [_item("fail", f) for f in fails] + [_item("warn", w) for w in warns]}


def _where(u: dict, kind: str) -> str:
    return f"{'slide' if kind == 'deck' else 'block'} {u['n']}" + (f" “{u['title'][:40]}”" if u["title"] else "")


def run(model: dict, template: Template, resolver: Resolver, shape_errs: list[str] | None = None) -> dict:
    """Every check over a normalised model. Returns {"ok", "checks": [...], "counts": {...}}."""
    kind = model["kind"]
    units = [u for s in model["sections"] for u in s["units"]]
    checks = [_check("shape", list(shape_errs or []), ok="valid")]

    # ---- sources: every figure, table, chart, quote and image names a source that resolves; numbers agree
    src_fail, src_warn, num_fail, tenant_fail, n_refs = [], [], [], [], 0
    for u in units:
        where = _where(u, kind)
        declared = u["figures"]
        for f in declared:
            if not f["source"]:
                src_fail.append(f"{where}: figure {f['text'] or f['value']!r} has no source")
                continue
            n_refs += 1
            r = resolver.resolve(f["source"])
            if not r["ok"]:
                (tenant_fail if "tenant" in r["why"] else src_fail).append(f"{where}: figure {f['text'] or f['value']!r} — {f['source']}: {r['why']}")
            elif r.get("value") is not None:
                want = f["value"] if f["value"] is not None else spec.norm_number(f["text"])
                try:
                    want_f = float(want)
                except (TypeError, ValueError):
                    want_f = None
                if want_f is not None and abs(want_f - float(r["value"])) > max(0.5, abs(float(r["value"])) * 0.005):
                    num_fail.append(f"{where}: figure {f['text'] or f['value']!r} says {want_f:g} but {f['source']} holds {float(r['value']):g}")
        # numbers in the prose must be declared figures
        covered = {spec.norm_number(f["text"]) for f in declared if f["text"]} | {spec.norm_number(str(f["value"])) for f in declared if f["value"] is not None}
        for t in spec.figure_texts(u):
            for tok in spec.figure_tokens(t):
                if spec.norm_number(tok) not in covered:
                    src_fail.append(f"{where}: the number {tok!r} in “{t[:60]}” is not a declared figure with a source (add it under figures, or take it out)")
        for part, label in ((u["table"], "table"), (u["chart"], "chart"), (u["quote"], "quote")):
            if not part:
                continue
            if not part.get("source"):
                src_fail.append(f"{where}: the {label} has no source")
                continue
            n_refs += 1
            r = resolver.resolve(part["source"])
            if not r["ok"]:
                (tenant_fail if "tenant" in r["why"] else src_fail).append(f"{where}: {label} source {part['source']}: {r['why']}")
        if u["image"]:
            r = resolver.resolve(u["image"]["file"])
            if not r["ok"]:
                (tenant_fail if "tenant" in r["why"] else src_fail).append(f"{where}: image {u['image']['file']}: {r['why']}")
        if u["diagram"] and u["diagram"].get("source"):
            r = resolver.resolve(u["diagram"]["source"])
            if not r["ok"]:
                (tenant_fail if "tenant" in r["why"] else src_warn).append(f"{where}: diagram source {u['diagram']['source']}: {r['why']}")
    checks.append(_check("sources", src_fail, src_warn, ok=f"{n_refs} source reference(s) resolve"))
    checks.append(_check("numbers", num_fail, ok="every figure with a value in its source agrees with it"))

    # ---- placeholders
    ph = []
    for u in units:
        for t in spec.reader_texts(u) + ([u["notes"]] if u["notes"] else []):
            m = PLACEHOLDER_RE.search(t)
            if m:
                ph.append(f"{_where(u, kind)}: placeholder text {m.group(0)!r} in “{t[:60]}”")
    for t in (model["title"], model["subtitle"]):
        if t and PLACEHOLDER_RE.search(t):
            ph.append(f"title: placeholder text in “{t[:60]}”")
    checks.append(_check("placeholders", ph, ok="no lorem, TODO or xxx"))

    # ---- limits
    lim = template.limits
    lf, lw = [], []
    if kind == "deck" and len(units) > lim["max_slides"]:
        lf.append(f"{len(units)} slides; the template allows {lim['max_slides']}")
    if kind == "doc":
        paras = sum(1 for u in units if u["layout"] in ("paragraph", "bullets"))
        if paras > lim["max_doc_paragraphs"]:
            lf.append(f"{paras} paragraphs; the template allows {lim['max_doc_paragraphs']}")
    for u in units:
        where = _where(u, kind)
        bullets = u["bullets"] + u["left"]["bullets"] + u["right"]["bullets"]
        if kind == "deck" and len(u["bullets"]) > lim["max_bullets"]:
            lf.append(f"{where}: {len(u['bullets'])} bullets; at most {lim['max_bullets']} per slide")
        for b in bullets:
            if len(b) > lim["max_bullet_chars"]:
                lw.append(f"{where}: a bullet is {len(b)} characters long (keep under {lim['max_bullet_chars']}): “{b[:50]}…”")
        if u["table"]:
            if len(u["table"]["rows"]) > lim["max_table_rows"]:
                (lf if kind == "deck" else lw).append(f"{where}: table has {len(u['table']['rows'])} rows; at most {lim['max_table_rows']} on a slide")
            if len(u["table"]["columns"]) > lim["max_table_cols"]:
                lw.append(f"{where}: table has {len(u['table']['columns'])} columns; at most {lim['max_table_cols']} read well")
    checks.append(_check("limits", lf, lw, ok=f"{len(units)} {'slides' if kind == 'deck' else 'blocks'} within limits"))

    # ---- contrast of the template's colours
    cf, cw = [], []
    for what, fg, bg, need in template.contrast_pairs():
        ratio = contrast(fg, bg)
        if ratio < need:
            (cw if what.startswith("muted") and ratio >= 3 else cf).append(f"{what}: {fg} on {bg} is {ratio}:1 (needs {need}:1)")
    checks.append(_check("contrast", cf, cw, ok="body text 4.5:1, large titles 3:1 (WCAG 2 AA)"))

    # ---- alt text
    af = []
    for u in units:
        where = _where(u, kind)
        if u["chart"] and not u["chart"]["alt"]:
            af.append(f"{where}: the chart needs alt text (what it shows, in one sentence)")
        if u["diagram"] and not u["diagram"]["alt"]:
            af.append(f"{where}: the diagram needs alt text")
        if u["image"] and not u["image"]["alt"]:
            af.append(f"{where}: the image needs alt text")
        if u["table"] and not (u["table"]["caption"] or u["table"]["alt"]):
            af.append(f"{where}: the table needs a caption")
    checks.append(_check("alt_text", af, ok="every chart, diagram, image and table is described"))

    # ---- house style: title lengths, British spelling, fonts (the template's), the tenant's notes
    hf, hw = [], []
    if model["title"] and len(model["title"]) > lim["max_title_chars"]:
        hw.append(f"the title is {len(model['title'])} characters (keep under {lim['max_title_chars']})")
    for u in units:
        where = _where(u, kind)
        if u["title"] and len(u["title"]) > lim["max_title_chars"]:
            hf.append(f"{where}: title is {len(u['title'])} characters (keep under {lim['max_title_chars']})")
        for t in spec.reader_texts(u):
            for w in WORD_RE.findall(PRODUCT_RE.sub(" ", t)):        # a product's own name keeps its spelling
                lw_ = w.lower()
                if lw_ in BRITISH:
                    hf.append(f"{where}: “{w}” — the house style spells it “{BRITISH[lw_]}”")
                    break
    if template.notes:
        hw.extend(template.notes)
    if template.brand.get("house_style"):
        hw.append("House style notes to follow: " + template.brand["house_style"][:300])
    checks.append(_check("house_style", hf, hw, ok=f"fonts {template.fonts['head']} / {template.fonts['body']}, titles short, British spelling"))

    # ---- tenant boundary (also any raw path in the YAML that the source checks did not already report)
    for u in units:
        for ref in [f["source"] for f in u["figures"]] + [p["source"] for p in (u["table"], u["chart"], u["quote"]) if p] + ([u["image"]["file"]] if u["image"] else []):
            scheme, rest, _ = split(ref)
            if scheme == "file" and rest and not resolver.inside(rest) and not any(rest in m for m in tenant_fail):
                tenant_fail.append(f"{_where(u, kind)}: {rest} is outside the project folder")
    checks.append(_check("tenant", tenant_fail, ok="every path stays inside the project folder"))

    ok = all(c["status"] != "fail" for c in checks)
    return {"ok": ok, "checks": checks, "counts": {"units": len(units), "figures": sum(len(u["figures"]) for u in units), "refs": n_refs,
                                                  "fails": sum(len([i for i in c["items"] if i["level"] == "fail"]) for c in checks),
                                                  "warnings": sum(len([i for i in c["items"] if i["level"] == "warn"]) for c in checks)},
            "template": template.name, "kind": kind}


def problems(report: dict) -> list[str]:
    """The fail items, each prefixed with its check, for the agent's fix round."""
    return [f"{c['label']}: {i['text']}" for c in report["checks"] for i in c["items"] if i["level"] == "fail"]


def text_report(report: dict, name: str = "") -> str:
    mark = {"pass": "OK ", "warn": "WRN", "fail": "ERR"}
    lines = [f"Checks for {name or report.get('kind', 'the deliverable')} — {'passed' if report['ok'] else 'FAILED'} ({report['counts']['fails']} problems, {report['counts']['warnings']} warnings)"]
    for c in report["checks"]:
        lines.append(f"[{mark[c['status']]}] {c['label']} — {c['summary']}")
        for i in c["items"]:
            lines.append(f"      {i['level']}: {i['text']}")
    return "\n".join(lines)
