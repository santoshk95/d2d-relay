/*
 * Data model for Atlas Finance: the shared category × series matrix for
 * Values (waterfall, ribbon, funnel) plus one candle per category from the
 * Open, High, Low, Close and Volume measures.
 */
import powerbi from "powerbi-visuals-api";
import { Model as Matrix, readModel as readMatrix } from "./common/matrix";
import { catsOf, valsOf, numOf, tipsAt, Tip } from "./common/data";
import { nameFormatter } from "./common/util";
import { BaseModel } from "./common/family";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface Candle { i: number; name: string; o: number; h: number; l: number; c: number; vol: number; id: ISelectionId; tips: Tip[]; hl: boolean | null; }
export interface Model extends BaseModel {
    mx: Matrix | null; candles: Candle[]; catTitle: string; priceFormat?: string; volumeFormat?: string; hasVolume: boolean;
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost, colorCats: boolean, chartType: string): Model | null {
    const cat = dv && dv.categorical;
    const catCol = cat ? catsOf(cat, "category")[0] : undefined;
    if (!cat || !catCol) return null;
    const mx = readMatrix(dv, host, colorCats);
    const o = valsOf(cat, "open")[0], h = valsOf(cat, "high")[0], l = valsOf(cat, "low")[0], c = valsOf(cat, "close")[0], v = valsOf(cat, "volume")[0];
    const candles: Candle[] = [];
    if (c && (o || h || l)) {
        const nm = nameFormatter(catCol.source.format, host.locale), tipCols = valsOf(cat, "tooltips");
        for (let r = 0; r < catCol.values.length; r++) {
            const cl = numOf(c.values[r]); if (isNaN(cl)) continue;
            const op = o ? numOf(o.values[r]) : cl, hi = h ? numOf(h.values[r]) : Math.max(op, cl), lo = l ? numOf(l.values[r]) : Math.min(op, cl);
            const hlv = c.highlights ? c.highlights[r] : undefined;
            candles.push({ i: candles.length, name: nm(catCol.values[r]), o: isNaN(op) ? cl : op, h: isNaN(hi) ? Math.max(op, cl) : hi, l: isNaN(lo) ? Math.min(op, cl) : lo, c: cl, vol: v ? numOf(v.values[r]) : NaN,
                id: host.createSelectionIdBuilder().withCategory(catCol, r).createSelectionId(), tips: tipsAt(tipCols, r, host.locale), hl: c.highlights ? hlv !== null && hlv !== undefined : null });
        }
    }
    if (!mx && !candles.length) return null;
    /* selection items are candles on a candlestick, matrix cells otherwise */
    const useCandles = !mx || (chartType === "candlestick" && candles.length > 0);
    return {
        mx, candles, catTitle: catCol.source.displayName, priceFormat: c ? c.source.format : undefined, volumeFormat: v ? v.source.format : undefined, hasVolume: !!v,
        colored: mx && !useCandles ? mx.colored : [], ids: useCandles ? candles.map(x => x.id) : (mx as Matrix).ids,
        hl: useCandles ? (candles.some(x => x.hl !== null) ? new Set(candles.filter(x => x.hl).map(x => x.i)) : null) : (mx as Matrix).hl,
        rows: catCol.values.length
    };
}
