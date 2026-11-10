/*
 * Atlas Proportion: Mekko, waffle, pictogram, aster plot, rose (polar
 * area) and Venn diagram in one Power BI visual. Host wiring comes from
 * common/family.ts, the data from the shared category × series matrix.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { ProportionSettings } from "./settings";
import { Model, readModel } from "./common/matrix";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

const NAMES: Record<string, string> = { mekko: "Mekko chart", waffle: "Waffle chart", pictogram: "Pictogram", aster: "Aster plot", rose: "Rose chart", venn: "Venn diagram" };

export class Visual extends FamilyVisual<ProportionSettings, Model> {
    protected readonly title = "Atlas Proportion";
    protected readonly landingLines: [string, string] = [
        "Add a field to Category and a measure to Values. Add a Legend for Mekko segments or a stacked rose.",
        "A second measure is the total (waffle, pictogram) or the weight (aster). For a Venn diagram, write overlaps in Category as \"A & B\"."];
    protected readonly limit = 1000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlp"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(ProportionSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) { return readModel(dv, this.host, true, ["waffle", "pictogram", "aster"].includes(this.settings.type)); }
    protected draw(c: Ctx<ProportionSettings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy({ series: m ? m.series.length : 1, cats: m ? m.cats.length : 0 }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "Proportion chart"} of ${m.series.map(s => s.name).join(", ")} by ${m.catTitle}`; }
}
