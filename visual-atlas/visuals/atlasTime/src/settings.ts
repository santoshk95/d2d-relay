/*
 * Format pane for Atlas Time: calendar heatmap, heat grid and punch card,
 * stream graph and timeline slicer. Shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, LegendCard } from "./common/cards";

const TYPES = [opt("calendar", "Calendar heatmap"), opt("heatgrid", "Heat grid"), opt("stream", "Stream graph"), opt("timeline", "Timeline slicer")];
const VIEW = [opt("year", "Year (weeks)"), opt("month", "Month pages")];
const WEEK = [opt("monday", "Monday"), opt("sunday", "Sunday")];
const SHAPE = [opt("cell", "Cells"), opt("circle", "Circles sized by value (punch card)")];
const OFFSET = [opt("wiggle", "Wiggle"), opt("silhouette", "Silhouette"), opt("zero", "Stacked"), opt("expand", "100% stacked")];
const GRAIN = [opt("day", "Day"), opt("week", "Week"), opt("month", "Month"), opt("quarter", "Quarter"), opt("year", "Year")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 40, options: range(0, 100) });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow];
}
const SMODE = [opt("linear", "By value"), opt("quantile", "By rank (quantiles)")];
class ScaleCard extends fs.SimpleCard {
    mode = new fs.ItemDropdown({ name: "mode", displayName: "Color by", items: SMODE, value: SMODE[0] });
    lowColor = new fs.ColorPicker({ name: "lowColor", displayName: "Low color", value: { value: "" } });
    highColor = new fs.ColorPicker({ name: "highColor", displayName: "High color", value: { value: "" } });
    emptyColor = new fs.ColorPicker({ name: "emptyColor", displayName: "No data color", value: { value: "" } });
    steps = new fs.NumUpDown({ name: "steps", displayName: "Color steps (0 = smooth)", value: 0, options: range(0, 12) });
    gap = new fs.NumUpDown({ name: "gap", displayName: "Gap between cells (px)", value: 2, options: range(0, 10) });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 2, options: range(0, 12) });
    name = "scale"; displayName = "Color scale";
    slices = [this.mode, this.lowColor, this.highColor, this.emptyColor, this.steps, this.gap, this.radius];
}
class CalendarCard extends fs.SimpleCard {
    view = new fs.ItemDropdown({ name: "view", displayName: "View", items: VIEW, value: VIEW[0] });
    weekStart = new fs.ItemDropdown({ name: "weekStart", displayName: "Week starts on", items: WEEK, value: WEEK[0] });
    dayNames = new fs.ToggleSwitch({ name: "dayNames", displayName: "Day names", value: true });
    monthNames = new fs.ToggleSwitch({ name: "monthNames", displayName: "Month names", value: true });
    name = "calendar"; displayName = "Calendar";
    slices = [this.view, this.weekStart, this.dayNames, this.monthNames];
}
class HeatCard extends fs.SimpleCard {
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Shape", items: SHAPE, value: SHAPE[0] });
    colorCircles = new fs.ToggleSwitch({ name: "colorCircles", displayName: "Shade circles by value", value: true });
    name = "heatgrid"; displayName = "Heat grid";
    slices = [this.shape, this.colorCircles];
}
class StreamCard extends fs.SimpleCard {
    offset = new fs.ItemDropdown({ name: "offset", displayName: "Layout", items: OFFSET, value: OFFSET[0] });
    smooth = new fs.ToggleSwitch({ name: "smooth", displayName: "Smooth curves", value: true });
    opacity = new fs.Slider({ name: "opacity", displayName: "Opacity (%)", value: 90, options: range(10, 100) });
    name = "stream"; displayName = "Stream graph";
    slices = [this.offset, this.smooth, this.opacity];
}
class TimelineCard extends fs.SimpleCard {
    granularity = new fs.ItemDropdown({ name: "granularity", displayName: "Granularity", items: GRAIN, value: GRAIN[2] });
    bars = new fs.ToggleSwitch({ name: "bars", displayName: "Value bars", value: true });
    selColor = new fs.ColorPicker({ name: "selColor", displayName: "Selection color", value: { value: "" } });
    name = "timeline"; displayName = "Timeline slicer";
    slices = [this.granularity, this.bars, this.selColor];
}

export class TimeSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    scale = new ScaleCard();
    calendar = new CalendarCard();
    heatgrid = new HeatCard();
    stream = new StreamCard();
    timeline = new TimelineCard();
    labels = new LabelsCard();
    categoryAxis = new CategoryAxisCard();
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.scale, this.calendar, this.heatgrid, this.stream, this.timeline, this.labels, this.categoryAxis, this.legend];

    get type() { return val(this.chart.chartType); }
    tidy(info: { series: number }) {
        const t = this.type, scaled = t === "calendar" || t === "heatgrid";
        this.scale.visible = scaled;
        this.calendar.visible = t === "calendar";
        this.heatgrid.visible = t === "heatgrid";
        this.heatgrid.colorCircles.visible = val(this.heatgrid.shape) === "circle";
        this.stream.visible = t === "stream";
        this.timeline.visible = t === "timeline";
        this.categoryAxis.visible = t !== "calendar";
        this.legend.visible = t === "stream" && info.series > 1;
        this.dataColors.visible = this.dataColors.visible && (t === "stream" || t === "timeline");
    }
}
