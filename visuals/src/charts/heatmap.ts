// Heatmap: rows x columns grid on a quiet->busy ramp; shows the peak cell's value (or index).
import { svg, text, measure, ramp } from "../dom";
import { parseFormat, fmt } from "../format";
import { Tokens, Header, Interactions, frame, emptyState, FONT, bind, dimmed } from "../theme";

export interface HeatmapModel {
    rows: string[];
    cols: string[];
    values: (number | null)[][];     // [row][col]
    keys?: unknown[][];
    format?: string;
    indexMode?: boolean;             // label values as an index where the peak = 100
    showValues?: "peak" | "all" | "none";
    legend?: { low?: string; high?: string };
    names?: { row?: string; col?: string; value?: string };
}

export function renderHeatmap(root: HTMLElement, m: HeatmapModel, t: Tokens, header: Header, ia: Interactions = {}): void {
    const flat = m.values.flat().filter(v => v !== null && v !== undefined && isFinite(v as number)) as number[];
    if (!m.rows.length || !m.cols.length || !flat.length) {
        emptyState(root, t, "Add rows, columns and a value");
        return;
    }
    const f = frame(root, t, header, "gb-heatmap");
    const nf = parseFormat(m.format);
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => ia.clear?.());

    const lo = Math.min(...flat), hi = Math.max(...flat);
    const stops = ["#FBF0E2", t.primaryLight, t.primary, t.primaryDark];
    const legend = { low: "Low", high: "High", ...(m.legend || {}) };
    const lw = 64, hiW = measure(legend.high, FONT(10, 400, t));
    const lx = W - hiW - 6 - lw;
    text(s, lx - 5, 10, legend.low, { "text-anchor": "end", "font-size": 10, fill: t.muted, "font-family": t.font });
    const grad = svg("linearGradient", { id: `gbhm${Math.random().toString(36).slice(2, 8)}` }, svg("defs", {}, s));
    stops.forEach((c, i) => svg("stop", { offset: `${(i / (stops.length - 1)) * 100}%`, "stop-color": c }, grad));
    svg("rect", { x: lx, y: 4, width: lw, height: 7, rx: 3.5, fill: `url(#${grad.getAttribute("id")})` }, s);
    text(s, W - hiW, 10, legend.high, { "font-size": 10, fill: t.muted, "font-family": t.font });

    const top = 18, bottom = 18;
    const left = Math.max(...m.rows.map(r => measure(r, FONT(11, 400, t)))) + 10;
    const cw = (W - left) / m.cols.length, ch = (H - top - bottom) / m.rows.length;
    const gap = Math.min(3, cw * 0.12, ch * 0.12);
    const every = Math.max(1, Math.ceil(24 / cw));
    m.cols.forEach((c, j) => {
        if (j % every === 0) text(s, left + cw * j + cw / 2, H - 4, c, { "text-anchor": "middle", "font-size": 10, fill: t.muted, "font-family": t.font });
    });
    let peak = { i: -1, j: -1, v: -Infinity };
    m.values.forEach((row, i) => row.forEach((v, j) => { if (v !== null && v > peak.v) peak = { i, j, v }; }));
    const names = { row: "Row", col: "Column", value: "Value", ...(m.names || {}) };
    const label = (v: number) => (m.indexMode ? String(Math.round((v / (hi || 1)) * 100)) : fmt(v, nf, { compact: true }));

    m.rows.forEach((r, i) => {
        const y = top + ch * i;
        text(s, left - 8, y + ch / 2 + 4, r, { "text-anchor": "end", "font-size": 11, fill: t.ink, "font-family": t.font });
        m.cols.forEach((c, j) => {
            const v = m.values[i]?.[j];
            if (v === null || v === undefined) return;
            const key = m.keys?.[i]?.[j];
            const fill = ramp(stops, (v - lo) / ((hi - lo) || 1));
            const g = svg("g", { opacity: dimmed(ia, key) ? 0.3 : 1, style: "cursor:pointer" }, s);
            svg("rect", { x: left + cw * j + gap / 2, y: y + gap / 2, width: Math.max(1, cw - gap), height: Math.max(1, ch - gap), rx: 2, fill }, g);
            const show = m.showValues === "all" || ((m.showValues ?? "peak") === "peak" && i === peak.i && j === peak.j);
            if (show && cw > 18 && ch > 12) {
                text(g, left + cw * j + cw / 2, y + ch / 2 + 4, label(v), { "text-anchor": "middle", "font-size": 11,
                    "font-weight": 700, fill: (v - lo) / ((hi - lo) || 1) > 0.55 ? "#fff" : t.ink, "font-family": t.font });
            }
            bind(g, ia, key, () => {
                const tip = [{ name: names.row, value: r }, { name: names.col, value: c }, { name: names.value, value: fmt(v, nf, { compact: true }) }];
                if (m.indexMode) tip.push({ name: "Index (peak = 100)", value: label(v) });
                return tip;
            });
        });
    });
}
