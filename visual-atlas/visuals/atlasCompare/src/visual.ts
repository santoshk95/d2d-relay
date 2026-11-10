/*
 * Atlas Compare: lollipop, dot plot, dumbbell, slope, bump, tornado and
 * radar in one Power BI visual. Host wiring comes from common/family.ts.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { CompareSettings } from "./settings";
import { Model, readModel } from "./model";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { val } from "./common/cards";

const NAMES: Record<string, string> = { lollipop: "Lollipop chart", dot: "Dot plot", dumbbell: "Dumbbell chart", slope: "Slope chart", bump: "Bump chart", tornado: "Tornado chart", radar: "Radar chart" };

export class Visual extends FamilyVisual<CompareSettings, Model> {
    protected readonly title = "Atlas Compare";
    protected readonly landingLines: [string, string] = [
        "Add a field to Category and one or more measures to Values (two for a dumbbell, slope or tornado).",
        "Add a Legend to compare series. Pick lollipop, dot plot, dumbbell, slope, bump, tornado or radar in the Format pane."];
    protected readonly limit = 3000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlk"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(CompareSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        return readModel(dv, this.host, this.settings.type === "lollipop" && val(this.settings.marks.colorBy) === "category");
    }
    protected draw(c: Ctx<CompareSettings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy({ series: m ? m.series.length : 1 }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "Comparison chart"} of ${m.series.map(s => s.name).join(", ")} by ${m.catTitle}`; }
}
