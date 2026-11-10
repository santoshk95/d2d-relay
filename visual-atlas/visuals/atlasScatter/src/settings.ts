/*
 * Format pane for Atlas Scatter: scatter and bubble (play axis, quadrants,
 * trend and ratio lines, symmetry shading, log axes, clusters, drag to
 * zoom), dot plot and Gantt. Shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard, LegendCard } from "./common/cards";

const TYPES = [opt("scatter", "Scatter or bubble"), opt("dotplot", "Dot plot"), opt("gantt", "Gantt")];
const SHAPES = [opt("circle", "Circle"), opt("square", "Square"), opt("diamond", "Diamond")];
const COLORBY = [opt("legend", "Legend"), opt("single", "One color"), opt("cluster", "Automatic clusters")];
const PROG = [opt("fill", "Fill the bar"), opt("overlay", "Thin overlay"), opt("none", "None")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 35, options: range(0, 100) });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow];
}
class PointsCard extends fs.SimpleCard {
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Marker shape", items: SHAPES, value: SHAPES[0] });
    size = new fs.NumUpDown({ name: "size", displayName: "Marker size", value: 5, options: range(1, 30) });
    maxBubble = new fs.NumUpDown({ name: "maxBubble", displayName: "Largest bubble", value: 26, options: range(4, 80) });
    opacity = new fs.Slider({ name: "opacity", displayName: "Opacity (%)", value: 80, options: range(10, 100) });
    colorBy = new fs.ItemDropdown({ name: "colorBy", displayName: "Color by", items: COLORBY, value: COLORBY[0] });
    clusters = new fs.NumUpDown({ name: "clusters", displayName: "Number of clusters", value: 3, options: range(2, 10) });
    name = "points"; displayName = "Markers";
    slices = [this.shape, this.size, this.maxBubble, this.opacity, this.colorBy, this.clusters];
}
class GuidesCard extends fs.SimpleCard {
    quadrants = new fs.ToggleSwitch({ name: "quadrants", displayName: "Quadrants", value: false });
    xSplit = new fs.TextInput({ name: "xSplit", displayName: "Quadrant X split", placeholder: "Average", value: "" });
    ySplit = new fs.TextInput({ name: "ySplit", displayName: "Quadrant Y split", placeholder: "Average", value: "" });
    trend = new fs.ToggleSwitch({ name: "trend", displayName: "Trend line", value: false });
    ratio = new fs.ToggleSwitch({ name: "ratio", displayName: "Ratio line", value: false });
    symmetry = new fs.ToggleSwitch({ name: "symmetry", displayName: "Symmetry shading (Y = X)", value: false });
    xLog = new fs.ToggleSwitch({ name: "xLog", displayName: "Logarithmic X-axis", value: false });
    yLog = new fs.ToggleSwitch({ name: "yLog", displayName: "Logarithmic Y-axis", value: false });
    zoom = new fs.ToggleSwitch({ name: "zoom", displayName: "Drag to zoom", value: true });
    color = new fs.ColorPicker({ name: "color", displayName: "Guide color", value: { value: "" } });
    name = "guides"; displayName = "Guides and axes";
    analyticsPane = true;
    slices = [this.quadrants, this.xSplit, this.ySplit, this.trend, this.ratio, this.symmetry, this.xLog, this.yLog, this.zoom, this.color];
}
class PlayCard extends fs.SimpleCard {
    speed = new fs.NumUpDown({ name: "speed", displayName: "Milliseconds per frame", value: 900, options: range(100, 10000) });
    loop = new fs.ToggleSwitch({ name: "loop", displayName: "Loop", value: false });
    name = "play"; displayName = "Play axis";
    slices = [this.speed, this.loop];
}
class GanttCard extends fs.SimpleCard {
    progress = new fs.ItemDropdown({ name: "progress", displayName: "Progress", items: PROG, value: PROG[0] });
    today = new fs.ToggleSwitch({ name: "today", displayName: "Today line", value: true });
    weekends = new fs.ToggleSwitch({ name: "weekends", displayName: "Shade weekends", value: true });
    barHeight = new fs.Slider({ name: "barHeight", displayName: "Bar height (%)", value: 62, options: range(20, 95) });
    ownerColumn = new fs.ToggleSwitch({ name: "ownerColumn", displayName: "Owner column", value: true });
    percentColumn = new fs.ToggleSwitch({ name: "percentColumn", displayName: "% complete column", value: true });
    milestoneColor = new fs.ColorPicker({ name: "milestoneColor", displayName: "Milestone color", value: { value: "" } });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 4, options: range(0, 20) });
    name = "gantt"; displayName = "Gantt";
    slices = [this.progress, this.today, this.weekends, this.barHeight, this.ownerColumn, this.percentColumn, this.milestoneColor, this.radius];
}

export class ScatterSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    points = new PointsCard();
    play = new PlayCard();
    gantt = new GanttCard();
    labels = new LabelsCard();
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    guides = new GuidesCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.points, this.play, this.gantt, this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend, this.guides];

    get type() { return val(this.chart.chartType); }
    tidy(info: { size: boolean; play: boolean; legend: boolean; owner: boolean; progress: boolean }) {
        const t = this.type, sc = t === "scatter";
        this.points.visible = t !== "gantt";
        this.points.maxBubble.visible = info.size && sc;
        this.points.clusters.visible = val(this.points.colorBy) === "cluster";
        this.guides.visible = sc;
        this.guides.xSplit.visible = this.guides.quadrants.value; this.guides.ySplit.visible = this.guides.quadrants.value;
        this.play.visible = sc && info.play;
        this.gantt.visible = t === "gantt";
        this.gantt.ownerColumn.visible = info.owner; this.gantt.percentColumn.visible = info.progress;
        this.legend.visible = info.legend && val(this.points.colorBy) !== "single";
    }
}
