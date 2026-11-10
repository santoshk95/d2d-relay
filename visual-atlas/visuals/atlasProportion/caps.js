// Atlas Proportion: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Category', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'Columns of a Mekko, wedges of a rose or aster, waffle parts, icon rows, or Venn regions written as "A & B".', descriptionKey: 'Role_Category_Desc' },
    { displayName: 'Legend', displayNameKey: 'Role_Series', name: 'series', kind: 'Grouping', description: 'Optional. Segments of a Mekko column or stacked rose wedge.', descriptionKey: 'Role_Series_Desc' },
    { displayName: 'Values', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'The value. A second measure is the total (waffle, pictogram) or the weight (aster).', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  sorting: { default: {} },
  mappings: [{
    conditions: [{ category: { max: 1 }, series: { max: 0 } }, { category: { max: 1 }, series: { max: 1 }, values: { max: 1 } }],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 1000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 40 } } } }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'categoryAxis', 'legend'],
  objects: {
    chart: { properties: {
      chartType: E(['mekko', 'Mekko'], ['waffle', 'Waffle'], ['pictogram', 'Pictogram'], ['aster', 'Aster plot'], ['rose', 'Rose (polar area)'], ['venn', 'Venn diagram']),
      look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num,
      content: E(['percent', 'Percent'], ['value', 'Value'], ['both', 'Value and percent']), emptyColor: color, multiples: bool
    } },
    waffle: { properties: { rows: num, columns: num, shape: E(['square', 'Square'], ['rounded', 'Rounded'], ['circle', 'Circle']), gap: num, bigNumber: bool } },
    pictogram: { properties: { icon: E(['person', 'Person'], ['circle', 'Circle'], ['square', 'Square'], ['star', 'Star'], ['heart', 'Heart'], ['drop', 'Drop']), unit: num, perRow: num, total: num } },
    radial: { properties: { hole: num, gap: num, maxScore: num, outline: bool, centerText: bool, shadeByValue: bool } },
    mekko: { properties: { gap: num, radius: num, showTotals: bool } },
    venn: { properties: { opacity: num, separator: text } }
  }
});
