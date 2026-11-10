/*
 * __TITLE__: a Gen BI custom visual on the Visual Atlas framework. FamilyVisual (common/family.ts)
 * does the host wiring: landing page, palette and per-item colors, look, selection, highlights,
 * high contrast, rendering events. This class reads the data and hands it to render().
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { Settings } from "./settings";
import { Model, readModel } from "./common/matrix";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

export class Visual extends FamilyVisual<Settings, Model> {
    protected readonly title = "__TITLE__";
    protected readonly landingLines: [string, string] = [
        "Add a field to Category and a measure to Values.",
        "Add a Legend field, or more measures, to split each group into series."];
    protected readonly limit = 1000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "__PREFIX__");
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(Settings, dv); }
    /* the category x series matrix (common/matrix.ts); true: one series gives each category its own color */
    protected read(dv: powerbi.DataView | undefined) { return readModel(dv, this.host, true); }
    protected draw(c: Ctx<Settings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy(m); }
    protected describe(m: Model) { return `__TITLE__ of ${m.series.map(s => s.name).join(", ")} by ${m.catTitle}`; }
}
