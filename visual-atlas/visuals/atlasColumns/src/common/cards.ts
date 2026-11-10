/*
 * Format pane cards shared by the Atlas family visuals: Style (font and
 * text color for the whole visual), Palette, per-item Colors, Data
 * labels, axes, Gridlines and Legend. A visual adds its own chart cards
 * next to these. Names match the objects in capabilities.json, so a
 * report theme can set them for every Atlas visual at once.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { isHex, normHex } from "./color";
import { MarkState } from "./corner";

export const opt = (value: string, displayName: string) => ({ value, displayName });
type Range = { minValue: { type: powerbi.visuals.ValidatorType.Min; value: number }; maxValue: { type: powerbi.visuals.ValidatorType.Max; value: number } };
export const range = (min: number, max: number): Range => ({ minValue: { type: powerbi.visuals.ValidatorType.Min, value: min }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: max } });
export const LOOKS = [opt("flat", "Flat"), opt("soft", "Soft"), opt("3d", "3D")];
export const SOURCES = [opt("theme", "Report theme"), opt("brand", "Brand color"), opt("custom", "Custom list")];
export const MODES = [opt("spectrum", "Spectrum"), opt("analogous", "Analogous"), opt("mono", "Mono")];
export const LEGEND_POS = [opt("top", "Top"), opt("topCenter", "Top center"), opt("bottom", "Bottom"), opt("bottomCenter", "Bottom center"), opt("right", "Right")];
export const LINE = [opt("solid", "Solid"), opt("dashed", "Dashed"), opt("dotted", "Dotted")];
export const DASH: Record<string, string | null> = { solid: null, dashed: "5 4", dotted: "1.5 3" };

/** the value of a color picker, or a fallback when it is empty */
export const colorOr = (c: fs.ColorPicker, fallback: string) => { const v = c.value && c.value.value; return v && isHex(v) ? normHex(v) : fallback; };
/** the value of a dropdown as a string */
export const val = (d: fs.ItemDropdown) => String(d.value.value);

export class StyleCard extends fs.SimpleCard {
    fontFamily = new fs.FontPicker({ name: "fontFamily", displayName: "Font", value: "'Segoe UI', wf_segoe-ui_normal, helvetica, arial, sans-serif" });
    textColor = new fs.ColorPicker({ name: "textColor", displayName: "Text color", value: { value: "" } });
    marker = new fs.ToggleSwitch({ name: "marker", displayName: "Selection marker (*)", value: true });
    markerColor = new fs.ColorPicker({ name: "markerColor", displayName: "Marker color", value: { value: "#e8590c" } });
    markerHighlight = new fs.ToggleSwitch({ name: "markerHighlight", displayName: "Also when another visual highlights it", value: false });
    keepOthers = new fs.ToggleSwitch({ name: "keepOthers", displayName: "Keep other visuals' selections", value: true });
    name = "style"; displayName = "Style";
    slices = [this.fontFamily, this.textColor, this.keepOthers, this.marker, this.markerColor, this.markerHighlight];
    tidy() { this.markerColor.visible = this.markerHighlight.visible = this.marker.value; }
    /** the marker for this visual's state: something selected here, a filter applied here, or (if asked) highlighted from elsewhere */
    mark(selected: boolean, filtered: boolean, highlighted: boolean, msg: (k: string, f: string) => string, clearSel: () => void, clearFilter: () => void): MarkState | null {
        if (!this.marker.value) return null;
        const color = colorOr(this.markerColor, "#e8590c");
        if (filtered) return { kind: "filter", color, title: msg("Mark_Filter", "This visual is filtering the report"), clear: clearFilter };
        if (selected) return { kind: "sel", color, title: msg("Mark_Selected", "Selected: this visual is filtering other visuals"), clear: clearSel };
        if (highlighted && this.markerHighlight.value) return { kind: "hl", color, title: msg("Mark_Highlighted", "Highlighted by a selection in another visual") };
        return null;
    }
}
export class PaletteCard extends fs.SimpleCard {
    source = new fs.ItemDropdown({ name: "source", displayName: "Colors from", items: SOURCES, value: SOURCES[0] });
    brand = new fs.ColorPicker({ name: "brand", displayName: "Brand color", value: { value: "#2a78d6" } });
    mode = new fs.ItemDropdown({ name: "mode", displayName: "Palette style", items: MODES, value: MODES[0] });
    custom = new fs.TextArea({ name: "custom", displayName: "Custom colors", placeholder: "Hex codes, or paste a theme JSON", value: "" });
    name = "palette"; displayName = "Palette";
    slices: fs.Slice[] = [this.source, this.brand, this.mode, this.custom];
    tidy() { const s = val(this.source); this.brand.visible = s === "brand"; this.mode.visible = s === "brand"; this.custom.visible = s === "custom"; }
    options() { return { source: val(this.source), brand: this.brand.value.value, mode: val(this.mode), custom: this.custom.value }; }
}
export class DataColorsCard extends fs.SimpleCard {
    name = "dataColors"; displayName = "Colors";
    slices: fs.Slice[] = [];
}
export class LabelsCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Data labels", value: false });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 9, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    displayUnits = new fs.AutoDropdown({ name: "displayUnits", displayName: "Display units", value: 0 });
    decimals = new fs.NumUpDown({ name: "decimals", displayName: "Decimal places", value: -1, options: range(-1, 9) });
    name = "labels"; displayName = "Data labels";
    slices: fs.Slice[] = [this.fontSize, this.color, this.displayUnits, this.decimals];
    constructor(on = false) { super(); this.show.value = on; }
}
export class CategoryAxisCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Axis", value: true });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    title = new fs.ToggleSwitch({ name: "title", displayName: "Title", value: false });
    name = "categoryAxis"; displayName = "Category axis";
    slices: fs.Slice[] = [this.fontSize, this.color, this.title];
}
export class ValueAxisCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Value axis", value: true });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    displayUnits = new fs.AutoDropdown({ name: "displayUnits", displayName: "Display units", value: 0 });
    decimals = new fs.NumUpDown({ name: "decimals", displayName: "Decimal places", value: -1, options: range(-1, 9) });
    start = new fs.TextInput({ name: "start", displayName: "Start", placeholder: "Auto", value: "" });
    end = new fs.TextInput({ name: "end", displayName: "End", placeholder: "Auto", value: "" });
    title = new fs.ToggleSwitch({ name: "title", displayName: "Title", value: false });
    name = "valueAxis"; displayName = "Value axis";
    slices: fs.Slice[] = [this.fontSize, this.color, this.displayUnits, this.decimals, this.start, this.end, this.title];
}
export class GridCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Gridlines", value: true });
    topLevelSlice = this.show;
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    style = new fs.ItemDropdown({ name: "style", displayName: "Line style", items: LINE, value: LINE[0] });
    width = new fs.NumUpDown({ name: "width", displayName: "Width", value: 1, options: range(0, 6) });
    name = "gridlines"; displayName = "Gridlines";
    slices: fs.Slice[] = [this.color, this.style, this.width];
}
export class LegendCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Legend", value: true });
    topLevelSlice = this.show;
    position = new fs.ItemDropdown({ name: "position", displayName: "Position", items: LEGEND_POS, value: LEGEND_POS[0] });
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    title = new fs.ToggleSwitch({ name: "title", displayName: "Title", value: true });
    name = "legend"; displayName = "Legend";
    slices: fs.Slice[] = [this.position, this.fontSize, this.color, this.title];
}
