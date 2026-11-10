// Precomputes circle-packing and force-directed layouts from the page's own sample data.
// Usage: node gen-layouts.mjs <node_modules dir> <src dir> <out file>
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
const [NM, SRC, OUT] = process.argv.slice(2);
const imp = (p) => import(path.join(NM, p));
const h = await imp('d3-hierarchy/src/index.js');
const f = await imp('d3-force/src/index.js');

// evaluate the page's data model to get the same hierarchies
const ctx = vm.createContext({ Math, String, Object, Array, JSON, Date, Map, Set, Number, console });
vm.runInContext(fs.readFileSync(path.join(SRC, 'geo.js'), 'utf8') + '\n' + fs.readFileSync(path.join(SRC, 'data.js'), 'utf8') + '\nthis.__HP=HP;this.__agg=agg;this.__leaves=leaves;', ctx);
const HP = ctx.__HP, agg = ctx.__agg;

const r3 = (v) => Math.round(v * 1000) / 1000;

// ---- circle packing: Category > Subcategory > Product (value = sales)
const toTree = (n) => (n.c ? { name: n.n, children: n.c.map(toTree) } : { name: n.n, value: n.v[0] });
const root = h.hierarchy(toTree(HP.root)).sum((d) => d.value || 0).sort((a, b) => b.value - a.value);
h.pack().size([1, 1]).padding((d) => (d.depth === 0 ? 0.012 : 0.006))(root);
const pack = [];
root.descendants().forEach((d) => {
  if (d.depth === 0) return;
  const cat = d.ancestors().find((a) => a.depth === 1);
  pack.push({ n: d.data.name, d: d.depth, x: r3(d.x), y: r3(d.y), r: r3(d.r), v: Math.round(d.value), c: root.children.indexOf(cat), p: d.parent && d.parent.depth > 0 ? d.parent.data.name : null });
});

// ---- co-purchase network: 5 products per category
let s = 7;
const rnd = () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
const nodes = [];
HP.root.c.forEach((cat, ci) => {
  const prods = ctx.__leaves(cat).sort((a, b) => b.v[0] - a.v[0]).slice(0, 5);
  prods.forEach((p) => nodes.push({ id: nodes.length, n: p.n, g: ci, v: p.v[0] }));
});
const links = [];
for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
  const same = nodes[i].g === nodes[j].g;
  const pr = same ? 0.62 : (nodes[i].g === 0 && nodes[j].g === 3) || (nodes[i].g === 0 && nodes[j].g === 1) ? 0.16 : 0.06;
  if (rnd() < pr) links.push({ source: i, target: j, w: Math.round((same ? 40 : 12) + rnd() * (same ? 160 : 60)) });
}
const sim = f.forceSimulation(nodes)
  .force('link', f.forceLink(links).id((d) => d.id).distance((l) => (nodes[l.source.id ?? l.source].g === nodes[l.target.id ?? l.target].g ? 0.11 : 0.3)).strength(0.6))
  .force('charge', f.forceManyBody().strength(-0.012))
  .force('center', f.forceCenter(0.5, 0.5))
  .force('collide', f.forceCollide(0.045))
  .stop();
for (let i = 0; i < 400; i++) sim.tick();
const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
const deg = nodes.map(() => 0);
links.forEach((l) => { deg[l.source.id]++; deg[l.target.id]++; });
const net = {
  nodes: nodes.map((n, i) => ({ n: n.n, g: n.g, x: r3((n.x - x0) / (x1 - x0)), y: r3((n.y - y0) / (y1 - y0)), deg: deg[i], v: n.v })),
  links: links.map((l) => ({ s: l.source.id, t: l.target.id, w: l.w }))
};
fs.writeFileSync(OUT, '/* Precomputed layouts (d3-hierarchy pack, d3-force) from the sample data */\nconst PACK=' + JSON.stringify(pack) + ';\nconst NET=' + JSON.stringify(net) + ';\n');
console.log('pack', pack.length, 'net nodes', net.nodes.length, 'links', net.links.length);
