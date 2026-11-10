/*
 * Data model for Atlas Flow: nodes and links built from the Source,
 * Target and Weight fields, plus the drawing context renderers share.
 */
import powerbi from "powerbi-visuals-api";
import { Look } from "./common/look";
import ISelectionId = powerbi.visuals.ISelectionId;

export interface FNode {
    key: string; name: string; i: number;
    inV: number; outV: number; value: number; deg: number;
    color: string; sel: ISelectionId; selector: powerbi.data.Selector;
    highlighted: boolean;
    /* layout */
    col?: number; x?: number; y0?: number; y1?: number; r?: number; comm?: number;
}
export interface FLink {
    s: number; t: number; v: number; hl: number | null; row: number;
    sel: ISelectionId; tips: { name: string; value: string }[];
    /* layout */
    sy?: number; ty?: number; back?: boolean;
}
export interface Ctx {
    root: SVGGElement; W: number; H: number; look: Look;
    nodes: FNode[]; links: FLink[];
    fmt: (v: number) => string;
    label: { show: boolean; size: number; color: string; values: boolean; };
    ink: string; muted: string; surface: string; grid: string;
    highlights: boolean;
    isSelected: (key: string) => boolean;
    anySelected: boolean;
    /** register a mark so it gets tooltips, selection and keyboard focus */
    bind: (elem: SVGElement, kind: "node" | "link", index: number) => void;
}
export const linkKey = (l: FLink) => "l" + l.row;
export const nodeKey = (n: FNode) => "n" + n.key;
