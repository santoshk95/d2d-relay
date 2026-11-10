/*
 * Format pane for Atlas Distribution. Every variation the gallery shows
 * for histograms, box plots, violins and parallel coordinates is a
 * setting here; settings that do not apply to the current chart type
 * are hidden.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { StyleCard } from "./common/cards";

const opt = (value: string, displayName: string) => ({ value, displayName });
type Range = { minValue: { type: powerbi.visuals.ValidatorType.Min; value: number }; maxValue: { type: powerbi.visuals.ValidatorType.Max; value: number } };
const range = (min: number, max: number): Range => ({ minValue: { type: powerbi.visuals.ValidatorType.Min, value: min }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: max } });

export const TYPES = [opt("histogram", "Histogram"), opt("box", "Box and whisker"), opt("violin", "Violin"), opt("parallel", "Parallel coordinates")];
const LOOKS = [opt("flat", "Flat"), opt("soft", "Soft"), opt("3d", "3D")];
const ORIENT = [opt("vertical", "Vertical"), opt("horizontal", "Horizontal")];
const SORT = [opt("none", "Data order"), opt("name", "Name"), opt("medianAsc", "Median, low to high"), opt("medianDesc", "Median, high to low")];
const SOURCES = [opt("theme", "Report theme"), opt("brand", "Brand color"), opt("custom", "Custom list")];
const MODES = [opt("spectrum", "Spectrum"), opt("analogous", "Analogous"), opt("mono", "Mono")];
const BINMODE = [opt("auto", "Auto"), opt("count", "Number of bins"), opt("width", "Bin width")];
const HLAYOUT = [opt("overlap", "Overlapping"), opt("stacked", "Stacked")];
const YMEAS = [opt("count", "Count"), opt("percent", "Percent of group")];
const WHISK = [opt("iqr", "1.5 × IQR"), opt("minmax", "Minimum to maximum"), opt("p5", "5th to 95th percentile")];
const BPOINTS = [opt("none", "None"), opt("jitter", "All, jittered"), opt("beside", "All, beside the box")];
const SIDE = [opt("full", "Full"), opt("half", "Half (raincloud)")];
const INNER = [opt("none", "None"), opt("box", "Box"), opt("quartiles", "Quartile lines")];
const VPOINTS = [opt("none", "None"), opt("jitter", "Jittered"), opt("barcode", "Barcode")];
const SCALES = [opt("independent", "One per axis"), opt("shared", "Shared")];
const CURVE = [opt("straight", "Straight"), opt("smooth", "Smooth")];
const PTICKS = [opt("minmax", "Minimum and maximum"), opt("full", "All ticks")];
const LEGEND = [opt("top", "Top"), opt("topCenter", "Top center"), opt("bottom", "Bottom"), opt("bottomCenter", "Bottom center"), opt("right", "Right")];
const LINE = [opt("solid", "Solid"), opt("dashed", "Dashed"), opt("dotted", "Dotted")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 55, options: range(0, 100) });
    orientation = new fs.ItemDropdown({ name: "orientation", displayName: "Orientation", items: ORIENT, value: ORIENT[0] });
    sort = new fs.ItemDropdown({ name: "sort", displayName: "Sort groups", items: SORT, value: SORT[0] });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.orientation, this.sort];
}
class PaletteCard extends fs.SimpleCard {
    source = new fs.ItemDropdown({ name: "source", displayName: "Colors from", items: SOURCES, value: SOURCES[0] });
    brand = new fs.ColorPicker({ name: "brand", displayName: "Brand color", value: { value: "#2a78d6" } });
    mode = new fs.ItemDropdown({ name: "mode", displayName: "Palette style", items: MODES, value: MODES[0] });
    custom = new fs.TextArea({ name: "custom", displayName: "Custom colors", placeholder: "Hex codes, or paste a theme JSON", value: "" });
    name = "palette"; displayName = "Palette";
    slices = [this.source, this.brand, this.mode, this.custom];
}
export class DataColorsCard extends fs.SimpleCard {
    name = "dataColors"; displayName = "Colors";
    slices: fs.Slice[] = [];
}
class HistogramCard extends fs.SimpleCard {
    binMode = new fs.ItemDropdown({ name: "binMode", displayName: "Bins", items: BINMODE, value: BINMODE[0] });
    binCount = new fs.NumUpDown({ name: "binCount", displayName: "Number of bins", value: 20, options: range(2, 200) });
    binWidth = new fs.NumUpDown({ name: "binWidth", displayName: "Bin width", value: 0 });
    layout = new fs.ItemDropdown({ name: "layout", displayName: "Groups", items: HLAYOUT, value: HLAYOUT[0] });
    opacity = new fs.Slider({ name: "opacity", displayName: "Opacity when overlapping (%)", value: 60, options: range(15, 100) });
    yMeasure = new fs.ItemDropdown({ name: "yMeasure", displayName: "Bar height", items: YMEAS, value: YMEAS[0] });
    normalCurve = new fs.ToggleSwitch({ name: "normalCurve", displayName: "Normal curve", value: false });
    gap = new fs.NumUpDown({ name: "gap", displayName: "Space between bars (px)", value: 1.5, options: range(0, 12) });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 2, options: range(0, 12) });
    name = "histogram"; displayName = "Histogram";
    slices = [this.binMode, this.binCount, this.binWidth, this.layout, this.opacity, this.yMeasure, this.normalCurve, this.gap, this.radius];
}
class BoxCard extends fs.SimpleCard {
    whiskers = new fs.ItemDropdown({ name: "whiskers", displayName: "Whiskers", items: WHISK, value: WHISK[0] });
    outliers = new fs.ToggleSwitch({ name: "outliers", displayName: "Outliers", value: true });
    mean = new fs.ToggleSwitch({ name: "mean", displayName: "Mean marker", value: false });
    points = new fs.ItemDropdown({ name: "points", displayName: "Data points", items: BPOINTS, value: BPOINTS[0] });
    width = new fs.Slider({ name: "width", displayName: "Box width (%)", value: 50, options: range(10, 100) });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 3, options: range(0, 20) });
    name = "box"; displayName = "Box and whisker";
    slices = [this.whiskers, this.outliers, this.mean, this.points, this.width, this.radius];
}
class ViolinCard extends fs.SimpleCard {
    side = new fs.ItemDropdown({ name: "side", displayName: "Shape", items: SIDE, value: SIDE[0] });
    inner = new fs.ItemDropdown({ name: "inner", displayName: "Inside the violin", items: INNER, value: INNER[0] });
    points = new fs.ItemDropdown({ name: "points", displayName: "Data points", items: VPOINTS, value: VPOINTS[0] });
    bandwidth = new fs.Slider({ name: "bandwidth", displayName: "Smoothing (%)", value: 100, options: range(20, 400) });
    width = new fs.Slider({ name: "width", displayName: "Violin width (%)", value: 84, options: range(20, 100) });
    trim = new fs.ToggleSwitch({ name: "trim", displayName: "Trim to the data range", value: true });
    name = "violin"; displayName = "Violin";
    slices = [this.side, this.inner, this.points, this.bandwidth, this.width, this.trim];
}
class PointsCard extends fs.SimpleCard {
    size = new fs.NumUpDown({ name: "size", displayName: "Point size", value: 2.4, options: range(0.5, 12) });
    opacity = new fs.Slider({ name: "opacity", displayName: "Point opacity (%)", value: 65, options: range(5, 100) });
    name = "points"; displayName = "Data points";
    slices = [this.size, this.opacity];
}
class ParallelCard extends fs.SimpleCard {
    scales = new fs.ItemDropdown({ name: "scales", displayName: "Axis scales", items: SCALES, value: SCALES[0] });
    curve = new fs.ItemDropdown({ name: "curve", displayName: "Lines", items: CURVE, value: CURVE[0] });
    lineWidth = new fs.NumUpDown({ name: "lineWidth", displayName: "Line width", value: 1.6, options: range(0.5, 8) });
    opacity = new fs.Slider({ name: "opacity", displayName: "Line opacity (%)", value: 60, options: range(5, 100) });
    ticks = new fs.ItemDropdown({ name: "ticks", displayName: "Axis labels", items: PTICKS, value: PTICKS[0] });
    name = "parallel"; displayName = "Parallel coordinates";
    slices = [this.scales, this.curve, this.lineWidth, this.opacity, this.ticks];
}
class LabelsCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Data labels", value: false });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 9, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    displayUnits = new fs.AutoDropdown({ name: "displayUnits", displayName: "Display units", value: 0 });
    decimals = new fs.NumUpDown({ name: "decimals", displayName: "Decimal places", value: -1, options: range(-1, 9) });
    name = "labels"; displayName = "Data labels";
    slices = [this.fontSize, this.color, this.displayUnits, this.decimals];
}
class CategoryAxisCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Axis", value: true });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 10, options: range(6, 40) });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    title = new fs.ToggleSwitch({ name: "title", displayName: "Title", value: false });
    name = "categoryAxis"; displayName = "Group axis";
    slices = [this.fontSize, this.color, this.title];
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
class StatsCard extends fs.SimpleCard {
    mean = new fs.ToggleSwitch({ name: "mean", displayName: "Mean line", value: false });
    median = new fs.ToggleSwitch({ name: "median", displayName: "Median line", value: false });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    style = new fs.ItemDropdown({ name: "style", displayName: "Line style", items: LINE, value: LINE[1] });
    label = new fs.ToggleSwitch({ name: "label", displayName: "Label", value: true });
    name = "stats"; displayName = "Mean and median";
    analyticsPane = true;
    slices = [this.mean, this.median, this.color, this.style, this.label];
}

export class DistSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    histogram = new HistogramCard();
    box = new BoxCard();
    violin = new ViolinCard();
    points = new PointsCard();
    parallel = new ParallelCard();
    labels = new LabelsCard();
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    stats = new StatsCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.histogram, this.box, this.violin, this.points, this.parallel,
        this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend, this.stats];

    /** hide settings that do not apply to the current data and chart type */
    tidy(info: { groups: number; measures: number }) {
        const t = String(this.chart.chartType.value.value), hist = t === "histogram", box = t === "box", vio = t === "violin", par = t === "parallel";
        const src = String(this.palette.source.value.value), look = String(this.chart.look.value.value);
        this.chart.shadow.visible = look !== "flat";
        this.chart.orientation.visible = box || vio;
        this.chart.sort.visible = (box || vio) && info.groups > 1;
        this.palette.brand.visible = src === "brand";
        this.palette.mode.visible = src === "brand";
        this.palette.custom.visible = src === "custom";
        this.dataColors.visible = this.dataColors.slices.length > 0;
        this.histogram.visible = hist;
        const bm = String(this.histogram.binMode.value.value);
        this.histogram.binCount.visible = bm === "count";
        this.histogram.binWidth.visible = bm === "width";
        this.histogram.layout.visible = info.groups > 1;
        this.histogram.opacity.visible = info.groups > 1 && String(this.histogram.layout.value.value) === "overlap";
        this.histogram.radius.visible = look !== "3d";
        this.box.visible = box;
        this.box.radius.visible = look !== "3d";
        this.violin.visible = vio;
        const pts = (box && String(this.box.points.value.value) !== "none") || (box && this.box.outliers.value) || (vio && String(this.violin.points.value.value) !== "none");
        this.points.visible = pts;
        this.parallel.visible = par;
        this.labels.visible = !par;
        this.categoryAxis.visible = (box || vio) && info.groups > 0;
        this.valueAxis.start.visible = !par || String(this.parallel.scales.value.value) === "shared";
        this.valueAxis.end.visible = this.valueAxis.start.visible;
        this.legend.visible = (hist || par) && info.groups > 1;
        this.stats.visible = !par;
    }
}
