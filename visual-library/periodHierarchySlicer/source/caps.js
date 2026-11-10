// Period Hierarchy Slicer: field wells (roles), data mapping and the visual's own Format-pane objects.
// `genbi visual build` turns this into capabilities.json and adds the shared objects listed in `shared`.
// Every object property here needs a slice with the same name in src/settings.ts, and the other way round.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Levels', name: 'levels', kind: 'Grouping', description: 'The levels of the tree, from the top (for example Year, Month, Week). Each pick filters the report on that level.' },
    { displayName: 'Values', name: 'values', kind: 'Measure', description: 'Optional. A number shown next to every item (for example Net Sales).' }
  ],
  sorting: { default: {} },
  mappings: [{
    conditions: [{ levels: { min: 1, max: 6 }, values: { max: 1 } }],
    categorical: {
      categories: { for: { in: 'levels' }, dataReductionAlgorithm: { top: { count: 30000 } } },
      values: { select: [{ for: { in: 'values' } }] }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels'],
  objects: {
    general: { properties: { filter: { type: { filter: true } } } },
    chart: { properties: { look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, rowHeight: num, corner: num } },
    slicer: { properties: { placeholder: text, startOpen: bool, multiSelect: bool, selColor: color } }
  }
});
