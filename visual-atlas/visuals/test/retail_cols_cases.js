// Retail cases for Relay Columns: weeks TY vs LY, departments vs plan, 120 stores ranked, comp % by division (negatives),
// share and comp / non-comp splits, zero and blank values, dark and small. Data from retail_data.js.
const CT = t => ({ chart: { chartType: t } });
const deptGrowth = [0.021, 0.034, -0.012, 0.045, 0.018, 0.052, -0.008, 0.11, 0.027, -0.041, 0.015, 0.061];
const deptTY = RT.departments.map((_, i) => RT.round(RT.total * RT.deptShare[i], 0)), deptLY = deptTY.map((v, i) => RT.round(v / (1 + deptGrowth[i]), 0));
const deptPlan = deptTY.map((v, i) => RT.round(v * (0.98 + (i % 5) * 0.012), 0));
const ranked = RT.stores.slice().sort((a, b) => b.sales - a.sales);
const divComp = RT.divisions.map(d => { const l = RT.div(d).filter(s => s.comp); return RT.sum(l, s => s.sales) / RT.sum(l, s => s.ly) - 1; });
// 0 weekly sales this year and last year, 52 weeks
C('Clustered column - weekly sales TY vs LY (52 weeks)', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks }], measures: [{ name: 'Net Sales', values: RT.weekly }, { name: 'Net Sales LY', values: RT.weeklyLY }], fmt: FMT.usd }), { w: 620, h: 320 });
// 1 departments: TY, LY and plan, bars with labels
C('Clustered bar - department sales TY, LY, plan', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Net Sales', values: deptTY }, { name: 'Net Sales LY', values: deptLY }, { name: 'Plan', values: deptPlan }], fmt: FMT.usd, objects: Object.assign(CT('clusteredBar'), { labels: { show: true } }) }), { w: 620, h: 420 });
// 2 120 stores ranked by sales, long names: scrolls
C('Bar - 120 stores ranked by sales (scrolls)', RDV({ cats: [{ name: 'Store', values: ranked.map(s => s.name) }], measures: [{ name: 'Net Sales', values: ranked.map(s => s.sales) }], fmt: FMT.usd, objects: Object.assign(CT('clusteredBar'), { labels: { show: true } }) }), { w: 560, h: 360 });
// 3 comp % by division, negatives, percent labels
C('Column - identical store sales % by division', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Identical Store Sales %', values: divComp.map(v => RT.round(v, 4)) }], fmt: FMT.comp, objects: { labels: { show: true } } }), { w: 560, h: 320 });
// 4 own brands vs national brands share by department (100% stacked bar)
C('100% stacked bar - own brands share by department', RDV({ cats: [{ name: 'Department', values: RT.departments.slice(0, 10) }], series: { name: 'Brand type', groups: [{ name: 'Own brands', values: deptTY.slice(0, 10).map((v, i) => RT.round(v * (0.18 + (i % 4) * 0.05), 0)) }, { name: 'National brands', values: deptTY.slice(0, 10).map((v, i) => RT.round(v * (0.82 - (i % 4) * 0.05), 0)) }] }, measure: 'Net Sales', fmt: FMT.usd, objects: Object.assign(CT('percentBar'), { labels: { show: true, content: 'percent' } }) }), { w: 560, h: 360 });
// 5 comp and non-comp sales by division (stacked column, totals)
C('Stacked column - comp and non-comp sales by division', RDV({ cats: [{ name: 'Division', values: RT.divisions }], series: { name: 'Store type', groups: [{ name: 'Comp stores', values: RT.divisions.map(d => RT.sum(RT.div(d).filter(s => s.comp), s => s.sales)) }, { name: 'Non-comp stores', values: RT.divisions.map(d => RT.sum(RT.div(d).filter(s => !s.comp), s => s.sales)) }] }, measure: 'Net Sales', fmt: FMT.usd, objects: Object.assign(CT('stackedColumn'), { totals: { show: true } }) }), { w: 620, h: 340 });
// 6 shrink % top 15 stores
const shrinky = RT.stores.slice().sort((a, b) => b.shrink - a.shrink).slice(0, 15);
C('Bar - shrink % top 15 stores', RDV({ cats: [{ name: 'Store', values: shrinky.map(s => s.name) }], measures: [{ name: 'Shrink %', values: shrinky.map(s => s.shrink) }], fmt: FMT.pct, objects: Object.assign(CT('clusteredBar'), { labels: { show: true } }) }), { w: 560, h: 360 });
// 7 variance to last year by department, dollars with negatives
C('Column - variance to LY by department', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Sales vs LY', values: deptTY.map((v, i) => v - deptLY[i]) }], fmt: FMT.usd, objects: { labels: { show: true } } }), { w: 620, h: 340 });
// 8 dark theme, stacked bar by division and department group
C('Stacked bar - dark, fresh and center store by division', RDV({ cats: [{ name: 'Division', values: RT.divisions }], series: { name: 'Area', groups: [{ name: 'Fresh', values: RT.divisions.map(d => RT.round(RT.sum(RT.div(d), s => s.sales) * 0.41, 0)) }, { name: 'Center store', values: RT.divisions.map(d => RT.round(RT.sum(RT.div(d), s => s.sales) * 0.44, 0)) }, { name: 'Pharmacy and HBC', values: RT.divisions.map(d => RT.round(RT.sum(RT.div(d), s => s.sales) * 0.15, 0)) }] }, measure: 'Net Sales', fmt: FMT.usd, objects: Object.assign(CT('stackedBar'), { labels: { show: true } }) }), { dark: true, w: 620, h: 340 });
// 9 zero and blank values (no fuel center, a new department)
C('Column - fuel sales with zeros and blanks', RDV({ cats: [{ name: 'Store', values: RT.stores.slice(0, 9).map(s => s.short) }], measures: [{ name: 'Fuel Sales', values: RT.stores.slice(0, 9).map((s, i) => (i === 4 ? null : s.fuel)) }], fmt: FMT.usd, objects: { labels: { show: true } } }), { w: 560, h: 300 });
// 10 small tile, average basket
C('Column - small tile, average basket', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Average Basket', values: RT.divisions.map((d, i) => RT.round(41 + i * 1.7, 2)) }], fmt: FMT.usd2, objects: { labels: { show: true } } }), { w: 300, h: 190 });
