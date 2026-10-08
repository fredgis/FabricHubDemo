import { beforeEach, expect, it, vi } from 'vitest';
import type { AnalyticsBinding } from '../../apps/cockpit/rayfin/data/schema';

const calls = vi.hoisted(() => ({ connections: 0, queries: [] as string[] }));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => ({
  default: {
    Int: 'Int',
    VarChar: () => 'VarChar',
    ConnectionPool: class {
      async connect() { calls.connections++; return this; }
      async close() {}
      request() {
        const request = {
          input: () => request,
          query: async (query: string) => {
            calls.queries.push(query);
            const dashboard = [[], [], [], [{ customers: '700', content: '305' }],
              [{ run_id: 'published', completed_at: '2026-10-08T06:09:28Z', order_lines: '1003' }]];
            const pages = [[], [], [], [], [], []];
            return { recordsets: query.includes('gold.commercial_activity')
              ? query.includes('FROM gold.fact_order_line') ? [...dashboard, ...pages] : dashboard : pages };
          },
        };
        return request;
      }
    },
  },
}));
import { goldView, readGoldPages } from '../../apps/cockpit/rayfin/functions/src/gold-pages';

const binding: AnalyticsBinding = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', binding_key: 'business-gold',
  name: 'MSFlixGold', sql_server: 'fixture.datawarehouse.fabric.microsoft.com',
  sql_database: '55555555-5555-4555-8555-555555555555',
  item_id: '55555555-5555-4555-8555-555555555555',
  workspace_id: '33333333-3333-4333-8333-333333333333',
  capacity_id: '22222222-2222-4222-8222-222222222222', verified: true,
};

beforeEach(() => { calls.connections = 0; calls.queries = []; });
it('reads Gold metrics and page details in one SQL connection and one batch', async () => {
  const result = await readGoldPages(binding, 'test-token');
  expect(result.dashboard.freshness.order_lines).toBe('1003');
  expect(calls.connections).toBe(1);
  expect(calls.queries).toHaveLength(1);
});
it('bounds the initial home activity to six records without changing the full read contract', async () => {
  const result = await readGoldPages(binding, 'test-token', 'overview');
  expect(result.window.orders).toBe(6);
  expect(result.window.sessions).toBe(6);
  expect(result.dashboard.freshness.order_lines).toBe('1003');
  expect(() => goldView('unbounded')).toThrow();
});
