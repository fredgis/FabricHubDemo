// @vitest-environment node
import { afterEach, describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const app = resolve(import.meta.dirname, '../../apps/cockpit');
const script = resolve(app, 'tools/artwork.mjs');
const temporaryDirectories: string[] = [];
const sha256 = (bytes: Buffer | string) => createHash('sha256').update(bytes).digest('hex');

function cachedFixture() {
  const cwd = mkdtempSync(resolve(tmpdir(), 'msflix-artwork-cache-'));
  temporaryDirectories.push(cwd);
  mkdirSync(resolve(cwd, 'public/artwork'), { recursive: true });
  mkdirSync(resolve(cwd, 'src/assets'), { recursive: true });
  const catalog = Array.from({ length: 305 }, (_, index) => ({
    content_key: index === 0 ? 'MSF-WD-Q9999999' : `CACHE-FILM-${index}`,
    title: `Cache film ${index}`,
    release_date: '1920-01-01',
    genre: 'Drama',
    artwork_available: index === 0,
    image_url: index === 0
      ? 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Cache_fixture.png'
      : '/catalog-unavailable.svg',
    artwork_license: 'CC0',
    artwork_source_url: 'https://commons.wikimedia.org/wiki/File:Cache_fixture.png',
    attribution: 'Fixture author',
  }));
  // Reuse a real, decoded production image rather than testing magic bytes alone.
  const current = JSON.parse(readFileSync(resolve(app, 'public/artwork-manifest.json'), 'utf8'));
  const source = current.items.find((item: { kind: string }) => item.kind === 'licensed-reference');
  const bytes = readFileSync(resolve(app, 'public', source.imagepath.slice(1)));
  const keyHash = sha256(catalog[0].content_key).slice(0, 20);
  const extension = source.imagepath.split('.').at(-1);
  const cached = {
    content_key: catalog[0].content_key,
    title: catalog[0].title,
    imagepath: `/artwork/${keyHash}-licensed.${extension}`,
    fallback_path: `/artwork/${keyHash}-editorial.svg`,
    kind: 'licensed-reference',
    license: 'CC0',
    attribution: 'Fixture author',
    alt: 'Licensed reference image associated with Cache film 0',
    source_url: catalog[0].artwork_source_url,
    canonical_artwork_available: true,
    asset_sha256: sha256(bytes),
  };
  writeFileSync(resolve(cwd, 'catalog.json'), JSON.stringify(catalog));
  writeFileSync(resolve(cwd, 'public', cached.imagepath.slice(1)), bytes);
  writeFileSync(resolve(cwd, 'public/artwork-manifest.json'), JSON.stringify({
    schema_version: 1, items: [cached],
  }));
  writeFileSync(resolve(cwd, 'throttled.mjs'),
    "globalThis.fetch = async () => { throw new Error('HTTP 429 simulated transient throttle'); };\n");
  return { cwd, cached, bytes };
}

afterEach(() => {
  for (const path of temporaryDirectories.splice(0)) rmSync(path, { recursive: true, force: true });
});

describe('licensed artwork cache preservation', () => {
  for (const download of [false, true]) {
    it(`preserves verified bytes, hash, path and credits ${download ? 'during a transient source failure' : 'without network refresh'}`, () => {
      const { cwd, cached, bytes } = cachedFixture();
      const result = spawnSync(process.execPath, [
        '--import', pathToFileURL(resolve(cwd, 'throttled.mjs')).href, script, '--catalog', 'catalog.json',
        ...(download ? ['--download-licensed'] : []),
      ], { cwd, encoding: 'utf8', timeout: 15_000 });
      expect(result.status, result.stderr).toBe(0);
      const manifest = JSON.parse(readFileSync(resolve(cwd, 'public/artwork-manifest.json'), 'utf8'));
      expect(manifest.items.find((item: { content_key: string }) => item.content_key === cached.content_key))
        .toMatchObject(cached);
      expect(readFileSync(resolve(cwd, 'public', cached.imagepath.slice(1)))).toEqual(bytes);
    });
  }

  it('keeps a good prior source when a reviewed replacement fails transiently', () => {
    const { cwd, cached, bytes } = cachedFixture();
    const candidate = {
      commons_title: 'File:Replacement.jpg',
      source_url: 'https://commons.wikimedia.org/wiki/File:Replacement.jpg',
      image_url: 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Replacement.jpg',
      license: 'CC0', license_url: 'https://creativecommons.org/publicdomain/zero/1.0/',
      author: 'Replacement artist', modifications: 'None',
    };
    writeFileSync(resolve(cwd, 'public/artwork/source-review.json'), JSON.stringify({
      known: {}, selections: { [cached.content_key]: {
        commons_title: candidate.commons_title, media_kind: 'film-poster',
        association_note: 'Exact fixture film and year.',
      } },
    }));
    writeFileSync(resolve(cwd, 'public/artwork/recovery-candidates.json'), JSON.stringify({
      films: [{
        content_key: cached.content_key, title: cached.title, year: '1920',
        wikidata: { qid: 'Q9999999', source_url: 'https://www.wikidata.org/wiki/Q9999999' },
        candidates: [candidate],
      }],
    }));
    const result = spawnSync(process.execPath, [
      '--import', pathToFileURL(resolve(cwd, 'throttled.mjs')).href,
      script, '--catalog', 'catalog.json', '--download-licensed',
    ], { cwd, encoding: 'utf8', timeout: 20_000 });
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(result.stdout).failed_licensed_cache).toHaveLength(1);
    const manifest = JSON.parse(readFileSync(resolve(cwd, 'public/artwork-manifest.json'), 'utf8'));
    expect(manifest.items[0]).toMatchObject(cached);
    expect(readFileSync(resolve(cwd, 'public', cached.imagepath.slice(1)))).toEqual(bytes);
  }, 25_000);

  it('archives a rejected portrait without presenting it as a film still or losing its bytes', () => {
    const { cwd, cached, bytes } = cachedFixture();
    writeFileSync(resolve(cwd, 'public/artwork/known-sources.json'), JSON.stringify({
      items: [{ content_key: cached.content_key, source_url: cached.source_url }],
    }));
    writeFileSync(resolve(cwd, 'public/artwork/source-review.json'), JSON.stringify({
      known: { [cached.content_key]: {
        eligible: false, media_kind: 'author-portrait',
        association_note: 'An author portrait is not a film still.',
      } }, selections: {},
    }));
    const result = spawnSync(process.execPath, [script, '--catalog', 'catalog.json'], {
      cwd, encoding: 'utf8', timeout: 15_000,
    });
    expect(result.status, result.stderr).toBe(0);
    const manifest = JSON.parse(readFileSync(resolve(cwd, 'public/artwork-manifest.json'), 'utf8'));
    expect(manifest.items[0].kind).toBe('original-editorial');
    expect(manifest.items[0].alt).toContain('not an official film poster');
    expect(manifest.items[0].artwork_unavailable_reason).toContain('portrait is not a film still');
    const inventory = JSON.parse(readFileSync(resolve(cwd, 'public/artwork/source-inventory.json'), 'utf8'));
    expect(inventory.items[0]).toMatchObject(cached);
    expect(readFileSync(resolve(cwd, 'public', cached.imagepath.slice(1)))).toEqual(bytes);
  });
});
