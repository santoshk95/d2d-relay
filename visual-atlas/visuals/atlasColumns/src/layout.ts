/*
 * Stacking, value domain and tick math for Atlas Columns.
 */
import { Model, Pt } from "./model";

export type Mode = "clustered" | "stacked" | "percent";
export interface CatTotal { pos: number; neg: number; net: number; abs: number; }
export interface Stacked { lo: number; hi: number; totals: CatTotal[]; anyNeg: boolean; maxAbs: number; byCat: Pt[][]; }

/** value-space start (a) and end (b) of every point, plus per-category totals */
export function stackUp(m: Model, mode: Mode): Stacked {
    const totals: CatTotal[] = m.cats.map(() => ({ pos: 0, neg: 0, net: 0, abs: 0 }));
    const byCat: Pt[][] = m.cats.map(() => []);
    m.pts.forEach(p => { byCat[p.c].push(p); const t = totals[p.c]; t.net += p.v; t.abs += Math.abs(p.v); });
    const grand = totals.reduce((s, t) => s + t.abs, 0) || 1, many = m.series.length > 1;
    let lo = 0, hi = 0, maxAbs = 0;
    byCat.forEach((list, c) => {
        list.sort((p, q) => p.s - q.s);
        const t = totals[c], k = mode === "percent" ? t.abs || 1 : 1;
        let pos = 0, neg = 0, firstPos: Pt | null = null, firstNeg: Pt | null = null, lastPos: Pt | null = null, lastNeg: Pt | null = null;
        for (const p of list) {
            p.share = many ? (t.abs ? p.v / t.abs : 0) : p.v / grand;
            maxAbs = Math.max(maxAbs, Math.abs(p.v));
            if (mode === "clustered") {
                p.a = 0; p.b = p.v; p.base = true; p.outer = true;
                if (p.hl !== null) { p.ha = 0; p.hb = p.hl; }
                lo = Math.min(lo, p.v); hi = Math.max(hi, p.v);
                continue;
            }
            const v = p.v / k;
            if (v >= 0) { p.a = pos; pos += v; p.b = pos; if (!firstPos) firstPos = p; lastPos = p; }
            else { p.a = neg; neg += v; p.b = neg; if (!firstNeg) firstNeg = p; lastNeg = p; }
            if (p.hl !== null) { p.ha = p.a; p.hb = p.a + p.hl / k; }
            p.base = false; p.outer = false;
        }
        if (mode !== "clustered") {
            for (const p of [firstPos, firstNeg]) if (p) p.base = true;
            for (const p of [lastPos, lastNeg]) if (p) p.outer = true;
            t.pos = pos * k; t.neg = neg * k;
            lo = Math.min(lo, neg); hi = Math.max(hi, pos);
        }
    });
    const anyNeg = m.pts.some(p => p.v < 0);
    if (mode === "percent") { lo = anyNeg ? -1 : 0; hi = m.pts.some(p => p.v > 0) || !anyNeg ? 1 : 0; }
    return { lo, hi, totals, anyNeg, maxAbs, byCat };
}

/** round domain and evenly spaced ticks (1, 2, 5 steps) */
export function nice(lo: number, hi: number, count: number): { lo: number; hi: number; ticks: number[] } {
    if (!(hi > lo)) { if (lo === 0) hi = 1; else if (lo > 0) { lo = 0; } else hi = 0; }
    if (!(hi > lo)) hi = lo + 1;
    const span = hi - lo; let step = Math.pow(10, Math.floor(Math.log10(span / Math.max(1, count))));
    const err = span / Math.max(1, count) / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step, ticks: number[] = [];
    for (let i = 0; i < 200; i++) { const v = a + i * step; if (v > b + step * 1e-6) break; ticks.push(Math.abs(v) < step * 1e-9 ? 0 : +v.toPrecision(12)); }
    return { lo: a, hi: b, ticks };
}

/** reference line value from the visible bars */
export function refValue(kind: string, constant: number, st: Stacked, mode: Mode, m: Model): number | null {
    if (kind === "constant") return constant;
    const vals = mode === "stacked" ? st.totals.map(t => t.net) : m.pts.map(p => p.v);
    if (!vals.length) return null;
    if (kind === "min") return Math.min(...vals);
    if (kind === "max") return Math.max(...vals);
    if (kind === "median") { const s = vals.slice().sort((a, b) => a - b), h = s.length >> 1; return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2; }
    return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/** numbers typed in the Format pane ("1,200", " 50 ") or NaN when empty */
export function parseNum(s: string): number {
    const t = String(s || "").replace(/[\s,]/g, "");
    return t === "" ? NaN : Number(t);
}
