// Retail cases for Relay Compare: LY to TY dumbbells (dollars and percentages), variance lollipops colored by sign,
// vendor fill rates, slopes and bumps by department and division, dark. Data from retail_data.js.
const deptGrowth = [0.021, 0.034, -0.012, 0.045, 0.018, 0.052, -0.008, 0.11, 0.027, -0.041, 0.015, 0.061];
const deptTY = RT.departments.map((_, i) => RT.round(RT.total * RT.deptShare[i], 0)), deptLY = deptTY.map((v, i) => RT.round(v / (1 + deptGrowth[i]), 0));
const gmTY = RT.departments.map((_, i) => RT.round(0.22 + (i % 6) * 0.031, 4)), gmLY = gmTY.map((v, i) => RT.round(v - 0.006 + (i % 4) * 0.004, 4));
const vendors = ['Golden Valley Farms Cooperative', 'Northwest Dairy Partners', 'Sunrise Bakery Supply', 'Pacific Seafood Distributors', 'Mountain Fresh Produce', 'Heritage Meats Inc', 'Bright Home Essentials', 'Clearwater Beverages', 'Prairie Grain Mills', 'Coastal Floral Wholesale', 'Evergreen Health Products', 'Metro Frozen Foods'];
const periods = Array.from({ length: 13 }, (_, i) => 'P' + String(i + 1).padStart(2, '0'));
// 0 dumbbell: department sales LY to TY, sorted by change
C('Dumbbell - department sales LY to TY', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Net Sales LY', values: deptLY }, { name: 'Net Sales', values: deptTY }], fmt: FMT.usd, type: 'dumbbell', objects: { chart: { sort: 'changeDesc' }, labels: { show: true } } }), { w: 620, h: 380 });
// 1 dumbbell of rates: the change is in points
C('Dumbbell - gross margin % LY to TY (points)', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Gross Margin % LY', values: gmLY }, { name: 'Gross Margin %', values: gmTY }], fmt: FMT.pct, type: 'dumbbell', objects: { labels: { show: true } } }), { w: 620, h: 380 });
// 2 lollipop colored by sign: sales vs LY by department
C('Lollipop - sales vs LY by department, colored by sign', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Sales vs LY', values: deptTY.map((v, i) => v - deptLY[i]) }], fmt: FMT.usd, type: 'lollipop', objects: { marks: { colorBy: 'sign' }, chart: { sort: 'valueDesc' }, labels: { show: true } } }), { w: 620, h: 380 });
// 3 lollipop: fill rate % by vendor, long names
C('Lollipop - fill rate % by vendor (long names)', RDV({ cats: [{ name: 'Vendor', values: vendors }], measures: [{ name: 'Fill Rate %', values: vendors.map((_, i) => RT.round(0.912 + (i * 37 % 80) / 1000, 4)) }], fmt: FMT.pct, type: 'lollipop', objects: { chart: { sort: 'valueAsc' }, labels: { show: true } } }), { w: 620, h: 380 });
// 4 slope: own brands penetration LY to TY
C('Slope - own brands penetration LY to TY', RDV({ cats: [{ name: 'Department', values: RT.departments.slice(0, 8) }], measures: [{ name: 'Own Brands % LY', values: RT.departments.slice(0, 8).map((_, i) => RT.round(0.21 + i * 0.012, 4)) }, { name: 'Own Brands %', values: RT.departments.slice(0, 8).map((_, i) => RT.round(0.22 + i * 0.011 + (i % 3) * 0.004, 4)) }], fmt: FMT.pct, type: 'slope', objects: { labels: { show: true } } }), { w: 560, h: 380 });
// 5 bump: division rank by period
C('Bump - division sales rank by period', RDV({ cats: [{ name: 'Period', values: periods }], series: { name: 'Division', groups: RT.divisions.map((d, k) => ({ name: d, values: periods.map((_, j) => RT.round(RT.sum(RT.div(d), s => s.sales) / 13 * (1 + 0.05 * Math.sin(j / 2 + k * 1.7)), 0)) })) }, measure: 'Net Sales', fmt: FMT.usd, type: 'bump' }), { w: 620, h: 360 });
// 6 tornado: TY vs LY by department
C('Tornado - department sales TY and LY', RDV({ cats: [{ name: 'Department', values: RT.departments }], measures: [{ name: 'Net Sales LY', values: deptLY }, { name: 'Net Sales', values: deptTY }], fmt: FMT.usd, type: 'tornado', objects: { labels: { show: true } } }), { w: 620, h: 380 });
// 7 dumbbell of comps that cross zero
C('Dumbbell - comp % LY to TY by division (crosses zero)', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Comp % LY', values: RT.divisions.map((_, i) => RT.round(-0.021 + i * 0.006, 4)) }, { name: 'Comp %', values: RT.divisions.map((_, i) => RT.round(0.031 - i * 0.007, 4)) }], fmt: FMT.comp, type: 'dumbbell', objects: { labels: { show: true } } }), { w: 620, h: 340 });
// 8 dark, dot plot by quarter
C('Dot plot - dark, division sales by quarter', RDV({ cats: [{ name: 'Division', values: RT.divisions }], series: { name: 'Quarter', groups: ['Q1', 'Q2', 'Q3', 'Q4'].map((q, k) => ({ name: q, values: RT.divisions.map(d => RT.round(RT.sum(RT.div(d), s => s.sales) / 4 * (0.95 + k * 0.03), 0)) })) }, measure: 'Net Sales', fmt: FMT.usd, type: 'dot' }), { dark: true, w: 620, h: 360 });
// 9 small tile lollipop with zero and blank
C('Lollipop - small tile, zero and blank', RDV({ cats: [{ name: 'Store', values: RT.stores.slice(0, 6).map(s => s.short) }], measures: [{ name: 'Fuel Sales', values: RT.stores.slice(0, 6).map((s, i) => (i === 2 ? null : s.fuel)) }], fmt: FMT.usd, type: 'lollipop', objects: { labels: { show: true } } }), { w: 300, h: 200 });
