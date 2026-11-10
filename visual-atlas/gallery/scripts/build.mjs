// Inlines CSS and JS into one self-contained HTML page.
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
const src = root + 'src/';
const order = ['geo.js', 'data.js', 'layouts.js', 'engine.js', 'engine-maps.js', 'engine-html.js', 'engine-x1.js', 'engine-x2.js', 'glyphs.js', 'catalog.js', 'catalog-x.js', 'brand.js', 'look.js', 'app.js'];
const js = order.map((f) => `/* ---- ${f} ---- */\n` + fs.readFileSync(src + f, 'utf8')).join('\n');
const css = fs.readFileSync(src + 'styles.css', 'utf8') + '\n' + fs.readFileSync(src + 'styles-x.css', 'utf8');
let html = fs.readFileSync(src + 'shell.html', 'utf8');
if (js.includes('</script')) throw new Error('script terminator inside JS');
html = html.replace('/*CSS*/', () => css).replace('/*JS*/', () => js);
fs.mkdirSync(root + 'dist', { recursive: true });
const out = process.argv[2] || root + 'dist/power-bi-visual-atlas.html';
fs.writeFileSync(out, html);
// separate JS copy for syntax checking
fs.writeFileSync(root + 'dist/bundle.js', js);
// local preview with a document skeleton (the artifact host adds one when publishing)
fs.writeFileSync(root + 'dist/preview.html', '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body>' + html + '</body></html>');
console.log('wrote', out, (html.length / 1024).toFixed(1) + ' KB');
