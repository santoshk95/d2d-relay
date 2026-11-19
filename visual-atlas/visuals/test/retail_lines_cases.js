// Retail cases for Relay Lines: TY vs LY (dashed) vs plan, sales and comp % combo, in-stock % against a target line,
// penetration trends, 8 divisions with long names, zero and blank weeks, dark and small. Data from retail_data.js.
const CT = t => ({ chart: { chartType: t } });
const comp = RT.weekly.map((v, i) => RT.round(v / RT.weeklyLY[i] - 1, 4));
const periods = Array.from({ length: 13 }, (_, i) => 'P' + String(i + 1).padStart(2, '0'));
const per = arr => periods.map((_, p) => arr.slice(p * 4, p * 4 + 4).reduce((a, b) => a + b, 0));
// 0 TY, LY dashed, plan dotted-ish, end labels
C('Line - weekly sales TY vs LY vs plan', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks }], measures: [{ name: 'Net Sales', values: RT.weekly }, { name: 'Net Sales LY', values: RT.weeklyLY }, { name: 'Plan', values: RT.weeklyPlan }], fmt: FMT.usd, objects: { lines: { dashed: 'Net Sales LY, Plan', endLabels: true } } }), { w: 620, h: 320 });
// 1 sales columns and comp % line on the secondary axis
C('Combo - weekly sales and comp % (secondary axis)', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks }], measures: [{ name: 'Net Sales', values: RT.weekly }, { name: 'Identical Store Sales %', role: 'lineValues', values: comp, fmt: FMT.comp }], fmt: FMT.usd, objects: Object.assign(CT('comboClustered'), { lines: { secondary: true } }) }), { w: 620, h: 320 });
// 2 in-stock % with a 95% target line
C('Line - in-stock % with a 95% target', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks }], measures: [{ name: 'In-Stock Rate %', values: RT.weeks.map((_, i) => RT.round(0.943 + 0.02 * Math.sin(i / 5) - (i > 44 && i < 48 ? 0.031 : 0), 4)) }], fmt: FMT.pct, objects: { analytics: { target: '0.95' }, labels: { show: false } } }), { w: 560, h: 300 });
// 3 digital and loyalty penetration by period, labels
C('Line - digital and loyalty penetration by period', RDV({ cats: [{ name: 'Period', values: periods }], measures: [{ name: 'Digital Sales Penetration %', values: periods.map((_, i) => RT.round(0.071 + i * 0.0021, 4)) }, { name: 'Loyalty Sales Penetration %', values: periods.map((_, i) => RT.round(0.682 + i * 0.0035, 4)) }], fmt: FMT.pct, objects: { labels: { show: true } } }), { w: 560, h: 320 });
// 4 stacked area: sales by division by period
C('Stacked area - sales by division by period', RDV({ cats: [{ name: 'Period', values: periods }], series: { name: 'Division', groups: RT.divisions.map((d, k) => ({ name: d, values: per(RT.weekly).map(v => RT.round(v * RT.sum(RT.div(d), s => s.sales) / RT.total, 0)) })) }, measure: 'Net Sales', fmt: FMT.usd, type: 'stackedArea' }), { w: 620, h: 340 });
// 5 comp % by division, 8 lines with long names, negatives
C('Line - comp % by division (8 lines, long names)', RDV({ cats: [{ name: 'Period', values: periods }], series: { name: 'Division', groups: RT.divisions.map((d, k) => ({ name: d, values: periods.map((_, i) => RT.round(0.012 + 0.018 * Math.sin(i / 3 + k) - k * 0.002, 4)) })) }, measure: 'Identical Store Sales %', fmt: FMT.comp }), { w: 620, h: 340 });
// 6 dark theme, scripts filled TY vs LY
C('Line - dark, prescriptions TY vs LY', RDV({ cats: [{ name: 'Period', values: periods }], measures: [{ name: 'Prescriptions Filled', values: periods.map((_, i) => 1842000 + i * 21000 + (i % 3) * 9000) }, { name: 'Prescriptions LY', values: periods.map((_, i) => 1801000 + i * 18000) }], fmt: FMT.num, objects: { lines: { dashed: 'Prescriptions LY' } } }), { dark: true, w: 560, h: 300 });
// 7 a store closed for a remodel: zero weeks, blank weeks before it reopened
C('Line - a remodel: zero and blank weeks', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks.slice(0, 20) }], measures: [{ name: 'Net Sales', values: RT.weeks.slice(0, 20).map((_, i) => (i >= 8 && i < 11 ? 0 : i >= 11 && i < 13 ? null : 612000 + i * 3100)) }], fmt: FMT.usd, objects: { labels: { show: true } } }), { w: 560, h: 300 });
// 8 fuel: gallons as columns, margin per gallon as a line
C('Combo - fuel gallons and margin per gallon', RDV({ cats: [{ name: 'Period', values: periods }], measures: [{ name: 'Fuel Gallons', values: periods.map((_, i) => 21400000 + (i % 4) * 900000) }, { name: 'Fuel Margin per Gallon', role: 'lineValues', values: periods.map((_, i) => RT.round(0.29 + (i % 5) * 0.03, 3)), fmt: FMT.usd2 }], fmt: FMT.num, objects: Object.assign(CT('comboClustered'), { lines: { secondary: true } }) }), { w: 560, h: 300 });
// 9 small tile
C('Line - small tile, weekly sales', RDV({ cats: [{ name: 'Fiscal week', values: RT.weeks }], measures: [{ name: 'Net Sales', values: RT.weekly }, { name: 'Net Sales LY', values: RT.weeklyLY }], fmt: FMT.usd, objects: { lines: { dashed: 'Net Sales LY' } } }), { w: 300, h: 190 });
