/*
 * Network graph: force-directed layout (d3-force, deterministic start),
 * node size by value or by number of connections, optional community
 * coloring by label propagation.
 */
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, SimulationNodeDatum, SimulationLinkDatum } from "d3-force";
import { Ctx, FNode, nodeKey, linkKey } from "./model";
import { el, r1, textW } from "./common/look";

export interface NetOpts { sizeBy: string; maxSize: number; labelCount: number; spacing: number; colorBy: string; opacity: number; communityColor: (k: number) => string; }
interface SN extends SimulationNodeDatum { i: number; r: number; }

/** label propagation in a fixed order, so the same data gives the same groups */
export function communities(nodes: FNode[], links: { s: number; t: number; v: number }[]): number[] {
    const lab = nodes.map((_, i) => i), nb: [number, number][][] = nodes.map(() => []);
    links.forEach(l => { if (l.s !== l.t) { nb[l.s].push([l.t, l.v]); nb[l.t].push([l.s, l.v]); } });
    for (let it = 0; it < 12; it++) {
        let moved = false;
        nodes.forEach((_, i) => { const w = new Map<number, number>(); nb[i].forEach(([j, v]) => w.set(lab[j], (w.get(lab[j]) || 0) + v)); let best = lab[i], bw = -1; w.forEach((v, kk) => { if (v > bw || (v === bw && kk < best)) { bw = v; best = kk; } }); if (best !== lab[i]) { lab[i] = best; moved = true; } });
        if (!moved) break;
    }
    const ids = new Map<number, number>(); return lab.map(l => { if (!ids.has(l)) ids.set(l, ids.size); return ids.get(l) as number; });
}

export function drawNetwork(c: Ctx, o: NetOpts) {
    const N = c.nodes, n = N.length; if (!n) return;
    const und = new Map<string, { s: number; t: number; v: number }>();
    c.links.forEach(l => { if (l.s === l.t) return; const a = Math.min(l.s, l.t), b = Math.max(l.s, l.t), key = a + "|" + b; const e = und.get(key); if (e) e.v += l.v; else und.set(key, { s: a, t: b, v: l.v }); });
    const E = [...und.values()];
    const vmax = Math.max(...N.map(nd => (o.sizeBy === "degree" ? nd.deg : nd.value)), 1), rmin = Math.max(3, o.maxSize * 0.32);
    const rad = (nd: FNode) => rmin + Math.sqrt((o.sizeBy === "degree" ? nd.deg : nd.value) / vmax) * (o.maxSize - rmin);
    const sn: SN[] = N.map((nd, i) => ({ i, r: rad(nd) }));
    const area = c.W * c.H, base = Math.sqrt(area / Math.max(1, n)) * (0.45 + o.spacing / 100);
    const sim = forceSimulation<SN>(sn)
        .force("link", forceLink<SN, SimulationLinkDatum<SN>>(E.map(e => ({ source: e.s, target: e.t }))).distance(base * 0.8).strength(0.5))
        .force("charge", forceManyBody<SN>().strength(-base * 1.6))
        .force("center", forceCenter(0, 0))
        .force("collide", forceCollide<SN>(d => d.r + 3))
        .stop();
    for (let i = 0; i < 300; i++) sim.tick();
    if (o.colorBy === "community") { const cm = communities(N, E); N.forEach((nd, i) => { nd.comm = cm[i]; nd.color = o.communityColor(cm[i]); }); }
    /* fit into the viewport, keeping room for labels */
    const fs = c.label.size, padX = c.label.show ? Math.min(c.W * 0.18, 70) : 16, padY = fs + 8;
    const xs = sn.map(d => d.x as number), ys = sn.map(d => d.y as number), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (c.W - padX * 2) / Math.max(1, x1 - x0), sy = (c.H - padY * 2) / Math.max(1, y1 - y0), s = Math.min(sx, sy);
    const ox = (c.W - (x1 - x0) * s) / 2, oy = (c.H - (y1 - y0) * s) / 2;
    sn.forEach(d => { d.x = ox + ((d.x as number) - x0) * s; d.y = oy + ((d.y as number) - y0) * s; });
    const wmax = Math.max(...E.map(e => e.v), 1);
    const nbr = N.map(() => new Set<number>()); E.forEach(e => { nbr[e.s].add(e.t); nbr[e.t].add(e.s); });
    const selNodes = N.filter(nd => c.isSelected(nodeKey(nd))).map(nd => nd.i);
    const lit = (i: number) => !c.anySelected || selNodes.includes(i) || selNodes.some(j => nbr[j].has(i));
    const gl = el("g", { class: "lks" }, c.root);
    c.links.forEach((l, q) => {
        if (l.s === l.t) return; const a = sn[l.s], b = sn[l.t];
        const on = c.anySelected && (selNodes.includes(l.s) || selNodes.includes(l.t) || c.isSelected(linkKey(l)));
        const dim = (c.anySelected && !on) || (c.highlights && !l.hl);
        const line = el("line", { class: "nl" + (on ? " on" : "") + (dim ? " dim" : ""), x1: r1(a.x as number), y1: r1(a.y as number), x2: r1(b.x as number), y2: r1(b.y as number), stroke: c.ink, "stroke-opacity": on ? 0.75 : o.opacity / 160, "stroke-width": r1(0.8 + (l.v / wmax) * 3) }, gl);
        c.bind(line, "link", q);
    });
    const gn = el("g", { class: "gm" }, c.root); const f = c.look.shadow(); if (f) gn.setAttribute("filter", f);
    const order = sn.slice().sort((p, q) => p.r - q.r);
    order.forEach(d => {
        const nd = N[d.i], dim = (c.anySelected && !lit(d.i)) || (c.highlights && !nd.highlighted);
        const circ = el("circle", { class: "nn" + (dim ? " dim" : ""), cx: r1(d.x as number), cy: r1(d.y as number), r: r1(d.r), fill: c.look.fill(nd.color, "r"), stroke: c.surface, "stroke-width": 1.4 }, gn);
        c.bind(circ, "node", d.i);
    });
    if (!c.label.show) return;
    const gt = el("g", { class: "lbls" }, c.root), placed: number[][] = [];
    N.slice().sort((a, b) => (o.sizeBy === "degree" ? b.deg - a.deg : b.value - a.value)).slice(0, Math.max(0, o.labelCount)).forEach(nd => {
        const d = sn[nd.i], w = textW(nd.name, fs), right = (d.x as number) < c.W * 0.62, lx = right ? (d.x as number) + d.r + 3 : (d.x as number) - d.r - 3, bx = right ? lx : lx - w;
        const box = [bx, (d.y as number) - fs * 0.62, bx + w, (d.y as number) + fs * 0.5];
        if (bx < 1 || bx + w > c.W - 1 || placed.some(p => !(box[2] < p[0] || box[0] > p[2] || box[3] < p[1] || box[1] > p[3]))) return;
        placed.push(box);
        el("text", { x: r1(lx), y: r1((d.y as number) + fs * 0.34), "text-anchor": right ? "start" : "end", class: "lbl halo", fill: c.label.color, "font-size": fs }, gt, nd.name);
    });
}
