"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, column, nums } from "./lib/pbi";
import { renderKpi } from "./lib/charts/kpi";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const n = dv?.categorical?.categories?.[0]?.values.length ?? column(dv, "value")?.values.length ?? 0;
        const first = (role: string) => {
            const c = column(dv, role);
            return c ? nums(c, Math.max(1, n)).find(v => v !== null) ?? null : undefined;
        };
        const value = column(dv, "value");
        const trend = column(dv, "trend");
        const k = this.props.kpi;
        renderKpi(this.root, {
            label: k.label || value?.source.displayName || "",
            value: (first("value") ?? null) as number | null,
            valueFormat: value?.source.format,
            target: first("target"),
            comparison: first("comparison"),
            spark: trend ? nums(trend, n) : undefined,
            lowerIsBetter: k.lowerIsBetter,
            signedValue: k.signedValue,
            comparisonLabel: k.comparisonLabel,
            targetLabel: k.targetLabel,
        }, t, { showCard: this.props.card.show });
    }
}
