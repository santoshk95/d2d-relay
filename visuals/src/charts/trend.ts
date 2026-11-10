// Trend line: actual vs target (dashed) vs comparison (grey), end label and event annotations.
import { svg, text, measure } from "../dom";
import { parseFormat, fmt, fmtTick, niceTicks } from "../format";
import { Tokens, Header, Interactions, frame, emptyState, FONT, dimmed } from "../theme";

export interface TrendModel {
    categories: string[];
    keys?: unknown[];
    actual: (number | null)[];
    target?: (number | null)[];
    comparison?: (number | null)[];
    annotations?: (string | null)[];
    format?: string;
    labels?: { actual?: string; target?: string; comparison?: string };
    showAllAnnotations?: boolean;
}

export function renderTrend(root: HTMLElement, m: TrendModel, t: Tokens, header: Header, ia: Interactions = {}): void {
    const series = [m.actual, m.target || [], m.comparison || []];
    const all = series.flat().filter(v => v !== null && v !== undefined && isFinite(v as number)) as number[];
    if (!m.categories.length || !all.length) {
        emptyState(root, t, "Add an axis and an Actual measure");
        return;
    }
    const f = frame(root, t, header, "gb-trend");
    const nf = parseFormat(m.format);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => ia.clear?.());

    // legend (top right)
    const labels = { actual: "Actual", target: "Target", comparison: "Last year", ...(m.labels || {}) };
    const legend: [string, string, string | undefined][] = [[labels.actual, t.primary, undefined]];
    if (m.target?.some(v => v !== null)) legend.push([labels.target, t.target, "4 3"]);
    if (m.comparison?.some(v => v !== null)) legend.push([labels.comparison, t.comparison, undefined]);
    let lx = W;
    for (let i = legend.length - 1; i >= 0; i--) {
        const [name, color, dash] = legend[i];
        lx -= measure(name, FONT(11, 400, t)) + 4;
        text(s, lx, 9, name, { "font-size": 11, fill: t.muted, "font-family": t.font });
        lx -= 22;
        svg("line", { x1: lx, x2: lx + 16, y1: 5.5, y2: 5.5, stroke: color, "stroke-width": 2, "stroke-dasharray": dash }, s);
        lx -= 12;
    }

    // scales
    const ticks = niceTicks(Math.min(...all), Math.max(...all), 5);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const step = ticks.length > 1 ? ticks[1] - ticks[0] : 1;
    const tickLabels = ticks.map(v => fmtTick(v, nf, step));
    const lastIdx = m.actual.reduce((acc: number, v, i) => (v !== null ? i : acc), -1);
    const endLabel = lastIdx >= 0 ? fmt(m.actual[lastIdx], nf, { compact: true }) : "";
    const left = Math.max(...tickLabels.map(l => measure(l, FONT(10, 400, t)))) + 8;
    const right = measure(endLabel, FONT(11, 700, t)) + 10;
    const top = 24, bottom = 20;
    const pw = Math.max(10, W - left - right), ph = Math.max(10, H - top - bottom);
    const n = m.categories.length;
    const x = (i: number) => left + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
    const y = (v: number) => top + ph - ((v - lo) / ((hi - lo) || 1)) * ph;

    ticks.forEach((v, i) => {
        svg("line", { x1: left, x2: left + pw, y1: y(v), y2: y(v), stroke: t.grid, "stroke-width": 1 }, s);
        text(s, left - 6, y(v) + 3.5, tickLabels[i], { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
    });
    const labelEvery = Math.max(1, Math.ceil((measure("Mmm", FONT(10, 400, t)) + 10) / (pw / Math.max(1, n - 1) || pw)));
    m.categories.forEach((c, i) => {
        if (i % labelEvery === 0 || i === n - 1) {
            text(s, x(i), H - 4, c, { "text-anchor": "middle", "font-size": 10, fill: t.muted, "font-family": t.font });
        }
    });

    const path = (vals: (number | null)[]) => {
        let d = "", pen = false;
        vals.forEach((v, i) => {
            if (v === null || v === undefined || !isFinite(v)) { pen = false; return; }
            d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
            pen = true;
        });
        return d;
    };
    if (m.comparison) svg("path", { d: path(m.comparison), fill: "none", stroke: t.comparison, "stroke-width": 2, "stroke-linejoin": "round" }, s);
    if (m.target) svg("path", { d: path(m.target), fill: "none", stroke: t.target, "stroke-width": 1.6, "stroke-dasharray": "5 4" }, s);
    svg("path", { d: path(m.actual), fill: "none", stroke: t.primary, "stroke-width": 2.6, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
    m.actual.forEach((v, i) => {
        if (v === null) return;
        const key = m.keys?.[i];
        svg("circle", { cx: x(i), cy: y(v), r: i === lastIdx ? 4 : 2.4, fill: t.primary,
            opacity: dimmed(ia, key) ? 0.3 : 1 }, s);
    });
    if (lastIdx >= 0) {
        text(s, x(lastIdx) + 7, y(m.actual[lastIdx] as number) + 4, endLabel,
            { "font-size": 11, "font-weight": 700, fill: t.primaryDark, "font-family": t.font });
    }

    // annotations (events): the latest one by default
    const ann = (m.annotations || []).map((a, i) => ({ a, i })).filter(p => p.a && m.actual[p.i] !== null);
    for (const p of m.showAllAnnotations ? ann : ann.slice(-1)) {
        const vy = y(m.actual[p.i] as number);
        const w = measure(p.a as string, FONT(11, 600, t));
        const tx = Math.min(x(p.i) - 4, left + pw - 2);
        const ty = Math.max(top + 2, vy - 12);
        text(s, Math.max(left + w, tx), ty, p.a as string, { "text-anchor": "end", "font-size": 11, "font-weight": 600,
            fill: t.ink, "font-family": t.font });
    }

    // hover / click columns
    const guide = svg("line", { y1: top, y2: top + ph, stroke: t.faint, "stroke-width": 1, opacity: 0 }, s);
    const colW = n > 1 ? pw / (n - 1) : pw;
    m.categories.forEach((c, i) => {
        const r = svg("rect", { x: x(i) - colW / 2, y: top, width: colW, height: ph, fill: "transparent", style: "cursor:pointer" }, s);
        const key = m.keys?.[i];
        r.addEventListener("mousemove", (e) => {
            guide.setAttribute("x1", String(x(i)));
            guide.setAttribute("x2", String(x(i)));
            guide.setAttribute("opacity", "1");
            const items = [{ name: "Period", value: c }, { name: labels.actual, value: fmt(m.actual[i], nf, { compact: true }) }];
            if (m.target) items.push({ name: labels.target, value: fmt(m.target[i], nf, { compact: true }) });
            if (m.comparison) items.push({ name: labels.comparison, value: fmt(m.comparison[i], nf, { compact: true }) });
            ia.tooltip?.(e as MouseEvent, items, key);
        });
        r.addEventListener("mouseleave", () => { guide.setAttribute("opacity", "0"); ia.tooltip?.(null, []); });
        r.addEventListener("click", (e) => {
            e.stopPropagation();
            const ev = e as MouseEvent;
            ia.select?.(key, ev.ctrlKey || ev.metaKey);
        });
        r.addEventListener("contextmenu", (e) => { e.preventDefault(); ia.contextMenu?.(e as MouseEvent, key); });
    });
}
