/*
 * Data model for Atlas Gauges: a list of items, each with a value and an
 * optional target, minimum, maximum, two band thresholds and a trend.
 * Items are categories; without a category, each measure in Value is an
 * item. With a trend axis, the latest period is the value shown.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, valsOf, fillOf, numOf, tipsAt, hlValue, hlModeOf, Tip, Val } from "./common/data";
import { BaseModel, Colored } from "./common/family";

export interface Item extends Colored {
    i: number; value: number; target: number; min: number; max: number; b1: number; b2: number;
    trend: { name: string; v: number }[]; format?: string; measure: string; tips: Tip[]; hl: boolean | null;
}
export interface Model extends BaseModel { list: Item[]; catTitle: string; hasTarget: boolean; hasTrend: boolean; hasBands: boolean; }

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values) return null;
    const vals = valsOf(cat, "values");
    if (!vals.length) return null;
    const one = (role: string) => valsOf(cat, role)[0] as Val | undefined;
    const tg = one("target"), mn = one("minValue"), mx = one("maxValue"), b1 = one("band1"), b2 = one("band2"), tipCols = valsOf(cat, "tooltips");
    const catCol = catsOf(cat, "category")[0], trendCol = catsOf(cat, "trend")[0], culture = host.locale;
    const n = cat.categories && cat.categories.length ? cat.categories[0].values.length : vals[0].values.length;
    /* under a cross-highlight every number shows the highlighted part (the selection in another visual), as a filter would */
    const hlMode = hlModeOf(vals.concat([tg, mn, mx, b1, b2].filter(x => !!x) as Val[]));
    const at = (c: Val | undefined, r: number) => (c ? hlValue(numOf(c.values[r]), c.highlights ? c.highlights[r] : undefined, !!c.highlights, hlMode) : NaN);
    const tname = trendCol ? nameFormatter(trendCol.source.format, culture) : null;
    const list: Item[] = [];
    const make = (key: string, name: string, rows: number[], col: Val, id: powerbi.visuals.ISelectionId | null, selector: powerbi.data.Selector | null, color: string): Item => {
        /* the latest row with a value is the current value; every row is a trend point */
        let r0 = rows[rows.length - 1];
        for (let k = rows.length - 1; k >= 0; k--) if (!isNaN(at(col, rows[k]))) { r0 = rows[k]; break; }
        const hlRow = col.highlights ? col.highlights[r0] : undefined;
        return {
            key, name, color, selector, id, items: [list.length], i: list.length, value: at(col, r0), target: at(tg, r0), min: at(mn, r0), max: at(mx, r0), b1: at(b1, r0), b2: at(b2, r0),
            trend: trendCol ? rows.map(r => ({ name: (tname as (v: powerbi.PrimitiveValue) => string)(trendCol.values[r]), v: at(col, r) })).filter(p => !isNaN(p.v)) : [],
            format: col.source.format, measure: col.source.displayName, tips: tipsAt(tipCols, r0, culture), hl: col.highlights ? hlRow !== null && hlRow !== undefined && hlRow !== 0 : null
        };
    };
    if (catCol) {
        const cname = nameFormatter(catCol.source.format, culture), groups = new Map<string, number[]>(), order: string[] = [];
        for (let r = 0; r < n; r++) { const k = String(catCol.values[r]); if (!groups.has(k)) { groups.set(k, []); order.push(k); } (groups.get(k) as number[]).push(r); }
        order.forEach(k => {
            const rows = groups.get(k) as number[], r = rows[0], id = host.createSelectionIdBuilder().withCategory(catCol, r).createSelectionId();
            list.push(make("c" + k, cname(catCol.values[r]), rows, vals[0], id, id.getSelector(), fillOf(catCol.objects && catCol.objects[r]) || ""));
        });
    } else {
        const rows = Array.from({ length: n }, (_, r) => r);
        vals.forEach(col => {
            const q = col.source.queryName as string, id = host.createSelectionIdBuilder().withMeasure(q).createSelectionId();
            list.push(make("m" + q, col.source.displayName, rows, col, id, { metadata: q }, fillOf(col.source.objects) || ""));
        });
    }
    const valid = list.filter(it => !isNaN(it.value));
    if (!valid.length) return null;
    valid.forEach((it, k) => { it.i = k; it.items = [k]; });
    const hasHl = valid.some(it => it.hl !== null);
    return {
        list: valid, catTitle: catCol ? catCol.source.displayName : "", hasTarget: !!tg, hasTrend: !!trendCol, hasBands: !!(b1 || b2),
        colored: valid, ids: valid.map(it => it.id as powerbi.visuals.ISelectionId), hl: hasHl ? new Set(valid.filter(it => it.hl).map(it => it.i)) : null, rows: n
    };
}
