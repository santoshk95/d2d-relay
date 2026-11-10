"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, columns, num, firstText, headerFrom } from "./lib/pbi";
import { renderFunnel } from "./lib/charts/funnel";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        renderFunnel(this.root, {
            stages: columns(dv, "stages").map(c => ({
                label: c.source.displayName, value: num(c.values[0]), format: c.source.format,
            })),
        }, t, headerFrom(this.props, firstText(dv, "title")), this.ia);
    }
}
