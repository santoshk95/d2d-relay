/*
 * Atlas looks: flat, soft (gradients, glossy dots, soft shadows) and 3D
 * (stronger shadows; renderers add extruded faces). Gradients and
 * filters live in the visual's own <defs> and are created on demand.
 */
import { mix } from "./color";

export const SVGNS = "http://www.w3.org/2000/svg";
export type Attrs = Record<string, string | number | undefined | null>;
/** create an SVG element; attributes and text are set as data, never parsed as markup */
export function el<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Attrs, parent?: Element | null, text?: string): SVGElementTagNameMap[K] {
    const e = document.createElementNS(SVGNS, tag) as SVGElementTagNameMap[K];
    for (const k in attrs) { const v = attrs[k]; if (v !== undefined && v !== null) e.setAttribute(k, String(v)); }
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
}
export function clear(node: Element) { while (node.firstChild) node.removeChild(node.firstChild); }
export const r1 = (v: number) => Math.round(v * 10) / 10;
export const FONT_STACK = "'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif";
let FONT = FONT_STACK;
/** font used to measure text (the Style card's font); the visual sets the same font on its root element */
export function setFont(family: string) { const f = family && family.trim() ? family : FONT_STACK; if (f !== FONT) { FONT = f; WIDTHS.clear(); } }
let CTX: CanvasRenderingContext2D | null | undefined;
const WIDTHS = new Map<string, number>();
/** text width for layout decisions, measured on a canvas in the visual's font (semibold, so it is never short) */
export function textW(text: string, size: number): number {
    const s = String(text), key = size + "|" + s, hit = WIDTHS.get(key);
    if (hit !== undefined) return hit;
    if (CTX === undefined) { try { CTX = document.createElement("canvas").getContext("2d"); } catch (e) { CTX = null; } }
    let w = s.length * size * 0.58;
    if (CTX) { CTX.font = `600 ${size}px ${FONT}`; w = CTX.measureText(s).width; }
    if (WIDTHS.size > 20000) WIDTHS.clear();
    WIDTHS.set(key, w); return w;
}
/** shorten a label with an ellipsis so it fits a width */
export function trunc(text: string, w: number, size: number): string {
    const s = String(text); if (textW(s, size) <= w) return s;
    let lo = 0, hi = s.length;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (textW(s.slice(0, mid) + "…", size) <= w) lo = mid; else hi = mid - 1; }
    return lo > 0 ? s.slice(0, lo).trimEnd() + "…" : s.slice(0, 1) + "…";
}

export type LookName = "flat" | "soft" | "3d";
export class Look {
    name: LookName = "soft";
    private defs: SVGDefsElement;
    private cache = new Map<string, string>();
    private n = 0;
    constructor(defs: SVGDefsElement, private pfx: string) { this.defs = defs; }
    reset(name: LookName, shadow: string, strength: number) {
        this.name = name; clear(this.defs); this.cache.clear(); this.n = 0;
        const s = Math.max(0, Math.min(100, strength)) / 100;
        const f = (id: string, dx: number, dy: number, sd: number, op: number) => {
            const flt = el("filter", { id: this.pfx + id, x: "-20%", y: "-20%", width: "140%", height: "150%", "color-interpolation-filters": "sRGB" }, this.defs);
            el("feDropShadow", { dx, dy, stdDeviation: sd, "flood-color": shadow, "flood-opacity": op }, flt);
        };
        f("sh", 0, 2.4, 2.4, 0.22 * s + 0.04);
        f("sh3", 2.5, 5, 3.6, 0.32 * s + 0.06);
        const g = el("filter", { id: this.pfx + "glow", x: "-10%", y: "-40%", width: "120%", height: "200%", "color-interpolation-filters": "sRGB" }, this.defs);
        el("feGaussianBlur", { in: "SourceGraphic", stdDeviation: 2.8, result: "b" }, g);
        el("feOffset", { in: "b", dy: 4, result: "o" }, g);
        const ct = el("feComponentTransfer", { in: "o", result: "t" }, g); el("feFuncA", { type: "linear", slope: 0.42 * s }, ct);
        const mg = el("feMerge", {}, g); el("feMergeNode", { in: "t" }, mg); el("feMergeNode", { in: "SourceGraphic" }, mg);
    }
    get flat() { return this.name === "flat"; }
    get is3d() { return this.name === "3d"; }
    /** fill for a mark: vertical (v), horizontal (h) or radial (r) gradient in soft and 3D, the plain color in flat */
    fill(color: string, dir: "v" | "h" | "r" = "v"): string {
        if (this.name === "flat" || !/^#[0-9a-f]{6}$/i.test(color)) return color;
        const key = dir + color; const hit = this.cache.get(key); if (hit) return hit;
        const id = this.pfx + "g" + (this.n++);
        if (dir === "r") {
            const rg = el("radialGradient", { id, cx: 0.38, cy: 0.32, r: 0.78, fx: 0.3, fy: 0.22 }, this.defs);
            el("stop", { offset: 0, "stop-color": mix(color, "#ffffff", 0.62) }, rg);
            el("stop", { offset: 0.5, "stop-color": color }, rg);
            el("stop", { offset: 1, "stop-color": mix(color, "#000000", 0.32) }, rg);
        } else {
            const lg = el("linearGradient", dir === "v" ? { id, x1: 0, y1: 0, x2: 0, y2: 1 } : { id, x1: 1, y1: 0, x2: 0, y2: 0 }, this.defs);
            el("stop", { offset: 0, "stop-color": mix(color, "#ffffff", 0.36) }, lg);
            el("stop", { offset: 0.55, "stop-color": color }, lg);
            el("stop", { offset: 1, "stop-color": mix(color, "#000000", 0.18) }, lg);
        }
        const url = `url(#${id})`; this.cache.set(key, url); return url;
    }
    /** gradient running along a link from one color to another (user space) */
    linkGradient(a: string, b: string, x0: number, x1: number): string {
        const id = this.pfx + "l" + (this.n++);
        const lg = el("linearGradient", { id, gradientUnits: "userSpaceOnUse", x1: x0, x2: x1, y1: 0, y2: 0 }, this.defs);
        el("stop", { offset: 0, "stop-color": a }, lg); el("stop", { offset: 1, "stop-color": b }, lg);
        return `url(#${id})`;
    }
    side = (c: string) => mix(c, "#000000", 0.34);
    top = (c: string) => mix(c, "#ffffff", 0.38);
    /** filter for a group of marks: soft shadow, deeper 3D shadow, or none */
    shadow(): string | null { return this.name === "soft" ? `url(#${this.pfx}sh)` : this.name === "3d" ? `url(#${this.pfx}sh3)` : null; }
    glow(): string | null { return this.name === "flat" ? null : `url(#${this.pfx}glow)`; }
}
