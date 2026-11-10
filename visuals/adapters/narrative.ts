"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { GenBIVisual } from "./base";
import { CardSpec, columns } from "./lib/pbi";
import { renderNarrative } from "./lib/charts/narrative";
import { Tokens } from "./lib/theme";
import cards from "./cards.json";

export class Visual extends GenBIVisual {
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, cards as CardSpec[]);
    }

    protected draw(dv: powerbi.DataView | undefined, t: Tokens): void {
        const n = this.props.narrative;
        // Each text measure is one item; a measure may also hold several lines (UNICHAR(10) separated).
        const fromMeasures = columns(dv, "items")
            .map(c => c.values?.[0])
            .filter(v => v !== null && v !== undefined && String(v).trim())
            .flatMap(v => String(v).split(/\r?\n/))
            .filter(line => line.trim());
        const items = fromMeasures.length ? fromMeasures : String(n.lines || "").split(/\r?\n|\\n/);
        const style = ["numbered", "list", "timeline"].includes(n.style) ? n.style : "numbered";
        renderNarrative(this.root, { heading: n.heading, note: n.note, items, style },
            t, { showCard: this.props.card.show });
    }
}
