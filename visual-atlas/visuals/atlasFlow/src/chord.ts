/*
 * Directed chord diagram: each node's arc holds its outgoing flows then
 * its incoming flows, so every ribbon keeps the same width at both ends.
 */
import { Ctx, nodeKey, linkKey } from "./model";
import { el, r1, textW, trunc } from "./common/look";

export interface ChordOpts { padDeg: number; arcW: number; opacity: number; linkBy: string; }

export function drawChord(c: Ctx, o: ChordOpts) {
    const N = c.nodes, L = c.links.filter(l => l.s !== l.t);
    const tot = N.reduce((s, nd) => s + nd.inV + nd.outV, 0); if (!tot) return;
    const fs = c.label.size, lw = c.label.show ? Math.min(c.W * 0.28, Math.max(...N.map(nd => textW(nd.name, fs)))) : 0;
    const ro = Math.max(20, Math.min(c.H / 2 - (c.label.show ? fs + 8 : 6), c.W / 2 - lw - 14)), ri = Math.max(8, ro - o.arcW), cx = c.W / 2, cy = c.H / 2;
    const pad = Math.min(o.padDeg * Math.PI / 180, (Math.PI * 2 * 0.4) / Math.max(1, N.length)), k = (Math.PI * 2 - pad * N.length) / tot;
    const P = (r: number, t: number) => r1(cx + r * Math.cos(t)) + "," + r1(cy + r * Math.sin(t));
    const big = (a: number, b: number) => (b - a > Math.PI ? 1 : 0);
    /* arc spans: outgoing slots then incoming slots */
    let a = -Math.PI / 2 + pad / 2;
    const span = N.map(nd => { const s = { a0: a, a1: a + (nd.inV + nd.outV) * k, cur: a }; a = s.a1 + pad; return s; });
    const outSlot = new Map<number, [number, number]>(), inSlot = new Map<number, [number, number]>();
    N.forEach((nd, i) => {
        const mine = L.map((l, q) => [l, q] as const);
        mine.filter(([l]) => l.s === i).sort((p, q) => q[0].t - p[0].t).forEach(([l, q]) => { const s0 = span[i].cur; span[i].cur += l.v * k; outSlot.set(q, [s0, span[i].cur]); });
        mine.filter(([l]) => l.t === i).sort((p, q) => p[0].s - q[0].s).forEach(([l, q]) => { const s0 = span[i].cur; span[i].cur += l.v * k; inSlot.set(q, [s0, span[i].cur]); });
    });
    const gr = el("g", { class: "lks" }, c.root);
    L.forEach((l, q) => {
        const s = outSlot.get(q), t = inSlot.get(q); if (!s || !t) return;
        const d = `M${P(ri, s[0])}A${r1(ri)},${r1(ri)} 0 ${big(s[0], s[1])},1 ${P(ri, s[1])}Q${r1(cx)},${r1(cy)} ${P(ri, t[0])}A${r1(ri)},${r1(ri)} 0 ${big(t[0], t[1])},1 ${P(ri, t[1])}Q${r1(cx)},${r1(cy)} ${P(ri, s[0])}Z`;
        const a1 = N[l.s], b1 = N[l.t];
        const dim = (c.anySelected && !c.isSelected(linkKey(l)) && !c.isSelected(nodeKey(a1)) && !c.isSelected(nodeKey(b1))) || (c.highlights && !l.hl);
        const p = el("path", { class: "rb" + (dim ? " dim" : ""), d, fill: o.linkBy === "target" ? b1.color : o.linkBy === "neutral" ? c.muted : a1.color, "fill-opacity": o.opacity / 100, stroke: c.surface, "stroke-width": 0.5 }, gr);
        c.bind(p, "link", c.links.indexOf(l));
    });
    const ga = el("g", { class: "gm" }, c.root); const f = c.look.shadow(); if (f) ga.setAttribute("filter", f);
    const gt = el("g", { class: "lbls" }, c.root);
    N.forEach((nd, i) => {
        const s = span[i]; if (s.a1 - s.a0 < 1e-4) return;
        const d = `M${P(ro, s.a0)}A${r1(ro)},${r1(ro)} 0 ${big(s.a0, s.a1)},1 ${P(ro, s.a1)}L${P(ri + 1, s.a1)}A${r1(ri + 1)},${r1(ri + 1)} 0 ${big(s.a0, s.a1)},0 ${P(ri + 1, s.a0)}Z`;
        const dim = (c.anySelected && !c.isSelected(nodeKey(nd))) || (c.highlights && !nd.highlighted);
        const p = el("path", { class: "arc" + (dim ? " dim" : ""), d, fill: c.look.fill(nd.color, "v"), stroke: c.surface, "stroke-width": 1 }, ga);
        c.bind(p, "node", i);
        if (!c.label.show) return;
        const m = (s.a0 + s.a1) / 2, cs = Math.cos(m), sn = Math.sin(m), lx = cx + (ro + 6) * cs, ly = cy + (ro + 6) * sn, an = Math.abs(cs) < 0.22 ? "middle" : cs > 0 ? "start" : "end";
        if ((s.a1 - s.a0) * ro < fs * 0.8) return;
        el("text", { x: r1(lx), y: r1(ly + fs * 0.36 + (an === "middle" ? (sn > 0 ? fs * 0.5 : -fs * 0.3) : 0)), "text-anchor": an, class: "lbl", fill: c.label.color, "font-size": fs }, gt, trunc(nd.name, lw + 4, fs));
    });
}
