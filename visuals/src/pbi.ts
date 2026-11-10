// Power BI glue shared by the 8 Gen BI visuals: settings, data roles, selection and tooltips.
import powerbi from "powerbi-visuals-api";
import { Tokens, DEFAULT_TOKENS, Interactions, Header } from "./theme";

type DataView = powerbi.DataView;
type DataViewValueColumn = powerbi.DataViewValueColumn;
type ISelectionId = powerbi.visuals.ISelectionId;
type IVisualHost = powerbi.extensibility.visual.IVisualHost;
type ISelectionManager = powerbi.extensibility.ISelectionManager;

export interface PropSpec { name: string; displayName: string; type: "text" | "color" | "bool" | "number"; default: unknown; }
export interface CardSpec { object: string; displayName: string; props: PropSpec[]; }
export type Props = Record<string, Record<string, any>>;

/** Current formatting values (report.json objects) merged over the defaults. */
export function readProps(dv: DataView | undefined, cards: CardSpec[]): Props {
    const objects: any = dv?.metadata?.objects || {};
    const out: Props = {};
    for (const card of cards) {
        out[card.object] = {};
        for (const p of card.props) {
            let v = objects[card.object]?.[p.name];
            if (p.type === "color") v = v?.solid?.color;
            out[card.object][p.name] = v === undefined || v === null ? p.default : v;
        }
    }
    return out;
}

export function tokensFrom(p: Props): Tokens {
    const c = p.colors || {};
    return { ...DEFAULT_TOKENS, ...Object.fromEntries(Object.entries(c).filter(([, v]) => !!v)) } as Tokens;
}

export function headerFrom(p: Props, dynamicTitle?: string | null): Header {
    return {
        title: dynamicTitle || p.header?.title || undefined,
        subtitle: p.header?.subtitle || undefined,
        showCard: p.card?.show !== false,
    };
}

/** Format pane model built from the same card specs as capabilities.json. */
export function formattingModel(cards: CardSpec[], p: Props): powerbi.visuals.FormattingModel {
    const control = (card: CardSpec, prop: PropSpec): any => {
        const descriptor = { objectName: card.object, propertyName: prop.name };
        const value = p[card.object]?.[prop.name];
        switch (prop.type) {
            case "color": return { type: "ColorPicker", properties: { descriptor, value: { value } } };
            case "bool": return { type: "ToggleSwitch", properties: { descriptor, value: !!value } };
            case "number": return { type: "NumUpDown", properties: { descriptor, value: Number(value) } };
            default: return { type: "TextInput", properties: { descriptor, value: String(value ?? ""), placeholder: prop.displayName } };
        }
    };
    return {
        cards: cards.map(card => ({
            displayName: card.displayName,
            uid: `${card.object}_card`,
            groups: [{
                displayName: undefined,
                uid: `${card.object}_group`,
                slices: card.props.map(prop => ({
                    uid: `${card.object}_${prop.name}`,
                    displayName: prop.displayName,
                    control: control(card, prop),
                })),
            }],
        })),
    } as any;
}

// ---------- data roles ----------
export function columns(dv: DataView | undefined, role: string): DataViewValueColumn[] {
    return (dv?.categorical?.values || []).filter(v => v.source?.roles?.[role]);
}

export function column(dv: DataView | undefined, role: string): DataViewValueColumn | undefined {
    return columns(dv, role)[0];
}

export function num(v: unknown): number | null {
    if (v === null || v === undefined || v === "") return null;
    const n = typeof v === "number" ? v : Number(v);
    return isFinite(n) ? n : null;
}

export function nums(c: DataViewValueColumn | undefined, n: number): (number | null)[] {
    return Array.from({ length: n }, (_, i) => num(c?.values?.[i]));
}

/** First non-blank text in a role (dynamic titles / annotations are written as text measures). */
export function firstText(dv: DataView | undefined, role: string): string | null {
    for (const c of columns(dv, role)) {
        for (const v of c.values || []) if (v !== null && v !== undefined && String(v).trim()) return String(v);
    }
    return null;
}

export function label(v: unknown): string {
    if (v instanceof Date) return v.toLocaleDateString("en-US", { month: "short", year: "numeric" });
    return v === null || v === undefined ? "(Blank)" : String(v);
}

export function categoryKeys(host: IVisualHost, dv: DataView | undefined): { labels: string[]; keys: ISelectionId[] } {
    const cat = dv?.categorical?.categories?.[0];
    if (!cat) return { labels: [], keys: [] };
    return {
        labels: cat.values.map(label),
        keys: cat.values.map((_, i) => host.createSelectionIdBuilder().withCategory(cat, i).createSelectionId()),
    };
}

// ---------- interactions ----------
export class PbiInteractions implements Interactions {
    private sm: ISelectionManager;
    private shown = false;

    constructor(private host: IVisualHost, private root: HTMLElement, private rerender: () => void) {
        this.sm = host.createSelectionManager();
        this.sm.registerOnSelectCallback(() => this.rerender());
        root.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            this.sm.showContextMenu({}, { x: e.clientX, y: e.clientY });
        });
    }

    select(key: unknown, multi: boolean): void {
        if (!key) return;
        this.sm.select(key as ISelectionId, multi).then(() => this.rerender());
    }

    clear(): void {
        if (this.sm.hasSelection()) this.sm.clear().then(() => this.rerender());
    }

    hasSelection(): boolean {
        return this.sm.hasSelection();
    }

    isActive(key: unknown): boolean {
        const ids = this.sm.getSelectionIds() as ISelectionId[];
        return !!key && ids.some(id => id.equals(key as ISelectionId));
    }

    tooltip(ev: MouseEvent | null, items: { name: string; value: string }[], key?: unknown): void {
        if (!ev) {
            if (this.shown) this.host.tooltipService.hide({ immediately: true, isTouchEvent: false });
            this.shown = false;
            return;
        }
        const r = this.root.getBoundingClientRect();
        const args: any = {
            coordinates: [ev.clientX - r.left, ev.clientY - r.top],
            isTouchEvent: false,
            dataItems: items.map(i => ({ displayName: i.name, value: i.value })),
            identities: key ? [key] : [],
        };
        if (this.shown) this.host.tooltipService.move(args);
        else this.host.tooltipService.show(args);
        this.shown = true;
    }

    contextMenu(ev: MouseEvent, key?: unknown): void {
        this.sm.showContextMenu((key as ISelectionId) || {}, { x: ev.clientX, y: ev.clientY });
    }
}
