// Atlas Finance: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Category', displayNameKey: 'Role_Category', name: 'category', kind: 'Grouping', description: 'Dates for a candlestick, drivers or months for a waterfall, periods for a ribbon, stages for a funnel.', descriptionKey: 'Role_Category_Desc' },
    { displayName: 'Legend', displayNameKey: 'Role_Series', name: 'series', kind: 'Grouping', description: 'Ribbon: the series that change rank. Waterfall: the breakdown between the first and last category.', descriptionKey: 'Role_Series_Desc' },
    { displayName: 'Values', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'Waterfall changes, ribbon values or funnel counts.', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Open', displayNameKey: 'Role_Open', name: 'open', kind: 'Measure' },
    { displayName: 'High', displayNameKey: 'Role_High', name: 'high', kind: 'Measure' },
    { displayName: 'Low', displayNameKey: 'Role_Low', name: 'low', kind: 'Measure' },
    { displayName: 'Close', displayNameKey: 'Role_Close', name: 'close', kind: 'Measure' },
    { displayName: 'Volume', displayNameKey: 'Role_Volume', name: 'volume', kind: 'Measure' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  sorting: { default: {} },
  mappings: [{
    conditions: [{ category: { max: 1 }, series: { max: 1 }, values: { max: 1 }, open: { max: 1 }, high: { max: 1 }, low: { max: 1 }, close: { max: 1 }, volume: { max: 1 } }],
    categorical: {
      categories: { for: { in: 'category' }, dataReductionAlgorithm: { top: { count: 5000 } } },
      values: { group: { by: 'series', select: [{ for: { in: 'values' } }, { for: { in: 'open' } }, { for: { in: 'high' } }, { for: { in: 'low' } }, { for: { in: 'close' } }, { for: { in: 'volume' } }, { for: { in: 'tooltips' } }], dataReductionAlgorithm: { top: { count: 40 } } } }
    }
  }],
  objects: {
    chart: { properties: { chartType: E(['candlestick', 'Candlestick'], ['waterfall', 'Waterfall'], ['ribbon', 'Ribbon'], ['funnel', 'Funnel']), look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num } },
    candles: { properties: { style: E(['candle', 'Candles'], ['ohlc', 'OHLC bars'], ['line', 'Close line']), upColor: color, downColor: color, volume: bool, movingAverage: num, maColor: color, minWidth: num } },
    waterfall: { properties: { startTotal: bool, endTotal: bool, endLabel: text, subtotals: text, incColor: color, decColor: color, totColor: color, connectors: bool, radius: num } },
    ribbon: { properties: { opacity: num, columnWidth: num, rank: bool } },
    funnel: { properties: { shape: E(['bars', 'Bars'], ['tapered', 'Tapered funnel']), content: E(['value', 'Value'], ['first', 'Value and % of first'], ['previous', 'Value and % of previous'], ['percentFirst', '% of first']), conversion: bool, colors: E(['single', 'One color'], ['vary', 'A color per stage'], ['gradient', 'Darker by stage']), radius: num } }
  }
});
