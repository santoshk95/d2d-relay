"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, column, num, nums, categoryKeys, firstText, headerFrom } from "./lib/pbi";
import { renderQuadrant } from "./lib/charts/quadrant";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const { labels, keys } = categoryKeys(this.host, dv);
        const n = labels.length;
        const x = column(dv, "x"), y = column(dv, "y"), size = column(dv, "size");
        const ref = (role: string) => nums(column(dv, role), n).find(v => v !== null) ?? null;
        const q = this.props.quadrant;
        renderQuadrant(this.root, {
            points: labels.map((label, i) => ({
                label, key: keys[i], x: num(x?.values[i]), y: num(y?.values[i]), size: size ? num(size.values[i]) : null,
            })),
            xRef: ref("xRef"),
            yRef: ref("yRef"),
            xFormat: x?.source.format,
            yFormat: y?.source.format,
            sizeFormat: size?.source.format,
            names: { x: x?.source.displayName, y: y?.source.displayName, size: size?.source.displayName },
            corners: { topLeft: q.topLeft, topRight: q.topRight, bottomLeft: q.bottomLeft, bottomRight: q.bottomRight },
            labelTop: Number(q.labelTop),
            labelBottom: Number(q.labelBottom),
        }, t, headerFrom(this.props, firstText(dv, "title")), this.ia);
    }
}
