/*
 * Reading helpers for the categorical data view, shared by the Atlas
 * family visuals: columns by role, colors stored in objects, and
 * formatted tooltip items.
 */
import powerbi from "powerbi-visuals-api";
import { formatter } from "./util";

export type Cat = powerbi.DataViewCategoryColumn;
export type Val = powerbi.DataViewValueColumn;
const has = (c: { source: powerbi.DataViewMetadataColumn }, role: string) => !!(c.source.roles && c.source.roles[role]);
/** category columns bound to a role */
export const catsOf = (cat: powerbi.DataViewCategorical, role: string): Cat[] => (cat.categories || []).filter(c => has(c, role));
/** value (measure) columns bound to a role */
export const valsOf = (cat: powerbi.DataViewCategorical, role: string): Val[] => (cat.values ? cat.values.filter(c => has(c, role)) : []);
/** a color stored in a data point's or column's objects (Colors card, theme or fx) */
export function fillOf(o: powerbi.DataViewObjects | undefined, obj = "dataColors", prop = "fill"): string | undefined {
    const f = o && o[obj] && (o[obj][prop] as powerbi.Fill);
    return f && f.solid && f.solid.color ? f.solid.color : undefined;
}
/** number or NaN for blanks */
export const numOf = (v: powerbi.PrimitiveValue | undefined) => (v === null || v === undefined || v === "" ? NaN : Number(v));
export interface Tip { name: string; value: string; }
/** tooltip items for the Tooltips role at one row */
export function tipsAt(cols: Val[], r: number, culture: string): Tip[] {
    return cols.map(c => ({ name: c.source.displayName, value: formatter(c.source.format, 1, null, numOf(c.values[r]), culture)(numOf(c.values[r])) }));
}
/**
 * The value to draw while another visual's selection highlights this one (Power BI sends highlight
 * values instead of filtering a visual that supports highlights). "filter" draws only the highlighted
 * part, like a filter would (0 where nothing matches): donuts, cards and gauges then change with the
 * selection. "keep" draws the highlighted part where something matches and the full value elsewhere
 * (the visual dims it): a line keeps its shape.
 */
export function hlValue(v: number, h: powerbi.PrimitiveValue | undefined, highlighted: boolean, mode: "filter" | "keep" = "filter"): number {
    if (!highlighted) return v;
    const x = h === null || h === undefined ? NaN : Number(h);
    if (isFinite(x) && x !== 0) return x;
    return mode === "filter" ? 0 : v;
}
/**
 * How a visual draws a cross-highlight. A selection on another field covers part of some values
 * (Online sales of each category): the visual then shows the highlighted parts ("filter"). A selection
 * of whole items (Bikes picked in another visual on the same field) highlights all of an item or none:
 * the visual keeps every value and dims the rest ("keep"), like Power BI's own pie.
 */
export function hlModeOf(cols: Val[]): "filter" | "keep" {
    const partly = cols.some(c => !!c.highlights && c.highlights.some((h, r) => {
        if (h === null || h === undefined) return false;
        const x = Number(h), v = numOf(c.values[r]);
        return isFinite(x) && x !== 0 && isFinite(v) && Math.abs(x - v) > 1e-9 * Math.max(1, Math.abs(v));
    }));
    return partly ? "filter" : "keep";
}
