import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import sharp from 'sharp';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
export async function optimizeArtwork() {
  const manifest = JSON.parse(await readFile('public/artwork-manifest.json', 'utf8'));
  await mkdir('public/artwork/optimized', { recursive: true });
  const items = [];
  for (const source of manifest.items) {
    if (source.kind !== 'licensed-reference') continue;
    if (!/^\/artwork\/[a-z0-9-]+\.(jpg|png|webp|gif)$/.test(source.imagepath))
      throw new Error(`Unexpected licensed artwork path: ${source.content_key}`);
    const input = await readFile(resolve('public', source.imagepath.slice(1)));
    if (hash(input) !== source.asset_sha256) throw new Error(`Source image checksum differs: ${source.content_key}`);
    const metadata = await sharp(input).metadata();
    const variants = [];
    for (const width of [320, 640, 1200]) {
      const { data, info } = await sharp(input, { animated: false, limitInputPixels: 64000000 })
        .rotate().resize({ width, withoutEnlargement: true }).webp({ quality: 76, effort: 4 })
        .toBuffer({ resolveWithObject: true });
      if (variants.some(variant => variant.width === info.width)) continue;
      const sha256 = hash(data);
      const path = `/artwork/optimized/${basename(source.imagepath).split('.')[0]}-${info.width}-${sha256.slice(0, 12)}.webp`;
      await writeFile(resolve('public', path.slice(1)), data);
      variants.push({ path, width: info.width, height: info.height, bytes: data.length, sha256 });
    }
    items.push({
      content_key: source.content_key, source_path: source.imagepath, source_sha256: source.asset_sha256,
      license: source.license, attribution: source.attribution,
      modifications: `Display derivatives: resized without cropping, auto-oriented and WebP encoded at quality 76.${(metadata.pages ?? 1) > 1 ? ' First animation frame only.' : ''} Originals retained unchanged.`,
      variants,
    });
  }
  await writeFile('public/artwork-variants.json', JSON.stringify({ schema_version: 1, items }, null, 2));
  const presentation = items.map(({ content_key, modifications, variants }) => ({ content_key, modifications, variants }));
  await writeFile('src/assets/catalog-art-variants.generated.ts',
    '// Generated display derivatives; original licensed assets and provenance stay unchanged.\n'
    + 'export const catalogArtVariants = ' + JSON.stringify(presentation) + ' as const;\n');
  const originalBytes = await Promise.all(items.map(async item => (await readFile(resolve('public', item.source_path.slice(1)))).length));
  console.log(JSON.stringify({
    optimized_films: items.length, original_bytes: originalBytes.reduce((a, b) => a + b, 0),
    card_bytes: items.reduce((total, item) => total + item.variants[0].bytes, 0),
    original_sources_unchanged: true,
  }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await optimizeArtwork();
