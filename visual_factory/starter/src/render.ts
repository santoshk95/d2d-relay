/*
 * Drawing for __TITLE__. The starter draws columns per category, side by side per series; replace
 * the marks with your own design and keep what every visual needs: a layout computed from W x H,
 * colors from c.colorOf() and the theme (c.t), the look (look.fill, look.shadow), text sizes from
 * the Format pane, tooltips and selection through c.bind(), and dimming of what is not selected.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Cell, catTarget } from "./common/matrix";
import { Settings } from "./settings";
import { Ctx } from "./common/family";
import { el, r1, trunc } from "./common/look";
import { colorOr } from "./common/cards";
import { legend, domain, valueAxis, tickWidth } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<Settings, Model>;

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, pad = 6, CA = s.categoryAxis, VA = s.valueAxis, LB = s.labels, CH = s.chart;
    /* one series: the categories carry the palette colors; several: the series do */
    const byCat = m.colored === m.cats;
    const colorOf = (cell: Cell) => c.colorOf(byCat ? m.cats[cell.c] : m.series[cell.s]);
    const lg = legend(s.legend, m.colored.map(x => ({
        key: x.key, name: x.name, color: c.colorOf(x), on: c.io.anyOn(x.items),
        target: { key: "c:" + x.key, items: x.items, ids: x.id ? [x.id] : [], tip: () => [{ displayName: byCat ? m.catTitle : m.serTitle || "Series", value: x.name }] }
    })), byCat ? m.catTitle : m.serTitle, W, H, pad, t);

    const cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value), axisH = CA.show.value ? cfs + 10 : 0;
    const T = pad + lg.top + (LB.show.value ? lbfs + 4 : 0), B = H - pad - lg.bottom - axisH;
    const vals = m.cells.map(x => x.v);
    const d = domain(Math.min(0, ...vals), Math.max(0, ...vals), B - T, 40, VA, m.format, c.culture);
    const L = pad + tickWidth(d, VA), R = W - pad - lg.right;
    if (R - L < 20 || B - T < 20) return;
    const y = (v: number) => B - (v - d.lo) / (d.hi - d.lo || 1) * (B - T);
    valueAxis(root, d, y, { L, R, T, B }, true, VA, s.gridlines, t);

    const band = (R - L) / Math.max(1, m.cats.length), inner = band * (1 - CH.gap.value / 100), bw = inner / Math.max(1, m.series.length);
    const fmtL = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...vals.map(Math.abs)), c.culture);
    const fmtT = formatter(m.format, 1, null, 0, c.culture);
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    const tip = (cell: Cell): TipItem[] => {
        const head: TipItem[] = [
            { displayName: m.catTitle, value: m.cats[cell.c].name, color: colorOf(cell) },
            { displayName: m.series[cell.s].name, value: fmtT(cell.full) }];
        return head.concat(cell.tips.map(tp => ({ displayName: tp.name, value: tp.value })));
    };

    m.cells.forEach(cell => {
        const x = L + band * cell.c + (band - inner) / 2 + bw * cell.s, y0 = y(Math.max(0, cell.v)), y1 = y(Math.min(0, cell.v));
        const col = colorOf(cell), g = el("g", { class: "mk" + (c.io.on(cell.i) ? "" : " dim") }, marks);
        el("rect", {
            x: r1(x + 1), y: r1(y0), width: r1(Math.max(1, bw - 2)), height: r1(Math.max(1, y1 - y0)), rx: r1(Math.min(CH.corner.value, bw / 2)),
            fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : "none"
        }, g);
        c.bind(g, { key: "i" + cell.i, items: [cell.i], ids: [cell.id], tip: () => tip(cell) });
        if (LB.show.value && bw > 8) {
            el("text", {
                x: r1(x + bw / 2), y: r1(cell.v >= 0 ? y0 - 4 : y1 + lbfs + 2), "text-anchor": "middle", "font-size": lbfs,
                fill: colorOr(LB.color, t.text), class: "lbl"
            }, labels, trunc(fmtL(cell.v), Math.max(bw + 10, 24), lbfs));
        }
    });

    if (CA.show.value) {
        const axis = el("g", { class: "axes" }, root), cC = colorOr(CA.color, t.axis);
        m.cats.forEach((ct, ci) => {
            const lbl = el("text", { x: r1(L + band * (ci + 0.5)), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, axis, trunc(ct.name, band - 4, cfs));
            c.io.bindLabel(lbl, catTarget(m, ci));
        });
    }
    lg.draw(root, c.bind);
}
