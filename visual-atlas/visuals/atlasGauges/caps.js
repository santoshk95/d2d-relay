// Atlas Gauges: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Category', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'Optional. One card, gauge, ring or bullet per value (for example Region or Measure name).', descriptionKey: 'Role_Category_Desc' },
    { displayName: 'Trend axis', displayNameKey: 'Role_Trend', name: 'trend', kind: 'Grouping', description: 'Optional. A date or period for the KPI sparkline; the latest period is the value shown.', descriptionKey: 'Role_Trend_Desc' },
    { displayName: 'Value', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'The value. Several measures without a Category make one card each.', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Target', displayNameKey: 'Role_Target', name: 'target', kind: 'Measure' },
    { displayName: 'Minimum', displayNameKey: 'Role_Min', name: 'minValue', kind: 'Measure' },
    { displayName: 'Maximum', displayNameKey: 'Role_Max', name: 'maxValue', kind: 'Measure' },
    { displayName: 'Band 1 (poor to fair)', displayNameKey: 'Role_Band1', name: 'band1', kind: 'Measure' },
    { displayName: 'Band 2 (fair to good)', displayNameKey: 'Role_Band2', name: 'band2', kind: 'Measure' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  mappings: [{
    conditions: [{ category: { max: 1 }, trend: { max: 1 }, target: { max: 1 }, minValue: { max: 1 }, maxValue: { max: 1 }, band1: { max: 1 }, band2: { max: 1 } }],
    categorical: {
      categories: { select: [{ for: { in: 'category' } }, { for: { in: 'trend' } }], dataReductionAlgorithm: { top: { count: 10000 } } },
      values: { select: [{ for: { in: 'values' } }, { for: { in: 'target' } }, { for: { in: 'minValue' } }, { for: { in: 'maxValue' } }, { for: { in: 'band1' } }, { for: { in: 'band2' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'categoryAxis'],
  objects: {
    chart: { properties: {
      chartType: E(['card', 'Card'], ['multirow', 'Multi-row card'], ['kpi', 'KPI'], ['gauge', 'Gauge'], ['dial', 'Dial (tachometer)'], ['radialBar', 'Radial bars'], ['liquid', 'Liquid fill'], ['bullet', 'Bullet chart'], ['ticker', 'Ticker']),
      look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, columns: num, accent: bool
    } },
    status: { properties: { direction: E(['higher', 'Higher is better'], ['lower', 'Lower is better']), tolerance: num, goodColor: color, warnColor: color, badColor: color, colorValue: bool, showTarget: bool } },
    trend: { properties: { show: bool, style: E(['area', 'Area'], ['line', 'Line'], ['column', 'Columns']) } },
    scale: { properties: { min: text, max: text, angle: E(['180', 'Half circle'], ['240', 'Three quarters'], ['270', 'Open ring']), width: num, band1: num, band2: num, needle: bool, ticks: bool } },
    liquid: { properties: { shape: E(['circle', 'Circle'], ['square', 'Rounded square']), wave: num } },
    bullet: { properties: { orientation: E(['horizontal', 'Horizontal'], ['vertical', 'Vertical']) } },
    ticker: { properties: { speed: num, direction: E(['left', 'Scroll left'], ['up', 'Scroll up']) } }
  }
});
