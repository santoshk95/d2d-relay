// Retail cases for Relay Proportion: own brands penetration as a waffle, area by division mekko, members per 10
// shoppers, in-stock scores as an aster plot, a rose, dark. Data from retail_data.js.
const deptTY = RT.departments.map((_, i) => RT.round(RT.total * RT.deptShare[i], 0));
const periods = Array.from({ length: 13 }, (_, i) => 'P' + String(i + 1).padStart(2, '0'));
// 0 waffle: one percentage
C('Waffle - own brands penetration', RDV({ cats: [{ name: 'Metric', values: ['of sales are own brands'] }], measures: [{ name: 'Own Brands Penetration %', values: [0.284] }], fmt: FMT.pct, type: 'waffle' }), { w: 420, h: 280 });
// 1 mekko: area mix within each division
C('Mekko - fresh, center store and pharmacy by division', RDV({ cats: [{ name: 'Division', values: RT.divisions }], series: { name: 'Area', groups: [['Fresh', 0.41], ['Center store', 0.44], ['Pharmacy and HBC', 0.15]].map(([n, k], j) => ({ name: n, values: RT.divisions.map((d, i) => RT.round(RT.sum(RT.div(d), s => s.sales) * (k + (j - 1) * (i % 3) * 0.02), 0)) })) }, measure: 'Net Sales', fmt: FMT.usd, type: 'mekko' }), { w: 620, h: 360 });
// 2 pictogram: members per 10 shoppers
C('Pictogram - 7 in 10 shoppers are loyalty members', RDV({ cats: [{ name: 'Group', values: ['shoppers scan a loyalty card'] }], measures: [{ name: 'Members', values: [7] }, { name: 'Shoppers', values: [10] }], type: 'pictogram' }), { w: 420, h: 220 });
// 3 aster: in-stock % by department
C('Aster - in-stock % by department', RDV({ cats: [{ name: 'Department', values: RT.departments.slice(0, 8) }], measures: [{ name: 'In-Stock Rate %', values: RT.departments.slice(0, 8).map((_, i) => RT.round(0.91 + i * 0.009, 4)) }], fmt: FMT.pct, type: 'aster' }), { w: 480, h: 340 });
// 4 rose: sales by period, dark
C('Rose - dark, sales by period', RDV({ cats: [{ name: 'Period', values: periods }], measures: [{ name: 'Net Sales', values: periods.map((_, i) => RT.round(RT.total / 13 * (1 + 0.08 * Math.sin(i / 2)), 0)) }], fmt: FMT.usd, type: 'rose', objects: { radial: { shadeByValue: true } } }), { dark: true, w: 480, h: 340 });
// 5 waffle: department shares
C('Waffle - department shares', RDV({ cats: [{ name: 'Department', values: RT.departments.slice(0, 6) }], measures: [{ name: 'Net Sales', values: deptTY.slice(0, 6) }], fmt: FMT.usd, type: 'waffle', objects: { waffle: { bigNumber: false } } }), { w: 560, h: 300 });
