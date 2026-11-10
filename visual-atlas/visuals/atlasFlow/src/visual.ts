/*
 * Atlas Flow: Sankey, chord and network in one Power BI visual.
 * Bound to Source, Target and Weight; colors follow the report theme,
 * a brand color or a pasted palette; every option is in the Format pane.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { FormattingSettingsService, formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import "./../style/visual.less";
import { FlowSettings } from "./settings";
import { FNode, FLink, Ctx, nodeKey, linkKey } from "./model";
import { drawSankey } from "./sankey";
import { drawChord } from "./chord";
import { drawNetwork } from "./network";
import { Look, LookName, el, clear, setFont } from "./common/look";
import { colorOr } from "./common/cards";
import { mix, isHex, normHex } from "./common/color";
import { colorer, isDark, formatter, landing } from "./common/util";
import { hlModeOf } from "./common/data";
import { selMark } from "./common/corner";
import { choose } from "./common/interact";

import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import IVisual = powerbi.extensibility.visual.IVisual;
import IVisualHost = powerbi.extensibility.visual.IVisualHost;
import ISelectionManager = powerbi.extensibility.ISelectionManager;
import DataView = powerbi.DataView;

/* instance counter keeps gradient and filter ids unique when several visuals share a page */
let SEQ = 0;

export class Visual implements IVisual {
    private host: IVisualHost;
    private sm: ISelectionManager;
    private fss: FormattingSettingsService;
    private settings: FlowSettings = new FlowSettings();
    private root: HTMLElement;
    private svg: SVGSVGElement;
    private plot: SVGGElement;
    private look: Look;
    private dataView: DataView | null = null;
    private viewport = { width: 300, height: 200 };
    private sel = new Set<string>();
    private nodes: FNode[] = [];
    private links: FLink[] = [];
    private names = { source: "Source", target: "Target", weight: "Weight" };
    private fmt: (v: number) => string = v => String(v);
    private lm: powerbi.extensibility.ILocalizationManager;
    private loc(key: string, fallback: string): string { const t = this.lm && this.lm.getDisplayName(key); return t && t !== key ? t : fallback; }

    constructor(options: VisualConstructorOptions) {
        this.host = options.host;
        this.sm = this.host.createSelectionManager();
        this.lm = this.host.createLocalizationManager();
        this.fss = new FormattingSettingsService(this.lm);
        this.root = options.element;
        this.root.classList.add("atl");
        this.svg = el("svg", { class: "atl-svg", role: "img" });
        const defs = el("defs", {}, this.svg);
        this.plot = el("g", {}, this.svg);
        this.look = new Look(defs, "atlf" + (++SEQ) + "-");
        this.root.appendChild(this.svg);
        this.svg.addEventListener("click", e => { if (e.target === this.svg && this.host.hostCapabilities.allowInteractions) { this.sel.clear(); this.sm.clear(); this.draw(); } });
        this.svg.addEventListener("contextmenu", e => { if (e.target === this.svg) { e.preventDefault(); this.sm.showContextMenu({} as powerbi.visuals.ISelectionId, { x: e.clientX, y: e.clientY }); } });
        this.sm.registerOnSelectCallback(() => { this.sel.clear(); this.draw(); });
    }

    public update(options: VisualUpdateOptions) {
        this.host.eventService.renderingStarted(options);
        try {
            this.viewport = { width: Math.max(1, options.viewport.width), height: Math.max(1, options.viewport.height) };
            const dv = options.dataViews && options.dataViews[0];
            this.settings = this.fss.populateFormattingSettingsModel(FlowSettings, dv);
            this.dataView = dv || null;
            if (!this.read(dv)) {
                this.svg.style.display = "none";
                landing(this.root, "Atlas Flow", [this.loc("Landing_Line1", "Add a Source, a Target and a Weight to draw a Sankey, chord or network."), this.loc("Landing_Line2", "Pick the chart type, look and palette in the Format pane.")]);
                this.root.appendChild(this.svg);
            } else {
                this.root.querySelectorAll(".atl-landing").forEach(n => n.remove());
                this.svg.style.display = "";
                this.draw();
            }
            this.host.eventService.renderingFinished(options);
        } catch (err) {
            this.host.eventService.renderingFailed(options, String(err));
        }
    }

    /** build nodes and links from the categorical data view; false when fields are missing */
    private read(dv: DataView | undefined): boolean {
        this.nodes = []; this.links = [];
        const cat = dv && dv.categorical, cats = (cat && cat.categories) || [];
        const sc = cats.find(c => c.source.roles && c.source.roles["source"]), tc = cats.find(c => c.source.roles && c.source.roles["target"]);
        const vals = (cat && cat.values) || [], wc = vals.find(v => v.source.roles && v.source.roles["weight"]);
        if (!sc || !tc || !wc) return false;
        const tips = vals.filter(v => v.source.roles && v.source.roles["tooltips"]);
        this.names = { source: sc.source.displayName, target: tc.source.displayName, weight: wc.source.displayName };
        const dark = isDark(this.host), s = this.settings, p = s.palette;
        const color = colorer({ source: String(p.source.value.value), brand: p.brand.value.value, mode: String(p.mode.value.value), custom: p.custom.value }, this.host, dark);
        const idx = new Map<string, FNode>(), hl = wc.highlights;
        const node = (name: string, col: powerbi.DataViewCategoryColumn, row: number): FNode => {
            let nd = idx.get(name);
            if (!nd) {
                const sel = this.host.createSelectionIdBuilder().withCategory(col, row).createSelectionId();
                nd = { key: name, name, i: idx.size, inV: 0, outV: 0, value: 0, deg: 0, color: "", sel, selector: sel.getSelector(), highlighted: false };
                const o = col.objects && col.objects[row], fill = o && o["nodeColors"] && (o["nodeColors"]["fill"] as powerbi.Fill);
                if (fill && fill.solid && fill.solid.color) nd.color = fill.solid.color;
                idx.set(name, nd);
            }
            return nd;
        };
        const n = sc.values.length;
        let maxV = 0;
        /* under a cross-highlight the flows show their highlighted part, as a filter would (unless nothing matches) */
        const useHl = !!hl && hlModeOf([wc]) === "filter" && Array.from({ length: n }, (_, r) => Number((hl as powerbi.PrimitiveValue[])[r]) || 0).some(x => x > 0);
        for (let r = 0; r < n; r++) {
            const v = useHl ? Number((hl as powerbi.PrimitiveValue[])[r]) || 0 : Number(wc.values[r]);
            if (!(v > 0)) continue;
            const a = node(sc.values[r] == null ? "(Blank)" : String(sc.values[r]), sc, r), b = node(tc.values[r] == null ? "(Blank)" : String(tc.values[r]), tc, r);
            const h = hl ? Number(hl[r]) || 0 : null;
            a.outV += v; b.inV += v; a.deg++; b.deg++; if (h) { a.highlighted = true; b.highlighted = true; }
            maxV = Math.max(maxV, v);
            const sel = this.host.createSelectionIdBuilder().withCategory(sc, r).withCategory(tc, r).createSelectionId();
            this.links.push({ s: a.i, t: b.i, v, hl: h, row: r, sel, tips: tips.map(tcol => ({ name: tcol.source.displayName, value: formatter(tcol.source.format, 1, null, Number(tcol.values[r]))(Number(tcol.values[r])) })) });
        }
        if (n >= 30000) this.host.displayWarningIcon(this.loc("Warn_Limit_Title", "Showing the first 30,000 rows"), this.loc("Warn_Limit_Text", "There are more source and target pairs than the visual can show. Filter the report to see the rest."));
        this.nodes = [...idx.values()];
        this.nodes.forEach(nd => { nd.value = Math.max(nd.inV, nd.outV); if (!nd.color || !isHex(nd.color)) nd.color = color(nd.key, nd.i); });
        const lb = s.labels;
        this.fmt = formatter(wc.source.format, Number(lb.displayUnits.value) || 0, lb.decimals.value, Math.max(maxV, ...this.nodes.map(nd => nd.value)));
        /* one color picker per node in the Format pane (first 60) */
        s.nodeColors.slices = this.nodes.slice(0, 60).map(nd => new fs.ColorPicker({ name: "fill", displayName: nd.name, value: { value: nd.color }, selector: nd.selector }));
        return this.nodes.length > 0;
    }

    private draw() {
        if (!this.dataView || !this.nodes.length) return;
        const s = this.settings, W = this.viewport.width, H = this.viewport.height, cp = this.host.colorPalette, hc = cp.isHighContrast;
        const fg = cp.foreground && isHex(cp.foreground.value) ? normHex(cp.foreground.value) : "#252423";
        const ink = hc ? fg : colorOr(s.style.textColor, fg), font = String(s.style.fontFamily.value || "");
        setFont(font);
        const surface = cp.background && isHex(cp.background.value) ? normHex(cp.background.value) : "#ffffff";
        const lookName = (hc ? "flat" : String(s.chart.look.value.value)) as LookName;
        this.look.reset(lookName, isDark(this.host) ? "#000000" : mix(ink, "#000000", 0.5), s.chart.shadow.value);
        clear(this.plot);
        this.svg.setAttribute("width", String(W)); this.svg.setAttribute("height", String(H)); this.svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
        this.svg.style.fontFamily = font; this.svg.style.setProperty("--atl-halo", surface);
        const lb = s.labels, chosen = lb.color.value && lb.color.value.value;
        const ctx: Ctx = {
            root: this.plot, W, H, look: this.look, nodes: this.nodes, links: this.links, fmt: this.fmt,
            label: { show: lb.show.value, size: Math.max(6, lb.fontSize.value), color: chosen && isHex(chosen) ? chosen : mix(ink, surface, 0.18), values: lb.showValues.value },
            ink, surface, muted: mix(ink, surface, 0.72), grid: mix(ink, surface, 0.88),
            highlights: this.links.some(l => l.hl !== null),
            isSelected: (k: string) => this.sel.has(k), anySelected: this.sel.size > 0,
            bind: (e, kind, i) => this.bind(e, kind, i)
        };
        const type = String(s.chart.chartType.value.value), linkBy = String(s.links.colorBy.value.value);
        this.svg.setAttribute("aria-label", `${type === "sankey" ? "Sankey" : type === "chord" ? "Chord" : "Network"} of ${this.names.weight} from ${this.names.source} to ${this.names.target}`);
        if (type === "chord") drawChord(ctx, { padDeg: s.chord.padAngle.value, arcW: Math.max(3, s.chord.arcWidth.value), opacity: s.chord.ribbonOpacity.value, linkBy });
        else if (type === "network") {
            const p = s.palette, comm = colorer({ source: String(p.source.value.value), brand: p.brand.value.value, mode: String(p.mode.value.value), custom: p.custom.value }, this.host, isDark(this.host));
            drawNetwork(ctx, { sizeBy: String(s.nodes.sizeBy.value.value), maxSize: Math.max(4, s.nodes.maxSize.value), labelCount: s.network.labelCount.value, spacing: s.network.spacing.value, colorBy: String(s.network.colorBy.value.value), opacity: s.links.opacity.value, communityColor: k => comm("community " + (k + 1), k) });
        } else drawSankey(ctx, { nodeW: Math.max(2, s.nodes.width.value), pad: Math.max(0, s.nodes.padding.value), radius: Math.max(0, s.nodes.radius.value), align: String(s.nodes.align.value.value), linkBy, opacity: s.links.opacity.value });
        selMark(this.root, s.style.mark(this.sel.size > 0, false, ctx.highlights, (k, f) => this.loc(k, f), () => { this.sel.clear(); this.sm.clear(); this.draw(); }, () => undefined));
        if (type === "sankey" && this.links.some(l => l.back)) this.host.displayWarningIcon(this.loc("Warn_Loops_Title", "Some flows loop back"), this.loc("Warn_Loops_Text", "Flows that return to an earlier stage are left out of the Sankey. Switch to Chord or Network to see them."));
    }

    /** tooltips, selection, context menu and keyboard access for one mark */
    private bind(e: SVGElement, kind: "node" | "link", i: number) {
        const nd = kind === "node" ? this.nodes[i] : null, lk = kind === "link" ? this.links[i] : null;
        if (!nd && !lk) return;
        const sel = (nd ? nd.sel : (lk as FLink).sel), key = nd ? nodeKey(nd) : linkKey(lk as FLink);
        e.setAttribute("tabindex", "0"); e.setAttribute("focusable", "true");
        e.setAttribute("aria-label", nd ? `${nd.name}: ${this.fmt(nd.value)}` : `${this.nodes[(lk as FLink).s].name} to ${this.nodes[(lk as FLink).t].name}: ${this.fmt((lk as FLink).v)}`);
        const items = (): powerbi.extensibility.VisualTooltipDataItem[] => nd
            ? [{ displayName: nd.name, value: this.fmt(nd.value), color: nd.color }, { displayName: "Incoming", value: this.fmt(nd.inV) }, { displayName: "Outgoing", value: this.fmt(nd.outV) }]
            : [{ displayName: this.names.source, value: this.nodes[(lk as FLink).s].name, color: this.nodes[(lk as FLink).s].color }, { displayName: this.names.target, value: this.nodes[(lk as FLink).t].name }, { displayName: this.names.weight, value: this.fmt((lk as FLink).v) }]
                .concat((lk as FLink).tips.map(t => ({ displayName: t.name, value: t.value, color: undefined as unknown as string })));
        const xy = (ev: MouseEvent) => { const r = this.root.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
        const ts = this.host.tooltipService;
        e.addEventListener("mouseenter", ev => { if (ts.enabled()) ts.show({ coordinates: xy(ev), isTouchEvent: false, dataItems: items(), identities: [sel] }); });
        e.addEventListener("mousemove", ev => { if (ts.enabled()) ts.move({ coordinates: xy(ev), isTouchEvent: false, dataItems: items(), identities: [sel] }); });
        e.addEventListener("mouseleave", () => ts.hide({ isTouchEvent: false, immediately: true }));
        const pick = (multi: boolean) => {
            if (!this.host.hostCapabilities.allowInteractions) return;
            choose(this.sm, [sel], multi, this.settings.style.keepOthers.value);
            if (multi) { if (this.sel.has(key)) this.sel.delete(key); else this.sel.add(key); }
            else if (this.sel.size === 1 && this.sel.has(key)) this.sel.clear();
            else { this.sel.clear(); this.sel.add(key); }
            if (!this.sel.size) this.sm.clear();
            this.draw();
        };
        e.addEventListener("click", ev => { ev.stopPropagation(); pick(ev.ctrlKey || ev.metaKey); });
        e.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev.ctrlKey || ev.metaKey); } });
        e.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); this.sm.showContextMenu(sel, { x: ev.clientX, y: ev.clientY }); });
    }

    public getFormattingModel(): powerbi.visuals.FormattingModel {
        this.settings.tidy(); this.settings.style.tidy();
        return this.fss.buildFormattingModel(this.settings);
    }
}
