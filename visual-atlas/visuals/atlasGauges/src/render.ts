/*
 * Drawing for Relay Gauges: card, multi-row card, KPI (status and trend),
 * gauge, dial (bands and needle), radial bars, liquid fill, bullet chart,
 * a scrolling ticker and a leaderboard. One tile per item for cards, KPIs,
 * gauges, dials and liquid fills; radial bars, bullets, rows, the ticker and
 * the leaderboard share one view.
 *
 * A change is said the way people read it (common/util.ts changeText): in
 * points between percentages ("+1.9 pts"), in % between positive amounts,
 * else as the difference. Status colors are darkened (or lightened on a dark
 * report) for text, so amber stays readable.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Item } from "./model";
import { GaugesSettings } from "./settings";
import { Ctx, SCROLLBAR } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn, readable } from "./common/color";
import { colorOr, val } from "./common/cards";
import { nice, parseNum } from "./common/chart";
import { labelFormatter, formatter, changeText, isPercent } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<GaugesSettings, Model>;
/** a part of a status line, in its own color */
interface Piece { text: string; color: string; }

/** ring segment between angles a0 and a1 (radians, 0 = up, clockwise) */
function arcPath(cx: number, cy: number, r0: number, r1_: number, a0: number, a1: number): string {
    const P = (a: number, r: number) => `${r1(cx + Math.sin(a) * r)},${r1(cy - Math.cos(a) * r)}`, lg = a1 - a0 > Math.PI ? 1 : 0;
    if (a1 - a0 < 1e-4) return "";
    return `M${P(a0, r1_)}A${r1(r1_)},${r1(r1_)} 0 ${lg} 1 ${P(a1, r1_)}L${P(a1, r0)}A${r1(r0)},${r1(r0)} 0 ${lg} 0 ${P(a0, r0)}Z`;
}
/* a text's box reaches about 0.92 of its size above the baseline and 0.24 below */
const UP = 0.92, DOWN = 0.24;

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6, items = m.list, N = items.length;
    const ST = s.status, LB = s.labels, CA = s.categoryAxis, SC = s.scale;
    const good = colorOr(ST.goodColor, "#1a9e5c"), warn = colorOr(ST.warnColor, "#d9a400"), bad = colorOr(ST.badColor, "#d64550");
    const lower = val(ST.direction) === "lower", tol = ST.tolerance.value / 100, cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value), nameC = colorOr(CA.color, t.text);
    const tl = String(ST.targetLabel.value || "").trim() || "target", cl = String(ST.compareLabel.value || "").trim() || "LY";
    const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    const fmtBig = (it: Item) => labelFormatter(it.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.abs(it.value), c.culture)(it.value);
    const fmtOf = (it: Item, v: number) => labelFormatter(it.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.abs(v), c.culture)(v);
    const fmtTip = (it: Item) => formatter(it.format, 1, null, 0, c.culture);
    /** a status color as text on the visual's background: the same hue, dark (or light) enough to read */
    const ink = (col: string) => (t.hc ? t.ink : readable(col, t.surface));
    /** good, close or off target: the gap to the target in the better direction; amber within the tolerance */
    const status = (it: Item): { color: string; ratio: number; ok: boolean; up: boolean } | null => {
        if (isNaN(it.target)) return null;
        const gap = (it.value - it.target) * (lower ? -1 : 1), near = tol * Math.abs(it.target);
        return { ratio: it.target ? it.value / it.target : NaN, ok: gap >= 0, up: it.value >= it.target, color: t.hc ? t.ink : gap >= 0 ? good : gap >= -near ? warn : bad };
    };
    const delta = (it: Item) => changeText(it.value, it.target, it.format, v => fmtOf(it, v));
    const cdelta = (it: Item) => changeText(it.value, it.compare, it.format, v => fmtOf(it, v));
    /** better than the comparison (on-target color), worse (off-target color) or the same (text color) */
    const ccolor = (it: Item) => { const d = (it.value - it.compare) * (lower ? -1 : 1); return t.hc ? t.ink : d > 0 ? good : d < 0 ? bad : t.text; };
    const vsTarget = (it: Item): Piece | null => { const st = status(it); return st && ST.showTarget.value ? { text: `${delta(it)} vs ${tl}`, color: ink(st.color) } : null; };
    const vsCompare = (it: Item): Piece | null => (isNaN(it.compare) ? null : { text: `${cdelta(it)} vs ${cl}`, color: ink(ccolor(it)) });
    /** the line under a value: the target and its change ("Target $10M (-7.0%)"), or each change ("-0.8% vs plan", "+3.2% vs LY") */
    const statusLine = (it: Item, goal: string): Piece[] => {
        const a = vsTarget(it), b = vsCompare(it), st = status(it);
        if (a && !b && st) return [{ text: `${goal} ${fmtOf(it, it.target)} (${delta(it)})`, color: ink(st.color) }];
        return [a, b].filter(x => !!x) as Piece[];
    };
    const GAP = 12;
    /** lines the pieces take: one when they fit side by side, else one each (up to max; then only the first) */
    const linesOf = (ps: Piece[], w: number, size: number, max: number) => (!ps.length ? 0 : ps.reduce((a, p) => a + textW(p.text, size), 0) + GAP * (ps.length - 1) <= w ? 1 : ps.length <= max ? ps.length : 1);
    /** draw the pieces from a first baseline y, centered on x or from x */
    const drawPieces = (ps: Piece[], x: number, y: number, w: number, size: number, anchor: "middle" | "start", max: number) => {
        const n = linesOf(ps, w, size, max);
        if (!n) return;
        if (n === 1 && ps.length > 1 && ps.reduce((a, p) => a + textW(p.text, size), 0) + GAP * (ps.length - 1) <= w) {
            const all = ps.reduce((a, p) => a + textW(p.text, size), 0) + GAP * (ps.length - 1);
            let px = anchor === "middle" ? x - all / 2 : x;
            ps.forEach(p => { el("text", { x: r1(px), y: r1(y), "font-size": size, fill: p.color, class: "lbl" }, labels, p.text); px += textW(p.text, size) + GAP; });
            return;
        }
        ps.slice(0, n).forEach((p, k) => el("text", { x: r1(x), y: r1(y + k * (size + 3)), "text-anchor": anchor, "font-size": size, fill: p.color, class: "lbl" }, labels, trunc(p.text, w, size)));
    };
    /** scale of an item: Format pane, then Minimum/Maximum measures, then 0 and a round number above value and target */
    const range = (it: Item): [number, number] => {
        const u0 = parseNum(SC.min.value), u1 = parseNum(SC.max.value);
        const lo = isFinite(u0) ? u0 : !isNaN(it.min) ? it.min : Math.min(0, it.value);
        let hi = isFinite(u1) ? u1 : !isNaN(it.max) ? it.max : NaN;
        if (!isFinite(hi)) { const top = Math.max(it.value, isNaN(it.target) ? -Infinity : it.target); hi = nice(lo, top * 1.12, 4).hi; }
        return [lo, hi > lo ? hi : lo + 1];
    };
    const frac = (it: Item, v: number) => { const [lo, hi] = range(it); return Math.max(0, Math.min(1, (v - lo) / (hi - lo))); };
    const colorFor = (it: Item) => (t.hc ? t.ink : c.colorOf(it));
    const tip = (it: Item): TipItem[] => {
        const f = fmtTip(it), out: TipItem[] = [{ displayName: m.catTitle || "Measure", value: it.name, color: colorFor(it) }, { displayName: it.measure, value: f(it.value) }];
        if (!isNaN(it.target)) out.push({ displayName: cap(tl), value: f(it.target) }, { displayName: "vs " + tl, value: delta(it) });
        if (!isNaN(it.compare)) out.push({ displayName: m.compareName || cap(cl), value: f(it.compare) }, { displayName: "vs " + cl, value: cdelta(it) });
        it.tips.forEach(tp => out.push({ displayName: tp.name, value: tp.value }));
        return out;
    };
    const target = (it: Item): Target => ({ key: "k" + it.key, items: [it.i], ids: it.id ? [it.id] : [], tip: () => tip(it) });
    const on = (it: Item) => c.io.on(it.i);
    /** biggest font size (up to a cap) at which a text fits a width */
    const fit = (text: string, w: number, cap_: number) => Math.max(8, Math.min(cap_, (w / Math.max(1, textW(text, 10))) * 10));
    /** an up or down triangle next to a value */
    const arrow = (g: Element, x: number, baseY: number, size: number, up: boolean, fill: string) => {
        el("path", { d: up ? `M${r1(x)},${r1(baseY - size * 0.1)}l${r1(size / 2)},${r1(-size)}l${r1(size / 2)},${r1(size)}Z` : `M${r1(x)},${r1(baseY - size * 1.1)}l${r1(size / 2)},${r1(size)}l${r1(size / 2)},${r1(-size)}Z`, fill }, g);
    };

    /* tiles: one per item, in a grid */
    const tiles = () => {
        const want = Math.round(s.chart.columns.value), aspect = type === "card" || type === "kpi" ? 1.6 : 1.05;
        const cols = want > 0 ? Math.min(N, want) : Math.max(1, Math.min(N, Math.round(Math.sqrt(N * W / H / aspect))));
        const rows = Math.ceil(N / cols), tw = (W - pad * 2) / cols, th = (H - pad * 2) / rows;
        return items.map((it, k) => ({ it, x: pad + tw * (k % cols), y: pad + th * Math.floor(k / cols), w: tw, h: th }));
    };

    if (type === "multirow") multirow();
    else if (type === "radialBar") radialBars();
    else if (type === "bullet") bullets();
    else if (type === "ticker") ticker();
    else if (type === "leaderboard") leaderboard();
    else tiles().forEach(tl_ => {
        const g = el("g", { class: "mk" + (on(tl_.it) ? "" : " dim") }, marks);
        el("rect", { x: r1(tl_.x + 3), y: r1(tl_.y + 3), width: r1(tl_.w - 6), height: r1(tl_.h - 6), fill: "transparent" }, g);
        if (type === "card") card(g, tl_.it, tl_.x + 3, tl_.y + 3, tl_.w - 6, tl_.h - 6);
        else if (type === "kpi") kpi(g, tl_.it, tl_.x + 3, tl_.y + 3, tl_.w - 6, tl_.h - 6);
        else if (type === "liquid") liquid(g, tl_.it, tl_.x + 3, tl_.y + 3, tl_.w - 6, tl_.h - 6);
        else gauge(g, tl_.it, tl_.x + 3, tl_.y + 3, tl_.w - 6, tl_.h - 6, type === "dial");
        c.bind(g, target(tl_.it));
    });

    /* ================================================================ card and KPI */
    function card(g: Element, it: Item, x: number, y: number, w: number, h: number) {
        const accent = s.chart.accent.value, st = status(it), big = fmtBig(it), col = colorFor(it);
        if (N > 1) el("rect", { x: r1(x), y: r1(y), width: r1(w), height: r1(h), rx: 8, fill: mix(t.surface, t.text, 0.03), stroke: mix(t.text, t.surface, 0.88) }, g);
        if (accent) el("rect", { x: r1(x), y: r1(y + 8), width: 4, height: r1(Math.max(4, h - 16)), rx: 2, fill: look.fill(col, "v") }, g);
        /* value, name and status line as one block, centered; each line starts below the one above (2026-11-19: a short
           value such as "$0" grew so tall it reached the name under it) */
        const ps = statusLine(it, cap(tl)), sfs = Math.max(7, cfs - 1), inner = w - 16, nl = linesOf(ps, inner, sfs, h > 120 ? 2 : 1);
        const nameH = CA.show.value ? 4 + cfs * (UP + DOWN) : 0, subH = nl ? nl * (sfs + 3) + 3 : 0;
        const fsBig = fit(big, w * 0.8, Math.max(9, Math.min(64, (h - 12 - nameH - subH) / (UP + DOWN))));
        const block = fsBig * (UP + DOWN) + nameH + subH, cx = x + w / 2, vy = y + Math.max(2, (h - block) / 2) + fsBig * UP;
        el("text", { x: r1(cx), y: r1(vy), "text-anchor": "middle", "font-size": r1(fsBig), fill: ST.colorValue.value && st ? ink(st.color) : t.ink, class: "ttl" }, labels, big);
        let below = vy + fsBig * DOWN;
        if (CA.show.value) { c.io.bindLabel(el("text", { x: r1(cx), y: r1(below + 4 + cfs * UP), "text-anchor": "middle", "font-size": cfs, fill: nameC, class: "ax" }, labels, trunc(it.name, w - 12, cfs)), target(it)); below += nameH; }
        if (nl) drawPieces(ps, cx, below + 3 + sfs * UP, inner, sfs, "middle", nl);
    }
    function kpi(g: Element, it: Item, x: number, y: number, w: number, h: number) {
        const st = status(it), big = fmtBig(it), tr = it.trend, showTrend = s.trend.show.value && tr.length > 1;
        /* the arrow and the trend follow the target; without one, the comparison */
        const dir = st ? { up: st.up, color: st.color } : !isNaN(it.compare) ? { up: it.value >= it.compare, color: ccolor(it) } : null;
        if (N > 1) el("rect", { x: r1(x), y: r1(y), width: r1(w), height: r1(h), rx: 8, fill: mix(t.surface, t.text, 0.03), stroke: mix(t.text, t.surface, 0.88) }, g);
        /* trend in the lower part, colored by status */
        if (showTrend) {
            const vs = tr.map(p => p.v), lo = Math.min(...vs), hi = Math.max(...vs), tx0 = x + 8, tx1 = x + w - 8, ty0 = y + h * 0.58, ty1 = y + h - 8;
            const X = (k: number) => tx0 + (tx1 - tx0) * k / (tr.length - 1), Y = (v: number) => ty1 - (hi > lo ? (v - lo) / (hi - lo) : 0.5) * (ty1 - ty0);
            const col = dir ? dir.color : colorFor(it), stl = val(s.trend.style);
            if (stl === "column") { const bw = (tx1 - tx0) / tr.length * 0.7; tr.forEach((p, k) => el("rect", { x: r1(tx0 + (tx1 - tx0) * k / tr.length), y: r1(Y(p.v)), width: r1(bw), height: r1(Math.max(1, ty1 - Y(p.v))), rx: 1.5, fill: mix(col, t.surface, 0.45) }, g)); }
            else {
                const d = tr.map((p, k) => `${k ? "L" : "M"}${r1(X(k))},${r1(Y(p.v))}`).join("");
                if (stl === "area") el("path", { d: `${d}L${r1(tx1)},${r1(ty1)}L${r1(tx0)},${r1(ty1)}Z`, fill: mix(col, t.surface, 0.78) }, g);
                el("path", { d, fill: "none", stroke: col, "stroke-width": 2, "stroke-linejoin": "round" }, g);
                el("circle", { cx: r1(X(tr.length - 1)), cy: r1(Y(vs[vs.length - 1])), r: 3, fill: col }, g);
            }
        }
        const area = showTrend ? h * 0.56 : h, ps = statusLine(it, ST.targetLabel.value ? cap(tl) + ":" : "Goal:"), gw = w - 12;
        const nl = linesOf(ps, gw, cfs, 2), goalH = nl ? nl * (cfs + 3) + 4 : 0;
        let fsBig = fit(big, w * 0.62, Math.min(area * 0.42, 56)), cx = x + w / 2, cy = y + area * 0.5 + fsBig * 0.12, nameMax = w - 20;
        /* the status lines go under the value: in a low tile the value moves up to leave them room */
        if (goalH && cy + fsBig * DOWN + goalH > y + area - 2) { const up_ = cy + fsBig * DOWN + goalH - (y + area - 2); cy -= up_; if (cy - fsBig * UP < y + 2) { fsBig = Math.max(9, fsBig - (y + 2 - (cy - fsBig * UP))); cy = y + 2 + fsBig * UP; } }
        if (CA.show.value) {
            /* the item's name sits top left. In a low tile a long name ran into the value ("Revenue Growth %+11.3%"):
               the value moves right, clear of the name, when the tile has room (the usual case); else just under the name if it stays
               14px or more; else the name stops short of the value. The value keeps its size where it can. */
            const nameR = x + 10 + Math.min(textW(it.name, cfs), w - 20), nameB = y + cfs * 1.3 + 7;
            const vw = () => textW(big, fsBig), arrowW = () => (dir ? 8 + Math.max(6, fsBig * 0.32) : 0);
            if (cy - fsBig * 0.95 < nameB && cx - vw() / 2 < nameR + 10) {
                const right = nameR + 12 + vw() / 2;
                if (right + vw() / 2 + arrowW() <= x + w - 8) cx = right;
                else {
                    const under = fit(big, w * 0.62, Math.min(fsBig, (y + area - nameB - goalH) * 0.8));
                    if (under >= Math.min(14, fsBig)) { fsBig = under; cy = nameB + fsBig * 0.95; }
                    else nameMax = Math.max(24, cx - vw() / 2 - 10 - (x + 10));
                }
            }
        }
        el("text", { x: r1(cx), y: r1(cy), "text-anchor": "middle", "font-size": r1(fsBig), fill: ST.colorValue.value && st ? ink(st.color) : t.ink, class: "ttl" }, labels, big);
        if (dir) arrow(g, cx + textW(big, fsBig) / 2 + 8, cy - fsBig * 0.32 + Math.max(6, fsBig * 0.32), Math.max(6, fsBig * 0.32), dir.up, dir.color);
        if (nl) {
            /* under the value, kept inside the tile when the value moved right of the name */
            const lw = Math.min(gw, nl === 1 ? ps.reduce((a, p) => a + textW(p.text, cfs), 0) + GAP * (ps.length - 1) : Math.max(...ps.map(p => textW(p.text, cfs))));
            drawPieces(ps, Math.max(x + 6 + lw / 2, Math.min(x + w - 6 - lw / 2, cx)), cy + fsBig * DOWN + 3 + cfs * UP, gw, cfs, "middle", nl);
        }
        if (CA.show.value) c.io.bindLabel(el("text", { x: r1(x + 10), y: r1(y + cfs + 6), "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, nameMax, cfs)), target(it));
    }

    /* ================================================================ gauge and dial */
    function gauge(g: Element, it: Item, x: number, y: number, w: number, h: number, dial: boolean) {
        const span = Number(val(SC.angle)) * Math.PI / 180, a0 = -span / 2, a1 = span / 2, [lo, hi] = range(it);
        const nameH = CA.show.value ? cfs + 6 : 0, half = span <= Math.PI + 1e-6;
        const R = Math.max(10, Math.min(w / 2 - 14, (h - nameH - (half ? 18 : 10)) / (half ? 1.08 : 1 + Math.cos(Math.PI - span / 2) * 0.9 + 0.1)));
        const cx = x + w / 2, cy = y + nameH + (half ? R + 6 : R + 4), thick = R * SC.width.value / 100, r0 = R - thick;
        const A = (v: number) => a0 + (a1 - a0) * Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
        const st = status(it), col = st ? st.color : colorFor(it);
        if (CA.show.value) c.io.bindLabel(el("text", { x: r1(cx), y: r1(y + cfs), "text-anchor": "middle", "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, w - 6, cfs)), target(it));
        if (dial) {
            /* bands: off target, close, on target (reversed when lower is better) */
            const q1 = !isNaN(it.b1) ? it.b1 : lo + (hi - lo) * SC.band1.value / 100, q2 = !isNaN(it.b2) ? it.b2 : lo + (hi - lo) * SC.band2.value / 100;
            const cols = lower ? [good, warn, bad] : [bad, warn, good];
            [[lo, q1], [q1, q2], [q2, hi]].forEach(([u, v], k) => el("path", { d: arcPath(cx, cy, r0, R, A(u), A(v)), fill: t.hc ? (k === 2 ? t.ink : t.surface) : look.flat ? cols[k] : look.fill(cols[k], "r"), stroke: t.hc ? t.ink : t.surface, "stroke-width": 1 }, g));
        } else {
            el("path", { d: arcPath(cx, cy, r0, R, a0, a1), fill: mix(t.text, t.surface, 0.9) }, g);
            el("path", { d: arcPath(cx, cy, r0, R, a0, A(it.value)), fill: t.hc ? t.ink : look.flat ? col : look.fill(col, "r") }, g);
        }
        if (SC.ticks.value) {
            const f = (v: number) => fmtOf(it, v);
            [[lo, a0], [hi, a1]].forEach(([v, a]) => el("text", { x: r1(cx + Math.sin(a) * (r0 + thick / 2)), y: r1(cy - Math.cos(a) * (r0 + thick / 2) + (half ? cfs + 4 : cfs + 2)), "text-anchor": "middle", "font-size": Math.max(7, cfs - 1), fill: t.axis, class: "ax" }, labels, f(v)));
            if (dial) for (let k = 1; k < 4; k++) { const v = lo + (hi - lo) * k / 4, a = A(v); el("text", { x: r1(cx + Math.sin(a) * (r0 - 9)), y: r1(cy - Math.cos(a) * (r0 - 9) + 3), "text-anchor": "middle", "font-size": Math.max(6, cfs - 2), fill: t.axis, class: "ax" }, labels, f(v)); }
        }
        if (!isNaN(it.target) && ST.showTarget.value) { const a = A(it.target); el("line", { x1: r1(cx + Math.sin(a) * (r0 - 4)), y1: r1(cy - Math.cos(a) * (r0 - 4)), x2: r1(cx + Math.sin(a) * (R + 4)), y2: r1(cy - Math.cos(a) * (R + 4)), stroke: t.ink, "stroke-width": 2.5, "stroke-linecap": "round" }, g); }
        if (dial && SC.needle.value) {
            const a = A(it.value), L2 = r0 - 4;
            el("path", { d: `M${r1(cx + Math.sin(a) * L2)},${r1(cy - Math.cos(a) * L2)}L${r1(cx + Math.sin(a + Math.PI / 2) * 4)},${r1(cy - Math.cos(a + Math.PI / 2) * 4)}L${r1(cx - Math.sin(a + Math.PI / 2) * 4)},${r1(cy + Math.cos(a + Math.PI / 2) * 4)}Z`, fill: t.ink }, g);
            el("circle", { cx: r1(cx), cy: r1(cy), r: 6, fill: t.ink }, g);
        }
        if (LB.show.value) {
            const big = fmtBig(it), fs2 = fit(big, r0 * 1.3, Math.min(R * 0.42, 40)), vy = dial ? cy + R * 0.42 : cy - (half ? 4 : -fs2 * 0.35);
            el("text", { x: r1(cx), y: r1(vy), "text-anchor": "middle", "font-size": r1(fs2), fill: ST.colorValue.value && st ? ink(st.color) : t.ink, class: "ttl" }, labels, big);
            const ps = [vsTarget(it), vsCompare(it)].filter(p => !!p) as Piece[], sfs = Math.max(7, cfs - 1);
            if (ps.length) drawPieces(ps, cx, vy + fs2 * DOWN + 2 + sfs * UP, Math.max(40, (dial ? r0 * 1.7 : w - 12)), sfs, "middle", 2);
        }
    }

    /* ================================================================ liquid fill */
    function liquid(g: Element, it: Item, x: number, y: number, w: number, h: number) {
        const nameH = CA.show.value ? cfs + 8 : 0, R = Math.max(10, Math.min(w, h - nameH) / 2 - 6), cx = x + w / 2, cy = y + nameH + (h - nameH) / 2;
        const k = frac(it, it.value), col = colorFor(it), sq = val(s.liquid.shape) === "square", amp = R * s.liquid.wave.value / 100;
        const id = "atlg-l" + (++CLIP), cp = el("clipPath", { id }, g);
        if (sq) el("rect", { x: r1(cx - R), y: r1(cy - R), width: r1(2 * R), height: r1(2 * R), rx: r1(R * 0.25) }, cp); else el("circle", { cx: r1(cx), cy: r1(cy), r: r1(R - 4) }, cp);
        if (sq) el("rect", { x: r1(cx - R - 3), y: r1(cy - R - 3), width: r1(2 * R + 6), height: r1(2 * R + 6), rx: r1(R * 0.28), fill: "none", stroke: col, "stroke-width": 2 }, g);
        else el("circle", { cx: r1(cx), cy: r1(cy), r: r1(R), fill: "none", stroke: col, "stroke-width": 2 }, g);
        const level = cy + R - 2 * R * k, wave: string[] = [];
        for (let i = 0; i <= 40; i++) { const xx = cx - R + 2 * R * i / 40; wave.push(`${i ? "L" : "M"}${r1(xx)},${r1(level + Math.sin(i / 40 * Math.PI * 4) * amp)}`); }
        const body = el("g", { "clip-path": `url(#${id})` }, g);
        el("rect", { x: r1(cx - R), y: r1(cy - R), width: r1(2 * R), height: r1(2 * R), fill: mix(col, t.surface, 0.9) }, body);
        el("path", { d: `${wave.join("")}L${r1(cx + R)},${r1(cy + R)}L${r1(cx - R)},${r1(cy + R)}Z`, fill: t.hc ? t.ink : look.flat ? col : look.fill(col, "v") }, body);
        const pct = (k * 100).toFixed(k < 0.1 ? 1 : 0) + "%", fs2 = Math.max(10, Math.min(R * 0.5, 44)), py = cy + fs2 * 0.35;
        el("text", { x: r1(cx), y: r1(py), "text-anchor": "middle", "font-size": r1(fs2), fill: level < cy ? inkOn(col) : t.ink, class: "ttl" }, labels, pct);
        /* "of" line under the big percent, below its descent (2026-11-19: it touched the percent) */
        const sy = py + fs2 * DOWN + 2 + cfs * UP;
        if (LB.show.value) el("text", { x: r1(cx), y: r1(sy), "text-anchor": "middle", "font-size": cfs, fill: level < sy - cfs ? inkOn(col) : t.axis, class: "ax" }, labels, trunc(`${fmtBig(it)} of ${fmtOf(it, range(it)[1])}`, R * 1.7, cfs));
        if (CA.show.value) c.io.bindLabel(el("text", { x: r1(cx), y: r1(y + cfs + 2), "text-anchor": "middle", "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, w - 6, cfs)), target(it));
    }

    /* ================================================================ radial bars */
    function radialBars() {
        const labelW = CA.show.value ? Math.min(W * 0.3, Math.max(...items.map(it => textW(it.name, cfs)))) + 10 : 0;
        /* three-quarter rings, centered, sized to fit both width and height */
        const R = Math.max(20, Math.min((W - pad * 2) / 2, (H - pad * 2) / 2) - 4), cx = W / 2, cy = H / 2;
        const span = 1.5 * Math.PI, ring = R / (N + 1), thick = ring * SC.width.value / 100 * 3.2;
        items.forEach((it, k) => {
            const r1_ = R - ring * k, r0 = Math.max(4, r1_ - Math.min(ring - 2, thick)), col = colorFor(it), kk = !isNaN(it.target) && it.target ? Math.min(1, it.value / it.target) : frac(it, it.value);
            const g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
            el("path", { d: arcPath(cx, cy, r0, r1_, 0, span), fill: mix(t.text, t.surface, 0.92) }, g);
            el("path", { d: arcPath(cx, cy, r0, r1_, 0, span * kk), fill: t.hc ? t.ink : look.flat ? col : look.fill(col, "r") }, g);
            c.bind(g, target(it));
            /* a rate shows itself (28.4%), an amount its progress ("95% of target"): "95%" beside a penetration rate read as the rate */
            const shown = !it.target || isNaN(it.target) || isPercent(it.format) ? fmtBig(it) : `${Math.round(kk * 100)}% of ${tl}`;
            const txt = `${CA.show.value ? it.name + "  " : ""}${LB.show.value ? shown : ""}`;
            el("text", { x: r1(cx - 6), y: r1(cy - (r0 + r1_) / 2 + Math.min(cfs, r1_ - r0) * 0.35), "text-anchor": "end", "font-size": Math.min(cfs, Math.max(6, r1_ - r0)), fill: nameC, class: "ax" }, labels, trunc(txt, labelW + 90, cfs));
        });
    }

    /* ================================================================ bullet chart */
    function bullets() {
        const vert = val(s.bullet.orientation) === "vertical", grays = [mix(t.text, t.surface, 0.72), mix(t.text, t.surface, 0.82), mix(t.text, t.surface, 0.91)];
        /* the value label, and the change against the target in its status color */
        const showD = ST.showTarget.value && m.hasTarget && !vert, dl = (it: Item) => (showD && status(it) ? delta(it) : "");
        if (!vert) {
            /* a band per item, at least a line of text high: many items (120 stores) scroll instead of squeezing (2026-11-19) */
            const band = Math.max(Math.max(cfs, lbfs) + 10, (H - pad * 2) / N), tall = band * N + pad * 2 > H + 0.5;
            if (tall) c.grow(W, band * N + pad * 2);
            const Wd = tall ? W - SCROLLBAR : W;
            const nameW = CA.show.value ? Math.min(Wd * 0.32, Math.max(...items.map(it => textW(it.name, cfs)))) + 12 : 0;
            const valW = LB.show.value ? Math.max(...items.map(it => textW(fmtBig(it), lbfs) + (dl(it) ? 6 + textW(dl(it), lbfs) : 0))) + 10 : 0;
            items.forEach((it, k) => {
                const [lo, hi] = range(it), q1 = !isNaN(it.b1) ? it.b1 : lo + (hi - lo) * SC.band1.value / 100, q2 = !isNaN(it.b2) ? it.b2 : lo + (hi - lo) * SC.band2.value / 100;
                const st = status(it), col = st && ST.colorValue.value ? st.color : colorFor(it), g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
                const bh = Math.min(band * 0.62, 34), y = pad + band * k + (band - bh) / 2, L = pad + nameW, R = Wd - pad - valW;
                const X = (v: number) => L + (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (R - L);
                [[lo, hi, 2], [lo, q2, 1], [lo, q1, 0]].forEach(([u, v, gi]) => el("rect", { x: r1(X(u)), y: r1(y), width: r1(Math.max(0, X(v) - X(u))), height: r1(bh), rx: 2, fill: t.hc ? t.surface : grays[gi], stroke: t.hc ? t.ink : "none" }, g));
                el("rect", { x: r1(L), y: r1(y + bh * 0.32), width: r1(Math.max(1, X(it.value) - L)), height: r1(bh * 0.36), rx: 2, fill: t.hc ? t.ink : look.fill(col, "h") }, g);
                if (!isNaN(it.target)) el("line", { x1: r1(X(it.target)), x2: r1(X(it.target)), y1: r1(y + bh * 0.12), y2: r1(y + bh * 0.88), stroke: t.ink, "stroke-width": 2.5 }, g);
                if (CA.show.value) c.io.bindLabel(el("text", { x: r1(L - 8), y: r1(y + bh / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, nameW - 10, cfs)), target(it));
                if (LB.show.value) {
                    const v = fmtBig(it), d = dl(it);
                    el("text", { x: r1(R + 6), y: r1(y + bh / 2 + lbfs * 0.35), "font-size": lbfs, fill: t.text, class: "lbl" }, labels, v);
                    if (d && st) el("text", { x: r1(R + 12 + textW(v, lbfs)), y: r1(y + bh / 2 + lbfs * 0.35), "font-size": lbfs, fill: ink(st.color), class: "lbl" }, labels, d);
                }
                c.bind(g, target(it));
            });
            return;
        }
        const band = Math.max(Math.max(26, cfs * 2.4), (W - pad * 2) / N), wide = band * N + pad * 2 > W + 0.5;
        if (wide) c.grow(band * N + pad * 2, H);
        const Hd = wide ? H - SCROLLBAR : H;
        items.forEach((it, k) => {
            const [lo, hi] = range(it), q1 = !isNaN(it.b1) ? it.b1 : lo + (hi - lo) * SC.band1.value / 100, q2 = !isNaN(it.b2) ? it.b2 : lo + (hi - lo) * SC.band2.value / 100;
            const st = status(it), col = st && ST.colorValue.value ? st.color : colorFor(it), g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
            const bw = Math.min(band * 0.5, 44), x = pad + band * k + (band - bw) / 2, T = pad + (LB.show.value ? lbfs + 6 : 0), B = Hd - pad - (CA.show.value ? cfs + 8 : 0);
            const Y = (v: number) => B - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (B - T);
            [[lo, hi, 2], [lo, q2, 1], [lo, q1, 0]].forEach(([u, v, gi]) => el("rect", { x: r1(x), y: r1(Y(v)), width: r1(bw), height: r1(Math.max(0, Y(u) - Y(v))), rx: 2, fill: t.hc ? t.surface : grays[gi], stroke: t.hc ? t.ink : "none" }, g));
            el("rect", { x: r1(x + bw * 0.32), y: r1(Y(it.value)), width: r1(bw * 0.36), height: r1(Math.max(1, B - Y(it.value))), rx: 2, fill: t.hc ? t.ink : look.fill(col, "v") }, g);
            if (!isNaN(it.target)) el("line", { x1: r1(x + bw * 0.12), x2: r1(x + bw * 0.88), y1: r1(Y(it.target)), y2: r1(Y(it.target)), stroke: t.ink, "stroke-width": 2.5 }, g);
            if (CA.show.value) c.io.bindLabel(el("text", { x: r1(x + bw / 2), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, band - 2, cfs)), target(it));
            if (LB.show.value) el("text", { x: r1(x + bw / 2), y: r1(T - 4), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "lbl" }, labels, trunc(fmtBig(it), band - 2, lbfs));
            c.bind(g, target(it));
        });
    }

    /* ================================================================ multi-row card */
    function multirow() {
        /* each card: the value, then the target, the change against it and against the comparison. A number is never cut
           short: the cards go to one column, the numbers get smaller (down to 12px), then the target amount gives way to
           its change (2026-11-19: "$6..." and "-0...." in two columns of four numbers) */
        const sfs = Math.max(7, cfs - 1), partsOf = (it: Item, amount: boolean): [string, string, string][] => {
            const st = status(it), out: [string, string, string][] = [[fmtBig(it), it.measure, ST.colorValue.value && st ? ink(st.color) : t.ink]];
            if (st && ST.showTarget.value) { if (amount) out.push([fmtOf(it, it.target), cap(tl), t.ink]); out.push([delta(it), "vs " + tl, ink(st.color)]); }
            if (!isNaN(it.compare)) out.push([cdelta(it), "vs " + cl, ink(ccolor(it))]);
            return out;
        };
        const widths = (ps: [string, string, string][], fsV: number) => ps.map(([v, lbl], j) => Math.max(textW(v, j ? fsV * 0.8 : fsV), textW(lbl, sfs)) + 14);
        const need = (fsV: number, amount: boolean) => Math.max(...items.map(it => widths(partsOf(it, amount), fsV).reduce((a, b) => a + b, 0)));
        /* a card is at least as high as its lines (name, a 12px value, the small labels under it) */
        const fsCap = (rh: number) => Math.max(12, Math.min(26, rh * 0.36, rh - cfs - sfs - 22));
        const layout = (cols: number) => {
            const rows = Math.ceil(N / cols), rh = Math.max(cfs + sfs + 34, Math.min(78, (H - pad * 2) / rows)), tall = rows * rh + pad * 2 > H;
            return { cols, rows, rh, tall, cw: ((tall ? W - SCROLLBAR : W) - pad * 2) / cols };
        };
        /* two columns where they fit (smaller numbers, then without the target amount), else one */
        const tryL = (cols: number, amount: boolean, least: number) => {
            const L = layout(cols); let f = fsCap(L.rh);
            while (f > least && need(f, amount) > L.cw - 24) f -= 1;
            return need(f, amount) <= L.cw - 24 ? { L, fsV: f, amount } : null;
        };
        const plan = (W > 520 && N > 3 ? tryL(2, true, 14) || tryL(2, false, 14) : null) || tryL(1, true, 12) || tryL(1, false, 12) || { L: layout(1), fsV: 12, amount: false };
        const { L, fsV, amount } = plan;
        if (L.tall) c.grow(W, L.rows * L.rh + pad * 2);
        const { cols, rh, cw } = L;
        items.forEach((it, k) => {
            const x = pad + cw * (k % cols), y = pad + rh * Math.floor(k / cols), col = colorFor(it);
            const g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
            el("rect", { x: r1(x + 2), y: r1(y + 2), width: r1(cw - 4), height: r1(rh - 4), rx: 6, fill: mix(t.surface, t.text, 0.03), stroke: mix(t.text, t.surface, 0.9) }, g);
            if (s.chart.accent.value) el("rect", { x: r1(x + 2), y: r1(y + 8), width: 4, height: r1(rh - 16), rx: 2, fill: look.fill(col, "v") }, g);
            c.io.bindLabel(el("text", { x: r1(x + 14), y: r1(y + cfs + 8), "font-size": cfs + 1, fill: t.ink, class: "ttl" }, labels, trunc(it.name, cw - 24, cfs + 1)), target(it));
            const parts = partsOf(it, amount), ws = widths(parts, fsV), spare = Math.max(0, (cw - 24 - ws.reduce((a, b) => a + b, 0)) / parts.length);
            let px = x + 14;
            parts.forEach(([v, lbl, clr], j) => {
                el("text", { x: r1(px), y: r1(y + cfs + 12 + fsV), "font-size": r1(j ? fsV * 0.8 : fsV), fill: clr, class: "ttl" }, labels, v);
                el("text", { x: r1(px), y: r1(y + cfs + 16 + fsV + sfs), "font-size": sfs, fill: t.axis, class: "ax" }, labels, trunc(lbl, ws[j] + spare - 6, sfs));
                px += ws[j] + spare;
            });
            c.bind(g, target(it));
        });
    }

    /* ================================================================ ticker */
    function ticker() {
        const up = val(s.ticker.direction) === "up", fs2 = Math.max(cfs + 2, Math.min(22, H * 0.28)), gap = 36;
        const strip = el("g", { class: "atl-tick" + (up ? " up" : "") }, marks);
        let x = pad, y = pad;
        const lineH = fs2 + 14, entries = items.map(it => {
            const st = status(it), useT = !!st, d = useT ? delta(it) : !isNaN(it.compare) ? cdelta(it) : "";
            return { it, text: `${it.name}  ${fmtBig(it)}`, d, dir: useT && st ? { up: st.up, color: st.color } : d ? { up: it.value >= it.compare, color: ccolor(it) } : null };
        });
        const placeAll = (offset: number) => entries.forEach(e => {
            const g = el("g", { class: "mk" + (on(e.it) ? "" : " dim") }, strip), w = textW(e.text, fs2) + (e.d ? textW(e.d, fs2) + 26 : 0);
            const px = up ? pad : offset + x, py = up ? offset + y + fs2 : H / 2 + fs2 * 0.35;
            el("rect", { x: r1(px - 6), y: r1(py - fs2 - 2), width: r1(w + 12), height: r1(fs2 + 10), fill: "transparent" }, g);
            el("text", { x: r1(px), y: r1(py), "font-size": r1(fs2), fill: t.ink, class: "ttl" }, g, e.text);
            if (e.d && e.dir) {
                const ax = px + textW(e.text, fs2) + 10, sz = fs2 * 0.45;
                arrow(g, ax, py - fs2 * 0.1 + sz * 0.1 + (e.dir.up ? 0 : sz), sz, e.dir.up, e.dir.color);
                el("text", { x: r1(ax + sz + 6), y: r1(py), "font-size": r1(fs2), fill: ink(e.dir.color), class: "lbl" }, g, e.d);
            }
            c.bind(g, target(e.it));
            if (up) y += lineH; else x += w + gap;
        });
        placeAll(0);
        const loop = up ? y - pad : x - pad;
        x = pad; y = pad; placeAll(loop);   /* a second copy, so the loop has no gap */
        strip.setAttribute("style", `--atl-shift:${up ? `0px,${-r1(loop)}px` : `${-r1(loop)}px,0px`};--atl-dur:${Math.max(3, s.ticker.speed.value)}s`);
        if (CA.show.value && m.catTitle) el("text", { x: r1(W - pad), y: r1(pad + cfs), "text-anchor": "end", "font-size": cfs, fill: t.axis, class: "ax" }, labels, m.catTitle);
    }

    /* ================================================================ leaderboard */
    /* ranked rows (stores, divisions, departments): rank, name, a bar for the value with the target marked, the value,
       the change against the target and against the comparison, and a sparkline of the trend; it scrolls when the rows
       need more room than the visual has (100+ stores) */
    function leaderboard() {
        const LD = s.leaderboard, order = val(LD.sort), topN = Math.max(0, Math.round(LD.topN.value)), pct = isPercent(items[0].format);
        const score = (v: number, b: number) => (isNaN(b) ? NaN : (pct || b <= 0 || v < 0 ? v - b : v / b - 1) * (lower ? -1 : 1));
        const key = (it: Item) => (/^target/.test(order) ? score(it.value, it.target) : /^compare/.test(order) ? score(it.value, it.compare) : it.value);
        const asc = /Asc$/.test(order);
        let rows = items.slice();
        if (order !== "none") rows.sort((a, b) => { const x = key(a), y = key(b); if (isNaN(x)) return isNaN(y) ? 0 : 1; if (isNaN(y)) return -1; return asc ? x - y : y - x; });
        if (topN > 0) rows = rows.slice(0, topN);
        const n = rows.length, fs = cfs, vfs = lbfs, headH = fs + 12, rowH = Math.max(Math.max(fs, vfs) + 9, Math.min(36, (H - pad * 2 - headH) / Math.max(1, n)));
        const total = pad * 2 + headH + rowH * n, tall = total > H + 0.5;
        if (tall) c.grow(W, total);
        const Wd = (tall ? W - SCROLLBAR : W) - pad * 2, x0 = pad;
        const showT = m.hasTarget && ST.showTarget.value, showC = m.hasCompare, spark = s.trend.show.value && m.hasTrend && rows.some(it => it.trend.length > 1);
        const fmtCol = labelFormatter(items[0].format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...rows.map(it => Math.abs(it.value))), c.culture);
        const vals = rows.map(it => fmtCol(it.value)), dts = rows.map(it => (showT ? delta(it) : "")), dcs = rows.map(it => (showC ? cdelta(it) : ""));
        const hT = "vs " + tl, hC = "vs " + cl, hName = m.catTitle || "", hVal = m.valueName;
        const rankW = LD.rank.value ? Math.max(textW("#", fs), textW(String(n), vfs)) + 12 : 0;
        const valW = Math.max(textW(hVal, fs), ...vals.map(v => textW(v, vfs))) + 12;
        const dtW = showT ? Math.max(textW(hT, fs), ...dts.map(v => textW(v, vfs))) + 14 : 0, dcW = showC ? Math.max(textW(hC, fs), ...dcs.map(v => textW(v, vfs))) + 14 : 0;
        let spW = spark ? Math.min(120, Math.max(48, Wd * 0.16)) : 0;
        const nameFull = Math.max(textW(hName, fs), ...rows.map(it => textW(it.name, fs))) + 12;
        let nameW = Math.min(nameFull, Math.max(80, Wd * 0.34)), barW = Wd - rankW - nameW - valW - dtW - dcW - spW;
        /* short of room: the sparkline goes first, then the names shorten, then the bars go */
        if (barW < 60 && spW) { barW += spW; spW = 0; }
        if (barW < 60) { const cut = Math.min(nameW - 60, 60 - barW); if (cut > 0) { nameW -= cut; barW += cut; } }
        const bars = LD.bars.value && barW >= 36;
        if (!bars) { const more = Math.max(0, Math.min(barW, nameFull - nameW)); nameW += more; }
        const xName = x0 + rankW, xBar = xName + nameW, xValR = xBar + (bars ? barW : 0) + valW - 6, xDtR = xValR + dtW, xDcR = xDtR + dcW, xSp = xDcR + 10, spR = xSp + spW - 14;
        const all = rows.map(it => it.value).concat(showT ? rows.map(it => it.target).filter(v => isFinite(v)) : []);
        const lo = Math.min(0, ...all), hi = Math.max(0, ...all), BX = (v: number) => xBar + 6 + (barW - 16) * ((Math.max(lo, Math.min(hi, v)) - lo) / ((hi - lo) || 1));
        const head = el("g", { class: "head" }, labels), hy = pad + fs * UP + 3;
        if (rankW) el("text", { x: r1(xName - 6), y: r1(hy), "text-anchor": "end", "font-size": fs, fill: t.axis, class: "ax" }, head, "#");
        el("text", { x: r1(xName), y: r1(hy), "font-size": fs, fill: t.axis, class: "ax" }, head, trunc(hName, nameW - 8, fs));
        el("text", { x: r1(xValR), y: r1(hy), "text-anchor": "end", "font-size": fs, fill: t.axis, class: "ax" }, head, trunc(hVal, (bars ? barW : 0) + valW - 8, fs));
        if (showT) el("text", { x: r1(xDtR), y: r1(hy), "text-anchor": "end", "font-size": fs, fill: t.axis, class: "ax" }, head, hT);
        if (showC) el("text", { x: r1(xDcR), y: r1(hy), "text-anchor": "end", "font-size": fs, fill: t.axis, class: "ax" }, head, hC);
        if (spW) el("text", { x: r1(xSp), y: r1(hy), "font-size": fs, fill: t.axis, class: "ax" }, head, trunc("Trend", spW - 14, fs));
        /* stripes and lines sit under the marks, out of the look's shadow */
        const back = el("g", {}, root); root.insertBefore(back, marks);
        el("line", { x1: r1(x0), x2: r1(x0 + Wd), y1: r1(pad + headH - 3) + 0.5, y2: r1(pad + headH - 3) + 0.5, stroke: mix(t.text, t.surface, 0.8), "stroke-width": 1 }, back);
        if (bars && lo < 0 && hi > 0) el("line", { x1: r1(BX(0)) + 0.5, x2: r1(BX(0)) + 0.5, y1: r1(pad + headH), y2: r1(pad + headH + rowH * n), stroke: mix(t.text, t.surface, 0.55), "stroke-width": 1 }, back);
        const one = colorFor(items[0]);
        rows.forEach((it, k) => {
            const y = pad + headH + rowH * k, mid = y + rowH / 2, st = status(it), g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
            if (k % 2) el("rect", { x: r1(x0), y: r1(y), width: r1(Wd), height: r1(rowH), rx: 3, fill: mix(t.surface, t.text, 0.04) }, back);
            el("rect", { x: r1(x0), y: r1(y), width: r1(Wd), height: r1(rowH), fill: "transparent" }, g);
            if (rankW) el("text", { x: r1(xName - 6), y: r1(mid + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: t.axis, class: "ax" }, labels, String(k + 1));
            c.io.bindLabel(el("text", { x: r1(xName), y: r1(mid + fs * 0.35), "font-size": fs, fill: nameC, class: "ax" }, labels, trunc(it.name, nameW - 8, fs)), target(it));
            if (bars) {
                const col = t.hc ? t.ink : ST.colorValue.value && st ? st.color : one, a = BX(0), b = BX(it.value), bh = Math.max(4, Math.min(rowH * 0.5, 14));
                el("rect", { x: r1(Math.min(a, b)), y: r1(mid - bh / 2), width: r1(Math.max(1, Math.abs(b - a))), height: r1(bh), rx: 2, fill: look.flat || t.hc ? col : look.fill(col, "h") }, g);
                if (showT && !isNaN(it.target)) el("line", { x1: r1(BX(it.target)), x2: r1(BX(it.target)), y1: r1(mid - bh / 2 - 3), y2: r1(mid + bh / 2 + 3), stroke: t.ink, "stroke-width": 2 }, g);
            }
            el("text", { x: r1(xValR), y: r1(mid + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: t.ink, class: "lbl" }, labels, vals[k]);
            if (showT && dts[k] && st) el("text", { x: r1(xDtR), y: r1(mid + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: ink(st.color), class: "lbl" }, labels, dts[k]);
            if (showC && dcs[k]) el("text", { x: r1(xDcR), y: r1(mid + vfs * 0.35), "text-anchor": "end", "font-size": vfs, fill: ink(ccolor(it)), class: "lbl" }, labels, dcs[k]);
            if (spW && it.trend.length > 1) {
                const vs = it.trend.map(p => p.v), a = Math.min(...vs), b = Math.max(...vs), y0 = y + 4, y1 = y + rowH - 4, scol = t.hc ? t.ink : mix(one, t.text, 0.25);
                const P = (j: number): [number, number] => [xSp + (spR - xSp) * j / (vs.length - 1), y1 - (b > a ? (vs[j] - a) / (b - a) : 0.5) * (y1 - y0)];
                el("path", { d: vs.map((_, j) => `${j ? "L" : "M"}${r1(P(j)[0])},${r1(P(j)[1])}`).join(""), fill: "none", stroke: scol, "stroke-width": 1.5, "stroke-linejoin": "round" }, g);
                const e = P(vs.length - 1); el("circle", { cx: r1(e[0]), cy: r1(e[1]), r: 2.2, fill: scol }, g);
            }
            c.bind(g, target(it));
        });
    }
}
let CLIP = 0;
