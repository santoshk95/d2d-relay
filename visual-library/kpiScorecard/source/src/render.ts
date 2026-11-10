/*
 * Drawing for KPI Scorecard: a header row, then one row per KPI with the name, result, latest period,
 * target, a status chip and a sparkline. Columns are sized from the text they hold; on narrow tiles the
 * sparkline, then the latest and target columns, give way. Too many rows for the height: the visual scrolls.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Row, Status } from "./model";
import { Settings } from "./settings";
import { Ctx } from "./common/family";
import { el, r1, textW, trunc } from "./common/look";
import { colorOr } from "./common/cards";
import { mix } from "./common/color";
import { formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<Settings, Model>;
type Col = "kpi" | "result" | "latest" | "target" | "status" | "trend";

export function render(c: C) {
    const { W, s, m, root, t, look } = c, pad = 8, gap = 14;
    const fs = Math.max(6, s.chart.fontSize.value), hfs = Math.max(6, s.headers.fontSize.value);
    const ink = colorOr(s.labels.color, t.ink), sub = t.axis;
    const ST = s.status, good = colorOr(ST.goodColor, "#1a9e5c"), warn = colorOr(ST.warnColor, "#d9a400"), bad = colorOr(ST.badColor, "#d64550");
    const stColor = (st: Status) => (t.hc ? t.ink : st === "good" ? good : st === "warn" ? warn : st === "bad" ? bad : t.axis);
    const accent = c.colorOf(m.accent);
    const H0 = c.H;

    /* column widths from their content */
    const head = (k: Col, f: string) => { const v = String((s.headers as unknown as Record<string, { value: string }>)[k].value || ""); return v || f; };
    const heads: Record<Col, string> = {
        kpi: head("kpi", m.catTitle), result: head("result", m.heads.result), latest: head("latest", m.heads.latest),
        target: head("target", m.heads.target), status: head("status", m.heads.status), trend: head("trend", m.heads.trend)
    };
    const showHead = s.headers.show.value;
    const wOf = (k: Col, get: (r: Row) => string) => Math.max(showHead ? textW(heads[k], hfs) : 0, ...m.list.map(r => textW(get(r), fs)));
    const icon = ST.icons.value ? fs + 4 : 0;
    const chipW = Math.max(...m.list.map(r => (r.statusText ? textW(r.statusText, fs) + icon + 14 : 0)));
    const want: Record<Col, number> = {
        kpi: Math.min(wOf("kpi", r => r.name), Math.max(90, W * 0.34)),
        result: m.has.result ? wOf("result", r => r.result) : 0,
        latest: m.has.latest ? wOf("latest", r => r.latest) : 0,
        target: m.has.target ? wOf("target", r => r.target) : 0,
        status: m.has.status ? Math.max(chipW, showHead ? textW(heads.status, hfs) : 0) : 0,
        trend: m.hasTrend && s.trend.show.value ? Math.max(48, Math.min(150, W * 0.2)) : 0
    };
    const order: Col[] = ["kpi", "result", "latest", "target", "status", "trend"];
    const minKpi = Math.min(want.kpi, 70);
    const total = () => order.reduce((a, k) => a + (want[k] > 0 ? want[k] + gap : 0), 0) - gap + 2 * pad;
    /* narrow: drop the sparkline, then latest, then target; then shrink the KPI names */
    for (const k of ["trend", "latest", "target"] as Col[]) { if (total() - want.kpi + minKpi <= W) break; want[k] = 0; }
    const spare = W - total();
    if (spare < 0) want.kpi = Math.max(minKpi, want.kpi + spare);
    else { const extraK = Math.min(spare, Math.max(0, wOf("kpi", r => r.name) - want.kpi)); want.kpi += extraK; if (want.trend > 0) want.trend += Math.min(spare - extraK, 60); }
    /* left edges; numeric columns are right-aligned, so spread leftover space before the numbers */
    const leftover = Math.max(0, W - total());
    const x: Record<Col, number> = { kpi: pad, result: 0, latest: 0, target: 0, status: 0, trend: 0 };
    let cur = pad + want.kpi + gap + leftover;
    order.slice(1).forEach(k => { if (want[k] > 0) { x[k] = cur; cur += want[k] + gap; } });

    const headH = showHead ? hfs + 12 : 2;
    const n = m.list.length;
    const rowH = Math.max(fs * 1.9, Math.min(fs * 3.4, (H0 - headH - pad) / Math.max(1, n)));
    const fullH = headH + rowH * n + pad;
    if (fullH > H0 + 0.5) c.grow(W, fullH);

    /* header */
    if (showHead) {
        const hg = el("g", { class: "hdr" }, root), hy = r1(hfs + 4);
        order.forEach(k => {
            if (want[k] <= 0) return;
            const right = k === "result" || k === "latest" || k === "target";
            el("text", { x: r1(right ? x[k] + want[k] : x[k]), y: hy, "text-anchor": right ? "end" : "start", "font-size": hfs, fill: sub, "font-weight": 600 }, hg, trunc(heads[k], want[k] + (right ? 0 : gap - 2), hfs));
        });
        el("line", { x1: pad, x2: W - pad, y1: r1(headH - 1), y2: r1(headH - 1), stroke: t.grid, "stroke-width": 1.2 }, hg);
    }

    const body = el("g", {}, root), trendFmt = formatter(m.list[0].trendFormat, 1, null, 0, c.culture);
    m.list.forEach((r, i) => {
        const y0 = headH + rowH * i, mid = y0 + rowH / 2, base = mid + fs * 0.36;
        const g = el("g", { class: "mk" + (c.io.on(r.i) ? "" : " dim") }, body);
        el("rect", { x: 0, y: r1(y0), width: W, height: r1(rowH), fill: s.chart.zebra.value && i % 2 ? mix(t.grid, t.surface, 0.5) : t.surface, "fill-opacity": s.chart.zebra.value && i % 2 ? 1 : 0 }, g);
        if (s.chart.rowLines.value && i < n - 1) el("line", { x1: pad, x2: W - pad, y1: r1(y0 + rowH), y2: r1(y0 + rowH), stroke: t.grid }, g);
        el("text", { x: x.kpi, y: r1(base), "font-size": fs, fill: ink, "font-weight": 600 }, g, trunc(r.name, want.kpi, fs));
        (["result", "latest", "target"] as Col[]).forEach(k => {
            if (want[k] <= 0) return;
            const v = (r as unknown as Record<string, string>)[k] || "–";
            el("text", { x: r1(x[k] + want[k]), y: r1(base), "text-anchor": "end", "font-size": fs, fill: k === "result" ? ink : t.text, "font-weight": k === "result" ? 600 : 400 }, g, trunc(v, want[k], fs));
        });
        if (want.status > 0 && r.statusText) {
            const col = stColor(r.status), cw = textW(r.statusText, fs) + icon + 14, ch = Math.min(rowH - 6, fs + 10);
            const chip = el("g", {}, g);
            el("rect", { x: r1(x.status), y: r1(mid - ch / 2), width: r1(Math.min(cw, want.status)), height: r1(ch), rx: r1(ch / 2), fill: t.hc ? t.surface : mix(col, t.surface, t.dark ? 0.7 : 0.86), stroke: t.hc ? t.ink : "none" }, chip);
            let tx = x.status + 7;
            if (icon) {
                const cr = (fs + 2) / 2, cx = tx + cr, sh = look.shadow();
                el("circle", { cx: r1(cx), cy: r1(mid), r: r1(cr), fill: t.hc ? t.ink : look.fill(col, "r"), filter: sh || undefined }, chip);
                glyph(chip, r.status, cx, mid, cr, t.hc ? t.surface : t.surface);
                tx += icon;
            }
            el("text", { x: r1(tx), y: r1(base), "font-size": fs, fill: t.hc ? t.ink : mix(col, t.ink, 0.45), "font-weight": 600 }, chip, trunc(r.statusText, want.status - (tx - x.status) - 4, fs));
        }
        if (want.trend > 0 && r.trend.length > 1) {
            const vs = r.trend.map(p => p.v), lo = Math.min(...vs), hi = Math.max(...vs), sh = Math.min(rowH - 8, fs * 2), dr = 3;
            const L = x.trend, R = x.trend + want.trend - dr - 1, T = mid - sh / 2, B = mid + sh / 2;
            const px = (k: number) => L + (R - L) * k / (r.trend.length - 1), py = (v: number) => (hi === lo ? mid : B - (v - lo) / (hi - lo) * (B - T));
            el("path", { d: r.trend.map((p, k) => (k ? "L" : "M") + r1(px(k)) + "," + r1(py(p.v))).join(""), fill: "none", stroke: t.hc ? t.ink : mix(t.axis, t.surface, 0.2), "stroke-width": s.trend.width.value, "stroke-linejoin": "round", "stroke-linecap": "round" }, g);
            if (s.trend.endDot.value) { const lp = r.trend[r.trend.length - 1]; el("circle", { cx: r1(px(r.trend.length - 1)), cy: r1(py(lp.v)), r: dr, fill: t.hc ? t.ink : look.fill(accent, "r") }, g); }
        }
        c.bind(g, { key: "i" + r.i, items: [r.i], ids: r.id ? [r.id] : [], tip: () => tip(r) });
    });

    function tip(r: Row): TipItem[] {
        const out: TipItem[] = [{ displayName: m.catTitle, value: r.name }];
        if (r.result) out.push({ displayName: heads.result, value: r.result });
        if (r.latest) out.push({ displayName: heads.latest, value: r.latest });
        if (r.target) out.push({ displayName: heads.target, value: r.target });
        if (r.statusText) out.push({ displayName: heads.status, value: r.statusText, color: stColor(r.status) });
        if (r.trend.length) { const lp = r.trend[r.trend.length - 1]; out.push({ displayName: lp.name, value: r.trendFormat ? trendFmt(lp.v) : String(lp.v) }); }
        return out.concat(r.tips.map(tp => ({ displayName: tp.name, value: tp.value })));
    }
}

/** check, exclamation or down arrow inside the status dot */
function glyph(g: SVGGElement, st: Status, cx: number, cy: number, r: number, color: string) {
    const w = Math.max(1.2, r * 0.32);
    if (st === "good") el("path", { d: `M${r1(cx - r * 0.45)},${r1(cy + r * 0.02)}L${r1(cx - r * 0.1)},${r1(cy + r * 0.38)}L${r1(cx + r * 0.48)},${r1(cy - r * 0.34)}`, fill: "none", stroke: color, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" }, g);
    else if (st === "warn") {
        el("line", { x1: r1(cx), x2: r1(cx), y1: r1(cy - r * 0.5), y2: r1(cy + r * 0.12), stroke: color, "stroke-width": w, "stroke-linecap": "round" }, g);
        el("circle", { cx: r1(cx), cy: r1(cy + r * 0.45), r: r1(w * 0.55), fill: color }, g);
    } else if (st === "bad") el("path", { d: `M${r1(cx)},${r1(cy - r * 0.5)}L${r1(cx)},${r1(cy + r * 0.45)}M${r1(cx - r * 0.4)},${r1(cy + r * 0.08)}L${r1(cx)},${r1(cy + r * 0.48)}L${r1(cx + r * 0.4)},${r1(cy + r * 0.08)}`, fill: "none", stroke: color, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" }, g);
}
