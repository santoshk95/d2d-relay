// Pull the JSON out of Power BI Desktop's webpack chunk: JSON.parse('<js string>') -> object, without eval.
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const a = src.indexOf("JSON.parse('") + "JSON.parse('".length;
const b = src.lastIndexOf("')");
const lit = src.slice(a, b);
let out = '';
for (let i = 0; i < lit.length; i++) {
  const c = lit[i];
  if (c !== '\\') { out += c; continue; }
  const n = lit[++i];
  if (n === 'n') out += '\n';
  else if (n === 't') out += '\t';
  else if (n === 'r') out += '\r';
  else if (n === 'u') { out += String.fromCharCode(parseInt(lit.substr(i + 1, 4), 16)); i += 4; }
  else if (n === 'x') { out += String.fromCharCode(parseInt(lit.substr(i + 1, 2), 16)); i += 2; }
  else out += n;   // \\ \' \"
}
const j = JSON.parse(out);
fs.writeFileSync(process.argv[3], JSON.stringify(j));        // compact, as genbi_kit/stock.py reads it
// summary: per visual, its own formatting objects and properties (definitions/visual-<type>, without commonCards)
const defs = j.definitions || {};
const rows = Object.keys(defs).filter(k => k.startsWith('visual-')).map(k => {
  const own = (defs[k].allOf || [defs[k]]).filter(p => !p.$ref).flatMap(p => Object.entries(p.properties || {}));
  const objs = own.filter(([o, s]) => o !== '*' && s.items);
  return [k.slice(7), objs.length, objs.reduce((n, [, s]) => n + Object.keys((s.items.properties) || {}).length, 0)];
});
console.log('schema', j.description, '· visuals', rows.length);
console.log(rows.sort((x, y) => y[2] - x[2]).map(r => `${r[0]} ${r[1]} objects / ${r[2]} properties`).join('\n'));
