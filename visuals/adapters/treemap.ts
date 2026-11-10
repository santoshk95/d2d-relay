"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, column, num, categoryKeys, firstText, headerFrom } from "./lib/pbi";
import { renderTreemap } from "./lib/charts/treemap";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const { labels, keys } = categoryKeys(this.host, dv);
        const size = column(dv, "size"), color = column(dv, "color");
        renderTreemap(this.root, {
            items: labels.map((label, i) => ({
                label, key: keys[i], size: num(size?.values[i]), color: color ? num(color.values[i]) : null,
            })),
            sizeFormat: size?.source.format,
            colorFormat: color?.source.format,
            names: { size: size?.source.displayName, color: color?.source.displayName },
        }, t, headerFrom(this.props, firstText(dv, "title")), this.ia);
    }
}
