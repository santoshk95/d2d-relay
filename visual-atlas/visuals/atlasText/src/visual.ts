/*
 * Atlas Text: word cloud and ranked words in one Power BI visual. Host
 * wiring comes from common/family.ts.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { TextSettings } from "./settings";
import { Model, readModel } from "./model";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

export class Visual extends FamilyVisual<TextSettings, Model> {
    protected readonly title = "Atlas Text";
    protected readonly landingLines: [string, string] = [
        "Add words, phrases or free text (comments, reviews) to Text. Add a Weight such as Mentions, or leave it empty to count words.",
        "Add a Topic or a Color value (for example Sentiment) to color the words. Pick word cloud or ranked words in the Format pane."];
    protected readonly limit = 5000;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlw"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(TextSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) { return readModel(dv, this.host, this.settings); }
    protected draw(c: Ctx<TextSettings, Model>) { render(c); }
    protected tidy(m: Model | null) { this.settings.tidy({ group: !!m && m.groups.length > 0, color: !!m && m.hasColor }); }
    protected describe(m: Model) { return `${this.settings.type === "bars" ? "Ranked words" : "Word cloud"} of ${m.textTitle}: ${m.words.slice(0, 8).map(w => w.text).join(", ")}`; }
}
