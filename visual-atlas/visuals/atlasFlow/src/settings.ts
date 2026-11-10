/*
 * Format pane for Atlas Flow. Every option the gallery shows as a
 * variation is a setting here.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { StyleCard } from "./common/cards";

const opt = (value: string, displayName: string) => ({ value, displayName });
const CHART = [opt("sankey", "Sankey"), opt("chord", "Chord"), opt("network", "Network")];
const LOOKS = [opt("flat", "Flat"), opt("soft", "Soft"), opt("3d", "3D")];
const SOURCES = [opt("theme", "Report theme"), opt("brand", "Brand color"), opt("custom", "Custom list")];
const MODES = [opt("spectrum", "Spectrum"), opt("analogous", "Analogous"), opt("mono", "Mono")];
const ALIGN = [opt("justify", "Justify"), opt("left", "Left")];
const SIZEBY = [opt("value", "Value"), opt("degree", "Connections")];
const LINKBY = [opt("source", "Source"), opt("target", "Target"), opt("gradient", "Gradient"), opt("neutral", "Neutral")];
const NETBY = [opt("node", "Each node"), opt("community", "Detected community")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: CHART, value: CHART[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 60, options: { minValue: { type: powerbi.visuals.ValidatorType.Min, value: 0 }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: 100 } } });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow];
}
class PaletteCard extends fs.SimpleCard {
    source = new fs.ItemDropdown({ name: "source", displayName: "Colors from", items: SOURCES, value: SOURCES[0] });
    brand = new fs.ColorPicker({ name: "brand", displayName: "Brand color", value: { value: "#2a78d6" } });
    mode = new fs.ItemDropdown({ name: "mode", displayName: "Palette style", items: MODES, value: MODES[0] });
    custom = new fs.TextArea({ name: "custom", displayName: "Custom colors", placeholder: "Hex codes, or paste a theme JSON", value: "" });
    name = "palette"; displayName = "Palette";
    slices = [this.source, this.brand, this.mode, this.custom];
}
export class NodeColorsCard extends fs.SimpleCard {
    name = "nodeColors"; displayName = "Node colors";
    slices: fs.Slice[] = [];
}
class NodesCard extends fs.SimpleCard {
    width = new fs.NumUpDown({ name: "width", displayName: "Node width", value: 12 });
    padding = new fs.NumUpDown({ name: "padding", displayName: "Node spacing", value: 12 });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 3 });
    align = new fs.ItemDropdown({ name: "align", displayName: "Sankey alignment", items: ALIGN, value: ALIGN[0] });
    sizeBy = new fs.ItemDropdown({ name: "sizeBy", displayName: "Network size by", items: SIZEBY, value: SIZEBY[0] });
    maxSize = new fs.NumUpDown({ name: "maxSize", displayName: "Network max node size", value: 16 });
    name = "nodes"; displayName = "Nodes";
    slices = [this.width, this.padding, this.radius, this.align, this.sizeBy, this.maxSize];
}
class LinksCard extends fs.SimpleCard {
    colorBy = new fs.ItemDropdown({ name: "colorBy", displayName: "Color by", items: LINKBY, value: LINKBY[0] });
    opacity = new fs.Slider({ name: "opacity", displayName: "Opacity", value: 38, options: { minValue: { type: powerbi.visuals.ValidatorType.Min, value: 5 }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: 100 } } });
    name = "links"; displayName = "Links";
    slices = [this.colorBy, this.opacity];
}
class LabelsCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Show", value: true });
    topLevelSlice = this.show;
    fontSize = new fs.NumUpDown({ name: "fontSize", displayName: "Text size", value: 11 });
    color = new fs.ColorPicker({ name: "color", displayName: "Color", value: { value: "" } });
    showValues = new fs.ToggleSwitch({ name: "showValues", displayName: "Show values", value: true });
    displayUnits = new fs.AutoDropdown({ name: "displayUnits", displayName: "Display units", value: 0 });
    decimals = new fs.NumUpDown({ name: "decimals", displayName: "Decimal places", value: -1 });
    name = "labels"; displayName = "Labels";
    slices = [this.fontSize, this.color, this.showValues, this.displayUnits, this.decimals];
}
class ChordCard extends fs.SimpleCard {
    padAngle = new fs.NumUpDown({ name: "padAngle", displayName: "Gap between arcs (°)", value: 2.6 });
    arcWidth = new fs.NumUpDown({ name: "arcWidth", displayName: "Arc width", value: 12 });
    ribbonOpacity = new fs.Slider({ name: "ribbonOpacity", displayName: "Ribbon opacity", value: 62, options: { minValue: { type: powerbi.visuals.ValidatorType.Min, value: 5 }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: 100 } } });
    name = "chord"; displayName = "Chord";
    slices = [this.padAngle, this.arcWidth, this.ribbonOpacity];
}
class NetworkCard extends fs.SimpleCard {
    colorBy = new fs.ItemDropdown({ name: "colorBy", displayName: "Color nodes by", items: NETBY, value: NETBY[0] });
    labelCount = new fs.NumUpDown({ name: "labelCount", displayName: "Labels for top N nodes", value: 8 });
    spacing = new fs.Slider({ name: "spacing", displayName: "Spacing", value: 50, options: { minValue: { type: powerbi.visuals.ValidatorType.Min, value: 0 }, maxValue: { type: powerbi.visuals.ValidatorType.Max, value: 100 } } });
    name = "network"; displayName = "Network";
    slices = [this.colorBy, this.labelCount, this.spacing];
}

export class FlowSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    nodeColors = new NodeColorsCard();
    nodes = new NodesCard();
    links = new LinksCard();
    labels = new LabelsCard();
    chord = new ChordCard();
    network = new NetworkCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.nodeColors, this.nodes, this.links, this.labels, this.chord, this.network];

    /** hide settings that do not apply to the current chart type or palette source */
    tidy() {
        const t = String(this.chart.chartType.value.value), src = String(this.palette.source.value.value);
        this.chart.shadow.visible = this.chart.look.value.value !== "flat";
        this.palette.brand.visible = src === "brand";
        this.palette.mode.visible = src === "brand";
        this.palette.custom.visible = src === "custom";
        this.nodes.align.visible = t === "sankey"; this.nodes.width.visible = t === "sankey"; this.nodes.padding.visible = t === "sankey"; this.nodes.radius.visible = t === "sankey";
        this.nodes.sizeBy.visible = t === "network"; this.nodes.maxSize.visible = t === "network";
        this.nodes.visible = t !== "chord";
        this.links.visible = t !== "chord";
        this.chord.visible = t === "chord";
        this.network.visible = t === "network";
    }
}
