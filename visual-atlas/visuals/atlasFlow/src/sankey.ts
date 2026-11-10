/*
 * Sankey: columns follow the flow order (links that loop back are
 * skipped), nodes are ordered by repeated barycenter passes, and bands
 * are sized by weight.
 */
import { Ctx, FNode, FLink, nodeKey, linkKey } from "./model";
import { el, r1, textW, trunc } from "./common/look";

export interface SankeyOpts { nodeW: number; pad: number; radius: number; align: string; linkBy: string; opacity: number; }

export function drawSankey(c: Ctx, o: SankeyOpts) {
    const N = c.nodes, L = c.links.filter(l => l.s !== l.t), n = N.length;
    if (!n) return;
    /* --- columns: longest path from sources (Kahn), back links ignored --- */
    const outs: number[][] = N.map(() => []), ins: number[][] = N.map(() => []);
    L.forEach((l, k) => { outs[l.s].push(k); ins[l.t].push(k); });
    const indeg = N.map((_, i) => ins[i].length), depth = N.map(() => 0), done = N.map(() => false), queue: number[] = [];
    indeg.forEach((d, i) => { if (!d) queue.push(i); });
    if (!queue.length) queue.push(N.reduce((b, nd, i) => (nd.outV > N[b].outV ? i : b), 0));
    let guard = 0;
    while (queue.length && guard++ < n * 4) {
        const i = queue.shift() as number; if (done[i]) continue; done[i] = true;
        outs[i].forEach(k => { const t = L[k].t; if (done[t]) return; depth[t] = Math.max(depth[t], depth[i] + 1); if (--indeg[t] <= 0) queue.push(t); });
        if (!queue.length) { const rest = N.findIndex((_, j) => !done[j]); if (rest >= 0) { depth[rest] = Math.max(depth[rest], ...ins[rest].filter(k => done[L[k].s]).map(k => depth[L[k].s] + 1), 0); queue.push(rest); } }
    }
    L.forEach(l => { l.back = depth[l.t] <= depth[l.s]; });
    let maxD = Math.max(0, ...depth);
    if (o.align !== "left") N.forEach((nd, i) => { if (!outs[i].some(k => !L[k].back) && ins[i].length) depth[i] = maxD; });
    maxD = Math.max(1, ...depth);
    N.forEach((nd, i) => { nd.col = depth[i]; nd.value = Math.max(nd.inV, nd.outV); });

    /* --- geometry --- */
    const fs = c.label.size, nw = o.nodeW, lastCol = N.filter(nd => nd.col === maxD);
    const labelW = c.label.show ? Math.min(c.W * 0.3, Math.max(0, ...lastCol.map(nd => Math.max(textW(nd.name, fs), c.label.values ? textW(c.fmt(nd.value), fs) : 0))) + 10) : 4;
    const top = 6, B = c.H - 6, X0 = 2, X1 = c.W - labelW;
    const cols: FNode[][] = []; for (let d = 0; d <= maxD; d++) cols.push(N.filter(nd => nd.col === d).sort((a, b) => b.value - a.value));
    let pad = o.pad; const ky = () => Math.min(...cols.filter(cn => cn.length).map(cn => (B - top - (cn.length - 1) * pad) / Math.max(1e-12, cn.reduce((s, nd) => s + nd.value, 0))));
    /* shrink the gaps when there are too many nodes for the height */
    while (ky() <= 0 && pad > 0.5) pad *= 0.6;
    const k = Math.max(1e-12, ky());
    const stack = (cn: FNode[]) => {
        cn.forEach(nd => { nd.y1 = (nd.y0 as number) + nd.value * k; });
        cn.sort((a, b) => (a.y0 as number) - (b.y0 as number));
        let y = top; cn.forEach(nd => { const h = (nd.y1 as number) - (nd.y0 as number); if ((nd.y0 as number) < y) nd.y0 = y; nd.y1 = (nd.y0 as number) + h; y = nd.y1 + pad; });
        y = B; for (let j = cn.length - 1; j >= 0; j--) { const nd = cn[j], h = (nd.y1 as number) - (nd.y0 as number); if ((nd.y1 as number) > y) { nd.y1 = y; nd.y0 = y - h; } y = (nd.y0 as number) - pad; }
        y = top; cn.forEach(nd => { const h = (nd.y1 as number) - (nd.y0 as number); if ((nd.y0 as number) < y) { nd.y0 = y; nd.y1 = y + h; } y = (nd.y1 as number) + pad; });
    };
    cols.forEach((cn, d) => {
        const tot = cn.reduce((s, nd) => s + nd.value * k, 0) + (cn.length - 1) * pad; let y = top + (B - top - tot) / 2;
        cn.forEach(nd => { nd.x = X0 + d * (X1 - X0 - nw) / maxD; nd.y0 = y; nd.y1 = y + nd.value * k; y = nd.y1 + pad; });
    });
    /* --- relaxation: move nodes toward the weighted center of their neighbours --- */
    const mid = (nd: FNode) => ((nd.y0 as number) + (nd.y1 as number)) / 2;
    for (let it = 0; it < 6; it++) {
        const a = 0.75 ** it;
        for (let d = 1; d <= maxD; d++) { cols[d].forEach(nd => { const ks = ins[nd.i].filter(q => !L[q].back); const w = ks.reduce((s, q) => s + L[q].v, 0); if (!w) return; const m = ks.reduce((s, q) => s + mid(N[L[q].s]) * L[q].v, 0) / w; const dy = (m - mid(nd)) * a; nd.y0 = (nd.y0 as number) + dy; nd.y1 = (nd.y1 as number) + dy; }); stack(cols[d]); }
        for (let d = maxD - 1; d >= 0; d--) { cols[d].forEach(nd => { const ks = outs[nd.i].filter(q => !L[q].back); const w = ks.reduce((s, q) => s + L[q].v, 0); if (!w) return; const m = ks.reduce((s, q) => s + mid(N[L[q].t]) * L[q].v, 0) / w; const dy = (m - mid(nd)) * a; nd.y0 = (nd.y0 as number) + dy; nd.y1 = (nd.y1 as number) + dy; }); stack(cols[d]); }
    }
    /* --- link slots --- */
    N.forEach((nd, i) => {
        let y = nd.y0 as number; outs[i].filter(q => !L[q].back).sort((p, q) => mid(N[L[p].t]) - mid(N[L[q].t])).forEach(q => { L[q].sy = y; y += L[q].v * k; });
        y = nd.y0 as number; ins[i].filter(q => !L[q].back).sort((p, q) => mid(N[L[p].s]) - mid(N[L[q].s])).forEach(q => { L[q].ty = y; y += L[q].v * k; });
    });

    /* --- draw links --- */
    const gl = el("g", { class: "lks" }, c.root);
    L.forEach(l => {
        if (l.back) return;
        const a = N[l.s], b = N[l.t], w = Math.max(0.7, l.v * k), x0 = (a.x as number) + nw, x1 = b.x as number, xm = (x0 + x1) / 2, sy = l.sy as number, ty = l.ty as number;
        const d = `M${r1(x0)},${r1(sy)}C${r1(xm)},${r1(sy)} ${r1(xm)},${r1(ty)} ${r1(x1)},${r1(ty)}V${r1(ty + w)}C${r1(xm)},${r1(ty + w)} ${r1(xm)},${r1(sy + w)} ${r1(x0)},${r1(sy + w)}Z`;
        const fill = o.linkBy === "target" ? b.color : o.linkBy === "gradient" ? c.look.linkGradient(a.color, b.color, x0, x1) : o.linkBy === "neutral" ? c.muted : a.color;
        const dim = (c.anySelected && !c.isSelected(linkKey(l)) && !c.isSelected(nodeKey(a)) && !c.isSelected(nodeKey(b))) || (c.highlights && !l.hl);
        const p = el("path", { class: "lk" + (dim ? " dim" : ""), d, fill, "fill-opacity": o.opacity / 100 }, gl);
        c.bind(p, "link", c.links.indexOf(l));
    });
    /* --- draw nodes --- */
    const gn = el("g", { class: "gm" }, c.root); const f = c.look.shadow(); if (f) gn.setAttribute("filter", f);
    const gt = el("g", { class: "lbls" }, c.root);
    N.forEach(nd => {
        const x = nd.x as number, y0 = nd.y0 as number, h = Math.max(1.5, (nd.y1 as number) - y0);
        const dim = (c.anySelected && !c.isSelected(nodeKey(nd)) && !c.links.some(l => (l.s === nd.i || l.t === nd.i) && c.isSelected(linkKey(l)))) || (c.highlights && !nd.highlighted);
        const g = el("g", { class: "nd" + (dim ? " dim" : "") }, gn);
        if (c.look.is3d) {
            const dep = Math.min(6, nw * 0.6 + 1), dx = dep, dy = dep * 0.62;
            el("path", { d: `M${r1(x + nw)},${r1(y0)}l${r1(dx)},${r1(-dy)}v${r1(h)}l${r1(-dx)},${r1(dy)}Z`, fill: c.look.side(nd.color) }, g);
            el("path", { d: `M${r1(x)},${r1(y0)}l${r1(dx)},${r1(-dy)}h${r1(nw)}l${r1(-dx)},${r1(dy)}Z`, fill: c.look.top(nd.color) }, g);
            el("rect", { x: r1(x), y: r1(y0), width: r1(nw), height: r1(h), fill: c.look.fill(nd.color, "h") }, g);
        } else el("rect", { x: r1(x), y: r1(y0), width: r1(nw), height: r1(h), rx: Math.min(o.radius, nw / 2, h / 2), fill: c.look.fill(nd.color, "h") }, g);
        c.bind(g, "node", nd.i);
        if (!c.label.show) return;
        const lx = x + nw + (c.look.is3d ? 9 : 5), cy = y0 + h / 2, room = nd.col === maxD ? labelW - 8 : (X1 - X0) / maxD - nw - 6, fsz = c.label.size;
        const t = el("text", { x: r1(lx), y: r1(h >= fsz * 2.2 && c.label.values ? cy - 1 : cy + fsz * 0.36), class: "lbl", fill: c.label.color, "font-size": fsz }, gt, trunc(nd.name, room, fsz));
        if (c.label.values) {
            if (h >= fsz * 2.2) el("text", { x: r1(lx), y: r1(cy + fsz), class: "lbl val", fill: c.label.color, "font-size": fsz }, gt, c.fmt(nd.value));
            else if (textW(nd.name + " " + c.fmt(nd.value), fsz) <= room) { const ts = el("tspan", { class: "val" }, t, " " + c.fmt(nd.value)); ts.setAttribute("dx", "2"); }
        }
    });
}
