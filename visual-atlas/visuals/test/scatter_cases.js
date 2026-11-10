// Test cases for Atlas Scatter in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
/* data view: category columns by role (details, legend, xCategory, play, task, start, end, owner) and measures by role (x, y, size, progress) */
function dv(o) {
  const cats = Object.entries(o.cats || {}).map(([role, c]) => ({ source: { displayName: c.name, queryName: 't.' + c.name, roles: { [role]: true }, type: c.date ? { dateTime: true } : { text: true } }, values: c.values }));
  const values = Object.entries(o.vals || {}).map(([role, v]) => { const col = { source: { displayName: v.name, queryName: 'm.' + v.name, roles: { [role]: true }, isMeasure: true, format: v.fmt || '#,0' }, values: v.values }; if (v.hl) col.highlights = v.hl; return col; });
  values.grouped = () => [{ values: values.slice() }];
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type || 'scatter' }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
let seed = 5; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const fmts = ['Flagship', 'Mall', 'Outlet'], stores = Array.from({ length: 40 }, (_, i) => { const f = fmts[i % 3], spend = 20 + rnd() * 80 + (f === 'Flagship' ? 30 : 0); return { n: 'Store ' + (101 + i), f, spend: Math.round(spend * 1000), rev: Math.round((spend * (4 + rnd() * 2) + (f === 'Outlet' ? -40 : 0)) * 1000), cust: Math.round(800 + rnd() * 5000) }; });
const sv = { details: { name: 'Store', values: stores.map(s => s.n) } }, xy = { x: { name: 'Marketing spend', values: stores.map(s => s.spend), fmt: '\\$#,0' }, y: { name: 'Revenue', values: stores.map(s => s.rev), fmt: '\\$#,0' } };
const mk = ['Bikes US', 'Bikes EU', 'E-bikes US', 'E-bikes EU', 'Parts', 'Apparel', 'Helmets', 'Lights'], years = ['2021', '2022', '2023', '2024', '2025'];
const play = []; mk.forEach((m, i) => years.forEach((y, k) => play.push({ m, y, share: 4 + i * 1.6 + (i > 1 && i < 4 ? k * 2.4 : -k * 0.4), growth: (i > 1 && i < 4 ? 18 : 3) - k * (i % 3) + (i % 2 ? 2 : -1), size: 50 + i * 40 + k * (i < 4 ? 30 : 5) })));
const regs = ['North', 'South', 'East', 'West'], dotp = []; regs.forEach((r, i) => { for (let k = 0; k < 14; k++) dotp.push({ r, v: Math.round(40 + i * 8 + (rnd() - 0.5) * 30) }); });
const prices = Array.from({ length: 36 }, (_, i) => ({ n: 'P' + i, price: Math.round(Math.pow(10, 1.3 + rnd() * 2.2)), units: Math.round(2000 / Math.pow(1.6, rnd() * 6) + rnd() * 50) }));
const d = (y, m, dd) => new Date(y, m - 1, dd);
const proj = [['Discovery', 'Plan', d(2026, 9, 1), d(2026, 9, 12), 'Avery', 1], ['Requirements', 'Plan', d(2026, 9, 8), d(2026, 9, 26), 'Kai', 1], ['Kick-off', 'Plan', d(2026, 9, 28), null, 'Avery', 1],
  ['Design', 'Build', d(2026, 9, 29), d(2026, 10, 24), 'Mira', 0.9], ['Build API', 'Build', d(2026, 10, 13), d(2026, 11, 21), 'Jon', 0.55], ['Build app', 'Build', d(2026, 10, 20), d(2026, 12, 5), 'Lee', 0.4],
  ['Data migration', 'Build', d(2026, 11, 2), d(2026, 11, 28), 'Kai', 0.2], ['Testing', 'Launch', d(2026, 11, 23), d(2026, 12, 12), 'Mira', 0], ['Training', 'Launch', d(2026, 12, 1), d(2026, 12, 15), 'Lee', 0], ['Go-live', 'Launch', d(2026, 12, 16), null, 'Avery', 0]];
const ganttDV = (rows, objects) => dv({ type: 'gantt', cats: { task: { name: 'Task', values: rows.map(r => r[0]) }, legend: { name: 'Phase', values: rows.map(r => r[1]) }, start: { name: 'Start', date: true, values: rows.map(r => r[2]) }, end: { name: 'End', date: true, values: rows.map(r => r[3]) }, owner: { name: 'Owner', values: rows.map(r => r[4]) } }, vals: { progress: { name: '% complete', values: rows.map(r => r[5]), fmt: '0%' } }, objects });
const sprint = [['Plan sprint', 'Sprint', d(2026, 11, 2), d(2026, 11, 3), 'Kai', 1], ['Checkout fix', 'Sprint', d(2026, 11, 3), d(2026, 11, 7), 'Jon', 0.6], ['Payment retry', 'Sprint', d(2026, 11, 5), d(2026, 11, 12), 'Lee', 0.3], ['QA', 'Sprint', d(2026, 11, 11), d(2026, 11, 17), 'Mira', 0], ['Release', 'Sprint', d(2026, 11, 18), null, 'Avery', 0]];

// 0-9 scatter and bubble
C('Scatter · spend vs revenue', dv({ cats: sv, vals: xy }));
C('Bubble · size is customers · legend by format', dv({ cats: { ...sv, legend: { name: 'Format', values: stores.map(s => s.f) } }, vals: { ...xy, size: { name: 'Customers', values: stores.map(s => s.cust) } } }));
C('Scatter · quadrants at the averages · flat', dv({ cats: { ...sv, legend: { name: 'Format', values: stores.map(s => s.f) } }, vals: xy, objects: { chart: { look: 'flat' }, guides: { quadrants: true } } }));
C('Scatter · trend line and ratio line', dv({ cats: sv, vals: xy, objects: { guides: { trend: true, ratio: true } } }));
C('Scatter · plan vs actual · symmetry shading · labels', dv({ cats: { details: { name: 'Region', values: regs } }, vals: { x: { name: 'Plan', values: [420, 380, 300, 260], fmt: '\\$#,0K' }, y: { name: 'Actual', values: [455, 342, 318, 231], fmt: '\\$#,0K' } }, objects: { guides: { symmetry: true }, labels: { show: true }, points: { size: 7 } } }));
C('Bubble · play axis 2021–2025 (frame 1) · labels', dv({ cats: { details: { name: 'Market', values: play.map(p => p.m) }, play: { name: 'Year', values: play.map(p => p.y) } }, vals: { x: { name: 'Market share %', values: play.map(p => p.share), fmt: '0.0' }, y: { name: 'Growth %', values: play.map(p => p.growth), fmt: '0' }, size: { name: 'Revenue', values: play.map(p => p.size) } }, objects: { labels: { show: true } } }));
C('Scatter · logarithmic X · price vs units', dv({ cats: { details: { name: 'Product', values: prices.map(p => p.n) } }, vals: { x: { name: 'Price', values: prices.map(p => p.price), fmt: '\\$#,0' }, y: { name: 'Units', values: prices.map(p => p.units) } }, objects: { guides: { xLog: true }, points: { shape: 'diamond' } } }));
C('Scatter · automatic clusters (3)', dv({ cats: sv, vals: xy, objects: { points: { colorBy: 'cluster', clusters: 3 } } }));
C('Dot plot · values by region', dv({ type: 'dotplot', cats: { details: { name: 'Store', values: dotp.map((_, i) => 'S' + i) }, xCategory: { name: 'Region', values: dotp.map(p => p.r) } }, vals: { y: { name: 'Score', values: dotp.map(p => p.v) } } }));
C('Scatter · cross-highlighted (flagships)', dv({ cats: { ...sv, legend: { name: 'Format', values: stores.map(s => s.f) } }, vals: { x: xy.x, y: { ...xy.y, hl: stores.map(s => (s.f === 'Flagship' ? s.rev : null)) } } }));
// 10-12 Gantt
C('Gantt · project schedule · progress fill · today', ganttDV(proj));
C('Gantt · thin progress overlay · 3D · no columns', ganttDV(proj, { chart: { look: '3d' }, gantt: { progress: 'overlay', ownerColumn: false, percentColumn: false } }));
C('Gantt · sprint in days · weekends shaded', ganttDV(sprint));
// 13-16 modes and edge cases
C('Scatter · high contrast', dv({ cats: { ...sv, legend: { name: 'Format', values: stores.map(s => s.f) } }, vals: xy }), { hc: true });
C('Bubble · dark', dv({ cats: { ...sv, legend: { name: 'Format', values: stores.map(s => s.f) } }, vals: { ...xy, size: { name: 'Customers', values: stores.map(s => s.cust) } } }), { dark: true });
C('Landing page (no fields)', null);
C('Gantt · small tile (scrolls)', ganttDV(proj), { w: 360, h: 200 });
