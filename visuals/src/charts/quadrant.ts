// Quadrant scatter: bubbles, dashed reference lines, corner labels, named stand-out points.
import { svg, text, measure } from "../dom";
import { parseFormat, fmt, fmtTick, niceTicks } from "../format";
import { Tokens, Header, Interactions, frame, emptyState, FONT, bind, dimmed } from "../theme";

export interface QuadPoint {
    label: string;
    x: number | null;
    y: number | null;
    size?: number | null;
    key?: unknown;
}

export interface QuadrantModel {
    points: QuadPoint[];
    xRef?: number | null;
    yRef?: number | null;
    xFormat?: string;
    yFormat?: string;
    sizeFormat?: string;
    names?: { x?: string; y?: string; size?: string };
    corners?: { topLeft?: string; topRight?: string; bottomLeft?: string; bottomRight?: string };
    labelTop?: number;      // how many best points (top-right) to name
    labelBottom?: number;   // how many worst points (bottom-left) to name
}

export function renderQuadrant(root: HTMLElement, m: QuadrantModel, t: Tokens, header: Header, ia: Interactions = {}): void {
    const pts = m.points.filter(p => p.x !== null && p.y !== null && isFinite(p.x as number) && isFinite(p.y as number));
    if (!pts.length) {
        emptyState(root, t, "Add details, X and Y");
        return;
    }
    const sub = header.subtitle?.replace("{n}", String(pts.length));
    const f = frame(root, t, { ...header, subtitle: sub }, "gb-quadrant");
    const nfx = parseFormat(m.xFormat), nfy = parseFormat(m.yFormat), nfs = parseFormat(m.sizeFormat);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => ia.clear?.());

    const xs = pts.map(p => p.x as number), ys = pts.map(p => p.y as number);
    const xRef = m.xRef ?? null, yRef = m.yRef ?? null;
    const xt = niceTicks(Math.min(...xs, xRef ?? Infinity), Math.max(...xs, xRef ?? -Infinity), 5);
    const yt = niceTicks(Math.min(...ys, yRef ?? Infinity), Math.max(...ys, yRef ?? -Infinity), 4);
    const xStep = xt[1] - xt[0], yStep = yt[1] - yt[0];
    const yl = yt.map(v => fmtTick(v, nfy, yStep));
    const left = Math.max(...yl.map(l => measure(l, FONT(10, 400, t)))) + 10;
    const top = 6, bottom = 20, right = 8;
    const pw = W - left - right, ph = H - top - bottom;
    const X = (v: number) => left + ((v - xt[0]) / ((xt[xt.length - 1] - xt[0]) || 1)) * pw;
    const Y = (v: number) => top + ph - ((v - yt[0]) / ((yt[yt.length - 1] - yt[0]) || 1)) * ph;

    yt.forEach((v, i) => {
        svg("line", { x1: left, x2: left + pw, y1: Y(v), y2: Y(v), stroke: t.grid }, s);
        text(s, left - 6, Y(v) + 3.5, yl[i], { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
    });
    xt.forEach(v => text(s, X(v), H - 5, fmtTick(v, nfx, xStep, true),
        { "text-anchor": "middle", "font-size": 10, fill: t.muted, "font-family": t.font }));
    if (xRef !== null) svg("line", { x1: X(xRef), x2: X(xRef), y1: top, y2: top + ph, stroke: t.target, "stroke-dasharray": "4 3", "stroke-width": 1.2 }, s);
    if (yRef !== null) svg("line", { x1: left, x2: left + pw, y1: Y(yRef), y2: Y(yRef), stroke: t.target, "stroke-dasharray": "4 3", "stroke-width": 1.2 }, s);

    const c = { topLeft: "", topRight: "", bottomLeft: "", bottomRight: "", ...(m.corners || {}) };
    const cs = { "font-size": 11, "font-weight": 600, fill: t.ink, "font-family": t.font };
    if (c.topLeft) text(s, left + 6, top + 13, c.topLeft, cs);
    if (c.topRight) text(s, left + pw - 6, top + 13, c.topRight, { ...cs, "text-anchor": "end" });
    if (c.bottomLeft) text(s, left + 6, top + ph - 6, c.bottomLeft, cs);
    if (c.bottomRight) text(s, left + pw - 6, top + ph - 6, c.bottomRight, { ...cs, "text-anchor": "end" });

    // name the stand-outs: best in the top-right, worst in the bottom-left
    const xr = xRef ?? xs.reduce((a, b) => a + b, 0) / xs.length;
    const yr = yRef ?? ys.reduce((a, b) => a + b, 0) / ys.length;
    const sx = (Math.max(...xs) - Math.min(...xs)) || 1, sy = (Math.max(...ys) - Math.min(...ys)) || 1;
    const score = (p: QuadPoint) => ((p.x as number) - xr) / sx + ((p.y as number) - yr) / sy;
    const named = new Set<QuadPoint>([
        ...pts.filter(p => (p.x as number) > xr && (p.y as number) > yr).sort((a, b) => score(b) - score(a)).slice(0, m.labelTop ?? 2),
        ...pts.filter(p => (p.x as number) < xr && (p.y as number) < yr).sort((a, b) => score(a) - score(b)).slice(0, m.labelBottom ?? 1),
    ]);

    const sizes = pts.map(p => (p.size ?? 0) as number);
    const maxSize = Math.max(...sizes, 0);
    const [rMin, rMax] = pts.length > 60 ? [2.5, 7.5] : pts.length > 20 ? [3.5, 10] : [5, 16];
    const radius = (p: QuadPoint) => (maxSize > 0 ? rMin + (rMax - rMin) * Math.sqrt(Math.max(0, (p.size ?? 0) as number) / maxSize) : rMin + 1.5);
    const names = { x: "X", y: "Y", size: "Size", ...(m.names || {}) };
    const dots = svg("g", {}, s);
    const top_ = svg("g", {}, s);          // named points + labels stay above the crowd
    const placed: { x0: number; x1: number; y0: number; y1: number }[] = [];
    const labelFont = FONT(11, 600, t);
    [...pts].sort((a, b) => radius(b) - radius(a)).forEach(p => {
        const isNamed = named.has(p);
        const cx = X(p.x as number), cy = Y(p.y as number), r = radius(p);
        const g = svg("g", { opacity: dimmed(ia, p.key) ? 0.25 : 1, style: "cursor:pointer" }, isNamed ? top_ : dots);
        svg("circle", { cx, cy, r, fill: isNamed ? t.ink : t.primary, "fill-opacity": isNamed ? 1 : 0.8,
            stroke: "#fff", "stroke-width": 0.8 }, g);
        if (isNamed) {
            const onLeft = cx > left + pw * 0.6;
            const w = measure(p.label, labelFont);
            const lx = onLeft ? cx - r - 4 : cx + r + 4;
            const x0 = onLeft ? lx - w : lx, x1 = onLeft ? lx : lx + w;
            // nudge the label up/down until it doesn't collide with one already placed
            const dy = [0, 13, -13, 26, -26].find(d => !placed.some(b => x0 < b.x1 && x1 > b.x0
                && cy + d - 9 < b.y1 && cy + d + 4 > b.y0)) ?? 0;
            placed.push({ x0, x1, y0: cy + dy - 9, y1: cy + dy + 4 });
            text(g, lx, cy + 4 + dy, p.label, { "text-anchor": onLeft ? "end" : "start",
                "font-size": 11, "font-weight": 600, fill: t.ink, "font-family": t.font,
                stroke: "#fff", "stroke-width": 3, "stroke-linejoin": "round", "paint-order": "stroke" });
        }
        bind(g, ia, p.key, () => {
            const items = [{ name: "", value: p.label }, { name: names.x, value: fmt(p.x, nfx, { signed: nfx.kind === "percent" }) },
                { name: names.y, value: fmt(p.y, nfy) }];
            if (p.size !== null && p.size !== undefined) items.push({ name: names.size, value: fmt(p.size, nfs, { compact: true }) });
            return items;
        });
    });
}
