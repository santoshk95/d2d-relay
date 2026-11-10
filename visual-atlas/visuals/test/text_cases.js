// Test cases for Atlas Text in the mock host.
const GUID = Object.keys(powerbi.visuals.plugins)[0];
function dv(o) {
  const cats = [{ source: { displayName: o.textName || 'Phrase', queryName: 't.Phrase', roles: { category: true }, type: { text: true } }, values: o.texts }];
  if (o.groups) cats.push({ source: { displayName: 'Topic', queryName: 't.Topic', roles: { group: true }, type: { text: true } }, values: o.groups });
  const values = [];
  if (o.weights) { const c = { source: { displayName: 'Mentions', queryName: 'm.Mentions', roles: { values: true }, isMeasure: true, format: '#,0' }, values: o.weights }; if (o.hl) c.highlights = o.hl; values.push(c); }
  if (o.sent) values.push({ source: { displayName: 'Sentiment', queryName: 'm.Sentiment', roles: { colorValue: true }, isMeasure: true, format: '0.00' }, values: o.sent });
  values.grouped = () => [{ values: values.slice() }];
  const objects = Object.assign({}, o.objects || {});
  objects.chart = Object.assign({ chartType: o.type || 'cloud' }, objects.chart || {});
  return { metadata: { columns: [], objects }, categorical: { categories: cats, values } };
}
const C = (title, d, o) => { try { return renderCase(GUID, title, d, o || {}); } catch (e) { LOG.push(['THROW', title, String(e && e.stack || e)]); } };
const phrases = [['fast delivery', 412, 0.8, 'Service'], ['friendly staff', 365, 0.9, 'Service'], ['great price', 301, 0.7, 'Price & offers'], ['easy returns', 244, 0.6, 'Service'], ['long wait', 233, -0.7, 'Service'],
  ['comfortable saddle', 198, 0.7, 'Product'], ['broken part', 176, -0.8, 'Product'], ['website slow', 165, -0.6, 'Online'], ['good quality', 160, 0.8, 'Product'], ['expensive', 152, -0.5, 'Price & offers'],
  ['helpful advice', 140, 0.8, 'Service'], ['out of stock', 132, -0.6, 'Online'], ['smooth gears', 120, 0.7, 'Product'], ['discount code', 110, 0.4, 'Price & offers'], ['late order', 104, -0.7, 'Online'],
  ['light frame', 96, 0.6, 'Product'], ['app crashes', 90, -0.8, 'Online'], ['free shipping', 88, 0.7, 'Price & offers'], ['nice design', 84, 0.6, 'Product'], ['rude reply', 70, -0.9, 'Service'],
  ['quick repair', 66, 0.7, 'Service'], ['easy checkout', 62, 0.6, 'Online'], ['loyalty points', 58, 0.4, 'Price & offers'], ['squeaky brakes', 54, -0.6, 'Product'], ['clear tracking', 50, 0.5, 'Online'],
  ['great colors', 46, 0.6, 'Product'], ['price match', 44, 0.3, 'Price & offers'], ['parking', 40, -0.2, 'Service'], ['gift wrap', 36, 0.4, 'Service'], ['size guide', 32, 0.1, 'Online']];
const reviews = ['The delivery was fast and the bike arrived in perfect condition. Great service!', 'Staff were friendly and helpful, but the wait at the repair desk was long.', 'Website was slow during checkout and the app crashed twice.',
  'Great price for a light frame. Gears are smooth and the saddle is comfortable.', 'Returns were easy. The refund arrived quickly.', 'The brakes were squeaky after a week; the repair was quick though.',
  'Order arrived late and tracking was not clear. Customer service apologised.', 'Love the colors and the design. Quality feels great for the price.', 'Out of stock again for my size. The size guide helped though.',
  'Free shipping and a discount code made it a great deal. Delivery was fast.'];

C('Word cloud · phrases · sentiment colors', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]), sent: phrases.map(p => p[2]), objects: { wcolor: { colorBy: 'value' } } }));
C('Word cloud · by topic · mixed angles · legend', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]), groups: phrases.map(p => p[3]), objects: { wcolor: { colorBy: 'group' }, cloud: { rotation: 'mixed' } } }));
C('Word cloud · free-text reviews split into words', dv({ textName: 'Review', texts: reviews }));
C('Word cloud · one color · no rotation · soft', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]), objects: { chart: { look: 'soft' }, wcolor: { colorBy: 'single' }, cloud: { rotation: 'none', scale: 'linear' } } }));
C('Ranked words · sentiment colors', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]), sent: phrases.map(p => p[2]), type: 'bars', objects: { wcolor: { colorBy: 'value' } } }));
C('Ranked words · reviews · remove "great"', dv({ textName: 'Review', texts: reviews, type: 'bars', objects: { words: { extraStopWords: 'great, though' } } }));
C('Word cloud · high contrast', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]) }), { hc: true });
C('Word cloud · dark · topics', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]), groups: phrases.map(p => p[3]), objects: { wcolor: { colorBy: 'group' } } }), { dark: true });
C('Landing page (no fields)', null);
C('Word cloud · cross-highlighted (service)', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]), hl: phrases.map(p => (p[3] === 'Service' ? p[1] : null)) }));
C('Word cloud · small tile', dv({ texts: phrases.map(p => p[0]), weights: phrases.map(p => p[1]) }), { w: 300, h: 200 });
