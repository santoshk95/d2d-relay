"""Charts for the HTML twin (inline SVG, one system: the brand accent first, then neutral steps, labelled axes, a
<title> for screen readers) — the deck gets native PowerPoint charts from the same data (pptx_build.py)."""
from __future__ import annotations

import math
from html import escape

from .template import PALETTE

W, H = 920, 420
PAD = {"l": 70, "r": 24, "t": 36, "b": 56}


def fmt(v: float, unit: str = "") -> str:
    if v is None:
        return ""
    if abs(v) >= 1000:
        s = f"{v:,.0f}"
    elif abs(v) >= 100:
        s = f"{v:.0f}"
    elif float(v).is_integer():
        s = f"{int(v)}"
    else:
        s = f"{v:.1f}"
    return f"{s} {unit}".strip() if unit and unit != "%" else (s + unit if unit else s)


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), mag)
    start = math.floor(lo / step) * step
    out, v = [], start
    while v <= hi + step * 0.001:
        out.append(round(v, 10))
        v += step
    return out


def svg(chart: dict, colours: dict | None = None, width: int = W, height: int = H) -> str:
    """An SVG for one chart spec ({type, categories, series:[{name, values}], unit, title, alt})."""
    colours = colours or {}
    ink, muted, line = colours.get("text", "#1A1A1A"), colours.get("muted", "#56626E"), colours.get("line", "#E3E8EE")
    kind, cats, series, unit = chart.get("type", "column"), chart.get("categories") or [], chart.get("series") or [], chart.get("unit") or ""
    alt = chart.get("alt") or chart.get("title") or "Chart"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(alt)}" class="chart">',
             f"<title>{escape(alt)}</title>", f'<desc>{escape(describe(chart))}</desc>']
    if not cats or not series:
        parts.append(f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" fill="{muted}">No data</text></svg>')
        return "".join(parts)
    if kind == "pie":
        parts.append(_pie(cats, series[0], unit, width, height, ink, muted))
        parts.append("</svg>")
        return "".join(parts)
    vals = [float(v) for s in series for v in s["values"]]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    ticks = _ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    x0, y0, x1, y1 = PAD["l"], PAD["t"], width - PAD["r"], height - PAD["b"]
    if kind == "bar":                                   # horizontal: categories on the y axis
        x0 = max(PAD["l"], 12 + 7 * max(len(c) for c in cats))
        sy = lambda i: y0 + (y1 - y0) * i / len(cats)  # noqa: E731
        sx = lambda v: x0 + (x1 - x0) * (v - lo) / (hi - lo)  # noqa: E731
        for t in ticks:
            parts.append(f'<line x1="{sx(t):.1f}" y1="{y0}" x2="{sx(t):.1f}" y2="{y1}" stroke="{line}"/><text x="{sx(t):.1f}" y="{y1 + 18}" text-anchor="middle" font-size="12" fill="{muted}">{escape(fmt(t, unit))}</text>')
        band = (y1 - y0) / len(cats)
        bh = band * 0.7 / len(series)
        for i, c in enumerate(cats):
            parts.append(f'<text x="{x0 - 8}" y="{sy(i) + band / 2 + 4:.1f}" text-anchor="end" font-size="12.5" fill="{ink}">{escape(c)}</text>')
            for j, s in enumerate(series):
                v = float(s["values"][i])
                yy = sy(i) + band * 0.15 + j * bh
                tip = escape(c + " - " + s["name"] + ": " + fmt(v, unit))
                parts.append(f'<rect x="{min(sx(0), sx(v)):.1f}" y="{yy:.1f}" width="{abs(sx(v) - sx(0)):.1f}" height="{bh:.1f}" fill="{PALETTE[j % len(PALETTE)]}" rx="2"><title>{tip}</title></rect>')
                parts.append(f'<text x="{max(sx(0), sx(v)) + 5:.1f}" y="{yy + bh / 2 + 4:.1f}" font-size="11.5" fill="{ink}">{escape(fmt(v, unit))}</text>')
    else:                                               # column / line: categories on the x axis
        sx = lambda i: x0 + (x1 - x0) * (i + 0.5) / len(cats)  # noqa: E731
        sy = lambda v: y1 - (y1 - y0) * (v - lo) / (hi - lo)  # noqa: E731
        for t in ticks:
            parts.append(f'<line x1="{x0}" y1="{sy(t):.1f}" x2="{x1}" y2="{sy(t):.1f}" stroke="{line}"/><text x="{x0 - 8}" y="{sy(t) + 4:.1f}" text-anchor="end" font-size="12" fill="{muted}">{escape(fmt(t, unit))}</text>')
        for i, c in enumerate(cats):
            label = c if len(c) <= 14 else c[:13] + "…"
            parts.append(f'<text x="{sx(i):.1f}" y="{y1 + 18}" text-anchor="middle" font-size="12" fill="{ink}"><title>{escape(c)}</title>{escape(label)}</text>')
        if kind == "line":
            for j, s in enumerate(series):
                pts = " ".join(f"{sx(i):.1f},{sy(float(v)):.1f}" for i, v in enumerate(s["values"]))
                col = PALETTE[j % len(PALETTE)]
                parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round"/>')
                for i, v in enumerate(s["values"]):
                    tip = escape(cats[i] + " - " + s["name"] + ": " + fmt(float(v), unit))
                    parts.append(f'<circle cx="{sx(i):.1f}" cy="{sy(float(v)):.1f}" r="4" fill="{col}"><title>{tip}</title></circle>')
                    if len(cats) <= 12:
                        parts.append(f'<text x="{sx(i):.1f}" y="{sy(float(v)) - 9:.1f}" text-anchor="middle" font-size="11" fill="{ink}">{escape(fmt(float(v), unit))}</text>')
        else:
            band = (x1 - x0) / len(cats)
            bw = band * 0.7 / len(series)
            for i, c in enumerate(cats):
                for j, s in enumerate(series):
                    v = float(s["values"][i])
                    xx = sx(i) - band * 0.35 + j * bw
                    tip = escape(c + " - " + s["name"] + ": " + fmt(v, unit))
                    parts.append(f'<rect x="{xx:.1f}" y="{min(sy(0), sy(v)):.1f}" width="{bw:.1f}" height="{abs(sy(v) - sy(0)):.1f}" fill="{PALETTE[j % len(PALETTE)]}" rx="2"><title>{tip}</title></rect>')
                    if len(cats) * len(series) <= 16:
                        parts.append(f'<text x="{xx + bw / 2:.1f}" y="{min(sy(0), sy(v)) - 5:.1f}" text-anchor="middle" font-size="11" fill="{ink}">{escape(fmt(v, unit))}</text>')
        parts.append(f'<line x1="{x0}" y1="{sy(0):.1f}" x2="{x1}" y2="{sy(0):.1f}" stroke="{muted}"/>')
    if len(series) > 1:                                 # legend
        lx = x0
        for j, s in enumerate(series):
            parts.append(f'<rect x="{lx}" y="{height - 16}" width="12" height="12" fill="{PALETTE[j % len(PALETTE)]}" rx="2"/><text x="{lx + 17}" y="{height - 6}" font-size="12" fill="{ink}">{escape(s["name"])}</text>')
            lx += 24 + 7 * len(s["name"])
    parts.append("</svg>")
    return "".join(parts)


def _pie(cats: list[str], s: dict, unit: str, width: int, height: int, ink: str, muted: str) -> str:
    vals = [max(0.0, float(v)) for v in s["values"]]
    total = sum(vals) or 1.0
    cx, cy, r = width * 0.35, height / 2, min(width * 0.3, height * 0.42)
    out, a = [], -math.pi / 2
    for i, (c, v) in enumerate(zip(cats, vals)):
        frac = v / total
        b = a + 2 * math.pi * frac
        tip = escape(c + ": " + fmt(v, unit) + " (" + f"{frac * 100:.0f}" + "%)")
        if frac >= 0.9999:
            out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{PALETTE[i % len(PALETTE)]}"><title>{tip}</title></circle>')
        elif frac > 0:
            large = 1 if frac > 0.5 else 0
            d = f"M{cx},{cy} L{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f} A{r},{r} 0 {large} 1 {cx + r * math.cos(b):.1f},{cy + r * math.sin(b):.1f} Z"
            out.append(f'<path d="{d}" fill="{PALETTE[i % len(PALETTE)]}" stroke="#fff" stroke-width="1.5"><title>{tip}</title></path>')
        ly = 40 + i * 24
        if i < 14:
            out.append(f'<rect x="{width * 0.68}" y="{ly - 11}" width="13" height="13" rx="2" fill="{PALETTE[i % len(PALETTE)]}"/>'
                       f'<text x="{width * 0.68 + 20}" y="{ly}" font-size="12.5" fill="{ink}">{escape(c)}</text>'
                       f'<text x="{width * 0.68 + 20}" y="{ly + 13}" font-size="11" fill="{muted}">{escape(fmt(v, unit))} ({frac * 100:.0f}%)</text>')
        a = b
    return "".join(out)


def describe(chart: dict) -> str:
    """One sentence of the data, for alt text and the desc element."""
    cats, series, unit = chart.get("categories") or [], chart.get("series") or [], chart.get("unit") or ""
    if not series:
        return "No data."
    bits = []
    for s in series[:3]:
        vals = [float(v) for v in s["values"]]
        if not vals:
            continue
        i_max = max(range(len(vals)), key=lambda i: vals[i])
        bits.append(f"{s['name']}: highest {cats[i_max] if i_max < len(cats) else ''} at {fmt(vals[i_max], unit)}, total {fmt(sum(vals), unit)}")
    return f"{chart.get('type', 'column')} chart of {len(cats)} categories. " + "; ".join(bits) + "."
