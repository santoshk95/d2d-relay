/*
 * Drawing for Atlas Parts: pie and donut (full or half), with a details
 * ring, top N plus Other, a progress track, a center total and labels
 * inside or outside with leader lines that never overlap.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Cell } from "./common/matrix";
import { PartsSettings } from "./settings";
import { Ctx, Colored } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr, val } from "./common/cards";
import { legend, LegendItem } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<PartsSettings, Model>;
/** ring segment between angles a0 and a1 (radians, 0 = up, clockwise), with a gap of g px along each edge */
function arc(cx: number, cy: number, r0: number, r1_: number, a0: number, a1: number, g: number): string {
    const pa = r1_ > 0 ? g / 2 / r1_ : 0, pb = r0 > 0 ? g / 2 / r0 : 0, span = a1 - a0;
    const s1 = a0 + Math.min(pa, span / 2), e1 = a1 - Math.min(pa, span / 2), s0 = a0 + Math.min(pb, span / 2), e0 = a1 - Math.min(pb, span / 2);
    const P = (a: number, r: number) => `${r1(cx + Math.sin(a) * r)},${r1(cy - Math.cos(a) * r)}`;
    if (span >= 2 * Math.PI - 1e-6) return `M${P(0, r1_)}A${r1(r1_)},${r1(r1_)} 0 1 1 ${P(Math.PI, r1_)}A${r1(r1_)},${r1(r1_)} 0 1 1 ${P(2 * Math.PI - 1e-4, r1_)}Z` + (r0 > 0 ? `M${P(0, r0)}A${r1(r0)},${r1(r0)} 0 1 0 ${P(Math.PI, r0)}A${r1(r0)},${r1(r0)} 0 1 0 ${P(2 * Math.PI - 1e-4, r0)}Z` : "");
    return `M${P(s1, r1_)}A${r1(r1_)},${r1(r1_)} 0 ${e1 - s1 > Math.PI ? 1 : 0} 1 ${P(e1, r1_)}` + (r0 > 0 ? `L${P(e0, r0)}A${r1(r0)},${r1(r0)} 0 ${e0 - s0 > Math.PI ? 1 : 0} 0 ${P(s0, r0)}` : `L${r1(cx)},${r1(cy)}`) + "Z";
}

export function render(c: C, topBand: number) {
    const { W, H, s, m, root, look, t } = c, pad = 6, CH = s.chart, SL = s.slices, LB = s.labels;
    const donut = s.type === "donut", half = CH.half.value, gap = CH.gap.value, content = val(SL.content), pos = val(SL.labelPosition), lbfs = Math.max(6, LB.fontSize.value);
    const fmtL = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...m.cells.map(x => Math.abs(x.v))), c.culture), fmtT = formatter(m.format, 1, null, 0, c.culture);
    const pct = (v: number) => (v * 100).toFixed(LB.decimals.value >= 0 ? Math.min(3, LB.decimals.value) : v < 0.1 ? 1 : 0) + "%";

    /* slices: category totals, largest first, top N with the rest as Other */
    interface Slice { key: string; name: string; v: number; cells: Cell[]; cat: Colored | null; other: boolean; }
    let slices: Slice[] = m.cats.map(ct => ({ key: ct.key, name: ct.name, v: ct.items.reduce((a, i) => a + Math.max(0, m.cells[i].v), 0), cells: ct.items.map(i => m.cells[i]), cat: ct, other: false })).filter(x => x.v > 0);
    if (val(CH.sort) === "value") slices.sort((a, b) => b.v - a.v);
    const topN = Math.round(CH.topN.value);
    if (topN > 0 && slices.length > topN) { const rest = slices.slice(topN); slices = slices.slice(0, topN).concat([{ key: "__other", name: CH.otherLabel.value || "Other", v: rest.reduce((a, x) => a + x.v, 0), cells: rest.flatMap(x => x.cells), cat: null, other: true }]); }
    const total = slices.reduce((a, x) => a + x.v, 0) || 1;
    const track = SL.track.value && slices.length >= 2, trackC = colorOr(SL.trackColor, mix(t.text, t.surface, 0.9));
    const colorOf = (sl: Slice, k: number) => (t.hc ? t.ink : track && k === slices.length - 1 ? trackC : sl.other ? mix(t.text, t.surface, 0.55) : sl.cat ? c.colorOf(sl.cat) : t.axis);
    const labelOf = (name: string, v: number) => content === "percent" ? pct(v / total) : content === "categoryPercent" ? `${name} ${pct(v / total)}` : content === "categoryValue" ? `${name} ${fmtL(v)}` : content === "value" ? fmtL(v) : `${name} ${fmtL(v)} (${pct(v / total)})`;

    const lg = legend(s.legend, slices.map((sl, k) => ({ key: sl.key, name: sl.name, color: colorOf(sl, k), on: c.io.anyOn(sl.cells.map(x => x.i)), target: { key: "c" + sl.key, items: sl.cells.map(x => x.i), ids: sl.cat && sl.cat.id ? [sl.cat.id] : sl.cells.map(x => x.id), tip: () => [{ displayName: m.catTitle, value: sl.name }] } })) as LegendItem[], m.catTitle, W, H, pad, t, true);
    const box = { l: pad, t: pad + Math.max(lg.top, topBand), r: W - pad - lg.right, b: H - pad - lg.bottom };
    const outside = LB.show.value && pos === "outside";
    const labelW = outside ? Math.min((box.r - box.l) * 0.28, Math.max(...slices.map(sl => textW(labelOf(sl.name, sl.v), lbfs)))) + 16 : 0;
    const BW = box.r - box.l - 2 * labelW, BH = box.b - box.t;
    const R = Math.max(10, half ? Math.min(BW / 2, BH - 10) : Math.min(BW, BH) / 2 - 4), cx = box.l + labelW + BW / 2, cy = half ? box.t + (BH + R) / 2 + 2 : box.t + BH / 2;
    const span = half ? Math.PI : 2 * Math.PI, start = (half ? -Math.PI / 2 : 0) + CH.startAngle.value * Math.PI / 180;
    const nested = m.series.length > 1 && !m.byMeasure;
    const r0 = donut ? R * CH.hole.value / 100 : 0, rMid = nested ? r0 + (R - r0) * 0.58 : R;
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    const tip = (sl: Slice): TipItem[] => [{ displayName: m.catTitle, value: sl.name, color: colorOf(sl, slices.indexOf(sl)) }, { displayName: m.series[0] && !nested ? m.series[0].name : "Value", value: fmtT(sl.v) }, { displayName: "Share", value: pct(sl.v / total) }].concat(sl.cells.length === 1 ? sl.cells[0].tips.map(tp => ({ displayName: tp.name, value: tp.value })) : []);
    const ends: { mid: number; text: string; color: string }[] = [];
    let a = start;
    slices.forEach((sl, k) => {
        const a0 = a, a1 = a + span * sl.v / total; a = a1;
        const col = colorOf(sl, k), items = sl.cells.map(x => x.i), g = el("g", { class: "mk" + (c.io.anyOn(items) ? "" : " dim") }, marks);
        if (look.is3d && !half) el("path", { d: arc(cx + 2, cy + 4, r0, rMid, a0, a1, gap), fill: look.side(col) }, g);
        el("path", { d: arc(cx, cy, r0, rMid, a0, a1, gap), fill: t.hc ? t.surface : look.flat ? col : look.fill(col, "r"), stroke: t.hc ? t.ink : "none" }, g);
        const tg: Target = { key: "c" + sl.key, items, ids: sl.cat && sl.cat.id ? [sl.cat.id] : sl.cells.map(x => x.id), tip: () => tip(sl) };
        c.bind(g, tg);
        /* details ring: each slice split by series */
        if (nested) {
            let b = a0;
            sl.cells.slice().sort((p, q) => p.s - q.s).forEach(cl => {
                const b1 = b + (a1 - a0) * Math.max(0, cl.v) / (sl.v || 1), shade = mix(col, t.surface, 0.12 + 0.55 * cl.s / Math.max(1, m.series.length));
                const og = el("g", { class: "mk" + (c.io.on(cl.i) ? "" : " dim") }, marks);
                el("path", { d: arc(cx, cy, rMid + 1.5, R, b, b1, gap), fill: t.hc ? t.surface : look.flat ? shade : look.fill(shade, "r"), stroke: t.hc ? t.ink : "none" }, og);
                c.bind(og, { key: "i" + cl.i, items: [cl.i], ids: [cl.id], tip: () => [{ displayName: m.catTitle, value: sl.name }, { displayName: m.serTitle, value: m.series[cl.s].name }, { displayName: "Value", value: fmtT(cl.v) }, { displayName: "Share of " + sl.name, value: pct(cl.v / (sl.v || 1)) }] });
                b = b1;
            });
        }
        if (!LB.show.value || (track && k === slices.length - 1)) return;
        const mid = (a0 + a1) / 2, text = labelOf(sl.name, sl.v);
        const rIn = (r0 + rMid) / 2, arcLen = (a1 - a0) * rIn, inside = pos === "inside" || (pos === "auto" && textW(text, lbfs) + 6 < Math.min(arcLen, (rMid - r0) * 1.6));
        if (inside) { if (arcLen > lbfs + 2) el("text", { x: r1(cx + Math.sin(mid) * rIn), y: r1(cy - Math.cos(mid) * rIn + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: t.hc ? t.ink : inkOn(col), class: "lbl", style: "stroke:none" }, labels, trunc(text, Math.max(30, arcLen), lbfs)); }
        else ends.push({ mid, text, color: col });
    });
    /* outside labels: two columns, spread so they never overlap, with leader lines */
    const side = (right: boolean) => {
        const list = ends.filter(e => (Math.sin(e.mid) >= 0) === right).map(e => ({ ...e, y: cy - Math.cos(e.mid) * (R + 10) }));
        list.sort((p, q) => p.y - q.y);
        const gapY = lbfs + 3; for (let k = 1; k < list.length; k++) list[k].y = Math.max(list[k].y, list[k - 1].y + gapY);
        const over = list.length ? list[list.length - 1].y - (box.b - 4) : 0; if (over > 0) list.forEach(e => { e.y -= over; }); for (let k = list.length - 2; k >= 0; k--) list[k].y = Math.min(list[k].y, list[k + 1].y - gapY);
        list.forEach(e => {
            const ex = cx + Math.sin(e.mid) * R, ey = cy - Math.cos(e.mid) * R, kx = cx + Math.sin(e.mid) * (R + 8), lx = right ? cx + R + 14 : cx - R - 14;
            el("path", { d: `M${r1(ex)},${r1(ey)}L${r1(kx)},${r1(e.y)}L${r1(lx)},${r1(e.y)}`, fill: "none", stroke: mix(e.color, t.surface, 0.3), "stroke-width": 1 }, labels);
            el("text", { x: r1(lx + (right ? 4 : -4)), y: r1(e.y + lbfs * 0.35), "text-anchor": right ? "start" : "end", "font-size": lbfs, fill: colorOr(LB.color, t.text), class: "lbl" }, labels, trunc(e.text, labelW - 6, lbfs));
        });
    };
    side(true); side(false);
    /* center total (donut) */
    if (donut && SL.centerTotal.value && r0 > 18) {
        const v = track ? slices[0].v / total : total, big = track ? pct(v) : fmtL(total), fs2 = Math.min(r0 * 0.5, 34), yy = half ? cy - 6 : cy + fs2 * 0.2;
        el("text", { x: r1(cx), y: r1(yy), "text-anchor": "middle", "font-size": r1(fs2), fill: t.ink, class: "ttl" }, labels, big);
        el("text", { x: r1(cx), y: r1(yy + Math.max(9, lbfs) + 4), "text-anchor": "middle", "font-size": Math.max(9, lbfs), fill: t.axis, class: "ax" }, labels, trunc(SL.centerLabel.value || (track ? slices[0].name : "Total"), r0 * 1.6, lbfs));
    }
    lg.draw(root, c.bind);
}
