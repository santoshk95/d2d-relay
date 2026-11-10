// Narrative panel: numbered insights (from text measures), a "how to" list, or a step timeline.
import { el, svg } from "../dom";
import { Tokens, Header, frame } from "../theme";

export interface NarrativeModel {
    heading?: string;          // small caps heading, e.g. "KEY INSIGHTS"
    note?: string;             // muted text after the heading
    items: string[];
    style?: "numbered" | "list" | "timeline";
}

/** Light markup: **bold** segments. */
function rich(parent: HTMLElement, value: string): void {
    value.split(/(\*\*[^*]+\*\*)/g).forEach(part => {
        if (!part) return;
        if (part.startsWith("**") && part.endsWith("**")) el("b", "", parent, part.slice(2, -2));
        else parent.appendChild(document.createTextNode(part));
    });
}

export function renderNarrative(root: HTMLElement, m: NarrativeModel, t: Tokens, header: Header = {}): void {
    const style = m.style || "numbered";
    const f = frame(root, t, { showCard: header.showCard }, `gb-narrative gb-${style}`);
    if (m.heading) {
        const h = el("div", "gb-nar-head", f.body);
        if (style !== "timeline") {
            const ic = svg("svg", { width: 14, height: 14, viewBox: "0 0 16 16", class: "gb-nar-icon" }, h);
            if (style === "numbered") {
                svg("path", { d: "M8 1.5a4.5 4.5 0 0 0-2.6 8.2V12h5.2V9.7A4.5 4.5 0 0 0 8 1.5zM5.9 13.3h4.2M6.6 14.8h2.8",
                    fill: "none", stroke: t.primary, "stroke-width": 1.4, "stroke-linecap": "round" }, ic);
            } else {
                svg("rect", { x: 2, y: 2, width: 12, height: 12, rx: 2.5, fill: "none", stroke: t.primary, "stroke-width": 1.4 }, ic);
                svg("path", { d: "M5 6h6M5 8.5h6M5 11h4", stroke: t.primary, "stroke-width": 1.3, "stroke-linecap": "round" }, ic);
            }
        }
        el("span", "gb-nar-title", h, m.heading);
        if (m.note) el("span", "gb-nar-note", h, ` · ${m.note}`);
    }
    const items = m.items.filter(s => s && s.trim());
    const list = el("div", "gb-nar-list", f.body);
    items.forEach((item, i) => {
        const row = el("div", "gb-nar-item", list);
        if (style === "timeline") {
            const [title, date, owner] = item.split("|").map(p => p.trim());
            el("span", "gb-nar-badge", row, String(i + 1).padStart(2, "0"));
            const txt = el("div", "gb-nar-step", row);
            const top = el("div", "", txt);
            el("b", "", top, title || "");
            if (date) el("span", "gb-nar-muted", top, ` · ${date}`);
            if (owner) el("div", "gb-nar-muted", txt, owner);
            return;
        }
        if (style === "numbered") el("span", "gb-nar-num", row, String(i + 1));
        else {
            const ic = svg("svg", { width: 12, height: 12, viewBox: "0 0 12 12", class: "gb-nar-bullet" }, row);
            svg("path", { d: "M2 1.5 10 6 2 10.5z", fill: "none", stroke: t.primary, "stroke-width": 1.3, "stroke-linejoin": "round" }, ic);
        }
        rich(el("div", "gb-nar-text", row), item);
    });
}
