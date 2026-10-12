/**
 * Public-source artwork recovery only. No credentials, catalog mutations, or SVG execution.
 * Wikimedia requests are sequential, paced, bounded, and honor server cooldowns.
 */
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { loadEnvironmentVariables } from '../node_modules/@microsoft/rayfin-cli/dist/utils/config-utils.js';

export function artworkUserAgent(projectUrl) {
  if (typeof projectUrl !== 'string' || !projectUrl.trim()) {
    throw new Error('Configure COCKPIT_ARTWORK_PROJECT_URL in private rayfin/.env or pass --project-url.');
  }
  const url = new URL(projectUrl);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('Artwork project URL must use HTTPS without credentials, query or fragment.');
  }
  return `MSFlixArtworkRecovery/1.1 (${url.href}; licensed film artwork cache; contact via repository issues)`;
}
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const allowedHosts = new Set([
  'studio.blender.org', 'upload.wikimedia.org', 'thumb.wikimedia.org',
  'commons.wikimedia.org', 'www.wikidata.org',
]);

export function publicSourceUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !allowedHosts.has(url.hostname) ||
      url.username || url.password || (url.port && url.port !== '443')) {
    throw new Error('Asset host is not in the verified-source allow-list.');
  }
  if (url.hostname === 'upload.wikimedia.org' && !url.pathname.startsWith('/wikipedia/commons/')) {
    throw new Error('Only Commons media, not fair-use Wikipedia uploads, are allowed.');
  }
  for (const key of [...url.searchParams.keys()]) if (key.startsWith('utm_')) url.searchParams.delete(key);
  return url;
}

export function retryAfterMilliseconds(value, now = Date.now()) {
  if (!value) return 0;
  if (/^\d+(?:\.\d+)?$/.test(value.trim())) return Math.ceil(Number(value) * 1000);
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, date - now) : 0;
}

/** Testable clock/transport; no parallel requests or credential-bearing requests. */
export function createArtworkClient({
  projectUrl = loadEnvironmentVariables({
    projectRoot: fileURLToPath(new URL('../', import.meta.url)),
  }).get('COCKPIT_ARTWORK_PROJECT_URL'),
  fetchImpl = globalThis.fetch,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  now = Date.now,
  intervalMs = 2200,
  maxAttempts = 3,
  maxRequests = 350,
  maxCooldownMs = 120_000,
} = {}) {
  const userAgent = artworkUserAgent(projectUrl);
  let nextRequestAt = 0;
  let requestCount = 0;
  let suspendedUntil = 0;
  let responseRetryAfterMs = 0;
  async function bytes(value, { limit = MAX_IMAGE_BYTES, accept = '*/*' } = {}) {
    let url = publicSourceUrl(value);
    let redirects = 0;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (suspendedUntil > now()) throw new Error(`Source cooldown until ${new Date(suspendedUntil).toISOString()}; not retried early.`);
      if (requestCount >= maxRequests) throw new Error('Bounded artwork request budget exhausted.');
      await sleep(Math.max(0, nextRequestAt - now()));
      requestCount++;
      nextRequestAt = now() + intervalMs;
      let response;
      try {
        response = await fetchImpl(url, {
          redirect: 'manual',
          signal: AbortSignal.timeout(30_000),
          headers: { 'User-Agent': userAgent, Accept: accept },
        });
      } catch (error) {
        if (attempt === maxAttempts - 1) throw error;
        nextRequestAt = Math.max(nextRequestAt, now() + 2000 * 2 ** attempt);
        continue;
      }
      responseRetryAfterMs = retryAfterMilliseconds(response.headers.get('retry-after'), now());
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        await response.body?.cancel();
        if (++redirects > 2) throw new Error('Too many artwork redirects.');
        url = publicSourceUrl(new URL(response.headers.get('location'), url).href);
        continue;
      }
      if (!response.ok) {
        await response.body?.cancel();
        const cooldown = retryAfterMilliseconds(response.headers.get('retry-after'), now());
        nextRequestAt = Math.max(nextRequestAt, now() + cooldown, now() + 3000 * 2 ** attempt);
        if (cooldown > maxCooldownMs) {
          suspendedUntil = now() + cooldown;
          throw new Error(`HTTP ${response.status}; Retry-After exceeds this bounded run (${cooldown / 1000}s).`);
        }
        if (![429, 500, 502, 503, 504].includes(response.status) || attempt === maxAttempts - 1) {
          throw new Error(`HTTP ${response.status}${cooldown ? `; Retry-After ${cooldown / 1000}s` : ''}`);
        }
        continue;
      }
      if (Number(response.headers.get('content-length')) > limit) {
        await response.body?.cancel();
        throw new Error('Image exceeds the 10 MiB asset limit.');
      }
      const chunks = [];
      let size = 0;
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > limit) throw new Error('Response exceeds the bounded byte limit.');
        chunks.push(Buffer.from(chunk));
      }
      return Buffer.concat(chunks);
    }
    throw new Error('Artwork redirect/retry budget exhausted.');
  }
  return {
    bytes,
    async json(url) {
      for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const data = JSON.parse((await bytes(url, { accept: 'application/json' })).toString('utf8'));
        if (!data.error) return data;
        if (data.error.code !== 'maxlag' || attempt === maxAttempts - 1) {
          throw new Error(`Official API ${data.error.code}: ${data.error.info}`);
        }
        const cooldown = Math.max(responseRetryAfterMs, 5000 * 2 ** attempt, Math.ceil(data.error.lag ?? 0) * 1000);
        if (cooldown > maxCooldownMs) {
          suspendedUntil = now() + cooldown;
          throw new Error('Official API maxlag cooldown exceeds this bounded run.');
        }
        nextRequestAt = Math.max(nextRequestAt, now() + cooldown);
      }
    },
    get requestCount() { return requestCount; },
  };
}

export function plainText(value = '') {
  return String(value).replace(/<[^>]*>/g, '').replace(/&quot;/g, '"')
    .replace(/&#0*39;|&apos;/g, "'").replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

/** A metadata CC0 claim is never used as a substitute for an image's license. */
export function permittedImageLicense(shortName, code = '') {
  const license = plainText(shortName);
  if (/\b(?:NC|ND)\b|non.?commercial|no.?derivative/i.test(`${license} ${code}`)) return false;
  return /^(?:CC BY(?:-SA)? \d\.\d(?: [a-z]{2,3}(?:-[a-z]+)?)?|CC0(?: 1\.0)?|Public domain|PDM(?: 1\.0)?)$/i.test(license);
}

export function normalizedFileTitle(value) {
  let decoded = value;
  try { decoded = decodeURIComponent(value); } catch { /* A literal % in a file title is valid. */ }
  return decoded.replace(/^.*\/wiki\//, '').replaceAll('_', ' ').normalize('NFC');
}

export function commonsRecord(page) {
  const info = page.imageinfo?.[0];
  if (!info) return null;
  const metadata = info.extmetadata ?? {};
  const value = key => metadata[key]?.value ?? '';
  const license = plainText(value('LicenseShortName'));
  if (!permittedImageLicense(license, value('License'))) return null;
  const sourceUrl = info.descriptionurl ?? `https://commons.wikimedia.org/wiki/${encodeURIComponent(page.title.replaceAll(' ', '_'))}`;
  // Standard 960px Commons rendering handles SVG/TIFF safely: never load source SVG in a browser.
  const originalIsRaster = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(info.mime);
  const imageUrl = originalIsRaster && info.size <= MAX_IMAGE_BYTES ? info.url : info.thumburl;
  if (!imageUrl) return null;
  return {
    commons_title: page.title,
    commons_page_id: page.pageid,
    source_url: sourceUrl,
    image_url: publicSourceUrl(imageUrl).href,
    original_url: publicSourceUrl(info.url).href,
    license,
    license_url: value('LicenseUrl') || `${sourceUrl}#Licensing`,
    license_evidence_url: `${sourceUrl}#Licensing`,
    author: plainText(value('Artist')) || 'Unknown author (as recorded on Commons)',
    image_description: plainText(value('ImageDescription')),
    credit: plainText(value('Credit')),
    categories: value('Categories').split('|').filter(Boolean),
    original_mime: info.mime,
    original_width: info.width,
    original_height: info.height,
    original_bytes: info.size,
    source_sha1: info.sha1,
    modifications: originalIsRaster && info.size <= MAX_IMAGE_BYTES
      ? 'None; original image bytes cached locally.'
      : 'Official Commons 960px raster thumbnail; source SVG is not executed.',
  };
}

export async function commonsImageInfo(titles, client) {
  const records = new Map();
  const unique = [...new Set(titles.map(normalizedFileTitle))];
  for (let offset = 0; offset < unique.length; offset += 40) {
    const url = new URL('https://commons.wikimedia.org/w/api.php');
    url.search = new URLSearchParams({
      action: 'query', format: 'json', redirects: '1', maxlag: '5',
      prop: 'imageinfo', iiprop: 'url|size|mime|sha1|extmetadata',
      iiurlwidth: '960', titles: unique.slice(offset, offset + 40).join('|'),
    }).toString();
    const data = await client.json(url.href);
    const byTitle = new Map();
    for (const page of Object.values(data.query?.pages ?? {})) {
      const record = commonsRecord(page);
      if (record) byTitle.set(normalizedFileTitle(page.title), record);
    }
    for (const title of unique.slice(offset, offset + 40)) {
      const redirected = data.query?.redirects?.find(row => normalizedFileTitle(row.from) === title)?.to;
      const record = byTitle.get(normalizedFileTitle(redirected ?? title));
      if (record) records.set(title, record);
    }
  }
  return records;
}

export function candidateHint(record) {
  const text = `${record.commons_title} ${record.image_description} ${record.categories.join(' ')}`;
  if (/\b(?:cosplay|wax figure|filming location|premiere|red carpet|press conference|autograph)\b/i.test(text)) return 'not-film-artwork';
  if (/\b(?:poster|affiche|filmplakat|locandina|plakat|cartaz)\b/i.test(text)) return 'poster-candidate';
  if (/\b(?:screenshot|screenshots|screen capture|trailer|film still|publicity still|scene from|scena|fotogramma|scène)\b/i.test(text)) return 'still-candidate';
  if (/\b(?:logo|logos|intertitle|intertitles|title screen|opening title|textlogo|Titeleinblendung)\b/i.test(text)) return 'title-graphic';
  return 'needs-association-review';
}

async function readJsonOr(path, fallback) {
  try { return JSON.parse(await readFile(path, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return fallback; throw error; }
}

/** Atomic checkpointing makes a bounded discovery resumable without repeating API calls. */
async function checkpoint(path, value) {
  await writeFile(`${path}.tmp`, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(`${path}.tmp`, path);
}

async function discoverFilmSources(values) {
  const catalog = await readJsonOr(values.catalog, []);
  if (catalog.length !== 305 || new Set(catalog.map(film => film.content_key)).size !== 305) {
    throw new Error('Expected the 305 unchanged canonical film keys.');
  }
  const maxFilms = Number(values['max-films']);
  const maxRequests = Number(values['max-requests']);
  if (!Number.isInteger(maxFilms) || maxFilms < 1 || maxFilms > 40 ||
      !Number.isInteger(maxRequests) || maxRequests < 1 || maxRequests > 120) {
    throw new Error('Discovery must be bounded: 1–40 films and 1–120 public requests.');
  }
  await mkdir('public/artwork', { recursive: true });
  const path = 'public/artwork/recovery-candidates.json';
  const evidence = await readJsonOr(path, {
    schema_version: 1,
    notice: 'Discovery candidates are NOT approved artwork. License and exact film association require review.',
    films: [],
  });
  const byKey = new Map(evidence.films.map(film => [film.content_key, film]));
  const client = createArtworkClient({ projectUrl: values['project-url'], maxRequests });
  const reviews = await readJsonOr('public/artwork/source-review.json', { known: {} });
  const films = catalog.filter(film => /^MSF-WD-Q\d+$/.test(film.content_key)
    && !byKey.get(film.content_key)?.discovery_complete
    && !['film-still', 'film-poster'].includes(reviews.known?.[film.content_key]?.media_kind)).slice(0, maxFilms);
  // Exact QIDs, original/localized titles, year and the QID's own Commons category.
  const missingEntities = films.filter(film => !byKey.get(film.content_key)?.wikidata);
  for (let offset = 0; offset < missingEntities.length; offset += 40) {
    const batch = missingEntities.slice(offset, offset + 40);
    const url = new URL('https://www.wikidata.org/w/api.php');
    url.search = new URLSearchParams({
      // These historical film identities tolerate ten seconds of replica lag.
      action: 'wbgetentities', format: 'json', maxlag: '10',
      ids: batch.map(film => film.content_key.slice(7)).join('|'),
      props: 'labels|claims|sitelinks', languages: 'en|fr',
      sitefilter: 'commonswiki|enwiki',
    }).toString();
    const data = await client.json(url.href);
    for (const film of batch) {
      const qid = film.content_key.slice(7);
      const entity = data.entities?.[qid];
      if (!entity || entity.missing !== undefined) continue;
      const claims = property => (entity.claims?.[property] ?? [])
        .filter(claim => claim.rank !== 'deprecated').map(claim => claim.mainsnak?.datavalue?.value).filter(Boolean);
      const entry = {
        content_key: film.content_key, title: film.title, year: String(film.release_date).slice(0, 4),
        wikidata: {
          qid, source_url: `https://www.wikidata.org/wiki/${qid}`,
          en_title: entity.labels?.en?.value, fr_title: entity.labels?.fr?.value,
          original_titles: claims('P1476').map(value => value.text),
          release_years: [...new Set(claims('P577').map(value => value.time.slice(1, 5)))],
          commons_categories: claims('P373'),
          commons_sitelink: entity.sitelinks?.commonswiki?.title,
          en_sitelink: entity.sitelinks?.enwiki?.title,
          images: claims('P18'),
        },
      };
      evidence.films.push(entry);
      byKey.set(entry.content_key, entry);
    }
    await checkpoint(path, evidence);
  }
  let searched = 0;
  for (const film of films) {
    const entry = byKey.get(film.content_key);
    if (!entry || entry.discovery_complete) continue;
    if (searched >= maxFilms || client.requestCount >= maxRequests - 2) break;
    // No metadata rewrite on a mismatch: retain an explicit unresolved case.
    if (entry.wikidata.release_years.length && !entry.wikidata.release_years.includes(entry.year)) {
      entry.discovery_complete = true;
      entry.review_note = 'Canonical year differs from current Wikidata releases; no automatic association.';
      await checkpoint(path, evidence);
      continue;
    }
    const category = entry.wikidata.commons_categories[0] ||
      (entry.wikidata.commons_sitelink?.startsWith('Category:') ? entry.wikidata.commons_sitelink.slice(9) : null);
    const title = (entry.wikidata.en_sitelink ?? entry.wikidata.en_title ?? entry.title).replace(/ \((?:\d{4} )?film\)$/, '');
    const query = `"${title.replaceAll('"', '')}" "${entry.year}" (poster OR screenshot OR trailer OR still OR logo)`;
    const url = new URL('https://commons.wikimedia.org/w/api.php');
    const common = {
      action: 'query', format: 'json', maxlag: '5',
      prop: 'imageinfo', iiprop: 'url|size|mime|sha1|extmetadata', iiurlwidth: '960',
    };
    url.search = new URLSearchParams(category ? {
      ...common, generator: 'categorymembers', gcmtitle: `Category:${category}`, gcmlimit: '50',
    } : {
      ...common, generator: 'search', gsrsearch: query, gsrnamespace: '6', gsrlimit: '15',
    }).toString();
    try {
      const data = await client.json(url.href);
      const pages = Object.values(data.query?.pages ?? {});
      const records = pages.map(commonsRecord).filter(Boolean);
      entry.association_search = category ? {
        method: 'exact-wikidata-commons-category', wikidata_qid: entry.wikidata.qid,
        category, source_url: `https://commons.wikimedia.org/wiki/Category:${encodeURIComponent(category.replaceAll(' ', '_'))}`,
      } : { method: 'exact-title-year-search', wikidata_qid: entry.wikidata.qid, query };
      entry.subcategories = pages.filter(page => page.ns === 14).map(page => page.title);
      // One bounded, film-category-specific drill-down for posters or screenshot sets.
      const relevantSubcategory = entry.subcategories.find(name => /poster|screenshot|trailer|still/i.test(name));
      if (relevantSubcategory && client.requestCount < maxRequests - 1) {
        const subUrl = new URL('https://commons.wikimedia.org/w/api.php');
        subUrl.search = new URLSearchParams({
          ...common, generator: 'categorymembers', gcmtitle: relevantSubcategory,
          gcmtype: 'file', gcmlimit: '30',
        }).toString();
        const subData = await client.json(subUrl.href);
        records.push(...Object.values(subData.query?.pages ?? {}).map(commonsRecord).filter(Boolean));
        entry.association_search.reviewed_subcategory = relevantSubcategory;
      }
      entry.candidates = [...new Map(records.map(record => [record.commons_title, {
        ...record, candidate_hint: candidateHint(record),
      }])).values()];
      entry.discovery_complete = true;
      entry.searched_at = new Date().toISOString();
      searched++;
      if (searched % 20 === 0) console.log(JSON.stringify({ searched, requests: client.requestCount }));
    } catch (error) {
      entry.discovery_error = error.message;
      await checkpoint(path, evidence);
      // A server cooldown or exhausted budget ends this run; no scraping loop.
      if (/cooldown|Retry-After|budget/i.test(error.message)) break;
      searched++;
    }
    await checkpoint(path, evidence);
  }
  console.log(JSON.stringify({
    discovery_only: true, searched_this_run: searched, requests: client.requestCount,
    exact_qids: evidence.films.length,
    films_searched: evidence.films.filter(film => film.discovery_complete).length,
    candidates: evidence.films.reduce((sum, film) => sum + (film.candidates?.length ?? 0), 0),
    evidence: path, no_images_assigned_without_review: true, no_canonical_data_modified: true,
  }));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { values } = parseArgs({ options: {
    discover: { type: 'boolean' },
    'project-url': { type: 'string' },
    catalog: { type: 'string', default: '../../data/catalog.json' },
    'max-films': { type: 'string', default: '25' },
    'max-requests': { type: 'string', default: '100' },
  } });
  if (!values.discover) throw new Error('Use --discover; this command gathers evidence but does not approve or assign images.');
  await discoverFilmSources(values);
}
