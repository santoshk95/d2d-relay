// Funnel: one centred bar per stage (measure), value and % of the first stage.
import { svg, text, measure, ramp } from "../dom";
import { parseFormat, fmt } from "../format";
import { Tokens, Header, Interactions, frame, emptyState, FONT } from "../theme";

export interface FunnelModel {
    stages: { label: string; value: number | null; format?: string }[];
}

export function renderFunnel(root: HTMLElement, m: FunnelModel, t: Tokens, header: Header, ia: Interactions = {}): void {
    const stages = m.stages.filter(s => s.value !== null && s.value !== undefined && isFinite(s.value as number));
    if (!stages.length) {
        emptyState(root, t, "Add two or more stage measures");
        return;
    }
    const f = frame(root, t, header, "gb-funnel");
    const W = f.width, H = f.height;
    const s = svg("svg", { width: W, height: H }, f.body);

    const first = stages[0].value as number;
    const max = Math.max(...stages.map(st => st.value as number));
    const labelW = Math.max(...stages.map(st => measure(st.label, FONT(12, 400, t)))) + 16;
    const vals = stages.map(st => fmt(st.value, parseFormat(st.format), { compact: true }));
    const valW = Math.max(...vals.map(v => measure(v, FONT(12, 700, t)))) + 18;
    const pctW = measure("100.0%", FONT(11, 400, t)) + 6;
    const area = Math.max(20, W - labelW - valW - pctW);
    const rowH = H / stages.length;
    const barH = Math.max(8, Math.min(22, rowH * 0.62));

    stages.forEach((st, i) => {
        const v = st.value as number;
        const cy = rowH * i + rowH / 2;
        const bw = Math.max(3, (v / (max || 1)) * area);
        const g = svg("g", {}, s);
        text(g, labelW - 12, cy + 4, st.label, { "text-anchor": "end", "font-size": 12, fill: t.ink, "font-family": t.font });
        svg("rect", { x: labelW + (area - bw) / 2, y: cy - barH / 2, width: bw, height: barH, rx: 3,
            fill: ramp([t.primary, t.primaryDark], stages.length > 1 ? i / (stages.length - 1) : 0) }, g);
        text(g, labelW + area + 10, cy + 4, vals[i], { "font-size": 12, "font-weight": 700, fill: t.ink, "font-family": t.font });
        const pct = first ? v / first : 0;
        text(g, W, cy + 4, pct >= 0.9995 ? "100%" : `${(pct * 100).toFixed(1)}%`,
            { "text-anchor": "end", "font-size": 11, fill: t.muted, "font-family": t.font });
        g.addEventListener("mousemove", (e) => ia.tooltip?.(e as MouseEvent, [
            { name: "Stage", value: st.label }, { name: "Value", value: vals[i] },
            { name: "% of first", value: `${(pct * 100).toFixed(1)}%` },
            ...(i ? [{ name: "% of previous", value: `${((v / ((stages[i - 1].value as number) || 1)) * 100).toFixed(1)}%` }] : []),
        ]));
        g.addEventListener("mouseleave", () => ia.tooltip?.(null, []));
    });
}
