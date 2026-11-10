/*
 * Data model for Atlas Time: one row per Time (× Rows) value, with a cell
 * per Legend series. Dates are recognized so the calendar and timeline can
 * lay out days, weeks and months.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, fillOf, numOf, tipsAt, hlValue, hlModeOf, Tip } from "./common/data";
import { BaseModel, Colored } from "./common/family";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface TCell { i: number; r: number; s: number; v: number; hlv: number | null; id: ISelectionId; tips: Tip[]; }
export interface TRow { r: number; raw: powerbi.PrimitiveValue; date: Date | null; name: string; rowRaw: powerbi.PrimitiveValue; rowName: string; cells: (TCell | undefined)[]; total: number; }
export interface Model extends BaseModel {
    points: TRow[]; cells: TCell[]; series: Colored[];
    timeName: string; rowsName: string; seriesName: string; valueName: string; format?: string;
    isDate: boolean; hasRows: boolean; seriesField: boolean;
    /** table and column of the Time field, for the timeline slicer's filter */
    target: { table: string; column: string } | null;
}

/** a date from a Power BI value (Date object, ISO text or year number); null otherwise */
export function asDate(v: powerbi.PrimitiveValue): Date | null {
    if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) { const d = new Date(v.length === 10 ? v + "T00:00:00" : v); return isNaN(d.getTime()) ? null : d; }
    return null;
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values || !cat.values.length) return null;
    const timeCol = catsOf(cat, "time")[0], rowsCol = catsOf(cat, "rows")[0];
    if (!timeCol) return null;
    const culture = host.locale, values = cat.values, seriesField = !!values.source, n = timeCol.values.length;
    const hlMode = hlModeOf(Array.from(values));
    const tname = nameFormatter(timeCol.source.format, culture), rname = rowsCol ? nameFormatter(rowsCol.source.format, culture) : null;
    const builder = () => { const b = host.createSelectionIdBuilder(); return b; };
    const base = (r: number) => { const b = builder().withCategory(timeCol, r); if (rowsCol) b.withCategory(rowsCol, r); return b; };
    const points: TRow[] = [];
    let dates = 0;
    for (let r = 0; r < n; r++) {
        const raw = timeCol.values[r], date = asDate(raw); if (date) dates++;
        points.push({ r, raw, date, name: tname(raw), rowRaw: rowsCol ? rowsCol.values[r] : null, rowName: rname ? rname(rowsCol.values[r]) : "", cells: [], total: 0 });
    }
    const series: Colored[] = [], cells: TCell[] = [];
    const groups = values.grouped();
    const sname = seriesField ? nameFormatter(values.source.format, culture) : null;
    let format: string | undefined, valueName = "";
    groups.forEach(g => {
        const col = g.values.find(c => !!(c.source.roles && c.source.roles["values"])); if (!col) return;
        const tipCols = g.values.filter(c => !!(c.source.roles && c.source.roles["tooltips"]));
        const s = series.length;
        const id = seriesField ? builder().withSeries(values, g).createSelectionId() : builder().withMeasure(col.source.queryName as string).createSelectionId();
        series.push({ key: seriesField ? "g" + String(g.name) : "m", name: seriesField && sname ? sname(g.name as powerbi.PrimitiveValue) : col.source.displayName, color: fillOf(seriesField ? g.objects : col.source.objects) || "", selector: seriesField ? id.getSelector() : { metadata: col.source.queryName as string }, id, items: [] });
        format = format || col.source.format; valueName = valueName || col.source.displayName;
        for (let r = 0; r < n; r++) {
            const raw = numOf(col.values[r]); if (isNaN(raw)) continue;
            /* under a cross-highlight each period shows its highlighted part, as a filter would */
            const v = hlValue(raw, col.highlights ? col.highlights[r] : undefined, !!col.highlights, hlMode);
            const h = col.highlights ? col.highlights[r] : undefined, b = base(r);
            if (seriesField) b.withSeries(values, g);
            const cell: TCell = { i: cells.length, r, s, v, hlv: col.highlights ? (h === null || h === undefined ? null : Number(h)) : null, id: b.createSelectionId(), tips: tipsAt(tipCols, r, culture) };
            cells.push(cell); points[r].cells[s] = cell; points[r].total += v; series[s].items.push(cell.i);
        }
    });
    if (!cells.length) return null;
    const q = String(timeCol.source.queryName || ""), dot = q.indexOf(".");
    /* a date hierarchy level ("Date.Date.Variation...") can't be filtered as a plain column */
    const target = dot > 0 && !/\.Variation\./.test(q) ? { table: q.slice(0, dot), column: q.slice(dot + 1) } : null;
    const hl = cells.some(c => c.hlv !== null) ? new Set(cells.filter(c => c.hlv !== null && c.hlv !== 0).map(c => c.i)) : null;
    return {
        points, cells, series, timeName: timeCol.source.displayName, rowsName: rowsCol ? rowsCol.source.displayName : "", seriesName: seriesField ? values.source.displayName : "",
        valueName, format, isDate: dates > n * 0.8, hasRows: !!rowsCol, seriesField, target,
        colored: series, ids: cells.map(c => c.id), hl, rows: n
    };
}
