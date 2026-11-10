/*
 * Data model for KPI Scorecard: one row per category value (KPI). Result, latest, target and status
 * are read from the latest trend row that has them (numbers are formatted with the measure's format,
 * text is shown as is). The trend values along the trend axis make the sparkline.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter, formatter } from "./common/util";
import { catsOf, valsOf, numOf, tipsAt, Tip, Val } from "./common/data";
import { BaseModel, Colored } from "./common/family";

export type Status = "good" | "warn" | "bad" | null;
export interface Row extends Colored {
    i: number; result: string; latest: string; target: string; statusText: string; status: Status;
    trend: { name: string; v: number }[]; tips: Tip[]; trendFormat?: string;
}
export interface Model extends BaseModel {
    list: Row[]; catTitle: string; hasTrend: boolean; heads: { result: string; latest: string; target: string; status: string; trend: string };
    has: { result: boolean; latest: boolean; target: boolean; status: boolean };
    accent: Colored;
}

/** status from text (On track / At risk / Off track ...) or a number (>0 good, 0 at risk, <0 off) */
export function statusOf(v: powerbi.PrimitiveValue | undefined): Status {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "number") return v > 0 ? "good" : v < 0 ? "bad" : "warn";
    const s = String(v).toLowerCase();
    if (/off|behind|fail|bad|red|critical/.test(s)) return "bad";
    if (/risk|watch|warn|amber|close/.test(s)) return "warn";
    return "good";
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost, units: number, decimals: number): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values) return null;
    const catCol = catsOf(cat, "category")[0];
    if (!catCol) return null;
    const trendCol = catsOf(cat, "trend")[0], culture = host.locale;
    const one = (role: string) => valsOf(cat, role)[0] as Val | undefined;
    const trendVals = one("values");
    /* without a trend axis, or without a Result, the trend values are the result */
    const rc = one("result") || (trendVals && !trendCol ? trendVals : undefined), lc = one("latest"), tc = one("target"), sc = one("status"), vc = one("values"), tipCols = valsOf(cat, "tooltips");
    if (!rc && !lc && !tc && !sc && !vc) return null;
    const n = catCol.values.length;
    const fmts = new Map<Val, (v: number) => string>();
    const show = (c: Val | undefined, r: number): string => {
        if (!c) return "";
        const v = c.values[r];
        if (v === null || v === undefined || v === "") return "";
        if (typeof v === "number") {
            let f = fmts.get(c);
            if (!f) { f = formatter(c.source.format, units, decimals < 0 ? null : decimals, Math.abs(v), culture); fmts.set(c, f); }
            return f(v);
        }
        return String(v);
    };
    const cname = nameFormatter(catCol.source.format, culture), tname = trendCol ? nameFormatter(trendCol.source.format, culture) : null;
    const groups = new Map<string, number[]>(), order: string[] = [];
    for (let r = 0; r < n; r++) { const k = String(catCol.values[r]); if (!groups.has(k)) { groups.set(k, []); order.push(k); } (groups.get(k) as number[]).push(r); }
    const list: Row[] = [];
    order.forEach(k => {
        const rows = groups.get(k) as number[];
        /* the latest row with a value wins */
        const last = (c: Val | undefined) => { if (!c) return -1; for (let j = rows.length - 1; j >= 0; j--) { const v = c.values[rows[j]]; if (v !== null && v !== undefined && v !== "") return rows[j]; } return -1; };
        const pick = (c: Val | undefined) => { const r = last(c); return r < 0 ? "" : show(c, r); };
        const rs = last(sc), r0 = rows[0];
        const id = host.createSelectionIdBuilder().withCategory(catCol, r0).createSelectionId();
        const row: Row = {
            key: "c" + k, name: cname(catCol.values[r0]), color: "", selector: null, id, items: [list.length], i: list.length,
            result: rc ? pick(rc) : pick(vc), latest: pick(lc), target: pick(tc), statusText: rs < 0 ? "" : String(sc ? sc.values[rs] : ""), status: rs < 0 ? null : statusOf(sc ? sc.values[rs] : null),
            trend: trendCol && vc ? rows.map(r => ({ name: (tname as (v: powerbi.PrimitiveValue) => string)(trendCol.values[r]), v: numOf(vc.values[r]) })).filter(p => !isNaN(p.v)) : [],
            tips: tipsAt(tipCols, last(tipCols[0]) < 0 ? r0 : last(tipCols[0]), culture), trendFormat: vc ? vc.source.format : undefined
        };
        if (typeof sc?.values[rs] === "number") row.statusText = row.status === "good" ? "On track" : row.status === "warn" ? "At risk" : row.status === "bad" ? "Off track" : "";
        if (row.result || row.latest || row.target || row.statusText || row.trend.length) list.push(row);
    });
    if (!list.length) return null;
    list.forEach((r, k) => { r.i = k; r.items = [k]; });
    const accent: Colored = { key: "trend", name: vc ? vc.source.displayName : "Trend", color: "", selector: vc ? { metadata: vc.source.queryName as string } : null, id: null, items: list.map(r => r.i) };
    const dn = (c: Val | undefined, f: string) => (c ? c.source.displayName : f);
    return {
        list, catTitle: catCol.source.displayName, hasTrend: !!(trendCol && vc),
        heads: { result: dn(rc || vc, "Result"), latest: dn(lc, "Latest"), target: dn(tc, "Target"), status: "Status", trend: "Trend" },
        has: { result: !!(rc || vc),latest: !!lc, target: !!tc, status: !!sc },
        accent, colored: [accent], ids: list.map(r => r.id as powerbi.visuals.ISelectionId), hl: null, rows: n
    };
}
