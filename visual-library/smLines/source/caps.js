// Small Multiple Lines: one small line panel per group (e.g. study), actual vs a comparison (plan),
// with end labels (value · % of comparison) and an on-track check per panel.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Axis', name: 'category', kind: 'Grouping', description: 'The x axis, usually a date or month.' },
    { displayName: 'Small multiples', name: 'group', kind: 'Grouping', description: 'One panel per value, for example Study.' },
    { displayName: 'Values', name: 'values', kind: 'Measure', description: 'The actual line (for example cumulative enrolled).' },
    { displayName: 'Comparison', name: 'comparison', kind: 'Measure', description: 'Optional. The plan or target line; end labels show the value as % of it.' },
    { displayName: 'Panel subtitle', name: 'subtitle', kind: 'Measure', description: 'Optional. A text measure shown under each panel title.' },
    { displayName: 'Tooltips', name: 'tooltips', kind: 'Measure', description: 'Extra measures shown in the tooltip.' }
  ],
  mappings: [{
    conditions: [{ category: { min: 1, max: 1 }, group: { max: 1 }, values: { min: 1, max: 1 }, comparison: { max: 1 }, subtitle: { max: 1 } }],
    categorical: {
      categories: { select: [{ for: { in: 'group' } }, { for: { in: 'category' } }], dataReductionAlgorithm: { top: { count: 10000 } } },
      values: { select: [{ for: { in: 'values' } }, { for: { in: 'comparison' } }, { for: { in: 'subtitle' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'categoryAxis', 'valueAxis', 'gridlines', 'legend'],
  objects: {
    chart: { properties: { look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, columns: num, lineWidth: num, sharedScale: bool, titleSize: num } },
    status: { properties: { show: bool, threshold: num, goodColor: color, warnColor: color } }
  }
});
