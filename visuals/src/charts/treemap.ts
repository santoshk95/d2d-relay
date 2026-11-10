// Treemap: squarified layout, colour = second measure on a gradient, two-line labels.
import { svg, text, measure, fit, ramp, isDark } from "../dom";
import { parseFormat, fmt } from "../format";
import { Tokens, Header, Interactions, frame, emptyState, FONT, bind, dimmed } from "../theme";

export interface TreeItem {
    label: string;
    size: number | null;
    color?: number | null;
    key?: unknown;
}

export interface TreemapModel {
    items: TreeItem[];
    sizeFormat?: string;
    colorFormat?: string;
    names?: { size?: string; color?: string };
}

interface Rect { x: number; y: number; w: number; h: number; item: TreeItem; }

/** Squarified treemap (Bruls, Huizing, van Wijk). */
function squarify(items: TreeItem[], x: number, y: number, w: number, h: number): Rect[] {
    const total = items.reduce((a, it) => a + (it.size as number), 0);
    const scale = (w * h) / (total || 1);
    const areas = items.map(it => ({ item: it, a: (it.size as number) * scale }));
    const out: Rect[] = [];
    let rx = x, ry = y, rw = w, rh = h;
    let row: { item: TreeItem; a: number }[] = [];
    const worst = (r: { a: number }[], side: number) => {
        const sum = r.reduce((s, v) => s + v.a, 0);
        const mx = Math.max(...r.map(v => v.a)), mn = Math.min(...r.map(v => v.a));
        return Math.max((side * side * mx) / (sum * sum), (sum * sum) / (side * side * mn));
    };
    const layout = (r: { item: TreeItem; a: number }[]) => {
        const sum = r.reduce((s, v) => s + v.a, 0);
        if (rw >= rh) {
            const cw = sum / rh;
            let cy = ry;
            for (const v of r) { const ch = v.a / cw; out.push({ x: rx, y: cy, w: cw, h: ch, item: v.item }); cy += ch; }
            rx += cw; rw -= cw;
        } else {
            const ch = sum / rw;
            let cx = rx;
            for (const v of r) { const cw = v.a / ch; out.push({ x: cx, y: ry, w: cw, h: ch, item: v.item }); cx += cw; }
            ry += ch; rh -= ch;
        }
    };
    for (const v of areas) {
        const side = Math.min(rw, rh);
        if (!row.length || worst([...row, v], side) <= worst(row, side)) row.push(v);
        else { layout(row); row = [v]; }
    }
    if (row.length) layout(row);
    return out;
}

export function renderTreemap(root: HTMLElement, m: TreemapModel, t: Tokens, header: Header, ia: Interactions = {}): void {
    const items = m.items.filter(i => i.size !== null && (i.size as number) > 0).sort((a, b) => (b.size as number) - (a.size as number));
    if (!items.length) {
        emptyState(root, t, "Add a category and a size measure");
        return;
    }
    const f = frame(root, t, header, "gb-treemap");
    const nfs = parseFormat(m.sizeFormat), nfc = parseFormat(m.colorFormat);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => ia.clear?.());

    const colors = items.map(i => i.color).filter(v => v !== null && v !== undefined) as number[];
    const hasColor = colors.length > 0;
    const lo = hasColor ? Math.min(...colors) : 0, hi = hasColor ? Math.max(...colors) : 1;
    const stops = [t.primaryLight, t.primary, t.primaryDark];
    const legendH = hasColor ? 18 : 0;
    if (hasColor) {
        const loT = fmt(lo, nfc, { decimals: 0 }), hiT = fmt(hi, nfc, { decimals: 0 });
        const hiW = measure(hiT, FONT(10, 400, t));
        const bx = W - hiW - 6 - 70;
        text(s, bx - 5, 10, loT, { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
        const grad = svg("linearGradient", { id: `gbtm${Math.random().toString(36).slice(2, 8)}` }, svg("defs", {}, s));
        stops.forEach((c, i) => svg("stop", { offset: `${(i / (stops.length - 1)) * 100}%`, "stop-color": c }, grad));
        svg("rect", { x: bx, y: 4, width: 70, height: 7, rx: 3.5, fill: `url(#${grad.getAttribute("id")})` }, s);
        text(s, W - hiW, 10, hiT, { "font-size": 10, fill: t.muted, "font-family": t.font });
    }

    const rects = squarify(items, 0, legendH, W, H - legendH);
    const names = { size: "Value", color: "Colour", ...(m.names || {}) };
    for (const r of rects) {
        const it = r.item;
        const fill = hasColor && it.color !== null && it.color !== undefined
            ? ramp(stops, ((it.color as number) - lo) / ((hi - lo) || 1)) : t.primary;
        const g = svg("g", { opacity: dimmed(ia, it.key) ? 0.3 : 1, style: "cursor:pointer" }, s);
        svg("rect", { x: r.x + 1, y: r.y + 1, width: Math.max(0, r.w - 2), height: Math.max(0, r.h - 2), rx: 2, fill }, g);
        const ink = isDark(fill) ? "#FFFFFF" : t.ink;
        const nameFont = FONT(12, 700, t), subFont = FONT(10.5, 400, t);
        if (r.w > 36 && r.h > 20) {
            text(g, r.x + 7, r.y + 17, fit(it.label, nameFont, r.w - 12), { "font-size": 12, "font-weight": 700, fill: ink, "font-family": t.font });
            if (r.h > 36) {
                const line = hasColor && it.color !== null && it.color !== undefined
                    ? `${fmt(it.size, nfs, { compact: true })} · ${fmt(it.color, nfc)}` : fmt(it.size, nfs, { compact: true });
                const shown = measure(line, subFont) <= r.w - 12 ? line
                    : hasColor && it.color !== null && it.color !== undefined ? fmt(it.color, nfc) : "";
                if (shown) text(g, r.x + 7, r.y + 31, shown, { "font-size": 10.5, fill: ink, opacity: 0.92, "font-family": t.font });
            }
        }
        bind(g, ia, it.key, () => {
            const tip = [{ name: "", value: it.label }, { name: names.size, value: fmt(it.size, nfs, { compact: true }) }];
            if (hasColor) tip.push({ name: names.color, value: fmt(it.color, nfc) });
            return tip;
        });
    }
}
