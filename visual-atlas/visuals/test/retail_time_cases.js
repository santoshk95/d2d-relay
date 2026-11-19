// Retail cases for Relay Time: a fiscal year of daily sales (calendar), holiday month pages, in-stock % by store and
// department (120 rows), comp % by department and period (negatives), transactions by hour, a fiscal-week timeline,
// dark. Data from retail_data.js.
const periods = Array.from({ length: 13 }, (_, i) => 'P' + String(i + 1).padStart(2, '0'));
const grid = (rows, cols, f) => { const r = [], c = [], v = []; rows.forEach((a, i) => cols.forEach((b, j) => { r.push(a); c.push(b); v.push(f(i, j)); })); return { r, c, v }; };
// 0 daily sales, fiscal year, year view
C('Calendar - daily sales, fiscal year', RDV({ cats: [{ name: 'Date', role: 'time', values: RT.days, date: true }], measures: [{ name: 'Net Sales', values: RT.daily }], fmt: FMT.usd, type: 'calendar' }), { w: 620, h: 240 });
// 1 holiday months as pages, labels on
C('Calendar - Nov and Dec month pages, labels', RDV({ cats: [{ name: 'Date', role: 'time', values: RT.days.slice(272, 333), date: true }], measures: [{ name: 'Net Sales', values: RT.daily.slice(272, 333) }], fmt: FMT.usd, type: 'calendar', objects: { calendar: { view: 'month', weekStart: 'sunday' }, labels: { show: true } } }), { w: 620, h: 360 });
// 2 in-stock % for 120 stores by 12 departments
const ins = grid(RT.stores.map(s => s.name), RT.departments, (i, j) => RT.round(Math.min(0.995, RT.stores[i].instock + ((i * 7 + j * 13) % 9 - 4) * 0.004), 4));
C('Heat grid - in-stock % by store (120) and department', RDV({ cats: [{ name: 'Department', role: 'time', values: ins.c }, { name: 'Store', role: 'rows', values: ins.r }], measures: [{ name: 'In-Stock Rate %', values: ins.v }], fmt: FMT.pct, type: 'heatgrid' }), { w: 620, h: 420 });
// 3 in-stock % by division and department, labels
const ind = grid(RT.divisions, RT.departments, (i, j) => RT.round(0.93 + ((i * 5 + j * 3) % 11) * 0.005, 4));
C('Heat grid - in-stock % by division and department, labels', RDV({ cats: [{ name: 'Department', role: 'time', values: ind.c }, { name: 'Division', role: 'rows', values: ind.r }], measures: [{ name: 'In-Stock Rate %', values: ind.v }], fmt: FMT.pct, type: 'heatgrid', objects: { labels: { show: true } } }), { w: 620, h: 360 });
// 4 comp % by department and period, negatives
const cmp = grid(RT.departments, periods, (i, j) => RT.round(0.02 * Math.sin(i + j / 3) + (i === 9 ? -0.03 : 0), 4));
C('Heat grid - comp % by department and period (negatives)', RDV({ cats: [{ name: 'Period', role: 'time', values: cmp.c }, { name: 'Department', role: 'rows', values: cmp.r }], measures: [{ name: 'Identical Store Sales %', values: cmp.v }], fmt: FMT.comp, type: 'heatgrid', objects: { labels: { show: true } } }), { w: 620, h: 360 });
// 5 transactions by hour and weekday: punch card
const hours = Array.from({ length: 17 }, (_, h) => String(h + 6).padStart(2, '0') + ':00'), wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const tx = grid(wd, hours, (i, j) => Math.round(42000 * (i === 0 || i === 6 ? 1.2 : 1) * (Math.exp(-((j - 6) ** 2) / 10) + 0.8 * Math.exp(-((j - 11) ** 2) / 6) + 0.1)));
C('Punch card - transactions by hour and weekday', RDV({ cats: [{ name: 'Hour', role: 'time', values: tx.c }, { name: 'Weekday', role: 'rows', values: tx.r }], measures: [{ name: 'Transactions', values: tx.v }], fmt: FMT.num, type: 'heatgrid', objects: { heatgrid: { shape: 'circle' } } }), { w: 620, h: 300 });
// 6 timeline slicer on fiscal weeks (dates)
const wkDates = RT.weeks.map((_, i) => new Date(2025, 1, 2 + i * 7));
C('Timeline - fiscal weeks with value bars', RDV({ cats: [{ name: 'Week start', role: 'time', values: wkDates, date: true }], measures: [{ name: 'Net Sales', values: RT.weekly }], fmt: FMT.usd, type: 'timeline', objects: { timeline: { granularity: 'week' } } }), { w: 620, h: 160 });
// 7 dark heat grid, shrink % by division and quarter
const shr = grid(RT.divisions, ['Q1', 'Q2', 'Q3', 'Q4'], (i, j) => RT.round(0.014 + ((i * 3 + j * 5) % 7) * 0.003, 4));
C('Heat grid - dark, shrink % by division and quarter, labels', RDV({ cats: [{ name: 'Quarter', role: 'time', values: shr.c }, { name: 'Division', role: 'rows', values: shr.r }], measures: [{ name: 'Shrink %', values: shr.v }], fmt: FMT.pct, type: 'heatgrid', objects: { labels: { show: true } } }), { dark: true, w: 560, h: 340 });
// 8 stream: sales by area by period
C('Stream - sales by department by period', RDV({ cats: [{ name: 'Period', role: 'time', values: periods }], series: { name: 'Department', groups: RT.departments.slice(0, 6).map((d, k) => ({ name: d, values: periods.map((_, j) => RT.round(RT.total * RT.deptShare[k] / 13 * (1 + 0.1 * Math.sin(j / 2 + k)), 0)) })) }, measure: 'Net Sales', fmt: FMT.usd, type: 'stream' }), { w: 620, h: 320 });
// 9-10 a middle value (2026-11-19): in-stock below 95% in the low color, comps below zero
C('Heat grid - in-stock % around a 95% middle, labels', RDV({ cats: [{ name: 'Department', role: 'time', values: ind.c }, { name: 'Division', role: 'rows', values: ind.r }], measures: [{ name: 'In-Stock Rate %', values: ind.v }], fmt: FMT.pct, type: 'heatgrid', objects: { labels: { show: true }, scale: { mid: '0.95' } } }), { w: 620, h: 360 });
C('Heat grid - comp % diverging at zero, dark', RDV({ cats: [{ name: 'Period', role: 'time', values: cmp.c }, { name: 'Department', role: 'rows', values: cmp.r }], measures: [{ name: 'Identical Store Sales %', values: cmp.v }], fmt: FMT.comp, type: 'heatgrid', objects: { labels: { show: true }, scale: { mid: '0' } } }), { dark: true, w: 620, h: 360 });
// 11 a store with zero-sales days (closed) and missing days
C('Calendar - closed days (zero) and missing days, small', RDV({ cats: [{ name: 'Date', role: 'time', values: RT.days.slice(0, 90).filter((_, i) => i < 40 || i > 46), date: true }], measures: [{ name: 'Net Sales', values: RT.daily.slice(0, 90).filter((_, i) => i < 40 || i > 46).map((v, i) => (i >= 30 && i < 35 ? 0 : RT.round(v / 120, 0))) }], fmt: FMT.usd, type: 'calendar', objects: { calendar: { view: 'month' } } }), { w: 380, h: 220 });
