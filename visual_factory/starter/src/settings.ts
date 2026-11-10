/*
 * Format pane for __TITLE__. The shared cards (style, palette, colors, labels, axes, gridlines,
 * legend) come from common/cards.ts; ChartCard holds this visual's own options. Card and slice
 * names must match the objects and properties in caps.js.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { range, LOOKS, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard, LegendCard } from "./common/cards";
import { Model } from "./common/matrix";

class ChartCard extends fs.SimpleCard {
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 50, options: range(0, 100) });
    gap = new fs.Slider({ name: "gap", displayName: "Gap between groups (%)", value: 30, options: range(0, 90) });
    corner = new fs.NumUpDown({ name: "corner", displayName: "Corner radius (px)", value: 4, options: range(0, 20) });
    name = "chart"; displayName = "Chart";
    slices = [this.look, this.shadow, this.gap, this.corner];
}

export class Settings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    labels = new LabelsCard(true);
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend];

    /** hide options that do not apply to the data shown (called before the Format pane opens) */
    tidy(m: Model | null) {
        this.chart.gap.visible = !m || m.cats.length > 1;
    }
}
