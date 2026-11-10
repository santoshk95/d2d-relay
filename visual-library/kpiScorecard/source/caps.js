// KPI Scorecard: one row per item (KPI) with a result, the latest period, a target, a coloured status chip
// and a sparkline. Result / latest / target may be numbers or text measures (pre-formatted per KPI).
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'KPI', name: 'category', kind: 'Grouping', description: 'One row per value, for example the KPI name.' },
    { displayName: 'Trend axis', name: 'trend', kind: 'Grouping', description: 'Optional. A date or month column for the sparkline.' },
    { displayName: 'Result', name: 'result', kind: 'Measure', description: 'The headline result per row (number or text).' },
    { displayName: 'Latest period', name: 'latest', kind: 'Measure', description: 'Optional. The value in the latest period (number or text).' },
    { displayName: 'Target', name: 'target', kind: 'Measure', description: 'Optional. The target per row (number or text, e.g. "≥ 95%").' },
    { displayName: 'Status', name: 'status', kind: 'Measure', description: 'Optional. Status text (On track / At risk / Off track) or a number (1 good, 0 at risk, -1 off).' },
    { displayName: 'Trend values', name: 'values', kind: 'Measure', description: 'Optional. The measure drawn as the sparkline along the trend axis.' },
    { displayName: 'Tooltips', name: 'tooltips', kind: 'Measure', description: 'Extra measures shown in the tooltip.' }
  ],
  mappings: [{
    conditions: [{ category: { min: 1, max: 1 }, trend: { max: 1 }, result: { min: 1, max: 1 }, latest: { max: 1 }, target: { max: 1 }, status: { max: 1 }, values: { max: 1 } }],
    categorical: {
      categories: { select: [{ for: { in: 'category' } }, { for: { in: 'trend' } }], dataReductionAlgorithm: { top: { count: 10000 } } },
      values: { select: [{ for: { in: 'result' } }, { for: { in: 'latest' } }, { for: { in: 'target' } }, { for: { in: 'status' } }, { for: { in: 'values' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels'],
  objects: {
    chart: { properties: { look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num, fontSize: num, zebra: bool, rowLines: bool } },
    headers: { properties: { show: bool, fontSize: num, kpi: text, result: text, latest: text, target: text, status: text, trend: text } },
    status: { properties: { goodColor: color, warnColor: color, badColor: color, icons: bool } },
    trend: { properties: { show: bool, width: num, endDot: bool } }
  }
});
