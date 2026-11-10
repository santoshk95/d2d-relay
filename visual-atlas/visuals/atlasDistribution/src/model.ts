/*
 * Data model for Atlas Distribution: one observation per row (Group ×
 * Sample by), grouped by the Group field (or by measure when there is
 * no group and several measures), plus the statistics the charts need:
 * quantiles, whiskers, kernel density and histogram bins.
 */
import powerbi from "powerbi-visuals-api";
import { formatter, nameFormatter } from "./common/util";
import ISelectionId = powerbi.visuals.ISelectionId;
import DataView = powerbi.DataView;

export interface Tip { name: string; value: string; }
export interface Obs {
    i: number; row: number; g: number;
    /** one value per measure (NaN when blank) */
    v: number[];
    label: string; id: ISelectionId; tips: Tip[];
    /** highlighted by another visual (null when the report sends no highlights) */
    hl: boolean | null;
}
export interface Group {
    i: number; key: string; name: string; color: string;
    id: ISelectionId | null; selector: powerbi.data.Selector | null;
    /** indexes into Model.obs */
    obs: number[];
    /** the measure this group stands for when groups come from measures */
    m: number;
}
export interface Measure { name: string; format?: string; query: string; }
export interface Model {
    obs: Obs[]; groups: Group[]; measures: Measure[];
    groupTitle: string; detailTitle: string;
    /** groups are measures (no Group field, several measures) */
    byMeasure: boolean;
    hasGroup: boolean; hasDetail: boolean; highlights: boolean; rows: number;
}
type Builder = powerbi.visuals.ISelectionIdBuilder;

const fillOf = (o: powerbi.DataViewObjects | undefined): string | undefined => {
    const f = o && o["dataColors"] && (o["dataColors"]["fill"] as powerbi.Fill);
    return f && f.solid && f.solid.color ? f.solid.color : undefined;
};

export function readModel(dv: DataView | undefined, host: powerbi.extensibility.visual.IVisualHost, chartType: string): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values || !cat.values.length) return null;
    const culture = host.locale;
    const cols = cat.categories || [];
    const gCol = cols.find(c => !!(c.source.roles && c.source.roles["category"]));
    const dCol = cols.find(c => !!(c.source.roles && c.source.roles["detail"]));
    const vals = cat.values.filter(c => !!(c.source.roles && c.source.roles["values"]));
    const tips = cat.values.filter(c => !!(c.source.roles && c.source.roles["tooltips"]));
    if (!vals.length) return null;
    const n = cols.length ? cols[0].values.length : vals[0].values.length;
    const builder = (): Builder => host.createSelectionIdBuilder();
    const measures: Measure[] = vals.map(c => ({ name: c.source.displayName, format: c.source.format, query: c.source.queryName as string }));
    const byMeasure = !gCol && vals.length > 1 && chartType !== "parallel";
    const gName = gCol ? nameFormatter(gCol.source.format, culture) : null, dName = dCol ? nameFormatter(dCol.source.format, culture) : null;
    const tipF = tips.map(c => formatter(c.source.format, 1, null, 0, culture));

    const groups: Group[] = [], byKey = new Map<string, number>();
    if (byMeasure) {
        vals.forEach((c, k) => {
            const id = builder().withMeasure(measures[k].query).createSelectionId();
            groups.push({ i: k, key: "m" + measures[k].query, name: measures[k].name, color: fillOf(c.source.objects) || "", id, selector: { metadata: measures[k].query }, obs: [], m: k });
        });
    }
    const obs: Obs[] = [];
    const hlCol = vals[0].highlights;
    for (let r = 0; r < n; r++) {
        const v = vals.map(c => { const x = c.values[r]; return x === null || x === undefined || x === "" ? NaN : Number(x); });
        let g = 0;
        if (gCol) {
            const raw = gCol.values[r], key = String(raw);
            let gi = byKey.get(key);
            if (gi === undefined) {
                gi = groups.length; byKey.set(key, gi);
                const id = builder().withCategory(gCol, r).createSelectionId();
                groups.push({ i: gi, key: "g" + key, name: (gName as (v: powerbi.PrimitiveValue) => string)(raw), color: fillOf(gCol.objects && gCol.objects[r]) || "", id, selector: id.getSelector(), obs: [], m: 0 });
            }
            g = gi;
        } else if (!byMeasure && !groups.length) {
            groups.push({ i: 0, key: "all", name: measures[0].name, color: fillOf(vals[0].source.objects) || "", id: null, selector: { metadata: measures[0].query }, obs: [], m: 0 });
        }
        const b = builder(); cols.forEach(c => b.withCategory(c, r));
        const label = dCol ? (dName as (v: powerbi.PrimitiveValue) => string)(dCol.values[r]) : gCol ? groups[g].name : String(r + 1);
        const hl = hlCol ? hlCol[r] !== null && hlCol[r] !== undefined : null;
        const tipItems = tips.map((c, k) => ({ name: c.source.displayName, value: tipF[k](Number(c.values[r])) }));
        if (byMeasure) {
            /* one observation per measure, so each measure group holds its own values */
            vals.forEach((c, k) => {
                if (isNaN(v[k])) return;
                const o: Obs = { i: obs.length, row: r, g: k, v: vals.map((_, j) => (j === k ? v[k] : NaN)), label, id: builder().withMeasure(measures[k].query).createSelectionId(), tips: tipItems, hl };
                if (cols.length) { const bb = builder(); cols.forEach(cc => bb.withCategory(cc, r)); o.id = bb.withMeasure(measures[k].query).createSelectionId(); }
                obs.push(o); groups[k].obs.push(o.i);
            });
            continue;
        }
        if (v.every(x => isNaN(x))) continue;
        const o: Obs = { i: obs.length, row: r, g, v, label, id: b.createSelectionId(), tips: tipItems, hl };
        obs.push(o); groups[g].obs.push(o.i);
    }
    if (!obs.length) return null;
    /* drop groups without values and renumber */
    const kept = groups.filter(g => g.obs.length > 0), renum = new Map<number, number>();
    kept.forEach((g, k) => { renum.set(g.i, k); g.i = k; });
    obs.forEach(o => { o.g = renum.get(o.g) as number; });
    return {
        obs, groups: kept, measures,
        groupTitle: gCol ? gCol.source.displayName : "", detailTitle: dCol ? dCol.source.displayName : "",
        byMeasure, hasGroup: !!gCol, hasDetail: !!dCol, highlights: !!hlCol, rows: n
    };
}

/* ------------------------------------------------------------------ statistics */
export interface Stats {
    n: number; min: number; max: number; mean: number; sd: number;
    q1: number; md: number; q3: number;
    /** whisker ends and the values beyond them */
    lo: number; hi: number; out: number[];
    sorted: number[];
}
/** linear-interpolated quantile of sorted values (type 7, as Excel and R use) */
export function quantile(s: number[], p: number): number {
    if (!s.length) return NaN;
    const h = (s.length - 1) * p, a = Math.floor(h), b = Math.min(s.length - 1, a + 1);
    return s[a] + (h - a) * (s[b] - s[a]);
}
export function stats(values: number[], whiskers: string): Stats {
    const s = values.filter(v => isFinite(v)).sort((a, b) => a - b), n = s.length;
    const mean = n ? s.reduce((a, b) => a + b, 0) / n : NaN;
    const sd = n > 1 ? Math.sqrt(s.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (n - 1)) : 0;
    const q1 = quantile(s, 0.25), md = quantile(s, 0.5), q3 = quantile(s, 0.75);
    let lo: number, hi: number;
    if (whiskers === "minmax") { lo = s[0]; hi = s[n - 1]; }
    else if (whiskers === "p5") { lo = quantile(s, 0.05); hi = quantile(s, 0.95); }
    else {
        const f = 1.5 * (q3 - q1), a = q1 - f, b = q3 + f;
        lo = s.find(v => v >= a) ?? q1; hi = q3;
        for (let k = n - 1; k >= 0; k--) if (s[k] <= b) { hi = s[k]; break; }
    }
    return { n, min: s[0], max: s[n - 1], mean, sd, q1, md, q3, lo, hi, out: s.filter(v => v < lo || v > hi), sorted: s };
}

/** Gaussian kernel density at `count` points between a and b; bandwidth from Silverman's rule × factor */
export function kde(sorted: number[], a: number, b: number, count: number, factor: number): [number, number][] {
    const n = sorted.length; if (!n) return [];
    const mean = sorted.reduce((s, v) => s + v, 0) / n;
    const sd = n > 1 ? Math.sqrt(sorted.reduce((s, v) => s + (v - mean) * (v - mean), 0) / (n - 1)) : 0;
    const iqr = quantile(sorted, 0.75) - quantile(sorted, 0.25);
    let h = 0.9 * Math.min(sd || Infinity, iqr > 0 ? iqr / 1.34 : Infinity) * Math.pow(n, -0.2);
    if (!isFinite(h) || h <= 0) h = Math.max(1e-9, Math.abs(sorted[0]) * 0.05 || 1);
    h *= factor;
    const out: [number, number][] = [], k = 1 / (n * h * Math.sqrt(2 * Math.PI));
    const lower = (x: number) => { let lo = 0, hi = n; while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < x) lo = m + 1; else hi = m; } return lo; };
    for (let i = 0; i < count; i++) {
        const x = count > 1 ? a + (b - a) * i / (count - 1) : a;
        let d = 0;
        for (let j = lower(x - 4 * h); j < n && sorted[j] <= x + 4 * h; j++) { const z = (x - sorted[j]) / h; d += Math.exp(-0.5 * z * z); }
        out.push([x, d * k]);
    }
    return out;
}

/** a 1-2-5 step close to span / count */
export function niceStep(span: number, count: number): number {
    if (!(span > 0)) return 1;
    const raw = span / Math.max(1, count), p = Math.pow(10, Math.floor(Math.log10(raw))), e = raw / p;
    return (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * p;
}
export interface Bins { start: number; step: number; count: number; }
/** equal-width bins aligned to a round step */
export function binning(min: number, max: number, n: number, mode: string, binCount: number, binWidth: number): Bins {
    if (!(max > min)) { const w = Math.abs(min) * 0.1 || 1; return { start: min - w / 2, step: w, count: 1 }; }
    let step: number;
    if (mode === "width" && binWidth > 0) step = binWidth;
    else if (mode === "count") step = (max - min) / Math.max(1, binCount);
    else step = niceStep(max - min, Math.max(5, Math.min(40, Math.ceil(Math.log2(n) + 1 + Math.sqrt(n) / 6))));
    if (mode !== "count") { const start = Math.floor(min / step + 1e-9) * step; return { start, step, count: Math.max(1, Math.min(1000, Math.ceil((max - start) / step - 1e-9) || 1)) }; }
    return { start: min, step, count: Math.max(1, Math.round((max - min) / step)) };
}
export function binOf(b: Bins, v: number): number { return Math.max(0, Math.min(b.count - 1, Math.floor((v - b.start) / b.step + 1e-9))); }

/** deterministic jitter in [0, 1) for an observation (no Math.random, so layouts repeat) */
export function jitter(i: number): number {
    let x = (i + 1) * 0x9e3779b1;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b); x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35); x ^= x >>> 16;
    return (x >>> 0) / 4294967296;
}
