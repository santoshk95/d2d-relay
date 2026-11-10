// Design tokens, card chrome and the interaction contract shared by all charts.
import { el, clear } from "./dom";

export interface Tokens {
    font: string;
    ink: string;
    muted: string;
    faint: string;
    grid: string;
    border: string;
    card: string;
    primary: string;
    primaryDark: string;
    primaryLight: string;
    negative: string;
    target: string;
    comparison: string;
    good: string;
    goodBg: string;
    warn: string;
    warnBg: string;
    bad: string;
    badBg: string;
}

export const DEFAULT_TOKENS: Tokens = {
    font: "'Segoe UI', 'Segoe UI Web (West European)', -apple-system, system-ui, sans-serif",
    ink: "#1F1A17",
    muted: "#6F6761",
    faint: "#A39B94",
    grid: "#EEE9E3",
    border: "#E7E0D7",
    card: "#FFFFFF",
    primary: "#DD7A12",
    primaryDark: "#9C4F0C",
    primaryLight: "#F6D3A3",
    negative: "#3B78D8",
    target: "#3A3330",
    comparison: "#A9A29B",
    good: "#2E7D3A",
    goodBg: "#E3F2E5",
    warn: "#A86400",
    warnBg: "#FCEFD4",
    bad: "#B3261E",
    badBg: "#FBE4E1",
};

export interface Header {
    title?: string;
    subtitle?: string;
    showCard?: boolean;
}

/** Selection / tooltip hooks; Power BI and the prototype each provide their own. */
export interface Interactions {
    select?(key: unknown, multi: boolean): void;
    clear?(): void;
    isActive?(key: unknown): boolean;
    hasSelection?(): boolean;
    tooltip?(ev: MouseEvent | null, items: { name: string; value: string }[], key?: unknown): void;
    contextMenu?(ev: MouseEvent, key?: unknown): void;
}

export const NO_INTERACTIONS: Interactions = {};

export function applyTokens(root: HTMLElement, t: Tokens): void {
    const vars: Record<string, string> = {
        "--gb-font": t.font, "--gb-ink": t.ink, "--gb-muted": t.muted, "--gb-faint": t.faint,
        "--gb-grid": t.grid, "--gb-border": t.border, "--gb-card": t.card, "--gb-primary": t.primary,
        "--gb-primary-dark": t.primaryDark, "--gb-primary-light": t.primaryLight, "--gb-negative": t.negative,
        "--gb-good": t.good, "--gb-good-bg": t.goodBg, "--gb-warn": t.warn, "--gb-warn-bg": t.warnBg,
        "--gb-bad": t.bad, "--gb-bad-bg": t.badBg,
    };
    for (const k of Object.keys(vars)) root.style.setProperty(k, vars[k]);
}

export interface Frame {
    card: HTMLElement;
    head: HTMLElement;
    body: HTMLElement;
    width: number;
    height: number;
}

/** Card with optional title/subtitle; returns the body element and its pixel size. */
export function frame(root: HTMLElement, t: Tokens, header: Header, extraClass = ""): Frame {
    clear(root);
    root.classList.add("gb-root");
    applyTokens(root, t);
    const card = el("div", `gb-card ${header.showCard === false ? "gb-flat" : ""} ${extraClass}`.trim(), root);
    const head = el("div", "gb-head", card);
    if (header.title) el("div", "gb-title", head, header.title);
    if (header.subtitle) el("div", "gb-sub", head, header.subtitle);
    if (!header.title && !header.subtitle) head.style.display = "none";
    const body = el("div", "gb-body", card);
    const r = body.getBoundingClientRect();
    return { card, head, body, width: Math.max(10, r.width), height: Math.max(10, r.height) };
}

export function emptyState(root: HTMLElement, t: Tokens, message: string): void {
    const f = frame(root, t, {});
    el("div", "gb-empty", f.body, message);
}

/** Wire hover/click/context-menu on an element for one data point. */
export function bind(node: Element, ia: Interactions, key: unknown,
    tip: () => { name: string; value: string }[]): void {
    node.addEventListener("click", (e) => {
        const ev = e as MouseEvent;
        ev.stopPropagation();
        ia.select?.(key, ev.ctrlKey || ev.metaKey || ev.shiftKey);
    });
    node.addEventListener("mousemove", (e) => ia.tooltip?.(e as MouseEvent, tip(), key));
    node.addEventListener("mouseleave", () => ia.tooltip?.(null, []));
    node.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        e.stopPropagation();
        ia.contextMenu?.(e as MouseEvent, key);
    });
}

export function dimmed(ia: Interactions, key: unknown): boolean {
    return !!ia.hasSelection?.() && !!ia.isActive && !ia.isActive(key);
}

export const FONT = (size: number, weight = 400, t: Tokens = DEFAULT_TOKENS) => `${weight} ${size}px ${t.font}`;
