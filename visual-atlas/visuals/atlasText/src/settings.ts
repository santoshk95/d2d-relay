/*
 * Format pane for Atlas Text: word cloud and ranked words. Shared cards
 * come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, LegendCard } from "./common/cards";

const TYPES = [opt("cloud", "Word cloud"), opt("bars", "Ranked words")];
const SPLIT = [opt("auto", "Auto"), opt("phrases", "Keep phrases"), opt("words", "Split into words")];
const ROT = [opt("none", "None"), opt("some", "Some vertical"), opt("mixed", "Mixed angles")];
const SCALE = [opt("sqrt", "Square root"), opt("linear", "Linear"), opt("log", "Logarithmic")];
const COLORBY = [opt("palette", "A color per word"), opt("single", "One color"), opt("group", "Topic"), opt("value", "Color value (gradient)")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[0] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 30, options: range(0, 100) });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow];
}
class WordsCard extends fs.SimpleCard {
    split = new fs.ItemDropdown({ name: "split", displayName: "Text", items: SPLIT, value: SPLIT[0] });
    stopWords = new fs.ToggleSwitch({ name: "stopWords", displayName: "Remove common words", value: true });
    extraStopWords = new fs.TextInput({ name: "extraStopWords", displayName: "Also remove", placeholder: "bike, store", value: "" });
    minLength = new fs.NumUpDown({ name: "minLength", displayName: "Minimum word length", value: 3, options: range(1, 20) });
    maxWords = new fs.NumUpDown({ name: "maxWords", displayName: "Maximum words", value: 120, options: range(5, 500) });
    lowercase = new fs.ToggleSwitch({ name: "lowercase", displayName: "Lowercase", value: true });
    name = "words"; displayName = "Words";
    slices = [this.split, this.stopWords, this.extraStopWords, this.minLength, this.maxWords, this.lowercase];
}
class CloudCard extends fs.SimpleCard {
    rotation = new fs.ItemDropdown({ name: "rotation", displayName: "Rotation", items: ROT, value: ROT[1] });
    minSize = new fs.NumUpDown({ name: "minSize", displayName: "Smallest text", value: 10, options: range(4, 80) });
    maxSize = new fs.NumUpDown({ name: "maxSize", displayName: "Largest text", value: 54, options: range(8, 200) });
    scale = new fs.ItemDropdown({ name: "scale", displayName: "Size scale", items: SCALE, value: SCALE[0] });
    padding = new fs.NumUpDown({ name: "padding", displayName: "Space between words (px)", value: 2, options: range(0, 20) });
    name = "cloud"; displayName = "Word cloud";
    slices = [this.rotation, this.minSize, this.maxSize, this.scale, this.padding];
}
class ColorCard extends fs.SimpleCard {
    colorBy = new fs.ItemDropdown({ name: "colorBy", displayName: "Color by", items: COLORBY, value: COLORBY[0] });
    lowColor = new fs.ColorPicker({ name: "lowColor", displayName: "Low color", value: { value: "#d64550" } });
    highColor = new fs.ColorPicker({ name: "highColor", displayName: "High color", value: { value: "#1a9e5c" } });
    name = "wcolor"; displayName = "Color rules";
    slices = [this.colorBy, this.lowColor, this.highColor];
}

export class TextSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    words = new WordsCard();
    cloud = new CloudCard();
    wcolor = new ColorCard();
    labels = new LabelsCard(true);
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.words, this.cloud, this.wcolor, this.labels, this.legend];

    get type() { return val(this.chart.chartType); }
    tidy(info: { group: boolean; color: boolean }) {
        const by = val(this.wcolor.colorBy);
        this.cloud.visible = this.type === "cloud";
        this.wcolor.lowColor.visible = by === "value"; this.wcolor.highColor.visible = by === "value";
        this.labels.visible = this.type === "bars";
        this.legend.visible = by === "group" && info.group;
        this.dataColors.visible = this.dataColors.visible && (by === "group" || by === "single");
    }
}
