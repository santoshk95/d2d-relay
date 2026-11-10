/*
 * Atlas Time: calendar heatmap, heat grid and punch card, stream graph
 * and timeline slicer in one Power BI visual. The timeline slicer filters
 * the report with an advanced filter on the Time column (applyJsonFilter)
 * and reads it back from jsonFilters, so bookmarks and reloads keep it.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { TimeSettings } from "./settings";
import { Model, readModel } from "./model";
import { render, Range } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { AdvancedFilter, IAdvancedFilter } from "powerbi-models";

const NAMES: Record<string, string> = { calendar: "Calendar heatmap", heatgrid: "Heat grid", stream: "Stream graph", timeline: "Timeline slicer" };

export class Visual extends FamilyVisual<TimeSettings, Model> {
    protected readonly title = "Atlas Time";
    protected readonly landingLines: [string, string] = [
        "Add a date (or a time field such as Hour) to Time and a measure to Values.",
        "Add Rows for a heat grid or a Legend for a stream graph. Pick calendar, heat grid, stream or timeline slicer in the Format pane."];
    protected readonly limit = 30000;
    private range: Range | null = null;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atlt"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(TimeSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        const m = readModel(dv, this.host);
        /* the current filter (after a reload, a bookmark or another slicer change) */
        this.range = null;
        const filters = (this.options && this.options.jsonFilters) as unknown as IAdvancedFilter[] | undefined;
        const f = filters && filters.find(x => x && x.conditions && m && m.target && x.target && (x.target as { column?: string }).column === m.target.column);
        if (f) {
            const ge = f.conditions.find(x => x.operator === "GreaterThanOrEqual"), lt = f.conditions.find(x => x.operator === "LessThan");
            if (ge && lt) this.range = { from: new Date(ge.value as string).getTime(), to: new Date(lt.value as string).getTime() };
        }
        if (m && this.settings.type === "timeline" && !m.target) this.host.displayWarningIcon(this.loc("Warn_Target_Title", "Use a date column"), this.loc("Warn_Target_Text", "The timeline filters a plain date column. Use the date field itself, not its date hierarchy."));
        return m;
    }
    protected draw(c: Ctx<TimeSettings, Model>) {
        const m = c.m;
        render(c, { range: this.range, ok: !!m.target, apply: r => this.apply(r) });
    }
    private apply(r: Range | null) {
        const m = this.model;
        this.range = r;
        if (m && m.target && this.host.hostCapabilities.allowInteractions) {
            if (!r) this.host.applyJsonFilter(null as unknown as powerbi.IFilter, "general", "filter", powerbi.FilterAction.remove);
            else {
                /* dates from the start of the first period up to (not including) the end of the last */
                const filter = new AdvancedFilter(m.target, "And", { operator: "GreaterThanOrEqual", value: new Date(r.from).toISOString() }, { operator: "LessThan", value: new Date(r.to).toISOString() });
                this.host.applyJsonFilter(filter.toJSON() as unknown as powerbi.IFilter, "general", "filter", powerbi.FilterAction.merge);
            }
        }
        this.render();
    }
    protected isFiltering() { return !!this.range; }
    protected clearFilter() { this.apply(null); }
    protected tidy(m: Model | null) { this.settings.tidy({ series: m ? m.series.length : 1 }); }
    protected describe(m: Model) { return `${NAMES[this.settings.type] || "Time chart"} of ${m.valueName} by ${m.timeName}`; }
}
