/*
 * Drawing for Atlas Text: a word cloud (deterministic spiral placement
 * with collision checks, shrinking to fit) and a ranked word list.
 */
import powerbi from "powerbi-visuals-api";
import { Model, Word } from "./model";
import { TextSettings } from "./settings";
import { Ctx } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix } from "./common/color";
import { colorOr, val } from "./common/cards";
import { legend, LegendItem } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<TextSettings, Model>;
/** a stable number in [0, 1) for a word, for its rotation */
const hash = (s: string) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967296; };

export function render(c: C) {
    const { W, H, s, m, root, look, t } = c, pad = 6, words = m.words, by = val(s.wcolor.colorBy);
    const low = colorOr(s.wcolor.lowColor, "#d64550"), high = colorOr(s.wcolor.highColor, "#1a9e5c");
    const cvs = words.map(w => w.colorV).filter(v => !isNaN(v)), cmin = Math.min(...cvs), cmax = Math.max(...cvs);
    const colorOf = (w: Word) => {
        if (t.hc) return t.ink;
        if (by === "value" && !isNaN(w.colorV)) { const k = cmax > cmin ? (w.colorV - cmin) / (cmax - cmin) : 0.5; return mix(mix(low, high, k), t.ink, 0.12); }
        if (by === "group" && w.group >= 0 && m.groups[w.group]) return c.colorOf(m.groups[w.group]);
        if (by === "single") return c.colorOf(m.colored[0]);
        return c.colorOf(w);
    };
    const fmtTip = formatter(m.format, 1, null, 0, c.culture), fmtL = labelFormatter(m.format, Number(s.labels.displayUnits.value) || 0, s.labels.decimals.value, words[0].weight, c.culture);
    const tip = (w: Word): TipItem[] => {
        const out: TipItem[] = [{ displayName: "Word", value: w.text, color: colorOf(w) }, { displayName: m.valueName, value: fmtTip(w.weight) }, { displayName: "Rows", value: String(w.rows.length) }];
        if (w.group >= 0 && m.groups[w.group]) out.push({ displayName: m.groupTitle, value: m.groups[w.group].name });
        if (!isNaN(w.colorV)) out.push({ displayName: m.colorName, value: w.colorV.toFixed(2) });
        return out;
    };
    const target = (w: Word): Target => ({ key: "w" + w.key, items: w.rows, ids: w.rows.map(r => m.ids[r]).slice(0, 500), tip: () => tip(w) });
    const lg = legend(s.legend, m.groups.map(g => ({ key: g.key, name: g.name, color: c.colorOf(g), on: c.io.anyOn(g.items), target: { key: "g" + g.key, items: g.items, ids: g.id ? [g.id] : [], tip: () => [{ displayName: m.groupTitle, value: g.name }] } })) as LegendItem[], m.groupTitle, W, H, pad, t, by === "group");
    const box = { l: pad, t: pad + lg.top, r: W - pad - lg.right, b: H - pad - lg.bottom };
    const sh = look.shadow(), g0 = el("g", sh ? { filter: sh } : {}, root);
    const maxW = words[0].weight, minW = words[words.length - 1].weight;

    if (s.type === "bars") {
        /* ranked words: one bar per word, as many as fit */
        const fs2 = Math.max(8, s.labels.fontSize.value + 1), rowH = fs2 + 8, n = Math.max(1, Math.min(words.length, Math.floor((box.b - box.t) / rowH)));
        const nameW = Math.min((box.r - box.l) * 0.35, Math.max(...words.slice(0, n).map(w => textW(w.text, fs2)))) + 10, valW = s.labels.show.value ? Math.max(...words.slice(0, n).map(w => textW(fmtL(w.weight), fs2))) + 8 : 0;
        const L = box.l + nameW, R = box.r - valW;
        words.slice(0, n).forEach((w, k) => {
            const y = box.t + k * rowH, col = colorOf(w), bw = Math.max(1, (R - L) * w.weight / maxW), g = el("g", { class: "mk" + (c.io.anyOn(w.rows) ? "" : " dim") }, g0);
            el("rect", { x: r1(L), y: r1(y + 3), width: r1(bw), height: r1(rowH - 6), rx: 3, fill: look.flat ? col : look.fill(col, "h") }, g);
            el("text", { x: r1(L - 6), y: r1(y + rowH / 2 + fs2 * 0.35), "text-anchor": "end", "font-size": fs2, fill: t.text, class: "ttl" }, g, trunc(w.text, nameW - 8, fs2));
            if (s.labels.show.value) el("text", { x: r1(L + bw + 5), y: r1(y + rowH / 2 + fs2 * 0.35), "font-size": fs2 - 1, fill: t.axis, class: "ax" }, g, fmtL(w.weight));
            c.bind(g, target(w));
        });
        lg.draw(root, c.bind);
        return;
    }

    /* word cloud: biggest first, each on an outward spiral until it fits without touching another */
    const CL = s.cloud, rot = val(CL.rotation), padW = CL.padding.value, sc = val(CL.scale);
    const norm = (v: number) => sc === "log" ? (Math.log(v) - Math.log(minW)) / ((Math.log(maxW) - Math.log(minW)) || 1) : sc === "linear" ? (v - minW) / ((maxW - minW) || 1) : (Math.sqrt(v) - Math.sqrt(minW)) / ((Math.sqrt(maxW) - Math.sqrt(minW)) || 1);
    const BW = box.r - box.l, BH = box.b - box.t, cx = box.l + BW / 2, cy = box.t + BH / 2;
    let factor = Math.min(1, Math.sqrt(BW * BH / (560 * 320)) * 1.1);
    interface P { w: Word; x: number; y: number; fs: number; ang: number; bw: number; bh: number; }
    let placed: P[] = [];
    for (let attempt = 0; attempt < 7; attempt++) {
        placed = [];
        const boxes: { x0: number; y0: number; x1: number; y1: number }[] = [];
        for (const w of words) {
            const fs2 = Math.max(4, (CL.minSize.value + (CL.maxSize.value - CL.minSize.value) * Math.max(0, Math.min(1, norm(w.weight)))) * factor);
            const hsh = hash(w.key), ang = rot === "none" ? 0 : rot === "some" ? (hsh < 0.3 ? -90 : 0) : [-60, -30, 0, 0, 30, 60][Math.floor(hsh * 6)];
            /* the box a word really takes: measured width, the line height of the text */
            const tw = textW(w.text, fs2) + padW * 2, th = fs2 * 1.12 + padW * 2, rad = ang * Math.PI / 180;
            const bw = Math.abs(Math.cos(rad)) * tw + Math.abs(Math.sin(rad)) * th, bh = Math.abs(Math.sin(rad)) * tw + Math.abs(Math.cos(rad)) * th;
            let done = false;
            /* Archimedean spiral, stretched to the box's aspect ratio */
            for (let i = 0; i < 1600 && !done; i++) {
                const a = i * 0.35, r = 1.6 * a, x = cx + Math.cos(a) * r * (BW / BH > 1 ? Math.min(2.2, BW / BH) : 1), y = cy + Math.sin(a) * r * (BW / BH < 1 ? Math.min(2.2, BH / BW) : 1);
                const b = { x0: x - bw / 2, y0: y - bh / 2, x1: x + bw / 2, y1: y + bh / 2 };
                if (b.x0 < box.l || b.y0 < box.t || b.x1 > box.r || b.y1 > box.b) { if (r > Math.max(BW, BH)) break; continue; }
                if (boxes.some(o => !(b.x1 < o.x0 || b.x0 > o.x1 || b.y1 < o.y0 || b.y0 > o.y1))) continue;
                boxes.push(b); placed.push({ w, x, y, fs: fs2, ang, bw, bh }); done = true;
            }
        }
        /* everything (or nearly) placed and the biggest word in: done; else shrink and try again */
        if (placed.length >= words.length * 0.92 && placed.some(p => p.w === words[0])) break;
        factor *= 0.84;
    }
    placed.forEach(p => {
        const col = colorOf(p.w), g = el("g", { class: "mk" + (c.io.anyOn(p.w.rows) ? "" : " dim") }, g0);
        el("rect", { x: r1(p.x - p.bw / 2), y: r1(p.y - p.bh / 2), width: r1(p.bw), height: r1(p.bh), fill: "transparent" }, g);
        el("text", { x: r1(p.x), y: r1(p.y + p.fs * 0.36), "text-anchor": "middle", "font-size": r1(p.fs), fill: col, class: "ttl", transform: p.ang ? `rotate(${p.ang} ${r1(p.x)} ${r1(p.y)})` : null }, g, p.w.text);
        c.bind(g, target(p.w));
    });
    lg.draw(root, c.bind);
}
