/*
 * Atlas Scatter: scatter, bubble and dot plot (with a play axis, drag to
 * zoom and guides) and Gantt in one Power BI visual. Host wiring comes from
 * common/family.ts; the zoom window and the play timer are kept here.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { ScatterSettings } from "./settings";
import { Model, readModel } from "./model";
import { render, View } from "./render";
import { FamilyVisual, Ctx } from "./common/family";

const NAMES: Record<string, string> = { scatter: "Scatter chart", dotplot: "Dot plot", gantt: "Gantt chart" };

export class Visual extends FamilyVisual<ScatterSettings, Model> {
    protected readonly title = "Atlas Scatter";
    protected readonly landingLines: [string, string] = [
        "Scatter: add a field to Values (details), and measures to X-axis and Y-axis (and Size for bubbles). Add a Play axis to animate.",
        "Gantt: add Task, Start date and End date (blank for a milestone), and optionally Legend (phase), Owner and % complete."];
    protected readonly limit = 10000;
    private view: View = { zoom: null, frame: 0, timer: null };
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) { super(options, "atl-fam", "atls"); }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(ScatterSettings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        /* new data: stop playing and zoom out */
        if (this.view.timer) window.clearInterval(this.view.timer);
        this.view = { zoom: null, frame: this.view.frame, timer: null };
        const m = readModel(dv, this.host);
        if (m && this.view.frame >= m.frames.length) this.view.frame = 0;
        return m;
    }
    protected draw(c: Ctx<ScatterSettings, Model>) { render(c, this.view, () => this.render()); }
    protected tidy(m: Model | null) { this.settings.tidy({ size: !!m && m.hasSize, play: !!m && m.frames.length > 1, legend: !!m && m.names.legend !== "", owner: !!m && m.hasOwner, progress: !!m && m.hasProgress }); }
    protected describe(m: Model) { return m.tasks.length ? `Gantt chart of ${m.tasks.length} tasks` : `${NAMES[this.settings.type] || "Scatter chart"} of ${m.names.y} by ${m.names.x || m.names.xcat}`; }
    public destroy() { if (this.view.timer) window.clearInterval(this.view.timer); }
}
