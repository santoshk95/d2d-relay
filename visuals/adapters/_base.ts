// Shared base for every Gen BI Power BI visual (copied into each package as src/base.ts).
import powerbi from "powerbi-visuals-api";
import { CardSpec, PbiInteractions, Props, readProps, tokensFrom, formattingModel } from "./lib/pbi";
import { Tokens } from "./lib/theme";

import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import IVisual = powerbi.extensibility.visual.IVisual;
import IVisualHost = powerbi.extensibility.visual.IVisualHost;
import DataView = powerbi.DataView;

export abstract class GenBIVisual implements IVisual {
    protected root: HTMLElement;
    protected host: IVisualHost;
    protected ia: PbiInteractions;
    protected props: Props = {};
    private last?: VisualUpdateOptions;

    constructor(options: VisualConstructorOptions, private cards: CardSpec[]) {
        this.root = options.element;
        this.host = options.host;
        this.ia = new PbiInteractions(this.host, this.root, () => this.redraw());
    }

    public update(options: VisualUpdateOptions): void {
        this.last = options;
        this.redraw();
    }

    private redraw(): void {
        const dv = this.last?.dataViews?.[0];
        this.props = readProps(dv, this.cards);
        try {
            this.draw(dv, tokensFrom(this.props));
        } catch (e) {
            this.root.textContent = `Gen BI visual error: ${(e as Error).message}`;
        }
    }

    protected abstract draw(dv: DataView | undefined, t: Tokens): void;

    public getFormattingModel(): powerbi.visuals.FormattingModel {
        return formattingModel(this.cards, this.props);
    }
}
