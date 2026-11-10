// One Power BI report theme from the Visual Atlas brand engine (custom_visuals/atlas/brand.js), printed as JSON.
// usage: node atlas_theme.js <brand.js> '{"look":"soft","dark":false,"brand":"#0f766e","mode":"spectrum","colors":null}'
// mode: spectrum | analogous | mono (from the brand color), atlas | classic (presets), custom (the colors list)
const fs = require('fs'), vm = require('vm');
const [brandFile, optsJson] = process.argv.slice(2);
const o = JSON.parse(optsJson || '{}');
const ctx = { localStorage: { getItem: () => null, setItem() {} }, document: { getElementById: () => null, createElement: () => ({}), head: { appendChild() {} } }, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(brandFile, 'utf8') + '\n;globalThis.BRAND = BRAND;', ctx);
const B = ctx.BRAND;
if (o.mode === 'custom' && Array.isArray(o.colors) && o.colors.length) {
  B.state.mode = 'custom';
  B.state.custom = o.colors.join(',');
} else {
  if (o.brand) B.state.brand = o.brand;
  B.state.mode = o.mode || (o.brand ? 'spectrum' : 'atlas');
}
process.stdout.write(B.themeJSON(o.look || 'soft', !!o.dark));
