"""The deck as a .pptx (python-pptx): the generated RELAY template draws every slide from the PASDACS brand tokens
on the default layouts; a tenant template keeps its own layouts (picked by name) and theme. Charts are native
PowerPoint charts, tables native tables, diagrams native shapes grouped (editable, with alt text), speaker notes on
every slide, and a closing slide that carries "Powered by PASDACS Relay" for partners."""
from __future__ import annotations

from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from . import charts, diagrams
from .template import DECK_LAYOUT_NAMES, TOKENS, Template

CHART_TYPES = {"column": XL_CHART_TYPE.COLUMN_CLUSTERED, "bar": XL_CHART_TYPE.BAR_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE}
SW, SH = Inches(13.333), Inches(7.5)
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def rgb(hex_colour: str) -> RGBColor:
    return RGBColor.from_string(hex_colour.lstrip("#").upper()[:6])


def set_alt(shape, text: str) -> None:
    """Alt text (descr) on any shape: picture, chart / table frame, autoshape or group."""
    for el in shape._element.iter():
        if el.tag == f"{{{NS_P}}}cNvPr":
            el.set("descr", text or "")
            if not el.get("name"):
                el.set("name", text[:60] or "shape")
            return


def _drop_slides(prs) -> int:
    """A tenant template's sample slides are removed; its layouts and masters stay."""
    lst = prs.slides._sldIdLst
    n = 0
    for sld in list(lst):
        prs.part.drop_rel(sld.rId)
        lst.remove(sld)
        n += 1
    return n


def _layout(prs, name: str):
    """The slide layout for a studio layout name: by the template's own names, then by position."""
    by_name = {ly.name: ly for ly in prs.slide_layouts}
    for cand in DECK_LAYOUT_NAMES.get(name, []):
        if cand in by_name:
            return by_name[cand]
    fallback = {"title": 0, "bullets": 1, "two-column": 3, "table": 5, "chart": 5, "diagram": 5, "quote": 6, "closing": 0, "image": 5}
    idx = fallback.get(name, 6)
    return prs.slide_layouts[min(idx, len(prs.slide_layouts) - 1)]


def _text(tf, lines: list[str], size: int, colour: str | None, font: str | None, bold: bool = False, bullets: bool = False, align=None, space: int = 6):
    tf.word_wrap = True
    first = True
    for ln in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.text = ("• " + ln) if bullets else ln
        p.space_after = Pt(space)
        if align is not None:
            p.alignment = align
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            if colour:
                r.font.color.rgb = rgb(colour)
            if font:
                r.font.name = font


class DeckBuilder:
    def __init__(self, model: dict, template: Template, resolver, root: Path, rasteriser=None):
        self.m, self.t, self.resolver, self.root, self.ras = model, template, resolver, root, rasteriser
        self.generated = template.pptx is None
        self.prs = Presentation(str(template.pptx)) if template.pptx else Presentation()
        if self.generated:
            self.prs.slide_width, self.prs.slide_height = SW, SH
        else:
            _drop_slides(self.prs)
        self.W, self.H = self.prs.slide_width, self.prs.slide_height
        self.info = {"slides": 0, "charts": 0, "tables": 0, "diagrams": 0, "images": 0, "notes": 0, "pictures_rendered": 0, "pictures_missing": 0}
        self.c, self.f = template.colours, template.fonts

    # ---- scaffolding
    def _slide(self, layout: str, title: str, subtitle: str = ""):
        s = self.prs.slides.add_slide(_layout(self.prs, layout))
        self.info["slides"] += 1
        if self.generated:
            self._paint(s, layout, title, subtitle)
        else:
            self._fill_placeholders(s, layout, title, subtitle)
        return s

    def _paint(self, s, layout: str, title: str, subtitle: str):
        """The generated RELAY look: an ink band with the title, the brand line in the footer; title / closing
        slides are the dark band (brand-900) with a mint bar and mint subtitle."""
        for ph in list(s.placeholders):                     # we draw our own shapes on the default layouts
            ph._element.getparent().remove(ph._element)
        full = layout in ("title", "closing")
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(self.c["night"] if full else self.c["bg"])
        if full:
            bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(3.05), Inches(1.1), Inches(0.09))
            bar.fill.solid(); bar.fill.fore_color.rgb = rgb(self.c["accent"]); bar.line.fill.background()
            set_alt(bar, "")
            tb = s.shapes.add_textbox(Inches(0.8), Inches(3.3), self.W - Inches(1.6), Inches(1.6))
            _text(tb.text_frame, [title], 40, "#FFFFFF", self.f["head"], bold=True)
            if subtitle:
                tb2 = s.shapes.add_textbox(Inches(0.8), Inches(4.9), self.W - Inches(1.6), Inches(1.0))
                _text(tb2.text_frame, [subtitle], 20, self.c.get("accent", TOKENS["signal_dark"]) if self.t.partner else TOKENS["signal_dark"], self.f["body"])
            self._brand_line(s, dark=True)
            return
        band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, self.W, Inches(1.15))
        band.fill.solid(); band.fill.fore_color.rgb = rgb(self.c["band"]); band.line.fill.background()
        set_alt(band, "")
        tb = s.shapes.add_textbox(Inches(0.6), Inches(0.22), self.W - Inches(1.2), Inches(0.8))
        _text(tb.text_frame, [title], 26, self.c["band_text"], self.f["head"], bold=True)
        if subtitle:
            tb2 = s.shapes.add_textbox(Inches(0.6), Inches(1.25), self.W - Inches(1.2), Inches(0.5))
            _text(tb2.text_frame, [subtitle], 14, self.c["muted"], self.f["body"])
        self._brand_line(s, dark=False)

    def _brand_line(self, s, dark: bool) -> None:
        colour = "#A3B1C2" if dark else self.c["muted"]
        tb = s.shapes.add_textbox(Inches(0.6), self.H - Inches(0.5), self.W - Inches(1.2), Inches(0.35))
        _text(tb.text_frame, [f"{self.t.owner}  ·  {self.m['title']}  ·  {self.info['slides']}" + (f"  ·  {self.t.powered}" if self.t.partner else "")], 10, colour, self.f["body"])

    def _fill_placeholders(self, s, layout: str, title: str, subtitle: str):
        """A tenant template: its title placeholder gets the title; a subtitle / body placeholder the subtitle."""
        if s.shapes.title is not None:
            s.shapes.title.text = title
        else:
            tb = s.shapes.add_textbox(Inches(0.6), Inches(0.3), self.W - Inches(1.2), Inches(0.9))
            _text(tb.text_frame, [title], 28, None, None, bold=True)
        if subtitle:
            ph = next((p for p in s.placeholders if p.placeholder_format.idx == 1), None)
            if ph is not None and ph.has_text_frame and layout in ("title", "closing"):
                ph.text = subtitle
            else:
                tb = s.shapes.add_textbox(Inches(0.6), Inches(1.25), self.W - Inches(1.2), Inches(0.5))
                _text(tb.text_frame, [subtitle], 14, None, None)
        if layout in ("title", "closing") and self.t.partner:
            tb = s.shapes.add_textbox(Inches(0.6), self.H - Inches(0.6), self.W - Inches(1.2), Inches(0.4))
            _text(tb.text_frame, [self.t.powered], 11, None, None)

    def _body_box(self, s, left=None, top=None, width=None, height=None):
        left = Inches(0.7) if left is None else left
        top = Inches(1.55) if top is None else top
        width = (self.W - Inches(1.4)) if width is None else width
        height = (self.H - top - Inches(0.75)) if height is None else height
        return left, top, width, height

    def _bullets(self, s, lines: list[str], left=None, top=None, width=None, height=None, heading: str = ""):
        ph = None if self.generated else next((p for p in s.placeholders if p.placeholder_format.idx == 1 and p.has_text_frame), None)
        if ph is not None and left is None and not heading:
            ph.text_frame.text = lines[0] if lines else ""
            for ln in lines[1:]:
                ph.text_frame.add_paragraph().text = ln
            return ph
        l, t, w, hgt = self._body_box(s, left, top, width, height)
        tb = s.shapes.add_textbox(l, t, w, hgt)
        items = ([heading] if heading else []) + lines
        _text(tb.text_frame, items, 18 if len(lines) <= 5 else 15, self.c["text"] if self.generated else None, self.f["body"] if self.generated else None, bullets=False)
        for i, p in enumerate(tb.text_frame.paragraphs):
            if heading and i == 0:
                for r in p.runs:
                    r.font.bold = True
                    r.font.size = Pt(18)
                continue
            p.text = "•  " + p.text
            for r in p.runs:
                r.font.size = Pt(18 if len(lines) <= 5 else 15)
        return tb

    def _notes(self, s, text: str):
        if text:
            s.notes_slide.notes_text_frame.text = text
            self.info["notes"] += 1

    def _caption(self, s, text: str, top):
        if text:
            tb = s.shapes.add_textbox(Inches(0.7), top, self.W - Inches(1.4), Inches(0.4))
            _text(tb.text_frame, [text], 11, self.c["muted"] if self.generated else None, self.f["body"] if self.generated else None)

    # ---- layouts
    def slide_title(self, u):
        s = self._slide("title", u["title"] or self.m["title"], u["subtitle"] or self.m["subtitle"] or (f"For {self.m['audience']}" if self.m["audience"] else ""))
        self._notes(s, u["notes"])

    def slide_closing(self, u):
        s = self._slide("closing", u["title"] or "Thank you", u["subtitle"] or (self.t.powered if self.t.partner else self.t.owner))
        if u["bullets"]:
            tb = s.shapes.add_textbox(Inches(0.8), Inches(5.4), self.W - Inches(1.6), Inches(1.4))
            _text(tb.text_frame, u["bullets"], 14, TOKENS["band_body"] if self.generated else None, self.f["body"] if self.generated else None, space=2)
        if self.t.partner:
            tb = s.shapes.add_textbox(Inches(0.8), self.H - Inches(1.05), self.W - Inches(1.6), Inches(0.45))
            _text(tb.text_frame, [self.t.powered], 13, TOKENS["signal_dark"] if self.generated else None, self.f["body"] if self.generated else None, bold=True)
        self._notes(s, u["notes"])

    def slide_bullets(self, u):
        s = self._slide("bullets", u["title"], u["subtitle"])
        self._bullets(s, u["bullets"])
        self._notes(s, u["notes"])

    def slide_two(self, u):
        s = self._slide("two-column", u["title"], u["subtitle"])
        l, t, w, hgt = self._body_box(s)
        half = int((w - Inches(0.4)) / 2)
        self._bullets(s, u["left"]["bullets"], l, t, half, hgt, heading=u["left"]["heading"])
        self._bullets(s, u["right"]["bullets"], l + half + Inches(0.4), t, half, hgt, heading=u["right"]["heading"])
        self._notes(s, u["notes"])

    def slide_table(self, u):
        s = self._slide("table", u["title"], u["subtitle"])
        tbl = u["table"]
        l, t, w, hgt = self._body_box(s)
        rows, cols = len(tbl["rows"]) + 1, len(tbl["columns"])
        rh = min(Inches(0.42), int((hgt - Inches(0.5)) / max(rows, 1)))
        gf = s.shapes.add_table(rows, cols, l, t, w, rh * rows)
        set_alt(gf, tbl["alt"] or tbl["caption"] or u["title"])
        table = gf.table
        for j, col in enumerate(tbl["columns"]):
            table.cell(0, j).text = col
        for i, r in enumerate(tbl["rows"], 1):
            for j, cell in enumerate(r):
                table.cell(i, j).text = cell
        for i in range(rows):
            for j in range(cols):
                for p in table.cell(i, j).text_frame.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(12 if rows <= 10 else 10)
                        if self.generated:
                            run.font.name = self.f["body"]
        self.info["tables"] += 1
        self._caption(s, (tbl["caption"] + "  ·  " if tbl["caption"] else "") + f"Source: {self._source_name(tbl['source'])}", t + rh * rows + Inches(0.1))
        self._notes(s, u["notes"])

    def slide_chart(self, u):
        s = self._slide("chart", u["title"], u["subtitle"])
        ch = u["chart"]
        l, t, w, hgt = self._body_box(s)
        cd = CategoryChartData()
        cd.categories = ch["categories"]
        for ser in ch["series"]:
            cd.add_series(ser["name"], [float(v) for v in ser["values"]])
        gf = s.shapes.add_chart(CHART_TYPES.get(ch["type"], XL_CHART_TYPE.COLUMN_CLUSTERED), l, t, w, hgt - Inches(0.45), cd)
        chart = gf.chart
        chart.has_legend = len(ch["series"]) > 1 or ch["type"] == "pie"
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
        chart.has_title = bool(ch["title"])
        if ch["title"]:
            chart.chart_title.text_frame.text = ch["title"]
        if ch["type"] != "pie":
            try:
                chart.value_axis.has_major_gridlines = True
                chart.value_axis.tick_labels.font.size = Pt(11)
                chart.category_axis.tick_labels.font.size = Pt(11)
            except Exception:  # noqa: BLE001 - some chart kinds have no axes
                pass
        plot = chart.plots[0]
        plot.has_data_labels = len(ch["categories"]) * len(ch["series"]) <= 16
        if plot.has_data_labels:
            plot.data_labels.font.size = Pt(10)
        for i, ser in enumerate(plot.series):
            if ch["type"] != "pie":
                ser.format.fill.solid()
                ser.format.fill.fore_color.rgb = rgb(charts.PALETTE[i % len(charts.PALETTE)])
                if ch["type"] == "line":
                    ser.format.line.color.rgb = rgb(charts.PALETTE[i % len(charts.PALETTE)])
        set_alt(gf, ch["alt"] or ch["title"] or u["title"])
        self.info["charts"] += 1
        self._caption(s, f"Source: {self._source_name(ch['source'])}" + (f"  ·  {ch['unit']}" if ch["unit"] else ""), t + hgt - Inches(0.4))
        self._notes(s, u["notes"])

    def slide_diagram(self, u):
        s = self._slide("diagram", u["title"], u["subtitle"])
        d = u["diagram"]
        r = diagrams.render(d["mermaid"], self.c, d["alt"])
        l, t, w, hgt = self._body_box(s)
        if r["kind"] == "flowchart" and r["model"].get("nodes"):
            self._native_diagram(s, r["model"], d["alt"] or u["title"], l, t, w, hgt - Inches(0.45))
        else:
            tb = s.shapes.add_textbox(l, t, w, hgt)
            _text(tb.text_frame, [r["note"] or "Diagram", *d["mermaid"].splitlines()[:12]], 12, self.c["muted"] if self.generated else None, "Consolas")
            set_alt(tb, d["alt"] or u["title"])
        self.info["diagrams"] += 1
        self._caption(s, d["alt"], t + hgt - Inches(0.4))
        self._notes(s, u["notes"])

    def _native_diagram(self, s, model: dict, alt: str, l, t, w, hgt):
        """The laid-out flowchart as native shapes in a group: boxes, connectors with arrowheads, labels."""
        mw, mh = max(model["width"], 1), max(model["height"], 1)
        scale = min(w / mw, hgt / mh, Emu(Inches(1)) / 110.0)
        ox = l + int((w - mw * scale) / 2)
        oy = t + int((hgt - mh * scale) / 2)
        grp = s.shapes.add_group_shape()
        by = {n["id"]: n for n in model["nodes"]}
        horizontal = model["direction"] in ("LR", "RL")
        for e in model["edges"]:
            a, b = by.get(e["from"]), by.get(e["to"])
            if not a or not b:
                continue
            x1, y1 = diagrams._anchor(a, b, horizontal)
            x2, y2 = diagrams._anchor(b, a, horizontal)
            con = grp.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, ox + int(x1 * scale), oy + int(y1 * scale), ox + int(x2 * scale), oy + int(y2 * scale))
            con.line.color.rgb = rgb(self.c["muted"])
            con.line.width = Pt(1.5 if e.get("style") != "thick" else 2.5)
            ln = con.line._get_or_add_ln()
            if e.get("style") == "dotted":
                etree.SubElement(ln, f"{{{NS_A}}}prstDash").set("val", "dash")
            if e.get("arrow", True):
                etree.SubElement(ln, f"{{{NS_A}}}tailEnd").set("type", "triangle")
            if e.get("label"):
                tb = grp.shapes.add_textbox(ox + int((x1 + x2) / 2 * scale) - Inches(0.6), oy + int((y1 + y2) / 2 * scale) - Inches(0.3), Inches(1.2), Inches(0.3))
                _text(tb.text_frame, [e["label"]], 9, self.c["muted"], self.f["body"], align=PP_ALIGN.CENTER)
        for n in model["nodes"]:
            shape = {"decision": MSO_SHAPE.DIAMOND, "circle": MSO_SHAPE.OVAL, "rounded": MSO_SHAPE.ROUNDED_RECTANGLE}.get(n.get("shape", "box"), MSO_SHAPE.RECTANGLE)
            sh = grp.shapes.add_shape(shape, ox + int(n["x"] * scale), oy + int(n["y"] * scale), int(diagrams.NW * scale), int(diagrams.NH * scale))
            sh.fill.solid(); sh.fill.fore_color.rgb = rgb(self.c["bg"])
            sh.line.color.rgb = rgb(self.c["accent"]); sh.line.width = Pt(1.25)
            _text(sh.text_frame, [n["label"]], 11 if scale > 9000 else 9, self.c["text"], self.f["body"], bold=True, align=PP_ALIGN.CENTER)
            set_alt(sh, n["label"])
        set_alt(grp, alt or diagrams.describe(model))

    def slide_quote(self, u):
        s = self._slide("quote", u["title"] or "", u["subtitle"])
        q = u["quote"]
        l, t, w, hgt = self._body_box(s, top=Inches(1.6))
        tb = s.shapes.add_textbox(l + Inches(0.6), t + Inches(0.6), w - Inches(1.2), hgt - Inches(1.6))
        _text(tb.text_frame, ["“" + q["text"] + "”"], 26, self.c["accent_text"] if self.generated else None, self.f["head"] if self.generated else None, bold=False)
        who = s.shapes.add_textbox(l + Inches(0.6), self.H - Inches(1.6), w - Inches(1.2), Inches(0.5))
        _text(who.text_frame, [("— " + q["who"]) if q["who"] else ""], 14, self.c["muted"] if self.generated else None, self.f["body"] if self.generated else None)
        self._caption(s, f"Source: {self._source_name(q['source'])}", self.H - Inches(1.15))
        self._notes(s, u["notes"])

    def slide_image(self, u):
        s = self._slide("image", u["title"] or "", u["subtitle"])
        im = u["image"]
        l, t, w, hgt = self._body_box(s)
        path = self.root / im["file"]
        if path.is_file() and self.resolver.inside(im["file"]):
            pic = s.shapes.add_picture(str(path), l, t, height=hgt - Inches(0.45))
            if pic.width > w:
                pic.width, pic.height = w, int(pic.height * w / pic.width)
            set_alt(pic, im["alt"])
            self.info["images"] += 1
        else:
            tb = s.shapes.add_textbox(l, t, w, Inches(0.6))
            _text(tb.text_frame, [f"Image {im['file']} is not in the project folder"], 12, self.c["muted"] if self.generated else None, None)
        self._caption(s, im["alt"], t + hgt - Inches(0.4))
        self._notes(s, u["notes"])

    def _source_name(self, ref: str) -> str:
        r = self.resolver.resolve(ref)
        return (r.get("name") or r.get("path") or ref) if r["ok"] else ref

    # ---- the deck
    def build(self, out: Path) -> dict:
        self.prs.core_properties.title = self.m["title"]
        self.prs.core_properties.author = self.t.owner
        self.prs.core_properties.subject = self.m["audience"]
        units = [u for sec in self.m["sections"] for u in sec["units"]]
        if not units or units[0]["layout"] != "title":
            self.slide_title({"title": self.m["title"], "subtitle": self.m["subtitle"], "notes": "", "bullets": []})
        fn = {"title": self.slide_title, "bullets": self.slide_bullets, "two-column": self.slide_two, "table": self.slide_table, "chart": self.slide_chart,
              "diagram": self.slide_diagram, "quote": self.slide_quote, "closing": self.slide_closing, "image": self.slide_image}
        for u in units:
            fn.get(u["layout"], self.slide_bullets)(u)
        if not units or units[-1]["layout"] != "closing":
            self.slide_closing({"title": "Thank you", "subtitle": "", "notes": "", "bullets": []})
        out.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(str(out))
        self.info["file"] = out.name
        self.info["bytes"] = out.stat().st_size
        self.info["template"] = self.t.name
        self.info["powered"] = self.t.powered
        return self.info


def build(model: dict, template: Template, resolver, root: Path, out: Path, rasteriser=None) -> dict:
    return DeckBuilder(model, template, resolver, root, rasteriser).build(out)


def read_back(path: Path) -> dict:
    """What a saved deck holds (the tests and the web app's build record): slides, titles, charts, tables, notes."""
    prs = Presentation(str(path))
    slides = []
    for i, s in enumerate(prs.slides, 1):
        texts, charts_n, tables_n, pics, groups, alts = [], 0, 0, 0, 0, []
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                texts.append(sh.text_frame.text.strip())
            if getattr(sh, "has_chart", False) and sh.has_chart:
                charts_n += 1
            if getattr(sh, "has_table", False) and sh.has_table:
                tables_n += 1
            if sh.shape_type is not None and "PICTURE" in str(sh.shape_type):
                pics += 1
            if sh.shape_type is not None and "GROUP" in str(sh.shape_type):
                groups += 1
            for el in sh._element.iter():
                if el.tag == f"{{{NS_P}}}cNvPr" and el.get("descr"):
                    alts.append(el.get("descr"))
                    break
        notes = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        slides.append({"n": i, "texts": texts, "charts": charts_n, "tables": tables_n, "pictures": pics, "groups": groups, "notes": notes, "alts": alts})
    return {"slides": slides, "count": len(slides), "title": prs.core_properties.title, "author": prs.core_properties.author}


def png_bytes_ok(data: bytes | None) -> bool:
    return bool(data) and data[:8] == b"\x89PNG\r\n\x1a\n"
