"""Templates: the RELAY house template generated from the PASDACS brand tokens (branding/pasdacs), or a tenant's
own .pptx / .potx / .docx / .dotx with named layouts. A partner install (brand.partner) gets its own name, mark colour
and logo everywhere, and the closing slide / footer says "Powered by PASDACS Relay". Limits and the house-style rules
live here too, so the checks and the builders agree."""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# PASDACS brand (branding/pasdacs/tokens.json): mono plus one mint. The key names are the engine's roles, kept from the
# first template so partner files and checks keep working: night = the dark band (brand-900), navy = the title band,
# signal = the logo mint for fills and bars (accent-500, never text on white), signal_text = mint text on white
# (accent-600, 5.36:1), signal_dark = mint text on the dark band (accent-400, 10.17:1 on brand-900).
TOKENS = {"night": "#111111", "navy": "#111111", "signal": "#00C48C", "signal_text": "#007A57", "signal_dark": "#33D6A6",
          "paper": "#F6F6F6", "line": "#E5E5E5", "ink": "#111111", "muted": "#525252", "white": "#FFFFFF", "band_body": "#E5E5E5",
          "ok": "#047857", "warn": "#8A5A00", "err": "#DC2626"}
PALETTE = ["#007A57", "#111111", "#00C48C", "#737373", "#33D6A6", "#A3A3A3", "#DC2626"]     # charts: mint and ink first, then neutral steps; red last
FONTS = {"head": "Manrope", "body": "Inter"}
LIMITS = {"max_slides": 40, "max_bullets": 7, "max_bullet_chars": 160, "max_title_chars": 70, "max_doc_paragraphs": 400,
          "max_table_rows": 14, "max_table_cols": 7, "min_contrast": 4.5}
POWERED = "Powered by PASDACS Relay"
PLACEHOLDER_RE = re.compile(r"\b(lorem|ipsum|todo|tbd|tbc|xxx+|placeholder|fixme|insert [a-z ]+ here)\b|\[(?:insert|placeholder|todo)[^\]]*\]|\?\?\?", re.I)
# American spellings the house style does not use (plain British English, glossary §1); value = the spelling to use.
BRITISH = {"organization": "organisation", "organizations": "organisations", "organize": "organise", "organized": "organised", "organizing": "organising",
           "optimize": "optimise", "optimized": "optimised", "optimization": "optimisation", "prioritize": "prioritise", "prioritized": "prioritised",
           "realize": "realise", "realized": "realised", "recognize": "recognise", "recognized": "recognised", "standardize": "standardise",
           "standardized": "standardised", "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing", "color": "colour", "colors": "colours",
           "center": "centre", "centers": "centres", "behavior": "behaviour", "behaviors": "behaviours", "catalog": "catalogue", "catalogs": "catalogues",
           "favorite": "favourite", "labor": "labour", "modeling": "modelling", "modeled": "modelled", "canceled": "cancelled", "traveled": "travelled",
           "fulfill": "fulfil", "enrollment": "enrolment", "gray": "grey", "defense": "defence", "aluminum": "aluminium", "liter": "litre",
           "theater": "theatre", "utilize": "utilise", "utilization": "utilisation", "summarize": "summarise", "summarized": "summarised",
           "customize": "customise", "customized": "customised", "visualization": "visualisation", "visualizations": "visualisations", "licensing": "licencing"}
# Product names keep their makers' spelling (the house style does not rewrite a name): "Unity Catalog", "Partner Center".
PRODUCT_NAMES = ("Unity Catalog", "AWS Glue Data Catalog", "Glue Data Catalog", "Azure Data Catalog", "Google Data Catalog", "Purview Data Catalog", "Data Catalog",
                 "Partner Center", "Admin Center", "Microsoft 365 admin center", "Security Center", "Defender for Cloud", "Control Center", "Service Catalog",
                 "AWS Service Catalog", "Color Contrast Analyser", "Optimizer", "Query Optimizer")
PRODUCT_RE = re.compile("|".join(re.escape(n) for n in sorted(PRODUCT_NAMES, key=len, reverse=True)), re.I)
DECK_LAYOUT_NAMES = {"title": ["Title Slide", "Title"], "bullets": ["Title and Content", "Content"], "two-column": ["Two Content", "Comparison", "Title and Content"],
                     "table": ["Title Only", "Title and Content"], "chart": ["Title Only", "Title and Content"], "diagram": ["Title Only", "Title and Content"],
                     "quote": ["Title Only", "Blank"], "closing": ["Title Slide", "Section Header", "Title"], "image": ["Title Only", "Blank"]}


@dataclass
class Template:
    name: str = "relay"
    pptx: Path | None = None                     # a tenant deck template (.pptx / .potx), None = generated
    docx: Path | None = None                     # a tenant document template (.docx / .dotx), None = generated
    colours: dict = field(default_factory=dict)  # bg, text, muted, accent, accent_text, band, band_text, line
    fonts: dict = field(default_factory=lambda: dict(FONTS))
    limits: dict = field(default_factory=lambda: dict(LIMITS))
    brand: dict = field(default_factory=dict)    # name, full, partner, mark, colour, logo (data URL), house_style, powered
    theme: dict = field(default_factory=dict)    # the tenant file's theme colours (dk1, lt1, accent1 …) when read
    notes: list = field(default_factory=list)    # what the loader could not do

    @property
    def partner(self) -> bool:
        return bool(self.brand.get("partner"))

    @property
    def owner(self) -> str:
        return self.brand.get("full") or self.brand.get("name") or "RELAY by PASDACS"

    @property
    def powered(self) -> str:
        return POWERED if self.partner else ""

    def footer(self) -> str:
        return f"{self.owner} · {POWERED}" if self.partner else self.owner

    def contrast_pairs(self) -> list[tuple[str, str, str, float]]:
        """(what, foreground, background, minimum ratio): 4.5:1 for body-size text, 3:1 for the large title text on the band (WCAG 2 AA)."""
        c = self.colours
        return [("body text on the background", c["text"], c["bg"], 4.5), ("muted text on the background", c["muted"], c["bg"], 4.5),
                ("accent text on the background", c["accent_text"], c["bg"], 4.5), ("title text on the band (large text)", c["band_text"], c["band"], 3.0)]


def default_template(brand: dict | None = None) -> Template:
    """The RELAY look from the tokens; a partner's brand swaps the name, the band colour and the logo and adds the
    Powered-by line. A partner colour too light for white text is reported by the contrast check, never silently fixed."""
    b = dict(brand or {})
    partner = bool(b.get("partner"))
    band = (b.get("color") or b.get("colour") or TOKENS["navy"]) if partner else TOKENS["navy"]
    colours = {"bg": TOKENS["white"], "paper": TOKENS["paper"], "text": TOKENS["ink"], "muted": TOKENS["muted"], "accent": TOKENS["signal"],
               "accent_text": TOKENS["signal_text"], "band": band, "band_text": TOKENS["white"], "line": TOKENS["line"], "night": TOKENS["night"]}
    if partner and b.get("accent_hex"):
        colours["accent"] = b["accent_hex"]
    info = {"name": b.get("name") or "Relay", "full": b.get("full") or "RELAY by PASDACS", "partner": partner, "mark": b.get("mark") or "R",
            "colour": band, "logo": b.get("logo_light") or "", "house_style": b.get("house_style") or "", "powered": POWERED if partner else "",
            "sender": b.get("sender") or ""}
    limits = dict(LIMITS)
    for k, v in (b.get("limits") or {}).items():
        if k in limits and isinstance(v, (int, float)):
            limits[k] = v
    return Template(name="relay" if not partner else f"partner:{info['name']}", colours=colours, brand=info, limits=limits)


# ---------------------------------------------------------------- tenant files

def as_pptx(path: Path, workdir: Path | None = None) -> Path:
    """python-pptx opens .pptx; a .potx (or .dotx for Word) is the same package with a template content type, so a
    copy with the presentation / document content type is made next to the build."""
    path = Path(path)
    if path.suffix.lower() not in (".potx", ".dotx"):
        return path
    target_ct = {".potx": ("application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
                           "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
                 ".dotx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")}[path.suffix.lower()]
    wd = workdir or Path(tempfile.mkdtemp(prefix="relay-tpl-"))
    wd.mkdir(parents=True, exist_ok=True)
    out = wd / (path.stem + (".pptx" if path.suffix.lower() == ".potx" else ".docx"))
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(target_ct[0].encode(), target_ct[1].encode())
            dst.writestr(item, data)
    return out


def theme_colours(path: Path) -> dict:
    """dk1 / lt1 / dk2 / lt2 / accent1-6 from the package's first theme (hex strings), or {} when unreadable."""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if re.match(r"(ppt|word)/theme/theme\d*\.xml$", n)]
            if not names:
                return {}
            xml = z.read(sorted(names)[0]).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile):
        return {}
    out = {}
    for name in ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"):
        m = re.search(rf"<a:{name}>\s*<a:(?:srgbClr val|sysClr val=\"\w+\" lastClr)=\"([0-9A-Fa-f]{{6}})\"", xml)
        if m:
            out[name] = "#" + m.group(1).upper()
    fonts = re.search(r"<a:majorFont>\s*<a:latin typeface=\"([^\"]*)\"", xml), re.search(r"<a:minorFont>\s*<a:latin typeface=\"([^\"]*)\"", xml)
    if fonts[0]:
        out["font_head"] = fonts[0].group(1)
    if fonts[1]:
        out["font_body"] = fonts[1].group(1)
    return out


def load_template(path: Path | str | None = None, brand: dict | None = None, docx: Path | str | None = None, workdir: Path | None = None) -> Template:
    """A tenant template: colours from its theme (text = dk1 on lt1, band = accent1 with lt1 text) so the contrast
    check judges the real file; layouts are picked by name at build time. Without a file: the generated RELAY template."""
    t = default_template(brand)
    if not path and not docx:
        return t
    if path:
        p = Path(path)
        if not p.is_file():
            t.notes.append(f"template {p.name} not found: the RELAY template is used")
        else:
            t.pptx = as_pptx(p, workdir)
            t.name = f"tenant:{p.name}"
            th = theme_colours(t.pptx)
            t.theme = th
            if th:
                # a tenant file's text is its own dk1 / dk2 on lt1; accent1 fills the title band (lt1 text on it, large)
                t.colours.update({"bg": th.get("lt1", t.colours["bg"]), "text": th.get("dk1", t.colours["text"]), "band": th.get("accent1", t.colours["band"]),
                                  "band_text": th.get("lt1", t.colours["band_text"]), "accent": th.get("accent1", t.colours["accent"]),
                                  "accent_text": th.get("dk1", t.colours["accent_text"]), "muted": th.get("dk2", t.colours["muted"])})
                t.fonts = {"head": th.get("font_head") or t.fonts["head"], "body": th.get("font_body") or t.fonts["body"]}
            else:
                t.notes.append(f"{p.name}: no theme colours could be read; the RELAY colours are assumed for the contrast check")
    if docx:
        d = Path(docx)
        if d.is_file():
            t.docx = as_pptx(d, workdir)
        else:
            t.notes.append(f"document template {d.name} not found: the RELAY document template is used")
    return t


# ---------------------------------------------------------------- colour maths (WCAG 2 contrast)

def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    s = hex_colour.lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg: str, bg: str) -> float:
    try:
        a, b = luminance(fg), luminance(bg)
    except (ValueError, IndexError):
        return 0.0
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def copy_into(path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / Path(path).name
    shutil.copyfile(path, out)
    return out
