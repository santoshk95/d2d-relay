/*
 * Atlas Columns: clustered, stacked and 100% stacked columns and bars,
 * rebuilt as a custom visual with drill-down, cross-highlighting,
 * selection, report-page tooltips and three looks. Colors follow the
 * report theme, a brand color or a pasted palette.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { FormattingSettingsService, formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import "./../style/visual.less";
import { ColumnsSettings } from "./settings";
import { Model, Pt, Ser, readModel } from "./model";
import { render, Drawn } from "./render";
import { Look, LookName, el, clear, setFont } from "./common/look";
import { colorOr } from "./common/cards";
import { mix, isHex, normHex } from "./common/color";
import { colorer, isDark, formatter, landing } from "./common/util";
import { DrillBar } from "./common/drill";
import { choose } from "./common/interact";
import { selMark } from "./common/corner";
import { dataViewWildcard } from "powerbi-visuals-utils-dataviewutils";

import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import IVisual = powerbi.extensibility.visual.IVisual;
import IVisualHost = powerbi.extensibility.visual.IVisualHost;
import ISelectionManager = powerbi.extensibility.ISelectionManager;
import ISelectionId = powerbi.visuals.ISelectionId;

/* instance counter keeps gradient and filter ids unique when several visuals share a page */
let SEQ = 0;
export class Visual implements IVisual {
    private host: IVisualHost;
    private sm: ISelectionManager;
    private fss: FormattingSettingsService;
    private lm: powerbi.extensibility.ILocalizationManager;
    private settings: ColumnsSettings = new ColumnsSettings();
    private root: HTMLElement;
    private back: SVGSVGElement; private backG: SVGGElement;
    private scroller: HTMLDivElement; private front: SVGSVGElement; private frontG: SVGGElement;
    private over: SVGSVGElement; private overG: SVGGElement;
    private drillBar: DrillBar;
    private look: Look;
    private model: Model | null = null;
    private viewport = { width: 300, height: 200 };
    private sel = new Set<string>();
    private drawn: Drawn | null = null;
    private loc(key: string, fallback: string): string { const t = this.lm && this.lm.getDisplayName(key); return t && t !== key ? t : fallback; }

    constructor(options: VisualConstructorOptions) {
        this.host = options.host;
        this.sm = this.host.createSelectionManager();
        this.lm = this.host.createLocalizationManager();
        this.fss = new FormattingSettingsService(this.lm);
        this.root = options.element;
        this.root.classList.add("atl", "atl-cols");
        this.back = el("svg", { class: "atl-svg atl-layer" });
        const defs = el("defs", {}, this.back);
        this.backG = el("g", {}, this.back);
        this.look = new Look(defs, "atlc" + (++SEQ) + "-");
        this.scroller = document.createElement("div"); this.scroller.className = "atl-scroll";
        this.front = el("svg", { class: "atl-svg", role: "img" }, this.scroller);
        this.frontG = el("g", {}, this.front);
        this.over = el("svg", { class: "atl-svg atl-layer atl-over" });
        this.overG = el("g", {}, this.over);
        this.drillBar = new DrillBar(this.host, this.root, (k, f) => this.loc(k, f));
        this.mount();
        const clearAll = (ev: MouseEvent) => { if (ev.target === this.front || ev.target === this.back) { if (!this.host.hostCapabilities.allowInteractions) return; this.sel.clear(); this.sm.clear(); this.draw(); } };
        this.front.addEventListener("click", clearAll); this.back.addEventListener("click", clearAll);
        const menu = (ev: MouseEvent) => { if (ev.target === this.front || ev.target === this.back) { ev.preventDefault(); this.sm.showContextMenu({} as ISelectionId, { x: ev.clientX, y: ev.clientY }); } };
        this.front.addEventListener("contextmenu", menu); this.back.addEventListener("contextmenu", menu);
        /* a vertical mouse wheel scrolls a wide column chart sideways */
        this.scroller.addEventListener("wheel", ev => {
            const sc = this.scroller;
            if (sc.scrollWidth > sc.clientWidth + 1 && Math.abs(ev.deltaY) > Math.abs(ev.deltaX)) { sc.scrollLeft += ev.deltaY; ev.preventDefault(); }
        }, { passive: false });
        this.sm.registerOnSelectCallback((ids: ISelectionId[]) => { this.syncSelection(ids); this.draw(); });
    }

    private mount() {
        [this.back, this.scroller, this.over].forEach(n => this.root.appendChild(n));
    }

    public update(options: VisualUpdateOptions) {
        this.host.eventService.renderingStarted(options);
        try {
            this.viewport = { width: Math.max(1, options.viewport.width), height: Math.max(1, options.viewport.height) };
            const dv = options.dataViews && options.dataViews[0];
            this.settings = this.fss.populateFormattingSettingsModel(ColumnsSettings, dv);
            this.drillBar.allow(this.settings.drill.allow.value);
            this.model = readModel(dv, this.host);
            if (this.model) this.drillBar.afterUpdate(this.model.drill);
            if (!this.model) {
                landing(this.root, "Atlas Columns", [
                    this.loc("Landing_Line1", "Add a field to the Category axis and one or more Values to draw columns or bars."),
                    this.loc("Landing_Line2", "Add a hierarchy such as Year, Quarter and Month to drill down. Pick the chart type, look and palette in the Format pane.")]);
                this.mount(); [this.back, this.scroller, this.over].forEach(n => (n.style.display = "none")); this.drillBar.draw(false, [], false);
            } else {
                this.root.querySelectorAll(".atl-landing").forEach(n => n.remove());
                [this.back, this.scroller, this.over].forEach(n => (n.style.display = ""));
                this.colorize(this.model);
                if (this.model.cats.length >= 5000) this.host.displayWarningIcon(this.loc("Warn_Limit_Title", "Showing the first 5,000 categories"), this.loc("Warn_Limit_Text", "There are more categories than the visual can show. Filter the report or drill down to see the rest."));
                this.syncSelection(this.sm.getSelectionIds() as ISelectionId[]);
                this.draw();
            }
            this.host.eventService.renderingFinished(options);
        } catch (err) {
            this.host.eventService.renderingFailed(options, String(err));
        }
    }

    /** series (or category) colors from the palette, with per-item overrides from the Format pane */
    private colorize(m: Model) {
        const p = this.settings.palette, dark = isDark(this.host);
        const pal = colorer({ source: String(p.source.value.value), brand: p.brand.value.value, mode: String(p.mode.value.value), custom: p.custom.value }, this.host, dark);
        m.series.forEach(s => { if (!s.color || !isHex(s.color)) s.color = pal(s.name, s.i); });
        const byCat = p.varyByCategory.value && m.series.length === 1 && m.levelNames.length > 0;
        if (byCat) m.cats.forEach(c => { c.color = c.override && isHex(c.override) ? c.override : pal(c.key, c.i); });
        /* one series: colors can be set per category or by a conditional-formatting rule (fx), like the built-in charts */
        const rule = { selector: dataViewWildcard.createDataViewWildcardSelector(dataViewWildcard.DataViewWildcardMatchingOption.InstancesAndTotals), instanceKind: powerbi.VisualEnumerationInstanceKinds.ConstantOrRule };
        const dc = this.settings.dataColors, single = m.series.length === 1;
        dc.slices = byCat
            ? m.cats.filter(c => c.selector).slice(0, 60).map(c => new fs.ColorPicker({ name: "fill", displayName: c.path.join(" "), value: { value: c.color as string }, ...rule, altConstantSelector: c.selector as powerbi.data.Selector }))
            : single
                ? [new fs.ColorPicker({ name: "fill", displayName: this.loc("Default_Color", "Default color"), value: { value: m.series[0].color }, ...rule, altConstantSelector: m.series[0].selector })]
                : m.series.slice(0, 60).map(s => new fs.ColorPicker({ name: "fill", displayName: s.name, value: { value: s.color }, selector: s.selector }));
    }
    private colorOf(p: Pt): string {
        const m = this.model as Model;
        if (this.host.colorPalette.isHighContrast) return this.host.colorPalette.foreground.value;
        const c = m.cats[p.c];
        if (m.series.length === 1 && c.override && isHex(c.override)) return c.override;
        return this.settings.palette.varyByCategory.value && m.series.length === 1 && c.color ? c.color : m.series[p.s].color;
    }

    private keyOf(p: Pt) { return "p" + p.c + "|" + p.s; }
    private syncSelection(ids: ISelectionId[]) {
        this.sel.clear();
        const m = this.model; if (!m || !ids || !ids.length) return;
        ids.forEach(id => {
            const s = m.series.find(x => x.id.equals(id)); if (s) { this.sel.add("s" + s.i); return; }
            m.pts.forEach(p => { if (p.id.equals(id)) this.sel.add(this.keyOf(p)); });
            m.cats.forEach(c => { if (c.id && c.id.equals(id)) m.pts.forEach(p => { if (p.c === c.i) this.sel.add(this.keyOf(p)); }); });
        });
    }

    private draw() {
        const m = this.model; if (!m) return;
        const s = this.settings, W = this.viewport.width, H = this.viewport.height, cp = this.host.colorPalette, hc = cp.isHighContrast;
        const fg = cp.foreground && isHex(cp.foreground.value) ? normHex(cp.foreground.value) : "#252423";
        const ink = hc ? fg : colorOr(s.style.textColor, fg), font = String(s.style.fontFamily.value || "");
        setFont(font);
        const surface = cp.background && isHex(cp.background.value) ? normHex(cp.background.value) : "#ffffff";
        const lookName = (hc ? "flat" : String(s.chart.look.value.value)) as LookName;
        this.look.reset(lookName, isDark(this.host) ? "#000000" : mix(ink, "#000000", 0.5), s.chart.shadow.value);
        clear(this.backG); clear(this.frontG); clear(this.overG);
        [this.back, this.over].forEach(svg => { svg.setAttribute("width", String(W)); svg.setAttribute("height", String(H)); });
        this.root.style.fontFamily = font; this.root.style.color = ink; this.root.style.setProperty("--atl-halo", surface);
        const anySel = this.sel.size > 0;
        const drillButtons = s.drill.buttons.value && m.drill.length > 0 && this.host.hostCapabilities.allowInteractions;
        this.drawn = render({
            W, H, m, s, look: this.look, ink, surface, hc, culture: this.host.locale, drillButtons,
            L: { back: this.backG, scroller: this.scroller, front: this.front, frontG: this.frontG, over: this.overG },
            colorOf: p => this.colorOf(p),
            isSelected: p => this.sel.has(this.keyOf(p)) || this.sel.has("s" + p.s), anySelected: anySel,
            seriesDim: sr => anySel && !this.sel.has("s" + sr.i) && !m.pts.some(p => p.s === sr.i && this.sel.has(this.keyOf(p))),
            bindPoint: (e, p) => this.bindPoint(e, p),
            bindSeries: (e, sr) => this.bindSeries(e, sr),
            bindCat: (e, ci) => this.bindCat(e, ci)
        });
        const type = String(s.chart.chartType.value.value), names: Record<string, string> = { clusteredColumn: "Clustered column", stackedColumn: "Stacked column", percentColumn: "100% stacked column", clusteredBar: "Clustered bar", stackedBar: "Stacked bar", percentBar: "100% stacked bar" };
        this.front.setAttribute("aria-label", `${names[type] || "Column"} chart of ${m.valueNames.join(", ")}${m.levelNames.length ? " by " + m.levelNames.join(", ") : ""}${m.legendTitle ? " and " + m.legendTitle : ""}`);
        const clearSel = () => { this.sel.clear(); this.sm.clear(); this.draw(); };
        this.drillBar.draw(drillButtons, m.drill, m.drillDisabled, { any: this.sel.size > 0, clear: clearSel });
        selMark(this.root, s.style.mark(anySel, false, m.highlights, (k, f) => this.loc(k, f), clearSel, () => undefined));
    }

    private tooltip(p: Pt): powerbi.extensibility.VisualTooltipDataItem[] {
        const m = this.model as Model, ser = m.series[p.s], c = m.cats[p.c], culture = this.host.locale;
        const f = formatter(ser.format, 1, null, p.v, culture), items: powerbi.extensibility.VisualTooltipDataItem[] = [];
        m.levelNames.forEach((nm, k) => items.push({ displayName: nm, value: c.path[k] }));
        if (m.seriesField) items.push({ displayName: m.legendTitle, value: ser.name });
        items.push({ displayName: m.seriesField ? ser.measure : ser.name, value: f(p.v), color: this.colorOf(p) });
        const d = this.drawn;
        if (d && (d.mode === "percent" || String(this.settings.labels.content.value.value) !== "value")) items.push({ displayName: m.series.length > 1 ? "Share of " + (c.label || "total") : "Share of total", value: d.pct(p.share || 0) });
        if (p.hl !== null) items.push({ displayName: "Highlighted", value: f(p.hl) });
        p.tips.forEach(t => items.push({ displayName: t.name, value: t.value }));
        return items;
    }

    /** tooltips, selection, context menu and keyboard access for one bar */
    private bindPoint(e: SVGElement, p: Pt) {
        const key = this.keyOf(p);
        e.setAttribute("tabindex", "0"); e.setAttribute("focusable", "true");
        const xy = (ev: MouseEvent) => { const r = this.root.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
        const ts = this.host.tooltipService;
        e.addEventListener("mouseenter", ev => { if (ts.enabled()) ts.show({ coordinates: xy(ev), isTouchEvent: false, dataItems: this.tooltip(p), identities: [p.id] }); });
        e.addEventListener("mousemove", ev => { if (ts.enabled()) ts.move({ coordinates: xy(ev), isTouchEvent: false, dataItems: this.tooltip(p), identities: [p.id] }); });
        e.addEventListener("mouseleave", () => ts.hide({ isTouchEvent: false, immediately: true }));
        const pick = (multi: boolean) => {
            if (!this.host.hostCapabilities.allowInteractions) return;
            choose(this.sm, [p.id], multi, this.settings.style.keepOthers.value);
            if (multi) { if (this.sel.has(key)) this.sel.delete(key); else this.sel.add(key); }
            else if (this.sel.size === 1 && this.sel.has(key)) this.sel.clear();
            else { this.sel.clear(); this.sel.add(key); }
            if (!this.sel.size) this.sm.clear();
            this.draw();
        };
        e.addEventListener("click", ev => { ev.stopPropagation(); pick(ev.ctrlKey || ev.metaKey); });
        e.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev.ctrlKey || ev.metaKey); } });
        e.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); this.sm.showContextMenu(p.id, { x: ev.clientX, y: ev.clientY }); });
    }
    /** a category label selects the whole category, like clicking every bar in it */
    private bindCat(e: SVGElement, ci: number): SVGElement {
        const m = this.model, cat = m && m.cats[ci];
        if (!m || !cat || !cat.id || !this.host.hostCapabilities.allowInteractions) return e;
        const id = cat.id, keys = m.pts.filter(p => p.c === ci).map(p => this.keyOf(p));
        e.style.pointerEvents = "all"; e.style.cursor = "pointer";
        e.setAttribute("tabindex", "0"); e.setAttribute("role", "button"); e.setAttribute("aria-label", cat.path.filter(x => x !== "").join(" "));
        const pick = (multi: boolean) => {
            const all = keys.every(k => this.sel.has(k));
            choose(this.sm, [id], multi, this.settings.style.keepOthers.value);
            if (multi) keys.forEach(k => (all ? this.sel.delete(k) : this.sel.add(k)));
            else if (all && this.sel.size === keys.length) this.sel.clear();
            else { this.sel.clear(); keys.forEach(k => this.sel.add(k)); }
            if (!this.sel.size) this.sm.clear();
            this.draw();
        };
        e.addEventListener("click", ev => { ev.stopPropagation(); pick(ev.ctrlKey || ev.metaKey); });
        e.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev.ctrlKey || ev.metaKey); } });
        e.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); this.sm.showContextMenu(id, { x: ev.clientX, y: ev.clientY }); });
        return e;
    }
    private bindSeries(e: SVGElement, sr: Ser) {
        const key = "s" + sr.i;
        e.setAttribute("tabindex", "0"); e.setAttribute("role", "button"); e.setAttribute("aria-label", sr.name);
        const pick = (multi: boolean) => {
            if (!this.host.hostCapabilities.allowInteractions) return;
            choose(this.sm, [sr.id], multi, this.settings.style.keepOthers.value);
            if (multi) { if (this.sel.has(key)) this.sel.delete(key); else this.sel.add(key); }
            else if (this.sel.size === 1 && this.sel.has(key)) this.sel.clear();
            else { this.sel.clear(); this.sel.add(key); }
            if (!this.sel.size) this.sm.clear();
            this.draw();
        };
        e.addEventListener("click", ev => { ev.stopPropagation(); pick(ev.ctrlKey || ev.metaKey); });
        e.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev.ctrlKey || ev.metaKey); } });
        e.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); this.sm.showContextMenu(sr.id, { x: ev.clientX, y: ev.clientY }); });
    }

    public getFormattingModel(): powerbi.visuals.FormattingModel {
        const m = this.model;
        this.settings.tidy({ series: m ? m.series.length : 1, levels: m ? m.levels : 1, drillable: !!m && m.drill.length > 0 });
        this.settings.style.tidy();
        return this.fss.buildFormattingModel(this.settings);
    }
}
