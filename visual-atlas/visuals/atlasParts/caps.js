// Atlas Parts: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Legend', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'The slices. Add a hierarchy, for example Category and Subcategory, to drill down.', descriptionKey: 'Role_Category_Desc' },
    { displayName: 'Details', displayNameKey: 'Role_Series', name: 'series', kind: 'Grouping', description: 'Optional. Splits each slice into an outer ring.', descriptionKey: 'Role_Series_Desc' },
    { displayName: 'Values', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  drilldown: { roles: ['category'], canDisableDrill: { disabledByDefault: false } },
  sorting: { default: {} },
  mappings: [{
    conditions: [{ category: { max: 1 }, series: { max: 0 } }, { category: { max: 1 }, series: { max: 1 }, values: { max: 1 } }],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 1000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 30 } } } }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'legend'],
  objects: {
    chart: { properties: { chartType: E(['pie', 'Pie'], ['donut', 'Donut']), look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, hole: num, startAngle: num, half: bool, sort: E(['value', 'Largest first'], ['none', 'Data order']), topN: num, otherLabel: text, gap: num } },
    slices: { properties: { labelPosition: E(['outside', 'Outside with leader lines'], ['inside', 'Inside'], ['auto', 'Inside when it fits']), content: E(['percent', 'Percent'], ['categoryPercent', 'Category, percent'], ['categoryValue', 'Category, value'], ['all', 'Category, value, percent'], ['value', 'Value']), centerTotal: bool, centerLabel: text, track: bool, trackColor: color } },
    drill: { properties: { buttons: bool, allow: bool } }
  }
});
