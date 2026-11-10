/*
 * Drill-down buttons on the visual, using the Drilldown API (host.drill),
 * shared by the visuals that declare "drilldown" in capabilities.json:
 * drill up, go to the next level, expand all one level, back to the top
 * (drills up level by level until no level is left above), and clear the
 * selection (shown only while something is selected).
 */
import powerbi from "powerbi-visuals-api";
import { el } from "./look";
import { corner } from "./corner";

/* drill types (powerbi.DrillType): Up = 1, Down (expand all one level) = 2, MoveToNextlevel = 3 */
const DRILL = [
    { type: 1, key: "Drill_Up", text: "Drill up", icon: "M8 13V3.5M3.8 7.6 8 3.4l4.2 4.2" },
    { type: 3, key: "Drill_Next", text: "Go to the next level", icon: "M3.8 3.2 8 7.4l4.2-4.2M3.8 8.6 8 12.8l4.2-4.2" },
    { type: 2, key: "Drill_Expand", text: "Expand all down one level", icon: "M8 2.6v5.2M8 7.8 3.6 13M8 7.8 12.4 13M8 7.8V13" }
];
const RESET = { key: "Drill_Reset", text: "Back to the top level", icon: "M3 3h10M8 13V6.2M4.2 9.6 8 5.8l3.8 3.8" };
const CLEAR = { key: "Clear_Selection", text: "Clear selection", icon: "M4 4l8 8M12 4l-8 8" };

export class DrillBar {
    private bar: HTMLDivElement;
    private canDrill: boolean | null = null;
    /** levels still to go up after "back to the top" (one host.drill per update) */
    private resetSteps = 0;
    constructor(private host: powerbi.extensibility.visual.IVisualHost, private root: HTMLElement, private loc: (key: string, fallback: string) => string, private role = "category") {
        this.bar = document.createElement("div"); this.bar.className = "atl-drill";
    }
    /** "Allow drilling" in the Format pane turns the host's drill mode on or off */
    allow(on: boolean) {
        if (this.canDrill !== on && (this.canDrill !== null || !on) && typeof this.host.setCanDrill === "function") this.host.setCanDrill(on);
        this.canDrill = on;
    }
    /** call on every data update: continues "back to the top" while there is a level above */
    afterUpdate(types: powerbi.DrillType[]) {
        if (this.resetSteps <= 0) return;
        if (types.indexOf(1 as powerbi.DrillType) >= 0) { this.resetSteps--; this.host.drill({ roleName: this.role, drillType: 1 } as powerbi.DrillArgs); }
        else this.resetSteps = 0;
    }
    /** show the buttons when the role can drill; each is enabled only when that drill is available */
    draw(show: boolean, types: powerbi.DrillType[], disabled: boolean, selection: { any: boolean; clear: () => void } | null = null) {
        const bar = this.bar;
        const row = corner(this.root); if (bar.parentElement !== row) row.appendChild(bar);
        while (bar.firstChild) bar.removeChild(bar.firstChild);
        const showClear = !!selection && selection.any;
        bar.style.display = show || showClear ? "" : "none";
        const button = (b: { key: string; text: string; icon: string }, ok: boolean, act: () => void) => {
            const btn = document.createElement("button"), label = this.loc(b.key, b.text);
            btn.type = "button"; btn.className = "atl-drill-b"; btn.title = label; btn.setAttribute("aria-label", label); btn.disabled = !ok;
            const svg = el("svg", { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true" }, btn);
            el("path", { d: b.icon, fill: "none", stroke: "currentColor", "stroke-width": 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
            btn.addEventListener("click", ev => { ev.stopPropagation(); if (ok) act(); });
            bar.appendChild(btn);
        };
        if (show) {
            const up = !disabled && types.indexOf(1 as powerbi.DrillType) >= 0;
            DRILL.forEach(d => button(d, !disabled && types.indexOf(d.type as powerbi.DrillType) >= 0, () => this.host.drill({ roleName: this.role, drillType: d.type } as powerbi.DrillArgs)));
            /* back to the top: one level now, the rest on the following updates (at most 8 levels) */
            button(RESET, up, () => { this.resetSteps = 7; this.host.drill({ roleName: this.role, drillType: 1 } as powerbi.DrillArgs); });
        }
        if (showClear && selection) button(CLEAR, true, () => selection.clear());
    }
}
