/*
 * Format pane for SPC Control Chart: look, line and marker sizes, sigma
 * multiple for computed limits, colours of the alarm points and limit lines.
 * Shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { range, LOOKS, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard } from "./common/cards";

class ChartCard extends fs.SimpleCard {
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 40, options: range(0, 100) });
    name = "chart"; displayName = "Chart";
    slices = [this.look, this.shadow];
}
class SpcCard extends fs.SimpleCard {
    width = new fs.NumUpDown({ name: "width", displayName: "Line width", value: 1.8, options: range(0.5, 8) });
    markerSize = new fs.NumUpDown({ name: "markerSize", displayName: "Point size", value: 4, options: range(1, 14) });
    sigma = new fs.NumUpDown({ name: "sigma", displayName: "Sigma multiple (when limits are not bound)", value: 3, options: range(1, 6) });
    showLimitLabels = new fs.ToggleSwitch({ name: "showLimitLabels", displayName: "Label the limits (UCL, mean, LCL)", value: true });
    shadeZone = new fs.ToggleSwitch({ name: "shadeZone", displayName: "Shade the in-control zone", value: true });
    runRule = new fs.ToggleSwitch({ name: "runRule", displayName: "Flag runs of 8 on one side of the centre", value: false });
    alarmColor = new fs.ColorPicker({ name: "alarmColor", displayName: "Out-of-control colour", value: { value: "#D64550" } });
    limitColor = new fs.ColorPicker({ name: "limitColor", displayName: "Control limit colour", value: { value: "" } });
    name = "spc"; displayName = "Control chart";
    slices = [this.width, this.markerSize, this.sigma, this.showLimitLabels, this.shadeZone, this.runRule, this.alarmColor, this.limitColor];
}

export class SpcSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    spc = new SpcCard();
    labels = new LabelsCard();
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.spc, this.labels, this.categoryAxis, this.valueAxis, this.gridlines];
}
