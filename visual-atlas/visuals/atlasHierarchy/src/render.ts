/*
 * Drawing for Atlas Hierarchy: treemap, sunburst, circle packing (zoom
 * into a group, breadcrumb to come back) and org chart / tree (open and
 * close branches). Layouts come from d3-hierarchy, which is deterministic.
 */
import powerbi from "powerbi-visuals-api";
import { hierarchy, treemap, treemapSquarify, treemapBinary, treemapSliceDice, pack, partition, tree, HierarchyRectangularNode, HierarchyCircularNode, HierarchyPointNode } from "d3-hierarchy";
import { Model, HNode } from "./model";
import { HierarchySettings } from "./settings";
import { Ctx } from "./common/family";
import { Target } from "./common/interact";
import { el, r1, textW, trunc } from "./common/look";
import { mix, inkOn } from "./common/color";
import { colorOr, val } from "./common/cards";
import { legend, LegendItem } from "./common/chart";
import { labelFormatter, formatter } from "./common/util";
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

type C = Ctx<HierarchySettings, Model>;
/** state kept by the visual between renders: zoom path and open tree branches */
export interface View { zoom: string[]; open: Set<string> | null; }

export function render(c: C, view: View, redraw: () => void) {
    const { W, H, s, m, root, look, t } = c, type = s.type, pad = 4;
    const LB = s.labels, lbfs = Math.max(6, LB.fontSize.value), content = val(s.chart.content);
    const colorBy = val(s.hcolor.colorBy), fade = s.hcolor.fade.value / 100, low = colorOr(s.hcolor.lowColor, "#d64550"), high = colorOr(s.hcolor.highColor, "#1a9e5c");
    const fmtV = labelFormatter(m.format, Number(LB.displayUnits.value) || 0, LB.decimals.value, m.root.total, c.culture);
    const fmtTip = formatter(m.format, 1, null, 0, c.culture), fmtC = formatter(m.colorFormat, 1, null, 0, c.culture);

    /* zoom: follow the stored path as far as it still exists */
    let z = m.root; const path: HNode[] = [m.root];
    for (const k of view.zoom) { const nx = z.children.find(ch => ch.key === k); if (!nx) break; z = nx; path.push(nx); }
    view.zoom = path.slice(1).map(p => p.key);
    const zoomTo = (nd: HNode) => { const p: string[] = []; for (let x: HNode | null = nd; x && x !== m.root; x = x.parent) p.unshift(x.key); view.zoom = p; redraw(); };

    /* color of a node */
    const visibleColorVals = m.nodes.map(n => n.colorV).filter(v => !isNaN(v)), cmin = Math.min(...visibleColorVals), cmax = Math.max(...visibleColorVals);
    const neutral = mix(t.text, t.surface, 0.55);
    const colorFor = (nd: HNode): string => {
        if (t.hc) return t.ink;
        if (colorBy === "value" && m.hasColor) {
            if (isNaN(nd.colorV)) return neutral;
            const k = cmax > cmin ? (nd.colorV - cmin) / (cmax - cmin) : 0.5;
            return k < 0.5 ? mix(low, mix(low, high, 0.5), k * 2) : mix(mix(low, high, 0.5), high, (k - 0.5) * 2);
        }
        if (colorBy === "level") { const lc = m.levelColors[Math.max(0, nd.depth - 1)]; return nd.depth === 0 ? neutral : c.colorOf(lc); }
        if (nd.depth === 0) return neutral;
        const b = m.branches[nd.branch];
        return mix(b ? c.colorOf(b) : neutral, t.surface, Math.min(0.7, fade * Math.max(0, nd.depth - 1)));
    };
    const pctOf = (nd: HNode) => (z.total ? nd.total / z.total : 0);
    const labelText = (nd: HNode) => content === "nameValue" && LB.show.value ? fmtV(nd.total) : content === "namePercent" && LB.show.value ? (pctOf(nd) * 100).toFixed(pctOf(nd) < 0.1 ? 1 : 0) + "%" : "";
    const tip = (nd: HNode): TipItem[] => {
        const items: TipItem[] = [];
        const chain: HNode[] = []; for (let x: HNode | null = nd; x && x !== m.root; x = x.parent) chain.unshift(x);
        if (m.org) items.push({ displayName: "Name", value: nd.name, color: colorFor(nd) });
        else chain.forEach(x => items.push({ displayName: m.levelNames[x.depth - 1] || "Level", value: x.name, color: x === nd ? colorFor(nd) : undefined } as TipItem));
        items.push({ displayName: m.valueName, value: m.hasValue ? fmtTip(nd.total) : String(nd.items.length) });
        if (z.total) items.push({ displayName: "Share of " + (z === m.root ? "total" : z.name), value: (pctOf(nd) * 100).toFixed(1) + "%" });
        if (m.org && nd.count) items.push({ displayName: "Team size", value: String(nd.count) });
        if (m.hasColor && !isNaN(nd.colorV)) items.push({ displayName: m.colorName, value: fmtC(nd.colorV) });
        const a = c.io.active; if (a && !c.io.sel.size) items.push({ displayName: "Highlighted", value: String(nd.items.filter(i => a.has(i)).length) + " of " + nd.items.length });
        nd.tips.forEach(tp => items.push({ displayName: tp.name, value: tp.value }));
        return items;
    };
    const target = (nd: HNode): Target => ({ key: "n" + nd.key, items: nd.items, ids: nd.id ? [nd.id] : nd.items.map(i => m.ids[i]).slice(0, 500), tip: () => tip(nd) });
    const zoomOnClick = val(s.chart.click) === "zoom";
    /** bind a node: tooltips, selection; groups zoom on click (or double-click when clicking selects) */
    const bindNode = (e: Element, nd: HNode, zoomable: boolean) => {
        if (zoomable && zoomOnClick) {
            e.setAttribute("tabindex", "0");
            e.addEventListener("click", ev => { ev.stopPropagation(); zoomTo(nd); });
            e.addEventListener("keydown", ev => { const k = (ev as KeyboardEvent).key; if (k === "Enter" || k === " ") { ev.preventDefault(); zoomTo(nd); } });
            /* tooltips and the context menu still work */
            const t2 = target(nd), host = c.bind;
            const ghost = { key: t2.key, items: t2.items, ids: [] as powerbi.visuals.ISelectionId[], tip: t2.tip };
            host(e, ghost); (e as SVGElement).style.cursor = "pointer";
        } else {
            c.bind(e, target(nd));
            if (zoomable) e.addEventListener("dblclick", ev => { ev.stopPropagation(); zoomTo(nd); });
        }
    };

    /* legend of branches (zoomed in: only the branch on screen stays bright) */
    const zoomBranch = path.length > 1 ? path[1].branch : -1;
    const lgItems: LegendItem[] = colorBy === "value" ? [] : (colorBy === "level" ? m.levelColors.map((lc, k) => ({ key: lc.key, name: m.levelNames[k], color: c.colorOf(lc), on: true })) : m.branches.map((b, k) => ({ key: b.key, name: b.name, color: c.colorOf(b), on: (zoomBranch < 0 || k === zoomBranch) && c.io.anyOn(b.items), target: { key: "n" + b.key, items: b.items, ids: b.id ? [b.id] : [], tip: () => [{ displayName: m.levelNames[0] || "Group", value: b.name }] } })));
    const lg = legend(s.legend, lgItems, colorBy === "level" ? "Level" : m.org ? "" : m.levelNames[0] || "", W, H, pad, t, type !== "tree" && colorBy !== "value");

    /* when zoomed: a Back button and the path (All › Bikes › Mountain) under the legend; each step zooms back out to it */
    let top = pad + lg.top;
    if (path.length > 1 && type !== "tree") {
        const bfs = Math.max(9, lbfs + 1), bh = bfs + 10, y0 = top + 2, mid = y0 + bh / 2 + bfs * 0.35, g = el("g", { class: "crumb" }, root);
        const goTo = (k: number) => { view.zoom = path.slice(1, k + 1).map(q => q.key); redraw(); };
        const step = (e: Element, k: number, label: string) => {
            e.setAttribute("tabindex", "0"); e.setAttribute("role", "button"); e.setAttribute("aria-label", label); (e as SVGElement).style.cursor = "pointer";
            e.addEventListener("click", ev => { ev.stopPropagation(); goTo(k); });
            e.addEventListener("keydown", ev => { const kk = (ev as KeyboardEvent).key; if (kk === "Enter" || kk === " ") { ev.preventDefault(); goTo(k); } });
        };
        const backText = "‹ " + c.msg("Zoom_Back", "Back"), bw = textW(backText, bfs) + 18;
        const back = el("g", { class: "crumb-back" }, g);
        el("rect", { x: pad, y: r1(y0), width: r1(bw), height: bh, rx: bh / 2, fill: t.hc ? t.surface : mix(t.ink, t.surface, 0.9), stroke: mix(t.ink, t.surface, 0.6), "stroke-width": 1 }, back);
        el("text", { x: r1(pad + bw / 2), y: r1(mid), "text-anchor": "middle", "font-size": bfs, fill: t.ink, class: "ttl" }, back, backText);
        step(back, path.length - 2, c.msg("Zoom_Out", "Zoom out one level"));
        let x = pad + bw + 10;
        path.forEach((p, k) => {
            const label = k === 0 ? (m.org ? p.name : c.msg("Zoom_All", "All")) : p.name, last = k === path.length - 1, shown = trunc(label, 160, bfs);
            const tx = el("text", { x: r1(x), y: r1(mid), "font-size": bfs, fill: last ? t.ink : t.axis, class: last ? "ttl" : "ax", style: last ? "" : "text-decoration:underline" }, g, shown);
            if (!last) { tx.setAttribute("pointer-events", "all"); step(tx, k, label); }
            x += textW(shown, bfs) + 6;
            if (!last) { el("text", { x: r1(x), y: r1(mid), "font-size": bfs, fill: t.axis, class: "ax" }, g, "›"); x += 12; }
        });
        top = y0 + bh + 6;
    }
    const box = { l: pad, t: top, r: W - pad - lg.right, b: H - pad - lg.bottom };
    const BW = Math.max(10, box.r - box.l), BH = Math.max(10, box.b - box.t);

    const maxDepth = Math.max(1, Math.round(s.chart.depth.value));
    const limited = (nd: HNode) => (nd.depth - z.depth < maxDepth ? nd.children : []);
    const build = () => hierarchy<HNode>(z, nd => { const ch = limited(nd); return ch.length ? ch : null; })
        .sum(nd => (limited(nd).length ? nd.own : nd.total)).sort((a, b) => (b.value || 0) - (a.value || 0));
    const sh = look.shadow(), marks = el("g", sh ? { filter: sh } : {}, root), labels = el("g", {}, root);
    const on = (nd: HNode) => c.io.anyOn(nd.items);

    if (type === "treemap") drawTreemap();
    else if (type === "sunburst") drawSunburst();
    else if (type === "pack") drawPack();
    else drawTree();
    lg.draw(root, c.bind);

    /* ================================================================ treemap */
    function drawTreemap() {
        const TM = s.treemap, tile = val(TM.tile), padIn = Math.max(0, TM.padding.value), headers = TM.headers.value, hh = lbfs + 8, rad = look.is3d ? 0 : TM.radius.value;
        const h = build();
        treemap<HNode>().tile(tile === "binary" ? treemapBinary : tile === "sliceDice" ? treemapSliceDice : treemapSquarify).size([BW, BH]).paddingInner(padIn)
            .paddingTop(nd => (nd.depth > 0 && nd.children && headers ? hh : nd.depth > 0 && nd.children ? padIn : 0)).paddingRight(nd => (nd.depth > 0 && nd.children ? padIn : 0))
            .paddingBottom(nd => (nd.depth > 0 && nd.children ? padIn : 0)).paddingLeft(nd => (nd.depth > 0 && nd.children ? padIn : 0)).round(true)(h);
        const rn = h as HierarchyRectangularNode<HNode>;
        rn.descendants().filter(d => d.depth > 0).forEach(d => {
            const nd = d.data, x = box.l + d.x0, y = box.t + d.y0, w = Math.max(0, d.x1 - d.x0), hgt = Math.max(0, d.y1 - d.y0);
            if (w < 0.5 || hgt < 0.5) return;
            const col = colorFor(nd), isGroup = !!d.children, g = el("g", { class: "grp" + (on(nd) ? "" : " dim") }, marks);
            if (isGroup) {
                el("rect", { x: r1(x), y: r1(y), width: r1(w), height: r1(hgt), rx: r1(rad), fill: t.hc ? t.surface : mix(col, t.surface, 0.82), stroke: t.hc ? t.ink : "none" }, g);
                if (headers && w > 24) {
                    const ink = t.hc ? t.ink : inkOn(mix(col, t.surface, 0.82)), extra = labelText(nd);
                    el("text", { x: r1(x + 5), y: r1(y + lbfs + 2), "font-size": lbfs, fill: ink, class: "ttl" }, labels, trunc(nd.name + (extra ? "  " + extra : ""), w - 8, lbfs));
                }
                bindNode(g, nd, true);
                return;
            }
            const fill = t.hc ? t.surface : look.fill(col, "v");
            el("rect", { x: r1(x), y: r1(y), width: r1(w), height: r1(hgt), rx: r1(Math.min(rad, w / 2, hgt / 2)), fill, stroke: t.hc ? t.ink : "none" }, g);
            if (look.is3d && w > 6 && hgt > 6) {
                el("path", { d: `M${r1(x)},${r1(y + hgt)}V${r1(y)}H${r1(x + w)}`, fill: "none", stroke: look.top(col), "stroke-width": 2 }, g);
                el("path", { d: `M${r1(x + w)},${r1(y)}V${r1(y + hgt)}H${r1(x)}`, fill: "none", stroke: look.side(col), "stroke-width": 2 }, g);
            }
            bindNode(g, nd, nd.children.length > 0 && zoomOnClick);
            const ink = t.hc ? t.ink : inkOn(col), extra = labelText(nd);
            if (w > 30 && hgt > lbfs + 6) {
                el("text", { x: r1(x + 5), y: r1(y + lbfs + 3), "font-size": lbfs, fill: ink, class: "ttl" }, labels, trunc(nd.name, w - 8, lbfs));
                if (extra && hgt > lbfs * 2 + 10) el("text", { x: r1(x + 5), y: r1(y + lbfs * 2 + 6), "font-size": lbfs, fill: ink, class: "ax" }, labels, trunc(extra, w - 8, lbfs));
            }
        });
    }

    /* ================================================================ sunburst */
    function drawSunburst() {
        const SB = s.sunburst, h = build(), depthN = Math.max(1, h.height);
        partition<HNode>().size([2 * Math.PI, depthN + 1])(h);
        const rn = h as HierarchyRectangularNode<HNode>, R = Math.max(10, Math.min(BW, BH) / 2 - 2), cx = box.l + BW / 2, cy = box.t + BH / 2;
        const hole = R * SB.hole.value / 100, ring = (R - hole) / depthN, gap = SB.gap.value;
        const rad = (y: number) => (y <= 1 ? hole * y : hole + (y - 1) * ring);
        const arc = (a0: number, a1: number, r0: number, r1_: number) => {
            const pa0 = r0 > 0 ? gap / 2 / r0 : 0, pa1 = gap / 2 / r1_;
            const s0 = a0 + Math.min(pa0, (a1 - a0) / 2), e0 = a1 - Math.min(pa0, (a1 - a0) / 2), s1 = a0 + Math.min(pa1, (a1 - a0) / 2), e1 = a1 - Math.min(pa1, (a1 - a0) / 2);
            const P = (a: number, r: number) => `${r1(cx + Math.sin(a) * r)},${r1(cy - Math.cos(a) * r)}`, large = (e: number, st: number) => (e - st > Math.PI ? 1 : 0);
            if (a1 - a0 >= 2 * Math.PI - 1e-6) {
                return `M${P(0, r1_)}A${r1(r1_)},${r1(r1_)} 0 1 1 ${P(Math.PI, r1_)}A${r1(r1_)},${r1(r1_)} 0 1 1 ${P(2 * Math.PI - 1e-4, r1_)}Z` + (r0 > 0 ? `M${P(0, r0)}A${r1(r0)},${r1(r0)} 0 1 0 ${P(Math.PI, r0)}A${r1(r0)},${r1(r0)} 0 1 0 ${P(2 * Math.PI - 1e-4, r0)}Z` : "");
            }
            return `M${P(s1, r1_)}A${r1(r1_)},${r1(r1_)} 0 ${large(e1, s1)} 1 ${P(e1, r1_)}L${P(e0, r0)}` + (r0 > 0 ? `A${r1(r0)},${r1(r0)} 0 ${large(e0, s0)} 0 ${P(s0, r0)}` : "") + "Z";
        };
        rn.descendants().filter(d => d.depth > 0).forEach(d => {
            const nd = d.data, r0 = rad(d.y0), r1_ = rad(d.y1) - (look.is3d ? 1.5 : 0), col = colorFor(nd);
            if (d.x1 - d.x0 < 1e-4) return;
            const g = el("g", { class: "grp" + (on(nd) ? "" : " dim") }, marks);
            if (look.is3d) el("path", { d: arc(d.x0, d.x1, r0, r1_), fill: look.side(col), transform: "translate(1.5,2.5)" }, g);
            el("path", { d: arc(d.x0, d.x1, r0, r1_), fill: t.hc ? t.surface : look.fill(col, "r"), stroke: t.hc ? t.ink : "none" }, g);
            bindNode(g, nd, nd.children.length > 0);
            /* label along the ring when it fits */
            const mid = (d.x0 + d.x1) / 2, rm = (r0 + r1_) / 2, arcLen = (d.x1 - d.x0) * rm, thick = r1_ - r0, half = (d.x1 - d.x0) / 2;
            const nm = nd.name, extra = labelText(nd);
            /* The label is a block of lines centred on the slice's middle at radius rm: a radial label runs along the
               radius with its lines side by side across the slice, the others run across it with their lines stacked
               along the radius. It is drawn only when the whole block stays inside its slice, clear of the gaps, so a
               thin slice never writes over its neighbours: name and value, else the name alone, else nothing. A slice
               narrower than its ring is thick tries radial first, the others across first, then the other way. */
            const inside = (lines: string[], rad: boolean) => {
                /* each line's glyphs reach about 0.6 of the font size either side of its middle; 1 px clear of the edges */
                const w = Math.max(...lines.map(l => textW(l, lbfs))), hb = lines.length * (lbfs + 1) + lbfs * 0.2 - 1;
                const along = rad ? w : hb, across = rad ? hb : w, edge = gap / 2 + 1;
                if (rm - along / 2 < r0 + 1) return false;
                return [-1, 1].every(i => [-1, 1].every(j => {
                    const px = rm + i * along / 2, py = j * across / 2, rho = Math.hypot(px, py), phi = Math.abs(Math.atan2(py, px));
                    return rho <= r1_ - 1 && (half - phi >= Math.PI / 2 || rho * Math.sin(half - phi) >= edge);
                }));
            };
            let txt: string[] | null = null, radial = arcLen < thick * 1.2;
            for (const rad of [radial, !radial]) {
                const room = rad ? thick - 6 : arcLen - 6;
                if (Math.min(room, rad ? arcLen : thick) < lbfs + 2 || room < 18) continue;
                for (const two of extra ? [true, false] : [false]) {
                    for (let max = room; !txt && max >= 18; max *= 0.8) {
                        /* no label rather than an unreadable stub ("Ro…") */
                        const cut = trunc(nm, max, lbfs); if (cut !== nm && cut.replace("…", "").length < 4) break;
                        const lines = two ? [cut, trunc(extra, max, lbfs)] : [cut];
                        if (inside(lines, rad)) { txt = lines; radial = rad; }
                    }
                    if (txt) break;
                }
                if (txt) break;
            }
            if (!txt) return;
            const x = cx + Math.sin(mid) * rm, y = cy - Math.cos(mid) * rm;
            let rot = radial ? (mid * 180 / Math.PI) - 90 : (mid * 180 / Math.PI);
            if (radial ? mid > Math.PI : (mid > Math.PI / 2 && mid < 3 * Math.PI / 2)) rot += 180;
            const ink = t.hc ? t.ink : inkOn(col), shown = txt;
            shown.forEach((line, k) => el("text", { x: r1(x), y: r1(y + lbfs * 0.35 + (k - (shown.length - 1) / 2) * (lbfs + 1)), "text-anchor": "middle", "font-size": lbfs, fill: ink, class: k ? "ax" : "ttl", transform: `rotate(${r1(rot)} ${r1(x)} ${r1(y)})` }, labels, line));
        });
        /* center: the zoom root; click to go up */
        if (hole > 14) {
            const cg = el("g", { class: "center", style: path.length > 1 ? "cursor:pointer" : "" }, root);
            el("circle", { cx: r1(cx), cy: r1(cy), r: r1(hole - 2), fill: t.surface, stroke: "none" }, cg);
            const name = z === m.root ? (m.org ? z.name : "Total") : z.name;
            el("text", { x: r1(cx), y: r1(cy - 2), "text-anchor": "middle", "font-size": lbfs + 1, fill: t.text, class: "ttl" }, cg, trunc(name, hole * 1.7, lbfs + 1));
            el("text", { x: r1(cx), y: r1(cy + lbfs + 2), "text-anchor": "middle", "font-size": lbfs, fill: t.axis, class: "ax" }, cg, m.hasValue ? fmtV(z.total) : String(z.items.length));
            if (path.length > 1) cg.addEventListener("click", ev => { ev.stopPropagation(); view.zoom = view.zoom.slice(0, -1); redraw(); });
        }
    }

    /* ================================================================ circle packing */
    function drawPack() {
        const h = build();
        pack<HNode>().size([BW, BH]).padding(Math.max(0, s.pack.padding.value))(h);
        const rn = h as HierarchyCircularNode<HNode>;
        rn.descendants().filter(d => d.depth > 0).forEach(d => {
            const nd = d.data, x = box.l + d.x, y = box.t + d.y, col = colorFor(nd), isGroup = !!d.children;
            if (d.r < 0.5) return;
            const g = el("g", { class: "grp" + (on(nd) ? "" : " dim") }, marks);
            if (isGroup) el("circle", { cx: r1(x), cy: r1(y), r: r1(d.r), fill: t.hc ? t.surface : mix(col, t.surface, 0.8), stroke: t.hc ? t.ink : mix(col, t.surface, 0.45), "stroke-width": 1 }, g);
            else el("circle", { cx: r1(x), cy: r1(y), r: r1(d.r), fill: t.hc ? t.surface : look.flat ? col : look.fill(col, "r"), stroke: t.hc ? t.ink : "none" }, g);
            bindNode(g, nd, isGroup || nd.children.length > 0);
            const extra = labelText(nd);
            if (isGroup) {
                if (d.r > 30 && d.depth === 1) el("text", { x: r1(x), y: r1(y - d.r + lbfs + 4), "text-anchor": "middle", "font-size": lbfs, fill: t.text, class: "ttl lbl" }, labels, trunc(nd.name, d.r * 1.5, lbfs));
            } else if (d.r > lbfs * 1.3) {
                const ink = t.hc ? t.ink : inkOn(col), two = extra && d.r > lbfs * 2.2;
                el("text", { x: r1(x), y: r1(y + (two ? -1 : lbfs * 0.35)), "text-anchor": "middle", "font-size": lbfs, fill: ink, class: "ttl" }, labels, trunc(nd.name, d.r * 1.8, lbfs));
                if (two) el("text", { x: r1(x), y: r1(y + lbfs + 1), "text-anchor": "middle", "font-size": lbfs, fill: ink, class: "ax" }, labels, trunc(extra, d.r * 1.8, lbfs));
            }
        });
    }

    /* ================================================================ org chart / tree */
    function drawTree() {
        const TR = s.tree, lr = val(TR.orientation) === "leftRight", cw = TR.cardWidth.value, ch = TR.cardHeight.value, linkStyle = val(TR.links);
        if (!view.open) { view.open = new Set(); const lim = Math.max(1, TR.expanded.value); m.nodes.concat([m.root]).forEach(nd => { if (nd.depth < lim - 1 + (m.root.depth)) view.open?.add(nd.key); }); }
        const open = view.open;
        const h = hierarchy<HNode>(m.root, nd => (nd === m.root || open.has(nd.key) ? (nd.children.length ? nd.children : null) : null));
        const gapX = lr ? ch * 0.5 : 14, gapY = lr ? 46 : ch * 0.9;
        tree<HNode>().nodeSize(lr ? [ch + gapX, cw + gapY] : [cw + gapX, ch + gapY]).separation((a, b) => (a.parent === b.parent ? 1 : 1.15))(h);
        const pn = h as HierarchyPointNode<HNode>, all = pn.descendants();
        const pos = (d: HierarchyPointNode<HNode>): [number, number] => (lr ? [d.y, d.x] : [d.x, d.y]);
        const barMax = Math.max(...all.filter(d => !d.children).map(d => d.data.total), 1), showBars = TR.bars.value && m.hasValue, barW = showBars ? (lr ? 90 : 0) : 0;
        let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
        all.forEach(d => { const [x, y] = pos(d); x0 = Math.min(x0, x - cw / 2); x1 = Math.max(x1, x + cw / 2 + (lr && !d.children ? barW : 0)); y0 = Math.min(y0, y - ch / 2); y1 = Math.max(y1, y + ch / 2 + (!lr && showBars && !d.children ? 10 : 0)); });
        /* fit the tile, but never below 60%: a larger tree scrolls instead */
        const k = Math.max(0.6, Math.min(1, BW / Math.max(1, x1 - x0), BH / Math.max(1, y1 - y0)));
        const cwid = (x1 - x0) * k, chgt = (y1 - y0) * k;
        if (cwid > BW + 1 || chgt > BH + 1) {
            c.grow(box.l + cwid + pad * 2, box.t + chgt + pad * 2);
            /* start scrolled to the top of the tree (the root card) */
            const host = root.ownerSVGElement && root.ownerSVGElement.parentElement;
            if (host && !lr) host.scrollLeft = Math.max(0, (pos(pn)[0] - x0) * k + box.l - BW / 2);
        }
        const ox = box.l + Math.max(0, (BW - cwid) / 2) - x0 * k, oy = box.t + (lr ? Math.max(0, (BH - chgt) / 2) : 0) - y0 * k;
        const g0 = el("g", { transform: `translate(${r1(ox)},${r1(oy)}) scale(${r1(k * 1000) / 1000})` }, root);
        const links = el("g", { fill: "none", stroke: mix(t.text, t.surface, 0.62), "stroke-width": 1.4 }, g0);
        all.filter(d => d.parent).forEach(d => {
            const [px, py] = pos(d.parent as HierarchyPointNode<HNode>), [x, y] = pos(d);
            const sx = lr ? px + cw / 2 : px, sy = lr ? py : py + ch / 2, tx = lr ? x - cw / 2 : x, ty = lr ? y : y - ch / 2;
            let dd: string;
            if (linkStyle === "straight") dd = `M${r1(sx)},${r1(sy)}L${r1(tx)},${r1(ty)}`;
            else if (linkStyle === "curve") dd = lr ? `M${r1(sx)},${r1(sy)}C${r1((sx + tx) / 2)},${r1(sy)} ${r1((sx + tx) / 2)},${r1(ty)} ${r1(tx)},${r1(ty)}` : `M${r1(sx)},${r1(sy)}C${r1(sx)},${r1((sy + ty) / 2)} ${r1(tx)},${r1((sy + ty) / 2)} ${r1(tx)},${r1(ty)}`;
            else dd = lr ? `M${r1(sx)},${r1(sy)}H${r1((sx + tx) / 2)}V${r1(ty)}H${r1(tx)}` : `M${r1(sx)},${r1(sy)}V${r1((sy + ty) / 2)}H${r1(tx)}V${r1(ty)}`;
            el("path", { d: dd }, links);
        });
        const cards = el("g", sh ? { filter: sh } : {}, g0), fs2 = Math.max(7, Math.min(lbfs + 2, ch * 0.3));
        all.forEach(d => {
            const nd = d.data, [x, y] = pos(d), col = colorFor(nd), g = el("g", { class: "grp" + (on(nd) ? "" : " dim") }, cards);
            const bx = x - cw / 2, by = y - ch / 2, hasKids = nd.children.length > 0, isOpen = open.has(nd.key) || nd === m.root;
            if (look.is3d) el("rect", { x: r1(bx + 3), y: r1(by + 3), width: r1(cw), height: r1(ch), rx: 6, fill: look.side(col) }, g);
            el("rect", { x: r1(bx), y: r1(by), width: r1(cw), height: r1(ch), rx: 6, fill: t.surface, stroke: t.hc ? t.ink : mix(col, t.surface, 0.5), "stroke-width": 1 }, g);
            el("rect", { x: r1(bx), y: r1(by), width: 5, height: r1(ch), rx: 2, fill: t.hc ? t.ink : look.fill(col, "v") }, g);
            const sub = m.hasValue && LB.show.value ? fmtV(nd.total) : m.org && nd.count ? `${nd.count} below` : "";
            el("text", { x: r1(bx + 11), y: r1(sub ? y - 2 : y + fs2 * 0.35), "font-size": fs2, fill: t.ink, class: "ttl" }, g, trunc(nd.name, cw - 18 - (hasKids && TR.badges.value ? 22 : 0), fs2));
            if (sub) el("text", { x: r1(bx + 11), y: r1(y + fs2), "font-size": Math.max(6, fs2 - 1), fill: t.axis, class: "ax" }, g, trunc(sub, cw - 18, fs2 - 1));
            if (hasKids && (TR.badges.value || !isOpen)) {
                const bxr = bx + cw - 12, label = isOpen ? "−" : TR.badges.value && m.org ? String(nd.count) : "+";
                el("circle", { cx: r1(bxr), cy: r1(y), r: 8, fill: isOpen ? mix(col, t.surface, 0.8) : t.hc ? t.ink : col }, g);
                el("text", { x: r1(bxr), y: r1(y + 3.2), "text-anchor": "middle", "font-size": 8.5, fill: isOpen ? t.ink : t.hc ? t.surface : inkOn(col), class: "ttl" }, g, label);
            }
            if (showBars && !d.children && !hasKids) {
                const w = (lr ? barW - 8 : cw - 10) * nd.total / barMax;
                el("rect", lr ? { x: r1(bx + cw + 6), y: r1(y - ch * 0.18), width: r1(Math.max(1, w)), height: r1(ch * 0.36), rx: 2, fill: look.fill(col, "h") } : { x: r1(bx + 5), y: r1(by + ch + 4), width: r1(Math.max(1, w)), height: 5, rx: 2, fill: look.fill(col, "h") }, g);
            }
            c.bind(g, target(nd)); if (hasKids) (g as SVGElement).style.cursor = "pointer";
            if (hasKids) {
                const toggle = (ev: Event) => { ev.stopImmediatePropagation(); if (open.has(nd.key)) open.delete(nd.key); else open.add(nd.key); redraw(); };
                if (zoomOnClick) { g.addEventListener("click", toggle, true); }
                else g.addEventListener("dblclick", toggle);
            }
        });
    }
}
