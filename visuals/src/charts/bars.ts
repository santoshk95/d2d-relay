// Driver bars: diverging horizontal bars (positive = primary, negative = blue) with signed labels.
import { svg, text, measure, fit } from "../dom";
import { parseFormat, fmt } from "../format";
import { Tokens, Header, Interactions, frame, emptyState, FONT, bind, dimmed } from "../theme";

export interface BarRow {
    label: string;
    value: number | null;
    key?: unknown;
}

export interface BarsModel {
    rows: BarRow[];
    format?: string;
    signed?: boolean;            // "+$16.3M" style labels (default true)
    sort?: "none" | "desc" | "asc";
}

export function renderBars(root: HTMLElement, m: BarsModel, t: Tokens, header: Header, ia: Interactions = {}): void {
    let rows = m.rows.filter(r => r.value !== null && r.value !== undefined && isFinite(r.value as number));
    if (!rows.length) {
        emptyState(root, t, "Add a category and a value");
        return;
    }
    if (m.sort === "desc") rows = [...rows].sort((a, b) => (b.value as number) - (a.value as number));
    if (m.sort === "asc") rows = [...rows].sort((a, b) => (a.value as number) - (b.value as number));
    const f = frame(root, t, header, "gb-bars");
    const nf = parseFormat(m.format);
    const signed = m.signed !== false;
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);
    s.addEventListener("click", () => ia.clear?.());

    const labelFont = FONT(12, 400, t), valueFont = FONT(11, 700, t);
    const labelW = Math.min(W * 0.42, Math.max(...rows.map(r => measure(r.label, labelFont))) + 14);
    const vals = rows.map(r => r.value as number);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const texts = rows.map(r => fmt(r.value, nf, { compact: true, signed }));
    const posW = Math.max(0, ...rows.map((r, i) => ((r.value as number) >= 0 ? measure(texts[i], valueFont) : 0))) + 6;
    const negW = Math.max(0, ...rows.map((r, i) => ((r.value as number) < 0 ? measure(texts[i], valueFont) : 0))) + 6;
    const x0 = labelW + (lo < 0 ? negW : 0);
    const x1 = W - (hi > 0 ? posW : 4);
    const sx = (v: number) => x0 + ((v - lo) / ((hi - lo) || 1)) * Math.max(10, x1 - x0);
    const rowH = H / rows.length;
    const barH = Math.max(6, Math.min(16, rowH * 0.5));

    rows.forEach((r, i) => {
        const v = r.value as number;
        const cy = rowH * i + rowH / 2;
        const g = svg("g", { opacity: dimmed(ia, r.key) ? 0.35 : 1, style: "cursor:pointer" }, s);
        svg("rect", { x: 0, y: rowH * i, width: W, height: rowH, fill: "transparent" }, g);
        text(g, labelW - 12, cy + 4, fit(r.label, labelFont, labelW - 14),
            { "text-anchor": "end", "font-size": 12, fill: t.ink, "font-family": t.font });
        const a = sx(Math.min(0, v)), b = sx(Math.max(0, v));
        svg("rect", { x: a, y: cy - barH / 2, width: Math.max(1, b - a), height: barH, rx: 2,
            fill: v >= 0 ? t.primary : t.negative }, g);
        text(g, v >= 0 ? b + 5 : a - 5, cy + 4, texts[i], { "text-anchor": v >= 0 ? "start" : "end",
            "font-size": 11, "font-weight": 700, fill: t.ink, "font-family": t.font });
        bind(g, ia, r.key, () => [{ name: r.label, value: fmt(v, nf, { compact: true, signed }) }]);
    });
}
