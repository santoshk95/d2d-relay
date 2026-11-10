/*
 * Selection, tooltips, context menu and keyboard access shared by the
 * Atlas family visuals. A mark is bound to a Target: a key, the item
 * indexes it covers, its selection ids and a tooltip builder. The
 * visual reads `active` (selected items, else highlighted items) to dim
 * the rest.
 */
import powerbi from "powerbi-visuals-api";
import ISelectionId = powerbi.visuals.ISelectionId;
import TipItem = powerbi.extensibility.VisualTooltipDataItem;

export interface Target {
    key: string; items: number[]; ids: ISelectionId[]; tip: () => TipItem[];
    /** a hover area that spans the plot (a category strip): it selects, but keeps the arrow cursor */
    wide?: boolean;
}

export class Interact {
    private sm: powerbi.extensibility.ISelectionManager;
    private picked = new Map<string, number[]>();
    readonly sel = new Set<number>();
    /** a plain click keeps other visuals' selections (Style card); set by the visual on every render */
    keepOthers = true;
    /** items highlighted by another visual (set by the visual on update) */
    highlighted: Set<number> | null = null;

    constructor(private host: powerbi.extensibility.visual.IVisualHost, private root: HTMLElement, background: Element, private redraw: () => void) {
        this.sm = host.createSelectionManager();
        background.addEventListener("click", ev => {
            if (ev.target !== background || !host.hostCapabilities.allowInteractions) return;
            this.clear(); this.sm.clear(); this.redraw();
        });
        background.addEventListener("contextmenu", ev => {
            if (ev.target !== background) return;
            const me = ev as MouseEvent; me.preventDefault();
            this.sm.showContextMenu({} as ISelectionId, { x: me.clientX, y: me.clientY });
        });
        this.sm.registerOnSelectCallback(() => this.redraw());
    }
    clear() { this.picked.clear(); this.sel.clear(); }
    /** clear the selection here and in the report (the drill bar's clear button) */
    clearSelection() { this.clear(); if (this.keepOthers) replaceSelection(this.sm, []); else this.sm.clear().then(() => undefined, () => undefined); this.redraw(); }
    /** select a group of items at once (click and drag across a chart): replaces the selection, or adds to it with Ctrl */
    selectMany(key: string, items: number[], ids: ISelectionId[], add: boolean) {
        if (!this.host.hostCapabilities.allowInteractions || !ids.length) return;
        choose(this.sm, ids, add, this.keepOthers);
        if (!add) this.picked.clear();
        this.picked.set(key, items);
        this.sel.clear(); this.picked.forEach(list => list.forEach(i => this.sel.add(i)));
        this.redraw();
    }
    /** items to emphasize: the selection, else items highlighted by another visual; null when nothing is emphasized */
    get active(): Set<number> | null { return this.sel.size ? this.sel : this.highlighted; }
    on(i: number): boolean { const a = this.active; return !a || a.has(i); }
    anyOn(items: number[]): boolean { const a = this.active; return !a || items.some(i => a.has(i)); }

    /** map the host's selection (bookmarks, other visuals) back to items: match(id) returns the items an id stands for */
    sync(match: (id: ISelectionId) => { key: string; items: number[] } | null) {
        this.clear();
        (this.sm.getSelectionIds() as ISelectionId[]).forEach(id => { const m = match(id); if (m) { this.picked.set(m.key, m.items); m.items.forEach(i => this.sel.add(i)); } });
    }

    /** an axis or category label that selects what it names (a month on the x axis, a product on a bar chart's y axis) */
    bindLabel(e: Element, t: Target) {
        if (!t.ids.length) return;
        (e as SVGElement).style.pointerEvents = "all";
        this.bind(e, t);
    }
    /** true when clicking these ids selects data (a category, a series value); a measure alone filters nothing */
    filters(ids: ISelectionId[]): boolean {
        return this.host.hostCapabilities.allowInteractions && ids.some(id => {
            const sel = typeof id.getSelector === "function" ? id.getSelector() as { data?: unknown[] } : null;
            return !sel || !!(sel.data && sel.data.length);
        });
    }
    bind(e: Element, t: Target) {
        e.setAttribute("tabindex", "0"); e.setAttribute("focusable", "true");
        /* the hand cursor only where a click selects something; full-plot hover areas and measure-only marks keep the arrow */
        (e as SVGElement).style.cursor = t.wide || !this.filters(t.ids) ? "default" : "pointer";
        const ts = this.host.tooltipService, ids = t.ids.slice(0, 50);
        const xy = (ev: MouseEvent) => { const r = this.root.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
        e.addEventListener("mouseenter", ev => { if (ts.enabled()) ts.show({ coordinates: xy(ev as MouseEvent), isTouchEvent: false, dataItems: t.tip(), identities: ids }); });
        e.addEventListener("mousemove", ev => { if (ts.enabled()) ts.move({ coordinates: xy(ev as MouseEvent), isTouchEvent: false, dataItems: t.tip(), identities: ids }); });
        e.addEventListener("mouseleave", () => ts.hide({ isTouchEvent: false, immediately: true }));
        const pick = (multi: boolean) => {
            if (!this.host.hostCapabilities.allowInteractions || !t.ids.length) return;
            if (multi) { if (this.picked.has(t.key)) this.picked.delete(t.key); else this.picked.set(t.key, t.items); }
            else if (this.picked.size === 1 && this.picked.has(t.key)) this.picked.clear();
            else { this.picked.clear(); this.picked.set(t.key, t.items); }
            this.sel.clear(); this.picked.forEach(list => list.forEach(i => this.sel.add(i)));
            if (!this.picked.size) { if (this.keepOthers) replaceSelection(this.sm, []); else this.sm.clear().then(() => undefined, () => undefined); }
            else choose(this.sm, t.ids, multi, this.keepOthers);
            this.redraw();
        };
        e.addEventListener("click", ev => { ev.stopPropagation(); const me = ev as MouseEvent; pick(me.ctrlKey || me.metaKey); });
        e.addEventListener("keydown", ev => { const ke = ev as KeyboardEvent; if (ke.key === "Enter" || ke.key === " ") { ke.preventDefault(); pick(ke.ctrlKey || ke.metaKey); } });
        e.addEventListener("contextmenu", ev => { ev.preventDefault(); ev.stopPropagation(); const me = ev as MouseEvent; this.sm.showContextMenu(t.ids[0] || ({} as ISelectionId), { x: me.clientX, y: me.clientY }); });
    }
}

/**
 * Replace this visual's selection and leave other visuals' selections in place (the Style card's
 * "Keep other visuals' selections"). select(ids, false) would clear every other visual's selection, so
 * this toggles with multiSelect instead: ids no longer picked go off, new ones go on, in one call.
 */
export function replaceSelection(sm: powerbi.extensibility.ISelectionManager, next: ISelectionId[]): void {
    /* with nothing next this switches this visual's ids off, without clear() (which might drop other visuals' selections too) */
    const prev = sm.getSelectionIds() as ISelectionId[];
    const off = prev.filter(p => !next.some(n => n.equals(p))), on = next.filter(n => !prev.some(p => p.equals(n)));
    if (off.length || on.length) sm.select(off.concat(on), true).then(() => undefined, () => undefined);
}
/** select ids after a click: Ctrl adds (toggles), a plain click replaces this visual's selection (keeping other visuals' when asked) */
export function choose(sm: powerbi.extensibility.ISelectionManager, ids: ISelectionId[], multi: boolean, keepOthers: boolean): void {
    if (multi) sm.select(ids, true).then(() => undefined, () => undefined);
    else if (keepOthers) replaceSelection(sm, ids);
    else sm.select(ids, false).then(() => undefined, () => undefined);
}
