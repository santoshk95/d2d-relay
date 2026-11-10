/*
 * Format pane for Atlas Compare. Every variation the gallery shows for
 * lollipops, dot plots, dumbbells, slopes, bumps, tornados and radars is
 * a setting; the shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard, LegendCard } from "./common/cards";

const TYPES = [opt("lollipop", "Lollipop"), opt("dot", "Dot plot"), opt("dumbbell", "Dumbbell"), opt("slope", "Slope"), opt("bump", "Bump"), opt("tornado", "Tornado"), opt("radar", "Radar")];
const ORIENT = [opt("horizontal", "Horizontal"), opt("vertical", "Vertical")];
const SORT = [opt("none", "Data order"), opt("valueDesc", "Value, high to low"), opt("valueAsc", "Value, low to high"), opt("changeDesc", "Change, largest first"), opt("name", "Name")];
const SHAPES = [opt("circle", "Circle"), opt("square", "Square"), opt("diamond", "Diamond")];
const COLORBY = [opt("series", "Series"), opt("category", "Each category"), opt("sign", "Positive and negative")];
const CONNECT = [opt("neutral", "Neutral"), opt("direction", "Up and down colors")];
const TMODE = [opt("mirror", "Mirror (pyramid)"), opt("base", "Around a base value")];
const GRID = [opt("polygon", "Polygon"), opt("circle", "Circle")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 55, options: range(0, 100) });
    orientation = new fs.ItemDropdown({ name: "orientation", displayName: "Orientation", items: ORIENT, value: ORIENT[0] });
    sort = new fs.ItemDropdown({ name: "sort", displayName: "Sort", items: SORT, value: SORT[0] });
    focus = new fs.TextInput({ name: "focus", displayName: "Focus on (name)", placeholder: "Gray out everything else", value: "" });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.orientation, this.sort, this.focus];
}
class MarksCard extends fs.SimpleCard {
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Marker shape", items: SHAPES, value: SHAPES[0] });
    size = new fs.NumUpDown({ name: "size", displayName: "Marker size", value: 6, options: range(1, 30) });
    stemWidth = new fs.NumUpDown({ name: "stemWidth", displayName: "Stem width", value: 2, options: range(0, 20) });
    lineWidth = new fs.NumUpDown({ name: "lineWidth", displayName: "Line width", value: 2.5, options: range(0.5, 16) });
    smooth = new fs.ToggleSwitch({ name: "smooth", displayName: "Smooth lines", value: true });
    colorBy = new fs.ItemDropdown({ name: "colorBy", displayName: "Color by", items: COLORBY, value: COLORBY[0] });
    connector = new fs.ItemDropdown({ name: "connector", displayName: "Connector", items: CONNECT, value: CONNECT[1] });
    upColor = new fs.ColorPicker({ name: "upColor", displayName: "Up / positive color", value: { value: "#1a9e5c" } });
    downColor = new fs.ColorPicker({ name: "downColor", displayName: "Down / negative color", value: { value: "#d64550" } });
    name = "marks"; displayName = "Markers and lines";
    slices = [this.shape, this.size, this.stemWidth, this.lineWidth, this.smooth, this.colorBy, this.connector, this.upColor, this.downColor];
}
class TornadoCard extends fs.SimpleCard {
    mode = new fs.ItemDropdown({ name: "mode", displayName: "Layout", items: TMODE, value: TMODE[0] });
    base = new fs.NumUpDown({ name: "base", displayName: "Base value", value: 0 });
    center = new fs.ToggleSwitch({ name: "center", displayName: "Names in the middle", value: true });
    name = "tornado"; displayName = "Tornado";
    slices = [this.mode, this.base, this.center];
}
class RadarCard extends fs.SimpleCard {
    grid = new fs.ItemDropdown({ name: "grid", displayName: "Grid shape", items: GRID, value: GRID[0] });
    levels = new fs.NumUpDown({ name: "levels", displayName: "Grid levels", value: 4, options: range(1, 10) });
    fill = new fs.ToggleSwitch({ name: "fill", displayName: "Fill areas", value: true });
    fillOpacity = new fs.Slider({ name: "fillOpacity", displayName: "Fill opacity (%)", value: 22, options: range(0, 100) });
    max = new fs.TextInput({ name: "max", displayName: "Maximum", placeholder: "Auto", value: "" });
    multiples = new fs.ToggleSwitch({ name: "multiples", displayName: "One radar per series", value: false });
    name = "radar"; displayName = "Radar";
    slices = [this.grid, this.levels, this.fill, this.fillOpacity, this.max, this.multiples];
}

export class CompareSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    marks = new MarksCard();
    tornado = new TornadoCard();
    radar = new RadarCard();
    labels = new LabelsCard();
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.marks, this.tornado, this.radar, this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend];

    get type() { return val(this.chart.chartType); }
    tidy(info: { series: number }) {
        const t = this.type, list = ["lollipop", "dot", "dumbbell", "tornado"].includes(t);
        this.chart.orientation.visible = ["lollipop", "dot", "dumbbell"].includes(t);
        this.chart.sort.visible = list || t === "slope";
        this.chart.focus.visible = ["slope", "bump", "radar", "dot"].includes(t);
        this.marks.shape.visible = t !== "tornado";
        this.marks.size.visible = t !== "tornado";
        this.marks.stemWidth.visible = t === "lollipop";
        this.marks.lineWidth.visible = ["dumbbell", "slope", "bump", "radar", "dot"].includes(t);
        this.marks.smooth.visible = t === "bump";
        this.marks.colorBy.visible = t === "lollipop" && info.series <= 1;
        this.marks.connector.visible = t === "dumbbell" && info.series === 2;
        const signs = (t === "lollipop" && val(this.marks.colorBy) === "sign") || (t === "dumbbell" && val(this.marks.connector) === "direction") || t === "slope";
        this.marks.upColor.visible = signs; this.marks.downColor.visible = signs;
        this.marks.visible = true;
        this.tornado.visible = t === "tornado";
        this.tornado.base.visible = val(this.tornado.mode) === "base";
        this.radar.visible = t === "radar";
        this.radar.fillOpacity.visible = this.radar.fill.value;
        this.valueAxis.visible = list;
        this.gridlines.visible = t !== "slope";
        this.legend.visible = info.series > 1 || t === "tornado";
    }
}
