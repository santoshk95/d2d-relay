/*
 * Data model for Atlas Compare: the shared category × series matrix
 * (common/matrix.ts). Every chart type reads it: rows of a lollipop or
 * dumbbell, lines of a slope or bump, spokes and polygons of a radar.
 */
export { Cell, Model, readModel, catTarget } from "./common/matrix";
