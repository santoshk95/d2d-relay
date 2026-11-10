/*
 * Format pane for Period Hierarchy Slicer. The shared cards (style, palette, colors, labels) come from
 * common/cards.ts; ChartCard holds the look and row sizes, SlicerCard the slicer behaviour. Card and
 * slice names must match the objects and properties in caps.js.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { range, LOOKS, StyleCard, PaletteCard, DataColorsCard, LabelsCard } from "./common/cards";

class ChartCard extends fs.SimpleCard {
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 50, options: range(0, 100) });
    rowHeight = new fs.NumUpDown({ name: "rowHeight", displayName: "Row height (px)", value: 22, options: range(16, 48) });
    corner = new fs.NumUpDown({ name: "corner", displayName: "Corner radius (px)", value: 6, options: range(0, 20) });
    name = "chart"; displayName = "Chart";
    slices = [this.look, this.shadow, this.rowHeight, this.corner];
}

class SlicerCard extends fs.SimpleCard {
    placeholder = new fs.TextInput({ name: "placeholder", displayName: "Text when nothing is picked", value: "All periods", placeholder: "All periods" });
    startOpen = new fs.ToggleSwitch({ name: "startOpen", displayName: "Show the tree open", value: true });
    multiSelect = new fs.ToggleSwitch({ name: "multiSelect", displayName: "Ctrl-click picks several", value: true });
    selColor = new fs.ColorPicker({ name: "selColor", displayName: "Selection color", value: { value: "" } });
    name = "slicer"; displayName = "Slicer";
    slices = [this.placeholder, this.startOpen, this.multiSelect, this.selColor];
}

export class Settings extends fs.Model {
    chart = new ChartCard();
    slicer = new SlicerCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    labels = new LabelsCard(true);
    cards: fs.Cards[] = [this.slicer, this.chart, this.style, this.palette, this.dataColors, this.labels];

    /** hide options that do not apply to the data shown (called before the Format pane opens) */
    tidy(hasValues: boolean) {
        this.labels.visible = hasValues;
    }
}
