import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const source = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_110m_admin_0_countries.geojson';
const response = await fetch(source);
if (!response.ok) throw new Error(`Natural Earth download failed: ${response.status}`);
const bytes = Buffer.from(await response.arrayBuffer());
const geo = JSON.parse(bytes.toString('utf8'));
if (geo.type !== 'FeatureCollection' || geo.features.length !== 177) throw new Error('Unexpected Natural Earth dataset');
const project = ([longitude, latitude]) => [longitude, -180 / Math.PI * Math.log(Math.tan(Math.PI / 4 + Math.max(-85, Math.min(85, latitude)) * Math.PI / 360))];
const round = value => Number(value.toFixed(3));
const countries = geo.features.map(({ properties: p, geometry }) => {
  if (!['Polygon', 'MultiPolygon'].includes(geometry.type)) throw new Error(`Unsupported geometry: ${geometry.type}`);
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  return {
    id: p.ADM0_A3,
    code: /^[A-Z]{2}$/.test(p.ISO_A2_EH) ? p.ISO_A2_EH : null,
    name: p.NAME_EN,
    continent: p.CONTINENT,
    label: project([p.LABEL_X, p.LABEL_Y]).map(round),
    path: polygons.flatMap(polygon => polygon.map(ring => ring.map((point, index) => `${index ? 'L' : 'M'}${project(point).map(round).join(',')}`).join('') + 'Z')).join(''),
  };
});
if (new Set(countries.map(country => country.id)).size !== countries.length) throw new Error('Duplicate country identifiers');
const asset = {
  source,
  sourceSha256: createHash('sha256').update(bytes).digest('hex'),
  license: 'Public domain',
  licenseUrl: 'https://www.naturalearthdata.com/about/terms-of-use/',
  projection: 'Mercator, latitude clamped to 85 degrees, coordinates rounded to 0.001 projected degrees',
  countries,
};
const output = resolve(import.meta.dirname, '..', 'src', 'assets', 'insights-world.generated.json');
await writeFile(output, JSON.stringify(asset) + '\n');
console.log(`Generated ${countries.length} country outlines; source SHA-256 ${asset.sourceSha256}`);
