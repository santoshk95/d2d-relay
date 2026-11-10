// SPC Control Chart: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Subgroup / batch (in time order)', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'One point per value, in the order they should be plotted (for example the batch ID, sorted by start date).' },
    { displayName: 'Value', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'The measured value that is charted (one measure).' },
    { displayName: 'Centre line', displayNameKey: 'Role_Centre', name: 'centre', kind: 'Measure', description: 'The process mean. Optional: if empty it is computed from the plotted values.' },
    { displayName: 'Upper control limit', displayNameKey: 'Role_Upper', name: 'upper', kind: 'Measure', description: 'Usually mean + 3 sigma. Optional: if empty it is computed from the plotted values.' },
    { displayName: 'Lower control limit', displayNameKey: 'Role_Lower', name: 'lower', kind: 'Measure', description: 'Usually mean - 3 sigma. Optional: if empty it is computed from the plotted values.' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  sorting: { default: {} },
  mappings: [{
    conditions: [{ category: { min: 1, max: 1 }, values: { min: 1, max: 1 }, centre: { max: 1 }, upper: { max: 1 }, lower: { max: 1 } }],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 5000 } } },
      values: { select: [{ for: { in: 'values' } }, { for: { in: 'centre' } }, { for: { in: 'lower' } }, { for: { in: 'upper' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  objects: {
    chart: { properties: { look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num } },
    spc: { properties: { width: num, markerSize: num, sigma: num, showLimitLabels: bool, shadeZone: bool, alarmColor: color, limitColor: color, runRule: bool } }
  }
});
