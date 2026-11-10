// Generates pre-projected, simplified map geometry for the atlas page.
// Usage: node gen-geo.mjs <node_modules dir> <out file>
import fs from 'node:fs';
import path from 'node:path';

const NM = process.argv[2];
const OUT = process.argv[3];
const imp = (p) => import(path.join(NM, p));

const { feature, mesh } = await imp('topojson-client/src/index.js');
const { presimplify, simplify } = await imp('topojson-simplify/src/index.js');
const d3 = await imp('d3-geo/src/index.js');

const round = (s) => s.replace(/-?\d+\.\d+/g, (m) => {
  const v = Math.round(parseFloat(m) * 10) / 10;
  return String(v);
});

// ---------- World land (Mercator, 1000 wide, cropped 83N..56S) ----------
const land = JSON.parse(fs.readFileSync(path.join(NM, 'world-atlas/land-110m.json')));
const W = 1000;
const s = W / (2 * Math.PI);
const yTop = -s * Math.log(Math.tan(Math.PI / 4 + (83 * Math.PI / 180) / 2));
const yBot = -s * Math.log(Math.tan(Math.PI / 4 + (-56 * Math.PI / 180) / 2));
const H = Math.round(yBot - yTop);
const merc = d3.geoMercator().scale(s).translate([W / 2, -yTop]).clipExtent([[0, 0], [W, H]]);
const wpath = d3.geoPath(merc);
const landF = feature(land, land.objects.land);
const landD = round(wpath(landF));

const worldCities = {
  'New York': [-74.006, 40.7128], 'Chicago': [-87.6298, 41.8781], 'San Francisco': [-122.4194, 37.7749],
  'Austin': [-97.7431, 30.2672], 'Toronto': [-79.3832, 43.6532], 'Vancouver': [-123.1207, 49.2827],
  'São Paulo': [-46.6333, -23.5505], 'Mexico City': [-99.1332, 19.4326], 'London': [-0.1276, 51.5072],
  'Manchester': [-2.2426, 53.4808], 'Berlin': [13.405, 52.52], 'Munich': [11.582, 48.1351],
  'Paris': [2.3522, 48.8566], 'Madrid': [-3.7038, 40.4168], 'Amsterdam': [4.9041, 52.3676],
  'Stockholm': [18.0686, 59.3293], 'Tokyo': [139.6917, 35.6895], 'Osaka': [135.5023, 34.6937],
  'Sydney': [151.2093, -33.8688], 'Melbourne': [144.9631, -37.8136], 'Mumbai': [72.8777, 19.076],
  'Bengaluru': [77.5946, 12.9716], 'Singapore': [103.8198, 1.3521], 'Seoul': [126.978, 37.5665],
  'Dubai': [55.2708, 25.2048], 'Johannesburg': [28.0473, -26.2041], 'Cairo': [31.2357, 30.0444],
  'Lagos': [3.3792, 6.5244], 'Nairobi': [36.8219, -1.2921]
};
const wc = {};
for (const [k, ll] of Object.entries(worldCities)) {
  const p = merc(ll);
  wc[k] = [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10];
}

// ---------- US states (Albers USA, pre-projected 975x610) ----------
const usTopo = JSON.parse(fs.readFileSync(path.join(NM, 'us-atlas/states-albers-10m.json')));
const minW = parseFloat(process.env.MINW || '2');
const simp = simplify(presimplify(usTopo), minW);
const upath = d3.geoPath(null);
const abbr = {
  'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA', 'Colorado': 'CO',
  'Connecticut': 'CT', 'Delaware': 'DE', 'District of Columbia': 'DC', 'Florida': 'FL', 'Georgia': 'GA',
  'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
  'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA',
  'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT',
  'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM',
  'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
  'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD',
  'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
  'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY'
};
const states = [];
for (const f of feature(simp, simp.objects.states).features) {
  const a = abbr[f.properties.name];
  if (!a) continue; // drop territories
  const d = round(upath(f));
  const c = upath.centroid(f);
  const b = upath.bounds(f);
  states.push({ a, n: f.properties.name, d, c: c.map((v) => Math.round(v)), b: b.flat().map((v) => Math.round(v)) });
}
states.sort((x, y) => x.a.localeCompare(y.a));
const nation = round(upath(mesh(simp, simp.objects.nation)));

const usCityLL = {
  'Seattle': [-122.3321, 47.6062], 'Portland': [-122.6765, 45.5231], 'San Francisco': [-122.4194, 37.7749],
  'Los Angeles': [-118.2437, 34.0522], 'Phoenix': [-112.074, 33.4484], 'Salt Lake City': [-111.891, 40.7608],
  'Denver': [-104.9903, 39.7392], 'Dallas': [-96.797, 32.7767], 'Houston': [-95.3698, 29.7604],
  'Kansas City': [-94.5786, 39.0997], 'Minneapolis': [-93.265, 44.9778], 'Chicago': [-87.6298, 41.8781],
  'Nashville': [-86.7816, 36.1627], 'Atlanta': [-84.388, 33.749], 'Detroit': [-83.0458, 42.3314],
  'Charlotte': [-80.8431, 35.2271], 'Miami': [-80.1918, 25.7617], 'Washington DC': [-77.0369, 38.9072],
  'New York': [-74.006, 40.7128], 'Boston': [-71.0589, 42.3601]
};
const albers = d3.geoAlbersUsa().scale(1300).translate([487.5, 305]);
const uc = {};
for (const [k, ll] of Object.entries(usCityLL)) {
  const p = albers(ll);
  uc[k] = [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10];
}

const GEO = {
  world: { w: W, h: H, land: landD, cities: wc },
  us: { w: 975, h: 610, states, cities: uc }
};
const js = '/* Map geometry: Natural Earth 1:110m land (world-atlas) and US Census states (us-atlas), simplified. */\nconst GEO=' + JSON.stringify(GEO) + ';\n';
fs.writeFileSync(OUT, js);
console.log('world h', H, 'land bytes', landD.length, 'states', states.length, 'state bytes', states.reduce((a, s) => a + s.d.length, 0), 'nation bytes', nation.length, 'total', js.length);
