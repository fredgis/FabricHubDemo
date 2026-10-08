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
  id: '1a3a7f8e-414d-4a80-aeab-62363b8c4d42', binding_key: 'business-gold',
  name: 'MSFlixGold', sql_server: 'fixture.datawarehouse.fabric.microsoft.com',
  sql_database: '7eb1318d-e4b5-4bc4-ae12-6c3a46b1b7f5',
  item_id: '7eb1318d-e4b5-4bc4-ae12-6c3a46b1b7f5',
  workspace_id: 'd9c835a9-16d2-4997-9969-16cc4389a7c7',
  capacity_id: '6e2bdf47-e6c5-4715-99ed-6c40461f59b7', verified: true,
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
