/*
 * Drawing for Atlas Proportion: Mekko, waffle, pictogram, aster plot,
 * rose (polar area) and Venn, from the shared category × series matrix.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Cell, catTarget } from "./common/matrix";
import { ProportionSettings } from "./settings";
import { Ctx, Colored } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr, val } from "./common/cards";
import { legend, LegendItem, nice } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<ProportionSettings, Model>;
/* built-in icons on a 24 × 24 grid (no network) */
const ICONS: Record<string, string> = {
    person: "M12 2a4.2 4.2 0 1 1 0 8.4a4.2 4.2 0 1 1 0-8.4ZM4 22v-2.6a6.4 6.4 0 0 1 6.4-6.4h3.2a6.4 6.4 0 0 1 6.4 6.4V22Z",
    circle: "M12 2a10 10 0 1 1 0 20a10 10 0 1 1 0-20Z",
    square: "M3 3h18v18H3Z",
    star: "M12 2l2.9 6.6 7.1.6-5.4 4.7 1.6 7-6.2-3.7-6.2 3.7 1.6-7L2 9.2l7.1-.6Z",
    heart: "M12 21s-8-5.2-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.8-8 11-8 11Z",
    drop: "M12 2s7 7.6 7 12.5a7 7 0 0 1-14 0C5 9.6 12 2 12 2Z"
};
let CLIP = 0;

/** area of the lens where two circles overlap */
function lens(r1_: number, r2: number, d: number): number {
    if (d >= r1_ + r2) return 0;
    if (d <= Math.abs(r1_ - r2)) return Math.PI * Math.min(r1_, r2) ** 2;
    const a = Math.acos((d * d + r1_ * r1_ - r2 * r2) / (2 * d * r1_)), b = Math.acos((d * d + r2 * r2 - r1_ * r1_) / (2 * d * r2));
    return r1_ * r1_ * (a - Math.sin(2 * a) / 2) + r2 * r2 * (b - Math.sin(2 * b) / 2);
}
/** distance between centers that gives a target overlap area (bisection) */
function distFor(r1_: number, r2: number, area: number): number {
    if (area <= 0) return r1_ + r2 + 2;
    let lo = Math.abs(r1_ - r2), hi = r1_ + r2;
    for (let i = 0; i < 50; i++) { const mid = (lo + hi) / 2; if (lens(r1_, r2, mid) > area) lo = mid; else hi = mid; }
    return (lo + hi) / 2;
}
/** largest-remainder split of n cells by shares */
function allocate(n: number, weights: number[]): number[] {
    const tot = weights.reduce((a, b) => a + Math.max(0, b), 0) || 1, raw = weights.map(w => Math.max(0, w) / tot * n), out = raw.map(Math.floor);
    let left = n - out.reduce((a, b) => a + b, 0);
    raw.map((x, i) => ({ i, f: x - Math.floor(x) })).sort((a, b) => b.f - a.f).forEach(o => { if (left > 0) { out[o.i]++; left--; } });
    return out;
}

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6;
    const LB = s.labels, CA = s.categoryAxis, lbfs = Math.max(6, LB.fontSize.value), cfs = Math.max(6, CA.fontSize.value), lbC = colorOr(LB.color, t.text), cC = colorOr(CA.color, t.text);
    const content = val(s.chart.content), empty = colorOr(s.chart.emptyColor, mix(t.text, t.surface, 0.9));
    const S = m.series.length, N = m.cats.length, multi = S > 1 && !m.byMeasure;
    const fmtV = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...m.cells.map(x => Math.abs(x.v))), c.culture);
    const fmtTip = formatter(m.format, 1, null, 0, c.culture);
    const pct = (v: number) => (v * 100).toFixed(LB.decimals.value >= 0 ? Math.min(4, LB.decimals.value) : Math.abs(v) < 0.1 ? 1 : 0) + "%";
    const lab = (v: number, share: number) => (content === "value" ? fmtV(v) : content === "both" ? `${fmtV(v)} (${pct(share)})` : pct(share));
    /* back: tracks and outlines under the marks */
    const back = el("g", {}, root), sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    /* a category's color (one series) or a series' color */
    const catColor = (ci: number) => c.colorOf(m.colored === m.cats ? m.cats[ci] : m.series[0]);
    const cellColor = (x: Cell) => (S > 1 && multi ? c.colorOf(m.series[x.s]) : catColor(x.c));
    const cellTip = (x: Cell, share?: number): TipItem[] => {
        const items: TipItem[] = [{ displayName: m.catTitle, value: m.cats[x.c].name, color: cellColor(x) }];
        if (m.serTitle) items.push({ displayName: m.serTitle, value: m.series[x.s].name });
        items.push({ displayName: m.serTitle ? "Value" : m.series[x.s].name, value: fmtTip(x.v) });
        if (share !== undefined) items.push({ displayName: "Share", value: (share * 100).toFixed(1) + "%" });
        if (x.hlv !== null) items.push({ displayName: "Before the selection", value: fmtTip(x.full) });
        x.tips.forEach(tp => items.push({ displayName: tp.name, value: tp.value }));
        return items;
    };
    const cellT = (x: Cell, share?: number): Target => ({ key: "i" + x.i, items: [x.i], ids: [x.id], tip: () => cellTip(x, share) });
    const note = (text: string) => {
        const lines: string[] = []; let cur = "";
        text.split(" ").forEach(w => { const nx = cur ? cur + " " + w : w; if (cur && textW(nx, 12) > W - 24) { lines.push(cur); cur = w; } else cur = nx; });
        if (cur) lines.push(cur);
        lines.forEach((ln, k) => el("text", { x: r1(W / 2), y: r1(H / 2 + (k - (lines.length - 1) / 2) * 16), "text-anchor": "middle", "font-size": 12, fill: t.text, class: "note" }, root, ln));
    };
    const on = (x: Cell) => c.io.on(x.i);

    /* legend: series for Mekko and stacked rose, categories otherwise */
    const legendOf: Colored[] = type === "venn" ? [] : (multi ? m.series : type === "pictogram" ? [] : m.cats);
    const lgItems: LegendItem[] = legendOf.map(g => ({ key: g.key, name: g.name, color: c.colorOf(g), on: c.io.anyOn(g.items), target: { key: "g" + g.key, items: g.items, ids: g.id ? [g.id] : [], tip: () => [{ displayName: multi ? m.serTitle : m.catTitle, value: g.name }] } }));
    const shaded = type === "rose" && !multi && s.radial.shadeByValue.value;
    const lg = legend(s.legend, lgItems, multi ? m.serTitle : m.catTitle, W, H, pad, t, type !== "pictogram" && type !== "venn" && !(type === "waffle" && s.chart.multiples.value) && type !== "aster" && !shaded);
    const box = { l: pad, t: pad + lg.top, r: W - pad - lg.right, b: H - pad - lg.bottom };
    const BW = Math.max(10, box.r - box.l), BH = Math.max(10, box.b - box.t);

    if (type === "mekko") mekko();
    else if (type === "waffle") waffle();
    else if (type === "pictogram") pictogram();
    else if (type === "aster") aster();
    else if (type === "rose") rose();
    else venn();
    lg.draw(root, c.bind);

    /* ================================================================ Mekko */
    function mekko() {
        const MK = s.mekko, gap = MK.gap.value, tot = m.cats.map((_, ci) => m.grid[ci].reduce((a, x) => a + (x ? Math.max(0, x.v) : 0), 0)), grand = tot.reduce((a, b) => a + b, 0) || 1;
        const totH = MK.showTotals.value ? lbfs + 6 : 0, catH = CA.show.value ? cfs + 8 : 0, axW = textW("100%", 9) + 8;
        const L = box.l + axW, R = box.r, T = box.t + totH, B = box.b - catH, usable = R - L - gap * Math.max(0, N - 1);
        [0, 0.25, 0.5, 0.75, 1].forEach(v => {
            const y = B - v * (B - T);
            el("line", { x1: r1(L), x2: r1(R), y1: r1(y) + 0.5, y2: r1(y) + 0.5, stroke: t.grid, "stroke-width": 1 }, root);
            el("text", { x: r1(L - 6), y: r1(y + 3), "text-anchor": "end", "font-size": 9, fill: t.axis, class: "ax" }, root, Math.round(v * 100) + "%");
        });
        let x = L;
        m.cats.forEach((ct, ci) => {
            const w = usable * tot[ci] / grand; if (w <= 0) return;
            let y = B;
            m.grid[ci].forEach(cell => {
                if (!cell || cell.v <= 0) return;
                const share = cell.v / (tot[ci] || 1), h = share * (B - T), col = cellColor(cell);
                const g = el("g", { class: "mk" + (on(cell) ? "" : " dim") }, marks);
                el("rect", { x: r1(x), y: r1(y - h + gap / 2), width: r1(Math.max(0.5, w)), height: r1(Math.max(0.5, h - gap)), rx: r1(Math.min(MK.radius.value, w / 2, h / 2)), fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : "none" }, g);
                c.bind(g, cellT(cell, share));
                if (LB.show.value && w > 28 && h > lbfs + 4) el("text", { x: r1(x + w / 2), y: r1(y - h / 2 + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: t.hc ? t.ink : inkOn(col), class: "ax" }, labels, trunc(lab(cell.v, share), w - 4, lbfs));
                y -= h;
            });
            if (CA.show.value) c.io.bindLabel(el("text", { x: r1(x + w / 2), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, labels, trunc(ct.name, w + gap - 2, cfs)), catTarget(m, ci));
            if (MK.showTotals.value && w > 20) el("text", { x: r1(x + w / 2), y: r1(box.t + lbfs), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "lbl" }, labels, trunc(content === "percent" ? pct(tot[ci] / grand) : fmtV(tot[ci]), w + gap - 2, lbfs));
            x += w + gap;
        });
    }

    /* ================================================================ waffle */
    function waffle() {
        const WF = s.waffle, rows = Math.max(1, WF.rows.value), cols = Math.max(1, WF.columns.value), n = rows * cols, gap = WF.gap.value, shape = val(WF.shape);
        /* ratio mode: two measures (part and total) or one value that reads as a share */
        const ratio = m.byMeasure && S >= 2, single = N === 1 && S === 1;
        const shareOf = (ci: number) => {
            const a = m.grid[ci][0]; if (!a) return 0;
            if (ratio) { const b = m.grid[ci][1]; return b && b.v ? a.v / b.v : 0; }
            return a.v <= 1 ? a.v : a.v <= 100 ? a.v / 100 : 1;
        };
        const panels: { title: string; parts: { cell: Cell | null; count: number; color: string }[]; big: string; cap: string }[] = [];
        if (s.chart.multiples.value || ratio || single) {
            const list = s.chart.multiples.value ? m.cats.map((_, ci) => ci) : [0];
            list.forEach(ci => {
                const sh2 = Math.max(0, Math.min(1, shareOf(ci))), k = Math.round(sh2 * n), cell = m.grid[ci][0] || null;
                panels.push({ title: s.chart.multiples.value ? m.cats[ci].name : "", parts: [{ cell, count: k, color: catColor(ci) }, { cell: null, count: n - k, color: empty }], big: pct(sh2), cap: s.chart.multiples.value ? "" : (N === 1 ? m.cats[0].name : m.series[0].name) });
            });
        } else {
            const cells = m.cats.map((_, ci) => m.grid[ci][0]).filter(x => x) as Cell[];
            const counts = allocate(n, cells.map(x => x.v)), tot = cells.reduce((a, x) => a + Math.max(0, x.v), 0) || 1;
            panels.push({ title: "", parts: cells.map((x, k) => ({ cell: x, count: counts[k], color: catColor(x.c) })), big: "", cap: "" });
            void tot;
        }
        const P = panels.length, pcols = Math.max(1, Math.min(P, Math.round(Math.sqrt(P * BW / BH)))), prow = Math.ceil(P / pcols);
        const pw = BW / pcols, ph = BH / prow;
        panels.forEach((p, pi) => {
            const px = box.l + pw * (pi % pcols), py = box.t + ph * Math.floor(pi / pcols), tH = p.title ? cfs + 6 : 0;
            const bigW = WF.bigNumber.value && p.big && pw > ph * 1.5 ? Math.min(pw * 0.4, 150) : 0;
            const cell = Math.max(2, Math.min((pw - bigW - 8 - gap * (cols - 1)) / cols, (ph - tH - 6 - gap * (rows - 1)) / rows));
            const gw = cols * cell + (cols - 1) * gap, gh = rows * cell + (rows - 1) * gap, gx = px + (pw - bigW - gw) / 2, gy = py + tH + (ph - tH - gh) / 2;
            if (p.title) el("text", { x: r1(px + pw / 2), y: r1(py + cfs), "text-anchor": "middle", "font-size": cfs, fill: t.text, class: "ttl" }, labels, trunc(p.title, pw - 4, cfs));
            let k = 0;
            p.parts.forEach(part => {
                const g = el("g", part.cell ? { class: "mk" + (on(part.cell) ? "" : " dim") } : {}, marks);
                for (let j = 0; j < part.count; j++, k++) {
                    /* fill column by column from the bottom left, like the built-in waffle visuals */
                    const col = Math.floor(k / rows), row = rows - 1 - (k % rows), x = gx + col * (cell + gap), y = gy + row * (cell + gap);
                    const fill = part.cell ? (t.hc ? t.ink : look.flat ? part.color : look.fill(part.color, shape === "circle" ? "r" : "v")) : empty;
                    if (shape === "circle") el("circle", { cx: r1(x + cell / 2), cy: r1(y + cell / 2), r: r1(cell / 2), fill }, g);
                    else el("rect", { x: r1(x), y: r1(y), width: r1(cell), height: r1(cell), rx: shape === "rounded" ? r1(cell * 0.22) : 0, fill }, g);
                }
                if (part.cell) c.bind(g, cellT(part.cell, part.count / n));
            });
            if (bigW) {
                const bfs = Math.min(bigW / 3.2, ph / 3), bx = px + pw - bigW;
                el("text", { x: r1(bx), y: r1(py + ph / 2), "font-size": r1(bfs), fill: t.hc ? t.ink : p.parts[0].color, class: "ttl" }, labels, p.big);
                if (p.cap) el("text", { x: r1(bx), y: r1(py + ph / 2 + cfs + 6), "font-size": cfs, fill: t.text, class: "ax" }, labels, trunc(p.cap, bigW, cfs));
            } else if (WF.bigNumber.value && p.big) el("text", { x: r1(px + pw / 2), y: r1(gy + gh + cfs + 4 > py + ph ? gy - 4 : gy + gh + cfs + 4), "text-anchor": "middle", "font-size": cfs + 2, fill: t.text, class: "ttl" }, labels, p.big);
        });
    }

    /* ================================================================ pictogram */
    function pictogram() {
        const PG = s.pictogram, icon = ICONS[val(PG.icon)] || ICONS.person;
        const ratio = (m.byMeasure && S >= 2) || PG.total.value > 0;
        const drawIcon = (g: Element, x: number, y: number, size: number, fill: string, part: number) => {
            const tf = `translate(${r1(x)},${r1(y)}) scale(${r1(size / 24 * 1000) / 1000})`;
            if (part >= 1) { el("path", { d: icon, transform: tf, fill }, g); return; }
            el("path", { d: icon, transform: tf, fill: empty }, g);
            if (part <= 0) return;
            const id = "atlp-clip" + (++CLIP), cp = el("clipPath", { id }, g);
            el("rect", { x: r1(x), y: r1(y), width: r1(size * part), height: r1(size) }, cp);
            el("path", { d: icon, transform: tf, fill, "clip-path": `url(#${id})` }, g);
        };
        if (ratio) {
            /* "7 in 10": the total as icons, the part filled */
            const list = s.chart.multiples.value ? m.cats.map((_, ci) => ci) : [0];
            const panelH = BH / list.length;
            list.forEach((ci, k) => {
                const a = m.grid[ci][0]; if (!a) return;
                const total = PG.total.value > 0 ? PG.total.value : (m.grid[ci][1] ? (m.grid[ci][1] as Cell).v : 0);
                if (!(total > 0)) return;
                const nIcons = total <= 20 && Number.isInteger(total) ? total : 10, filled = a.v / total * nIcons;
                const py = box.t + panelH * k, textW_ = Math.min(BW * 0.38, 190), per = PG.perRow.value > 0 ? PG.perRow.value : nIcons;
                const rowsN = Math.ceil(nIcons / per), size = Math.max(6, Math.min((BW - textW_ - 10) / per * 0.86, (panelH - 8) / rowsN * 0.86)), stepI = size / 0.86;
                const col = catColor(ci), g = el("g", { class: "mk" + (on(a) ? "" : " dim") }, marks);
                for (let i = 0; i < nIcons; i++) drawIcon(g, box.l + (i % per) * stepI, py + (panelH - rowsN * stepI) / 2 + Math.floor(i / per) * stepI, size, t.hc ? t.ink : col, Math.max(0, Math.min(1, filled - i)));
                c.bind(g, cellT(a, a.v / total));
                const tx = box.l + per * stepI + 12, big = `${Number.isInteger(+filled.toFixed(1)) ? filled.toFixed(0) : filled.toFixed(1)} in ${nIcons}`, bfs = Math.min(textW_ / 4.2, panelH / 3);
                el("text", { x: r1(tx), y: r1(py + panelH / 2 - 2), "font-size": r1(bfs), fill: t.hc ? t.ink : col, class: "ttl" }, labels, big);
                el("text", { x: r1(tx), y: r1(py + panelH / 2 + cfs + 4), "font-size": cfs, fill: t.text, class: "ax" }, labels, trunc(m.cats[ci].name, BW - (tx - box.l), cfs));
            });
            return;
        }
        /* rows: one row of icons per category, each icon a number of units */
        const vals = m.cats.map((_, ci) => (m.grid[ci][0] ? (m.grid[ci][0] as Cell).v : 0)), mx = Math.max(...vals, 0);
        const per = PG.perRow.value > 0 ? PG.perRow.value : 20, unit = PG.unit.value > 0 ? PG.unit.value : nice(0, mx / per, 1).ticks[1] || 1;
        const nameW = CA.show.value ? Math.min(BW * 0.3, Math.max(...m.cats.map(x => textW(x.name, cfs)))) + 10 : 0, valW = LB.show.value ? Math.max(...vals.map(v => textW(fmtV(v), lbfs))) + 8 : 0;
        const rowH = BH / Math.max(1, N) - (N > 1 ? 2 : 0), size = Math.max(5, Math.min(rowH * 0.8, (BW - nameW - valW) / per * 0.9)), stepI = size / 0.9;
        m.cats.forEach((ct, ci) => {
            const a = m.grid[ci][0]; if (!a) return;
            const y = box.t + (BH / N) * ci + (BH / N - size) / 2, nIcons = Math.min(per, a.v / unit), col = catColor(ci);
            const g = el("g", { class: "mk" + (on(a) ? "" : " dim") }, marks);
            for (let i = 0; i < Math.ceil(nIcons - 1e-9); i++) drawIcon(g, box.l + nameW + i * stepI, y, size, t.hc ? t.ink : col, Math.min(1, nIcons - i));
            c.bind(g, cellT(a));
            if (CA.show.value) c.io.bindLabel(el("text", { x: r1(box.l + nameW - 8), y: r1(y + size / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, labels, trunc(ct.name, nameW - 10, cfs)), catTarget(m, ci));
            if (LB.show.value) el("text", { x: r1(box.l + nameW + Math.ceil(nIcons) * stepI + 4), y: r1(y + size / 2 + lbfs * 0.35), "font-size": lbfs, fill: lbC, class: "lbl" }, labels, fmtV(a.v));
        });
        el("text", { x: r1(box.r), y: r1(box.b - 2), "text-anchor": "end", "font-size": Math.max(7, cfs - 1), fill: t.axis, class: "ax" }, labels, `each icon = ${fmtV(unit)}`);
    }

    /* ================================================================ aster and rose: wedges around a center */
    function wedge(cx: number, cy: number, r0: number, r1_: number, a0: number, a1: number, gap: number): string {
        const pa = r1_ > 0 ? gap / 2 / r1_ : 0, s1 = a0 + Math.min(pa, (a1 - a0) / 2), e1 = a1 - Math.min(pa, (a1 - a0) / 2);
        const pb = r0 > 0 ? gap / 2 / r0 : 0, s0 = a0 + Math.min(pb, (a1 - a0) / 2), e0 = a1 - Math.min(pb, (a1 - a0) / 2);
        const P = (a: number, r: number) => `${r1(cx + Math.sin(a) * r)},${r1(cy - Math.cos(a) * r)}`, lg1 = e1 - s1 > Math.PI ? 1 : 0, lg0 = e0 - s0 > Math.PI ? 1 : 0;
        return `M${P(s1, r1_)}A${r1(r1_)},${r1(r1_)} 0 ${lg1} 1 ${P(e1, r1_)}L${P(e0, r0)}` + (r0 > 0 ? `A${r1(r0)},${r1(r0)} 0 ${lg0} 0 ${P(s0, r0)}` : "") + "Z";
    }
    /** a category name outside the circle; clicking it selects the whole category (every wedge of that month, say) */
    function outsideLabel(cx: number, cy: number, R: number, mid: number, text: string, g: Element, ct?: Colored) {
        const x = cx + Math.sin(mid) * (R + 8), y = cy - Math.cos(mid) * (R + 8), anchor = Math.abs(Math.sin(mid)) < 0.25 ? "middle" : Math.sin(mid) > 0 ? "start" : "end";
        const tx = el("text", { x: r1(x), y: r1(y + cfs * 0.35 + (Math.cos(mid) < -0.9 ? cfs * 0.4 : 0)), "text-anchor": anchor, "font-size": cfs, fill: cC, class: "ax" + (ct && !c.io.anyOn(ct.items) ? " dim" : "") }, g, text);
        if (ct && ct.id) { tx.setAttribute("style", "pointer-events:all;cursor:pointer"); c.bind(tx, { key: "c" + ct.key, items: ct.items, ids: [ct.id], tip: () => [{ displayName: m.catTitle, value: ct.name }, { displayName: m.series.length > 1 ? "Total" : m.series[0].name, value: fmtTip(ct.items.reduce((a, i) => a + m.cells[i].v, 0)) }] }); }
    }
    function aster() {
        const RD = s.radial, scores = m.cats.map((_, ci) => m.grid[ci][0]), weights = m.cats.map((_, ci) => (m.byMeasure && S >= 2 && m.grid[ci][1] ? Math.max(0, (m.grid[ci][1] as Cell).v) : 1));
        const wsum = weights.reduce((a, b) => a + b, 0) || 1, mx = RD.maxScore.value > 0 ? RD.maxScore.value : Math.max(...scores.map(x => (x ? x.v : 0)));
        const labW = CA.show.value ? Math.min(BW * 0.22, Math.max(...m.cats.map(x => textW(x.name, cfs)))) : 0;
        const R = Math.max(10, Math.min((BW - 2 * labW - 20) / 2, (BH - 2 * cfs - 16) / 2)), cx = box.l + BW / 2, cy = box.t + BH / 2, hole = R * RD.hole.value / 100;
        let a = 0;
        m.cats.forEach((ct, ci) => {
            const span = 2 * Math.PI * weights[ci] / wsum, x = scores[ci], a0 = a, a1 = a + span; a = a1;
            if (span <= 0) return;
            if (RD.outline.value) el("path", { d: wedge(cx, cy, hole, R, a0, a1, RD.gap.value), fill: empty, stroke: "none" }, back);
            if (CA.show.value) outsideLabel(cx, cy, R, (a0 + a1) / 2, trunc(ct.name, labW + 6, cfs), labels, ct);
            if (!x) return;
            const rr = hole + (R - hole) * Math.max(0, Math.min(1.05, x.v / (mx || 1))), col = catColor(ci);
            const g = el("g", { class: "mk" + (on(x) ? "" : " dim") }, marks);
            el("path", { d: wedge(cx, cy, hole, rr, a0, a1, RD.gap.value), fill: t.hc ? t.surface : look.fill(col, "r"), stroke: t.hc ? t.ink : "none" }, g);
            c.bind(g, cellT(x));
            if (LB.show.value && rr - hole > lbfs + 6) { const mid = (a0 + a1) / 2, lr = (hole + rr) / 2; el("text", { x: r1(cx + Math.sin(mid) * lr), y: r1(cy - Math.cos(mid) * lr + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: t.hc ? t.ink : inkOn(col), class: "ax" }, labels, fmtV(x.v)); }
        });
        if (RD.centerText.value && hole > 14) {
            const avg = m.cats.reduce((acc, _, ci) => acc + (scores[ci] ? (scores[ci] as Cell).v * weights[ci] : 0), 0) / wsum;
            el("text", { x: r1(cx), y: r1(cy + hole * 0.18), "text-anchor": "middle", "font-size": r1(Math.min(hole * 0.62, 34)), fill: t.text, class: "ttl" }, labels, fmtV(avg));
        }
    }
    function rose() {
        const RD = s.radial, stacked = S > 1 && multi;
        const tots = m.cats.map((_, ci) => m.grid[ci].reduce((acc, x) => acc + (x ? Math.max(0, x.v) : 0), 0)), mx = Math.max(...tots, 1e-9);
        const labW = CA.show.value ? Math.min(BW * 0.18, Math.max(...m.cats.map(x => textW(x.name, cfs)))) : 0;
        const R = Math.max(10, Math.min((BW - 2 * labW - 20) / 2, (BH - 2 * cfs - 16) / 2)), cx = box.l + BW / 2, cy = box.t + BH / 2, hole = R * RD.hole.value / 100;
        const rad = (v: number) => hole + (R - hole) * Math.sqrt(Math.max(0, v) / mx);   /* area, not radius, follows the value */
        const span = 2 * Math.PI / Math.max(1, N);
        [0.25, 0.5, 0.75, 1].forEach(f => el("circle", { cx: r1(cx), cy: r1(cy), r: r1(rad(mx * f)), fill: "none", stroke: t.grid, "stroke-width": 1 }, back));
        m.cats.forEach((ct, ci) => {
            const a0 = span * ci, a1 = a0 + span;
            let acc = 0;
            (stacked ? m.grid[ci] : [m.grid[ci][0]]).forEach(x => {
                if (!x || x.v <= 0) return;
                const r0 = rad(acc), r1_ = rad(acc + x.v); acc += x.v;
                let col = cellColor(x);
                /* one color, lighter for smaller months (the first palette color) */
                if (!stacked && RD.shadeByValue.value) col = mix(c.colorOf(m.cats[0]), t.surface, 0.65 * (1 - x.v / mx));
                const g = el("g", { class: "mk" + (on(x) ? "" : " dim") }, marks);
                el("path", { d: wedge(cx, cy, r0, r1_, a0, a1, RD.gap.value), fill: t.hc ? t.surface : look.fill(col, "r"), stroke: t.hc ? t.ink : "none" }, g);
                c.bind(g, cellT(x, x.v / (tots[ci] || 1)));
            });
            if (CA.show.value) outsideLabel(cx, cy, R, (a0 + a1) / 2, trunc(ct.name, labW + 6, cfs), labels, ct);
            if (LB.show.value && tots[ci] > 0) { const mid = (a0 + a1) / 2, rr = rad(tots[ci]) + lbfs * 0.9; if (rr < R + 2) el("text", { x: r1(cx + Math.sin(mid) * rr), y: r1(cy - Math.cos(mid) * rr + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, labels, fmtV(tots[ci])); }
        });
    }

    /* ================================================================ Venn */
    function venn() {
        const sep = (s.venn.separator.value || "&").trim() || "&";
        const parts = m.cats.map(ct => ct.name.split(sep).map(x => x.trim()).filter(x => x));
        const sets: string[] = [];
        parts.forEach(p => p.forEach(x => { if (!sets.includes(x)) sets.push(x); }));
        if (sets.length < 2 || sets.length > 3) { note(c.msg("Venn_Sets", `A Venn diagram needs 2 or 3 sets. Write overlaps in Category as "A ${sep} B".`)); return; }
        const valOf = (ci: number) => (m.grid[ci][0] ? Math.max(0, (m.grid[ci][0] as Cell).v) : 0);
        const total = (names: string[]) => parts.reduce((acc, p, ci) => acc + (names.every(nm => p.includes(nm)) ? valOf(ci) : 0), 0);
        const setTot = sets.map(x => total([x])), all = parts.reduce((a, _, ci) => a + valOf(ci), 0) || 1;
        const maxT = Math.max(...setTot, 1e-9), r0 = sets.map(v => Math.sqrt(setTot[sets.indexOf(v)] / maxT));
        /* layout in unit space: pairwise distances from overlap areas */
        const area = (k: number) => Math.PI * r0[k] * r0[k];
        const d = (i: number, j: number) => distFor(r0[i], r0[j], total([sets[i], sets[j]]) / (setTot[i] || 1) * area(i));
        const pos: [number, number][] = [[0, 0], [d(0, 1), 0]];
        if (sets.length === 3) {
            const a = d(0, 1), b = d(0, 2), cc = d(1, 2);
            let x = (b * b - cc * cc + a * a) / (2 * a), yy = b * b - x * x;
            if (yy < 0) { x = Math.max(-b, Math.min(b, x)); yy = Math.max(0, b * b - x * x); }
            pos.push([x, Math.sqrt(yy)]);
        }
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        pos.forEach((p, k) => { minX = Math.min(minX, p[0] - r0[k]); maxX = Math.max(maxX, p[0] + r0[k]); minY = Math.min(minY, p[1] - r0[k]); maxY = Math.max(maxY, p[1] + r0[k]); });
        const nameH = cfs + 8, scale = Math.min((BW - 16) / (maxX - minX), (BH - 2 * nameH) / (maxY - minY));
        const ox = box.l + (BW - (maxX - minX) * scale) / 2 - minX * scale, oy = box.t + nameH + (BH - 2 * nameH - (maxY - minY) * scale) / 2 - minY * scale;
        const P = (p: [number, number]): [number, number] => [ox + p[0] * scale, oy + p[1] * scale], R = r0.map(r => r * scale), Cc = pos.map(P);
        const op = s.venn.opacity.value / 100;
        const setColor = (k: number) => { const ci = parts.findIndex(p => p.length === 1 && p[0] === sets[k]); return ci >= 0 ? catColor(ci) : catColor(k % N); };
        sets.forEach((nm, k) => {
            const items = parts.map((p, ci) => (p.includes(nm) && m.grid[ci][0] ? (m.grid[ci][0] as Cell).i : -1)).filter(i => i >= 0);
            const g = el("g", { class: "grp" + (c.io.anyOn(items) ? "" : " dim") }, marks), col = setColor(k);
            el("circle", { cx: r1(Cc[k][0]), cy: r1(Cc[k][1]), r: r1(R[k]), fill: t.hc ? "none" : look.flat ? col : look.fill(col, "r"), "fill-opacity": op, stroke: t.hc ? t.ink : col, "stroke-width": 1.5 }, g);
            c.bind(g, { key: "set" + k, items, ids: items.map(i => m.cells[i].id), tip: () => [{ displayName: nm, value: fmtTip(setTot[k]), color: col }, { displayName: "Share of all", value: pct(setTot[k] / all) }] });
            /* set name outside the circle, away from the center of the diagram */
            const gx = Cc.reduce((a, p) => a + p[0], 0) / Cc.length, gy = Cc.reduce((a, p) => a + p[1], 0) / Cc.length;
            let dx = Cc[k][0] - gx, dy = Cc[k][1] - gy; const len = Math.hypot(dx, dy) || 1; dx /= len; dy /= len;
            if (sets.length === 2) { dx = k === 0 ? -0.5 : 0.5; dy = -0.87; }
            const lx = Cc[k][0] + dx * (R[k] + 6), ly = Cc[k][1] + dy * (R[k] + 6);
            el("text", { x: r1(lx), y: r1(ly + (dy > 0.3 ? cfs : dy < -0.3 ? -2 : cfs * 0.35)), "text-anchor": dx > 0.3 ? "start" : dx < -0.3 ? "end" : "middle", "font-size": cfs, fill: t.hc ? t.ink : mix(col, t.ink, 0.35), class: "ttl" }, labels, trunc(nm, BW / 2, cfs));
        });
        /* region labels at the point deepest inside each region (sampled grid) */
        if (LB.show.value) {
            const inside = (x: number, y: number) => Cc.map((p, k) => Math.hypot(x - p[0], y - p[1]) < R[k]);
            const best = new Map<string, { x: number; y: number; d: number }>();
            const x0 = Math.min(...Cc.map((p, k) => p[0] - R[k])), x1 = Math.max(...Cc.map((p, k) => p[0] + R[k])), y0 = Math.min(...Cc.map((p, k) => p[1] - R[k])), y1 = Math.max(...Cc.map((p, k) => p[1] + R[k]));
            for (let i = 0; i <= 60; i++) for (let j = 0; j <= 60; j++) {
                const x = x0 + (x1 - x0) * i / 60, y = y0 + (y1 - y0) * j / 60, inn = inside(x, y); if (!inn.some(Boolean)) continue;
                const key = sets.filter((_, k) => inn[k]).sort().join("|"), dist = Math.min(...Cc.map((p, k) => Math.abs(Math.hypot(x - p[0], y - p[1]) - R[k])));
                const b = best.get(key); if (!b || dist > b.d) best.set(key, { x, y, d: dist });
            }
            parts.forEach((p, ci) => {
                const x = m.grid[ci][0], b = best.get(p.slice().sort().join("|")); if (!x || !b) return;
                const g = el("g", { class: "mk" }, labels);
                el("text", { x: r1(b.x), y: r1(b.y + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs + 1, fill: t.ink, class: "lbl", "pointer-events": "all" }, g, lab(x.v, x.v / all));
                c.bind(g, cellT(x, x.v / all));
            });
        }
    }
}
