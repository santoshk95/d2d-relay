/*
 * Format pane for Atlas Proportion: Mekko, waffle, pictogram, aster plot,
 * rose and Venn. Shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, LegendCard } from "./common/cards";

const TYPES = [opt("mekko", "Mekko"), opt("waffle", "Waffle"), opt("pictogram", "Pictogram"), opt("aster", "Aster plot"), opt("rose", "Rose (polar area)"), opt("venn", "Venn diagram")];
const CONTENT = [opt("percent", "Percent"), opt("value", "Value"), opt("both", "Value and percent")];
const SHAPES = [opt("square", "Square"), opt("rounded", "Rounded"), opt("circle", "Circle")];
const ICONS = [opt("person", "Person"), opt("circle", "Circle"), opt("square", "Square"), opt("star", "Star"), opt("heart", "Heart"), opt("drop", "Drop")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 55, options: range(0, 100) });
    content = new fs.ItemDropdown({ name: "content", displayName: "Labels show", items: CONTENT, value: CONTENT[0] });
    emptyColor = new fs.ColorPicker({ name: "emptyColor", displayName: "Empty color", value: { value: "" } });
    multiples = new fs.ToggleSwitch({ name: "multiples", displayName: "One per category", value: false });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.content, this.emptyColor, this.multiples];
}
class WaffleCard extends fs.SimpleCard {
    rows = new fs.NumUpDown({ name: "rows", displayName: "Rows", value: 10, options: range(1, 40) });
    columns = new fs.NumUpDown({ name: "columns", displayName: "Columns", value: 10, options: range(1, 40) });
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Cell shape", items: SHAPES, value: SHAPES[1] });
    gap = new fs.NumUpDown({ name: "gap", displayName: "Gap (px)", value: 2, options: range(0, 10) });
    bigNumber = new fs.ToggleSwitch({ name: "bigNumber", displayName: "Big number", value: true });
    name = "waffle"; displayName = "Waffle";
    slices = [this.rows, this.columns, this.shape, this.gap, this.bigNumber];
}
class PictogramCard extends fs.SimpleCard {
    icon = new fs.ItemDropdown({ name: "icon", displayName: "Icon", items: ICONS, value: ICONS[0] });
    unit = new fs.NumUpDown({ name: "unit", displayName: "Units per icon (0 = auto)", value: 0 });
    perRow = new fs.NumUpDown({ name: "perRow", displayName: "Icons per row (0 = auto)", value: 0, options: range(0, 100) });
    total = new fs.NumUpDown({ name: "total", displayName: "Out of (0 = from data)", value: 0 });
    name = "pictogram"; displayName = "Pictogram";
    slices = [this.icon, this.unit, this.perRow, this.total];
}
class RadialCard extends fs.SimpleCard {
    hole = new fs.Slider({ name: "hole", displayName: "Center hole (%)", value: 22, options: range(0, 70) });
    gap = new fs.NumUpDown({ name: "gap", displayName: "Gap between wedges (px)", value: 1.5, options: range(0, 10) });
    maxScore = new fs.NumUpDown({ name: "maxScore", displayName: "Maximum score", value: 100 });
    outline = new fs.ToggleSwitch({ name: "outline", displayName: "Outline at maximum", value: true });
    centerText = new fs.ToggleSwitch({ name: "centerText", displayName: "Score in the center", value: true });
    shadeByValue = new fs.ToggleSwitch({ name: "shadeByValue", displayName: "Shade by value", value: false });
    name = "radial"; displayName = "Aster and rose";
    slices = [this.hole, this.gap, this.maxScore, this.outline, this.centerText, this.shadeByValue];
}
class MekkoCard extends fs.SimpleCard {
    gap = new fs.NumUpDown({ name: "gap", displayName: "Gap (px)", value: 2, options: range(0, 12) });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 2, options: range(0, 12) });
    showTotals = new fs.ToggleSwitch({ name: "showTotals", displayName: "Column totals", value: true });
    name = "mekko"; displayName = "Mekko";
    slices = [this.gap, this.radius, this.showTotals];
}
class VennCard extends fs.SimpleCard {
    opacity = new fs.Slider({ name: "opacity", displayName: "Circle opacity (%)", value: 45, options: range(10, 100) });
    separator = new fs.TextInput({ name: "separator", displayName: "Separator in category", placeholder: "&", value: "&" });
    name = "venn"; displayName = "Venn";
    slices = [this.opacity, this.separator];
}

export class ProportionSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    waffle = new WaffleCard();
    pictogram = new PictogramCard();
    radial = new RadialCard();
    mekko = new MekkoCard();
    venn = new VennCard();
    labels = new LabelsCard(true);
    categoryAxis = new CategoryAxisCard();
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.waffle, this.pictogram, this.radial, this.mekko, this.venn, this.labels, this.categoryAxis, this.legend];

    get type() { return val(this.chart.chartType); }
    tidy(info: { series: number; cats: number }) {
        const t = this.type;
        this.chart.emptyColor.visible = t === "waffle" || t === "pictogram" || t === "aster";
        this.chart.multiples.visible = t === "waffle" || t === "pictogram";
        this.waffle.visible = t === "waffle";
        this.pictogram.visible = t === "pictogram";
        this.radial.visible = t === "aster" || t === "rose";
        this.radial.maxScore.visible = t === "aster"; this.radial.outline.visible = t === "aster"; this.radial.centerText.visible = t === "aster";
        this.radial.shadeByValue.visible = t === "rose" && info.series <= 1;
        this.mekko.visible = t === "mekko";
        this.venn.visible = t === "venn";
        this.categoryAxis.visible = t === "mekko" || t === "pictogram" || t === "aster" || t === "rose";
        this.legend.visible = t !== "pictogram";
    }
}
