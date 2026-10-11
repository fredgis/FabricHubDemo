// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AnalyticsBinding } from '../../apps/cockpit/rayfin/data/schema';

const calls = vi.hoisted(() => ({ query: vi.fn(), input: vi.fn(), read: vi.fn() }));
vi.mock('../../apps/cockpit/rayfin/functions/src/gold-connection', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/rayfin/functions/src/gold-connection')>(),
  withGoldPool: async (binding: AnalyticsBinding, token: string, read: (pool: unknown) => Promise<unknown>) => {
    calls.read(binding, token);
    const request = {
      input: (...args: unknown[]) => { calls.input(...args); return request; },
      query: calls.query,
    };
    return read({ request: () => request });
  },
}));
import { catalogDashboardFromRows, dashboardFromRows, GOLD_DASHBOARD_QUERY, GOLD_PUBLICATION_QUERY } from '../../apps/cockpit/rayfin/functions/src/gold-dashboard';
import { readGoldPages } from '../../apps/cockpit/rayfin/functions/src/gold-pages';

const binding: AnalyticsBinding = {
  id: 'binding', binding_key: 'business-gold', name: 'MSFlixGold', verified: true,
  sql_server: 'fixture.datawarehouse.fabric.microsoft.com',
  sql_database: '55555555-5555-4555-8555-555555555555', item_id: '55555555-5555-4555-8555-555555555555',
  workspace_id: '33333333-3333-4333-8333-333333333333', capacity_id: '22222222-2222-4222-8222-222222222222',
};
const source = { name: binding.name, workspace_id: binding.workspace_id, item_id: binding.item_id };
const publication = [{ run_id: 'published', completed_at: '2026-10-08T06:09:28Z', order_lines: '9007199254740993' }];
const catalog = [{ content_key: 'film', title: 'Film', genre: 'Drama', duration_seconds: '600' }];
const offers = [{ offer_key: 'film:EST', content_key: 'film', currency: 'EUR', price_minor: '1299',
  transaction_type: 'EST', start_window_hours: null, play_window_hours: null }];
const details = [catalog, [], offers, [], [], []];
const fullDashboard = [
  [{ currency: 'EUR', transaction_type: 'EST', current_order_lines: '12', booked_amount_minor: '15588', booked_amount_decimal: '155.8800' }],
  [{ content_key: 'film', status: 'STARTED', current_sessions: '7', furthest_position_seconds: '400' }],
  [{ campaign_key: 'campaign', recorded_conversions: '2' }], [{ customers: '9', content: '1' }], publication,
];

beforeEach(() => {
  vi.clearAllMocks();
  calls.query.mockImplementation(async (query: string) => ({ recordsets: query.startsWith(GOLD_DASHBOARD_QUERY)
    ? [...fullDashboard, ...details] : [publication, ...details] }));
});

describe('Catalog publication-only Gold read', () => {
  it('omits all four dashboard aggregates while retaining one typed batch and unchanged reference statements', async () => {
    const result = await readGoldPages(binding, 'test-token', 'catalog');
    const query = calls.query.mock.calls[0][0] as string;
    expect(query.startsWith(GOLD_PUBLICATION_QUERY)).toBe(true);
    expect(query).not.toMatch(/gold\.(commercial_activity|playback_activity|campaign_activity)|COUNT_BIG/);
    expect(calls.query).toHaveBeenCalledTimes(1);
    expect(calls.read).toHaveBeenCalledExactlyOnceWith(binding, 'test-token');
    expect(calls.input.mock.calls.map(([name, , value]) => [name, value])).toEqual([
      ['references', 10001], ['activity', 1000], ['view', 'catalog'],
    ]);
    expect(result.catalog).toEqual(catalog);
    expect(result.offers).toEqual(offers);
    expect([result.customers, result.orders, result.sessions, result.campaigns]).toEqual([[], [], [], []]);
    await readGoldPages(binding, 'test-token', 'overview');
    const overview = calls.query.mock.calls[1][0] as string;
    expect(query.slice(GOLD_PUBLICATION_QUERY.length)).toBe(overview.slice(GOLD_DASHBOARD_QUERY.length));
  });

  it('marks unrequested metrics null instead of reporting zero or empty measured activity', async () => {
    const result = await readGoldPages(binding, 'test-token', 'catalog');
    expect(result.dashboard).toEqual({ source: { ...source, views: ['gold.publication'] }, scope: 'catalog', state: 'ready',
      freshness: { queried_at: expect.any(String), published_at: '2026-10-08T06:09:28.000Z',
        publication_run_id: 'published', order_lines: '9007199254740993' },
      commercial: null, playback: null, campaigns: null, dimensions: null });
    expect(Number.isFinite(Date.parse(result.dashboard.freshness.queried_at))).toBe(true);
    expect(result.window).toEqual({ orders: 1000, sessions: 1000, references: 10000 });
  });

  it('uses exactly the full-dashboard publication freshness and integer validation', () => {
    const now = new Date('2026-10-09T01:02:03Z');
    const metadata = catalogDashboardFromRows(source, publication, now);
    const full = dashboardFromRows(source, { commercial: [], playback: [], campaigns: [], counts: [], publication }, now);
    expect(metadata.freshness).toEqual(full.freshness);
    expect(full.state).toBe('empty');
    expect(metadata.state).toBe('ready');
    expect(metadata.dimensions).toBeNull();
  });

  it('keeps references gated when there is no publication', async () => {
    calls.query.mockResolvedValueOnce({ recordsets: [[], ...details] });
    const result = await readGoldPages(binding, 'test-token', 'catalog');
    expect(result.dashboard.state).toBe('unpublished');
    expect(result.dashboard.freshness).toMatchObject({ published_at: null, publication_run_id: null, order_lines: null });
    expect([result.catalog, result.offers, result.customers, result.orders, result.sessions, result.campaigns]).toEqual([[], [], [], [], [], []]);
    expect(result.dashboard.commercial).toBeNull();
  });

  it.each(['all', 'overview', 'audiences', 'demo'] as const)('keeps the full %s dashboard and original five-resultset offset', async view => {
    const result = await readGoldPages(binding, 'test-token', view);
    expect((calls.query.mock.calls[0][0] as string).startsWith(GOLD_DASHBOARD_QUERY)).toBe(true);
    expect(result.dashboard).not.toHaveProperty('scope');
    expect(result.dashboard.state).toBe('ready');
    expect(result.dashboard.commercial).toEqual(fullDashboard[0]);
    expect(result.dashboard.playback).toEqual(fullDashboard[1]);
    expect(result.dashboard.campaigns).toEqual(fullDashboard[2]);
    expect(result.dashboard.dimensions).toEqual({ customers: '9', content: '1' });
    expect(result.catalog).toEqual(catalog);
    expect(result.offers).toEqual(offers);
  });

  it.each([0, 1, 2, 5])('keeps the 10,000-row fail-closed reference boundary for resultset %i', async index => {
    const oversized = [...details];
    oversized[index] = Array.from({ length: 10001 }, () => ({ content_key: 'film', title: 'Film', genre: 'Drama', duration_seconds: '600' }));
    calls.query.mockResolvedValueOnce({ recordsets: [publication, ...oversized] });
    await expect(readGoldPages(binding, 'test-token', 'catalog')).rejects.toThrow('No operational fallback');
  });

  it('rejects invalid publication metadata rather than displaying freshness for malformed data', async () => {
    for (const changes of [{ completed_at: 'invalid' }, { order_lines: '-1' }, { order_lines: '1.5' }]) {
      calls.query.mockResolvedValueOnce({ recordsets: [[{ ...publication[0], ...changes }], ...details] });
      await expect(readGoldPages(binding, 'test-token', 'catalog')).rejects.toThrow('No operational fallback');
    }
  });

  it('validates the Gold binding before opening a pooled read', async () => {
    await expect(readGoldPages({ ...binding, verified: false }, 'test-token', 'catalog')).rejects.toThrow('not verified');
    expect(calls.read).not.toHaveBeenCalled();
    expect(calls.query).not.toHaveBeenCalled();
  });
});
