/*
 * Format pane for Atlas Lines: line, area, stacked and 100% area, and
 * line-and-column combos, with analytics (trend, min/max, average, target
 * zone, forecast, anomalies) and drill-down. Shared cards come from
 * common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard, LegendCard } from "./common/cards";

const TYPES = [opt("line", "Line"), opt("area", "Area"), opt("stackedArea", "Stacked area"), opt("percentArea", "100% stacked area"), opt("comboStacked", "Line and stacked column"), opt("comboClustered", "Line and clustered column")];
const CURVE = [opt("linear", "Straight"), opt("smooth", "Smooth"), opt("step", "Stepped")];
const MARKERS = [opt("none", "None"), opt("all", "All points"), opt("last", "Last point")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 40, options: range(0, 100) });
    curve = new fs.ItemDropdown({ name: "curve", displayName: "Line shape", items: CURVE, value: CURVE[0] });
    zoom = new fs.ToggleSwitch({ name: "zoom", displayName: "Zoom slider", value: false });
    zoomToSelection = new fs.ToggleSwitch({ name: "zoomToSelection", displayName: "Zoom to the selection", value: true });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.curve, this.zoom, this.zoomToSelection];
}
class LinesCard extends fs.SimpleCard {
    width = new fs.NumUpDown({ name: "width", displayName: "Line width", value: 2.2, options: range(0.5, 12) });
    markers = new fs.ItemDropdown({ name: "markers", displayName: "Markers", items: MARKERS, value: MARKERS[0] });
    markerSize = new fs.NumUpDown({ name: "markerSize", displayName: "Marker size", value: 3.5, options: range(1, 20) });
    dashed = new fs.TextInput({ name: "dashed", displayName: "Dashed series", placeholder: "Sales LY", value: "" });
    areaOpacity = new fs.Slider({ name: "areaOpacity", displayName: "Area opacity (%)", value: 30, options: range(5, 100) });
    endLabels = new fs.ToggleSwitch({ name: "endLabels", displayName: "Series names at line ends", value: false });
    focus = new fs.TextInput({ name: "focus", displayName: "Focus on series", placeholder: "Gray out the others", value: "" });
    secondary = new fs.ToggleSwitch({ name: "secondary", displayName: "Lines on a secondary axis", value: true });
    columnSpacing = new fs.Slider({ name: "columnSpacing", displayName: "Space between columns (%)", value: 30, options: range(0, 80) });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Column corner radius", value: 3, options: range(0, 20) });
    name = "lines"; displayName = "Lines and columns";
    slices = [this.width, this.markers, this.markerSize, this.dashed, this.areaOpacity, this.endLabels, this.focus, this.secondary, this.columnSpacing, this.radius];
}
class AnalyticsCard extends fs.SimpleCard {
    trend = new fs.ToggleSwitch({ name: "trend", displayName: "Trend line", value: false });
    minMax = new fs.ToggleSwitch({ name: "minMax", displayName: "Min and max lines", value: false });
    average = new fs.ToggleSwitch({ name: "average", displayName: "Average line", value: false });
    target = new fs.TextInput({ name: "target", displayName: "Target zone from", placeholder: "Value", value: "" });
    forecast = new fs.NumUpDown({ name: "forecast", displayName: "Forecast periods", value: 0, options: range(0, 60) });
    anomalies = new fs.ToggleSwitch({ name: "anomalies", displayName: "Anomalies", value: false });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    name = "analytics"; displayName = "Analytics";
    analyticsPane = true;
    slices = [this.trend, this.minMax, this.average, this.target, this.forecast, this.anomalies, this.color];
}
class DrillCard extends fs.SimpleCard {
    buttons = new fs.ToggleSwitch({ name: "buttons", displayName: "Drill buttons on the visual", value: true });
    allow = new fs.ToggleSwitch({ name: "allow", displayName: "Allow drilling", value: true });
    name = "drill"; displayName = "Drill-down";
    slices = [this.buttons, this.allow];
}

export class LinesSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    lines = new LinesCard();
    labels = new LabelsCard();
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    analytics = new AnalyticsCard();
    drill = new DrillCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.lines, this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend, this.analytics, this.drill];

    get type() { return val(this.chart.chartType); }
    tidy(info: { series: number; lines: number; drillable: boolean }) {
        const t = this.type, combo = t.startsWith("combo"), area = t.includes("rea");
        this.lines.areaOpacity.visible = area;
        this.chart.zoomToSelection.visible = this.chart.zoom.value;
        this.lines.secondary.visible = combo && info.lines > 0;
        this.lines.columnSpacing.visible = combo; this.lines.radius.visible = combo;
        this.lines.markerSize.visible = val(this.lines.markers) !== "none";
        this.analytics.visible = t !== "percentArea";
        this.analytics.forecast.visible = t === "line" || t === "area";
        this.analytics.anomalies.visible = t === "line" || t === "area";
        this.drill.buttons.visible = info.drillable;
        this.legend.visible = info.series > 1 && !this.lines.endLabels.value;
    }
}
