// Test cases for Atlas Proportion in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
const D = window.DATA;
/* categorical data view: one category column, measures or a legend */
function dv(o) {
  const cats = [{ source: { displayName: o.cat, queryName: 't.' + o.cat, roles: { category: true }, type: { text: true } }, values: o.cats }];
  let values;
  if (o.series) {
    const groups = o.series.groups.map(g => {
      const col = { source: { displayName: o.measure, queryName: 'm.' + o.measure, roles: { values: true }, isMeasure: true, format: o.fmt || '#,0', groupName: g.name }, values: g.values };
      if (g.hl) col.highlights = g.hl;
      return { name: g.name, values: [col], identity: { key: g.name } };
    });
    values = groups.map(g => g.values[0]);
    values.source = { displayName: o.series.name, queryName: 't.' + o.series.name, roles: { series: true } };
    values.grouped = () => groups;
  } else {
    values = o.measures.map(mm => { const c = { source: { displayName: mm.name, queryName: 'm.' + mm.name, roles: { values: true }, isMeasure: true, format: mm.fmt || o.fmt || '#,0' }, values: mm.values }; if (mm.hl) c.highlights = mm.hl; return c; });
    values.grouped = () => [{ values: values.slice() }];
  }
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const regions = ['North America', 'Europe', 'Asia Pacific', 'Latin America'], chans = ['Online', 'Retail', 'Partner'];
const rc = [[420, 310, 120], [380, 220, 160], [290, 140, 90], [110, 95, 40]];
const months = D.months, sales = months.map(mm => D.hd.filter(r => r[2] === mm).reduce((a, r) => a + r[3], 0));
const chanVal = (mm, c) => (D.chan.find(r => r[0] === mm && r[1] === c) || [0, 0, 0])[2];
const cats4 = ['Bikes', 'Components', 'Clothing', 'Accessories'], cat4s = cats4.map(c => D.hp.filter(r => r[0] === c).reduce((a, r) => a + r[3], 0));

// 0-1 Mekko
C('Mekko · region by channel · percent labels', dv({ cat: 'Region', cats: regions, series: { name: 'Channel', groups: chans.map((c, k) => ({ name: c, values: rc.map(r => r[k] * 1000) })) }, measure: 'Sales', fmt: '\\$#,0', type: 'mekko' }));
C('Mekko · value labels · flat', dv({ cat: 'Region', cats: regions, series: { name: 'Channel', groups: chans.map((c, k) => ({ name: c, values: rc.map(r => r[k] * 1000) })) }, measure: 'Sales', fmt: '\\$#,0', type: 'mekko', objects: { chart: { look: 'flat', content: 'value' }, mekko: { gap: 4 } } }));
// 2-4 waffles
C('Waffle · one percentage · big number', dv({ cat: 'Metric', cats: ['Bought again within 12 months'], measures: [{ name: 'Repeat rate', values: [0.68], fmt: '0%' }], type: 'waffle' }));
C('Waffle · category shares · circles', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], fmt: '\\$#,0', type: 'waffle', objects: { waffle: { shape: 'circle', bigNumber: false } } }));
C('Waffle · one per channel (part and total)', dv({ cat: 'Channel', cats: chans, measures: [{ name: 'Discounted orders', values: [340, 220, 410] }, { name: 'Orders', values: [1000, 1000, 1000] }], type: 'waffle', objects: { chart: { multiples: true } } }));
// 5-6 pictograms
C('Pictogram · 7 in 10 people', dv({ cat: 'Group', cats: ['customers ride at least weekly'], measures: [{ name: 'Weekly riders', values: [7] }, { name: 'Customers', values: [10] }], type: 'pictogram' }));
C('Pictogram · stars per region · 500 per icon', dv({ cat: 'Region', cats: regions, measures: [{ name: 'Customers', values: [5400, 4100, 2750, 1180] }], type: 'pictogram', objects: { pictogram: { icon: 'star', unit: 500 } } }));
// 7-10 aster and rose
const attrs = ['Product range', 'Price', 'Delivery', 'Support', 'Website', 'Returns'];
C('Aster · scores with importance weights', dv({ cat: 'Attribute', cats: attrs, measures: [{ name: 'Score', values: [82, 64, 71, 88, 76, 59] }, { name: 'Importance', values: [2, 3, 2, 1, 1, 1] }], type: 'aster' }));
C('Aster · equal weights · 3D · labels', dv({ cat: 'Attribute', cats: attrs, measures: [{ name: 'Score', values: [82, 64, 71, 88, 76, 59] }], type: 'aster', objects: { chart: { look: '3d' } } }));
C('Rose · sales by month · shade by value', dv({ cat: 'Month', cats: months, measures: [{ name: 'Sales', values: sales }], fmt: '\\$#,0', type: 'rose', objects: { radial: { shadeByValue: true }, labels: { show: false } } }));
C('Rose · stacked by channel', dv({ cat: 'Month', cats: months, series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', fmt: '\\$#,0', type: 'rose', objects: { labels: { show: false } } }));
// 11-13 Venn
C('Venn · two groups', dv({ cat: 'Customers who', cats: ['Bought a bike', 'Booked a service', 'Bought a bike & Booked a service'], measures: [{ name: 'Customers', values: [2800, 1200, 1400] }], type: 'venn', objects: { chart: { content: 'value' } } }));
C('Venn · three channels', dv({ cat: 'Shopped', cats: ['Online', 'Retail', 'Partner', 'Online & Retail', 'Online & Partner', 'Retail & Partner', 'Online & Retail & Partner'], measures: [{ name: 'Customers', values: [2900, 2100, 900, 1400, 500, 300, 400] }], type: 'venn' }));
C('Venn · four sets · hint', dv({ cat: 'Sets', cats: ['A', 'B', 'C', 'D', 'A & B'], measures: [{ name: 'Count', values: [1, 2, 3, 4, 1] }], type: 'venn' }), { w: 360, h: 200 });
// 14-18 modes and edge cases
C('Waffle · category shares · high contrast', dv({ cat: 'Category', cats: cats4, measures: [{ name: 'Sales', values: cat4s }], type: 'waffle' }), { hc: true });
C('Rose · stacked · dark', dv({ cat: 'Month', cats: months, series: { name: 'Channel', groups: chans.map(c => ({ name: c, values: months.map(mm => chanVal(mm, c)) })) }, measure: 'Revenue', type: 'rose', objects: { labels: { show: false } } }), { dark: true });
C('Landing page (no fields)', null);
C('Mekko · cross-highlighted (online)', dv({ cat: 'Region', cats: regions, series: { name: 'Channel', groups: chans.map((c, k) => ({ name: c, values: rc.map(r => r[k] * 1000), hl: k === 0 ? rc.map(r => r[k] * 1000) : rc.map(() => null) })) }, measure: 'Sales', fmt: '\\$#,0', type: 'mekko' }));
C('Pictogram · small tile', dv({ cat: 'Region', cats: regions, measures: [{ name: 'Customers', values: [5400, 4100, 2750, 1180] }], type: 'pictogram' }), { w: 300, h: 200 });
