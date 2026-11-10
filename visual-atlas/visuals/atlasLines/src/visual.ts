/*
 * Atlas Lines: line, area, stacked and 100% stacked area, and line-and-
 * column combos in one Power BI visual, with drill-down (host.drill) and
 * a zoom slider. Host wiring comes from common/family.ts.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { LinesSettings } from "./settings";
import { Model, readModel } from "./model";
import { render, View } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { DrillBar } from "./common/drill";

const NAMES: Record<string, string> = { line: "Line chart", area: "Area chart", stackedArea: "Stacked area chart", percentArea: "100% stacked area chart", comboStacked: "Line and stacked column chart", comboClustered: "Line and clustered column chart" };
export class Visual extends FamilyVisual<LinesSettings, Model> {
    protected readonly title = "Atlas Lines";
    protected readonly landingLines: [string, string] = [
        "Add a field to X-axis (a date hierarchy drills down) and one or more measures to Y-axis.",
        "For a combo chart, put the column measures in Y-axis and the line measures in Line y-axis. Pick the chart type in the Format pane."];
    protected readonly limit = 5000;
    private view: View = { a: 0, b: 0, n: -1 };
    private drillBar: DrillBar;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "atll");
        this.drillBar = new DrillBar(this.host, this.root, (k, f) => this.loc(k, f));
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(LinesSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        this.drillBar.allow(this.settings.drill.allow.value);
        const m = readModel(dv, this.host);
        if (m) this.drillBar.afterUpdate(m.drill);
        return m;
    }
    protected draw(c: Ctx<LinesSettings, Model>) {
        const show = this.settings.drill.buttons.value && c.m.drill.length > 0 && this.host.hostCapabilities.allowInteractions;
        render(c, this.view, () => this.render(), show ? 30 : 0);
        this.drillBar.draw(show, c.m.drill, c.m.drillDisabled, { any: this.io.sel.size > 0, clear: () => this.io.clearSelection() });
    }
    protected tidy(m: Model | null) { this.settings.tidy({ series: m ? m.series.length : 1, lines: m ? m.series.filter(s => s.line).length : 0, drillable: !!m && m.drill.length > 0 }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "Line chart"} of ${m.series.map(s => s.name).join(", ")} by ${m.levelNames.join(", ")}`; }
}
