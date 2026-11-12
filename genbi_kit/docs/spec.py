"""deck.yaml / doc.yaml: the shape of a deliverable and its normalised model.

deck.yaml
  kind: deck                         # deck | doc
  title: ...   subtitle: ...   audience: ...   author: ...   date: 2026-11-05   template: relay | tenant
  sections:
    - title: Where we are
      slides:
        - layout: title | bullets | two-column | table | chart | diagram | quote | closing | image
          title: ...   subtitle: ...   bullets: [...]   notes: speaker notes
          left: {heading: ..., bullets: [...]}   right: {...}                         # two-column
          table: {columns: [...], rows: [[...]], source: record:assess#tables, caption: ...}
          chart: {type: column|bar|line|pie, categories: [...], series: [{name: ..., values: [...]}], unit: ..., source: ..., alt: ...}
          diagram: {mermaid: "graph LR; A[Source] --> B[Warehouse]", alt: ...}
          quote: {text: ..., who: ..., source: ...}
          image: {file: sources/photo.png, alt: ...}
          figures: [{text: "1,842", value: 1842, source: "dashboard:atlas-1a2b/Reports"}]   # every number in the text
doc.yaml
  kind: doc ... sections: [{title, blocks: [{kind: paragraph|heading|bullets|table|chart|diagram|quote|image, ...}]}]

Every number a reader sees (bullets, titles, quotes, paragraphs) must be declared under `figures` with a `source`;
tables, charts and quotes carry their own `source`. Sources are references (sources.py): dashboard:<id>/<measure>,
record:<name>#<key>, attachment:<file>, library:<id>, module:<id>, or a file path inside the project."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

LAYOUTS = ("title", "bullets", "two-column", "table", "chart", "diagram", "quote", "closing", "image")
BLOCKS = ("paragraph", "heading", "bullets", "table", "chart", "diagram", "quote", "image")
CHART_TYPES = ("column", "bar", "line", "pie")
KINDS = ("deck", "doc")
# A number a reader takes as a fact: currency, percentage, thousands with separators, decimals, 4+ digits (years excluded).
FIGURE_RE = re.compile(r"(?<![\w./#-])(?:[₹$€£]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:%|per cent|percent)|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{4,})(?![\w/-])")
YEAR_RE = re.compile(r"^(19|20)\d\d$")
# ...and a count with its unit ("48 stores", "12 waves") - small plain integers on their own are not figures.
COUNT_RE = re.compile(r"(?<![\w./#-])(\d{2,3})\s+(?:stores?|reports?|users?|days?|hours?|people|persons?|clients?|dashboards?|tickets?|rows?|tables?|months?|weeks?|years?|"
                      r"modules?|systems?|sites?|FTEs?|licen[cs]es?|sources?|pipelines?|bots?|flows?|integrations?|pages?|visuals?|measures?|requirements?|waves?|teams?|countries|regions?)\b", re.I)


class DocError(Exception):
    pass


def load(path: Path | str) -> dict:
    p = Path(path)
    if not p.exists():
        raise DocError(f"{p.name} was not written")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DocError(f"{p.name} does not parse: {str(e).splitlines()[0][:200]}") from e
    if not isinstance(raw, dict):
        raise DocError(f"{p.name} must be a mapping with title, kind and sections")
    return raw


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _strs(v) -> list[str]:
    return [_s(x) for x in _list(v) if _s(x)]


def normalise_figures(v) -> list[dict]:
    out = []
    for f in _list(v):
        if isinstance(f, dict):
            out.append({"text": _s(f.get("text")), "value": f.get("value"), "source": _s(f.get("source")), "label": _s(f.get("label"))})
        elif f is not None:
            out.append({"text": _s(f), "value": None, "source": "", "label": ""})
    return out


def normalise_unit(u: dict, kind: str, n: int, section: str) -> dict:
    layout = _s(u.get("layout") or u.get("kind") or ("bullets" if kind == "deck" else "paragraph")).lower()
    col = lambda c: {"heading": _s((c or {}).get("heading")) if isinstance(c, dict) else "", "bullets": _strs((c or {}).get("bullets") if isinstance(c, dict) else c)}  # noqa: E731
    table = u.get("table") if isinstance(u.get("table"), dict) else None
    chart = u.get("chart") if isinstance(u.get("chart"), dict) else None
    diagram = u.get("diagram") if isinstance(u.get("diagram"), dict) else ({"mermaid": _s(u.get("diagram"))} if u.get("diagram") else None)
    quote = u.get("quote") if isinstance(u.get("quote"), dict) else ({"text": _s(u.get("quote"))} if u.get("quote") else None)
    image = u.get("image") if isinstance(u.get("image"), dict) else ({"file": _s(u.get("image"))} if u.get("image") else None)
    unit = {"n": n, "layout": layout, "section": section, "title": _s(u.get("title")), "subtitle": _s(u.get("subtitle")),
            "text": _s(u.get("text")), "bullets": _strs(u.get("bullets")), "notes": _s(u.get("notes")),
            "left": col(u.get("left")), "right": col(u.get("right")), "figures": normalise_figures(u.get("figures")),
            "table": None, "chart": None, "diagram": None, "quote": None, "image": None}
    if table:
        unit["table"] = {"columns": _strs(table.get("columns")), "rows": [[_s(c) for c in _list(r)] for r in _list(table.get("rows"))],
                         "source": _s(table.get("source")), "caption": _s(table.get("caption")), "alt": _s(table.get("alt"))}
    if chart:
        series = []
        for s in _list(chart.get("series")):
            if isinstance(s, dict):
                series.append({"name": _s(s.get("name")) or "Series", "values": [x for x in _list(s.get("values"))]})
        unit["chart"] = {"type": _s(chart.get("type") or "column").lower(), "categories": _strs(chart.get("categories")), "series": series,
                         "unit": _s(chart.get("unit")), "source": _s(chart.get("source")), "alt": _s(chart.get("alt")), "title": _s(chart.get("title"))}
    if diagram:
        unit["diagram"] = {"mermaid": _s(diagram.get("mermaid") or diagram.get("text")), "alt": _s(diagram.get("alt")), "source": _s(diagram.get("source"))}
    if quote:
        unit["quote"] = {"text": _s(quote.get("text")), "who": _s(quote.get("who")), "source": _s(quote.get("source"))}
    if image:
        unit["image"] = {"file": _s(image.get("file") or image.get("path")), "alt": _s(image.get("alt")), "source": _s(image.get("source"))}
    return unit


def normalise(raw: dict) -> dict:
    """The model every builder, the twin and the checks work on. Shape problems are collected by shape_errors."""
    kind = _s(raw.get("kind") or "deck").lower()
    sections, n = [], 0
    for sec in _list(raw.get("sections")):
        if not isinstance(sec, dict):
            continue
        units = []
        for u in _list(sec.get("slides") if kind == "deck" else sec.get("blocks")):
            if isinstance(u, dict):
                n += 1
                units.append(normalise_unit(u, kind, n, _s(sec.get("title"))))
        sections.append({"title": _s(sec.get("title")), "units": units})
    return {"kind": kind, "title": _s(raw.get("title")), "subtitle": _s(raw.get("subtitle")), "audience": _s(raw.get("audience")),
            "author": _s(raw.get("author")), "date": _s(raw.get("date")), "template": _s(raw.get("template") or "relay"),
            "language": _s(raw.get("language") or "en-GB"), "sections": sections, "units": n,
            "summary": _s(raw.get("summary")), "figures": normalise_figures(raw.get("figures"))}


def shape_errors(raw: dict) -> list[str]:
    """What is wrong with the YAML's shape (empty = fine) - the agent fixes these in a resumed session."""
    errs = []
    kind = _s(raw.get("kind") or "deck").lower()
    if kind not in KINDS:
        errs.append(f"kind must be deck or doc (got {kind!r})")
    if not _s(raw.get("title")):
        errs.append("title is missing")
    secs = _list(raw.get("sections"))
    if not secs:
        errs.append("sections is empty - list the sections with their slides (deck) or blocks (doc)")
    key = "slides" if kind == "deck" else "blocks"
    n = 0
    for i, sec in enumerate(secs, 1):
        if not isinstance(sec, dict):
            errs.append(f"sections[{i}] must be a mapping with title and {key}")
            continue
        if not _s(sec.get("title")):
            errs.append(f"sections[{i}] needs a title")
        units = _list(sec.get(key))
        if not units:
            errs.append(f"section \"{_s(sec.get('title')) or i}\" has no {key}")
        for u in units:
            n += 1
            if not isinstance(u, dict):
                errs.append(f"{key[:-1]} {n} must be a mapping")
                continue
            layout = _s(u.get("layout") or u.get("kind") or ("bullets" if kind == "deck" else "paragraph")).lower()
            allowed = LAYOUTS if kind == "deck" else BLOCKS
            if layout not in allowed:
                errs.append(f"{key[:-1]} {n}: layout {layout!r} is not one of {', '.join(allowed)}")
                continue
            if kind == "deck" and layout not in ("closing", "quote", "image") and not _s(u.get("title")):
                errs.append(f"slide {n} ({layout}) needs a title")
            if layout == "bullets" and not _strs(u.get("bullets")):
                errs.append(f"{key[:-1]} {n}: bullets is empty")
            if layout == "paragraph" and not _s(u.get("text")):
                errs.append(f"block {n}: paragraph text is empty")
            if layout == "heading" and not _s(u.get("title") or u.get("text")):
                errs.append(f"block {n}: heading text is empty")
            if layout == "two-column":
                for side in ("left", "right"):
                    c = u.get(side)
                    if not (_strs(c.get("bullets")) if isinstance(c, dict) else _strs(c)):
                        errs.append(f"slide {n}: {side} column is empty")
            if layout == "table":
                t = u.get("table")
                if not isinstance(t, dict) or not _strs(t.get("columns")) or not _list(t.get("rows")):
                    errs.append(f"{key[:-1]} {n}: table needs columns and rows")
                elif any(len(_list(r)) != len(_strs(t.get("columns"))) for r in _list(t.get("rows"))):
                    errs.append(f"{key[:-1]} {n}: every table row needs one cell per column")
            if layout == "chart":
                c = u.get("chart")
                if not isinstance(c, dict):
                    errs.append(f"{key[:-1]} {n}: chart needs type, categories and series")
                else:
                    if _s(c.get("type") or "column").lower() not in CHART_TYPES:
                        errs.append(f"{key[:-1]} {n}: chart type must be one of {', '.join(CHART_TYPES)}")
                    cats, series = _strs(c.get("categories")), _list(c.get("series"))
                    if not cats or not series:
                        errs.append(f"{key[:-1]} {n}: chart needs categories and at least one series")
                    for s in series:
                        vals = _list(s.get("values")) if isinstance(s, dict) else []
                        if len(vals) != len(cats):
                            errs.append(f"{key[:-1]} {n}: series {(s or {}).get('name') if isinstance(s, dict) else '?'} needs one value per category")
                        elif any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in vals):
                            errs.append(f"{key[:-1]} {n}: chart values must be numbers")
            if layout == "diagram":
                d = u.get("diagram")
                if not (_s(d.get("mermaid") or d.get("text")) if isinstance(d, dict) else _s(d)):
                    errs.append(f"{key[:-1]} {n}: diagram needs mermaid text")
            if layout == "quote":
                q = u.get("quote")
                if not (_s(q.get("text")) if isinstance(q, dict) else _s(q)):
                    errs.append(f"{key[:-1]} {n}: quote needs text")
            if layout == "image":
                im = u.get("image")
                if not (_s(im.get("file") or im.get("path")) if isinstance(im, dict) else _s(im)):
                    errs.append(f"{key[:-1]} {n}: image needs a file")
            for f in _list(u.get("figures")):
                if isinstance(f, dict) and not _s(f.get("text")) and f.get("value") is None:
                    errs.append(f"{key[:-1]} {n}: a figure needs text or value")
    return errs


# ---------------------------------------------------------------- what a unit says (for the checks and the twin)

def reader_texts(u: dict) -> list[str]:
    """Every text a reader sees on this unit (titles, bullets, cells, captions, quotes) - notes are the speaker's."""
    out = [u["title"], u["subtitle"], u["text"], *u["bullets"], u["left"]["heading"], *u["left"]["bullets"], u["right"]["heading"], *u["right"]["bullets"]]
    if u["table"]:
        out += [u["table"]["caption"], *u["table"]["columns"], *[c for r in u["table"]["rows"] for c in r]]
    if u["chart"]:
        out += [u["chart"]["title"], u["chart"]["alt"], *u["chart"]["categories"]]
    if u["diagram"]:
        out += [u["diagram"]["alt"], u["diagram"]["mermaid"]]
    if u["quote"]:
        out += [u["quote"]["text"], u["quote"]["who"]]
    if u["image"]:
        out += [u["image"]["alt"]]
    return [t for t in out if t]


def figure_texts(u: dict) -> list[str]:
    """Where a number needs a declared figure: prose a reader takes as fact (tables, charts and quotes carry their own source)."""
    return [t for t in [u["title"], u["subtitle"], u["text"], *u["bullets"], u["left"]["heading"], *u["left"]["bullets"], u["right"]["heading"], *u["right"]["bullets"]] if t]


def figure_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, token) of every figure in a text, in order - figures with units / grouping / decimals and counts with a unit noun."""
    out = []
    for m in FIGURE_RE.finditer(text):
        t = m.group(0).strip()
        if YEAR_RE.match(t.replace(",", "")):
            continue
        out.append((m.start(), m.start() + len(m.group(0).rstrip()), t))
    for m in COUNT_RE.finditer(text):
        if not any(a <= m.start(1) < b for a, b, _ in out):
            out.append((m.start(1), m.end(1), m.group(1)))
    return sorted(out)


def figure_tokens(text: str) -> list[str]:
    return [t for _, _, t in figure_spans(text)]


def norm_number(t: str) -> str:
    """'₹4,82,160.00' -> '482160', '98.7 %' -> '98.7', '1,842' -> '1842' (so a figure's value matches its text)."""
    s = re.sub(r"[₹$€£,\s]|%|per cent|percent", "", str(t)).strip()
    if re.fullmatch(r"-?\d+\.\d+", s):
        s = s.rstrip("0").rstrip(".") if "." in s else s
    return s
