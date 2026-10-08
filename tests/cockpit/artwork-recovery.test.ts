// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import {
  ARTWORK_USER_AGENT, commonsRecord, createArtworkClient,
  permittedImageLicense, publicSourceUrl, retryAfterMilliseconds,
} from '../../apps/cockpit/tools/artwork-recovery.mjs';

describe('bounded public-source artwork recovery', () => {
  it('honors numeric and HTTP-date Retry-After values', () => {
    expect(retryAfterMilliseconds('12', 0)).toBe(12_000);
    expect(retryAfterMilliseconds('Thu, 08 Oct 2026 06:00:10 GMT',
      Date.parse('2026-10-08T06:00:00Z'))).toBe(10_000);
  });

  it('paces retries and identifies the project without credentials', async () => {
    let clock = 0;
    const requestTimes: number[] = [];
    const fetchImpl = vi.fn(async (_url, options) => {
      requestTimes.push(clock);
      expect(options.headers['User-Agent']).toBe(ARTWORK_USER_AGENT);
      expect(ARTWORK_USER_AGENT).toContain('https://example.org/artwork-recovery');
      expect(options.headers.Authorization).toBeUndefined();
      return requestTimes.length === 1
        ? new Response('throttled', { status: 429, headers: { 'Retry-After': '7' } })
        : new Response('downloaded');
    });
    const client = createArtworkClient({
      fetchImpl, now: () => clock, sleep: async (ms: number) => { clock += ms; },
    });
    expect((await client.bytes('https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg')).toString())
      .toBe('downloaded');
    expect(requestTimes[1] - requestTimes[0]).toBeGreaterThanOrEqual(7000);
    expect(client.requestCount).toBe(2);
  });

  it('stops instead of retrying before an excessive server cooldown expires', async () => {
    const fetchImpl = vi.fn(async () => new Response('throttled', {
      status: 429, headers: { 'Retry-After': '600' },
    }));
    const client = createArtworkClient({ fetchImpl, sleep: async () => {}, now: () => 0 });
    const url = 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg';
    await expect(client.bytes(url)).rejects.toThrow('Retry-After exceeds');
    await expect(client.bytes(url)).rejects.toThrow('not retried early');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('backs off on MediaWiki maxlag errors even when HTTP status is 200', async () => {
    let clock = 0;
    const times: number[] = [];
    const client = createArtworkClient({
      now: () => clock, sleep: async (ms: number) => { clock += ms; },
      fetchImpl: async () => {
        times.push(clock);
        return times.length === 1
          ? Response.json({ error: { code: 'maxlag', info: 'Replica lag', lag: 8.3 } },
            { headers: { 'Retry-After': '10' } })
          : Response.json({ query: { pages: {} } });
      },
    });
    await expect(client.json('https://commons.wikimedia.org/w/api.php')).resolves.toEqual({ query: { pages: {} } });
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(10_000);
  });

  it('rejects unlicensed, noncommercial, no-derivatives and non-Commons uploads', () => {
    for (const license of ['CC BY-NC 4.0', 'CC BY-ND 4.0', 'Fair use', 'CC0 metadata / unknown artwork']) {
      expect(permittedImageLicense(license)).toBe(false);
    }
    for (const license of ['CC BY 3.0', 'CC BY-SA 4.0', 'CC BY-SA 2.5 hu', 'CC0', 'Public domain']) {
      expect(permittedImageLicense(license)).toBe(true);
    }
    expect(() => publicSourceUrl('https://upload.wikimedia.org/wikipedia/en/a/ab/Poster.jpg')).toThrow();
    expect(() => publicSourceUrl('https://example.com/Poster.jpg')).toThrow();
  });

  it('uses the official raster rendering of licensed SVG, never the executable source', () => {
    const source = 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Poster.svg';
    const raster = 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Poster.svg/960px-Poster.svg.png';
    const record = commonsRecord({
      title: 'File:Poster.svg', pageid: 1,
      imageinfo: [{
        mime: 'image/svg+xml', size: 4000, width: 600, height: 900,
        url: source, thumburl: raster,
        descriptionurl: 'https://commons.wikimedia.org/wiki/File:Poster.svg',
        extmetadata: {
          LicenseShortName: { value: 'CC BY-SA 4.0' },
          LicenseUrl: { value: 'https://creativecommons.org/licenses/by-sa/4.0/' },
          Artist: { value: 'Poster artist' },
        },
      }],
    });
    expect(record?.image_url).toBe(raster);
    expect(record?.original_url).toBe(source);
    expect(record?.modifications).toContain('source SVG is not executed');
  });
});
