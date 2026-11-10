/*
 * Data model for Atlas Text: words (or whole phrases) with a weight, the
 * rows they came from (for selection), their most common topic and their
 * weighted color value. Free text is split into words and common English
 * words are removed.
 */
import powerbi from "powerbi-visuals-api";
import { catsOf, valsOf, fillOf, numOf, hlValue, hlModeOf } from "./common/data";
import { BaseModel, Colored } from "./common/family";
import { TextSettings } from "./settings";
import { val } from "./common/cards";

const STOP = new Set(("a about above after again against all am an and any are as at be because been before being below between both but by can could did do does doing down during each few for from further had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too under until up very was we were what when where which while who whom why will with would you your yours yourself yourselves " +
    "also get got really much many one two lot just like still even well back way thing things im ive dont didnt cant wont isnt its thats theres though although made felt after again").split(" "));

export interface Word extends Colored { text: string; weight: number; rows: number[]; group: number; colorV: number; }
export interface Model extends BaseModel { words: Word[]; groups: Colored[]; textTitle: string; groupTitle: string; valueName: string; format?: string; hasColor: boolean; colorName: string; }

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost, s: TextSettings): Model | null {
    const cat = dv && dv.categorical;
    const textCol = cat ? catsOf(cat, "category")[0] : undefined;
    if (!cat || !textCol) return null;
    const groupCol = catsOf(cat, "group")[0], wCol = valsOf(cat, "values")[0], cCol = valsOf(cat, "colorValue")[0];
    const hlMode = wCol ? hlModeOf([wCol]) : "keep";
    const n = textCol.values.length, texts = textCol.values.map(v => (v === null || v === undefined ? "" : String(v)));
    const W = s.words, mode = val(W.split), lower = W.lowercase.value, minLen = Math.max(1, W.minLength.value);
    const extra = new Set(W.extraStopWords.value.split(",").map(x => x.trim().toLowerCase()).filter(x => x));
    const avgWords = texts.reduce((a, t) => a + t.split(/\s+/).filter(x => x).length, 0) / Math.max(1, n);
    const split = mode === "words" || (mode === "auto" && avgWords > 3);
    /* groups (topics) */
    const groups: Colored[] = [], gIndex = new Map<string, number>();
    const groupOf = (r: number) => {
        if (!groupCol) return -1;
        const k = String(groupCol.values[r]);
        let gi = gIndex.get(k);
        if (gi === undefined) {
            gi = groups.length; gIndex.set(k, gi);
            const id = host.createSelectionIdBuilder().withCategory(groupCol, r).createSelectionId();
            groups.push({ key: "g" + k, name: k, color: fillOf(groupCol.objects && groupCol.objects[r]) || "", selector: id.getSelector(), id, items: [] });
        }
        groups[gi].items.push(r);
        return gi;
    };
    const map = new Map<string, { text: string; weight: number; rows: number[]; gcount: Map<number, number>; cw: number; cs: number }>();
    for (let r = 0; r < n; r++) {
        const raw = texts[r]; if (!raw) continue;
        /* under a cross-highlight a word is sized by its highlighted part (words with none drop out, as with a filter) */
        const w = wCol ? hlValue(numOf(wCol.values[r]), wCol.highlights ? wCol.highlights[r] : undefined, !!wCol.highlights, hlMode) : 1; if (isNaN(w) || w <= 0) continue;
        const gi = groupOf(r), cv = cCol ? numOf(cCol.values[r]) : NaN;
        const tokens = split ? (raw.match(/[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu) || []) : [raw.trim()];
        tokens.forEach(tok => {
            let word = tok.replace(/['’]s$/u, "");
            if (lower) word = word.toLowerCase();
            const key = word.toLowerCase().replace(/['’]/g, "");
            if (split && (key.length < minLen || (W.stopWords.value && STOP.has(key)) || /^\d+$/.test(key))) return;
            if (extra.has(key)) return;
            let e = map.get(key);
            if (!e) { e = { text: word, weight: 0, rows: [], gcount: new Map(), cw: 0, cs: 0 }; map.set(key, e); }
            e.weight += w; if (e.rows[e.rows.length - 1] !== r) e.rows.push(r);
            if (gi >= 0) e.gcount.set(gi, (e.gcount.get(gi) || 0) + w);
            if (!isNaN(cv)) { e.cw += w; e.cs += w * cv; }
        });
    }
    const words: Word[] = [...map.entries()].sort((a, b) => b[1].weight - a[1].weight || a[0].localeCompare(b[0])).slice(0, Math.max(5, W.maxWords.value)).map(([key, e]) => {
        let g = -1, best = -1; e.gcount.forEach((c, gi) => { if (c > best) { best = c; g = gi; } });
        return { key, name: e.text, text: e.text, color: "", selector: null, id: null, items: e.rows, weight: e.weight, rows: e.rows, group: g, colorV: e.cw ? e.cs / e.cw : NaN };
    });
    if (!words.length) return null;
    const ids = Array.from({ length: n }, (_, r) => { const b = host.createSelectionIdBuilder().withCategory(textCol, r); if (groupCol) b.withCategory(groupCol, r); return b.createSelectionId(); });
    const by = val(s.wcolor.colorBy);
    const single: Colored = { key: "all", name: wCol ? wCol.source.displayName : "Words", color: wCol ? fillOf(wCol.source.objects) || "" : "", selector: wCol ? { metadata: wCol.source.queryName as string } : null, id: null, items: [] };
    return {
        words, groups, textTitle: textCol.source.displayName, groupTitle: groupCol ? groupCol.source.displayName : "", valueName: wCol ? wCol.source.displayName : "Count", format: wCol ? wCol.source.format : "#,0",
        hasColor: !!cCol, colorName: cCol ? cCol.source.displayName : "",
        colored: by === "group" && groups.length ? groups : by === "single" ? [single] : words,
        ids, hl: wCol && wCol.highlights ? new Set(Array.from({ length: n }, (_, r) => r).filter(r => { const h = (wCol.highlights as powerbi.PrimitiveValue[])[r]; return h !== null && h !== undefined; })) : null, rows: n
    };
}
