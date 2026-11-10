// KPI card: label, big value, sparkline, target line, delta vs comparison and a status pill.
import { el, svg } from "../dom";
import { parseFormat, fmt, deltaText } from "../format";
import { Tokens, Header, frame, emptyState } from "../theme";

export interface KpiModel {
    label: string;
    value: number | null;
    valueFormat?: string;
    target?: number | null;
    comparison?: number | null;
    spark?: (number | null)[];
    lowerIsBetter?: boolean;
    signedValue?: boolean;
    comparisonLabel?: string;   // "vs LY"
    targetLabel?: string;       // "Target"
    riskBand?: number;          // tolerance before "Off track" (ratio, points or relative)
}

type Status = "ok" | "risk" | "off";
const STATUS_TEXT: Record<Status, string> = { ok: "On track", risk: "At risk", off: "Off track" };

function statusOf(m: KpiModel, diff: number, kind: string, target: number): Status {
    const good = m.lowerIsBetter ? diff <= 0 : diff >= 0;
    if (good) return "ok";
    const band = m.riskBand ?? (kind === "points" ? 1.0 : kind === "absolute" ? 0.15 : 0.03);
    const size = kind === "absolute" ? Math.abs(diff) / Math.max(Math.abs(target), 1e-9) : Math.abs(diff);
    return size <= band ? "risk" : "off";
}

function icon(parent: Element, status: Status, t: Tokens): void {
    const s = svg("svg", { width: 13, height: 13, viewBox: "0 0 16 16", class: "gb-pill-icon" }, parent);
    if (status === "ok") {
        svg("circle", { cx: 8, cy: 8, r: 8, fill: t.good }, s);
        svg("path", { d: "M4.5 8.3l2.2 2.2 4.8-4.9", fill: "none", stroke: "#fff", "stroke-width": 1.8,
            "stroke-linecap": "round", "stroke-linejoin": "round" }, s);
    } else {
        const c = status === "risk" ? t.warn : t.bad;
        svg("path", { d: "M8 1.2 15.2 14.4H.8z", fill: c, "stroke-linejoin": "round" }, s);
        svg("rect", { x: 7.1, y: 5.6, width: 1.8, height: 4.6, rx: 0.9, fill: "#fff" }, s);
        svg("circle", { cx: 8, cy: 12.1, r: 1, fill: "#fff" }, s);
    }
}

function sparkline(parent: Element, values: (number | null)[], t: Tokens, w: number, h: number): void {
    const pts = values.map((v, i) => ({ v, i })).filter(p => p.v !== null && isFinite(p.v as number)) as
        { v: number; i: number }[];
    if (pts.length < 2) return;
    const s = svg("svg", { width: w, height: h, class: "gb-spark" }, parent);
    const lo = Math.min(...pts.map(p => p.v));
    const hi = Math.max(...pts.map(p => p.v));
    const n = values.length - 1 || 1;
    const x = (i: number) => 2 + (i / n) * (w - 6);
    const y = (v: number) => h - 3 - ((v - lo) / ((hi - lo) || 1)) * (h - 7);
    const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    svg("path", { d, fill: "none", stroke: t.primary, "stroke-width": 1.6, "stroke-linejoin": "round",
        "stroke-linecap": "round" }, s);
    const last = pts[pts.length - 1];
    svg("circle", { cx: x(last.i), cy: y(last.v), r: 2.8, fill: t.primary }, s);
}

export function renderKpi(root: HTMLElement, m: KpiModel, t: Tokens, header: Header = {}): void {
    if (m.value === null || m.value === undefined) {
        emptyState(root, t, "Add a measure to Value");
        return;
    }
    const f = frame(root, t, { showCard: header.showCard }, "gb-kpi");
    const nf = parseFormat(m.valueFormat);
    const box = el("div", "gb-kpi-box", f.body);

    const label = el("div", "gb-kpi-label", box);
    const [main, ...rest] = m.label.split(" · ");
    el("span", "", label, main);
    if (rest.length) el("span", "gb-kpi-label-muted", label, " · " + rest.join(" · "));

    const row = el("div", "gb-kpi-row", box);
    const valueText = fmt(m.value, nf, { compact: true, signed: m.signedValue });
    const valueEl = el("div", "gb-kpi-value", row, valueText);
    const size = Math.max(20, Math.min(32, f.height * 0.24, (f.width * 0.58) / Math.max(4, valueText.length) * 1.7));
    valueEl.style.fontSize = `${size}px`;
    if (m.spark && m.spark.length > 1) sparkline(row, m.spark, t, Math.max(56, Math.min(110, f.width * 0.36)), size + 6);

    const hasTarget = m.target !== null && m.target !== undefined;
    let status: Status | null = null;
    if (hasTarget) {
        const target = m.target as number;
        const kind = nf.kind === "percent" ? "points" : nf.suffix.trim() && nf.scale === 1 ? "absolute" : "relative";
        const d = deltaText(m.value, target, nf);
        const attain = kind === "relative" ? `${(m.value / (target || 1) * 100).toFixed(1)}%` : d.text;
        el("div", "gb-kpi-target", box,
            `${m.targetLabel || "Target"} ${fmt(target, nf, { compact: true, signed: m.signedValue })} · ${attain}`);
        status = statusOf(m, d.diff, kind, target);
    }

    const foot = el("div", "gb-kpi-foot", box);
    if (m.comparison !== null && m.comparison !== undefined) {
        const d = deltaText(m.value, m.comparison, nf);
        const good = m.lowerIsBetter ? d.diff <= 0 : d.diff >= 0;
        const delta = el("span", `gb-delta ${good ? "good" : "bad"}`, foot);
        el("span", "gb-delta-arrow", delta, d.diff >= 0 ? "▲" : "▼");
        el("span", "", delta, ` ${d.text} `);
        el("span", "gb-delta-label", delta, m.comparisonLabel || "vs LY");
    } else {
        el("span", "", foot);
    }
    if (status) {
        const pill = el("span", `gb-pill ${status}`, foot);
        icon(pill, status, t);
        el("span", "", pill, STATUS_TEXT[status]);
    }
}
