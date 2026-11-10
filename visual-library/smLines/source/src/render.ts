/*
 * Drawing for Small Multiple Lines: a grid of panels, one per group. Each panel has a title with an
 * on-track check, an optional subtitle, a value axis, the comparison line (muted) and the actual line
 * (palette color), and end labels "value · % of comparison" and "plan value" right of the last point.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Panel, Pt } from "./model";
import { Settings } from "./settings";
import { Ctx } from "./common/family";
import { el, r1, textW, trunc } from "./common/look";
import { colorOr, val } from "./common/cards";
import { mix } from "./common/color";
import { legend, domain, valueAxis, tickWidth } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<Settings, Model>;

export function render(c: C) {
    const { W, H, s, m, root, t, look } = c, pad = 6, CA = s.categoryAxis, VA = s.valueAxis, LB = s.labels, CH = s.chart, ST = s.status;
    const actualC = c.colorOf(m.actual), planC = t.hc ? t.ink : mix(t.axis, t.surface, 0.35);
    const good = colorOr(ST.goodColor, "#1a9e5c"), warn = colorOr(ST.warnColor, "#d9a400");
    const lg = legend(s.legend, [
        { key: "a", name: m.actual.name, color: actualC, on: true, shape: "line" },
        ...(m.hasComp ? [{ key: "p", name: m.plan.name, color: planC, on: true, shape: "line" as const }] : [])
    ], "", W, H, pad, t);
    const top = pad + lg.top, bottom = H - pad - lg.bottom, right = W - pad - lg.right;
    const n = m.panels.length;
    /* panel grid: as many columns as fit ~240 px panels, or the user's choice */
    let cols = CH.columns.value > 0 ? CH.columns.value : Math.max(1, Math.min(n, Math.floor((right - pad) / 240)));
    cols = Math.min(cols, n);
    const rows = Math.ceil(n / cols), gapX = 18, gapY = 12;
    const pw = (right - pad - gapX * (cols - 1)) / cols, ph = (bottom - top - gapY * (rows - 1)) / rows;
    const tfs = Math.max(6, CH.titleSize.value), sfs = Math.max(6, tfs - 2), cfs = Math.max(6, CA.fontSize.value), lfs = Math.max(6, LB.fontSize.value);
    const fmtT = formatter(m.format, 1, null, 0, c.culture);
    const allV = m.panels.reduce((a, p) => a.concat(p.pts.map(q => q.v), p.pts.map(q => q.p)), [] as number[]).filter(v => !isNaN(v));
    const fmtL = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...allV.map(Math.abs)), c.culture);
    const shared = CH.sharedScale.value;
    const nA = m.axis.length, pos = new Map(m.axis.map((a, k) => [a.key, k]));
    const pct = (p: Panel) => { const last = p.pts[p.pts.length - 1]; return m.hasComp && last && !isNaN(last.v) && !isNaN(last.p) && last.p !== 0 ? last.v / last.p : NaN; };
    const sh = look.shadow();

    m.panels.forEach((p, k) => {
        const px = pad + (k % cols) * (pw + gapX), py = top + Math.floor(k / cols) * (ph + gapY);
        const g = el("g", { class: "panel" }, root);
        const ratio = pct(p), ok = ratio * 100 >= ST.threshold.value;
        /* title row with the check on the right */
        const ic = ST.show.value && !isNaN(ratio) ? tfs + 2 : 0;
        el("text", { x: r1(px), y: r1(py + tfs), "font-size": tfs, "font-weight": 700, fill: t.ink }, g, trunc(p.name, pw - ic - 6, tfs));
        if (ic) {
            const cr = ic / 2, cx = px + pw - cr, cy = py + tfs * 0.62, col = t.hc ? t.ink : ok ? good : warn;
            const ig = el("g", {}, g);
            el("circle", { cx: r1(cx), cy: r1(cy), r: r1(cr), fill: look.fill(col, "r") }, ig);
            const w = Math.max(1.2, cr * 0.32);
            if (ok) el("path", { d: `M${r1(cx - cr * 0.45)},${r1(cy + cr * 0.02)}L${r1(cx - cr * 0.1)},${r1(cy + cr * 0.38)}L${r1(cx + cr * 0.48)},${r1(cy - cr * 0.34)}`, fill: "none", stroke: t.surface, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" }, ig);
            else { el("line", { x1: r1(cx), x2: r1(cx), y1: r1(cy - cr * 0.5), y2: r1(cy + cr * 0.12), stroke: t.surface, "stroke-width": w, "stroke-linecap": "round" }, ig); el("circle", { cx: r1(cx), cy: r1(cy + cr * 0.45), r: r1(w * 0.55), fill: t.surface }, ig); }
            c.bind(ig, { key: "s" + k, items: p.items, ids: p.pts.map(q => q.id), tip: () => [{ displayName: p.name, value: `${(ratio * 100).toFixed(0)}% of ${m.plan.name}` }] });
        }
        let y0 = py + tfs + 4;
        if (p.sub && ph > tfs * 5) { el("text", { x: r1(px), y: r1(y0 + sfs), "font-size": sfs, fill: t.axis }, g, trunc(p.sub, pw, sfs)); y0 += sfs + 4; }
        /* plot box */
        const vals = shared ? allV : p.pts.reduce((a, q) => a.concat([q.v, q.p]), [] as number[]).filter(v => !isNaN(v));
        const T = y0 + 6, B = py + ph - (CA.show.value ? cfs + 6 : 2);
        if (B - T < 16) return;
        const d = domain(Math.min(...vals), Math.max(...vals), B - T, Math.max(22, VA.fontSize.value * 2.6), VA, m.format, c.culture, false);
        /* small panels: thin the ticks until the labels have room */
        while (d.ticks.length > 2 && (B - T) / (d.ticks.length - 1) < VA.fontSize.value + 8) d.ticks = d.ticks.filter((_, k2) => k2 % 2 === 0);
        const last = p.pts[p.pts.length - 1];
        const lab1 = !isNaN(last.v) ? fmtL(last.v) + (isNaN(ratio) ? "" : " · " + Math.round(ratio * 100) + "%") : "";
        const lab2 = m.hasComp && !isNaN(last.p) ? m.plan.name.toLowerCase() + " " + fmtL(last.p) : "";
        const labW = LB.show.value ? Math.max(textW(lab1, lfs), textW(lab2, lfs * 0.92)) + 8 : 4;
        const L = px + tickWidth(d, VA), R = px + pw - Math.min(labW, pw * 0.42);
        if (R - L < 30) return;
        const y = (v: number) => B - (v - d.lo) / (d.hi - d.lo || 1) * (B - T);
        const x = (q: Pt) => L + (nA > 1 ? (R - L) * (pos.get(q.key) as number) / (nA - 1) : (R - L) / 2);
        valueAxis(g, d, y, { L, R, T, B }, true, VA, s.gridlines, t);
        if (CA.show.value) {
            const ax = el("g", { class: "axes" }, g), cC = colorOr(CA.color, t.axis);
            const step = Math.max(1, Math.ceil(nA / Math.max(2, Math.floor((R - L) / Math.max(36, Math.max(...m.axis.map(a => textW(a.name, cfs))) + 12)))));
            m.axis.forEach((a, k2) => {
                if (k2 % step && k2 !== nA - 1) return;
                if (k2 !== nA - 1 && nA - 1 - k2 < step) return;
                const xx = L + (nA > 1 ? (R - L) * k2 / (nA - 1) : (R - L) / 2);
                el("text", { x: r1(xx), y: r1(B + cfs + 3), "text-anchor": k2 === 0 ? "start" : k2 === nA - 1 ? "end" : "middle", "font-size": cfs, fill: cC }, ax, a.name);
            });
        }
        const line = (get: (q: Pt) => number) => { let dd = "", pen = false; p.pts.forEach(q => { const v = get(q); if (isNaN(v)) { pen = false; return; } dd += (pen ? "L" : "M") + r1(x(q)) + "," + r1(y(v)); pen = true; }); return dd; };
        if (m.hasComp) el("path", { d: line(q => q.p), fill: "none", stroke: planC, "stroke-width": Math.max(1, CH.lineWidth.value - 0.5), "stroke-linejoin": "round" }, g);
        const lg2 = el("g", sh ? { filter: sh } : {}, g);
        el("path", { d: line(q => q.v), fill: "none", stroke: actualC, "stroke-width": CH.lineWidth.value, "stroke-linejoin": "round", "stroke-linecap": "round" }, lg2);
        /* hover targets: one dot per point (only the last is visible) */
        p.pts.forEach((q, k2) => {
            if (isNaN(q.v)) return;
            const isLast = k2 === p.pts.length - 1;
            const dot = el("circle", { cx: r1(x(q)), cy: r1(y(q.v)), r: isLast ? CH.lineWidth.value + 2 : Math.max(3, Math.min(8, (R - L) / Math.max(1, nA) / 2)), fill: isLast ? look.fill(actualC, "r") : actualC, "fill-opacity": isLast ? 1 : 0, class: "mk" + (c.io.on(q.i) ? "" : " dim") }, g);
            c.bind(dot, { key: "i" + q.i, items: [q.i], ids: [q.id], tip: () => tip(p, q) });
        });
        if (LB.show.value) {
            const ya = y(last.v), yp = isNaN(last.p) ? ya : y(last.p);
            /* the actual label goes on the side away from the plan, so the two never overlap */
            const lo = T + lfs * 0.6, hi = B + lfs * 0.35, sep = lfs + 2;
            let ta = Math.max(lo, Math.min(hi, ya + lfs * 0.35)), tp = Math.max(lo, Math.min(hi, yp + lfs * 0.35));
            if (lab2 && Math.abs(ta - tp) < sep) {
                const aUp = ya <= yp;
                let up = aUp ? ta : tp, dn = aUp ? tp : ta;
                up = Math.max(lo, Math.min(up, (up + dn) / 2 - sep / 2)); dn = up + sep;
                if (dn > hi) { dn = hi; up = dn - sep; }
                ta = aUp ? up : dn; tp = aUp ? dn : up;
            }
            const lx = R + 6, lC = colorOr(LB.color, t.ink);
            if (lab1) el("text", { x: r1(lx), y: r1(ta), "font-size": lfs, "font-weight": 700, fill: lC, class: "lbl" }, g, trunc(lab1, px + pw - lx, lfs));
            if (lab2) el("text", { x: r1(lx), y: r1(tp), "font-size": r1(lfs * 0.92), fill: t.axis, class: "lbl" }, g, trunc(lab2, px + pw - lx, lfs));
        }
    });
    lg.draw(root, c.bind);

    function tip(p: Panel, q: Pt): TipItem[] {
        const out: TipItem[] = [];
        if (m.groupTitle) out.push({ displayName: m.groupTitle, value: p.name });
        out.push({ displayName: m.catTitle, value: q.name }, { displayName: m.actual.name, value: fmtT(q.v), color: actualC });
        if (m.hasComp && !isNaN(q.p)) { out.push({ displayName: m.plan.name, value: fmtT(q.p), color: planC }); if (q.p) out.push({ displayName: "% of " + m.plan.name, value: (q.v / q.p * 100).toFixed(1) + "%" }); }
        return out.concat(q.tips.map(tp => ({ displayName: tp.name, value: tp.value })));
    }
    void val;
}
