/*
 * Drawing for Atlas Gauges: card, multi-row card, KPI (status and trend),
 * gauge, dial (bands and needle), radial bars, liquid fill, bullet chart
 * and a scrolling ticker. One tile per item for cards, KPIs, gauges, dials
 * and liquid fills; radial bars, bullets, rows and the ticker share one view.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Item } from "./model";
import { GaugesSettings } from "./settings";
import { Ctx } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr, val } from "./common/cards";
import { nice, parseNum } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<GaugesSettings, Model>;

/** ring segment between angles a0 and a1 (radians, 0 = up, clockwise) */
function arcPath(cx: number, cy: number, r0: number, r1_: number, a0: number, a1: number): string {
    const P = (a: number, r: number) => `${r1(cx + Math.sin(a) * r)},${r1(cy - Math.cos(a) * r)}`, lg = a1 - a0 > Math.PI ? 1 : 0;
    if (a1 - a0 < 1e-4) return "";
    return `M${P(a0, r1_)}A${r1(r1_)},${r1(r1_)} 0 ${lg} 1 ${P(a1, r1_)}L${P(a1, r0)}A${r1(r0)},${r1(r0)} 0 ${lg} 0 ${P(a0, r0)}Z`;
}

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6, items = m.list, N = items.length;
    const ST = s.status, LB = s.labels, CA = s.categoryAxis, SC = s.scale;
    const good = colorOr(ST.goodColor, "#1a9e5c"), warn = colorOr(ST.warnColor, "#d9a400"), bad = colorOr(ST.badColor, "#d64550");
    const lower = val(ST.direction) === "lower", tol = ST.tolerance.value / 100, cfs = Math.max(6, CA.fontSize.value), lbfs = Math.max(6, LB.fontSize.value), nameC = colorOr(CA.color, t.text);
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    const fmtBig = (it: Item) => labelFormatter(it.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.abs(it.value), c.culture)(it.value);
    const fmtOf = (it: Item, v: number) => labelFormatter(it.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.abs(v), c.culture)(v);
    const fmtTip = (it: Item) => formatter(it.format, 1, null, 0, c.culture);
    /** good, close or off target */
    const status = (it: Item): { color: string; ratio: number; ok: boolean } | null => {
        if (isNaN(it.target) || !it.target) return null;
        const ratio = it.value / it.target, score = lower ? 2 - ratio : ratio;
        return { ratio, ok: score >= 1, color: t.hc ? t.ink : score >= 1 ? good : score >= 1 - tol ? warn : bad };
    };
    const delta = (it: Item) => { const st = status(it); if (!st) return ""; const d = (st.ratio - 1) * 100; return `${d >= 0 ? "+" : ""}${d.toFixed(Math.abs(d) < 10 ? 1 : 0)}%`; };
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
        if (!isNaN(it.target)) out.push({ displayName: "Target", value: f(it.target) }, { displayName: "vs target", value: delta(it) });
        it.tips.forEach(tp => out.push({ displayName: tp.name, value: tp.value }));
        return out;
    };
    const target = (it: Item): Target => ({ key: "k" + it.key, items: [it.i], ids: it.id ? [it.id] : [], tip: () => tip(it) });
    const on = (it: Item) => c.io.on(it.i);
    /** biggest font size (up to a cap) at which a text fits a width */
    const fit = (text: string, w: number, cap: number) => Math.max(8, Math.min(cap, (w / Math.max(1, textW(text, 10))) * 10));

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
    else tiles().forEach(tl => {
        const g = el("g", { class: "mk" + (on(tl.it) ? "" : " dim") }, marks);
        el("rect", { x: r1(tl.x + 3), y: r1(tl.y + 3), width: r1(tl.w - 6), height: r1(tl.h - 6), fill: "transparent" }, g);
        if (type === "card") card(g, tl.it, tl.x + 3, tl.y + 3, tl.w - 6, tl.h - 6);
        else if (type === "kpi") kpi(g, tl.it, tl.x + 3, tl.y + 3, tl.w - 6, tl.h - 6);
        else if (type === "liquid") liquid(g, tl.it, tl.x + 3, tl.y + 3, tl.w - 6, tl.h - 6);
        else gauge(g, tl.it, tl.x + 3, tl.y + 3, tl.w - 6, tl.h - 6, type === "dial");
        c.bind(g, target(tl.it));
    });

    /* ================================================================ card and KPI */
    function card(g: Element, it: Item, x: number, y: number, w: number, h: number) {
        const accent = s.chart.accent.value, st = status(it), big = fmtBig(it), col = colorFor(it);
        if (N > 1) el("rect", { x: r1(x), y: r1(y), width: r1(w), height: r1(h), rx: 8, fill: mix(t.surface, t.text, 0.03), stroke: mix(t.text, t.surface, 0.88) }, g);
        if (accent) el("rect", { x: r1(x), y: r1(y + 8), width: 4, height: r1(Math.max(4, h - 16)), rx: 2, fill: look.fill(col, "v") }, g);
        const sub = ST.showTarget.value && st ? `Target ${fmtOf(it, it.target)} · ${delta(it)}` : "";
        const fsBig = fit(big, w * 0.8, Math.min(h * (sub ? 0.36 : 0.44), 64)), cx = x + w / 2, cy = y + h / 2 + fsBig * 0.2 - (sub ? cfs * 0.6 : 0);
        el("text", { x: r1(cx), y: r1(cy), "text-anchor": "middle", "font-size": r1(fsBig), fill: ST.colorValue.value && st ? st.color : t.ink, class: "ttl" }, labels, big);
        if (CA.show.value) c.io.bindLabel(el("text", { x: r1(cx), y: r1(cy + cfs + 6), "text-anchor": "middle", "font-size": cfs, fill: nameC, class: "ax" }, labels, trunc(it.name, w - 12, cfs)), target(it));
        if (sub) el("text", { x: r1(cx), y: r1(cy + cfs * 2 + 10), "text-anchor": "middle", "font-size": Math.max(7, cfs - 1), fill: st ? st.color : t.axis, class: "lbl" }, labels, trunc(sub, w - 10, cfs));
    }
    function kpi(g: Element, it: Item, x: number, y: number, w: number, h: number) {
        const st = status(it), big = fmtBig(it), tr = it.trend, showTrend = s.trend.show.value && tr.length > 1;
        if (N > 1) el("rect", { x: r1(x), y: r1(y), width: r1(w), height: r1(h), rx: 8, fill: mix(t.surface, t.text, 0.03), stroke: mix(t.text, t.surface, 0.88) }, g);
        /* trend in the lower part, colored by status */
        if (showTrend) {
            const vs = tr.map(p => p.v), lo = Math.min(...vs), hi = Math.max(...vs), tx0 = x + 8, tx1 = x + w - 8, ty0 = y + h * 0.58, ty1 = y + h - 8;
            const X = (k: number) => tx0 + (tx1 - tx0) * k / (tr.length - 1), Y = (v: number) => ty1 - (hi > lo ? (v - lo) / (hi - lo) : 0.5) * (ty1 - ty0);
            const col = st ? st.color : colorFor(it), stl = val(s.trend.style);
            if (stl === "column") { const bw = (tx1 - tx0) / tr.length * 0.7; tr.forEach((p, k) => el("rect", { x: r1(tx0 + (tx1 - tx0) * k / tr.length), y: r1(Y(p.v)), width: r1(bw), height: r1(Math.max(1, ty1 - Y(p.v))), rx: 1.5, fill: mix(col, t.surface, 0.45) }, g)); }
            else {
                const d = tr.map((p, k) => `${k ? "L" : "M"}${r1(X(k))},${r1(Y(p.v))}`).join("");
                if (stl === "area") el("path", { d: `${d}L${r1(tx1)},${r1(ty1)}L${r1(tx0)},${r1(ty1)}Z`, fill: mix(col, t.surface, 0.78) }, g);
                el("path", { d, fill: "none", stroke: col, "stroke-width": 2, "stroke-linejoin": "round" }, g);
                el("circle", { cx: r1(X(tr.length - 1)), cy: r1(Y(vs[vs.length - 1])), r: 3, fill: col }, g);
            }
        }
        const area = showTrend ? h * 0.56 : h, fsBig = fit(big, w * 0.62, Math.min(area * 0.42, 56)), cx = x + w / 2, cy = y + area * 0.5 + fsBig * 0.12;
        el("text", { x: r1(cx), y: r1(cy), "text-anchor": "middle", "font-size": r1(fsBig), fill: ST.colorValue.value && st ? st.color : t.ink, class: "ttl" }, labels, big);
        if (st) {
            /* status arrow next to the number */
            const ax = cx + textW(big, fsBig) / 2 + 8, up = st.ratio >= 1, sz = Math.max(6, fsBig * 0.32);
            el("path", { d: up ? `M${r1(ax)},${r1(cy - fsBig * 0.32 + sz)}l${r1(sz / 2)},${r1(-sz)}l${r1(sz / 2)},${r1(sz)}Z` : `M${r1(ax)},${r1(cy - fsBig * 0.32)}l${r1(sz / 2)},${r1(sz)}l${r1(sz / 2)},${r1(-sz)}Z`, fill: st.color }, g);
            if (ST.showTarget.value) el("text", { x: r1(cx), y: r1(cy + cfs + 6), "text-anchor": "middle", "font-size": cfs, fill: st.color, class: "lbl" }, labels, trunc(`Goal: ${fmtOf(it, it.target)} (${delta(it)})`, w - 10, cfs));
        }
        if (CA.show.value) c.io.bindLabel(el("text", { x: r1(x + 10), y: r1(y + cfs + 6), "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, w - 20, cfs)), target(it));
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
            el("text", { x: r1(cx), y: r1(vy), "text-anchor": "middle", "font-size": r1(fs2), fill: ST.colorValue.value && st ? st.color : t.ink, class: "ttl" }, labels, big);
            if (st && ST.showTarget.value) el("text", { x: r1(cx), y: r1(vy + Math.max(8, cfs) + 3), "text-anchor": "middle", "font-size": Math.max(7, cfs - 1), fill: st.color, class: "lbl" }, labels, delta(it) + " vs target");
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
        const pct = (k * 100).toFixed(k < 0.1 ? 1 : 0) + "%", fs2 = Math.max(10, Math.min(R * 0.5, 44));
        el("text", { x: r1(cx), y: r1(cy + fs2 * 0.35), "text-anchor": "middle", "font-size": r1(fs2), fill: level < cy ? inkOn(col) : t.ink, class: "ttl" }, labels, pct);
        if (LB.show.value) el("text", { x: r1(cx), y: r1(cy + fs2 * 0.35 + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: level < cy + fs2 ? inkOn(col) : t.axis, class: "ax" }, labels, `${fmtBig(it)} of ${fmtOf(it, range(it)[1])}`);
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
            const txt = `${CA.show.value ? it.name + "  " : ""}${LB.show.value ? (it.target ? Math.round(kk * 100) + "%" : fmtBig(it)) : ""}`;
            el("text", { x: r1(cx - 6), y: r1(cy - (r0 + r1_) / 2 + Math.min(cfs, r1_ - r0) * 0.35), "text-anchor": "end", "font-size": Math.min(cfs, Math.max(6, r1_ - r0)), fill: nameC, class: "ax" }, labels, trunc(txt, labelW + 60, cfs));
        });
    }

    /* ================================================================ bullet chart */
    function bullets() {
        const vert = val(s.bullet.orientation) === "vertical";
        const nameW = CA.show.value && !vert ? Math.min(W * 0.32, Math.max(...items.map(it => textW(it.name, cfs)))) + 12 : 0, valW = LB.show.value && !vert ? Math.max(...items.map(it => textW(fmtBig(it), lbfs))) + 10 : 0;
        const grays = [mix(t.text, t.surface, 0.72), mix(t.text, t.surface, 0.82), mix(t.text, t.surface, 0.91)];
        items.forEach((it, k) => {
            const [lo, hi] = range(it), q1 = !isNaN(it.b1) ? it.b1 : lo + (hi - lo) * SC.band1.value / 100, q2 = !isNaN(it.b2) ? it.b2 : lo + (hi - lo) * SC.band2.value / 100;
            const st = status(it), col = st && ST.colorValue.value ? st.color : colorFor(it), g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
            if (!vert) {
                const band = (H - pad * 2) / N, bh = Math.min(band * 0.62, 34), y = pad + band * k + (band - bh) / 2, L = pad + nameW, R = W - pad - valW;
                const X = (v: number) => L + (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (R - L);
                [[lo, hi, 2], [lo, q2, 1], [lo, q1, 0]].forEach(([u, v, gi]) => el("rect", { x: r1(X(u)), y: r1(y), width: r1(Math.max(0, X(v) - X(u))), height: r1(bh), rx: 2, fill: t.hc ? t.surface : grays[gi], stroke: t.hc ? t.ink : "none" }, g));
                el("rect", { x: r1(L), y: r1(y + bh * 0.32), width: r1(Math.max(1, X(it.value) - L)), height: r1(bh * 0.36), rx: 2, fill: t.hc ? t.ink : look.fill(col, "h") }, g);
                if (!isNaN(it.target)) el("line", { x1: r1(X(it.target)), x2: r1(X(it.target)), y1: r1(y + bh * 0.12), y2: r1(y + bh * 0.88), stroke: t.ink, "stroke-width": 2.5 }, g);
                if (CA.show.value) c.io.bindLabel(el("text", { x: r1(L - 8), y: r1(y + bh / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, nameW - 10, cfs)), target(it));
                if (LB.show.value) el("text", { x: r1(R + 6), y: r1(y + bh / 2 + lbfs * 0.35), "font-size": lbfs, fill: t.text, class: "lbl" }, labels, fmtBig(it));
            } else {
                const band = (W - pad * 2) / N, bw = Math.min(band * 0.5, 44), x = pad + band * k + (band - bw) / 2, T = pad + (LB.show.value ? lbfs + 6 : 0), B = H - pad - (CA.show.value ? cfs + 8 : 0);
                const Y = (v: number) => B - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (B - T);
                [[lo, hi, 2], [lo, q2, 1], [lo, q1, 0]].forEach(([u, v, gi]) => el("rect", { x: r1(x), y: r1(Y(v)), width: r1(bw), height: r1(Math.max(0, Y(u) - Y(v))), rx: 2, fill: t.hc ? t.surface : grays[gi], stroke: t.hc ? t.ink : "none" }, g));
                el("rect", { x: r1(x + bw * 0.32), y: r1(Y(it.value)), width: r1(bw * 0.36), height: r1(Math.max(1, B - Y(it.value))), rx: 2, fill: t.hc ? t.ink : look.fill(col, "v") }, g);
                if (!isNaN(it.target)) el("line", { x1: r1(x + bw * 0.12), x2: r1(x + bw * 0.88), y1: r1(Y(it.target)), y2: r1(Y(it.target)), stroke: t.ink, "stroke-width": 2.5 }, g);
                if (CA.show.value) c.io.bindLabel(el("text", { x: r1(x + bw / 2), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: nameC, class: "ttl" }, labels, trunc(it.name, band - 2, cfs)), target(it));
                if (LB.show.value) el("text", { x: r1(x + bw / 2), y: r1(T - 4), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "lbl" }, labels, fmtBig(it));
            }
            c.bind(g, target(it));
        });
    }

    /* ================================================================ multi-row card */
    function multirow() {
        const cols = W > 520 && N > 3 ? 2 : 1, rows = Math.ceil(N / cols), rh = Math.max(cfs * 3 + 10, Math.min(78, (H - pad * 2) / rows)), cw = (W - pad * 2) / cols;
        if (rows * rh + pad * 2 > H) c.grow(W, rows * rh + pad * 2);
        items.forEach((it, k) => {
            const x = pad + cw * (k % cols), y = pad + rh * Math.floor(k / cols), st = status(it), col = colorFor(it);
            const g = el("g", { class: "mk" + (on(it) ? "" : " dim") }, marks);
            el("rect", { x: r1(x + 2), y: r1(y + 2), width: r1(cw - 4), height: r1(rh - 4), rx: 6, fill: mix(t.surface, t.text, 0.03), stroke: mix(t.text, t.surface, 0.9) }, g);
            if (s.chart.accent.value) el("rect", { x: r1(x + 2), y: r1(y + 8), width: 4, height: r1(rh - 16), rx: 2, fill: look.fill(col, "v") }, g);
            c.io.bindLabel(el("text", { x: r1(x + 14), y: r1(y + cfs + 8), "font-size": cfs + 1, fill: t.ink, class: "ttl" }, labels, trunc(it.name, cw - 24, cfs + 1)), target(it));
            const fsV = Math.min(rh * 0.36, 26), parts: [string, string, string][] = [[fmtBig(it), it.measure, ST.colorValue.value && st ? st.color : t.ink]];
            if (st && ST.showTarget.value) parts.push([fmtOf(it, it.target), "Target", t.ink], [delta(it), "vs target", st.color]);
            const colW = (cw - 24) / parts.length;
            parts.forEach(([v, lbl, clr], j) => {
                el("text", { x: r1(x + 14 + colW * j), y: r1(y + cfs + 12 + fsV), "font-size": r1(j ? fsV * 0.8 : fsV), fill: clr, class: "ttl" }, labels, trunc(v, colW - 6, fsV));
                el("text", { x: r1(x + 14 + colW * j), y: r1(y + cfs + 16 + fsV + Math.max(7, cfs - 1)), "font-size": Math.max(7, cfs - 1), fill: t.axis, class: "ax" }, labels, trunc(lbl, colW - 6, cfs));
            });
            c.bind(g, target(it));
        });
    }

    /* ================================================================ ticker */
    function ticker() {
        const up = val(s.ticker.direction) === "up", fs2 = Math.max(cfs + 2, Math.min(22, H * 0.28)), gap = 36;
        const strip = el("g", { class: "atl-tick" + (up ? " up" : "") }, marks);
        let x = pad, y = pad;
        const lineH = fs2 + 14, entries = items.map(it => ({ it, text: `${it.name}  ${fmtBig(it)}`, d: delta(it), st: status(it) }));
        const placeAll = (offset: number) => entries.forEach(e => {
            const g = el("g", { class: "mk" + (on(e.it) ? "" : " dim") }, strip), w = textW(e.text, fs2) + (e.d ? textW(e.d, fs2) + 26 : 0);
            const px = up ? pad : offset + x, py = up ? offset + y + fs2 : H / 2 + fs2 * 0.35;
            el("rect", { x: r1(px - 6), y: r1(py - fs2 - 2), width: r1(w + 12), height: r1(fs2 + 10), fill: "transparent" }, g);
            el("text", { x: r1(px), y: r1(py), "font-size": r1(fs2), fill: t.ink, class: "ttl" }, g, e.text);
            if (e.d && e.st) {
                const ax = px + textW(e.text, fs2) + 10, upArrow = e.st.ratio >= 1, sz = fs2 * 0.45;
                el("path", { d: upArrow ? `M${r1(ax)},${r1(py - fs2 * 0.1)}l${r1(sz / 2)},${r1(-sz)}l${r1(sz / 2)},${r1(sz)}Z` : `M${r1(ax)},${r1(py - fs2 * 0.1 - sz)}l${r1(sz / 2)},${r1(sz)}l${r1(sz / 2)},${r1(-sz)}Z`, fill: e.st.color }, g);
                el("text", { x: r1(ax + sz + 6), y: r1(py), "font-size": r1(fs2), fill: e.st.color, class: "lbl" }, g, e.d);
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
}
let CLIP = 0;
