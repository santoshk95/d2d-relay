"""Diagrams from Mermaid text. The flowchart grammar the studio uses is parsed here (graph / flowchart LR TD TB RL;
nodes A[box] B(rounded) C{decision} D((circle)); edges --> --- -.-> ==> with |labels|; chains; subgraphs are read and
ignored) and laid out in layers, so the same model draws an SVG for the HTML twin, native shapes in the deck and a
PNG — rendered in headless Chromium through Playwright where it is installed (the agent image), or through a
renderer callback the web app points at the agent's /render. Other Mermaid kinds (sequence, gantt …) are reported
as unsupported: the check warns and the slide shows the text."""
from __future__ import annotations

import re
from html import escape

NODE_RE = re.compile(r"^(?P<id>[A-Za-z0-9_]+)\s*(?:(?P<open>\(\(|\[/|\[|\(|\{|>)\s*(?P<label>.*?)\s*(?P<close>\)\)|/\]|\]|\)|\})?)?$")
NW, NH, GX, GY = 170, 56, 60, 44


def parse(text: str) -> dict:
    """{kind, direction, nodes: [{id, label, shape}], edges: [{from, to, label, style}], note}"""
    lines = [ln.strip() for ln in (text or "").replace(";", "\n").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]
    if not lines:
        return {"kind": "empty", "nodes": [], "edges": [], "direction": "LR", "note": "no diagram text"}
    head = lines[0]
    m = re.match(r"^(graph|flowchart)\s*(LR|TD|TB|RL|BT)?", head, re.I)
    if not m:
        kind = head.split()[0].lower()
        return {"kind": kind, "nodes": [], "edges": [], "direction": "LR", "note": f"{kind} diagrams are not drawn yet (flowcharts are); the text is shown instead"}
    direction = (m.group(2) or "TD").upper()
    nodes: dict[str, dict] = {}
    order: list[str] = []
    edges = []

    def node(tok: str) -> str | None:
        tok = tok.strip()
        mm = NODE_RE.match(tok)
        if not mm:
            return None
        nid = mm.group("id")
        label = (mm.group("label") or "").strip().strip('"')
        shape = {"[": "box", "(": "rounded", "((": "circle", "{": "decision", ">": "flag", "[/": "slant"}.get(mm.group("open") or "[", "box")
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label or nid, "shape": shape}
            order.append(nid)
        elif label:
            nodes[nid].update(label=label, shape=shape)
        return nid

    node_tok = re.compile(r"[A-Za-z0-9_]+\s*(?:\(\(.*?\)\)|\[/.*?/\]|\[.*?\]|\(.*?\)|\{.*?\}|>.*?\])?")
    amp = re.compile(r"\s*&\s*")
    edge_op = re.compile(r"\s*(?:(?P<op1>-\.->|-\.-|-->|---|==>|==)\s*(?:\|(?P<lbl1>[^|]*)\|)?"
                         r"|(?P<op2>--|==|-\.)\s*(?P<lbl2>[^-=.|>][^->=|]*?)\s*(?P<op3>-->|---|==>|\.->|-\.->|==))\s*")
    depth = 0
    for ln in lines[1:]:
        low = ln.lower()
        if low.startswith("subgraph"):
            depth += 1
            continue
        if low == "end":
            depth = max(0, depth - 1)
            continue
        if low.startswith(("classdef", "class ", "style ", "linkstyle", "click ", "direction")):
            continue
        groups, ops, pos = [], [], 0
        while pos < len(ln):
            nm = node_tok.match(ln, pos)
            if not nm:
                break
            grp = [node(nm.group(0))]
            pos = nm.end()
            am = amp.match(ln, pos)
            while am:
                nm2 = node_tok.match(ln, am.end())
                if not nm2:
                    break
                grp.append(node(nm2.group(0)))
                pos = nm2.end()
                am = amp.match(ln, pos)
            groups.append([g for g in grp if g])
            em = edge_op.match(ln, pos)
            if not em or em.end() == pos:
                break
            op = em.group("op1") or em.group("op3") or "-->"
            label = (em.group("lbl1") or em.group("lbl2") or "").strip()
            ops.append({"label": label, "style": "dotted" if "." in op else "thick" if "=" in op else "solid", "arrow": op.endswith(">")})
            pos = em.end()
        for i, e in enumerate(ops):
            if i + 1 < len(groups):
                for a in groups[i]:
                    for b in groups[i + 1]:
                        edges.append({"from": a, "to": b, **e})
    return {"kind": "flowchart", "direction": direction, "nodes": [nodes[i] for i in order], "edges": edges, "note": ""}


def layout(model: dict) -> dict:
    """Layers by longest path from the sources; positions in a unit grid (x, y, w, h)."""
    nodes = {n["id"]: dict(n) for n in model["nodes"]}
    ids = list(nodes)
    preds: dict[str, list[str]] = {i: [] for i in ids}
    succs: dict[str, list[str]] = {i: [] for i in ids}
    for e in model["edges"]:
        if e["from"] in nodes and e["to"] in nodes and e["from"] != e["to"]:
            succs[e["from"]].append(e["to"])
            preds[e["to"]].append(e["from"])
    rank: dict[str, int] = {}

    def r(i: str, seen: frozenset = frozenset()) -> int:
        if i in rank:
            return rank[i]
        if i in seen:                                    # a cycle: break it here
            return 0
        rank[i] = 1 + max((r(p, seen | {i}) for p in preds[i]), default=-1)
        return rank[i]

    for i in ids:
        r(i)
    layers: dict[int, list[str]] = {}
    for i in ids:                                        # keep the declaration order inside a layer
        layers.setdefault(rank[i], []).append(i)
    horizontal = model["direction"] in ("LR", "RL")
    depth = max(layers) + 1 if layers else 0
    breadth = max((len(v) for v in layers.values()), default=0)
    for k, lst in layers.items():
        for j, i in enumerate(lst):
            off = (breadth - len(lst)) / 2
            a, b = k, j + off
            if model["direction"] == "RL":
                a = depth - 1 - k
            if model["direction"] == "BT":
                a = depth - 1 - k
            if horizontal:
                nodes[i].update(x=a * (NW + GX), y=b * (NH + GY))
            else:
                nodes[i].update(x=b * (NW + GX), y=a * (NH + GY))
    w = (depth if horizontal else breadth) * (NW + GX) - GX if ids else 0
    h = (breadth if horizontal else depth) * (NH + GY) - GY if ids else 0
    return {**model, "nodes": [nodes[i] for i in ids], "width": max(w, 10), "height": max(h, 10), "layers": depth}


def _anchor(n: dict, other: dict, horizontal: bool) -> tuple[float, float]:
    cx, cy = n["x"] + NW / 2, n["y"] + NH / 2
    ox, oy = other["x"] + NW / 2, other["y"] + NH / 2
    if horizontal and abs(ox - cx) >= abs(oy - cy):
        return (n["x"] + NW if ox > cx else n["x"], cy)
    if not horizontal and abs(oy - cy) >= abs(ox - cx):
        return (cx, n["y"] + NH if oy > cy else n["y"])
    return (n["x"] + NW if ox > cx else n["x"], cy) if abs(ox - cx) > abs(oy - cy) else (cx, n["y"] + NH if oy > cy else n["y"])


def _wrap(label: str, width_chars: int = 20) -> list[str]:
    words, lines, cur = label.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width_chars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines[:3] or [label]


def svg(model: dict, colours: dict | None = None, alt: str = "") -> str:
    """The laid-out flowchart as SVG (fits its content; the twin scales it)."""
    c = colours or {}
    ink, accent, line, bg = c.get("text", "#1A1A1A"), c.get("accent", "#00C48C"), c.get("muted", "#525252"), c.get("bg", "#FFFFFF")
    if model.get("kind") != "flowchart" or not model.get("nodes"):
        text = escape(model.get("note") or "No diagram")
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 80" role="img" aria-label="{escape(alt or text)}"><title>{escape(alt or text)}</title><text x="12" y="44" font-size="14" fill="{line}">{text}</text></svg>'
    lay = model if "width" in model else layout(model)
    pad = 12
    W, H = lay["width"] + 2 * pad, lay["height"] + 2 * pad
    by = {n["id"]: n for n in lay["nodes"]}
    horizontal = lay["direction"] in ("LR", "RL")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(alt or "Diagram")}" class="diagram">',
           f"<title>{escape(alt or 'Diagram')}</title><desc>{escape(describe(lay))}</desc>",
           f'<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{line}"/></marker></defs>']
    for e in lay["edges"]:
        a, b = by.get(e["from"]), by.get(e["to"])
        if not a or not b:
            continue
        x1, y1 = _anchor(a, b, horizontal)
        x2, y2 = _anchor(b, a, horizontal)
        dash = ' stroke-dasharray="5 4"' if e.get("style") == "dotted" else ""
        width = 3 if e.get("style") == "thick" else 1.6
        head = ' marker-end="url(#arr)"' if e.get("arrow", True) else ""
        out.append(f'<line x1="{x1 + pad:.1f}" y1="{y1 + pad:.1f}" x2="{x2 + pad:.1f}" y2="{y2 + pad:.1f}" stroke="{line}" stroke-width="{width}"{dash}{head}/>')
        if e.get("label"):
            out.append(f'<text x="{(x1 + x2) / 2 + pad:.1f}" y="{(y1 + y2) / 2 + pad - 6:.1f}" text-anchor="middle" font-size="11.5" fill="{line}">{escape(e["label"])}</text>')
    for n in lay["nodes"]:
        x, y = n["x"] + pad, n["y"] + pad
        shape = n.get("shape", "box")
        if shape == "decision":
            out.append(f'<path d="M{x + NW / 2},{y} L{x + NW},{y + NH / 2} L{x + NW / 2},{y + NH} L{x},{y + NH / 2} Z" fill="{bg}" stroke="{accent}" stroke-width="1.6"/>')
        elif shape == "circle":
            out.append(f'<ellipse cx="{x + NW / 2}" cy="{y + NH / 2}" rx="{NW / 2}" ry="{NH / 2}" fill="{bg}" stroke="{accent}" stroke-width="1.6"/>')
        else:
            rx = 14 if shape == "rounded" else 6
            out.append(f'<rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="{rx}" fill="{bg}" stroke="{accent}" stroke-width="1.6"/>')
        lines = _wrap(n["label"])
        y0 = y + NH / 2 - (len(lines) - 1) * 8
        for i, ln in enumerate(lines):
            out.append(f'<text x="{x + NW / 2}" y="{y0 + i * 16 + 4.5:.1f}" text-anchor="middle" font-size="13" font-weight="600" fill="{ink}">{escape(ln)}</text>')
    out.append("</svg>")
    return "".join(out)


def describe(model: dict) -> str:
    nodes, edges = model.get("nodes") or [], model.get("edges") or []
    if not nodes:
        return model.get("note") or "No diagram."
    by = {n["id"]: n["label"] for n in nodes}
    flows = "; ".join(f"{by.get(e['from'], e['from'])} to {by.get(e['to'], e['to'])}" + (f" ({e['label']})" if e.get("label") else "") for e in edges[:12])
    return f"Flowchart with {len(nodes)} steps and {len(edges)} connections: {flows}."


def render(text: str, colours: dict | None = None, alt: str = "") -> dict:
    """Mermaid text -> {model (laid out), svg, note}."""
    model = layout(parse(text)) if parse(text)["kind"] == "flowchart" else parse(text)
    return {"model": model, "svg": svg(model, colours, alt), "note": model.get("note", ""), "kind": model.get("kind")}


# ---------------------------------------------------------------- PNG (headless Chromium)

def html_for(svg_text: str, width: int = 1200) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><style>body{{margin:0;background:#fff}}svg{{width:{width}px;height:auto;display:block}}</style></head><body>{svg_text}</body></html>'


class Rasteriser:
    """SVG -> PNG. With Playwright installed (the agent image) one Chromium is kept open for the whole build; otherwise
    `renderer(html) -> bytes | None` (the web app's callback to the agent's /render) is used; otherwise None."""

    def __init__(self, renderer=None, width: int = 1200):
        self.renderer, self.width = renderer, width
        self._pw = self._browser = None
        self.used = "none"

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
            self.used = "playwright"
        except Exception:  # noqa: BLE001 - no browser here: fall back to the callback
            self._pw = self._browser = None
            self.used = "callback" if self.renderer else "none"
        return self

    def __exit__(self, *a):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass

    def png(self, svg_text: str) -> bytes | None:
        html = html_for(svg_text, self.width)
        if self._browser:
            try:
                page = self._browser.new_page(viewport={"width": self.width, "height": 800}, device_scale_factor=2)
                page.set_content(html, wait_until="load", timeout=15000)
                el = page.query_selector("svg")
                data = el.screenshot(type="png") if el else page.screenshot(type="png")
                page.close()
                return data
            except Exception:  # noqa: BLE001
                return None
        if self.renderer:
            try:
                return self.renderer(html)
            except Exception:  # noqa: BLE001
                return None
        return None
