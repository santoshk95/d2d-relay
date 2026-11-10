/*
 * Category × series matrix read from the categorical data view, shared by
 * the Atlas family visuals (Compare, Proportion, ...). Series come from the
 * Legend or, without one, from the measures in Values.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./util";
import { catsOf, valsOf, fillOf, numOf, tipsAt, hlValue, hlModeOf, Tip, Val } from "./data";
import { BaseModel, Colored } from "./family";
import { Target } from "./interact";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface Cell { i: number; c: number; s: number; v: number; /** the value before a cross-highlight (v is the highlighted part) */ full: number; hlv: number | null; id: ISelectionId; tips: Tip[]; }
export interface Model extends BaseModel {
    cats: Colored[]; series: Colored[]; cells: Cell[];
    /** grid[c][s]: the cell at a category and series, if it has a value */
    grid: (Cell | undefined)[][];
    catTitle: string; serTitle: string; byMeasure: boolean; format?: string; formats: (string | undefined)[];
    /** drill-down: the drill types available for the category role, and whether drilling is off */
    drill: powerbi.DrillType[]; drillDisabled: boolean; levelNames: string[];
}

/**
 * colorCats: give the palette colors to the categories when there is one series.
 * measuresAreParts: the extra measures are a total or a weight, not series (waffle, pictogram, aster), so categories keep the colors.
 */
export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost, colorCats: boolean, measuresAreParts = false, hlMode?: "filter" | "keep"): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values || !cat.values.length) return null;
    const culture = host.locale, catCols = catsOf(cat, "category"), catCol = catCols[0];
    if (!catCol) return null;
    const values = cat.values, seriesField = !!values.source, n = catCol.values.length;
    const mode = hlMode || hlModeOf(values ? Array.from(values) : []);
    const builder = () => host.createSelectionIdBuilder();
    /* an expanded hierarchy sends several category columns: names are joined, selection covers every level */
    const cnames = catCols.map(c => nameFormatter(c.source.format, culture));
    const withCats = (b: powerbi.visuals.ISelectionIdBuilder, r: number) => { catCols.forEach(c => b.withCategory(c, r)); return b; };
    const cats: Colored[] = [];
    for (let r = 0; r < n; r++) {
        const id = withCats(builder(), r).createSelectionId();
        let over: string | undefined; catCols.forEach(c => { over = over || fillOf(c.objects && c.objects[r]); });
        cats.push({ key: catCols.map(c => String(c.values[r])).join("\u001f"), name: catCols.map((c, k) => cnames[k](c.values[r])).join(" › "), color: over || "", selector: id.getSelector(), id, items: [] });
    }
    const series: Colored[] = [], cells: Cell[] = [], formats: (string | undefined)[] = [];
    const add = (col: Val, s: number, tipCols: Val[], extra: (b: powerbi.visuals.ISelectionIdBuilder) => powerbi.visuals.ISelectionIdBuilder) => {
        for (let r = 0; r < n; r++) {
            const v = numOf(col.values[r]); if (isNaN(v)) continue;
            const h = col.highlights ? col.highlights[r] : undefined;
            const cell: Cell = { i: cells.length, c: r, s, v: hlValue(v, h, !!col.highlights, mode), full: v, hlv: col.highlights ? (h === null || h === undefined ? null : Number(h)) : null, id: extra(withCats(builder(), r)).createSelectionId(), tips: tipsAt(tipCols, r, culture) };
            cells.push(cell); cats[r].items.push(cell.i); series[s].items.push(cell.i);
        }
    };
    if (seriesField) {
        const sname = nameFormatter(values.source.format, culture);
        values.grouped().forEach(g => {
            const col = g.values.find(c => !!(c.source.roles && c.source.roles["values"])); if (!col) return;
            const id = builder().withSeries(values, g).createSelectionId();
            series.push({ key: "g" + String(g.name), name: sname(g.name as powerbi.PrimitiveValue), color: fillOf(g.objects) || "", selector: id.getSelector(), id, items: [] });
            formats.push(col.source.format);
            add(col, series.length - 1, g.values.filter(c => !!(c.source.roles && c.source.roles["tooltips"])), b => b.withSeries(values, g));
        });
    } else {
        const tipCols = valsOf(cat, "tooltips");
        valsOf(cat, "values").forEach(col => {
            const q = col.source.queryName as string, id = builder().withMeasure(q).createSelectionId();
            series.push({ key: "m" + q, name: col.source.displayName, color: fillOf(col.source.objects) || "", selector: { metadata: q }, id, items: [] });
            formats.push(col.source.format);
            add(col, series.length - 1, tipCols, b => b.withMeasure(q));
        });
    }
    if (!series.length || !cells.length) return null;
    const grid = cats.map(() => new Array<Cell | undefined>(series.length));
    cells.forEach(c => { grid[c.c][c.s] = c; });
    const roles = dv && dv.metadata && dv.metadata.dataRoles;
    const hasHl = cells.some(c => c.hlv !== null) || valsOf(cat, "values").some(c => !!c.highlights);
    return {
        cats, series, cells, grid, catTitle: catCols.map(c => c.source.displayName).join(" › "), serTitle: seriesField ? values.source.displayName : "",
        byMeasure: !seriesField, format: formats[0], formats,
        colored: colorCats && (series.length === 1 || (measuresAreParts && !seriesField)) ? cats : series,
        drill: (roles && roles.drillableRoles && roles.drillableRoles["category"]) || [], drillDisabled: !!(roles && roles.isDrillDisabled), levelNames: catCols.map(c => c.source.displayName),
        ids: cells.map(c => c.id), hl: hasHl ? new Set(cells.filter(c => c.hlv !== null && c.hlv !== 0).map(c => c.i)) : null, rows: n
    };
}
/** what a category label selects (an axis label, a funnel stage name): the whole category */
export function catTarget(m: Model, ci: number): Target {
    const ct = m.cats[ci];
    return { key: "c:" + ct.key, items: ct.items, ids: ct.id ? [ct.id] : [], tip: () => [{ displayName: m.catTitle, value: ct.name }] };
}
