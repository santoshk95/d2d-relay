// Retail cases for Relay Finance: sales and margin bridges against last year, many steps, a digital order funnel,
// department ranks by period. Data from retail_data.js.
const deptGrowth = [0.021, 0.034, -0.012, 0.045, 0.018, 0.052, -0.008, 0.11, 0.027, -0.041, 0.015, 0.061];
const deptTY = RT.departments.map((_, i) => RT.round(RT.total * RT.deptShare[i], 0)), deptLY = deptTY.map((v, i) => RT.round(v / (1 + deptGrowth[i]), 0));
const lyTotal = deptLY.reduce((a, b) => a + b, 0);
// 0 the classic retail bridge: last year's sales, the change by department, this year
C('Waterfall - sales bridge LY to TY by department', RDV({ cats: [{ name: 'Department', values: ['Last year'].concat(RT.departments) }], measures: [{ name: 'Net Sales change', values: [lyTotal].concat(deptTY.map((v, i) => v - deptLY[i])) }], fmt: FMT.usd, type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'This year' }, labels: { show: true } } }), { w: 620, h: 360 });
// 1 comp bridge: comp growth, new stores, closed stores, in billions
C('Waterfall - comp bridge in billions', RDV({ cats: [{ name: 'Driver', values: ['Last year sales', 'Identical store growth', 'New stores (non-comp)', 'Closed and remodeled stores', 'Fuel price'] }], measures: [{ name: 'Sales', values: [4.62e9, 0.118e9, 0.064e9, -0.041e9, -0.023e9] }], fmt: FMT.usd, type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'This year sales' } } }), { w: 560, h: 320 });
// 2 gross margin rate walk in percentage points
C('Waterfall - gross margin % walk (points)', RDV({ cats: [{ name: 'Driver', values: ['Gross margin LY', 'Price investment', 'Mix (fresh, own brands)', 'Shrink', 'Markdowns', 'Vendor funding'] }], measures: [{ name: 'Gross margin %', values: [0.2791, -0.0034, 0.0021, -0.0012, 0.0008, 0.0019] }], fmt: FMT.pct, type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'Gross margin TY' }, labels: { show: true } } }), { w: 560, h: 320 });
// 3 52 weekly variances to plan: crowded axis
C('Waterfall - 52 weeks of variance to plan', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks }], measures: [{ name: 'Variance to plan', values: RT.weekly.map((v, i) => v - RT.weeklyPlan[i]) }], fmt: FMT.usd, type: 'waterfall', objects: { waterfall: { endLabel: 'Year to date' } } }), { w: 620, h: 320 });
// 4 digital order funnel with conversion
C('Funnel - digital orders, % of first', RDV({ cats: [{ name: 'Step', values: ['Sessions', 'Product views', 'Added to cart', 'Checkout started', 'Orders placed', 'Orders picked up or delivered'] }], measures: [{ name: 'Shoppers', values: [18400000, 9650000, 3120000, 1480000, 1210000, 1188000] }], type: 'funnel', objects: { funnel: { content: 'first', conversion: true } } }), { w: 560, h: 320 });
// 5 funnel, % of previous step, tapered
C('Funnel - tapered, % of previous', RDV({ cats: [{ name: 'Step', values: ['Coupons clipped', 'Coupons redeemed', 'Repeat purchase'] }], measures: [{ name: 'Members', values: [2450000, 1310000, 402000] }], type: 'funnel', objects: { funnel: { shape: 'tapered', content: 'previous' } } }), { w: 420, h: 260 });
// 6 ribbon: department ranks by period
const periods = Array.from({ length: 13 }, (_, i) => 'P' + String(i + 1).padStart(2, '0'));
C('Ribbon - department sales rank by period', RDV({ cats: [{ name: 'Period', values: periods }], series: { name: 'Department', groups: RT.departments.slice(0, 6).map((d, k) => ({ name: d, values: periods.map((_, j) => RT.round(deptTY[k] / 13 * (1 + 0.08 * Math.sin(j / 2 + k)), 0)) })) }, measure: 'Net Sales', fmt: FMT.usd, type: 'ribbon', objects: { labels: { show: false } } }), { w: 620, h: 320 });
// 7 dark theme bridge with long driver names
C('Waterfall - dark, long driver names', RDV({ cats: [{ name: 'Driver', values: ['Last year', 'Southern California Division', 'Northern California Division', 'Pacific Northwest Division', 'Rocky Mountain Division', 'Southwest Division'] }], measures: [{ name: 'Sales change', values: [1.84e9, 0.031e9, -0.012e9, 0.022e9, -0.004e9, 0.009e9] }], fmt: FMT.usd, type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'This year' } } }), { dark: true, w: 560, h: 320 });
// 8 a step of zero and a blank step
C('Waterfall - a zero step and a blank step', RDV({ cats: [{ name: 'Driver', values: ['Last year', 'Price', 'Volume', 'Fuel', 'New stores'] }], measures: [{ name: 'Sales change', values: [412000000, 6100000, 0, null, 2200000] }], fmt: FMT.usd, type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'This year' }, labels: { show: true } } }), { w: 480, h: 280 });
// 9 small tile
C('Waterfall - small tile', RDV({ cats: [{ name: 'Department', values: ['Last year'].concat(RT.departments.slice(0, 6)) }], measures: [{ name: 'Change', values: [lyTotal].concat(deptTY.slice(0, 6).map((v, i) => v - deptLY[i])) }], fmt: FMT.usd, type: 'waterfall', objects: { waterfall: { startTotal: true, endLabel: 'TY' } } }), { w: 300, h: 190 });
