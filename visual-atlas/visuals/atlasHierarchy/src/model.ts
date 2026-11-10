/*
 * Data model for Atlas Hierarchy: one tree, built either from Levels
 * (Category › Subcategory › Product, one path per row) or from ID and
 * Parent ID (an org chart, one node per row). Every node knows its total,
 * the rows under it (for selection) and its top-level branch (for color).
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, valsOf, fillOf, numOf, tipsAt, hlValue, hlModeOf, Tip } from "./common/data";
import { BaseModel, Colored } from "./common/family";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface HNode {
    key: string; name: string; depth: number; parent: HNode | null; children: HNode[];
    /** value of the node's own row(s); total = own + children */
    own: number; total: number;
    /** value-weighted color measure (NaN when there is none) */
    colorV: number;
    /** rows in the subtree (selection items) and the node's own rows */
    items: number[]; rows: number[];
    id: ISelectionId | null; branch: number; tips: Tip[];
    /** number of nodes below (team size in an org chart) */
    count: number;
}
export interface Model extends BaseModel {
    root: HNode; nodes: HNode[]; levels: number; levelNames: string[]; org: boolean;
    branches: Colored[]; levelColors: Colored[];
    valueName: string; format?: string; hasValue: boolean;
    colorName: string; colorFormat?: string; hasColor: boolean;
}

function node(key: string, name: string, depth: number, parent: HNode | null): HNode {
    return { key, name, depth, parent, children: [], own: 0, total: 0, colorV: NaN, items: [], rows: [], id: null, branch: 0, tips: [], count: 0 };
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost, colorBy: string): Model | null {
    const cat = dv && dv.categorical;
    if (!cat || !cat.categories || !cat.categories.length) return null;
    const culture = host.locale, builder = () => host.createSelectionIdBuilder();
    const levelCols = catsOf(cat, "levels"), idCol = catsOf(cat, "nodeId")[0], parentCol = catsOf(cat, "parentId")[0], labelCol = catsOf(cat, "label")[0];
    const valCol = valsOf(cat, "values")[0], colCol = valsOf(cat, "colorValue")[0], tipCols = valsOf(cat, "tooltips");
    const org = !!idCol && !!parentCol;
    if (!org && !levelCols.length) return null;
    const n = cat.categories[0].values.length;
    const allCols = org ? [idCol] : levelCols;
    const rowId = (r: number) => { const b = builder(); allCols.forEach(c => b.withCategory(c, r)); return b.createSelectionId(); };
    const ids: ISelectionId[] = [], hlMode = valCol ? hlModeOf([valCol]) : "keep", valueAt = (r: number) => (valCol ? hlValue(numOf(valCol.values[r]), valCol.highlights ? valCol.highlights[r] : undefined, !!valCol.highlights, hlMode) : 1), colorAt = (r: number) => (colCol ? numOf(colCol.values[r]) : NaN);
    const colorSum = new Map<HNode, { w: number; s: number }>();
    for (let r = 0; r < n; r++) ids.push(rowId(r));

    const root = node("", "All", 0, null), nodes: HNode[] = [];
    if (!org) {
        const names = levelCols.map(c => nameFormatter(c.source.format, culture)), map = new Map<string, HNode>();
        for (let r = 0; r < n; r++) {
            let cur = root, key = "";
            for (let k = 0; k < levelCols.length; k++) {
                const raw = levelCols[k].values[r];
                if (raw === null || raw === undefined || raw === "") break;
                key += "\u001f" + String(raw);
                let nd = map.get(key);
                if (!nd) {
                    nd = node(key, names[k](raw), k + 1, cur); map.set(key, nd); cur.children.push(nd); nodes.push(nd);
                    const b = builder(); for (let j = 0; j <= k; j++) b.withCategory(levelCols[j], r);
                    nd.id = b.createSelectionId();
                }
                cur = nd;
            }
            if (cur === root) continue;
            const v = valueAt(r);
            cur.own += isNaN(v) ? 0 : Math.max(0, v); cur.rows.push(r); cur.tips = tipsAt(tipCols, r, culture);
            const cv = colorAt(r); if (!isNaN(cv)) { const w = isNaN(v) || v <= 0 ? 1 : v, e = colorSum.get(cur) || { w: 0, s: 0 }; e.w += w; e.s += w * cv; colorSum.set(cur, e); }
        }
    } else {
        const idName = nameFormatter(idCol.source.format, culture), lab = labelCol ? nameFormatter(labelCol.source.format, culture) : null;
        const byId = new Map<string, HNode>();
        for (let r = 0; r < n; r++) {
            const raw = idCol.values[r]; if (raw === null || raw === undefined || raw === "") continue;
            const key = String(raw); if (byId.has(key)) continue;
            const nd = node(key, lab ? lab(labelCol.values[r]) : idName(raw), 0, null);
            nd.id = ids[r]; nd.rows.push(r); nd.tips = tipsAt(tipCols, r, culture);
            const v = valueAt(r); nd.own = isNaN(v) ? 0 : Math.max(0, v);
            const cv = colorAt(r); if (!isNaN(cv)) colorSum.set(nd, { w: 1, s: cv });
            byId.set(key, nd); nodes.push(nd);
        }
        nodes.forEach(nd => {
            const r = nd.rows[0], pr = parentCol.values[r], p = pr === null || pr === undefined || pr === "" ? undefined : byId.get(String(pr));
            /* a parent that is missing, or a cycle back to this node, makes the node a top node */
            let up = p, loop = false; for (let guard = 0; up && guard < 10000; guard++) { if (up === nd) { loop = true; break; } const q = parentCol.values[up.rows[0]]; up = q === null || q === undefined ? undefined : byId.get(String(q)); }
            const par = p && !loop ? p : root;
            nd.parent = par; par.children.push(nd);
        });
    }
    if (!nodes.length) return null;
    /* a single top node becomes the root (the CEO of an org chart) */
    let top = root;
    if (org && root.children.length === 1) { top = root.children[0]; top.parent = null; }
    const fix = (nd: HNode, depth: number) => { nd.depth = depth; nd.children.forEach(ch => fix(ch, depth + 1)); };
    fix(top, 0);
    /* totals, subtree rows, counts and weighted colors, bottom up */
    const post = (nd: HNode): { w: number; s: number } => {
        let total = nd.own, items = nd.rows.slice(), count = 0;
        const acc = colorSum.get(nd) ? { ...(colorSum.get(nd) as { w: number; s: number }) } : { w: 0, s: 0 };
        nd.children.forEach(ch => { const a = post(ch); total += ch.total; items = items.concat(ch.items); count += 1 + ch.count; acc.w += a.w; acc.s += a.s; });
        nd.total = total; nd.items = items; nd.count = count; nd.colorV = acc.w ? acc.s / acc.w : NaN;
        return acc;
    };
    post(top);
    /* top-level branches carry the palette colors (and the Colors card pickers) */
    const levelCol0 = levelCols[0];
    const branches: Colored[] = top.children.map(ch => {
        const r = ch.items[0], over = levelCol0 && r !== undefined ? fillOf(levelCol0.objects && levelCol0.objects[r]) : r !== undefined && idCol ? fillOf(idCol.objects && idCol.objects[r]) : undefined;
        return { key: ch.key, name: ch.name, color: over || "", selector: ch.id ? ch.id.getSelector() : null, id: ch.id, items: ch.items };
    });
    const setBranch = (nd: HNode, b: number) => { nd.branch = b; nd.children.forEach(ch => setBranch(ch, b)); };
    top.children.forEach((ch, i) => setBranch(ch, i));
    let maxDepth = 0; const walk = (nd: HNode) => { maxDepth = Math.max(maxDepth, nd.depth); nd.children.forEach(walk); }; walk(top);
    const levelNames = org ? Array.from({ length: maxDepth }, (_, k) => "Level " + (k + 1)) : levelCols.map(c => c.source.displayName);
    const levelColors: Colored[] = levelNames.map((nm, k) => ({ key: "L" + k, name: nm, color: "", selector: null, id: null, items: [] }));
    const hasHl = !!(valCol && valCol.highlights);
    return {
        root: top, nodes, levels: Math.max(1, maxDepth), levelNames, org, branches, levelColors,
        valueName: valCol ? valCol.source.displayName : "Count", format: valCol ? valCol.source.format : "#,0", hasValue: !!valCol,
        colorName: colCol ? colCol.source.displayName : "", colorFormat: colCol ? colCol.source.format : undefined, hasColor: !!colCol,
        colored: colorBy === "level" ? levelColors : branches, ids,
        hl: hasHl ? new Set(Array.from({ length: n }, (_, r) => r).filter(r => { const h = (valCol as powerbi.DataViewValueColumn).highlights as powerbi.PrimitiveValue[]; return h[r] !== null && h[r] !== undefined && h[r] !== 0; })) : null,
        rows: n
    };
}
