// Retail cases for Relay Scatter: 120 stores (sales vs comp %, bubbles, quadrants), labor productivity, shrink vs sales
// with a trend, comp % by division as a dot plot, dark. Data from retail_data.js.
const st = RT.stores, compOf = s => (s.ly ? RT.round(s.sales / s.ly - 1, 4) : null);
// 0 sales vs comp %, bubble size transactions, quadrants, division legend
C('Bubble - 120 stores, sales vs comp %, quadrants', RDV({ cats: [{ name: 'Store', role: 'details', values: st.map(s => s.name) }, { name: 'Division', role: 'legend', values: st.map(s => s.division) }], measures: [{ name: 'Net Sales', role: 'x', values: st.map(s => s.sales), fmt: FMT.usd }, { name: 'Identical Store Sales %', role: 'y', values: st.map(compOf), fmt: FMT.comp }, { name: 'Transactions', role: 'size', values: st.map(s => s.tx) }], type: 'scatter', objects: { guides: { quadrants: true } } }), { w: 620, h: 400 });
// 1 labor: hours vs sales per labor hour, labels
const lab = st.slice(0, 30);
C('Scatter - labor hours vs sales per labor hour, labels', RDV({ cats: [{ name: 'Store', role: 'details', values: lab.map(s => s.short) }], measures: [{ name: 'Labor Hours', role: 'x', values: lab.map(s => RT.round(s.sales / s.splh, 0)), fmt: FMT.num }, { name: 'Sales per Labor Hour', role: 'y', values: lab.map(s => s.splh), fmt: FMT.usd2 }], type: 'scatter', objects: { labels: { show: true } } }), { w: 620, h: 380 });
// 2 shrink % vs sales with a trend line
C('Scatter - shrink % vs sales, trend', RDV({ cats: [{ name: 'Store', role: 'details', values: st.map(s => s.name) }], measures: [{ name: 'Net Sales', role: 'x', values: st.map(s => s.sales), fmt: FMT.usd }, { name: 'Shrink %', role: 'y', values: st.map(s => s.shrink), fmt: FMT.pct }], type: 'scatter', objects: { guides: { trend: true } } }), { w: 560, h: 340 });
// 3 dot plot: comp % of stores by division
const cs = st.filter(s => s.ly);
C('Dot plot - store comp % by division', RDV({ cats: [{ name: 'Store', role: 'details', values: cs.map(s => s.name) }, { name: 'Division', role: 'xCategory', values: cs.map(s => s.division) }], measures: [{ name: 'Identical Store Sales %', role: 'y', values: cs.map(compOf), fmt: FMT.comp }], type: 'dotplot' }), { w: 620, h: 360 });
// 4 dark: digital penetration vs average basket
C('Scatter - dark, digital penetration vs basket', RDV({ cats: [{ name: 'Store', role: 'details', values: st.slice(0, 60).map(s => s.name) }], measures: [{ name: 'Digital Sales Penetration %', role: 'x', values: st.slice(0, 60).map(s => s.digital), fmt: FMT.pct }, { name: 'Average Basket Value', role: 'y', values: st.slice(0, 60).map(s => RT.round(s.sales / s.tx, 2)), fmt: FMT.usd2 }], type: 'scatter' }), { dark: true, w: 560, h: 340 });
