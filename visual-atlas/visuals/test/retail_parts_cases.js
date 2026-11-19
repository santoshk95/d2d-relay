// Retail cases for Relay Parts: department share of sales (12 slices), comp and non-comp, channel mix, top 5 and Other,
// details ring, dark, zero and blank slices. Data from retail_data.js.
const deptTY = RT.departments.map((_, i) => RT.round(RT.total * RT.deptShare[i], 0));
const compTY = RT.sum(RT.stores.filter(s => s.comp), s => s.sales), nonComp = RT.sum(RT.stores.filter(s => !s.comp), s => s.sales);
// 0 department share, outside labels with leader lines
C('Donut - share of sales by department (12)', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Net Sales', values: deptTY }], fmt: FMT.usd, type: 'donut', objects: { slices: { content: 'categoryPercent' }, legend: { show: false } } }), { w: 620, h: 380 });
// 1 comp and non-comp, total in the center
C('Donut - comp and non-comp sales, total in the center', RDV({ cats: [{ name: 'Store type', values: ['Comp stores', 'Non-comp stores'] }], measures: [{ name: 'Net Sales', values: [compTY, nonComp] }], fmt: FMT.usd, type: 'donut', objects: { slices: { centerTotal: true, content: 'all' } } }), { w: 480, h: 300 });
// 2 channel mix pie
C('Pie - sales by channel', RDV({ cats: [{ name: 'Channel', values: ['In store', 'Pickup', 'Delivery', 'Ship to home'] }], measures: [{ name: 'Net Sales', values: [4.21e9, 0.262e9, 0.158e9, 0.021e9] }], fmt: FMT.usd, type: 'pie', objects: { slices: { content: 'categoryValue' } } }), { w: 480, h: 300 });
// 3 top 5 divisions and Other
C('Donut - top 5 divisions and Other', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: RT.divisions.map(d => RT.sum(RT.div(d), s => s.sales)) }], fmt: FMT.usd, type: 'donut', objects: { chart: { topN: 5 }, legend: { position: 'right' } } }), { w: 620, h: 320 });
// 4 details ring: own and national brands within departments
C('Donut - details ring, brand type in each department', RDV({ cats: [{ name: 'Department', values: RT.departments.slice(0, 5) }], series: { name: 'Brand type', groups: [{ name: 'Own brands', values: deptTY.slice(0, 5).map((v, i) => RT.round(v * (0.2 + i * 0.03), 0)) }, { name: 'National brands', values: deptTY.slice(0, 5).map((v, i) => RT.round(v * (0.8 - i * 0.03), 0)) }] }, measure: 'Net Sales', fmt: FMT.usd, type: 'donut', objects: { slices: { labelPosition: 'auto', content: 'percent' } } }), { w: 560, h: 340 });
// 5 dark
C('Donut - dark, tender mix', RDV({ cats: [{ name: 'Tender', values: ['Credit card', 'Debit card', 'Cash', 'SNAP and EBT', 'Mobile wallet', 'Gift card'] }], measures: [{ name: 'Transactions', values: [48200000, 39100000, 14900000, 8800000, 6100000, 900000] }], fmt: FMT.num, type: 'donut' }), { dark: true, w: 560, h: 320 });
// 6 zero and blank slices
C('Pie - zero and blank slices', RDV({ cats: [{ name: 'Fuel center', values: ['Has fuel', 'No fuel', 'Opening soon', 'Unknown'] }], measures: [{ name: 'Fuel Sales', values: [612000000, 0, null, 41000] }], fmt: FMT.usd, type: 'pie', objects: { slices: { content: 'categoryPercent' } } }), { w: 420, h: 260 });
// 7 small tile
C('Donut - small tile, 12 departments', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Net Sales', values: deptTY }], fmt: FMT.usd, type: 'donut' }), { w: 300, h: 200 });
