/*
 * Base class for the Atlas family visuals. It does the host wiring every
 * family shares: one SVG with its own <defs>, the look (flat, soft, 3D),
 * the Style card (font, text color), palette and per-item colors,
 * selection sync, highlights, landing page, rendering events and the
 * row-limit warning. A family supplies read() and draw().
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { FormattingSettingsService, formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { Look, LookName, el, clear, setFont } from "./look";
import { mix, isHex, normHex } from "./color";
import { colorer, isDark, landing } from "./util";
import { StyleCard, PaletteCard, DataColorsCard, colorOr, val } from "./cards";
import { Interact, Target } from "./interact";
import { selMark, resetButton } from "./corner";
import ISelectionId = powerbi.visuals.ISelectionId;

/** something that gets a palette color and a color picker in the Colors card (a series, a group, a category) */
export interface Colored { key: string; name: string; color: string; selector: powerbi.data.Selector | null; id: ISelectionId | null; items: number[]; }
export interface BaseModel {
    colored: Colored[];
    /** selection id of every item (row) */
    ids: ISelectionId[];
    /** highlighted items, or null when the report sends no highlights */
    hl: Set<number> | null;
    rows: number;
}
export interface FamilySettings extends fs.Model {
    style: StyleCard; palette: PaletteCard; dataColors: DataColorsCard;
    chart: { look: fs.ItemDropdown; shadow: fs.Slider };
}
/** colors and helpers handed to draw() */
export interface Theme { ink: string; surface: string; text: string; axis: string; grid: string; hc: boolean; dark: boolean; }
export interface Ctx<S, M> {
    W: number; H: number; s: S; m: M; root: SVGGElement; look: Look; t: Theme; culture: string;
    io: Interact; colorOf: (c: Colored) => string; bind: (e: Element, t: Target) => void; msg: (key: string, fallback: string) => string;
    /** make the drawing larger than the viewport; the visual then scrolls */
    grow: (w: number, h: number) => void;
    /** the labelled Reset zoom button in the top-right corner, shown while zoomed in */
    resetZoom: (show: boolean, act: () => void) => void;
}

let SEQ = 0;
/** room a scrollbar takes (draw() lays out for H - SCROLLBAR when it scrolls sideways) */
export const SCROLLBAR = 17;

export abstract class FamilyVisual<S extends FamilySettings, M extends BaseModel> implements powerbi.extensibility.visual.IVisual {
    protected host: powerbi.extensibility.visual.IVisualHost;
    protected fss: FormattingSettingsService;
    protected lm: powerbi.extensibility.ILocalizationManager;
    protected settings: S;
    protected root: HTMLElement;
    protected svg: SVGSVGElement;
    protected plot: SVGGElement;
    protected look: Look;
    protected io: Interact;
    protected model: M | null = null;
    protected viewport = { width: 300, height: 200 };
    /** the latest update from the host (jsonFilters for slicers, view and edit mode) */
    protected options: powerbi.extensibility.visual.VisualUpdateOptions | null = null;

    protected abstract readonly title: string;
    protected abstract readonly landingLines: [string, string];
    protected abstract readonly limit: number;
    protected abstract newSettings(dv?: powerbi.DataView): S;
    protected abstract read(dv: powerbi.DataView | undefined): M | null;
    protected abstract draw(c: Ctx<S, M>): void;
    protected abstract tidy(m: M | null): void;
    protected describe(m: M): string { void m; return this.title; }

    protected loc(key: string, fallback: string): string { const t = this.lm && this.lm.getDisplayName(key); return t && t !== key ? t : fallback; }

    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions, cls: string, prefix: string) {
        this.host = options.host;
        this.lm = this.host.createLocalizationManager();
        this.fss = new FormattingSettingsService(this.lm);
        this.root = options.element;
        this.root.classList.add("atl", cls);
        this.svg = el("svg", { class: "atl-svg", role: "img" });
        const defs = el("defs", {}, this.svg);
        this.plot = el("g", {}, this.svg);
        this.look = new Look(defs, prefix + (++SEQ) + "-");
        this.root.appendChild(this.svg);
        this.io = new Interact(this.host, this.root, this.svg, () => this.render());
        this.settings = this.newSettings();
    }

    public update(options: powerbi.extensibility.visual.VisualUpdateOptions) {
        this.host.eventService.renderingStarted(options);
        try {
            this.viewport = { width: Math.max(1, options.viewport.width), height: Math.max(1, options.viewport.height) };
            this.options = options;
            const dv = options.dataViews && options.dataViews[0];
            this.settings = this.newSettings(dv);
            this.model = this.read(dv);
            if (!this.model) {
                landing(this.root, this.title, [this.loc("Landing_Line1", this.landingLines[0]), this.loc("Landing_Line2", this.landingLines[1])]);
                this.root.appendChild(this.svg); this.svg.style.display = "none";
            } else {
                this.root.querySelectorAll(".atl-landing").forEach(n => n.remove());
                this.svg.style.display = "";
                this.colorize(this.model);
                if (this.model.rows >= this.limit) this.host.displayWarningIcon(this.loc("Warn_Limit_Title", `Showing the first ${this.limit.toLocaleString("en-US")} rows`), this.loc("Warn_Limit_Text", "There is more data than the visual can show. Filter the report to see the rest."));
                this.io.highlighted = this.model.hl;
                const m = this.model;
                this.io.sync(id => {
                    const c = m.colored.find(x => x.id && x.id.equals(id)); if (c) return { key: "c:" + c.key, items: c.items };
                    const i = m.ids.findIndex(x => x.equals(id)); return i >= 0 ? { key: "i" + i, items: [i] } : null;
                });
                this.render();
            }
            this.host.eventService.renderingFinished(options);
        } catch (err) {
            this.host.eventService.renderingFailed(options, String(err));
        }
    }

    /** palette colors, then per-item overrides from the Format pane (colors already read into c.color win) */
    private colorize(m: M) {
        const pal = colorer(this.settings.palette.options(), this.host, isDark(this.host));
        m.colored.forEach((c, i) => { if (!c.color || !isHex(c.color)) c.color = pal(c.name, i); });
        this.settings.dataColors.slices = m.colored.filter(c => c.selector).slice(0, 60).map(c => new fs.ColorPicker({
            name: "fill", displayName: c.name, value: { value: c.color }, selector: c.selector as powerbi.data.Selector
        }));
    }

    protected render() {
        const m = this.model; if (!m) return;
        const s = this.settings, W = this.viewport.width, H = this.viewport.height, cp = this.host.colorPalette, hc = cp.isHighContrast, dark = isDark(this.host);
        const surface = cp.background && isHex(cp.background.value) ? normHex(cp.background.value) : "#ffffff";
        const fg = cp.foreground && isHex(cp.foreground.value) ? normHex(cp.foreground.value) : "#252423";
        const ink = hc ? fg : colorOr(s.style.textColor, fg);
        const t: Theme = { ink, surface, text: mix(ink, surface, 0.14), axis: mix(ink, surface, 0.4), grid: mix(ink, surface, 0.88), hc, dark };
        const font = String(s.style.fontFamily.value || "");
        setFont(font);
        this.look.reset((hc ? "flat" : val(s.chart.look)) as LookName, dark ? "#000000" : mix(ink, "#000000", 0.5), s.chart.shadow.value);
        clear(this.plot);
        this.svg.setAttribute("width", String(W)); this.svg.setAttribute("height", String(H));
        this.io.keepOthers = s.style.keepOthers.value;
        this.root.style.overflow = "hidden";
        this.root.style.fontFamily = font; this.root.style.color = ink; this.root.style.setProperty("--atl-halo", surface);
        this.draw({
            W, H, s, m, root: this.plot, look: this.look, t, culture: this.host.locale, io: this.io,
            colorOf: c => (hc ? fg : c.color), bind: (e, tg) => this.io.bind(e, tg), msg: (k, f) => this.loc(k, f),
            resetZoom: (show, act) => resetButton(this.root, show, this.loc("Zoom_Reset", "Reset zoom"), act),
            grow: (w, h) => {
                /* scrolling one way: the other side shrinks by the scrollbar, so only one scrollbar shows */
                const wide = w > W + 0.5, tall = h > H + 0.5;
                this.svg.setAttribute("width", String(wide ? Math.ceil(w) : tall ? W - SCROLLBAR : W));
                this.svg.setAttribute("height", String(tall ? Math.ceil(h) : wide ? H - SCROLLBAR : H));
                this.root.style.overflow = "auto";
            }
        });
        this.svg.setAttribute("aria-label", this.describe(m));
        /* the * marker: selected here, filtering from here, or highlighted from another visual */
        const filtered = this.isFiltering();
        selMark(this.root, s.style.mark(this.io.sel.size > 0, filtered, !!m.hl, (k, f) => this.loc(k, f), () => this.io.clearSelection(), () => this.clearFilter()));
    }
    /** true while this visual applies a filter (jsonFilters from the host; a slicer with its own state overrides this) */
    protected isFiltering(): boolean { const f = this.options && this.options.jsonFilters; return !!f && f.length > 0; }
    /** remove the filter this visual applied (the marker's click when it filters) */
    protected clearFilter() { this.host.applyJsonFilter(null as unknown as powerbi.IFilter, "general", "filter", powerbi.FilterAction.remove); }

    public getFormattingModel(): powerbi.visuals.FormattingModel {
        this.settings.palette.tidy(); this.settings.style.tidy();
        this.settings.dataColors.visible = this.settings.dataColors.slices.length > 0;
        const look = val(this.settings.chart.look);
        this.settings.chart.shadow.visible = look !== "flat";
        this.tidy(this.model);
        return this.fss.buildFormattingModel(this.settings);
    }
}
