// Retail test data for the Relay visuals: a large US grocery and drug retailer (made-up stores and divisions), one fiscal
// year of 52 weeks, 120 stores in 8 divisions, 12 departments. Seeded, so every run draws the same numbers.
// Edge cases on purpose: long store names, 120 stores, zero values (stores without a fuel center, a store closed for a
// remodel), blanks (new stores have no last year), negative comps and variances, totals in the billions.
// RDV(o) builds a categorical data view for any family: o.cats [{name, role, values, date, objects}], o.measures
// [{name, role, values, fmt, hl}] or o.series {name, groups: [{name, values, hl}]} with o.measure / o.fmt, o.objects,
// o.type (chart type), o.drill (drillable types for the category role).
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
function RDV(o) {
  const cats = (o.cats || []).map(c => ({ source: { displayName: c.name, queryName: (c.table || 'Store') + '.' + c.name, roles: { [c.role || 'category']: true }, type: c.date ? { dateTime: true } : { text: true }, format: c.format }, values: c.values, objects: c.objects }));
  let values;
  if (o.series) {
    const groups = o.series.groups.map(g => {
      const cols = [{ source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0', groupName: g.name }, values: g.values }];
      if (g.hl) cols[0].highlights = g.hl;
      (o.tips || []).forEach(tp => cols.push({ source: { displayName: tp.name, queryName: 'm.' + tp.name, roles: { tooltips: true }, isMeasure: true, format: tp.fmt || '#,0', groupName: g.name }, values: tp.values }));
      return { name: g.name, values: cols, identity: { key: g.name }, objects: g.objects };
    });
    values = groups.flatMap(g => g.values);
    values.source = { displayName: o.series.name, queryName: 'Store.' + o.series.name, roles: { [o.series.role || 'series']: true } };
    values.grouped = () => groups;
  } else {
    values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { [mm.role || 'values']: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0', objects: mm.objects }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; });
    values.grouped = () => [{ values: values.slice() }];
  }
  const objects = Object.assign({}, o.objects || {});
  if (o.type) objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects, dataRoles: o.drill ? { drillableRoles: { category: o.drill } } : {} }, categorical: { categories: cats, values } };
}
const FMT = { usd: '\\$#,0', usd2: '\\$#,0.00', pct: '0.0%', comp: '+0.0%;-0.0%;0.0%', num: '#,0', dec: '#,0.0' };
const RT = (() => {
  let seed = 20261119;
  const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const round = (v, d) => Math.round(v * 10 ** d) / 10 ** d;
  const divisions = ['Southern California Division', 'Northern California Division', 'Pacific Northwest Division', 'Rocky Mountain Division', 'Southwest Division', 'Mid-Atlantic Division', 'Texas and Louisiana Division', 'New England Division'];
  const cities = ['Pleasanton', 'Rancho Santa Margarita', 'Bellevue', 'Boise', 'Scottsdale', 'Bethesda', 'Plano', 'Worcester', 'Fremont', 'San Clemente', 'Tacoma', 'Denver', 'Tucson', 'Annapolis', 'Houston', 'Providence', 'Walnut Creek', 'Irvine', 'Spokane', 'Fort Collins'];
  const streets = ['Main St', 'Hacienda Crossings', 'Antonio Parkway and Avenida de las Banderas', '4th Ave', 'Camelback Rd', 'Wisconsin Ave', 'Preston Rd', 'Shrewsbury St', 'Mowry Ave', 'Del Mar', 'Pacific Ave', 'Colfax Ave', 'Oracle Rd', 'West St', 'Westheimer Rd', 'Thayer St'];
  const departments = ['Grocery', 'Dairy', 'Frozen', 'Produce', 'Meat and Seafood', 'Deli and Prepared Foods', 'Bakery', 'Floral', 'Health and Beauty Care', 'General Merchandise', 'Beer, Wine and Spirits', 'Pharmacy'];
  const deptShare = [0.27, 0.09, 0.07, 0.12, 0.13, 0.07, 0.04, 0.012, 0.05, 0.04, 0.06, 0.098];
  const stores = [];
  for (let k = 0; k < 120; k++) {
    const id = 1001 + k * 3, city = cities[k % cities.length], street = streets[(k * 7) % streets.length];
    const division = divisions[k % divisions.length], size = 0.55 + rnd() * 1.1, comp = k % 8 !== 5;    /* every 8th store opened this year: non-comp, no last year */
    const sales = round(38e6 * size, 0), compPct = (rnd() - 0.42) * 0.11, ly = comp ? round(sales / (1 + compPct), 0) : null;
    stores.push({
      id, name: `#${id} ${city} - ${street}`, short: `#${id} ${city}`, division, comp, sales, ly, plan: round(sales * (0.97 + rnd() * 0.07), 0),
      gm: round(0.255 + rnd() * 0.05, 4), shrink: round(0.011 + rnd() * 0.028, 4), instock: round(0.885 + rnd() * 0.11, 4),
      tx: Math.round(sales / (39 + rnd() * 14)), fuel: k % 3 === 0 ? 0 : round(sales * (0.08 + rnd() * 0.06), 0), splh: round(150 + rnd() * 110, 2),
      ownBrands: round(0.24 + rnd() * 0.08, 4), digital: round(0.055 + rnd() * 0.07, 4)
    });
  }
  const weeks = Array.from({ length: 52 }, (_, i) => 'FW' + String(i + 1).padStart(2, '0'));
  const season = i => 1 + 0.06 * Math.sin((i - 8) / 52 * 2 * Math.PI) + (i === 21 ? 0.07 : 0) + (i === 42 ? 0.16 : 0) + (i === 46 ? 0.21 : 0) + (i === 47 ? 0.12 : 0);
  const total = stores.reduce((a, s) => a + s.sales, 0), totalLY = stores.reduce((a, s) => a + (s.ly || 0), 0);
  const norm = weeks.reduce((a, _, i) => a + season(i), 0);
  const weekly = weeks.map((_, i) => round(total * season(i) / norm * (0.985 + rnd() * 0.03), 0));
  const weeklyLY = weekly.map((v, i) => round(v / (1.021 + (rnd() - 0.5) * 0.05 - (i > 30 && i < 36 ? 0.045 : 0)), 0));
  const weeklyPlan = weekly.map(v => round(v * (0.985 + rnd() * 0.04), 0));
  /* one year of days, a weekday pattern and holiday peaks (fiscal year from 2 Feb 2025) */
  const days = [], daily = [];
  for (let d = new Date(2025, 1, 2); d <= new Date(2026, 0, 31); d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
    const wd = [1.22, 0.86, 0.84, 0.9, 0.95, 1.08, 1.15][d.getDay()], m = d.getMonth(), dd = d.getDate();
    const holiday = (m === 10 && dd >= 24 && dd <= 26) ? 1.55 : (m === 11 && dd >= 22 && dd <= 24) ? 1.6 : (m === 6 && dd === 3) ? 1.35 : (m === 11 && dd === 25) ? 0.25 : 1;
    days.push(d); daily.push(round(total / 364 * wd * holiday * (0.97 + rnd() * 0.06), 0));
  }
  const div = name => stores.filter(s => s.division === name);
  const sum = (list, f) => list.reduce((a, s) => a + (f(s) || 0), 0);
  return { rnd, round, divisions, departments, deptShare, stores, weeks, weekly, weeklyLY, weeklyPlan, days, daily, total, totalLY, div, sum, season };
})();
