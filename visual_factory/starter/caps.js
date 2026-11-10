// __TITLE__: field wells (roles), data mapping and the chart's own Format-pane objects.
// `genbi visual build` turns this into capabilities.json and adds the shared objects listed in `shared`
// (style, palette, dataColors, labels, categoryAxis, valueAxis, gridlines, legend: the cards in common/cards.ts).
// Every object property here needs a slice with the same name in src/settings.ts, and the other way round.
// `min` in a condition marks a well as required: the report check and Power BI's landing page use it.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Category', name: 'category', kind: 'Grouping', description: 'One group of marks per item, for example Region.' },
    { displayName: 'Legend', name: 'series', kind: 'Grouping', description: 'Optional. Splits each group by this field.' },
    { displayName: 'Values', name: 'values', kind: 'Measure', description: 'The numbers to show. Several measures become several series.' },
    { displayName: 'Tooltips', name: 'tooltips', kind: 'Measure', description: 'Extra measures shown in the tooltip.' }
  ],
  sorting: { default: {} },
  mappings: [{
    conditions: [
      { category: { min: 1, max: 1 }, series: { max: 0 }, values: { min: 1 } },
      { category: { min: 1, max: 1 }, series: { max: 1 }, values: { min: 1, max: 1 } }
    ],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 1000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 30 } } } }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'categoryAxis', 'valueAxis', 'gridlines', 'legend'],
  objects: {
    chart: { properties: { look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, gap: num, corner: num } }
  }
});
