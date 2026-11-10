// Browser bundle for HTML prototypes: the same renderers the Power BI visuals use.
import { DEFAULT_TOKENS, Interactions, Tokens } from "./theme";
import { renderKpi } from "./charts/kpi";
import { renderTrend } from "./charts/trend";
import { renderBars } from "./charts/bars";
import { renderQuadrant } from "./charts/quadrant";
import { renderTreemap } from "./charts/treemap";
import { renderHeatmap } from "./charts/heatmap";
import { renderFunnel } from "./charts/funnel";
import { renderNarrative } from "./charts/narrative";

/** Simple prototype interactions: hover tooltip and click-to-select (dims the rest). */
function interactions(rerender: () => void): Interactions {
    let tip: HTMLDivElement | null = null;
    let selected: unknown[] = [];
    return {
        select(key, multi) {
            const has = selected.includes(key);
            selected = multi ? (has ? selected.filter(k => k !== key) : [...selected, key]) : has && selected.length === 1 ? [] : [key];
            rerender();
        },
        clear() { if (selected.length) { selected = []; rerender(); } },
        hasSelection: () => selected.length > 0,
        isActive: (key) => selected.includes(key),
        tooltip(ev, items) {
            if (!ev) { tip?.remove(); tip = null; return; }
            if (!tip) { tip = document.createElement("div"); tip.className = "gb-tooltip"; document.body.appendChild(tip); }
            tip.innerHTML = items.map(i => (i.name ? `${i.name}: <b>${i.value}</b>` : `<b>${i.value}</b>`)).join("<br>");
            tip.style.left = `${ev.clientX + 14}px`;
            tip.style.top = `${ev.clientY + 12}px`;
        },
    };
}

const RENDERERS: Record<string, (root: HTMLElement, model: any, t: Tokens, header: any, ia: Interactions) => void> = {
    kpiCard: (r, m, t, h) => renderKpi(r, m, t, h),
    trendLine: renderTrend,
    driverBars: renderBars,
    quadrant: renderQuadrant,
    treemap: renderTreemap,
    heatmap: renderHeatmap,
    funnel: renderFunnel,
    narrative: (r, m, t, h) => renderNarrative(r, m, t, h),
};

/** Render one visual into an element; re-renders itself on selection. */
function render(type: string, root: HTMLElement, model: unknown, header: unknown = {}, tokens: Partial<Tokens> = {}): void {
    const t = { ...DEFAULT_TOKENS, ...tokens };
    const fn = RENDERERS[type];
    if (!fn) throw new Error(`Unknown visual type ${type}`);
    const draw = () => fn(root, model, t, header, ia);
    const ia = interactions(draw);
    draw();
    new ResizeObserver(() => draw()).observe(root);
}

(window as any).GenBIVisuals = { render, DEFAULT_TOKENS, types: Object.keys(RENDERERS) };
