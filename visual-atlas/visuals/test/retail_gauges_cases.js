// Retail cases for Relay Gauges: an executive summary's KPI tiles (dollars in billions, comp % and margin % against plan
// and last year, lower-is-better shrink), bullets vs plan for divisions and 120 stores, gauges and dials for in-stock and
// OTIF, penetration rings, a division ticker, dark, small tiles, zeros and blanks. Data from retail_data.js.
const T = 'Plan', last = a => a[a.length - 1];
const w13 = RT.weeks.slice(-13), s13 = RT.weekly.slice(-13), l13 = RT.weeklyLY.slice(-13), p13 = RT.weeklyPlan.slice(-13);
const divSales = RT.divisions.map(d => RT.sum(RT.div(d), s => s.sales)), divPlan = RT.divisions.map(d => RT.sum(RT.div(d), s => s.plan));
const divLY = RT.divisions.map(d => RT.sum(RT.div(d).filter(s => s.ly), s => s.ly) + RT.sum(RT.div(d).filter(s => !s.ly), s => s.sales * 0.2));
const kpiTile = (name, values, o) => RDV({ cats: o.trend ? [{ name: 'Fiscal week', role: 'trend', values: o.trend }] : [], measures: [{ name, values, fmt: o.fmt }].concat(o.target ? [{ name: T, role: 'target', values: o.target }] : []).concat(o.compare ? [{ name: name + ' LY', role: 'compare', values: o.compare }] : []), type: o.type || 'kpi', objects: o.objects });
// 0 card: total sales in billions against plan
C('Card - net sales vs plan (billions)', kpiTile('Net Sales', [RT.total], { fmt: FMT.usd, target: [RT.total * 1.008], type: 'card' }), { w: 300, h: 160 });
// 1 KPI: weekly net sales, 13-week trend and plan
C('KPI - net sales this week, trend and plan', kpiTile('Net Sales', s13, { fmt: FMT.usd, trend: w13, target: p13 }), { w: 300, h: 170 });
// 2 KPI: a rate against a rate target (comp %): the change is in points
C('KPI - identical store sales % vs plan (points)', kpiTile('Identical Store Sales %', s13.map((v, i) => RT.round(v / l13[i] - 1, 4)), { fmt: FMT.comp, trend: w13, target: w13.map(() => 0.025) }), { w: 300, h: 170 });
// 3 KPI: shrink %, lower is better, goal
C('KPI - shrink %, lower is better', kpiTile('Shrink %', w13.map((_, i) => RT.round(0.0231 - i * 0.0002, 4)), { fmt: FMT.pct, trend: w13, target: w13.map(() => 0.021), objects: { status: { direction: 'lower' } } }), { w: 300, h: 170 });
// 4 bullet: division sales vs plan, long names
C('Bullet - division sales vs plan', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: T, role: 'target', values: divPlan }], type: 'bullet', objects: { status: { colorValue: true } } }), { w: 620, h: 340 });
// 5 bullet: 120 stores vs plan (crowded)
C('Bullet - 120 stores vs plan', RDV({ cats: [{ name: 'Store', values: RT.stores.map(s => s.name) }], measures: [{ name: 'Net Sales', values: RT.stores.map(s => s.sales), fmt: FMT.usd }, { name: T, role: 'target', values: RT.stores.map(s => s.plan) }], type: 'bullet' }), { w: 620, h: 420 });
// 6 multi-row card: divisions with plan
C('Multi-row card - divisions vs plan', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: T, role: 'target', values: divPlan }], type: 'multirow' }), { w: 620, h: 360 });
// 7 gauge: in-stock % against 95% on an 85-100% scale
C('Gauge - in-stock % vs 95% target', kpiTile('In-Stock Rate %', [0.9412], { fmt: FMT.pct, target: [0.95], type: 'gauge', objects: { scale: { min: '0.85', max: '1' } } }), { w: 320, h: 220 });
// 8 dial: OTIF % with bands
C('Dial - on-time in-full % with bands', RDV({ measures: [{ name: 'On-Time In-Full %', values: [0.874], fmt: FMT.pct }, { name: T, role: 'target', values: [0.9] }, { name: 'Min', role: 'minValue', values: [0.6] }, { name: 'Max', role: 'maxValue', values: [1] }, { name: 'Fair', role: 'band1', values: [0.8] }, { name: 'Good', role: 'band2', values: [0.9] }], type: 'dial', objects: { scale: { angle: '240' } } }), { w: 320, h: 240 });
// 9 radial bars: penetration vs target
C('Radial bars - penetration vs target', RDV({ cats: [{ name: 'KPI', values: ['Own brands penetration', 'Digital penetration', 'Loyalty penetration'] }], measures: [{ name: 'Actual', values: [0.284, 0.083, 0.712], fmt: FMT.pct }, { name: T, role: 'target', values: [0.3, 0.09, 0.7] }], type: 'radialBar' }), { w: 420, h: 300 });
// 10 liquid: fill rate
C('Liquid - DC fill rate %', kpiTile('Fill Rate %', [0.962], { fmt: FMT.pct, type: 'liquid', objects: { scale: { max: '1' } } }), { w: 260, h: 220 });
// 11 ticker: division comps
C('Ticker - division sales vs plan', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: T, role: 'target', values: divPlan }], type: 'ticker' }), { w: 620, h: 80 });
// 12 dark KPI
C('KPI - dark, average basket', kpiTile('Average Basket Value', w13.map((_, i) => RT.round(46.1 + i * 0.12, 2)), { fmt: FMT.usd2, trend: w13, target: w13.map(() => 47) }), { dark: true, w: 300, h: 170 });
// 13 zero value and blank target
C('Card - zero value, blank target', RDV({ measures: [{ name: 'Fuel Sales', values: [0], fmt: FMT.usd }, { name: T, role: 'target', values: [null] }], type: 'card' }), { w: 300, h: 160 });
// 14 small tile in billions
C('KPI - small tile, year to date sales', kpiTile('Net Sales YTD', [RT.total], { fmt: FMT.usd, target: [RT.total * 0.991] }), { w: 220, h: 110 });
// 15 cards: four measures in one visual
C('Cards - transactions, basket, units per basket, GM %', RDV({ measures: [{ name: 'Transactions', values: [118400000], fmt: FMT.num }, { name: 'Average Basket Value', values: [47.12], fmt: FMT.usd2 }, { name: 'Units per Transaction', values: [9.4], fmt: FMT.dec }, { name: 'Gross Margin %', values: [0.2843], fmt: FMT.pct }], type: 'card' }), { w: 620, h: 160 });
// ---- the comparison (last year) and the leaderboard, new on 2026-11-19
// 16-18 KPI tiles against plan and last year: an amount, a rate (points), lower is better
C('KPI - net sales vs plan and LY', kpiTile('Net Sales', s13, { fmt: FMT.usd, trend: w13, target: p13, compare: l13, objects: { status: { targetLabel: 'plan' } } }), { w: 300, h: 170 });
C('KPI - gross margin % vs plan and LY (points)', kpiTile('Gross Margin %', w13.map((_, i) => RT.round(0.2831 + i * 0.0004, 4)), { fmt: FMT.pct, trend: w13, target: w13.map(() => 0.2875), compare: w13.map(() => 0.2802), objects: { status: { targetLabel: 'plan' } } }), { w: 300, h: 170 });
C('KPI - shrink % vs plan and LY, lower is better, low tile', kpiTile('Shrink %', w13.map((_, i) => RT.round(0.0231 - i * 0.0002, 4)), { fmt: FMT.pct, trend: w13, target: w13.map(() => 0.021), compare: w13.map(() => 0.0244), objects: { status: { direction: 'lower', targetLabel: 'plan' } } }), { w: 270, h: 110 });
// 19 card with both, 20 card with last year only
C('Card - net sales vs plan and LY', kpiTile('Net Sales', [RT.total], { fmt: FMT.usd, target: [RT.total * 1.008], compare: [RT.totalLY], type: 'card', objects: { status: { targetLabel: 'plan' } } }), { w: 300, h: 160 });
C('Card - transactions vs LY only', kpiTile('Transactions', [118400000], { fmt: FMT.num, compare: [121900000], type: 'card' }), { w: 300, h: 140 });
// 21 multi-row card: divisions vs plan and LY
C('Multi-row card - divisions vs plan and LY', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: 'Plan', role: 'target', values: divPlan }, { name: 'Net Sales LY', role: 'compare', values: divLY }], type: 'multirow', objects: { status: { targetLabel: 'plan' } } }), { w: 620, h: 360 });
// 22 leaderboard: 120 stores, latest week, plan, LY and a 13-week sparkline (1,560 rows); scrolls
const lbRows = []; RT.stores.forEach((s, k) => w13.forEach((wk, j) => lbRows.push({ s, wk, v: RT.round(s.sales / 52 * RT.season(39 + j) * (0.97 + ((k * 7 + j * 3) % 7) * 0.01), 0), p: RT.round(s.plan / 52 * RT.season(39 + j), 0), ly: s.ly ? RT.round(s.ly / 52 * RT.season(39 + j), 0) : null })));
C('Leaderboard - 120 stores, latest week vs plan and LY, trend (scrolls)', RDV({ cats: [{ name: 'Store', values: lbRows.map(r => r.s.name) }, { name: 'Fiscal week', role: 'trend', values: lbRows.map(r => r.wk) }], measures: [{ name: 'Net Sales', values: lbRows.map(r => r.v), fmt: FMT.usd }, { name: 'Plan', role: 'target', values: lbRows.map(r => r.p) }, { name: 'Net Sales LY', role: 'compare', values: lbRows.map(r => r.ly) }], type: 'leaderboard', objects: { status: { targetLabel: 'plan' } } }), { w: 620, h: 420 });
// 23 bottom 10 stores by comp % (rates, negatives), lowest first, no bars of their own sign confusion
const cs = RT.stores.filter(s => s.ly);
C('Leaderboard - bottom 10 stores by comp %', RDV({ cats: [{ name: 'Store', values: cs.map(s => s.name) }], measures: [{ name: 'Identical Store Sales %', values: cs.map(s => RT.round(s.sales / s.ly - 1, 4)), fmt: FMT.comp }, { name: 'Plan', role: 'target', values: cs.map(() => 0.02) }], type: 'leaderboard', objects: { leaderboard: { sort: 'valueAsc', topN: 10 }, status: { targetLabel: 'plan' } } }), { w: 560, h: 320 });
// 24 divisions, dark, long names, worst against plan first
C('Leaderboard - dark, divisions worst against plan first', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: 'Plan', role: 'target', values: divPlan }, { name: 'Net Sales LY', role: 'compare', values: divLY }], type: 'leaderboard', objects: { leaderboard: { sort: 'targetAsc' }, status: { targetLabel: 'plan' } } }), { dark: true, w: 620, h: 300 });
// 25 zeros (no fuel center) and blanks (no last year)
C('Leaderboard - fuel sales with zeros and blanks', RDV({ cats: [{ name: 'Store', values: RT.stores.slice(0, 12).map(s => s.name) }], measures: [{ name: 'Fuel Sales', values: RT.stores.slice(0, 12).map(s => s.fuel), fmt: FMT.usd }, { name: 'Fuel Sales LY', role: 'compare', values: RT.stores.slice(0, 12).map(s => (s.ly ? RT.round(s.fuel * 0.96, 0) : null)) }], type: 'leaderboard' }), { w: 560, h: 320 });
// 26 small tile: the sparkline and then the bars give way
C('Leaderboard - small tile', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: 'Plan', role: 'target', values: divPlan }, { name: 'Net Sales LY', role: 'compare', values: divLY }], type: 'leaderboard' }), { w: 300, h: 200 });
// 27 gauge of a rate against plan and LY
C('Gauge - in-stock % vs plan and LY', kpiTile('In-Stock Rate %', [0.9412], { fmt: FMT.pct, target: [0.95], compare: [0.9381], type: 'gauge', objects: { scale: { min: '0.85', max: '1' }, status: { targetLabel: 'plan' } } }), { w: 320, h: 220 });
// 28 ticker with last year only
C('Ticker - division sales vs LY', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: 'Net Sales LY', role: 'compare', values: divLY }], type: 'ticker' }), { w: 620, h: 80 });
// 29 bullets with the change against plan, 120 stores scroll
C('Bullet - divisions vs plan, change shown', RDV({ cats: [{ name: 'Division', values: RT.divisions }], measures: [{ name: 'Net Sales', values: divSales, fmt: FMT.usd }, { name: T, role: 'target', values: divPlan }], type: 'bullet', objects: { status: { colorValue: true } } }), { dark: true, w: 620, h: 340 });
