/*
 * Format pane for KPI Scorecard. Card and slice names match the objects and properties in caps.js.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { range, LOOKS, StyleCard, PaletteCard, DataColorsCard, LabelsCard } from "./common/cards";
import { Model } from "./model";

class ChartCard extends fs.SimpleCard {
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 50, options: range(0, 100) });
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Row text size", value: 11, options: range(6, 30) });
    zebra = new fs.ToggleSwitch({ name: "zebra", displayName: "Banded rows", value: false });
    rowLines = new fs.ToggleSwitch({ name: "rowLines", displayName: "Row lines", value: true });
    name = "chart"; displayName = "Chart";
    slices = [this.look, this.shadow, this.fontSize, this.zebra, this.rowLines];
}
class HeadersCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Column headers", value: true });
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Header text size", value: 9, options: range(6, 30) });
    kpi = new fs.TextInput({ name: "kpi", displayName: "KPI column", placeholder: "Field name", value: "" });
    result = new fs.TextInput({ name: "result", displayName: "Result column", placeholder: "Measure name", value: "" });
    latest = new fs.TextInput({ name: "latest", displayName: "Latest column", placeholder: "Measure name", value: "" });
    target = new fs.TextInput({ name: "target", displayName: "Target column", placeholder: "Target", value: "" });
    status = new fs.TextInput({ name: "status", displayName: "Status column", placeholder: "Status", value: "" });
    trend = new fs.TextInput({ name: "trend", displayName: "Trend column", placeholder: "Trend", value: "" });
    name = "headers"; displayName = "Column headers";
    slices = [this.show, this.fontSize, this.kpi, this.result, this.latest, this.target, this.status, this.trend];
}
class StatusCard extends fs.SimpleCard {
    goodColor = new fs.ColorPicker({ name: "goodColor", displayName: "On track", value: { value: "#1a9e5c" } });
    warnColor = new fs.ColorPicker({ name: "warnColor", displayName: "At risk", value: { value: "#d9a400" } });
    badColor = new fs.ColorPicker({ name: "badColor", displayName: "Off track", value: { value: "#d64550" } });
    icons = new fs.ToggleSwitch({ name: "icons", displayName: "Status icons", value: true });
    name = "status"; displayName = "Status chips";
    slices = [this.goodColor, this.warnColor, this.badColor, this.icons];
}
class TrendCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Sparkline", value: true });
    width = new fs.NumUpDown({ name: "width", displayName: "Line width", value: 1.5, options: range(0, 6) });
    endDot = new fs.ToggleSwitch({ name: "endDot", displayName: "Latest-point dot", value: true });
    name = "trend"; displayName = "Sparkline";
    slices = [this.show, this.width, this.endDot];
}

export class Settings extends fs.Model {
    chart = new ChartCard();
    headers = new HeadersCard();
    status = new StatusCard();
    trend = new TrendCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    labels = new LabelsCard(true);
    cards: fs.Cards[] = [this.chart, this.headers, this.status, this.trend, this.style, this.palette, this.dataColors, this.labels];

    /** hide options that do not apply to the data shown */
    tidy(m: Model | null) {
        this.trend.visible = !m || m.hasTrend;
    }
}
