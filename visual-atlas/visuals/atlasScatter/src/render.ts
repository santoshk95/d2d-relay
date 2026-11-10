/*
 * Drawing for Atlas Scatter: scatter and bubble (play axis, quadrants,
 * trend and ratio lines, symmetry shading, log axes, k-means clusters,
 * drag to zoom), dot plot and Gantt (phases, progress, milestones, today
 * line, weekend shading, owner and % columns).
 */
import powerbi from "powerbi-visuals-api";
import { Model, Pt, Task } from "./model";
import { ScatterSettings } from "./settings";
import { Ctx } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix } from "./common/color";
import { colorOr, val } from "./common/cards";
import { nice, parseNum, legend, LegendItem } from "./common/chart";
import { axisFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<ScatterSettings, Model>;
/** state kept by the visual: zoom window, current play frame and the play timer */
export interface View { zoom: { x0: number; x1: number; y0: number; y1: number } | null; frame: number; timer: number | null; }
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const hash = (i: number) => { let x = (i + 1) * 0x9e3779b1; x = Math.imul(x ^ (x >>> 16), 0x85ebca6b); x ^= x >>> 13; return (x >>> 0) / 4294967296; };

/** k-means with deterministic starts (evenly spread along x), on standardized x and y */
function kmeans(p: [number, number][], k: number): number[] {
    const n = p.length; if (!n) return [];
    const mx = p.reduce((s, q) => s + q[0], 0) / n, my = p.reduce((s, q) => s + q[1], 0) / n;
    const sx = Math.sqrt(p.reduce((s, q) => s + (q[0] - mx) ** 2, 0) / n) || 1, sy = Math.sqrt(p.reduce((s, q) => s + (q[1] - my) ** 2, 0) / n) || 1;
    const z = p.map(q => [(q[0] - mx) / sx, (q[1] - my) / sy]), order = z.map((_, i) => i).sort((a, b) => z[a][0] - z[b][0]);
    let cent = Array.from({ length: Math.min(k, n) }, (_, j) => z[order[Math.floor((j + 0.5) * n / Math.min(k, n))]].slice());
    let lab = new Array(n).fill(0);
    for (let it = 0; it < 30; it++) {
        lab = z.map(q => { let b = 0, bd = Infinity; cent.forEach((c, j) => { const d = (q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2; if (d < bd) { bd = d; b = j; } }); return b; });
        cent = cent.map((c, j) => { const mem = z.filter((_, i) => lab[i] === j); return mem.length ? [mem.reduce((s, q) => s + q[0], 0) / mem.length, mem.reduce((s, q) => s + q[1], 0) / mem.length] : c; });
    }
    return lab;
}

export function render(c: C, view: View, redraw: () => void) {
    const { s, m } = c;
    if (s.type === "gantt" || (m.tasks.length && !m.pts.length)) gantt(c);
    else scatter(c, view, redraw);
}

function marker(parent: Element, shape: string, x: number, y: number, r: number, attrs: Record<string, string | number | null>) {
    if (shape === "square") return el("rect", { x: r1(x - r), y: r1(y - r), width: r1(2 * r), height: r1(2 * r), rx: r1(r * 0.2), ...attrs }, parent);
    if (shape === "diamond") return el("path", { d: `M${r1(x)},${r1(y - r * 1.25)}L${r1(x + r * 1.25)},${r1(y)}L${r1(x)},${r1(y + r * 1.25)}L${r1(x - r * 1.25)},${r1(y)}Z`, ...attrs }, parent);
    return el("circle", { cx: r1(x), cy: r1(y), r: r1(r), ...attrs }, parent);
}

/* ================================================================ scatter, bubble, dot plot */
function scatter(c: C, view: View, redraw: () => void) {
    const { W, H, s, m, root, look, t } = c, pad = 6, PT = s.points, GD = s.guides, CA = s.categoryAxis, VA = s.valueAxis, GR = s.gridlines, LB = s.labels;
    const dot = s.type === "dotplot" && m.xcats.length > 0, shape = val(PT.shape), colorBy = val(PT.colorBy), gC = colorOr(GD.color, mix(t.ink, t.surface, 0.35));
    const frames = m.frames, playing = frames.length > 1 && s.type === "scatter";
    if (view.frame >= frames.length) view.frame = 0;
    const frame = playing ? frames[view.frame] : null;
    const all = m.pts, shown = frame === null ? all : all.filter(p => p.frame === frame);
    const clusters = colorBy === "cluster" ? kmeans(all.map(p => [p.x, p.y]), Math.round(PT.clusters.value)) : [];
    const CL = ["#2a78d6", "#e66c37", "#1a9e5c", "#7c3aed", "#d9a400", "#d64550", "#0e7490", "#b45309", "#4338ca", "#15803d"];
    const colorOf = (p: Pt) => (t.hc ? t.ink : colorBy === "cluster" ? CL[clusters[p.i] % CL.length] : colorBy === "single" ? c.colorOf(m.groups[0]) : c.colorOf(m.groups[p.group] || m.groups[0]));
    const items: LegendItem[] = colorBy === "cluster" ? Array.from({ length: Math.round(PT.clusters.value) }, (_, k) => ({ key: "k" + k, name: `Cluster ${k + 1}`, color: CL[k % CL.length], on: true })) : m.groups.map(g => ({ key: g.key, name: g.name, color: c.colorOf(g), on: c.io.anyOn(g.items), target: { key: "g" + g.key, items: g.items, ids: g.id ? [g.id] : [], tip: () => [{ displayName: m.names.legend, value: g.name }] } }));
    const lg = legend(s.legend, items, colorBy === "cluster" ? "" : m.names.legend, W, H, pad, t, colorBy !== "single" && (m.names.legend !== "" || colorBy === "cluster"));
    const playH = playing ? 30 : 0, vfs = Math.max(6, VA.fontSize.value), cfs = Math.max(6, CA.fontSize.value);
    /* domains (over every frame, so the axes stay put while playing) */
    const xLog = GD.xLog.value && !dot, yLog = GD.yLog.value;
    const tr = (v: number, log: boolean) => (log ? Math.log10(Math.max(1e-9, v)) : v), un = (v: number, log: boolean) => (log ? Math.pow(10, v) : v);
    const xs = all.map(p => tr(p.x, xLog)).filter(isFinite), ys = all.map(p => tr(p.y, yLog)).filter(isFinite);
    const uLo = parseNum(VA.start.value), uHi = parseNum(VA.end.value);
    let ylo = isFinite(uLo) ? tr(uLo, yLog) : Math.min(...ys), yhi = isFinite(uHi) ? tr(uHi, yLog) : Math.max(...ys), xlo = Math.min(...xs), xhi = Math.max(...xs);
    if (GD.symmetry.value && !dot) { ylo = xlo = Math.min(xlo, ylo); yhi = xhi = Math.max(xhi, yhi); }
    /* bubbles: widen the domain by the biggest radius so no bubble is cut at the plot edge */
    if (m.hasSize && !view.zoom) {
        const rMax = PT.maxBubble.value + 2, ph = Math.max(40, H - pad * 2 - lg.top - lg.bottom - playH - cfs - 20), pw = Math.max(40, W - pad * 2 - lg.right - 60);
        const grow = (lo: number, hi: number, px: number) => { const k = rMax / Math.max(1, px - 2 * rMax), d = (hi - lo || Math.abs(hi) || 1) * k; return [lo - d, hi + d]; };
        if (!yLog) { const [a, b] = grow(ylo, yhi, ph); if (!isFinite(uLo)) ylo = ylo >= 0 && a < 0 ? 0 : a; if (!isFinite(uHi)) yhi = b; }
        if (!xLog && !dot) { const [a, b] = grow(xlo, xhi, pw); xlo = xlo >= 0 && a < 0 ? 0 : a; xhi = b; }
    }
    if (view.zoom) ({ x0: xlo, x1: xhi, y0: ylo, y1: yhi } = view.zoom);
    const ny = yLog ? { lo: Math.floor(ylo), hi: Math.ceil(yhi), ticks: Array.from({ length: Math.ceil(yhi) - Math.floor(ylo) + 1 }, (_, k) => Math.floor(ylo) + k) } : nice(ylo, yhi, 5);
    const nx = dot ? { lo: 0, hi: 1, ticks: [] as number[] } : xLog ? { lo: Math.floor(xlo), hi: Math.ceil(xhi), ticks: Array.from({ length: Math.ceil(xhi) - Math.floor(xlo) + 1 }, (_, k) => Math.floor(xlo) + k) } : nice(xlo, xhi, 6);
    if (view.zoom) { ny.lo = ylo; ny.hi = yhi; nx.lo = xlo; nx.hi = xhi; ny.ticks = ny.ticks.filter(v => v >= ylo && v <= yhi); nx.ticks = nx.ticks.filter(v => v >= xlo && v <= xhi); }
    /* a log axis spans powers of ten, so each tick gets its own display unit ($10, $1K, $100K) */
    const logFmt = (format: string | undefined) => (v: number) => formatter(format, 0, null, v, c.culture)(v);
    const fY = yLog ? logFmt(m.fmt.y) : axisFormatter(m.fmt.y, Number(VA.displayUnits.value) || 0, VA.decimals.value, ny.ticks.map(v => un(v, yLog)), c.culture);
    const fX = xLog ? logFmt(m.fmt.x) : axisFormatter(m.fmt.x, 0, null, nx.ticks.map(v => un(v, xLog)), c.culture);
    const yW = VA.show.value ? Math.max(...ny.ticks.map(v => textW(fY(un(v, yLog)), vfs))) + 8 : 0, yT = VA.title.value ? vfs + 6 : 0, xT = CA.title.value ? cfs + 6 : 0;
    const L = pad + yW + yT, R = W - pad - lg.right - 6, T = pad + Math.max(lg.top, view.zoom && GD.zoom.value && !dot ? 26 : 0) + 6, B = H - pad - lg.bottom - playH - (CA.show.value ? cfs + 8 : 0) - xT;
    const X = (v: number) => L + (tr(v, xLog) - nx.lo) / ((nx.hi - nx.lo) || 1) * (R - L), Y = (v: number) => B - (tr(v, yLog) - ny.lo) / ((ny.hi - ny.lo) || 1) * (B - T);
    const band = dot ? (R - L) / m.xcats.length : 0, XD = (p: Pt) => L + band * (m.xcats.indexOf(p.xcat) + 0.5) + (hash(p.i) - 0.5) * band * 0.5;
    const back = el("g", {}, root), grid = el("g", {}, back);
    const gridStyle = `stroke:${colorOr(GR.color, t.grid)};stroke-width:${GR.width.value}px`;
    ny.ticks.forEach(v => { const y = r1(B - (v - ny.lo) / ((ny.hi - ny.lo) || 1) * (B - T)) + 0.5; if (GR.show.value) el("line", { x1: r1(L), x2: r1(R), y1: y, y2: y, style: gridStyle }, grid); if (VA.show.value) el("text", { x: r1(L - 6), y: r1(y + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: colorOr(VA.color, t.axis), class: "ax" }, back, fY(un(v, yLog))); });
    if (dot) m.xcats.forEach((xc, k) => { const x = L + band * (k + 0.5); if (GR.show.value && k) el("line", { x1: r1(L + band * k) + 0.5, x2: r1(L + band * k) + 0.5, y1: r1(T), y2: r1(B), style: gridStyle }, grid); if (CA.show.value) c.io.bindLabel(el("text", { x: r1(x), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: colorOr(CA.color, t.axis), class: "ax" }, back, trunc(xc, band - 2, cfs)), ((ps: Pt[]) => ({ key: "x" + xc, items: ps.map(p => p.i), ids: ps.map(p => p.id).slice(0, 500), tip: () => [{ displayName: m.names.xcat, value: xc }] }))(all.filter(p => p.xcat === xc))); });
    else nx.ticks.forEach(v => { const x = r1(L + (v - nx.lo) / ((nx.hi - nx.lo) || 1) * (R - L)) + 0.5; if (GR.show.value) el("line", { x1: x, x2: x, y1: r1(T), y2: r1(B), style: gridStyle }, grid); if (CA.show.value) { const tx = fX(un(v, xLog)), hw = textW(tx, cfs) / 2; el("text", { x: r1(Math.min(W - pad - hw, Math.max(pad + hw, x))), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: colorOr(CA.color, t.axis), class: "ax" }, back, tx); } });
    if (VA.title.value) el("text", { x: r1(pad + vfs), y: r1((T + B) / 2), "text-anchor": "middle", "font-size": vfs, fill: t.text, class: "ttl", transform: `rotate(-90 ${r1(pad + vfs)} ${r1((T + B) / 2)})` }, back, trunc(m.names.y, B - T, vfs));
    if (CA.title.value) el("text", { x: r1((L + R) / 2), y: r1(B + cfs * 2 + 10), "text-anchor": "middle", "font-size": cfs, fill: t.text, class: "ttl" }, back, trunc(dot ? m.names.xcat : m.names.x, R - L, cfs));
    /* guides */
    const clip = `M${r1(L)},${r1(T)}H${r1(R)}V${r1(B)}H${r1(L)}Z`, cid = "atls-c" + (++SEQ), cp = el("clipPath", { id: cid }, back); el("path", { d: clip }, cp);
    const guides = el("g", { "clip-path": `url(#${cid})` }, back);
    const vx = shown.map(p => p.x), vy = shown.map(p => p.y), avg = (a: number[]) => a.reduce((p, q) => p + q, 0) / Math.max(1, a.length);
    if (GD.symmetry.value && !dot) {
        el("path", { d: `M${r1(X(un(nx.lo, xLog)))},${r1(Y(un(nx.lo, yLog)))}L${r1(X(un(nx.hi, xLog)))},${r1(Y(un(nx.hi, yLog)))}L${r1(L)},${r1(T)}Z`, fill: mix("#1a9e5c", t.surface, 0.9) }, guides);
        el("path", { d: `M${r1(X(un(nx.lo, xLog)))},${r1(Y(un(nx.lo, yLog)))}L${r1(X(un(nx.hi, xLog)))},${r1(Y(un(nx.hi, yLog)))}L${r1(R)},${r1(B)}Z`, fill: mix("#d64550", t.surface, 0.92) }, guides);
        el("line", { x1: r1(L), y1: r1(B), x2: r1(R), y2: r1(T), stroke: gC, "stroke-dasharray": "4 3" }, guides);
    }
    if (GD.quadrants.value && !dot) {
        const qx = isFinite(parseNum(GD.xSplit.value)) ? parseNum(GD.xSplit.value) : avg(vx), qy = isFinite(parseNum(GD.ySplit.value)) ? parseNum(GD.ySplit.value) : avg(vy);
        el("line", { x1: r1(X(qx)) + 0.5, x2: r1(X(qx)) + 0.5, y1: r1(T), y2: r1(B), stroke: gC, "stroke-dasharray": "5 4" }, guides);
        el("line", { x1: r1(L), x2: r1(R), y1: r1(Y(qy)) + 0.5, y2: r1(Y(qy)) + 0.5, stroke: gC, "stroke-dasharray": "5 4" }, guides);
        el("text", { x: r1(R - 4), y: r1(T + 12), "text-anchor": "end", "font-size": 9, fill: gC, class: "ref" }, guides, `${m.names.y} above ${formatter(m.fmt.y, 0, null, qy, c.culture)(qy)}`);
    }
    if (GD.trend.value && !dot && shown.length > 1) {
        const px = shown.map(p => tr(p.x, xLog)), py = shown.map(p => tr(p.y, yLog)), mx2 = avg(px), my2 = avg(py);
        let sxx = 0, sxy = 0; px.forEach((x, i) => { sxx += (x - mx2) ** 2; sxy += (x - mx2) * (py[i] - my2); });
        const b = sxx ? sxy / sxx : 0, a = my2 - b * mx2, x0 = nx.lo, x1 = nx.hi;
        el("line", { x1: r1(L), y1: r1(B - (a + b * x0 - ny.lo) / ((ny.hi - ny.lo) || 1) * (B - T)), x2: r1(R), y2: r1(B - (a + b * x1 - ny.lo) / ((ny.hi - ny.lo) || 1) * (B - T)), stroke: gC, "stroke-width": 1.6, "stroke-dasharray": "7 4" }, guides);
    }
    if (GD.ratio.value && !dot && !xLog && !yLog) {
        const k = vx.reduce((a, b) => a + b, 0) ? vy.reduce((a, b) => a + b, 0) / vx.reduce((a, b) => a + b, 0) : 0;
        el("line", { x1: r1(X(0)), y1: r1(Y(0)), x2: r1(X(un(nx.hi, false))), y2: r1(Y(k * un(nx.hi, false))), stroke: gC, "stroke-width": 1.4 }, guides);
        el("text", { x: r1(R - 4), y: r1(Math.max(T + 22, Y(k * un(nx.hi, false)) + 12)), "text-anchor": "end", "font-size": 9, fill: gC, class: "ref" }, guides, `Ratio ${k.toFixed(2)}`);
    }
    /* points: biggest drawn first so small ones stay on top */
    const sizes = all.map(p => p.size).filter(v => isFinite(v) && v > 0), smax = Math.max(...sizes, 1e-9);
    const rad = (p: Pt) => (m.hasSize && isFinite(p.size) && p.size > 0 ? Math.max(PT.size.value * 0.6, PT.maxBubble.value * Math.sqrt(p.size / smax)) : PT.size.value);
    const marks = el("g", { "clip-path": `url(#${cid})` }, root), sh = look.shadow(); if (sh) marks.setAttribute("filter", sh);
    const fx = formatter(m.fmt.x, 1, null, 0, c.culture), fy = formatter(m.fmt.y, 1, null, 0, c.culture), fs = formatter(m.fmt.size, 1, null, 0, c.culture);
    const tip = (p: Pt): TipItem[] => {
        const out: TipItem[] = [];
        if (m.names.details) out.push({ displayName: m.names.details, value: p.name, color: colorOf(p) });
        if (m.names.legend) out.push({ displayName: m.names.legend, value: (m.groups[p.group] || m.groups[0]).name });
        if (dot) out.push({ displayName: m.names.xcat, value: p.xcat }); else out.push({ displayName: m.names.x, value: fx(p.x) });
        out.push({ displayName: m.names.y, value: fy(p.y) });
        if (m.hasSize) out.push({ displayName: m.names.size, value: fs(p.size) });
        if (frame !== null) out.push({ displayName: m.names.play, value: p.frame });
        if (colorBy === "cluster") out.push({ displayName: "Cluster", value: String(clusters[p.i] + 1) });
        p.tips.forEach(tp => out.push({ displayName: tp.name, value: tp.value }));
        return out;
    };
    const ordered = shown.slice().sort((a, b) => rad(b) - rad(a));
    const labelBoxes: { x0: number; x1: number; y0: number; y1: number }[] = [];
    ordered.forEach(p => {
        const x = dot ? XD(p) : X(p.x), y = Y(p.y), r = rad(p), col = colorOf(p), on = c.io.on(p.i);
        const mk = marker(marks, shape, x, y, r, { fill: t.hc ? t.surface : look.flat ? col : look.fill(col, "r"), "fill-opacity": PT.opacity.value / 100, stroke: t.hc ? t.ink : mix(col, t.ink, 0.25), "stroke-width": t.hc ? 1.2 : 0.8, class: "mk" + (on ? "" : " dim") });
        c.bind(mk, { key: "p" + p.i, items: [p.i], ids: [p.id], tip: () => tip(p) } as Target);
        if (LB.show.value && m.names.details) {
            const fs2 = Math.max(6, LB.fontSize.value), w = textW(p.name, fs2), bx = { x0: x + r + 2, x1: x + r + 4 + w, y0: y - fs2 / 2, y1: y + fs2 / 2 };
            if (bx.x1 < R && !labelBoxes.some(o => !(bx.x1 < o.x0 || bx.x0 > o.x1 || bx.y1 < o.y0 || bx.y0 > o.y1))) { labelBoxes.push(bx); el("text", { x: r1(bx.x0), y: r1(y + fs2 * 0.35), "font-size": fs2, fill: colorOr(LB.color, t.text), class: "lbl" }, root, p.name); }
        }
    });
    /* drag a rectangle to zoom; double-click or the reset button zooms out */
    if (GD.zoom.value && !dot) {
        const hit = el("rect", { x: r1(L), y: r1(T), width: r1(R - L), height: r1(B - T), fill: "transparent" }, back);
        hit.addEventListener("pointerdown", ev0 => {
            const pe = ev0 as PointerEvent, rect = (root.ownerSVGElement as SVGSVGElement).getBoundingClientRect(), sx = pe.clientX - rect.left, sy = pe.clientY - rect.top;
            const rb = el("rect", { x: r1(sx), y: r1(sy), width: 0, height: 0, fill: mix(gC, t.surface, 0.8), "fill-opacity": 0.4, stroke: gC, "stroke-dasharray": "3 2" }, root);
            const move = (ev: Event) => { const e2 = ev as PointerEvent, ex = e2.clientX - rect.left, ey = e2.clientY - rect.top; rb.setAttribute("x", String(Math.min(sx, ex))); rb.setAttribute("y", String(Math.min(sy, ey))); rb.setAttribute("width", String(Math.abs(ex - sx))); rb.setAttribute("height", String(Math.abs(ey - sy))); };
            const up = (ev: Event) => {
                window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); rb.remove();
                const e2 = ev as PointerEvent, ex = e2.clientX - rect.left, ey = e2.clientY - rect.top;
                if (Math.abs(ex - sx) < 8 || Math.abs(ey - sy) < 8) return;
                const ix = (px: number) => nx.lo + (px - L) / (R - L) * (nx.hi - nx.lo), iy = (py: number) => ny.lo + (B - py) / (B - T) * (ny.hi - ny.lo);
                view.zoom = { x0: ix(Math.min(sx, ex)), x1: ix(Math.max(sx, ex)), y0: iy(Math.max(sy, ey)), y1: iy(Math.min(sy, ey)) };
                redraw();
            };
            window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
        });
        hit.addEventListener("dblclick", () => { if (view.zoom) { view.zoom = null; redraw(); } });
    }
    /* a labelled Reset zoom button in the top-right corner, clear of the plot's own labels */
    c.resetZoom(!!view.zoom && GD.zoom.value && !dot, () => { view.zoom = null; redraw(); });
    /* play axis: play/pause, a slider of frames and the current frame in large type */
    if (playing) {
        el("text", { x: r1(R - 6), y: r1(B - 8), "text-anchor": "end", "font-size": r1(Math.min(48, (B - T) * 0.25)), fill: mix(t.text, t.surface, 0.8), class: "ttl", "pointer-events": "none" }, back, frames[view.frame]);
        const py = H - pad - lg.bottom - playH / 2, x0 = L + 34, x1 = R - 10, g = el("g", {}, root);
        const btn = el("g", { class: "lg", style: "cursor:pointer", tabindex: 0, role: "button", "aria-label": view.timer ? "Pause" : "Play" }, g);
        el("circle", { class: "hit", cx: r1(L + 12), cy: r1(py), r: 11, fill: mix(t.text, t.surface, 0.92) }, btn);
        if (view.timer) el("path", { d: `M${r1(L + 8)},${r1(py - 5)}v10M${r1(L + 16)},${r1(py - 5)}v10`, stroke: t.ink, "stroke-width": 2.5 }, btn);
        else el("path", { d: `M${r1(L + 9)},${r1(py - 6)}l9,6l-9,6Z`, fill: t.ink }, btn);
        const toggle = (ev: Event) => {
            ev.stopPropagation();
            if (view.timer) { window.clearInterval(view.timer); view.timer = null; redraw(); return; }
            if (view.frame >= frames.length - 1) view.frame = 0;
            view.timer = window.setInterval(() => {
                if (view.frame >= frames.length - 1) { if (s.play.loop.value) view.frame = 0; else { if (view.timer) window.clearInterval(view.timer); view.timer = null; } }
                else view.frame++;
                redraw();
            }, Math.max(100, s.play.speed.value));
            redraw();
        };
        btn.addEventListener("click", toggle); btn.addEventListener("keydown", ev => { const k = (ev as KeyboardEvent).key; if (k === "Enter" || k === " ") toggle(ev); });
        el("line", { x1: r1(x0), x2: r1(x1), y1: r1(py), y2: r1(py), stroke: t.grid, "stroke-width": 3, "stroke-linecap": "round" }, g);
        frames.forEach((f, k) => {
            const fx2 = x0 + (x1 - x0) * k / Math.max(1, frames.length - 1), tick = el("circle", { cx: r1(fx2), cy: r1(py), r: k === view.frame ? 6 : 4, fill: k === view.frame ? c.colorOf(m.groups[0]) : t.surface, stroke: t.axis, style: "cursor:pointer" }, g);
            tick.addEventListener("click", ev => { ev.stopPropagation(); view.frame = k; redraw(); });
            if (frames.length <= 12) el("text", { x: r1(fx2), y: r1(py + 15), "text-anchor": "middle", "font-size": 8, fill: t.axis, class: "ax" }, g, f);
        });
    }
    lg.draw(root, c.bind);
}
let SEQ = 0;

/* ================================================================ Gantt */
function gantt(c: C) {
    const { W, H, s, m, root, look, t } = c, pad = 6, GT = s.gantt, CA = s.categoryAxis, cfs = Math.max(6, CA.fontSize.value);
    const tasks = m.tasks.slice().sort((a, b) => (a.start as Date).getTime() - (b.start as Date).getTime() || a.i - b.i);
    if (!tasks.length) { el("text", { x: r1(W / 2), y: r1(H / 2), "text-anchor": "middle", "font-size": 12, fill: t.text, class: "note" }, root, c.msg("Need_Tasks", "Add Task, Start date and End date for a Gantt chart.")); return; }
    const lg = legend(s.legend, m.groups.map(g => ({ key: g.key, name: g.name, color: c.colorOf(g), on: c.io.anyOn(g.items), target: { key: "g" + g.key, items: g.items, ids: g.id ? [g.id] : [], tip: () => [{ displayName: m.names.legend, value: g.name }] } })) as LegendItem[], m.names.legend, W, H, pad, t, m.names.legend !== "");
    const t0 = Math.min(...tasks.map(k => (k.start as Date).getTime())), t1 = Math.max(...tasks.map(k => (k.end || k.start as Date).getTime()));
    const span = Math.max(864e5, t1 - t0), day0 = new Date(t0), from = new Date(day0.getFullYear(), day0.getMonth(), day0.getDate() - Math.ceil(span / 864e5 * 0.02)), to = new Date(t1 + Math.max(864e5, span * 0.04));
    const nameW = Math.min(W * 0.3, Math.max(...tasks.map(k => textW(k.name, cfs)))) + 10, ownerW = GT.ownerColumn.value && m.hasOwner ? Math.min(W * 0.14, Math.max(...tasks.map(k => textW(k.owner, cfs - 1)))) + 12 : 0, pctW = GT.percentColumn.value && m.hasProgress ? textW("100%", cfs) + 12 : 0;
    const L = pad + nameW + ownerW + pctW, R = W - pad - lg.right - 4, headH = cfs * 2 + 10, T = pad + lg.top + headH, B = H - pad - lg.bottom;
    const rowH = Math.max(cfs + 6, Math.min(36, (B - T) / tasks.length)), need = tasks.length * rowH;
    if (T + need > B) c.grow(W, T + need + pad + lg.bottom);
    const X = (d: Date | number) => L + ((typeof d === "number" ? d : d.getTime()) - from.getTime()) / (to.getTime() - from.getTime()) * (R - L);
    const days = (to.getTime() - from.getTime()) / 864e5, unit = days <= 45 ? "day" : days <= 200 ? "week" : "month";
    const back = el("g", {}, root), hdr = el("g", {}, root);
    /* time header and gridlines; weekends shaded at day scale */
    for (let d = new Date(from); d <= to; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
        const x = X(d), wk = d.getDay() === 0 || d.getDay() === 6;
        if (unit === "day" && GT.weekends.value && wk) el("rect", { x: r1(x), y: r1(T), width: r1(X(d.getTime() + 864e5) - x), height: r1(Math.max(need, B - T)), fill: mix(t.text, t.surface, 0.95) }, back);
        const first = d.getDate() === 1, monday = d.getDay() === 1;
        if ((unit === "day") || (unit === "week" && monday) || (unit === "month" && first)) {
            el("line", { x1: r1(x) + 0.5, x2: r1(x) + 0.5, y1: r1(T - 4), y2: r1(T + Math.max(need, B - T)), stroke: t.grid, "stroke-width": 1 }, back);
            const lbl = unit === "month" ? MONTHS[d.getMonth()] : String(d.getDate());
            if (unit !== "day" || X(d.getTime() + 864e5) - x > textW(lbl, cfs - 1) + 2) el("text", { x: r1(x + 3), y: r1(T - 6), "font-size": Math.max(6, cfs - 1), fill: t.axis, class: "ax" }, hdr, lbl);
        }
        /* month (or year) captions: at each month start, and for the first partial month only when there is room */
        const nextMonth = new Date(d.getFullYear(), d.getMonth() + 1, 1), roomy = X(nextMonth) - x > 70;
        if (first || (d.getTime() === from.getTime() && roomy)) el("text", { x: r1(Math.max(L, x) + 3), y: r1(T - cfs - 8), "font-size": cfs, fill: t.text, class: "ttl" }, hdr, unit === "month" ? (first && d.getMonth() === 0 || d.getTime() === from.getTime() ? String(d.getFullYear()) : "") : `${MONTHS[d.getMonth()]} ${d.getFullYear()}`);
    }
    /* columns */
    el("text", { x: r1(pad), y: r1(T - 6), "font-size": cfs, fill: t.text, class: "ttl" }, hdr, m.names.task);
    if (ownerW) el("text", { x: r1(pad + nameW), y: r1(T - 6), "font-size": cfs, fill: t.text, class: "ttl" }, hdr, "Owner");
    if (pctW) el("text", { x: r1(pad + nameW + ownerW), y: r1(T - 6), "font-size": cfs, fill: t.text, class: "ttl" }, hdr, "%");
    const sh = look.shadow(), bars = el("g", sh ? { filter: sh } : {}, root), mileC = colorOr(GT.milestoneColor, t.ink), prog = val(GT.progress);
    const fmtD = (d: Date) => `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
    tasks.forEach((k, row) => {
        const y = T + row * rowH, bh = rowH * GT.barHeight.value / 100, by = y + (rowH - bh) / 2, col = t.hc ? t.ink : c.colorOf(m.groups[k.group] || m.groups[0]), on = c.io.on(k.i);
        if (row % 2) el("rect", { x: r1(pad), y: r1(y), width: r1(R - pad), height: r1(rowH), fill: mix(t.text, t.surface, 0.975) }, back);
        c.io.bindLabel(el("text", { x: r1(pad), y: r1(y + rowH / 2 + cfs * 0.35), "font-size": cfs, fill: t.text, class: "ax" }, hdr, trunc(k.name, nameW - 8, cfs)), { key: "t" + k.i, items: [k.i], ids: [k.id], tip: () => [{ displayName: m.names.task || "Task", value: k.name }] });
        if (ownerW) el("text", { x: r1(pad + nameW), y: r1(y + rowH / 2 + cfs * 0.35), "font-size": cfs - 1, fill: t.axis, class: "ax" }, hdr, trunc(k.owner, ownerW - 8, cfs - 1));
        if (pctW && !isNaN(k.progress)) el("text", { x: r1(pad + nameW + ownerW), y: r1(y + rowH / 2 + cfs * 0.35), "font-size": cfs - 1, fill: t.axis, class: "ax" }, hdr, Math.round(k.progress * 100) + "%");
        const g = el("g", { class: "mk" + (on ? "" : " dim") }, bars);
        const milestone = !k.end || k.end.getTime() === (k.start as Date).getTime();
        if (milestone) { const x = X(k.start as Date), r = bh * 0.55; el("path", { d: `M${r1(x)},${r1(by + bh / 2 - r)}l${r1(r)},${r1(r)}l${r1(-r)},${r1(r)}l${r1(-r)},${r1(-r)}Z`, fill: mileC }, g); }
        else {
            const x0 = X(k.start as Date), x1 = X(k.end as Date), w = Math.max(2, x1 - x0), rr = Math.min(GT.radius.value, bh / 2);
            if (prog === "fill" && !isNaN(k.progress)) {
                el("rect", { x: r1(x0), y: r1(by), width: r1(w), height: r1(bh), rx: r1(rr), fill: mix(col, t.surface, 0.75), stroke: col, "stroke-width": 1 }, g);
                el("rect", { x: r1(x0), y: r1(by), width: r1(Math.max(0, w * Math.min(1, k.progress))), height: r1(bh), rx: r1(rr), fill: t.hc ? t.ink : look.fill(col, "v") }, g);
            } else {
                el("rect", { x: r1(x0), y: r1(by), width: r1(w), height: r1(bh), rx: r1(rr), fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : "none" }, g);
                if (prog === "overlay" && !isNaN(k.progress)) el("rect", { x: r1(x0), y: r1(by + bh * 0.38), width: r1(w * Math.min(1, k.progress)), height: r1(bh * 0.24), rx: 1, fill: mix(col, "#000000", 0.45) }, g);
            }
        }
        c.bind(g, { key: "t" + k.i, items: [k.i], ids: [k.id], tip: () => {
            const out: TipItem[] = [{ displayName: m.names.task, value: k.name, color: col }, { displayName: "Start", value: fmtD(k.start as Date) }];
            if (k.end && !milestone) out.push({ displayName: "End", value: fmtD(k.end) }, { displayName: "Days", value: String(Math.round((k.end.getTime() - (k.start as Date).getTime()) / 864e5)) });
            if (m.names.legend) out.push({ displayName: m.names.legend, value: (m.groups[k.group] || m.groups[0]).name });
            if (k.owner) out.push({ displayName: "Owner", value: k.owner });
            if (!isNaN(k.progress)) out.push({ displayName: "Complete", value: Math.round(k.progress * 100) + "%" });
            k.tips.forEach(tp => out.push({ displayName: tp.name, value: tp.value }));
            return out;
        } });
    });
    /* today line (only when today is in range) */
    const now = Date.now();
    if (GT.today.value && now >= from.getTime() && now <= to.getTime()) { const x = r1(X(now)) + 0.5; el("line", { x1: x, x2: x, y1: r1(T - 4), y2: r1(T + Math.max(need, B - T)), stroke: "#d64550", "stroke-width": 1.5 }, root); el("text", { x: r1(x + 3), y: r1(T + 10), "font-size": 9, fill: "#d64550", class: "ref" }, root, "Today"); }
    lg.draw(root, c.bind);
}
