// Number formatting shared by every Gen BI visual (Power BI and the HTML prototype).
// Understands the measure format strings the generator writes, e.g. "\$#,0", "0.0%",
// "+0.0%;-0.0%;0.0%", "#,0", "0.0\" wks\"", and scaled ones like "\$#,0.0,,\"M\"" (millions).

export interface NumFormat {
    kind: "currency" | "percent" | "number";
    prefix: string;     // currency symbol
    suffix: string;     // literal unit, e.g. " wks" or "M"
    decimals: number;
    scale: number;      // 1, or 1e3 / 1e6 / 1e9 when the format divides the value itself ("#,0.0,," = millions)
}

const MINUS = "−";

export function parseFormat(fmt?: string | null): NumFormat {
    const section = (fmt || "").split(";")[0];
    let prefix = "";
    let suffix = "";
    const trimmed = section.trim();
    const literals = trimmed.match(/"[^"]*"/g) || [];
    if (literals.length && trimmed.endsWith(literals[literals.length - 1])) {
        suffix = literals[literals.length - 1].slice(1, -1);
    }
    const core = trimmed.replace(/"[^"]*"/g, "").replace(/\\/g, "");
    const cur = core.match(/[$€£¥₹]/);
    if (cur) prefix = cur[0];
    const kind = core.includes("%") ? "percent" : prefix ? "currency" : "number";
    const dec = core.match(/\.(0+)/);
    // commas right after the last digit placeholder divide by 1,000 each (Excel / Power BI format strings)
    const scaling = core.replace(/[$€£¥₹%\s]/g, "").match(/[0#](?:\.[0#]+)?(,+)$/);
    return { kind, prefix, suffix, decimals: dec ? dec[1].length : 0, scale: scaling ? Math.pow(1000, scaling[1].length) : 1 };
}

function group(v: number, decimals: number): string {
    return v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function sign(v: number, signed: boolean): string {
    if (v < 0) return MINUS;
    return signed && v > 0 ? "+" : "";
}

export interface FormatOptions {
    compact?: boolean;      // 412.6M, 612K
    signed?: boolean;       // +6.4%
    decimals?: number;      // override
}

/** Format a value with a measure format string ("–" for blanks). */
export function fmt(v: number | null | undefined, nf: NumFormat, o: FormatOptions = {}): string {
    if (v === null || v === undefined || isNaN(v)) return "–";
    const s = sign(v, !!o.signed);
    const a = Math.abs(v);
    if (nf.kind === "percent") {
        const d = o.decimals ?? (nf.decimals || (a * 100 >= 100 ? 0 : 1));
        return `${s}${group(a * 100, d)}%`;
    }
    if (nf.scale > 1) {     // the format already picked its unit (millions + "M"): never shorten on top of it
        const d = o.decimals ?? nf.decimals;
        return `${s}${nf.prefix}${group(a / nf.scale, d)}${nf.suffix}`;
    }
    if (o.compact && a >= 1e4) {
        const [div, unit] = a >= 1e9 ? [1e9, "B"] : a >= 1e6 ? [1e6, "M"] : [1e3, "K"];
        const u = a / div;
        const d = o.decimals ?? (u < 10 ? 2 : u < 100 ? 1 : unit === "K" ? 0 : 1);
        return `${s}${nf.prefix}${group(u, d)}${unit}${nf.suffix}`;
    }
    const d = o.decimals ?? nf.decimals;
    return `${s}${nf.prefix}${group(a, d)}${nf.suffix}`;
}

/** Fewest decimals (up to 2) that show a tick step exactly: 500 -> 0, 2.5 -> 1, 0.25 -> 2. */
function stepDecimals(step: number): number {
    for (let d = 0; d < 2; d++) {
        const x = step * Math.pow(10, d);
        if (Math.abs(x - Math.round(x)) < 1e-9) return d;
    }
    return 2;
}

/** Short axis tick labels: compact, no more decimals than needed to tell ticks apart. */
export function fmtTick(v: number, nf: NumFormat, step: number, signed = false): string {
    if (nf.kind === "percent") {
        const d = step * 100 >= 1 ? 0 : step * 100 >= 0.1 ? 1 : 2;
        return fmt(v, nf, { decimals: d, signed });
    }
    if (nf.scale > 1) return fmt(v, nf, { decimals: stepDecimals(step / nf.scale), signed });
    const a = Math.abs(v);
    if (a >= 1e4 || step >= 1e4) {
        const div = Math.max(a, step) >= 1e9 ? 1e9 : Math.max(a, step) >= 1e6 ? 1e6 : 1e3;
        const d = step / div >= 1 ? 0 : step / div >= 0.1 ? 1 : 2;
        return fmt(v, nf, { compact: true, decimals: d, signed });
    }
    return fmt(v, nf, { decimals: step >= 1 ? 0 : 1, signed });
}

/** Difference text used by KPI cards: percent formats -> points, unit formats (" wks") -> absolute, else relative %.
 * A scaled format's suffix ("M") is a size, not a unit, so those compare relatively like currency. */
export function deltaText(a: number, b: number, nf: NumFormat): { text: string; diff: number } {
    if (nf.kind === "percent") {
        const d = (a - b) * 100;
        return { text: `${sign(d, true)}${group(Math.abs(d), 1)} pts`, diff: d };
    }
    if (nf.suffix.trim() && nf.scale === 1) {
        const d = a - b;
        return { text: fmt(d, nf, { signed: true, decimals: Math.max(1, nf.decimals) }), diff: d };
    }
    const d = b ? a / b - 1 : 0;
    return { text: `${sign(d, true)}${group(Math.abs(d) * 100, 1)}%`, diff: d };
}

export function niceTicks(min: number, max: number, count = 5): number[] {
    if (!isFinite(min) || !isFinite(max)) return [0, 1];
    if (min === max) {
        const pad = Math.abs(min) * 0.1 || 1;
        min -= pad;
        max += pad;
    }
    const raw = (max - min) / Math.max(1, count - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    const start = Math.floor(min / step) * step;
    const ticks: number[] = [];
    for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Math.round(v / step) * step);
    if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
    return ticks;
}
