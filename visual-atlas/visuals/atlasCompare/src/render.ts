/*
 * Drawing for Atlas Compare: lollipop, dot plot, dumbbell, slope, bump,
 * tornado and radar from one category × series matrix, with the shared
 * value axis, legend and labels, in flat, soft and 3D looks.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Cell, catTarget } from "./model";
import { CompareSettings } from "./settings";
import { Ctx, Colored } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix } from "./common/color";
import { colorOr, val } from "./common/cards";
import { nice, parseNum, domain, tickWidth, valueAxis, legend, LegendItem } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<CompareSettings, Model>;

/** marker of a given shape centered on x, y */
function marker(parent: Element, shape: string, x: number, y: number, r: number, attrs: Record<string, string | number | null>) {
    if (shape === "square") return el("rect", { x: r1(x - r), y: r1(y - r), width: r1(2 * r), height: r1(2 * r), rx: r1(r * 0.25), ...attrs }, parent);
    if (shape === "diamond") return el("path", { d: `M${r1(x)},${r1(y - r * 1.25)}L${r1(x + r * 1.25)},${r1(y)}L${r1(x)},${r1(y + r * 1.25)}L${r1(x - r * 1.25)},${r1(y)}Z`, ...attrs }, parent);
    return el("circle", { cx: r1(x), cy: r1(y), r: r1(r), ...attrs }, parent);
}
/** smooth path through points with horizontal tangents */
function smoothPath(p: [number, number][]): string {
    let d = `M${r1(p[0][0])},${r1(p[0][1])}`;
    for (let i = 1; i < p.length; i++) { const mx = (p[i - 1][0] + p[i][0]) / 2; d += `C${r1(mx)},${r1(p[i - 1][1])} ${r1(mx)},${r1(p[i][1])} ${r1(p[i][0])},${r1(p[i][1])}`; }
    return d;
}
const linePath = (p: [number, number][]) => "M" + p.map(q => `${r1(q[0])},${r1(q[1])}`).join("L");
/** spread label positions so they keep a minimum gap (labels at the ends of slope and bump lines) */
function spread(ys: number[], gap: number, lo: number, hi: number): number[] {
    const idx = ys.map((y, i) => i).sort((a, b) => ys[a] - ys[b]), out = ys.slice();
    for (let k = 1; k < idx.length; k++) out[idx[k]] = Math.max(out[idx[k]], out[idx[k - 1]] + gap);
    const over = idx.length ? out[idx[idx.length - 1]] - hi : 0;
    if (over > 0) for (let k = idx.length - 1; k >= 0; k--) { out[idx[k]] = Math.min(out[idx[k]], (k === idx.length - 1 ? hi : out[idx[k + 1]] - gap)); out[idx[k]] = Math.max(out[idx[k]], lo); }
    return out;
}

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6;
    const MK = s.marks, LB = s.labels, CA = s.categoryAxis, VA = s.valueAxis, GR = s.gridlines;
    const cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value), cC = colorOr(CA.color, t.text), lbC = colorOr(LB.color, t.text);
    const up = colorOr(MK.upColor, "#1a9e5c"), down = colorOr(MK.downColor, "#d64550"), shape = val(MK.shape), msz = Math.max(1, MK.size.value);
    const focus = s.chart.focus.value.trim().toLowerCase(), gray = mix(t.text, t.surface, 0.72);
    const fmt = (si: number) => labelFormatter(m.formats[si] || m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...m.cells.map(x => Math.abs(x.v))), c.culture);
    const fmtL = m.series.map((_, i) => fmt(i)), fmtTip = m.series.map((_, i) => formatter(m.formats[i] || m.format, 1, null, 0, c.culture));
    const S = m.series.length, N = m.cats.length;
    const focused = (name: string) => !focus || name.toLowerCase() === focus;
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root);

    /* tooltips and targets */
    const cellTip = (x: Cell): TipItem[] => {
        const items: TipItem[] = [{ displayName: m.catTitle, value: m.cats[x.c].name }];
        if (m.serTitle) items.push({ displayName: m.serTitle, value: m.series[x.s].name });
        items.push({ displayName: m.serTitle ? "Value" : m.series[x.s].name, value: fmtTip[x.s](x.v), color: c.colorOf(m.series[x.s]) });
        if (x.hlv !== null) items.push({ displayName: "Before the selection", value: fmtTip[x.s](x.full) });
        x.tips.forEach(tp => items.push({ displayName: tp.name, value: tp.value }));
        return items;
    };
    const cellT = (x: Cell): Target => ({ key: "i" + x.i, items: [x.i], ids: [x.id], tip: () => cellTip(x) });
    const groupT = (g: Colored, kind: string, tip: () => TipItem[]): Target => ({ key: kind + g.key, items: g.items, ids: g.id ? [g.id] : [], tip });
    const catTip = (ci: number) => (): TipItem[] => [{ displayName: m.catTitle, value: m.cats[ci].name }].concat(m.series.map((sr, si) => {
        const x = m.grid[ci][si]; return { displayName: sr.name, value: x ? fmtTip[si](x.v) : "(Blank)", color: c.colorOf(sr) } as TipItem;
    }));
    const serTip = (si: number) => (): TipItem[] => [{ displayName: m.serTitle || "Series", value: m.series[si].name, color: c.colorOf(m.series[si]) } as TipItem].concat(
        m.series[si].items.slice(0, 12).map(i => { const x = m.cells[i]; return { displayName: m.cats[x.c].name, value: fmtTip[si](x.v) }; }));

    /* legend: series, shown when there are two or more */
    const lgItems: LegendItem[] = m.series.map((sr, si) => ({ key: sr.key, name: sr.name, color: c.colorOf(sr), on: c.io.anyOn(sr.items) && focused(sr.name), shape: type === "slope" || type === "bump" || type === "radar" ? "line" : "dot", target: groupT(sr, "s", serTip(si)) }));
    const lg = legend(s.legend, lgItems, m.serTitle, W, H, pad, t, S > 1 && type !== "slope" && !(type === "radar" && s.radar.multiples.value));
    const box = { l: pad, t: pad + lg.top, r: W - pad - lg.right, b: H - pad - lg.bottom };
    const note = (text: string) => {
        const lines: string[] = []; let cur = "";
        text.split(" ").forEach(w => { const nx = cur ? cur + " " + w : w; if (cur && textW(nx, 12) > W - 24) { lines.push(cur); cur = w; } else cur = nx; });
        if (cur) lines.push(cur);
        lines.forEach((ln, k) => el("text", { x: r1(W / 2), y: r1(H / 2 + (k - (lines.length - 1) / 2) * 16), "text-anchor": "middle", "font-size": 12, fill: t.text, class: "note" }, root, ln));
    };

    /* category order for list charts */
    const order = m.cats.map((_, i) => i);
    const sort = val(s.chart.sort), last = (ci: number) => { for (let si = S - 1; si >= 0; si--) { const x = m.grid[ci][si]; if (x) return x.v; } return NaN; };
    const first = (ci: number) => { for (let si = 0; si < S; si++) { const x = m.grid[ci][si]; if (x) return x.v; } return NaN; };
    const nn = (v: number) => (isNaN(v) ? -Infinity : v);
    if (sort === "valueDesc") order.sort((a, b) => nn(last(b)) - nn(last(a)));
    else if (sort === "valueAsc") order.sort((a, b) => nn(last(a)) - nn(last(b)));
    else if (sort === "changeDesc") order.sort((a, b) => type === "tornado" ? nn(Math.abs(last(b) - first(b))) - nn(Math.abs(last(a) - first(a))) : nn(last(b) - first(b)) - nn(last(a) - first(a)));
    else if (sort === "name") order.sort((a, b) => m.cats[a].name.localeCompare(m.cats[b].name));

    if (type === "slope") slope();
    else if (type === "bump") bump();
    else if (type === "radar") radar();
    else if (type === "tornado") tornado();
    else list();
    lg.draw(root, c.bind);

    /* ================================================================ lollipop, dot plot, dumbbell */
    function list() {
        const horiz = val(s.chart.orientation) === "horizontal", n = order.length;
        const vals = m.cells.map(x => x.v), lbW = LB.show.value ? Math.max(...m.cells.map(x => textW(fmtL[x.s](x.v), lbfs))) + msz + 6 : 0;
        const names = order.map(ci => m.cats[ci].name), cTitle = CA.title.value ? m.catTitle : "";
        let L: number, R: number, T: number, B: number;
        const zero = type === "lollipop";
        let d = domain(Math.min(...vals), Math.max(...vals), horiz ? box.r - box.l : box.b - box.t, horiz ? 80 : 44, VA, m.format, c.culture, zero);
        if (horiz) {
            const nameW = CA.show.value ? Math.min(W * 0.35, Math.max(...names.map(x => textW(x, cfs)))) + 10 : 0;
            L = box.l + nameW + (cTitle ? cfs + 8 : 0); R = box.r - lbW - (look.is3d ? 4 : 0);
            T = box.t + 2; B = box.b - (VA.show.value ? Math.max(6, VA.fontSize.value) + 8 : 0);
            d = domain(Math.min(...vals), Math.max(...vals), R - L, 80, VA, m.format, c.culture, zero);
        } else {
            T = box.t + (LB.show.value ? lbfs + 6 : 4); B = box.b - (CA.show.value ? cfs + 8 : 0) - (cTitle ? cfs + 6 : 0);
            d = domain(Math.min(...vals), Math.max(...vals), B - T, 44, VA, m.format, c.culture, zero);
            L = box.l + tickWidth(d, VA); R = box.r - 4;
        }
        const V = (v: number) => (horiz ? L + (Math.max(d.lo, Math.min(d.hi, v)) - d.lo) / (d.hi - d.lo) * (R - L) : B - (Math.max(d.lo, Math.min(d.hi, v)) - d.lo) / (d.hi - d.lo) * (B - T));
        const band = (horiz ? B - T : R - L) / Math.max(1, n), U = (k: number) => (horiz ? T : L) + band * (k + 0.5);
        const P = (u: number, v: number): [number, number] => (horiz ? [V(v), u] : [u, V(v)]);
        valueAxis(root, d, V, { L, R, T, B }, !horiz, VA, GR, t);
        if (zero && d.lo < 0 && d.hi > 0) { const z = V(0); el("line", horiz ? { x1: r1(z), x2: r1(z), y1: r1(T), y2: r1(B), stroke: t.axis, "stroke-width": 1 } : { x1: r1(L), x2: r1(R), y1: r1(z), y2: r1(z), stroke: t.axis, "stroke-width": 1 }, root); }
        const r = Math.max(1, Math.min(msz, band * 0.42));
        const colorBy = val(MK.colorBy);
        const cellColor = (x: Cell) => {
            if (t.hc) return t.ink;
            if (type === "lollipop" && S === 1 && colorBy === "sign") return x.v >= 0 ? up : down;
            if (type === "lollipop" && S === 1 && colorBy === "category") return m.cats[x.c].color || c.colorOf(m.series[0]);
            return c.colorOf(m.series[x.s]);
        };
        const lab = el("g", {}, root), skip = horiz ? Math.max(1, Math.ceil(cfs * 1.15 / band)) : 1;
        order.forEach((ci, k) => {
            const u = U(k), row = m.grid[ci], present = row.map((x, si) => ({ x, si })).filter(o => o.x) as { x: Cell; si: number }[];
            const g = el("g", { class: "grp" + (c.io.anyOn(m.cats[ci].items) && focused(m.cats[ci].name) ? "" : " dim") }, marks);
            if (CA.show.value && k % skip === 0) {
                if (horiz) c.io.bindLabel(el("text", { x: r1(L - 8), y: r1(u + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, lab, trunc(names[k], L - box.l - 10 - (cTitle ? cfs + 8 : 0), cfs)), catTarget(m, ci));
                else c.io.bindLabel(el("text", { x: r1(u), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, lab, trunc(names[k], band - 2, cfs)), catTarget(m, ci));
            }
            if (!present.length) return;
            if (type === "lollipop") {
                const sub = band * 0.7 / present.length;
                present.forEach((o, j) => {
                    const uu = present.length > 1 ? u - band * 0.35 + sub * (j + 0.5) : u, col = cellColor(o.x), base = d.lo > 0 ? d.lo : d.hi < 0 ? d.hi : 0;
                    const a = P(uu, base), b = P(uu, o.x.v);
                    el("line", { x1: r1(a[0]), y1: r1(a[1]), x2: r1(b[0]), y2: r1(b[1]), stroke: col, "stroke-width": MK.stemWidth.value, "stroke-linecap": "round", class: c.io.on(o.x.i) ? "" : "dim" }, g);
                    const mk = marker(g, shape, b[0], b[1], Math.min(r, sub * 0.45 + 1), { fill: look.flat ? col : look.fill(col, "r"), class: "mk" + (c.io.on(o.x.i) ? "" : " dim") });
                    c.bind(mk, cellT(o.x));
                    if (LB.show.value) { const neg = o.x.v < 0, txt = fmtL[o.si](o.x.v); el("text", horiz ? { x: r1(b[0] + (neg ? -r - 4 : r + 4)), y: r1(b[1] + lbfs * 0.35), "text-anchor": neg ? "end" : "start", "font-size": lbfs, fill: lbC, class: "lbl" } : { x: r1(b[0]), y: r1(b[1] + (neg ? r + lbfs + 2 : -r - 4)), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, txt); }
                });
                return;
            }
            const lo = Math.min(...present.map(o => o.x.v)), hi = Math.max(...present.map(o => o.x.v));
            if (present.length > 1) {
                const a = P(u, lo), b = P(u, hi);
                let col = mix(t.text, t.surface, 0.55), w = type === "dot" ? Math.max(1, MK.lineWidth.value * 0.6) : MK.lineWidth.value;
                if (type === "dumbbell" && present.length === 2 && val(MK.connector) === "direction") col = present[1].x.v >= present[0].x.v ? up : down;
                if (type === "dot") { col = mix(t.text, t.surface, 0.82); w = Math.max(w, r * 0.9); }
                el("line", { x1: r1(a[0]), y1: r1(a[1]), x2: r1(b[0]), y2: r1(b[1]), stroke: t.hc ? t.ink : col, "stroke-width": w, "stroke-linecap": "round" }, g);
            } else if (type === "dot") {
                const a = P(u, d.lo), b = P(u, d.hi);
                el("line", { x1: r1(a[0]), y1: r1(a[1]), x2: r1(b[0]), y2: r1(b[1]), stroke: mix(t.text, t.surface, 0.9), "stroke-width": 1, "stroke-dasharray": "1.5 3" }, g);
            }
            present.forEach(o => {
                const p = P(u, o.x.v), col = cellColor(o.x);
                const mk = marker(g, shape, p[0], p[1], r, { fill: look.flat ? col : look.fill(col, "r"), stroke: t.surface, "stroke-width": 1.2, class: "mk" + (c.io.on(o.x.i) ? "" : " dim") });
                c.bind(mk, cellT(o.x));
            });
            if (LB.show.value) {
                const hiP = P(u, hi), si = present[present.length - 1].si;
                let txt = fmtL[si](present[present.length - 1].x.v);
                if (type === "dumbbell" && present.length === 2 && present[0].x.v) { const ch = (present[1].x.v / present[0].x.v - 1) * 100; txt = (ch >= 0 ? "+" : "") + ch.toFixed(Math.abs(ch) < 10 ? 1 : 0) + "%"; }
                el("text", horiz ? { x: r1(hiP[0] + r + 5), y: r1(hiP[1] + lbfs * 0.35), "font-size": lbfs, fill: lbC, class: "lbl" } : { x: r1(hiP[0]), y: r1(hiP[1] - r - 4), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, txt);
            }
        });
        if (cTitle) {
            if (horiz) el("text", { x: r1(box.l + cfs * 0.8), y: r1((T + B) / 2), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ttl", transform: `rotate(-90 ${r1(box.l + cfs * 0.8)} ${r1((T + B) / 2)})` }, root, trunc(cTitle, B - T, cfs));
            else el("text", { x: r1((L + R) / 2), y: r1(box.b - 2), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ttl" }, root, trunc(cTitle, R - L, cfs));
        }
    }

    /* ================================================================ tornado */
    function tornado() {
        if (S < 2) { note(c.msg("Need_Two_Series", "A tornado needs two series: two measures in Values, or a Legend with two values.")); return; }
        const TR = s.tornado, mirror = val(TR.mode) === "mirror", base = TR.base.value, n = order.length;
        const names = order.map(ci => m.cats[ci].name), center = mirror && TR.center.value && CA.show.value;
        const nameW = CA.show.value ? Math.min(W * 0.28, Math.max(...names.map(x => textW(x, cfs)))) + 12 : 0;
        const vfs = Math.max(6, VA.fontSize.value), lbW = LB.show.value ? Math.max(...m.cells.map(x => textW(fmtL[x.s](x.v), lbfs))) + 6 : 0;
        const T = box.t + 2, B = box.b - (VA.show.value ? vfs + 8 : 0);
        const band = (B - T) / Math.max(1, n), bh = Math.max(2, band * 0.68);
        const cellsOf = (ci: number) => [m.grid[ci][0], m.grid[ci][1]];
        const bars = marks, lab = el("g", {}, root);
        const sh3 = look.is3d ? 5 : 0;
        const bar = (x0: number, x1: number, y: number, col: string, cell: Cell, end: "l" | "r") => {
            const a = Math.min(x0, x1), w = Math.max(1, Math.abs(x1 - x0)), on = c.io.on(cell.i);
            const g = el("g", { class: "mk" + (on ? "" : " dim") }, bars);
            if (sh3) { el("path", { d: `M${r1(a)},${r1(y)}l${sh3},${-sh3 * 0.6}h${r1(w)}l${-sh3},${sh3 * 0.6}Z`, fill: look.top(col) }, g); if (end === "r") el("path", { d: `M${r1(a + w)},${r1(y)}l${sh3},${-sh3 * 0.6}v${r1(bh)}l${-sh3},${sh3 * 0.6}Z`, fill: look.side(col) }, g); }
            const rr = look.is3d ? 0 : Math.min(4, bh / 2);
            const d = end === "r" ? `M${r1(a)},${r1(y)}H${r1(a + w - rr)}A${rr},${rr} 0 0 1 ${r1(a + w)},${r1(y + rr)}V${r1(y + bh - rr)}A${rr},${rr} 0 0 1 ${r1(a + w - rr)},${r1(y + bh)}H${r1(a)}Z`
                : `M${r1(a + w)},${r1(y)}H${r1(a + rr)}A${rr},${rr} 0 0 0 ${r1(a)},${r1(y + rr)}V${r1(y + bh - rr)}A${rr},${rr} 0 0 0 ${r1(a + rr)},${r1(y + bh)}H${r1(a + w)}Z`;
            el("path", { d, fill: t.hc ? t.ink : look.fill(col, "h") }, g);
            c.bind(g, cellT(cell));
        };
        if (mirror) {
            const mx = Math.max(...m.cells.filter(x => x.s < 2).map(x => Math.abs(x.v))) || 1;
            const nt = nice(0, mx, 4), half = (box.r - box.l - (center ? nameW : nameW) - 2 * lbW) / 2;
            const cx0 = center ? box.l + lbW + half : box.l + nameW + lbW + half, cx1 = center ? cx0 + nameW : cx0;
            const Lx = (v: number) => cx0 - Math.min(1, Math.abs(v) / nt.hi) * half, Rx = (v: number) => cx1 + Math.min(1, Math.abs(v) / nt.hi) * half;
            const f = formatter(m.format, Number(VA.displayUnits.value) || 0, VA.decimals.value >= 0 ? VA.decimals.value : null, nt.hi, c.culture);
            nt.ticks.forEach(v => {
                [Lx(v), Rx(v)].forEach(x => {
                    if (GR.show.value) el("line", { x1: r1(x) + 0.5, x2: r1(x) + 0.5, y1: r1(T), y2: r1(B), stroke: colorOr(GR.color, t.grid), "stroke-width": GR.width.value }, root);
                    if (VA.show.value) el("text", { x: r1(x), y: r1(B + vfs + 4), "text-anchor": "middle", "font-size": vfs, fill: colorOr(VA.color, t.axis), class: "ax" }, root, v === 0 ? "0" : f(v));
                });
            });
            order.forEach((ci, k) => {
                const y = T + band * k + (band - bh) / 2, [a, b] = cellsOf(ci);
                if (a) bar(cx0, Lx(a.v), y, c.colorOf(m.series[0]), a, "l");
                if (b) bar(cx1, Rx(b.v), y, c.colorOf(m.series[1]), b, "r");
                if (CA.show.value) c.io.bindLabel(el("text", center ? { x: r1((cx0 + cx1) / 2), y: r1(y + bh / 2 + cfs * 0.35), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" } : { x: r1(box.l + nameW - 6), y: r1(y + bh / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, lab, trunc(names[k], nameW - 8, cfs)), catTarget(m, ci));
                if (LB.show.value) {
                    if (a) el("text", { x: r1(Lx(a.v) - 4), y: r1(y + bh / 2 + lbfs * 0.35), "text-anchor": "end", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, fmtL[0](a.v));
                    if (b) el("text", { x: r1(Rx(b.v) + 4), y: r1(y + bh / 2 + lbfs * 0.35), "font-size": lbfs, fill: lbC, class: "lbl" }, lab, fmtL[1](b.v));
                }
            });
        } else {
            const vals = m.cells.filter(x => x.s < 2).map(x => x.v).concat([base]);
            const L = box.l + nameW + lbW, R = box.r - lbW;
            const d = domain(Math.min(...vals), Math.max(...vals), R - L, 80, VA, m.format, c.culture, false);
            const X = (v: number) => L + (Math.max(d.lo, Math.min(d.hi, v)) - d.lo) / (d.hi - d.lo) * (R - L);
            valueAxis(root, d, X, { L, R, T, B }, false, VA, GR, t);
            order.forEach((ci, k) => {
                const y = T + band * k + (band - bh) / 2;
                cellsOf(ci).forEach((x, si) => { if (x) bar(X(base), X(x.v), y, c.colorOf(m.series[si]), x, x.v >= base ? "r" : "l"); });
                if (CA.show.value) c.io.bindLabel(el("text", { x: r1(box.l + nameW - 6), y: r1(y + bh / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, lab, trunc(names[k], nameW - 8, cfs)), catTarget(m, ci));
                if (LB.show.value) cellsOf(ci).forEach((x, si) => { if (x) { const right = x.v >= base; el("text", { x: r1(X(x.v) + (right ? 4 : -4)), y: r1(y + bh / 2 + lbfs * 0.35), "text-anchor": right ? "start" : "end", "font-size": lbfs, fill: lbC, class: "lbl" }, lab, fmtL[si](x.v)); } });
            });
            const bx = r1(X(base)) + 0.5;
            el("line", { x1: bx, x2: bx, y1: r1(T - 2), y2: r1(B), stroke: t.ink, "stroke-width": 1.5 }, root);
        }
    }

    /* ================================================================ slope */
    function slope() {
        if (S < 2) { note(c.msg("Need_Two_Series", "A slope chart needs two series: two measures in Values, or a Legend with two or more values.")); return; }
        const vals = m.cells.map(x => x.v), d = nice(Math.min(...vals), Math.max(...vals), 4);
        const lfs = cfs, names = m.cats.map(x => x.name);
        const fmts = (si: number, v: number) => fmtL[si](v);
        const sideW = CA.show.value ? Math.min(W * 0.26, Math.max(...names.map(x => textW(x, lfs)))) : 0;
        const valW = Math.max(...m.cells.map(x => textW(fmts(x.s, x.v), lfs))) + 6;
        const T = box.t + lfs + 10, B = box.b - 4, L = box.l + sideW + valW + 8, R = box.r - sideW - valW - 8;
        const X = (si: number) => L + (R - L) * si / (S - 1), Y = (v: number) => B - (v - d.lo) / ((d.hi - d.lo) || 1) * (B - T);
        m.series.forEach((sr, si) => {
            const x = X(si);
            el("line", { x1: r1(x) + 0.5, x2: r1(x) + 0.5, y1: r1(T), y2: r1(B), stroke: t.grid, "stroke-width": 1 }, root);
            el("text", { x: r1(x), y: r1(box.t + lfs), "text-anchor": si === 0 ? "end" : si === S - 1 ? "start" : "middle", "font-size": lfs, fill: t.text, class: "ttl" }, root, trunc(sr.name, 140, lfs));
        });
        const lw = MK.lineWidth.value, r = Math.max(1, msz * 0.7);
        const ends: { ci: number; y: number; left: boolean; text: string; col: string }[] = [];
        order.forEach(ci => {
            const pts = m.series.map((_, si) => m.grid[ci][si]).map((x, si) => (x ? { x, p: [X(si), Y(x.v)] as [number, number] } : null)).filter(o => o) as { x: Cell; p: [number, number] }[];
            if (!pts.length) return;
            const cat = m.cats[ci], rise = pts[pts.length - 1].x.v >= pts[0].x.v, on = c.io.anyOn(cat.items) && focused(cat.name);
            const col = t.hc ? t.ink : focus ? (focused(cat.name) ? c.colorOf(m.series[0]) : gray) : rise ? up : down;
            const g = el("g", { class: "grp" + (on ? "" : " dim") }, marks);
            el("path", { d: linePath(pts.map(o => o.p)), fill: "none", stroke: col, "stroke-width": lw, "stroke-linecap": "round", "stroke-linejoin": "round" }, g);
            pts.forEach(o => c.bind(marker(g, shape, o.p[0], o.p[1], r, { fill: col, stroke: t.surface, "stroke-width": 1, class: "mk" }), cellT(o.x)));
            c.bind(g, groupT(cat, "c", catTip(ci)));
            const a = pts[0], b = pts[pts.length - 1];
            ends.push({ ci, y: a.p[1], left: true, text: `${CA.show.value ? names[ci] + "  " : ""}${fmts(a.x.s, a.x.v)}`, col });
            ends.push({ ci, y: b.p[1], left: false, text: `${fmts(b.x.s, b.x.v)}${CA.show.value ? "  " + names[ci] : ""}`, col });
        });
        [true, false].forEach(left => {
            const list = ends.filter(e => e.left === left), ys = spread(list.map(e => e.y), lfs + 2, T, B);
            list.forEach((e, k) => el("text", { x: r1(left ? L - r - 6 : R + r + 6), y: r1(ys[k] + lfs * 0.35), "text-anchor": left ? "end" : "start", "font-size": lfs, fill: focus && !focused(m.cats[e.ci].name) ? gray : t.text, class: "lbl" }, root, e.text));
        });
    }

    /* ================================================================ bump */
    function bump() {
        if (S < 2) { note(c.msg("Need_Legend", "A bump chart ranks series: put the periods in Category and the items in Legend.")); return; }
        /* rank of each series in each category, 1 = highest value */
        const rank: (number | null)[][] = m.series.map(() => new Array(N).fill(null));
        for (let ci = 0; ci < N; ci++) {
            const list = m.series.map((_, si) => ({ si, x: m.grid[ci][si] })).filter(o => o.x).sort((a, b) => (b.x as Cell).v - (a.x as Cell).v);
            list.forEach((o, k) => { rank[o.si][ci] = k + 1; });
        }
        const lfs = cfs, nameW = CA.show.value ? Math.min(W * 0.22, Math.max(...m.series.map(sr => textW(sr.name, lfs)))) + 10 : 0;
        const T = box.t + 6, B = box.b - (CA.show.value ? cfs + 10 : 4), L = box.l + lfs * 2 + 8, R = box.r - nameW - 4;
        const X = (ci: number) => (N > 1 ? L + (R - L) * ci / (N - 1) : (L + R) / 2), Y = (k: number) => T + (B - T) * (k - 1) / Math.max(1, S - 1);
        for (let k = 1; k <= S; k++) el("text", { x: r1(box.l), y: r1(Y(k) + lfs * 0.35), "font-size": Math.max(6, lfs - 1), fill: t.axis, class: "ax" }, root, "#" + k);
        if (CA.show.value) m.cats.forEach((ct, ci) => c.io.bindLabel(el("text", { x: r1(X(ci)), y: r1(B + cfs + 6), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, root, trunc(ct.name, (R - L) / Math.max(1, N - 1) - 2, cfs)), catTarget(m, ci)));
        if (s.gridlines.show.value) m.cats.forEach((_, ci) => el("line", { x1: r1(X(ci)) + 0.5, x2: r1(X(ci)) + 0.5, y1: r1(T - 4), y2: r1(B + 4), stroke: colorOr(GR.color, t.grid), "stroke-width": GR.width.value }, root));
        const lw = MK.lineWidth.value * 1.4, r = Math.max(msz, lw * 1.6), smooth = MK.smooth.value;
        const ordered = m.series.map((_, si) => si).sort((a, b) => Number(focused(m.series[a].name)) - Number(focused(m.series[b].name)));
        const ends: { si: number; y: number }[] = [];
        ordered.forEach(si => {
            const sr = m.series[si], on = c.io.anyOn(sr.items) && focused(sr.name), col = t.hc ? t.ink : focus && !focused(sr.name) ? gray : c.colorOf(sr);
            const g = el("g", { class: "grp" + (on ? "" : " dim") }, marks);
            const runs: [number, number][][] = [[]];
            rank[si].forEach((k, ci) => { if (k === null) { if (runs[runs.length - 1].length) runs.push([]); } else runs[runs.length - 1].push([X(ci), Y(k)]); });
            runs.filter(rn => rn.length > 1).forEach(rn => el("path", { d: smooth ? smoothPath(rn) : linePath(rn), fill: "none", stroke: col, "stroke-width": lw, "stroke-linecap": "round", "stroke-linejoin": "round" }, g));
            rank[si].forEach((k, ci) => {
                if (k === null) return;
                const x = m.grid[ci][si] as Cell, mk = marker(g, shape, X(ci), Y(k), r, { fill: col, stroke: t.surface, "stroke-width": 1.5, class: "mk" });
                c.bind(mk, cellT(x));
                if (LB.show.value && r >= 6) el("text", { x: r1(X(ci)), y: r1(Y(k) + Math.min(r, lbfs) * 0.36), "text-anchor": "middle", "font-size": Math.min(r * 1.1, lbfs), fill: "#ffffff", class: "ax", "pointer-events": "none" }, g, String(k));
            });
            c.bind(g, groupT(sr, "s", serTip(si)));
            const lastK = rank[si][N - 1]; if (lastK !== null) ends.push({ si, y: Y(lastK) });
        });
        if (CA.show.value) ends.forEach(e => el("text", { x: r1(R + r + 6), y: r1(e.y + lfs * 0.35), "font-size": lfs, fill: focus && !focused(m.series[e.si].name) ? gray : t.text, class: "lbl" }, root, trunc(m.series[e.si].name, nameW, lfs)));
    }

    /* ================================================================ radar */
    function radar() {
        if (N < 3) { note(c.msg("Need_Three", "A radar needs three or more categories (spokes).")); return; }
        const RD = s.radar, circle = val(RD.grid) === "circle", levels = Math.max(1, Math.round(RD.levels.value));
        const um = parseNum(RD.max.value), mx = isFinite(um) && um > 0 ? um : nice(0, Math.max(...m.cells.map(x => x.v)), levels).hi;
        const multi = RD.multiples.value && S > 1;
        const panels = multi ? m.series.map((_, si) => [si]) : [m.series.map((_, si) => si)];
        const cols = multi ? Math.ceil(Math.sqrt(panels.length * (box.r - box.l) / Math.max(1, box.b - box.t))) : 1, rows = Math.ceil(panels.length / cols);
        const pw = (box.r - box.l) / cols, ph = (box.b - box.t) / rows;
        const fmtA = formatter(m.format, Number(VA.displayUnits.value) || 0, null, mx, c.culture);
        panels.forEach((list, pi) => {
            const px = box.l + pw * (pi % cols), py = box.t + ph * Math.floor(pi / cols), tH = multi ? cfs + 6 : 0;
            const labW = CA.show.value ? Math.min(pw * 0.22, Math.max(...m.cats.map(x => textW(x.name, cfs)))) : 0;
            const rad = Math.max(8, Math.min((pw - 2 * labW - 12) / 2, (ph - tH - 2 * (cfs + 6)) / 2)), cx = px + pw / 2, cy = py + tH + (ph - tH) / 2;
            const ang = (k: number) => -Math.PI / 2 + 2 * Math.PI * k / N, at = (k: number, v: number): [number, number] => [cx + Math.cos(ang(k)) * rad * Math.min(1.05, Math.max(0, v) / mx), cy + Math.sin(ang(k)) * rad * Math.min(1.05, Math.max(0, v) / mx)];
            if (multi) el("text", { x: r1(cx), y: r1(py + cfs), "text-anchor": "middle", "font-size": cfs, fill: t.text, class: "ttl" }, root, trunc(m.series[list[0]].name, pw - 4, cfs));
            const gC = colorOr(GR.color, t.grid);
            if (GR.show.value) for (let l = 1; l <= levels; l++) {
                const rr = rad * l / levels;
                if (circle) el("circle", { cx: r1(cx), cy: r1(cy), r: r1(rr), fill: "none", stroke: gC, "stroke-width": GR.width.value }, root);
                else el("path", { d: linePath(m.cats.map((_, k) => [cx + Math.cos(ang(k)) * rr, cy + Math.sin(ang(k)) * rr] as [number, number])) + "Z", fill: "none", stroke: gC, "stroke-width": GR.width.value }, root);
                const la = -Math.PI / 2 + Math.PI / N;
                if (VA.show.value && pi === 0) el("text", { x: r1(cx + Math.cos(la) * rr + 2), y: r1(cy + Math.sin(la) * rr - 2), "font-size": Math.max(6, VA.fontSize.value - 1), fill: colorOr(VA.color, t.axis), class: "ax" }, root, fmtA(mx * l / levels));
            }
            m.cats.forEach((ct, k) => {
                const e = at(k, mx);
                if (GR.show.value) el("line", { x1: r1(cx), y1: r1(cy), x2: r1(e[0]), y2: r1(e[1]), stroke: gC, "stroke-width": GR.width.value }, root);
                if (CA.show.value) {
                    const a = ang(k), lx = cx + Math.cos(a) * (rad + 8), ly = cy + Math.sin(a) * (rad + 8), anchor = Math.abs(Math.cos(a)) < 0.3 ? "middle" : Math.cos(a) > 0 ? "start" : "end";
                    el("text", { x: r1(lx), y: r1(ly + cfs * 0.35 + (Math.sin(a) > 0.9 ? cfs * 0.4 : Math.sin(a) < -0.9 ? -cfs * 0.2 : 0)), "text-anchor": anchor, "font-size": cfs, fill: cC, class: "ax" }, root, trunc(ct.name, labW + 4, cfs));
                }
            });
            const ord = list.slice().sort((a, b) => Number(focused(m.series[a].name)) - Number(focused(m.series[b].name)));
            ord.forEach(si => {
                const sr = m.series[si], on = c.io.anyOn(sr.items) && focused(sr.name), col = t.hc ? t.ink : focus && !focused(sr.name) ? gray : c.colorOf(sr);
                const pts = m.cats.map((_, k) => { const x = m.grid[k][si]; return { x, p: at(k, x ? x.v : 0) }; });
                const g = el("g", { class: "grp" + (on ? "" : " dim") }, marks);
                el("path", { d: linePath(pts.map(o => o.p)) + "Z", fill: RD.fill.value && !t.hc ? (look.flat ? col : look.fill(col, "r")) : "none", "fill-opacity": RD.fillOpacity.value / 100, stroke: col, "stroke-width": MK.lineWidth.value, "stroke-linejoin": "round" }, g);
                pts.forEach(o => { if (o.x) c.bind(marker(g, shape, o.p[0], o.p[1], Math.max(1, msz * 0.55), { fill: col, stroke: t.surface, "stroke-width": 1, class: "mk" }), cellT(o.x)); });
                c.bind(g, groupT(sr, "s", serTip(si)));
                if (LB.show.value) pts.forEach(o => { if (o.x) el("text", { x: r1(o.p[0]), y: r1(o.p[1] - msz * 0.55 - 3), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, root, fmtL[si](o.x.v)); });
            });
        });
    }
}
