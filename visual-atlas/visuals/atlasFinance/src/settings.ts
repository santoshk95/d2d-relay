/*
 * Format pane for Atlas Finance: candlestick, waterfall, ribbon and
 * funnel. Shared cards come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard, ValueAxisCard, GridCard, LegendCard } from "./common/cards";

const TYPES = [opt("candlestick", "Candlestick"), opt("waterfall", "Waterfall"), opt("ribbon", "Ribbon"), opt("funnel", "Funnel")];
const CSTYLE = [opt("candle", "Candles"), opt("ohlc", "OHLC bars"), opt("line", "Close line")];
const FSHAPE = [opt("bars", "Bars"), opt("tapered", "Tapered funnel")];
const FCONTENT = [opt("value", "Value"), opt("first", "Value and % of first"), opt("previous", "Value and % of previous"), opt("percentFirst", "% of first")];
const FCOLORS = [opt("single", "One color"), opt("vary", "A color per stage"), opt("gradient", "Darker by stage")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[1] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 45, options: range(0, 100) });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow];
}
class CandleCard extends fs.SimpleCard {
    style = new fs.ItemDropdown({ name: "style", displayName: "Style", items: CSTYLE, value: CSTYLE[0] });
    upColor = new fs.ColorPicker({ name: "upColor", displayName: "Up color", value: { value: "#1a9e5c" } });
    downColor = new fs.ColorPicker({ name: "downColor", displayName: "Down color", value: { value: "#d64550" } });
    volume = new fs.ToggleSwitch({ name: "volume", displayName: "Volume panel", value: true });
    movingAverage = new fs.NumUpDown({ name: "movingAverage", displayName: "Moving average (periods, 0 = off)", value: 0, options: range(0, 200) });
    maColor = new fs.ColorPicker({ name: "maColor", displayName: "Moving average color", value: { value: "" } });
    minWidth = new fs.NumUpDown({ name: "minWidth", displayName: "Minimum candle width (px)", value: 5, options: range(1, 40) });
    name = "candles"; displayName = "Candlestick";
    slices = [this.style, this.upColor, this.downColor, this.volume, this.movingAverage, this.maColor, this.minWidth];
}
class WaterfallCard extends fs.SimpleCard {
    startTotal = new fs.ToggleSwitch({ name: "startTotal", displayName: "First bar is a total", value: false });
    endTotal = new fs.ToggleSwitch({ name: "endTotal", displayName: "Total bar at the end", value: true });
    endLabel = new fs.TextInput({ name: "endLabel", displayName: "Total label", placeholder: "Total", value: "Total" });
    subtotals = new fs.TextInput({ name: "subtotals", displayName: "Subtotal categories", placeholder: "Gross profit, Operating profit", value: "" });
    incColor = new fs.ColorPicker({ name: "incColor", displayName: "Increase color", value: { value: "#1a9e5c" } });
    decColor = new fs.ColorPicker({ name: "decColor", displayName: "Decrease color", value: { value: "#d64550" } });
    totColor = new fs.ColorPicker({ name: "totColor", displayName: "Total color", value: { value: "" } });
    connectors = new fs.ToggleSwitch({ name: "connectors", displayName: "Connector lines", value: true });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 3, options: range(0, 20) });
    name = "waterfall"; displayName = "Waterfall";
    slices = [this.startTotal, this.endTotal, this.endLabel, this.subtotals, this.incColor, this.decColor, this.totColor, this.connectors, this.radius];
}
class RibbonCard extends fs.SimpleCard {
    opacity = new fs.Slider({ name: "opacity", displayName: "Ribbon opacity (%)", value: 35, options: range(5, 100) });
    columnWidth = new fs.Slider({ name: "columnWidth", displayName: "Column width (%)", value: 45, options: range(10, 90) });
    rank = new fs.ToggleSwitch({ name: "rank", displayName: "Largest on top", value: true });
    name = "ribbon"; displayName = "Ribbon";
    slices = [this.opacity, this.columnWidth, this.rank];
}
class FunnelCard extends fs.SimpleCard {
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Shape", items: FSHAPE, value: FSHAPE[0] });
    content = new fs.ItemDropdown({ name: "content", displayName: "Labels show", items: FCONTENT, value: FCONTENT[1] });
    conversion = new fs.ToggleSwitch({ name: "conversion", displayName: "Conversion rate label", value: true });
    colors = new fs.ItemDropdown({ name: "colors", displayName: "Colors", items: FCOLORS, value: FCOLORS[0] });
    radius = new fs.NumUpDown({ name: "radius", displayName: "Corner radius", value: 4, options: range(0, 20) });
    name = "funnel"; displayName = "Funnel";
    slices = [this.shape, this.content, this.conversion, this.colors, this.radius];
}

export class FinanceSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    candles = new CandleCard();
    waterfall = new WaterfallCard();
    ribbon = new RibbonCard();
    funnel = new FunnelCard();
    labels = new LabelsCard(true);
    categoryAxis = new CategoryAxisCard();
    valueAxis = new ValueAxisCard();
    gridlines = new GridCard();
    legend = new LegendCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.candles, this.waterfall, this.ribbon, this.funnel, this.labels, this.categoryAxis, this.valueAxis, this.gridlines, this.legend];

    get type() { return val(this.chart.chartType); }
    tidy(info: { series: number; volume: boolean }) {
        const t = this.type;
        this.candles.visible = t === "candlestick";
        this.candles.volume.visible = info.volume;
        this.candles.maColor.visible = this.candles.movingAverage.value > 0;
        this.waterfall.visible = t === "waterfall";
        this.waterfall.endLabel.visible = this.waterfall.endTotal.value;
        this.ribbon.visible = t === "ribbon";
        this.funnel.visible = t === "funnel";
        this.valueAxis.visible = t !== "funnel";
        this.gridlines.visible = t !== "funnel";
        this.legend.visible = t === "ribbon" && info.series > 1;
        this.dataColors.visible = this.dataColors.visible && (t === "ribbon" || (t === "funnel" && val(this.funnel.colors) !== "gradient"));
    }
}
