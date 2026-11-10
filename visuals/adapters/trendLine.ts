"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, column, nums, categoryKeys, firstText, headerFrom } from "./lib/pbi";
import { renderTrend } from "./lib/charts/trend";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const { labels, keys } = categoryKeys(this.host, dv);
        const n = labels.length;
        const actual = column(dv, "actual");
        const target = column(dv, "target");
        const comparison = column(dv, "comparison");
        const annotation = column(dv, "annotation");
        const p = this.props.trend;
        renderTrend(this.root, {
            categories: labels,
            keys,
            actual: nums(actual, n),
            target: target ? nums(target, n) : undefined,
            comparison: comparison ? nums(comparison, n) : undefined,
            annotations: annotation ? labels.map((_, i) => {
                const v = annotation.values[i];
                return v === null || v === undefined || v === "" ? null : String(v);
            }) : undefined,
            format: actual?.source.format,
            labels: { actual: p.actualLabel, target: p.targetLabel, comparison: p.comparisonLabel },
            showAllAnnotations: p.showAllAnnotations,
        }, t, headerFrom(this.props, firstText(dv, "title")), this.ia);
    }
}
