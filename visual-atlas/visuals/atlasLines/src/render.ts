/*
 * Drawing for Atlas Lines: line, area, stacked and 100% stacked area, and
 * line-and-column combos (secondary axis), with markers, dashed series,
 * end labels, focus, an error band, analytics (trend, min/max, average,
 * target zone, forecast with a 95% band, anomalies) and a zoom slider.
 */
import powerbi from "powerbi-visuals-api";
import { Model, LSer, LCell } from "./model";
import { LinesSettings } from "./settings";
import { Ctx } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix } from "./common/color";
import { colorOr, val } from "./common/cards";
import { domain, tickWidth, valueAxis, legend, LegendItem, parseNum, Domain } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<LinesSettings, Model>;
/** the zoom window (first and last visible category), kept by the visual */
/** the zoom window (first and last visible category), kept by the visual; key and saved: the selection it zoomed to and the window before it */
export interface View { a: number; b: number; n: number; key?: string; saved?: [number, number] | null; }

/** least-squares line through (x, y) points: y = a + b·x, with the residual spread */
function fit(xs: number[], ys: number[]) {
    const n = xs.length, mx = xs.reduce((s, x) => s + x, 0) / n, my = ys.reduce((s, y) => s + y, 0) / n;
    let sxx = 0, sxy = 0; xs.forEach((x, i) => { sxx += (x - mx) ** 2; sxy += (x - mx) * (ys[i] - my); });
    const b = sxx ? sxy / sxx : 0, a = my - b * mx;
    const se = Math.sqrt(xs.reduce((s, x, i) => s + (ys[i] - (a + b * x)) ** 2, 0) / Math.max(1, n - 2));
    return { a, b, se, mx, sxx, n };
}

export function render(c: C, view: View, redraw: () => void, topBand: number) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6, LN = s.lines, AN = s.analytics, LB = s.labels, CA = s.categoryAxis, VA = s.valueAxis, GR = s.gridlines;
    const combo = type.startsWith("combo"), stacked = type === "stackedArea" || type === "percentArea", percent = type === "percentArea", area = type.includes("rea");
    const cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value), cC = colorOr(CA.color, t.axis), aC = colorOr(AN.color, mix(t.ink, t.surface, 0.3));
    const focus = LN.focus.value.trim().toLowerCase(), gray = mix(t.text, t.surface, 0.75), dashed = LN.dashed.value.split(",").map(x => x.trim().toLowerCase()).filter(x => x);
    const N = m.cats.length;
    if (view.n !== N) { view.a = 0; view.b = N - 1; view.n = N; view.key = ""; view.saved = null; }
    zoomToSelection(c, view, N);
    const a0 = Math.max(0, Math.min(view.a, N - 1)), b0 = Math.max(a0, Math.min(view.b, N - 1)), vis = Array.from({ length: b0 - a0 + 1 }, (_, k) => a0 + k);
    const colSeries = combo ? m.series.filter(sr => !sr.line) : [], lineSeries = combo ? m.series.filter(sr => sr.line) : m.series;
    const colorOf = (sr: LSer) => (t.hc ? t.ink : focus && sr.name.toLowerCase() !== focus ? gray : c.colorOf(sr));
    const fmtT = (sr: LSer) => formatter(sr.format, 1, null, 0, c.culture);
    const fmtL = (sr: LSer) => labelFormatter(sr.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...sr.v.filter(v => !isNaN(v)).map(Math.abs)), c.culture);

    /* legend or end labels */
    const endLabels = LN.endLabels.value && m.series.length >= 1;
    const lg = legend(s.legend, m.series.map(sr => ({ key: sr.key, name: sr.name, color: colorOf(sr), on: c.io.anyOn(sr.items), shape: sr.line || !combo ? "line" : "box", target: { key: "s" + sr.key, items: sr.items, ids: sr.id ? [sr.id] : [], tip: () => [{ displayName: m.legendTitle || "Series", value: sr.name }] } })) as LegendItem[], m.legendTitle, W, H, pad, t, !endLabels);
    const zoomH = s.chart.zoom.value && N > 3 ? 30 : 0;
    const F = (type === "line" || type === "area") && b0 === N - 1 ? Math.max(0, Math.round(AN.forecast.value)) : 0;

    /* stacks (areas) or columns: value-space bottoms and tops per category */
    const stackOf = (list: LSer[], pct: boolean) => {
        const lo: number[][] = list.map(() => []), hi: number[][] = list.map(() => []);
        m.cats.forEach((_, ci) => {
            const tot = pct ? list.reduce((s2, sr) => s2 + Math.abs(isNaN(sr.v[ci]) ? 0 : sr.v[ci]), 0) || 1 : 1;
            let p = 0, q = 0;
            list.forEach((sr, k) => { const v = isNaN(sr.v[ci]) ? 0 : sr.v[ci] / tot; if (v >= 0) { lo[k][ci] = p; p += v; hi[k][ci] = p; } else { lo[k][ci] = q; q += v; hi[k][ci] = q; } });
        });
        return { lo, hi };
    };
    const areaStack = stacked ? stackOf(m.series, percent) : null;
    const colStack = combo && type === "comboStacked" ? stackOf(colSeries, false) : null;

    /* value domains: left (lines, areas or columns) and right (combo lines on a secondary axis) */
    const leftVals: number[] = [], rightVals: number[] = [];
    const secondary = combo && LN.secondary.value && lineSeries.length > 0 && colSeries.length > 0;
    const pushStack = (st: { lo: number[][]; hi: number[][] }, ci: number) => { st.hi.forEach(h => leftVals.push(h[ci])); st.lo.forEach(l => leftVals.push(l[ci])); };
    vis.forEach(ci => {
        if (stacked && areaStack) pushStack(areaStack, ci);
        else if (combo) {
            if (colStack) pushStack(colStack, ci); else colSeries.forEach(sr => leftVals.push(sr.v[ci]));
            lineSeries.forEach(sr => (secondary ? rightVals : leftVals).push(sr.v[ci]));
        } else m.series.forEach(sr => leftVals.push(sr.v[ci]));
        if (m.lower) leftVals.push(m.lower[ci]);
        if (m.upper) leftVals.push(m.upper[ci]);
    });
    const tgt = parseNum(AN.target.value); if (isFinite(tgt)) leftVals.push(tgt);
    /* forecast first (it widens the domain) */
    const base = lineSeries[0], fc: { ci: number; y: number; lo: number; hi: number }[] = [];
    let fitAll: ReturnType<typeof fit> | null = null;
    if (base) {
        const xs: number[] = [], ys: number[] = []; base.v.forEach((v, i) => { if (!isNaN(v)) { xs.push(i); ys.push(v); } });
        if (xs.length >= 3) {
            fitAll = fit(xs, ys);
            /* the forecast starts at the last actual value and follows the trend slope; the 95% band widens with the horizon */
            const lastV = ys[ys.length - 1];
            for (let k = 1; k <= F; k++) { const x = N - 1 + k, y = lastV + fitAll.b * (x - xs[xs.length - 1]), h = 1.96 * fitAll.se * Math.sqrt(k); fc.push({ ci: x, y, lo: y - h, hi: y + h }); leftVals.push(y - h, y + h); }
        }
    }
    const fin = (a: number[]) => a.filter(v => isFinite(v));
    const catH = CA.show.value ? cfs + 8 : 0, T = pad + Math.max(lg.top, topBand, zoomH && (a0 > 0 || b0 < N - 1) ? 30 : 0) + (LB.show.value ? lbfs + 4 : 4), B = H - pad - lg.bottom - catH - zoomH - (zoomH ? 6 : 0);
    const dL: Domain = percent ? { lo: 0, hi: 1, ticks: [0, 0.25, 0.5, 0.75, 1], f: (v: number) => Math.round(v * 100) + "%" } : domain(Math.min(...fin(leftVals)), Math.max(...fin(leftVals)), B - T, 44, VA, (combo ? colSeries[0] || m.series[0] : m.series[0]).format, c.culture, area || combo || stacked);
    const dR: Domain | null = secondary ? domain(Math.min(...fin(rightVals)), Math.max(...fin(rightVals)), B - T, 44, VA, lineSeries[0].format, c.culture, false) : null;
    const endW = endLabels ? Math.min(W * 0.25, Math.max(...m.series.map(sr => textW(sr.name, lbfs)))) + 10 : 0;
    const L = pad + tickWidth(dL, VA), R = W - pad - lg.right - endW - (dR ? tickWidth(dR, VA) : 0) - (look.is3d && combo ? 5 : 0);
    const slots = vis.length + F, step = (R - L) / Math.max(1, slots), X = (ci: number) => L + step * (ci - a0 + 0.5);
    const YL = (v: number) => B - (v - dL.lo) / (dL.hi - dL.lo) * (B - T), YR = dR ? (v: number) => B - (v - dR.lo) / (dR.hi - dR.lo) * (B - T) : YL;
    valueAxis(root, dL, YL, { L, R, T, B }, true, VA, GR, t);
    if (dR && VA.show.value) dR.ticks.forEach(v => el("text", { x: r1(R + 6), y: r1(YR(v) + Math.max(6, VA.fontSize.value) * 0.35), "font-size": Math.max(6, VA.fontSize.value), fill: colorOr(VA.color, t.axis), class: "ax" }, root, dR.f(v)));

    /* layers: bands under the marks would let an area swallow every click, so the hover bands sit above the lines and areas, under the markers */
    const back = el("g", {}, root), sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), bands = el("g", {}, root), over = el("g", {}, root), labels = el("g", {}, root);
    /* target zone: shaded from the target value up */
    if (isFinite(tgt)) { const y = YL(tgt); el("rect", { x: r1(L), y: r1(T), width: r1(R - L), height: r1(Math.max(0, y - T)), fill: mix(aC, t.surface, 0.9) }, back); el("line", { x1: r1(L), x2: r1(R), y1: r1(y) + 0.5, y2: r1(y) + 0.5, stroke: aC, "stroke-width": 1.2, "stroke-dasharray": "5 3" }, back); el("text", { x: r1(R - 4), y: r1(y - 4), "text-anchor": "end", "font-size": 9, fill: aC, class: "ref" }, labels, `Target ${dL.f(tgt)}`); }
    /* error band */
    if (m.lower && m.upper) {
        const top: string[] = [], bot: string[] = [];
        vis.forEach(ci => { const lo = m.lower ? m.lower[ci] : NaN, hi = m.upper ? m.upper[ci] : NaN; if (isFinite(lo) && isFinite(hi)) { top.push(`${r1(X(ci))},${r1(YL(hi))}`); bot.unshift(`${r1(X(ci))},${r1(YL(lo))}`); } });
        if (top.length > 1) el("path", { d: `M${top.join("L")}L${bot.join("L")}Z`, fill: mix(colorOf(m.series[0]), t.surface, 0.8), opacity: 0.85 }, back);
    }

    /* path through points with gaps at blanks: straight, smooth or stepped */
    const curve = val(s.chart.curve);
    const pathOf = (pts: ([number, number] | null)[]) => {
        let d = "", prev: [number, number] | null = null;
        pts.forEach(p => {
            if (!p) { prev = null; return; }
            if (!prev) d += `M${r1(p[0])},${r1(p[1])}`;
            else if (curve === "smooth") { const mx = (prev[0] + p[0]) / 2; d += `C${r1(mx)},${r1(prev[1])} ${r1(mx)},${r1(p[1])} ${r1(p[0])},${r1(p[1])}`; }
            else if (curve === "step") { const mx = (prev[0] + p[0]) / 2; d += `H${r1(mx)}V${r1(p[1])}H${r1(p[0])}`; }
            else d += `L${r1(p[0])},${r1(p[1])}`;
            prev = p;
        });
        return d;
    };
    const seriesT = (sr: LSer): Target => ({ key: "s" + sr.key, items: sr.items, ids: sr.id ? [sr.id] : [], tip: () => [{ displayName: m.legendTitle || "Series", value: sr.name, color: colorOf(sr) }] });
    const cellT = (cl: LCell): Target => ({ key: "i" + cl.i, items: [cl.i], ids: [cl.id], tip: () => catTip(cl.c) });
    const catTip = (ci: number): TipItem[] => {
        const out: TipItem[] = m.levelNames.map((nm, k) => ({ displayName: nm, value: m.cats[ci].path[k] }));
        m.series.forEach(sr => {
            const v = sr.v[ci]; if (isNaN(v)) return;
            const share = percent && areaStack ? `  (${Math.round((areaStack.hi[sr.i][ci] - areaStack.lo[sr.i][ci]) * 100)}%)` : "";
            out.push({ displayName: sr.name, value: fmtT(sr)(v) + share, color: colorOf(sr) });
        });
        if (m.lower && m.upper && isFinite(m.lower[ci])) out.push({ displayName: "Range", value: `${fmtT(m.series[0])(m.lower[ci])} – ${fmtT(m.series[0])(m.upper[ci])}` });
        const first = m.series[0].cells[ci]; if (first >= 0) m.cells[first].tips.forEach(tp => out.push({ displayName: tp.name, value: tp.value }));
        return out;
    };

    /* columns (combo) */
    if (combo) {
        const sp = Math.min(0.9, LN.columnSpacing.value / 100), bw = step * (1 - sp), rad = look.is3d ? 0 : LN.radius.value;
        colSeries.forEach((sr, k) => {
            const col = colorOf(sr);
            vis.forEach(ci => {
                const ix = sr.cells[ci]; if (ix < 0) return;
                const cl = m.cells[ix], lo = colStack ? colStack.lo[k][ci] : 0, hi = colStack ? colStack.hi[k][ci] : cl.v;
                const w = colStack ? bw : bw / colSeries.length, x = colStack ? X(ci) - bw / 2 : X(ci) - bw / 2 + w * k, y0 = YL(Math.max(lo, hi)), h = Math.max(0.5, Math.abs(YL(lo) - YL(hi)));
                const g = el("g", { class: "mk" + (c.io.on(cl.i) ? "" : " dim") }, marks);
                if (look.is3d) { el("path", { d: `M${r1(x)},${r1(y0)}l4,-3h${r1(w - 1)}l-4,3Z`, fill: look.top(col) }, g); el("path", { d: `M${r1(x + w - 1)},${r1(y0)}l4,-3v${r1(h)}l-4,3Z`, fill: look.side(col) }, g); }
                el("rect", { x: r1(x), y: r1(y0), width: r1(Math.max(0.5, w - 1)), height: r1(h), rx: r1(Math.min(rad, w / 3, h / 2)), fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : "none" }, g);
                c.bind(g, cellT(cl));
                if (LB.show.value && !colStack && h > 0) el("text", { x: r1(x + w / 2), y: r1(y0 - 3), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "lbl" }, labels, trunc(fmtL(sr)(cl.v), step, lbfs));
            });
        });
    }

    /* lines and areas */
    const drawn = combo ? lineSeries : m.series;
    const order = drawn.slice().sort((p, q) => Number(!focus || p.name.toLowerCase() === focus) - Number(!focus || q.name.toLowerCase() === focus));
    order.forEach(sr => {
        const col = colorOf(sr), Y = combo && sr.line && dR ? YR : YL, k = sr.i, on = c.io.anyOn(sr.items);
        const pts = vis.map(ci => { const v = stacked && areaStack ? areaStack.hi[k][ci] : sr.v[ci]; return isNaN(sr.v[ci]) && !stacked ? null : [X(ci), Y(v)] as [number, number]; });
        const g = el("g", { class: "grp" + (on ? "" : " dim") }, marks);
        /* part of the series selected or highlighted: the rest of the line and area fades, the selected stretch is drawn on top */
        const act = c.io.active, inAct = (ci: number) => !!act && sr.cells[ci] >= 0 && act.has(sr.cells[ci]);
        const part = on && !!act && vis.some(ci => inAct(ci)) && vis.some(ci => sr.cells[ci] >= 0 && !inAct(ci)), fade = part ? 0.28 : 1;
        if (area) {
            const bot = vis.map(ci => [X(ci), Y(stacked && areaStack ? areaStack.lo[k][ci] : Math.max(dL.lo, Math.min(dL.hi, 0)))] as [number, number]);
            const okPts = pts.filter(p => p) as [number, number][];
            if (okPts.length > 1) el("path", { d: pathOf(pts) + "L" + pathOf(bot.slice().reverse()).slice(1) + "Z", fill: t.hc ? t.surface : look.flat ? col : look.fill(col, "v"), "fill-opacity": (stacked ? Math.max(0.55, LN.areaOpacity.value / 100) : LN.areaOpacity.value / 100) * fade, stroke: "none" }, g);
        }
        el("path", { d: pathOf(pts), fill: "none", stroke: col, "stroke-opacity": fade, "stroke-width": LN.width.value, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": dashed.includes(sr.name.toLowerCase()) ? "6 4" : null }, g);
        if (part) {
            const sp = vis.map((ci, j) => (inAct(ci) ? pts[j] : null));
            el("path", { d: pathOf(sp), fill: "none", stroke: col, "stroke-width": LN.width.value + 0.6, "stroke-linejoin": "round", "stroke-linecap": "round", class: "sel-run" }, g);
            /* a selected point with no selected neighbour still shows */
            sp.forEach((p, j) => { if (p && !sp[j - 1] && !sp[j + 1]) el("circle", { cx: r1(p[0]), cy: r1(p[1]), r: r1(LN.width.value + 1.5), fill: col }, g); });
        }
        c.bind(g, seriesT(sr));
        const mk = val(LN.markers), r = LN.markerSize.value;
        vis.forEach((ci, j) => {
            const p = pts[j], ix = sr.cells[ci]; if (!p || ix < 0) return;
            const isLast = j === vis.length - 1 || vis.slice(j + 1).every(cc => sr.cells[cc] < 0);
            if (mk === "all" || (mk === "last" && isLast)) {
                const dot = el("circle", { cx: r1(p[0]), cy: r1(p[1]), r: r1(r), fill: t.surface, stroke: col, "stroke-width": 2, class: "mk" + (c.io.on(ix) ? "" : " dim") }, over);
                c.bind(dot, cellT(m.cells[ix]));
            }
            if (LB.show.value && (!combo || sr.line)) el("text", { x: r1(p[0]), y: r1(p[1] - Math.max(r, 3) - 4), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "lbl" }, labels, fmtL(sr)(sr.v[ci]));
            if (endLabels && isLast) el("text", { x: r1(R + (dR ? tickWidth(dR, VA) : 0) + 8), y: r1(p[1] + lbfs * 0.35), "font-size": lbfs + 1, fill: col, class: "ttl" }, labels, trunc(sr.name, endW - 8, lbfs + 1));
        });
    });

    /* analytics on the first line */
    if (base && !percent) {
        const Y = combo && dR ? YR : YL, pts = vis.filter(ci => !isNaN(base.v[ci]));
        const vs = pts.map(ci => base.v[ci]);
        const ref = (v: number, text: string, dash: string) => { const y = r1(Y(v)) + 0.5; el("line", { x1: r1(L), x2: r1(R), y1: y, y2: y, stroke: aC, "stroke-width": 1.2, "stroke-dasharray": dash }, over); el("text", { x: r1(L + 4), y: r1(Y(v) - 4), "font-size": 9, fill: aC, class: "lbl ref" }, labels, text); };
        if (AN.minMax.value && vs.length) { ref(Math.max(...vs), `Max ${fmtT(base)(Math.max(...vs))}`, "2 3"); ref(Math.min(...vs), `Min ${fmtT(base)(Math.min(...vs))}`, "2 3"); }
        if (AN.average.value && vs.length) ref(vs.reduce((a, b) => a + b, 0) / vs.length, `Average ${fmtT(base)(vs.reduce((a, b) => a + b, 0) / vs.length)}`, "6 3");
        if (AN.trend.value && pts.length > 1) { const f = fit(pts, vs); el("line", { x1: r1(X(pts[0])), y1: r1(Y(f.a + f.b * pts[0])), x2: r1(X(pts[pts.length - 1])), y2: r1(Y(f.a + f.b * pts[pts.length - 1])), stroke: aC, "stroke-width": 1.6, "stroke-dasharray": "7 4" }, over); }
        if (fc.length && fitAll) {
            const lastX = N - 1, lastV = base.v[lastX], col = colorOf(base);
            const top = [`${r1(X(lastX))},${r1(Y(lastV))}`].concat(fc.map(p => `${r1(X(p.ci))},${r1(Y(p.hi))}`)), bot = fc.map(p => `${r1(X(p.ci))},${r1(Y(p.lo))}`).reverse().concat([`${r1(X(lastX))},${r1(Y(lastV))}`]);
            el("path", { d: `M${top.join("L")}L${bot.join("L")}Z`, fill: mix(col, t.surface, 0.8) }, back);
            el("path", { d: `M${r1(X(lastX))},${r1(Y(lastV))}` + fc.map(p => `L${r1(X(p.ci))},${r1(Y(p.y))}`).join(""), fill: "none", stroke: col, "stroke-width": LN.width.value, "stroke-dasharray": "4 3" }, over);
            el("text", { x: r1(X(fc[fc.length - 1].ci)), y: r1(Y(fc[fc.length - 1].hi) - 4), "text-anchor": "end", "font-size": 9, fill: t.axis, class: "ax" }, labels, `Forecast (95% band)`);
        }
        if (AN.anomalies.value && vs.length >= 5) {
            /* expected value: median of the neighbors (the point itself left out, so a spike can't hide);
               spread: 1.4826 × the median absolute deviation; an anomaly scores above 3.5 (Iglewicz and Hoaglin's modified z-score) */
            const med = (a: number[]) => { const q = a.slice().sort((x, y) => x - y), h = q.length >> 1; return q.length % 2 ? q[h] : (q[h - 1] + q[h]) / 2; };
            const ma = pts.map((_, j) => med(vs.slice(Math.max(0, j - 3), j).concat(vs.slice(j + 1, j + 4))));
            const sd = Math.max(1e-9, 1.4826 * med(vs.map((v, j) => Math.abs(v - ma[j]))));
            const top = pts.map((ci, j) => `${r1(X(ci))},${r1(Y(ma[j] + 3.5 * sd))}`), bot = pts.map((ci, j) => `${r1(X(ci))},${r1(Y(ma[j] - 3.5 * sd))}`).reverse();
            el("path", { d: `M${top.join("L")}L${bot.join("L")}Z`, fill: mix(aC, t.surface, 0.94), opacity: 0.8 }, back);
            pts.forEach((ci, j) => { if (Math.abs(vs[j] - ma[j]) > 3.5 * sd) { el("circle", { cx: r1(X(ci)), cy: r1(Y(vs[j])), r: 6, fill: "none", stroke: "#d64550", "stroke-width": 2.2 }, over); el("circle", { cx: r1(X(ci)), cy: r1(Y(vs[j])), r: 2.6, fill: "#d64550", class: "anomaly" }, over); } });
        }
    }

    /* hover bands: one per category, the tooltip lists every series */
    vis.forEach(ci => {
        const items = m.series.map(sr => sr.cells[ci]).filter(i => i >= 0);
        const hb = el("rect", { x: r1(X(ci) - step / 2), y: r1(T), width: r1(step), height: r1(B - T), fill: "transparent", class: "band" }, bands);
        c.bind(hb, { key: "c" + ci, items, ids: items.map(i => m.cells[i].id), tip: () => catTip(ci), wide: true });
    });
    /* click and drag across the plot selects every category in between (Ctrl adds to the selection) */
    bands.addEventListener("pointerdown", ev0 => {
        const pe = ev0 as PointerEvent, svg = root.ownerSVGElement; if (pe.button !== 0 || !svg) return;
        const box0 = svg.getBoundingClientRect(), x0 = pe.clientX - box0.left;
        let x1 = x0, sweep: Element | null = null;
        const ciAt = (x: number) => Math.max(a0, Math.min(b0, Math.round((x - L) / step - 0.5) + a0));
        const draw = () => {
            const ca = ciAt(Math.min(x0, x1)), cb = ciAt(Math.max(x0, x1)), xa = X(ca) - step / 2, xb = X(cb) + step / 2;
            if (!sweep) sweep = el("rect", { y: r1(T), height: r1(B - T), fill: mix(colorOf(m.series[0]), t.surface, 0.7), "fill-opacity": 0.35, stroke: colorOf(m.series[0]), "stroke-dasharray": "3 2", "pointer-events": "none" }, over);
            sweep.setAttribute("x", String(r1(xa))); sweep.setAttribute("width", String(r1(xb - xa)));
        };
        const move = (ev: Event) => { x1 = (ev as PointerEvent).clientX - box0.left; if (sweep || Math.abs(x1 - x0) > 6) draw(); };
        const up = (ev: Event) => {
            window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
            if (!sweep) return;
            sweep.remove();
            const ca = ciAt(Math.min(x0, x1)), cb = ciAt(Math.max(x0, x1)), items: number[] = [];
            for (let ci = ca; ci <= cb; ci++) m.series.forEach(sr => { if (sr.cells[ci] >= 0) items.push(sr.cells[ci]); });
            const me = ev as PointerEvent;
            c.io.selectMany(`r${ca}-${cb}`, items, items.map(i => m.cells[i].id).slice(0, 500), me.ctrlKey || me.metaKey);
        };
        window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
    });

    /* category labels (skip any that would overlap) */
    if (CA.show.value) {
        let right = -Infinity;
        vis.forEach(ci => { const txt = m.cats[ci].path.length > 1 ? m.cats[ci].path.join(" › ") : m.cats[ci].label, w = textW(txt, cfs), left = X(ci) - w / 2; if (left < right + 6) return; right = left + w; const tx = el("text", { x: r1(X(ci)), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, labels, txt); const its = m.series.map(sr => sr.cells[ci]).filter(i => i >= 0); c.io.bindLabel(tx, { key: "c" + ci, items: its, ids: [m.cats[ci].id], tip: () => catTip(ci) }); });
        fc.forEach((p, k) => { if (k === fc.length - 1) el("text", { x: r1(X(p.ci)), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: t.axis, class: "ax" }, labels, `+${k + 1}`); });
    }

    lg.draw(root, c.bind);

    /* zoom slider: an overview of the first series with two handles */
    if (zoomH) {
        const zy = H - pad - lg.bottom - zoomH, zx0 = L, zx1 = R, zg = el("g", { class: "zoom" }, root), sr = m.series[0];
        const ZX = (ci: number) => zx0 + (zx1 - zx0) * ci / Math.max(1, N - 1), vv = sr.v.filter(v => !isNaN(v)), vlo = Math.min(...vv), vhi = Math.max(...vv);
        el("rect", { x: r1(zx0), y: r1(zy), width: r1(zx1 - zx0), height: zoomH, rx: 4, fill: mix(t.text, t.surface, 0.95) }, zg);
        el("path", { d: pathOf(sr.v.map((v, ci) => (isNaN(v) ? null : [ZX(ci), zy + zoomH - 4 - (v - vlo) / ((vhi - vlo) || 1) * (zoomH - 8)] as [number, number]))), fill: "none", stroke: mix(colorOf(sr), t.surface, 0.3), "stroke-width": 1.2 }, zg);
        const win = el("rect", { x: r1(ZX(a0)), y: r1(zy), width: r1(Math.max(4, ZX(b0) - ZX(a0))), height: zoomH, fill: mix(colorOf(sr), t.surface, 0.8), "fill-opacity": 0.6, stroke: colorOf(sr), "stroke-width": 1, style: "cursor:grab" }, zg);
        const handle = (ci: number, which: "a" | "b") => {
            const h = el("rect", { x: r1(ZX(ci) - 4), y: r1(zy + 4), width: 8, height: zoomH - 8, rx: 3, fill: t.surface, stroke: colorOf(sr), "stroke-width": 1.5, style: "cursor:ew-resize", tabindex: 0, role: "slider", "aria-label": which === "a" ? "Zoom start" : "Zoom end" }, zg);
            drag(h, which);
            h.addEventListener("keydown", ev => { const k = (ev as KeyboardEvent).key, d = k === "ArrowLeft" ? -1 : k === "ArrowRight" ? 1 : 0; if (!d) return; ev.preventDefault(); if (which === "a") view.a = Math.max(0, Math.min(view.b - 1, view.a + d)); else view.b = Math.min(N - 1, Math.max(view.a + 1, view.b + d)); redraw(); });
        };
        /* dragging a handle moves one end; dragging the window moves both. The pointer is captured by the
           <svg> (it survives the redraws, the handle does not), so the drag keeps going outside the slider. */
        const svg = root.ownerSVGElement;
        function drag(e: Element, which: "a" | "b" | "both") {
            (e as SVGElement).style.touchAction = "none";
            e.addEventListener("pointerdown", ev0 => {
                const pe = ev0 as PointerEvent, x0 = pe.clientX, A = view.a, Bv = view.b, per = (zx1 - zx0) / Math.max(1, N - 1);
                pe.stopPropagation(); pe.preventDefault();
                const tgt: Element = svg || e;
                try { tgt.setPointerCapture(pe.pointerId); } catch { /* not supported: window listeners still work */ }
                let last = "";
                const move = (ev: Event) => {
                    const dx = Math.round(((ev as PointerEvent).clientX - x0) / per);
                    if (which === "a") view.a = Math.max(0, Math.min(Bv - 1, A + dx));
                    else if (which === "b") view.b = Math.min(N - 1, Math.max(A + 1, Bv + dx));
                    else { const span = Bv - A, na = Math.max(0, Math.min(N - 1 - span, A + dx)); view.a = na; view.b = na + span; }
                    const now = view.a + ":" + view.b; if (now !== last) { last = now; redraw(); }
                };
                const up = (ev: Event) => {
                    try { tgt.releasePointerCapture((ev as PointerEvent).pointerId); } catch { /* already released */ }
                    tgt.removeEventListener("pointermove", move); tgt.removeEventListener("pointerup", up); tgt.removeEventListener("pointercancel", up);
                    window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
                };
                tgt.addEventListener("pointermove", move); tgt.addEventListener("pointerup", up); tgt.addEventListener("pointercancel", up);
                window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
            });
            /* double-click: show everything again */
            e.addEventListener("dblclick", ev => { ev.stopPropagation(); view.a = 0; view.b = N - 1; redraw(); });
        }
        drag(win, "both");
        handle(a0, "a"); handle(b0, "b");
        /* the slider track: double-click resets, a click jumps the window there */
        const track = zg.firstChild as Element;
        track.addEventListener("dblclick", ev => { ev.stopPropagation(); view.a = 0; view.b = N - 1; redraw(); });
        track.addEventListener("click", ev => {
            ev.stopPropagation();
            const r = (track as SVGGraphicsElement).getBoundingClientRect(), ci = Math.round((N - 1) * ((ev as MouseEvent).clientX - r.left) / Math.max(1, r.width)), span = b0 - a0;
            view.a = Math.max(0, Math.min(N - 1 - span, ci - Math.round(span / 2))); view.b = view.a + span; redraw();
        });
        /* mouse wheel over the plot zooms around the pointer; double-click on the plot shows everything */
        bands.addEventListener("wheel", ev => {
            const we = ev as WheelEvent, r = (bands as SVGGraphicsElement).getBoundingClientRect(); if (!r.width) return;
            we.preventDefault();
            const span = b0 - a0, f = Math.max(0, Math.min(1, (we.clientX - r.left) / r.width)), at = a0 + f * span;
            const ns = Math.max(2, Math.min(N - 1, Math.round(span * (we.deltaY > 0 ? 1.25 : 0.8))));
            if (ns === span) return;
            view.a = Math.max(0, Math.min(N - 1 - ns, Math.round(at - f * ns))); view.b = view.a + ns; redraw();
        }, { passive: false });
        bands.addEventListener("dblclick", ev => { ev.stopPropagation(); if (a0 === 0 && b0 === N - 1) return; view.a = 0; view.b = N - 1; redraw(); });
    }
    /* while zoomed: a labelled Reset zoom button in the top-right corner (beside the drill buttons) */
    c.resetZoom(zoomH > 0 && (a0 > 0 || b0 < N - 1), () => { view.a = 0; view.b = N - 1; redraw(); });
}

/**
 * Zoom to the selection (with the zoom slider on): the range dragged here, or the categories another
 * visual's selection highlights. A single click here doesn't zoom. When the selection goes away, the
 * window from before it comes back.
 */
function zoomToSelection(c: C, view: View, N: number) {
    const CH = c.s.chart; if (!CH.zoom.value || !CH.zoomToSelection.value || N <= 3) return;
    const act = c.io.active, own = c.io.sel.size > 0;
    let lo = -1, hi = -1;
    if (act) c.m.series.forEach(sr => sr.cells.forEach((ix, ci) => { if (ix >= 0 && act.has(ix)) { if (lo < 0 || ci < lo) lo = ci; if (ci > hi) hi = ci; } }));
    const key = lo >= 0 && (!own || hi > lo) && !(lo === 0 && hi === N - 1) ? `${lo}-${hi}` : "";
    if (key === (view.key || "")) return;
    if (key) {
        if (!view.saved) view.saved = [view.a, view.b];
        /* at least a week of days (or 7 categories) around a single highlighted one */
        const w = Math.min(N - 1, Math.max(hi - lo, 6)), mid = (lo + hi) / 2;
        view.a = Math.max(0, Math.min(N - 1 - w, Math.round(mid - w / 2))); view.b = view.a + w;
    } else if (view.saved) { [view.a, view.b] = view.saved; view.saved = null; }
    view.key = key;
}
