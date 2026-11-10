/*
 * SPC Control Chart: an individuals control chart with centre line, upper and
 * lower control limits and highlighted out-of-control points.
 * Host wiring comes from common/family.ts.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { SpcSettings } from "./settings";
import { Model, readModel } from "./model";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

export class Visual extends FamilyVisual<SpcSettings, Model> {
    protected readonly title = "SPC Control Chart";
    protected readonly landingLines: [string, string] = [
        "Add the batches (in time order) to Subgroup and the measured value to Value.",
        "Bind Centre line, Upper and Lower control limit measures, or leave them empty to use mean ± 3 sigma of the plotted values."];
    protected readonly limit = 5000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "gspcchart");
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(SpcSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) { return readModel(dv, this.host); }
    protected draw(c: Ctx<SpcSettings, Model>) { render(c); }
    protected tidy(m: Model | null) { void m; }
    protected describe(m: Model) { return `Control chart of ${m.series[0].name} by ${m.levelNames.join(", ")}`; }
}
