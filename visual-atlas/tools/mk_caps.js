// Writes a family visual's capabilities.json from its caps.js plus the objects shared by every Atlas
// family (style, palette, dataColors, labels, axes, gridlines, legend - the cards in common/cards.ts).
// usage: node tools/mk_caps.js visuals/atlasCompare      (visuals/sync.sh runs it for every caps.js)
// caps.js exports ({ E, num, bool, text, color, fsz, units, font, LINE }) => ({ roles, mappings, objects, shared, ... })
const fs = require('fs'), path = require('path');
const dir = path.resolve(process.argv[2]);
const E = (...pairs) => ({ type: { enumeration: pairs.map(([value, displayName]) => ({ value, displayName })) } });
const num = { type: { numeric: true } }, bool = { type: { bool: true } }, text = { type: { text: true } };
const color = { type: { fill: { solid: { color: true } } } }, fsz = { type: { formatting: { fontSize: true } } };
const units = { type: { formatting: { labelDisplayUnits: true } } }, font = { type: { formatting: { fontFamily: true } } };
const LINE = E(['solid', 'Solid'], ['dashed', 'Dashed'], ['dotted', 'Dotted']);
const SHARED = {
  style: { properties: { fontFamily: font, textColor: color, keepOthers: bool, marker: bool, markerColor: color, markerHighlight: bool } },
  palette: { properties: { source: E(['theme', 'Report theme'], ['brand', 'Brand color'], ['custom', 'Custom list']), brand: color, mode: E(['spectrum', 'Spectrum'], ['analogous', 'Analogous'], ['mono', 'Mono']), custom: text } },
  dataColors: { properties: { fill: color } },
  labels: { properties: { show: bool, fontSize: fsz, color, displayUnits: units, decimals: num } },
  categoryAxis: { properties: { show: bool, fontSize: fsz, color, title: bool } },
  valueAxis: { properties: { show: bool, fontSize: fsz, color, displayUnits: units, decimals: num, start: text, end: text, title: bool } },
  gridlines: { properties: { show: bool, color, style: LINE, width: num } },
  legend: { properties: { show: bool, position: E(['top', 'Top'], ['topCenter', 'Top center'], ['bottom', 'Bottom'], ['bottomCenter', 'Bottom center'], ['right', 'Right']), fontSize: fsz, color, title: bool } }
};
const spec = require(path.join(dir, 'caps.js'))({ E, num, bool, text, color, fsz, units, font, LINE });
const objects = {};
(spec.shared || Object.keys(SHARED)).forEach(k => { objects[k] = SHARED[k]; });
Object.assign(objects, spec.objects || {});
const caps = {
  dataRoles: spec.roles,
  ...(spec.drilldown ? { drilldown: spec.drilldown } : {}),
  ...(spec.sorting ? { sorting: spec.sorting } : {}),
  dataViewMappings: spec.mappings,
  objects,
  tooltips: { supportedTypes: { default: true, canvas: true }, roles: ['tooltips'] },
  supportsHighlight: spec.supportsHighlight !== false,
  supportsLandingPage: true, supportsEmptyDataView: true, supportsKeyboardFocus: true, supportsMultiVisualSelection: true,
  ...(spec.extra || {}),
  privileges: []
};
fs.writeFileSync(path.join(dir, 'capabilities.json'), JSON.stringify(caps, null, 2) + '\n');
console.log('capabilities ->', path.relative(process.cwd(), path.join(dir, 'capabilities.json')), Object.keys(objects).length, 'objects');
