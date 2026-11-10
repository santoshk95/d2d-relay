/*
 * Drawing helpers shared by the Atlas family visuals: 1-2-5 ticks, a
 * linear value axis with gridlines (either orientation), and the legend
 * (top, bottom, centered or right; wraps, then "+N").
 */
import { el, r1, textW, trunc } from "./look";
import { LegendCard, ValueAxisCard, GridCard, colorOr, val, DASH } from "./cards";
import { axisFormatter } from "./util";
import { Theme } from "./family";
import { Target } from "./interact";

/** round domain and evenly spaced ticks (1, 2, 5 steps) */
export function nice(lo: number, hi: number, count: number): { lo: number; hi: number; ticks: number[] } {
    if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
    if (!(hi > lo)) { const w = Math.abs(lo) * 0.1 || 1; if (lo === 0) hi = 1; else { lo -= w; hi += w; } }
    const span = hi - lo; let step = Math.pow(10, Math.floor(Math.log10(span / Math.max(1, count))));
    const err = span / Math.max(1, count) / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step, ticks: number[] = [];
    for (let i = 0; i < 200; i++) { const v = a + i * step; if (v > b + step * 1e-6) break; ticks.push(Math.abs(v) < step * 1e-9 ? 0 : +v.toPrecision(12)); }
    return { lo: a, hi: b, ticks };
}
/** numbers typed in the Format pane ("1,200", " 50 ") or NaN when empty */
export const parseNum = (s: string) => { const t = String(s || "").replace(/[\s,]/g, ""); return t === "" ? NaN : Number(t); };

export interface Domain { lo: number; hi: number; ticks: number[]; f: (v: number) => string; }
/** value domain from data, the axis card's start/end and a target tick spacing in pixels */
export function domain(lo: number, hi: number, px: number, per: number, va: ValueAxisCard, format: string | undefined, culture: string, zero = true): Domain {
    const uLo = parseNum(va.start.value), uHi = parseNum(va.end.value);
    if (zero) { lo = Math.min(0, lo); hi = Math.max(0, hi); }
    if (isFinite(uLo)) lo = uLo;
    if (isFinite(uHi)) hi = uHi;
    const nt = nice(lo, hi, Math.max(2, Math.min(10, Math.round(px / per))));
    const a = isFinite(uLo) ? uLo : nt.lo, b = isFinite(uHi) && uHi > a ? uHi : Math.max(nt.hi, a + 1e-9);
    const eps = (b - a) * 1e-9, ticks = nt.ticks.filter(t => t >= a - eps && t <= b + eps);
    return { lo: a, hi: b, ticks, f: axisFormatter(format, Number(va.displayUnits.value) || 0, va.decimals.value, ticks, culture) };
}
/** widest tick label, to reserve room for a vertical value axis */
export const tickWidth = (d: Domain, va: ValueAxisCard) => (va.show.value ? Math.max(0, ...d.ticks.map(t => textW(d.f(t), va.fontSize.value))) + 8 : 0);

/** value axis labels and gridlines; vertical: values run up the left edge (x = L), horizontal: along the bottom (y = B) */
export function valueAxis(root: Element, d: Domain, pos: (v: number) => number, box: { L: number; R: number; T: number; B: number }, vertical: boolean, va: ValueAxisCard, gr: GridCard, t: Theme) {
    const g = el("g", { class: "axes" }, root), vfs = Math.max(6, va.fontSize.value), vC = colorOr(va.color, t.axis);
    const gC = colorOr(gr.color, t.grid), dash = DASH[val(gr.style)];
    d.ticks.forEach(v => {
        const p = r1(pos(v)) + 0.5;
        if (gr.show.value) {
            const ln = el("line", vertical ? { x1: r1(box.L), x2: r1(box.R), y1: p, y2: p } : { x1: p, x2: p, y1: r1(box.T), y2: r1(box.B) }, g);
            ln.setAttribute("style", `stroke:${gC};stroke-width:${gr.width.value}px${dash ? ";stroke-dasharray:" + dash : ""}`);
        }
        /* horizontal: the tick at the right edge is right-aligned so it isn't clipped */
        const atEdge = !vertical && pos(v) + textW(d.f(v), vfs) / 2 > box.R + 2;
        if (va.show.value) el("text", vertical ? { x: r1(box.L - 6), y: r1(pos(v) + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: vC, class: "ax" } : { x: r1(atEdge ? box.R + 2 : pos(v)), y: r1(box.B + vfs + 4), "text-anchor": atEdge ? "end" : "middle", "font-size": vfs, fill: vC, class: "ax" }, g, d.f(v));
    });
    return g;
}

export interface LegendItem { key: string; name: string; color: string; on: boolean; target?: Target; shape?: "box" | "line" | "dot"; }
export interface LegendBox { top: number; bottom: number; right: number; draw: (root: Element, bind: (e: Element, t: Target) => void) => void; }
/** lay out the legend and return the space it takes; draw() adds it to the SVG */
export function legend(card: LegendCard, items: LegendItem[], title: string, W: number, H: number, pad: number, t: Theme, show = true): LegendBox {
    const none: LegendBox = { top: 0, bottom: 0, right: 0, draw: () => undefined };
    if (!show || !card.show.value || items.length < 2) return none;
    const lfs = Math.max(6, card.fontSize.value), lpos = val(card.position), rowH = lfs + 9, lgC = colorOr(card.color, t.text);
    const lTitle = card.title.value ? title : "";
    interface LI { it?: LegendItem; text: string; x: number; y: number; w: number; kind: "item" | "title" | "more"; }
    const out: LI[] = [];
    const iw = (s: string) => 13 + textW(s, lfs) + 14;
    let top = 0, bottom = 0, right = 0;
    if (lpos === "right") {
        const lw = Math.min(W * 0.3, Math.max(lTitle ? textW(lTitle, lfs) + 4 : 0, ...items.map(i => iw(trunc(i.name, 150, lfs)) - 10)));
        right = lw + 8; let y = pad + rowH / 2; const x = W - pad - lw;
        if (lTitle) { out.push({ text: trunc(lTitle, lw, lfs), x, y, w: lw, kind: "title" }); y += rowH; }
        for (let k = 0; k < items.length; k++) {
            if (y > H - pad - rowH && k < items.length - 1) { out.push({ text: `+${items.length - k} more`, x, y, w: lw, kind: "more" }); break; }
            out.push({ it: items[k], text: trunc(items[k].name, lw - 14, lfs), x, y, w: lw, kind: "item" }); y += rowH;
        }
    } else {
        const atTop = lpos.startsWith("top"), center = lpos.endsWith("Center"), avail = W - 2 * pad;
        const rows: LI[][] = [[]]; let x = 0, full = false;
        const push = (li: LI) => {
            if (x + li.w > avail && rows[rows.length - 1].length) { if (rows.length >= 2) return false; rows.push([]); x = 0; }
            li.x = x; rows[rows.length - 1].push(li); x += li.w; return true;
        };
        if (lTitle) push({ text: lTitle, x: 0, y: 0, w: textW(lTitle, lfs) + 10, kind: "title" });
        for (let k = 0; k < items.length && !full; k++) {
            const s = trunc(items[k].name, 160, lfs);
            if (!push({ it: items[k], text: s, x: 0, y: 0, w: iw(s), kind: "item" })) { rows[rows.length - 1].push({ text: `+${items.length - k}`, x, y: 0, w: 30, kind: "more" }); full = true; }
        }
        const h = rows.length * rowH, y0 = atTop ? pad + rowH / 2 : H - pad - h + rowH / 2;
        rows.forEach((r, ri) => {
            const rw = r.length ? r[r.length - 1].x + r[r.length - 1].w - 14 : 0, off = center ? Math.max(0, (avail - rw) / 2) : 0;
            r.forEach(li => { li.x += pad + off; li.y = y0 + ri * rowH; out.push(li); });
        });
        if (atTop) top = h + 4; else bottom = h + 4;
    }
    return {
        top, bottom, right,
        draw: (root, bind) => {
            const lg = el("g", { class: "legend" }, root);
            out.forEach(li => {
                if (li.kind !== "item" || !li.it) { el("text", { x: r1(li.x), y: r1(li.y + lfs * 0.35), "font-size": lfs, fill: lgC, class: li.kind === "title" ? "lgt" : "ax" }, lg, li.text); return; }
                const it = li.it, g = el("g", { class: "lg" + (it.on ? "" : " dim") }, lg);
                el("rect", { class: "hit", x: r1(li.x - 2), y: r1(li.y - rowH / 2 + 1), width: r1(Math.min(li.w - 4, textW(li.text, lfs) + 18)), height: rowH - 2, rx: 4, fill: "transparent", stroke: "none" }, g);
                if (it.shape === "line") el("rect", { x: r1(li.x), y: r1(li.y - 1.5), width: 10, height: 3, rx: 1.5, fill: it.color }, g);
                else if (it.shape === "dot") el("circle", { cx: r1(li.x + 5), cy: r1(li.y), r: 4.5, fill: it.color }, g);
                else el("rect", { x: r1(li.x), y: r1(li.y - 5), width: 10, height: 10, rx: 2.5, fill: it.color }, g);
                el("text", { x: r1(li.x + 14), y: r1(li.y + lfs * 0.35), "font-size": lfs, fill: lgC, class: "ax" }, g, li.text);
                if (it.target) bind(g, it.target);
            });
        }
    };
}
