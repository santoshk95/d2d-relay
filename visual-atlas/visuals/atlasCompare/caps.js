// Atlas Compare: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects
// (style, palette, dataColors, labels, categoryAxis, valueAxis, gridlines, legend) and writes capabilities.json.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Category', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'The items to compare (rows of a lollipop or dumbbell, spokes of a radar, periods of a bump chart).', descriptionKey: 'Role_Category_Desc' },
    { displayName: 'Legend', displayNameKey: 'Role_Series', name: 'series', kind: 'Grouping', description: 'Optional. Splits the values into series (periods for a slope chart, items for a bump chart, lines on a radar).', descriptionKey: 'Role_Series_Desc' },
    { displayName: 'Values', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'One measure, or several (for example Sales 2024 and Sales 2025 for a dumbbell).', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  sorting: { default: {} },
  mappings: [{
    conditions: [{ category: { max: 1 }, series: { max: 0 } }, { category: { max: 1 }, series: { max: 1 }, values: { max: 1 } }],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 3000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 60 } } } }
    }
  }],
  objects: {
    chart: { properties: {
      chartType: E(['lollipop', 'Lollipop'], ['dot', 'Dot plot'], ['dumbbell', 'Dumbbell'], ['slope', 'Slope'], ['bump', 'Bump'], ['tornado', 'Tornado'], ['radar', 'Radar']),
      look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num,
      orientation: E(['horizontal', 'Horizontal'], ['vertical', 'Vertical']),
      sort: E(['none', 'Data order'], ['valueDesc', 'Value, high to low'], ['valueAsc', 'Value, low to high'], ['changeDesc', 'Change, largest first'], ['name', 'Name']),
      focus: text
    } },
    marks: { properties: {
      shape: E(['circle', 'Circle'], ['square', 'Square'], ['diamond', 'Diamond']), size: num, stemWidth: num, lineWidth: num, smooth: bool,
      colorBy: E(['series', 'Series'], ['category', 'Each category'], ['sign', 'Positive and negative']),
      connector: E(['neutral', 'Neutral'], ['direction', 'Up and down colors']), upColor: color, downColor: color
    } },
    tornado: { properties: { mode: E(['mirror', 'Mirror (pyramid)'], ['base', 'Around a base value']), base: num, center: bool } },
    radar: { properties: { grid: E(['polygon', 'Polygon'], ['circle', 'Circle']), levels: num, fill: bool, fillOpacity: num, max: text, multiples: bool } }
  }
});
