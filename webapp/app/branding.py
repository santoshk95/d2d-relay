"""D2D Relay › Branding: the person's logo and a few words about their brand become 2-3 report palettes, made by the
Relay Model; they pick one, and every new dashboard uses it (main.create_project, unless they untick it).

Stored in the meta table as JSON (one brand per install: D2D Relay has one client):
  {"logo": "data:image/png;base64,…", "logo_colors": ["#RRGGBB", …], "description": "…",
   "variants": [{"name", "why", "accent", "colors": [6-8 × "#RRGGBB"], "look": soft|flat|3d, "dark": bool}, …],
   "chosen": 0 | null, "updated": <time>}
"""
from __future__ import annotations

import base64
import io
import json
import re
import time

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from . import askd, auth, db

router = APIRouter()
KEY = "d2d_brand"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_LOGO = 1_500_000
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "image/svg+xml": "svg+xml"}
LOOKS = ("soft", "flat", "3d")

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


def _load() -> dict:
    try:
        return json.loads(db.meta(KEY) or "{}")
    except ValueError:
        return {}


def _save(b: dict) -> dict:
    b["updated"] = time.time()
    db.set_meta(KEY, json.dumps(b))
    return b


def public(b: dict | None = None) -> dict:
    b = _load() if b is None else b
    chosen = b.get("chosen")
    v = b.get("variants") or []
    return {"logo": b.get("logo"), "logo_colors": b.get("logo_colors") or [], "description": b.get("description") or "",
            "variants": v, "chosen": chosen if isinstance(chosen, int) and 0 <= chosen < len(v) else None, "updated": b.get("updated")}


def chosen_style() -> dict | None:
    """The theme keys of the chosen palette (for main.create_project), or None."""
    b = public()
    if b["chosen"] is None:
        return None
    v = b["variants"][b["chosen"]]
    return {"look": v["look"], "accent": v["accent"], "palette": "custom", "colors": v["colors"], "dark": bool(v.get("dark")),
            "brand_name": v["name"]}


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
    return {"name": str(v.get("name") or "Palette")[:40], "why": str(v.get("why") or "")[:240], "accent": accent,
            "colors": colors, "look": look, "dark": bool(v.get("dark"))}


# ---------------------------------------------------------------- routes

def _me() -> dict:
    u = auth.current.get()
    if not u:
        raise HTTPException(401, "Sign in first.")
    return u


@router.get("/api/branding")
def get_branding():
    _me()
    return public()


@router.post("/api/branding/logo")
async def upload_logo(file: UploadFile = File(...)):
    _me()
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
    return public(_save(b))


class Describe(BaseModel):
    description: str = ""


@router.post("/api/branding/generate")
async def generate(body: Describe):
    u = _me()
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
        raise HTTPException(502, "Relay could not make palettes this time. Try again, or add a few words about the brand.")
    b.update({"description": desc, "variants": variants, "chosen": None})
    return public(_save(b))


class Choose(BaseModel):
    index: int | None = None


@router.post("/api/branding/choose")
def choose(body: Choose):
    _me()
    b = _load()
    n = len(b.get("variants") or [])
    if body.index is not None and not 0 <= body.index < n:
        raise HTTPException(400, "Pick one of the palettes shown.")
    b["chosen"] = body.index
    return public(_save(b))


@router.delete("/api/branding/logo")
def remove_logo():
    _me()
    b = _load()
    b.update({"logo": None, "logo_colors": []})
    return public(_save(b))
