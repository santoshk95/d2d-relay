/*
 * Data model for Atlas Scatter: points (Details × Legend × Play axis, with
 * X, Y and Size) for scatter, bubble and dot plot, or tasks (Task, Phase,
 * Start, End, Owner, % complete) for a Gantt chart.
 */
import powerbi from "powerbi-visuals-api";
import { nameFormatter } from "./common/util";
import { catsOf, valsOf, fillOf, numOf, tipsAt, hlValue, Tip, Cat } from "./common/data";
import { BaseModel, Colored } from "./common/family";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface Pt { i: number; name: string; group: number; xcat: string; frame: string; x: number; y: number; size: number; id: ISelectionId; tips: Tip[]; hl: boolean | null; }
export interface Task { i: number; name: string; group: number; start: Date | null; end: Date | null; owner: string; progress: number; id: ISelectionId; tips: Tip[]; }
export interface Model extends BaseModel {
    pts: Pt[]; tasks: Task[]; groups: Colored[]; frames: string[]; xcats: string[];
    names: { details: string; legend: string; x: string; y: string; size: string; play: string; xcat: string; task: string };
    fmt: { x?: string; y?: string; size?: string }; hasSize: boolean; hasOwner: boolean; hasProgress: boolean;
}

function asDate(v: powerbi.PrimitiveValue): Date | null {
    if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) { const d = new Date(v.length === 10 ? v + "T00:00:00" : v); return isNaN(d.getTime()) ? null : d; }
    return null;
}

export function readModel(dv: powerbi.DataView | undefined, host: powerbi.extensibility.visual.IVisualHost): Model | null {
    const cat = dv && dv.categorical;
    if (!cat) return null;
    const one = (r: string): Cat | undefined => catsOf(cat, r)[0];
    const det = one("details"), leg = one("legend"), xc = one("xCategory"), play = one("play"), task = one("task"), st = one("start"), en = one("end"), own = one("owner");
    const xv = valsOf(cat, "x")[0], yv = valsOf(cat, "y")[0], sv = valsOf(cat, "size")[0], pv = valsOf(cat, "progress")[0], tips = valsOf(cat, "tooltips");
    const cols = cat.categories || [], n = cols.length ? cols[0].values.length : (cat.values && cat.values.length ? cat.values[0].values.length : 0), culture = host.locale;
    const nm = (c: Cat | undefined) => (c ? nameFormatter(c.source.format, culture) : null);
    const fDet = nm(det), fLeg = nm(leg), fXc = nm(xc), fPlay = nm(play), fTask = nm(task), fOwn = nm(own);
    const rowId = (r: number) => { const b = host.createSelectionIdBuilder(); cols.forEach(c => b.withCategory(c, r)); return b.createSelectionId(); };
    /* legend groups (or phases) */
    const groups: Colored[] = [], gIndex = new Map<string, number>();
    const groupOf = (r: number) => {
        if (!leg) return 0;
        const k = String(leg.values[r]); let gi = gIndex.get(k);
        if (gi === undefined) {
            gi = groups.length; gIndex.set(k, gi);
            const id = host.createSelectionIdBuilder().withCategory(leg, r).createSelectionId();
            groups.push({ key: "g" + k, name: (fLeg as (v: powerbi.PrimitiveValue) => string)(leg.values[r]), color: fillOf(leg.objects && leg.objects[r]) || "", selector: id.getSelector(), id, items: [] });
        }
        return gi;
    };
    if (!leg) groups.push({ key: "all", name: yv ? yv.source.displayName : task ? task.source.displayName : "Points", color: "", selector: yv ? { metadata: yv.source.queryName as string } : null, id: null, items: [] });
    const pts: Pt[] = [], tasks: Task[] = [], frames: string[] = [], xcats: string[] = [];
    if (task && st) {
        for (let r = 0; r < n; r++) {
            const s0 = asDate(st.values[r]); if (!s0) continue;
            const g = groupOf(r), e0 = en ? asDate(en.values[r]) : null, p = pv ? numOf(pv.values[r]) : NaN;
            const tk: Task = { i: tasks.length, name: (fTask as (v: powerbi.PrimitiveValue) => string)(task.values[r]), group: g, start: s0, end: e0, owner: fOwn && own ? fOwn(own.values[r]) : "", progress: isNaN(p) ? NaN : p > 1 ? p / 100 : p, id: rowId(r), tips: tipsAt(tips, r, culture) };
            tasks.push(tk); groups[g].items.push(tk.i);
        }
    } else if (yv && (xv || xc)) {
        for (let r = 0; r < n; r++) {
            /* under a cross-highlight a point moves to its highlighted values; a point with nothing selected stays (dimmed) */
            const hv = (c: powerbi.DataViewValueColumn, raw: number) => (isNaN(raw) ? raw : hlValue(raw, c.highlights ? c.highlights[r] : undefined, !!c.highlights, "keep"));
            const x = xv ? hv(xv, numOf(xv.values[r])) : NaN, y = hv(yv, numOf(yv.values[r])); if (isNaN(y) || (xv && isNaN(x))) continue;
            const g = groupOf(r), frame = fPlay && play ? fPlay(play.values[r]) : "", xcat = fXc && xc ? fXc(xc.values[r]) : "";
            if (play && !frames.includes(frame)) frames.push(frame);
            if (xc && !xcats.includes(xcat)) xcats.push(xcat);
            const h = yv.highlights ? yv.highlights[r] : undefined;
            const p: Pt = { i: pts.length, name: fDet && det ? fDet(det.values[r]) : fLeg && leg ? fLeg(leg.values[r]) : String(r + 1), group: g, xcat, frame, x, y, size: sv ? hv(sv, numOf(sv.values[r])) : NaN, id: rowId(r), tips: tipsAt(tips, r, culture), hl: yv.highlights ? h !== null && h !== undefined && h !== 0 : null };
            pts.push(p); groups[g].items.push(p.i);
        }
    }
    if (!pts.length && !tasks.length) return null;
    const used = groups.filter(g => g.items.length);
    return {
        pts, tasks, groups: used, frames, xcats,
        names: { details: det ? det.source.displayName : "", legend: leg ? leg.source.displayName : "", x: xv ? xv.source.displayName : "", y: yv ? yv.source.displayName : "", size: sv ? sv.source.displayName : "", play: play ? play.source.displayName : "", xcat: xc ? xc.source.displayName : "", task: task ? task.source.displayName : "" },
        fmt: { x: xv ? xv.source.format : undefined, y: yv ? yv.source.format : undefined, size: sv ? sv.source.format : undefined }, hasSize: !!sv, hasOwner: !!own, hasProgress: !!pv,
        colored: used, ids: pts.length ? pts.map(p => p.id) : tasks.map(tk => tk.id),
        hl: pts.some(p => p.hl !== null) ? new Set(pts.filter(p => p.hl).map(p => p.i)) : null, rows: n
    };
}
