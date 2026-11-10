/*
 * Format pane for Atlas Columns. Every variation the gallery shows for
 * columns and bars is a setting here; settings that do not apply to the
 * current chart type are hidden.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { StyleCard } from "./common/cards";

const opt = (value: string, displayName: string) => ({ value, displayName });
type Range = { minValue: { type: powerbi.visuals.ValidatorType.Min; value: number }; maxValue: { type: powerbi.visuals.ValidatorType.Max; value: number } };
const range = (min: number, max: number): Range => ({ minValue: { type: powerbi.visuals.ValidatorType.Min, value: min }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: max } });

export const TYPES = [opt("clusteredColumn", "Clustered column"), opt("stackedColumn", "Stacked column"), opt("percentColumn", "100% stacked column"), opt("clusteredBar", "Clustered bar"), opt("stackedBar", "Stacked bar"), opt("percentBar", "100% stacked bar")];
const LOOKS = [opt("flat", "Flat"), opt("soft", "Soft"), opt("3d", "3D")];
const SHAPES = [opt("rounded", "Rounded ends"), opt("square", "Square"), opt("pill", "Pill"), opt("lollipop", "Lollipop")];
const SOURCES = [opt("theme", "Report theme"), opt("brand", "Brand color"), opt("custom", "Custom list")];
const MODES = [opt("spectrum", "Spectrum"), opt("analogous", "Analogous"), opt("mono", "Mono")];
const POS_ALL = [opt("auto", "Auto"), opt("insideEnd", "Inside end"), opt("insideCenter", "Inside center"), opt("insideBase", "Inside base"), opt("outsideEnd", "Outside end")];
const CONTENT = [opt("value", "Value"), opt("percent", "Percent of total"), opt("both", "Value and percent")];
const LEGEND = [opt("top", "Top"), opt("topCenter", "Top center"), opt("bottom", "Bottom"), opt("bottomCenter", "Bottom center"), opt("right", "Right")];
const LINE = [opt("solid", "Solid"), opt("dashed", "Dashed"), opt("dotted", "Dotted")];
const REF = [opt("average", "Average"), opt("median", "Median"), opt("min", "Minimum"), opt("max", "Maximum"), opt("constant", "Constant value")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 55, options: range(0, 100) });
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Bar shape", items: SHAPES, value: SHAPES[0] });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 4, options: range(0, 40) });
    spacing = new fs.Slider({ name: "spacing", displayName: "Space between categories (%)", value: 28, options: range(0, 80) });
    groupGap = new fs.NumUpDown({ name: "groupGap", displayName: "Space between bars (px)", value: 2, options: range(0, 30) });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.shape, this.radius, this.spacing, this.groupGap];
}
class PaletteCard extends fs.SimpleCard {
    source = new fs.ItemDropdown({ name: "source", displayName: "Colors from", items: SOURCES, value: SOURCES[0] });
    brand = new fs.ColorPicker({ name: "brand", displayName: "Brand color", value: { value: "#2a78d6" } });
    mode = new fs.ItemDropdown({ name: "mode", displayName: "Palette style", items: MODES, value: MODES[0] });
    custom = new fs.TextArea({ name: "custom", displayName: "Custom colors", placeholder: "Hex codes, or paste a theme JSON", value: "" });
    varyByCategory = new fs.ToggleSwitch({ name: "varyByCategory", displayName: "Color each category", value: false });
    name = "palette"; displayName = "Palette";
    slices = [this.source, this.brand, this.mode, this.custom, this.varyByCategory];
}
export class DataColorsCard extends fs.SimpleCard {
    name = "dataColors"; displayName = "Colors";
    slices: fs.Slice[] = [];
}
class LabelsCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Data labels", value: false });
    topLevelSlice = this.show;
    position = new fs.ItemDropdown({ name: "position", displayName: "Position", items: POS_ALL, value: POS_ALL[0] });
    content = new fs.ItemDropdown({ name: "content", displayName: "Show", items: CONTENT, value: CONTENT[0] });
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    displayUnits = new fs.AutoDropdown({ name: "displayUnits", displayName: "Display units", value: 0 });
    decimals = new fs.NumUpDown({ name: "decimals", displayName: "Decimal places", value: -1, options: range(-1, 9) });
    name = "labels"; displayName = "Data labels";
    slices = [this.position, this.content, this.fontSize, this.color, this.displayUnits, this.decimals];
}
class TotalsCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Total labels", value: true });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    name = "totals"; displayName = "Total labels";
    slices = [this.fontSize, this.color];
}
class CategoryAxisCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Category axis", value: true });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    concatenate = new fs.ToggleSwitch({ name: "concatenate", displayName: "Concatenate labels", value: false });
    maxSize = new fs.Slider({ name: "maxSize", displayName: "Maximum label area (%)", value: 30, options: range(10, 60) });
    title = new fs.ToggleSwitch({ name: "title", displayName: "Title", value: false });
    name = "categoryAxis"; displayName = "Category axis";
    slices = [this.fontSize, this.color, this.concatenate, this.maxSize, this.title];
}
class ValueAxisCard extends fs.SimpleCard {
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
    slices = [this.fontSize, this.color, this.displayUnits, this.decimals, this.start, this.end, this.title];
}
class GridCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Gridlines", value: true });
    topLevelSlice = this.show;
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    style = new fs.ItemDropdown({ name: "style", displayName: "Line style", items: LINE, value: LINE[0] });
    width = new fs.NumUpDown({ name: "width", displayName: "Width", value: 1, options: range(0, 6) });
    name = "gridlines"; displayName = "Gridlines";
    slices = [this.color, this.style, this.width];
}
class LegendCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Legend", value: true });
    topLevelSlice = this.show;
    position = new fs.ItemDropdown({ name: "position", displayName: "Position", items: LEGEND, value: LEGEND[0] });
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    title = new fs.ToggleSwitch({ name: "title", displayName: "Title", value: true });
    name = "legend"; displayName = "Legend";
    slices = [this.position, this.fontSize, this.color, this.title];
}
class RefLineCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Reference line", value: false });
    topLevelSlice = this.show;
    kind = new fs.ItemDropdown({ name: "kind", displayName: "Type", items: REF, value: REF[0] });
    value = new fs.NumUpDown({ name: "value", displayName: "Value", value: 0 });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    style = new fs.ItemDropdown({ name: "style", displayName: "Line style", items: LINE, value: LINE[1] });
    label = new fs.ToggleSwitch({ name: "label", displayName: "Label", value: true });
    name = "refLine"; displayName = "Reference line";
    analyticsPane = true;
    slices = [this.kind, this.value, this.color, this.style, this.label];
}
class DrillCard extends fs.SimpleCard {
    buttons = new fs.ToggleSwitch({ name: "buttons", displayName: "Drill buttons on the visual", value: true });
    allow = new fs.ToggleSwitch({ name: "allow", displayName: "Allow drilling", value: true });
    name = "drill"; displayName = "Drill-down";
    slices = [this.buttons, this.allow];
}

export class ColumnsSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    labels = new LabelsCard();
    totals = new TotalsCard();
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    refLine = new RefLineCard();
    drill = new DrillCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.labels, this.totals, this.categoryAxis, this.valueAxis, this.gridlines, this.legend, this.refLine, this.drill];

    /** hide settings that do not apply to the current data and chart type */
    tidy(info: { series: number; levels: number; drillable: boolean }) {
        const t = String(this.chart.chartType.value.value), clustered = t.startsWith("clustered"), stacked = t.startsWith("stacked"), percent = t.startsWith("percent");
        const src = String(this.palette.source.value.value), shape = String(this.chart.shape.value.value), look = String(this.chart.look.value.value);
        this.chart.shadow.visible = look !== "flat";
        this.chart.radius.visible = shape === "rounded" && look !== "3d";
        this.chart.shape.visible = look !== "3d";
        this.chart.groupGap.visible = clustered && info.series > 1 || !clustered;
        this.palette.brand.visible = src === "brand";
        this.palette.mode.visible = src === "brand";
        this.palette.custom.visible = src === "custom";
        this.palette.varyByCategory.visible = info.series <= 1;
        this.dataColors.visible = this.dataColors.slices.length > 0;
        this.labels.position.items = clustered ? POS_ALL : POS_ALL.filter(o => o.value !== "outsideEnd");
        if (!clustered && this.labels.position.value.value === "outsideEnd") this.labels.position.value = POS_ALL[0];
        this.totals.visible = stacked;
        this.categoryAxis.concatenate.visible = info.levels > 1;
        this.valueAxis.displayUnits.visible = !percent; this.valueAxis.decimals.visible = !percent;
        this.valueAxis.start.visible = !percent; this.valueAxis.end.visible = !percent;
        this.legend.visible = info.series > 1;
        this.refLine.value.visible = String(this.refLine.kind.value.value) === "constant";
        this.refLine.visible = !percent;
        this.drill.buttons.visible = info.drillable;
    }
}
