/*
 * Atlas Hierarchy: treemap, sunburst, circle packing and org chart / tree
 * in one Power BI visual. Host wiring comes from common/family.ts; the
 * zoom path and open tree branches are kept here between renders.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { HierarchySettings } from "./settings";
import { Model, readModel } from "./model";
import { render, View } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { val } from "./common/cards";

const NAMES: Record<string, string> = { treemap: "Treemap", sunburst: "Sunburst", pack: "Circle packing", tree: "Org chart" };

export class Visual extends FamilyVisual<HierarchySettings, Model> {
    protected readonly title = "Atlas Hierarchy";
    protected readonly landingLines: [string, string] = [
        "Add one or more fields to Levels (for example Category, Subcategory, Product) and a measure to Size.",
        "For an org chart, use ID and Parent ID instead of Levels. Pick treemap, sunburst, circle packing or org chart in the Format pane."];
    protected readonly limit = 10000;
    private view: View = { zoom: [], open: null };
    private shape = "";
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlh"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(HierarchySettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        const m = readModel(dv, this.host, val(this.settings.hcolor.colorBy));
        /* new fields or a new "levels open" setting start the tree again */
        const shape = m ? `${m.org}|${m.levelNames.join(",")}|${this.settings.tree.expanded.value}` : "";
        if (shape !== this.shape) { this.view = { zoom: [], open: null }; this.shape = shape; }
        return m;
    }
    protected draw(c: Ctx<HierarchySettings, Model>) { render(c, this.view, () => this.render()); }
    protected tidy(m: Model | null) { this.settings.tidy({ levels: m ? m.levels : 1, colorValue: !!m && m.hasColor, org: !!m && m.org }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "Hierarchy"} of ${m.valueName} by ${m.levelNames.join(", ")}`; }
}
