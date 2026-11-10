// Atlas Scatter: roles, data mapping and chart objects. tools/mk_caps.js adds the shared objects.
module.exports = ({ E, num, bool, text, color }) => ({
  roles: [
    { displayName: 'Values (details)', displayNameKey: 'Role_Details', name: 'details', kind: 'Grouping', description: 'Scatter: one point per value, for example Store.', descriptionKey: 'Role_Details_Desc' },
    { displayName: 'Legend', displayNameKey: 'Role_Legend', name: 'legend', kind: 'Grouping', description: 'Colors points by group. Gantt: the phase.', descriptionKey: 'Role_Legend_Desc' },
    { displayName: 'X-axis category', displayNameKey: 'Role_XCat', name: 'xCategory', kind: 'Grouping', description: 'Dot plot: a categorical x-axis.', descriptionKey: 'Role_XCat_Desc' },
    { displayName: 'Play axis', displayNameKey: 'Role_Play', name: 'play', kind: 'Grouping', description: 'Animates the scatter through the values, for example Year.', descriptionKey: 'Role_Play_Desc' },
    { displayName: 'X-axis', displayNameKey: 'Role_X', name: 'x', kind: 'Measure' },
    { displayName: 'Y-axis', displayNameKey: 'Role_Y', name: 'y', kind: 'Measure' },
    { displayName: 'Size', displayNameKey: 'Role_Size', name: 'size', kind: 'Measure' },
    { displayName: 'Task', displayNameKey: 'Role_Task', name: 'task', kind: 'Grouping', description: 'Gantt: one bar per task.', descriptionKey: 'Role_Task_Desc' },
    { displayName: 'Start date', displayNameKey: 'Role_Start', name: 'start', kind: 'Grouping' },
    { displayName: 'End date', displayNameKey: 'Role_End', name: 'end', kind: 'Grouping', description: 'Gantt: leave blank for a milestone.', descriptionKey: 'Role_End_Desc' },
    { displayName: 'Owner', displayNameKey: 'Role_Owner', name: 'owner', kind: 'Grouping' },
    { displayName: '% complete', displayNameKey: 'Role_Progress', name: 'progress', kind: 'Measure' },
    { displayName: 'Tooltips', displayNameKey: 'Role_Tooltips', name: 'tooltips', kind: 'Measure' }
  ],
  mappings: [{
    conditions: [{ details: { max: 1 }, legend: { max: 1 }, xCategory: { max: 1 }, play: { max: 1 }, x: { max: 1 }, y: { max: 1 }, size: { max: 1 }, task: { max: 1 }, start: { max: 1 }, end: { max: 1 }, owner: { max: 1 }, progress: { max: 1 } }],
    categorical: {
      categories: { select: [{ for: { in: 'details' } }, { for: { in: 'legend' } }, { for: { in: 'xCategory' } }, { for: { in: 'play' } }, { for: { in: 'task' } }, { for: { in: 'start' } }, { for: { in: 'end' } }, { for: { in: 'owner' } }], dataReductionAlgorithm: { top: { count: 10000 } } },
      values: { select: [{ for: { in: 'x' } }, { for: { in: 'y' } }, { for: { in: 'size' } }, { for: { in: 'progress' } }, { for: { in: 'tooltips' } }] }
    }
  }],
  objects: {
    chart: { properties: { chartType: E(['scatter', 'Scatter or bubble'], ['dotplot', 'Dot plot'], ['gantt', 'Gantt']), look: E(['flat', 'Flat'], ['soft', 'Soft'], ['3d', '3D']), shadow: num } },
    points: { properties: { shape: E(['circle', 'Circle'], ['square', 'Square'], ['diamond', 'Diamond']), size: num, maxBubble: num, opacity: num, colorBy: E(['legend', 'Legend'], ['single', 'One color'], ['cluster', 'Automatic clusters']), clusters: num } },
    guides: { properties: { quadrants: bool, xSplit: text, ySplit: text, trend: bool, ratio: bool, symmetry: bool, xLog: bool, yLog: bool, zoom: bool, color: color }, objectCategory: 2 },
    play: { properties: { speed: num, loop: bool } },
    gantt: { properties: { progress: E(['fill', 'Fill the bar'], ['overlay', 'Thin overlay'], ['none', 'None']), today: bool, weekends: bool, barHeight: num, ownerColumn: bool, percentColumn: bool, milestoneColor: color, radius: num } }
  }
});
