/*
 * Data model for Period Hierarchy Slicer: the rows of the Levels fields (Year, Month, Week …) become a
 * tree, one node per distinct value under its parent, in the order Power BI sends them (each level's
 * own sort). The optional Values measure is summed up the tree.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, valsOf, numOf } from "./common/data";
import { BaseModel, Colored } from "./common/family";

export interface TNode {
    i: number; key: string; level: number; raw: powerbi.PrimitiveValue; name: string;
    value: number; parent: TNode | null; children: TNode[];
}
export interface Level { name: string; target: { table: string; column: string } | null; }
export interface Model extends BaseModel {
    roots: TNode[]; nodes: TNode[]; levels: Level[];
    hasValues: boolean; valueName: string; format?: string;
}

/** a value as a filter / lookup key: dates as ISO text, everything else as text */
export const keyOf = (v: powerbi.PrimitiveValue): string => (v instanceof Date ? v.toISOString() : v === null || v === undefined ? "" : String(v));

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat) return null;
    const cols = catsOf(cat, "levels");
    if (!cols.length || !cols[0].values.length) return null;
    const vcol = valsOf(cat, "values")[0];
    const culture = host.locale, n = cols[0].values.length;
    const names = cols.map(c => nameFormatter(c.source.format, culture));
    const levels: Level[] = cols.map(c => {
        const q = String(c.source.queryName || ""), dot = q.indexOf(".");
        /* a date hierarchy level ("Date.Date.Variation...") can't be filtered as a plain column */
        return { name: c.source.displayName, target: dot > 0 && !/\.Variation\./.test(q) ? { table: q.slice(0, dot), column: q.slice(dot + 1) } : null };
    });
    const roots: TNode[] = [], nodes: TNode[] = [], index = new Map<string, TNode>();
    for (let r = 0; r < n; r++) {
        const v = vcol ? numOf(vcol.values[r]) : NaN;
        let parent: TNode | null = null, path = "";
        for (let l = 0; l < cols.length; l++) {
            const raw = cols[l].values[r];
            if (raw === null || raw === undefined || raw === "") break;
            path += "\u0001" + keyOf(raw);
            let node = index.get(path);
            if (!node) {
                node = { i: nodes.length, key: path, level: l, raw, name: names[l](raw), value: 0, parent, children: [] };
                index.set(path, node); nodes.push(node);
                (parent ? parent.children : roots).push(node);
            }
            if (!isNaN(v)) node.value += v;
            parent = node;
        }
    }
    if (!nodes.length) return null;
    const colored: Colored[] = [{ key: "sel", name: "Selection", color: "", selector: null, id: null, items: [] }];
    return {
        roots, nodes, levels, hasValues: !!vcol, valueName: vcol ? vcol.source.displayName : "", format: vcol ? vcol.source.format : undefined,
        colored, ids: [], hl: null, rows: n
    };
}
