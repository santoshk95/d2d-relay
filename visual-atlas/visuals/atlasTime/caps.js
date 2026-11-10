// Atlas Time: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, color }) => ({
  roles: [
    { displayName: 'Time', displayNameKey: 'Role_Time', name: 'time', kind: 'Grouping', description: 'A date (calendar, timeline slicer), the x-axis of a stream graph, or the columns of a heat grid (for example Hour).', descriptionKey: 'Role_Time_Desc' },
    { displayName: 'Rows', displayNameKey: 'Role_Rows', name: 'rows', kind: 'Grouping', description: 'Heat grid and punch card: the rows (for example Weekday).', descriptionKey: 'Role_Rows_Desc' },
    { displayName: 'Legend', displayNameKey: 'Role_Series', name: 'series', kind: 'Grouping', description: 'Stream graph: one stream per value.', descriptionKey: 'Role_Series_Desc' },
    { displayName: 'Values', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  mappings: [{
    conditions: [{ time: { max: 1 }, rows: { max: 1 }, series: { max: 1 }, values: { max: 1 } }],
    categorical: {
      categories: { select: [{ for: { in: 'time' } }, { for: { in: 'rows' } }], dataReductionAlgorithm: { top: { count: 30000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 30 } } } }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'categoryAxis', 'legend'],
  objects: {
    general: { properties: { filter: { type: { filter: true } } } },
    chart: { properties: {
      chartType: E(['calendar', 'Calendar heatmap'], ['heatgrid', 'Heat grid'], ['stream', 'Stream graph'], ['timeline', 'Timeline slicer']),
      look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num
    } },
    scale: { properties: { mode: E(['linear', 'By value'], ['quantile', 'By rank (quantiles)']), lowColor: color, highColor: color, emptyColor: color, steps: num, gap: num, radius: num } },
    calendar: { properties: { view: E(['year', 'Year (weeks)'], ['month', 'Month pages']), weekStart: E(['monday', 'Monday'], ['sunday', 'Sunday']), dayNames: bool, monthNames: bool } },
    heatgrid: { properties: { shape: E(['cell', 'Cells'], ['circle', 'Circles sized by value (punch card)']), colorCircles: bool } },
    stream: { properties: { offset: E(['wiggle', 'Wiggle'], ['silhouette', 'Silhouette'], ['zero', 'Stacked'], ['expand', '100% stacked']), smooth: bool, opacity: num } },
    timeline: { properties: { granularity: E(['day', 'Day'], ['week', 'Week'], ['month', 'Month'], ['quarter', 'Quarter'], ['year', 'Year']), bars: bool, selColor: color } }
  }
});
