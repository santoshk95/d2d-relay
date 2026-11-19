// Retail cases for Relay Hierarchy: department > category sales, division > store sunburst (thin slices), a treemap
// colored by comp %, dark. Data from retail_data.js.
const hcats = { 'Grocery': ['Cereal and breakfast', 'Snacks', 'Beverages', 'Canned and dry goods', 'Baking'], 'Produce': ['Fresh fruit', 'Fresh vegetables', 'Packaged salads', 'Organic produce'], 'Meat and Seafood': ['Beef', 'Chicken', 'Pork', 'Seafood'], 'Dairy': ['Milk', 'Cheese', 'Yogurt', 'Eggs'], 'Pharmacy': ['Prescriptions', 'Over the counter', 'Vitamins'] };
const rows = []; Object.entries(hcats).forEach(([d, cs], i) => cs.forEach((c, j) => rows.push([d, c, RT.round(RT.total * 0.12 / cs.length * (1 + 0.3 * Math.sin(i + j)), 0), RT.round(0.04 * Math.sin(i * 2 + j), 4)])));
const T = (type, extra) => { const o = Object.assign({}, extra || {}); o.chart = Object.assign({ chartType: type }, o.chart || {}); return o; };
// 0 treemap: department > category, name and value
C('Treemap - department and category sales', RDV({ cats: [{ name: 'Department', role: 'levels', values: rows.map(r => r[0]) }, { name: 'Category', role: 'levels', values: rows.map(r => r[1]) }], measures: [{ name: 'Net Sales', values: rows.map(r => r[2]) }], fmt: FMT.usd, objects: T('treemap', { chart: { content: 'nameValue' } }) }), { w: 620, h: 380 });
// 1 sunburst: division > store (thin slices)
const sb = RT.stores.slice(0, 64);
C('Sunburst - division and store sales (thin slices)', RDV({ cats: [{ name: 'Division', role: 'levels', values: sb.map(s => s.division) }, { name: 'Store', role: 'levels', values: sb.map(s => s.short) }], measures: [{ name: 'Net Sales', values: sb.map(s => s.sales) }], fmt: FMT.usd, objects: T('sunburst', { chart: { content: 'namePercent' } }) }), { w: 560, h: 420 });
// 2 treemap colored by comp % (gradient)
C('Treemap - categories colored by comp %', RDV({ cats: [{ name: 'Category', role: 'levels', values: rows.map(r => r[1]) }], measures: [{ name: 'Net Sales', values: rows.map(r => r[2]) }, { name: 'Identical Store Sales %', role: 'colorValue', values: rows.map(r => r[3]), fmt: FMT.comp }], fmt: FMT.usd, objects: T('treemap', { hcolor: { colorBy: 'value' } }) }), { w: 620, h: 360 });
// 3 dark treemap
C('Treemap - dark, department and category', RDV({ cats: [{ name: 'Department', role: 'levels', values: rows.map(r => r[0]) }, { name: 'Category', role: 'levels', values: rows.map(r => r[1]) }], measures: [{ name: 'Net Sales', values: rows.map(r => r[2]) }], fmt: FMT.usd, objects: T('treemap') }), { dark: true, w: 560, h: 340 });
