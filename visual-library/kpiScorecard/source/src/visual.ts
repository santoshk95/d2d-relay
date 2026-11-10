/*
 * KPI Scorecard: a Gen BI custom visual on the Visual Atlas framework. FamilyVisual (common/family.ts)
 * does the host wiring; this class reads the data and hands it to render().
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { Settings } from "./settings";
import { Model, readModel } from "./model";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

export class Visual extends FamilyVisual<Settings, Model> {
    protected readonly title = "KPI Scorecard";
    protected readonly landingLines: [string, string] = [
        "Add a KPI field and a Result, Target or Status measure.",
        "Add a Trend axis (month) and Trend values for the sparkline."];
    protected readonly limit = 10000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "gkpiscorecard");
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(Settings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        const s = this.newSettings(dv);
        return readModel(dv, this.host, Number(s.labels.displayUnits.value) || 0, s.labels.decimals.value);
    }
    protected draw(c: Ctx<Settings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy(m); }
    protected describe(m: Model) { return `KPI Scorecard: ${m.list.map(r => `${r.name} ${r.result} ${r.statusText}`.trim()).join("; ")}`; }
}
