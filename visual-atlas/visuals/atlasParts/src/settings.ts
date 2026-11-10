/*
 * Format pane for Atlas Parts: pie and donut. Shared cards come from
 * common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, LegendCard } from "./common/cards";

const TYPES = [opt("pie", "Pie"), opt("donut", "Donut")];
const SORT = [opt("value", "Largest first"), opt("none", "Data order")];
const POS = [opt("outside", "Outside with leader lines"), opt("inside", "Inside"), opt("auto", "Inside when it fits")];
const CONTENT = [opt("percent", "Percent"), opt("categoryPercent", "Category, percent"), opt("categoryValue", "Category, value"), opt("all", "Category, value, percent"), opt("value", "Value")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[1] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 50, options: range(0, 100) });
    hole = new fs.Slider({ name: "hole", displayName: "Inner radius (%)", value: 58, options: range(10, 92) });
    startAngle = new fs.NumUpDown({ name: "startAngle", displayName: "Start angle (degrees)", value: 0, options: range(-360, 360) });
    half = new fs.ToggleSwitch({ name: "half", displayName: "Half circle", value: false });
    sort = new fs.ItemDropdown({ name: "sort", displayName: "Order", items: SORT, value: SORT[0] });
    topN = new fs.NumUpDown({ name: "topN", displayName: "Top N (0 = all)", value: 0, options: range(0, 100) });
    otherLabel = new fs.TextInput({ name: "otherLabel", displayName: "Name for the rest", placeholder: "Other", value: "Other" });
    gap = new fs.NumUpDown({ name: "gap", displayName: "Gap between slices (px)", value: 2, options: range(0, 12) });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.hole, this.startAngle, this.half, this.sort, this.topN, this.otherLabel, this.gap];
}
class SlicesCard extends fs.SimpleCard {
    labelPosition = new fs.ItemDropdown({ name: "labelPosition", displayName: "Label position", items: POS, value: POS[0] });
    content = new fs.ItemDropdown({ name: "content", displayName: "Labels show", items: CONTENT, value: CONTENT[1] });
    centerTotal = new fs.ToggleSwitch({ name: "centerTotal", displayName: "Total in the center", value: true });
    centerLabel = new fs.TextInput({ name: "centerLabel", displayName: "Center caption", placeholder: "Total", value: "" });
    track = new fs.ToggleSwitch({ name: "track", displayName: "Last slice as a track (progress ring)", value: false });
    trackColor = new fs.ColorPicker({ name: "trackColor", displayName: "Track color", value: { value: "" } });
    name = "slices"; displayName = "Slices and labels";
    slices = [this.labelPosition, this.content, this.centerTotal, this.centerLabel, this.track, this.trackColor];
}
class DrillCard extends fs.SimpleCard {
    buttons = new fs.ToggleSwitch({ name: "buttons", displayName: "Drill buttons on the visual", value: true });
    allow = new fs.ToggleSwitch({ name: "allow", displayName: "Allow drilling", value: true });
    name = "drill"; displayName = "Drill-down";
    slices = [this.buttons, this.allow];
}

export class PartsSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    slices = new SlicesCard();
    labels = new LabelsCard(true);
    legend = new LegendCard();
    drill = new DrillCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.slices, this.labels, this.legend, this.drill];

    get type() { return val(this.chart.chartType); }
    tidy(info: { drillable: boolean }) {
        const donut = this.type === "donut";
        this.chart.hole.visible = donut;
        this.chart.otherLabel.visible = this.chart.topN.value > 0;
        this.slices.centerTotal.visible = donut; this.slices.centerLabel.visible = donut && this.slices.centerTotal.value;
        this.slices.trackColor.visible = this.slices.track.value;
        this.drill.buttons.visible = info.drillable;
    }
}
