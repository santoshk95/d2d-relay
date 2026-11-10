// Atlas Lines: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'X-axis', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'Usually dates or periods. Add a hierarchy, for example Year, Quarter and Month, to drill down.', descriptionKey: 'Role_Category_Desc' },
    { displayName: 'Legend', displayNameKey: 'Role_Series', name: 'series', kind: 'Grouping' },
    { displayName: 'Y-axis', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'Lines and areas, or the columns of a combo chart.', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Line y-axis', displayNameKey: 'Role_Line', name: 'lineValues', kind: 'Measure', description: 'Combo charts: the measures drawn as lines.', descriptionKey: 'Role_Line_Desc' },
    { displayName: 'Lower bound', displayNameKey: 'Role_Lower', name: 'lower', kind: 'Measure', description: 'Optional. With Upper bound, a shaded error band around the first line.', descriptionKey: 'Role_Lower_Desc' },
    { displayName: 'Upper bound', displayNameKey: 'Role_Upper', name: 'upper', kind: 'Measure' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  drilldown: { roles: ['category'], canDisableDrill: { disabledByDefault: false } },
  sorting: { default: {} },
  mappings: [{
    conditions: [{ category: { max: 1 }, series: { max: 0 }, lower: { max: 1 }, upper: { max: 1 } }, { category: { max: 1 }, series: { max: 1 }, values: { max: 1 }, lineValues: { max: 0 }, lower: { max: 0 }, upper: { max: 0 } }],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 5000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'lineValues' } }, { for: { in: 'lower' } }, { for: { in: 'upper' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 40 } } } }
    }
  }],
  objects: {
    chart: { properties: {
      chartType: E(['line', 'Line'], ['area', 'Area'], ['stackedArea', 'Stacked area'], ['percentArea', '100% stacked area'], ['comboStacked', 'Line and stacked column'], ['comboClustered', 'Line and clustered column']),
      look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, curve: E(['linear', 'Straight'], ['smooth', 'Smooth'], ['step', 'Stepped']), zoom: bool, zoomToSelection: bool
    } },
    lines: { properties: { width: num, markers: E(['none', 'None'], ['all', 'All points'], ['last', 'Last point']), markerSize: num, dashed: text, areaOpacity: num, endLabels: bool, focus: text, secondary: bool, columnSpacing: num, radius: num } },
    analytics: { properties: { trend: bool, minMax: bool, average: bool, target: text, forecast: num, anomalies: bool, color: color }, objectCategory: 2 },
    drill: { properties: { buttons: bool, allow: bool } }
  }
});
