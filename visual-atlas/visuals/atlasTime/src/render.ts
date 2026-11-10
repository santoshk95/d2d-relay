/*
 * Drawing for Atlas Time: calendar heatmap (year of weeks, or month
 * pages), heat grid and punch card, stream graph (wiggle, silhouette,
 * stacked, 100%) and a timeline slicer that filters the report.
 */
import powerbi from "powerbi-visuals-api";
import { Model, TCell, TRow } from "./model";
import { TimeSettings } from "./settings";
import { Ctx, SCROLLBAR } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr, val } from "./common/cards";
import { legend, LegendItem } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<TimeSettings, Model>;
/** timeline state kept by the visual: the selected range, from the first period's start to the last period's end (exclusive) */
export interface Range { from: number; to: number; }
export interface TimelineIO { range: Range | null; apply: (r: Range | null) => void; ok: boolean; }

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());

export function render(c: C, tl: TimelineIO) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 6;
    const LB = s.labels, CA = s.categoryAxis, lbfs = Math.max(6, LB.fontSize.value), cfs = Math.max(6, CA.fontSize.value), cC = colorOr(CA.color, t.axis);
    const SC = s.scale, high = t.hc ? t.ink : colorOr(SC.highColor, c.colorOf(m.series[0])), low = t.hc ? t.surface : colorOr(SC.lowColor, mix(high, t.surface, 0.88));
    const empty = colorOr(SC.emptyColor, mix(t.text, t.surface, 0.94)), steps = Math.round(SC.steps.value), gap = SC.gap.value, rad = look.is3d ? 1 : SC.radius.value;
    const fmtV = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, Math.max(...m.cells.map(x => Math.abs(x.v))), c.culture);
    const fmtTip = formatter(m.format, 1, null, 0, c.culture);
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    /* sequential color for a value between lo and hi (optionally in steps) */
    const quant = val(SC.mode) === "quantile";
    /* by value: position between lo and hi; by rank: share of values below (one spike no longer washes out the rest) */
    const scale = (lo: number, hi: number, all?: number[]) => {
        const sorted = (all || []).slice().sort((a, b) => a - b);
        const rank = (v: number) => { let a = 0, b = sorted.length; while (a < b) { const md = (a + b) >> 1; if (sorted[md] < v) a = md + 1; else b = md; } return sorted.length > 1 ? a / (sorted.length - 1) : 1; };
        return (v: number) => {
        let k = quant && sorted.length ? rank(v) : hi > lo ? (v - lo) / (hi - lo) : 1; k = Math.max(0, Math.min(1, k));
        if (steps > 0) k = Math.min(steps - 1, Math.floor(k * steps)) / Math.max(1, steps - 1);
        return mix(low, high, k);
        };
    };
    const note = (text: string) => el("text", { x: r1(W / 2), y: r1(H / 2), "text-anchor": "middle", "font-size": 12, fill: t.text, class: "note" }, root, trunc(text, W - 16, 12));
    /** items, ids and tooltip for a group of rows (a day, a grid cell, a period) */
    const group = (key: string, rows: TRow[], title: [string, string][], extra?: TipItem[]): Target => {
        const cells = rows.flatMap(p => p.cells.filter(x => x) as TCell[]);
        return {
            key, items: cells.map(x => x.i), ids: cells.map(x => x.id).slice(0, 400), tip: () => {
                const items: TipItem[] = title.map(([k, v]) => ({ displayName: k, value: v }));
                items.push({ displayName: m.valueName, value: fmtTip(cells.reduce((a, x) => a + x.v, 0)) });
                if (cells.some(x => x.hlv !== null)) items.push({ displayName: "Highlighted", value: fmtTip(cells.reduce((a, x) => a + (x.hlv || 0), 0)) });
                if (rows.length === 1) (rows[0].cells.find(x => x) as TCell | undefined)?.tips.forEach(tp => items.push({ displayName: tp.name, value: tp.value }));
                return items.concat(extra || []);
            }
        };
    };
    const cellBox = (g: Element, x: number, y: number, w: number, h: number, fill: string) => {
        el("rect", { x: r1(x), y: r1(y), width: r1(Math.max(0.5, w)), height: r1(Math.max(0.5, h)), rx: r1(Math.min(rad, w / 2, h / 2)), fill, stroke: t.hc ? t.ink : "none", "stroke-width": t.hc ? 0.6 : 0 }, g);
        if (look.is3d && w > 5) el("path", { d: `M${r1(x + w)},${r1(y)}V${r1(y + h)}H${r1(x)}`, fill: "none", stroke: mix(fill, "#000000", 0.25), "stroke-width": 1.2 }, g);
    };

    if (type === "calendar") calendar();
    else if (type === "heatgrid") heatgrid();
    else if (type === "stream") stream();
    else timeline();

    /* ================================================================ calendar heatmap */
    function calendar() {
        const dated = m.points.filter(p => p.date);
        if (!dated.length) { note(c.msg("Need_Dates", "A calendar needs a date in Time.")); return; }
        const byDay = new Map<string, TRow[]>();
        dated.forEach(p => { const k = dayKey(p.date as Date); const l = byDay.get(k) || []; l.push(p); byDay.set(k, l); });
        const totOf = (k: string) => (byDay.get(k) || []).reduce((a, p) => a + p.total, 0);
        /* daily counts rarely go near zero, so the scale runs from the smallest day to the largest */
        const vals = [...byDay.keys()].map(totOf), col = scale(Math.min(...vals), Math.max(...vals), vals);
        const d0 = startOfDay(new Date(Math.min(...dated.map(p => (p.date as Date).getTime())))), d1 = startOfDay(new Date(Math.max(...dated.map(p => (p.date as Date).getTime()))));
        const mon = val(s.calendar.weekStart) === "monday", dow = (d: Date) => (mon ? (d.getDay() + 6) % 7 : d.getDay());
        const dayNames = mon ? DAYS : ["Sun"].concat(DAYS.slice(0, 6));
        const on = (k: string) => c.io.anyOn((byDay.get(k) || []).flatMap(p => p.cells.filter(x => x).map(x => (x as TCell).i)));
        const dayCell = (g: Element, d: Date, x: number, y: number, size: number, numbers: boolean) => {
            const k = dayKey(d), has = byDay.has(k), v = totOf(k), fill = has ? col(v) : empty;
            const cg = el("g", { class: has ? "mk" + (on(k) ? "" : " dim") : "" }, g);
            cellBox(cg, x, y, size, size, fill);
            if (numbers && size > 14) el("text", { x: r1(x + 3), y: r1(y + Math.min(10, size * 0.4) + 1), "font-size": r1(Math.min(9, size * 0.32)), fill: has ? inkOn(fill) : t.axis, class: "ax" }, labels, String(d.getDate()));
            if (has && LB.show.value && size > lbfs * 2.2) el("text", { x: r1(x + size / 2), y: r1(y + size * 0.7), "text-anchor": "middle", "font-size": lbfs, fill: inkOn(fill), class: "lbl in" }, labels, trunc(fmtV(v), size - 2, lbfs));
            if (has) c.bind(cg, group("d" + k, byDay.get(k) as TRow[], [["Date", `${dayNames[dow(d)]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`]]));
        };
        if (val(s.calendar.view) === "month") {
            const months: Date[] = []; for (let d = new Date(d0.getFullYear(), d0.getMonth(), 1); d <= d1; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) months.push(d);
            const nM = months.length, cols = Math.max(1, Math.min(nM, Math.round(Math.sqrt(nM * W / H * 6 / 7)))), rows = Math.ceil(nM / cols);
            const pw = (W - pad * 2) / cols, ph = (H - pad * 2) / rows, head = cfs + 6 + (s.calendar.dayNames.value ? cfs + 2 : 0);
            const size = Math.max(4, Math.min((pw - 10) / 7, (ph - head - 6) / 6) - gap);
            months.forEach((mo, k) => {
                const px = pad + pw * (k % cols), py = pad + ph * Math.floor(k / cols), g = el("g", {}, marks);
                const gx = px + (pw - 7 * (size + gap)) / 2;
                el("text", { x: r1(gx), y: r1(py + cfs), "font-size": cfs, fill: t.text, class: "ttl" }, labels, `${MONTHS[mo.getMonth()]} ${mo.getFullYear()}`);
                if (s.calendar.dayNames.value) dayNames.forEach((dn, j) => el("text", { x: r1(gx + j * (size + gap) + size / 2), y: r1(py + cfs * 2 + 4), "text-anchor": "middle", "font-size": Math.max(6, cfs - 2), fill: t.axis, class: "ax" }, labels, size > 16 ? dn : dn[0]));
                const first = dow(mo);
                for (let d = new Date(mo); d.getMonth() === mo.getMonth(); d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
                    const idx = first + d.getDate() - 1, x = gx + (idx % 7) * (size + gap), y = py + head + Math.floor(idx / 7) * (size + gap);
                    dayCell(g, d, x, y, size, true);
                }
            });
            return;
        }
        /* year view: one block per year, weeks as columns and weekdays as rows */
        const years: number[] = []; for (let y = d0.getFullYear(); y <= d1.getFullYear(); y++) years.push(y);
        const yLab = textW("2026", cfs) + 8, dLab = s.calendar.dayNames.value ? textW("Wed", cfs) + 6 : 0, mH = s.calendar.monthNames.value ? cfs + 4 : 0;
        const size = Math.max(3, Math.min((W - pad * 2 - yLab - dLab) / 54 - gap, (H - pad * 2 - years.length * (mH + 8)) / (years.length * 7) - gap));
        const blockH = 7 * (size + gap) + mH + 8, top = Math.max(pad, (H - years.length * blockH) / 2);
        years.forEach((yr, k) => {
            const y0 = top + k * blockH + mH, x0 = pad + yLab + dLab, g = el("g", {}, marks);
            el("text", { x: r1(pad), y: r1(y0 + 3.5 * (size + gap)), "font-size": cfs, fill: t.text, class: "ttl" }, labels, String(yr));
            if (s.calendar.dayNames.value) [0, 2, 4].forEach(j => el("text", { x: r1(pad + yLab), y: r1(y0 + j * (size + gap) + size * 0.8), "font-size": Math.max(6, Math.min(cfs, size * 1.1)), fill: t.axis, class: "ax" }, labels, dayNames[j]));
            const jan1 = new Date(yr, 0, 1), off = dow(jan1);
            for (let d = new Date(jan1); d.getFullYear() === yr; d = new Date(yr, d.getMonth(), d.getDate() + 1)) {
                const doy = Math.round((d.getTime() - jan1.getTime()) / 864e5), wk = Math.floor((doy + off) / 7), x = x0 + wk * (size + gap), y = y0 + dow(d) * (size + gap);
                if (d.getDate() === 1 && s.calendar.monthNames.value) el("text", { x: r1(x), y: r1(y0 - 4), "font-size": Math.max(6, cfs - 1), fill: t.axis, class: "ax" }, labels, MONTHS[d.getMonth()]);
                if (d < d0 || d > d1) { cellBox(g, x, y, size, size, mix(empty, t.surface, 0.5)); continue; }
                dayCell(g, d, x, y, size, false);
            }
        });
    }

    /* ================================================================ heat grid and punch card */
    function heatgrid() {
        const rowKeys: string[] = [], colKeys: string[] = [], rowName = new Map<string, string>(), colName = new Map<string, string>(), cell = new Map<string, TRow[]>();
        m.points.forEach(p => {
            const rk = m.hasRows ? String(p.rowRaw) : "", ck = String(p.raw);
            if (!rowName.has(rk)) { rowName.set(rk, m.hasRows ? p.rowName : m.valueName); rowKeys.push(rk); }
            if (!colName.has(ck)) { colName.set(ck, p.name); colKeys.push(ck); }
            const k = rk + "\u001f" + ck, l = cell.get(k) || []; l.push(p); cell.set(k, l);
        });
        const tot = (k: string) => (cell.get(k) || []).reduce((a, p) => a + p.total, 0), all = [...cell.keys()].map(tot);
        const lo = Math.min(0, ...all), hi = Math.max(...all), col = scale(lo, hi, all), punch = val(s.heatgrid.shape) === "circle";
        const nameW = CA.show.value ? Math.min(W * 0.3, Math.max(...rowKeys.map(k => textW(rowName.get(k) as string, cfs)))) + 8 : 0, colH = CA.show.value ? cfs + 8 : 0;
        const L = pad + nameW, T = pad, R = W - pad, B = H - pad - colH;
        const cw = (R - L) / colKeys.length, ch = (B - T) / rowKeys.length, skip = Math.max(1, Math.ceil((Math.max(...colKeys.map(k => textW(colName.get(k) as string, cfs))) + 6) / cw));
        rowKeys.forEach((rk, i) => {
            if (CA.show.value) c.io.bindLabel(el("text", { x: r1(L - 6), y: r1(T + ch * i + ch / 2 + cfs * 0.35), "text-anchor": "end", "font-size": cfs, fill: cC, class: "ax" }, labels, trunc(rowName.get(rk) as string, nameW - 8, cfs)), group("r" + rk, m.points.filter(p => (m.hasRows ? String(p.rowRaw) : "") === rk), [[m.hasRows ? m.rowsName : "Row", rowName.get(rk) as string]]));
            colKeys.forEach((ck, j) => {
                const k = rk + "\u001f" + ck, rows = cell.get(k), x = L + cw * j, y = T + ch * i;
                if (!rows) { if (!punch) cellBox(marks, x + gap / 2, y + gap / 2, cw - gap, ch - gap, empty); return; }
                const v = tot(k), items = rows.flatMap(p => p.cells.filter(z => z).map(z => (z as TCell).i));
                const g = el("g", { class: "mk" + (c.io.anyOn(items) ? "" : " dim") }, marks);
                let fill: string;
                if (punch) {
                    const r = Math.max(0.5, Math.sqrt(Math.max(0, v) / (hi || 1)) * Math.min(cw, ch) * 0.46);
                    fill = s.heatgrid.colorCircles.value ? col(v) : high;
                    el("circle", { cx: r1(x + cw / 2), cy: r1(y + ch / 2), r: r1(r), fill: look.flat || t.hc ? fill : look.fill(fill, "r") }, g);
                } else { fill = col(v); cellBox(g, x + gap / 2, y + gap / 2, cw - gap, ch - gap, fill); }
                c.bind(g, group("h" + k, rows, [[m.hasRows ? m.rowsName : "Row", rowName.get(rk) as string], [m.timeName, colName.get(ck) as string]]));
                if (LB.show.value && !punch && cw > textW(fmtV(v), lbfs) + 4 && ch > lbfs + 2) el("text", { x: r1(x + cw / 2), y: r1(y + ch / 2 + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: inkOn(fill), class: "ax" }, labels, fmtV(v));
            });
        });
        if (CA.show.value) colKeys.forEach((ck, j) => { if (j % skip === 0) c.io.bindLabel(el("text", { x: r1(L + cw * j + cw / 2), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: cC, class: "ax" }, labels, trunc(colName.get(ck) as string, cw * skip - 2, cfs)), group("t" + ck, m.points.filter(p => String(p.raw) === ck), [[m.timeName, colName.get(ck) as string]])); });
    }

    /* ================================================================ stream graph */
    function stream() {
        const xs = m.points, n = xs.length, S = m.series.length, ST = s.stream, offset = val(ST.offset);
        if (n < 2) { note(c.msg("Need_Two_Times", "A stream graph needs two or more points in Time.")); return; }
        const v = m.series.map((_, si) => xs.map(p => (p.cells[si] ? Math.max(0, (p.cells[si] as TCell).v) : 0)));
        const sum = xs.map((_, j) => v.reduce((a, row) => a + row[j], 0));
        const base = new Array(n).fill(0);
        if (offset === "silhouette") for (let j = 0; j < n; j++) base[j] = -sum[j] / 2;
        else if (offset === "wiggle") {
            /* Byron & Wattenberg: minimize the weighted wiggle of every layer */
            let y = 0;
            for (let j = 1; j < n; j++) {
                let s1 = 0, s2 = 0;
                for (let i = 0; i < S; i++) {
                    let s3 = (v[i][j] - v[i][j - 1]) / 2;
                    for (let k = 0; k < i; k++) s3 += v[k][j] - v[k][j - 1];
                    s1 += v[i][j]; s2 += s3 * v[i][j];
                }
                if (s1) y -= s2 / s1;
                base[j] = y;
            }
            const mid = base.reduce((a, b, j) => a + b + sum[j] / 2, 0) / n;
            for (let j = 0; j < n; j++) base[j] -= mid;
        }
        const norm = offset === "expand";
        const lg = legend(s.legend, m.series.map(sr => ({ key: sr.key, name: sr.name, color: c.colorOf(sr), on: c.io.anyOn(sr.items), target: { key: "s" + sr.key, items: sr.items, ids: sr.id ? [sr.id] : [], tip: () => [{ displayName: m.seriesName || "Series", value: sr.name }] } })) as LegendItem[], m.seriesName, W, H, pad, t, S > 1);
        const L = pad, R = W - pad - lg.right, T = pad + lg.top, B = H - pad - lg.bottom - (CA.show.value ? cfs + 8 : 0);
        const lo = norm ? 0 : Math.min(...base), hi = norm ? 1 : Math.max(...base.map((b, j) => b + sum[j]));
        const X = (j: number) => L + (R - L) * j / (n - 1), Y = (y: number) => B - (y - lo) / ((hi - lo) || 1) * (B - T);
        const smooth = ST.smooth.value;
        const pathOf = (pts: [number, number][]) => {
            if (!smooth) return pts.map((p, k) => `${k ? "L" : "M"}${r1(p[0])},${r1(p[1])}`).join("");
            let d = `M${r1(pts[0][0])},${r1(pts[0][1])}`;
            for (let k = 1; k < pts.length; k++) { const mx = (pts[k - 1][0] + pts[k][0]) / 2; d += `C${r1(mx)},${r1(pts[k - 1][1])} ${r1(mx)},${r1(pts[k][1])} ${r1(pts[k][0])},${r1(pts[k][1])}`; }
            return d;
        };
        const acc = base.slice().map((b, j) => (norm ? 0 : b));
        m.series.forEach((sr, si) => {
            const y0 = acc.slice(), y1 = acc.map((a, j) => a + (norm ? (sum[j] ? v[si][j] / sum[j] : 0) : v[si][j]));
            for (let j = 0; j < n; j++) acc[j] = y1[j];
            const top = y1.map((y, j): [number, number] => [X(j), Y(y)]), bot = y0.map((y, j): [number, number] => [X(j), Y(y)]).reverse();
            const d = pathOf(top) + "L" + pathOf(bot).slice(1) + "Z", col = c.colorOf(sr);
            const g = el("g", { class: "grp" + (c.io.anyOn(sr.items) ? "" : " dim") }, marks);
            el("path", { d, fill: t.hc ? t.surface : look.flat ? col : look.fill(col, "v"), "fill-opacity": ST.opacity.value / 100, stroke: t.hc ? t.ink : t.surface, "stroke-width": t.hc ? 1 : 0.6 }, g);
            const peak = v[si].indexOf(Math.max(...v[si])), total = v[si].reduce((a, b) => a + b, 0);
            c.bind(g, { key: "s" + sr.key, items: sr.items, ids: sr.id ? [sr.id] : [], tip: () => [{ displayName: m.seriesName || "Series", value: sr.name, color: col }, { displayName: "Total", value: fmtTip(total) }, { displayName: "Peak", value: `${xs[peak].name}: ${fmtTip(v[si][peak])}` }] });
            /* label at the thickest point when it fits */
            let best = -1, th = 0; for (let j = 1; j < n - 1; j++) { const h = Y(y0[j]) - Y(y1[j]); if (h > th) { th = h; best = j; } }
            if (LB.show.value && best > 0 && th > lbfs + 4 && textW(sr.name, lbfs) < (R - L) / 3) el("text", { x: r1(X(best)), y: r1((Y(y0[best]) + Y(y1[best])) / 2 + lbfs * 0.35), "text-anchor": "middle", "font-size": lbfs, fill: t.hc ? t.ink : inkOn(col), class: "ttl" }, labels, sr.name);
        });
        if (CA.show.value) { let right = -Infinity; xs.forEach((p, j) => { const w = textW(p.name, cfs), left = j === 0 ? X(j) : j === n - 1 ? X(j) - w : X(j) - w / 2; if (left < right + 8) return; right = left + w; el("text", { x: r1(X(j)), y: r1(B + cfs + 4), "text-anchor": j === 0 ? "start" : j === n - 1 ? "end" : "middle", "font-size": cfs, fill: cC, class: "ax" }, labels, p.name); }); }
        lg.draw(root, c.bind);
    }

    /* ================================================================ timeline slicer */
    function timeline() {
        const dated = m.points.filter(p => p.date);
        if (!dated.length) { note(c.msg("Need_Dates", "A timeline slicer needs a date in Time.")); return; }
        const grain = val(s.timeline.granularity);
        const periodOf = (d: Date): { start: Date; end: Date; label: string; group: string } => {
            const y = d.getFullYear(), mo = d.getMonth();
            if (grain === "year") return { start: new Date(y, 0, 1), end: new Date(y + 1, 0, 1), label: String(y), group: "" };
            if (grain === "quarter") { const q = Math.floor(mo / 3); return { start: new Date(y, q * 3, 1), end: new Date(y, q * 3 + 3, 1), label: "Q" + (q + 1), group: String(y) }; }
            if (grain === "month") return { start: new Date(y, mo, 1), end: new Date(y, mo + 1, 1), label: MONTHS[mo], group: String(y) };
            if (grain === "week") { const st = new Date(y, mo, d.getDate() - ((d.getDay() + 6) % 7)); return { start: st, end: new Date(st.getFullYear(), st.getMonth(), st.getDate() + 7), label: `${st.getDate()}`, group: `${MONTHS[st.getMonth()]} ${st.getFullYear()}` }; }
            const st = startOfDay(d); return { start: st, end: new Date(y, mo, d.getDate() + 1), label: String(d.getDate()), group: `${MONTHS[mo]} ${y}` };
        };
        /* every period between the first and the last date, with or without data */
        const t0 = periodOf(new Date(Math.min(...dated.map(p => (p.date as Date).getTime())))).start, t1 = periodOf(new Date(Math.max(...dated.map(p => (p.date as Date).getTime())))).start;
        const periods: { start: Date; end: Date; label: string; group: string; rows: TRow[] }[] = [];
        for (let p = periodOf(t0); p.start <= t1; p = periodOf(p.end)) periods.push({ ...p, rows: [] });
        const idx = new Map(periods.map((p, k) => [p.start.getTime(), k]));
        dated.forEach(row => { const k = idx.get(periodOf(row.date as Date).start.getTime()); if (k !== undefined) periods[k].rows.push(row); });
        const tot = periods.map(p => p.rows.reduce((a, r) => a + r.total, 0)), mx = Math.max(...tot, 1e-9);
        const sel = colorOr(s.timeline.selColor, high), range = tl.range;
        const inRange = (p: { start: Date; end: Date }) => !!range && p.start.getTime() >= range.from && p.end.getTime() <= range.to;
        const headH = cfs + 12, groupH = cfs + 6, minW = Math.max(14, Math.max(...periods.map(p => textW(p.label, cfs))) + 6);
        const plotW = W - pad * 2, needW = periods.length * minW;
        if (needW > plotW) c.grow(needW + pad * 2, H);
        const Hs = needW > plotW ? H - SCROLLBAR : H, cw = Math.max(minW, plotW / periods.length), T = pad + headH, B = Hs - pad - groupH - cfs - 8, barArea = s.timeline.bars.value ? B - T : 0;
        /* header: the selected range and a clear button */
        const first = periods.find(inRange), last = [...periods].reverse().find(inRange);
        const fmtP = (p: { label: string; group: string }) => (p.group ? `${p.label} ${p.group}` : p.label);
        el("text", { x: r1(pad), y: r1(pad + cfs + 2), "font-size": cfs + 1, fill: t.text, class: "ttl" }, labels, first && last ? (first === last ? fmtP(first) : `${fmtP(first)} – ${fmtP(last)}`) : c.msg("All_Periods", "All periods"));
        if (range) {
            const bx = Math.min(W, pad + plotW) - 16, cg = el("g", { class: "lg", style: "cursor:pointer" }, root);
            el("rect", { class: "hit", x: r1(bx - 4), y: r1(pad), width: 18, height: 18, rx: 4, fill: mix(t.text, t.surface, 0.92) }, cg);
            el("path", { d: `M${r1(bx)},${r1(pad + 4)}l10,10M${r1(bx + 10)},${r1(pad + 4)}l-10,10`, stroke: t.text, "stroke-width": 1.6, "stroke-linecap": "round" }, cg);
            cg.addEventListener("click", ev => { ev.stopPropagation(); tl.apply(null); });
        }
        let lastGroup = "";
        periods.forEach((p, k) => {
            const x = pad + cw * k, inside = inRange(p), items = p.rows.flatMap(r => r.cells.filter(z => z).map(z => (z as TCell).i));
            const g = el("g", { class: "mk" + (c.io.anyOn(items) || !items.length ? "" : " dim"), style: "cursor:pointer" }, marks);
            el("rect", { x: r1(x + 1), y: r1(T), width: r1(cw - 2), height: r1(B - T), rx: 3, fill: inside ? mix(sel, t.surface, 0.8) : mix(t.text, t.surface, 0.95) }, g);
            if (barArea > 4 && tot[k] > 0) { const h = Math.max(1, (B - T - 4) * tot[k] / mx); el("rect", { x: r1(x + cw * 0.22), y: r1(B - h), width: r1(cw * 0.56), height: r1(h), rx: 2, fill: inside || !range ? (look.flat ? sel : look.fill(sel, "v")) : mix(t.text, t.surface, 0.7) }, g); }
            el("text", { x: r1(x + cw / 2), y: r1(B + cfs + 4), "text-anchor": "middle", "font-size": cfs, fill: inside ? t.ink : cC, class: inside ? "ttl" : "ax" }, labels, trunc(p.label, cw - 2, cfs));
            if (p.group && p.group !== lastGroup) { el("text", { x: r1(x + 2), y: r1(B + cfs * 2 + 8), "font-size": Math.max(6, cfs - 1), fill: t.text, class: "ttl" }, labels, p.group); if (k > 0) el("line", { x1: r1(x) + 0.5, x2: r1(x) + 0.5, y1: r1(T), y2: r1(B + cfs * 2 + 8), stroke: t.grid }, root); lastGroup = p.group; }
            /* click picks a period, shift-click extends the range, clicking the only selected period clears */
            g.addEventListener("click", ev => {
                ev.stopPropagation();
                const a = p.start.getTime(), b = p.end.getTime(), me = ev as MouseEvent;
                if (range && (me.shiftKey || me.ctrlKey)) tl.apply({ from: Math.min(range.from, a), to: Math.max(range.to, b) });
                else if (range && range.from === a && range.to === b) tl.apply(null);
                else tl.apply({ from: a, to: b });
            });
            g.setAttribute("tabindex", "0"); g.setAttribute("role", "button"); g.setAttribute("aria-label", fmtP(p));
            g.addEventListener("keydown", ev => { const ke = ev as KeyboardEvent; if (ke.key === "Enter" || ke.key === " ") { ke.preventDefault(); g.dispatchEvent(new MouseEvent("click", { shiftKey: ke.shiftKey })); } });
        });
    }
}
