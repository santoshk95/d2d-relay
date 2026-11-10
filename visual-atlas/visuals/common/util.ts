/*
 * Shared helpers: palette resolution (report theme, brand generator or
 * pasted colors), value formatting and the landing page.
 */
import powerbi from "powerbi-visuals-api";
import { valueFormatter } from "powerbi-visuals-utils-formattingutils";
import { adapt, generate, parseColors, isHex, normHex, luminance, PaletteMode } from "./color";
import { el, clear } from "./look";

export interface PaletteOptions { source: string; brand: string; mode: string; custom: string; }

/** returns a function that gives the color for an item (stable by key) */
export function colorer(p: PaletteOptions, host: powerbi.extensibility.visual.IVisualHost, dark: boolean): (key: string, index: number) => string {
    const cp = host.colorPalette;
    if (cp.isHighContrast) { const fg = cp.foreground.value; return () => fg; }
    if (p.source === "brand" || p.source === "custom") {
        let pal = p.source === "custom" ? parseColors(p.custom) : [];
        const seed = isHex(p.brand) ? normHex(p.brand) : "#2a78d6";
        if (pal.length < 12) pal = pal.concat(generate(pal[0] || seed, (["spectrum", "analogous", "mono"].includes(p.mode) ? p.mode : "spectrum") as PaletteMode, 12).slice(pal.length ? 1 : 0)).slice(0, Math.max(12, pal.length));
        const ready = pal.map(c => (p.source === "custom" && !dark ? c : adapt(c, dark)));
        return (_k, i) => ready[((i % ready.length) + ready.length) % ready.length];
    }
    /* theme colors too are pulled into a readable range on a dark background */
    return (k) => { const c = cp.getColor(k).value; return dark && isHex(c) ? adapt(normHex(c), true) : c; };
}
/** is the report background dark? */
export function isDark(host: powerbi.extensibility.visual.IVisualHost): boolean {
    const bg = host.colorPalette.background && host.colorPalette.background.value;
    return !!bg && isHex(bg) && luminance(normHex(bg)) < 0.25;
}
/** Power BI value formatter honoring the column's format string, display units and decimals */
export function formatter(format: string | undefined, units: number, decimals: number | null | undefined, sample: number, culture?: string): (v: number) => string {
    const f = valueFormatter.create({ format: format || "#,0.##", value: units === 0 ? Math.abs(sample) || 1 : units, precision: decimals == null || decimals < 0 ? undefined : decimals, allowFormatBeautification: true, cultureSelector: culture });
    return (v: number) => (v == null || isNaN(v) ? "" : f.format(v));
}
/** display unit Power BI's Auto setting would pick for a value */
export function autoUnit(v: number): number { const a = Math.abs(v); return a >= 1e12 ? 1e12 : a >= 1e9 ? 1e9 : a >= 1e6 ? 1e6 : a >= 1e3 ? 1e3 : 1; }
const fewest = (x: number, cap: number) => { let p = cap; const r = Number(x.toFixed(cap)); while (p > 0 && Math.abs(r - Number(r.toFixed(p - 1))) < 1e-9) p--; return p; };
/** data labels: with Auto decimals, about three significant digits and no trailing zeros ($4.77M, $209K, 48K) */
export function labelFormatter(format: string | undefined, units: number, decimals: number | null | undefined, sample: number, culture?: string): (v: number) => string {
    if (decimals != null && decimals >= 0) return formatter(format, units, decimals, sample, culture);
    const auto = units === 0, unit = auto ? autoUnit(sample) : Math.max(1, units);
    if (unit === 1) return formatter(format, 1, null, sample, culture);
    const cache = new Map<string, (v: number) => string>(), plain = formatter(format, 1, null, sample, culture);
    return (v: number) => {
        if (v == null || isNaN(v)) return "";
        /* Auto units: a value smaller than the visual's unit keeps its own ("90", not "0.09K") */
        const u = auto ? Math.min(unit, autoUnit(v)) : unit;
        if (u === 1) return plain(v);
        const sv = Math.abs(v) / u, p = fewest(sv, sv >= 100 ? 0 : sv >= 10 ? 1 : 2), key = u + ":" + p;
        let f = cache.get(key); if (!f) { f = formatter(format, u, p, sample, culture); cache.set(key, f); }
        return f(v);
    };
}
/** axis ticks: one unit for the whole axis and only the decimals the step needs */
export function axisFormatter(format: string | undefined, units: number, decimals: number | null | undefined, ticks: number[], culture?: string): (v: number) => string {
    const top = Math.max(0, ...ticks.map(Math.abs));
    if (decimals != null && decimals >= 0) return formatter(format, units, decimals, top, culture);
    /* zero needs no display unit or decimals: "$0", not "$0K" */
    const auto = axisAuto(format, units, ticks, top, culture), zero = formatter(format, 1, 0, 0, culture)(0);
    return (v: number) => (v === 0 ? zero : auto(v));
}
function axisAuto(format: string | undefined, units: number, ticks: number[], top: number, culture?: string): (v: number) => string {
    const unit = units === 0 ? autoUnit(top) : Math.max(1, units), step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : top || 1;
    /* a percent format shows the value × 100, so a 0.01 step needs no decimals */
    const shown = format && /%/.test(format.replace(/\\./g, "").replace(/"[^"]*"/g, "")) ? step * 100 : step;
    const cap = Math.max(0, Math.min(4, Math.ceil(-Math.log10(shown / unit) - 1e-9)));
    if (unit === 1 && cap === 0) return formatter(format, 1, null, top, culture);
    const cache = new Map<number, (v: number) => string>();
    return (v: number) => { const p = fewest(Math.abs(v) / unit, cap); let f = cache.get(p); if (!f) { f = formatter(format, unit, p, top, culture); cache.set(p, f); } return f(v); };
}
/** formatter for category and series names (dates, numbers or text), blanks shown as (Blank) */
export function nameFormatter(format: string | undefined, culture?: string): (v: powerbi.PrimitiveValue) => string {
    const f = valueFormatter.create({ format, cultureSelector: culture });
    return (v: powerbi.PrimitiveValue) => (v == null || v === "" ? "(Blank)" : String(f.format(v)));
}
/** friendly start screen shown when the required fields are missing */
export function landing(root: HTMLElement, title: string, lines: string[]) {
    clear(root);
    const box = document.createElement("div"); box.className = "atl-landing";
    const h = document.createElement("div"); h.className = "atl-landing-t"; h.textContent = title; box.appendChild(h);
    lines.forEach(t => { const p = document.createElement("div"); p.textContent = t; box.appendChild(p); });
    root.appendChild(box);
}
export { el };
