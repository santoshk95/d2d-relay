/*
 * Atlas color engine: OKLab/OKLCH math, brand palette generation and
 * readability checks. Shared by every Atlas visual.
 */
export type RGB = [number, number, number];

const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const gam = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(Math.max(c, 0), 1 / 2.4) - 0.055);

export function hex2rgb(h: string): RGB {
    h = String(h).trim().replace("#", "");
    if (h.length === 3) h = h.split("").map(c => c + c).join("");
    const n = parseInt(h.slice(0, 6), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
function labLin([r, g, b]: RGB): RGB {
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function lab2rgb([L, a, b]: RGB): RGB {
    const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3), m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3), s = Math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3);
    return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
}
const toHex = (rl: RGB) => "#" + rl.map(v => Math.round(Math.max(0, Math.min(1, gam(v))) * 255).toString(16).padStart(2, "0")).join("");
export const isHex = (h: string) => /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(h || "").trim());
export const normHex = (h: string) => { h = String(h).trim(); if (!h.startsWith("#")) h = "#" + h; if (h.length === 4) h = "#" + h.slice(1).split("").map(c => c + c).join(""); return h.toLowerCase(); };
export function lch(hex: string): RGB { const [L, a, b] = labLin(hex2rgb(hex).map(lin) as RGB); return [L, Math.hypot(a, b), (Math.atan2(b, a) * 180 / Math.PI + 360) % 360]; }
/** OKLCH to hex, reducing chroma until the color fits in sRGB */
export function hexOf(L: number, C: number, h: number): string {
    L = Math.max(0, Math.min(1, L)); let c = Math.max(0, C), rl: RGB = [0, 0, 0];
    for (let i = 0; i < 48; i++) { const hr = h * Math.PI / 180; rl = lab2rgb([L, c * Math.cos(hr), c * Math.sin(hr)]); if (rl.every(v => v >= -0.0004 && v <= 1.0004)) break; c *= 0.93; }
    return toHex(rl);
}
/** mix two colors in OKLab; t = 0 gives a, 1 gives b */
export function mix(a: string, b: string, t: number): string {
    const A = labLin(hex2rgb(a).map(lin) as RGB), B = labLin(hex2rgb(b).map(lin) as RGB);
    return toHex(lab2rgb(A.map((v, i) => v + (B[i] - v) * t) as RGB));
}
export function luminance(hex: string): number { const [r, g, b] = hex2rgb(hex).map(lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
export function contrast(a: string, b: string): number { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
/** text color (white or near-black) that reads best on a fill */
export const inkOn = (hex: string) => (contrast(hex, "#ffffff") >= contrast(hex, "#141414") * 0.82 ? "#ffffff" : "#141414");

/* ---- separation checks: OKLab distance under normal vision and protan/deutan simulation (Machado 2009) ---- */
const CVD = [[[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]], [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]]];
const dE = (a: RGB, b: RGB) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * 100;
const LABC = new Map<string, RGB[]>();
function labs(hex: string): RGB[] {
    let v = LABC.get(hex);
    if (!v) { const l = hex2rgb(hex).map(lin) as RGB; v = [labLin(l), ...CVD.map(M => labLin(M.map(r => Math.max(0, Math.min(1, r[0] * l[0] + r[1] * l[1] + r[2] * l[2]))) as RGB))]; LABC.set(hex, v); }
    return v;
}
export function separation(a: string, b: string) { const A = labs(a), B = labs(b); return { n: dE(A[0], B[0]), c: Math.min(dE(A[1], B[1]), dE(A[2], B[2])) }; }

/** keep categorical colors in readable lightness bands: light surface L .43-.77, dark surface L .48-.67 */
export function adapt(hex: string, dark: boolean): string {
    const [L, C, h] = lch(hex);
    if (dark) { if (L < 0.48) return hexOf(Math.min(0.62, Math.max(0.52, L + 0.2)), C * 1.04, h); if (L > 0.67) return hexOf(0.65, C, h); return hex; }
    if (L > 0.77) return hexOf(0.74, C < 0.03 ? C : Math.max(C, 0.06), h); if (L < 0.43) return hexOf(0.45, C, h); return hex;
}
function sep2(a: string, b: string) { const x = separation(adapt(a, false), adapt(b, false)), y = separation(adapt(a, true), adapt(b, true)); return { n: Math.min(x.n, y.n), c: Math.min(x.c, y.c) }; }
/** greedy order: each next color as far as possible from its neighbours (also for color-blind readers) and from all earlier colors */
function pick(first: string, pool: string[], count: number, one?: boolean): string[] {
    const S = one ? separation : sep2, out = [first];
    while (out.length < count && out.length <= pool.length) {
        let best = "", bs = -1;
        for (const p of pool) {
            if (out.includes(p)) continue;
            const a = S(out[out.length - 1], p), b = out.length > 1 ? S(out[out.length - 2], p) : { n: 99, c: 99 };
            let all = 1e9; for (const q of out) all = Math.min(all, S(q, p).n);
            const sc = Math.min(a.c * 2.2, a.n, all * 1.7, b.c * 3.2);
            if (sc > bs) { bs = sc; best = p; }
        }
        if (!best) break; out.push(best);
    }
    return out;
}
/** data colors need chroma: keep the brand hue, lift a muted brand, start a gray brand from a calm blue */
function lead(b: string): string {
    const [L, C, h] = lch(b);
    if (C < 0.03) return hexOf(0.55, 0.13, 250);
    if (C < 0.105) { for (const l of [L, 0.55, 0.6, 0.65, 0.7, 0.5].map(x => Math.max(0.45, Math.min(0.72, x)))) { const x = hexOf(l, 0.115, h); if (lch(x)[1] >= 0.1) return x; } return hexOf(0.6, 0.115, h); }
    return b;
}
export type PaletteMode = "spectrum" | "analogous" | "mono";
const GEN = new Map<string, string[]>();
/** generate a categorical palette from one brand color */
export function generate(brand: string, mode: PaletteMode, count = 12): string[] {
    const key = brand + mode + count; const hit = GEN.get(key); if (hit) return hit.slice();
    let out: string[];
    if (mode === "mono") {
        const [L, C, h] = lch(brand), c = C < 0.03 ? 0.012 : Math.max(0.085, Math.min(0.17, C));
        const pool = [0.26, 0.32, 0.38, 0.44, 0.5, 0.56, 0.62, 0.68, 0.74, 0.8, 0.85].filter(l => Math.abs(l - L) > 0.045).map(l => hexOf(l, c * (1 - Math.abs(l - 0.62) * 0.7), h));
        out = pick(brand, pool, Math.min(count, pool.length + 1), true);
    } else {
        const b = lead(brand), [, C, h] = lch(b), c = Math.max(0.11, Math.min(0.17, C)), pool: string[] = [];
        if (mode === "analogous") [0, 30, -30, 60, -60, 90, -90].forEach(o => [0.46, 0.52, 0.58, 0.64, 0.7, 0.76].forEach(l => pool.push(hexOf(l, Math.max(0.12, c), (h + o + 720) % 360))));
        else for (let k = 1; k < 24; k++) for (const l of [0.5, 0.56, 0.62, 0.68, 0.74]) pool.push(hexOf(l, Math.max(0.12, c), (h + k * 15) % 360));
        const chroma = pool.filter(x => lch(x)[1] >= 0.1);
        out = pick(b, chroma.length >= 20 ? chroma : pool, count);
    }
    GEN.set(key, out); return out.slice();
}
/** hex codes from free text or from a Power BI theme JSON ("dataColors") */
export function parseColors(text: string): string[] {
    const t = String(text || "").trim(); if (!t) return [];
    try { const j = JSON.parse(t); if (j && Array.isArray(j.dataColors)) return j.dataColors.filter(isHex).map(normHex); } catch { /* not JSON */ }
    return (t.match(/#?[0-9a-f]{6}\b|#[0-9a-f]{3}\b/gi) || []).filter(isHex).map(normHex);
}
/** worst neighbouring separation of a palette: n = normal vision, c = color-blind */
export function check(pal: string[]) { let n = 1e9, c = 1e9; for (let i = 0; i < pal.length - 1; i++) { const d = separation(pal[i], pal[i + 1]); n = Math.min(n, d.n); c = Math.min(c, d.c); } return { n: Math.round(n), c: Math.round(c) }; }
