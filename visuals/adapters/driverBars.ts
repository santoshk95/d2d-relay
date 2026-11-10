"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, column, num, categoryKeys, firstText, headerFrom } from "./lib/pbi";
import { renderBars } from "./lib/charts/bars";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const { labels, keys } = categoryKeys(this.host, dv);
        const value = column(dv, "value");
        renderBars(this.root, {
            rows: labels.map((label, i) => ({ label, value: num(value?.values[i]), key: keys[i] })),
            format: value?.source.format,
            signed: this.props.bars.signed,
            sort: this.props.bars.sortDescending ? "desc" : "none",
        }, t, headerFrom(this.props, firstText(dv, "title")), this.ia);
    }
}
