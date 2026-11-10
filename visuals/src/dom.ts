// Tiny DOM/SVG helpers (no d3: keeps every visual small and dependency-free).

export const SVG_NS = "http://www.w3.org/2000/svg";

export function el<K extends keyof HTMLElementTagNameMap>(
    tag: K, cls?: string, parent?: Element, text?: string): HTMLElementTagNameMap[K] {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
}

export function svg(tag: string, attrs: Record<string, string | number | undefined>, parent?: Element): SVGElement {
    const e = document.createElementNS(SVG_NS, tag) as SVGElement;
    for (const k of Object.keys(attrs)) {
        const v = attrs[k];
        if (v !== undefined) e.setAttribute(k, String(v));
    }
    if (parent) parent.appendChild(e);
    return e;
}

export function text(parent: Element, x: number, y: number, value: string,
    attrs: Record<string, string | number | undefined> = {}): SVGElement {
    const t = svg("text", { x, y, ...attrs }, parent);
    t.textContent = value;
    return t;
}

export function clear(e: Element): void {
    while (e.firstChild) e.removeChild(e.firstChild);
}

let ctx: CanvasRenderingContext2D | null = null;

/** Width of a string in px for a CSS font like "600 12px Segoe UI". */
export function measure(value: string, font: string): number {
    if (!ctx) ctx = document.createElement("canvas").getContext("2d");
    if (!ctx) return value.length * 7;
    ctx.font = font;
    return ctx.measureText(value).width;
}

/** Shorten a label with an ellipsis so it fits maxWidth. */
export function fit(value: string, font: string, maxWidth: number): string {
    if (measure(value, font) <= maxWidth) return value;
    let s = value;
    while (s.length > 1 && measure(s + "…", font) > maxWidth) s = s.slice(0, -1);
    return s.length > 1 ? s + "…" : "";
}

export function hexToRgb(hex: string): [number, number, number] {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Interpolate along a colour ramp (t in 0..1). */
export function ramp(stops: string[], t: number): string {
    const x = Math.max(0, Math.min(1, isFinite(t) ? t : 0)) * (stops.length - 1);
    const i = Math.min(stops.length - 2, Math.floor(x));
    const f = x - i;
    const a = hexToRgb(stops[i]);
    const b = hexToRgb(stops[i + 1]);
    const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function isDark(color: string): boolean {
    const m = color.match(/\d+/g);
    const [r, g, b] = color.startsWith("#") ? hexToRgb(color) : (m || ["0", "0", "0"]).map(Number);
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.58;
}
