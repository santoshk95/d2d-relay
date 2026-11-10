/*
 * Drawing for Atlas Distribution: histogram, box and whisker, violin
 * (with raincloud) and parallel coordinates, with axes, gridlines,
 * legend, data labels and mean/median lines, in flat, soft and 3D looks.
 * Marks that hold observations are handed to the visual through bind().
 */
import powerbi from "powerbi-visuals-api";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { Model, Group, Obs, stats, Stats, kde, binning, binOf, jitter } from "./model";
import { DistSettings } from "./settings";
import { Look, el, r1, textW, trunc } from "./common/look";
import { mix, isHex, normHex } from "./common/color";
import { labelFormatter, axisFormatter, formatter } from "./common/util";
import ISelectionId = powerbi.visuals.ISelectionId;
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

/** something the reader can hover, click or focus: a bar, a box, a point, a line or a legend item */
export interface Target { key: string; obs: number[]; ids: ISelectionId[]; tip: () => TipItem[]; }
export interface Env {
    W: number; H: number; m: Model; s: DistSettings; look: Look; root: SVGGElement;
    ink: string; surface: string; hc: boolean; culture: string;
    colorOf: (g: Group) => string;
    /** observations to emphasize (selection, else highlights); null when nothing is emphasized */
    active: Set<number> | null;
    bind: (e: SVGElement, t: Target) => void;
    msg: (key: string, fallback: string) => string;
}

const DASH: Record<string, string | null> = { solid: null, dashed: "5 4", dotted: "1.5 3" };
const D3 = 7;
const colorOr = (c: fs.ColorPicker, fallback: string) => { const v = c.value && c.value.value; return v && isHex(v) ? normHex(v) : fallback; };

/** round domain and 1-2-5 ticks */
function nice(lo: number, hi: number, count: number): { lo: number; hi: number; ticks: number[] } {
    if (!(hi > lo)) { const w = Math.abs(lo) * 0.1 || 1; lo -= w; hi += w; }
    const span = hi - lo; let step = Math.pow(10, Math.floor(Math.log10(span / Math.max(1, count))));
    const err = span / Math.max(1, count) / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step, ticks: number[] = [];
    for (let i = 0; i < 200; i++) { const v = a + i * step; if (v > b + step * 1e-6) break; ticks.push(Math.abs(v) < step * 1e-9 ? 0 : +v.toPrecision(12)); }
    return { lo: a, hi: b, ticks };
}
const parseNum = (s: string) => { const t = String(s || "").replace(/[\s,]/g, ""); return t === "" ? NaN : Number(t); };
/** rectangle with rounded corners on one end only (t = top, r = right) */
function rpath(x: number, y: number, w: number, h: number, r: number, end: "t" | "r"): string {
    const e = Math.max(0, Math.min(r, w / 2, h / 2));
    if (e < 0.05) return `M${r1(x)},${r1(y)}h${r1(w)}v${r1(h)}h${r1(-w)}Z`;
    return end === "t"
        ? `M${r1(x)},${r1(y + h)}V${r1(y + e)}A${r1(e)},${r1(e)} 0 0 1 ${r1(x + e)},${r1(y)}H${r1(x + w - e)}A${r1(e)},${r1(e)} 0 0 1 ${r1(x + w)},${r1(y + e)}V${r1(y + h)}Z`
        : `M${r1(x)},${r1(y)}H${r1(x + w - e)}A${r1(e)},${r1(e)} 0 0 1 ${r1(x + w)},${r1(y + e)}V${r1(y + h - e)}A${r1(e)},${r1(e)} 0 0 1 ${r1(x + w - e)},${r1(y + h)}H${r1(x)}Z`;
}
/** smooth path through points with horizontal tangents (parallel coordinates) */
function smoothPath(p: [number, number][]): string {
    let d = `M${r1(p[0][0])},${r1(p[0][1])}`;
    for (let i = 1; i < p.length; i++) { const mx = (p[i - 1][0] + p[i][0]) / 2; d += `C${r1(mx)},${r1(p[i - 1][1])} ${r1(mx)},${r1(p[i][1])} ${r1(p[i][0])},${r1(p[i][1])}`; }
    return d;
}

export function render(e: Env): void {
    const { W, H, m, s, look, root } = e, ink = e.ink, surf = e.surface;
    const type = String(s.chart.chartType.value.value);
    const textC = mix(ink, surf, 0.14), axisC = mix(ink, surf, 0.4);
    const VA = s.valueAxis, CA = s.categoryAxis, GR = s.gridlines, LG = s.legend, LB = s.labels, ST = s.stats;
    const vfs = Math.max(6, VA.fontSize.value), cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value);
    const vC = colorOr(VA.color, axisC), cC = colorOr(CA.color, axisC), gC = colorOr(GR.color, mix(ink, surf, 0.88)), lbC = colorOr(LB.color, textC);
    const pad = 6, d3 = look.is3d ? D3 : 0;
    const fmt0 = m.measures[0].format;
    const valOf = (o: Obs) => o.v[m.byMeasure ? m.groups[o.g].m : 0];
    const on = (i: number) => !e.active || e.active.has(i);
    const grpOn = (g: Group) => !e.active || g.obs.some(i => (e.active as Set<number>).has(i));
    const gidOf = (g: Group) => (g.id ? [g.id] : []);
    const shadowed = (parent: Element) => { const f = look.shadow(); return el("g", f ? { filter: f } : {}, parent); };

    /* ---------- legend (histogram and parallel coordinates) ---------- */
    const legendOn = LG.show.value && (type === "histogram" || type === "parallel") && m.groups.length > 1;
    const lfs = Math.max(6, LG.fontSize.value), lpos = String(LG.position.value.value), rowH = lfs + 9, lgC = colorOr(LG.color, textC);
    const lTitle = legendOn && LG.title.value ? (m.byMeasure ? "" : m.groupTitle) : "";
    let lgTop = 0, lgBottom = 0, lgRight = 0;
    const drawLegend: (() => void)[] = [];
    if (legendOn) {
        interface LI { g?: Group; text: string; x: number; y: number; w: number; kind: "item" | "title" | "more"; }
        const items: LI[] = [];
        const iw = (t: string) => 13 + textW(t, lfs) + 14;
        if (lpos === "right") {
            const lw = Math.min(W * 0.3, Math.max(lTitle ? textW(lTitle, lfs) + 4 : 0, ...m.groups.map(g => iw(trunc(g.name, 150, lfs)) - 10)));
            lgRight = lw + 8; let y = pad + rowH / 2; const x = W - pad - lw;
            if (lTitle) { items.push({ text: trunc(lTitle, lw, lfs), x, y, w: lw, kind: "title" }); y += rowH; }
            for (let k = 0; k < m.groups.length; k++) {
                if (y > H - pad - rowH && k < m.groups.length - 1) { items.push({ text: `+${m.groups.length - k} more`, x, y, w: lw, kind: "more" }); break; }
                items.push({ g: m.groups[k], text: trunc(m.groups[k].name, lw - 14, lfs), x, y, w: lw, kind: "item" }); y += rowH;
            }
        } else {
            const top = lpos.startsWith("top"), center = lpos.endsWith("Center"), avail = W - 2 * pad;
            const rows: LI[][] = [[]]; let x = 0, full = false;
            const push = (li: LI) => {
                if (x + li.w > avail && rows[rows.length - 1].length) { if (rows.length >= 2) return false; rows.push([]); x = 0; }
                li.x = x; rows[rows.length - 1].push(li); x += li.w; return true;
            };
            if (lTitle) push({ text: lTitle, x: 0, y: 0, w: textW(lTitle, lfs) + 10, kind: "title" });
            for (let k = 0; k < m.groups.length && !full; k++) {
                const t = trunc(m.groups[k].name, 160, lfs);
                if (!push({ g: m.groups[k], text: t, x: 0, y: 0, w: iw(t), kind: "item" })) { rows[rows.length - 1].push({ text: `+${m.groups.length - k}`, x, y: 0, w: 30, kind: "more" }); full = true; }
            }
            const h = rows.length * rowH, y0 = top ? pad + rowH / 2 : H - pad - h + rowH / 2;
            rows.forEach((r, ri) => {
                const rw = r.length ? r[r.length - 1].x + r[r.length - 1].w - 14 : 0, off = center ? Math.max(0, (avail - rw) / 2) : 0;
                r.forEach(li => { li.x += pad + off; li.y = y0 + ri * rowH; items.push(li); });
            });
            if (top) lgTop = h + 4; else lgBottom = h + 4;
        }
        drawLegend.push(() => {
            const lg = el("g", { class: "legend" }, root);
            items.forEach(li => {
                if (li.kind !== "item" || !li.g) { el("text", { x: r1(li.x), y: r1(li.y + lfs * 0.35), "font-size": lfs, fill: lgC, class: li.kind === "title" ? "lgt" : "ax" }, lg, li.text); return; }
                const g = li.g, c = e.colorOf(g);
                const it = el("g", { class: "lg" + (grpOn(g) ? "" : " dim") }, lg);
                el("rect", { class: "hit", x: r1(li.x - 2), y: r1(li.y - rowH / 2 + 1), width: r1(Math.min(li.w - 4, textW(li.text, lfs) + 18)), height: rowH - 2, rx: 4, fill: "transparent", stroke: "none" }, it);
                if (type === "parallel") el("rect", { x: r1(li.x), y: r1(li.y - 1.5), width: 10, height: 3, rx: 1.5, fill: c }, it);
                else el("rect", { x: r1(li.x), y: r1(li.y - 5), width: 10, height: 10, rx: 2.5, fill: c }, it);
                el("text", { x: r1(li.x + 14), y: r1(li.y + lfs * 0.35), "font-size": lfs, fill: lgC, class: "ax" }, it, li.text);
                e.bind(it, { key: "g" + g.i, obs: g.obs, ids: gidOf(g), tip: () => [{ displayName: m.groupTitle || "Group", value: g.name, color: c }, { displayName: "Observations", value: String(g.obs.length) }] });
            });
        });
    }
    const box = { l: pad, t: pad + lgTop, r: W - pad - lgRight, b: H - pad - lgBottom };

    /* ---------- shared value-axis helpers ---------- */
    const uLo = parseNum(VA.start.value), uHi = parseNum(VA.end.value);
    const domain = (lo: number, hi: number, px: number, per: number) => {
        if (isFinite(uLo)) lo = uLo;
        if (isFinite(uHi)) hi = uHi;
        const nt = nice(lo, hi, Math.max(2, Math.min(10, Math.round(px / per))));
        const a = isFinite(uLo) ? uLo : nt.lo, b = isFinite(uHi) && uHi > a ? uHi : Math.max(nt.hi, a + 1e-9);
        const eps = (b - a) * 1e-9;
        return { lo: a, hi: b, ticks: nt.ticks.filter(t => t >= a - eps && t <= b + eps) };
    };
    const vTitle = VA.title.value ? (m.byMeasure ? m.measures.map(x => x.name).join(", ") : m.measures[0].name) : "";
    const dash = DASH[String(GR.style.value.value)];
    const allStats = stats(m.obs.map(valOf), "iqr");
    const statLines = (draw: (v: number, name: string, k: number) => void) => {
        const list: [number, string][] = [];
        if (ST.mean.value) list.push([allStats.mean, "Mean"]);
        if (ST.median.value) list.push([allStats.md, "Median"]);
        list.forEach(([v, n], k) => { if (isFinite(v)) draw(v, n, k); });
    };
    const stC = colorOr(ST.color, mix(ink, surf, 0.25)), stDash = DASH[String(ST.style.value.value)];

    if (type === "parallel") parallel(); else if (type === "histogram") histogram(); else boxOrViolin(type === "violin");
    drawLegend.forEach(f => f());

    /* ================================================================ histogram */
    function histogram() {
        const HS = s.histogram, all = m.obs.map(valOf).filter(v => isFinite(v));
        let mn = Math.min(...all), mx = Math.max(...all);
        if (isFinite(uLo)) mn = uLo;
        if (isFinite(uHi)) mx = uHi;
        const bins = binning(mn, mx, all.length, String(HS.binMode.value.value), HS.binCount.value, HS.binWidth.value);
        const G = m.groups.length, stacked = G > 1 && String(HS.layout.value.value) === "stacked", pct = String(HS.yMeasure.value.value) === "percent";
        const cnt: number[][] = m.groups.map(() => new Array(bins.count).fill(0)), hot: number[][] = m.groups.map(() => new Array(bins.count).fill(0));
        const members: number[][][] = m.groups.map(() => Array.from({ length: bins.count }, () => [] as number[]));
        m.obs.forEach(o => { const v = valOf(o); if (!isFinite(v) || v < bins.start - 1e-9 || v > bins.start + bins.step * bins.count + 1e-9) return; const k = binOf(bins, v); cnt[o.g][k]++; members[o.g][k].push(o.i); if (on(o.i)) hot[o.g][k]++; });
        const tot = m.groups.map((_, g) => cnt[g].reduce((a, b) => a + b, 0) || 1);
        const yv = (g: number, c: number) => (pct ? c / tot[g] : c);
        let top = 0;
        for (let k = 0; k < bins.count; k++) { let acc = 0; for (let g = 0; g < G; g++) { acc = stacked ? acc + yv(g, cnt[g][k]) : Math.max(acc, yv(g, cnt[g][k])); } top = Math.max(top, acc); }
        const pdfs = HS.normalCurve.value ? m.groups.map((g, gi) => { const st = stats(g.obs.map(i => valOf(m.obs[i])), "iqr"); return { st, n: pct ? 1 : tot[gi] }; }).filter(p => p.st.sd > 0) : [];
        pdfs.forEach(p => { top = Math.max(top, p.n * bins.step / (p.st.sd * Math.sqrt(2 * Math.PI))); });
        const yd = nice(0, top * 1.04 || 1, 5), yTicks = yd.ticks, yHi = yd.hi;
        const fmtY = pct ? (v: number) => (v * 100).toFixed(yTicks.length > 1 && (yTicks[1] - yTicks[0]) * 100 < 1 ? 1 : 0) + "%" : formatter("#,0", 1, null, yHi, e.culture);
        const lbH = LB.show.value ? lbfs + 4 : 0;
        const yLabW = VA.show.value ? Math.max(...yTicks.map(t => textW(fmtY(t), vfs))) + 8 : 0;
        const L = box.l + yLabW, R = box.r - d3 - 4, T = box.t + lbH + d3 * 0.6 + 2, B = box.b - (VA.show.value ? vfs + 8 : 0) - (vTitle ? vfs + 6 : 0);
        const x0 = bins.start, x1 = bins.start + bins.step * bins.count;
        const X = (v: number) => L + (v - x0) / (x1 - x0) * (R - L), Y = (v: number) => B - v / yHi * (B - T);
        /* value ticks along x */
        const xt = nice(x0, x1, Math.max(2, Math.min(10, Math.round((R - L) / 80))));
        const xTicks = xt.ticks.filter(t => t >= x0 - 1e-9 && t <= x1 + 1e-9);
        const fmtX = axisFormatter(fmt0, Number(VA.displayUnits.value) || 0, VA.decimals.value, xTicks, e.culture);
        const ax = el("g", { class: "axes" }, root);
        if (GR.show.value) yTicks.forEach(t => { if (t > 0) el("line", { x1: r1(L), x2: r1(R + d3), y1: r1(Y(t)) + 0.5, y2: r1(Y(t)) + 0.5, stroke: gC, "stroke-width": GR.width.value, "stroke-dasharray": dash }, ax); });
        el("line", { x1: r1(L), x2: r1(R), y1: r1(B) + 0.5, y2: r1(B) + 0.5, stroke: mix(ink, surf, 0.7), "stroke-width": 1 }, ax);
        if (VA.show.value) {
            yTicks.forEach(t => el("text", { x: r1(L - 6), y: r1(Y(t) + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: vC, class: "ax" }, ax, fmtY(t)));
            let lastR = -Infinity;
            xTicks.forEach(t => { const tx = fmtX(t), w = textW(tx, vfs), cx = X(t); if (cx - w / 2 < lastR + 6) return; lastR = cx + w / 2; el("text", { x: r1(Math.min(W - pad - w / 2, Math.max(pad + w / 2, cx))), y: r1(B + vfs + 4), "text-anchor": "middle", "font-size": vfs, fill: vC, class: "ax" }, ax, tx); });
        }
        if (vTitle) el("text", { x: r1((L + R) / 2), y: r1(box.b - 2), "text-anchor": "middle", "font-size": vfs, fill: vC, class: "ttl" }, ax, trunc(vTitle, R - L, vfs));

        const bars = shadowed(root), gap = Math.max(0, HS.gap.value), rad = look.is3d ? 0 : HS.radius.value;
        const op = G > 1 && !stacked ? Math.max(0.15, HS.opacity.value / 100) : 1;
        const fmtV = formatter(fmt0, 1, null, x1, e.culture);
        const base: number[] = new Array(bins.count).fill(0);
        for (let g = 0; g < G; g++) {
            const grp = m.groups[g], c = e.colorOf(grp), layer = el("g", {}, bars);
            for (let k = 0; k < bins.count; k++) {
                const n = cnt[g][k]; if (!n) continue;
                const v = yv(g, n), a = stacked ? base[k] : 0, b = a + v;
                if (stacked) base[k] = b;
                const xa = X(x0 + k * bins.step) + gap / 2, xb = X(x0 + (k + 1) * bins.step) - gap / 2, w = Math.max(0.6, xb - xa);
                const ya = Y(b), h = Math.max(0.5, Y(a) - Y(b));
                const lo = x0 + k * bins.step, hi = lo + bins.step;
                const t: Target = {
                    key: `b${g}|${k}`, obs: members[g][k], ids: members[g][k].map(i => m.obs[i].id).slice(0, 2000),
                    tip: () => {
                        const items: TipItem[] = [{ displayName: "Bin", value: `${fmtV(lo)} – ${fmtV(hi)}` }];
                        if (G > 1) items.push({ displayName: m.groupTitle || "Group", value: grp.name, color: c });
                        items.push({ displayName: "Count", value: String(n), color: c }, { displayName: "Share of " + (G > 1 ? grp.name : "total"), value: (n / tot[g] * 100).toFixed(1) + "%" });
                        if (e.active && hot[g][k] !== n) items.push({ displayName: "Highlighted", value: String(hot[g][k]) });
                        return items;
                    }
                };
                const partial = e.active ? hot[g][k] / n : 1;
                const mk = el("g", { class: "grp bar" + (partial === 0 ? " dim" : "") }, layer);
                const draw = (yy: number, hh: number, cls: string) => {
                    if (look.is3d) {
                        const dy = D3 * 0.6;
                        el("path", { d: `M${r1(xa)},${r1(yy)}l${D3},${-dy}h${r1(w)}l${-D3},${dy}Z`, fill: e.hc ? surf : look.top(c), stroke: e.hc ? ink : "none", class: cls, "fill-opacity": op }, mk);
                        el("path", { d: `M${r1(xa + w)},${r1(yy)}l${D3},${-dy}v${r1(hh)}l${-D3},${dy}Z`, fill: e.hc ? surf : look.side(c), stroke: e.hc ? ink : "none", class: cls, "fill-opacity": op }, mk);
                    }
                    el("path", { d: rpath(xa, yy, w, hh, stacked && g < G - 1 ? 0 : rad, "t"), fill: e.hc ? ink : look.fill(c, "v"), "fill-opacity": op, class: cls }, mk);
                };
                if (e.active && partial > 0 && partial < 1) {
                    draw(ya, h, "ghost");
                    const hh = Math.max(0.5, h * partial);
                    el("path", { d: rpath(xa, ya + h - hh, w, hh, 0, "t"), fill: e.hc ? ink : look.fill(c, "v"), "fill-opacity": op }, mk);
                } else draw(ya, h, "");
                e.bind(mk, t);
            }
        }
        /* labels: bin totals above the bars (one group or stacked) */
        if (LB.show.value && (G === 1 || stacked)) {
            const lg = el("g", {}, root);
            const fmtC = pct ? (v: number) => (v * 100).toFixed(LB.decimals.value >= 0 ? Math.min(4, LB.decimals.value) : 0) + "%" : formatter("#,0", Number(LB.displayUnits.value) || 1, LB.decimals.value, 1, e.culture);
            for (let k = 0; k < bins.count; k++) {
                let v = 0; for (let g = 0; g < G; g++) v += yv(g, cnt[g][k]);
                if (!v) continue;
                const xa = X(x0 + k * bins.step), xb = X(x0 + (k + 1) * bins.step), t = fmtC(v);
                if (textW(t, lbfs) > xb - xa + 2) continue;
                el("text", { x: r1((xa + xb) / 2 + d3 / 2), y: r1(Y(v) - 4 - d3 * 0.6), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl val" }, lg, t);
            }
        }
        /* normal curves */
        pdfs.forEach((p, k) => {
            const pts: string[] = [], c = e.hc ? ink : mix(e.colorOf(m.groups[Math.min(k, G - 1)]), ink, 0.25);
            for (let i = 0; i <= 80; i++) { const v = x0 + (x1 - x0) * i / 80, y = p.n * bins.step * Math.exp(-0.5 * ((v - p.st.mean) / p.st.sd) ** 2) / (p.st.sd * Math.sqrt(2 * Math.PI)); pts.push(`${r1(X(v))},${r1(Y(y))}`); }
            el("path", { d: "M" + pts.join("L"), fill: "none", stroke: c, "stroke-width": 2, "stroke-linejoin": "round", "pointer-events": "none" }, root);
        });
        statLines((v, name, k) => {
            const xx = r1(X(v)) + 0.5; if (xx < L || xx > R) return;
            el("line", { x1: xx, x2: xx, y1: r1(T - lbH), y2: r1(B), stroke: stC, "stroke-width": 1.5, "stroke-dasharray": stDash }, root);
            if (ST.label.value) el("text", { x: r1(xx + (k ? -4 : 4)), y: r1(T - lbH + vfs), "text-anchor": k ? "end" : "start", "font-size": vfs, fill: stC, class: "lbl ref" }, root, `${name} ${fmtV(v)}`);
        });
    }

    /* ================================================================ box and violin */
    function boxOrViolin(violin: boolean) {
        const BX = s.box, VI = s.violin, PT = s.points;
        const horiz = String(s.chart.orientation.value.value) === "horizontal";
        const whisk = String(BX.whiskers.value.value);
        const order = m.groups.map(g => ({ g, st: stats(g.obs.map(i => valOf(m.obs[i])), whisk) }));
        const sort = String(s.chart.sort.value.value);
        if (sort === "name") order.sort((a, b) => a.g.name.localeCompare(b.g.name));
        else if (sort === "medianAsc") order.sort((a, b) => a.st.md - b.st.md);
        else if (sort === "medianDesc") order.sort((a, b) => b.st.md - a.st.md);
        const n = order.length;
        const half = violin && String(VI.side.value.value) === "half";
        const bwF = Math.max(0.2, VI.bandwidth.value / 100), trim = VI.trim.value;
        /* densities over the data range (or a little beyond it when not trimmed) */
        const dens = violin ? order.map(o => {
            const st = o.st, span = (st.max - st.min) || Math.abs(st.max) * 0.1 || 1, ext = trim ? 0 : span * 0.12;
            return kde(st.sorted, st.min - ext, st.max + ext, 64, bwF);
        }) : [];
        const dmax = violin ? Math.max(1e-12, ...dens.map(d => Math.max(...d.map(p => p[1])))) : 1;
        let lo = Math.min(...order.map(o => (violin ? (trim ? o.st.min : dens[order.indexOf(o)][0][0]) : (BX.outliers.value || String(BX.points.value.value) !== "none" ? o.st.min : o.st.lo))));
        let hi = Math.max(...order.map(o => (violin ? (trim ? o.st.max : dens[order.indexOf(o)][63][0]) : (BX.outliers.value || String(BX.points.value.value) !== "none" ? o.st.max : o.st.hi))));
        if (ST.mean.value) { lo = Math.min(lo, allStats.mean); hi = Math.max(hi, allStats.mean); }
        if (lo > 0 && lo < (hi - lo) * 0.35) lo = 0;
        /* layout */
        const showCat = CA.show.value && (m.hasGroup || m.byMeasure || n > 1);
        const cTitle = CA.title.value && showCat ? (m.byMeasure ? "" : m.groupTitle) : "";
        let L: number, R: number, T: number, B: number;
        let dom: { lo: number; hi: number; ticks: number[] };
        let fmtA: (v: number) => string;
        if (!horiz) {
            T = box.t + d3 * 0.6 + (vTitle ? vfs + 6 : 0) + 4; B = box.b - (showCat ? cfs + 8 : 0) - (cTitle ? cfs + 6 : 0);
            dom = domain(lo, hi, B - T, 44);
            fmtA = axisFormatter(fmt0, Number(VA.displayUnits.value) || 0, VA.decimals.value, dom.ticks, e.culture);
            L = box.l + (VA.show.value ? Math.max(...dom.ticks.map(t => textW(fmtA(t), vfs))) + 8 : 0); R = box.r - d3 - 2;
        } else {
            const nameW = showCat ? Math.min(W * 0.3, Math.max(...order.map(o => textW(o.g.name, cfs)))) + 10 : 0;
            L = box.l + nameW + (cTitle ? cfs + 8 : 0); R = box.r - d3 - 10;
            T = box.t + d3 * 0.6 + 2; B = box.b - (VA.show.value ? vfs + 8 : 0) - (vTitle ? vfs + 6 : 0);
            dom = domain(lo, hi, R - L, 80);
            fmtA = axisFormatter(fmt0, Number(VA.displayUnits.value) || 0, VA.decimals.value, dom.ticks, e.culture);
        }
        const vlo = dom.lo, vhi = dom.hi;
        const clampV = (v: number) => Math.max(vlo, Math.min(vhi, v));
        /* value -> pixel along the value axis; slot -> pixel along the group axis */
        const VP = (v: number) => (horiz ? L + (clampV(v) - vlo) / (vhi - vlo) * (R - L) : B - (clampV(v) - vlo) / (vhi - vlo) * (B - T));
        const slot = (horiz ? B - T : R - L) / Math.max(1, n);
        const UP = (k: number) => (horiz ? T : L) + slot * (k + 0.5);
        /* point in (group-axis offset, value) space to x,y */
        const P = (u: number, v: number): [number, number] => (horiz ? [VP(v), u] : [u, VP(v)]);
        const pstr = (u: number, v: number) => { const p = P(u, v); return `${r1(p[0])},${r1(p[1])}`; };
        const rectUV = (u0: number, u1: number, v0: number, v1: number) => {
            const a = P(u0, v0), b = P(u1, v1);
            return { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), w: Math.abs(b[0] - a[0]), h: Math.max(1, Math.abs(b[1] - a[1])) };
        };

        /* axes and gridlines */
        const ax = el("g", { class: "axes" }, root);
        dom.ticks.forEach(t => {
            const p = VP(t);
            if (GR.show.value) el("line", horiz ? { x1: r1(p) + 0.5, x2: r1(p) + 0.5, y1: r1(T - d3 * 0.6), y2: r1(B) } : { x1: r1(L), x2: r1(R + d3), y1: r1(p) + 0.5, y2: r1(p) + 0.5 }, ax)
                .setAttribute("style", `stroke:${gC};stroke-width:${GR.width.value}px${dash ? ";stroke-dasharray:" + dash : ""}`);
            if (VA.show.value) el("text", horiz ? { x: r1(p), y: r1(B + vfs + 4), "text-anchor": "middle", "font-size": vfs, fill: vC, class: "ax" } : { x: r1(L - 6), y: r1(p + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: vC, class: "ax" }, ax, fmtA(t));
        });
        if (vTitle) el("text", horiz ? { x: r1((L + R) / 2), y: r1(box.b - 2), "text-anchor": "middle", "font-size": vfs, fill: vC, class: "ttl" } : { x: r1(box.l), y: r1(box.t + vfs), "font-size": vfs, fill: vC, class: "ttl" }, ax, trunc(vTitle, horiz ? R - L : W - 2 * pad, vfs));
        if (showCat) order.forEach((o, k) => {
            const u = UP(k);
            if (horiz) el("text", { x: r1(L - 8), y: r1(u + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, ax, trunc(o.g.name, L - box.l - (cTitle ? cfs + 8 : 0) - 10, cfs));
            else el("text", { x: r1(u), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, ax, trunc(o.g.name, slot - 4, cfs));
        });
        if (cTitle) {
            if (horiz) el("text", { x: r1(box.l + cfs * 0.8), y: r1((T + B) / 2), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ttl", transform: `rotate(-90 ${r1(box.l + cfs * 0.8)} ${r1((T + B) / 2)})` }, ax, trunc(cTitle, B - T, cfs));
            else el("text", { x: r1((L + R) / 2), y: r1(box.b - 2), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ttl" }, ax, trunc(cTitle, R - L, cfs));
        }

        const fmtV = formatter(fmt0, 1, null, vhi, e.culture);
        const fmtL = labelFormatter(fmt0, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(Math.abs(vlo), Math.abs(vhi)), e.culture);
        const marks = shadowed(root), pts = el("g", { class: "pts" }, root), lab = el("g", {}, root);
        const pr = Math.max(0.5, PT.size.value), pop = Math.max(0.05, PT.opacity.value / 100);
        const bindPts = m.obs.length <= 4000;
        const groupTip = (o: { g: Group; st: Stats }, c: string): TipItem[] => {
            const st = o.st, items: TipItem[] = [];
            if (m.hasGroup || m.byMeasure) items.push({ displayName: m.byMeasure ? "Measure" : m.groupTitle, value: o.g.name, color: c });
            items.push({ displayName: "Median", value: fmtV(st.md), color: c }, { displayName: "Middle 50%", value: `${fmtV(st.q1)} – ${fmtV(st.q3)}` });
            if (!violin) items.push({ displayName: "Whiskers", value: `${fmtV(st.lo)} – ${fmtV(st.hi)}` }, { displayName: "Outliers", value: String(st.out.length) });
            else items.push({ displayName: "Range", value: `${fmtV(st.min)} – ${fmtV(st.max)}` });
            items.push({ displayName: "Mean", value: fmtV(st.mean) }, { displayName: "Observations", value: String(st.n) });
            if (e.active) items.push({ displayName: "Highlighted", value: String(o.g.obs.filter(i => (e.active as Set<number>).has(i)).length) });
            return items;
        };
        const point = (o: Obs, u: number, c: string, r: number, cls: string, parent: Element) => {
            const p = P(u, valOf(o));
            const dot = el("circle", { cx: r1(p[0]), cy: r1(p[1]), r: r1(r), fill: e.hc ? ink : look.flat ? c : look.fill(c, "r"), "fill-opacity": cls === "ol" ? 0 : pop, stroke: cls === "ol" ? (e.hc ? ink : c) : "none", "stroke-width": cls === "ol" ? 1.2 : 0, class: "pt " + cls + (on(o.i) ? "" : " dim") }, parent);
            if (bindPts) e.bind(dot, { key: "o" + o.i, obs: [o.i], ids: [o.id], tip: () => obsTip(o, c) });
        };
        const obsTip = (o: Obs, c: string): TipItem[] => {
            const items: TipItem[] = [];
            if (m.detailTitle) items.push({ displayName: m.detailTitle, value: o.label });
            if (m.hasGroup) items.push({ displayName: m.groupTitle, value: m.groups[o.g].name, color: c });
            items.push({ displayName: m.byMeasure ? m.groups[o.g].name : m.measures[0].name, value: fmtV(valOf(o)), color: c });
            o.tips.forEach(t => items.push({ displayName: t.name, value: t.value }));
            return items;
        };

        order.forEach((o, k) => {
            const g = o.g, st = o.st, c = e.colorOf(g), u = UP(k);
            const gEl = el("g", { class: "grp" + (grpOn(g) ? "" : " dim") }, marks);
            const target: Target = { key: "g" + g.i, obs: g.obs, ids: gidOf(g), tip: () => groupTip(o, c) };
            const sgn = horiz ? 1 : -1;  /* half violins sit above (horizontal) or left (vertical) of the slot center */
            if (!violin) {
                const ptsMode = String(BX.points.value.value), beside = ptsMode === "beside";
                const bw = Math.max(3, slot * Math.max(0.1, BX.width.value / 100) * (beside ? 0.6 : 1)), cu = beside ? u - slot * 0.12 : u;
                const r = rectUV(cu - bw / 2, cu + bw / 2, st.q1, st.q3), rad = look.is3d ? 0 : Math.min(BX.radius.value, bw / 2);
                const light = ptsMode === "jitter";
                /* whiskers and caps */
                el("path", { d: `M${pstr(cu, st.hi)}L${pstr(cu, st.q3)}M${pstr(cu, st.q1)}L${pstr(cu, st.lo)}M${pstr(cu - bw * 0.25, st.hi)}L${pstr(cu + bw * 0.25, st.hi)}M${pstr(cu - bw * 0.25, st.lo)}L${pstr(cu + bw * 0.25, st.lo)}`, fill: "none", stroke: e.hc ? ink : mix(c, ink, 0.35), "stroke-width": 1.4, "stroke-linecap": "round" }, gEl);
                if (look.is3d) {
                    const dy = D3 * 0.6;
                    el("path", { d: `M${r1(r.x)},${r1(r.y)}l${D3},${-dy}h${r1(r.w)}l${-D3},${dy}Z`, fill: e.hc ? surf : look.top(c), stroke: e.hc ? ink : "none" }, gEl);
                    el("path", { d: `M${r1(r.x + r.w)},${r1(r.y)}l${D3},${-dy}v${r1(r.h)}l${-D3},${dy}Z`, fill: e.hc ? surf : look.side(c), stroke: e.hc ? ink : "none" }, gEl);
                }
                el("rect", { x: r1(r.x), y: r1(r.y), width: r1(r.w), height: r1(r.h), rx: r1(rad), fill: e.hc ? surf : look.fill(c, horiz ? "v" : "h"), "fill-opacity": light ? 0.35 : 1, stroke: e.hc ? ink : light ? c : "none", "stroke-width": e.hc || light ? 1.2 : 0 }, gEl);
                const mA = P(cu - bw / 2 + 1.5, st.md), mB = P(cu + bw / 2 - 1.5, st.md);
                el("line", { x1: r1(mA[0]), y1: r1(mA[1]), x2: r1(mB[0]), y2: r1(mB[1]), stroke: e.hc ? ink : light ? mix(c, ink, 0.4) : surf, "stroke-width": 2.2, "stroke-linecap": "round" }, gEl);
                if (BX.mean.value) { const p = P(cu, st.mean), q = Math.max(3, Math.min(5, bw / 5)); el("path", { d: `M${r1(p[0])},${r1(p[1] - q)}l${q},${q}l${-q},${q}l${-q},${-q}Z`, fill: e.hc ? ink : light ? c : surf, stroke: e.hc ? surf : mix(c, ink, 0.4), "stroke-width": 1 }, gEl); }
                e.bind(gEl, target);
                if (ptsMode !== "none") {
                    const su = beside ? u + slot * 0.22 : u, sw = beside ? slot * 0.26 : bw * 0.8;
                    g.obs.forEach(i => point(m.obs[i], su - sw / 2 + jitter(i) * sw, c, pr, "jt", pts));
                } else if (BX.outliers.value) {
                    g.obs.forEach(i => { const v = valOf(m.obs[i]); if (v < st.lo || v > st.hi) point(m.obs[i], cu, c, pr + 0.4, "ol", pts); });
                }
                if (LB.show.value) {
                    const t = fmtL(st.md), p = P(cu + bw / 2 + (horiz ? 0 : 4), st.md);
                    if (horiz) el("text", { x: r1(p[0]), y: r1(u - bw / 2 - 4), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, t);
                    else el("text", { x: r1(p[0] + d3), y: r1(p[1] + lbfs * 0.35), "font-size": lbfs, fill: lbC, class: "lbl" }, lab, trunc(t, Math.max(20, slot / 2 - bw / 2 + 10), lbfs));
                }
            } else {
                const d = dens[k], hw = slot * Math.max(0.2, VI.width.value / 100) * (half ? 0.62 : 0.5);
                const cu = half ? u + sgn * slot * 0.04 : u;
                const wOf = (y: number) => y / dmax * hw;
                const path = half
                    ? `M${pstr(cu, d[0][0])}L${d.map(p => pstr(cu + sgn * wOf(p[1]), p[0])).join("L")}L${pstr(cu, d[d.length - 1][0])}Z`
                    : `M${d.map(p => pstr(cu - wOf(p[1]), p[0])).join("L")}L${d.slice().reverse().map(p => pstr(cu + wOf(p[1]), p[0])).join("L")}Z`;
                if (look.is3d) el("path", { d: path, fill: e.hc ? surf : look.side(c), transform: `translate(${D3 * 0.6},${-D3 * 0.4})` }, gEl);
                const inner = String(VI.inner.value.value), ptsMode = String(VI.points.value.value);
                const soft = inner !== "none" || ptsMode !== "none";
                el("path", { d: path, fill: e.hc ? surf : look.fill(c, horiz ? "v" : "h"), "fill-opacity": soft && !look.is3d ? 0.82 : 1, stroke: e.hc ? ink : mix(c, ink, 0.2), "stroke-width": e.hc ? 1.2 : 0.8, "stroke-linejoin": "round" }, gEl);
                const near = (v: number) => { let best = d[0]; for (const p of d) if (Math.abs(p[0] - v) < Math.abs(best[0] - v)) best = p; return wOf(best[1]); };
                if (inner === "box") {
                    const bw = Math.max(4, Math.min(12, slot * 0.07)), bu = half ? u - sgn * slot * 0.08 : cu;
                    el("path", { d: `M${pstr(bu, st.hi)}L${pstr(bu, st.lo)}`, stroke: e.hc ? ink : mix(c, ink, 0.55), "stroke-width": 1.4 }, gEl);
                    const r = rectUV(bu - bw / 2, bu + bw / 2, st.q1, st.q3);
                    el("rect", { x: r1(r.x), y: r1(r.y), width: r1(r.w), height: r1(r.h), rx: 2, fill: e.hc ? ink : mix(c, ink, 0.6) }, gEl);
                    const p = P(bu, st.md); el("circle", { cx: r1(p[0]), cy: r1(p[1]), r: r1(Math.max(2.2, bw * 0.32)), fill: e.hc ? surf : "#ffffff" }, gEl);
                } else if (inner === "quartiles") {
                    [[st.q1, "3 3"], [st.md, null], [st.q3, "3 3"]].forEach(([v, ds]) => {
                        const w = near(v as number), a = half ? P(cu, v as number) : P(cu - w, v as number), b = half ? P(cu + sgn * w, v as number) : P(cu + w, v as number);
                        el("line", { x1: r1(a[0]), y1: r1(a[1]), x2: r1(b[0]), y2: r1(b[1]), stroke: e.hc ? ink : mix(c, ink, 0.55), "stroke-width": ds ? 1 : 1.8, "stroke-dasharray": ds as string | null }, gEl);
                    });
                }
                e.bind(gEl, target);
                if (ptsMode !== "none") {
                    const rainU = half ? u - sgn * slot * 0.25 : cu, rainW = half ? slot * 0.2 : 0;
                    g.obs.forEach(i => {
                        const ob = m.obs[i], v = valOf(ob);
                        if (ptsMode === "barcode") {
                            const w = half ? rainW / 2 : Math.max(3, near(v) * 0.5), a = P(rainU - w, v), b = P(rainU + w, v);
                            const ln = el("line", { x1: r1(a[0]), y1: r1(a[1]), x2: r1(b[0]), y2: r1(b[1]), stroke: e.hc ? ink : c, "stroke-opacity": pop, "stroke-width": 1, class: "pt" + (on(i) ? "" : " dim") }, pts);
                            if (bindPts) e.bind(ln, { key: "o" + i, obs: [i], ids: [ob.id], tip: () => obsTip(ob, c) });
                        } else {
                            const off = half ? rainU - rainW / 2 + jitter(i) * rainW : cu + (jitter(i) * 2 - 1) * near(v) * 0.8;
                            point(ob, off, c, pr, "jt", pts);
                        }
                    });
                }
                if (LB.show.value) {
                    const t = fmtL(st.md), p = P(half ? cu + sgn * near(st.md) : cu + near(st.md), st.md);
                    if (horiz) el("text", { x: r1(p[0]), y: r1(p[1] - 4), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, t);
                    else el("text", { x: r1(half ? p[0] - 4 : p[0] + 4), y: r1(p[1] + lbfs * 0.35), "text-anchor": half ? "end" : "start", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, t);
                }
            }
        });
        statLines((v, name, k) => {
            const p = VP(v);
            el("line", horiz ? { x1: r1(p) + 0.5, x2: r1(p) + 0.5, y1: r1(T), y2: r1(B) } : { x1: r1(L), x2: r1(R), y1: r1(p) + 0.5, y2: r1(p) + 0.5 }, root)
                .setAttribute("style", `stroke:${stC};stroke-width:1.5px${stDash ? ";stroke-dasharray:" + stDash : ""};pointer-events:none`);
            if (ST.label.value) el("text", horiz ? { x: r1(p + 4), y: r1(T + vfs + k * (vfs + 3)), "font-size": vfs, fill: stC, class: "lbl ref" } : { x: r1(R), y: r1(p - 4), "text-anchor": "end", "font-size": vfs, fill: stC, class: "lbl ref" }, root, `${name} ${fmtV(v)}`);
        });
    }

    /* ================================================================ parallel coordinates */
    function parallel() {
        const PA = s.parallel, D = m.measures.length;
        if (D < 2) {
            el("text", { x: r1(W / 2), y: r1(H / 2), "text-anchor": "middle", "font-size": 12, fill: textC, class: "note" }, root, e.msg("Need_Two", "Parallel coordinates needs two or more measures in Values."));
            return;
        }
        const tfs = vfs, shared = String(PA.scales.value.value) === "shared", full = String(PA.ticks.value.value) === "full";
        const T = box.t + tfs + 8 + (full ? 0 : tfs + 4), B = box.b - (full ? 4 : tfs + 6);
        const edge = Math.max(18, Math.min(60, (box.r - box.l) * 0.06));
        const L = box.l + edge + (full ? 26 : 0), R = box.r - edge;
        const X = (k: number) => L + (R - L) * k / (D - 1);
        const colVals = m.measures.map((_, k) => m.obs.map(o => o.v[k]).filter(v => isFinite(v)));
        const uLo2 = parseNum(VA.start.value), uHi2 = parseNum(VA.end.value);
        const scales = m.measures.map((mm, k) => {
            const vs = shared ? colVals.flat() : colVals[k];
            let lo = vs.length ? Math.min(...vs) : 0, hi = vs.length ? Math.max(...vs) : 1;
            if (shared && isFinite(uLo2)) lo = uLo2;
            if (shared && isFinite(uHi2)) hi = uHi2;
            const nt = nice(lo, hi, Math.max(2, Math.min(8, Math.round((B - T) / 50))));
            const a = shared && isFinite(uLo2) ? uLo2 : nt.lo, b = shared && isFinite(uHi2) && uHi2 > a ? uHi2 : nt.hi;
            const f = axisFormatter(mm.format, Number(VA.displayUnits.value) || 0, VA.decimals.value, nt.ticks, e.culture);
            return { lo: a, hi: b, ticks: nt.ticks.filter(t => t >= a - 1e-9 && t <= b + 1e-9), f, y: (v: number) => B - (Math.max(a, Math.min(b, v)) - a) / ((b - a) || 1) * (B - T) };
        });
        const ax = el("g", { class: "axes" }, root);
        m.measures.forEach((mm, k) => {
            const x = X(k), sc = scales[k], room = (R - L) / (D - 1) - 6;
            if (GR.show.value) el("line", { x1: r1(x) + 0.5, x2: r1(x) + 0.5, y1: r1(T), y2: r1(B), stroke: mix(ink, surf, 0.6), "stroke-width": Math.max(1, GR.width.value), "stroke-dasharray": dash }, ax);
            el("text", { x: r1(Math.max(box.l + textW(trunc(mm.name, room, tfs), tfs) / 2, Math.min(box.r - textW(trunc(mm.name, room, tfs), tfs) / 2, x))), y: r1(box.t + tfs), "text-anchor": "middle", "font-size": tfs, fill: textC, class: "ttl" }, ax, trunc(mm.name, Math.max(30, room), tfs));
            if (!VA.show.value) return;
            const anchor = k === D - 1 ? "end" : "start", dx = k === D - 1 ? -4 : 4;
            if (full) sc.ticks.forEach(t => el("text", { x: r1(x + dx), y: r1(sc.y(t) + tfs * 0.35), "text-anchor": anchor, "font-size": tfs - 1, fill: vC, class: "lbl val" }, ax, sc.f(t)));
            else {
                el("text", { x: r1(x), y: r1(T - 5), "text-anchor": "middle", "font-size": tfs - 1, fill: vC, class: "ax" }, ax, sc.f(sc.hi));
                el("text", { x: r1(x), y: r1(B + tfs + 2), "text-anchor": "middle", "font-size": tfs - 1, fill: vC, class: "ax" }, ax, sc.f(sc.lo));
            }
        });
        const lw = Math.max(0.5, PA.lineWidth.value), op = Math.max(0.05, PA.opacity.value / 100), smooth = String(PA.curve.value.value) === "smooth";
        const lines = el("g", { class: "lines", fill: "none", "stroke-linejoin": "round", "stroke-linecap": "round" }, root);
        const f = look.glow(); if (f && m.obs.length <= 400) lines.setAttribute("filter", f);
        const fmts = m.measures.map(mm => formatter(mm.format, 1, null, 0, e.culture));
        const bindLines = m.obs.length <= 3000;
        /* dimmed lines first, emphasized ones on top */
        const ordered = m.obs.slice().sort((a, b) => Number(on(a.i)) - Number(on(b.i)));
        ordered.slice(0, 8000).forEach(o => {
            const g = m.groups[o.g], c = e.colorOf(g);
            const segs: [number, number][][] = [[]];
            o.v.forEach((v, k) => { if (isFinite(v)) segs[segs.length - 1].push([X(k), scales[k].y(v)]); else if (segs[segs.length - 1].length) segs.push([]); });
            const d = segs.filter(sg => sg.length > 1).map(sg => (smooth ? smoothPath(sg) : "M" + sg.map(p => `${r1(p[0])},${r1(p[1])}`).join("L"))).join("");
            if (!d) return;
            const pth = el("path", { d, stroke: e.hc ? ink : c, "stroke-width": lw, "stroke-opacity": on(o.i) ? (e.active ? Math.min(1, op + 0.3) : op) : 0.08, class: "pl" }, lines);
            if (bindLines) e.bind(pth, {
                key: "o" + o.i, obs: [o.i], ids: [o.id], tip: () => {
                    const items: TipItem[] = [];
                    if (m.detailTitle) items.push({ displayName: m.detailTitle, value: o.label });
                    if (m.hasGroup) items.push({ displayName: m.groupTitle, value: g.name, color: c });
                    m.measures.forEach((mm, k) => items.push({ displayName: mm.name, value: isFinite(o.v[k]) ? fmts[k](o.v[k]) : "(Blank)" }));
                    o.tips.forEach(t => items.push({ displayName: t.name, value: t.value }));
                    return items;
                }
            });
        });
    }
}
