/*
 * Small Multiple Lines: a Gen BI custom visual on the Visual Atlas framework. FamilyVisual (common/family.ts)
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
    protected readonly title = "Small Multiple Lines";
    protected readonly landingLines: [string, string] = [
        "Add a date or month to Axis and a measure to Values.",
        "Add a Small multiples field for one panel per item, and a Comparison (plan) measure."];
    protected readonly limit = 10000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "gsmlines");
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(Settings, dv); }
    protected read(dv: powerbi.DataView | undefined) { return readModel(dv, this.host); }
    protected draw(c: Ctx<Settings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy(m); }
    protected describe(m: Model) { return `Small multiple lines of ${m.actual.name}${m.hasComp ? " vs " + m.plan.name : ""} for ${m.panels.map(p => p.name).join(", ")}`; }
}
