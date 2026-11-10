/*
 * Format pane for Atlas Gauges: cards, multi-row cards, KPIs, gauges,
 * dials, radial bars, liquid fill, bullet charts and a ticker. Shared cards
 * come from common/cards.ts.
 */
"use strict";
import { formattingSettings as fs } from "powerbi-visuals-utils-formattingmodel";
import { opt, range, LOOKS, val, StyleCard, PaletteCard, DataColorsCard, LabelsCard, CategoryAxisCard } from "./common/cards";

const TYPES = [opt("card", "Card"), opt("multirow", "Multi-row card"), opt("kpi", "KPI"), opt("gauge", "Gauge"), opt("dial", "Dial (tachometer)"), opt("radialBar", "Radial bars"), opt("liquid", "Liquid fill"), opt("bullet", "Bullet chart"), opt("ticker", "Ticker")];
const DIR = [opt("higher", "Higher is better"), opt("lower", "Lower is better")];
const TSTYLE = [opt("area", "Area"), opt("line", "Line"), opt("column", "Columns")];
const ANGLE = [opt("180", "Half circle"), opt("240", "Three quarters"), opt("270", "Open ring")];
const LSHAPE = [opt("circle", "Circle"), opt("square", "Rounded square")];
const ORIENT = [opt("horizontal", "Horizontal"), opt("vertical", "Vertical")];
const TDIR = [opt("left", "Scroll left"), opt("up", "Scroll up")];

class ChartCard extends fs.SimpleCard {
    chartType = new fs.ItemDropdown({ name: "chartType", displayName: "Chart type", items: TYPES, value: TYPES[0] });
    look = new fs.ItemDropdown({ name: "look", displayName: "Look", items: LOOKS, value: LOOKS[1] });
    shadow = new fs.Slider({ name: "shadow", displayName: "Shadow strength", value: 45, options: range(0, 100) });
    columns = new fs.NumUpDown({ name: "columns", displayName: "Columns (0 = auto)", value: 0, options: range(0, 12) });
    accent = new fs.ToggleSwitch({ name: "accent", displayName: "Accent bar", value: true });
    name = "chart"; displayName = "Chart";
    slices = [this.chartType, this.look, this.shadow, this.columns, this.accent];
}
class StatusCard extends fs.SimpleCard {
    direction = new fs.ItemDropdown({ name: "direction", displayName: "Direction", items: DIR, value: DIR[0] });
    tolerance = new fs.NumUpDown({ name: "tolerance", displayName: "Amber within (% of target)", value: 5, options: range(0, 100) });
    goodColor = new fs.ColorPicker({ name: "goodColor", displayName: "On target", value: { value: "#1a9e5c" } });
    warnColor = new fs.ColorPicker({ name: "warnColor", displayName: "Close", value: { value: "#d9a400" } });
    badColor = new fs.ColorPicker({ name: "badColor", displayName: "Off target", value: { value: "#d64550" } });
    colorValue = new fs.ToggleSwitch({ name: "colorValue", displayName: "Color the value by status", value: false });
    showTarget = new fs.ToggleSwitch({ name: "showTarget", displayName: "Show target", value: true });
    name = "status"; displayName = "Target and status";
    slices = [this.direction, this.tolerance, this.goodColor, this.warnColor, this.badColor, this.colorValue, this.showTarget];
}
class TrendCard extends fs.SimpleCard {
    show = new fs.ToggleSwitch({ name: "show", displayName: "Trend", value: true });
    topLevelSlice = this.show;
    style = new fs.ItemDropdown({ name: "style", displayName: "Style", items: TSTYLE, value: TSTYLE[0] });
    name = "trend"; displayName = "Trend";
    slices = [this.style];
}
class ScaleCard extends fs.SimpleCard {
    min = new fs.TextInput({ name: "min", displayName: "Minimum", placeholder: "Auto (0)", value: "" });
    max = new fs.TextInput({ name: "max", displayName: "Maximum", placeholder: "Auto", value: "" });
    angle = new fs.ItemDropdown({ name: "angle", displayName: "Arc", items: ANGLE, value: ANGLE[0] });
    width = new fs.Slider({ name: "width", displayName: "Arc width (%)", value: 22, options: range(4, 60) });
    band1 = new fs.Slider({ name: "band1", displayName: "Band 1 at (% of scale)", value: 50, options: range(0, 100) });
    band2 = new fs.Slider({ name: "band2", displayName: "Band 2 at (% of scale)", value: 80, options: range(0, 100) });
    needle = new fs.ToggleSwitch({ name: "needle", displayName: "Needle", value: true });
    ticks = new fs.ToggleSwitch({ name: "ticks", displayName: "Tick labels", value: true });
    name = "scale"; displayName = "Scale and bands";
    slices = [this.min, this.max, this.angle, this.width, this.band1, this.band2, this.needle, this.ticks];
}
class LiquidCard extends fs.SimpleCard {
    shape = new fs.ItemDropdown({ name: "shape", displayName: "Shape", items: LSHAPE, value: LSHAPE[0] });
    wave = new fs.Slider({ name: "wave", displayName: "Wave height (%)", value: 6, options: range(0, 20) });
    name = "liquid"; displayName = "Liquid fill";
    slices = [this.shape, this.wave];
}
class BulletCard extends fs.SimpleCard {
    orientation = new fs.ItemDropdown({ name: "orientation", displayName: "Orientation", items: ORIENT, value: ORIENT[0] });
    name = "bullet"; displayName = "Bullet chart";
    slices = [this.orientation];
}
class TickerCard extends fs.SimpleCard {
    speed = new fs.NumUpDown({ name: "speed", displayName: "Seconds per loop", value: 30, options: range(3, 600) });
    direction = new fs.ItemDropdown({ name: "direction", displayName: "Direction", items: TDIR, value: TDIR[0] });
    name = "ticker"; displayName = "Ticker";
    slices = [this.speed, this.direction];
}

export class GaugesSettings extends fs.Model {
    chart = new ChartCard();
    style = new StyleCard();
    palette = new PaletteCard();
    dataColors = new DataColorsCard();
    status = new StatusCard();
    trend = new TrendCard();
    scale = new ScaleCard();
    liquid = new LiquidCard();
    bullet = new BulletCard();
    ticker = new TickerCard();
    labels = new LabelsCard(true);
    categoryAxis = new CategoryAxisCard();
    cards: fs.Cards[] = [this.chart, this.style, this.palette, this.dataColors, this.status, this.trend, this.scale, this.liquid, this.bullet, this.ticker, this.labels, this.categoryAxis];

    get type() { return val(this.chart.chartType); }
    tidy(info: { items: number; target: boolean; trend: boolean; bands: boolean }) {
        const t = this.type, round = ["gauge", "dial", "radialBar", "liquid"].includes(t);
        this.chart.columns.visible = info.items > 1 && !["multirow", "ticker", "radialBar", "bullet"].includes(t);
        this.chart.accent.visible = t === "card" || t === "multirow";
        this.status.visible = info.target || t === "dial";
        this.trend.visible = t === "kpi" && info.trend;
        this.scale.visible = round || t === "bullet";
        this.scale.angle.visible = t === "gauge" || t === "dial";
        this.scale.width.visible = t === "gauge" || t === "dial" || t === "radialBar";
        this.scale.band1.visible = (t === "dial" || t === "bullet") && !info.bands; this.scale.band2.visible = this.scale.band1.visible;
        this.scale.needle.visible = t === "dial";
        this.scale.ticks.visible = t === "gauge" || t === "dial";
        this.liquid.visible = t === "liquid";
        this.bullet.visible = t === "bullet";
        this.ticker.visible = t === "ticker";
    }
}
