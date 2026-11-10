/*
 * Period Hierarchy Slicer: one dropdown slicer with an expandable tree (Year › Month › Week …). A pick
 * filters the report on the level picked (a basic "In" filter on that column, applyJsonFilter) and is
 * read back from jsonFilters, so bookmarks, reloads and synced copies on other pages keep it.
 */
"use strict";
import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";
import { Settings } from "./settings";
import { Model, readModel, keyOf, TNode } from "./model";
import { render, Pick } from "./render";
import { FamilyVisual, Ctx } from "./common/family";
import { BasicFilter, IBasicFilter } from "powerbi-models";

export class Visual extends FamilyVisual<Settings, Model> {
    protected readonly title = "Period Hierarchy Slicer";
    protected readonly landingLines: [string, string] = [
        "Add the levels of the tree to Levels, from the top (for example Year, Month, Week).",
        "Add a measure to Values to show a number next to every item."];
    protected readonly limit = 30000;
    private pick: Pick | null = null;
    private open: boolean | null = null;
    private expanded = new Set<string>();
    private seeded = false;
    constructor(options: powerbi.extensibility.visual.VisualConstructorOptions) {
        super(options, "atl-fam", "gperiodhierar");
    }
    protected newSettings(dv?: powerbi.DataView) { return this.fss.populateFormattingSettingsModel(Settings, dv); }
    protected read(dv: powerbi.DataView | undefined) {
        const m = readModel(dv, this.host);
        if (this.open === null) this.open = this.settings.slicer.startOpen.value;
        /* the current filter (after a reload, a bookmark, a synced slicer on another page) */
        this.pick = null;
        const filters = (this.options && this.options.jsonFilters) as unknown as IBasicFilter[] | undefined;
        if (m && filters) {
            for (const f of filters) {
                const tg = f && f.target as { table?: string; column?: string } | undefined;
                const level = tg ? m.levels.findIndex(l => !!l.target && l.target.column === tg.column && l.target.table === tg.table) : -1;
                if (level >= 0 && f.values && f.values.length) { this.pick = { level, keys: new Set(f.values.map(v => keyOf(v as powerbi.PrimitiveValue))) }; break; }
            }
        }
        if (m && !this.seeded) {
            /* first draw: open the path to what is picked, else the latest top-level item */
            this.seeded = true;
            const p = this.pick;
            if (p) m.nodes.filter(x => x.level === p.level && p.keys.has(keyOf(x.raw))).forEach(x => { for (let a = x.parent; a; a = a.parent) this.expanded.add(a.key); });
            else if (m.roots.length) this.expanded.add(m.roots[m.roots.length - 1].key);
        }
        if (m && m.levels.some(l => !l.target)) this.host.displayWarningIcon(this.loc("Warn_Target_Title", "Use plain columns"), this.loc("Warn_Target_Text", "Each level filters its own column. Use the columns themselves, not a date hierarchy."));
        return m;
    }
    protected draw(c: Ctx<Settings, Model>) {
        render(c, {
            pick: this.pick, open: !!this.open, expanded: this.expanded,
            toggleOpen: () => { this.open = !this.open; this.render(); },
            toggleNode: (n: TNode) => { if (this.expanded.has(n.key)) this.expanded.delete(n.key); else this.expanded.add(n.key); this.render(); },
            choose: (n: TNode, multi: boolean) => this.choose(n, multi),
            clear: () => this.apply(null)
        });
    }
    private choose(n: TNode, multi: boolean) {
        const p = this.pick, k = keyOf(n.raw);
        if (multi && this.settings.slicer.multiSelect.value && p && p.level === n.level) {
            const keys = new Set(p.keys); if (keys.has(k)) keys.delete(k); else keys.add(k);
            this.apply(keys.size ? { level: n.level, keys } : null);
        } else if (p && p.level === n.level && p.keys.size === 1 && p.keys.has(k)) this.apply(null);
        else this.apply({ level: n.level, keys: new Set([k]) });
    }
    private apply(p: Pick | null) {
        const m = this.model;
        this.pick = p;
        if (m && this.host.hostCapabilities.allowInteractions) {
            const target = p ? m.levels[p.level].target : null;
            if (!p || !target) this.host.applyJsonFilter(null as unknown as powerbi.IFilter, "general", "filter", powerbi.FilterAction.remove);
            else {
                /* the raw values of the picked items (numbers stay numbers, so a Year filter matches) */
                const raws: (string | number | boolean)[] = [];
                m.nodes.forEach(x => {
                    if (x.level !== p.level || !p.keys.has(keyOf(x.raw))) return;
                    const r = x.raw instanceof Date ? x.raw.toISOString() : x.raw as string | number | boolean;
                    if (!raws.some(y => keyOf(y) === keyOf(r))) raws.push(r);
                });
                const filter = new BasicFilter(target, "In", raws);
                this.host.applyJsonFilter(filter.toJSON() as unknown as powerbi.IFilter, "general", "filter", powerbi.FilterAction.merge);
            }
        }
        this.render();
    }
    protected isFiltering() { return !!this.pick; }
    protected clearFilter() { this.apply(null); }
    protected tidy(m: Model | null) { this.settings.tidy(!!m && m.hasValues); }
    protected describe(m: Model) { return `Period slicer: ${m.levels.map(l => l.name).join(" › ")}`; }
}
