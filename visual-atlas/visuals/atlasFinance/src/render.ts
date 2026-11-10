/*
 * Drawing for Atlas Finance: candlestick (candles, OHLC bars or a close
 * line, volume panel, moving average), waterfall (totals, subtotals,
 * breakdown, connectors), ribbon (ranked columns joined by ribbons) and
 * funnel (bars or tapered, percent of first or previous, conversion).
 */
import powerbi from "powerbi-visuals-api";
import { Model, Candle } from "./model";
import { Cell, catTarget } from "./common/matrix";
import { FinanceSettings } from "./settings";
import { Ctx, SCROLLBAR } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr, val } from "./common/cards";
import { domain, tickWidth, valueAxis, legend, LegendItem } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<FinanceSettings, Model>;

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6;
    const LB = s.labels, CA = s.categoryAxis, VA = s.valueAxis, GR = s.gridlines;
    const lbfs = Math.max(6, LB.fontSize.value), cfs = Math.max(6, CA.fontSize.value), lbC = colorOr(LB.color, t.text), cC = colorOr(CA.color, t.axis);
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    const note = (text: string) => el("text", { x: r1(W / 2), y: r1(H / 2), "text-anchor": "middle", "font-size": 12, fill: t.text, class: "note" }, root, trunc(text, W - 16, 12));
    /** split a label into two lines that each fit a width (words stay whole where possible) */
    const twoLines = (text: string, w: number): string[] => {
        if (textW(text, cfs) <= w) return [text];
        const words = text.split(/\s+/); let a = "", i = 0;
        for (; i < words.length; i++) { const nx = a ? a + " " + words[i] : words[i]; if (a && textW(nx, cfs) > w) break; a = nx; }
        return i < words.length ? [trunc(a, w, cfs), trunc(words.slice(i).join(" "), w, cfs)] : [trunc(a, w, cfs)];
    };
    /** do the category names need a second line in slots of this width? */
    const needsTwo = (names: string[], slot: number) => CA.show.value && names.some(nm => textW(nm, cfs) > slot - 4);
    /** category labels along the bottom (wrapped to two lines when allowed), skipping any that would overlap */
    const catLabels = (xs: { x: number; text: string; target?: Target }[], y: number, maxW: number, wrap = false) => {
        if (!CA.show.value) return;
        let right = -Infinity;
        xs.forEach((p, k) => {
            const lines = wrap ? twoLines(p.text, Math.max(maxW, 30)) : [trunc(p.text, Math.max(maxW, 30), cfs)];
            const w = Math.max(...lines.map(ln => textW(ln, cfs))), left = p.x - w / 2;
            if (left < right + 6 && k) return;
            right = left + w;
            lines.forEach((ln, j) => { const tx = el("text", { x: r1(p.x), y: r1(y + j * (cfs + 2)), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, labels, ln); if (p.target) c.io.bindLabel(tx, p.target); });
        });
    };
    const mx = m.mx;

    if (type === "candlestick") candlestick();
    else if (!mx) note(c.msg("Need_Values", "Add a measure to Values for this chart type."));
    else if (type === "waterfall") waterfall();
    else if (type === "ribbon") ribbon();
    else funnel();

    /* ================================================================ candlestick */
    function candlestick() {
        const K = m.candles, CS = s.candles;
        if (!K.length) { note(c.msg("Need_OHLC", "Add Close and Open, High or Low to draw candles.")); return; }
        const up = colorOr(CS.upColor, "#1a9e5c"), down = colorOr(CS.downColor, "#d64550"), style = val(CS.style), showVol = CS.volume.value && m.hasVolume;
        const fmtP = formatter(m.priceFormat, 1, null, 0, c.culture), fmtVol = formatter(m.volumeFormat, 0, null, Math.max(...K.map(k => k.vol || 0)), c.culture);
        const plotW0 = W - pad * 2, minStep = Math.max(2, CS.minWidth.value) * 1.6, need = K.length * minStep;
        const lo = Math.min(...K.map(k => k.l)), hi = Math.max(...K.map(k => k.h));
        const Hs = need > plotW0 ? H - SCROLLBAR : H, volH = showVol ? Math.max(30, (Hs - pad * 2) * 0.22) : 0, B = Hs - pad - (CA.show.value ? cfs + 8 : 0), T = pad + 4, priceB = B - volH - (showVol ? 8 : 0);
        const d = domain(lo, hi, priceB - T, 44, VA, m.priceFormat, c.culture, false);
        const L = pad + tickWidth(d, VA), R = Math.max(L + 10, (need > plotW0 ? L + need : W - pad) - 4);
        if (need > plotW0) c.grow(R + pad + 4, H);
        const step = (R - L) / K.length, bw = Math.max(1, step * 0.62);
        const X = (i: number) => L + step * (i + 0.5), Y = (v: number) => priceB - (v - d.lo) / (d.hi - d.lo) * (priceB - T);
        valueAxis(root, d, Y, { L, R, T, B: priceB }, true, VA, GR, t);
        const vmax = Math.max(...K.map(k => k.vol || 0), 1e-9);
        const tip = (k: Candle): TipItem[] => {
            const items: TipItem[] = [{ displayName: m.catTitle, value: k.name, color: k.c >= k.o ? up : down }, { displayName: "Open", value: fmtP(k.o) }, { displayName: "High", value: fmtP(k.h) }, { displayName: "Low", value: fmtP(k.l) }, { displayName: "Close", value: fmtP(k.c) }];
            if (k.o) items.push({ displayName: "Change", value: ((k.c / k.o - 1) * 100).toFixed(2) + "%" });
            if (!isNaN(k.vol)) items.push({ displayName: "Volume", value: fmtVol(k.vol) });
            k.tips.forEach(tp => items.push({ displayName: tp.name, value: tp.value }));
            return items;
        };
        if (style === "line") {
            const ln = K.map((k, i) => `${i ? "L" : "M"}${r1(X(i))},${r1(Y(k.c))}`).join("");
            el("path", { d: ln, fill: "none", stroke: t.hc ? t.ink : up, "stroke-width": 2, "stroke-linejoin": "round" }, marks);
        }
        K.forEach((k, i) => {
            const rise = k.c >= k.o, col = t.hc ? t.ink : rise ? up : down, x = X(i), g = el("g", { class: "mk" + (c.io.on(k.i) ? "" : " dim") }, marks);
            if (style === "candle") {
                el("line", { x1: r1(x), x2: r1(x), y1: r1(Y(k.h)), y2: r1(Y(k.l)), stroke: col, "stroke-width": 1.2 }, g);
                const y0 = Y(Math.max(k.o, k.c)), hh = Math.max(1, Math.abs(Y(k.o) - Y(k.c)));
                el("rect", { x: r1(x - bw / 2), y: r1(y0), width: r1(bw), height: r1(hh), rx: r1(Math.min(2, bw / 4)), fill: rise && !t.hc ? (look.flat ? col : look.fill(col, "h")) : t.hc ? t.surface : col, stroke: col, "stroke-width": 1 }, g);
            } else if (style === "ohlc") {
                el("path", { d: `M${r1(x)},${r1(Y(k.h))}V${r1(Y(k.l))}M${r1(x - bw / 2)},${r1(Y(k.o))}H${r1(x)}M${r1(x)},${r1(Y(k.c))}H${r1(x + bw / 2)}`, stroke: col, "stroke-width": 1.4, fill: "none" }, g);
            } else el("circle", { cx: r1(x), cy: r1(Y(k.c)), r: r1(Math.max(1.5, Math.min(3, bw / 3))), fill: col, opacity: 0.001 }, g);
            if (showVol && !isNaN(k.vol)) { const vh = (volH - 4) * k.vol / vmax; el("rect", { x: r1(x - bw / 2), y: r1(B - vh), width: r1(bw), height: r1(Math.max(0.5, vh)), fill: mix(col, t.surface, 0.55) }, g); }
            /* a hit area as tall as the plot so thin candles are easy to point at */
            el("rect", { x: r1(x - step / 2), y: r1(T), width: r1(step), height: r1(B - T), fill: "transparent", style: "cursor:default" }, g);
            c.bind(g, { key: "k" + k.i, items: [k.i], ids: [k.id], tip: () => tip(k) });
        });
        const n = Math.round(CS.movingAverage.value);
        if (n > 1 && K.length > n) {
            let sum = 0; const pts: string[] = [];
            K.forEach((k, i) => { sum += k.c; if (i >= n) sum -= K[i - n].c; if (i >= n - 1) pts.push(`${pts.length ? "L" : "M"}${r1(X(i))},${r1(Y(sum / n))}`); });
            el("path", { d: pts.join(""), fill: "none", stroke: colorOr(CS.maColor, t.hc ? t.ink : mix(t.ink, t.surface, 0.25)), "stroke-width": 1.8, "stroke-dasharray": "5 3", "pointer-events": "none" }, root);
            el("text", { x: r1(R), y: r1(T + 10), "text-anchor": "end", "font-size": 9, fill: t.axis, class: "ax" }, labels, `${n}-period average`);
        }
        if (showVol) el("text", { x: r1(L + 2), y: r1(priceB + 16), "font-size": 9, fill: t.axis, class: "ax" }, labels, "Volume");
        catLabels(K.map((k, i) => ({ x: X(i), text: k.name, target: { key: "k" + k.i, items: [k.i], ids: [k.id], tip: () => tip(k) } })), B + cfs + 4, 140);
    }

    /* ================================================================ waterfall */
    function waterfall() {
        const M = mx as NonNullable<typeof mx>, WF = s.waterfall;
        const inc = colorOr(WF.incColor, "#1a9e5c"), dec = colorOr(WF.decColor, "#d64550"), tot = colorOr(WF.totColor, mix(t.ink, t.surface, 0.35));
        const subs = WF.subtotals.value.split(",").map(x => x.trim().toLowerCase()).filter(x => x);
        interface Step { name: string; v: number; total: boolean; cells: Cell[]; a: number; b: number; }
        const steps: Step[] = [];
        if (M.series.length > 1 && !M.byMeasure && M.cats.length >= 2) {
            /* breakdown: first category total, one step per series (change to the last category), last category total */
            const first = 0, last = M.cats.length - 1, sumOf = (ci: number) => M.grid[ci].reduce((a, x) => a + (x ? x.v : 0), 0);
            steps.push({ name: M.cats[first].name, v: sumOf(first), total: true, cells: M.grid[first].filter(x => x) as Cell[], a: 0, b: 0 });
            M.series.forEach((sr, si) => { const a = M.grid[first][si], b = M.grid[last][si]; steps.push({ name: sr.name, v: (b ? b.v : 0) - (a ? a.v : 0), total: false, cells: [a, b].filter(x => x) as Cell[], a: 0, b: 0 }); });
            steps.push({ name: M.cats[last].name, v: sumOf(last), total: true, cells: M.grid[last].filter(x => x) as Cell[], a: 0, b: 0 });
        } else {
            M.cats.forEach((ct, ci) => { const x = M.grid[ci][0]; if (!x) return; steps.push({ name: ct.name, v: x.v, total: (ci === 0 && WF.startTotal.value) || subs.includes(ct.name.toLowerCase()), cells: [x], a: 0, b: 0 }); });
            if (WF.endTotal.value) steps.push({ name: WF.endLabel.value || "Total", v: 0, total: true, cells: [], a: 0, b: 0 });
        }
        /* running total: totals stand on zero and reset the running value (a subtotal shows the running value) */
        let run = 0;
        steps.forEach((st, k) => {
            if (st.total) {
                const isEnd = k === steps.length - 1 && st.cells.length === 0;
                if (isEnd) st.v = run;
                else if (subs.includes(st.name.toLowerCase()) && k > 0) st.v = run;
                st.a = 0; st.b = st.v; run = st.v;
            } else { st.a = run; run += st.v; st.b = run; }
        });
        const vals = steps.flatMap(st => [st.a, st.b]), wrap = needsTwo(steps.map(st => st.name), (W - pad * 2 - 40) / steps.length);
        const T = pad + (LB.show.value ? lbfs + 6 : 4), B = H - pad - (CA.show.value ? cfs + 8 + (wrap ? cfs + 2 : 0) : 0);
        const d = domain(Math.min(...vals), Math.max(...vals), B - T, 44, VA, M.format, c.culture, true);
        const L = pad + tickWidth(d, VA), R = W - pad - (look.is3d ? 6 : 0);
        const Y = (v: number) => B - (Math.max(d.lo, Math.min(d.hi, v)) - d.lo) / (d.hi - d.lo) * (B - T);
        valueAxis(root, d, Y, { L, R, T, B }, true, VA, GR, t);
        const step = (R - L) / steps.length, bw = Math.max(2, step * 0.66), rad = look.is3d ? 0 : s.waterfall.radius.value;
        const fmtL = labelFormatter(M.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...vals.map(Math.abs)), c.culture), fmtT = formatter(M.format, 1, null, 0, c.culture);
        steps.forEach((st, k) => {
            const x = L + step * k + (step - bw) / 2, y0 = Y(Math.max(st.a, st.b)), h = Math.max(1, Math.abs(Y(st.a) - Y(st.b)));
            const col = t.hc ? t.ink : st.total ? tot : st.v >= 0 ? inc : dec, items = st.cells.map(x2 => x2.i);
            const g = el("g", { class: "mk" + (c.io.anyOn(items) || !items.length ? "" : " dim") }, marks);
            if (look.is3d) { el("path", { d: `M${r1(x)},${r1(y0)}l5,-3h${r1(bw)}l-5,3Z`, fill: look.top(col) }, g); el("path", { d: `M${r1(x + bw)},${r1(y0)}l5,-3v${r1(h)}l-5,3Z`, fill: look.side(col) }, g); }
            el("rect", { x: r1(x), y: r1(y0), width: r1(bw), height: r1(h), rx: r1(Math.min(rad, bw / 2, h / 2)), fill: t.hc ? (st.total ? t.ink : t.surface) : look.fill(col, "v"), stroke: t.hc ? t.ink : "none" }, g);
            const tg: Target = { key: "w" + k, items, ids: st.cells.map(x2 => x2.id), tip: () => [{ displayName: st.total ? "Total" : "Change", value: (st.v > 0 && !st.total ? "+" : "") + fmtT(st.v), color: col }, { displayName: M.catTitle, value: st.name }, { displayName: "Running total", value: fmtT(st.b) }] };
            c.bind(g, tg);
            if (WF.connectors.value && k < steps.length - 1) { const yy = r1(Y(st.b)) + 0.5; el("line", { x1: r1(x + bw), x2: r1(x + step), y1: yy, y2: yy, stroke: mix(t.text, t.surface, 0.5), "stroke-width": 1, "stroke-dasharray": "2 2" }, root); }
            if (LB.show.value) el("text", { x: r1(x + bw / 2), y: r1(y0 - 4), "text-anchor": "middle", "font-size": lbfs, fill: lbC, class: "lbl" }, labels, trunc((st.v > 0 && !st.total ? "+" : "") + fmtL(st.v), step + 4, lbfs));
        });
        catLabels(steps.map((st, k) => ({ x: L + step * (k + 0.5), text: st.name, target: { key: "w" + k, items: st.cells.map(x => x.i), ids: st.cells.map(x => x.id), tip: () => [{ displayName: M.catTitle || "Step", value: st.name }] } })), B + cfs + 4, step - 4, wrap);
    }

    /* ================================================================ ribbon */
    function ribbon() {
        const M = mx as NonNullable<typeof mx>, RB = s.ribbon, N = M.cats.length, S = M.series.length;
        const lg = legend(s.legend, M.series.map(sr => ({ key: sr.key, name: sr.name, color: c.colorOf(sr), on: c.io.anyOn(sr.items), target: { key: "s" + sr.key, items: sr.items, ids: sr.id ? [sr.id] : [], tip: () => [{ displayName: M.serTitle || "Series", value: sr.name }] } })) as LegendItem[], M.serTitle, W, H, pad, t, S > 1);
        const totals = M.cats.map((_, ci) => M.grid[ci].reduce((a, x) => a + (x ? Math.max(0, x.v) : 0), 0));
        const wrap = needsTwo(M.cats.map(ct => ct.name), (W - pad * 2 - 40 - lg.right) / N);
        const T = pad + lg.top + 4, B = H - pad - lg.bottom - (CA.show.value ? cfs + 8 + (wrap ? cfs + 2 : 0) : 0);
        const d = domain(0, Math.max(...totals), B - T, 44, VA, M.format, c.culture, true);
        const L = pad + tickWidth(d, VA), R = W - pad - lg.right;
        const Y = (v: number) => B - v / (d.hi - d.lo) * (B - T);
        valueAxis(root, d, Y, { L, R, T, B }, true, VA, GR, t);
        const step = (R - L) / N, bw = step * RB.columnWidth.value / 100;
        /* stack each column, largest on top when ranking */
        const pos = M.cats.map((_, ci) => {
            const order = M.series.map((_, si) => si).filter(si => M.grid[ci][si]);
            if (RB.rank.value) order.sort((a, b) => (M.grid[ci][a] as Cell).v - (M.grid[ci][b] as Cell).v);
            const out = new Map<number, [number, number]>(); let acc = 0;
            order.forEach(si => { const v = Math.max(0, (M.grid[ci][si] as Cell).v); out.set(si, [acc, acc + v]); acc += v; });
            return out;
        });
        const ribbons = el("g", {}, marks), cols = el("g", {}, marks), fmtL = labelFormatter(M.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...totals), c.culture);
        M.series.forEach((sr, si) => {
            const col = c.colorOf(sr), on = c.io.anyOn(sr.items);
            for (let ci = 0; ci < N - 1; ci++) {
                const a = pos[ci].get(si), b = pos[ci + 1].get(si); if (!a || !b) continue;
                const x0 = L + step * ci + (step + bw) / 2, x1 = L + step * (ci + 1) + (step - bw) / 2, mxm = (x0 + x1) / 2;
                const dd = `M${r1(x0)},${r1(Y(a[1]))}C${r1(mxm)},${r1(Y(a[1]))} ${r1(mxm)},${r1(Y(b[1]))} ${r1(x1)},${r1(Y(b[1]))}L${r1(x1)},${r1(Y(b[0]))}C${r1(mxm)},${r1(Y(b[0]))} ${r1(mxm)},${r1(Y(a[0]))} ${r1(x0)},${r1(Y(a[0]))}Z`;
                const rg = el("path", { d: dd, fill: t.hc ? t.surface : col, "fill-opacity": t.hc ? 1 : RB.opacity.value / 100, stroke: t.hc ? t.ink : "none", class: "grp" + (on ? "" : " dim") }, ribbons);
                c.bind(rg, { key: "s" + sr.key, items: sr.items, ids: sr.id ? [sr.id] : [], tip: () => [{ displayName: M.serTitle || "Series", value: sr.name, color: col }] });
            }
            M.cats.forEach((ct, ci) => {
                const p = pos[ci].get(si), x = M.grid[ci][si]; if (!p || !x) return;
                const g = el("g", { class: "mk" + (c.io.on(x.i) ? "" : " dim") }, cols), y0 = Y(p[1]), hh = Math.max(0.5, Y(p[0]) - Y(p[1]));
                el("rect", { x: r1(L + step * ci + (step - bw) / 2), y: r1(y0), width: r1(bw), height: r1(hh), fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : t.surface, "stroke-width": 0.8 }, g);
                c.bind(g, { key: "i" + x.i, items: [x.i], ids: [x.id], tip: () => [{ displayName: M.catTitle, value: ct.name }, { displayName: sr.name, value: formatter(M.format, 1, null, 0, c.culture)(x.v), color: col }] });
                if (LB.show.value && hh > lbfs + 3 && bw > textW(fmtL(x.v), lbfs) + 2) el("text", { x: r1(L + step * ci + step / 2), y: r1(y0 + hh / 2 + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: t.hc ? t.ink : inkOn(col), class: "ax" }, labels, fmtL(x.v));
            });
        });
        catLabels(M.cats.map((ct, ci) => ({ x: L + step * (ci + 0.5), text: ct.name, target: catTarget(M, ci) })), B + cfs + 4, step - 4, wrap);
        lg.draw(root, c.bind);
    }

    /* ================================================================ funnel */
    function funnel() {
        const M = mx as NonNullable<typeof mx>, FN = s.funnel, rows = M.cats.map((ct, ci) => ({ ct, x: M.grid[ci][0] })).filter(r => r.x) as { ct: typeof M.cats[0]; x: Cell }[];
        if (!rows.length) return;
        const top = Math.max(...rows.map(r => r.x.v), 1e-9), first = rows[0].x.v || 1, n = rows.length, content = val(FN.content), colors = val(FN.colors);
        const convH = FN.conversion.value ? lbfs + 10 : 0, nameW = CA.show.value ? Math.min(W * 0.28, Math.max(...rows.map(r => textW(r.ct.name, cfs)))) + 12 : 0;
        const L = pad + nameW, R = W - pad, T = pad, B = H - pad - convH, band = (B - T) / n, bh = Math.max(3, band * 0.78), cx = (L + R) / 2, maxW = R - L;
        const fmtL = labelFormatter(M.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, top, c.culture), fmtT = formatter(M.format, 1, null, 0, c.culture);
        const pct = (v: number) => (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%";
        const base = c.colorOf(M.cats[0] && M.colored === M.cats ? M.cats[0] : M.series[0]);
        rows.forEach((r, k) => {
            const w = Math.max(2, maxW * Math.max(0, r.x.v) / top), y = T + band * k + (band - bh) / 2;
            const col = t.hc ? t.ink : colors === "vary" && M.colored === M.cats ? c.colorOf(r.ct) : colors === "gradient" ? mix(base, "#000000", 0.45 * k / Math.max(1, n - 1)) : base;
            const g = el("g", { class: "mk" + (c.io.on(r.x.i) ? "" : " dim") }, marks);
            if (val(FN.shape) === "tapered") {
                const next = rows[k + 1] ? Math.max(2, maxW * Math.max(0, rows[k + 1].x.v) / top) : w * 0.85;
                el("path", { d: `M${r1(cx - w / 2)},${r1(y)}H${r1(cx + w / 2)}L${r1(cx + next / 2)},${r1(y + bh)}H${r1(cx - next / 2)}Z`, fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : "none" }, g);
            } else el("rect", { x: r1(cx - w / 2), y: r1(y), width: r1(w), height: r1(bh), rx: r1(Math.min(FN.radius.value, bh / 2, w / 2)), fill: t.hc ? t.surface : look.fill(col, "v"), stroke: t.hc ? t.ink : "none" }, g);
            const prev = k ? rows[k - 1].x.v : r.x.v;
            c.bind(g, { key: "i" + r.x.i, items: [r.x.i], ids: [r.x.id], tip: () => [{ displayName: M.catTitle, value: r.ct.name, color: col }, { displayName: M.series[0].name, value: fmtT(r.x.v) }, { displayName: "% of first", value: pct(r.x.v / first) }, { displayName: "% of previous", value: pct(prev ? r.x.v / prev : 0) }].concat(r.x.tips.map(tp => ({ displayName: tp.name, value: tp.value }))) });
            if (CA.show.value) c.io.bindLabel(el("text", { x: r1(L - 8), y: r1(y + bh / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, labels, trunc(r.ct.name, nameW - 10, cfs)), { key: "c:" + r.ct.key, items: r.ct.items, ids: r.ct.id ? [r.ct.id] : [], tip: () => [{ displayName: M.catTitle, value: r.ct.name }] });
            if (LB.show.value) {
                const txt = content === "value" ? fmtL(r.x.v) : content === "percentFirst" ? pct(r.x.v / first) : content === "previous" ? `${fmtL(r.x.v)} · ${k ? pct(prev ? r.x.v / prev : 0) : "100%"}` : `${fmtL(r.x.v)} · ${pct(r.x.v / first)}`;
                /* a tapered stage is narrowest at its bottom edge */
                const narrow = val(FN.shape) === "tapered" ? Math.min(w, rows[k + 1] ? Math.max(2, maxW * Math.max(0, rows[k + 1].x.v) / top) : w * 0.85) : w;
                const inside = textW(txt, lbfs) + 8 < narrow;
                el("text", { x: r1(inside ? cx : cx + Math.max(w, narrow) / 2 + 6), y: r1(y + bh / 2 + lbfs * 0.35), "text-anchor": inside ? "middle" : "start", "font-size": lbfs, fill: inside ? (t.hc ? t.ink : inkOn(col)) : lbC, class: inside ? "lbl in" : "lbl" }, labels, txt);
            }
        });
        if (FN.conversion.value && n > 1) el("text", { x: r1(cx), y: r1(H - pad - 2), "text-anchor": "middle", "font-size": lbfs + 1, fill: t.text, class: "ttl" }, labels, `${c.msg("Conversion", "Conversion rate")}: ${pct(rows[n - 1].x.v / first)}`);
    }
}
