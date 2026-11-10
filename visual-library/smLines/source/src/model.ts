/*
 * Data model for Small Multiple Lines: panels (one per group value), each with points along the axis
 * holding the actual value and the comparison (plan).
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, valsOf, numOf, tipsAt, Tip, Val } from "./common/data";
import { BaseModel, Colored } from "./common/family";

export interface Pt { i: number; key: string; name: string; v: number; p: number; id: powerbi.visuals.ISelectionId; tips: Tip[]; }
export interface Panel { key: string; name: string; sub: string; pts: Pt[]; items: number[]; }
export interface Model extends BaseModel {
    panels: Panel[]; axis: { key: string; name: string }[]; hasComp: boolean;
    actual: Colored; plan: Colored; format?: string; groupTitle: string; catTitle: string;
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values) return null;
    const axisCol = catsOf(cat, "category")[0], groupCol = catsOf(cat, "group")[0];
    const vc = valsOf(cat, "values")[0] as Val | undefined, pc = valsOf(cat, "comparison")[0] as Val | undefined, sc = valsOf(cat, "subtitle")[0] as Val | undefined;
    if (!axisCol || !vc) return null;
    const culture = host.locale, tipCols = valsOf(cat, "tooltips"), n = axisCol.values.length;
    /* dates read as short months ("Nov 25"): a time axis only needs the month */
    const fmtName = nameFormatter(axisCol.source.format, culture);
    const aname = (v: powerbi.PrimitiveValue) => {
        const d = v instanceof Date ? v : null;
        if (!d || isNaN(d.getTime())) return fmtName(v);
        try { return d.toLocaleDateString(culture || "en-US", { month: "short", year: "2-digit" }); } catch (e) { return fmtName(v); }
    };
    const gname = groupCol ? nameFormatter(groupCol.source.format, culture) : null;
    const panels = new Map<string, Panel>(), order: Panel[] = [], axisKeys = new Map<string, { key: string; name: string; raw: powerbi.PrimitiveValue }>();
    const ids: powerbi.visuals.ISelectionId[] = [];
    let i = 0;
    for (let r = 0; r < n; r++) {
        const gk = groupCol ? String(groupCol.values[r]) : "", ak = String(axisCol.values[r] instanceof Date ? (axisCol.values[r] as Date).getTime() : axisCol.values[r]);
        if (!axisKeys.has(ak)) axisKeys.set(ak, { key: ak, name: aname(axisCol.values[r]), raw: axisCol.values[r] });
        let pn = panels.get(gk);
        if (!pn) { pn = { key: gk, name: gname ? gname(groupCol.values[r]) : vc.source.displayName, sub: "", pts: [], items: [] }; panels.set(gk, pn); order.push(pn); }
        const subv = sc ? sc.values[r] : null;
        if (subv !== null && subv !== undefined && subv !== "") pn.sub = String(subv);
        const v = numOf(vc.values[r]), p = pc ? numOf(pc.values[r]) : NaN;
        if (isNaN(v) && isNaN(p)) continue;
        const b = host.createSelectionIdBuilder(); if (groupCol) b.withCategory(groupCol, r); b.withCategory(axisCol, r);
        const id = b.createSelectionId();
        pn.pts.push({ i, key: ak, name: aname(axisCol.values[r]), v, p, id, tips: tipsAt(tipCols, r, culture) });
        pn.items.push(i); ids.push(id); i++;
    }
    const list = order.filter(p => p.pts.length);
    if (!list.length) return null;
    /* axis order: dates and numbers ascending, text in data order */
    const axis = Array.from(axisKeys.values());
    if (axis.every(a => a.raw instanceof Date || typeof a.raw === "number")) axis.sort((a, b) => Number(a.raw instanceof Date ? a.raw.getTime() : a.raw) - Number(b.raw instanceof Date ? b.raw.getTime() : b.raw));
    const pos = new Map(axis.map((a, k) => [a.key, k]));
    list.forEach(pn => pn.pts.sort((a, b) => (pos.get(a.key) as number) - (pos.get(b.key) as number)));
    const all = list.reduce((a, pn) => a.concat(pn.items), [] as number[]);
    const actual: Colored = { key: "actual", name: vc.source.displayName, color: "", selector: { metadata: vc.source.queryName as string }, id: null, items: all };
    const plan: Colored = { key: "plan", name: pc ? pc.source.displayName : "", color: "", selector: null, id: null, items: all };
    return {
        panels: list, axis: axis.map(a => ({ key: a.key, name: a.name })), hasComp: !!pc, actual, plan, format: vc.source.format,
        groupTitle: groupCol ? groupCol.source.displayName : "", catTitle: axisCol.source.displayName,
        colored: [actual], ids, hl: null, rows: n
    };
}
