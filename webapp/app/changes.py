"""What changed between two versions of a report definition, in words a business user reads: pages, visuals,
measures (with the DAX before and after), the data model, the look and the filters."""


def _norm(x) -> str:
    return " ".join(str(x).split()) if x is not None else ""


def _pages(d: dict) -> dict:
    """page name -> {visual id -> visual}, in page order."""
    out = {}
    for p in (d or {}).get("pages") or []:
        visuals = list(p.get("visuals") or [])
        for row in p.get("rows") or []:
            visuals += list(row.get("visuals") or [])
        out[p.get("name", "?")] = {str(v.get("id")): v for v in visuals if isinstance(v, dict)}
    return out


def _label(v: dict) -> str:
    """How a business user knows a visual: its static title, else its subtitle or header, else its id."""
    title, kind = v.get("title"), str(v.get("type", "visual"))
    header = (v.get("format") or {}).get("header") if isinstance(v.get("format"), dict) else None
    if isinstance(title, str) and title.strip() and not title.strip().startswith("["):
        name = title.strip()
    elif v.get("subtitle"):
        name = v["subtitle"]
    elif isinstance(header, dict) and header.get("title"):
        name = header["title"]
    elif isinstance(v.get("format"), dict) and isinstance(v["format"].get("kpi"), dict) and v["format"]["kpi"].get("label"):
        name = v["format"]["kpi"]["label"]
    else:
        name = v.get("id")
    return f"{name} ({kind}{' · ' + v['chart'] if v.get('chart') else ''})"


ASPECTS = (("type", "visual type"), ("chart", "chart type"), ("title", "title"), ("subtitle", "subtitle"),
           ("fields", "fields"), ("format", "formatting"), ("sort", "sort order"), ("span", "width"))


def _by_name(items, key="name") -> dict:
    return {str(i.get(key)): i for i in items or [] if isinstance(i, dict)}


def _rel(r) -> str:
    if isinstance(r, str):
        return _norm(r)
    return _norm(f"{r.get('from')} -> {r.get('to')}") if isinstance(r, dict) else _norm(r)


def diff(old: dict | None, new: dict) -> dict:
    """{"summary": [lines], "sections": [{"title", "items": [{"kind", "text", "before", "after"}]}]}."""
    sections: list[dict] = []

    def section(title, items):
        if items:
            sections.append({"title": title, "items": items})

    if old is None:
        pages = _pages(new)
        items = [{"kind": "added", "text": f"Page {name} — {len(vs)} visual{'s' if len(vs) != 1 else ''}"} for name, vs in pages.items()]
        section("Pages", items)
        section("Measures", [{"kind": "added", "text": f"[{m.get('name')}]", "after": _norm(m.get("expression"))}
                             for m in new.get("measures") or []])
        n_vis = sum(len(v) for v in pages.values())
        return {"first": True, "sections": sections,
                "summary": [f"First version: {len(pages)} page{'s' if len(pages) != 1 else ''}, {n_vis} visuals, "
                            f"{len(new.get('measures') or [])} measures, {len(new.get('tables') or [])} tables"]}

    # pages and visuals
    po, pn = _pages(old), _pages(new)
    section("Pages", [{"kind": "added", "text": f"Page {n} — {len(pn[n])} visuals"} for n in pn if n not in po]
            + [{"kind": "removed", "text": f"Page {n}"} for n in po if n not in pn])
    vis = []
    for page in pn:
        if page not in po:
            continue
        a, b = po[page], pn[page]
        vis += [{"kind": "added", "text": f"{page}: {_label(b[i])}"} for i in b if i not in a]
        vis += [{"kind": "removed", "text": f"{page}: {_label(a[i])}"} for i in a if i not in b]
        for i in b:
            if i in a:
                what = [label for key, label in ASPECTS if _norm(a[i].get(key)) != _norm(b[i].get(key))]
                if "formatting" in what:            # which format settings: colors, labels, header …
                    fa, fb = a[i].get("format") or {}, b[i].get("format") or {}
                    keys = sorted(k for k in set(fa) | set(fb) if _norm(fa.get(k)) != _norm(fb.get(k))) \
                        if isinstance(fa, dict) and isinstance(fb, dict) else []
                    if keys:
                        what[what.index("formatting")] = f"formatting ({', '.join(keys)})"
                if what:
                    item = {"kind": "changed", "text": f"{page}: {_label(b[i])} — {', '.join(what)}"}
                    if "chart type" in what or "visual type" in what:
                        item.update(before=_label(a[i]), after=_label(b[i]))
                    vis.append(item)
    section("Visuals", vis)

    # measures
    mo, mn = _by_name(old.get("measures")), _by_name(new.get("measures"))
    meas = [{"kind": "added", "text": f"[{n}]", "after": _norm(mn[n].get("expression"))} for n in mn if n not in mo]
    meas += [{"kind": "removed", "text": f"[{n}]", "before": _norm(mo[n].get("expression"))} for n in mo if n not in mn]
    for n in mn:
        if n in mo:
            what = [w for k, w in (("expression", "DAX"), ("format", "format"), ("description", "description"))
                    if _norm(mo[n].get(k)) != _norm(mn[n].get(k))]
            if what:
                item = {"kind": "changed", "text": f"[{n}] — {', '.join(what)}"}
                if "DAX" in what:
                    item.update(before=_norm(mo[n].get("expression")), after=_norm(mn[n].get("expression")))
                elif "format" in what:
                    item.update(before=_norm(mo[n].get("format")), after=_norm(mn[n].get("format")))
                meas.append(item)
    section("Measures", meas)

    # data model
    model = []
    to, tn = _by_name(old.get("tables")), _by_name(new.get("tables"))
    model += [{"kind": "added", "text": f"Table {n}" + (f" from {tn[n]['csv']}" if tn[n].get("csv") else "")} for n in tn if n not in to]
    model += [{"kind": "removed", "text": f"Table {n}"} for n in to if n not in tn]
    for n in tn:
        if n in to:
            co, cn = _by_name(to[n].get("columns")), _by_name(tn[n].get("columns"))
            model += [{"kind": "added", "text": f"Column {n}[{c}]"} for c in cn if c not in co]
            model += [{"kind": "removed", "text": f"Column {n}[{c}]"} for c in co if c not in cn]
    key = lambda c: f"{c.get('table')}[{c.get('name')}]"
    cco = {key(c): c for c in old.get("calculated_columns") or []}
    ccn = {key(c): c for c in new.get("calculated_columns") or []}
    model += [{"kind": "added", "text": f"Calculated column {k}", "after": _norm(ccn[k].get("expression"))} for k in ccn if k not in cco]
    model += [{"kind": "removed", "text": f"Calculated column {k}"} for k in cco if k not in ccn]
    model += [{"kind": "changed", "text": f"Calculated column {k} — DAX", "before": _norm(cco[k].get("expression")),
               "after": _norm(ccn[k].get("expression"))} for k in ccn if k in cco and _norm(cco[k].get("expression")) != _norm(ccn[k].get("expression"))]
    ro, rn = {_rel(r) for r in old.get("relationships") or []}, {_rel(r) for r in new.get("relationships") or []}
    model += [{"kind": "added", "text": f"Relationship {r}"} for r in sorted(rn - ro)]
    model += [{"kind": "removed", "text": f"Relationship {r}"} for r in sorted(ro - rn)]
    section("Data model", model)

    # look and filters
    tho, thn = old.get("theme") or {}, new.get("theme") or {}
    section("Look and theme", [{"kind": "changed", "text": k, "before": _norm(tho.get(k)) or "default", "after": _norm(thn.get(k)) or "default"}
                               for k in sorted(set(tho) | set(thn)) if _norm(tho.get(k)) != _norm(thn.get(k))])
    fo, fn = _by_name(old.get("filters"), "field"), _by_name(new.get("filters"), "field")
    section("Filters", [{"kind": "added", "text": f"Filter {f}"} for f in fn if f not in fo]
            + [{"kind": "removed", "text": f"Filter {f}"} for f in fo if f not in fn]
            + [{"kind": "changed", "text": f"Filter {f}", "before": _norm(fo[f]), "after": _norm(fn[f])}
               for f in fn if f in fo and _norm(fo[f]) != _norm(fn[f])])

    summary = []
    for s in sections:
        counts = {k: sum(i["kind"] == k for i in s["items"]) for k in ("added", "changed", "removed")}
        parts = [f"{n} {k}" for k, n in counts.items() if n]
        summary.append(f"{s['title']}: {', '.join(parts)}")
    return {"first": False, "sections": sections, "summary": summary or ["No changes to the report definition"]}
