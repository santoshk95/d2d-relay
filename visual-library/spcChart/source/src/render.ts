/*
 * Drawing for SPC Control Chart (individuals chart): the value per point in
 * order, centre line, upper and lower control limits, a shaded in-control
 * zone, and out-of-control points (beyond a limit, optionally runs of 8 on
 * one side of the centre) highlighted with a ring.
 */
import powerbi from "powerbi-visuals-api";
import { Model } from "./model";
import { SpcSettings } from "./settings";
import { Ctx } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix } from "./common/color";
import { colorOr } from "./common/cards";
import { domain, tickWidth, valueAxis } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<SpcSettings, Model>;

const mean = (a: number[]) => a.reduce((s, v) => s + v, 0) / a.length;
const sd = (a: number[]) => { const m = mean(a); return a.length > 1 ? Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1)) : 0; };
const first = (a: number[] | null) => { const v = a ? a.find(x => isFinite(x)) : undefined; return v === undefined ? NaN : v; };

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, pad = 6, SP = s.spc, LB = s.labels, CA = s.categoryAxis, VA = s.valueAxis, GR = s.gridlines;
    const sr = m.series[0], N = m.cats.length;
    const cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value);
    const cC = colorOr(CA.color, t.axis), alarm = colorOr(SP.alarmColor, "#d64550"), limC = colorOr(SP.limitColor, mix(t.text, t.surface, 0.35));
    const col = t.hc ? t.ink : c.colorOf(sr);
    const fmtT = formatter(sr.format, 1, null, 0, c.culture);
    const ys = sr.v.filter(v => !isNaN(v));
    const fmtL = labelFormatter(sr.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...ys.map(Math.abs)), c.culture);

    /* limits: bound measures when given, otherwise computed from the plotted values */
    const bound = (a: number[] | null) => (a ? (i: number) => (isFinite(a[i]) ? a[i] : first(a)) : null);
    const mu = mean(ys), sg = sd(ys), k = SP.sigma.value;
    const cen = bound(m.centre) || (() => mu), ucl = bound(m.upper) || (() => mu + k * sg), lcl = bound(m.lower) || (() => mu - k * sg);
    const varying = (f: (i: number) => number) => { const v0 = f(0); return m.cats.some((_, i) => Math.abs(f(i) - v0) > 1e-9); };
    const stepped = varying(ucl) || varying(lcl) || varying(cen);

    /* out-of-control points */
    const ooc = new Set<number>(), run = new Set<number>();
    m.cats.forEach((_, i) => { const v = sr.v[i]; if (!isNaN(v) && (v > ucl(i) || v < lcl(i))) ooc.add(i); });
    if (SP.runRule.value) {
        let streak = 0, side = 0;
        m.cats.forEach((_, i) => {
            const v = sr.v[i]; if (isNaN(v)) return;
            const sd0 = Math.sign(v - cen(i)); streak = sd0 !== 0 && sd0 === side ? streak + 1 : sd0 !== 0 ? 1 : 0; side = sd0;
            if (streak >= 8) for (let j = i, n = 0; n < streak; n++) { while (j >= 0 && isNaN(sr.v[j])) j--; if (j >= 0) run.add(j); j--; }
        });
    }

    /* layout */
    const lblW = SP.showLimitLabels.value ? Math.max(textW("UCL " + fmtT(ucl(N - 1)), 9), textW("LCL " + fmtT(lcl(N - 1)), 9), textW("Mean " + fmtT(cen(N - 1)), 9)) + 6 : 0;
    const catH = CA.show.value ? cfs + 8 : 0, T = pad + 8, B = H - pad - catH;
    const all = ys.concat(m.cats.map((_, i) => ucl(i)), m.cats.map((_, i) => lcl(i))).filter(v => isFinite(v));
    const dL = domain(Math.min(...all), Math.max(...all), B - T, 44, VA, sr.format, c.culture, false);
    const L = pad + tickWidth(dL, VA), R = W - pad - lblW, step = (R - L) / Math.max(1, N);
    const X = (i: number) => L + step * (i + 0.5), Y = (v: number) => B - (v - dL.lo) / (dL.hi - dL.lo) * (B - T);
    valueAxis(root, dL, Y, { L, R, T, B }, true, VA, GR, t);

    const back = el("g", {}, root), sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), bands = el("g", {}, root), over = el("g", {}, root), labels = el("g", {}, root);
    const pathOf = (f: (i: number) => number) => m.cats.map((_, i) => (stepped ? `${i ? "H" + r1(X(i) - step / 2) + "V" + r1(Y(f(i))) + "H" : "M" + r1(L) + "," + r1(Y(f(i))) + "H"}${r1(X(i) + step / 2)}` : `${i ? "L" : "M"}${r1(X(i))},${r1(Y(f(i)))}`)).join("");
    const lineP = (f: (i: number) => number) => (stepped ? pathOf(f) : `M${r1(L)},${r1(Y(f(0)))}H${r1(R)}`);

    /* in-control zone */
    if (SP.shadeZone.value) {
        const top = m.cats.map((_, i) => `${r1(X(i) - step / 2)},${r1(Y(ucl(i)))} ${r1(X(i) + step / 2)},${r1(Y(ucl(i)))}`), bot = m.cats.map((_, i) => `${r1(X(i) + step / 2)},${r1(Y(lcl(i)))} ${r1(X(i) - step / 2)},${r1(Y(lcl(i)))}`).reverse();
        el("polygon", { points: top.concat(bot).join(" "), fill: mix(col, t.surface, 0.9), opacity: 0.9 }, back);
    }
    /* limits and centre line */
    el("path", { d: lineP(ucl), fill: "none", stroke: limC, "stroke-width": 1.4, "stroke-dasharray": "6 4" }, back);
    el("path", { d: lineP(lcl), fill: "none", stroke: limC, "stroke-width": 1.4, "stroke-dasharray": "6 4" }, back);
    el("path", { d: lineP(cen), fill: "none", stroke: mix(t.text, t.surface, 0.2), "stroke-width": 1.3 }, back);
    if (SP.showLimitLabels.value) {
        const last = N - 1, lab = (txt: string, v: number, fill: string) => el("text", { x: r1(R + 4), y: r1(Y(v) + 3), "font-size": 9, fill, class: "ref" }, labels, txt);
        lab("UCL " + fmtT(ucl(last)), ucl(last), limC); lab("LCL " + fmtT(lcl(last)), lcl(last), limC); lab("Mean " + fmtT(cen(last)), cen(last), t.text);
    }

    /* tooltips */
    const catTip = (ci: number): TipItem[] => {
        const out: TipItem[] = m.levelNames.map((nm, j) => ({ displayName: nm, value: m.cats[ci].path[j] }));
        const v = sr.v[ci];
        if (!isNaN(v)) out.push({ displayName: sr.name, value: fmtT(v), color: col });
        out.push({ displayName: "Centre line", value: fmtT(cen(ci)) }, { displayName: "Control limits", value: `${fmtT(lcl(ci))} – ${fmtT(ucl(ci))}` });
        if (!isNaN(v)) out.push({ displayName: "Status", value: ooc.has(ci) ? (v > ucl(ci) ? "Above upper limit" : "Below lower limit") : run.has(ci) ? "Run of 8 on one side" : "In control", color: ooc.has(ci) ? alarm : undefined });
        const ix = sr.cells[ci]; if (ix >= 0) m.cells[ix].tips.forEach(tp => out.push({ displayName: tp.name, value: tp.value }));
        return out;
    };
    const cellT = (ci: number): Target => ({ key: "i" + sr.cells[ci], items: [sr.cells[ci]], ids: [m.cells[sr.cells[ci]].id], tip: () => catTip(ci) });

    /* the process line and the points */
    const pts = m.cats.map((_, i) => (isNaN(sr.v[i]) ? null : ([X(i), Y(sr.v[i])] as [number, number])));
    let d = "", pen = false;
    pts.forEach(p => { if (!p) { pen = false; return; } d += `${pen ? "L" : "M"}${r1(p[0])},${r1(p[1])}`; pen = true; });
    el("path", { d, fill: "none", stroke: col, "stroke-width": SP.width.value, "stroke-linejoin": "round", "stroke-linecap": "round" }, marks);
    const r = SP.markerSize.value;
    m.cats.forEach((_, i) => {
        const p = pts[i], ix = sr.cells[i]; if (!p || ix < 0) return;
        const bad = ooc.has(i), flag = bad || run.has(i), g = el("g", { class: "mk" + (c.io.on(ix) ? "" : " dim") }, over);
        if (flag) el("circle", { cx: r1(p[0]), cy: r1(p[1]), r: r1(r + 4), fill: "none", stroke: alarm, "stroke-width": bad ? 2 : 1.4, "stroke-dasharray": bad ? null : "3 2" }, g);
        el("circle", { cx: r1(p[0]), cy: r1(p[1]), r: r1(r), fill: flag ? alarm : t.surface, stroke: flag ? alarm : col, "stroke-width": 2 }, g);
        c.bind(g, cellT(i));
        if (bad) el("text", { x: r1(p[0]), y: r1(p[1] + (sr.v[i] > ucl(i) ? -r - 8 : r + 14)), "text-anchor": "middle", "font-size": lbfs, fill: alarm, class: "lbl" }, labels, fmtL(sr.v[i]));
        else if (LB.show.value) el("text", { x: r1(p[0]), y: r1(p[1] - r - 4), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "lbl" }, labels, trunc(fmtL(sr.v[i]), step, lbfs));
    });

    /* hover bands */
    m.cats.forEach((_, i) => {
        if (sr.cells[i] < 0) return;
        const hb = el("rect", { x: r1(X(i) - step / 2), y: r1(T), width: r1(step), height: r1(B - T), fill: "transparent", class: "band" }, bands);
        c.bind(hb, { ...cellT(i), wide: true });
    });

    /* category labels (skip any that would overlap) */
    if (CA.show.value) {
        let right = -Infinity;
        m.cats.forEach((ct, i) => {
            const w = textW(ct.label, cfs), left = X(i) - w / 2; if (left < right + 6) return; right = left + w;
            el("text", { x: r1(X(i)), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, labels, ct.label);
        });
    }
}
