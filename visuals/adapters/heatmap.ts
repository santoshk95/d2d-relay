"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, num, label, firstText, headerFrom } from "./lib/pbi";
import { renderHeatmap } from "./lib/charts/heatmap";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const cat = dv?.categorical?.categories?.[0];
        const vals = dv?.categorical?.values;
        const groups = vals?.grouped ? vals.grouped() : [];
        const names = groups.map(g => g.name);
        // Hours and similar small integers read better zero-padded (08, 10, 12 ...).
        const pad = names.length > 0 && names.every(v => typeof v === "number" && Number.isInteger(v) && v >= 0 && v < 100);
        const cols = names.map(v => (pad ? String(v).padStart(2, "0") : label(v)));
        const rows = cat ? cat.values.map(label) : [];
        const valueCol = (j: number) => groups[j].values.find(v => v.source?.roles?.value);
        const values = rows.map((_, i) => cols.map((__, j) => num(valueCol(j)?.values[i])));
        const keys = rows.map((_, i) => cols.map((__, j) => cat && vals
            ? this.host.createSelectionIdBuilder().withCategory(cat, i).withSeries(vals, groups[j]).createSelectionId()
            : undefined));
        const h = this.props.heatmap;
        const value = valueCol(0);
        renderHeatmap(this.root, {
            rows, cols, values, keys,
            format: value?.source.format,
            indexMode: h.indexMode,
            showValues: h.showAll ? "all" : "peak",
            legend: { low: h.lowLabel, high: h.highLabel },
            names: {
                row: cat?.source.displayName,
                col: dv?.categorical?.values?.source?.displayName,
                value: value?.source.displayName,
            },
        }, t, headerFrom(this.props, firstText(dv, "title")), this.ia);
    }
}
