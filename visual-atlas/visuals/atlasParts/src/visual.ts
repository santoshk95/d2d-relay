/*
 * Atlas Parts: pie and donut in one Power BI visual, with drill-down
 * (host.drill). Host wiring comes from common/family.ts, the data from the
 * shared category × series matrix.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { PartsSettings } from "./settings";
import { Model, readModel } from "./common/matrix";
import { render } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { DrillBar } from "./common/drill";

export class Visual extends FamilyVisual<PartsSettings, Model> {
    protected readonly title = "Atlas Parts";
    protected readonly landingLines: [string, string] = [
        "Add a field to Legend (the slices) and a measure to Values. Add a hierarchy such as Category and Subcategory to drill down.",
        "Add Details to split each slice into an outer ring. Pick pie or donut, labels and the center total in the Format pane."];
    protected readonly limit = 1000;
    private drillBar: DrillBar;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "atlq");
        this.drillBar = new DrillBar(this.host, this.root, (k, f) => this.loc(k, f));
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(PartsSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        this.drillBar.allow(this.settings.drill.allow.value);
        const m = readModel(dv, this.host, true);
        /* slices always carry the colors; a details ring is drawn in shades of its slice */
        if (m) { m.colored = m.cats; this.drillBar.afterUpdate(m.drill); }
        return m;
    }
    protected draw(c: Ctx<PartsSettings, Model>) {
        const show = this.settings.drill.buttons.value && c.m.drill.length > 0 && this.host.hostCapabilities.allowInteractions;
        render(c, show ? 30 : 0);
        this.drillBar.draw(show, c.m.drill, c.m.drillDisabled, { any: this.io.sel.size > 0, clear: () => this.io.clearSelection() });
    }
    protected tidy(m: Model | null) { this.settings.tidy({ drillable: !!m && m.drill.length > 0 }); }
    protected describe(m: Model) { return `${this.settings.type === "pie" ? "Pie" : "Donut"} chart of ${m.series.map(s => s.name).join(", ")} by ${m.catTitle}`; }
}
