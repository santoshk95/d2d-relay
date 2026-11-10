/*
 * Format pane for Atlas Hierarchy: treemap, sunburst, circle packing and
 * org chart / tree. Shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, LegendCard } from "./common/cards";

const TYPES = [opt("treemap", "Treemap"), opt("sunburst", "Sunburst"), opt("pack", "Circle packing"), opt("tree", "Org chart / tree")];
const CLICK = [opt("zoom", "Zoom into groups"), opt("select", "Select (cross-filter)")];
const CONTENT = [opt("name", "Name"), opt("nameValue", "Name and value"), opt("namePercent", "Name and percent")];
const COLORBY = [opt("branch", "Top-level branch"), opt("level", "Level"), opt("value", "Color value (gradient)")];
const TILE = [opt("squarify", "Squarified"), opt("binary", "Balanced"), opt("sliceDice", "Slice and dice")];
const ORIENT = [opt("topDown", "Top down"), opt("leftRight", "Left to right")];
const LINKS = [opt("curve", "Curved"), opt("elbow", "Elbow"), opt("straight", "Straight")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 55, options: range(0, 100) });
    depth = new fs.NumUpDown({ name: "depth", displayName: "Levels shown", value: 3, options: range(1, 6) });
    click = new fs.ItemDropdown({ name: "click", displayName: "Clicking a group", items: CLICK, value: CLICK[0] });
    content = new fs.ItemDropdown({ name: "content", displayName: "Labels show", items: CONTENT, value: CONTENT[1] });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.depth, this.click, this.content];
}
class ColorCard extends fs.SimpleCard {
    colorBy = new fs.ItemDropdown({ name: "colorBy", displayName: "Color by", items: COLORBY, value: COLORBY[0] });
    fade = new fs.Slider({ name: "fade", displayName: "Lighten each level (%)", value: 18, options: range(0, 60) });
    lowColor = new fs.ColorPicker({ name: "lowColor", displayName: "Low color", value: { value: "#d64550" } });
    highColor = new fs.ColorPicker({ name: "highColor", displayName: "High color", value: { value: "#1a9e5c" } });
    name = "hcolor"; displayName = "Color rules";
    slices = [this.colorBy, this.fade, this.lowColor, this.highColor];
}
class TreemapCard extends fs.SimpleCard {
    tile = new fs.ItemDropdown({ name: "tile", displayName: "Tiling", items: TILE, value: TILE[0] });
    padding = new fs.NumUpDown({ name: "padding", displayName: "Space between tiles (px)", value: 2, options: range(0, 20) });
    headers = new fs.ToggleSwitch({ name: "headers", displayName: "Group headers", value: true });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 4, options: range(0, 20) });
    name = "treemap"; displayName = "Treemap";
    slices = [this.tile, this.padding, this.headers, this.radius];
}
class SunburstCard extends fs.SimpleCard {
    hole = new fs.Slider({ name: "hole", displayName: "Center hole (%)", value: 28, options: range(0, 70) });
    gap = new fs.NumUpDown({ name: "gap", displayName: "Gap between segments (px)", value: 1.5, options: range(0, 10) });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 3, options: range(0, 12) });
    name = "sunburst"; displayName = "Sunburst";
    slices = [this.hole, this.gap, this.radius];
}
class PackCard extends fs.SimpleCard {
    padding = new fs.NumUpDown({ name: "padding", displayName: "Space between circles (px)", value: 3, options: range(0, 20) });
    name = "pack"; displayName = "Circle packing";
    slices = [this.padding];
}
class TreeCard extends fs.SimpleCard {
    orientation = new fs.ItemDropdown({ name: "orientation", displayName: "Orientation", items: ORIENT, value: ORIENT[0] });
    expanded = new fs.NumUpDown({ name: "expanded", displayName: "Levels open at start", value: 2, options: range(1, 10) });
    links = new fs.ItemDropdown({ name: "links", displayName: "Links", items: LINKS, value: LINKS[1] });
    cardWidth = new fs.NumUpDown({ name: "cardWidth", displayName: "Card width", value: 132, options: range(40, 400) });
    cardHeight = new fs.NumUpDown({ name: "cardHeight", displayName: "Card height", value: 46, options: range(20, 200) });
    badges = new fs.ToggleSwitch({ name: "badges", displayName: "Team size badges", value: true });
    bars = new fs.ToggleSwitch({ name: "bars", displayName: "Value bars", value: true });
    name = "tree"; displayName = "Org chart / tree";
    slices = [this.orientation, this.expanded, this.links, this.cardWidth, this.cardHeight, this.badges, this.bars];
}

export class HierarchySettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    hcolor = new ColorCard();
    treemap = new TreemapCard();
    sunburst = new SunburstCard();
    pack = new PackCard();
    tree = new TreeCard();
    labels = new LabelsCard(true);
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.hcolor, this.treemap, this.sunburst, this.pack, this.tree, this.labels, this.legend];

    get type() { return val(this.chart.chartType); }
    tidy(info: { levels: number; colorValue: boolean; org: boolean }) {
        const t = this.type;
        this.chart.depth.visible = t !== "tree" && info.levels > 1;
        this.hcolor.lowColor.visible = val(this.hcolor.colorBy) === "value";
        this.hcolor.highColor.visible = this.hcolor.lowColor.visible;
        this.treemap.visible = t === "treemap";
        this.treemap.headers.visible = info.levels > 1;
        this.sunburst.visible = t === "sunburst";
        this.pack.visible = t === "pack";
        this.tree.visible = t === "tree";
        this.tree.badges.visible = info.org;
        this.legend.visible = t !== "tree";
    }
}
