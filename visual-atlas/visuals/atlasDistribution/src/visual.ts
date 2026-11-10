/*
 * Atlas Distribution: histogram, box and whisker, violin (and raincloud)
 * and parallel coordinates in one Power BI visual. One row per
 * observation (Group × Sample by); colors follow the report theme, a
 * brand color or a pasted palette; every option is in the Format pane.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { FormattingSettingsService, formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import "./../style/visual.less";
import { DistSettings } from "./settings";
import { Model, Group, readModel } from "./model";
import { render, Target } from "./render";
import { Look, LookName, el, clear, setFont } from "./common/look";
import { colorOr } from "./common/cards";
import { mix, isHex, normHex } from "./common/color";
import { colorer, isDark, landing } from "./common/util";
import { selMark } from "./common/corner";
import { choose } from "./common/interact";

import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import IVisual = powerbi.extensibility.visual.IVisual;
import IVisualHost = powerbi.extensibility.visual.IVisualHost;
import ISelectionManager = powerbi.extensibility.ISelectionManager;
import ISelectionId = powerbi.visuals.ISelectionId;

/* instance counter keeps gradient and filter ids unique when several visuals share a page */
let SEQ = 0;
const NAMES: Record<string, string> = { histogram: "Histogram", box: "Box and whisker chart", violin: "Violin chart", parallel: "Parallel coordinates chart" };

export class Visual implements IVisual {
    private host: IVisualHost;
    private sm: ISelectionManager;
    private fss: FormattingSettingsService;
    private lm: powerbi.extensibility.ILocalizationManager;
    private settings: DistSettings = new DistSettings();
    private root: HTMLElement;
    private svg: SVGSVGElement;
    private plot: SVGGElement;
    private look: Look;
    private model: Model | null = null;
    private viewport = { width: 300, height: 200 };
    /** selected targets (by key) and the observations they cover */
    private picked = new Map<string, number[]>();
    private sel = new Set<number>();
    private loc(key: string, fallback: string): string { const t = this.lm && this.lm.getDisplayName(key); return t && t !== key ? t : fallback; }

    constructor(options: VisualConstructorOptions) {
        this.host = options.host;
        this.sm = this.host.createSelectionManager();
        this.lm = this.host.createLocalizationManager();
        this.fss = new FormattingSettingsService(this.lm);
        this.root = options.element;
        this.root.classList.add("atl", "atl-dist");
        this.svg = el("svg", { class: "atl-svg", role: "img" });
        const defs = el("defs", {}, this.svg);
        this.plot = el("g", {}, this.svg);
        this.look = new Look(defs, "atld" + (++SEQ) + "-");
        this.root.appendChild(this.svg);
        this.svg.addEventListener("click", ev => {
            if (ev.target !== this.svg || !this.host.hostCapabilities.allowInteractions) return;
            this.picked.clear(); this.sel.clear(); this.sm.clear(); this.draw();
        });
        this.svg.addEventListener("contextmenu", ev => { if (ev.target === this.svg) { ev.preventDefault(); this.sm.showContextMenu({} as ISelectionId, { x: ev.clientX, y: ev.clientY }); } });
        this.sm.registerOnSelectCallback((ids: ISelectionId[]) => { this.syncSelection(ids); this.draw(); });
    }

    public update(options: VisualUpdateOptions) {
        this.host.eventService.renderingStarted(options);
        try {
            this.viewport = { width: Math.max(1, options.viewport.width), height: Math.max(1, options.viewport.height) };
            const dv = options.dataViews && options.dataViews[0];
            this.settings = this.fss.populateFormattingSettingsModel(DistSettings, dv);
            this.model = readModel(dv, this.host, String(this.settings.chart.chartType.value.value));
            if (!this.model) {
                landing(this.root, "Atlas Distribution", [
                    this.loc("Landing_Line1", "Add a measure to Values and the field that identifies one observation (Order ID, Shipment ID) to Sample by."),
                    this.loc("Landing_Line2", "Add a Group to compare distributions. Pick histogram, box, violin or parallel coordinates in the Format pane.")]);
                this.root.appendChild(this.svg); this.svg.style.display = "none";
            } else {
                this.root.querySelectorAll(".atl-landing").forEach(n => n.remove());
                this.svg.style.display = "";
                this.colorize(this.model);
                if (this.model.rows >= 30000) this.host.displayWarningIcon(this.loc("Warn_Limit_Title", "Showing the first 30,000 rows"), this.loc("Warn_Limit_Text", "There are more observations than the visual can show. Filter the report to see a complete distribution."));
                this.syncSelection(this.sm.getSelectionIds() as ISelectionId[]);
                this.draw();
            }
            this.host.eventService.renderingFinished(options);
        } catch (err) {
            this.host.eventService.renderingFailed(options, String(err));
        }
    }

    /** group colors from the palette, with per-group overrides from the Format pane */
    private colorize(m: Model) {
        const p = this.settings.palette, dark = isDark(this.host);
        const pal = colorer({ source: String(p.source.value.value), brand: p.brand.value.value, mode: String(p.mode.value.value), custom: p.custom.value }, this.host, dark);
        m.groups.forEach(g => { if (!g.color || !isHex(g.color)) g.color = pal(g.name, g.i); });
        this.settings.dataColors.slices = m.groups.filter(g => g.selector).slice(0, 60).map(g => new fs.ColorPicker({
            name: "fill", displayName: m.groups.length === 1 && !m.hasGroup ? this.loc("Default_Color", "Default color") : g.name,
            value: { value: g.color }, selector: g.selector as powerbi.data.Selector
        }));
    }
    private colorOf(g: Group): string {
        return this.host.colorPalette.isHighContrast ? this.host.colorPalette.foreground.value : g.color;
    }

    /** selection made elsewhere (bookmarks, other visuals) mapped back to observations */
    private syncSelection(ids: ISelectionId[]) {
        this.picked.clear(); this.sel.clear();
        const m = this.model; if (!m || !ids || !ids.length) return;
        ids.forEach(id => {
            const g = m.groups.find(x => x.id && x.id.equals(id));
            if (g) { this.picked.set("g" + g.i, g.obs); g.obs.forEach(i => this.sel.add(i)); return; }
            m.obs.forEach(o => { if (o.id.equals(id)) { this.picked.set("o" + o.i, [o.i]); this.sel.add(o.i); } });
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
        clear(this.plot);
        this.svg.setAttribute("width", String(W)); this.svg.setAttribute("height", String(H));
        this.root.style.fontFamily = font; this.root.style.color = ink; this.root.style.setProperty("--atl-halo", surface);
        let active: Set<number> | null = null;
        if (this.sel.size) active = this.sel;
        else if (m.highlights) active = new Set(m.obs.filter(o => o.hl).map(o => o.i));
        const type = String(s.chart.chartType.value.value);
        selMark(this.root, s.style.mark(this.sel.size > 0, false, !!m.highlights, (k, f) => this.loc(k, f), () => { this.picked.clear(); this.sel.clear(); this.sm.clear(); this.draw(); }, () => undefined));
        render({
            W, H, m, s, look: this.look, root: this.plot, ink, surface, hc, culture: this.host.locale, active,
            colorOf: g => this.colorOf(g), bind: (e, t) => this.bind(e, t), msg: (k, f) => this.loc(k, f)
        });
        const what = m.byMeasure ? m.measures.map(x => x.name).join(", ") : type === "parallel" ? m.measures.map(x => x.name).join(", ") : m.measures[0].name;
        this.svg.setAttribute("aria-label", `${NAMES[type] || "Distribution chart"} of ${what}${m.hasGroup ? " by " + m.groupTitle : ""}`);
    }

    /** tooltips, selection, context menu and keyboard access for one mark */
    private bind(e: SVGElement, t: Target) {
        e.setAttribute("tabindex", "0"); e.setAttribute("focusable", "true");
        const ts = this.host.tooltipService;
        const xy = (ev: MouseEvent) => { const r = this.root.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
        const ids = t.ids.slice(0, 50);
        e.addEventListener("mouseenter", ev => { if (ts.enabled()) ts.show({ coordinates: xy(ev), isTouchEvent: false, dataItems: t.tip(), identities: ids }); });
        e.addEventListener("mousemove", ev => { if (ts.enabled()) ts.move({ coordinates: xy(ev), isTouchEvent: false, dataItems: t.tip(), identities: ids }); });
        e.addEventListener("mouseleave", () => ts.hide({ isTouchEvent: false, immediately: true }));
        const pick = (multi: boolean) => {
            if (!this.host.hostCapabilities.allowInteractions || !t.ids.length) return;
            choose(this.sm, t.ids, multi, this.settings.style.keepOthers.value);
            if (multi) { if (this.picked.has(t.key)) this.picked.delete(t.key); else this.picked.set(t.key, t.obs); }
            else if (this.picked.size === 1 && this.picked.has(t.key)) this.picked.clear();
            else { this.picked.clear(); this.picked.set(t.key, t.obs); }
            this.sel.clear(); this.picked.forEach(list => list.forEach(i => this.sel.add(i)));
            if (!this.picked.size) this.sm.clear();
            this.draw();
        };
        e.addEventListener("click", ev => { ev.stopPropagation(); pick(ev.ctrlKey || ev.metaKey); });
        e.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev.ctrlKey || ev.metaKey); } });
        e.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); this.sm.showContextMenu(t.ids[0] || ({} as ISelectionId), { x: ev.clientX, y: ev.clientY }); });
    }

    public getFormattingModel(): powerbi.visuals.FormattingModel {
        const m = this.model;
        this.settings.tidy({ groups: m ? m.groups.length : 0, measures: m ? m.measures.length : 1 });
        this.settings.style.tidy();
        return this.fss.buildFormattingModel(this.settings);
    }
}
