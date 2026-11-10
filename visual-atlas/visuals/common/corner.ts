/*
 * The top-right corner of a visual: the Reset zoom button, the drill
 * buttons and the selection marker sit side by side in one flex row, so
 * they never cover each other or the chart's own labels.
 */
import { el } from "./look";

/** what a click on a corner element does (set on every render) */
const acts = new WeakMap<HTMLElement, () => void>();

/** the corner row of a visual's element (created on first use, kept above the SVG) */
export function corner(root: HTMLElement): HTMLDivElement {
    let c: HTMLDivElement | null = null;
    for (let n = root.firstElementChild; n; n = n.nextElementSibling) if (n.classList.contains("atl-corner")) c = n as HTMLDivElement;
    if (!c) { c = document.createElement("div"); c.className = "atl-corner"; }
    if (c !== root.lastElementChild) root.appendChild(c);
    return c;
}
function find<T extends HTMLElement>(c: HTMLElement, cls: string): T | null {
    for (let n = c.firstElementChild; n; n = n.nextElementSibling) if (n.classList.contains(cls)) return n as T;
    return null;
}

/** a labelled "Reset zoom" button, shown while the visual is zoomed in */
export function resetButton(root: HTMLElement, show: boolean, label: string, act: () => void) {
    const c = corner(root);
    let b = find<HTMLButtonElement>(c, "atl-reset");
    if (!b) {
        b = document.createElement("button"); b.type = "button"; b.className = "atl-reset";
        const svg = el("svg", { width: 14, height: 14, viewBox: "0 0 16 16", "aria-hidden": "true" }, b);
        el("path", { d: "M3.2 8a4.8 4.8 0 1 0 1.5-3.5M3 2.6v2.6h2.6", fill: "none", stroke: "currentColor", "stroke-width": 1.7, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
        const s = document.createElement("span"); b.appendChild(s);
        b.addEventListener("click", ev => { ev.stopPropagation(); const f = acts.get(b as HTMLElement); if (f) f(); });
        c.appendChild(b);
    }
    (b.lastChild as HTMLElement).textContent = label;
    b.title = label; b.setAttribute("aria-label", label);
    acts.set(b, act);
    b.style.display = show ? "" : "none";
}

export interface MarkState {
    /** sel: something is selected in this visual; filter: this visual applies a filter; hl: another visual highlights this one */
    kind: "sel" | "filter" | "hl";
    color: string;
    title: string;
    /** clicking the marker clears it (selection or filter); none for highlights */
    clear?: () => void;
}
/** the selection marker: a small colored * while the visual is selected, filtering or highlighted */
export function selMark(root: HTMLElement, st: MarkState | null) {
    const c = corner(root);
    let m = find<HTMLSpanElement>(c, "atl-mark");
    if (!m) {
        m = document.createElement("span"); m.className = "atl-mark"; m.textContent = "*";
        m.addEventListener("click", ev => { const f = acts.get(m as HTMLElement); if (f) { ev.stopPropagation(); f(); } });
        m.addEventListener("keydown", ev => { const k = ev.key, f = acts.get(m as HTMLElement); if (f && (k === "Enter" || k === " ")) { ev.preventDefault(); f(); } });
        c.appendChild(m);
    }
    root.classList.toggle("atl-marked", !!st);
    if (!st) { m.style.display = "none"; return; }
    m.style.display = ""; m.style.color = st.color;
    m.className = "atl-mark atl-mark-" + st.kind;
    const tip = st.clear ? `${st.title} (click to clear)` : st.title;
    m.title = tip; m.setAttribute("aria-label", tip);
    if (st.clear) acts.set(m, st.clear); else acts.delete(m);
    if (st.clear) { m.setAttribute("role", "button"); m.setAttribute("tabindex", "0"); } else { m.removeAttribute("role"); m.removeAttribute("tabindex"); }
}
