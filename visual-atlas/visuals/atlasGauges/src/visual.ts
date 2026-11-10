/*
 * Atlas Gauges: card, multi-row card, KPI, gauge, dial, radial bars,
 * liquid fill, bullet chart and ticker in one Power BI visual. Host
 * wiring comes from common/family.ts.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GaugesSettings } from "./settings";
import { Model, readModel } from "./model";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

const NAMES: Record<string, string> = { card: "Card", multirow: "Multi-row card", kpi: "KPI", gauge: "Gauge", dial: "Dial", radialBar: "Radial bar chart", liquid: "Liquid fill gauge", bullet: "Bullet chart", ticker: "Ticker" };

export class Visual extends FamilyVisual<GaugesSettings, Model> {
    protected readonly title = "Atlas Gauges";
    protected readonly landingLines: [string, string] = [
        "Add a measure to Value, and a Target, Minimum and Maximum if you have them.",
        "Add a Category for one tile per item, or a Trend axis for a KPI sparkline. Pick card, KPI, gauge, dial, radial bars, liquid fill, bullet or ticker in the Format pane."];
    protected readonly limit = 10000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlg"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(GaugesSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) { return readModel(dv, this.host); }
    protected draw(c: Ctx<GaugesSettings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy({ items: m ? m.list.length : 1, target: !!m && m.hasTarget, trend: !!m && m.hasTrend, bands: !!m && m.hasBands }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "KPI"}: ${m.list.slice(0, 6).map(it => it.name).join(", ")}`; }
}
