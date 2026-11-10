/*
 * Data model for Atlas Lines: categories (one or more hierarchy levels
 * when drilled with "expand"), series from the Legend or from the measures
 * (Y-axis and Line y-axis), one cell per category and series, and the
 * optional Lower/Upper bounds of an error band.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, fillOf, numOf, tipsAt, hlValue, Tip, Val } from "./common/data";
import { BaseModel, Colored } from "./common/family";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface LCat { i: number; path: string[]; label: string; id: ISelectionId; }
export interface LSer extends Colored { i: number; line: boolean; format?: string; measure: string; v: number[]; cells: number[]; }
export interface LCell { i: number; c: number; s: number; v: number; hl: number | null; id: ISelectionId; tips: Tip[]; }
export interface Model extends BaseModel {
    cats: LCat[]; series: LSer[]; cells: LCell[]; levelNames: string[]; legendTitle: string; seriesField: boolean;
    lower: number[] | null; upper: number[] | null; drill: powerbi.DrillType[]; drillDisabled: boolean;
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values || !cat.values.length) return null;
    const culture = host.locale, catCols = catsOf(cat, "category"), values = cat.values, seriesField = !!values.source;
    if (!catCols.length) return null;
    const n = catCols[0].values.length, names = catCols.map(c => nameFormatter(c.source.format, culture));
    const withCats = (b: powerbi.visuals.ISelectionIdBuilder, r: number) => { catCols.forEach(c => b.withCategory(c, r)); return b; };
    const cats: LCat[] = [];
    for (let r = 0; r < n; r++) { const path = catCols.map((c, k) => names[k](c.values[r])); cats.push({ i: r, path, label: path[path.length - 1], id: withCats(host.createSelectionIdBuilder(), r).createSelectionId() }); }
    const series: LSer[] = [], cells: LCell[] = [];
    const role = (c: Val, r: string) => !!(c.source.roles && c.source.roles[r]);
    const add = (col: Val, line: boolean, key: string, name: string, color: string, id: ISelectionId, selector: powerbi.data.Selector, tipCols: Val[], extra: (b: powerbi.visuals.ISelectionIdBuilder) => powerbi.visuals.ISelectionIdBuilder) => {
        const s = series.length, sr: LSer = { key, name, color, selector, id, items: [], i: s, line, format: col.source.format, measure: col.source.displayName, v: [], cells: [] };
        for (let r = 0; r < n; r++) {
            /* under a cross-highlight a point shows its highlighted part; points with nothing selected keep their value and are dimmed */
            const raw = numOf(col.values[r]), v = isNaN(raw) ? raw : hlValue(raw, col.highlights ? col.highlights[r] : undefined, !!col.highlights, "keep"); sr.v.push(v);
            if (isNaN(v)) { sr.cells.push(-1); continue; }
            const h = col.highlights ? col.highlights[r] : undefined;
            const cell: LCell = { i: cells.length, c: r, s, v, hl: col.highlights ? (h === null || h === undefined ? null : Number(h)) : null, id: extra(withCats(host.createSelectionIdBuilder(), r)).createSelectionId(), tips: tipsAt(tipCols, r, culture) };
            cells.push(cell); sr.cells.push(cell.i); sr.items.push(cell.i);
        }
        series.push(sr);
    };
    if (seriesField) {
        const sname = nameFormatter(values.source.format, culture);
        values.grouped().forEach(g => {
            const col = g.values.find(c => role(c, "values") || role(c, "lineValues")); if (!col) return;
            const id = host.createSelectionIdBuilder().withSeries(values, g).createSelectionId();
            add(col, role(col, "lineValues"), "g" + String(g.name), sname(g.name as powerbi.PrimitiveValue), fillOf(g.objects) || "", id, id.getSelector(), g.values.filter(c => role(c, "tooltips")), b => b.withSeries(values, g));
        });
    } else {
        const tipCols = values.filter(c => role(c, "tooltips"));
        values.filter(c => role(c, "values") || role(c, "lineValues")).forEach(col => {
            const q = col.source.queryName as string, id = host.createSelectionIdBuilder().withMeasure(q).createSelectionId();
            add(col, role(col, "lineValues"), "m" + q, col.source.displayName, fillOf(col.source.objects) || "", id, { metadata: q }, tipCols, b => b.withMeasure(q));
        });
    }
    if (!series.length || !cells.length) return null;
    const lo = values.find(c => role(c, "lower")), up = values.find(c => role(c, "upper"));
    const roles = dv && dv.metadata && dv.metadata.dataRoles;
    return {
        cats, series, cells, levelNames: catCols.map(c => c.source.displayName), legendTitle: seriesField ? values.source.displayName : "", seriesField,
        lower: lo ? cats.map((_, r) => numOf(lo.values[r])) : null, upper: up ? cats.map((_, r) => numOf(up.values[r])) : null,
        drill: (roles && roles.drillableRoles && roles.drillableRoles["category"]) || [], drillDisabled: !!(roles && roles.isDrillDisabled),
        colored: series, ids: cells.map(c => c.id), hl: cells.some(c => c.hl !== null) ? new Set(cells.filter(c => c.hl !== null && c.hl !== 0).map(c => c.i)) : null, rows: n
    };
}
