/*
 * Format pane for Small Multiple Lines. Card and slice names match the objects and properties in caps.js.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { range, LOOKS, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard, LegendCard } from "./common/cards";
import { Model } from "./model";

class ChartCard extends fs.SimpleCard {
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 50, options: range(0, 100) });
    columns = new fs.NumUpDown({ name: "columns", displayName: "Panels per row (0 = auto)", value: 0, options: range(0, 12) });
    lineWidth = new fs.NumUpDown({ name: "lineWidth", displayName: "Line width", value: 2, options: range(1, 8) });
    sharedScale = new fs.ToggleSwitch({ name: "sharedScale", displayName: "Same scale in every panel", value: false });
    titleSize = new fs.NumUpDown({ name: "titleSize", displayName: "Panel title size", value: 11, options: range(6, 30) });
    name = "chart"; displayName = "Chart";
    slices = [this.look, this.shadow, this.columns, this.lineWidth, this.sharedScale, this.titleSize];
}
class StatusCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "On-track check", value: true });
    threshold = new fs.NumUpDown({ name: "threshold", displayName: "On track from (% of comparison)", value: 95, options: range(0, 1000) });
    goodColor = new fs.ColorPicker({ name: "goodColor", displayName: "On track", value: { value: "#1a9e5c" } });
    warnColor = new fs.ColorPicker({ name: "warnColor", displayName: "Behind", value: { value: "#d9a400" } });
    topLevelSlice = this.show;
    name = "status"; displayName = "On-track check";
    slices = [this.threshold, this.goodColor, this.warnColor];
}

export class Settings extends fs.Model {
    chart = new ChartCard();
    status = new StatusCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    labels = new LabelsCard(true);
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.status, this.style, this.palette, this.dataColors, this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend];

    tidy(m: Model | null) {
        this.status.visible = !m || m.hasComp;
    }
}
