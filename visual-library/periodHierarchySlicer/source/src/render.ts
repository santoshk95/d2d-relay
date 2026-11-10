/*
 * Drawing for Period Hierarchy Slicer: a dropdown header that says what is picked (click to open or close,
 * × to clear), and under it the tree: a chevron to expand each item, a check box (full when picked or
 * inside a pick, a dot when something below is picked), the name and an optional value. The tree scrolls
 * when it is taller than the visual.
 */
import powerbi from "powerbi-visuals-api";
import { Model, TNode, keyOf } from "./model";
import { Settings } from "./settings";
import { Ctx, SCROLLBAR } from "./common/family";
import { el, r1, trunc, textW } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr } from "./common/cards";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<Settings, Model>;
/** what is picked: values of one level */
export interface Pick { level: number; keys: Set<string>; }
export interface SlicerIO {
    pick: Pick | null; open: boolean; expanded: Set<string>;
    toggleOpen: () => void; toggleNode: (n: TNode) => void; choose: (n: TNode, multi: boolean) => void; clear: () => void;
}

/** a click or Enter / Space on an element */
function onAct(e: Element, act: (multi: boolean) => void) {
    (e as SVGElement).style.cursor = "pointer";
    e.addEventListener("click", ev => { ev.stopPropagation(); const me = ev as MouseEvent; act(me.ctrlKey || me.metaKey); });
    e.addEventListener("keydown", ev => { const ke = ev as KeyboardEvent; if (ke.key === "Enter" || ke.key === " ") { ke.preventDefault(); ke.stopPropagation(); act(ke.ctrlKey || ke.metaKey); } });
}

export function render(c: C, io: SlicerIO) {
    const { W, H, s, m, root, look, t } = c, CH = s.chart, SL = s.slicer, LB = s.labels;
    const pad = 4, rh = Math.max(16, CH.rowHeight.value), corner = Math.max(0, CH.corner.value);
    const fsz = Math.max(9, Math.min(14, Math.round(rh * 0.55)));
    const accent = t.hc ? t.ink : colorOr(SL.selColor, c.colorOf(m.colored[0]));
    const hh = Math.max(26, rh + 6);

    /* what is picked, what lies inside a pick, what has a pick below it */
    const picked = new Set<number>(), inside = new Set<number>(), partial = new Set<number>();
    const p = io.pick;
    if (p) m.nodes.forEach(n => { if (n.level === p.level && p.keys.has(keyOf(n.raw))) picked.add(n.i); });
    const down = (n: TNode) => n.children.forEach(ch => { inside.add(ch.i); down(ch); });
    m.nodes.forEach(n => { if (!picked.has(n.i)) return; down(n); for (let a = n.parent; a; a = a.parent) partial.add(a.i); });

    /* the rows the open tree shows */
    const rows: TNode[] = [];
    const walk = (list: TNode[]) => list.forEach(n => { rows.push(n); if (n.children.length && io.expanded.has(n.key)) walk(n.children); });
    if (io.open) walk(m.roots);
    const treeTop = pad + hh + 4, total = treeTop + rows.length * rh + pad;
    const tall = io.open && total > H + 0.5;
    if (tall) c.grow(W, total);
    const w = (tall ? W - SCROLLBAR : W) - pad * 2;
    if (w < 40 || H < hh) return;

    /* header: the dropdown */
    const names: string[] = [];
    m.nodes.forEach(n => { if (picked.has(n.i) && names.indexOf(n.name) < 0) names.push(n.name); });
    const summary = !names.length ? (SL.placeholder.value || "All periods") : names.length <= 2 ? names.join(", ") : `${names[0]} +${names.length - 1} more`;
    const sh = look.shadow();
    const head = el("g", { class: "mk", role: "button", "aria-expanded": io.open ? "true" : "false", "aria-label": `Period: ${summary}` }, root);
    el("rect", {
        x: pad, y: pad, width: r1(w), height: hh, rx: Math.min(corner, hh / 2),
        fill: t.surface, stroke: p ? accent : mix(t.ink, t.surface, 0.75), "stroke-width": p ? 1.5 : 1, filter: sh || undefined
    }, head);
    const clearW = p ? 20 : 0, chevX = pad + w - 14;
    const levelName = p ? m.levels[p.level].name : "";
    el("text", { x: pad + 10, y: r1(pad + hh / 2 + fsz * 0.36), "font-size": fsz, "font-weight": p ? 600 : 400, fill: p ? t.ink : t.text, class: "lbl" }, head, trunc(summary, w - 34 - clearW, fsz));
    el("path", { d: io.open ? `M${r1(chevX - 4)},${r1(pad + hh / 2 + 2)} l4,-4 l4,4` : `M${r1(chevX - 4)},${r1(pad + hh / 2 - 2)} l4,4 l4,-4`, fill: "none", stroke: t.axis, "stroke-width": 1.6, "stroke-linecap": "round" }, head);
    c.bind(head, { key: "head", items: [], ids: [], tip: () => [{ displayName: p ? levelName : "Period", value: names.length ? names.join(", ") : summary }] });
    onAct(head, () => io.toggleOpen());
    if (p) {
        const cx = chevX - 22, cy = pad + hh / 2;
        const x = el("g", { class: "mk", role: "button", "aria-label": "Clear the period filter" }, root);
        el("circle", { cx: r1(cx), cy: r1(cy), r: 8, fill: mix(accent, t.surface, 0.85) }, x);
        el("path", { d: `M${r1(cx - 3)},${r1(cy - 3)} l6,6 M${r1(cx + 3)},${r1(cy - 3)} l-6,6`, stroke: t.ink, "stroke-width": 1.4, "stroke-linecap": "round" }, x);
        c.bind(x, { key: "clear", items: [], ids: [], tip: () => [{ displayName: "Clear", value: "Show all periods" }] });
        onAct(x, () => io.clear());
    }
    if (!io.open) return;

    /* the tree */
    const showVals = m.hasValues && LB.show.value;
    const vfs = Math.max(6, Math.min(fsz, LB.fontSize.value + 1));
    const maxV = Math.max(0, ...m.nodes.map(n => Math.abs(n.value)));
    const fmtL = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, maxV, c.culture);
    const fmtT = formatter(m.format, 1, null, 0, c.culture);
    const valW = showVals ? Math.max(...m.nodes.map(n => textW(fmtL(n.value), vfs))) + 8 : 0;
    const tree = el("g", { role: "tree" }, root);
    const indent = 14, box = Math.min(12, rh - 8);
    rows.forEach((n, k) => {
        const y = treeTop + k * rh, cy = y + rh / 2, x0 = pad + 4 + n.level * indent;
        const isPicked = picked.has(n.i), isIn = inside.has(n.i), isPart = partial.has(n.i);
        const g = el("g", { class: "mk" + (c.io.on(n.i) ? "" : " dim"), role: "treeitem", "aria-level": n.level + 1, "aria-selected": isPicked ? "true" : "false" }, tree);
        el("rect", {
            x: pad, y: r1(y + 1), width: r1(w), height: rh - 2, rx: Math.min(corner, (rh - 2) / 2),
            fill: isPicked ? mix(accent, t.surface, 0.82) : isIn ? mix(accent, t.surface, 0.93) : t.surface, "fill-opacity": isPicked || isIn ? 1 : 0.001
        }, g);
        /* check box */
        const bx = x0 + 14, by = cy - box / 2;
        el("rect", {
            x: r1(bx), y: r1(by), width: box, height: box, rx: 2.5,
            fill: isPicked || isIn ? look.fill(accent) : t.surface, stroke: isPicked || isIn || isPart ? accent : t.axis, "stroke-width": 1.2
        }, g);
        if (isPicked || isIn) el("path", { d: `M${r1(bx + box * 0.22)},${r1(cy)} l${r1(box * 0.2)},${r1(box * 0.22)} l${r1(box * 0.36)},${r1(-box * 0.44)}`, fill: "none", stroke: inkOn(accent), "stroke-width": 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" }, g);
        else if (isPart) el("rect", { x: r1(bx + box * 0.28), y: r1(by + box * 0.28), width: r1(box * 0.44), height: r1(box * 0.44), rx: 1, fill: accent }, g);
        /* name and value */
        const tx = bx + box + 6, textMax = pad + w - 6 - valW - tx;
        el("text", { x: r1(tx), y: r1(cy + fsz * 0.36), "font-size": fsz, "font-weight": n.level === 0 || isPicked ? 600 : 400, fill: t.ink, class: "lbl" }, g, trunc(n.name, Math.max(10, textMax), fsz));
        if (showVals) el("text", { x: r1(pad + w - 6), y: r1(cy + vfs * 0.36), "text-anchor": "end", "font-size": vfs, fill: colorOr(LB.color, t.text), class: "lbl" }, g, fmtL(n.value));
        const tip = (): TipItem[] => {
            const out: TipItem[] = [{ displayName: m.levels[n.level].name, value: n.name, color: accent }];
            if (m.hasValues) out.push({ displayName: m.valueName, value: fmtT(n.value) });
            return out;
        };
        c.bind(g, { key: "n" + n.i, items: [n.i], ids: [], tip });
        onAct(g, multi => io.choose(n, multi));
        /* chevron: expand or collapse */
        if (n.children.length) {
            const open = io.expanded.has(n.key);
            const ch = el("g", { class: "mk", role: "button", "aria-label": (open ? "Collapse " : "Expand ") + n.name, tabindex: "0" }, tree);
            el("rect", { x: r1(x0 - 2), y: r1(y + 1), width: 14, height: rh - 2, fill: t.surface, "fill-opacity": 0.001 }, ch);
            el("path", { d: open ? `M${r1(x0 + 1)},${r1(cy - 2)} l4,4 l4,-4` : `M${r1(x0 + 3)},${r1(cy - 4)} l4,4 l-4,4`, fill: "none", stroke: t.axis, "stroke-width": 1.5, "stroke-linecap": "round", "stroke-linejoin": "round" }, ch);
            onAct(ch, () => io.toggleNode(n));
        }
    });
}
