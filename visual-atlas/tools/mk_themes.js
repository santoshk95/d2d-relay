// Generates the Power BI report themes from the gallery's brand engine (gallery/src/brand.js).
// usage: node tools/mk_themes.js [outDir]   (default visuals/themes)
// Each theme = palette + structural colors + text sizes + the look (flat/soft/3d) as container styles,
// plus defaults for every Atlas custom visual in visuals/ (visualStyles keyed by their GUIDs), so one
// theme restyles all of them.
// Options (environment variables):
//   BRAND_COLOR=#0f766e PALETTE=spectrum|analogous|mono   palette from a brand color
//   ATLAS_FONT="Segoe UI Semibold"                         font of every Atlas visual (Style card)
//   ATLAS_SHADOW=0..100                                    shadow strength of the soft and 3D looks
const fs = require('fs'), vm = require('vm'), path = require('path');
const root = path.resolve(__dirname, '..');
const out = path.resolve(process.argv[2] || path.join(root, 'visuals/themes'));
const src = fs.readFileSync(path.join(root, 'gallery/src/brand.js'), 'utf8');
const ctx = { localStorage: { getItem: () => null, setItem() {} }, document: { getElementById: () => null, createElement: () => ({}), head: { appendChild() {} } }, console };
vm.createContext(ctx);
vm.runInContext(src + '\n;globalThis.BRAND = BRAND;', ctx);
const B = ctx.BRAND;
if (process.env.BRAND_COLOR) {
  B.state.brand = process.env.BRAND_COLOR;
  B.state.mode = process.env.PALETTE || 'spectrum';
}
const SHADOW = Math.max(0, Math.min(100, Number(process.env.ATLAS_SHADOW || 55)));
function atlasGuids() {
  const dir = path.join(root, 'visuals');
  return fs.readdirSync(dir).map(d => path.join(dir, d, 'pbiviz.json')).filter(f => fs.existsSync(f))
    .map(f => JSON.parse(fs.readFileSync(f, 'utf8')).visual.guid).sort();
}
const guids = atlasGuids();
fs.mkdirSync(out, { recursive: true });
[['flat', false], ['soft', false], ['3d', false], ['soft', true]].forEach(([look, dark]) => {
  const file = path.join(out, `atlas-theme-${look}${dark ? '-dark' : ''}.json`);
  const theme = JSON.parse(B.themeJSON(look, dark));
  /* built-in column and bar charts: a theme can't add gradients or rounded bars (no such property in the
     theme schema), but it can drop the axis titles, soften the gridlines, show bold labels and narrow the gap between series */
  const ink = dark ? '#e6e6e6' : '#252423', grid = dark ? '#3b3b3b' : '#ececec';
  const bars = {
    categoryAxis: [{ showAxisTitle: false, gridlineShow: false, labelColor: { solid: { color: ink } } }],
    valueAxis: [{ showAxisTitle: false, gridlineShow: true, gridlineColor: { solid: { color: grid } } }],
    labels: [{ show: true, color: { solid: { color: ink } }, fontFamily: 'Segoe UI Semibold' }],
    layout: [{ clusteredGapSize: 4 }]
  };
  for (const v of ['columnChart', 'clusteredColumnChart', 'barChart', 'clusteredBarChart', 'hundredPercentStackedColumnChart', 'hundredPercentStackedBarChart']) {
    const cur = (theme.visualStyles[v] && theme.visualStyles[v]['*']) || {};
    theme.visualStyles[v] = { '*': Object.assign({}, cur, bars) };
  }
  for (const guid of guids) {
    const style = { chart: [{ look, shadow: SHADOW }], palette: [{ source: 'theme' }] };
    if (process.env.ATLAS_FONT) style.style = [{ fontFamily: process.env.ATLAS_FONT }];
    theme.visualStyles[guid] = { '*': style };
  }
  fs.writeFileSync(file, JSON.stringify(theme, null, 2) + '\n');
  console.log(path.relative(root, file), '-', theme.name, '-', guids.length, 'Atlas visuals');
});
