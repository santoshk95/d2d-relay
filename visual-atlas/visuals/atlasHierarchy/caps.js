// Atlas Hierarchy: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, color }) => ({
  roles: [
    { displayName: 'Levels', displayNameKey: 'Role_Levels', name: 'levels', kind: 'Grouping', description: 'One or more fields from the top level down, for example Category, Subcategory, Product.', descriptionKey: 'Role_Levels_Desc' },
    { displayName: 'ID', displayNameKey: 'Role_Id', name: 'nodeId', kind: 'Grouping', description: 'For an org chart: the field that identifies each person or node (use instead of Levels).', descriptionKey: 'Role_Id_Desc' },
    { displayName: 'Parent ID', displayNameKey: 'Role_Parent', name: 'parentId', kind: 'Grouping', description: 'For an org chart: the ID of the manager or parent node. Empty for the top.', descriptionKey: 'Role_Parent_Desc' },
    { displayName: 'Label', displayNameKey: 'Role_Label', name: 'label', kind: 'Grouping', description: 'For an org chart: the name shown on each card (defaults to the ID).', descriptionKey: 'Role_Label_Desc' },
    { displayName: 'Size', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'The value that sizes tiles, segments and circles.', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Color value', displayNameKey: 'Role_Color', name: 'colorValue', kind: 'Measure', description: 'Optional. Colors items on a gradient (for example Margin %) when Colors › Color by is Value.', descriptionKey: 'Role_Color_Desc' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  mappings: [{
    conditions: [
      { levels: { max: 6 }, nodeId: { max: 0 }, parentId: { max: 0 }, label: { max: 0 }, values: { max: 1 }, colorValue: { max: 1 } },
      { levels: { max: 0 }, nodeId: { max: 1 }, parentId: { max: 1 }, label: { max: 1 }, values: { max: 1 }, colorValue: { max: 1 } }
    ],
    categorical: {
      categories: { select: [{ for: { in: 'levels' } }, { for: { in: 'nodeId' } }, { for: { in: 'parentId' } }, { for: { in: 'label' } }], dataReductionAlgorithm: { top: { count: 10000 } } },
      values: { select: [{ for: { in: 'values' } }, { for: { in: 'colorValue' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'legend'],
  objects: {
    chart: { properties: {
      chartType: E(['treemap', 'Treemap'], ['sunburst', 'Sunburst'], ['pack', 'Circle packing'], ['tree', 'Org chart / tree']),
      look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, depth: num,
      click: E(['zoom', 'Zoom into groups'], ['select', 'Select (cross-filter)']), content: E(['name', 'Name'], ['nameValue', 'Name and value'], ['namePercent', 'Name and percent'])
    } },
    hcolor: { properties: { colorBy: E(['branch', 'Top-level branch'], ['level', 'Level'], ['value', 'Color value (gradient)']), fade: num, lowColor: color, highColor: color } },
    treemap: { properties: { tile: E(['squarify', 'Squarified'], ['binary', 'Balanced'], ['sliceDice', 'Slice and dice']), padding: num, headers: bool, radius: num } },
    sunburst: { properties: { hole: num, gap: num, radius: num } },
    pack: { properties: { padding: num } },
    tree: { properties: {
      orientation: E(['topDown', 'Top down'], ['leftRight', 'Left to right']), expanded: num, links: E(['curve', 'Curved'], ['elbow', 'Elbow'], ['straight', 'Straight']),
      cardWidth: num, cardHeight: num, badges: bool, bars: bool
    } }
  }
});
