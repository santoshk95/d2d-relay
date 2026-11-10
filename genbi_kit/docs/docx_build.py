"""The document as a .docx (python-docx): headings per section, paragraphs, bullets, tables with their source as a
caption, charts and diagrams as pictures rendered in headless Chromium (Playwright in the agent image, or the web
app's renderer) with alt text — where no renderer is available the chart's data goes in as a table and the diagram
as its described text, and the build says so. A tenant .docx / .dotx keeps its styles; the RELAY document carries
the brand line in the footer ("Powered by PASDACS Relay" for partners)."""
from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from . import charts, diagrams
from .template import Template

NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def _rgb(hex_colour: str) -> RGBColor:
    s = hex_colour.lstrip("#")
    return RGBColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _clear_body(doc) -> None:
    body = doc.element.body
    for el in list(body):
        if el.tag.endswith("}sectPr"):
            continue
        body.remove(el)


def _alt(doc, text: str) -> None:
    """Alt text on the picture just added (docPr descr)."""
    try:
        shape = doc.inline_shapes[-1]
        shape._inline.docPr.set("descr", text or "")
        if not shape._inline.docPr.get("title"):
            shape._inline.docPr.set("title", (text or "Picture")[:60])
    except (IndexError, AttributeError):
        pass


class DocBuilder:
    def __init__(self, model: dict, template: Template, resolver, root: Path, rasteriser=None):
        self.m, self.t, self.resolver, self.root, self.ras = model, template, resolver, root, rasteriser
        self.generated = template.docx is None
        self.doc = Document(str(template.docx)) if template.docx else Document()
        if not self.generated:
            _clear_body(self.doc)
        self.info = {"blocks": 0, "paragraphs": 0, "tables": 0, "charts": 0, "diagrams": 0, "images": 0, "pictures_rendered": 0, "pictures_missing": 0, "headings": 0}
        self.c, self.f = template.colours, template.fonts
        if self.generated:
            st = self.doc.styles["Normal"]
            st.font.name = self.f["body"]
            st.font.size = Pt(11)
            st.font.color.rgb = _rgb(self.c["text"])
            for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
                try:
                    hs = self.doc.styles[name]
                    hs.font.name = self.f["head"]
                    hs.font.color.rgb = _rgb(self.c["band"])
                except KeyError:
                    pass

    def _p(self, text: str, style: str | None = None, size: int | None = None, colour: str | None = None, italic: bool = False, align=None):
        p = self.doc.add_paragraph(style=style) if style else self.doc.add_paragraph()
        run = p.add_run(text)
        if size:
            run.font.size = Pt(size)
        if colour:
            run.font.color.rgb = _rgb(colour)
        run.italic = italic
        if align is not None:
            p.alignment = align
        return p

    def _source(self, ref: str) -> str:
        r = self.resolver.resolve(ref)
        return (r.get("name") or r.get("path") or ref) if r["ok"] else ref

    def _picture(self, svg_text: str, alt: str, caption: str) -> bool:
        png = self.ras.png(svg_text) if self.ras else None
        if not png:
            self.info["pictures_missing"] += 1
            return False
        self.doc.add_picture(io.BytesIO(png), width=Inches(6.2))
        _alt(self.doc, alt)
        self.info["pictures_rendered"] += 1
        if caption:
            self._p(caption, size=9, colour=self.c["muted"], italic=True)
        return True

    # ---- blocks
    def block_heading(self, u):
        self.doc.add_heading(u["title"] or u["text"], level=2)
        self.info["headings"] += 1

    def block_paragraph(self, u):
        if u["title"]:
            self.doc.add_heading(u["title"], level=3)
        self._p(u["text"])
        self.info["paragraphs"] += 1

    def block_bullets(self, u):
        if u["title"]:
            self.doc.add_heading(u["title"], level=3)
        for b in u["bullets"]:
            self.doc.add_paragraph(b, style="List Bullet")
        self.info["paragraphs"] += 1

    def block_table(self, u):
        tbl = u["table"]
        if u["title"]:
            self.doc.add_heading(u["title"], level=3)
        table = self.doc.add_table(rows=1, cols=len(tbl["columns"]))
        try:
            table.style = "Table Grid"
        except (KeyError, ValueError):
            pass
        for j, col in enumerate(tbl["columns"]):
            cell = table.rows[0].cells[j]
            cell.text = col
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.bold = True
        for row in tbl["rows"]:
            cells = table.add_row().cells
            for j, v in enumerate(row):
                cells[j].text = v
        self.info["tables"] += 1
        self._p((tbl["caption"] + " · " if tbl["caption"] else "") + f"Source: {self._source(tbl['source'])}", size=9, colour=self.c["muted"], italic=True)

    def block_chart(self, u):
        ch = u["chart"]
        if u["title"]:
            self.doc.add_heading(u["title"], level=3)
        svg_text = charts.svg(ch, self.c)
        caption = (ch["alt"] + " · " if ch["alt"] else "") + f"Source: {self._source(ch['source'])}"
        if not self._picture(svg_text, ch["alt"] or ch["title"] or u["title"], caption):
            # no renderer here: the data itself, as a table, so nothing is lost
            table = self.doc.add_table(rows=1, cols=len(ch["series"]) + 1)
            try:
                table.style = "Table Grid"
            except (KeyError, ValueError):
                pass
            table.rows[0].cells[0].text = "Category"
            for j, s in enumerate(ch["series"], 1):
                table.rows[0].cells[j].text = s["name"]
            for i, cat in enumerate(ch["categories"]):
                cells = table.add_row().cells
                cells[0].text = cat
                for j, s in enumerate(ch["series"], 1):
                    cells[j].text = charts.fmt(float(s["values"][i]), ch["unit"])
            self._p(f"{ch['alt'] or 'Chart data'} (chart drawn in the deck and the preview) · Source: {self._source(ch['source'])}", size=9, colour=self.c["muted"], italic=True)
        self.info["charts"] += 1

    def block_diagram(self, u):
        d = u["diagram"]
        if u["title"]:
            self.doc.add_heading(u["title"], level=3)
        r = diagrams.render(d["mermaid"], self.c, d["alt"])
        if not self._picture(r["svg"], d["alt"] or u["title"], d["alt"]):
            self._p(f"{d['alt'] or 'Diagram'}: {diagrams.describe(r['model'])}", size=10, colour=self.c["muted"], italic=True)
        self.info["diagrams"] += 1

    def block_quote(self, u):
        q = u["quote"]
        p = self._p("“" + q["text"] + "”", size=13, colour=self.c["accent_text"], italic=True)
        p.paragraph_format.left_indent = Inches(0.4)
        self._p(("— " + q["who"] + " · " if q["who"] else "") + f"Source: {self._source(q['source'])}", size=9, colour=self.c["muted"])

    def block_image(self, u):
        im = u["image"]
        if u["title"]:
            self.doc.add_heading(u["title"], level=3)
        path = self.root / im["file"]
        if path.is_file() and self.resolver.inside(im["file"]):
            self.doc.add_picture(str(path), width=Inches(6.2))
            _alt(self.doc, im["alt"])
            self.info["images"] += 1
            if im["alt"]:
                self._p(im["alt"], size=9, colour=self.c["muted"], italic=True)
        else:
            self._p(f"Image {im['file']} is not in the project folder", size=9, colour=self.c["muted"])

    # ---- the document
    def build(self, out: Path) -> dict:
        d = self.doc
        d.core_properties.title = self.m["title"]
        d.core_properties.author = self.t.owner
        d.core_properties.subject = self.m["audience"]
        d.add_heading(self.m["title"], level=0)
        sub = " · ".join(x for x in (self.m["subtitle"], f"For {self.m['audience']}" if self.m["audience"] else "", self.m["date"]) if x)
        if sub:
            self._p(sub, size=12, colour=self.c["muted"])
        if self.m["summary"]:
            self._p(self.m["summary"])
        fn = {"heading": self.block_heading, "paragraph": self.block_paragraph, "bullets": self.block_bullets, "table": self.block_table, "chart": self.block_chart,
              "diagram": self.block_diagram, "quote": self.block_quote, "image": self.block_image,
              # a deck's layouts, should a deck be asked for as a document
              "title": self.block_heading, "two-column": self.block_bullets, "closing": self.block_paragraph}
        for sec in self.m["sections"]:
            d.add_heading(sec["title"], level=1)
            self.info["headings"] += 1
            for u in sec["units"]:
                if u["layout"] == "two-column":
                    u = {**u, "bullets": u["left"]["bullets"] + u["right"]["bullets"]}
                fn.get(u["layout"], self.block_paragraph)(u)
                self.info["blocks"] += 1
        footer = d.sections[0].footer
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.text = self.t.footer()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in fp.runs:
            r.font.size = Pt(8)
            r.font.color.rgb = _rgb(self.c["muted"])
        out.parent.mkdir(parents=True, exist_ok=True)
        d.save(str(out))
        self.info.update(file=out.name, bytes=out.stat().st_size, template=self.t.name, powered=self.t.powered, renderer=getattr(self.ras, "used", "none"))
        return self.info


def build(model: dict, template: Template, resolver, root: Path, out: Path, rasteriser=None) -> dict:
    return DocBuilder(model, template, resolver, root, rasteriser).build(out)


def read_back(path: Path) -> dict:
    doc = Document(str(path))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    heads = [p.text for p in doc.paragraphs if p.style is not None and p.style.name.startswith(("Heading", "Title")) and p.text.strip()]
    alts = []
    for sh in doc.inline_shapes:
        try:
            alts.append(sh._inline.docPr.get("descr") or "")
        except AttributeError:
            alts.append("")
    footer = " ".join(p.text for p in doc.sections[0].footer.paragraphs) if doc.sections else ""
    return {"paragraphs": paras, "headings": heads, "tables": len(doc.tables), "pictures": len(doc.inline_shapes), "alts": alts, "footer": footer,
            "title": doc.core_properties.title}
