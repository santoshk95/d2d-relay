/*
 * Atlas Finance: candlestick, waterfall, ribbon and funnel in one Power BI
 * visual. Host wiring comes from common/family.ts.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { FinanceSettings } from "./settings";
import { Model, readModel } from "./model";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { val } from "./common/cards";

const NAMES: Record<string, string> = { candlestick: "Candlestick chart", waterfall: "Waterfall chart", ribbon: "Ribbon chart", funnel: "Funnel" };

export class Visual extends FamilyVisual<FinanceSettings, Model> {
    protected readonly title = "Atlas Finance";
    protected readonly landingLines: [string, string] = [
        "Add a field to Category and a measure to Values for a waterfall, ribbon or funnel.",
        "For a candlestick, add Open, High, Low and Close (and Volume). Pick the chart type in the Format pane."];
    protected readonly limit = 5000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlx"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(FinanceSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        return readModel(dv, this.host, this.settings.type === "funnel" && val(this.settings.funnel.colors) === "vary", this.settings.type);
    }
    protected draw(c: Ctx<FinanceSettings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy({ series: m && m.mx ? m.mx.series.length : 1, volume: !!m && m.hasVolume }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "Finance chart"} by ${m.catTitle}`; }
}
