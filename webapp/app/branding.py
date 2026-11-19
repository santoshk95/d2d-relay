"""D2D Relay > Branding: the organisation's brand, the style every report it makes uses: a palette (2-3 made by the
Relay Model from its logo and a few words, or a standard one) and a font family (a body font and an optional heading
font, from Power BI's own list). Since 2026-11-19 it is mandatory (the user: "prototype and theme needs to be set
mandate before starting so its a step for branding and maintaining across the reporting and including fonts family"):
a new dashboard needs one (require_style, called by main._options), every new dashboard uses it, and only the
organisation's owners change it. Only reports use it: the app and Ask Relay keep their own look (Ask Relay's charts
take the palette's colours, never its fonts).

Stored in the workspace's meta table as JSON (each organisation is a workspace):
  {"logo": "data:image/png;base64,...", "logo_colors": ["#RRGGBB", ...], "description": "...",
   "variants": [{"name", "why", "accent", "colors": [6-8 × "#RRGGBB"], "look": soft|flat|3d, "dark": bool}, ...],
   "style": <the palette in use: one of the variants, or a standard palette> | null,
   "chosen": <its index in variants> | null, "font": "Segoe UI", "heading_font": null | "<a font>", "updated": <time>}
Before 2026-11-19 there was no "style": "chosen" pointed into "variants" (still read that way, and still written for
older readers).
"""
from __future__ import annotations

import base64
import io
import json
import re
import time

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from genbi_kit.plaintext import human

from . import askd, auth, db, orgs

router = APIRouter()
KEY = "d2d_brand"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_LOGO = 1_500_000
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "image/svg+xml": "svg+xml"}
LOOKS = ("soft", "flat", "3d")

# The fonts a brand may use: Power BI's own list (the Format pane's Font family; Power BI Desktop 2.159, October 2026:
# FontService.standardFontInfos), less its symbol fonts (Symbol, Wingdings, Cambria Math), Arial Unicode MS (no longer
# installed with Windows or Office) and Comic Sans MS. Power BI serves the Segoe UI and DIN families itself, so they look
# the same in Desktop and the service on every device; the others are Windows and Office fonts.
SERVED = ("Segoe UI", "Segoe UI Light", "Segoe UI Semibold", "Segoe UI Bold", "DIN", "DIN Light")
FONTS = SERVED + ("Arial", "Arial Black", "Calibri", "Cambria", "Candara", "Consolas", "Constantia", "Corbel",
                  "Courier New", "Georgia", "Lucida Sans Unicode", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana")
DEFAULT_FONT = "Segoe UI"
WEIGHTED = re.compile(r"\b(Light|Semibold|Bold|Black)$")      # a font named for its weight: its titles are not made bold

# Palettes that need no logo and no Relay Model: a brand can be set when the Relay Model is busy, or before there is a
# logo. The first is Power BI's own default palette, the second the classic warm theme reports had before brands.
STANDARD = (
    {"name": "Classic blue", "why": "Power BI's own default colours: familiar to every reader.", "accent": "#118DFF",
     "colors": ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2", "#D9B300", "#D64550"],
     "look": "flat", "dark": False, "standard": True},
    {"name": "Warm amber", "why": "The warm amber, brown and blue Relay reports have always used.", "accent": "#DD7A12",
     "colors": ["#DD7A12", "#9C4F0C", "#F2B166", "#3B78D8", "#6F6761", "#C9A27A", "#2E7D3A", "#B3261E"],
     "look": "soft", "dark": False, "standard": True},
    {"name": "Calm teal", "why": "Teal with navy and amber: calm and corporate.", "accent": "#0F766E",
     "colors": ["#0F766E", "#1E3A8A", "#F59E0B", "#BE185D", "#64748B", "#7C3AED", "#65A30D", "#0284C7"],
     "look": "soft", "dark": False, "standard": True},
)

SYSTEM = """You are the Relay Model, designing Power BI report colour palettes for a company's dashboards.
Reply with exactly ONE JSON object and nothing else - no prose, no code fence:
{"variants": [{"name": "<2-3 words>", "why": "<one sentence: how it reflects the brand>",
               "accent": "#RRGGBB", "colors": ["#RRGGBB", ... 6 to 8 colours], "look": "soft" | "flat" | "3d",
               "dark": false | true}, ... 3 variants]}
Rules: colours come from the logo's colours and the brand description; the first colour is the main brand colour.
Every colour must be distinct and readable as a chart series on the report background (white, or near-black when
dark is true): no two series colours so close that a reader confuses them, no near-white series on a light report.
Make the 3 variants clearly different: for example one faithful to the logo, one calmer or more corporate, one
bolder or dark. Never mention any AI model or company."""


def font_name(name) -> str | None:
    """One of FONTS, as Power BI spells it (any case), or None."""
    n = " ".join(str(name or "").split()).lower()
    return next((f for f in FONTS if f.lower() == n), None)


def _same(a: dict | None, b: dict | None) -> bool:
    """The same palette (a variant kept as the style in use is a copy of it)."""
    keys = ("name", "accent", "colors", "look")
    return bool(a) and bool(b) and all(a.get(k) == b.get(k) for k in keys) and bool(a.get("dark")) == bool(b.get("dark"))


def _load() -> dict:
    try:
        b = json.loads(db.meta(KEY) or "{}")
    except ValueError:
        b = {}
    b = b if isinstance(b, dict) else {}
    if not isinstance(b.get("style"), dict):          # before 2026-11-19: "chosen" pointed into "variants"
        v, c = b.get("variants") or [], b.get("chosen")
        b["style"] = v[c] if "style" not in b and isinstance(c, int) and 0 <= c < len(v) and isinstance(v[c], dict) else None
    return b


def _save(b: dict) -> dict:
    v = b.get("variants") or []
    b["chosen"] = next((i for i, x in enumerate(v) if _same(x, b.get("style"))), None)     # for readers from before "style"
    b["updated"] = time.time()
    db.set_meta(KEY, json.dumps(b))
    return b


def public(b: dict | None = None) -> dict:
    """The brand as the screens and New dashboard see it. `variants` lists the palettes on offer with the one in use
    first when it is not one of them (a standard palette, or one from an earlier set), so `variants[chosen]` is always
    the palette in use; `ready` says a dashboard can be started (a palette is chosen; the fonts default to Segoe UI)."""
    b = _load() if b is None else b
    offers = [v for v in (b.get("variants") or []) if isinstance(v, dict)]
    style = b.get("style") if isinstance(b.get("style"), dict) else None
    chosen = next((i for i, v in enumerate(offers) if _same(v, style)), None) if style else None
    if style and chosen is None:
        offers, chosen = [style] + offers, 0
    font = font_name(b.get("font")) or DEFAULT_FONT
    head = font_name(b.get("heading_font"))
    return {"logo": b.get("logo"), "logo_colors": b.get("logo_colors") or [], "description": b.get("description") or "",
            "variants": offers, "chosen": chosen, "style": style, "font": font, "heading_font": head if head != font else None,
            "ready": style is not None, "updated": b.get("updated")}


def chosen_style() -> dict | None:
    """The theme keys of the organisation's brand (main._options puts them in a new dashboard's request.md; Ask Relay
    reads only its colours), or None while it has no palette."""
    b = public()
    v = b["style"]
    if not v or not v.get("colors"):
        return None
    return {"look": v.get("look") if v.get("look") in LOOKS else "soft", "accent": v.get("accent") or v["colors"][0],
            "palette": "custom", "colors": v["colors"], "dark": bool(v.get("dark")), "brand_name": v.get("name") or "",
            "font": b["font"], **({"heading_font": b["heading_font"]} if b["heading_font"] else {})}


def title_style(font: str) -> str:
    """definition.yaml's theme.styles for a heading font: every visual title in it (a font named for its weight keeps
    that weight: Power BI would otherwise make the title bold on top)."""
    return '{"*": {title: {fontFamily: "%s"%s}}}' % (font, ", bold: false" if WEIGHTED.search(font) else "")


def may_edit(u: dict | None) -> bool:
    """Who changes the brand: the organisation's owners (and PASDACS on the admin portal); in a workspace that is no
    organisation, anyone signed in (as before 2026-11-19)."""
    if not u:
        return False
    if not orgs.row(db.tenant()):
        return True
    return orgs.is_owner(u) or orgs.platform_admin(u)


def require_style() -> dict:
    """The brand style for a new dashboard (main._options, before anything is saved or charged). Without one, a 400
    that says where to set it: an owner sets it under Branding (New dashboard's Theme step links to
    #/branding?return=new)."""
    s = chosen_style()
    if s:
        return s
    if may_edit(auth.current.get()):
        raise HTTPException(400, "Set your brand first: choose a palette and fonts under Branding. Every new dashboard uses them.")
    o = orgs.row(db.tenant()) or {}
    raise HTTPException(400, f"{o.get('name') or 'Your organisation'} has no brand yet: an owner chooses its palette and "
                             "fonts under Branding before dashboards can be started.")


def _hexes(colors) -> list[str]:
    out = []
    for c in colors or []:
        c = str(c).strip().upper()
        if HEX.match(c) and c not in out:
            out.append(c)
    return out


def logo_colors(raw: bytes, kind: str) -> list[str]:
    """The logo's main colours, most used first: SVG fill/stroke colours, or a small-palette count of the pixels
    (transparent, near-white and near-black pixels skipped when the logo has other colours)."""
    if kind == "svg+xml":
        found = re.findall(r"#[0-9A-Fa-f]{6}\b", raw.decode("utf-8", "replace"))
        counts: dict[str, int] = {}
        for c in found:
            counts[c.upper()] = counts.get(c.upper(), 0) + 1
        return _distinct(sorted(counts, key=counts.get, reverse=True))[:6]
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img.thumbnail((160, 160))
    px = [p for p in img.getdata() if p[3] > 128]
    if not px:
        return []
    q = Image.new("RGB", (len(px), 1))
    q.putdata([p[:3] for p in px])
    pal = q.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    rgb = pal.getpalette()[:24]
    counts = sorted(pal.getcolors(), reverse=True)
    out = []
    for n, i in counts:
        r, g, b_ = rgb[i * 3:i * 3 + 3]
        light, dark = min(r, g, b_) > 235, max(r, g, b_) < 25
        out.append(("#%02X%02X%02X" % (r, g, b_), n, light or dark))
    keep = [c for c, _, plain in out if not plain] or [c for c, _, _ in out]
    return _distinct(keep)[:6]


def _distinct(colors: list[str], gap: int = 48) -> list[str]:
    """Drop shades too close to a colour already kept (anti-aliased logo edges give many near-copies)."""
    rgb = lambda c: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))  # noqa: E731
    out: list[str] = []
    for c in colors:
        if all(sum((a - b) ** 2 for a, b in zip(rgb(c), rgb(k))) ** 0.5 >= gap for k in out):
            out.append(c)
    return out


def _clean_variant(v: dict) -> dict | None:
    if not isinstance(v, dict):
        return None
    colors = _hexes(v.get("colors"))[:8]
    accent = str(v.get("accent") or "").upper()
    if len(colors) < 4:
        return None
    if not HEX.match(accent):
        accent = colors[0]
    look = v.get("look") if v.get("look") in LOOKS else "soft"
    return {"name": human(str(v.get("name") or "Palette"))[:40], "why": human(str(v.get("why") or ""))[:240], "accent": accent,
            "colors": colors, "look": look, "dark": bool(v.get("dark"))}


# ---------------------------------------------------------------- routes

def _me() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in first.")
    return u


def _owner() -> dict:
    """The person changing the brand: one of the organisation's owners."""
    u = _me()
    if not may_edit(u):
        o = orgs.row(db.tenant()) or {}
        raise HTTPException(403, f"Only an owner of {o.get('name') or 'your organisation'} changes its brand.")
    return u


def _out(b: dict, u: dict | None) -> dict:
    """What the Branding screens get: the brand, the fonts and standard palettes to choose from (`served`: a font
    Power BI serves itself, the same on every device), and whether this person may change it."""
    return {**b, "fonts": [{"name": f, "served": f in SERVED} for f in FONTS], "default_font": DEFAULT_FONT,
            "standard": [dict(s) for s in STANDARD], "may_edit": may_edit(u)}


@router.get("/api/branding")
def get_branding():
    return _out(public(), _me())


@router.post("/api/branding/logo")
async def upload_logo(file: UploadFile = File(...)):
    u = _owner()
    kind = IMAGE_TYPES.get((file.content_type or "").lower())
    if not kind:
        raise HTTPException(400, "Use a PNG, JPG, WebP or SVG logo.")
    raw = await file.read()
    if len(raw) > MAX_LOGO:
        raise HTTPException(400, "The logo is too large: keep it under 1.5 MB.")
    try:
        colors = logo_colors(raw, kind)
    except Exception:  # noqa: BLE001 - a broken image is the person's to fix; say so plainly
        raise HTTPException(400, "Could not read that image. Try a PNG or SVG of the logo.")
    b = _load()
    b.update({"logo": f"data:image/{kind};base64," + base64.b64encode(raw).decode(), "logo_colors": colors})
    return _out(public(_save(b)), u)


class Describe(BaseModel):
    description: str = ""


@router.post("/api/branding/generate")
async def generate(body: Describe):
    """New palettes on offer. The palette in use stays in use (the brand is never unset) until an owner picks another."""
    u = _owner()
    b = _load()
    desc = (body.description or "").strip()[:1500]
    if not desc and not b.get("logo_colors"):
        raise HTTPException(400, "Add your logo or describe your brand first.")
    prompt = ("Design 3 report palettes for this brand.\n\n"
              f"Logo colours (most used first): {', '.join(b.get('logo_colors') or []) or 'no logo given'}\n"
              f"Brand description: {desc or '(none given: use the logo colours)'}\n")
    try:
        res = await askd.ask_json(u, SYSTEM, prompt, "branding", "relay")
    except askd.AskError as e:
        raise HTTPException(503, str(e))
    variants = [v for v in (_clean_variant(x) for x in (res.get("variants") or [])) if v][:3]
    if len(variants) < 2:
        raise HTTPException(502, "Relay could not make palettes this time. Try again, add a few words about the brand, "
                                 "or start from a standard palette.")
    b.update({"description": desc, "variants": variants})
    return _out(public(_save(b)), u)


class Choose(BaseModel):
    index: int | None = None
    standard: bool = False          # index into the standard palettes, not the brand's own


@router.post("/api/branding/choose")
def choose(body: Choose):
    """The palette every new dashboard uses: one on offer (an index into GET's `variants`) or a standard one. The
    brand cannot be switched off: a dashboard always uses the organisation's brand."""
    u = _owner()
    b = _load()
    pool = list(STANDARD) if body.standard else public(b)["variants"]
    if body.index is None or not 0 <= body.index < len(pool):
        raise HTTPException(400, "Pick one of the palettes shown.")
    b["style"] = dict(pool[body.index])
    db.audit("branding.palette", None, {"name": b["style"].get("name"), "standard": bool(body.standard)}, u["id"])
    return _out(public(_save(b)), u)


class Fonts(BaseModel):
    font: str = DEFAULT_FONT
    heading_font: str | None = None  # None or "": the same as the body font


@router.post("/api/branding/fonts")
def set_fonts(body: Fonts):
    """The brand's fonts: a body font for every text in a report, and a heading font for its visual titles."""
    u = _owner()
    font = font_name(body.font)
    head = font_name(body.heading_font) if (body.heading_font or "").strip() else None
    if not font or ((body.heading_font or "").strip() and not head):
        raise HTTPException(400, "Pick fonts from the list: those are the fonts Power BI reports can use.")
    b = _load()
    b.update({"font": font, "heading_font": head if head != font else None})
    db.audit("branding.fonts", None, {"font": font, "heading_font": b["heading_font"]}, u["id"])
    return _out(public(_save(b)), u)


@router.delete("/api/branding/logo")
def remove_logo():
    u = _owner()
    b = _load()
    b.update({"logo": None, "logo_colors": []})
    return _out(public(_save(b)), u)
