// Atlas Text: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Text', displayNameKey: 'Role_Text', name: 'category', kind: 'Grouping', description: 'Words, phrases or free text (comments, reviews). Free text is split into words.', descriptionKey: 'Role_Text_Desc' },
    { displayName: 'Topic', displayNameKey: 'Role_Group', name: 'group', kind: 'Grouping', description: 'Optional. Colors words by topic.', descriptionKey: 'Role_Group_Desc' },
    { displayName: 'Weight', displayNameKey: 'Role_Values', name: 'values', kind: 'Measure', description: 'Optional. Sizes words (for example Mentions). Without it, words are sized by how often they appear.', descriptionKey: 'Role_Values_Desc' },
    { displayName: 'Color value', displayNameKey: 'Role_Color', name: 'colorValue', kind: 'Measure', description: 'Optional. Colors words on a gradient (for example Sentiment).', descriptionKey: 'Role_Color_Desc' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  mappings: [{
    conditions: [{ category: { max: 1 }, group: { max: 1 }, values: { max: 1 }, colorValue: { max: 1 } }],
    categorical: {
      categories: { select: [{ for: { in: 'category' } }, { for: { in: 'group' } }], dataReductionAlgorithm: { top: { count: 5000 } } },
      values: { select: [{ for: { in: 'values' } }, { for: { in: 'colorValue' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  shared: ['style', 'palette', 'dataColors', 'labels', 'legend'],
  objects: {
    chart: { properties: { chartType: E(['cloud', 'Word cloud'], ['bars', 'Ranked words']), look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num } },
    words: { properties: { split: E(['auto', 'Auto'], ['phrases', 'Keep phrases'], ['words', 'Split into words']), stopWords: bool, extraStopWords: text, minLength: num, maxWords: num, lowercase: bool } },
    cloud: { properties: { rotation: E(['none', 'None'], ['some', 'Some vertical'], ['mixed', 'Mixed angles']), minSize: num, maxSize: num, scale: E(['sqrt', 'Square root'], ['linear', 'Linear'], ['log', 'Logarithmic']), padding: num } },
    wcolor: { properties: { colorBy: E(['palette', 'A color per word'], ['single', 'One color'], ['group', 'Topic'], ['value', 'Color value (gradient)']), lowColor: color, highColor: color } }
  }
});
