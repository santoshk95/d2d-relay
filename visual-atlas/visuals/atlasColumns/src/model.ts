/*
 * Data model for Atlas Columns: categories (one or more hierarchy
 * levels), series (legend values or measures) and one point per
 * category and series, read from the categorical data view.
 */
import powerbi from "powerbi-visuals-api";
import { formatter, nameFormatter } from "./common/util";
import ISelectionId = powerbi.visuals.ISelectionId;
import DataView = powerbi.DataView;

export interface Cat {
    i: number; key: string; path: string[]; label: string;
    id: ISelectionId | null; selector: powerbi.data.Selector | null;
    /** color set in the Format pane or by a conditional-formatting rule */
    override?: string;
    /** palette color when each category gets its own color */
    color?: string;
}
export interface Ser {
    i: number; key: string; name: string; color: string;
    id: ISelectionId; selector: powerbi.data.Selector;
    format?: string; measure: string;
}
export interface Tip { name: string; value: string; }
export interface Pt {
    c: number; s: number; v: number; hl: number | null;
    id: ISelectionId; tips: Tip[];
    /* layout, in value space */
    a?: number; b?: number; ha?: number; hb?: number; share?: number;
    base?: boolean; outer?: boolean;
}
export interface Model {
    cats: Cat[]; series: Ser[]; pts: Pt[];
    levels: number; levelNames: string[];
    valueNames: string[]; legendTitle: string; seriesField: boolean;
    format?: string; highlights: boolean;
    drill: powerbi.DrillType[]; drillDisabled: boolean;
}
type Builder = powerbi.visuals.ISelectionIdBuilder;

const fillOf = (o: powerbi.DataViewObjects | undefined): string | undefined => {
    const f = o && o["dataColors"] && (o["dataColors"]["fill"] as powerbi.Fill);
    return f && f.solid && f.solid.color ? f.solid.color : undefined;
};

export function readModel(dv: DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.values || !cat.values.length) return null;
    const culture = host.locale;
    const catCols = (cat.categories || []).filter(c => c.source.roles && c.source.roles["category"]);
    const values = cat.values, grouped = values.grouped(), seriesField = !!values.source;
    const n = catCols.length ? catCols[0].values.length : 1;
    const isValue = (c: powerbi.DataViewValueColumn) => !!(c.source.roles && c.source.roles["values"]);
    const isTip = (c: powerbi.DataViewValueColumn) => !!(c.source.roles && c.source.roles["tooltips"]);
    const builder = (): Builder => host.createSelectionIdBuilder();
    const withCats = (b: Builder, r: number) => { catCols.forEach(c => b.withCategory(c, r)); return b; };

    /* categories, one path per row (several columns when a hierarchy is expanded) */
    const names = catCols.map(c => nameFormatter(c.source.format, culture));
    const cats: Cat[] = [];
    for (let r = 0; r < n; r++) {
        const path = catCols.length ? catCols.map((c, k) => names[k](c.values[r])) : [""];
        const id = catCols.length ? withCats(builder(), r).createSelectionId() : null;
        let override: string | undefined;
        catCols.forEach(c => { override = override || fillOf(c.objects && c.objects[r]); });
        cats.push({ i: r, key: path.join("\u001f"), path, label: path[path.length - 1], id, selector: id ? id.getSelector() : null, override });
    }

    /* series: legend values, or one series per measure */
    const series: Ser[] = [], pts: Pt[] = [];
    const tipsOf = (cols: powerbi.DataViewValueColumn[], r: number): Tip[] => cols.map(c => ({ name: c.source.displayName, value: formatter(c.source.format, 1, null, Number(c.values[r]), culture)(Number(c.values[r])) }));
    const addPoints = (col: powerbi.DataViewValueColumn, s: number, tipCols: powerbi.DataViewValueColumn[], finish: (b: Builder) => Builder) => {
        for (let r = 0; r < n; r++) {
            const raw = col.values[r];
            if (raw === null || raw === undefined || raw === "" || isNaN(Number(raw))) continue;
            const h = col.highlights ? col.highlights[r] : undefined;
            pts.push({ c: r, s, v: Number(raw), hl: col.highlights ? (h === null || h === undefined ? 0 : Number(h)) : null, id: finish(withCats(builder(), r)).createSelectionId(), tips: tipsOf(tipCols, r) });
        }
    };
    let format: string | undefined;
    if (seriesField) {
        const sname = nameFormatter(values.source.format, culture);
        grouped.forEach((g, k) => {
            const col = g.values.find(isValue); if (!col) return;
            const id = builder().withSeries(values, g).createSelectionId();
            const s = series.length;
            series.push({ i: s, key: "g" + String(g.name), name: sname(g.name as powerbi.PrimitiveValue), color: fillOf(g.objects) || "", id, selector: id.getSelector(), format: col.source.format, measure: col.source.displayName });
            format = format || col.source.format;
            addPoints(col, s, g.values.filter(isTip), b => b.withSeries(values, g));
            void k;
        });
    } else {
        const tipCols = values.filter(isTip);
        values.filter(isValue).forEach(col => {
            const s = series.length, q = col.source.queryName as string;
            const id = builder().withMeasure(q).createSelectionId();
            series.push({ i: s, key: "m" + q, name: col.source.displayName, color: fillOf(col.source.objects) || "", id, selector: { metadata: q }, format: col.source.format, measure: col.source.displayName });
            format = format || col.source.format;
            addPoints(col, s, tipCols, b => b.withMeasure(q));
        });
    }
    if (!series.length) return null;
    const roles = dv && dv.metadata && dv.metadata.dataRoles;
    return {
        cats, series, pts, levels: Math.max(1, catCols.length), levelNames: catCols.map(c => c.source.displayName),
        valueNames: series.length && !seriesField ? series.map(s => s.name) : [series[0].measure],
        legendTitle: seriesField ? values.source.displayName : "", seriesField, format,
        highlights: pts.some(p => p.hl !== null),
        drill: (roles && roles.drillableRoles && roles.drillableRoles["category"]) || [], drillDisabled: !!(roles && roles.isDrillDisabled)
    };
}
