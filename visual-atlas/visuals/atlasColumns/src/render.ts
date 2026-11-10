/*
 * Drawing for Atlas Columns: gridlines and value axis, bars in flat,
 * soft and 3D looks, data and total labels, category labels (with
 * hierarchy tiers when a hierarchy is expanded), legend and reference
 * line. When categories do not fit, the bars and category labels sit in
 * a scrolling layer while the value axis stays put.
 */
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { Model, Pt, Ser } from "./model";
import { ColumnsSettings } from "./settings";
import { Mode, stackUp, nice, refValue, parseNum } from "./layout";
import { Look, el, r1, textW, trunc } from "./common/look";
import { mix, inkOn, isHex, normHex } from "./common/color";
import { labelFormatter, axisFormatter } from "./common/util";

export interface Layers {
    back: SVGGElement;          /* gridlines, value axis, titles */
    scroller: HTMLDivElement;   /* scrolls when categories overflow */
    front: SVGSVGElement;       /* bars, labels and category axis, inside the scroller */
    frontG: SVGGElement;
    over: SVGGElement;          /* legend and reference line, above the bars */
}
export interface Env {
    W: number; H: number; m: Model; s: ColumnsSettings; look: Look; L: Layers;
    ink: string; surface: string; hc: boolean; culture: string; drillButtons: boolean;
    colorOf: (p: Pt) => string;
    isSelected: (p: Pt) => boolean; anySelected: boolean;
    seriesDim: (s: Ser) => boolean;
    bindPoint: (e: SVGElement, p: Pt) => void;
    bindSeries: (e: SVGElement, s: Ser) => void;
    /** a category label: clicking it selects the whole category (returns the label) */
    bindCat: (e: SVGElement, ci: number) => SVGElement;
}
export interface Drawn { mode: Mode; horiz: boolean; labelOf: (p: Pt) => string; pct: (v: number) => string; }

const DASH: Record<string, string | null> = { solid: null, dashed: "5 4", dotted: "1.5 3" };
const HC_DASH = [null, "5 3", "1.5 2.5", "8 3 2 3", "3 3"];
type Side = "top" | "bottom" | "left" | "right";

/** rectangle path with its own radius on the data end and on the base end */
function rpath(x: number, y: number, w: number, h: number, rEnd: number, rBase: number, end: Side): string {
    const cap = Math.min(w, h) / 2, e = Math.min(rEnd, cap), b = Math.min(rBase, cap);
    const [tl, tr, br, bl] = end === "top" ? [e, e, b, b] : end === "bottom" ? [b, b, e, e] : end === "right" ? [b, e, e, b] : [e, b, b, e];
    const A = (r: number, x2: number, y2: number) => (r > 0.05 ? `A${r1(r)},${r1(r)} 0 0 1 ${r1(x2)},${r1(y2)}` : `L${r1(x2)},${r1(y2)}`);
    return `M${r1(x + tl)},${r1(y)}H${r1(x + w - tr)}${A(tr, x + w, y + tr)}V${r1(y + h - br)}${A(br, x + w - br, y + h)}H${r1(x + bl)}${A(bl, x, y + h - bl)}V${r1(y + tl)}${A(tl, x + tl, y)}Z`;
}
/** split a label into at most two lines that fit a width, or null */
function wrap2(t: string, w: number, size: number): string[] | null {
    if (textW(t, size) <= w) return [t];
    const words = t.split(/\s+/); if (words.length < 2) return null;
    let a = ""; let i = 0;
    for (; i < words.length; i++) { const next = a ? a + " " + words[i] : words[i]; if (textW(next, size) > w) break; a = next; }
    const b = words.slice(i).join(" ");
    return a && textW(b, size) <= w ? [a, b] : null;
}
const colorOr = (c: fs.ColorPicker, fallback: string) => { const v = c.value && c.value.value; return v && isHex(v) ? normHex(v) : fallback; };

export function render(e: Env): Drawn {
    const { W, H, m, s, look, L } = e;
    const type = String(s.chart.chartType.value.value), horiz = type.endsWith("Bar");
    const mode: Mode = type.startsWith("clustered") ? "clustered" : type.startsWith("stacked") ? "stacked" : "percent";
    const st = stackUp(m, mode), pad = 6, ink = e.ink, surf = e.surface;
    const C = s.chart, LB = s.labels, TT = s.totals, CA = s.categoryAxis, VA = s.valueAxis, GR = s.gridlines, LG = s.legend, RL = s.refLine;
    const textC = mix(ink, surf, 0.14), axisC = mix(ink, surf, 0.4);

    /* ---------- options ---------- */
    const shapeSel = look.is3d ? "square" : String(C.shape.value.value);
    const lolli = shapeSel === "lollipop" && mode === "clustered";
    const shape = shapeSel === "lollipop" && !lolli ? "rounded" : shapeSel;
    const radius = Math.max(0, C.radius.value), spacing = Math.min(0.9, Math.max(0, C.spacing.value / 100));
    let gap = Math.max(0, C.groupGap.value);
    const lbShow = LB.show.value, lbfs = Math.max(6, LB.fontSize.value), pos0 = String(LB.position.value.value);
    const lbPos = pos0 === "auto" ? (mode === "clustered" ? "outsideEnd" : "insideCenter") : (mode !== "clustered" && pos0 === "outsideEnd" ? "insideEnd" : pos0);
    const ttShow = TT.show.value && mode === "stacked", ttfs = Math.max(6, TT.fontSize.value);
    const hasCat = m.levelNames.length > 0, cShow = CA.show.value && hasCat, cfs = Math.max(6, CA.fontSize.value);
    const vShow = VA.show.value, vfs = Math.max(6, VA.fontSize.value);
    const lblC = colorOr(LB.color, ""), totC = colorOr(TT.color, textC), cC = colorOr(CA.color, axisC), vC = colorOr(VA.color, axisC);
    const gC = colorOr(GR.color, mix(ink, surf, 0.88)), lgC = colorOr(LG.color, textC);

    /* ---------- number formats ---------- */
    const dec = LB.decimals.value;
    const fmtL = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, dec, st.maxAbs, e.culture);
    const pct = (v: number) => (v * 100).toFixed(dec >= 0 ? Math.min(dec, 4) : Math.abs(v) < 0.1 ? 1 : 0) + "%";
    const content = String(LB.content.value.value);
    const labelOf = (p: Pt) => (content === "percent" ? pct(p.share || 0) : content === "both" ? `${fmtL(p.v)} (${pct(p.share || 0)})` : fmtL(p.v));

    /* ---------- value domain ---------- */
    let lo = st.lo, hi = st.hi;
    const refV = RL.show.value && mode !== "percent" ? refValue(String(RL.kind.value.value), RL.value.value, st, mode, m) : null;
    if (refV !== null && isFinite(refV)) { lo = Math.min(lo, refV); hi = Math.max(hi, refV); }
    const uLo = mode === "percent" ? NaN : parseNum(VA.start.value), uHi = mode === "percent" ? NaN : parseNum(VA.end.value);
    if (isFinite(uLo)) lo = uLo;
    if (isFinite(uHi)) hi = uHi;
    const nt = nice(lo, hi, Math.max(2, Math.min(10, Math.round((horiz ? W * 0.6 : H * 0.62) / (horiz ? 85 : 44)))));
    if (!isFinite(uLo)) lo = nt.lo;
    if (!isFinite(uHi)) hi = nt.hi;
    if (!(hi > lo)) hi = lo + 1;
    const eps = (hi - lo) * 1e-9, ticks = nt.ticks.filter(t => t >= lo - eps && t <= hi + eps);
    const fmtA = mode === "percent" ? (v: number) => Math.round(v * 100) + "%" : axisFormatter(m.format, Number(VA.displayUnits.value) || 0, VA.decimals.value, ticks, e.culture);
    const tickText = ticks.map(t => fmtA(t)), vLabW = vShow ? Math.max(0, ...tickText.map(t => textW(t, vfs))) : 0;
    const vTitle = VA.title.value ? m.valueNames.join(", ") : "", cTitle = CA.title.value && hasCat ? m.levelNames.join(" › ") : "";

    /* ---------- category labels and hierarchy runs ---------- */
    const n = m.cats.length, concat = CA.concatenate.value || m.levels < 2;
    const leaf = m.cats.map(c => (concat ? c.path.filter(x => x !== "").join(" ") : c.label));
    const tiers = concat ? 0 : m.levels - 1;
    const runs: { i0: number; i1: number; label: string }[][] = [];
    for (let t = 0; t < tiers; t++) {
        const list: { i0: number; i1: number; label: string }[] = []; let start = 0;
        const same = (i: number, j: number) => { for (let k = 0; k <= t; k++) if (m.cats[i].path[k] !== m.cats[j].path[k]) return false; return true; };
        for (let i = 1; i <= n; i++) if (i === n || !same(i, start)) { list.push({ i0: start, i1: i - 1, label: m.cats[start].path[t] }); start = i; }
        runs.push(list);
    }

    /* ---------- legend ---------- */
    const showLegend = LG.show.value && m.series.length > 1, lfs = Math.max(6, LG.fontSize.value), lpos = String(LG.position.value.value);
    const lTitle = showLegend && LG.title.value && m.legendTitle ? m.legendTitle : "";
    const drillW = e.drillButtons ? 86 : 0, drillH = e.drillButtons ? 30 : 0, rowH = lfs + 9;
    interface LI { ser?: Ser; text: string; x: number; y: number; w: number; kind: "item" | "title" | "more"; }
    const lItems: LI[] = [];
    let lgTop = 0, lgBottom = 0, lgRight = 0;
    if (showLegend) {
        const iw = (t: string) => 13 + textW(t, lfs) + 14;
        const its = m.series.map(sr => ({ ser: sr, text: trunc(sr.name, 160, lfs) }));
        if (lpos === "right") {
            const lw = Math.min(W * 0.3, Math.max(lTitle ? textW(lTitle, lfs) * 1.06 + 4 : 0, ...its.map(it => iw(it.text) - 10)));
            lgRight = lw + 8;
            const x = W - pad - lw; let y = pad + drillH + rowH / 2;
            if (lTitle) { lItems.push({ text: trunc(lTitle, lw, lfs), x, y, w: lw, kind: "title" }); y += rowH; }
            for (let k = 0; k < its.length; k++) {
                if (y > H - pad - rowH && k < its.length - 1) { lItems.push({ text: `+${its.length - k} more`, x, y, w: lw, kind: "more" }); break; }
                lItems.push({ ser: its[k].ser, text: trunc(its[k].text, lw - 14, lfs), x, y, w: lw, kind: "item" }); y += rowH;
            }
        } else {
            const top = lpos.startsWith("top"), center = lpos.endsWith("Center"), avail = W - 2 * pad - (top ? drillW : 0);
            const rows: LI[][] = [[]]; let x = 0, full = false;
            const push = (li: LI) => {
                if (x + li.w > avail && rows[rows.length - 1].length) { if (rows.length >= 3) return false; rows.push([]); x = 0; }
                li.x = x; rows[rows.length - 1].push(li); x += li.w; return true;
            };
            if (lTitle) push({ text: lTitle, x: 0, y: 0, w: textW(lTitle, lfs) * 1.06 + 10, kind: "title" });
            for (let k = 0; k < its.length && !full; k++) {
                if (!push({ ser: its[k].ser, text: its[k].text, x: 0, y: 0, w: iw(its[k].text), kind: "item" })) {
                    const row = rows[rows.length - 1]; row.push({ text: `+${its.length - k}`, x, y: 0, w: 30, kind: "more" }); full = true;
                }
            }
            const h = rows.length * rowH, y0 = top ? pad + rowH / 2 : H - pad - h + rowH / 2;
            rows.forEach((r, ri) => {
                const rw = r.length ? r[r.length - 1].x + r[r.length - 1].w - 14 : 0, off = center ? Math.max(0, (avail - rw) / 2) : 0;
                r.forEach(li => { li.x += pad + off; li.y = y0 + ri * rowH; lItems.push(li); });
            });
            if (top) lgTop = h + 4; else lgBottom = h + 4;
        }
    }
    const topBand = Math.max(lgTop, drillH), D3 = look.is3d ? 8 : 0, D3y = D3 * 0.6;

    /* ---------- layout ---------- */
    const maxArea = Math.max(0.1, CA.maxSize.value / 100);
    const outside = (lbShow && lbPos === "outsideEnd") || ttShow;
    const outTexts = (lbShow && lbPos === "outsideEnd" ? m.pts.map(labelOf).map(t => textW(t, lbfs)) : []).concat(ttShow ? st.totals.map(t => textW(fmtL(t.net), ttfs) * 1.05) : []);
    let plotL: number, plotR: number, plotT: number, plotB: number, step: number, scroll: boolean;
    let catMode = "none", catH = 0, rotLen = 0, skip = 1, leafW = 0, catAxisH = 0, inset = 0;
    let wraps: (string[] | null)[] = [];
    const tierWs: number[] = [];
    let V: (v: number) => number;
    const clampV = (v: number) => Math.max(lo, Math.min(hi, v));
    let sx: number, sy: number, sw: number, sh: number, cw: number, ch: number;
    if (!horiz) {
        plotL = pad + (vTitle ? vfs + 8 : 0) + (vShow ? vLabW + 8 : 0);
        plotR = W - pad - lgRight - D3 - 2;
        const plotW = Math.max(10, plotR - plotL), minStep = cShow ? Math.max(cfs + 3, 10) : 5;
        scroll = n * minStep > plotW + 0.5; const cLen = scroll ? n * minStep : plotW; step = cLen / n;
        if (cShow) {
            const maxLeaf = Math.max(0, ...leaf.map(t => textW(t, cfs)));
            if (maxLeaf + 6 <= step) { catMode = "flat"; catH = cfs + 8; }
            else if ((wraps = leaf.map(t => wrap2(t, step - 6, cfs))).every(w => w !== null)) { catMode = "wrap"; catH = cfs * 2.3 + 8; }
            else { catMode = "rot"; skip = Math.max(1, Math.ceil(cfs * 1.2 / (step * 0.7071))); rotLen = Math.min(maxLeaf, Math.max(24, (H * maxArea - cfs) / 0.7071)); catH = rotLen * 0.7071 + cfs + 6; }
        }
        catAxisH = cShow ? catH + tiers * (cfs + 10) : 0;
        plotT = pad + topBand + D3y + 2;
        plotB = H - pad - lgBottom - catAxisH - (cTitle ? cfs + 8 : 0) - (scroll ? 12 : 0);
        if (plotB - plotT < 20) plotB = plotT + 20;
        const head = outside ? Math.max(lbShow ? lbfs : 0, ttShow ? ttfs : 0) + 6 : 0, foot = st.anyNeg ? head : 0;
        const yb = plotB - foot, yt = plotT + head;
        V = v => yb - (clampV(v) - lo) / (hi - lo) * (yb - yt);
        const first = catMode === "rot" ? Math.min(rotLen, textW(leaf[0] || "", cfs)) * 0.7071 + cfs * 0.6 - step / 2 : 0;
        inset = scroll ? Math.max(0, first) : 0;
        sx = scroll ? plotL : pad; sy = plotT - D3y - 4; sw = (scroll ? plotW : plotR - pad) + D3 + 4; sh = plotB - sy + catAxisH + (scroll ? 12 : 0);
        cw = (scroll ? inset + cLen : sw - D3 - 4) + D3 + 4; ch = sh - (scroll ? 12 : 0);
    } else {
        const maxLeaf = cShow ? Math.max(0, ...leaf.map(t => textW(t, cfs))) : 0;
        leafW = cShow ? Math.min(maxLeaf, W * maxArea) + 8 : 0;
        runs.forEach(list => tierWs.push(cShow ? Math.min(W * 0.2, Math.max(...list.map(r => textW(r.label, cfs)))) + 14 : 0));
        plotL = pad + (cTitle ? cfs + 8 : 0) + tierWs.reduce((a, b) => a + b, 0) + leafW;
        const outW = outside ? Math.max(0, ...outTexts) + 8 : 0, outR = outW, outL = st.anyNeg ? outW : 0;
        plotT = pad + topBand + D3y + 2;
        plotB = H - pad - lgBottom - (vShow ? vfs + 8 : 0) - (vTitle ? vfs + 8 : 0);
        if (plotB - plotT < 20) plotB = plotT + 20;
        const plotH = plotB - plotT, minStep = cShow ? Math.max(cfs * 1.25, 8) : 4;
        scroll = n * minStep > plotH + 0.5; const cLen = scroll ? n * minStep : plotH; step = cLen / n;
        skip = cShow ? Math.max(1, Math.ceil(cfs * 1.1 / step)) : 1;
        plotR = W - pad - lgRight - D3 - 2 - (scroll ? 12 : 0);
        const xl = plotL + outL, xr = Math.max(xl + 10, plotR - outR);
        V = v => xl + (clampV(v) - lo) / (hi - lo) * (xr - xl);
        sx = pad; sy = plotT - D3y - 4; sw = W - pad - lgRight - sx; sh = plotB - sy;
        cw = sw - (scroll ? 12 : 0); ch = cLen + D3y + 4;
    }
    const ox = sx, oy = sy;
    const catStart = horiz ? plotT - oy : plotL - ox + inset;
    const cs = (i: number) => catStart + i * step;
    const Vc = (v: number) => (horiz ? V(v) - ox : V(v) - oy);

    /* ---------- scroller ---------- */
    const sc = L.scroller;
    sc.style.left = r1(sx) + "px"; sc.style.top = r1(sy) + "px"; sc.style.width = r1(Math.max(1, sw)) + "px"; sc.style.height = r1(Math.max(1, sh)) + "px";
    sc.style.overflowX = scroll && !horiz ? "auto" : "hidden"; sc.style.overflowY = scroll && horiz ? "auto" : "hidden";
    sc.classList.toggle("scrolling", scroll);
    L.front.setAttribute("width", String(r1(Math.max(1, cw)))); L.front.setAttribute("height", String(r1(Math.max(1, ch))));

    /* ---------- back: gridlines, value axis, titles ---------- */
    const B = L.back, gw = Math.max(0, GR.width.value), dash = DASH[String(GR.style.value.value)] || null;
    const gx0 = horiz ? 0 : plotL, gx1 = horiz ? 0 : plotR + D3 * 0.5;
    ticks.forEach((t, i) => {
        const p = V(t);
        if (GR.show.value && gw > 0 && Math.abs(t) > eps) {
            if (horiz) el("line", { x1: r1(p), x2: r1(p), y1: r1(plotT - D3y), y2: r1(plotB), stroke: gC, "stroke-width": gw, "stroke-dasharray": dash, "stroke-linecap": "round" }, B);
            else el("line", { x1: r1(gx0), x2: r1(gx1), y1: r1(p), y2: r1(p), stroke: gC, "stroke-width": gw, "stroke-dasharray": dash, "stroke-linecap": "round" }, B);
        }
        if (vShow) {
            if (horiz) el("text", { x: r1(p), y: r1(plotB + 4 + vfs), "text-anchor": "middle", fill: vC, "font-size": vfs, class: "ax" }, B, tickText[i]);
            else el("text", { x: r1(plotL - 8), y: r1(p + vfs * 0.35), "text-anchor": "end", fill: vC, "font-size": vfs, class: "ax" }, B, tickText[i]);
        }
    });
    if (lo <= 0 && hi >= 0) {
        const z = V(0), zc = mix(ink, surf, 0.62);
        if (horiz) el("line", { x1: r1(z), x2: r1(z), y1: r1(plotT - 2), y2: r1(plotB), stroke: zc, "stroke-width": 1 }, B);
        else el("line", { x1: r1(plotL), x2: r1(plotR), y1: r1(z), y2: r1(z), stroke: zc, "stroke-width": 1 }, B);
    }
    if (vTitle) {
        if (horiz) el("text", { x: r1((plotL + plotR) / 2), y: r1(H - pad - lgBottom - 3), "text-anchor": "middle", fill: vC, "font-size": vfs, class: "ttl" }, B, trunc(vTitle, plotR - plotL, vfs));
        else { const cy = (plotT + plotB) / 2, x = pad + vfs * 0.85; el("text", { x: r1(x), y: r1(cy), "text-anchor": "middle", fill: vC, "font-size": vfs, class: "ttl", transform: `rotate(-90 ${r1(x)} ${r1(cy)})` }, B, trunc(vTitle, plotB - plotT, vfs)); }
    }
    if (cTitle) {
        if (horiz) { const cy = (plotT + plotB) / 2, x = pad + cfs * 0.85; el("text", { x: r1(x), y: r1(cy), "text-anchor": "middle", fill: cC, "font-size": cfs, class: "ttl", transform: `rotate(-90 ${r1(x)} ${r1(cy)})` }, B, trunc(cTitle, plotB - plotT, cfs)); }
        else el("text", { x: r1((plotL + plotR) / 2), y: r1(plotB + catAxisH + (scroll ? 12 : 0) + cfs + 3), "text-anchor": "middle", fill: cC, "font-size": cfs, class: "ttl" }, B, trunc(cTitle, plotR - plotL, cfs));
    }

    /* ---------- bars ---------- */
    const F = L.frontG, S = m.series.length;
    const bw = Math.max(1, step * (1 - spacing));
    if (mode === "clustered" && bw - (S - 1) * gap < S) gap = 0;
    const slot = mode === "clustered" ? Math.max(1, (bw - (S - 1) * gap) / S) : bw;
    const catPos = (p: Pt) => cs(p.c) + (step - bw) / 2 + (mode === "clustered" ? p.s * (slot + gap) : 0);
    const ext = el("g", { class: "ext" }, F), fronts = el("g", { class: "bars" }, F);
    const shf = look.shadow(); if (shf) { fronts.setAttribute("filter", shf); if (look.is3d) ext.setAttribute("filter", shf); }
    const lbls = el("g", { class: "lbls" }, F);
    const dirFill = horiz ? "h" : "v";
    const ends = (p: Pt, a: number, b: number): [number, number] => {
        let pa = Vc(a), pb = Vc(b); const d = Math.sign(pb - pa) || (horiz ? 1 : -1);
        if (mode !== "clustered") { if (!p.base) pa += d * gap / 2; if (!p.outer) pb -= d * gap / 2; if ((pb - pa) * d < 0.6) pb = pa + d * 0.6; }
        return [pa, pb];
    };
    const rectOf = (pos: number, thick: number, pa: number, pb: number) => horiz
        ? { x: Math.min(pa, pb), y: pos, w: Math.abs(pb - pa), h: thick }
        : { x: pos, y: Math.min(pa, pb), w: thick, h: Math.abs(pb - pa) };
    const sideOf = (pa: number, pb: number): Side => (horiz ? (pb >= pa ? "right" : "left") : (pb <= pa ? "top" : "bottom"));
    const exts: { p: Pt; x: number; y: number; w: number; h: number; color: string; cls: string }[] = [];
    const hcStyle = (p: Pt) => (e.hc ? { stroke: ink, "stroke-width": 1.5, "stroke-dasharray": HC_DASH[p.s % HC_DASH.length] } : {});
    const ariaOf = (p: Pt) => `${m.cats[p.c].path.filter(x => x !== "").join(" ")}${m.cats[p.c].path.join("") ? ", " : ""}${m.series[p.s].name}: ${fmtL(p.v)}`;

    const drawMark = (p: Pt, a: number, b: number, color: string, cls: string, roundOk: boolean): SVGElement | null => {
        const pos = catPos(p), [pa, pb] = ends(p, a, b);
        if (lolli) {
            const c = pos + slot / 2, headR = Math.max(3, Math.min(slot / 2, 7)), g = el("g", { class: cls }, fronts);
            const sw2 = Math.max(1.2, Math.min(2.5, slot * 0.4));
            if (horiz) el("line", { x1: r1(pa), x2: r1(pb), y1: r1(c), y2: r1(c), stroke: e.hc ? ink : color, "stroke-width": sw2 }, g);
            else el("line", { x1: r1(c), x2: r1(c), y1: r1(pa), y2: r1(pb), stroke: e.hc ? ink : color, "stroke-width": sw2 }, g);
            el("circle", { cx: r1(horiz ? pb : c), cy: r1(horiz ? c : pb), r: r1(headR), fill: e.hc ? surf : look.fill(color, "r"), stroke: e.hc ? ink : surf, "stroke-width": e.hc ? 1.5 : 1.2 }, g);
            return g;
        }
        const r = rectOf(pos, slot, pa, pb);
        if (look.is3d) {
            exts.push({ p, x: r.x, y: r.y, w: r.w, h: r.h, color, cls });
            return el("rect", { x: r1(r.x), y: r1(r.y), width: r1(Math.max(0.5, r.w)), height: r1(Math.max(0.5, r.h)), fill: e.hc ? surf : look.fill(color, dirFill), class: cls, ...hcStyle(p) }, fronts);
        }
        const thick = slot, end = sideOf(pa, pb);
        const rEnd = !roundOk ? 0 : shape === "rounded" ? (p.outer ? radius : 0) : shape === "pill" ? (p.outer ? thick / 2 : 0) : 0;
        const rBase = shape === "pill" && p.base ? thick / 2 : 0;
        return el("path", { d: rpath(r.x, r.y, Math.max(0.5, r.w), Math.max(0.5, r.h), rEnd, rBase, end), fill: e.hc ? surf : look.fill(color, dirFill), class: cls, ...hcStyle(p) }, fronts);
    };
    m.pts.forEach(p => {
        if (p.a === undefined || p.b === undefined || (p.a === p.b && !lolli)) return;
        const color = e.colorOf(p), dim = e.anySelected && !e.isSelected(p);
        if (m.highlights) {
            const ghost = drawMark(p, p.a, p.b, color, "bar ghost", true);
            if (ghost) e.bindPoint(ghost, p);
            if (p.hl && p.ha !== undefined && p.hb !== undefined && p.ha !== p.hb) {
                const hm = drawMark(p, p.ha, p.hb, color, "bar" + (dim ? " dim" : ""), Math.abs(p.hb - p.b) < 1e-9);
                if (hm) e.bindPoint(hm, p);
            }
            return;
        }
        const mk = drawMark(p, p.a, p.b, color, "bar" + (dim ? " dim" : ""), true);
        if (mk) { mk.setAttribute("aria-label", ariaOf(p)); e.bindPoint(mk, p); }
    });
    /* 3D: side and top faces first (lowest and leftmost first), front faces stay on top */
    if (look.is3d && exts.length) {
        exts.sort((a, b) => (b.y + b.h) - (a.y + a.h) || a.x - b.x);
        exts.forEach(x => {
            const thick = horiz ? x.h : x.w, dep = Math.min(D3, Math.max(3, thick * 0.35)), dy = dep * 0.6;
            const g = el("g", { class: x.cls }, ext);
            el("path", { d: `M${r1(x.x + x.w)},${r1(x.y)}l${r1(dep)},${r1(-dy)}v${r1(x.h)}l${r1(-dep)},${r1(dy)}Z`, fill: e.hc ? surf : look.side(x.color), ...hcStyle(x.p) }, g);
            el("path", { d: `M${r1(x.x)},${r1(x.y)}l${r1(dep)},${r1(-dy)}h${r1(x.w)}l${r1(-dep)},${r1(dy)}Z`, fill: e.hc ? surf : look.top(x.color), ...hcStyle(x.p) }, g);
            e.bindPoint(g, x.p);
        });
    }

    /* ---------- data labels ---------- */
    if (lbShow) m.pts.forEach(p => {
        if (p.a === undefined || p.b === undefined || (p.a === p.b && !lolli)) return;
        const t = labelOf(p); if (!t) return;
        const tw = textW(t, lbfs), along = horiz ? tw : lbfs * 1.05, across = horiz ? lbfs * 1.05 : tw;
        let where = lbPos;
        const room = where === "outsideEnd" ? (S === 1 && !horiz ? step - 3 : slot + gap + 2) : slot - 2;
        if (across > room) return;
        const [pa, pb] = ends(p, p.a, p.b), d = Math.sign(pb - pa) || (horiz ? 1 : -1), len = Math.abs(pb - pa);
        if (where !== "outsideEnd" && (len < along + 4 || lolli)) { if (mode === "clustered") where = "outsideEnd"; else return; }
        const headR = lolli ? Math.max(3, Math.min(slot / 2, 7)) : 0;
        const extra = look.is3d && ((horiz && d > 0) || (!horiz && d < 0)) ? D3 * (horiz ? 1 : 0.6) : 0;
        const c = where === "insideEnd" ? pb - d * (along / 2 + 3) : where === "insideCenter" ? (pa + pb) / 2 : where === "insideBase" ? pa + d * (along / 2 + 3) : pb + d * (along / 2 + 3 + headR + extra);
        const inside = where !== "outsideEnd", mid = catPos(p) + slot / 2;
        const fill = inside ? (lblC && !e.hc ? lblC : e.hc ? ink : inkOn(e.colorOf(p))) : lblC || textC;
        const dim = e.anySelected && !e.isSelected(p);
        el("text", { x: r1(horiz ? c : mid), y: r1((horiz ? mid : c) + lbfs * 0.35), "text-anchor": "middle", fill, "font-size": lbfs, class: (inside ? "ilbl" : "lbl") + (dim ? " dim" : "") }, lbls, t);
    });
    if (ttShow) st.totals.forEach((t, c) => {
        if (!st.byCat[c].length) return;
        const up = t.pos > 0 || t.neg === 0, txt = fmtL(t.net), tw = textW(txt, ttfs) * 1.05;
        if (!horiz && tw > step + 2) return;
        if (horiz && ttfs > step) return;
        const pe = Vc(up ? t.pos : t.neg), d = horiz ? (up ? 1 : -1) : (up ? -1 : 1), along = horiz ? tw : ttfs * 1.05;
        const extra = look.is3d && up ? D3 * (horiz ? 1 : 0.6) : 0;
        const at = pe + d * (along / 2 + 3 + extra), mid = cs(c) + step / 2;
        el("text", { x: r1(horiz ? at : mid), y: r1((horiz ? mid : at) + ttfs * 0.35), "text-anchor": "middle", fill: totC, "font-size": ttfs, class: "lbl tot" }, lbls, txt);
    });

    /* ---------- category axis (scrolls with the bars) ---------- */
    if (cShow) {
        const g = el("g", { class: "cax" }, F);
        if (!horiz) {
            const y0 = plotB - oy + 4;
            leaf.forEach((t, i) => {
                if (i % skip) return;
                const cx = cs(i) + step / 2;
                if (catMode === "flat") e.bindCat(el("text", { x: r1(cx), y: r1(y0 + cfs * 0.9), "text-anchor": "middle", fill: cC, "font-size": cfs }, g, t), i);
                else if (catMode === "wrap") {
                    const lines = wraps[i] || [t], tx = e.bindCat(el("text", { x: r1(cx), y: r1(y0 + cfs * 0.9), "text-anchor": "middle", fill: cC, "font-size": cfs }, g), i);
                    lines.forEach((ln, k) => { el("tspan", { x: r1(cx), dy: k ? r1(cfs * 1.15) : 0 }, tx, ln); });
                } else {
                    const ax = cx + cfs * 0.25, ay = y0 + cfs * 0.55;
                    e.bindCat(el("text", { x: r1(ax), y: r1(ay), "text-anchor": "end", fill: cC, "font-size": cfs, transform: `rotate(-45 ${r1(ax)} ${r1(ay)})` }, g, trunc(t, rotLen, cfs)), i);
                }
            });
            for (let t = 0; t < tiers; t++) {
                const rr = tiers - 1 - t, rowTop = y0 + catH - 4 + rr * (cfs + 10), ty = rowTop + cfs + 3, sepC = mix(ink, surf, 0.78);
                runs[t].forEach((r, k) => {
                    const x0 = cs(r.i0), x1 = cs(r.i1 + 1);
                    el("text", { x: r1((x0 + x1) / 2), y: r1(ty), "text-anchor": "middle", fill: cC, "font-size": cfs, class: "tier" }, g, trunc(r.label, x1 - x0 - 6, cfs));
                    el("line", { x1: r1(x0), x2: r1(x0), y1: r1(y0 - 4), y2: r1(rowTop + cfs + 8), stroke: sepC, "stroke-width": 1 }, g);
                    if (k === runs[t].length - 1) el("line", { x1: r1(x1), x2: r1(x1), y1: r1(y0 - 4), y2: r1(rowTop + cfs + 8), stroke: sepC, "stroke-width": 1 }, g);
                });
            }
        } else {
            const xr = plotL - ox - 8;
            leaf.forEach((t, i) => {
                if (i % skip) return;
                e.bindCat(el("text", { x: r1(xr), y: r1(cs(i) + step / 2 + cfs * 0.35), "text-anchor": "end", fill: cC, "font-size": cfs }, g, trunc(t, leafW - 8, cfs)), i);
            });
            let right = xr - leafW + 8;
            for (let t = tiers - 1; t >= 0; t--) {
                const tw = tierWs[t], left = right - tw, sepC = mix(ink, surf, 0.78);
                runs[t].forEach((r, k) => {
                    const y0 = cs(r.i0), y1 = cs(r.i1 + 1);
                    el("text", { x: r1(right - 6), y: r1((y0 + y1) / 2 + cfs * 0.35), "text-anchor": "end", fill: cC, "font-size": cfs, class: "tier" }, g, trunc(r.label, tw - 10, cfs));
                    el("line", { x1: r1(left), x2: r1(plotL - ox), y1: r1(y0), y2: r1(y0), stroke: sepC, "stroke-width": 1 }, g);
                    if (k === runs[t].length - 1) el("line", { x1: r1(left), x2: r1(plotL - ox), y1: r1(y1), y2: r1(y1), stroke: sepC, "stroke-width": 1 }, g);
                });
                right = left;
            }
        }
    }

    /* ---------- over: reference line and legend ---------- */
    const O = L.over;
    if (refV !== null && isFinite(refV) && refV >= lo && refV <= hi) {
        const p = V(refV), rc = colorOr(RL.color, mix(ink, surf, 0.25)), rd = DASH[String(RL.style.value.value)] || null;
        const kindName: Record<string, string> = { average: "Average", median: "Median", min: "Min", max: "Max", constant: "Target" };
        const txt = `${kindName[String(RL.kind.value.value)] || ""} ${fmtL(refV)}`.trim();
        if (horiz) {
            el("line", { x1: r1(p), x2: r1(p), y1: r1(plotT - D3y), y2: r1(plotB), stroke: rc, "stroke-width": 1.5, "stroke-dasharray": rd, "stroke-linecap": "round" }, O);
            if (RL.label.value) { const right = p + textW(txt, lbfs) + 8 < plotR; el("text", { x: r1(right ? p + 5 : p - 5), y: r1(plotT + lbfs * 0.4), "text-anchor": right ? "start" : "end", fill: rc, "font-size": lbfs, class: "lbl ref" }, O, txt); }
        } else {
            el("line", { x1: r1(plotL), x2: r1(plotR), y1: r1(p), y2: r1(p), stroke: rc, "stroke-width": 1.5, "stroke-dasharray": rd, "stroke-linecap": "round" }, O);
            if (RL.label.value) el("text", { x: r1(plotR - 2), y: r1(p - 5), "text-anchor": "end", fill: rc, "font-size": lbfs, class: "lbl ref" }, O, txt);
        }
    }
    lItems.forEach(li => {
        if (li.kind === "title") { el("text", { x: r1(li.x), y: r1(li.y + lfs * 0.35), fill: lgC, "font-size": lfs, class: "lgt" }, O, li.text); return; }
        if (li.kind === "more" || !li.ser) { el("text", { x: r1(li.x), y: r1(li.y + lfs * 0.35), fill: mix(lgC, surf, 0.35), "font-size": lfs }, O, li.text); return; }
        const sr = li.ser, g = el("g", { class: "lg" + (e.seriesDim(sr) ? " dim" : "") }, O);
        el("rect", { x: r1(li.x - 2), y: r1(li.y - rowH / 2), width: r1(li.w - 8), height: r1(rowH), class: "hit", fill: "#000000", "fill-opacity": 0 }, g);
        const sw0 = e.hc ? { fill: surf, stroke: ink, "stroke-width": 1.5, "stroke-dasharray": HC_DASH[sr.i % HC_DASH.length] } : { fill: look.flat ? sr.color : look.fill(sr.color, "r") };
        if (lolli || look.flat) el("circle", { cx: r1(li.x + 4.5), cy: r1(li.y), r: 4.5, ...sw0 }, g);
        else el("rect", { x: r1(li.x), y: r1(li.y - 4.5), width: 9, height: 9, rx: 2.5, ...sw0 }, g);
        el("text", { x: r1(li.x + 13), y: r1(li.y + lfs * 0.35), fill: lgC, "font-size": lfs }, g, li.text);
        e.bindSeries(g, sr);
    });
    return { mode, horiz, labelOf, pct };
}
